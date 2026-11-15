# -*- coding: utf-8 -*-
"""Find the structure (slab / beam) above a point, including linked models."""
from Autodesk.Revit import DB


def find_3d_view(doc):
    """A usable 3D view for ray casting: prefer the default '{3D}' view.

    Links must be visible in this view, and its section box must not cut
    the area that is being checked.
    """
    fallback = None
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View3D):
        if view.IsTemplate or view.IsPerspective:
            continue
        if view.Name.startswith("{3D"):
            return view
        if fallback is None:
            fallback = view
    return fallback


class StructureAbove(object):
    """Ray-casts straight up and returns the distance to the nearest structure."""

    def __init__(self, view3d, category_names):
        filters = []
        for name in category_names:
            bic = getattr(DB.BuiltInCategory, name, None)
            if bic is not None:
                filters.append(DB.ElementCategoryFilter(bic))
        if not filters:
            raise ValueError("No valid structure categories in settings.")
        if len(filters) == 1:
            element_filter = filters[0]
        else:
            element_filter = DB.LogicalOrFilter(filters)
        self._intersector = DB.ReferenceIntersector(
            element_filter, DB.FindReferenceTarget.Face, view3d)
        self._intersector.FindReferencesInRevitLinks = True
        self._up = DB.XYZ(0, 0, 1)

    def distance_up(self, point):
        """Distance in feet from point to the first structure face above, or None."""
        context = self._intersector.FindNearest(point, self._up)
        if context is None:
            return None
        return context.Proximity
