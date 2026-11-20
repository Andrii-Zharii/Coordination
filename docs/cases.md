# Case recording (Cases panel)

Goal: collect real examples of how clashes are resolved, so the rerouting rules
and tools are built on what the team actually does.

## Zone session (several connected fixes)

When one fix leads to another and you cannot go clash by clash:

1. **Clash у зоні** — the zone and settings of this check are used.
2. **Start Zone** — snapshot of all MEP in the zone + clash list (use the last check, or check now) + screenshot.
3. Work as usual: any order, any number of fixes. After a fix, press **Zone Note** and write in a few
   words what you did and why — so nothing is forgotten by the end. Each note is saved at once with the time,
   the clash open in the navigator, the selected elements and a screenshot (`journal.json`, `journal.txt`,
   `note_NN.jpg`), and goes into `session.json` at Finish Zone.
4. **Finish Zone** — snapshot and clash check again. The changes are found automatically and
   grouped into **nodes** (changed elements that are connected or closer than 0.3 m).
   Each node is selected in Revit; write one short note: *why* you did it this way (Win+H).
   Cancel skips the remaining notes. Then an optional note about the zone as a whole.
5. The report shows per node: what changed, which clashes it resolved, which new ones appeared;
   plus the clashes that remain. Run **Clash у зоні** again to refresh the list and the boxes.

```
cases/<model>/sessions/<start time>/
  session.json  zone, check settings, nodes (changes, resolved/new clashes, note), remaining clashes
  start.json    data of all MEP in the zone + clashes at the start
  finish.json   data of the changed elements + clashes at the finish
  start.jpg / finish.jpg   screenshots of the active view
  note.txt      notes per node + zone notes
  journal.json / journal.txt / note_NN.jpg   notes written with Zone Note during the session
```

Press Start Zone **before** the first change: what was changed earlier cannot be reconstructed.

## Workflow (one clash at a time)

1. **Clash у зоні** — run the check (Clash panel).
2. **Наступна / Список** — open a clash in the *CLASH Navigator* 3D view.
3. One of:
   - **Before** → fix the clash in Revit → **After** + short note (what was wrong, what you did, *why*).
     Status: `resolved`.
   - **Skip** → choose:
     - *Not a clash* — false detection; note why;
     - *Escalate* — cannot be fixed by us, needs discussion with the contractors; note why.
4. Next clash.
5. End of the day: GitHub Desktop → commit `cases/` → **Push origin**.

### Notes: voice or text

After and Skip ask for a note: **Record voice** (any language, Ukrainian included),
**Type text** or **No note**. Voice is recorded from the default microphone with Windows MCI
(`lib/coordination/voice.py`) and saved as `note.wav` in the case folder.
In the cloud session, `tools/transcribe_cases.py` (Whisper large-v3-turbo) writes
`note.transcript.txt` next to each new recording.

Without a current clash, Before/Skip record the **selected** elements (case name `SEL-hhmmss`).

## What is recorded

```
cases/<model>/<clash check date>/CLASH-007/
  case.json     clash (both elements, linked element bbox), zone, levels, status, note
  before.jpg    screenshot of the active view before the fix
  before.json   MEP data before
  after.jpg     screenshot after the fix                (resolved only)
  after.json    MEP data after + note + diff            (resolved only)
  note.txt      [status] + note
  note.wav      voice note (if recorded)
  note.transcript.txt   transcript of the voice note (made in the cloud session)
```

Element data: id, category, family/type, size, system, workset, bounding box,
start/end (curves), length, slope, height, location (fittings), part type and angle,
connected elements. Coordinates in mm, Revit internal origin; level elevations in `case.json`.

**Recorded area** (same before and after):
- MEP within 1.5 m around the clash;
- the **whole straight runs** of the clash elements up to the next bend/branch, with MEP within 0.3 m of them.
  A fix at the clash point can create a new clash anywhere along the run.

The diff lists elements that were moved, changed (size, type, system, slope, angle),
created (new elbows, segments) or deleted.
