# -*- coding: utf-8 -*-
"""Відкрийте план поверху і натисніть. Для кожної мережі поверху знаходить основний ворксет (на якому більшість її елементів) і переносить на нього елементи, що випадково опинились на іншому. Ворксети -DC не чіпає."""
from pyrevit import revit, DB, forms, script
from coordination import worksets as W

doc = revit.doc
output = script.get_output()

if not doc.IsWorkshared:
    forms.alert(u"У цій моделі немає ворксетів.", exitscript=True)

level = getattr(revit.active_view, "GenLevel", None)
if level is None:
    forms.alert(u"Відкрийте план поверху, який треба перевірити.", exitscript=True)

res = W.analyse(doc, level)
fixes = res["fixes"]

output.print_md(u"## Fix Worksets: %s" % level.Name)
output.print_md(u"Перевірено мереж: %d. Елементів не на своєму ворксеті: **%d**."
                % (res["networks"], len(fixes)))

if fixes:
    by_net = {}
    for r in fixes:
        by_net.setdefault((r["network"], r["to"]), []).append(r)
    rows = []
    for (net, to), items in sorted(by_net.items()):
        froms = sorted(set(r["from"] for r in items))
        rows.append([net, u", ".join(froms), to, len(items),
                     output.linkify([r["id"] for r in items])])
    output.print_table(rows, columns=[u"Мережа", u"Зараз", u"Буде", u"К-сть", u"Елементи"])

if res["borrowed"]:
    output.print_md(u"**Зайняті іншим користувачем, не будуть змінені (%d):** %s" % (
        len(res["borrowed"]), output.linkify([r["id"] for r in res["borrowed"]])))

if res["unclear"]:
    output.print_md(u"**Мережі без явного основного ворксету — перевірте вручну:**")
    for u_ in res["unclear"]:
        counts = u", ".join(u"%s: %d" % kv for kv in sorted(u_["counts"].items(), key=lambda kv: -kv[1]))
        output.print_md(u"- %s — %s %s" % (u_["network"], counts,
                                           output.linkify([DB.ElementId(i) for i in u_["ids"]][:200])))

if not fixes:
    forms.alert(u"Усі мережі поверху %s на своїх ворксетах.%s" % (
        level.Name, u"\nЄ що перевірити вручну — дивіться звіт." if res["unclear"] or res["borrowed"] else u""),
        exitscript=True)

if not forms.alert(u"Перенести %d елементів на основні ворксети їхніх мереж?\nСписок — у звіті pyRevit."
                   % len(fixes), yes=True, no=True):
    script.exit()

moved, failed = W.apply(doc, fixes)
if moved:
    revit.get_selection().set_to(moved)
output.print_md(u"### Перенесено: %d %s" % (len(moved), output.linkify(moved[:200])))
if failed:
    output.print_md(u"**Не вдалося змінити:** %s" % output.linkify(failed))
forms.alert(u"Перенесено на основний ворксет: %d елементів (виділені).%s" % (
    len(moved), u"\nНе вдалося: %d — дивіться звіт." % len(failed) if failed else u""))
