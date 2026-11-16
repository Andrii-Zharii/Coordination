# -*- coding: utf-8 -*-
"""Case recorder: captures how a clash was resolved, for learning coordination rules.

Workflow (buttons on the Cases panel):
  Before -> screenshot of the active view + data of the clash elements, their whole
            straight runs (to the next bend/tee) and the MEP around them.
  (user fixes the clash)
  After  -> the same capture again, a short note from the user, and a diff
            (moved / new / deleted elements). Status: resolved.
  Skip   -> the clash is not a real clash (status: not_a_clash) or cannot be fixed by us
            and must be discussed with the contractors (status: escalate). Screenshot + note.

Files go to <repo>/cases/<model>/<check date>/CLASH-NNN/ and are pushed with GitHub Desktop.
No model changes are made.
"""
import io
import json
import os
import re
import shutil
from datetime import datetime

from System.Collections.Generic import List
from pyrevit import DB

from coordination import config, mep
from coordination.clash import core as gc

REPO_DIR = os.path.dirname(config.EXTENSION_DIR)
CASES_DIR = os.path.join(REPO_DIR, "cases")
STATE_FILE = os.path.join(gc.DATA_DIR, "case_pending.json")

CONTEXT_MARGIN_MM = 1500.0   # MEP around the clash point
RUN_MARGIN_MM = 300.0        # MEP along the whole runs of the clash elements
RUN_LIMIT = 400              # safety limit of elements per run
IMAGE_PIXELS = 1400

STATUS_RESOLVED = "resolved"
STATUS_NOT_A_CLASH = "not_a_clash"
STATUS_ESCALATE = "escalate"
MOVE_TOLERANCE_MM = 1.0

MEP_CATEGORIES = [
    DB.BuiltInCategory.OST_PipeCurves, DB.BuiltInCategory.OST_PipeFitting,
    DB.BuiltInCategory.OST_PipeAccessory, DB.BuiltInCategory.OST_FlexPipeCurves,
    DB.BuiltInCategory.OST_DuctCurves, DB.BuiltInCategory.OST_DuctFitting,
    DB.BuiltInCategory.OST_DuctAccessory, DB.BuiltInCategory.OST_FlexDuctCurves,
    DB.BuiltInCategory.OST_CableTray, DB.BuiltInCategory.OST_CableTrayFitting,
    DB.BuiltInCategory.OST_Conduit, DB.BuiltInCategory.OST_ConduitFitting,
    DB.BuiltInCategory.OST_Sprinklers,
]


# ---------------------------------------------------------------- helpers

def _mm(value):
    return round(gc.to_mm(value), 1)


def _xyz(point):
    return [_mm(point.X), _mm(point.Y), _mm(point.Z)]


def _safe_name(text):
    text = re.sub(u"[\\\\/:*?\"<>|]+", u"_", text or u"model")
    return text.strip(u" ._") or u"model"


def _write_json(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=1)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(u"%s" % text)


def _read_json(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())


def _connectors(element):
    manager = None
    if isinstance(element, DB.MEPCurve):
        manager = element.ConnectorManager
    elif isinstance(element, DB.FamilyInstance) and element.MEPModel is not None:
        manager = element.MEPModel.ConnectorManager
    if manager is None:
        return []
    result = []
    for connector in manager.Connectors:
        if connector.ConnectorType == DB.ConnectorType.Logical:
            continue
        result.append(connector)
    return result


def _neighbours(element):
    result = []
    for connector in _connectors(element):
        try:
            if not connector.IsConnected:
                continue
            refs = connector.AllRefs
        except Exception:
            continue
        for ref in refs:
            owner = ref.Owner
            if owner is None or owner.Id == element.Id:
                continue
            if ref.ConnectorType == DB.ConnectorType.Logical:
                continue
            if isinstance(owner, (DB.MEPCurve, DB.FamilyInstance)):
                result.append(owner)
    return result


def _is_passthrough(element):
    """In-line fitting/accessory (coupling, reducer, valve): two opposite connectors."""
    connectors = _connectors(element)
    if len(connectors) != 2:
        return False
    try:
        a = connectors[0].CoordinateSystem.BasisZ
        b = connectors[1].CoordinateSystem.BasisZ
    except Exception:
        return False
    return a.DotProduct(b) < -0.99


def straight_run(start, limit=RUN_LIMIT):
    """The element plus everything connected to it in a straight line, up to and including
    the next bend or branch (elbow, tee) in both directions."""
    seen = {gc.id_int(start.Id): start}
    stack = [start]
    while stack and len(seen) < limit:
        element = stack.pop()
        if element is not start and isinstance(element, DB.FamilyInstance) and not _is_passthrough(element):
            continue  # bend / branch: include it, do not go further
        for neighbour in _neighbours(element):
            key = gc.id_int(neighbour.Id)
            if key not in seen:
                seen[key] = neighbour
                stack.append(neighbour)
    return list(seen.values())


def _bbox(element, transform=None):
    bb = element.get_BoundingBox(None)
    if bb is None:
        return None
    if transform is None:
        return gc.Box(bb.Min, bb.Max)
    return gc.Box.of_points([transform.OfPoint(DB.XYZ(x, y, z))
                             for x in (bb.Min.X, bb.Max.X)
                             for y in (bb.Min.Y, bb.Max.Y)
                             for z in (bb.Min.Z, bb.Max.Z)])


def _box_json(box):
    return {"min": [box.lo.X, box.lo.Y, box.lo.Z], "max": [box.hi.X, box.hi.Y, box.hi.Z]}


def _box_from_json(data):
    return gc.Box(DB.XYZ(*data["min"]), DB.XYZ(*data["max"]))


def _type_name(doc, element):
    if isinstance(element, DB.FamilyInstance):
        param = element.Symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        return u"%s : %s" % (element.Symbol.FamilyName, param.AsString() if param is not None else u"")
    type_element = doc.GetElement(element.GetTypeId())
    if type_element is None:
        return u""
    param = type_element.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return param.AsString() if param is not None else u""


def describe(doc, element):
    """JSON-ready description of a host MEP element. Coordinates in mm (internal origin)."""
    size = element.get_Parameter(DB.BuiltInParameter.RBS_CALCULATED_SIZE)
    data = {
        "id": gc.id_int(element.Id),
        "category": element.Category.Name if element.Category else u"",
        "type": _type_name(doc, element),
        "size": (size.AsString() if size is not None and size.HasValue else u"") or u"",
        "system": mep.system_name(element),
        "workset": gc._workset_name(doc, element),
    }
    box = _bbox(element)
    if box is not None:
        data["bbox"] = [_xyz(box.lo), _xyz(box.hi)]
    location = element.Location
    if isinstance(location, DB.LocationCurve):
        curve = location.Curve
        data["start"] = _xyz(curve.GetEndPoint(0))
        data["end"] = _xyz(curve.GetEndPoint(1))
        data["length"] = _mm(curve.Length)
        slope = mep.slope_percent(element)
        if slope is not None:
            data["slope_percent"] = round(slope, 2)
        data["height"] = _mm(mep.vertical_size(element))
    elif isinstance(location, DB.LocationPoint):
        data["point"] = _xyz(location.Point)
    if isinstance(element, DB.FamilyInstance) and element.MEPModel is not None:
        part_type = getattr(element.MEPModel, "PartType", None)
        if part_type is not None:
            data["part_type"] = u"%s" % part_type
        angle = element.LookupParameter(u"Angle")
        if angle is not None and angle.HasValue and angle.StorageType == DB.StorageType.Double:
            data["angle_deg"] = round(angle.AsDouble() * 180.0 / 3.141592653589793, 1)
    data["connected_to"] = sorted(set(gc.id_int(n.Id) for n in _neighbours(element)))
    return data


def _linked_side(doc, side):
    """Bounding box of a linked element of the clash (e.g. the beam), in mm."""
    link = doc.GetElement(gc.make_id(side["link_id"]))
    if link is None or link.GetLinkDocument() is None:
        return None
    element = link.GetLinkDocument().GetElement(gc.make_id(side["id"]))
    if element is None:
        return None
    box = _bbox(element, link.GetTotalTransform())
    return [_xyz(box.lo), _xyz(box.hi)] if box is not None else None


def _collect_region(doc, boxes):
    """Host MEP elements whose bounding box overlaps any of the boxes."""
    if not boxes:
        return []
    lo = DB.XYZ(min(b.lo.X for b in boxes), min(b.lo.Y for b in boxes), min(b.lo.Z for b in boxes))
    hi = DB.XYZ(max(b.hi.X for b in boxes), max(b.hi.Y for b in boxes), max(b.hi.Z for b in boxes))
    categories = List[DB.BuiltInCategory](MEP_CATEGORIES)
    collector = (DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
                 .WherePasses(DB.ElementMulticategoryFilter(categories))
                 .WherePasses(DB.BoundingBoxIntersectsFilter(DB.Outline(lo, hi))))
    result = []
    for element in collector:
        box = _bbox(element)
        if box is not None and any(box.overlaps(b) for b in boxes):
            result.append(element)
    return result


def export_view_image(doc, view, target_path):
    """Exports the view as a JPEG to target_path (Revit adds view names to file names,
    so export into a temporary folder and rename)."""
    temp_dir = os.path.join(os.path.dirname(target_path), "_export")
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    options = DB.ImageExportOptions()
    options.ExportRange = DB.ExportRange.SetOfViews
    options.SetViewsAndSheets(List[DB.ElementId]([view.Id]))
    options.FilePath = os.path.join(temp_dir, "img")
    options.ZoomType = DB.ZoomFitType.FitToPage
    options.PixelSize = IMAGE_PIXELS
    options.FitDirection = DB.FitDirectionType.Horizontal
    options.HLRandWFViewsFileType = DB.ImageFileType.JPEGMedium
    options.ShadowViewsFileType = DB.ImageFileType.JPEGMedium
    doc.ExportImage(options)
    files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir)]
    if files:
        if os.path.isfile(target_path):
            os.remove(target_path)
        shutil.move(files[0], target_path)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return os.path.isfile(target_path)


# ---------------------------------------------------------------- capture

def current_clash(doc):
    """(number, clash dict, results) of the clash shown by the navigator, or (None, None, None)."""
    results = gc.load_results()
    if not results or results.get("document") != doc.Title:
        return None, None, None
    index = results.get("current", -1)
    clashes = results.get("clashes") or []
    if not 0 <= index < len(clashes):
        return None, None, None
    return index + 1, clashes[index], results


def capture(doc, view, case_dir, stage, element_ids, region_boxes):
    """Screenshot + data of the given host elements, their runs and the region around them."""
    elements = {}
    runs = []
    for value in element_ids:
        element = doc.GetElement(gc.make_id(value))
        if element is None:
            continue
        run = straight_run(element)
        runs.append({"start": value, "ids": sorted(gc.id_int(e.Id) for e in run)})
        for e in run:
            elements[gc.id_int(e.Id)] = e
    for e in _collect_region(doc, region_boxes):
        elements[gc.id_int(e.Id)] = e
    image_ok = False
    image_error = None
    try:
        image_ok = export_view_image(doc, view, os.path.join(case_dir, stage + ".jpg"))
    except Exception as error:
        image_error = u"%s" % error
    data = {
        "stage": stage,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": doc.Application.Username,
        "view": view.Name,
        "runs": runs,
        "elements": [describe(doc, e) for e in sorted(elements.values(), key=lambda x: gc.id_int(x.Id))],
    }
    if image_error:
        data["image_error"] = image_error
    _write_json(os.path.join(case_dir, stage + ".json"), data)
    return data, image_ok


def start_case(doc, view, selection_ids):
    """Before: captures the current clash of the navigator (or the selected elements)."""
    number, clash, results = current_clash(doc)
    levels = sorted(([l.Name, _mm(l.ProjectElevation)] for l in
                     DB.FilteredElementCollector(doc).OfClass(DB.Level)), key=lambda l: l[1])
    if clash is not None:
        case_name = u"CLASH-%03d" % number
        check = _safe_name((results.get("created") or u"").replace(u":", u"-"))
        host_ids = [s["id"] for s in (clash["a"], clash["b"]) if s["link_id"] is None]
        point_box = gc.Box(DB.XYZ(*clash["min"]), DB.XYZ(*clash["max"]))
        info = {"source": "clash", "number": number, "label": gc.clash_label(number - 1, clash),
                "zone": results.get("zone"), "clash": clash}
        for side in ("a", "b"):
            if clash[side]["link_id"] is not None:
                info["linked_" + side + "_bbox"] = _linked_side(doc, clash[side])
    elif selection_ids:
        case_name = u"SEL-" + datetime.now().strftime("%H%M%S")
        check = datetime.now().strftime("%Y-%m-%d")
        host_ids = list(selection_ids)
        boxes = [_bbox(doc.GetElement(gc.make_id(i))) for i in host_ids]
        boxes = [b for b in boxes if b is not None]
        if not boxes:
            raise ValueError(u"The selected elements have no geometry to record.")
        point_box = gc.Box(DB.XYZ(min(b.lo.X for b in boxes), min(b.lo.Y for b in boxes), min(b.lo.Z for b in boxes)),
                           DB.XYZ(max(b.hi.X for b in boxes), max(b.hi.Y for b in boxes), max(b.hi.Z for b in boxes)))
        info = {"source": "selection", "label": u"Selected elements: %s" % u", ".join(u"%d" % i for i in host_ids)}
    else:
        raise ValueError(u"No current clash. Open one with Next / Previous / List on the Clash panel, "
                         u"or select the elements of the problem.")

    case_dir = os.path.join(CASES_DIR, _safe_name(doc.Title), check, case_name)
    if not os.path.isdir(case_dir):
        os.makedirs(case_dir)

    region = [point_box.expanded(gc.to_ft(CONTEXT_MARGIN_MM))]
    for value in host_ids:
        element = doc.GetElement(gc.make_id(value))
        if element is None:
            continue
        for e in straight_run(element):
            box = _bbox(e)
            if box is not None:
                region.append(box.expanded(gc.to_ft(RUN_MARGIN_MM)))

    info.update({"model": doc.Title, "levels": levels, "host_ids": host_ids})
    _write_json(os.path.join(case_dir, "case.json"), info)
    data, image_ok = capture(doc, view, case_dir, "before", host_ids, region)

    if not os.path.isdir(gc.DATA_DIR):
        os.makedirs(gc.DATA_DIR)
    _write_json(STATE_FILE, {"document": doc.Title, "case_dir": case_dir, "case": case_name,
                             "host_ids": host_ids, "region": [_box_json(b) for b in region]})
    return case_name, case_dir, len(data["elements"]), image_ok


def pending_case(doc):
    if not os.path.isfile(STATE_FILE):
        return None
    state = _read_json(STATE_FILE)
    if state.get("document") != doc.Title or not os.path.isdir(state.get("case_dir", u"")):
        return None
    return state


def finish_case(doc, view, state, note):
    """After: captures the same region again, stores the note and the diff."""
    case_dir = state["case_dir"]
    region = [_box_from_json(b) for b in state["region"]]
    after, image_ok = capture(doc, view, case_dir, "after", state["host_ids"], region)
    before = _read_json(os.path.join(case_dir, "before.json"))
    changes = diff(before["elements"], after["elements"])
    after["note"] = note or u""
    after["diff"] = changes
    _write_json(os.path.join(case_dir, "after.json"), after)
    set_status(case_dir, STATUS_RESOLVED, note)
    os.remove(STATE_FILE)
    return changes, image_ok


def set_status(case_dir, status, note):
    """Stores the outcome of the case in case.json and the note in note.txt."""
    path = os.path.join(case_dir, "case.json")
    info = _read_json(path) if os.path.isfile(path) else {}
    info["status"] = status
    info["note"] = note or u""
    info["closed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(path, info)
    with io.open(os.path.join(case_dir, "note.txt"), "w", encoding="utf-8") as f:
        f.write(u"[%s]\n%s\n" % (status, note or u""))


def skip_case(doc, view, selection_ids, status, note):
    """Skip: records the current clash as not_a_clash or escalate.

    Uses the case started with Before when it is the same clash; otherwise captures it now.
    """
    state = pending_case(doc)
    number, clash, results = current_clash(doc)
    expected = u"CLASH-%03d" % number if clash is not None else None
    if state is None or (expected is not None and state.get("case") != expected):
        case_name, case_dir, _, image_ok = start_case(doc, view, selection_ids)
        state = pending_case(doc)
    else:
        case_name, case_dir, image_ok = state["case"], state["case_dir"], True
    set_status(case_dir, status, note)
    if os.path.isfile(STATE_FILE):
        os.remove(STATE_FILE)
    return case_name, case_dir, image_ok


# ---------------------------------------------------------------- diff

def _delta(a, b):
    return [round(b[i] - a[i], 1) for i in range(3)]


def _moved(delta):
    return any(abs(v) > MOVE_TOLERANCE_MM for v in delta)


def _describe_short(e):
    parts = [e.get("category"), e.get("size"), e.get("part_type")]
    if e.get("angle_deg"):
        parts.append(u"%g°" % e["angle_deg"])
    return u" ".join(p for p in parts if p)


def diff(before, after):
    """List of changes between two element lists (dicts from describe)."""
    old = dict((e["id"], e) for e in before)
    new = dict((e["id"], e) for e in after)
    changes = []
    for key in sorted(set(old) - set(new)):
        changes.append({"id": key, "change": "deleted", "what": _describe_short(old[key])})
    for key in sorted(set(new) - set(old)):
        changes.append({"id": key, "change": "new", "what": _describe_short(new[key]), "element": new[key]})
    for key in sorted(set(old) & set(new)):
        a, b = old[key], new[key]
        notes = []
        if "start" in a and "start" in b:
            d0 = _delta(a["start"], b["start"])
            d1 = _delta(a["end"], b["end"])
            if _moved(d0) or _moved(d1):
                if d0 == d1:
                    notes.append(u"moved dx=%g dy=%g dz=%g mm" % tuple(d0))
                else:
                    notes.append(u"start dz=%g, end dz=%g mm, length %g -> %g" % (
                        d0[2], d1[2], a.get("length", 0), b.get("length", 0)))
        elif "point" in a and "point" in b:
            d = _delta(a["point"], b["point"])
            if _moved(d):
                notes.append(u"moved dx=%g dy=%g dz=%g mm" % tuple(d))
        for field in ("size", "type", "system", "slope_percent", "angle_deg"):
            if a.get(field) != b.get(field):
                notes.append(u"%s: %s -> %s" % (field, a.get(field), b.get(field)))
        if notes:
            changes.append({"id": key, "change": "changed", "what": _describe_short(b), "details": u"; ".join(notes)})
    return changes
