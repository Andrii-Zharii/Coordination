# -*- coding: utf-8 -*-
"""MEP of one floor, as section placement sees it.

Segment  one straight horizontal pipe / duct / cable tray / conduit of the floor.
Run      main segments of one network that continue each other in a straight line
         at the same height (through couplings, tees, transitions): what a cross
         section shows as one pipe or tray.
Event    a height change: a run ends and the same network goes on at another height
         nearby (drop, rise, offset).
"""
import math

from Autodesk.Revit import DB

from coordination import mep
from coordination.units import mm_to_ft

HORIZONTAL_MAX_SLOPE = math.tan(math.radians(10))
PARALLEL_SIN = math.sin(math.radians(3))


def _p2(point):
    return (point.X, point.Y)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def next_level_elevation(doc, level):
    """Elevation of the next level above (at least 1 m higher), or None."""
    best = None
    for other in DB.FilteredElementCollector(doc).OfClass(DB.Level):
        z = other.ProjectElevation
        if z > level.ProjectElevation + mm_to_ft(1000) and (best is None or z < best):
            best = z
    return best


def floor_band(doc, level, settings):
    """(level z, next level z) in feet."""
    z0 = level.ProjectElevation
    z1 = next_level_elevation(doc, level)
    if z1 is None:
        z1 = z0 + mm_to_ft(4000)
    return z0, z1


def _double(element, bip):
    param = element.get_Parameter(bip)
    if param is not None and param.HasValue:
        return param.AsDouble()
    return None


def cross_size(element):
    """(width, height) of the cross section in feet."""
    name = mep.category_name(element)
    width = height = None
    if name == "Pipes":
        width = height = _double(element, DB.BuiltInParameter.RBS_PIPE_OUTER_DIAMETER)
    elif name == "Ducts":
        width = _double(element, DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
        height = _double(element, DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
        if not width:
            width = height = _double(element, DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
    elif name == "Cable Trays":
        width = _double(element, DB.BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM)
        height = _double(element, DB.BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM)
    elif name == "Conduits":
        width = height = (_double(element, DB.BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM)
                          or _double(element, DB.BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM))
    if not width or not height:
        bbox = element.get_BoundingBox(None)
        size = 0.0
        if bbox is not None:
            size = bbox.Max.Z - bbox.Min.Z
        width = width or size
        height = height or size
    return width, height


class Segment(object):
    def __init__(self, element, p, q, key, kind, width, height, main):
        self.element = element
        self.id = mep.element_id_value(element.Id)
        self.p = p
        self.q = q
        dx = q.X - p.X
        dy = q.Y - p.Y
        self.length = math.hypot(dx, dy)
        self.u = (dx / self.length, dy / self.length)
        self.key = key
        self.kind = kind
        self.width = width
        self.height = height
        self.size = max(width, height)
        self.main = main
        self.z = (p.Z + q.Z) / 2.0
        self.mid = ((p.X + q.X) / 2.0, (p.Y + q.Y) / 2.0)


def _kind(element, category, system, settings):
    if category == "Cable Trays":
        return "tray"
    if category == "Conduits":
        return "conduit"
    if category == "Ducts":
        return "duct"
    if mep.is_gravity_pipe(element, settings["gravity"]):
        return "gravity"
    lowered = system.lower()
    for keyword in settings["sections"]["sprinkler_keywords"]:
        if keyword.lower() in lowered:
            return "sprinkler"
    return "pipe"


def _is_main(kind, width, height, cfg):
    size_mm = max(width, height) * 304.8
    if kind == "tray":
        return bool(cfg.get("cable_trays", True))
    if kind == "conduit":
        return bool(cfg.get("conduits", False))
    if kind == "duct":
        return size_mm >= cfg["duct_min_size_mm"] - 1
    if kind == "sprinkler":
        return size_mm >= cfg["sprinkler_min_od_mm"] - 1
    return size_mm >= cfg["pipe_min_od_mm"] - 1


def collect_segments(doc, level, settings):
    """All horizontal MEP segments of the floor (main and small), -DC worksets left out."""
    cfg = settings["sections"]
    z0, z1 = floor_band(doc, level, settings)
    zlo = z0 - mm_to_ft(cfg["below_level_mm"])
    suffix = cfg.get("exclude_workset_suffix") or ""
    table = doc.GetWorksetTable() if doc.IsWorkshared else None
    excluded = {}
    result = []
    for element in mep.collect_mep_curves(doc):
        if table is not None and suffix:
            ws_id = element.WorksetId
            key = ws_id.IntegerValue
            if key not in excluded:
                excluded[key] = table.GetWorkset(ws_id).Name.endswith(suffix)
            if excluded[key]:
                continue
        line = mep.location_line(element)
        if line is None or not isinstance(line, DB.Line):
            continue
        p = line.GetEndPoint(0)
        q = line.GetEndPoint(1)
        zm = (p.Z + q.Z) / 2.0
        if zm < zlo or zm > z1:
            continue
        flat = math.hypot(q.X - p.X, q.Y - p.Y)
        if flat < mm_to_ft(50) or abs(q.Z - p.Z) / flat > HORIZONTAL_MAX_SLOPE:
            continue
        category = mep.category_name(element)
        system = mep.system_name(element) or category
        if category in ("Cable Trays", "Conduits"):
            system = category
        kind = _kind(element, category, system, settings)
        width, height = cross_size(element)
        main = _is_main(kind, width, height, cfg["main_network"])
        result.append(Segment(element, p, q, system, kind, width, height, main))
    return result


DEPTH_CATEGORIES = [
    DB.BuiltInCategory.OST_PipeCurves, DB.BuiltInCategory.OST_DuctCurves,
    DB.BuiltInCategory.OST_CableTray, DB.BuiltInCategory.OST_Conduit,
    DB.BuiltInCategory.OST_FlexPipeCurves, DB.BuiltInCategory.OST_FlexDuctCurves,
    DB.BuiltInCategory.OST_PipeFitting, DB.BuiltInCategory.OST_DuctFitting,
    DB.BuiltInCategory.OST_CableTrayFitting, DB.BuiltInCategory.OST_ConduitFitting,
    DB.BuiltInCategory.OST_PipeAccessory, DB.BuiltInCategory.OST_DuctAccessory,
    DB.BuiltInCategory.OST_Sprinklers, DB.BuiltInCategory.OST_DuctTerminal,
    DB.BuiltInCategory.OST_MechanicalEquipment, DB.BuiltInCategory.OST_PlumbingFixtures,
]


class DepthItem(object):
    """Any MEP element of the floor, for the far clip: plan points, radius, z range."""

    def __init__(self, points, radius, zmin, zmax, element_id):
        self.points = points
        self.radius = radius
        self.zmin = zmin
        self.zmax = zmax
        self.id = element_id


def collect_depth_items(doc, level, settings):
    """Every MEP element of the floor (pipes, risers, fittings, accessories, sprinklers,
    terminals, equipment), -DC worksets left out. A section's far clip stops before the
    first of them in front of the cut that the cut itself does not go through."""
    cfg = settings["sections"]
    z0, z1 = floor_band(doc, level, settings)
    zlo = z0 - mm_to_ft(cfg["below_level_mm"])
    zhi = z1 + mm_to_ft(1000)
    suffix = cfg.get("exclude_workset_suffix") or ""
    table = doc.GetWorksetTable() if doc.IsWorkshared else None
    excluded = {}
    items = []
    for bic in DEPTH_CATEGORIES:
        collector = DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()
        for element in collector:
            if table is not None and suffix:
                key = element.WorksetId.IntegerValue
                if key not in excluded:
                    excluded[key] = table.GetWorkset(element.WorksetId).Name.endswith(suffix)
                if excluded[key]:
                    continue
            bbox = element.get_BoundingBox(None)
            if bbox is None or bbox.Max.Z < zlo or bbox.Min.Z > zhi:
                continue
            eid = mep.element_id_value(element.Id)
            line = None
            if isinstance(element, DB.MEPCurve):
                line = mep.location_line(element)
            if isinstance(line, DB.Line):
                p, q = line.GetEndPoint(0), line.GetEndPoint(1)
                width, height = cross_size(element)
                r = max(width, height) / 2.0
                items.append(DepthItem([(p.X, p.Y), (q.X, q.Y)], r,
                                       min(p.Z, q.Z) - r, max(p.Z, q.Z) + r, eid))
            else:
                corners = [(bbox.Min.X, bbox.Min.Y), (bbox.Max.X, bbox.Min.Y),
                           (bbox.Max.X, bbox.Max.Y), (bbox.Min.X, bbox.Max.Y)]
                items.append(DepthItem(corners, 0.0, bbox.Min.Z, bbox.Max.Z, eid))
    return items


class Run(object):
    def __init__(self, index, segments):
        self.index = index
        self.segments = segments
        longest = max(segments, key=lambda s: s.length)
        u = longest.u
        if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):
            u = (-u[0], -u[1])
        self.u = u
        self.key = longest.key
        self.kind = longest.kind
        self.size = max(s.size for s in segments)
        self.width = max(s.width for s in segments)
        ends = []
        for s in segments:
            ends.append((dot(_p2(s.p), u), s.p))
            ends.append((dot(_p2(s.q), u), s.q))
        ends.sort(key=lambda e: e[0])
        self.s0, self.end0 = ends[0]
        self.s1, self.end1 = ends[-1]
        self.length = self.s1 - self.s0
        self.joints = sorted(e[0] for e in ends)
        self.mid = ((self.end0.X + self.end1.X) / 2.0, (self.end0.Y + self.end1.Y) / 2.0)
        self.z = sum(s.z * s.length for s in segments) / sum(s.length for s in segments)
        self.ids = [s.id for s in segments]

    def label(self):
        return u"{} {:.0f} ({:.0f} m)".format(self.key, self.size * 304.8, self.length * 0.3048)

    def point_at(self, s):
        """Point on the run's centre line at along-run coordinate s (XYZ), or None in a gap."""
        for seg in self.segments:
            a = dot(_p2(seg.p), self.u)
            b = dot(_p2(seg.q), self.u)
            if min(a, b) - 1e-6 <= s <= max(a, b) + 1e-6 and abs(b - a) > 1e-9:
                lam = (s - a) / (b - a)
                return seg.p + (seg.q - seg.p) * lam
        return None


class _UnionFind(object):
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _continues(a, b):
    """True if segment b continues segment a in a straight line at the same height."""
    if abs(cross(a.u, b.u)) > PARALLEL_SIN:
        return False
    normal = (-a.u[1], a.u[0])
    base = _p2(a.p)
    for point in (b.p, b.q):
        if abs(dot((point.X - base[0], point.Y - base[1]), normal)) > mm_to_ft(60):
            return False
    sa = sorted([(dot(_p2(a.p), a.u), a.p), (dot(_p2(a.q), a.u), a.q)], key=lambda e: e[0])
    sb = sorted([(dot(_p2(b.p), a.u), b.p), (dot(_p2(b.q), a.u), b.q)], key=lambda e: e[0])
    if sb[0][0] >= sa[1][0]:
        gap, za, zb = sb[0][0] - sa[1][0], sa[1][1].Z, sb[0][1].Z
    elif sa[0][0] >= sb[1][0]:
        gap, za, zb = sa[0][0] - sb[1][0], sa[0][1].Z, sb[1][1].Z
    else:
        gap, za, zb = 0.0, a.z, b.z
    if gap > mm_to_ft(1000):
        return False
    return abs(za - zb) <= mm_to_ft(40)


def build_runs(segments, settings):
    """Main segments joined into straight runs; runs shorter than min_run_length_mm are dropped."""
    main = [s for s in segments if s.main]
    buckets = {}
    for i, seg in enumerate(main):
        angle = math.degrees(math.atan2(seg.u[1], seg.u[0])) % 180.0
        buckets.setdefault((seg.key, int(angle // 3) % 60), []).append(i)
    uf = _UnionFind(len(main))
    for (key, abin), items in buckets.items():
        next_bin = buckets.get((key, (abin + 1) % 60), [])
        for ii, i in enumerate(items):
            for j in items[ii + 1:] + next_bin:
                if _continues(main[i], main[j]):
                    uf.union(i, j)
    groups = {}
    for i in range(len(main)):
        groups.setdefault(uf.find(i), []).append(main[i])
    min_len = mm_to_ft(settings["sections"]["main_network"]["min_run_length_mm"])
    runs = []
    for segs in groups.values():
        run = Run(len(runs), segs)
        if run.length >= min_len:
            runs.append(run)
    return runs


class Event(object):
    """Height change between the end of run_a and the end of run_b."""

    def __init__(self, index, run_a, s_a, run_b, s_b, dz, point):
        self.index = index
        self.run_a = run_a
        self.s_a = s_a
        self.run_b = run_b
        self.s_b = s_b
        self.dz = dz
        self.point = point

    def label(self):
        return u"height change {} {:.0f}: {:+.0f} mm".format(
            self.run_a.key, self.run_a.size * 304.8, self.dz * 304.8)


def _connectors(element):
    manager = None
    if isinstance(element, DB.MEPCurve):
        manager = element.ConnectorManager
    elif isinstance(element, DB.FamilyInstance) and element.MEPModel is not None:
        manager = element.MEPModel.ConnectorManager
    if manager is None:
        return []
    return [c for c in manager.Connectors
            if int(c.ConnectorType) & int(DB.ConnectorType.Physical)]


def _end_segment(run, point):
    best, best_d = None, None
    for seg in run.segments:
        for end in (seg.p, seg.q):
            d = end.DistanceTo(point)
            if best_d is None or d < best_d:
                best, best_d = seg, d
    return best


def _reached_runs(run, end_point, run_of_segment, max_steps=8, max_dist=mm_to_ft(3000)):
    """Runs reached from one end of `run` through fittings, accessories and short or
    sloped pieces (connected network only). Returns {run: point where it was entered}."""
    seg = _end_segment(run, end_point)
    start = None
    for c in _connectors(seg.element):
        if start is None or c.Origin.DistanceTo(end_point) < start.Origin.DistanceTo(end_point):
            start = c
    if start is None or not start.IsConnected:
        return {}
    own = set(run.ids)
    found = {}
    visited = set(own)
    frontier = [start]
    for _ in range(max_steps):
        nxt = []
        for conn in frontier:
            for ref in conn.AllRefs:
                owner = ref.Owner
                if owner is None or isinstance(owner, DB.MEPSystem):
                    continue
                if not (int(ref.ConnectorType) & int(DB.ConnectorType.Physical)):
                    continue
                oid = mep.element_id_value(owner.Id)
                if oid in visited:
                    continue
                visited.add(oid)
                if math.hypot(ref.Origin.X - end_point.X, ref.Origin.Y - end_point.Y) > max_dist:
                    continue
                other = run_of_segment.get(oid)
                if other is not None:
                    if other is not run:
                        found.setdefault(other, ref.Origin)
                    continue
                for c in _connectors(owner):
                    if c.IsConnected and c.Origin.DistanceTo(ref.Origin) > 1e-6:
                        nxt.append(c)
        if not nxt:
            break
        frontier = nxt
    return found


def find_height_changes(runs, settings):
    """Height changes: from a run end the connected network goes on in another run of the
    same system at another height. Neighbouring changes of the same system with the same
    sign within 1.5 m (parallel trays dropping together) count as one."""
    cfg = settings["sections"]
    run_of_segment = {}
    for run in runs:
        for i in run.ids:
            run_of_segment[i] = run
    raw = []
    seen = set()
    for run in runs:
        limit = cfg["sprinkler_height_change_mm"] if run.kind == "sprinkler" else cfg["height_change_mm"]
        limit = mm_to_ft(limit)
        for s, point in ((run.s0, run.end0), (run.s1, run.end1)):
            for other, entered in _reached_runs(run, point, run_of_segment).items():
                if other.key != run.key:
                    continue
                pair = (min(run.index, other.index), max(run.index, other.index))
                if pair in seen:
                    continue
                s_other = dot(_p2(entered), other.u)
                s_other = other.s0 if abs(s_other - other.s0) < abs(s_other - other.s1) else other.s1
                other_point = other.end0 if s_other == other.s0 else other.end1
                dz = other_point.Z - point.Z
                if abs(dz) < limit:
                    continue
                seen.add(pair)
                mid = ((point.X + other_point.X) / 2.0, (point.Y + other_point.Y) / 2.0)
                raw.append((run, s, other, s_other, dz, mid))
    # merge neighbours
    events = []
    merge = mm_to_ft(1500)
    for item in sorted(raw, key=lambda r: -abs(r[4])):
        run, s, other, s_other, dz, mid = item
        twin = None
        for ev in events:
            if (ev.run_a.key == run.key and (ev.dz > 0) == (dz > 0)
                    and math.hypot(ev.point[0] - mid[0], ev.point[1] - mid[1]) <= merge):
                twin = ev
                break
        if twin is not None:
            twin.others.append((run, s, other, s_other))
            continue
        ev = Event(len(events), run, s, other, s_other, dz, mid)
        ev.others = []
        events.append(ev)
    return events
