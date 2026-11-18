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

### Cases panel

Records how each clash was handled — the examples the rerouting tools are built from. Details: [docs/cases.md](docs/cases.md).

| Button | What it does |
|---|---|
| **Start Zone** | Start of a work session in the zone of the last *Clash у зоні*: snapshot of all MEP in the zone and the clash list. Then fix freely, in any order. |
| **Finish Zone** | Snapshot and clash check again. Changes are found automatically and grouped into nodes; each node is selected and you add one short note (why). Report: per node — changes, resolved and new clashes; remaining clashes. |
| **Before** | Screenshot of the active view + data of the current clash (from the navigator), the whole straight runs of its elements and the MEP around it. Without a current clash — the selected elements. |
| **After** | After you fixed it: screenshot + data again, your short note, and the list of changes. Status *resolved*. |
| **Skip** | *Not a clash* or *Escalate* (needs discussion with the contractors) + your note and a screenshot. |

Cases are saved in `cases/` inside the repository — commit and push them with GitHub Desktop at the end of the day.
Notes can be recorded by **voice** in any language (button *Record voice*); they are transcribed later.

### Clash panel

| Button | What it does |
|---|---|
| **Clash у зоні** | Asks for 4 grids, a level, a height range (mm), host worksets, the categories to check, links and their categories, and a minimum overlap. Finds clashes of your elements (pipes, cable trays… by default) with each other and with the chosen links. Elements joined into one MEP network, sleeves/openings and link-vs-link pairs are not clashes; each of your elements is listed once. Shows a clickable table and puts a **Clash Region** box (Generic Model family, must be loaded) around each clash on workset **Clash** (created if missing); **ARC clash** is ticked for clashes with linked walls, floors, beams and columns. |
| **Попередня / Список / Наступна** | Open the previous, chosen or next clash of the last check in your own 3D view `CLASH Navigator - <user>`: section box around the clash, only the checked links visible, scope boxes hidden, your elements selected and painted red. |

Clash settings and the last results are kept in `%APPDATA%\pyRevit\GRHL Clash\`. Code: `lib/coordination/clash/core.py`.

### Trays panel

| Button | What it does |
|---|---|
| **Split Tee** | Select the tees or trays of a T-junction of 2–3 parallel cable tray mains whose branches cross each other. Every main gets its own tier around its tee (one stays put); moved branches ramp back to their old height. Shows the variants checked for clashes (✔ ok, ⚠ soft clashes with other services, ✖ concrete) with a section sketch, and applies the one you pick. Rules: not below 2300 mm from the level, not into concrete, all new and changed elements on workset **EL**. |
| **Split Tee Links** | Choose the links Split Tee checks for clashes (the host model is always checked; concrete is searched only in the chosen links). |

Code: `lib/coordination/trays/tees.py` (logic) and `tee_ui.py` (window).

### Pipes panel

| Button | What it does |
|---|---|
| **Match Connection** | Connects loose pipes the same way as a sample. Select the sample connection (its fitting, or both elbows of an offset — the pipe between them may be selected too), click the button, then click pairs of pipes near the ends to connect; **Esc** to finish. Sample → result: one **elbow** → elbow where the axes cross; **two elbows** → offset between parallel pipes with the sample's angle (45°, 90°…); **tee** or **tap** → the branch end is joined to the main (pick the main first); **transition/union** → pipes on one axis. New fittings get the sample's family types. Each pair is one undo step; a pair Revit refuses leaves the model unchanged. |

Code: `lib/coordination/pipes/connect.py`.

## Repository layout

```
Coordination.extension/
  Coordination.tab/        ribbon tab (panels → buttons, one script.py per button)
  lib/coordination/        shared code used by all buttons
  config/                  default rules (default_settings.json)
docs/                      vision, requirements, decisions
```

Code runs on pyRevit's IronPython 2.7 engine: no f-strings or Python-3-only syntax.
