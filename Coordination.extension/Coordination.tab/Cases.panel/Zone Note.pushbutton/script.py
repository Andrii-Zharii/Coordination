# -*- coding: utf-8 -*-
"""Write a note during a zone session: what you just did and why."""
from pyrevit import revit, forms, script

from coordination import session
from coordination.clash import core as gc

doc = revit.doc
view = revit.active_view

state = session.pending_session(doc)
if state is None:
    forms.alert(u"No zone session started. Press Start Zone first.", exitscript=True)

results = gc.load_results()
name, clash, label = gc.current_item(results) if results and results.get("document") == doc.Title else (None, None, None)
count = len(session.journal(state))
prompt = u"Note {} for the zone {}".format(count + 1, state["zone"])
if name:
    prompt += u"\nOpen in the navigator: {}".format(name)
prompt += u"\nWhat did you do and why?"

text = forms.ask_for_string(prompt=prompt, title=u"Zone Note")
if not text:
    script.exit()

selection = [gc.id_int(i) for i in revit.get_selection().element_ids]
number, image_ok = session.add_note(doc, view, state, text, selection)
message = u"Note {} saved{}.".format(number, u" ({})".format(name) if name else u"")
if not image_ok:
    message += u"\nScreenshot failed."
forms.show_balloon(u"Zone Note", message)
