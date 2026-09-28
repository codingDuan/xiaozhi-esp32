---
name: pcb-check
description: Use when checking, validating, or reporting on the KiCad board in hardware/plush-toy-mainboard — before export_fab.sh, after route.py / post_route.py / any ECO script, or whenever asked whether the board is DRC-clean or has unconnected nets.
---

# PCB Check (plush-toy-mainboard)

Board: `hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb`.
KiCad 10 CLI: `scripts/kicad_env.KICAD_CLI`.

## The Iron Rule

**A DRC result produced without refilling the copper zones is not a result. Do not report it, do not act on it, do not record it in README/STATUS.**

Copper pours are cached in the file. Any track, via, footprint move, or ECO script leaves the stored fill stale, so clearance and connectivity are computed against copper that no longer exists. Stale fill hides shorts and invents opens.

## Workflow

Run in order. Do not skip ahead.

### 1. Close KiCad and check for a lock

```sh
cd hardware/plush-toy-mainboard
ls -a | grep '\.lck$' || echo "no lock"
```

A `~<name>.kicad_pcb.lck` (or `.kicad_sch.lck` / `.kicad_pro.lck`) means the GUI has the file open. **Stop and ask the user to close KiCad.** Never delete a lock file yourself and never write to a locked board — the GUI will overwrite your changes on its next save, and `board.Save()` also rewrites `.kicad_pro` with default rules.

### 2. Refill all zones

```sh
"$KICAD_CLI" pcb drc --refill-zones --save-board \
  --format json --schematic-parity --severity-all \
  -o /tmp/drc.json plush-toy-mainboard.kicad_pcb
```

`--refill-zones` refills before checking; `--save-board` persists the fill so later steps agree. This single command does steps 2 and 3. If you refill in a script instead, use `pcbnew.ZONE_FILLER(board).Fill(board.Zones())` and then `project_rules.apply()` after saving.

### 3. Run DRC

Covered by the command above. Then run the regression test, which asserts the reviewed-baseline state:

```sh
python3 scripts/test_drc.py
```

Note: `test_drc.py` invokes `kicad-cli` **without** `--refill-zones` — it checks the saved fill. It is only meaningful after step 2 has been run and the board saved.

### 4. Report the two categories separately

Never merge these into one number.

```
未连接网络 (unconnected_items): N 处
  - <pad/net for each>
DRC 违规 (violations): M 处
  - <type / severity / location for each>
原理图一致性 (schematic_parity): K 处
```

`unconnected_items` are routing gaps — the board is incomplete.
`violations` are rule breaches — the board may be routed but unmanufacturable.
They have different causes and different fixes. "0 errors" with unreported opens is a false all-clear.

Known accepted baseline: 2 `silk_edge_clearance` **warnings** on U1 silkscreen at (-6.15, 20.8) and (-6.15, 39.2). Everything else is a regression.

## Red Flags — stop and restart the workflow

- "I just ran DRC, the fill probably didn't change" → refill anyway.
- "post_route.py already filled zones" → it did, but only if it ran and saved *after* your last edit. Refill.
- "DRC passed" reported without saying whether zones were refilled.
- Reporting a single combined count, or omitting `unconnected_items` because it was zero.
- Editing or DRC-ing the board while a `.lck` exists.

## Rationalization Table

| Excuse | Reality |
|---|---|
| "Only moved silkscreen / a label" | Refill costs seconds. Prove it, don't assume it. |
| "It's just a quick sanity check" | A quick check that can be wrong is worse than no check — it gets reported as fact. |
| "The last run was clean" | The last run was against different copper. |
| "The user only asked about unconnected nets" | Connectivity is computed from the fill too. |
| "I'll delete the .lck, KiCad is probably stale" | The GUI may hold unsaved user work. Ask. |

## Context

Another agent (codex) also edits this board — check `git log` and the working tree before and after. Full regeneration from `gen_pcb.py` does not converge; prefer an ECO on the converged board (see `README.md` in that directory).
