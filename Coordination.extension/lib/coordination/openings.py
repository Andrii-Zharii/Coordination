# -*- coding: utf-8 -*-
"""Place Openings: puts an opening family where a pipe passes through a linked wall / slab without an opening.

Works on the results of 'Clash у зоні' (best with the analysis "План отворів"): every clash of kind "through"
between a straight pipe of the model and a linked wall or floor gets one instance of the round opening family
(settings "openings": pipe_family), on the face of the wall / slab where the pipe axis crosses it, on the
workset "Openings". The type is the smallest one whose diameter >= pipe outer diameter + clearance.

The family is face based: it is hosted on the face of the linked element (a link reference).
Electrical and mechanical openings (rectangular, other families) come later.
"""
import re

from pyrevit import DB

from coordination import config
from coordination.clash import core as gc

FACE_CATEGORIES = (u"Walls", u"Floors", u"Structural Foundations", u"Roofs")


def settings():
    return config.load().get("openings", {})


# ---------------------------------------------------------------- family types

def _type_name(symbol):
    param = symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return (param.AsString() if param is not None else u"") or u""


def _diameter_from_name(name):
    """Inches written in the type name, e.g. 'שרוול "2' or '2"' or '1 1/2"' -> mm, or None."""
    match = re.search(u'(\\d+(?:[.,]\\d+)?(?:\\s+\\d+/\\d+)?|\\d+/\\d+)\\s*"', name) or \
        re.search(u'"\\s*(\\d+(?:[.,]\\d+)?(?:\\s+\\d+/\\d+)?|\\d+/\\d+)', name)
    if not match:
        return None
    total = 0.0
    for part in match.group(1).replace(u",", u".").split():
        if u"/" in part:
            a, b = part.split(u"/")
            total += float(a) / float(b)
        else:
            total += float(part)
    return total * 25.4


def symbol_diameter_mm(symbol, names):
    """Diameter of a round opening type: a length parameter of the type (names from settings),
    else inches in the type name. None when unknown."""
    for name in names:
        param = symbol.LookupParameter(name)
        if param is not None and param.HasValue and param.StorageType == DB.StorageType.Double and param.AsDouble() > 0:
            return gc.to_mm(param.AsDouble())
    return _diameter_from_name(_type_name(symbol))


def opening_types(doc, cfg):
    """[(diameter mm, symbol)] of the round pipe opening family, smallest first."""
    part = cfg.get("pipe_family", u"פתח למערכות עגול")
    names = cfg.get("diameter_parameters", [u"Diameter"])
    result = []
    for symbol in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        if part not in symbol.FamilyName:
            continue
        diameter = symbol_diameter_mm(symbol, names)
        if diameter:
            result.append((diameter, symbol))
    result.sort(key=lambda x: x[0])
    return result


def pick_type(types, pipe_mm, clearance_mm):
    need = pipe_mm + clearance_mm
    for diameter, symbol in types:
        if diameter >= need - 0.5:
            return diameter, symbol
    return None, None


# ---------------------------------------------------------------- geometry

def _pipe_axis(pipe):
    location = pipe.Location
    if isinstance(location, DB.LocationCurve) and isinstance(location.Curve, DB.Line):
        return location.Curve
    return None


def _outer_diameter_mm(pipe):
    param = pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_OUTER_DIAMETER)
    if param is not None and param.HasValue:
        return gc.to_mm(param.AsDouble())
    return None


def _host_face(link, element, line):
    """(link reference of the face, point on it in host coordinates, face normal in host coordinates,
    thickness across in feet) for the planar face of the linked element that the pipe axis enters first."""
    transform = link.GetTotalTransform()
    inverse = transform.Inverse
    options = DB.Options()
    options.ComputeReferences = True
    options.DetailLevel = DB.ViewDetailLevel.Fine
    p0 = inverse.OfPoint(line.GetEndPoint(0))
    p1 = inverse.OfPoint(line.GetEndPoint(1))
    d = (p1 - p0).Normalize()
    hits = []
    for g in element.get_Geometry(options):
        if not isinstance(g, DB.Solid) or g.Volume <= 0:
            continue
        for face in g.Faces:
            if not isinstance(face, DB.PlanarFace) or face.Reference is None:
                continue
            n = face.FaceNormal
            denom = d.DotProduct(n)
            if abs(denom) < 0.7:
                continue
            t = (face.Origin - p0).DotProduct(n) / denom
            point = p0 + d.Multiply(t)
            projected = face.Project(point)
            if projected is None or projected.Distance > gc.to_ft(1):
                continue
            hits.append((t, face, point))
    if not hits:
        return None
    hits.sort(key=lambda h: h[0])
    t, face, point = hits[0]
    thickness = abs(hits[-1][0] - t) if len(hits) > 1 else 0.0
    reference = face.Reference.CreateLinkReference(link)
    return reference, transform.OfPoint(point), transform.OfVector(face.FaceNormal), thickness


# ---------------------------------------------------------------- planning and placing

def plan(doc, groups, first_index=0):
    """What would be placed: list of dicts (clash name, pipe id, pipe Ø, type, diameter, link face...) and a
    list of skipped (name, reason)."""
    cfg = settings()
    types = opening_types(doc, cfg)
    if not types:
        raise ValueError(u"No opening family '%s' with diameters in the model." % cfg.get("pipe_family"))
    clearance = float(cfg.get("clearance_mm", 0))
    items, skipped = [], []
    for index, group in enumerate(groups):
        members = group.get("members") or [group]
        for member_index, clash in enumerate(members):
            name = gc.clash_name(first_index + index, member_index, group)
            if clash.get("kind") != u"through":
                continue
            host = [s for s in (clash["a"], clash["b"]) if s["link_id"] is None]
            linked = [s for s in (clash["a"], clash["b"]) if s["link_id"] is not None]
            if len(host) != 1 or len(linked) != 1:
                skipped.append((name, u"not pipe x linked structure"))
                continue
            pipe = doc.GetElement(gc.make_id(host[0]["id"]))
            if not isinstance(pipe, DB.Plumbing.Pipe):
                skipped.append((name, u"%s: only straight pipes for now" % host[0]["category"]))
                continue
            if linked[0]["category"] not in FACE_CATEGORIES:
                skipped.append((name, u"%s: only walls and floors for now" % linked[0]["category"]))
                continue
            line = _pipe_axis(pipe)
            pipe_mm = _outer_diameter_mm(pipe)
            link = doc.GetElement(gc.make_id(linked[0]["link_id"]))
            structure = link.GetLinkDocument().GetElement(gc.make_id(linked[0]["id"])) if link else None
            if line is None or not pipe_mm or structure is None:
                skipped.append((name, u"pipe or linked element not found"))
                continue
            face = _host_face(link, structure, line)
            if face is None:
                skipped.append((name, u"no face of the wall / slab on the pipe axis"))
                continue
            diameter, symbol = pick_type(types, pipe_mm, clearance)
            if symbol is None:
                skipped.append((name, u"pipe %.0f mm larger than the largest opening type" % pipe_mm))
                continue
            items.append({"name": name, "pipe": pipe, "pipe_mm": pipe_mm, "symbol": symbol,
                          "diameter": diameter, "type": _type_name(symbol), "face": face,
                          "structure": u"%s %s" % (linked[0]["category"], linked[0]["type"])})
    return items, skipped


def _workset_id(doc, name):
    for workset in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset):
        if workset.Name == name:
            return workset.Id
    return DB.Workset.Create(doc, name).Id


def place(doc, items):
    """Places the planned openings (one undo step). Returns (placed, errors)."""
    cfg = settings()
    depth_names = cfg.get("depth_parameters", [])
    placed, errors = [], []
    transaction = DB.Transaction(doc, u"Place openings")
    transaction.Start()
    try:
        workset_id = _workset_id(doc, cfg.get("workset", u"Openings")) if doc.IsWorkshared else None
        for item in items:
            reference, point, normal, thickness = item["face"]
            direction = normal.CrossProduct(DB.XYZ.BasisZ)
            if direction.GetLength() < 1e-6:
                direction = DB.XYZ.BasisX
            try:
                symbol = item["symbol"]
                if not symbol.IsActive:
                    symbol.Activate()
                instance = doc.Create.NewFamilyInstance(reference, point, direction.Normalize(), symbol)
                if workset_id is not None:
                    instance.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM).Set(workset_id.IntegerValue)
                if thickness > 0:
                    for name in depth_names:
                        param = instance.LookupParameter(name)
                        if param is not None and not param.IsReadOnly and param.StorageType == DB.StorageType.Double:
                            param.Set(thickness)
                            break
                comments = instance.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                if comments is not None and not comments.IsReadOnly:
                    comments.Set(u"auto %s, pipe #%d" % (item["name"], gc.id_int(item["pipe"].Id)))
                placed.append((item, gc.id_int(instance.Id)))
            except Exception as error:
                errors.append((item["name"], u"%s" % error))
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise
    return placed, errors
