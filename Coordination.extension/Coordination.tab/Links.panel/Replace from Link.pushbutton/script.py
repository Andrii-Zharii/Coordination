# -*- coding: utf-8 -*-
"""Відкрийте план поверху і натисніть. Видаляє з виду все на ворксеті PL і вставляє на це місце копію з лінка PL (те, що потрапляє у view range). Shift+Click — вибрати інший лінк або ворксет."""
from pyrevit import revit, DB, forms, script, EXEC_PARAMS
from coordination import link_copy as L

doc = revit.doc
view = revit.active_view
output = script.get_output()
config = script.get_config("Coordination.ReplaceFromLink")

if not doc.IsWorkshared:
    forms.alert(u"У цій моделі немає ворксетів.", exitscript=True)
if not isinstance(view, DB.ViewPlan) or view.GenLevel is None:
    forms.alert(u"Відкрийте план поверху.", exitscript=True)

links = L.loaded_links(doc)
if not links:
    forms.alert(u"У моделі немає завантажених лінків.", exitscript=True)

# Remembered choice; Shift+Click or a missing link/workset asks again.
ws_name = config.get_option("workset", "PL")
link_title = config.get_option("link", "")
workset = L.workset_by_name(doc, ws_name)
by_title = dict(links)
if EXEC_PARAMS.config_mode or workset is None or link_title not in by_title:
    names = sorted(w.Name for w in L.user_worksets(doc))
    pick = forms.SelectFromList.show(names, title=u"Який ворксет замінити?", button_name=u"Далі")
    if not pick:
        script.exit()
    ws_name = pick
    workset = L.workset_by_name(doc, ws_name)
    titles = sorted(by_title)
    guess = [t for t in titles if ws_name.upper() in t.upper()]
    titles = guess + [t for t in titles if t not in guess]
    pick = forms.SelectFromList.show(titles, title=u"З якого лінка брати %s?" % ws_name,
                                     button_name=u"Вибрати")
    if not pick:
        script.exit()
    link_title = pick
    config.set_option("workset", ws_name)
    config.set_option("link", link_title)
    script.save_config()

link = by_title[link_title]
p = L.plan(doc, view, workset, link)
z0, z1, xy = p["band"]
lvl = view.GenLevel.ProjectElevation

output.print_md(u"## Replace from Link: %s" % view.Name)
output.print_md(u"Ворксет **%s**, лінк **%s**. View range: від %.0f до %.0f мм від рівня %s%s." % (
    ws_name, link_title, (z0 - lvl) * 304.8, (z1 - lvl) * 304.8, view.GenLevel.Name,
    u", в межах crop box" if xy else u", весь план (crop box вимкнений)"))
output.print_md(u"Буде видалено: **%d**, буде вставлено з лінка: **%d**." % (
    len(p["to_delete"]), len(p["to_copy"])))
if p["borrowed"]:
    output.print_md(u"**Зайняті іншим користувачем, не будуть видалені (%d):** %s" % (
        len(p["borrowed"]), output.linkify(p["borrowed"][:200])))
if p["sticking"]:
    output.print_md(u"З лінка %d елементів виходять за view range (стояки тощо) — вони вставляться цілком."
                    % p["sticking"])

if not p["to_delete"] and not p["to_copy"]:
    forms.alert(u"На цьому виді немає ні елементів %s, ні елементів лінка у view range." % ws_name,
                exitscript=True)

msg = u"Видалити %d елементів %s з виду «%s»\nі вставити %d елементів з лінка %s?" % (
    len(p["to_delete"]), ws_name, view.Name, len(p["to_copy"]), link_title)
if p["borrowed"]:
    msg += u"\n\n%d елементів зайняті іншим користувачем і залишаться — можливі дублікати." % len(p["borrowed"])
msg += u"\n\nShift+Click по кнопці — вибрати інший лінк або ворксет."
if not forms.alert(msg, yes=True, no=True):
    script.exit()

new_ids, errors = L.apply(doc, p, workset)
if errors:
    output.print_md(u"**Не виконано, модель не змінено:** " + u"; ".join(errors[:5]))
    forms.alert(u"Revit не прийняв зміни, модель не змінено:\n" + u"\n".join(errors[:5]), exitscript=True)

revit.get_selection().set_to(new_ids)
output.print_md(u"### Готово: видалено %d, вставлено %d %s" % (
    len(p["to_delete"]), len(new_ids), output.linkify(new_ids[:200])))
forms.alert(u"Готово.\nВидалено: %d\nВставлено з %s: %d (виділені), ворксет %s." % (
    len(p["to_delete"]), link_title, len(new_ids), ws_name))
