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

### Clash panel

| Button | What it does |
|---|---|
| **Clash у зоні** | Asks for 4 grids, a level, a height range (mm), host worksets, the categories to check, links and their categories, and a minimum overlap. Finds clashes of your elements (pipes, cable trays… by default) with each other and with the chosen links. Elements joined into one MEP network, sleeves/openings and link-vs-link pairs are not clashes; each of your elements is listed once. Shows a clickable table and puts a **Clash Region** box (Generic Model family, must be loaded) around each clash on workset **Clash** (created if missing); **ARC clash** is ticked for clashes with linked walls, floors, beams and columns. |
| **Попередня / Список / Наступна** | Open the previous, chosen or next clash of the last check in your own 3D view `CLASH Navigator - <user>`: section box around the clash, only the checked links visible, scope boxes hidden, your elements selected and painted red. |

Clash settings and the last results are kept in `%APPDATA%\pyRevit\GRHL Clash\`. Code: `lib/coordination/clash/core.py`.

## Repository layout

```
Coordination.extension/
  Coordination.tab/        ribbon tab (panels → buttons, one script.py per button)
  lib/coordination/        shared code used by all buttons
  config/                  default rules (default_settings.json)
docs/                      vision, requirements, decisions
```

Code runs on pyRevit's IronPython 2.7 engine: no f-strings or Python-3-only syntax.
