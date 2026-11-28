# -*- coding: utf-8 -*-
"""Відкрийте вид і натисніть. Видаляє з виду всі елементи на ворксеті PL, потім копіює з лінка PL усе, що видно на цьому виді, і вставляє на ворксет PL. Shift+Click — вибрати інший лінк або ворксет."""
from pyrevit import revit, DB, forms, script, EXEC_PARAMS
from coordination import link_copy as L

doc = revit.doc
view = revit.active_view
output = script.get_output()
config = script.get_config("Coordination.CopyFromLink")

if not doc.IsWorkshared:
    forms.alert(u"У цій моделі немає ворксетів.", exitscript=True)
if view is None or view.IsTemplate or isinstance(view, (DB.ViewSheet, DB.ViewSchedule)):
    forms.alert(u"Відкрийте план, розріз або 3D-вид, на якому треба оновити елементи.", exitscript=True)

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
old_ids, borrowed = L.host_elements_in_view(doc, view, workset)
new_src = L.link_elements_in_view(doc, view, link)

output.print_md(u"## Copy from Link: %s" % view.Name)
output.print_md(u"Ворксет **%s**, лінк **%s**." % (ws_name, link_name))
output.print_md(u"Видалити з виду (старі): **%d**. Скопіювати з лінка (нові): **%d**." % (len(old_ids), len(new_src)))
if borrowed:
    output.print_md(u"**Зайняті іншим користувачем, не будуть видалені (%d):** %s" % (
        len(borrowed), output.linkify(borrowed[:200])))
if not new_src:
    output.print_md(u"**З лінка на цьому виді нічого не видно.** Перевірте, що лінк увімкнений "
                    u"у Visibility/Graphics цього виду і потрапляє у view range.")

if not old_ids and not new_src:
    forms.alert(u"На виді немає ні елементів %s, ні видимих елементів лінка %s." % (ws_name, link_name),
                exitscript=True)

msg = (u"Вид «%s»\n\n1. Видалити старі елементи %s: %d\n2. Скопіювати з лінка %s і вставити: %d\n\n"
       u"Продовжити?" % (view.Name, ws_name, len(old_ids), link_name, len(new_src)))
if borrowed:
    msg += u"\n\n%d елементів зайняті іншим користувачем і залишаться." % len(borrowed)
if not new_src:
    msg += u"\n\nУВАГА: з лінка нічого не буде вставлено — старі елементи будуть просто видалені."
msg += u"\n\n(Shift+Click по кнопці — вибрати інший лінк або ворксет.)"
if not forms.alert(msg, yes=True, no=True):
    script.exit()

new_ids, errors, step = L.run(doc, old_ids, link, new_src, workset)
if errors:
    output.print_md(u"**Не виконано (крок: %s), модель не змінено:**" % step)
    for e in errors[:10]:
        output.print_md(u"- %s" % e)
    forms.alert(u"Не виконано на кроці «%s», модель не змінено:\n%s" % (step, u"\n".join(errors[:5])),
                exitscript=True)

if new_ids:
    revit.get_selection().set_to(new_ids)
output.print_md(u"### Готово: видалено %d, вставлено %d %s" % (
    len(old_ids), len(new_ids), output.linkify(new_ids[:200])))
forms.alert(u"Готово.\nВидалено старих: %d\nВставлено з %s: %d (виділені), ворксет %s." % (
    len(old_ids), link_name, len(new_ids), ws_name))
