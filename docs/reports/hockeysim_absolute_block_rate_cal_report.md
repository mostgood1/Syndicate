# hockeysim absolute block-rate calibration

Closes the gap `hockeysim_per_team_block_rate_report.md` explicitly left open: that pass built
PER-TEAM relative differentiation (`block_rate_index`) but left the vendor's original, never-measured
base constants — `block_rate_ev=0.45`, `block_rate_pk=0.55`, `block_rate_pp_def=0.35` — untouched.
This pass calibrates the ABSOLUTE level.

## Why one shared scale, not three independent fits

The truth source (`historical_truth.boxscore_block_rate`) has exactly ONE league-wide target: real
average blocks/team/game. Blocked shots carry no strength-state breakdown in the `boxscore` payload
at all (unlike PP/PK shots, which the per-goalie splits do carry) — so there is no way to fit
`block_rate_ev`, `block_rate_pk`, and `block_rate_pp_def` independently; three unknowns against one
number is underdetermined. `scripts/calibrate_nhl_block_rate.py` instead fits ONE proportional
scale factor `k`, applied uniformly to all three, preserving their existing structural ratio
(higher on the penalty kill, lower while on the power play defending) — the only degree of freedom
the data actually supports, per `model_engine_standard.md` §4.4 (don't invent an unconstrained
degree of freedom).

## Truth target

`build_league_block_rate_snapshot`, 1,312 regular-season games: **blocks_per_game(team) = 14.1905**
(same number the per-team report already established).

## Method

Fit `block_scale` with `block_rate_index` (§2g's per-team layer) held NEUTRAL for every team, to
isolate "what absolute scale matches truth" from "how do teams differ from each other" —
mechanism-vs-estimator, same split every other calibration this session used. Real per-team
`pp_pct`/`pk_pct`/`committed_per_game`/`pp_shot_index`/`pk_shot_index_allowed` were left ON (the
substrate production actually runs on), only `block_rate_index` was pinned to 1.0 during the fit.
Random-sample pairings during the iterative search (a single-parameter proportional fit against one
plain mean has no shared-denominator or cross-parameter bias to protect against, unlike the
shot-multiplier calibration's joint 2-parameter fit) — full 992-pairing round-robin reserved for the
two final verification runs.

Proportional-correction search converged in 5 iterations:

| iter | scale | measured | target |
|---|---|---|---|
| 0 | 1.0000 | 13.2613 | 14.1905 |
| 1 | 1.0701 | 14.2800 | 14.1905 |
| 2 | 1.0634 | 14.1821 | 14.1905 |
| 3 | 1.0640 | 14.1958 | 14.1905 |
| 4 | 1.0636 | 14.1975 | 14.1905 |

**Result: `block_scale = 1.0631`** — a modest ~6.3% uniform correction.

| constant | old (vendor, uncalibrated) | new (calibrated) |
|---|---|---|
| `block_rate_ev` | 0.45 | 0.4784 |
| `block_rate_pk` | 0.55 | 0.5847 |
| `block_rate_pp_def` | 0.35 | 0.3721 |

## Verified twice, fresh seed, full round-robin (992 pairings × 20 sims = 19,840 games each)

| | simulated blocks/game(team) | target | delta |
|---|---|---|---|
| `block_rate_index` still NEUTRAL | 14.2606 | 14.1905 | +0.5% |
| REAL per-team `block_rate_index` active | 14.2583 | 14.1905 | +0.48% |

Both runs land within ~0.5% of truth, well inside simulation noise. The second run is the important
one: it confirms — again, now with the CALIBRATED base — that turning the real per-team index back
on does not disturb the league-wide level, exactly the same property verified (at the uncalibrated
base) in the per-team report.

## What this completes

All three of hockeysim's special-teams block-rate constants are now both (a) differentiated by team
(§2g) and (b) calibrated in absolute terms against real truth (§2h, this report) — the last item on
the special-teams punch list this session opened. `nhl_sim_input_checklist.py`'s Part B now reports
`blocks_ev_rate`/`blocks_pk_rate`/`blocks_pp_def_rate` as "calibrated (differs from the old neutral
default)", matching the other four `special_teams_cal` keys.

## What remains open

- **Strength-state-specific calibration** — the single-scale approach preserves the vendor's
  ORIGINAL EV/PK/PP-def ratio (0.45 : 0.55 : 0.35), which was never itself validated against real
  per-strength-state block data (no such data exists in any source checked this session). If a
  strength-state-split block data source is ever found, the ratio itself — not just the overall
  scale — could be re-fit.
- **A true shot-ATTEMPT basis** — the calibration still runs on the engine's existing SOG-equivalent
  "shot" event population, the same basis mismatch `engine.py`'s own long-standing comment flags.
  This pass calibrates the CONSTANT that compensates for that mismatch to match real output; it does
  not remove the mismatch itself (would require the engine to simulate shot attempts, not just SOG).
