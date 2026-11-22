# -*- coding: utf-8 -*-
"""Annotation of a section view: dimensions and tags (team rules 2026-11-22).

What is annotated: only what the section CUTS (pipes, ducts, cable trays, conduits whose
axis passes through the cut plane inside the crop). What is seen beyond is not.

Dimensions (type annotation.dimension_type):
  1. Floor to ceiling, vertical: level of the floor -> (bottom of a concrete beam cut by
     the section, if any) -> underside of the concrete slab above (linked models).
  2. Pipes, horizontal: one chain from the extreme concrete on the left through the centres
     of all cut round objects (pipes, round ducts, conduits) to the extreme concrete on the
     right. A block wall is used only when it is the outermost wall and there is no
     concrete on that side.
  3. Rectangular objects (cable trays, rectangular ducts), horizontal: one chain from the
     concrete through the left and right edges of each object (shows their widths).
  4. Rectangular objects, vertical: floor -> bottom and top of each object -> ceiling;
     objects at the same height are dimensioned once.
  5. Pipes, vertical: floor -> centres -> ceiling, one chain per group of pipes along the
     section (gap > annotation.pipe_group_gap_mm), at most annotation.max_pipe_chains.

Reference helpers drawn with detail lines (annotation.line_style):
  - a cross at the centre of a round object cut obliquely (a sloped pipe): each arm is
    annotation.cross_factor x the diameter; dimensions use the cross.
  - an outline around each rectangular object (cable trays give no references in a section).

Tags: one per cut object (tag types by category from annotation), free leader end at the
centre of the object, text straight below it (vertical leader). Placing them nicely is the
next step; for now they go annotation.tag_offset_mm under the object.
"""
import math

from Autodesk.Revit import DB

from coordination import mep
from coordination.units import mm_to_ft
from coordination.sections import views as V


def _name(element):
    try:
        return DB.Element.Name.GetValue(element)
    except Exception:
        return element.Name


class Frame(object):
    """Coordinates of a section view: t along the line (left to right), z height."""

    def __init__(self, view):
        self.view = view
        o, look, t_min, t_max = V.view_line(view)
        self.o = o
        self.look = look
        self.along = (look[1], -look[0])
        self.t_min = t_min
        self.t_max = t_max
        box = view.CropBox
        tr = box.Transform
        self.z_bottom = tr.OfPoint(DB.XYZ(0, box.Min.Y, 0)).Z
        self.z_top = tr.OfPoint(DB.XYZ(0, box.Max.Y, 0)).Z

    def point(self, t, z):
        return DB.XYZ(self.o[0] + self.along[0] * t, self.o[1] + self.along[1] * t, z)

    def t_of(self, p):
        return (p.X - self.o[0]) * self.along[0] + (p.Y - self.o[1]) * self.along[1]

    def ahead(self, p):
        return (p.X - self.o[0]) * self.look[0] + (p.Y - self.o[1]) * self.look[1]


class Cut(object):
    """An MEP element cut by the section."""

    def __init__(self, element, kind, t, z, width, height, oblique, reference):
        self.element = element
        self.kind = kind            # "round" or "rect"
        self.t = t
        self.z = z
        self.width = width          # along the section line
        self.height = height
        self.oblique = oblique      # cut at an angle (sloped pipe): needs a cross
        self.reference = reference  # centre line reference (round, not oblique)
        self.left = self.right = self.bottom = self.top = None   # outline references
        self.cross_v = self.cross_h = None                        # cross references


CATEGORIES = [
    (DB.BuiltInCategory.OST_PipeCurves, "Pipes"),
    (DB.BuiltInCategory.OST_DuctCurves, "Ducts"),
    (DB.BuiltInCategory.OST_CableTray, "Cable Trays"),
    (DB.BuiltInCategory.OST_Conduit, "Conduits"),
]


def _centre_reference(element, view):
    opt = DB.Options()
    opt.ComputeReferences = True
    opt.IncludeNonVisibleObjects = True
    opt.View = view
    for g in element.get_Geometry(opt):
        if isinstance(g, DB.Line) and g.Reference is not None:
            return g.Reference
    return None


def cut_elements(doc, frame, settings):
    """MEP elements of the view whose axis passes through the cut plane inside the crop."""
    from coordination.sections.floor import cross_size
    cfg = settings["sections"]
    suffix = cfg.get("exclude_workset_suffix") or ""
    table = doc.GetWorksetTable() if doc.IsWorkshared else None
    cuts = []
    for bic, cat in CATEGORIES:
        collector = (DB.FilteredElementCollector(doc, frame.view.Id)
                     .OfCategory(bic).WhereElementIsNotElementType())
        for element in collector:
            if table is not None and suffix and \
                    table.GetWorkset(element.WorksetId).Name.endswith(suffix):
                continue
            line = mep.location_line(element)
            if not isinstance(line, DB.Line):
                continue
            p, q = line.GetEndPoint(0), line.GetEndPoint(1)
            dp, dq = frame.ahead(p), frame.ahead(q)
            if dp * dq > 0 or abs(dp - dq) < 1e-9:
                continue
            x = p + (q - p) * (dp / (dp - dq))
            t = frame.t_of(x)
            if not (frame.t_min <= t <= frame.t_max and frame.z_bottom <= x.Z <= frame.z_top):
                continue
            width, height = cross_size(element)
            round_shape = cat in ("Pipes", "Conduits") or (
                cat == "Ducts" and element.get_Parameter(DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
                is not None and element.get_Parameter(DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM).HasValue
                and not (element.get_Parameter(DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM) and
                         element.get_Parameter(DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM).HasValue))
            d = q - p
            length = d.GetLength()
            facing = abs(d.X * frame.look[0] + d.Y * frame.look[1]) / length if length else 0
            oblique = round_shape and facing < math.cos(math.radians(cfg["annotation"].get(
                "oblique_deg", 0.5)))
            ref = _centre_reference(element, frame.view) if (round_shape and not oblique) else None
            if round_shape and not oblique and ref is None:
                oblique = True   # no centre reference: use a cross
            cuts.append(Cut(element, "round" if round_shape else "rect", t, x.Z,
                            width, height, oblique, ref))
    cuts.sort(key=lambda c: c.t)
    return cuts


class Face(object):
    def __init__(self, reference, position, kind, name, element_id):
        self.reference = reference   # link reference, usable in host dimensions
        self.position = position     # t (vertical faces) or z (horizontal faces)
        self.kind = kind             # concrete / block / beam / slab
        self.name = name
        self.element_id = element_id


def _solids(element, opt):
    geo = element.get_Geometry(opt)
    if geo is None:
        return []
    out = []
    for g in geo:
        if isinstance(g, DB.Solid) and g.Faces.Size:
            out.append(g)
        elif isinstance(g, DB.GeometryInstance):
            for s in g.GetInstanceGeometry():
                if isinstance(s, DB.Solid) and s.Faces.Size:
                    out.append(s)
    return out


def linked_faces(doc, frame, settings):
    """Faces of linked walls, columns, beams and floors at the section, as references.

    vertical: faces across the section line (normal along it) of walls / columns / beams
    horizontal: floor and beam faces facing down (undersides) or up."""
    from coordination.sections import concrete as C
    ccfg = settings["sections"]["concrete"]
    opt = DB.Options()
    opt.ComputeReferences = True
    corners = [frame.point(frame.t_min, frame.z_bottom), frame.point(frame.t_max, frame.z_top)]
    vertical, horizontal = [], []
    cats = [(DB.BuiltInCategory.OST_Walls, "wall"), (DB.BuiltInCategory.OST_StructuralColumns, "column"),
            (DB.BuiltInCategory.OST_StructuralFraming, "beam"), (DB.BuiltInCategory.OST_Floors, "slab")]
    for link in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ldoc = link.GetLinkDocument()
        if ldoc is None:
            continue
        tr = link.GetTotalTransform()
        inv = tr.Inverse
        pts = [inv.OfPoint(p) for p in corners]
        pad = mm_to_ft(500)
        outline = DB.Outline(DB.XYZ(min(p.X for p in pts) - pad, min(p.Y for p in pts) - pad,
                                    min(p.Z for p in pts) - pad),
                             DB.XYZ(max(p.X for p in pts) + pad, max(p.Y for p in pts) + pad,
                                    max(p.Z for p in pts) + pad))
        bbf = DB.BoundingBoxIntersectsFilter(outline)
        for bic, kind in cats:
            for e in (DB.FilteredElementCollector(ldoc).OfCategory(bic)
                      .WhereElementIsNotElementType().WherePasses(bbf)):
                name = _name(e.WallType) if isinstance(e, DB.Wall) else _name(e)
                if kind == "wall":
                    if C._has(name, ccfg["wall_keywords"]) and not C._has(name, ccfg["wall_exclude_keywords"]):
                        fkind = "concrete"
                    elif e.Width >= mm_to_ft(70):
                        fkind = "block"
                    else:
                        continue   # linings, paint, cladding
                elif kind == "column":
                    fkind = "concrete"
                else:
                    fkind = kind
                for solid in _solids(e, opt):
                    for f in solid.Faces:
                        if not isinstance(f, DB.PlanarFace) or f.Reference is None:
                            continue
                        n = tr.OfVector(f.FaceNormal)
                        org = tr.OfPoint(f.Origin)
                        # the face must actually be at the cut plane (within the section)
                        bb = f.GetBoundingBox()
                        ref = f.Reference.CreateLinkReference(link)
                        if kind != "slab" and abs(n.X * frame.along[0] + n.Y * frame.along[1]) > 0.99:
                            if not _face_at_plane(f, tr, frame):
                                continue
                            vertical.append(Face(ref, frame.t_of(org), fkind if kind != "beam" else "beam",
                                                 name, e.Id))
                        elif kind in ("slab", "beam") and abs(n.Z) > 0.99:
                            if not _face_at_plane(f, tr, frame):
                                continue
                            horizontal.append(Face(ref, org.Z, kind + ("_down" if n.Z < 0 else "_up"),
                                                   name, e.Id))
    return vertical, horizontal


def _face_at_plane(face, tr, frame):
    """True if the face reaches the cut plane (its points are on both sides of it)."""
    try:
        mesh = face.Triangulate()
        sides = set()
        for i in range(mesh.Vertices.Count):
            a = frame.ahead(tr.OfPoint(mesh.Vertices[i]))
            if a > 1e-4:
                sides.add(1)
            elif a < -1e-4:
                sides.add(-1)
            else:
                sides.add(0)
        return 0 in sides or (1 in sides and -1 in sides)
    except Exception:
        return True


def _line_style(doc, name):
    lines = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
    for sub in lines.SubCategories:
        if sub.Name == name:
            return sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    return None


def _detail_line(doc, view, a, b, style):
    curve = doc.Create.NewDetailCurve(view, DB.Line.CreateBound(a, b))
    if style is not None:
        curve.LineStyle = style
    return curve


def draw_helpers(doc, frame, cuts, settings):
    """Crosses at obliquely cut round objects, outlines around rectangular ones."""
    cfg = settings["sections"]["annotation"]
    style = _line_style(doc, cfg.get("line_style", "<Thin Lines>"))
    view = frame.view
    count = 0
    for c in cuts:
        if c.kind == "round" and c.oblique:
            arm = c.width * cfg.get("cross_factor", 1.2) / 2.0
            h = _detail_line(doc, view, frame.point(c.t - arm, c.z), frame.point(c.t + arm, c.z), style)
            v = _detail_line(doc, view, frame.point(c.t, c.z - arm), frame.point(c.t, c.z + arm), style)
            c.cross_h = h.GeometryCurve.Reference
            c.cross_v = v.GeometryCurve.Reference
            count += 2
        elif c.kind == "rect":
            l, r = c.t - c.width / 2.0, c.t + c.width / 2.0
            b, t = c.z - c.height / 2.0, c.z + c.height / 2.0
            c.bottom = _detail_line(doc, view, frame.point(l, b), frame.point(r, b), style).GeometryCurve.Reference
            c.top = _detail_line(doc, view, frame.point(l, t), frame.point(r, t), style).GeometryCurve.Reference
            c.left = _detail_line(doc, view, frame.point(l, b), frame.point(l, t), style).GeometryCurve.Reference
            c.right = _detail_line(doc, view, frame.point(r, b), frame.point(r, t), style).GeometryCurve.Reference
            count += 4
    return count


def _dimension(doc, frame, refs, a, b, dim_type):
    """refs: list of (position, reference); duplicates (same position) are dropped."""
    refs = sorted(refs, key=lambda r: r[0])
    arr = DB.ReferenceArray()
    last = None
    n = 0
    for pos, ref in refs:
        if ref is None or (last is not None and abs(pos - last) < mm_to_ft(5)):
            continue
        arr.Append(ref)
        last = pos
        n += 1
    if n < 2:
        return None
    return doc.Create.NewDimension(frame.view, DB.Line.CreateBound(a, b), arr, dim_type)


def _dim_type(doc, name):
    for d in DB.FilteredElementCollector(doc).OfClass(DB.DimensionType):
        if _name(d) == name:
            return d
    return None


def _ends(vertical, cuts, frame):
    """Concrete (or, if none, block) face nearest outside the objects on each side."""
    if not cuts:
        return None, None
    lo = min(c.t - c.width / 2.0 for c in cuts)
    hi = max(c.t + c.width / 2.0 for c in cuts)
    inside = [f for f in vertical
              if frame.t_min - mm_to_ft(20) <= f.position <= frame.t_max + mm_to_ft(20)]
    left = right = None
    for kinds in (("concrete", "beam"), ("block",)):
        cand_l = [f for f in inside if f.kind in kinds and f.position <= lo + 1e-3]
        cand_r = [f for f in inside if f.kind in kinds and f.position >= hi - 1e-3]
        if left is None and cand_l:
            left = max(cand_l, key=lambda f: f.position)    # the inner face nearest the objects
        if right is None and cand_r:
            right = min(cand_r, key=lambda f: f.position)
    return left, right


def dimension_section(doc, frame, cuts, vertical, horizontal, level, settings):
    cfg = settings["sections"]["annotation"]
    dim_type = _dim_type(doc, cfg.get("dimension_type", "Diagonal - 2.5mm Arial RED"))
    floor_ref = level.GetPlaneReference()
    z_floor = level.ProjectElevation
    mep_top = max([c.z + c.height / 2.0 for c in cuts] or [z_floor + mm_to_ft(2000)])
    slabs = [f for f in horizontal if f.kind == "slab_down" and f.position > mep_top]
    ceiling = min(slabs, key=lambda f: f.position) if slabs else None
    beams = [f for f in horizontal if f.kind == "beam_down" and mep_top - mm_to_ft(2000) < f.position
             and (ceiling is None or f.position < ceiling.position - mm_to_ft(10))]
    made = []
    gap = mm_to_ft(cfg.get("dimension_gap_mm", 400))

    # 1. floor to ceiling (+ beam)
    if ceiling is not None:
        refs = [(z_floor, floor_ref), (ceiling.position, ceiling.reference)]
        t_line = frame.t_min + mm_to_ft(400)
        if beams:
            beam = min(beams, key=lambda f: f.position)
            refs.append((beam.position, beam.reference))
            beam_faces = [f for f in vertical if f.kind == "beam" and f.element_id == beam.element_id]
            if beam_faces:
                t_line = sum(f.position for f in beam_faces) / len(beam_faces)
        d = _dimension(doc, frame, refs, frame.point(t_line, z_floor), frame.point(t_line, ceiling.position),
                       dim_type)
        if d:
            made.append(("floor-ceiling", d))

    rounds = [c for c in cuts if c.kind == "round"]
    rects = [c for c in cuts if c.kind == "rect"]
    left, right = _ends(vertical, cuts, frame)
    ends = [(f.position, f.reference) for f in (left, right) if f is not None]

    # 2. pipes horizontal
    if rounds:
        z_line = min(c.z - c.height / 2.0 for c in rounds) - gap
        refs = ends + [(c.t, c.cross_v if c.oblique else c.reference) for c in rounds]
        d = _dimension(doc, frame, refs, frame.point(frame.t_min, z_line), frame.point(frame.t_max, z_line),
                       dim_type)
        if d:
            made.append(("pipes horizontal", d))

    # 3. rectangular horizontal (edges)
    if rects:
        z_line = min(c.z - c.height / 2.0 for c in rects) - gap
        if rounds:
            z_line = min(z_line, min(c.z - c.height / 2.0 for c in rounds) - 2 * gap)
        refs = list(ends)
        for c in rects:
            refs += [(c.t - c.width / 2.0, c.left), (c.t + c.width / 2.0, c.right)]
        d = _dimension(doc, frame, refs, frame.point(frame.t_min, z_line), frame.point(frame.t_max, z_line),
                       dim_type)
        if d:
            made.append(("rect horizontal", d))

    top_ref = [(ceiling.position, ceiling.reference)] if ceiling is not None else []

    # 4. rectangular vertical (bottom and top of each, once per height)
    if rects:
        t_line = max(c.t + c.width / 2.0 for c in rects) + gap
        refs = [(z_floor, floor_ref)] + top_ref
        for c in rects:
            refs += [(c.z - c.height / 2.0, c.bottom), (c.z + c.height / 2.0, c.top)]
        d = _dimension(doc, frame, refs, frame.point(t_line, z_floor), frame.point(t_line, frame.z_top),
                       dim_type)
        if d:
            made.append(("rect vertical", d))

    # 5. pipes vertical, one chain per group along the section
    if rounds:
        groups = [[rounds[0]]]
        for c in rounds[1:]:
            if c.t - groups[-1][-1].t > mm_to_ft(cfg.get("pipe_group_gap_mm", 1500)):
                groups.append([c])
            else:
                groups[-1].append(c)
        max_chains = cfg.get("max_pipe_chains", 3)
        while len(groups) > max_chains:   # merge the two closest groups
            gaps = [groups[i + 1][0].t - groups[i][-1].t for i in range(len(groups) - 1)]
            i = gaps.index(min(gaps))
            groups[i:i + 2] = [groups[i] + groups[i + 1]]
        for g in groups:
            t_line = max(c.t + c.width / 2.0 for c in g) + mm_to_ft(250)
            refs = [(z_floor, floor_ref)] + top_ref + [(c.z, c.cross_h if c.oblique else c.reference) for c in g]
            d = _dimension(doc, frame, refs, frame.point(t_line, z_floor), frame.point(t_line, frame.z_top),
                           dim_type)
            if d:
                made.append(("pipes vertical", d))
    return made, ceiling, beams


def _tag_type(doc, category_name, family, type_name):
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        if s.Category is not None and s.Category.Name == category_name and \
                s.FamilyName == family and _name(s) == type_name:
            return s
    return None


def tag_cuts(doc, frame, cuts, settings):
    cfg = settings["sections"]["annotation"]
    types = {}
    for cat, spec in cfg["tag_types"].items():
        types[cat] = _tag_type(doc, spec[0], spec[1], spec[2])
    offset = mm_to_ft(cfg.get("tag_offset_mm", 400))
    tags = []
    for c in cuts:
        cat = mep.category_name(c.element)
        symbol = types.get(cat)
        if symbol is None:
            continue
        centre = frame.point(c.t, c.z)
        head = frame.point(c.t, c.z - c.height / 2.0 - offset)
        ref = DB.Reference(c.element)
        tag = DB.IndependentTag.Create(doc, symbol.Id, frame.view.Id, ref, True,
                                       DB.TagOrientation.Horizontal, head)
        tag.LeaderEndCondition = DB.LeaderEndCondition.Free
        try:
            tag.SetLeaderEnd(ref, centre)
        except Exception:
            tag.LeaderEnd = centre
        tag.TagHeadPosition = head
        try:
            if tag.HasLeaderElbow(ref):
                tag.SetLeaderElbow(ref, frame.point(c.t, (centre.Z + head.Z) / 2.0))
        except Exception:
            pass
        tags.append(tag)
    return tags


def annotate(doc, view, level, settings):
    """Annotate one section view (inside an open transaction). Returns a summary dict."""
    frame = Frame(view)
    cuts = cut_elements(doc, frame, settings)
    vertical, horizontal = linked_faces(doc, frame, settings)
    helpers = draw_helpers(doc, frame, cuts, settings)
    dims, ceiling, beams = dimension_section(doc, frame, cuts, vertical, horizontal, level, settings)
    tags = tag_cuts(doc, frame, cuts, settings)
    return {
        "view": view, "cuts": cuts, "helpers": helpers, "dimensions": dims, "tags": tags,
        "ceiling": ceiling, "beams": beams,
        "concrete_faces": len([f for f in vertical if f.kind in ("concrete", "beam")]),
    }
