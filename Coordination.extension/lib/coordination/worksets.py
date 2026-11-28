# -*- coding: utf-8 -*-
"""Put stray elements of a network back on the network's workset.

A network = MEP elements of the floor joined through physical connectors
(pipes, fittings, accessories, sprinklers, ducts, terminals, trays, conduits...).
Its main workset = the workset most of its elements are on. Elements on another
workset are moved to the main one, when the main one is a clear majority.

Left alone: worksets ending with -DC (temporary copies from contractor models)
- they neither vote nor get moved; networks without a clear majority (reported);
elements borrowed by another user (reported). Insulation and lining follow
their host.
"""
from pyrevit.api import DB
from System.Collections.Generic import List

from coordination.sections.floor import floor_band
from coordination.units import mm_to_ft

B = DB.BuiltInCategory
CATEGORIES = [
    B.OST_PipeCurves, B.OST_PipeFitting, B.OST_PipeAccessory, B.OST_FlexPipeCurves,
    B.OST_Sprinklers,
    B.OST_DuctCurves, B.OST_DuctFitting, B.OST_DuctAccessory, B.OST_FlexDuctCurves,
    B.OST_DuctTerminal,
    B.OST_CableTray, B.OST_CableTrayFitting, B.OST_Conduit, B.OST_ConduitFitting,
]
# Equipment and plumbing fixtures are left out on purpose: a fan coil joins chilled
# water, condensate and air, so it would merge different networks into one.
INSULATION = [B.OST_PipeInsulations, B.OST_DuctInsulations, B.OST_DuctLinings]

TEMP_SUFFIX = "-DC"
MIN_SHARE = 0.6       # main workset must hold at least this share of the network
MIN_MAIN = 3          # ... and at least this many elements
BELOW_LEVEL = mm_to_ft(300)


def idv(element_id):
    value = getattr(element_id, "Value", None)
    return element_id.IntegerValue if value is None else value


def _connectors(e):
    try:
        if isinstance(e, DB.MEPCurve):
            return list(e.ConnectorManager.Connectors)
        mm = getattr(e, "MEPModel", None)
        if mm is not None and mm.ConnectorManager is not None:
            return list(mm.ConnectorManager.Connectors)
    except Exception:
        pass
    return []


def _neighbours(e):
    out = set()
    for c in _connectors(e):
        try:
            if c.ConnectorType == DB.ConnectorType.Logical or not c.IsConnected:
                continue
            refs = list(c.AllRefs)
        except Exception:
            continue
        for r in refs:
            o = r.Owner
            if o is None or o.Id == e.Id or isinstance(o, DB.MEPSystem):
                continue
            if r.ConnectorType == DB.ConnectorType.Logical:
                continue
            out.add(idv(o.Id))
    return out


def _mid_z(e):
    loc = e.Location
    if isinstance(loc, DB.LocationCurve):
        c = loc.Curve
        return (c.GetEndPoint(0).Z + c.GetEndPoint(1).Z) / 2.0
    if isinstance(loc, DB.LocationPoint):
        return loc.Point.Z
    bb = e.get_BoundingBox(None)
    if bb is not None:
        return (bb.Min.Z + bb.Max.Z) / 2.0
    return None


def floor_elements(doc, level):
    """MEP elements of the floor: between the level (a little below) and the next level."""
    z0, z1 = floor_band(doc, level, {})
    flt = DB.ElementMulticategoryFilter(List[B](CATEGORIES))
    out = {}
    for e in DB.FilteredElementCollector(doc).WherePasses(flt).WhereElementIsNotElementType():
        if isinstance(e, DB.FamilyInstance) and e.SuperComponent is not None:
            continue            # nested part of a family: follows its parent
        z = _mid_z(e)
        if z is None or z < z0 - BELOW_LEVEL or z >= z1:
            continue
        out[idv(e.Id)] = e
    return out


def _networks(elements):
    """Connected groups (lists of ids) among `elements` {id: element}."""
    seen = set()
    groups = []
    for start in elements:
        if start in seen:
            continue
        seen.add(start)
        group, stack = [], [start]
        while stack:
            cur = stack.pop()
            group.append(cur)
            for n in _neighbours(elements[cur]):
                if n in elements and n not in seen:
                    seen.add(n)
                    stack.append(n)
        groups.append(group)
    return groups


def _system_name(e):
    for bip in (DB.BuiltInParameter.RBS_SYSTEM_NAME_PARAM,
                DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM,
                DB.BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM):
        p = e.get_Parameter(bip)
        if p is not None and p.HasValue:
            t = p.AsString() or p.AsValueString()
            if t:
                return t
    return e.Category.Name if e.Category is not None else u""


def _owned_by_other(doc, eid):
    try:
        st = DB.WorksharingUtils.GetCheckoutStatus(doc, eid)
        return st == DB.CheckoutStatus.OwnedByOtherUser
    except Exception:
        return False


def analyse(doc, level):
    """Returns dict:
      fixes:     [{"id", "from", "to", "network"}]   elements to move
      unclear:   [{"network", "counts": {ws: n}, "ids"}]  no clear majority
      borrowed:  [{"id", "from", "to", "network"}]   owned by another user
      networks:  number of networks checked (2+ elements)
    """
    table = doc.GetWorksetTable()
    names = {}

    def ws_name(e):
        k = idv(e.WorksetId)
        if k not in names:
            names[k] = table.GetWorkset(e.WorksetId).Name
        return names[k]

    elements = floor_elements(doc, level)
    res = {"fixes": [], "unclear": [], "borrowed": [], "networks": 0}
    for group in _networks(elements):
        voters = [i for i in group if not ws_name(elements[i]).endswith(TEMP_SUFFIX)]
        if len(voters) < 2:
            continue
        res["networks"] += 1
        counts = {}
        for i in voters:
            w = ws_name(elements[i])
            counts[w] = counts.get(w, 0) + 1
        if len(counts) < 2:
            continue
        main, n = max(counts.items(), key=lambda kv: kv[1])
        net = _network_label(elements, voters)
        if n < MIN_MAIN or float(n) / len(voters) < MIN_SHARE:
            res["unclear"].append({"network": net, "counts": counts, "ids": voters})
            continue
        main_id = [elements[i].WorksetId for i in voters if ws_name(elements[i]) == main][0]
        for i in voters:
            e = elements[i]
            w = ws_name(e)
            if w == main:
                continue
            row = {"id": e.Id, "from": w, "to": main, "to_id": main_id, "network": net}
            res["borrowed" if _owned_by_other(doc, e.Id) else "fixes"].append(row)
    return res


def _network_label(elements, ids):
    counts = {}
    for i in ids:
        s = _system_name(elements[i])
        counts[s] = counts.get(s, 0) + 1
    name = max(counts.items(), key=lambda kv: kv[1])[0]
    return u"%s (%d ел.)" % (name, len(ids))


def _insulation_of(doc, eid):
    try:
        return list(DB.InsulationLiningBase.GetInsulationIds(doc, eid)) + \
            list(DB.InsulationLiningBase.GetLiningIds(doc, eid))
    except Exception:
        return []


def _set_workset(e, ws_id):
    p = e.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
    if p is None or p.IsReadOnly:
        return False
    p.Set(idv(ws_id))
    return True


def apply(doc, fixes):
    """Move the elements (and their insulation/lining). Returns (moved ids, failed ids)."""
    moved, failed = [], []
    t = DB.Transaction(doc, "Fix Worksets")
    t.Start()
    try:
        for row in fixes:
            e = doc.GetElement(row["id"])
            ok = e is not None and _set_workset(e, row["to_id"])
            (moved if ok else failed).append(row["id"])
            if ok:
                for iid in _insulation_of(doc, row["id"]):
                    ins = doc.GetElement(iid)
                    if ins is not None and ins.WorksetId != row["to_id"]:
                        _set_workset(ins, row["to_id"])
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return moved, failed
