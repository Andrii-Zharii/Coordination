# -*- coding: utf-8 -*-
"""Check the MEP of the active floor plan's level against the coordination rules:
ceiling clear height, clearance to the slab/beam above, and gravity pipe slopes."""
__title__ = "Check\nFloor"
__author__ = "Coordination"

import os

from pyrevit import revit, DB, forms, script

from coordination import config, mep, structure
from coordination.units import ft_to_mm

doc = revit.doc
output = script.get_output()


def get_level():
    view = revit.active_view
    level = getattr(view, "GenLevel", None)
    if level is None:
        forms.alert("Open a floor plan (or ceiling plan) of the level you want to check.",
                    exitscript=True)
    return level


def fmt(value_mm):
    return "{:.0f}".format(value_mm)


def check_ceiling(elements, level, settings, skip_vertical, vertical_angle):
    """Bottom of MEP must be at least min_clear_height above the level."""
    min_height = settings["ceiling"]["min_clear_height_mm"]
    level_z = level.ProjectElevation
    rows, ids = [], []
    for element in elements:
        if skip_vertical and mep.angle_from_horizontal_deg(element) > vertical_angle:
            continue
        half = mep.vertical_size(element) / 2.0
        points = mep.sample_points(element)
        if not points:
            continue
        bottom_mm = min(ft_to_mm(p.Z - half - level_z) for p in points)
        if bottom_mm < min_height:
            ids.append(element.Id)
            rows.append([output.linkify(element.Id), mep.category_name(element),
                         mep.system_name(element), fmt(bottom_mm), fmt(min_height),
                         fmt(min_height - bottom_mm)])
    return rows, ids


def check_structure(elements, settings, skip_vertical, vertical_angle, ray):
    """Top of MEP must be at least N mm below the nearest slab/beam above."""
    limits = settings["clearance_to_structure_mm"]
    rows, ids = [], []
    for element in elements:
        name = mep.category_name(element)
        required = limits.get(name, 0) if name else 0
        if not required:
            continue
        if skip_vertical and mep.angle_from_horizontal_deg(element) > vertical_angle:
            continue
        half = mep.vertical_size(element) / 2.0
        gaps = []
        for p in mep.sample_points(element):
            top = DB.XYZ(p.X, p.Y, p.Z + half)
            distance = ray.distance_up(top)
            if distance is not None:
                gaps.append(ft_to_mm(distance))
        if not gaps:
            continue
        gap = min(gaps)
        if gap < required:
            ids.append(element.Id)
            rows.append([output.linkify(element.Id), name, mep.system_name(element),
                         fmt(gap), fmt(required), fmt(required - gap)])
    return rows, ids


def check_slopes(elements, settings, vertical_angle):
    """Gravity pipes must have at least min_slope_percent."""
    gravity = settings["gravity"]
    min_slope = gravity["min_slope_percent"]
    rows, ids = [], []
    for element in elements:
        if not mep.is_gravity_pipe(element, gravity):
            continue
        if mep.angle_from_horizontal_deg(element) > vertical_angle:
            continue  # risers / stacks
        slope = mep.slope_percent(element)
        if slope is None:
            continue
        if slope < min_slope:
            ids.append(element.Id)
            rows.append([output.linkify(element.Id), mep.system_name(element),
                         "{:.2f}".format(slope), "{:.2f}".format(min_slope)])
    return rows, ids


def print_section(title, rows, ids, columns):
    output.print_md("## {} — {}".format(title, len(rows)))
    if not rows:
        output.print_md("No issues.")
        return
    output.print_md("Select all: {}".format(output.linkify(ids, "{} elements".format(len(ids)))))
    output.print_table(table_data=rows, columns=columns)


def main():
    settings = config.load()
    level = get_level()
    skip_vertical = settings.get("skip_vertical_elements", True)
    vertical_angle = settings.get("vertical_angle_deg", 45)

    elements = mep.collect_mep_curves(doc, level.Id)
    output.print_md("# Check Floor: {}".format(level.Name))
    output.print_md("Checked **{}** pipes / ducts / cable trays / conduits "
                    "with reference level *{}*.".format(len(elements), level.Name))
    if not elements:
        return

    all_ids = []

    rows, ids = check_ceiling(elements, level, settings, skip_vertical, vertical_angle)
    print_section("Below ceiling height ({} mm)".format(settings["ceiling"]["min_clear_height_mm"]),
                  rows, ids,
                  ["Element", "Category", "System", "Bottom, mm", "Required, mm", "Short by, mm"])
    all_ids.extend(ids)

    view3d = structure.find_3d_view(doc)
    if view3d is None:
        output.print_md("## Clearance to structure — skipped\n"
                        "No 3D view found. Open the default 3D view once and run again.")
    else:
        ray = structure.StructureAbove(view3d, settings["structure_categories"])
        rows, ids = check_structure(elements, settings, skip_vertical, vertical_angle, ray)
        print_section("Too close to slab / beam above", rows, ids,
                      ["Element", "Category", "System", "Gap, mm", "Required, mm", "Short by, mm"])
        output.print_md("*Structure detected through 3D view \"{}\": links must be visible "
                        "there and its section box must not cut this floor.*".format(view3d.Name))
        all_ids.extend(ids)

    rows, ids = check_slopes(elements, settings, vertical_angle)
    print_section("Gravity pipes with low slope (< {} %)".format(settings["gravity"]["min_slope_percent"]),
                  rows, ids, ["Element", "System", "Slope, %", "Required, %"])
    all_ids.extend(ids)

    unique = list({mep.element_id_value(i): i for i in all_ids}.values())
    output.print_md("---\n**Total elements with issues: {}**".format(len(unique)))
    if unique:
        output.print_md("Select all with issues: {}".format(
            output.linkify(unique, "{} elements".format(len(unique)))))
    output.print_md("*Rules: {}*".format(config.USER_PATH if os.path.isfile(config.USER_PATH)
                                         else config.DEFAULTS_PATH))


main()
