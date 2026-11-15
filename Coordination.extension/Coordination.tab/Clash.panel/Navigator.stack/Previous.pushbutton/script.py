# -*- coding: utf-8 -*-
"""Показує попередню колізію останньої перевірки у 3D-виді CLASH Navigator і виділяє обидва елементи."""
from pyrevit import revit, forms

from coordination.clash import core as gc

try:
    header, text = gc.navigate(revit.uidoc, step=-1)
except ValueError as error:
    forms.alert(unicode(error), exitscript=True)
forms.show_balloon(header, text)
