# -*- coding: utf-8 -*-
"""Section views in Revit for the chosen section lines.

Height  from the slab of the level to the slab above, included:
        bottom = level - below_level_mm;
        top    = top of the slab above at the section (highest top face of the floors of the
                 linked models over three points of the line) + above_slab_mm.
Width   the line's extent (concrete to concrete, see placement).
Depth   far clip just before the first MEP element in front of the cut that the cut does not
        go through (turned piece, riser, fitting, sprinkler...), depth_min_mm..depth_max_mm.
View    type view_type, template view_template, scale, name name_format ("00-01"),
        numbered right to left, top to bottom on the plan (Hebrew reading order).
"""
import re

from Autodesk.Revit import DB

from coordination.units import mm_to_ft
from coordination.sections import floor
from coordination.sections.floor import dot

NAME = DB.Element.Name.GetValue


def section_type(doc, name):
    types = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
             if t.ViewFamily == DB.ViewFamily.Section]
    for t in types:
        if NAME(t) == name:
            return t
    return types[0] if types else None


def view_template(doc, name):
    if not name:
        return None
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if view.IsTemplate and view.Name == name:
            return view
    return None


class SlabFinder(object):
    """Top of the slab above: top faces of the floors of the linked models (and of this model)
    whose top is within [z1 - 1.5 m, z1 + 1.2 m]."""

    def __init__(self, doc, z1):
        self.floors = []
        lo, hi = z1 - mm_to_ft(1500), z1 + mm_to_ft(1200)
        sources = [(doc, DB.Transform.Identity)]
        for link in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
            if link.GetLinkDocument() is not None:
                sources.append((link.GetLinkDocument(), link.GetTotalTransform()))
        for source, transform in sources:
            collector = (DB.FilteredElementCollector(source)
                         .OfCategory(DB.BuiltInCategory.OST_Floors).WhereElementIsNotElementType())
            for floor in collector:
                if not isinstance(floor, DB.Floor):
                    continue
                bbox = floor.get_BoundingBox(None)
                if bbox is None:
                    continue
                top = transform.OfPoint(bbox.Max).Z
                if not (lo <= top <= hi):
                    continue
                corners = [transform.OfPoint(DB.XYZ(x, y, bbox.Max.Z))
                           for x in (bbox.Min.X, bbox.Max.X) for y in (bbox.Min.Y, bbox.Max.Y)]
                xs = [c.X for c in corners]
                ys = [c.Y for c in corners]
                self.floors.append((floor, transform, (min(xs), min(ys), max(xs), max(ys)), None))
        self.z1 = z1

    def _faces(self, i):
        floor, transform, rect, faces = self.floors[i]
        if faces is None:
            faces = []
            try:
                for ref in DB.HostObjectUtils.GetTopFaces(floor):
                    face = floor.GetGeometryObjectFromReference(ref)
                    if isinstance(face, DB.Face):
                        faces.append(face)
            except Exception:
                faces = []
            self.floors[i] = (floor, transform, rect, faces)
        return faces

    def top(self, x, y, z0, z1):
        """Highest top face of a floor above (x, y), or None."""
        best = None
        for i in range(len(self.floors)):
            floor, transform, rect, _ = self.floors[i]
            if not (rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]):
                continue
            local = transform.Inverse.OfPoint(DB.XYZ(x, y, z1))
            for face in self._faces(i):
                hit = face.Project(local)
                if hit is None:
                    continue
                point = transform.OfPoint(hit.XYZPoint)
                if abs(point.X - x) > 1e-3 or abs(point.Y - y) > 1e-3:
                    continue   # projected onto an edge: not above this point
                if best is None or point.Z > best:
                    best = point.Z
        return best


def section_height(line, finder, z0, z1, cfg):
    bottom = z0 - mm_to_ft(cfg["below_level_mm"])
    tops = []
    span = line.t_max - line.t_min
    for f in (0.15, 0.5, 0.85):
        x, y = line.point(line.t_min + span * f)
        z = finder.top(x, y, z0, z1)
        if z is not None:
            tops.append(z)
    slab_found = bool(tops)
    top = max(tops) if tops else z1 + mm_to_ft(300)
    return bottom, top + mm_to_ft(cfg["above_slab_mm"]), slab_found


def section_depth(line, items, bottom, top, cfg):
    """Far clip: just before the first MEP element in front of the cut that the cut does
    not go through (a turned piece, riser, fitting, sprinkler...). Elements the cut goes
    through are in the section anyway. Returns (depth, id of the element that limits it)."""
    o = line.origin
    best = mm_to_ft(cfg["depth_max_mm"])
    limiting = None
    for item in items:
        if item.zmax < bottom or item.zmin > top:
            continue
        rel = [(p[0] - o[0], p[1] - o[1]) for p in item.points]
        ahead = [dot(p, line.look) for p in rel]
        near = min(ahead) - item.radius
        if near <= 0.0 or near >= best:
            continue   # cut by the plane, behind it, or farther than what we have
        ts = [dot(p, line.along) for p in rel]
        if max(ts) + item.radius < line.t_min or min(ts) - item.radius > line.t_max:
            continue
        best = near
        limiting = item.id
    depth = best - mm_to_ft(20)
    depth = max(mm_to_ft(cfg["depth_min_mm"]), min(mm_to_ft(cfg["depth_max_mm"]), depth))
    return depth, limiting


def create_section(doc, vtype, line, bottom, top, depth):
    """Section looking line.look, cut plane through line.origin, far clip `depth` beyond it.

    ViewSection.CreateSection reads the box differently from the stored crop box:
    the view looks along the box's BasisZ, the cut plane is at Min.Z and the far clip
    at Max.Z (checked in Revit 2025). Revit then stores it turned by 180 degrees
    (BasisZ towards the viewer, cut plane at Max.Z = 0). So BasisZ = look and
    BasisX = -along, which makes the stored right direction = along.
    """
    transform = DB.Transform.Identity
    transform.Origin = DB.XYZ(line.origin[0], line.origin[1], bottom)
    transform.BasisX = DB.XYZ(-line.along[0], -line.along[1], 0)
    transform.BasisY = DB.XYZ.BasisZ
    transform.BasisZ = DB.XYZ(line.look[0], line.look[1], 0)
    box = DB.BoundingBoxXYZ()
    box.Transform = transform
    box.Min = DB.XYZ(-line.t_max, 0.0, 0.0)
    box.Max = DB.XYZ(-line.t_min, top - bottom, depth)
    return DB.ViewSection.CreateSection(doc, vtype.Id, box)


def order_lines(lines, plan_up, plan_right, row_mm=10000):
    """Right to left, top to bottom on the plan, in rows of row_mm."""
    row = mm_to_ft(row_mm)

    def key(line):
        mid = line.point((line.t_min + line.t_max) / 2.0)
        return (-int(dot(mid, plan_up) // row), -dot(mid, plan_right))
    return sorted(lines, key=key)


def level_sections(doc, level_name):
    """Existing section views named '<level>-NN': {number: view}."""
    pattern = re.compile(u"^" + re.escape(level_name) + u"-(\\d+)$")
    result = {}
    for view in DB.FilteredElementCollector(doc).OfClass(DB.ViewSection):
        if view.IsTemplate or view.ViewType != DB.ViewType.Section:
            continue
        match = pattern.match(view.Name)
        if match:
            result[int(match.group(1))] = view
    return result


def view_line(view):
    """(origin, look, t_min, t_max) of an existing section view in plan."""
    box = view.CropBox
    tr = box.Transform
    look = tr.BasisZ.Negate()
    along = tr.BasisX
    origin = tr.Origin
    # our convention: along = (look.y, -look.x); flip the extent if the view uses the other one
    sign = 1.0 if (along.X * look.Y - along.Y * look.X) >= 0 else -1.0
    t_a, t_b = box.Min.X * sign, box.Max.X * sign
    return (origin.X, origin.Y), (look.X, look.Y), min(t_a, t_b), max(t_a, t_b)


def make_views(doc, level, chosen, floor_data, settings, plan_up, plan_right, start_number):
    """Create the views (inside an open transaction). Returns rows for the report."""
    cfg = settings["sections"]
    vtype = section_type(doc, cfg["view_type"])
    template = view_template(doc, cfg.get("view_template"))
    z0, z1 = floor_data["z0"], floor_data["z1"]
    finder = SlabFinder(doc, z1)
    items = floor.collect_depth_items(doc, level, settings)
    taken = set(v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.View))
    rows = []
    number = start_number
    for line in order_lines(chosen, plan_up, plan_right):
        bottom, top, slab_found = section_height(line, finder, z0, z1, cfg)
        depth, limiting = section_depth(line, items, bottom, top, cfg)
        view = create_section(doc, vtype, line, bottom, top, depth)
        name = cfg["name_format"].format(level=level.Name, num=number)
        while name in taken:
            number += 1
            name = cfg["name_format"].format(level=level.Name, num=number)
        view.Name = name
        taken.add(name)
        number += 1
        if template is not None:
            view.ViewTemplateId = template.Id
        try:
            view.Scale = int(cfg.get("scale", 25))
        except Exception:
            pass   # the template controls the scale
        rows.append({"view": view, "line": line, "depth": depth, "bottom": bottom, "top": top,
                     "slab_found": slab_found, "depth_limited_by": limiting})
    return rows
