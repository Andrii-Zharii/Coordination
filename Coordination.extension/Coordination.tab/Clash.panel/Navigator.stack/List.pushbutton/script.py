# -*- coding: utf-8 -*-
"""Список колізій останньої перевірки: обрана колізія відкривається у 3D-виді CLASH Navigator."""
from pyrevit import revit, forms, script

from coordination.clash import core as gc

results = gc.load_results()
if not results or not results.get("clashes"):
    forms.alert(u"Немає результатів перевірки. Спершу запустіть «Clash у зоні».", exitscript=True)

labels = [gc.clash_label(i, c) for i, c in enumerate(results["clashes"])]
current = results.get("current", -1)
if 0 <= current < len(labels):
    labels[current] = u"► " + labels[current]
choice = forms.SelectFromList.show(labels, multiselect=False, width=1000, button_name=u"Показати",
                                   title=u"Колізії: %s (%s)" % (results.get("zone", u""), results.get("created", u"")))
if choice is None:
    script.exit()

try:
    header, text = gc.navigate(revit.uidoc, index=labels.index(choice))
except ValueError as error:
    forms.alert(unicode(error), exitscript=True)
forms.show_balloon(header, text)
