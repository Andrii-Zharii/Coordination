# -*- coding: utf-8 -*-
"""Re-check the current clash group; resolved clashes and their Clash Region boxes disappear."""
from pyrevit import revit, forms

from coordination.clash import core as gc

try:
    name, before, after, other = gc.refresh_group(revit.uidoc)
except ValueError as error:
    forms.alert(u"{}".format(error), exitscript=True)

if after:
    message = u"{}: було {}, лишилось {} колізій.".format(name, before, after)
    gc.navigate(revit.uidoc, index=gc.load_results()["current"])
else:
    message = u"{}: вирішено (було {}). Бокси прибрано.".format(name, before)
if other:
    message += u"\nПоруч є інші колізії: {} (перевірте «Clash у зоні»).".format(other)
forms.show_balloon(u"Оновити групу", message)
