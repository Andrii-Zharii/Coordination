# -*- coding: utf-8 -*-
"""Section box around a run of pipes / ducts / trays / conduits up to the next turn.

From the selected elements the network is followed in both directions, element by
element through their connectors. Through tees and crosses the walk goes straight on
(the branch is left out). It stops at, and includes, the first fitting that turns the
run in the chosen way:

  plan      left / right: the direction in plan changes (vertical offsets are passed)
  vertical  up / down: the slope changes (turns in plan are passed)
  any       either of them

It also stops at equipment, terminals, open ends and where a branch is entered from
the side. The section box is oriented along the selected run in plan.
"""
import math
from System.Collections.Generic import List
from pyrevit.api import DB

from coordination.clash import core as gc

MM = 1 / 304.8
MARGIN_MM = 500.0
TURN_DEG = 5.0
LIMIT = 3000
STRAIGHT = math.cos(math.radians(TURN_DEG))
PASS_CATEGORIES = (
    DB.BuiltInCategory.OST_PipeFitting, DB.BuiltInCategory.OST_DuctFitting,
    DB.BuiltInCategory.OST_CableTrayFitting, DB.BuiltInCategory.OST_ConduitFitting,
    DB.BuiltInCategory.OST_PipeAccessory, DB.BuiltInCategory.OST_DuctAccessory,
)
MODE_NAMES = {
    "plan": u"вліво / вправо",
    "vertical": u"вгору / вниз",
    "any": u"будь-який поворот",
}


def _connectors(element):
    manager = None
    if isinstance(element, DB.MEPCurve):
        manager = element.ConnectorManager
    elif isinstance(element, DB.FamilyInstance) and element.MEPModel is not None:
        manager = element.MEPModel.ConnectorManager
    if manager is None:
        return []
    return [c for c in manager.Connectors if c.ConnectorType != DB.ConnectorType.Logical]


def _direction(connector):
    """Outward direction of a connector (away from its owner)."""
    try:
        return connector.CoordinateSystem.BasisZ
    except Exception:
        return None


def _plan(vector):
    flat = DB.XYZ(vector.X, vector.Y, 0)
    if flat.GetLength() < 0.05:
        return None  # vertical
    return flat.Normalize()


def _elevation(vector):
    return math.degrees(math.asin(max(-1.0, min(1.0, vector.Z))))


def _is_pass(element):
    if isinstance(element, DB.MEPCurve):
        return True
    category = element.Category
    if category is None:
        return False
    return gc.id_int(category.Id) in [int(c) for c in PASS_CATEGORIES]


def _partner(connector, owner_id):
    """The connector of the next element joined to this one, or None."""
    try:
        if not connector.IsConnected:
            return None
        refs = list(connector.AllRefs)
    except Exception:
        return None
    for ref in refs:
        if ref.Owner is None or ref.Owner.Id == owner_id or ref.ConnectorType == DB.ConnectorType.Logical:
            continue
        if isinstance(ref.Owner, (DB.MEPCurve, DB.FamilyInstance)):
            return ref
    return None


def _exit(element, entry, incoming):
    """Where the run leaves the element when entered at `entry`, or None."""
    others = [c for c in _connectors(element) if not entry.Origin.IsAlmostEqualTo(c.Origin)]
    if isinstance(element, DB.MEPCurve):
        if entry.ConnectorType != DB.ConnectorType.End:
            return None  # entered a main from a tap
        others = [c for c in others if c.ConnectorType == DB.ConnectorType.End]
        return others[0] if len(others) == 1 else None
    if len(others) == 1:
        return others[0]
    best, best_dot = None, -2.0
    for c in others:
        d = _direction(c)
        if d is not None and d.DotProduct(incoming) > best_dot:
            best, best_dot = c, d.DotProduct(incoming)
    return best if best_dot > STRAIGHT else None  # entered a tee from the branch


def _turns(mode, incoming, outgoing, last_plan):
    plan_out = _plan(outgoing)
    horizontal = (plan_out is not None and last_plan is not None
                  and plan_out.DotProduct(last_plan) < STRAIGHT)
    vertical = abs(_elevation(incoming) - _elevation(outgoing)) > TURN_DEG
    if mode == "plan":
        return horizontal
    if mode == "vertical":
        return vertical
    return horizontal or vertical


def _walk(start, connector, mode, seen):
    """Follow the run from `start` out through `connector`; adds elements to `seen`."""
    direction = _direction(connector)
    if direction is None:
        return
    last_plan = _plan(direction)
    current, out = start, connector
    while len(seen) < LIMIT:
        entry = _partner(out, current.Id)
        if entry is None:
            return
        element = entry.Owner
        key = gc.id_int(element.Id)
        if key in seen:
            return
        seen[key] = element
        if not _is_pass(element):
            return  # equipment, terminal
        incoming = _direction(entry)
        if incoming is None:
            return
        incoming = incoming.Negate()
        nxt = _exit(element, entry, incoming)
        if nxt is None:
            return
        outgoing = _direction(nxt)
        if outgoing is None or _turns(mode, incoming, outgoing, last_plan):
            return
        if _plan(outgoing) is not None:
            last_plan = _plan(outgoing)
        current, out = element, nxt


def run_elements(starts, mode):
    """The start elements plus their runs in both directions up to the next turn."""
    seen = {}
    for start in starts:
        seen[gc.id_int(start.Id)] = start
    for start in starts:
        for connector in _connectors(start):
            if isinstance(start, DB.MEPCurve) and connector.ConnectorType != DB.ConnectorType.End:
                continue
            _walk(start, connector, mode, seen)
    return list(seen.values())


def _axis(starts):
    for start in starts:
        if isinstance(start, DB.MEPCurve) and isinstance(start.Location, DB.LocationCurve):
            curve = start.Location.Curve
            plan = _plan(curve.GetEndPoint(1) - curve.GetEndPoint(0))
            if plan is not None:
                return plan
    return DB.XYZ.BasisX


def _half_size(curve_element):
    size = 0.0
    for name in ("Diameter", "Width", "Height"):
        try:
            size = max(size, getattr(curve_element, name))
        except Exception:
            pass
    for bip in (DB.BuiltInParameter.RBS_PIPE_OUTER_DIAMETER,):
        p = curve_element.get_Parameter(bip)
        if p is not None and p.HasValue:
            size = max(size, p.AsDouble())
    return size / 2.0 if size > 0 else 0.5


def _points(element):
    location = element.Location
    if isinstance(element, DB.MEPCurve) and isinstance(location, DB.LocationCurve):
        r = _half_size(element)
        result = []
        for i in (0, 1):
            p = location.Curve.GetEndPoint(i)
            result += [p + DB.XYZ(dx, dy, dz) for dx in (-r, r) for dy in (-r, r) for dz in (-r, r)]
        return result
    bb = element.get_BoundingBox(None)
    if bb is None:
        return []
    return [DB.XYZ(x, y, z) for x in (bb.Min.X, bb.Max.X)
            for y in (bb.Min.Y, bb.Max.Y) for z in (bb.Min.Z, bb.Max.Z)]


def section_box(elements, starts, margin_mm=MARGIN_MM):
    """BoundingBoxXYZ around the elements, oriented along the start run in plan."""
    x = _axis(starts)
    z = DB.XYZ.BasisZ
    y = z.CrossProduct(x)
    points = []
    for element in elements:
        points += _points(element)
    if not points:
        return None
    local = [(p.DotProduct(x), p.DotProduct(y), p.DotProduct(z)) for p in points]
    margin = margin_mm * MM
    lo = [min(v[i] for v in local) - margin for i in range(3)]
    hi = [max(v[i] for v in local) + margin for i in range(3)]
    transform = DB.Transform.Identity
    transform.BasisX = x
    transform.BasisY = y
    transform.BasisZ = z
    transform.Origin = DB.XYZ.Zero
    box = DB.BoundingBoxXYZ()
    box.Transform = transform
    box.Min = DB.XYZ(*lo)
    box.Max = DB.XYZ(*hi)
    return box


def _set_box(view, box):
    view.SetSectionBox(box)
    view.IsSectionBoxActive = True


def apply(uidoc, elements, starts, margin_mm=MARGIN_MM):
    """Puts the section box into the active 3D view (or the user's CLASH Navigator view
    when the active view is not 3D or its box is locked by a template), selects the run
    and zooms to it. One undo step. Returns the view used."""
    doc = uidoc.Document
    box = section_box(elements, starts, margin_mm)
    if box is None:
        raise ValueError(u"Немає геометрії для section box.")
    active = uidoc.ActiveView
    transaction = DB.Transaction(doc, u"Box Run")
    transaction.Start()
    try:
        view = None
        if isinstance(active, DB.View3D) and not active.IsTemplate:
            try:
                _set_box(active, box)
                view = active
            except Exception:
                view = None
        if view is None:
            view = gc._nav_view(doc)
            if view.ViewTemplateId != DB.ElementId.InvalidElementId:
                view.ViewTemplateId = DB.ElementId.InvalidElementId
            _set_box(view, box)
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise
    if uidoc.ActiveView.Id != view.Id:
        uidoc.ActiveView = view
    ids = List[DB.ElementId]([e.Id for e in elements])
    uidoc.Selection.SetElementIds(ids)
    corners = [box.Transform.OfPoint(box.Min), box.Transform.OfPoint(box.Max)]
    for ui_view in uidoc.GetOpenUIViews():
        if ui_view.ViewId == view.Id:
            lo = DB.XYZ(min(c.X for c in corners), min(c.Y for c in corners), min(c.Z for c in corners))
            hi = DB.XYZ(max(c.X for c in corners), max(c.Y for c in corners), max(c.Z for c in corners))
            ui_view.ZoomAndCenterRectangle(lo, hi)
    return view
