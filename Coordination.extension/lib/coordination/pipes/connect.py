# -*- coding: utf-8 -*-
"""Connect two loose pipes the same way as a sample connection.

The user selects a sample: the fitting(s) of an existing connection, optionally
together with its pipes. Supported samples:

  elbow     one elbow between two pipes       -> axes of the targets must cross
  offset    two elbows (+ the pipe between)   -> targets parallel, any offset;
            the jog gets the sample's angle (45°, 90°, 30°...)
  tee       one tee between three pipes       -> end of a branch onto a main
  takeoff   one tap/spud on a main            -> end of a branch onto a main
  straight  one transition or union           -> targets on one axis

New fittings get the sample's family types. Works for pipes; elbows, offsets
and straights also for ducts and conduits.
"""
import math
from pyrevit.api import DB
from Autodesk.Revit.DB.Plumbing import Pipe, PlumbingUtils
from Autodesk.Revit.DB.Mechanical import Duct, MechanicalUtils

MM = 1 / 304.8
CROSS_TOL = 5 * MM       # how far apart the axes may be and still "cross"
MIN_LEN = 20 * MM        # shortest pipe piece we leave or create
PARALLEL = math.cos(math.radians(1.0))
TAKEOFFS = ("TapPerpendicular", "TapAdjustable", "SpudPerpendicular", "SpudAdjustable")
TEES = ("Tee", "LateralTee", "Wye")
STRAIGHTS = ("Transition", "Union")

KIND_NAMES = {
    "elbow": u"відвід",
    "offset": u"зміщення двома відводами",
    "tee": u"трійник",
    "takeoff": u"врізка",
    "straight": u"перехід / муфта",
}


class ConnectError(Exception):
    pass


# --- reading elements -------------------------------------------------------

def idv(element_id):
    value = getattr(element_id, "Value", None)
    return element_id.IntegerValue if value is None else value


def conns(e):
    cm = e.ConnectorManager if isinstance(e, DB.MEPCurve) else e.MEPModel.ConnectorManager
    return list(cm.Connectors)


def near_conn(e, p):
    return min(conns(e), key=lambda c: c.Origin.DistanceTo(p))


FITTING_CATEGORIES = set(int(c) for c in (
    DB.BuiltInCategory.OST_PipeFitting, DB.BuiltInCategory.OST_DuctFitting,
    DB.BuiltInCategory.OST_ConduitFitting, DB.BuiltInCategory.OST_CableTrayFitting))


def is_fitting(e):
    """Pipe, duct, conduit or cable tray fitting (elbow, tee, tap, transition...)."""
    if not isinstance(e, DB.FamilyInstance) or e.Category is None:
        return False
    if idv(e.Category.Id) not in FITTING_CATEGORIES:
        return False
    model = e.MEPModel
    return model is not None and getattr(model, "PartType", None) is not None


def is_straight_curve(e):
    return (isinstance(e, DB.MEPCurve) and isinstance(e.Location, DB.LocationCurve)
            and isinstance(e.Location.Curve, DB.Line))


def part(e):
    return str(e.MEPModel.PartType)


def neighbours(e):
    """[(my connector, other element, other connector)] physical connections."""
    out = []
    for c in conns(e):
        if not c.IsConnected:
            continue
        for r in c.AllRefs:
            o = r.Owner
            if o is None or o.Id == e.Id or isinstance(o, DB.MEPSystem):
                continue
            if not (isinstance(o, DB.MEPCurve) or isinstance(o, DB.FamilyInstance)):
                continue
            out.append((c, o, r))
    return out


def type_name(doc, type_id):
    t = doc.GetElement(type_id)
    if t is None:
        return "?"
    fam = getattr(t, "FamilyName", "") or ""
    p = t.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
    name = p.AsString() if p is not None else ""
    return (u"%s: %s" % (fam, name)) if fam else (name or "?")


def angle_deg(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, a.DotProduct(b)))))


# --- one selection: sample + the pipes to connect -----------------------------

def split_selection(doc, ids):
    """Split one selection into the sample connection and the loose pipes to
    connect. Loose = selected straight pipes not joined to any selected fitting.
    Returns (sample ids, [loose pipes])."""
    els = [doc.GetElement(i) for i in ids]
    els = [e for e in els if e is not None]
    fitting_ids = set(idv(e.Id) for e in els if is_fitting(e))
    sample, loose = [], []
    for e in els:
        if is_fitting(e):
            sample.append(e.Id)
        elif isinstance(e, DB.MEPCurve):
            if any(idv(o.Id) in fitting_ids for _, o, _ in neighbours(e)):
                sample.append(e.Id)
            elif is_straight_curve(e):
                loose.append(e)
    return sample, loose


def connect_pair(doc, sample, a, b):
    """Connect two selected pipes. For a tee/takeoff the main is found
    automatically: whichever order Revit accepts."""
    if not needs_main(sample):
        return connect(doc, sample, a, None, b, None)
    try:
        return connect(doc, sample, a, None, b, None)
    except ConnectError as first_error:
        try:
            return connect(doc, sample, b, None, a, None)
        except ConnectError:
            raise first_error


# --- the sample ---------------------------------------------------------------

def analyse_sample(doc, ids):
    """Read the sample connection. Returns a dict:
    kind, types (fitting type ids, from the first pipe's side), part,
    theta (offset: angle of the jog to the pipes, radians), text."""
    els = [doc.GetElement(i) for i in ids]
    els = [e for e in els if e is not None]
    fittings = [e for e in els if is_fitting(e)]
    if not fittings:
        raise ConnectError(u"У зразку немає фітингів. Виділіть відвід, трійник, врізку чи перехід "
                           u"з'єднання, яке треба повторити.")
    chain = set(idv(f.Id) for f in fittings)
    fitting_ids = set(chain)
    # A selected pipe is part of the connection only if both its ends go to
    # selected fittings (e.g. the short pipe between two elbows of an offset).
    for e in els:
        if isinstance(e, DB.MEPCurve):
            nb = neighbours(e)
            if len(nb) >= 2 and all(idv(o.Id) in fitting_ids for _, o, _ in nb):
                chain.add(idv(e.Id))

    by_id = dict((idv(e.Id), e) for e in els)
    outer = []          # (outer pipe, its connector, chain element, chain connector)
    for cid in chain:
        e = by_id[cid]
        for mc, o, oc in neighbours(e):
            if idv(o.Id) in chain:
                continue
            if not isinstance(o, DB.MEPCurve):
                raise ConnectError(u"Зразок з'єднаний з елементом %d, який не є трубою. "
                                   u"Виділіть усі фітинги з'єднання." % idv(o.Id))
            outer.append((o, oc, e, mc))

    parts = [part(f) for f in fittings]
    res = {"types": [], "part": None, "theta": None}
    if len(fittings) == 1 and len(chain) == 1:
        f = fittings[0]
        p = parts[0]
        res["types"] = [f.GetTypeId()]
        res["part"] = p
        if p == "Elbow":
            res["kind"] = "elbow"
        elif p in TEES:
            res["kind"] = "tee"
        elif p in TAKEOFFS:
            res["kind"] = "takeoff"
        elif p in STRAIGHTS:
            res["kind"] = "straight"
        else:
            raise ConnectError(u"Фітинг типу %s поки не підтримується як зразок." % p)
    elif len(fittings) == 2 and all(p == "Elbow" for p in parts):
        if len(outer) != 2:
            raise ConnectError(u"Два відводи зразка мають з'єднувати рівно дві труби "
                               u"(знайдено %d)." % len(outer))
        pipe_a, oc_a, el1, mc1 = outer[0]
        el2 = [f for f in fittings if f.Id != el1.Id][0]
        d_a = oc_a.CoordinateSystem.BasisZ          # out of pipe A, into the elbow
        other = [c for c in conns(el1) if c.Origin.DistanceTo(mc1.Origin) > 1e-6]
        if not other:
            raise ConnectError(u"Не вдалося прочитати геометрію відводу %d." % idv(el1.Id))
        d_mid = other[0].CoordinateSystem.BasisZ    # out of elbow 1, towards elbow 2
        theta = math.acos(max(-1.0, min(1.0, abs(d_a.DotProduct(d_mid)))))
        if math.degrees(theta) < 5:
            raise ConnectError(u"Кут зміщення у зразку менший за 5°.")
        res.update(kind="offset", theta=theta, types=[el1.GetTypeId(), el2.GetTypeId()], part="Elbow")
    else:
        raise ConnectError(u"Такий зразок поки не підтримується: %s.\nПідтримуються: один відвід, "
                           u"два відводи (зміщення), трійник, врізка, перехід або муфта."
                           % ", ".join(parts))

    text = KIND_NAMES[res["kind"]]
    if res["kind"] == "offset":
        text += u" %.0f°" % math.degrees(res["theta"])
    names = []
    for t in res["types"]:
        n = type_name(doc, t)
        if n not in names:
            names.append(n)
    res["text"] = u"%s (%s)" % (text, u"; ".join(names))
    return res


# --- target pipes -------------------------------------------------------------

def end_info(pipe, pick=None, other=None):
    """Which end of `pipe` to connect: the only free one, otherwise the one
    nearer to the picked point, otherwise the one nearer to the `other` pipe."""
    if not is_straight_curve(pipe):
        raise ConnectError(u"Елемент %d не є прямою трубою." % idv(pipe.Id))
    line = pipe.Location.Curve
    ends = [line.GetEndPoint(0), line.GetEndPoint(1)]
    free = [not near_conn(pipe, p).IsConnected for p in ends]
    if free[0] != free[1]:
        k = 0 if free[0] else 1
    elif not free[0]:
        raise ConnectError(u"Обидва кінці труби %d уже з'єднані." % idv(pipe.Id))
    elif pick is not None:
        d = (ends[1] - ends[0]).Normalize()
        k = 0 if (pick - ends[0]).DotProduct(d) < line.Length / 2 else 1
    elif other is not None and is_straight_curve(other):
        oc = other.Location.Curve
        dist = [oc.Project(p).Distance for p in ends]
        k = 0 if dist[0] <= dist[1] else 1
    else:
        k = 1
    near, far = ends[k], ends[1 - k]
    return {"pipe": pipe, "near": near, "far": far, "k": k,
            "u": (near - far).Normalize()}        # out of the pipe at the near end


def free_end_info(pipe, pick=None, other=None):
    info = end_info(pipe, pick, other)
    if near_conn(pipe, info["near"]).IsConnected:
        raise ConnectError(u"Цей кінець труби %d уже з'єднаний." % idv(pipe.Id))
    return info


def _set_near(info, p):
    """Move the near end of the pipe to p, the far end stays."""
    if (p - info["far"]).DotProduct(info["u"]) < MIN_LEN:
        raise ConnectError(u"Труба %d стала б надто короткою." % idv(info["pipe"].Id))
    a, b = (p, info["far"]) if info["k"] == 0 else (info["far"], p)
    info["pipe"].Location.Curve = DB.Line.CreateBound(a, b)


def closest(p, u, q, v):
    """Closest points of the lines p + s*u and q + t*v (unit vectors), or None if parallel."""
    w = p - q
    b = u.DotProduct(v)
    d = u.DotProduct(w)
    e = v.DotProduct(w)
    den = 1.0 - b * b
    if den < 1e-9:
        return None
    s = (b * e - d) / den
    t = (e - b * d) / den
    return p + u * s, q + v * t, s, t


def _copy(doc, src, a, b):
    nid = list(DB.ElementTransformUtils.CopyElement(doc, src.Id, DB.XYZ(0, 0, 10)))[0]
    n = doc.GetElement(nid)
    n.Location.Curve = DB.Line.CreateBound(a, b)
    return n


def _apply_type(doc, fitting, type_id, notes):
    if type_id is None or fitting.GetTypeId() == type_id:
        return
    t = doc.GetElement(type_id)
    if t is None or t.Category is None or fitting.Category is None \
            or t.Category.Id != fitting.Category.Id:
        notes.append(u"тип зразка не підходить до фітинга %d" % idv(fitting.Id))
        return
    try:
        fitting.ChangeTypeId(type_id)
    except Exception as ex:
        notes.append(u"не вдалося змінити тип фітинга %d: %s" % (idv(fitting.Id), ex))


def _mm(x):
    return x / MM


# --- builders -----------------------------------------------------------------

def build_elbow(doc, sample, a, b, notes):
    r = closest(a["near"], a["u"], b["near"], b["u"])
    if r is None:
        raise ConnectError(u"Труби паралельні: одним відводом їх не з'єднати. "
                           u"Візьміть зразком зміщення з двох відводів.")
    pa, pb, s, t = r
    gap = pa.DistanceTo(pb)
    if gap > CROSS_TOL:
        raise ConnectError(u"Осі труб не перетинаються (розходяться на %.0f мм), "
                           u"одним відводом їх не з'єднати." % _mm(gap))
    v = (pa + pb) * 0.5
    _set_near(a, v)
    _set_near(b, v)
    doc.Regenerate()
    el = doc.Create.NewElbowFitting(near_conn(a["pipe"], v), near_conn(b["pipe"], v))
    _apply_type(doc, el, sample["types"][0], notes)
    return [el.Id]


def build_offset(doc, sample, a, b, notes):
    u = a["u"]
    if b["u"].DotProduct(u) > -PARALLEL:
        if abs(b["u"].DotProduct(u)) >= PARALLEL:
            raise ConnectError(u"Вибрані кінці труб дивляться в один бік. Клікніть ближче до "
                               u"кінців, які треба з'єднати.")
        raise ConnectError(u"Для зразка з двох відводів труби мають бути паралельні "
                           u"(кут між ними %.0f°)." % angle_deg(u, b["u"].Negate()))
    w = b["near"] - a["near"]
    g = w.DotProduct(u)
    o = w - u * g
    h = o.GetLength()
    if h < CROSS_TOL:
        raise ConnectError(u"Труби на одній осі, зміщувати нічого. Візьміть зразком перехід або муфту.")
    theta = sample["theta"]
    along = 0.0 if math.degrees(theta) > 89.9 else h / math.tan(theta)
    t1 = (g - along) / 2.0
    p1 = a["near"] + u * t1
    p2 = p1 + u * along + o
    bd = b["u"].Negate()
    p2 = b["near"] + bd * (p2 - b["near"]).DotProduct(bd)
    if p1.DistanceTo(p2) < MIN_LEN:
        raise ConnectError(u"Зміщення замале для кута %.0f°." % math.degrees(theta))
    _set_near(a, p1)
    _set_near(b, p2)
    mid = _copy(doc, a["pipe"], p1, p2)
    doc.Regenerate()
    e1 = doc.Create.NewElbowFitting(near_conn(a["pipe"], p1), near_conn(mid, p1))
    e2 = doc.Create.NewElbowFitting(near_conn(mid, p2), near_conn(b["pipe"], p2))
    _apply_type(doc, e1, sample["types"][0], notes)
    _apply_type(doc, e2, sample["types"][1], notes)
    if along > 0 and g < along:
        notes.append(u"розрив між трубами був коротший за зміщення, труби вкорочено")
    return [mid.Id, e1.Id, e2.Id]


def _branch_point(main, br):
    line = main.Location.Curve
    m0 = line.GetEndPoint(0)
    md = (line.GetEndPoint(1) - m0).Normalize()
    r = closest(br["near"], br["u"], m0, md)
    if r is None:
        raise ConnectError(u"Відгалуження паралельне магістралі.")
    pb, pm, s, t = r
    gap = pb.DistanceTo(pm)
    if gap > CROSS_TOL:
        raise ConnectError(u"Вісь відгалуження не перетинає вісь магістралі (розходяться на %.0f мм)."
                           % _mm(gap))
    if t < MIN_LEN or t > line.Length - MIN_LEN:
        raise ConnectError(u"Відгалуження не потрапляє на магістраль між її кінцями.")
    return pm


def _break(doc, main, p):
    if isinstance(main, Pipe):
        return PlumbingUtils.BreakCurve(doc, main.Id, p)
    if isinstance(main, Duct):
        return MechanicalUtils.BreakCurve(doc, main.Id, p)
    raise ConnectError(u"Трійник поки можна вставити лише в трубу або повітровід.")


def build_tee(doc, sample, main, br, notes):
    pm = _branch_point(main, br)
    _set_near(br, pm)
    other = doc.GetElement(_break(doc, main, pm))
    doc.Regenerate()
    tee = doc.Create.NewTeeFitting(near_conn(main, pm), near_conn(other, pm),
                                   near_conn(br["pipe"], pm))
    _apply_type(doc, tee, sample["types"][0], notes)
    return [other.Id, tee.Id]


def build_takeoff(doc, sample, main, br, notes):
    pm = _branch_point(main, br)
    _set_near(br, pm)
    doc.Regenerate()
    tap = doc.Create.NewTakeoffFitting(near_conn(br["pipe"], pm), main)
    _apply_type(doc, tap, sample["types"][0], notes)
    return [tap.Id]


def build_straight(doc, sample, a, b, notes):
    u = a["u"]
    if b["u"].DotProduct(u) > -PARALLEL:
        raise ConnectError(u"Для переходу труби мають бути на одній осі, кінцями одна до одної.")
    w = b["near"] - a["near"]
    g = w.DotProduct(u)
    off = (w - u * g).GetLength()
    if off > CROSS_TOL:
        raise ConnectError(u"Труби не на одній осі (зміщення %.0f мм). Візьміть зразком "
                           u"зміщення з двох відводів." % _mm(off))
    if g < -MIN_LEN:
        raise ConnectError(u"Труби заходять одна на одну на %.0f мм." % _mm(-g))
    p = b["near"]
    _set_near(a, p)
    doc.Regenerate()
    ca, cb = near_conn(a["pipe"], p), near_conn(b["pipe"], p)
    makers = [doc.Create.NewTransitionFitting, doc.Create.NewUnionFitting]
    if sample["part"] == "Union":
        makers.reverse()
    errors = []
    for make in makers:
        try:
            f = make(ca, cb)
            _apply_type(doc, f, sample["types"][0], notes)
            return [f.Id]
        except Exception as ex:
            errors.append(str(ex))
    raise ConnectError(u"Revit не створив перехід: %s" % "; ".join(errors))


BUILDERS = {
    "elbow": build_elbow,
    "offset": build_offset,
    "tee": build_tee,
    "takeoff": build_takeoff,
    "straight": build_straight,
}


def needs_main(sample):
    return sample["kind"] in ("tee", "takeoff")


# --- transaction ----------------------------------------------------------------

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


def connect(doc, sample, first, first_pick, second, second_pick):
    """Connect one pair in its own transaction. For tee/takeoff `first` is the
    main and `second` the branch. Returns (created ids, notes); raises
    ConnectError and leaves the model unchanged when it cannot."""
    if first.Id == second.Id:
        raise ConnectError(u"Двічі вибрано ту саму трубу.")
    if needs_main(sample):
        if not is_straight_curve(first):
            raise ConnectError(u"Магістраль %d не є прямою трубою." % idv(first.Id))
        args = (first, free_end_info(second, second_pick, first))
    else:
        args = (free_end_info(first, first_pick, second), free_end_info(second, second_pick, first))
    notes = []
    t = DB.Transaction(doc, "Match Connection")
    t.Start()
    try:
        ids = BUILDERS[sample["kind"]](doc, sample, args[0], args[1], notes)
    except ConnectError:
        t.RollBack()
        raise
    except Exception as ex:
        t.RollBack()
        raise ConnectError(u"Revit не прийняв з'єднання: %s" % ex)
    fp = _Failures()
    o = t.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(fp)
    o.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(o)
    if t.Commit() != DB.TransactionStatus.Committed:
        raise ConnectError(u"Revit відхилив з'єднання: %s" % "; ".join(fp.errors[:2]))
    return ids, notes
