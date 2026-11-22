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
| **Start Zone / Zone Note / Finish Zone** | Record a whole work session in the zone. **Zone Note** — a short note any time during the session (what you did and why), saved with a screenshot. |
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

**Clash groups.** The check no longer hides repeated clashes; it groups them. Clashes join one group when
they are between the same pair of networks (System Type; insulation counts as its pipe/duct; all cable trays
are one network; linked elements by category) and their centres are within **1 m** — or within **4 m** when
one side is the same linked element or the same connected MEP network (a pipe through three trays side by
side; several sprinkler branches touching the same pipe). The report lists each group and, under it, its
clashes (1.1, 1.2 …). **Clash Region**: one box per clash, Mark `CLASH-001.3` (or `CLASH-002` for a group of one).
**Next / Previous** step through groups; **List**: pick a group, then the whole group or one of its clashes.
Cases record what the navigator shows (a group or one clash). Distances: `group_near_mm` / `group_far_mm` in `%APPDATA%\pyRevit\GRHL Clash\settings.json`.

### Trays panel

| Button | What it does |
|---|---|
| **Split Tee** | Select the tees or trays of a T-junction of 2–3 parallel cable tray mains whose branches cross each other. Every main gets its own tier around its tee (one stays put); moved branches ramp back to their old height. Shows the variants checked for clashes (✔ ok, ⚠ soft clashes with other services, ✖ concrete) with a section sketch, and applies the one you pick. Rules: not below 2300 mm from the level, not into concrete, all new and changed elements on workset **EL**. |
| **Split Tee Links** | Choose the links Split Tee checks for clashes (the host model is always checked; concrete is searched only in the chosen links). |

Code: `lib/coordination/trays/tees.py` (logic) and `tee_ui.py` (window).

### Pipes panel

| Button | What it does |
|---|---|
| **Match Connection** | Select together the sample connection (its fitting, or both elbows of an offset) **and the two loose pipes**, click — the pipes are connected the same way: elbow, offset with the sample's angle, tee/tap onto the main, or transition/union. New fittings get the sample's family types. One undo step; if Revit refuses, the model is unchanged. Without loose pipes in the selection, you click pairs of pipes one by one (Esc to finish). |

| **Box Run** | Select a pipe (duct, cable tray, conduit), click and choose the turn: *left / right*, *up / down* or *any*. The section box of the active 3D view (or of `CLASH Navigator - <user>`) is set around the run in both directions up to and including the next such turn, oriented along the run in plan, +0.5 m. Through tees it goes straight on; it also stops at equipment and open ends. The run is selected. |

Code: `lib/coordination/pipes/connect.py`, `run_box.py`.

### Sections panel

| Button | What it does |
|---|---|
| **Place Sections** | Open a floor plan of the level, click, type how many sections (default 30). Creates cross sections of the main networks, most important first, and reports what each one shows and which runs are left without a section. If the level already has sections `00-NN`, new ones get the next numbers and what the old ones show is not repeated. |

How it chooses (rules: [docs/vision.md](docs/vision.md) section 4.0; settings: section `sections` of the rules file):

1. **Networks.** Horizontal pipes, ducts, cable trays of the floor (between the level and the next level, `-DC` worksets left out).
   *Main* networks only: pipes from 50 mm, sprinkler pipes from 80 mm (mains, not branches), ducts from 200 mm, all cable trays.
   Main pieces that continue each other in a straight line at the same height (through couplings, tees) form a **run**.
2. **Height changes.** From each run end the connected network (through fittings and short or sloped pieces) is followed;
   if it goes on in another run of the same system at another height (≥ 50 mm, sprinklers ≥ 300 mm), that is a height change.
   Neighbouring changes of the same system (parallel trays dropping together) count as one. A slope is not a change.
3. **Candidates.** Along every run every 1.5 m, away from its fittings: a line **across** the run, looking up or right on the plan.
   The line always follows the grid axes exactly (the axis closest to the run), never the pipe's own direction —
   a pipe drawn 0.1° off the grid does not give a skewed section.
   **Wall to wall:** on each side the line goes to the first **room wall** of any kind (or concrete column / beam) if it is within 7 m
   of the last network, and ends 50 mm past its outer face (touching walls, e.g. cladding on concrete, count as one; a wall the pipe itself
   runs in bounds the side where the wall is). So a section covers the room or corridor its networks run in.
   A room wall stands on the floor and the networks do not pass over it: partitions up to a suspended ceiling, gypsum boxes and
   linings hanging among the networks (e.g. `AR_01_Int_GypsBrd` at 3.2–5.7 m in GRHL-INT-MAIN) do not end a section.
   A concrete wall hanging from the slab above counts as a beam.
   No wall within 7 m: it ends 600 mm after the networks. If both ends reach a wall but one side is empty for more
   than 2 m, that side ends 600 mm after the networks instead (no long empty stretch just to reach a second wall).
   **Width economy:** a side also ends at a wall crossed inside the section if beyond it there is at most one network
   weighing ≤ 20 % of the section (not twice as wide for one more small pipe). Concrete (preferred at least on one side): wall types with
   `(Cn` / `Concrete` (not `(Bb`), ≥ 150 mm; structural columns; beams of 400 mm+ hanging under the slab above.
4. **Choice.** One by one, the line that adds the most not shown yet: each run (weight: gravity 3 > ducts, trays 2 > pressure pipes 1.5 >
   sprinklers 0.6, × size (at most ×1.5) × length), each height change near the line (within 3 m) and each place where a network
   **appears** in the bundle or leaves it (a run end that is not a height change: tee, riser, turn) near the line (0.5 × the run),
   plus 0.3 for every main network in the cut — sections that show many networks together win.
   Concrete at both ends ×1, one ×0.75, none ×0.3; small pipes and fittings in the cut lower the score; a line cutting a main network
   lengthwise is never taken, nor a line running inside **any** wall or concrete beam or along its face
   (closer than 100 mm for more than 100 mm).
   Crossing a wall or ending at its edge is fine. Two sections closer than 1.5 m that overlap by more than half are duplicates.
   A section must cut at least 3 main networks. **Spread:** each section already chosen within 8 m divides the value of
   one more there by (1 + 0.3 × count), so sections are spread over the floor instead of piling up in one part.
5. **View.** Type `חתך לגיליון`, template `Electra_Section KN`, 1:25, names `00-01…` from top right (Hebrew order).
   Height: level −150 mm to the top of the slab above (top faces of the linked floors at the section) +150 mm.
   Depth: **300 mm** (what the team sets), shorter only before a **fragment** of a main network in front of the cut —
   a horizontal main pipe / duct / tray running along the section, visible over 0.5 m but less than half of the section
   (a piece after a turn). Fittings, takeoffs, valves, risers, sprinkler heads and a main running along the whole section may appear.

Code: `lib/coordination/sections/` (`floor.py` runs and height changes, `concrete.py`, `placement.py`, `views.py`).

**Annotate Sections** — select section views in the Project Browser (or open one) and click. Annotates only what the
section **cuts** (pipes, ducts, cable trays, conduits through the cut plane), not what is seen beyond (team rules 2026-11-22):

| Dimension | From → through → to |
|---|---|
| Floor to ceiling (vertical) | level of the floor → bottom of a concrete beam cut by the section (if any) → underside of the slab above (linked) |
| Pipes (horizontal) | extreme concrete on the left → centres of all cut round objects (pipes, round ducts, conduits) → extreme concrete on the right; a block wall only if it is the outermost and there is no concrete on that side |
| Trays and rectangular ducts (horizontal) | concrete → left and right edges of each object (shows widths) → concrete |
| Trays and rectangular ducts (vertical) | floor → bottom and top of each object (objects at one height once) → ceiling |
| Pipes (vertical) | floor → centres → ceiling, one chain per group of pipes along the section (up to 3) |

A sloped pipe (cut at an angle) gets a cross of detail lines (`<Thin Lines>`, arms 1.2 × diameter) at its centre and the
dimensions use it; cable trays and rectangular ducts get an outline of detail lines. Dimension type `Diagonal - 2.5mm Arial RED`.
Tags (1:50): pipes `M_Pipe Size Inch_Type : 1.5 1 decimal`, trays `M_Cable Tray Size+Type Tag : 1.5+Service Type`,
ducts `M_Duct Size_Type Tag : 1.5`; free leader end at the centre of the object, text straight below it.
Placing dimensions and tags neatly (no overlaps) is the next step. Code: `lib/coordination/sections/annotate.py`.

## Repository layout

```
Coordination.extension/
  Coordination.tab/        ribbon tab (panels → buttons, one script.py per button)
  lib/coordination/        shared code used by all buttons
  config/                  default rules (default_settings.json)
docs/                      vision, requirements, decisions
```

Code runs on pyRevit's IronPython 2.7 engine: no f-strings or Python-3-only syntax.
