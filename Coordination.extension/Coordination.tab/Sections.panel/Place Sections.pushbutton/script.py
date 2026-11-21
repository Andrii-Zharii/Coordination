# -*- coding: utf-8 -*-
"""Place sections for the floor of the active plan (vision section 4):
across the main networks, where heights change, from concrete to concrete,
from the slab of the level to the slab above. Most important first."""
import time

from pyrevit import revit, DB, forms, script

from coordination import config
from coordination.sections import placement, views

doc = revit.doc
output = script.get_output()

plan_view = revit.active_view
level = getattr(plan_view, "GenLevel", None)
if level is None:
    forms.alert("Open a floor plan of the level you want sections for.", exitscript=True)

settings = config.load()
cfg = settings["sections"]

text = forms.ask_for_string(default=str(cfg["count"]), prompt="How many sections (at most)?",
                            title="Place Sections: {}".format(level.Name))
if not text:
    script.exit()
try:
    count = max(1, int(text))
except ValueError:
    forms.alert("Type a number.", exitscript=True)

existing = views.level_sections(doc, level.Name)
existing_lines = []
start_number = 1
if existing:
    numbers = sorted(existing)
    answer = forms.alert(
        "Level {0} already has {1} sections ({0}-{2:02d} ... {0}-{3:02d}).\n\n"
        "New sections get the next numbers; what the existing ones already show is not "
        "repeated. Existing sections are not changed.".format(
            level.Name, len(numbers), numbers[0], numbers[-1]),
        options=["Add sections", "Cancel"])
    if answer != "Add sections":
        script.exit()
    existing_lines = [views.view_line(v) for v in existing.values()]
    start_number = numbers[-1] + 1

up = (plan_view.UpDirection.X, plan_view.UpDirection.Y)
right = (plan_view.RightDirection.X, plan_view.RightDirection.Y)

started = time.time()
output.print_md("# Place Sections: {}".format(level.Name))
output.print_md("Analysing the floor ...")
result = placement.plan(doc, level, settings, up, right, count, existing_lines)
chosen = result["chosen"]
if not chosen:
    output.print_md("Nothing to show: no main networks found on this floor.")
    script.exit()

with revit.Transaction("Place Sections {}".format(level.Name)):
    rows = views.make_views(doc, level, chosen, result, settings, up, right, start_number)

runs = result["runs"]
events = result["events"]
weights = dict((r.index, placement.run_weight(r, cfg)) for r in runs)
total = sum(weights.values()) or 1.0
shown = sum(weights[i] for i in result["covered_runs"])

output.print_md(
    "**{}** sections created in {:.0f} s. Main runs: **{}**, shown **{}** "
    "({:.0f} % by importance). Height changes: **{}**, shown **{}**. "
    "Places where a network appears: **{}**, shown **{}**. "
    "Concrete elements found in the links: {}.".format(
        len(rows), time.time() - started, len(runs), len(result["covered_runs"]),
        100.0 * shown / total, len(events), len(result["covered_events"]),
        len(result["ends"]), len(result["covered_ends"]), len(result["obstacles"])))

END_NAMES = {"concrete": "concrete", "wall": "wall", None: "open"}
table = []
for row in rows:
    line = row["line"]
    view = row["view"]
    table.append([
        output.linkify(view.Id, view.Name),
        "{:.1f}".format((line.t_max - line.t_min) * 0.3048),
        "{:.0f}".format(row["depth"] * 304.8),
        " / ".join(END_NAMES[k] for k in line.ends),
        str(len(line.cuts)),
        u"; ".join(line.reasons[:3]) + (u" ..." if len(line.reasons) > 3 else u""),
    ])
output.print_table(table_data=table,
                   columns=["Section", "Length, m", "Depth, mm", "Ends (left / right)", "Networks cut", "Why"])

missing = [r for r in runs if r.index not in result["covered_runs"]]
missing.sort(key=lambda r: -weights[r.index])
if missing:
    output.print_md("## Not shown, most important first")
    rows_missing = []
    for run in missing[:20]:
        ids = [DB.ElementId(i) for i in run.ids]
        rows_missing.append([output.linkify(ids, run.key), "{:.0f}".format(run.size * 304.8),
                             "{:.1f}".format(run.length * 0.3048)])
    output.print_table(table_data=rows_missing, columns=["Run", "Size, mm", "Length, m"])
no_slab = [r["view"].Name for r in rows if not r["slab_found"]]
if no_slab:
    output.print_md("*Slab above not found for {}: top set to the level above + 300 mm.*".format(
        ", ".join(no_slab)))
output.print_md("*Rules: section `sections` of {}*".format(config.USER_PATH))
