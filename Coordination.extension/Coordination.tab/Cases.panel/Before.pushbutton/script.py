# -*- coding: utf-8 -*-
"""Record a case before fixing the clash."""
from pyrevit import revit, forms, script

from coordination import cases
from coordination.clash import core as gc

doc = revit.doc
view = revit.active_view

pending = cases.pending_case(doc)
if pending is not None:
    if not forms.alert(u"Case {} was started with Before but not finished.\n\n"
                       u"Start a new case anyway? (the old one stays without After)".format(pending["case"]),
                       yes=True, no=True):
        script.exit()

selection = [gc.id_int(i) for i in revit.get_selection().element_ids]
try:
    name, case_dir, count, image_ok = cases.start_case(doc, view, selection)
except ValueError as error:
    forms.alert(u"{}".format(error), exitscript=True)

message = u"{}: recorded {} elements.".format(name, count)
if not image_ok:
    message += u"\nScreenshot failed (see before.json)."
forms.show_balloon(u"Before", message + u"\nNow fix it and press After (or Skip).")
