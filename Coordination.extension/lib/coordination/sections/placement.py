# -*- coding: utf-8 -*-
"""Where to put the sections of a floor (vision section 4).

1. Candidates. Along every main run, every station_step_mm (and near its ends), a section
   line across the run: a cross section of the run and of everything parallel to it.
   The line always follows a model axis (grid directions and their perpendiculars), the
   one closest to the run: a pipe drawn 0.1 deg off the grid never makes a skewed section.
   Runs at up to 45 deg to the line still count as cut.
   Stations keep away from the run's fittings.
2. Extent of each line (wall to wall, the room or corridor the networks run in): on each
   side the line goes to the first room wall of any kind (standing on the floor, with the
   networks near the seed not passing over it: not a partition up to a suspended ceiling,
   not a box or lining hanging among the networks), or concrete column / beam (a concrete
   wall hanging from the slab counts as a beam), if it is
   not farther than max_reach_to_structure_mm from the last network before it, and ends
   margin_past_structure_mm past it (touching walls, e.g. cladding on concrete, are one).
   Otherwise that side ends margin_no_structure_mm after the networks (bundle_gap_mm
   between networks still counts as one bundle). Concrete at an end scores higher.
3. What a candidate shows: the main runs it cuts across (each run counts once), the
   height changes it is close to (it cuts one of the two runs within
   height_change_cover_mm of the change), and the places where a network appears in the
   bundle or leaves it (run ends that are not height changes: tees, risers, turns),
   cut within the same distance.
4. Choice. One by one, the candidate that adds most of what is not shown yet:
   weight of each run = class weight (gravity > ducts, trays > pressure pipes > sprinklers)
   x size x length; each height change = height_change_weight x the run's weight x size of the change;
   each place a network appears = network_end_weight x the run's weight.
   Multiplied by concrete_factor (concrete on both sides / one / none) and lowered for
   small pipes and fittings in the cut. A line whose plane runs lengthwise through a main
   pipe / duct / tray is never chosen (small ones lengthwise: a bigger penalty), nor a line
   that runs inside any wall (concrete, block, gypsum...) or along its face, closer than
   wall_clearance_mm, over more than wall_overlap_mm. Crossing a wall or ending at it is fine.
   Stops at count sections or when nothing is left.
"""
import math

from coordination.units import mm_to_ft
from coordination.sections.floor import dot
from coordination.sections import concrete as C


def run_weight(run, cfg):
    cls = cfg["class_weight"].get(run.kind, 1.0)
    size = max(0.6, min(cfg.get("max_size_factor", 1.5), math.sqrt(run.size * 304.8 / 100.0)))
    length = max(0.5, min(2.0, run.length * 0.3048 / 5.0))
    return cls * size * length


def event_weight(event, cfg):
    run = event.run_a
    cls = cfg["class_weight"].get(run.kind, 1.0)
    size = max(0.6, min(cfg.get("max_size_factor", 1.5), math.sqrt(run.size * 304.8 / 100.0)))
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
        self.concrete = [None, None]   # concrete obstacle at the left / right end
        self.ends = [None, None]       # "concrete", "wall" or None at the left / right end
        self.cuts = []                 # (run, t, s_on_run)
        self.small_cuts = 0
        self.fitting_cuts = 0
        self.lengthwise_main = 0       # main segments the plane cuts along their length
        self.in_wall = []              # walls the plane runs inside / along the face of
        self.runs = set()
        self.events = set()
        self.ends_shown = set()        # RunEnd indexes near the line
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
        if min(abs(interval[0]), abs(interval[1])) > max_half:
            continue
        hits.append((interval, ob))
    return hits


def _side_extent(sign, crossings, hits, cfg):
    """End of the line on one side: (distance from origin, concrete obstacle or None, kind).

    The line ends past the first wall of any kind, or concrete column / beam, on this side
    (walls touching each other, e.g. cladding on concrete, count as one), so a section
    covers the room or corridor its networks run in. kind: "concrete", "wall" or None
    (no wall within max_reach_to_structure_mm of the networks: ends after the networks)."""
    reach = mm_to_ft(cfg["max_reach_to_structure_mm"])
    gap_max = mm_to_ft(cfg["bundle_gap_mm"])
    touch = mm_to_ft(50)
    nets = sorted(abs(c[1]) for c in crossings if c[1] * sign > 0)
    structs = []
    for (a, b), ob, concrete in hits:
        if a <= 0.0 <= b:
            # the seed pipe runs in this wall: it bounds the side where most of the wall is
            if (a + b) * sign > 0:
                structs.append((0.0, max(a * sign, b * sign), ob, concrete))
        elif sign > 0 and a > 0:
            structs.append((a, b, ob, concrete))
        elif sign < 0 and b < 0:
            structs.append((-b, -a, ob, concrete))
    structs.sort(key=lambda s: s[0])
    limit = float("inf")
    if structs:
        near, far, ob, concrete = structs[0]
        group_concrete = ob if concrete else None
        for n2, f2, ob2, c2 in structs[1:]:
            if n2 > far + touch:
                break
            far = max(far, f2)
            if c2 and group_concrete is None:
                group_concrete = ob2
        before = [d for d in nets if d < near]
        outer = max(before) if before else 0.0
        if near - outer <= reach:
            kind = "concrete" if group_concrete is not None else "wall"
            return far + mm_to_ft(cfg["margin_past_structure_mm"]), group_concrete, kind
        limit = near
    outer = 0.0
    for d in nets:
        if d >= limit or d - outer > gap_max:
            break
        outer = d
    return outer + mm_to_ft(cfg["margin_no_structure_mm"]), None, None


class Floor(object):
    """Runs, concrete and small segments of the floor with their strip indexes."""

    def __init__(self, runs, events, obstacles, segments, walls=None, z0=None, settings=None):
        self.runs = runs
        self.events = events
        self.obstacles = obstacles
        self.segments = segments
        self.z0 = z0
        self.settings = settings
        walls = walls or []
        self.boundary_walls = walls                    # where a section may end (if a room wall)
        self.boundary_index = StripIndex(walls, _obstacle_points)
        # never cut along: every wall and every concrete beam
        self.walls = walls + [ob for ob in obstacles if ob.kind == "beam"]
        self.wall_index = StripIndex(self.walls, _obstacle_points)
        self.ends = run_ends(runs, events)
        self.small = [s for s in segments if not s.main]
        self.run_index = StripIndex(runs, _run_points)
        self.obstacle_index = StripIndex(obstacles, _obstacle_points)
        self.small_index = StripIndex(self.small, _seg_points)


def make_line(origin, look, fl, cfg, use_concrete=True):
    """Section line through origin looking `look`, with its extent and what it cuts."""
    line = Line(origin, look)
    max_half = mm_to_ft(cfg["max_half_length_mm"])
    crossings = _line_crossings(line, fl.run_index.near(look, origin), max_half)
    small = fl.small_index.near(look, origin)
    hits = []
    if use_concrete:
        # a wall ends the section only if it stands on the floor and the networks near the
        # seed do not pass over it (room wall); columns and beams always do
        tops = [c[4].z + c[4].height / 2.0 for c in crossings if abs(c[1]) <= mm_to_ft(3000)]
        networks_top = max(tops) if tops else None

        def bounds(ob):
            if networks_top is None or fl.z0 is None:
                return True
            return C.is_room_wall(ob, fl.z0, networks_top, fl.settings)

        hits = [(iv, ob, True) for iv, ob in
                _obstacle_hits(line, fl.obstacle_index.near(look, origin), max_half) if bounds(ob)]
        hits += [(iv, ob, ob.kind == "beam") for iv, ob in
                 _obstacle_hits(line, fl.boundary_index.near(look, origin), max_half) if bounds(ob)]
    right, ob_r, kind_r = _side_extent(1, crossings, hits, cfg)
    left, ob_l, kind_l = _side_extent(-1, crossings, hits, cfg)
    line.t_min, line.t_max = -left, right
    line.concrete = [ob_l, ob_r]
    line.ends = [kind_l, kind_r]
    for run, t, s_on_run, near_end, seg in crossings:
        if line.t_min <= t <= line.t_max:
            line.cuts.append((run, t, s_on_run))
            line.runs.add(run.index)
            if near_end:
                line.fitting_cuts += 1
    o = line.origin
    for wall in fl.wall_index.near(look, origin):
        if _along_wall(line, wall, cfg):
            line.in_wall.append(wall)
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


def _along_wall(line, wall, cfg):
    """True if the cut plane runs inside the wall or along its face (closer than
    wall_clearance_mm to it) over more than wall_overlap_mm of the section's length.
    Crossing a wall, or ending at its edge, is fine."""
    if abs(dot(wall.u, line.along)) < math.cos(math.radians(15)):
        return False
    o = line.origin
    distance = abs(dot((wall.mid[0] - o[0], wall.mid[1] - o[1]), line.look))
    if distance > wall.width / 2.0 + mm_to_ft(cfg.get("wall_clearance_mm", 100)):
        return False
    ta = dot((wall.a[0] - o[0], wall.a[1] - o[1]), line.along)
    tb = dot((wall.b[0] - o[0], wall.b[1] - o[1]), line.along)
    overlap = min(max(ta, tb), line.t_max) - max(min(ta, tb), line.t_min)
    return overlap > mm_to_ft(cfg.get("wall_overlap_mm", 100))


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


class RunEnd(object):
    """A place where a network appears in (or leaves) the bundle: an end of a run that is
    not a height change (branch from a tee, riser, turn in plan, start of the network)."""

    def __init__(self, index, run, s):
        self.index = index
        self.run = run
        self.s = s

    def label(self):
        return u"network appears: " + self.run.label()


def run_ends(runs, events):
    at_events = set()
    for ev in events:
        pairs = [(ev.run_a, ev.s_a), (ev.run_b, ev.s_b)]
        for run_a, s_a, run_b, s_b in getattr(ev, "others", []):
            pairs.extend([(run_a, s_a), (run_b, s_b)])
        for run, s in pairs:
            at_events.add((run.index, round(s, 3)))
    result = []
    for run in runs:
        for s in (run.s0, run.s1):
            if (run.index, round(s, 3)) not in at_events:
                result.append(RunEnd(len(result), run, s))
    return result


def mark_ends(line, ends, cfg):
    cover = mm_to_ft(cfg["height_change_cover_mm"])
    by_run = {}
    for run, t, s_on_run in line.cuts:
        by_run[run.index] = s_on_run
    for end in ends:
        s = by_run.get(end.run.index)
        if s is not None and abs(s - end.s) <= cover:
            line.ends_shown.add(end.index)


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
            mark_ends(line, fl.ends, cfg)
            result.append(line)
    return result


def choose(lines, fl, cfg, count, covered):
    """Greedy choice of the most important lines. `covered` ({"runs", "events", "ends"}:
    sets of indexes already shown, e.g. by existing sections) is updated in place."""
    runs, events, ends = fl.runs, fl.events, fl.ends
    run_w = dict((r.index, run_weight(r, cfg)) for r in runs)
    ev_w = dict((e.index, event_weight(e, cfg)) for e in events)
    end_w = dict((e.index, cfg.get("network_end_weight", 0.5) * run_w[e.run.index]) for e in ends)
    covered_runs = covered["runs"]
    covered_events = covered["events"]
    covered_ends = covered["ends"]
    factor = cfg["concrete_factor"]
    factors = {2: factor["both"], 1: factor["one"], 0: factor["none"]}
    spacing = mm_to_ft(cfg["min_spacing_mm"])
    chosen = []
    pool = list(lines)
    while pool and len(chosen) < count:
        best, best_score = None, 0.0
        for line in pool:
            if line.lengthwise_main or line.in_wall:
                continue
            gain = sum(run_w[i] for i in line.runs - covered_runs)
            gain += sum(ev_w[i] for i in line.events - covered_events)
            gain += sum(end_w[i] for i in line.ends_shown - covered_ends)
            if gain <= 0:
                continue
            gain += cfg.get("network_in_cut_bonus", 0.3) * len(line.runs)   # many networks together
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
        new_ends = [ends[i] for i in best.ends_shown - covered_ends]
        new_ends.sort(key=lambda e: -end_w[e.index])
        best.reasons = ([e.label() for e in new_events]
                        + ["cuts " + r.label() for r in new_runs]
                        + [e.label() for e in new_ends])
        covered_runs |= best.runs
        covered_events |= best.events
        covered_ends |= best.ends_shown
        chosen.append(best)
        pool = [ln for ln in pool if ln is not best and not _too_close(ln, best, spacing)]
    return chosen


def _too_close(a, b, spacing):
    if abs(dot(a.look, b.look)) < 0.9:
        return False
    d = (a.origin[0] - b.origin[0], a.origin[1] - b.origin[1])
    if abs(dot(d, b.look)) > spacing:
        return False
    # overlapping along the line by more than half of the shorter one? (two sections that
    # only meet at a shared wall, one on each side of it, are not duplicates)
    ta = dot(d, b.along)
    overlap = min(ta + a.t_max, b.t_max) - max(ta + a.t_min, b.t_min)
    shorter = min(a.t_max - a.t_min, b.t_max - b.t_min)
    return overlap > 0.5 * shorter


def existing_line(origin, look, t_min, t_max, fl, cfg):
    """What an already existing section of the floor shows (its own extent)."""
    line = Line(origin, look)
    crossings = _line_crossings(line, fl.run_index.near(look, origin), mm_to_ft(cfg["max_half_length_mm"]))
    line.t_min, line.t_max = t_min, t_max
    line.cuts = [(c[0], c[1], c[2]) for c in crossings if t_min <= c[1] <= t_max]
    line.runs = set(c[0].index for c in line.cuts)
    mark_events(line, fl.events, cfg)
    mark_ends(line, fl.ends, cfg)
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
    walls = C.collect_all_walls(doc, z0, z1, settings)
    fl = Floor(runs, events, obstacles, segments, walls, z0, settings)
    covered = {"runs": set(), "events": set(), "ends": set()}
    for origin, look, t_min, t_max in (existing_lines or []):
        line = existing_line(origin, look, t_min, t_max, fl, cfg)
        covered["runs"] |= line.runs
        covered["events"] |= line.events
        covered["ends"] |= line.ends_shown
    axes = model_axes(doc, plan_up)
    lines = candidates(fl, plan_up, plan_right, cfg, axes)
    chosen = choose(lines, fl, cfg, count, covered)
    return {
        "z0": z0, "z1": z1, "floor": fl, "segments": segments, "runs": runs, "events": events,
        "ends": fl.ends, "obstacles": obstacles, "candidates": len(lines), "chosen": chosen,
        "covered_runs": covered["runs"], "covered_events": covered["events"],
        "covered_ends": covered["ends"],
    }
