# -*- coding: utf-8 -*-
"""Skip the current clash: not a clash, or escalate to the contractors."""
from pyrevit import revit, forms, script

from coordination import cases
from coordination.clash import core as gc

doc = revit.doc
view = revit.active_view

NOT_A_CLASH = u"Not a clash"
ESCALATE = u"Escalate - discuss with contractors"

choice = forms.CommandSwitchWindow.show([NOT_A_CLASH, ESCALATE], message=u"Why skip this clash?")
if not choice:
    script.exit()
status = cases.STATUS_NOT_A_CLASH if choice == NOT_A_CLASH else cases.STATUS_ESCALATE

note = forms.ask_for_string(prompt=u"{}: why? (Win+H = voice typing)".format(choice), title=u"Skip")
if note is None:
    script.exit()

selection = [gc.id_int(i) for i in revit.get_selection().element_ids]
try:
    name, case_dir, image_ok = cases.skip_case(doc, view, selection, status, note)
except ValueError as error:
    forms.alert(u"{}".format(error), exitscript=True)

message = u"{}: {}".format(name, choice)
if not image_ok:
    message += u"\nScreenshot failed."
forms.show_balloon(u"Skip", message)
