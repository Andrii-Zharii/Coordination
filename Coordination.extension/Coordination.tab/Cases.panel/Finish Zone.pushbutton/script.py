# -*- coding: utf-8 -*-
"""Finish a zone session: find the changes, group them into nodes, ask one note per node."""
from System.Collections.Generic import List
from pyrevit import revit, DB, forms, script

from coordination import session
from coordination.clash import core as gc

doc = revit.doc
uidoc = revit.uidoc
view = revit.active_view

state = session.pending_session(doc)
if state is None:
    forms.alert(u"No zone session started. Press Start Zone before you begin the fixes.", exitscript=True)

with forms.ProgressBar(title=u"Finish: checking clashes... ({value} of {max_value})") as bar:
    result = session.analyse_session(doc, view, state, bar.update_progress)

nodes = result["nodes"]
notes = {}
asking = True
for index, node in enumerate(nodes):
    if not asking:
        break
    ids = session.node_element_ids(doc, node)
    if ids:
        id_list = List[DB.ElementId]([gc.make_id(i) for i in ids])
        uidoc.Selection.SetElementIds(id_list)
        try:
            uidoc.ShowElements(id_list)
        except Exception:
            pass
    lines = [u"Node {} of {} (selected in Revit): {} changed elements, "
             u"resolved {} clashes, new {}.".format(index + 1, len(nodes), len(node["changes"]),
                                                    len(node["resolved"]), len(node["created"]))]
    lines += [u"  " + line for line in session.node_summary(node, limit=4)]
    lines.append(u"Why did you do it this way? (Win+H = voice typing; Cancel = skip the rest)")
    note = forms.ask_for_string(prompt=u"\n".join(lines), title=u"Finish Zone")
    if note is None:
        asking = False
    else:
        notes[index] = note

general = forms.ask_for_string(
    prompt=u"Session: {} changed elements in {} nodes, clashes {} -> {}.\n"
           u"Anything about the zone as a whole? (optional)".format(
               len(result["changes"]), len(nodes), result["before_count"], result["after_count"]),
    title=u"Finish Zone")
folder = session.save_session(state, result, notes, general)

output = script.get_output()
output.set_title(u"Zone session")
output.print_md(u"## Zone session — {}".format(result["info"]["zone"]))
output.print_md(u"**Clashes:** {} → {}  \n**Changed elements:** {} in {} nodes  \n**Folder:** {}".format(
    result["before_count"], result["after_count"], len(result["changes"]), len(nodes), folder))
if not result["image_ok"]:
    output.print_md(u"**Screenshot failed.**")


def element_link(change):
    if doc.GetElement(gc.make_id(change["id"])) is None:
        return u"#{}".format(change["id"])
    return output.linkify(gc.make_id(change["id"]))


for index, node in enumerate(nodes):
    output.print_md(u"### Node {}".format(index + 1))
    output.print_md(u"**Note:** {}".format(notes.get(index) or u"-"))
    for clash in node["resolved"]:
        output.print_md(u"- resolved: {}".format(session.clash_text(clash)))
    for clash in node["created"]:
        output.print_md(u"- **new:** {}".format(session.clash_text(clash)))
    output.print_table([[element_link(c), c["change"], c["what"], c.get("details", u"")] for c in node["changes"]],
                       columns=[u"Id", u"Change", u"Element", u"Details"])

summary = result["summary"]
if summary["resolved_elsewhere"] or summary["created_elsewhere"]:
    output.print_md(u"### Not near any change")
    for clash in summary["resolved_elsewhere"]:
        output.print_md(u"- resolved: {}".format(session.clash_text(clash)))
    for clash in summary["created_elsewhere"]:
        output.print_md(u"- **new:** {}".format(session.clash_text(clash)))
output.print_md(u"**Remaining clashes:** {}. Run 'Clash у зоні' to refresh the list and the Clash Region boxes.".format(
    len(summary["remaining"])))
