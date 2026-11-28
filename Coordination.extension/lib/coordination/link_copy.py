# -*- coding: utf-8 -*-
"""Re-copy a workset's elements on the active plan from a link.

1. Delete: every model element of the host on the chosen workset (PL) that
   the active plan shows.
2. Copy: every model element of the chosen link that the plan shows
   (Revit's own visibility: view range, crop box, visibility/graphics),
   pasted into the host on the same workset.

Risers that run through several floors are left alone on both sides: not
deleted in the host, not copied from the link. A riser = vertical pipes
(ducts, conduits) on one axis plus the inline fittings between them (tees,
couplings on the riser), reaching more than RISER_OUT beyond the floor
(level .. next level). Their insulation stays with them.

Connections of copied elements to things that were not copied (the link's
risers) are disconnected instead of failing, then free ends that meet a
kept host riser at the same point are connected again.

Host and link risers are compared by plan position: moved, missing in the
link, new in the link. Risers are reported, never moved.

Not touched: annotations and other view-specific elements, links, imports,
rooms/areas, levels/grids.
"""
import math

from pyrevit.api import DB
from System.Collections.Generic import List

from coordination.sections.floor import next_level_elevation

MM = 1 / 304.8
VERTICAL = math.sin(math.radians(85))   # |dz| / length above this = vertical
SAME_AXIS = 10 * MM                     # pipes of one riser: plan distance
RISER_OUT = 50 * MM                     # reaches beyond the floor by more = riser
MOVED = 5 * MM                          # host vs link riser: plan shift reported
MATCH = 1000 * MM                       # search radius to pair host and link risers
JOIN = 2 * MM                           # free ends this close are connected again


def idv(element_id):
    value = getattr(element_id, "Value", None)
    return element_id.IntegerValue if value is None else value


def _is_model_element(e):
    if e is None or isinstance(e, DB.ElementType):
        return False
    if isinstance(e, (DB.RevitLinkInstance, DB.ImportInstance, DB.SpatialElement,
                      DB.Level, DB.Grid, DB.View)):
        return False
    if e.OwnerViewId != DB.ElementId.InvalidElementId:
        return False                    # annotation / view-specific
    cat = e.Category
    if cat is None or cat.CategoryType != DB.CategoryType.Model:
        return False
    if isinstance(e, DB.FamilyInstance) and e.SuperComponent is not None:
        return False                    # nested part: goes with its parent
    if isinstance(e, DB.MEPSystem):
        return False
    return e.get_BoundingBox(None) is not None


# --- connectors ------------------------------------------------------------------

def _conns(e):
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
    out = []
    for c in _conns(e):
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
            out.append(o)
    return out


# --- risers ----------------------------------------------------------------------

def _vertical(e):
    """(x, y, zmin, zmax) of a vertical straight MEP curve, else None (own coordinates)."""
    if not isinstance(e, DB.MEPCurve):
        return None
    loc = e.Location
    if not isinstance(loc, DB.LocationCurve) or not isinstance(loc.Curve, DB.Line):
        return None
    a, b = loc.Curve.GetEndPoint(0), loc.Curve.GetEndPoint(1)
    length = a.DistanceTo(b)
    if length < 1e-6 or abs(b.Z - a.Z) / length < VERTICAL:
        return None
    return ((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0, min(a.Z, b.Z), max(a.Z, b.Z))


def _size_mm(e):
    for bip in (DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM, DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
                DB.BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM, DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM):
        p = e.get_Parameter(bip)
        if p is not None and p.HasValue and p.AsDouble() > 0:
            return int(round(p.AsDouble() / MM))
    return 0


def _system(e):
    for bip in (DB.BuiltInParameter.RBS_SYSTEM_NAME_PARAM, DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM):
        p = e.get_Parameter(bip)
        if p is not None and p.HasValue:
            t = p.AsString() or p.AsValueString()
            if t:
                return t
    return u""


class Riser(object):
    def __init__(self):
        self.ids = set()        # element id values in its own document
        self.x = self.y = 0.0   # host coordinates
        self.zmin = self.zmax = 0.0
        self.size = 0
        self.system = u""
        self.first = None       # ElementId of one of its pipes


def _riser_from(seed, axis, transform):
    """Walk a riser from a vertical pipe along its axis, through inline fittings."""
    x0, y0 = axis[0], axis[1]
    r = Riser()
    r.first = seed.Id
    r.size = _size_mm(seed)
    r.system = _system(seed)
    zs = []
    stack = [seed]
    r.ids.add(idv(seed.Id))
    while stack:
        pipe = stack.pop()
        v = _vertical(pipe)
        zs += [v[2], v[3]]
        for n in _neighbours(pipe):
            if idv(n.Id) in r.ids:
                continue
            nv = _vertical(n)
            if nv is not None:
                if math.hypot(nv[0] - x0, nv[1] - y0) < SAME_AXIS:
                    r.ids.add(idv(n.Id))
                    stack.append(n)
                continue
            if isinstance(n, DB.MEPCurve):
                continue
            # A fitting is part of the riser when it leads on to the next riser pipe.
            for n2 in _neighbours(n):
                if idv(n2.Id) in r.ids:
                    continue
                v2 = _vertical(n2)
                if v2 is not None and math.hypot(v2[0] - x0, v2[1] - y0) < SAME_AXIS:
                    r.ids.add(idv(n.Id))
                    r.ids.add(idv(n2.Id))
                    stack.append(n2)
    p = transform.OfPoint(DB.XYZ(x0, y0, min(zs))) if transform else DB.XYZ(x0, y0, min(zs))
    q = transform.OfPoint(DB.XYZ(x0, y0, max(zs))) if transform else DB.XYZ(x0, y0, max(zs))
    r.x, r.y = p.X, p.Y
    r.zmin, r.zmax = min(p.Z, q.Z), max(p.Z, q.Z)
    return r


def risers_among(elements, band, transform=None):
    """Risers through several floors that touch `elements`."""
    z0, z1 = band
    done = set()
    out = []
    for e in elements:
        if idv(e.Id) in done:
            continue
        v = _vertical(e)
        if v is None:
            continue
        r = _riser_from(e, v, transform)
        done |= r.ids
        if r.zmin < z0 - RISER_OUT or r.zmax > z1 + RISER_OUT:
            out.append(r)
    return out


def _with_insulation(doc, elements, keep_ids):
    """Drop elements whose id is in keep_ids, and insulation/lining hosted by them."""
    out = []
    for e in elements:
        if idv(e.Id) in keep_ids:
            continue
        if isinstance(e, DB.InsulationLiningBase) and idv(e.HostElementId) in keep_ids:
            continue
        out.append(e)
    return out


def floor_band(doc, level):
    z0 = level.ProjectElevation
    z1 = next_level_elevation(doc, level)
    return z0, (z1 if z1 is not None else z0 + 4000 * MM)


# --- what to do ------------------------------------------------------------------

def plan(doc, view, workset, link):
    """dict: delete (ids), borrowed (ids), copy (link ids), host_risers, link_risers,
    kept_ids (host riser element id values), pairs (riser comparison)."""
    band = floor_band(doc, view.GenLevel)
    host, borrowed = [], []
    for e in DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        if e.WorksetId != workset.Id or not _is_model_element(e):
            continue
        try:
            other = DB.WorksharingUtils.GetCheckoutStatus(doc, e.Id) == DB.CheckoutStatus.OwnedByOtherUser
        except Exception:
            other = False
        (borrowed if other else host).append(e)
    linked = [e for e in DB.FilteredElementCollector(doc, view.Id, link.Id).WhereElementIsNotElementType()
              if _is_model_element(e)]

    tr = link.GetTotalTransform()
    host_risers = risers_among(host + borrowed, band)
    link_risers = risers_among(linked, band, tr)
    kept = set()
    for r in host_risers:
        kept |= r.ids
    skipped = set()
    for r in link_risers:
        skipped |= r.ids
    delete = _with_insulation(doc, host, kept)
    copy = _with_insulation(link.GetLinkDocument(), linked, skipped)
    return {
        "delete": [e.Id for e in delete],
        "borrowed": [e.Id for e in borrowed],
        "copy": [e.Id for e in copy],
        "kept": kept,
        "kept_count": len(host) - len(delete),
        "skipped_count": len(linked) - len(copy),
        "host_risers": host_risers,
        "link_risers": link_risers,
        "compare": compare_risers(host_risers, link_risers),
    }


def compare_risers(host_risers, link_risers):
    """[(kind, host riser or None, link riser or None, plan shift mm)];
    kind: 'moved', 'same', 'only_host', 'only_link'."""
    out = []
    used = set()
    for h in host_risers:
        best, dist = None, None
        for k, l in enumerate(link_risers):
            if k in used or l.zmax < h.zmin or l.zmin > h.zmax:
                continue
            d = math.hypot(l.x - h.x, l.y - h.y)
            if d < MATCH and (dist is None or d < dist):
                best, dist = k, d
        if best is None:
            out.append(("only_host", h, None, None))
            continue
        used.add(best)
        kind = "moved" if dist > MOVED else "same"
        out.append((kind, h, link_risers[best], dist / MM))
    for k, l in enumerate(link_risers):
        if k not in used:
            out.append(("only_link", None, l, None))
    return out


# --- transaction ------------------------------------------------------------------

class _UseHostTypes(DB.IDuplicateTypeNamesHandler):
    def OnDuplicateTypeNamesFound(self, args):
        return DB.DuplicateTypeAction.UseDestinationTypes


class _Failures(DB.IFailuresPreprocessor):
    """Warnings are dismissed; errors Revit can resolve itself (e.g. 'disconnect
    the family from the network') are resolved; others roll back."""

    def __init__(self):
        self.errors = []
        self.resolved = 0

    def PreprocessFailures(self, fa):
        bad = False
        resolved = False
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
            elif f.HasResolutions():
                fa.ResolveFailure(f)
                self.resolved += 1
                resolved = True
            else:
                self.errors.append(f.GetDescriptionText())
                bad = True
        if bad:
            return DB.FailureProcessingResult.ProceedWithRollBack
        if resolved:
            return DB.FailureProcessingResult.ProceedWithCommit
        return DB.FailureProcessingResult.Continue


def _commit(t):
    fp = _Failures()
    o = t.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(fp)
    o.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(o)
    ok = t.Commit() == DB.TransactionStatus.Committed
    return ok, fp.errors, fp.resolved


def _rejoin(doc, new_ids, kept_ids):
    """Connect free ends of new elements to free ends of kept risers at the same point."""
    targets = []
    for i in kept_ids:
        try:
            e = doc.GetElement(DB.ElementId(i))
        except Exception:
            e = None
        if e is None:
            continue
        for c in _conns(e):
            try:
                if c.ConnectorType != DB.ConnectorType.Logical and not c.IsConnected:
                    targets.append((e, c))
            except Exception:
                pass
    joined = 0
    if not targets:
        return joined
    for i in new_ids:
        e = doc.GetElement(i)
        if e is None:
            continue
        for c in _conns(e):
            try:
                if c.ConnectorType == DB.ConnectorType.Logical or c.IsConnected:
                    continue
            except Exception:
                continue
            for owner, h in targets:
                if h.IsConnected or c.Origin.DistanceTo(h.Origin) > JOIN:
                    continue
                if isinstance(owner, DB.MEPCurve) and isinstance(e, DB.MEPCurve):
                    continue            # two pipe ends need a fitting between them
                try:
                    c.ConnectTo(h)
                    joined += 1
                    break
                except Exception:
                    pass
    return joined


def run(doc, p, link, workset):
    """Delete, copy, rejoin - one undo step. Returns dict: new_ids, errors, step,
    disconnected, joined. On errors nothing is changed."""
    res = {"new_ids": [], "errors": [], "step": None, "disconnected": 0, "joined": 0}
    table = doc.GetWorksetTable()
    old_active = table.GetActiveWorksetId()
    table.SetActiveWorksetId(workset.Id)
    group = DB.TransactionGroup(doc, "Copy from Link")
    group.Start()
    t = None

    def fail(step, errors):
        group.RollBack()
        res.update(step=step, errors=errors or [u"Revit відхилив зміни"], new_ids=[])
        return res

    try:
        if p["delete"]:
            t = DB.Transaction(doc, "Delete old")
            t.Start()
            doc.Delete(List[DB.ElementId](p["delete"]))
            ok, errors, _ = _commit(t)
            if not ok:
                return fail(u"видалення", errors)
        if p["copy"]:
            t = DB.Transaction(doc, "Copy from link")
            t.Start()
            opts = DB.CopyPasteOptions()
            opts.SetDuplicateTypeNamesHandler(_UseHostTypes())
            new_ids = list(DB.ElementTransformUtils.CopyElements(
                link.GetLinkDocument(), List[DB.ElementId](p["copy"]), doc,
                link.GetTotalTransform(), opts))
            for i in new_ids:
                e = doc.GetElement(i)
                if e is None or e.WorksetId == workset.Id:
                    continue
                prm = e.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
                if prm is not None and not prm.IsReadOnly:
                    prm.Set(idv(workset.Id))
            ok, errors, resolved = _commit(t)
            if not ok:
                return fail(u"вставка", errors)
            res["disconnected"] = resolved
            res["new_ids"] = [i for i in new_ids if doc.GetElement(i) is not None]
        if res["new_ids"] and p["kept"]:
            t = DB.Transaction(doc, "Rejoin risers")
            t.Start()
            joined = _rejoin(doc, res["new_ids"], p["kept"])
            ok, errors, _ = _commit(t)
            if ok:
                res["joined"] = joined
        group.Assimilate()
        return res
    except Exception as ex:
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
        res.update(step=u"виконання", errors=[u"%s" % ex], new_ids=[])
        return res
    finally:
        try:
            table.SetActiveWorksetId(old_active)
        except Exception:
            pass


# --- links and worksets ----------------------------------------------------------

def loaded_links(doc):
    """[(name, link instance)] of loaded links; the name is unique."""
    out = []
    seen = {}
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is None:
            continue
        name = ld.Title
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = u"%s (%d)" % (name, seen[name])
        out.append((name, li))
    return out


def user_worksets(doc):
    return list(DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset))


def workset_by_name(doc, name):
    for w in user_worksets(doc):
        if w.Name == name:
            return w
    return None
