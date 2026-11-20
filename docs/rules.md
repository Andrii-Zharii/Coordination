# Coordination rules — learned from cases

> Draft. Each rule: what we saw, in which cases, and whether the team confirmed it.
> Status: **observed** (seen in data) → **confirmed** (team agreed) → **in tool**.

Sources so far (model GRHL-DC-Kelvin-New):
- single cases `cases/.../2026-11-16 17-03/CLASH-001…004`
- zone session `cases/.../sessions/2026-11-17 16-08` — grids 1–8 × A–L, level 01, −5000…0 mm;
  clashes **120 → 43** in ~1 day, 15 nodes, no node notes.

## R1. Gravity pipes move in plan, not in height — observed
Sewage (`ביוב`), AC condensate (`ניקוז מזגן`), balcony drain (`ניקוז מרפסת`) were shifted
**horizontally** (dx 200 mm in CLASH-002, dy 10 mm, 170 mm) with slope kept (~1%).
Elbows 45° were sometimes replaced by 90° in the shifted part.

## R2. Sprinklers: drop or shift the head with its branch — observed
- Head lowered **300 mm**, the 32 mm drop pipe extended by 300 mm (nodes 1, 2).
- Head shifted sideways **120 mm / 580 mm** with its branch (nodes 8, 15).
- Question: why exactly 300 mm down? (ceiling? deflector distance?)

## R3. Small local moves, round numbers — observed
Most moves are ≤ 200 mm and multiples of 10 mm: dz −80, dx +40, dy −80, dx +180,
dy −200 & dz −100, dz −30, dz −100, dx −200, dx +100 (most frequent first, zone session).
Matches the vision rule "local moves only".

## R4. Re-connect branches instead of bending around — observed
Several fixes deleted a branch tee/elbows and re-created the connection elsewhere with a
**45° tee + 45° elbow** (nodes 3, 5, 9: 160/50, 110/110, 90/50 drainage).
Question: why — shorter path, avoid an obstacle, keep the slope?

## R5. Escalate when the space itself is too small — observed
- CLASH-001: 500ø generator exhaust pipe does not fit inside the shaft designed by the architect.
- CLASH-003: a duct takes the whole space, other networks cannot pass.
→ Not a routing problem: goes to the list for contractors / architect.

## Sessions 2026-11-20 (zone grids 12–8 × A–L, levels B1 / 01)
- `10-28` (B1): 1 note, session not finished.
- `10-40` (01): clashes 198 → 191, 1 node, 2 notes.
- `11-58` (01): clashes **131 → 100**, 8 nodes, 11 notes (Zone Note).

## R6. Cable trays go tight side by side — observed + team note
"Trays are usually tight one next to another, without gaps" (10-28 #1). A tray shifted a few mm into a wall
was moved back tight to the wall and to the neighbouring tray.
→ Parallel trays touching side by side are **not** a clash; a tray overlapping another is.

## R7. Crossing cable trays → different elevations — observed + team note
Trays lying on each other / crossing at one level: split them to **different elevations at the crossing**
(11-58 #1, #4, #10; one tray moved dz +100 / −100 mm, nodes 6, 8).

## R8. Sprinkler branch moves as a whole — observed + team note
"Moved the whole sprinkler branch up, between the points where it changes height on both sides, because there
was room" (10-40 #2): 78 elements (pipes 32/50, fittings, 15 heads) all **dz +80 mm**.
Sideways: branch with heads dy −100, +100 mm, dx +290 mm (11-58 nodes 1, 2, 6).
→ The unit to move is the **branch between its height-change points**, heads included.

## R9. Pipes into a wall without an opening → missing opening — team note
Sewage 160 through concrete wall `INT-35 (Cn35)`: "missing opening in the wall" (11-58 #2);
tray through `INT-25 (Cn25)`: tray split by height + "opening needed in the wall" (#5).
→ MEP × concrete wall is usually not rerouted: it goes to the **openings list** for the architect/structure.

## R10. Not a clash: pipes that run inside walls — team note
- Roof drain 160 × linked drain fixture `Koltan 6"`: "these pipes must run in the wall" (10-40 #1).
- Roof drain 160 × floor `Str-25 (Cn)` of GRHL-A-T2: "not a clash, must be inside the walls" (11-58 #9).
→ Candidates to filter out automatically (to define: how to recognise "inside the wall").

## R11. Other resolutions — team notes
- Change the connection type so pipes do not enter the wall and the duct (11-58 #3: sewage × kitchen hood exhaust; fittings rebuilt).
- Route around the duct (11-58 #8: fire water 90 × fresh air duct 170x60).
- "Not a clash, a bad connection" (11-58 #6: condensate 50 × kitchen hood duct bend) — a modelling defect.
- Just move it out of the wall (11-58 #7: sprinkler 32 × column 100/100).

## Notes on the tools
- Zone session grouping: changes closer than 0.3 m are merged, so in a dense corridor
  ~940 changed elements ended up in one node (node 10, 76 clashes). Grouping should also
  split by connected network and by equal displacement.
- Check settings use `min_depth` 0 mm: side-by-side contacts (trays, R6) are reported. A minimum overlap of
  a few mm would drop them.
- Pipe sizes changed label `mmר` → `ø` on many elements (pipe type changed). Probably the
  team's own pipe types replacing the contractor's — to confirm.
