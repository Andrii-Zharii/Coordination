# -*- coding: utf-8 -*-
"""Place opening families where pipes pass through linked walls / slabs without an opening."""
from pyrevit import revit, forms, script

from coordination import openings
from coordination.clash import core as gc

doc = revit.doc
results = gc.load_results()
if not results or not results.get("clashes") or results.get("document") != doc.Title:
    forms.alert(u"Спершу запустіть «Clash у зоні» (краще «План отворів»).", exitscript=True)

groups = results["clashes"]
CURRENT = u"Поточна група (з навігатора)"
ALL = u"Усі групи останньої перевірки ({})".format(len(groups))
options = [ALL]
current = results.get("current", -1)
if 0 <= current < len(groups):
    options.insert(0, CURRENT)
scope = forms.CommandSwitchWindow.show(options, message=u"Де ставити отвори?")
if not scope:
    script.exit()
chosen = [groups[current]] if scope == CURRENT else groups
offset = current if scope == CURRENT else 0

try:
    items, skipped = openings.plan(doc, chosen, offset)
except ValueError as error:
    forms.alert(u"{}".format(error), exitscript=True)

output = script.get_output()
output.set_title(u"Поставити отвори")
output.print_md(u"## Отвори для труб: {} до розстановки, пропущено {}".format(len(items), len(skipped)))
if items:
    output.print_table([[i["name"], output.linkify(i["pipe"].Id),
                         u"{:.0f}".format(i["pipe_mm"]), i["type"], u"{:.0f}".format(i["diameter"]), i["structure"]]
                        for i in items],
                       columns=[u"Колізія", u"Труба", u"Ø труби, мм", u"Тип отвору", u"Ø отвору, мм", u"Конструкція"])
if skipped:
    output.print_md(u"### Пропущено")
    output.print_table([[name, reason] for name, reason in skipped], columns=[u"Колізія", u"Причина"])
if not items:
    forms.alert(u"Нема чого ставити. Деталі у вікні pyRevit.", exitscript=True)

if not forms.alert(u"Поставити {} отворів на воркcеті «{}»?".format(len(items), openings.settings().get("workset", u"Openings")),
                   sub_msg=u"Список і розміри - у вікні pyRevit.", yes=True, no=True):
    script.exit()

placed, errors = openings.place(doc, items)
output.print_md(u"## Поставлено: {}".format(len(placed)))
if placed:
    output.print_md(u"Виділити всі: {}".format(output.linkify([gc.make_id(i) for _, i in placed], u"{} отворів".format(len(placed)))))
if errors:
    output.print_md(u"### Не вдалося")
    output.print_table([[name, error] for name, error in errors], columns=[u"Колізія", u"Помилка"])
output.print_md(u"Далі: **Оновити групу** або знову **Clash у зоні → План отворів** - проходи з новими отворами "
                u"перейдуть у «в порядку».")
forms.show_balloon(u"Поставити отвори", u"Поставлено {}, помилок {}.".format(len(placed), len(errors)))
