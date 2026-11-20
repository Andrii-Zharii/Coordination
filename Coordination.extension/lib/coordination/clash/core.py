# -*- coding: utf-8 -*-
"""Clash detection core for the Coordination extension (Clash panel).

A clash is a physical intersection of two elements that are not joined into one
MEP network through connectors, whatever their discipline. Host elements are
filtered by workset, linked elements by category. Linked-vs-linked pairs are
not checked: every clash involves at least one element of the host model.
"""
import io
import json
import os

import System
from System.Collections.Generic import List
from pyrevit import DB

HOST_KEY = u"host"
NAV_VIEW_PREFIX = u"CLASH Navigator"
DATA_DIR = os.path.join(os.environ["APPDATA"], "pyRevit", "GRHL Clash")
RESULTS_FILE = os.path.join(DATA_DIR, "results.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

SKIP_CATEGORIES = set(int(c) for c in (
    DB.BuiltInCategory.OST_VolumeOfInterest,
    DB.BuiltInCategory.OST_Cameras,
    DB.BuiltInCategory.OST_Levels,
    DB.BuiltInCategory.OST_Grids,
    DB.BuiltInCategory.OST_Rooms,
    DB.BuiltInCategory.OST_Areas,
    DB.BuiltInCategory.OST_MEPSpaces,
    DB.BuiltInCategory.OST_RvtLinks,
    DB.BuiltInCategory.OST_Mass,
    DB.BuiltInCategory.OST_SketchLines,
))
DEFAULT_OFF_CATEGORIES = (u"Parking", u"Structural opening cut", u"Center Line", u"Center line")
# Linked categories checked when nothing is remembered yet: building structure only, no MEP inside links.
DEFAULT_LINK_CATEGORIES = (u"Walls", u"Floors", u"Structural Framing", u"Structural Columns", u"Columns",
                           u"Structural Foundations")
DEFAULT_FOCUS_CATEGORIES = (u"Pipes", u"Pipe Fittings", u"Cable Trays", u"Cable Tray Fittings")
OPENING_MARKERS = (u"שרוול", u"פתח", u"-OP")
IGNORED_MARKERS = (u"CHANNEL DRAIN", u"EBL_LIGHT_FIX_CEIL_LED")
IGNORED_WALL_PREFIXES = (u"INT",)
# Type names of floors that are placeholders, not structure (Revit's default "Wood Joist..." type in a concrete building).
IGNORED_FLOOR_TYPE_MARKERS = (u"WOOD JOIST",)
KEPT_WALL_MARKERS = (u"(CN",)
REGION_FAMILY = u"Clash Region"
REGION_WORKSET = u"Clash"
REGION_MARGIN_MM = 100.0
REGION_ARC_PARAM = u"ARC clash"
ARC_CATEGORIES = (u"Walls", u"Floors", u"Structural Framing", u"Structural Columns", u"Columns")
TRAY_CATEGORIES = (u"Cable Trays", u"Cable Tray Fittings")
GROUP_NEAR_MM = 1000.0   # same pair of networks this close -> one group
GROUP_FAR_MM = 4000.0    # ... up to this far when one side is the same element / MEP network


def code_version():
    """Short git commit of the extension's repository (what pyRevit runs now), or "?"."""
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        git = os.path.join(os.path.dirname(repo), ".git")
        with io.open(os.path.join(git, "HEAD"), "r", encoding="utf-8") as f:
            head = f.read().strip()
        if not head.startswith(u"ref:"):
            return head[:7]
        ref = head[4:].strip()
        path = os.path.join(git, *ref.split(u"/"))
        if os.path.isfile(path):
            with io.open(path, "r", encoding="utf-8") as f:
                return f.read().strip()[:7]
        packed = os.path.join(git, "packed-refs")
        if os.path.isfile(packed):
            with io.open(packed, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().endswith(ref):
                        return line.split()[0][:7]
    except Exception:
        pass
    return u"?"


def to_ft(mm):
    return DB.UnitUtils.ConvertToInternalUnits(float(mm), DB.UnitTypeId.Millimeters)


def to_mm(ft):
    return DB.UnitUtils.ConvertFromInternalUnits(ft, DB.UnitTypeId.Millimeters)


def id_int(element_id):
    value = getattr(element_id, "Value", None)
    return int(value) if value is not None else int(element_id.IntegerValue)


def make_id(value):
    return DB.ElementId(System.Int64(value))


class Box(object):
    """Axis-aligned box in host model coordinates (feet)."""

    def __init__(self, lo, hi):
        self.lo = lo
        self.hi = hi

    @classmethod
    def of_points(cls, points):
        xs = [p.X for p in points]
        ys = [p.Y for p in points]
        zs = [p.Z for p in points]
        return cls(DB.XYZ(min(xs), min(ys), min(zs)), DB.XYZ(max(xs), max(ys), max(zs)))

    def corners(self):
        return [DB.XYZ(x, y, z)
                for x in (self.lo.X, self.hi.X)
                for y in (self.lo.Y, self.hi.Y)
                for z in (self.lo.Z, self.hi.Z)]

    def overlaps(self, other):
        return not (self.hi.X < other.lo.X or self.lo.X > other.hi.X or
                    self.hi.Y < other.lo.Y or self.lo.Y > other.hi.Y or
                    self.hi.Z < other.lo.Z or self.lo.Z > other.hi.Z)

    def contains(self, p):
        return (self.lo.X <= p.X <= self.hi.X and self.lo.Y <= p.Y <= self.hi.Y and
                self.lo.Z <= p.Z <= self.hi.Z)

    def union(self, other):
        return Box.of_points([self.lo, self.hi, other.lo, other.hi])

    def expanded(self, d):
        v = DB.XYZ(d, d, d)
        return Box(self.lo - v, self.hi + v)

    def center(self):
        return (self.lo + self.hi) * 0.5

    def to_outline(self, transform=None):
        """Outline of the box; in a linked document's coordinates when its link-to-host transform is given."""
        points = self.corners()
        if transform is not None:
            inverse = transform.Inverse
            points = [inverse.OfPoint(p) for p in points]
        box = Box.of_points(points)
        return DB.Outline(box.lo, box.hi)


def _grid_line(grid):
    curve = grid.Curve
    if not isinstance(curve, DB.Line):
        raise ValueError(u"Вісь %s не пряма." % grid.Name)
    p = curve.GetEndPoint(0)
    d = curve.Direction
    return p.X, p.Y, d.X, d.Y


def _cross(a, b):
    ax, ay, adx, ady = a
    bx, by, bdx, bdy = b
    det = bdx * ady - adx * bdy
    t = (bdx * (by - ay) - bdy * (bx - ax)) / det
    return ax + t * adx, ay + t * ady


def zone_from_grids(grids, z_min, z_max):
    """Box bounded by two pairs of parallel grids and z_min..z_max (feet).

    Raises ValueError unless the grids form exactly two parallel pairs.
    """
    groups = []
    for grid in grids:
        line = _grid_line(grid)
        for group in groups:
            ref = group[0]
            if abs(ref[2] * line[3] - ref[3] * line[2]) < 1e-6:
                group.append(line)
                break
        else:
            groups.append([line])
    if len(groups) != 2 or any(len(g) != 2 for g in groups):
        raise ValueError(u"Оберіть 4 осі: дві паралельні в одному напрямку і дві в іншому.")
    points = [_cross(a, b) for a in groups[0] for b in groups[1]]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return Box(DB.XYZ(min(xs), min(ys), z_min), DB.XYZ(max(xs), max(ys), z_max))


class Source(object):
    """The host document or one loaded link instance."""

    def __init__(self, doc, link_instance=None):
        self.link = link_instance
        if link_instance is None:
            self.doc = doc
            self.transform = None
            self.key = HOST_KEY
            self.name = u"Модель"
        else:
            self.doc = link_instance.GetLinkDocument()
            self.transform = link_instance.GetTotalTransform()
            self.key = u"link:%d" % id_int(link_instance.Id)
            self.name = link_display_name(link_instance)


def link_display_name(link_instance):
    return link_instance.Name.split(u" : ")[0]


def loaded_links(doc):
    links = [li for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance)
             if li.GetLinkDocument() is not None]
    return sorted(links, key=link_display_name)


def _options():
    options = DB.Options()
    options.DetailLevel = DB.ViewDetailLevel.Fine
    return options


def element_solids(element, transform=None):
    solids = []

    def walk(geometry):
        for g in geometry:
            if isinstance(g, DB.Solid):
                if g.Volume > 1e-9:
                    solids.append(g)
            elif isinstance(g, DB.GeometryInstance):
                walk(g.GetInstanceGeometry())

    geometry = element.get_Geometry(_options())
    if geometry:
        walk(geometry)
    if transform is not None:
        solids = [DB.SolidUtils.CreateTransformed(s, transform) for s in solids]
    return solids


def solid_box(solid):
    bb = solid.GetBoundingBox()
    t = bb.Transform
    return Box.of_points([t.OfPoint(DB.XYZ(x, y, z))
                          for x in (bb.Min.X, bb.Max.X)
                          for y in (bb.Min.Y, bb.Max.Y)
                          for z in (bb.Min.Z, bb.Max.Z)])


def _connector_manager(element):
    if isinstance(element, DB.MEPCurve):
        return element.ConnectorManager
    if isinstance(element, DB.FamilyInstance) and element.MEPModel is not None:
        return element.MEPModel.ConnectorManager
    return None


class Networks(object):
    """Groups a document's elements into MEP networks joined through physical connectors."""

    def __init__(self, doc, limit=5000):
        self.doc = doc
        self.limit = limit
        self._root = {}

    def _neighbours(self, element):
        ids = set()
        manager = _connector_manager(element)
        if manager is None:
            return ids
        for connector in manager.Connectors:
            if connector.ConnectorType == DB.ConnectorType.Logical:
                continue
            try:
                connected = connector.IsConnected
            except Exception:
                continue
            if not connected:
                continue
            for ref in connector.AllRefs:
                owner = ref.Owner
                if owner is not None and owner.Id != element.Id and ref.ConnectorType != DB.ConnectorType.Logical:
                    ids.add(id_int(owner.Id))
        return ids

    def of(self, element):
        start = id_int(element.Id)
        if start in self._root:
            return self._root[start]
        seen = set([start])
        stack = [start]
        while stack and len(seen) < self.limit:
            current = self.doc.GetElement(make_id(stack.pop()))
            if current is None:
                continue
            for n in self._neighbours(current):
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        for s in seen:
            self._root[s] = start
        return start


def _family_text(element):
    """Upper-cased family and type name of a family instance, or an empty string."""
    if not isinstance(element, DB.FamilyInstance):
        return u""
    symbol = element.Symbol
    type_name = symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return (u"%s %s" % (symbol.FamilyName, type_name.AsString() if type_name is not None else u"")).upper()


def is_opening(element):
    """True for sleeve and opening families, recognised by the markers in their family or type name."""
    text = _family_text(element)
    return any(marker in text for marker in OPENING_MARKERS)


def is_ignored(element):
    """True for elements the user does not want in clash checks at all.

    Families matching IGNORED_MARKERS, and walls whose type name starts with IGNORED_WALL_PREFIXES
    (interior block walls, where an opening is cut freely) unless it contains KEPT_WALL_MARKERS (concrete).
    """
    if isinstance(element, DB.Wall):
        name = element.Name.upper()
        return name.startswith(IGNORED_WALL_PREFIXES) and not any(m in name for m in KEPT_WALL_MARKERS)
    text = _family_text(element)
    return any(marker in text for marker in IGNORED_MARKERS + (REGION_FAMILY.upper(),))


def _host_of(source, element):
    """The pipe/duct of an insulation or lining element; the element itself otherwise."""
    if isinstance(element, DB.InsulationLiningBase):
        host = source.doc.GetElement(element.HostElementId)
        if host is not None:
            return host
    return element


def _system_type_name(element):
    for bip in (DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM,
                DB.BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM):
        param = element.get_Parameter(bip)
        if param is not None and param.HasValue:
            text = param.AsValueString()
            if text and text != u"Undefined":
                return text
    return u""


def class_key(source, element):
    """Which network an element belongs to, for grouping: the System Type of pipes and ducts
    (insulation counts as its pipe/duct), "Cable Trays" for trays, the category otherwise;
    linked elements: "LINK:<category>"."""
    if source.key != HOST_KEY:
        return u"LINK:" + element.Category.Name
    element = _host_of(source, element)
    category = element.Category.Name if element.Category is not None else u""
    if category in TRAY_CATEGORIES:
        return u"Cable Trays"
    return _system_type_name(element) or category


def is_real(element):
    """False for elements that exist in the model but are not part of the built design:
    secondary design options, demolished elements, placeholder floor types."""
    option = element.DesignOption
    if option is not None and not option.IsPrimary:
        return False
    demolished = element.get_Parameter(DB.BuiltInParameter.PHASE_DEMOLISHED)
    if demolished is not None and demolished.HasValue and demolished.AsElementId() != DB.ElementId.InvalidElementId:
        return False
    if isinstance(element, DB.Floor):
        name = element.FloorType.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        text = (name.AsString() if name is not None else u"") or u""
        if any(marker in text.upper() for marker in IGNORED_FLOOR_TYPE_MARKERS):
            return False
    return True


class Item(object):
    def __init__(self, source, element, solids, box, network, workset):
        self.source = source
        self.element = element
        self.solids = solids
        self.box = box
        self.network = network
        self.workset = workset
        self.is_opening = is_opening(element)
        self.class_key = class_key(source, element)


def _zone_elements(source, zone):
    collector = (DB.FilteredElementCollector(source.doc).WhereElementIsNotElementType()
                 .WherePasses(DB.BoundingBoxIntersectsFilter(zone.to_outline(source.transform))))
    for element in collector:
        category = element.Category
        if category is None or element.ViewSpecific or category.CategoryType != DB.CategoryType.Model:
            continue
        if id_int(category.Id) in SKIP_CATEGORIES:
            continue
        if isinstance(element, (DB.ImportInstance, DB.RevitLinkInstance)):
            continue
        if is_ignored(element) or not is_real(element):
            continue
        yield element


def _workset_name(doc, element):
    if not doc.IsWorkshared:
        return u""
    return doc.GetWorksetTable().GetWorkset(element.WorksetId).Name


def zone_categories(source, zone):
    return sorted(set(e.Category.Name for e in _zone_elements(source, zone)))


def opening_boxes(source, zone):
    """Bounding boxes of the sleeves and openings of a source in the zone, on any workset."""
    boxes = []
    for element in _zone_elements(source, zone):
        if not is_opening(element):
            continue
        bb = element.get_BoundingBox(None)
        if bb is not None:
            boxes.append(Box(bb.Min, bb.Max))
    return boxes


def collect(source, zone, worksets=None, categories=None):
    """Elements of a source inside the zone that have solid geometry, with solids in host coordinates.

    worksets and categories are sets of names; None means no filter.
    """
    networks = Networks(source.doc)
    items = []
    for element in _zone_elements(source, zone):
        workset = _workset_name(source.doc, element)
        if worksets is not None and workset not in worksets:
            continue
        if categories is not None and element.Category.Name not in categories:
            continue
        solids = element_solids(element, source.transform)
        if not solids:
            continue
        box = solid_box(solids[0])
        for s in solids[1:]:
            box = box.union(solid_box(s))
        if not box.overlaps(zone):
            continue
        items.append(Item(source, element, solids, box, networks.of(_host_of(source, element)), workset))
    return items


def _intersection(a, b, zone):
    volume = 0.0
    hit_box = None
    for x in a.solids:
        for y in b.solids:
            try:
                r = DB.BooleanOperationsUtils.ExecuteBooleanOperation(x, y, DB.BooleanOperationsType.Intersect)
            except Exception:
                continue
            if r is None or r.Volume <= 1e-6:
                continue
            box = solid_box(r)
            if not zone.contains(box.center()):
                continue
            volume += r.Volume
            hit_box = box if hit_box is None else hit_box.union(box)
    return volume, hit_box


def _in_focus(item, focus):
    return item.source.key == HOST_KEY and item.element.Category.Name in focus


def _describe(item):
    element = item.element
    doc = item.source.doc
    type_element = doc.GetElement(element.GetTypeId())
    type_name = u""
    if type_element is not None:
        p = type_element.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        type_name = p.AsString() if p is not None else u""
    size = element.get_Parameter(DB.BuiltInParameter.RBS_CALCULATED_SIZE)
    return {
        "source": item.source.name,
        "link_id": id_int(item.source.link.Id) if item.source.link is not None else None,
        "id": id_int(element.Id),
        "category": element.Category.Name,
        "type": type_name or u"",
        "size": (size.AsString() if size is not None and size.HasValue else u"") or u"",
        "workset": item.workset,
        "system": item.class_key,
        "network": item.network if item.source.key == HOST_KEY else None,
    }


def find_clashes(items, zone, min_depth_mm=0.0, progress=None, focus=None, openings=(), stats=None):
    """Clashes between items as JSON-ready dicts, deepest first.

    Pairs from one network of one document and pairs of two linked elements are skipped, and so
    is every pair with a sleeve or opening. focus is a set of category names: a pair counts only
    if one of its host elements has such a category. A hit between a host element and a linked
    element is dropped when it lies inside one of the opening boxes (a pipe passing its sleeve);
    stats["in_openings"] counts those.
    depth_mm is the intersection volume divided by the largest face of its bounding box, so
    thin slivers where fittings touch come out at a few millimetres; shallower hits are dropped.
    """
    min_depth = to_ft(min_depth_mm)
    tolerance = to_ft(10)
    openings = [o.expanded(tolerance) for o in openings]
    in_openings = 0
    clashes = []
    count = len(items)
    for i in range(count):
        if progress is not None:
            progress(i, count)
        a = items[i]
        for j in range(i + 1, count):
            b = items[j]
            if a.source.key != HOST_KEY and b.source.key != HOST_KEY:
                continue
            if a.source.key == b.source.key and a.network == b.network:
                continue
            if a.is_opening or b.is_opening:
                continue
            if focus is not None and not (_in_focus(a, focus) or _in_focus(b, focus)):
                continue
            if not a.box.overlaps(b.box):
                continue
            volume, box = _intersection(a, b, zone)
            if box is None:
                continue
            if a.source.key != b.source.key and any(o.contains(box.center()) for o in openings):
                in_openings += 1
                continue
            size = box.hi - box.lo
            sides = sorted([size.X, size.Y, size.Z])
            depth = volume / (sides[1] * sides[2]) if sides[1] * sides[2] > 0 else 0.0
            if depth < min_depth:
                continue
            clashes.append({
                "a": _describe(a),
                "b": _describe(b),
                "volume_cm3": round(DB.UnitUtils.ConvertFromInternalUnits(volume, DB.UnitTypeId.CubicCentimeters), 1),
                "depth_mm": int(round(to_mm(depth))),
                "min": [box.lo.X, box.lo.Y, box.lo.Z],
                "max": [box.hi.X, box.hi.Y, box.hi.Z],
            })
    clashes.sort(key=lambda c: -c["volume_cm3"])
    if stats is not None:
        stats["in_openings"] = in_openings
    return clashes


def unique_by_element(clashes):
    """Keeps, in order, only clashes whose host elements have not appeared in an earlier kept clash.

    Linked elements do not count, so one beam cannot hide the other pipes crossing it.
    Each kept clash gets "also": the number of clashes dropped because of its elements.
    """
    owners = {}
    kept = []
    for clash in clashes:
        host_ids = [s["id"] for s in (clash["a"], clash["b"]) if s["link_id"] is None]
        owner = next((owners[i] for i in host_ids if i in owners), None)
        if owner is not None:
            owner["also"] += 1
            continue
        clash["also"] = 0
        kept.append(clash)
        for i in host_ids:
            owners[i] = clash
    return kept


def _side_identity(side):
    """Same element (linked) or same MEP network (host) -> same identity."""
    if side.get("link_id") is not None:
        return (u"link", side["link_id"], side["id"])
    return (u"net", side.get("network", side["id"]))


def _pair_key(clash):
    return tuple(sorted([clash["a"].get("system") or clash["a"]["category"],
                         clash["b"].get("system") or clash["b"]["category"]]))


def _center(clash):
    return [(clash["min"][i] + clash["max"][i]) * 0.5 for i in range(3)]


def group_clashes(clashes, near_mm=GROUP_NEAR_MM, far_mm=GROUP_FAR_MM):
    """Groups clashes that are one problem in one place.

    Two clashes join when they are between the same pair of networks (e.g. sprinkler x cable trays) and
    - their centres are within near_mm, or
    - one side is the same linked element / the same MEP network and centres are within far_mm
      (one pipe through three trays side by side; several branches touching the same pipe).
    Joining is transitive. Returns groups as clash-like dicts, biggest first: "a"/"b" of the deepest
    member, "min"/"max" around all members, "count", "systems", "members" (the clashes).
    """
    near, far = to_ft(near_mm), to_ft(far_mm)
    count = len(clashes)
    parent = list(range(count))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    keys = [_pair_key(c) for c in clashes]
    centers = [_center(c) for c in clashes]
    ids = [set([_side_identity(c["a"]), _side_identity(c["b"])]) for c in clashes]
    for i in range(count):
        for j in range(i + 1, count):
            if keys[i] != keys[j]:
                continue
            d = sum((centers[i][k] - centers[j][k]) ** 2 for k in range(3)) ** 0.5
            if d <= near or (d <= far and ids[i] & ids[j]):
                parent[root(i)] = root(j)

    buckets = {}
    for i in range(count):
        buckets.setdefault(root(i), []).append(clashes[i])
    groups = []
    for members in buckets.values():
        members.sort(key=lambda c: -c["volume_cm3"])
        top = members[0]
        groups.append({
            "a": top["a"],
            "b": top["b"],
            "min": [min(c["min"][k] for c in members) for k in range(3)],
            "max": [max(c["max"][k] for c in members) for k in range(3)],
            "depth_mm": max(c["depth_mm"] for c in members),
            "volume_cm3": round(sum(c["volume_cm3"] for c in members), 1),
            "count": len(members),
            "also": len(members) - 1,
            "systems": u" x ".join(_pair_key(top)),
            "members": members,
        })
    groups.sort(key=lambda g: (-g["count"], -g["volume_cm3"]))
    return groups


def host_ids_of(clash):
    """Host element ids of a clash or of all members of a group."""
    members = clash.get("members") or [clash]
    result = []
    for member in members:
        for side in (member["a"], member["b"]):
            if side["link_id"] is None and side["id"] not in result:
                result.append(side["id"])
    return result


def side_label(side):
    parts = [side["category"], side["type"], side["size"]]
    text = u" ".join(p for p in parts if p)
    return u"[%s] %s #%d" % (side["source"], text, side["id"])


def clash_name(group_index, member_index=None, group=None):
    """CLASH-001 for a group (or a one-clash group's clash), CLASH-001.3 for the 3rd clash of a group."""
    name = u"CLASH-%03d" % (group_index + 1)
    if member_index is not None and member_index >= 0 and group is not None and group.get("count", 1) > 1:
        name += u".%d" % (member_index + 1)
    return name


def member_label(group_index, member_index, member):
    return u"%d.%d  %s  x  %s  (%d мм)" % (group_index + 1, member_index + 1, side_label(member["a"]),
                                         side_label(member["b"]), member["depth_mm"])


def current_item(results):
    """(name, clash-or-group, label) shown by the navigator now, or (None, None, None).
    A group when the whole group is shown, one of its clashes when the user picked it in the list."""
    clashes = (results or {}).get("clashes") or []
    index = (results or {}).get("current", -1)
    if not 0 <= index < len(clashes):
        return None, None, None
    group = clashes[index]
    member = (results or {}).get("current_member", -1)
    members = group.get("members") or []
    if members and len(members) > 1 and 0 <= member < len(members):
        return clash_name(index, member, group), members[member], member_label(index, member, members[member])
    return clash_name(index), group, clash_label(index, group)


def clash_label(index, clash):
    if clash.get("members"):
        return u"%d. [%s] %d колізій: %s  x  %s  (%d мм)" % (
            index + 1, clash["systems"], clash["count"], side_label(clash["a"]), side_label(clash["b"]), clash["depth_mm"])
    also = clash.get("also", 0)
    return u"%d. %s  x  %s  (%d мм)%s" % (index + 1, side_label(clash["a"]), side_label(clash["b"]), clash["depth_mm"],
                                          u"  +ще %d" % also if also else u"")


def _read_json(path, default):
    if not os.path.isfile(path):
        return default
    with io.open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())


def _write_json(path, data):
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(unicode(text))


def load_settings():
    return _read_json(SETTINGS_FILE, {})


def save_settings(settings):
    _write_json(SETTINGS_FILE, settings)


def load_results():
    return _read_json(RESULTS_FILE, None)


def save_results(results):
    _write_json(RESULTS_FILE, results)


def _nav_view(doc):
    name = u"%s - %s" % (NAV_VIEW_PREFIX, doc.Application.Username)
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View3D):
        if not view.IsTemplate and view.Name == name:
            return view
    family_type = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                   if t.ViewFamily == DB.ViewFamily.ThreeDimensional][0]
    view = DB.View3D.CreateIsometric(doc, family_type.Id)
    view.Name = name
    return view


def _red_override(doc):
    red = DB.Color(255, 0, 0)
    solid = [p for p in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement)
             if p.GetFillPattern().IsSolidFill][0]
    override = DB.OverrideGraphicSettings()
    override.SetSurfaceForegroundPatternId(solid.Id)
    override.SetSurfaceForegroundPatternColor(red)
    override.SetProjectionLineColor(red)
    override.SetCutForegroundPatternId(solid.Id)
    override.SetCutForegroundPatternColor(red)
    return override


def _show_only_links(doc, view, link_ids):
    keep = set(link_ids)
    hide = List[DB.ElementId]()
    show = List[DB.ElementId]()
    for link in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        if id_int(link.Id) in keep:
            if link.IsHidden(view):
                show.Add(link.Id)
        elif not link.IsHidden(view) and link.CanBeHidden(view):
            hide.Add(link.Id)
    if hide.Count:
        view.HideElements(hide)
    if show.Count:
        view.UnhideElements(show)


def show_clash(uidoc, clash, previous_ids=(), link_ids=(), margin_mm=1000.0):
    """Frames the clash in the user's own 'CLASH Navigator' 3D view with a section box,
    selects the host model's elements of the clash and paints them red in that view.

    previous_ids are host element ids painted by the previous call; their overrides are cleared.
    link_ids are the link instances that stay visible; every other link and all scope boxes
    are hidden in the view.
    Changes the model: creates the view on first use, moves its section box and changes
    visibility and element overrides in it (one undo step). Returns the ids painted now.
    """
    doc = uidoc.Document
    box = Box(DB.XYZ(*clash["min"]), DB.XYZ(*clash["max"])).expanded(to_ft(margin_mm))
    host_ids = [make_id(value) for value in host_ids_of(clash) if doc.GetElement(make_id(value)) is not None]
    transaction = DB.Transaction(doc, u"Clash Navigator")
    transaction.Start()
    try:
        view = _nav_view(doc)
        if view.ViewTemplateId != DB.ElementId.InvalidElementId:
            view.ViewTemplateId = DB.ElementId.InvalidElementId
        section = DB.BoundingBoxXYZ()
        section.Min = box.lo
        section.Max = box.hi
        view.SetSectionBox(section)
        view.IsSectionBoxActive = True
        view.DetailLevel = DB.ViewDetailLevel.Fine
        scope_boxes = DB.ElementId(DB.BuiltInCategory.OST_VolumeOfInterest)
        if view.CanCategoryBeHidden(scope_boxes):
            view.SetCategoryHidden(scope_boxes, True)
        _show_only_links(doc, view, link_ids)
        for value in previous_ids:
            element_id = make_id(value)
            if doc.GetElement(element_id) is not None:
                view.SetElementOverrides(element_id, DB.OverrideGraphicSettings())
        override = _red_override(doc)
        for element_id in host_ids:
            view.SetElementOverrides(element_id, override)
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise
    uidoc.ActiveView = view
    uidoc.Selection.SetElementIds(List[DB.ElementId](host_ids))
    for ui_view in uidoc.GetOpenUIViews():
        if ui_view.ViewId == view.Id:
            ui_view.ZoomAndCenterRectangle(box.lo, box.hi)
    return [id_int(i) for i in host_ids]


def _region_symbol(doc):
    for symbol in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        if symbol.FamilyName == REGION_FAMILY:
            return symbol
    raise ValueError(u"У проєкті немає сімейства «%s». Завантажте його." % REGION_FAMILY)


def _region_workset(doc):
    """Id of the user workset REGION_WORKSET, created when missing. Needs an open transaction."""
    for workset in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset):
        if workset.Name == REGION_WORKSET:
            return workset.Id
    return DB.Workset.Create(doc, REGION_WORKSET).Id


def _level_below(levels, z):
    below = [l for l in levels if l.ProjectElevation <= z + 1e-6]
    if below:
        return max(below, key=lambda l: l.ProjectElevation)
    return min(levels, key=lambda l: l.ProjectElevation)


def is_arc_clash(clash):
    """True when one side of the clash is a linked wall, floor, beam or column (ARC_CATEGORIES)."""
    return any(side["link_id"] is not None and side["category"] in ARC_CATEGORIES for side in (clash["a"], clash["b"]))


def place_regions(doc, clashes, zone=None, margin_mm=REGION_MARGIN_MM):
    """Puts one Clash Region box around each clash, on the workset Clash (created when missing).

    The box is the clash intersection box grown by margin_mm on every side, so both elements
    pass through it. Earlier Clash Region boxes on that workset whose centre lies in zone are
    deleted first; boxes elsewhere stay. Sets Mark to CLASH-<number> and Comments to the clash
    label, ticks REGION_ARC_PARAM for clashes with linked walls, floors, beams and columns,
    and stores each box id in clash["region"]. Changes the model (one undo step).
    Returns (placed, deleted).
    """
    if not doc.IsWorkshared:
        raise ValueError(u"Модель не має воркcетів.")
    symbol = _region_symbol(doc)
    levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level))
    margin = to_ft(margin_mm)
    transaction = DB.Transaction(doc, u"Clash Regions")
    transaction.Start()
    try:
        workset_id = _region_workset(doc)
        old = List[DB.ElementId]()
        for instance in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
            if instance.Symbol.FamilyName != REGION_FAMILY or instance.WorksetId != workset_id:
                continue
            bb = instance.get_BoundingBox(None)
            if zone is None or (bb is not None and zone.contains((bb.Min + bb.Max) * 0.5)):
                old.Add(instance.Id)
        if old.Count:
            doc.Delete(old)
        if not symbol.IsActive:
            symbol.Activate()
        boxes = []
        for index, group in enumerate(clashes):
            members = group.get("members") or [group]
            for member_index, member in enumerate(members):
                boxes.append((clash_name(index, member_index, group), member, group, index))
        for name, clash, group, index in boxes:
            box = Box(DB.XYZ(*clash["min"]), DB.XYZ(*clash["max"])).expanded(margin)
            centre = box.center()
            size = box.hi - box.lo
            level = _level_below(levels, centre.Z)
            instance = doc.Create.NewFamilyInstance(DB.XYZ(centre.X, centre.Y, level.ProjectElevation), symbol, level,
                                                    DB.Structure.StructuralType.NonStructural)
            instance.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM).Set(workset_id.IntegerValue)
            instance.get_Parameter(DB.BuiltInParameter.INSTANCE_ELEVATION_PARAM).Set(centre.Z - level.ProjectElevation)
            instance.LookupParameter(u"Width").Set(size.X)
            instance.LookupParameter(u"Length").Set(size.Y)
            instance.LookupParameter(u"Height").Set(size.Z)
            instance.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK).Set(name)
            instance.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(clash_label(index, group)[:250])
            arc = instance.LookupParameter(REGION_ARC_PARAM)
            if arc is not None:
                arc.Set(1 if is_arc_clash(clash) else 0)
            clash["region"] = id_int(instance.Id)
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise
    return len(boxes), old.Count


def navigate(uidoc, step=None, index=None, member=None):
    """Shows the next (step=1) / previous (step=-1) group of the last check, or the given group
    (index), or one clash of it (member). Returns (header, label).

    Raises ValueError when there is no check for the active document.
    """
    results = load_results()
    if not results or not results.get("clashes"):
        raise ValueError(u"Немає результатів перевірки. Спершу запустіть «Clash у зоні».")
    if results.get("document") != uidoc.Document.Title:
        raise ValueError(u"Останню перевірку робили в моделі «%s»." % results.get("document"))
    clashes = results["clashes"]
    if index is None:
        index = (results.get("current", -1) + (step or 1)) % len(clashes)
    results["current"] = index
    results["current_member"] = member if member is not None else -1
    name, target, label = current_item(results)
    link_ids = results.get("links")
    if link_ids is None:
        link_ids = set(side["link_id"] for c in clashes for side in (c["a"], c["b"]) if side["link_id"] is not None)
    results["highlighted"] = show_clash(uidoc, target, results.get("highlighted", []), link_ids)
    save_results(results)
    return u"%s  (група %d з %d)" % (name, index + 1, len(clashes)), label
