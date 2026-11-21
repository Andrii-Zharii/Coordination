# -*- coding: utf-8 -*-
"""Vertical concrete of one floor from the linked models, as footprints in plan.

A section should run from vertical structure to vertical structure (vision 4):
concrete walls, concrete columns and massive concrete beams under the slab above.
Block walls do not count.

  walls    type name has a concrete keyword ("(Cn", "Concrete"), no block keyword ("(Bb"),
           width >= wall_min_width_mm; must stand at level + 1.5 m
  columns  structural columns standing at level + 1.5 m, not steel profiles
  beams    structural framing hanging under the slab above, section depth >= beam_min_depth_mm

Each footprint is a convex polygon in host coordinates (feet).
"""
import math
import re

from Autodesk.Revit import DB

from coordination.units import mm_to_ft

NAME = DB.Element.Name.GetValue


class Obstacle(object):
    def __init__(self, polygon, kind, name):
        self.polygon = polygon
        self.kind = kind
        self.name = name
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        self.center = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
        self.radius = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / 2.0


def _rectangle(a, b, width):
    """Footprint of a straight element from a to b (plan points) with the given width."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return None
    nx, ny = -dy / length * width / 2.0, dx / length * width / 2.0
    return [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
            (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)]


def _has(text, keywords):
    lowered = text.lower()
    return any(k.lower() in lowered for k in keywords)


def _bbox_z(element, transform):
    bbox = element.get_BoundingBox(None)
    if bbox is None:
        return None
    return transform.OfPoint(bbox.Min).Z, transform.OfPoint(bbox.Max).Z, bbox


def _wall_centre_offset(wall):
    """Offset from the wall's location line to its centre, along wall.Orientation (feet)."""
    param = wall.get_Parameter(DB.BuiltInParameter.WALL_KEY_REF_PARAM)
    ref = param.AsInteger() if param is not None else 0
    half = wall.Width / 2.0
    if ref in (2, 4):   # finish / core face exterior
        return -half
    if ref in (3, 5):   # finish / core face interior
        return half
    return 0.0


def _walls(link_doc, transform, z_test, cfg, out):
    min_width = mm_to_ft(cfg["wall_min_width_mm"])
    collector = (DB.FilteredElementCollector(link_doc)
                 .OfCategory(DB.BuiltInCategory.OST_Walls).WhereElementIsNotElementType())
    for wall in collector:
        if not isinstance(wall, DB.Wall) or wall.Width < min_width:
            continue
        name = NAME(wall.WallType)
        if not _has(name, cfg["wall_keywords"]) or _has(name, cfg["wall_exclude_keywords"]):
            continue
        z = _bbox_z(wall, transform)
        if z is None or not (z[0] <= z_test <= z[1]):
            continue
        location = wall.Location
        if not isinstance(location, DB.LocationCurve):
            continue
        shift = wall.Orientation * _wall_centre_offset(wall)
        points = [transform.OfPoint(p + shift) for p in location.Curve.Tessellate()]
        for a, b in zip(points[:-1], points[1:]):
            polygon = _rectangle((a.X, a.Y), (b.X, b.Y), wall.Width)
            if polygon:
                out.append(Obstacle(polygon, "wall", name))


def _bbox_footprint(bbox, transform):
    corners = []
    for x in (bbox.Min.X, bbox.Max.X):
        for y in (bbox.Min.Y, bbox.Max.Y):
            p = transform.OfPoint(DB.XYZ(x, y, bbox.Min.Z))
            corners.append((p.X, p.Y))
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]


def _columns(link_doc, transform, z_test, cfg, out):
    collector = (DB.FilteredElementCollector(link_doc)
                 .OfCategory(DB.BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType())
    for column in collector:
        name = NAME(column)
        if _has(name, cfg["steel_keywords"]):
            continue
        z = _bbox_z(column, transform)
        if z is None or not (z[0] <= z_test <= z[1]):
            continue
        out.append(Obstacle(_bbox_footprint(z[2], transform), "column", name))


def _beam_width(beam, name):
    match = re.search(r"(\d+)\s*/\s*(\d+)", name)
    if match:
        return int(match.group(1)) * 10.0 / 304.8   # "35/90" = b/h in cm
    symbol = getattr(beam, "Symbol", None)
    for owner in (beam, symbol):
        if owner is None:
            continue
        for pname in ("b", "Width", "B"):
            param = owner.LookupParameter(pname)
            if param is not None and param.HasValue and param.StorageType == DB.StorageType.Double:
                return param.AsDouble()
    return mm_to_ft(300)


def _beams(link_doc, transform, z0, z1, cfg, out):
    min_depth = mm_to_ft(cfg["beam_min_depth_mm"])
    collector = (DB.FilteredElementCollector(link_doc)
                 .OfCategory(DB.BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType())
    for beam in collector:
        name = NAME(beam)
        if _has(name, cfg["steel_keywords"]):
            continue
        z = _bbox_z(beam, transform)
        if z is None:
            continue
        bottom, top = z[0], z[1]
        if top - bottom < min_depth:
            continue
        # hangs under the slab above: bottom inside the floor, top near the next level
        if not (z0 + mm_to_ft(300) <= bottom <= z1 + mm_to_ft(300)) or top < z1 - mm_to_ft(500):
            continue
        location = beam.Location
        if not isinstance(location, DB.LocationCurve):
            continue
        a = transform.OfPoint(location.Curve.GetEndPoint(0))
        b = transform.OfPoint(location.Curve.GetEndPoint(1))
        polygon = _rectangle((a.X, a.Y), (b.X, b.Y), _beam_width(beam, name))
        if polygon:
            out.append(Obstacle(polygon, "beam", name))


class WallPiece(Obstacle):
    """A straight piece of any wall (concrete, block, gypsum, curtain...)."""

    def __init__(self, a, b, width, name):
        Obstacle.__init__(self, _rectangle(a, b, width), "wall", name)
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        self.a = a
        self.b = b
        self.u = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
        self.width = width
        self.mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def collect_all_walls(doc, z0, z1):
    """Every wall of the floor, of any type, from this model and the loaded links:
    a section line must never run inside a wall or along its face."""
    lo, hi = z0 + mm_to_ft(300), z1 - mm_to_ft(300)
    sources = [(doc, DB.Transform.Identity)]
    for link in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        if link.GetLinkDocument() is not None:
            sources.append((link.GetLinkDocument(), link.GetTotalTransform()))
    out = []
    for source, transform in sources:
        collector = (DB.FilteredElementCollector(source)
                     .OfCategory(DB.BuiltInCategory.OST_Walls).WhereElementIsNotElementType())
        for wall in collector:
            if not isinstance(wall, DB.Wall):
                continue
            z = _bbox_z(wall, transform)
            if z is None or z[1] < lo or z[0] > hi:
                continue
            location = wall.Location
            if not isinstance(location, DB.LocationCurve):
                continue
            try:
                width = wall.Width
            except Exception:
                width = 0.0
            width = max(width, mm_to_ft(10))
            shift = wall.Orientation * _wall_centre_offset(wall) if width > mm_to_ft(10) else DB.XYZ.Zero
            points = [transform.OfPoint(p + shift) for p in location.Curve.Tessellate()]
            for a, b in zip(points[:-1], points[1:]):
                if math.hypot(b.X - a.X, b.Y - a.Y) < mm_to_ft(50):
                    continue
                out.append(WallPiece((a.X, a.Y), (b.X, b.Y), width, NAME(wall.WallType)))
    return out


def collect(doc, z0, z1, settings):
    """Concrete footprints of the floor between levels z0 and z1 from all loaded links."""
    cfg = settings["sections"]["concrete"]
    z_test = z0 + mm_to_ft(1500)
    out = []
    for link in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        link_doc = link.GetLinkDocument()
        if link_doc is None:
            continue
        transform = link.GetTotalTransform()
        _walls(link_doc, transform, z_test, cfg, out)
        _columns(link_doc, transform, z_test, cfg, out)
        _beams(link_doc, transform, z0, z1, cfg, out)
    return out


def line_interval(origin, direction, polygon):
    """(t_min, t_max) where the line origin + t * direction crosses a convex polygon, or None."""
    ts = []
    n = len(polygon)
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        den = direction[0] * ey - direction[1] * ex
        if abs(den) < 1e-12:
            continue
        wx, wy = ax - origin[0], ay - origin[1]
        t = (wx * ey - wy * ex) / den
        s = (wx * direction[1] - wy * direction[0]) / den
        if -1e-9 <= s <= 1 + 1e-9:
            ts.append(t)
    if len(ts) < 2:
        return None
    return min(ts), max(ts)
