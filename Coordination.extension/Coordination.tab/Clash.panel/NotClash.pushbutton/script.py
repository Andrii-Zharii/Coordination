# -*- coding: utf-8 -*-
"""Mark the current clash group as not a clash. Shift+Click: restore clashes from the list."""
from pyrevit import revit, forms, script

from coordination.clash import core as gc

doc = revit.doc

if __shiftclick__:  # noqa: F821  (injected by pyRevit)
    entries = gc.load_ignored(doc)
    if not entries:
        forms.alert(u"Список «не колізія» порожній.", exitscript=True)
    labels = [u"{}  {}  [{}] {}".format(e["time"][:16], e.get("name", u""), e["reason"], e.get("note", u""))
              + u"  |  " + gc.short_side(e["a"]) + u" x " + gc.short_side(e["b"]) for e in entries]
    picked = forms.SelectFromList.show(labels, multiselect=True, width=1100, button_name=u"Повернути",
                                       title=u"Повернути в перевірку (з'являться при наступному «Clash у зоні»)")
    if picked:
        gc.unignore(doc, [entries[labels.index(p)]["key"] for p in picked])
        forms.show_balloon(u"Не колізія", u"Повернуто: {}".format(len(picked)))
    script.exit()

titles = [title for _, title in gc.IGNORE_REASONS]
choice = forms.CommandSwitchWindow.show(titles, message=u"Чому це не колізія?")
if not choice:
    script.exit()
reason = gc.IGNORE_REASONS[titles.index(choice)][0]
note = forms.ask_for_string(prompt=u"Коментар (необов'язково): кому питання, що не так", title=u"Не колізія")
if note is None:
    script.exit()
try:
    name, count = gc.ignore_current(revit.uidoc, reason, note)
except ValueError as error:
    forms.alert(u"{}".format(error), exitscript=True)
forms.show_balloon(u"Не колізія", u"{}: {} колізій позначено «{}». Більше не показуватимуться.".format(name, count, choice))
