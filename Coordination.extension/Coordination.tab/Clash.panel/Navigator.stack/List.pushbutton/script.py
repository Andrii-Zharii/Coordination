# -*- coding: utf-8 -*-
"""Список груп колізій останньої перевірки. Оберіть групу, потім - усю групу або одну її колізію."""
from pyrevit import revit, forms, script

from coordination.clash import core as gc

results = gc.load_results()
if not results or not results.get("clashes"):
    forms.alert(u"Немає результатів перевірки. Спершу запустіть «Clash у зоні».", exitscript=True)

groups = results["clashes"]
labels = [gc.clash_label(i, c) for i, c in enumerate(groups)]
current = results.get("current", -1)
if 0 <= current < len(labels):
    labels[current] = u"► " + labels[current]
choice = forms.SelectFromList.show(labels, multiselect=False, width=1100, button_name=u"Далі",
                                   title=u"Групи колізій: %s (%s)" % (results.get("zone", u""), results.get("created", u"")))
if choice is None:
    script.exit()
index = labels.index(choice)

member = None
members = groups[index].get("members") or []
if len(members) > 1:
    whole = u"Уся група: %d колізій" % len(members)
    options = [whole] + [gc.member_label(index, j, m) for j, m in enumerate(members)]
    picked = forms.SelectFromList.show(options, multiselect=False, width=1100, button_name=u"Показати",
                                       title=gc.clash_label(index, groups[index]))
    if picked is None:
        script.exit()
    if picked != whole:
        member = options.index(picked) - 1

try:
    header, text = gc.navigate(revit.uidoc, index=index, member=member)
except ValueError as error:
    forms.alert(unicode(error), exitscript=True)
forms.show_balloon(header, text)
