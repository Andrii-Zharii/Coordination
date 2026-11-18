# -*- coding: utf-8 -*-
"""Розносить паралельні лотки Т-вузла на різні рівні. Виділіть трійки або лотки вузла, виберіть варіант зі списку перевірених на колізії. Не нижче 2300, не в бетон, усе на workset EL."""
from pyrevit import revit, DB, forms, script
from coordination.trays import tees as T
from coordination.trays import tee_ui as UI

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

ids = [i.IntegerValue for i in uidoc.Selection.GetElementIds()]
if not ids:
    forms.alert("Виділіть трійки або лотки Т-вузла.", exitscript=True)

groups = T.junctions_for(doc, ids)
if not groups:
    forms.alert("У виділеному не знайдено Т-вузла з 2-3 паралельних лотків.", exitscript=True)

grids = T.grids_of(doc)
if len(groups) > 1:
    names = {}
    for g in groups:
        d = T.describe(doc, g, grids)
        names["%s  %s  (%s)" % (d["level"], d["bay"], ", ".join(n.split()[0] for n in d["trays"]))] = g
    pick = forms.SelectFromList.show(sorted(names), title="Який вузол обробити?", button_name="Далі")
    if not pick:
        script.exit()
    g = names[pick]
else:
    g = groups[0]

info = T.describe(doc, g, grids)
if len(g) > 3:
    forms.alert("Вузол з %d лотків поки не підтримується." % len(g), exitscript=True)

titles = script.get_config("AgentTools.SplitTee").get_option("links", T.DEFAULT_LINKS)
links = T.links_of(doc, titles)
missing = [t for t in titles if t not in [ld.Title for ld, _ in links]]

with forms.ProgressBar(title="Перевіряю варіанти {value} з {max_value}", cancellable=True) as pb:
    def progress(i, n):
        if pb.cancelled:
            return False
        pb.update_progress(i + 1, n)
    opts, obstacles = T.evaluate(doc, g, links, progress=progress)

output.print_md("## Т-вузол %s, %s, %d мм" % (info["bay"], info["level"], info["offset_mm"]))
output.print_md("Лотки від магістралі з боку відгалужень: **%s**" % ", ".join(info["trays"]))
output.print_md("Перевірка колізій: хост-модель, %s" % (", ".join(ld.Title for ld, _ in links) or "без лінків"))
if missing:
    output.print_md("**Не завантажені лінки, їх не перевірено:** %s" % ", ".join(missing))


def show(o):
    mark = {"ok": "✔", "soft": "⚠", "est": "◌", "hard": "✖", "fail": "✖", "skip": "–"}[o["status"]]
    extra = ""
    if o["soft"]:
        extra = " — м'які колізії: " + ", ".join("%s %s %d" % (s[0], s[2], s[1]) for s in o["soft"][:4])
    elif o.get("why"):
        extra = " — " + o["why"]
    output.print_md("%s `%s`%s" % (mark, o["label"], extra))


for o in opts:
    show(o)


title = "Split Tee: вузол %s, %s, %d мм" % (info["bay"], info["level"], info["offset_mm"])
chosen = UI.Chooser(doc, g, title, opts, obstacles, __revit__.MainWindowHandle).show()
if chosen is None:
    script.exit()

res = T.apply_scheme(doc, g, chosen["scheme"], obstacles, chosen.get("low", False))
if not res["applied"]:
    output.print_md("**Не застосовано:** " + "; ".join(res["errors"]))
    forms.alert("Revit не прийняв цей варіант, модель не змінено.\n" + "\n".join(res["errors"]), exitscript=True)

created = [DB.ElementId(i) for i in res["created"]]
revit.get_selection().set_to(created)
try:
    uidoc.ShowElements(revit.get_selection().element_ids)
except Exception:
    pass

output.print_md("### Застосовано: `%s`" % chosen["label"])
if chosen.get("low"):
    output.print_md("**Застосовано всупереч правилу: нижче 2300 мм від рівня.**")
if chosen["hard"]:
    output.print_md("**Застосовано всупереч правилу, зачіпає бетон:**")
    for src, eid, cat in chosen["hard"]:
        ref = output.linkify(DB.ElementId(eid)) if src == "host" else "%d" % eid
        output.print_md("- %s %s %s" % (src, cat, ref))
if obstacles.excused:
    output.print_md("Не вважалось колізією (лоток іде через отвір або стіну, яку вже перетинав): %s" % ", ".join(
        "%s %s %d" % (src, cat, eid) for src, eid, cat in sorted(obstacles.excused)))
output.print_md("Нових і змінених елементів: %d %s" % (len(created), output.linkify(created[:200])))
if chosen["soft"]:
    output.print_md("**Перевірте вручну м'які колізії:**")
    for src, eid, cat in chosen["soft"]:
        ref = output.linkify(DB.ElementId(eid)) if src == "host" else "%d" % eid
        output.print_md("- %s %s %s" % (src, cat, ref))
if res["gaps_mm"]:
    output.print_md("**Залишились розриви:** %s" % res["gaps_mm"])

msg = "Вузол %s: %s\nЕлементів: %d, workset EL." % (info["bay"], chosen["label"], len(created))
if missing:
    msg += "\nНе завантажені лінки, їх не перевірено: %s." % ", ".join(missing)
if chosen.get("low") or chosen["hard"]:
    msg += "\nЗастосовано всупереч правилам: дивіться звіт pyRevit."
if chosen["soft"] or res["gaps_mm"]:
    msg += "\nЄ що перевірити вручну — дивіться звіт pyRevit."
forms.alert(msg)
