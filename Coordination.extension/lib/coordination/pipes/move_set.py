# -*- coding: utf-8 -*-
"""What moves together with the selected pipe (duct, cable tray, conduit).

From the selected element the connected network is followed through connectors in all
directions, branches of tees and taps included. Each pipe reached is compared with the
selected one in the chosen direction:

  vertical    its angle to the horizontal (slope) must be the same: a riser, a 45-degree
              offset or another slope stops the walk;
  horizontal  its direction in plan must be the same (parallel or opposite): any turn in
              plan, a perpendicular branch or a riser stops the walk.

A pipe that differs is the one that stretches when the network is moved, so it is not
taken, but the fitting before it is. Fittings and accessories are passed. Flexible pipes
and ducts stretch, so they stop the walk too. Equipment stops the walk and is not taken.

Terminals (sprinkler heads, air terminals) and the short drops leading to them
(steep pipes / flex up to drop_max_elements elements, ending only in terminals) are
returned apart: the button asks whether they move too.
"""
import math
from System.Collections.Generic import List
from pyrevit.api import DB

from coordination import mep

MM = 1 / 304.8
LIMIT = 20000
VERTICAL_FLAT = math.sin(math.radians(1.0))  # a pipe steeper than 89 degrees has no plan direction
DROP_MIN_DEG = 45.0

MODES = ("horizontal", "vertical")
MODE_NAMES = {
    "horizontal": u"Зсув по горизонталі",
    "vertical": u"Зсув по вертикалі",
}

PASS_CATEGORIES = set(int(c) for c in (
    DB.BuiltInCategory.OST_PipeFitting, DB.BuiltInCategory.OST_DuctFitting,
    DB.BuiltInCategory.OST_CableTrayFitting, DB.BuiltInCategory.OST_ConduitFitting,
    DB.BuiltInCategory.OST_PipeAccessory, DB.BuiltInCategory.OST_DuctAccessory,
))
TERMINAL_CATEGORIES = set(int(c) for c in (
    DB.BuiltInCategory.OST_Sprinklers, DB.BuiltInCategory.OST_DuctTerminal,
))


def _key(element):
    return mep.element_id_value(element.Id)


def connectors(element):
    manager = None
    if isinstance(element, DB.MEPCurve):
        manager = element.ConnectorManager
    elif isinstance(element, DB.FamilyInstance) and element.MEPModel is not None:
        manager = element.MEPModel.ConnectorManager
    if manager is None:
        return []
    return [c for c in manager.Connectors
            if int(c.ConnectorType) & int(DB.ConnectorType.Physical)]


def _neighbours(element):
    """Elements joined to `element` through its physical connectors."""
    own = element.Id
    result = []
    for c in connectors(element):
        try:
            if not c.IsConnected:
                continue
            refs = list(c.AllRefs)
        except Exception:
            continue
        for ref in refs:
            owner = ref.Owner
            if owner is None or owner.Id == own or isinstance(owner, DB.MEPSystem):
                continue
            if not (int(ref.ConnectorType) & int(DB.ConnectorType.Physical)):
                continue
            if isinstance(owner, (DB.MEPCurve, DB.FamilyInstance)):
                result.append(owner)
    return result


def _category(element):
    category = element.Category
    return mep.element_id_value(category.Id) if category is not None else None


def _is_flex(element):
    for name in ("FlexPipe", "FlexDuct"):
        for space in (getattr(DB, "Plumbing", None), getattr(DB, "Mechanical", None)):
            cls = getattr(space, name, None) if space is not None else None
            if cls is not None and isinstance(element, cls):
                return True
    return False


def kind(element):
    """'curve', 'flex', 'pass' (fitting, accessory), 'terminal' or 'stop' (equipment, other)."""
    if isinstance(element, DB.MEPCurve):
        if _is_flex(element) or not isinstance(element.Location, DB.LocationCurve):
            return "flex"
        return "curve"
    cat = _category(element)
    if cat in PASS_CATEGORIES:
        return "pass"
    if cat in TERMINAL_CATEGORIES:
        return "terminal"
    return "stop"


def _direction(curve_element):
    curve = curve_element.Location.Curve
    d = curve.GetEndPoint(1) - curve.GetEndPoint(0)
    if d.GetLength() < 1e-9:
        return None
    return d.Normalize()


def elevation_deg(direction):
    return math.degrees(math.asin(min(1.0, abs(direction.Z))))


def _plan_deg(direction):
    """Direction in plan, 0..180 degrees, or None for a vertical pipe."""
    if math.hypot(direction.X, direction.Y) < VERTICAL_FLAT:
        return None
    return math.degrees(math.atan2(direction.Y, direction.X)) % 180.0


class Reference(object):
    """The selected pipe: what the others are compared with."""

    def __init__(self, curve_element, mode, tolerance_deg):
        self.mode = mode
        self.tolerance = tolerance_deg
        d = _direction(curve_element)
        self.elevation = elevation_deg(d) if d is not None else 0.0
        self.plan = _plan_deg(d) if d is not None else None

    def same(self, curve_element):
        d = _direction(curve_element)
        if d is None:
            return True
        if self.mode == "vertical":
            return abs(elevation_deg(d) - self.elevation) <= self.tolerance
        plan = _plan_deg(d)
        if self.plan is None or plan is None:
            return self.plan is None and plan is None
        diff = abs(plan - self.plan) % 180.0
        return min(diff, 180.0 - diff) <= self.tolerance


class MoveSet(object):
    def __init__(self):
        self.moving = {}      # key -> element: moves together with the selection
        self.stretching = {}  # key -> element: pipes / flex that stretch (not taken)
        self.terminals = {}   # key -> element: terminals reached directly
        self.equipment = {}   # key -> element: equipment the network runs into
        self.drops = []       # [ [elements] ]: terminal with its drop, asked separately

    def drop_elements(self):
        return [e for group in self.drops for e in group]

    def drop_terminal_count(self):
        return len([e for e in self.drop_elements() if kind(e) == "terminal"])


def _walk(start, reference, result):
    queue = [start]
    result.moving[_key(start)] = start
    while queue and len(result.moving) < LIMIT:
        element = queue.pop()
        for other in _neighbours(element):
            key = _key(other)
            if (key in result.moving or key in result.stretching or key in result.terminals
                    or key in result.equipment):
                continue
            k = kind(other)
            if k == "curve":
                if reference.same(other):
                    result.moving[key] = other
                    queue.append(other)
                else:
                    result.stretching[key] = other
            elif k == "flex":
                result.stretching[key] = other
            elif k == "pass":
                result.moving[key] = other
                queue.append(other)
            elif k == "terminal":
                result.terminals[key] = other
            else:
                result.equipment[key] = other


def _drop_from(first, taken, max_elements):
    """The elements beyond `first` (a stretching pipe or a terminal) if they are only a
    drop to terminals: steep pipes / flex, fittings and terminals, at most max_elements."""
    group = {_key(first): first}
    queue = [first]
    while queue:
        element = queue.pop()
        k = kind(element)
        if k == "stop":
            return None
        if k == "curve" and elevation_deg(_direction(element) or DB.XYZ.BasisZ) < DROP_MIN_DEG:
            return None
        for other in _neighbours(element):
            key = _key(other)
            if key in group or key in taken:
                continue
            group[key] = other
            if len(group) > max_elements:
                return None
            queue.append(other)
    elements = list(group.values())
    if not [e for e in elements if kind(e) == "terminal"]:
        return None
    return elements


def collect(starts, mode, settings=None):
    """MoveSet for the selected elements in the chosen mode ('horizontal' / 'vertical')."""
    cfg = (settings or {}).get("move_set", {})
    tolerance = float(cfg.get("angle_tolerance_deg", 0.1))
    max_drop = int(cfg.get("drop_max_elements", 8))
    curves = [s for s in starts if kind(s) == "curve"]
    if not curves:
        raise ValueError(u"У виділенні немає труби, повітропроводу, лотка чи кабелепроводу.")
    result = MoveSet()
    for start in starts:
        own = curves[0] if kind(start) != "curve" else start
        _walk(start, Reference(own, mode, tolerance), result)
    # a selected element is never "stretching"
    for start in starts:
        result.stretching.pop(_key(start), None)
    taken = set(result.moving.keys())
    used = set()
    for first in list(result.terminals.values()) + list(result.stretching.values()):
        if _key(first) in used:
            continue
        group = _drop_from(first, taken | used, max_drop)
        if group:
            result.drops.append(group)
            used.update(_key(e) for e in group)
    return result


# --- section box -----------------------------------------------------------------

def _plan_axis(starts):
    for start in starts:
        if kind(start) == "curve":
            d = _direction(start)
            if d is not None and _plan_deg(d) is not None:
                return DB.XYZ(d.X, d.Y, 0).Normalize()
    return DB.XYZ.BasisX


def _half_size(curve_element):
    size = 0.0
    for name in ("Diameter", "Width", "Height"):
        try:
            size = max(size, getattr(curve_element, name))
        except Exception:
            pass
    p = curve_element.get_Parameter(DB.BuiltInParameter.RBS_PIPE_OUTER_DIAMETER)
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


def section_box(elements, starts, margin_mm):
    """BoundingBoxXYZ around the elements, oriented along the selected pipe in plan."""
    x = _plan_axis(starts)
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


def show(uidoc, elements, starts, margin_mm=500.0):
    """Selects the elements. In a 3D view the section box is fitted around them (the
    user's CLASH Navigator view is used when the active view's box is locked by a
    template); in other views the view is zoomed to them. Returns the view used."""
    doc = uidoc.Document
    ids = List[DB.ElementId]([e.Id for e in elements])
    uidoc.Selection.SetElementIds(ids)
    active = uidoc.ActiveView
    if not isinstance(active, DB.View3D) or active.IsTemplate:
        try:
            uidoc.ShowElements(ids)
        except Exception:
            pass
        return active
    box = section_box(elements, starts, margin_mm)
    if box is None:
        raise ValueError(u"Немає геометрії для section box.")
    transaction = DB.Transaction(doc, u"Move Set")
    transaction.Start()
    try:
        view = None
        try:
            active.SetSectionBox(box)
            active.IsSectionBoxActive = True
            view = active
        except Exception:
            view = None
        if view is None:
            from coordination.clash import core as gc
            view = gc._nav_view(doc)
            if view.ViewTemplateId != DB.ElementId.InvalidElementId:
                view.ViewTemplateId = DB.ElementId.InvalidElementId
            view.SetSectionBox(box)
            view.IsSectionBoxActive = True
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise
    if uidoc.ActiveView.Id != view.Id:
        uidoc.ActiveView = view
    uidoc.Selection.SetElementIds(ids)
    corners = [box.Transform.OfPoint(box.Min), box.Transform.OfPoint(box.Max)]
    for ui_view in uidoc.GetOpenUIViews():
        if ui_view.ViewId == view.Id:
            lo = DB.XYZ(min(c.X for c in corners), min(c.Y for c in corners), min(c.Z for c in corners))
            hi = DB.XYZ(max(c.X for c in corners), max(c.Y for c in corners), max(c.Z for c in corners))
            ui_view.ZoomAndCenterRectangle(lo, hi)
    return view
