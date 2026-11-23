# -*- coding: utf-8 -*-
"""Select everything that moves together with the selected pipe (horizontal or vertical move)."""
from pyrevit import revit, forms, script

from coordination import config
from coordination.pipes import move_set as M

doc = revit.doc
uidoc = revit.uidoc

starts = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
starts = [e for e in starts if e is not None and M.connectors(e)]
if not [e for e in starts if M.kind(e) == "curve"]:
    forms.alert(u"Виділіть трубу, повітропровід, лоток або кабелепровід і натисніть ще раз.", exitscript=True)

options = [M.MODE_NAMES[m] for m in M.MODES]
choice = forms.CommandSwitchWindow.show(options, message=u"Як посунете мережу?")
if not choice:
    script.exit()
mode = [m for m in M.MODES if M.MODE_NAMES[m] == choice][0]

settings = config.load()
result = M.collect(starts, mode, settings)
elements = list(result.moving.values())

if result.drops:
    heads = result.drop_terminal_count()
    others = len(result.drop_elements()) - heads
    message = u"Мережа доходить до {} кінцевих елементів (спринклерні головки, решітки, дифузори)".format(heads)
    if others:
        message += u" з опусками ({} труб і фітингів)".format(others)
    message += u".\n\nВиділити їх теж (посунуться разом з мережею)?"
    if forms.alert(message, yes=True, no=True):
        elements += result.drop_elements()

cfg = settings.get("move_set", {})
try:
    M.show(uidoc, elements, starts, float(cfg.get("section_box_margin_mm", 500)))
except Exception as error:
    forms.alert(u"Елементи виділено, але section box не вдалося поставити:\n{}".format(error))
