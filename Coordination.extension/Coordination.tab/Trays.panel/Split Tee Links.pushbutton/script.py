# -*- coding: utf-8 -*-
"""Вибір лінків, з якими Split Tee перевіряє колізії. Хост-модель перевіряється завжди."""
from pyrevit import revit, forms, script
from coordination.trays import tees as T

config = script.get_config("AgentTools.SplitTee")
current = config.get_option("links", T.DEFAULT_LINKS)
loaded = sorted(set(ld.Title for ld, _ in T.links_of(revit.doc)))
if not loaded:
    forms.alert("У цій моделі немає завантажених лінків.", exitscript=True)

items = [forms.TemplateListItem(title, checked=title in current) for title in loaded]
picked = forms.SelectFromList.show(items, multiselect=True,
                                   title="З якими лінками перевіряти колізії?",
                                   button_name="Зберегти")
if picked is None:
    script.exit()

config.links = list(picked)
script.save_config()
forms.alert("Split Tee перевірятиме: хост-модель%s.\nБетон шукається лише у вибраних лінках." % (
    "".join(", " + title for title in picked)))
