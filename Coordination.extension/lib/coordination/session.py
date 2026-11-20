# -*- coding: utf-8 -*-
"""Zone session: records a whole stretch of clash work in one zone, without per-clash buttons.

  Start  -> snapshot of all MEP in the zone of the last clash check (settings of
            "Clash у зоні") + the clash list at that moment + a screenshot.
  (user works freely: any order, any number of fixes)
  Finish -> snapshot again + the clash check again. Changes are found automatically and
            grouped into nodes (connected or close changed elements); each node gets the
            clashes it resolved or created and one short note from the user ("why").

Files: <repo>/cases/<model>/sessions/<start time>/
  session.json  zone, check settings, nodes, clash summary, notes
  start.json    data of all MEP in the zone + clashes at the start
  finish.json   data of the changed elements only + clashes at the finish
  start.jpg / finish.jpg    screenshots of the active view
  note.txt      notes per node
No model changes are made.
"""
import io
import os
import shutil
from datetime import datetime

from pyrevit import DB

from coordination import cases
from coordination.clash import core as gc

STATE_FILE = os.path.join(gc.DATA_DIR, "session_pending.json")
ZONE_MARGIN_MM = 500.0      # MEP recorded around the zone
NODE_GAP_MM = 300.0         # changed elements closer than this belong to one node
CLASH_NEAR_MM = 500.0       # a clash this close to a node is credited to it


# ---------------------------------------------------------------- zone and check

def _by_name(doc, cls, names):
    wanted = set(names)
    return [e for e in DB.FilteredElementCollector(doc).OfClass(cls) if e.Name in wanted]


def zone_from_settings(doc, settings):
    """(zone box, text) from the settings saved by the last 'Clash у зоні' run."""
    grids = _by_name(doc, DB.Grid, settings.get("grids", []))
    levels = _by_name(doc, DB.Level, [settings.get("level")])
    if len(grids) != 4 or not levels:
        raise ValueError(u"Run 'Clash у зоні' first: the zone (4 grids and a level) is taken from its last settings.")
    bottom, top = [float(v) for v in settings.get("heights", u"-1500 0").split()]
    level = levels[0]
    zone = gc.zone_from_grids(grids, level.ProjectElevation + gc.to_ft(bottom),
                              level.ProjectElevation + gc.to_ft(top))
    text = u"grids %s, level %s %+g..%+g mm" % (u" ".join(sorted(g.Name for g in grids)), level.Name, bottom, top)
    return zone, text


def run_check(doc, settings, zone, progress=None):
    """The same clash check as the 'Clash у зоні' button, with its last settings, no dialogs."""
    worksets = set(settings.get("worksets", []))
    focus = set(settings.get("focus", gc.DEFAULT_FOCUS_CATEGORIES))
    link_names = set(settings.get("links", []))
    link_categories = settings.get("link_categories")
    link_categories = set(link_categories) if link_categories is not None else None
    host = gc.Source(doc)
    items = gc.collect(host, zone, worksets=worksets) if worksets else []
    for link in gc.loaded_links(doc):
        if gc.link_display_name(link) in link_names:
            items += gc.collect(gc.Source(doc, link), zone, categories=link_categories)
    found = gc.find_clashes(items, zone, min_depth_mm=settings.get("min_depth", 10), progress=progress,
                            focus=focus, openings=gc.opening_boxes(host, zone), stats={})
    return found


def clash_key(clash):
    sides = sorted(((s["link_id"] or 0), s["id"]) for s in (clash["a"], clash["b"]))
    return u"%d:%d|%d:%d" % (sides[0][0], sides[0][1], sides[1][0], sides[1][1])


def _clash_host_ids(clash):
    return set(s["id"] for s in (clash["a"], clash["b"]) if s["link_id"] is None)


def _clash_box(clash):
    return gc.Box(DB.XYZ(*clash["min"]), DB.XYZ(*clash["max"]))


def clash_text(clash):
    return u"%s  x  %s" % (gc.side_label(clash["a"]), gc.side_label(clash["b"]))


# ---------------------------------------------------------------- snapshot

def _snapshot(doc, view, folder, stage, region, extra_ids, clashes):
    elements = {}
    for e in cases._collect_region(doc, region):
        elements[gc.id_int(e.Id)] = e
    for value in extra_ids:
        e = doc.GetElement(gc.make_id(value))
        if e is not None:
            elements[value] = e
    image_ok = False
    data = {"stage": stage, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": doc.Application.Username, "view": view.Name}
    try:
        image_ok = cases.export_view_image(doc, view, os.path.join(folder, stage + ".jpg"))
    except Exception as error:
        data["image_error"] = u"%s" % error
        shutil.rmtree(os.path.join(folder, "_export"), ignore_errors=True)
    data["elements"] = [cases.describe(doc, e) for e in sorted(elements.values(), key=lambda x: gc.id_int(x.Id))]
    data["clashes"] = clashes
    cases._write_json(os.path.join(folder, stage + ".json"), data)
    return data, image_ok


def flatten(clashes):
    """Single clashes of a list that may hold groups (results of 'Clash у зоні')."""
    result = []
    for clash in clashes:
        result.extend(clash.get("members") or [clash])
    return result


JOURNAL_FILE = "journal.json"


def add_note(doc, view, state, text, selection_ids):
    """Zone Note: a note written during the session, stored at once in the session folder
    (journal.json + journal.txt) with the time, the clash shown by the navigator, the selected
    elements and a screenshot. Returns (number, image_ok)."""
    folder = state["folder"]
    path = os.path.join(folder, JOURNAL_FILE)
    journal = cases._read_json(path) if os.path.isfile(path) else []
    number = len(journal) + 1
    entry = {"n": number, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "text": text,
             "selected": list(selection_ids), "view": view.Name}
    results = gc.load_results()
    if results and results.get("document") == doc.Title:
        name, clash, label = gc.current_item(results)
        if clash is not None:
            entry["clash"] = name
            entry["clash_label"] = label
    image = u"note_%02d.jpg" % number
    image_ok = False
    try:
        image_ok = cases.export_view_image(doc, view, os.path.join(folder, image))
    except Exception as error:
        entry["image_error"] = u"%s" % error
        shutil.rmtree(os.path.join(folder, "_export"), ignore_errors=True)
    if image_ok:
        entry["image"] = image
    journal.append(entry)
    cases._write_json(path, journal)
    with io.open(os.path.join(folder, "journal.txt"), "a", encoding="utf-8") as f:
        f.write(u"[%d] %s  %s\n%s\n\n" % (number, entry["time"], entry.get("clash", u""), text))
    return number, image_ok


def journal(state):
    path = os.path.join(state["folder"], JOURNAL_FILE)
    return cases._read_json(path) if os.path.isfile(path) else []


def pending_session(doc):
    if not os.path.isfile(STATE_FILE):
        return None
    state = cases._read_json(STATE_FILE)
    if state.get("document") != doc.Title or not os.path.isdir(state.get("folder", u"")):
        return None
    return state


def last_check(doc):
    """The results of the last 'Clash у зоні' run on this document, or None."""
    results = gc.load_results()
    if not results or results.get("document") != doc.Title:
        return None
    return results


def start_session(doc, view, progress=None, clashes=None):
    """Start: snapshot of the zone of the last clash check. Returns (state, element count, clash count, image ok).

    clashes: the clash list to start from (e.g. of the last check); None runs the check now.
    """
    settings = gc.load_settings()
    zone, zone_text = zone_from_settings(doc, settings)
    if clashes is None:
        clashes = run_check(doc, settings, zone, progress)
    else:
        clashes = flatten(clashes)
    started = datetime.now()
    folder = os.path.join(cases.CASES_DIR, cases._safe_name(doc.Title), "sessions",
                          started.strftime("%Y-%m-%d %H-%M"))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    region = zone.expanded(gc.to_ft(ZONE_MARGIN_MM))
    data, image_ok = _snapshot(doc, view, folder, "start", [region], [], clashes)
    info = {"model": doc.Title, "user": doc.Application.Username, "started": data["time"],
            "zone": zone_text, "zone_box": cases._box_json(zone), "check_settings": settings,
            "status": "open"}
    cases._write_json(os.path.join(folder, "session.json"), info)
    state = {"document": doc.Title, "folder": folder, "zone": zone_text,
             "region": cases._box_json(region), "started": data["time"]}
    if not os.path.isdir(gc.DATA_DIR):
        os.makedirs(gc.DATA_DIR)
    cases._write_json(STATE_FILE, state)
    return state, len(data["elements"]), len(clashes), image_ok


# ---------------------------------------------------------------- nodes

def _element_box(data):
    if "bbox" not in data:
        return None
    lo, hi = data["bbox"]
    return gc.Box(DB.XYZ(*[gc.to_ft(v) for v in lo]), DB.XYZ(*[gc.to_ft(v) for v in hi]))


def group_nodes(changes, before, after):
    """Splits the changes into nodes: elements that are connected (before or after) or closer
    than NODE_GAP_MM end up in one node. Returns a list of {"ids", "changes", "box"}."""
    old = dict((e["id"], e) for e in before)
    new = dict((e["id"], e) for e in after)
    ids = [c["id"] for c in changes]
    parent = dict((i, i) for i in ids)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    boxes = {}
    for i in ids:
        for data in (old.get(i), new.get(i)):
            if data is None:
                continue
            for other in data.get("connected_to", []):
                if other in parent:
                    join(i, other)
            box = _element_box(data)
            if box is not None:
                boxes[i] = box if i not in boxes else boxes[i].union(box)
    gap = gc.to_ft(NODE_GAP_MM)
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a, b = boxes.get(ids[x]), boxes.get(ids[y])
            if a is not None and b is not None and a.expanded(gap).overlaps(b):
                join(ids[x], ids[y])
    groups = {}
    for change in changes:
        groups.setdefault(find(change["id"]), []).append(change)
    nodes = []
    for members in groups.values():
        member_ids = set(c["id"] for c in members)
        member_boxes = [boxes[i] for i in member_ids if i in boxes]
        box = None
        for b in member_boxes:
            box = b if box is None else box.union(b)
        nodes.append({"ids": member_ids, "changes": members, "box": box})
    nodes.sort(key=lambda n: (n["box"].center().X, n["box"].center().Y) if n["box"] is not None else (0, 0))
    return nodes


def _credit(clash, nodes):
    """Index of the node a clash belongs to: it shares an element, or is the nearest within CLASH_NEAR_MM."""
    host_ids = _clash_host_ids(clash)
    for index, node in enumerate(nodes):
        if host_ids & node["ids"]:
            return index
    box = _clash_box(clash)
    near = gc.to_ft(CLASH_NEAR_MM)
    best, best_distance = None, None
    for index, node in enumerate(nodes):
        if node["box"] is None or not node["box"].expanded(near).overlaps(box):
            continue
        distance = node["box"].center().DistanceTo(box.center())
        if best is None or distance < best_distance:
            best, best_distance = index, distance
    return best


def node_summary(node, limit=6):
    lines = []
    for change in node["changes"][:limit]:
        text = u"%s %s" % (change["change"], change["what"])
        if change.get("details"):
            text += u": " + change["details"]
        lines.append(text)
    if len(node["changes"]) > limit:
        lines.append(u"... and %d more" % (len(node["changes"]) - limit))
    return lines


# ---------------------------------------------------------------- finish

def analyse_session(doc, view, state, progress=None):
    """Finish, step 1: snapshot again, check again, diff and nodes. Nothing is saved as final yet."""
    folder = state["folder"]
    info = cases._read_json(os.path.join(folder, "session.json"))
    start = cases._read_json(os.path.join(folder, "start.json"))
    settings = info["check_settings"]
    zone = cases._box_from_json(info["zone_box"])
    clashes = run_check(doc, settings, zone, progress)
    region = cases._box_from_json(state["region"])
    finish, image_ok = _snapshot(doc, view, folder, "finish", [region],
                                 [e["id"] for e in start["elements"]], clashes)
    changes = cases.diff(start["elements"], finish["elements"])
    nodes = group_nodes(changes, start["elements"], finish["elements"])
    changed_ids = set(c["id"] for c in changes)
    finish["elements"] = [e for e in finish["elements"] if e["id"] in changed_ids]  # unchanged ones are in start.json
    cases._write_json(os.path.join(folder, "finish.json"), finish)

    before = dict((clash_key(c), c) for c in flatten(start["clashes"]))
    after = dict((clash_key(c), c) for c in clashes)
    for node in nodes:
        node["resolved"] = []
        node["created"] = []
    summary = {"resolved_elsewhere": [], "created_elsewhere": [],
               "remaining": [after[k] for k in after if k in before]}
    for key in before:
        if key in after:
            continue
        index = _credit(before[key], nodes)
        (nodes[index]["resolved"] if index is not None else summary["resolved_elsewhere"]).append(before[key])
    for key in after:
        if key in before:
            continue
        index = _credit(after[key], nodes)
        (nodes[index]["created"] if index is not None else summary["created_elsewhere"]).append(after[key])
    return {"info": info, "changes": changes, "nodes": nodes, "summary": summary,
            "before_count": len(before), "after_count": len(after), "image_ok": image_ok}


def node_element_ids(doc, node):
    """Ids of the node's elements that still exist (for selecting them in Revit)."""
    return [i for i in sorted(node["ids"]) if doc.GetElement(gc.make_id(i)) is not None]


def save_session(state, result, notes, general_note):
    """Finish, step 2: stores the nodes with the user's notes and closes the session."""
    folder = state["folder"]
    info = result["info"]
    nodes_json = []
    for index, node in enumerate(result["nodes"]):
        nodes_json.append({
            "node": index + 1,
            "ids": sorted(node["ids"]),
            "bbox_mm": ([cases._xyz(node["box"].lo), cases._xyz(node["box"].hi)] if node["box"] is not None else None),
            "changes": node["changes"],
            "resolved_clashes": node["resolved"],
            "new_clashes": node["created"],
            "note": notes.get(index, u""),
        })
    summary = result["summary"]
    info.update({
        "status": "closed",
        "finished": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "clashes_before": result["before_count"],
        "clashes_after": result["after_count"],
        "nodes": nodes_json,
        "resolved_elsewhere": summary["resolved_elsewhere"],
        "new_clashes_elsewhere": summary["created_elsewhere"],
        "remaining_clashes": summary["remaining"],
        "note": general_note or u"",
        "journal": journal(state),
    })
    cases._write_json(os.path.join(folder, "session.json"), info)
    lines = [u"Zone: %s" % info["zone"], u"Clashes: %d -> %d" % (result["before_count"], result["after_count"]),
             u"", u"[session] %s" % (general_note or u"")]
    for entry in info["journal"]:
        lines.append(u"[journal %d] %s %s: %s" % (entry["n"], entry["time"], entry.get("clash", u""), entry["text"]))
    for node in nodes_json:
        lines.append(u"")
        lines.append(u"[node %d] resolved %d, new %d, changed %d elements" % (
            node["node"], len(node["resolved_clashes"]), len(node["new_clashes"]), len(node["changes"])))
        lines.append(node["note"] or u"-")
    with io.open(os.path.join(folder, "note.txt"), "w", encoding="utf-8") as f:
        f.write(u"\n".join(lines) + u"\n")
    if os.path.isfile(STATE_FILE):
        os.remove(STATE_FILE)
    return folder


def discard_session():
    if os.path.isfile(STATE_FILE):
        os.remove(STATE_FILE)
