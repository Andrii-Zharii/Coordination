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

## Notes on the tools
- Zone session grouping: changes closer than 0.3 m are merged, so in a dense corridor
  ~940 changed elements ended up in one node (node 10, 76 clashes). Grouping should also
  split by connected network and by equal displacement.
- Pipe sizes changed label `mmר` → `ø` on many elements (pipe type changed). Probably the
  team's own pipe types replacing the contractor's — to confirm.
