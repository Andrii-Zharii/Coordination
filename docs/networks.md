# Networks: what the model consists of

> Draft built from the zone snapshot `cases/GRHL-DC-Kelvin-New/sessions/2026-11-17 16-08/start.json`
> (grids 1–8 × A–L, level 01, 4200 MEP elements). Gravity column confirmed by the team (2026-11-19).

## Idea

Clashes are checked between elements, but coordination decisions are made about **networks**:
"sewage has priority over sprinklers", "the three cable trays go together".
So the tools need three levels:

1. **Network class** — our own list (sewage, sprinklers, cable trays…) with rules:
   gravity or not, priority, how it may be moved, clearances.
2. **Mapping** — contractor system names → our class. One class has many names
   (`H_Chilled Water Supply` and `CHWS - Chilled Water Supply` are the same thing).
3. **Runs and bundles** inside a network — a run is a line from bend to bend;
   a bundle is several parallel elements going together (e.g. 3 cable trays side by side) —
   they are moved as one.

## Draft: classes and contractor names

Columns *Gravity / Priority / May move* — to be filled in by the team.

| # | Class | Contractor system names (elements in zone) | Typical content | Gravity | Priority | May move |
|---|---|---|---|---|---|---|
| 1 | Sewage | `ביוב` (335), `Sanitary` (1) | pipes 110–160, 45° fittings | yes | | plan only? |
| 2 | Roof drainage | `ניקוז גג` (349) | pipes 110–250 | yes | | |
| 3 | AC condensate | `ניקוז מזגן` (306), `H_Condensate Drainage` (8) | pipes 50–160 | yes | | |
| 4 | Balcony drainage | `ניקוז מרפסת` (61) | pipes 110–160 | yes | | |
| 5 | Shaft drainage | `ניקוז פיר` (91) | pipes 110 | yes | | |
| 6 | Sprinkler drainage | `ניקוז ספרינקלרים` (18) | pipes 110: horizontal runs at slope 0, risers | no (no slope) | | |
| 7 | Pumped drainage | `ניקוז סניקה` (6) | pipes 110 | no (pumped) | | |
| 8 | Vent | `צינור אוויר` (123) | pipes 110–160 (workset PL) | no | | |
| 9 | Sprinklers | `ספרינקלר` (1358) | pipes 32–110, heads, fittings, valves | no | | |
| 10 | Fire water | `כיבוי אש` (304), `כיבוי אש הסנקה` (1) | pipes 90–110, valves | no | | |
| 11 | Cold water | `מים קרים` (251), `מי צריכה מאגר תחתון משאבות` (2) | pipes 63–110, valves | no | | |
| 12 | Chilled water supply | `H_Chilled Water Supply` (74), `CHWS - Chilled Water Supply` (3) | pipes 25–350 | no | | |
| 13 | Chilled water return | `H_Chilled Water Return` (73), `CHWR - Chilled Water Return` (8) | pipes 25–350 | no | | |
| 14 | Supply air | `BT_Supply Air` (183), `Supply Air` (10) | ducts, flex ducts 20ø–60x30 | no | | |
| 15 | Return air | `BT_Return Air` (32), `Return Air` (21) | ducts | no | | |
| 16 | Outside air | `Outside Air` (7) | ducts up to 250x50 | no | | |
| 17 | Exhaust | `Toilet Extract` (66), `Kitchenette Extract` (27) | ducts 20x20–80x35 | no | | |
| 18 | Kitchen hood exhaust | `Kitchen Hood Exhaust` (50) | ducts 70x70–110x65 | no | | |
| 19 | Smoke exhaust | `Smoke Exhaust Air` (123), `Smoke Exhaust` (31) | ducts up to 150x70 | no | | |
| 20 | Generator exhaust | `Generator Exhaust` (2) | pipe 500ø | no | | |
| 21 | Cable trays | *no system* (127 trays) + `Undefined` (93 tray fittings) | trays 10x8–50x10 cm | no | | |

### Not classified
- `Undefined` (149): tray fittings (93), unconnected pipe fittings/accessories (48), sprinkler heads (7).
- Cable trays have **no system** in Revit — they must be grouped another way (type, workset, bundles).

## Observations
- Same network appears under different names (Hebrew/English, with/without prefix `H_`, `BT_`).
- Worksets: `PL`, `ME`, `EL` and `PL-DC`, `EL-DC` — meaning of `-DC` to confirm.
- Pipe sizes come in two labels: `160 mmר` (contractor type) and `160ø` (another type).
