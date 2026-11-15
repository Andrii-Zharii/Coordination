# -*- coding: utf-8 -*-
"""Helpers for reading MEP elements: geometry, size, system, slope."""
import math

from Autodesk.Revit import DB

# Display name -> built-in category of the straight MEP segments we check.
MEP_CATEGORIES = [
    ("Pipes", DB.BuiltInCategory.OST_PipeCurves),
    ("Ducts", DB.BuiltInCategory.OST_DuctCurves),
    ("Cable Trays", DB.BuiltInCategory.OST_CableTray),
    ("Conduits", DB.BuiltInCategory.OST_Conduit),
]


def element_id_value(element_id):
    """Integer value of an ElementId (Revit 2024+ uses .Value)."""
    value = getattr(element_id, "Value", None)
    if value is None:
        value = element_id.IntegerValue
    return value


def category_name(element):
    """Our display name for the element's category, or None."""
    if element.Category is None:
        return None
    cat_id = element_id_value(element.Category.Id)
    for name, bic in MEP_CATEGORIES:
        if cat_id == int(bic):
            return name
    return None


def collect_mep_curves(doc, level_id=None):
    """All pipes, ducts, cable trays and conduits (optionally on one reference level)."""
    result = []
    for name, bic in MEP_CATEGORIES:
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(bic)
                     .WhereElementIsNotElementType())
        for element in collector:
            if not isinstance(element, DB.MEPCurve):
                continue
            if level_id is not None:
                ref_level = element.ReferenceLevel
                if ref_level is None or ref_level.Id != level_id:
                    continue
            result.append(element)
    return result


def _param_double(element, bip):
    param = element.get_Parameter(bip)
    if param is not None and param.HasValue:
        return param.AsDouble()
    return None


def _param_string(element, bip):
    param = element.get_Parameter(bip)
    if param is None or not param.HasValue:
        return ""
    return param.AsString() or param.AsValueString() or ""


def vertical_size(element):
    """Outer height of the element cross-section in feet (insulation not included)."""
    name = category_name(element)
    candidates = []
    if name == "Pipes":
        candidates = [DB.BuiltInParameter.RBS_PIPE_OUTER_DIAMETER]
    elif name == "Ducts":
        candidates = [DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
                      DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM]
    elif name == "Cable Trays":
        candidates = [DB.BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM]
    elif name == "Conduits":
        candidates = [DB.BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM,
                      DB.BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM]
    for bip in candidates:
        value = _param_double(element, bip)
        if value:
            return value
    # Fallback: bounding box height.
    bbox = element.get_BoundingBox(None)
    if bbox is not None:
        return bbox.Max.Z - bbox.Min.Z
    return 0.0


def location_line(element):
    location = element.Location
    if isinstance(location, DB.LocationCurve):
        return location.Curve
    return None


def angle_from_horizontal_deg(element):
    """0 = horizontal, 90 = vertical riser."""
    line = location_line(element)
    if line is None:
        return 0.0
    p0 = line.GetEndPoint(0)
    p1 = line.GetEndPoint(1)
    dz = abs(p1.Z - p0.Z)
    dxy = math.hypot(p1.X - p0.X, p1.Y - p0.Y)
    if dxy < 1e-9:
        return 90.0
    return math.degrees(math.atan2(dz, dxy))


def sample_points(element, fractions=(0.05, 0.5, 0.95)):
    """Points on the element's centre line."""
    line = location_line(element)
    if line is None:
        return []
    return [line.Evaluate(f, True) for f in fractions]


def system_name(element):
    """Readable system type name, e.g. 'Sanitary' or a contractor's custom name."""
    for bip in (DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM,
                DB.BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM,
                DB.BuiltInParameter.RBS_SYSTEM_NAME_PARAM):
        param = element.get_Parameter(bip)
        if param is not None and param.HasValue:
            text = param.AsValueString() or param.AsString()
            if text:
                return text
    return ""


def system_classification(element):
    return _param_string(element, DB.BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM)


def slope_percent(element):
    """Pipe slope in percent, or None if the element has no slope parameter."""
    value = _param_double(element, DB.BuiltInParameter.RBS_PIPE_SLOPE)
    if value is None:
        return None
    return value * 100.0


def is_gravity_pipe(element, gravity_settings):
    if category_name(element) != "Pipes":
        return False
    classification = system_classification(element).lower()
    for item in gravity_settings.get("system_classifications", []):
        if item.lower() in classification:
            return True
    name = system_name(element).lower()
    for keyword in gravity_settings.get("system_name_keywords", []):
        if keyword.lower() in name:
            return True
    return False
