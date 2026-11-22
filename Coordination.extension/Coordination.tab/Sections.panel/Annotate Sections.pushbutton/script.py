# -*- coding: utf-8 -*-
"""Annotate section views: dimensions, crosses / outlines and tags of what the section cuts.
Select section views in the Project Browser (or open one) and click."""
from pyrevit import revit, DB, forms, script

from coordination import config
from coordination.sections import annotate

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

views = []
for element_id in uidoc.Selection.GetElementIds():
    element = doc.GetElement(element_id)
    if isinstance(element, DB.ViewSection) and not element.IsTemplate:
        views.append(element)
if not views and isinstance(revit.active_view, DB.ViewSection):
    views = [revit.active_view]
if not views:
    forms.alert("Select section views in the Project Browser, or open a section, and click again.",
                exitscript=True)

settings = config.load()
levels = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level), key=lambda l: l.ProjectElevation)


def level_of(view):
    """The level the section stands on: the highest level not above its bottom + 1 m."""
    frame = annotate.Frame(view)
    best = levels[0]
    for level in levels:
        if level.ProjectElevation <= frame.z_bottom + 3.3:
            best = level
    return best


rows = []
with revit.Transaction("Annotate Sections"):
    for view in views:
        result = annotate.annotate(doc, view, level_of(view), settings)
        rows.append([output.linkify(view.Id, view.Name), str(len(result["cuts"])),
                     str(len(result["dimensions"])), str(len(result["tags"])), str(result["helpers"])])
output.print_md("# Annotate Sections")
output.print_table(table_data=rows, columns=["Section", "Cut objects", "Dimensions", "Tags", "Helper lines"])
output.print_md("*Placing the dimensions and tags neatly is not done yet: move them by hand for now.*")
