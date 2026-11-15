# Coordination

pyRevit tools for MEP/BIM coordination in Revit 2025–2026: rule checks, rerouting helpers,
sections and sheets. Product vision and requirements: [docs/vision.md](docs/vision.md).

## Install (once)

1. Install [pyRevit](https://github.com/pyrevitlabs/pyRevit/releases) 5+ (tested target: 7.0).
2. Clone this repository with GitHub Desktop: **File → Clone repository → Andrii-Zharii/Coordination**.
   Remember the local folder, e.g. `C:\Users\<you>\Documents\GitHub\Coordination`.
3. In Revit: **pyRevit tab → Settings → Custom Extension Directories → Add folder**,
   choose the repository folder (the one that contains `Coordination.extension`).
4. **Save Settings and Reload**. A new **Coordination** tab appears in the ribbon.

## Update

1. GitHub Desktop: **Fetch origin → Pull origin**.
2. Revit: **pyRevit tab → Reload**.

## Tools

### Rules panel

| Button | What it does |
|---|---|
| **Check Floor** | Open a floor plan of the level, click. Checks pipes, ducts, cable trays and conduits whose reference level is that level: bottom below ceiling height, top too close to the slab/beam above (linked models included), gravity pipes with too low slope. Results are clickable; "Select all" selects the elements in Revit. |
| **Rules Settings** | Opens your rules file (`%APPDATA%\Coordination\settings.json`) in the text editor. Distances are in mm. **Shift+Click** resets it to defaults. |

**Clearance to structure** is detected by casting rays upward in the default 3D view `{3D}`:
linked structural/architectural models must be visible there and its section box must not cut the floor.

## Repository layout

```
Coordination.extension/
  Coordination.tab/        ribbon tab (panels → buttons, one script.py per button)
  lib/coordination/        shared code used by all buttons
  config/                  default rules (default_settings.json)
docs/                      vision, requirements, decisions
```

Code runs on pyRevit's IronPython 2.7 engine: no f-strings or Python-3-only syntax.
