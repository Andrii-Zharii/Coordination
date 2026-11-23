# -*- coding: utf-8 -*-
"""Шукає колізії в зоні між чотирма осями і в діапазоні висот від рівня: між елементами обраних воркcетів моделі та з обраними лінками."""
from datetime import datetime

from pyrevit import revit, DB, forms, script

from coordination.clash import core as gc

doc = revit.doc
settings = gc.load_settings()


def pick(items, title, name_attr, checked_names, multiselect=True, button=u"Далі"):
    entries = [forms.TemplateListItem(i, checked=getattr(i, name_attr) in checked_names, name_attr=name_attr)
               for i in items] if multiselect else items
    return forms.SelectFromList.show(entries, title=title, multiselect=multiselect,
                                     name_attr=None if multiselect else name_attr, button_name=button)


def ask_numbers(default, prompt, count):
    text = forms.ask_for_string(default=default, prompt=prompt, title=u"Clash у зоні")
    if text is None:
        script.exit()
    try:
        values = [float(v.replace(u",", u".")) for v in text.split()]
    except ValueError:
        values = []
    if len(values) != count:
        forms.alert(u"Потрібно ввести %d числа через пробіл." % count, exitscript=True)
    return values


RECT = u"Прямокутник на плані (як рамка виділення)"
GRIDS = u"4 осі"
WHOLE = u"Весь поверх"
modes = {RECT: u"rect", GRIDS: u"grids", WHOLE: u"level"}
last_mode = settings.get("zone_mode", u"grids")
options = sorted(modes, key=lambda k: modes[k] != last_mode)
mode_name = forms.CommandSwitchWindow.show(options, message=u"Зона перевірки:")
if not mode_name:
    script.exit()
zone_mode = modes[mode_name]

zone_rect = None
picked_grids = []
if zone_mode == u"rect":
    view = revit.active_view
    if not isinstance(view, DB.ViewPlan):
        forms.alert(u"Відкрийте план поверху: прямокутник вказується на плані.", exitscript=True)
    from Autodesk.Revit.UI.Selection import PickBoxStyle
    try:
        box = revit.uidoc.Selection.PickBox(PickBoxStyle.Directional,
                                            u"Вкажіть зону перевірки: два протилежні кути прямокутника")
    except Exception:
        script.exit()
    zone_rect = [min(box.Min.X, box.Max.X), min(box.Min.Y, box.Max.Y),
                 max(box.Min.X, box.Max.X), max(box.Min.Y, box.Max.Y)]
    if zone_rect[2] - zone_rect[0] < gc.to_ft(500) or zone_rect[3] - zone_rect[1] < gc.to_ft(500):
        forms.alert(u"Прямокутник замалий.", exitscript=True)
    if view.GenLevel is not None:
        settings["level"] = view.GenLevel.Name
elif zone_mode == u"grids":
    grids = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Grid), key=lambda g: g.Name)
    picked_grids = pick(grids, u"Оберіть 4 осі: 2 в одному напрямку і 2 в іншому", "Name", settings.get("grids", []))
    if not picked_grids:
        script.exit()
    if len(picked_grids) != 4:
        forms.alert(u"Потрібно рівно 4 осі.", exitscript=True)

levels = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level), key=lambda l: l.ProjectElevation)
last_level = settings.get("level")
levels.sort(key=lambda l: l.Name != last_level)
level = pick(levels, u"Рівень", "Name", [], multiselect=False)
if not level:
    script.exit()

bottom, top = ask_numbers(settings.get("heights", u"-1500 0"),
                          u"Діапазон висоти від рівня %s, мм: низ і верх через пробіл" % level.Name, 2)
if bottom >= top:
    forms.alert(u"Низ має бути нижче за верх.", exitscript=True)

zone_settings = {"zone_mode": zone_mode, "level": level.Name, "heights": u"%g %g" % (bottom, top)}
if zone_rect is not None:
    zone_settings["zone_rect"] = zone_rect
if picked_grids:
    zone_settings["grids"] = [g.Name for g in picked_grids]
try:
    merged = dict(settings)
    merged.update(zone_settings)
    zone, zone_text = gc.zone_from_settings(doc, merged)
except (ValueError, KeyError) as error:
    forms.alert(unicode(error), exitscript=True)


class Named(object):
    def __init__(self, name, value=None):
        self.name = name
        self.value = value


worksets = sorted(w.Name for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset))
picked_ws = pick([Named(w) for w in worksets], u"Воркcети моделі", "name",
                 settings.get("worksets", [u"EL", u"ME", u"PL"]))
if picked_ws is None:
    script.exit()
picked_ws = set(w.name for w in picked_ws)

host = gc.Source(doc)
host_categories = gc.zone_categories(host, zone)
picked_focus = pick([Named(c) for c in host_categories], u"Що саме перевіряти у вашій моделі", "name",
                    settings.get("focus", gc.DEFAULT_FOCUS_CATEGORIES))
if picked_focus is None:
    script.exit()
focus = set(c.name for c in picked_focus)
if not focus:
    forms.alert(u"Не обрано жодної категорії.", exitscript=True)

links =[Named(gc.link_display_name(li), li) for li in gc.loaded_links(doc)]
picked_links = pick(links, u"Лінки для перевірки (можна жодного)", "name", settings.get("links", [])) if links else []
picked_links = picked_links or []

sources = [gc.Source(doc, l.value) for l in picked_links]
link_categories = set()
if sources:
    available = sorted(set(c for s in sources for c in gc.zone_categories(s, zone)))
    remembered = settings.get("link_categories")
    checked = remembered if remembered is not None else [c for c in available if c in gc.DEFAULT_LINK_CATEGORIES]
    picked_cats = pick([Named(c) for c in available], u"Категорії елементів у лінках", "name", checked)
    if picked_cats is None:
        script.exit()
    link_categories = set(c.name for c in picked_cats)

if not picked_ws and not sources:
    forms.alert(u"Не обрано ні воркcетів, ні лінків.", exitscript=True)

min_depth = ask_numbers(unicode(settings.get("min_depth", 10)),
                        u"Мінімальне заходження, мм. Менші перетини (дотики фітингів) ігноруються", 1)[0]

settings.update(zone_settings)
settings.update({
    "level": level.Name,
    "heights": u"%g %g" % (bottom, top),
    "worksets": sorted(picked_ws),
    "focus": sorted(focus),
    "links": [l.name for l in picked_links],
    "min_depth": min_depth,
})
if sources:
    settings["link_categories"] = sorted(link_categories)
gc.save_settings(settings)

with forms.ProgressBar(title=u"Пошук колізій... ({value} з {max_value})") as bar:
    items = gc.collect(host, zone, worksets=picked_ws) if picked_ws else []
    for source in sources:
        items += gc.collect(source, zone, categories=link_categories)
    stats = {}
    found = gc.find_clashes(items, zone, min_depth_mm=min_depth, progress=bar.update_progress, focus=focus,
                            openings=gc.opening_boxes(host, zone), stats=stats)
    found, ignored_count = gc.drop_ignored(doc, found)
    clashes = gc.group_clashes(found, settings.get("group_near_mm", gc.GROUP_NEAR_MM),
                               settings.get("group_far_mm", gc.GROUP_FAR_MM))

region_error = None
placed = deleted = 0
try:
    placed, deleted = gc.place_regions(doc, clashes, zone)
except Exception as error:
    region_error = unicode(error)

gc.save_results({
    "document": doc.Title,
    "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "zone": zone_text,
    "links": [gc.id_int(l.value.Id) for l in picked_links],
    "clashes": clashes,
    "current": -1,
})

output = script.get_output()
output.set_title(u"Clash у зоні")
output.print_md(u"## Групи колізій: %d (колізій усього: %d)" % (len(clashes), len(found)))
output.print_md(u"**Мережі:** %d  ·  **крізь конструкцію:** %d  ·  **всередині конструкції:** %d" % tuple(
    sum(1 for c in found if c.get("kind", u"mep") == k) for k in gc.KIND_ORDER))
output.print_md(u"*Версія коду: %s*" % gc.code_version())
if ignored_count:
    output.print_md(u"Не показано **%d** колізій зі списку «не колізія» (%s)." % (ignored_count, gc.ignore_file(doc)))
output.print_md(u"**Зона:** %s  \n**Перевіряється:** %s  \n**Воркcети:** %s  \n**Лінки:** %s  \n**Мінімальне заходження:** %g мм  \n**Перевірено елементів:** %d  \n**Усього перетинів:** %d, зібрано в групи: та сама пара мереж поруч (до %g мм, або до %g мм уздовж тієї самої мережі)  \n**Проходи крізь шрулі й отвори (не колізії):** %d" % (
    zone_text, u", ".join(sorted(focus)), u", ".join(sorted(picked_ws)) or u"-",
    u", ".join(l.name for l in picked_links) or u"-", min_depth, len(items), len(found),
    settings.get("group_near_mm", gc.GROUP_NEAR_MM), settings.get("group_far_mm", gc.GROUP_FAR_MM), stats["in_openings"]))
if region_error:
    output.print_md(u"**Бокси Clash Region не поставлено:** %s" % region_error)
else:
    output.print_md(u"**Бокси Clash Region:** поставлено %d на воркcеті %s, старих у цій зоні видалено %d" % (
        placed, gc.REGION_WORKSET, deleted))


def region_link(clash, name):
    return output.linkify(gc.make_id(clash["region"]), title=name) if clash.get("region") else name


def cell(side):
    ident = output.linkify(gc.make_id(side["id"])) if side["link_id"] is None else u"#%d" % side["id"]
    text = u" ".join(p for p in (side["category"], side["type"], side["size"]) if p)
    return u"%s<br>%s %s" % (side["source"], text, ident)


def table_rows(kind):
    """A row per group of this kind, then (for groups of several clashes) a row per clash: 1.1, 1.2 ..."""
    rows = []
    for i, group in enumerate(clashes):
        if group.get("kind", u"mep") != kind:
            continue
        members = group.get("members") or [group]
        if len(members) == 1:
            rows.append([u"<b>%d</b>" % (i + 1), gc.short_systems(group), 1, cell(group["a"]), cell(group["b"]),
                         group["depth_mm"], region_link(members[0], gc.clash_name(i))])
            continue
        rows.append([u"<b>%d</b>" % (i + 1), u"<b>%s</b>" % gc.short_systems(group), u"<b>%d</b>" % group["count"],
                     u"<i>група</i>", u"", group["depth_mm"], u""])
        for j, member in enumerate(members):
            rows.append([u"&nbsp;&nbsp;%d.%d" % (i + 1, j + 1), u"", u"", cell(member["a"]), cell(member["b"]),
                         member["depth_mm"], region_link(member, gc.clash_name(i, j, group))])
    return rows


KIND_HEADERS = {
    u"mep": u"Мережі × мережі — колізії координації",
    u"through": u"Крізь конструкцію — мережа перетинає стіну / плиту / колону / балку (потрібен отвір)",
    u"inside": u"Всередині конструкції — мережа йде вздовж у плиті / стіні (зазвичай так задумано)",
}
if clashes:
    for kind in gc.KIND_ORDER:
        kind_groups = [g for g in clashes if g.get("kind", u"mep") == kind]
        if not kind_groups:
            continue
        output.print_md(u"### %s: %d груп, %d колізій" % (
            KIND_HEADERS[kind], len(kind_groups), sum(g.get("count", 1) for g in kind_groups)))
        output.print_table(table_rows(kind),
                           columns=[u"№", u"Мережі", u"Колізій", u"Елемент A", u"Елемент B", u"Заходження, мм", u"Бокс"])
    output.print_md(u"**Наступна / Попередня** — по групах. **Список** — оберіть групу, потім усю групу або одну її колізію.")
    forms.alert(u"Знайдено груп: %d (колізій: %d)." % (len(clashes), len(found)),
                sub_msg=u"Таблиця відкрита у вікні pyRevit. Перейти до колізій можна кнопками Наступна / Попередня / Список.")
else:
    output.print_md(u"Колізій не знайдено.")
    forms.alert(u"Колізій не знайдено.")
