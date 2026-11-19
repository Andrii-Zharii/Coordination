# -*- coding: utf-8 -*-
"""Section box around the selected run up to the next turn (left/right, up/down or any)."""
from pyrevit import revit, DB, forms, script

from coordination.pipes import run_box as R

doc = revit.doc
uidoc = revit.uidoc

starts = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
starts = [e for e in starts if e is not None and R._connectors(e)]
if not starts:
    forms.alert(u"Виділіть трубу, повітропровід, лоток або кабелепровід і натисніть ще раз.", exitscript=True)

options = [R.MODE_NAMES["plan"], R.MODE_NAMES["vertical"], R.MODE_NAMES["any"]]
choice = forms.CommandSwitchWindow.show(options, message=u"До якого повороту?")
if not choice:
    script.exit()
mode = [key for key, name in R.MODE_NAMES.items() if name == choice][0]

elements = R.run_elements(starts, mode)
try:
    R.apply(uidoc, elements, starts)
except Exception as error:
    forms.alert(u"Не вдалося поставити section box:\n{}".format(error), exitscript=True)
