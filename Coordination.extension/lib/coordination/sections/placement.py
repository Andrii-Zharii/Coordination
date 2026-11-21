# -*- coding: utf-8 -*-
"""Where to put the sections of a floor (vision section 4).

1. Candidates. Along every main run, every station_step_mm (and near its ends), a section
   line across the run: a cross section of the run and of everything parallel to it.
   The line always follows a model axis (grid directions and their perpendiculars), the
   one closest to the run: a pipe drawn 0.1 deg off the grid never makes a skewed section.
   Runs at up to 45 deg to the line still count as cut.
   Stations keep away from the run's fittings.
2. Extent of each line (from vertical concrete to vertical concrete): on each side the
   line goes to the first concrete wall / column / beam if it is not farther than
   max_reach_to_structure_mm from the last network before it, and ends just past it.
   Otherwise that side ends margin_no_structure_mm after the networks (bundle_gap_mm
   between networks still counts as one bundle).
3. What a candidate shows: the main runs it cuts across (each run counts once), and
   the height changes it is close to (it cuts one of the two runs within
   height_change_cover_mm of the change).
4. Choice. One by one, the candidate that adds most of what is not shown yet:
   weight of each run = class weight (gravity > ducts, trays > pressure pipes > sprinklers)
   x size x length; each height change = height_change_weight x the run's weight x size of the change.
   Multiplied by concrete_factor (concrete on both sides / one / none) and lowered for
   small pipes and fittings in the cut. A line whose plane runs lengthwise through a main
   pipe / duct / tray is never chosen (small ones lengthwise: a bigger penalty).
   Stops at count sections or when nothing is left.
"""
import math

from coordination.units import mm_to_ft
from coordination.sections.floor import dot
from coordination.sections import concrete as C


def run_weight(run, cfg):
    cls = cfg["class_weight"].get(run.kind, 1.0)
    size = max(0.6, min(2.5, math.sqrt(run.size * 304.8 / 100.0)))
    length = max(0.5, min(2.0, run.length * 0.3048 / 5.0))
    return cls * size * length


def event_weight(event, cfg):
    run = event.run_a
    cls = cfg["class_weight"].get(run.kind, 1.0)
    size = max(0.6, min(2.5, math.sqrt(run.size * 304.8 / 100.0)))
    change = max(0.5, min(2.0, abs(event.dz) * 304.8 / 300.0))
    return cfg["height_change_weight"] * cls * size * change


class Line(object):
    """A section line in plan.

    origin  point on the cut plane (on the seed run)
    look    view direction (unit, plan): the section looks this way
    along   direction of the line on the sheet, left to right (unit, plan)
    t_min / t_max   extent along `along` from origin (feet)
    """

    def __init__(self, origin, look):
        self.origin = origin
        self.look = look
        self.along = (look[1], -look[0])
        self.t_min = 0.0
        self.t_max = 0.0
        self.concrete = [None, None]   # obstacle kind/name at the left / right end
        self.cuts = []                 # (run, t, s_on_run)
        self.small_cuts = 0
        self.fitting_cuts = 0
        self.lengthwise_main = 0       # main segments the plane cuts along their length
        self.runs = set()
        self.events = set()
        self.seed = None
        self.reasons = []
        self.score = 0.0

    @property
    def concrete_sides(self):
        return len([c for c in self.concrete if c])

    def point(self, t):
        return (self.origin[0] + self.along[0] * t, self.origin[1] + self.along[1] * t)


def model_axes(doc, plan_up):
    """Directions sections may have: the directions of the straight grids and the
    perpendiculars to them (angles mod 90 deg, grids within 0.5 deg are one family).
    Without grids: the plan view's up direction. Sections are never skewed to the model,
    whatever the direction of the pipe they are placed on."""
    from Autodesk.Revit import DB
    angles = []
    for grid in DB.FilteredElementCollector(doc).OfClass(DB.Grid):
        curve = grid.Curve
        if not isinstance(curve, DB.Line):
            continue
        d = curve.Direction
        angles.append(math.degrees(math.atan2(d.Y, d.X)) % 90.0)
    if not angles:
        angles = [math.degrees(math.atan2(plan_up[1], plan_up[0])) % 90.0]
    families = []
    for a in sorted(angles):
        if not any(min(abs(a - f), 90.0 - abs(a - f)) < 0.5 for f in families):
            families.append(a)
    axes = []
    for a in families:
        for k in range(4):
            r = math.radians(a + 90.0 * k)
            axes.append((math.cos(r), math.sin(r)))
    return axes


def snap_to_axes(u, axes):
    """The model axis closest to direction u."""
    return max(axes, key=lambda a: dot(a, u))


def view_direction(run_u, plan_up, plan_right, axes=None):
    """Along a model axis (the one closest to the run), looking up or right on the plan."""
    u = snap_to_axes(run_u, axes) if axes else run_u
    if abs(dot(u, plan_up)) >= abs(dot(u, plan_right)):
        ref = plan_up
    else:
        ref = plan_right
    if dot(u, ref) < 0:
        u = (-u[0], -u[1])
    return u


class StripIndex(object):
    """Objects binned by their extent along a view direction, so a section line only
    looks at what lies across its cut plane. One table per direction (few directions)."""

    BIN = mm_to_ft(1000)

    def __init__(self, objects, points_of):
        self.objects = objects
        self.points_of = points_of
        self.tables = {}

    def near(self, look, origin):
        key = (round(look[0], 3), round(look[1], 3))
        table = self.tables.get(key)
        if table is None:
            table = {}
            for obj in self.objects:
                values = [dot(p, look) for p in self.points_of(obj)]
                lo = int(math.floor(min(values) / self.BIN))
                hi = int(math.floor(max(values) / self.BIN))
                for b in range(lo, hi + 1):
                    table.setdefault(b, []).append(obj)
            self.tables[key] = table
        return table.get(int(math.floor(dot(origin, look) / self.BIN)), [])


def _run_points(run):
    pad = run.width
    pts = []
    for seg in run.segments:
        for p in (seg.p, seg.q):
            pts.extend([(p.X - pad, p.Y - pad), (p.X + pad, p.Y + pad),
                        (p.X - pad, p.Y + pad), (p.X + pad, p.Y - pad)])
    return pts


def _seg_points(seg):
    return [(seg.p.X, seg.p.Y), (seg.q.X, seg.q.Y)]


def _obstacle_points(ob):
    return ob.polygon


def _line_crossings(line, runs, max_half):
    """Main runs the infinite line crosses (runs roughly parallel to the view direction)."""
    o = line.origin
    result = []
    for run in runs:
        if abs(dot(run.u, line.along)) > 0.72:   # run within 44 deg of the line: not a cross section
            continue
        for seg in run.segments:
            ip = _intersect(o, line.along, (seg.p.X, seg.p.Y), (seg.q.X, seg.q.Y))
            if ip is None:
                continue
            t, lam = ip
            if abs(t) > max_half:
                continue
            near_end = min(lam, 1.0 - lam) * seg.length < mm_to_ft(150)
            s_on_run = dot(line.point(t), run.u)
            result.append((run, t, s_on_run, near_end, seg))
            break
    return result


def _intersect(origin, direction, a, b):
    """(t, lam) where origin + t*direction meets segment a-b at a + lam*(b-a), or None."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    den = direction[0] * ey - direction[1] * ex
    if abs(den) < 1e-12:
        return None
    wx, wy = a[0] - origin[0], a[1] - origin[1]
    t = (wx * ey - wy * ex) / den
    lam = (wx * direction[1] - wy * direction[0]) / den
    if lam < 0.0 or lam > 1.0:
        return None
    return t, lam


def _obstacle_hits(line, obstacles, max_half):
    o = line.origin
    hits = []
    for ob in obstacles:
        interval = C.line_interval(o, line.along, ob.polygon)
        if interval is None:
            continue
        if interval[0] <= 0.0 <= interval[1]:
            continue   # the seed point is inside it (pipe in a wall): ignore
        if min(abs(interval[0]), abs(interval[1])) > max_half:
            continue
        hits.append((interval, ob))
    return hits


def _side_extent(sign, crossings, hits, cfg):
    """End of the line on one side: (distance from origin, obstacle or None)."""
    reach = mm_to_ft(cfg["max_reach_to_structure_mm"])
    gap_max = mm_to_ft(cfg["bundle_gap_mm"])
    nets = sorted(abs(c[1]) for c in crossings if c[1] * sign > 0)
    structs = []
    for (a, b), ob in hits:
        if sign > 0 and a > 0:
            structs.append((a, b, ob))
        elif sign < 0 and b < 0:
            structs.append((-b, -a, ob))
    structs.sort(key=lambda s: s[0])
    limit = float("inf")
    if structs:
        near, far, ob = structs[0]
        before = [d for d in nets if d < near]
        outer = max(before) if before else 0.0
        if near - outer <= reach:
            return far + mm_to_ft(cfg["margin_past_structure_mm"]), ob
        limit = near
    outer = 0.0
    for d in nets:
        if d >= limit or d - outer > gap_max:
            break
        outer = d
    return outer + mm_to_ft(cfg["margin_no_structure_mm"]), None


class Floor(object):
    """Runs, concrete and small segments of the floor with their strip indexes."""

    def __init__(self, runs, events, obstacles, segments):
        self.runs = runs
        self.events = events
        self.obstacles = obstacles
        self.segments = segments
        self.small = [s for s in segments if not s.main]
        self.run_index = StripIndex(runs, _run_points)
        self.obstacle_index = StripIndex(obstacles, _obstacle_points)
        self.small_index = StripIndex(self.small, _seg_points)


def make_line(origin, look, fl, cfg, use_concrete=True):
    """Section line through origin looking `look`, with its extent and what it cuts."""
    line = Line(origin, look)
    max_half = mm_to_ft(cfg["max_half_length_mm"])
    crossings = _line_crossings(line, fl.run_index.near(look, origin), max_half)
    obstacles = fl.obstacle_index.near(look, origin) if use_concrete else []
    small = fl.small_index.near(look, origin)
    hits = _obstacle_hits(line, obstacles, max_half)
    right, ob_r = _side_extent(1, crossings, hits, cfg)
    left, ob_l = _side_extent(-1, crossings, hits, cfg)
    line.t_min, line.t_max = -left, right
    line.concrete = [ob_l, ob_r]
    for run, t, s_on_run, near_end, seg in crossings:
        if line.t_min <= t <= line.t_max:
            line.cuts.append((run, t, s_on_run))
            line.runs.add(run.index)
            if near_end:
                line.fitting_cuts += 1
    o = line.origin
    for run in fl.run_index.near(look, origin):
        for seg in run.segments:
            if _lengthwise(line, seg):
                line.lengthwise_main += 1
    for seg in small:
        if _lengthwise(line, seg):
            line.small_cuts += 3
            continue
        if abs(dot((seg.mid[0] - o[0], seg.mid[1] - o[1]), look)) > seg.length / 2.0 + 0.1:
            continue
        ip = _intersect(o, line.along, (seg.p.X, seg.p.Y), (seg.q.X, seg.q.Y))
        if ip is not None and line.t_min <= ip[0] <= line.t_max:
            line.small_cuts += 1
    return line


def _lengthwise(line, seg):
    """True if the cut plane runs along the segment through its body (a lengthwise cut)."""
    if abs(dot(seg.u, line.along)) < 0.7:
        return False
    o = line.origin
    rel_p = (seg.p.X - o[0], seg.p.Y - o[1])
    rel_q = (seg.q.X - o[0], seg.q.Y - o[1])
    a_p, a_q = dot(rel_p, line.look), dot(rel_q, line.look)
    half = seg.width / 2.0 + mm_to_ft(20)
    if min(a_p, a_q) > half or max(a_p, a_q) < -half:
        return False
    t_p, t_q = dot(rel_p, line.along), dot(rel_q, line.along)
    return max(t_p, t_q) > line.t_min and min(t_p, t_q) < line.t_max


def mark_events(line, events, cfg):
    cover = mm_to_ft(cfg["height_change_cover_mm"])
    by_run = {}
    for run, t, s_on_run in line.cuts:
        by_run[run.index] = s_on_run
    for ev in events:
        ends = [(ev.run_a, ev.s_a), (ev.run_b, ev.s_b)]
        for run_a, s_a, run_b, s_b in getattr(ev, "others", []):
            ends.extend([(run_a, s_a), (run_b, s_b)])
        for run, s_end in ends:
            s = by_run.get(run.index)
            if s is not None and abs(s - s_end) <= cover:
                line.events.add(ev.index)
                break


def stations(run, cfg):
    """Along-run coordinates for candidate lines: every step, near the ends, away from fittings."""
    step = mm_to_ft(cfg["station_step_mm"])
    keep = mm_to_ft(300)
    result = []
    for seg in run.segments:
        a = dot((seg.p.X, seg.p.Y), run.u)
        b = dot((seg.q.X, seg.q.Y), run.u)
        a, b = min(a, b), max(a, b)
        if b - a < 2 * keep:
            if b - a > mm_to_ft(300):
                result.append((a + b) / 2.0)
            continue
        s = a + keep
        while s <= b - keep + 1e-6:
            result.append(s)
            s += step
        if b - keep - result[-1] > step / 3.0:
            result.append(b - keep)
    return result


def candidates(fl, plan_up, plan_right, cfg, axes=None):
    result = []
    for run in fl.runs:
        look = view_direction(run.u, plan_up, plan_right, axes)
        for s in stations(run, cfg):
            point = run.point_at(s)
            if point is None:
                continue
            line = make_line((point.X, point.Y), look, fl, cfg)
            line.seed = run
            mark_events(line, fl.events, cfg)
            result.append(line)
    return result


def choose(lines, runs, events, cfg, count, covered_runs=None, covered_events=None):
    """Greedy choice of the most important lines."""
    run_w = dict((r.index, run_weight(r, cfg)) for r in runs)
    ev_w = dict((e.index, event_weight(e, cfg)) for e in events)
    covered_runs = set(covered_runs or [])
    covered_events = set(covered_events or [])
    factor = cfg["concrete_factor"]
    factors = {2: factor["both"], 1: factor["one"], 0: factor["none"]}
    spacing = mm_to_ft(cfg["min_spacing_mm"])
    chosen = []
    pool = list(lines)
    while pool and len(chosen) < count:
        best, best_score = None, 0.0
        for line in pool:
            if line.lengthwise_main:
                continue
            gain = sum(run_w[i] for i in line.runs - covered_runs)
            gain += sum(ev_w[i] for i in line.events - covered_events)
            if gain <= 0:
                continue
            score = (gain * factors[line.concrete_sides]
                     - cfg["small_cut_penalty"] * line.small_cuts
                     - cfg["fitting_cut_penalty"] * line.fitting_cuts)
            if score > best_score:
                best, best_score = line, score
        if best is None or best_score < 0.2:
            break
        best.score = best_score
        new_events = [events[i] for i in best.events - covered_events]
        new_runs = [runs[i] for i in best.runs - covered_runs]
        new_runs.sort(key=lambda r: -run_w[r.index])
        best.reasons = ([e.label() for e in new_events]
                        + ["cuts " + r.label() for r in new_runs])
        covered_runs |= best.runs
        covered_events |= best.events
        chosen.append(best)
        pool = [ln for ln in pool if ln is not best and not _too_close(ln, best, spacing)]
    return chosen, covered_runs, covered_events


def _too_close(a, b, spacing):
    if abs(dot(a.look, b.look)) < 0.9:
        return False
    d = (a.origin[0] - b.origin[0], a.origin[1] - b.origin[1])
    if abs(dot(d, b.look)) > spacing:
        return False
    # overlapping along the line?
    ta = dot(d, b.along)
    return ta + a.t_max > b.t_min and ta + a.t_min < b.t_max


def existing_line(origin, look, t_min, t_max, fl, cfg):
    """What an already existing section of the floor shows (its own extent)."""
    line = Line(origin, look)
    crossings = _line_crossings(line, fl.run_index.near(look, origin), mm_to_ft(cfg["max_half_length_mm"]))
    line.t_min, line.t_max = t_min, t_max
    line.cuts = [(c[0], c[1], c[2]) for c in crossings if t_min <= c[1] <= t_max]
    line.runs = set(c[0].index for c in line.cuts)
    mark_events(line, fl.events, cfg)
    return line


def plan(doc, level, settings, plan_up, plan_right, count, existing_lines=None):
    """Full analysis of the floor. Returns a dict with everything the button reports."""
    from coordination.sections import floor
    cfg = settings["sections"]
    z0, z1 = floor.floor_band(doc, level, settings)
    segments = floor.collect_segments(doc, level, settings)
    runs = floor.build_runs(segments, settings)
    events = floor.find_height_changes(runs, settings)
    obstacles = C.collect(doc, z0, z1, settings)
    fl = Floor(runs, events, obstacles, segments)
    covered_runs, covered_events = set(), set()
    for origin, look, t_min, t_max in (existing_lines or []):
        line = existing_line(origin, look, t_min, t_max, fl, cfg)
        covered_runs |= line.runs
        covered_events |= line.events
    axes = model_axes(doc, plan_up)
    lines = candidates(fl, plan_up, plan_right, cfg, axes)
    chosen, covered_runs, covered_events = choose(
        lines, runs, events, cfg, count, covered_runs, covered_events)
    return {
        "z0": z0, "z1": z1, "floor": fl, "segments": segments, "runs": runs, "events": events,
        "obstacles": obstacles, "candidates": len(lines), "chosen": chosen,
        "covered_runs": covered_runs, "covered_events": covered_events,
    }
