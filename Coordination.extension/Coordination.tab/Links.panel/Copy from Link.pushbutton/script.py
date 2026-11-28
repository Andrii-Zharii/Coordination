# -*- coding: utf-8 -*-
"""Відкрийте план поверху і натисніть. Видаляє з виду всі елементи на ворксеті PL, потім копіює з лінка PL усе, що видно на цьому виді, і вставляє на ворксет PL. Стояки через кілька поверхів не чіпає, а порівнює з лінком. Shift+Click — вибрати інший лінк або ворксет."""
from pyrevit import revit, DB, forms, script, EXEC_PARAMS
from coordination import link_copy as L

doc = revit.doc
view = revit.active_view
output = script.get_output()
config = script.get_config("Coordination.CopyFromLink")

if not doc.IsWorkshared:
    forms.alert(u"У цій моделі немає ворксетів.", exitscript=True)
if not isinstance(view, DB.ViewPlan) or view.GenLevel is None:
    forms.alert(u"Відкрийте план поверху, на якому треба оновити елементи.", exitscript=True)

links = L.loaded_links(doc)
if not links:
    forms.alert(u"У моделі немає завантажених лінків.", exitscript=True)
by_name = dict(links)

# Remembered choice; Shift+Click or a missing link/workset asks again.
ws_name = config.get_option("workset", "PL")
link_name = config.get_option("link", "")
workset = L.workset_by_name(doc, ws_name)
if EXEC_PARAMS.config_mode or workset is None or link_name not in by_name:
    names = sorted(w.Name for w in L.user_worksets(doc))
    if ws_name in names:
        names = [ws_name] + [n for n in names if n != ws_name]
    pick = forms.SelectFromList.show(names, title=u"Елементи якого ворксету оновити?", button_name=u"Далі")
    if not pick:
        script.exit()
    ws_name = pick
    workset = L.workset_by_name(doc, ws_name)
    titles = sorted(by_name)
    guess = [t for t in titles if ws_name.upper() in t.upper()]
    titles = guess + [t for t in titles if t not in guess]
    pick = forms.SelectFromList.show(titles, title=u"З якого лінка копіювати?", button_name=u"Вибрати")
    if not pick:
        script.exit()
    link_name = pick
    config.set_option("workset", ws_name)
    config.set_option("link", link_name)
    script.save_config()

link = by_name[link_name]
p = L.plan(doc, view, workset, link)

output.print_md(u"## Copy from Link: %s" % view.Name)
output.print_md(u"Ворксет **%s**, лінк **%s**." % (ws_name, link_name))
output.print_md(u"Видалити з виду (старі): **%d**. Скопіювати з лінка (нові): **%d**." % (
    len(p["delete"]), len(p["copy"])))
output.print_md(u"Стояки через кілька поверхів не чіпаються: у моделі %d стояків (%d елементів залишаться), "
                u"у лінку %d стояків (%d елементів не копіюються)." % (
                    len(p["host_risers"]), p["kept_count"], len(p["link_risers"]), p["skipped_count"]))
if p["borrowed"]:
    output.print_md(u"**Зайняті іншим користувачем, не будуть видалені (%d):** %s" % (
        len(p["borrowed"]), output.linkify(p["borrowed"][:200])))
if not p["copy"]:
    output.print_md(u"**З лінка на цьому виді нічого не видно.** Перевірте, що лінк увімкнений "
                    u"у Visibility/Graphics цього виду і потрапляє у view range.")

# Risers: model vs link.
moved = [c for c in p["compare"] if c[0] == "moved"]
only_host = [c for c in p["compare"] if c[0] == "only_host"]
only_link = [c for c in p["compare"] if c[0] == "only_link"]


def riser_text(r):
    return u"%s ø%d" % (r.system or u"?", r.size) if r.size else (r.system or u"?")


if moved or only_host or only_link:
    output.print_md(u"### Стояки: модель vs лінк")
    rows = []
    for kind, h, l, d in moved:
        rows.append([u"зсунутий на %.0f мм" % d, riser_text(h), output.linkify(h.first),
                     u"%d" % L.idv(l.first)])
    for kind, h, l, d in only_host:
        rows.append([u"немає в лінку", riser_text(h), output.linkify(h.first), u"—"])
    for kind, h, l, d in only_link:
        rows.append([u"новий у лінку, немає в моделі", riser_text(l), u"—", u"%d" % L.idv(l.first)])
    output.print_table(rows, columns=[u"Стан", u"Стояк", u"У моделі", u"Id у лінку"])
    output.print_md(u"Стояки не змінено — перевірте і виправте їх вручну.")
else:
    output.print_md(u"Стояки моделі й лінка збігаються.")

if not p["delete"] and not p["copy"]:
    forms.alert(u"На виді немає ні елементів %s, ні видимих елементів лінка %s." % (ws_name, link_name),
                exitscript=True)

msg = (u"Вид «%s»\n\n1. Видалити старі елементи %s: %d\n2. Скопіювати з лінка %s і вставити: %d\n"
       u"Стояки через кілька поверхів не чіпаються." % (
           view.Name, ws_name, len(p["delete"]), link_name, len(p["copy"])))
if moved or only_host or only_link:
    msg += u"\n\nСтояки, що відрізняються від лінка: %d — дивіться звіт." % (
        len(moved) + len(only_host) + len(only_link))
if p["borrowed"]:
    msg += u"\n\n%d елементів зайняті іншим користувачем і залишаться." % len(p["borrowed"])
if not p["copy"]:
    msg += u"\n\nУВАГА: з лінка нічого не буде вставлено — старі елементи будуть просто видалені."
msg += u"\n\nПродовжити?\n(Shift+Click по кнопці — вибрати інший лінк або ворксет.)"
if not forms.alert(msg, yes=True, no=True):
    script.exit()

res = L.run(doc, p, link, workset)
if res["errors"]:
    output.print_md(u"**Не виконано (крок: %s), модель не змінено:**" % res["step"])
    for e in sorted(set(res["errors"]))[:10]:
        output.print_md(u"- %s" % e)
    forms.alert(u"Не виконано на кроці «%s», модель не змінено:\n%s" % (
        res["step"], u"\n".join(sorted(set(res["errors"]))[:5])), exitscript=True)

new_ids = res["new_ids"]
if new_ids:
    revit.get_selection().set_to(new_ids)
output.print_md(u"### Готово: видалено %d, вставлено %d %s" % (
    len(p["delete"]), len(new_ids), output.linkify(new_ids[:200])))
if res["disconnected"]:
    output.print_md(u"Від'єднано від стояків лінка: %d з'єднань; знову приєднано до стояків моделі: %d."
                    % (res["disconnected"], res["joined"]))
msg = u"Готово.\nВидалено старих: %d\nВставлено з %s: %d (виділені), ворксет %s." % (
    len(p["delete"]), link_name, len(new_ids), ws_name)
if res["disconnected"]:
    msg += u"\n\nВідгалуження від'єднано від стояків лінка; до стояків моделі приєднано: %d.\nПеревірте з'єднання біля стояків." % res["joined"]
if moved or only_host or only_link:
    msg += u"\nСтояки, що відрізняються від лінка, — у звіті pyRevit."
forms.alert(msg)
