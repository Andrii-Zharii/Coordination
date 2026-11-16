# -*- coding: utf-8 -*-
"""Record the case after fixing the clash: screenshot, data, note and changes."""
from pyrevit import revit, forms, script

from coordination import cases, note_ui

doc = revit.doc
view = revit.active_view

state = cases.pending_case(doc)
if state is None:
    forms.alert(u"No case started. Press Before first, then fix the clash, then After.", exitscript=True)

answer = note_ui.ask_note(u"After - {}".format(state["case"]),
                          u"What was the problem, what did you do and why?")
if answer is None:
    script.exit()
note, voice_path = answer

changes, image_ok = cases.finish_case(doc, view, state, note, voice_path)

output = script.get_output()
output.set_title(u"Case {}".format(state["case"]))
output.print_md(u"## {} — resolved".format(state["case"]))
output.print_md(u"**Note:** {}".format(note or (u"voice note recorded" if voice_path else u"-")))
output.print_md(u"**Folder:** {}".format(state["case_dir"]))
if not image_ok:
    output.print_md(u"**Screenshot failed.**")
if changes:
    output.print_table([[c["id"], c["change"], c["what"], c.get("details", u"")] for c in changes],
                       columns=[u"Id", u"Change", u"Element", u"Details"])
else:
    output.print_md(u"No changes detected in the recorded area.")
