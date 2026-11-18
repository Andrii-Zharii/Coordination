# -*- coding: utf-8 -*-
"""Split parallel cable-tray T-junctions onto different elevations.

A junction is 2-3 parallel mains whose tees branch the same way, so the
branches of the far mains cross the near mains. Every main gets its own
tier around its tee; one stays put. Moved branches run back to their old
height, or straight to the next straight when they bend soon after the tee,
which merges the old transition into the new ramp.

Rules: never below 2300 mm from the level, never into concrete (structure is
a hard clash), other services are soft clashes for manual review, all new and
changed elements go to the EL workset.
"""
import math
import itertools
from pyrevit.api import DB
from System.Collections.Generic import List

MM = 1 / 304.8
CM = 1 / 30.48
MIN_OFFSET = 2300 * MM
BEND_RADIUS = 5 * CM
BEND_LENGTH = 2.5 * CM
RAMP_ANGLE = 45.0
RAMP_ANGLES = [45.0, 30.0, 20.0, 15.0]
CLEAR = 0.4
TOL = 0.01
GAP = 0.5 * MM
WORKSET = "EL"

B = DB.BuiltInCategory
HARD = [B.OST_StructuralFraming, B.OST_Floors, B.OST_Walls, B.OST_StructuralColumns,
        B.OST_Columns, B.OST_StructuralFoundation, B.OST_Roofs, B.OST_Stairs]
SOFT = [B.OST_PipeCurves, B.OST_PipeFitting, B.OST_PipeAccessory, B.OST_FlexPipeCurves,
        B.OST_DuctCurves, B.OST_DuctFitting, B.OST_DuctAccessory, B.OST_FlexDuctCurves,
        B.OST_DuctTerminal, B.OST_MechanicalEquipment, B.OST_CableTray,
        B.OST_CableTrayFitting, B.OST_Conduit, B.OST_ConduitFitting, B.OST_Sprinklers,
        B.OST_ElectricalEquipment, B.OST_PlumbingFixtures]
TRAY_IDS = set([int(B.OST_CableTray), int(B.OST_CableTrayFitting)])
HARD_IDS = set(int(c) for c in HARD)
DUP_TRAY_LINKS = ["GRHL-MAIN-E"]
DEFAULT_LINKS = ["GRHL-A-MAIN"]
ZONE_XY = 15.0
ZONE_Z = 1.5
MAX_BUILDS = 5
BELOW_LIMIT = u"нижче 2300"
MAX_CROSSING = 8.0
OPENING_WORDS = [u"פתח", u"שרוול", u"opening", u"sleeve"]
MAX_OPENING = 12.0
OPENING_TOL = 10 * MM


def conns(e):
    cm = e.ConnectorManager if isinstance(e, DB.MEPCurve) else e.MEPModel.ConnectorManager
    return list(cm.Connectors)


def near_conn(e, p):
    return min(conns(e), key=lambda c: c.Origin.DistanceTo(p))


def _reducer_after(o, c):
    """If fitting `o` on tee connector `c` is an inline width reducer leading to
    a straight, return {el, seg, len}, otherwise None."""
    try:
        cs = conns(o)
    except Exception:
        return None
    if len(cs) != 2:
        return None
    near = min(cs, key=lambda k: k.Origin.DistanceTo(c.Origin))
    far = cs[0] if cs[1] is near else cs[1]
    if near.CoordinateSystem.BasisZ.DotProduct(far.CoordinateSystem.BasisZ) > -0.999:
        return None
    if abs(near.Width - far.Width) < 1e-6:
        return None
    for r in far.AllRefs:
        if r.Owner.Id != o.Id and isinstance(r.Owner, DB.MEPCurve):
            return {"el": o, "seg": r.Owner, "len": near.Origin.DistanceTo(far.Origin)}
    return None


def tee_info(doc, f):
    """Geometry of a horizontal tee with three straight horizontal legs, or None.
    A main leg may start with a width reducer; a branch may not."""
    try:
        cm = f.MEPModel.ConnectorManager
    except Exception:
        return None
    if cm is None or cm.Connectors.Size != 3:
        return None
    PT = f.Location.Point
    legs = []
    for c in cm.Connectors:
        seg = None
        red = None
        for r in c.AllRefs:
            if r.Owner.Id == f.Id:
                continue
            if isinstance(r.Owner, DB.MEPCurve):
                seg = r.Owner
            else:
                red = _reducer_after(r.Owner, c)
                if red:
                    seg = red["seg"]
        if seg is None:
            return None
        a = seg.Location.Curve.GetEndPoint(0)
        b = seg.Location.Curve.GetEndPoint(1)
        if abs(a.Z - b.Z) > TOL or abs(a.Z - PT.Z) > TOL:
            return None
        ff = a.DistanceTo(PT) > b.DistanceTo(PT)
        far = a if ff else b
        v = far - PT
        d = DB.XYZ(v.X, v.Y, 0)
        if d.GetLength() < 1e-6:
            return None
        legs.append({"seg": seg, "far": far, "ff": ff, "d": d.Normalize(),
                     "reach": d.GetLength(), "conn": c.Origin.DistanceTo(PT),
                     "reducer": red, "w": c.Width, "h": c.Height})
    bi = None
    for i in range(3):
        o = [k for k in range(3) if k != i]
        if (legs[o[0]]["d"].DotProduct(legs[o[1]]["d"]) < -0.999
                and abs(legs[i]["d"].DotProduct(legs[o[0]]["d"])) < 0.001):
            bi = i
    if bi is None:
        return None
    br = legs[bi]
    if br["reducer"]:
        return None
    mains = [legs[k] for k in range(3) if k != bi]
    ms = mains[0]["seg"]
    return {"tee": f, "id": f.Id.IntegerValue, "PT": PT, "u": mains[0]["d"], "v": br["d"],
            "mains": mains, "branch": br, "W": max(m["w"] for m in mains), "H": ms.Height,
            "Wb": br["w"], "tee_main": max(m["conn"] for m in mains),
            "tee_br": br["conn"], "level": ms.LevelId,
            "offset": ms.get_Parameter(DB.BuiltInParameter.RBS_OFFSET_PARAM).AsDouble(),
            "name": doc.GetElement(ms.GetTypeId()).get_Parameter(
                DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()}


def _same_height(a, b):
    """Trays at one height: bottoms, centres or tops level within TOL, so trays
    of different heights laid on one bottom line still form a junction."""
    za, zb = a["PT"].Z, b["PT"].Z
    ha, hb = a["H"] / 2, b["H"] / 2
    return min(abs((za - ha) - (zb - hb)), abs(za - zb), abs((za + ha) - (zb + hb))) <= TOL


def detect(doc, outline=None):
    """All tees and the junctions they form: (tees, [members nearest-first])."""
    col = DB.FilteredElementCollector(doc).OfCategory(B.OST_CableTrayFitting) \
        .OfClass(DB.FamilyInstance)
    if outline is not None:
        col = col.WherePasses(DB.BoundingBoxIntersectsFilter(outline))
    tees = [t for t in (tee_info(doc, f) for f in col) if t]
    parent = list(range(len(tees)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    buckets = {}
    for i, t in enumerate(tees):
        buckets.setdefault(int(math.floor(t["PT"].Z)), []).append(i)
    for key, idx in buckets.items():
        near = idx + buckets.get(key + 1, [])
        for x in range(len(idx)):
            for y in range(x + 1, len(near)):
                a, b = tees[idx[x]], tees[near[y]]
                if not _same_height(a, b) or a["v"].DotProduct(b["v"]) < 0.999:
                    continue
                d = b["PT"] - a["PT"]
                if abs(d.DotProduct(a["u"])) < 5 and 0.1 < abs(d.DotProduct(a["v"])) < 3:
                    parent[find(idx[x])] = find(near[y])
    groups = {}
    for i in range(len(tees)):
        groups.setdefault(find(i), []).append(tees[i])
    out = []
    for g in groups.values():
        if len(g) < 2:
            continue
        v = g[0]["v"]
        g.sort(key=lambda t: -t["PT"].DotProduct(v))
        out.append(g)
    return tees, out


def schemes_for(ms):
    """Tier per member (ms[0] = main nearest the branch side). Every member
    gets its own tier; one stays at 0. Order: all-up, split, all-down; within
    a set, the nearest main staying and the far one just above it come first."""
    n = len(ms)
    if n == 2:
        sets = [[0, 1], [-1, 0]]
    elif n == 3:
        sets = [[0, 1, 2], [-1, 0, 1], [-2, -1, 0]]
    else:
        return []
    out = []
    for base in sets:
        perms = list(itertools.permutations(base))
        perms.sort(key=lambda p: (abs(p[0]), p != (0, 2, 1), [abs(t) for t in p]))
        out.extend(perms)
    return out


def tiers(ms, scheme):
    """Height change per member: the tier-0 member stays, the others are stacked
    above and below it with touching faces, whatever their heights and their
    current centres."""
    order = sorted(range(len(ms)), key=lambda i: scheme[i])
    zero = list(scheme).index(0)
    k0 = order.index(zero)
    centre = {zero: ms[zero]["PT"].Z}
    for k in range(k0 + 1, len(order)):
        a, b = order[k - 1], order[k]
        centre[b] = centre[a] + (ms[a]["H"] + ms[b]["H"]) / 2
    for k in range(k0 - 1, -1, -1):
        a, b = order[k + 1], order[k]
        centre[b] = centre[a] - (ms[a]["H"] + ms[b]["H"]) / 2
    return [centre[i] - ms[i]["PT"].Z for i in range(len(ms))]


def short_name(m, ms):
    """First word of the tray type, with its width when another member shares it."""
    word = m["name"].split()[0]
    if sum(1 for o in ms if o["name"].split()[0] == word) > 1:
        word += str(int(round(m["W"] / MM)))
    return word


def label(ms, scheme):
    dzs = tiers(ms, scheme)
    return " ".join("%s%+d" % (short_name(m, ms), round(dz / MM)) if abs(dz) > 1e-6 else
                    "%s 0" % short_name(m, ms) for m, dz in zip(ms, dzs))


def _others(e, prev_id):
    return [r.Owner for c in conns(e) for r in c.AllRefs
            if r.Owner.Id != e.Id and r.Owner.Id != prev_id
            and isinstance(r.Owner, (DB.MEPCurve, DB.FamilyInstance))]


def _walk_target(first, prev, PT, v, need):
    """Walk from straight `first` along direction v, past bends, slopes and
    reducers, to the first horizontal straight on the same line that reaches
    `need` ft from PT. Returns {seg, far, ff, z, between, red_len}, or None at a
    branching, a turn in plan or a sideways shift. `between` excludes `first`."""
    prev, cur = prev, first
    between = []
    red_len = 0.0
    for _ in range(10):
        nxt = _others(cur, prev)
        if len(nxt) != 1:
            return None
        prev, cur = cur.Id, nxt[0]
        if isinstance(cur, DB.MEPCurve):
            a, b = cur.Location.Curve.GetEndPoint(0), cur.Location.Curve.GetEndPoint(1)
            d = b - a
            flat = DB.XYZ(d.X, d.Y, 0)
            if flat.GetLength() < 1e-6 or abs(flat.Normalize().DotProduct(v)) < 0.999:
                return None
            off = DB.XYZ(a.X - PT.X, a.Y - PT.Y, 0)
            if off.CrossProduct(v).GetLength() > TOL:
                return None
            if abs(d.Z) < TOL:
                ff = (a - PT).DotProduct(v) > (b - PT).DotProduct(v)
                far = a if ff else b
                if (far - PT).DotProduct(v) >= need + 0.15:
                    return {"seg": cur, "far": far, "ff": ff, "z": far.Z,
                            "between": between, "red_len": red_len}
        else:
            cs = conns(cur)
            if len(cs) != 2:
                return None
            if abs(cs[0].Width - cs[1].Width) > 1e-6:
                red_len = max(red_len, cs[0].Origin.DistanceTo(cs[1].Origin))
        between.append(cur.Id)
    return None


def branch_target(m, need):
    """Target straight for a branch; a width change along the way is not handled."""
    tgt = _walk_target(m["branch"]["seg"], m["tee"].Id, m["PT"], m["v"], need)
    if tgt and tgt["red_len"]:
        return None
    return tgt


def main_target(m, leg, need):
    """Target straight for a main leg that is too short for its own ramp."""
    prev = leg["reducer"]["el"].Id if leg["reducer"] else m["tee"].Id
    tgt = _walk_target(leg["seg"], prev, m["PT"], leg["d"], need)
    if tgt:
        tgt["narrow"] = abs(tgt["seg"].Width - leg["w"]) > 1e-6
        tgt["neck_len"] = max(tgt["red_len"], leg["reducer"]["len"] if leg["reducer"] else 0.0)
    return tgt


def _ramp_clear(m, leg, F, z_flat, z_end, obstacles):
    """Distance from the tee where a ramp from z_flat to z_end may start: past any
    structure crossing the tray that the ramp would hit but the flat part at
    z_flat passes under or over. Structure running along the tray for more than
    MAX_CROSSING is ignored, so a ramp never moves far from the junction; the
    clash test judges it. Works on bounding boxes of the structure in `obstacles`."""
    if obstacles is None:
        return F
    h, e = m["H"], 1e-3
    lo, hi = min(z_flat, z_end) - h / 2, max(z_flat, z_end) + h / 2
    PT, d = m["PT"], leg["d"]
    n = DB.XYZ(-d.Y, d.X, 0)
    half = leg["w"] / 2
    for a, b in obstacles.boxes:
        if b.Z <= lo + e or a.Z >= hi - e:
            continue
        if a.Z < z_flat + h / 2 - e and b.Z > z_flat - h / 2 + e:
            continue
        corners = [DB.XYZ(x, y, PT.Z) - PT for x in (a.X, b.X) for y in (a.Y, b.Y)]
        side = [c.DotProduct(n) for c in corners]
        along = [c.DotProduct(d) for c in corners]
        if max(side) <= -half or min(side) >= half or max(along) <= 0:
            continue
        if max(along) - min(along) > MAX_CROSSING:
            continue
        F = max(F, max(along) + CLEAR)
    return F


def _ramp_limit(m, leg, z_flat, z_end, obstacles):
    """Distance from the tee to the nearest structure ahead that a ramp from
    z_flat back to z_end would hit but a tray at z_end clears, or None."""
    if obstacles is None:
        return None
    h, e = m["H"], 1e-3
    lo, hi = min(z_flat, z_end) - h / 2, max(z_flat, z_end) + h / 2
    PT, d = m["PT"], leg["d"]
    n = DB.XYZ(-d.Y, d.X, 0)
    half = leg["w"] / 2
    limit = None
    for a, b in obstacles.boxes:
        if b.Z <= lo + e or a.Z >= hi - e:
            continue
        if a.Z < z_end + h / 2 - e and b.Z > z_end - h / 2 + e:
            continue
        corners = [DB.XYZ(x, y, PT.Z) - PT for x in (a.X, b.X) for y in (a.Y, b.Y)]
        side = [c.DotProduct(n) for c in corners]
        along = [c.DotProduct(d) for c in corners]
        if max(side) <= -half or min(side) >= half or min(along) <= 0:
            continue
        limit = min(along) if limit is None else min(limit, min(along))
    return limit


def plan(ms, scheme, obstacles=None, ignore_limit=False):
    """Per member: None (stays) or the deviation sizes. A raised main only covers
    the crossings of branches not on the opposite side of the base height.
    ignore_limit lets a plan go below MIN_OFFSET. Returns (plan, why_not)."""
    dzs = tiers(ms, scheme)
    out = []
    for i in range(len(ms)):
        m = ms[i]
        dz = dzs[i]
        if abs(dz) < 1e-6:
            out.append(None)
            continue
        R = abs(dz) / math.tan(math.radians(RAMP_ANGLE))
        if m["offset"] + dz < MIN_OFFSET - 1e-4 and not ignore_limit:
            return None, BELOW_LIMIT
        F = m["tee_main"] + CLEAR
        tight = m["tee_main"] + 0.1
        for k in range(i + 1, len(ms)):
            if dzs[k] * dz >= 0:
                cross = abs((ms[k]["PT"] - m["PT"]).DotProduct(m["u"])) + ms[k]["Wb"] / 2
                F = max(F, cross + CLEAR)
                tight = max(tight, cross + 0.1)
        for l in m["mains"]:
            if l["reducer"]:
                F = max(F, l["conn"] + 2 * l["reducer"]["len"] + 0.1 + CLEAR)
                tight = max(tight, l["conn"] + 2 * l["reducer"]["len"] + 0.1 + 0.1)
        L = m["tee_br"] + CLEAR
        if i > 0:
            L = max(L, (ms[0]["PT"] - m["PT"]).DotProduct(m["v"]) + ms[0]["W"] / 2 + CLEAR)
        z_new = m["PT"].Z + dz
        leg_targets = [None] * len(m["mains"])
        for _ in range(2):
            for n, l in enumerate(m["mains"]):
                if l["reach"] >= F + R + 0.3:
                    leg_targets[n] = None
                    continue
                tgt = main_target(m, l, F + abs(dz))
                if tgt is not None:
                    tgt = main_target(m, l, F + abs(tgt["z"] - z_new)) or tgt
                if tgt is None:
                    return None, "коротка магістраль"
                if tgt["narrow"]:
                    F = max(F, l["conn"] + 1.5 * tgt["neck_len"] + 0.4)
                leg_F = _ramp_clear(m, l, F, z_new, tgt["z"], obstacles)
                tgt = main_target(m, l, leg_F + abs(tgt["z"] - z_new))
                if tgt is None:
                    return None, "коротка магістраль"
                tgt["R2"] = abs(tgt["z"] - z_new)
                tgt["F"] = leg_F
                leg_targets[n] = tgt
        leg_F = []
        for l, t in zip(m["mains"], leg_targets):
            limit = _ramp_limit(m, l, z_new, m["PT"].Z, obstacles) if t is None else None
            if limit is not None and F + R + 0.25 > limit:
                leg_F.append(max(tight, limit - R - 0.25))
            else:
                leg_F.append(F)
        p = {"dz": dz, "F": F, "L": L, "R": R, "target": None, "legs": leg_targets, "leg_F": leg_F}
        if m["branch"]["reach"] < L + R + 0.3:
            z_new = m["PT"].Z + dz
            tgt = None
            for _ in range(2):
                R2 = abs((tgt["z"] if tgt else m["PT"].Z) - z_new)
                tgt = branch_target(m, L + R2)
                if tgt is None:
                    return None, "коротке відгалуження"
            tgt["R2"] = abs(tgt["z"] - z_new)
            if tgt["R2"] < TOL:
                tgt["R2"] = 0.0
                p["dz"] = tgt["z"] - m["PT"].Z
            if tgt["z"] < m["PT"].Z - m["offset"] + MIN_OFFSET - 1e-4 and not ignore_limit:
                return None, BELOW_LIMIT
            p["target"] = tgt
        out.append(p)
    return out, None


def _copy(doc, src, a, b):
    nid = list(DB.ElementTransformUtils.CopyElement(doc, src.Id, DB.XYZ(0, 0, 20)))[0]
    n = doc.GetElement(nid)
    n.Location.Curve = DB.Line.CreateBound(a, b)
    return n


def _small_bend(el):
    for name, val in (("Bend Radius", BEND_RADIUS), ("Tray Length", BEND_LENGTH)):
        p = el.LookupParameter(name)
        if p and not p.IsReadOnly:
            p.Set(val)


class StepError(Exception):
    pass


class _Failures(DB.IFailuresPreprocessor):
    def __init__(self):
        self.errors = []

    def PreprocessFailures(self, fa):
        bad = False
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
            else:
                self.errors.append(f.GetDescriptionText())
                bad = True
        if bad:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


def _commit(t):
    fp = _Failures()
    o = t.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(fp)
    o.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(o)
    ok = t.Commit() == DB.TransactionStatus.Committed
    return ok, fp.errors


def _step(doc, name, fn, created, angles=(None,)):
    """Run fn(angle) -> (result, ids) in its own transaction, trying each
    angle until Revit accepts the fittings. Must run inside a TransactionGroup;
    raises StepError with Revit's messages when no angle works."""
    errors = []
    for a in angles:
        t = DB.Transaction(doc, "tray " + name)
        t.Start()
        try:
            res, ids = fn(math.radians(a) if a else None)
            ok, errs = _commit(t)
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            ok, errs = False, [str(ex)]
        if ok:
            created.extend(ids)
            return res
        errors.append("%s@%s: %s" % (name, a, "; ".join(errs[:1])))
    raise StepError(errors)


def _elbows(doc, pairs, ids):
    for e1, e2, p in pairs:
        el = doc.Create.NewElbowFitting(near_conn(e1, p), near_conn(e2, p))
        _small_bend(el)
        ids.append(el.Id)


def _leg(doc, leg, PT, dist, dz, Z, created):
    s, d, far = leg["seg"], leg["d"], leg["far"]

    def go(a):
        R = abs(dz) / math.tan(a)
        base = PT + d * (dist + R)
        top = PT + d * dist + Z
        s.Location.Curve = DB.Line.CreateBound(far, base) if leg["ff"] else DB.Line.CreateBound(base, far)
        ramp = _copy(doc, s, base, top)
        red = leg["reducer"]
        if red:
            neck = PT + d * (leg["conn"] + red["len"] + 0.1) + Z
            flat = _copy(doc, s, top, neck)
            stub = _copy(doc, s, neck, PT + Z)
            stub.get_Parameter(DB.BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM).Set(leg["w"])
            stub.get_Parameter(DB.BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM).Set(leg["h"])
        else:
            flat = _copy(doc, s, top, PT + Z)
        doc.Regenerate()
        ids = [ramp.Id, flat.Id]
        _elbows(doc, ((s, ramp, base), (ramp, flat, top)), ids)
        if red:
            tr = doc.Create.NewTransitionFitting(near_conn(stub, neck), near_conn(flat, neck))
            ids.extend([stub.Id, tr.Id])
            return stub, ids
        return flat, ids
    return _step(doc, "ramp", go, created, RAMP_ANGLES)


def _main_to(doc, leg, PT, Z, tgt, created):
    """Replace a short main leg up to its target straight: the old bends, slopes
    and reducers go, one ramp runs from the new height to the target, and a new
    reducer is placed at the new height when the tray narrows on the way."""
    d, t, F = leg["d"], tgt["seg"], tgt["F"]

    def clear(a):
        doc.Delete(List[DB.ElementId]([leg["seg"].Id] + list(tgt["between"])))
        return None, []
    _step(doc, "clear main", clear, created)
    neck = PT + d * (leg["conn"] + tgt["neck_len"] + 0.1) + Z
    start = neck if tgt["narrow"] else PT + Z
    top = PT + d * F + Z

    def go(a):
        if tgt["R2"] < TOL:
            t.Location.Curve = DB.Line.CreateBound(tgt["far"], start) if tgt["ff"] \
                else DB.Line.CreateBound(start, tgt["far"])
            piece = t
            ids = [t.Id]
        else:
            end = PT + d * (F + tgt["R2"] / math.tan(a))
            end = DB.XYZ(end.X, end.Y, tgt["z"])
            if (tgt["far"] - end).DotProduct(d) < 0.15:
                raise ValueError("target too short for the ramp")
            t.Location.Curve = DB.Line.CreateBound(tgt["far"], end) if tgt["ff"] \
                else DB.Line.CreateBound(end, tgt["far"])
            ramp = _copy(doc, t, top, end)
            piece = _copy(doc, t, start, top)
            doc.Regenerate()
            ids = [t.Id, ramp.Id, piece.Id]
            _elbows(doc, ((t, ramp, end), (ramp, piece, top)), ids)
        if not tgt["narrow"]:
            return piece, ids
        stub = _copy(doc, t, neck, PT + Z)
        stub.get_Parameter(DB.BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM).Set(leg["w"])
        stub.get_Parameter(DB.BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM).Set(leg["h"])
        doc.Regenerate()
        tr = doc.Create.NewTransitionFitting(near_conn(stub, neck), near_conn(piece, neck))
        ids.extend([stub.Id, tr.Id])
        return stub, ids
    return _step(doc, "main to target", go, created, RAMP_ANGLES)


def _branch_to(doc, m, p, Z, created):
    PT, v, tgt = m["PT"], m["v"], p["target"]
    seg = m["branch"]["seg"]
    t = tgt["seg"]

    def clear(a):
        doc.Delete(List[DB.ElementId](tgt["between"]))
        return None, []
    _step(doc, "clear branch", clear, created)
    if tgt["R2"] < 1e-3:
        def stretch(a):
            doc.Delete(seg.Id)
            start = PT + Z
            t.Location.Curve = DB.Line.CreateBound(tgt["far"], start) if tgt["ff"] \
                else DB.Line.CreateBound(start, tgt["far"])
            return t, [t.Id]
        return _step(doc, "stretch branch", stretch, created)
    top = PT + v * p["L"] + Z

    def go(a):
        end = PT + v * (p["L"] + tgt["R2"] / math.tan(a))
        end = DB.XYZ(end.X, end.Y, tgt["z"])
        if (tgt["far"] - end).DotProduct(v) < 0.3:
            raise ValueError("target too short for the ramp")
        seg.Location.Curve = DB.Line.CreateBound(PT + Z, top)
        t.Location.Curve = DB.Line.CreateBound(tgt["far"], end) if tgt["ff"] \
            else DB.Line.CreateBound(end, tgt["far"])
        ramp = _copy(doc, seg, top, end)
        doc.Regenerate()
        ids = [ramp.Id, seg.Id, t.Id]
        _elbows(doc, ((seg, ramp, top), (ramp, t, end)), ids)
        return seg, ids
    return _step(doc, "branch ramp", go, created, RAMP_ANGLES)


def _to_workset(doc, ids):
    if not doc.IsWorkshared:
        return
    ws = [w for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)
          if w.Name == WORKSET]
    if not ws:
        raise StepError(["workset %s not found" % WORKSET])
    for i in ids:
        e = doc.GetElement(i)
        if e is None or e.WorksetId == ws[0].Id:
            continue
        p = e.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
        if p and not p.IsReadOnly:
            p.Set(ws[0].Id.IntegerValue)


def _heal(doc, ids):
    """Pull segment ends onto fitting connectors that a shrunk bend left apart."""
    for i in ids:
        seg = doc.GetElement(i)
        if not isinstance(seg, DB.MEPCurve):
            continue
        c = seg.Location.Curve
        ends = [c.GetEndPoint(0), c.GetEndPoint(1)]
        new = list(ends)
        for k, p in enumerate(ends):
            sc = near_conn(seg, p)
            for r in sc.AllRefs:
                if r.Owner.Id != seg.Id and sc.Origin.DistanceTo(r.Origin) > GAP:
                    new[k] = p + (r.Origin - sc.Origin)
        if any(a.DistanceTo(b) > 1e-9 for a, b in zip(ends, new)):
            seg.Location.Curve = DB.Line.CreateBound(new[0], new[1])


def gaps(doc, ids):
    """Connected pairs among `ids` whose connectors are apart: [a, b, mm]."""
    out = []
    for i in ids:
        e = doc.GetElement(i)
        if e is None:
            continue
        for c in conns(e):
            for r in c.AllRefs:
                d = c.Origin.DistanceTo(r.Origin)
                if r.Owner.Id != e.Id and d > GAP:
                    out.append([e.Id.IntegerValue, r.Owner.Id.IntegerValue, round(d / MM, 1)])
    return out


def build(doc, ms, pl):
    """Rebuild the moved members, one transaction per step, then move all new
    pieces to EL and close gaps. Call inside a TransactionGroup; raises
    StepError when Revit refuses a step."""
    created = []
    for m, p in zip(ms, pl):
        if p is None:
            continue
        PT = m["PT"]
        Z = DB.XYZ(0, 0, p["dz"])
        gone = List[DB.ElementId]([m["tee"].Id] + [l["reducer"]["el"].Id for l in m["mains"] if l["reducer"]])
        _step(doc, "delete tee", lambda a: (doc.Delete(gone), []), created)
        flats = [_main_to(doc, l, PT, Z, t, created) if t
                 else _leg(doc, l, PT, f, p["dz"], Z, created)
                 for l, t, f in zip(m["mains"], p["legs"], p["leg_F"])]
        if p["target"]:
            fb = _branch_to(doc, m, p, Z, created)
        else:
            fb = _leg(doc, m["branch"], PT, p["L"], p["dz"], Z, created)

        def tee(a):
            t = doc.Create.NewTeeFitting(near_conn(flats[0], PT + Z), near_conn(flats[1], PT + Z),
                                         near_conn(fb, PT + Z))
            return t, [t.Id]
        _step(doc, "tee " + m["name"].split()[0], tee, created)
    _step(doc, "workset", lambda a: (_to_workset(doc, created), []), created)
    _step(doc, "heal gaps", lambda a: (_heal(doc, created), []), created)
    return created


def _build_safe(doc, ms, pl):
    try:
        return True, build(doc, ms, pl), []
    except StepError as ex:
        return False, [], list(ex.args[0])
    except Exception as ex:
        return False, [], [str(ex)]


def _solids(e):
    out = []
    opt = DB.Options()
    opt.DetailLevel = DB.ViewDetailLevel.Fine

    def walk(g):
        for o in g:
            if isinstance(o, DB.Solid) and o.Volume > 1e-6:
                out.append(o)
            elif isinstance(o, DB.GeometryInstance):
                walk(o.GetInstanceGeometry())
    g = e.get_Geometry(opt)
    if g:
        walk(g)
    return out


def _box_of(pts):
    return DB.Outline(DB.XYZ(min(p.X for p in pts), min(p.Y for p in pts), min(p.Z for p in pts)),
                      DB.XYZ(max(p.X for p in pts), max(p.Y for p in pts), max(p.Z for p in pts)))


def links_of(doc, titles=None):
    """Loaded links as (document, transform), only those named in `titles`
    when it is given."""
    out = []
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is not None and (titles is None or ld.Title in titles):
            out.append((ld, li.GetTotalTransform()))
    return out


def _is_opening(e):
    """True for a family instance that marks an opening or sleeve, by the name
    of its family or type."""
    if not isinstance(e, DB.FamilyInstance):
        return False
    try:
        name = (e.Symbol.Family.Name + u" " + e.Symbol.get_Parameter(
            DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()).lower()
    except Exception:
        return False
    return any(w in name for w in OPENING_WORDS)


def _openings(doc, corners):
    """Boxes (min, max in host coordinates) of opening families near a junction,
    from the host and every loaded link, whichever links are clash-tested.
    Boxes larger than MAX_OPENING are shaft-like artefacts and are left out."""
    out = []
    for d, T in [(doc, DB.Transform.Identity)] + links_of(doc):
        inv = T.Inverse
        col = DB.FilteredElementCollector(d).OfClass(DB.FamilyInstance) \
            .WherePasses(DB.BoundingBoxIntersectsFilter(_box_of([inv.OfPoint(p) for p in corners])))
        for e in col:
            if not _is_opening(e):
                continue
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            box = _box_of([T.OfPoint(bb.Min), T.OfPoint(bb.Max)])
            size = box.MaximumPoint - box.MinimumPoint
            if max(size.X, size.Y, size.Z) <= MAX_OPENING:
                out.append((box.MinimumPoint, box.MaximumPoint))
    return out


class Obstacles(object):
    """Elements around one junction, collected once so that every clash test
    only looks at these. Sources: the host model and the given links; trays of
    DUP_TRAY_LINKS and opening families are left out. Parts of long trays outside
    the zone are not tested against anything. Concrete crossed only inside an
    opening family's box is not a clash, nor is a wall the trays' old route
    already crossed (`crossed`); `excused` records those elements. `boxes` are
    the host-coordinate boxes of all structure in the zone."""

    def __init__(self, doc, points, links):
        cats = DB.ElementMulticategoryFilter(List[B](HARD + SOFT))
        lo = _box_of(points)
        a, b = lo.MinimumPoint, lo.MaximumPoint
        pts = [DB.XYZ(x, y, z) for x in (a.X - ZONE_XY, b.X + ZONE_XY)
               for y in (a.Y - ZONE_XY, b.Y + ZONE_XY) for z in (a.Z - ZONE_Z, b.Z + ZONE_Z)]

        def near(d, corners, skip_trays):
            col = DB.FilteredElementCollector(d).WherePasses(cats).WhereElementIsNotElementType() \
                .WherePasses(DB.BoundingBoxIntersectsFilter(_box_of(corners)))
            return [e.Id for e in col if e.Category is not None and not _is_opening(e) and
                    not (skip_trays and e.Category.Id.IntegerValue in TRAY_IDS)]

        self.host = near(doc, pts, False)
        self.openings = _openings(doc, pts)
        self.excused = set()
        self.crossed = set()
        self.boxes = []
        self.links = []

        def add_boxes(d, ids, T):
            for i in ids:
                e = d.GetElement(i)
                if e.Category.Id.IntegerValue in HARD_IDS:
                    bb = e.get_BoundingBox(None)
                    if bb is not None:
                        box = _box_of([T.OfPoint(bb.Min), T.OfPoint(bb.Max)])
                        self.boxes.append((box.MinimumPoint, box.MaximumPoint))

        add_boxes(doc, self.host, DB.Transform.Identity)
        for ld, T in links:
            inv = T.Inverse
            ids = near(ld, [inv.OfPoint(p) for p in pts], ld.Title in DUP_TRAY_LINKS)
            if ids:
                self.links.append((ld, inv, List[DB.ElementId](ids), T))
                add_boxes(ld, ids, T)

    def note_old_route(self, doc, ms):
        """Record the walls that the members' current trays already cross."""
        chain = set()
        for m in ms:
            chain |= _chain_ids(m)
        solids = []
        for i in chain:
            e = doc.GetElement(DB.ElementId(i))
            if e is not None:
                solids.extend(_solids(e))
        self.clashes(doc, solids, chain, collect_walls=True)

    def _inside_openings(self, solid, element, T):
        """True when every part of `solid` inside `element` lies within one
        opening box. `solid` and `element` share a document; T maps it to host."""
        if not self.openings:
            return False
        try:
            found = False
            for es in _solids(element):
                part = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                    solid, es, DB.BooleanOperationsType.Intersect)
                if part is None or part.Volume < 1e-6:
                    continue
                found = True
                bb = part.GetBoundingBox()
                pts = [T.OfPoint(bb.Transform.OfPoint(DB.XYZ(x, y, z))) for x in (bb.Min.X, bb.Max.X)
                       for y in (bb.Min.Y, bb.Max.Y) for z in (bb.Min.Z, bb.Max.Z)]
                if not any(all(a.X - OPENING_TOL <= p.X <= b.X + OPENING_TOL and
                               a.Y - OPENING_TOL <= p.Y <= b.Y + OPENING_TOL and
                               a.Z - OPENING_TOL <= p.Z <= b.Z + OPENING_TOL for p in pts)
                           for a, b in self.openings):
                    return False
            return found
        except Exception:
            return False

    def clashes(self, doc, solids, excl, collect_walls=False):
        """(hard, soft) lists of [source, id, category] for the given solids;
        `excl` holds host ids (integers) to ignore. With collect_walls the walls
        hit are only added to `crossed`."""
        host = [i for i in self.host if i.IntegerValue not in excl and doc.GetElement(i) is not None]
        host_ids = List[DB.ElementId](host)
        hard, soft, seen = [], [], set()

        def add(src, e, solid, T):
            key = (src, e.Id.IntegerValue)
            if key in seen:
                return
            is_hard = e.Category.Id.IntegerValue in HARD_IDS
            if collect_walls:
                if e.Category.Id.IntegerValue == int(B.OST_Walls):
                    self.crossed.add(key)
                return
            if is_hard and (key in self.crossed or self._inside_openings(solid, e, T)):
                self.excused.add((src, e.Id.IntegerValue, e.Category.Name))
                return
            seen.add(key)
            rec = [src, e.Id.IntegerValue, e.Category.Name]
            (hard if is_hard else soft).append(rec)

        for s in solids:
            if host:
                for h in DB.FilteredElementCollector(doc, host_ids).WherePasses(DB.ElementIntersectsSolidFilter(s)):
                    add("host", h, s, DB.Transform.Identity)
            for ld, inv, ids, T in self.links:
                sl = DB.SolidUtils.CreateTransformed(s, inv)
                for h in DB.FilteredElementCollector(ld, ids).WherePasses(DB.ElementIntersectsSolidFilter(sl)):
                    add(ld.Title, h, sl, T)
        return hard, soft


def check(doc, created, own, obstacles):
    """Clashes of the built pieces: (hard, soft)."""
    excl = set(i.IntegerValue for i in own)
    excl.update(i.IntegerValue for i in created)
    solids = []
    for eid in created:
        e = doc.GetElement(eid)
        if e is not None:
            solids.extend(_solids(e))
    return obstacles.clashes(doc, solids, excl)


def _cuboid(a, d, length, w, zc, h):
    n = DB.XYZ(-d.Y, d.X, 0)
    base = DB.XYZ(a.X, a.Y, zc - h / 2)
    p = [base - n * (w / 2), base - n * (w / 2) + d * length,
         base + n * (w / 2) + d * length, base + n * (w / 2)]
    loop = DB.CurveLoop()
    for k in range(4):
        loop.Append(DB.Line.CreateBound(p[k], p[(k + 1) % 4]))
    return DB.GeometryCreationUtilities.CreateExtrusionGeometry(
        List[DB.CurveLoop]([loop]), DB.XYZ.BasisZ, h)


def _chain_ids(m):
    """Ids along a member's branch and mains past its tee, which a rebuild may
    replace."""
    out = set()
    for leg in m["mains"] + [m["branch"]]:
        prev, cur = m["tee"].Id, leg["seg"]
        if leg["reducer"]:
            out.add(leg["reducer"]["el"].Id.IntegerValue)
            prev = leg["reducer"]["el"].Id
        for _ in range(10):
            out.add(cur.Id.IntegerValue)
            nxt = _others(cur, prev)
            if len(nxt) != 1:
                break
            prev, cur = cur.Id, nxt[0]
    return out


def _screen(doc, ms, pl, own, obstacles, cache):
    """Estimate a scheme's clashes without building it: boxes where each moved
    main and branch will run at its new height. Results are cached per member,
    height and box size, since schemes share them. Ramps are not covered."""
    hard, soft, seen = [], [], set()
    for i, (m, p) in enumerate(zip(ms, pl)):
        if p is None:
            continue
        key = (i, round(p["dz"], 3), round(p["F"], 3), round(p["L"], 3))
        if key not in cache:
            zc = m["PT"].Z + p["dz"]
            solids = [_cuboid(m["PT"] - m["u"] * p["F"], m["u"], 2 * p["F"], m["W"], zc, m["H"]),
                      _cuboid(m["PT"], m["v"], p["L"], m["Wb"], zc, m["H"])]
            excl = set(x.IntegerValue for x in own) | _chain_ids(m)
            cache[key] = obstacles.clashes(doc, solids, excl)
        for target, recs in zip((hard, soft), cache[key]):
            for r in recs:
                if (r[0], r[1]) not in seen:
                    seen.add((r[0], r[1]))
                    target.append(r)
    return hard, soft


def grids_of(doc):
    out = []
    for g in DB.FilteredElementCollector(doc).OfClass(DB.Grid):
        c = g.Curve
        if isinstance(c, DB.Line):
            d = c.Direction
            if d.X < -1e-6 or (abs(d.X) <= 1e-6 and d.Y < 0):
                d = d.Negate()
            out.append((g.Name, c.GetEndPoint(0), d))
    return out


def bay(grids, p):
    """Grid bay of a point, e.g. 'J-K / 8-9'."""
    groups = {}
    for name, o, d in grids:
        ang = round(math.degrees(math.atan2(d.Y, d.X)) % 180) % 180
        groups.setdefault(ang, []).append((name, o, d))
    parts = []
    for ang in sorted(groups):
        below, above = None, None
        for name, o, d in groups[ang]:
            n = DB.XYZ(-d.Y, d.X, 0)
            s = (p - o).DotProduct(n)
            if s <= 0 and (below is None or s > below[0]):
                below = (s, name)
            if s > 0 and (above is None or s < above[0]):
                above = (s, name)
        parts.append("%s-%s" % (below[1] if below else "?", above[1] if above else "?"))
    return " / ".join(parts)


def describe(doc, g, grids):
    m = g[0]
    return {"tees": [t["id"] for t in g], "trays": [t["name"] for t in g],
            "level": doc.GetElement(m["level"]).Name,
            "offset_mm": round(m["offset"] / MM), "bay": bay(grids, m["PT"]),
            "xyz": [round(m["PT"].X, 2), round(m["PT"].Y, 2), round(m["PT"].Z, 2)]}


def junctions_for(doc, ids):
    """Junctions touching the given element ids (tees, or trays next to a tee)."""
    want = set(ids)
    for i in ids:
        e = doc.GetElement(DB.ElementId(i))
        if isinstance(e, DB.MEPCurve):
            for c in conns(e):
                for r in c.AllRefs:
                    want.add(r.Owner.Id.IntegerValue)
    _, groups = detect(doc)
    return [g for g in groups if set(t["id"] for t in g) & want]


def _members(doc, g):
    return [tee_info(doc, doc.GetElement(DB.ElementId(t["id"]))) for t in g]


def overridable(opt):
    """True when an option breaks only the rules a user may knowingly override:
    going below MIN_OFFSET or hitting structure. A clash with a tray of the same
    junction or a plan that cannot be built is not overridable."""
    if opt["status"] in ("fail", "skip") or opt.get("inner"):
        return False
    return bool(opt.get("low")) or opt["status"] == "hard"


def _own_ids(ms):
    own = []
    for m in ms:
        own.append(m["tee"].Id)
        own.extend(l["seg"].Id for l in m["mains"] + [m["branch"]])
        own.extend(l["reducer"]["el"].Id for l in m["mains"] if l["reducer"])
    return own


def verify(doc, g, opt, obstacles):
    """Build one option inside a rolled-back group and test the real geometry;
    the model is left unchanged. Updates opt in place: status 'ok', 'soft',
    'hard' or 'fail', with why, hard, soft, errors."""
    ms = _members(doc, g)
    pl, why = plan(ms, opt["scheme"], obstacles, opt.get("low", False))
    if pl is None:
        opt.update(status="skip", why=why, hard=[], soft=[])
        return opt
    moved = [m for m, p in zip(ms, pl) if p is not None]
    still = set()
    for m, p in zip(ms, pl):
        if p is None:
            still |= _chain_ids(m)
            still.add(m["tee"].Id.IntegerValue)
    own = _own_ids(moved)
    tg = DB.TransactionGroup(doc, "eval tray tiers")
    tg.Start()
    ok, created, errors = _build_safe(doc, ms, pl)
    hard, soft = check(doc, created, own, obstacles) if ok else ([], [])
    tg.RollBack()
    inner = [r for r in soft if r[0] == "host" and r[1] in still]
    soft = [r for r in soft if r not in inner]
    opt.update(hard=hard + inner, soft=soft, errors=errors[-3:], why=None, inner=bool(inner))
    if not ok:
        opt.update(status="fail", why="фітинги не стають")
    elif inner:
        opt.update(status="hard", why="перетин з лотком цього вузла")
    elif hard:
        opt.update(status="hard", why="бетон")
    else:
        opt["status"] = "soft" if soft else "ok"
    return opt


def evaluate(doc, g, links, progress=None, max_builds=MAX_BUILDS, stop_on_clean=True):
    """Rank the tier schemes of a junction with a box estimate, then build the
    most promising ones to test them for real, stopping at the first clean one,
    or after max_builds once a usable one exists; max_builds=0 builds nothing.
    The model is left unchanged. Returns (options,
    obstacles). Option: {scheme, label, status, why, hard, soft, errors, low};
    status 'ok' or 'soft' = tested, 'est' = estimate only (call verify before
    using it), 'hard' = hits structure, 'fail', 'skip' = cannot be built. `low`
    marks a plan below MIN_OFFSET, which is never auto-built; `low` and structure
    hits are the rule breaks a user may still choose (`overridable`).
    `progress(i, n)` returning False stops the builds early."""
    ms = _members(doc, g)
    if any(m is None for m in ms):
        return [], None
    obstacles = Obstacles(doc, [m["PT"] for m in ms], links)
    obstacles.note_old_route(doc, ms)
    own = _own_ids(ms)
    cache = {}
    opts = []
    for scheme in schemes_for(ms):
        opt = {"scheme": scheme, "label": label(ms, scheme), "hard": [], "soft": [],
               "errors": [], "why": None}
        pl, why = plan(ms, scheme, obstacles)
        if why == BELOW_LIMIT:
            pl, why = plan(ms, scheme, obstacles, True)
            opt["low"] = pl is not None
        if pl is None:
            opt.update(status="skip", why=why)
        else:
            opt["hard"], opt["soft"] = _screen(doc, ms, pl, own, obstacles, cache)
            if opt["hard"]:
                opt.update(status="hard", why="бетон (за попередньою оцінкою)")
            else:
                opt["status"] = "est"
        opts.append(opt)
    todo = sorted([o for o in opts if o["status"] == "est" and not o.get("low")],
                  key=lambda o: len(o["soft"])) if max_builds else []
    for n, opt in enumerate(todo):
        if n >= max_builds and any(o["status"] in ("ok", "soft") for o in opts):
            break
        if progress and progress(n, len(todo)) is False:
            break
        verify(doc, g, opt, obstacles)
        if stop_on_clean and opt["status"] == "ok":
            break
    return opts, obstacles


def _preview_view(doc, created, keep):
    """Temporary isometric view framed on the rebuilt pieces, with them coloured.
    Must run inside a transaction."""
    vft = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
           if t.ViewFamily == DB.ViewFamily.ThreeDimensional][0]
    v = DB.View3D.CreateIsometric(doc, vft.Id)
    v.ViewTemplateId = DB.ElementId.InvalidElementId
    v.DetailLevel = DB.ViewDetailLevel.Fine
    v.DisplayStyle = DB.DisplayStyle.ShadingWithEdges
    v.AreImportCategoriesHidden = True
    pts = []
    for e in [doc.GetElement(i) for i in list(created) + list(keep)]:
        bb = e.get_BoundingBox(None) if e is not None else None
        if bb is not None and bb.Max.DistanceTo(bb.Min) < 12:
            pts.extend([bb.Min, bb.Max])
    box = _box_of(pts)
    a, b = box.MinimumPoint, box.MaximumPoint
    sb = DB.BoundingBoxXYZ()
    sb.Min = DB.XYZ(a.X - 1.5, a.Y - 1.5, a.Z - 1)
    sb.Max = DB.XYZ(b.X + 1.5, b.Y + 1.5, b.Z + 1.5)
    v.SetSectionBox(sb)
    fill = [f for f in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement)
            if f.GetFillPattern().IsSolidFill]
    ogs = DB.OverrideGraphicSettings()
    orange = DB.Color(240, 130, 30)
    ogs.SetSurfaceForegroundPatternColor(orange)
    if fill:
        ogs.SetSurfaceForegroundPatternId(fill[0].Id)
    for i in created:
        if doc.GetElement(i) is not None:
            v.SetElementOverrides(i, ogs)
    return v


def preview_image(doc, g, scheme, obstacles, folder, ignore_limit=False):
    """Build a scheme temporarily, export an isometric PNG of the node into
    `folder`, roll everything back; the model is left unchanged. New pieces are
    orange. Returns (path, errors)."""
    import os
    ms = _members(doc, g)
    pl, why = plan(ms, scheme, obstacles, ignore_limit)
    if pl is None:
        return None, [why]
    keep = []
    for m in ms:
        keep.append(m["tee"].Id)
    tg = DB.TransactionGroup(doc, "tray preview")
    tg.Start()
    try:
        ok, created, errors = _build_safe(doc, ms, pl)
        if not ok:
            return None, errors[-3:]
        created = [i for i in created if doc.GetElement(i) is not None]
        holder = {}

        def make(a):
            holder["view"] = _preview_view(doc, created, [k for k in keep if doc.GetElement(k) is not None])
            return None, []
        _step(doc, "preview view", make, [])
        before = set(os.listdir(folder))
        opts = DB.ImageExportOptions()
        opts.ExportRange = DB.ExportRange.SetOfViews
        opts.SetViewsAndSheets(List[DB.ElementId]([holder["view"].Id]))
        opts.FilePath = os.path.join(folder, "tee")
        opts.HLRandWFViewsFileType = DB.ImageFileType.PNG
        opts.ShadowViewsFileType = DB.ImageFileType.PNG
        opts.ImageResolution = DB.ImageResolution.DPI_150
        opts.PixelSize = 1000
        opts.FitDirection = DB.FitDirectionType.Horizontal
        opts.ZoomType = DB.ZoomFitType.FitToPage
        doc.ExportImage(opts)
        new = [n for n in os.listdir(folder) if n not in before and n.lower().endswith(".png")]
        if not new:
            return None, ["Revit не створив зображення"]
        return os.path.join(folder, new[0]), []
    except StepError as ex:
        return None, list(ex.args[0])[-3:]
    except Exception as ex:
        return None, [str(ex)]
    finally:
        tg.RollBack()


def apply_scheme(doc, g, scheme, obstacles=None, ignore_limit=False):
    """Build one scheme for real as a single undo step 'Split tray tee by
    elevation'. Pass the `obstacles` it was verified with, so the same ramps get
    built. Returns {applied, created, errors, gaps_mm}."""
    ms = _members(doc, g)
    if any(m is None for m in ms):
        return {"applied": False, "errors": ["вузол змінився, запустіть ще раз"]}
    pl, why = plan(ms, scheme, obstacles, ignore_limit)
    if pl is None:
        return {"applied": False, "errors": [why]}
    tg = DB.TransactionGroup(doc, "Split tray tee by elevation")
    tg.Start()
    ok, created, errors = _build_safe(doc, ms, pl)
    if not ok:
        tg.RollBack()
        return {"applied": False, "errors": errors[-3:]}
    tg.Assimilate()
    alive = [i for i in created if doc.GetElement(i) is not None]
    return {"applied": True, "created": [i.IntegerValue for i in alive],
            "gaps_mm": gaps(doc, alive), "errors": []}


def run(doc, inputs):
    """Agent entry: inputs {mode: detect|plan|apply, only: [tee ids],
    force: label, links: [titles], default DEFAULT_LINKS}."""
    tees, groups = detect(doc)
    grids = grids_of(doc)
    only = inputs.get("only")
    if only:
        groups = [g for g in groups if set(t["id"] for t in g) & set(only)]
    report = []
    mode = inputs.get("mode")
    links = links_of(doc, inputs.get("links", DEFAULT_LINKS)) if mode != "detect" else []
    for g in groups:
        r = describe(doc, g, grids)
        if mode != "detect":
            force = inputs.get("force")
            opts, obstacles = evaluate(doc, g, links, max_builds=0 if force else MAX_BUILDS)
            if force:
                opts = [o for o in opts if o["label"] == force]
                for o in opts:
                    verify(doc, g, o, obstacles)
            usable = [o for o in opts if o["status"] in ("ok", "soft") and (force or not o.get("low"))]
            r["tried"] = [dict((k, v) for k, v in o.items() if k != "scheme") for o in opts]
            if usable:
                best = sorted(usable, key=lambda o: len(o["soft"]))[0]
                r["scheme"] = best["label"]
                r["status"] = "ok" if best["status"] == "ok" else "review"
                if mode == "apply":
                    res = apply_scheme(doc, g, best["scheme"], obstacles, best.get("low", False))
                    r.update(res)
                    if res.get("gaps_mm"):
                        r["status"] = "review"
            else:
                r["status"] = "manual"
        report.append(r)
    return {"tees_total": len(tees), "junctions": len(groups), "report": report}
