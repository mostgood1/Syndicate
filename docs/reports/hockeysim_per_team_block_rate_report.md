# hockeysim per-team block-rate differentiation

A NEW mechanism, closing the last special-teams gap flagged across the shot-rate report
(`hockeysim_per_team_shot_rate_report.md`): `block_rate_ev`/`block_rate_pk`/`block_rate_pp_def`
(`engine.py`'s `p_block_ev`/`p_block_pk`/`p_block_pp_def`) had no per-team differentiation, and had
**never been checked against a real block rate at all** — the vendor's shipped defaults
(0.45/0.55/0.35) were never measured against anything.

## The new signal

`historical_truth/boxscore_block_rate.py::compute_team_block_rate_index` — for each team:

```
block_index = (team's blocks / team's shots faced) / the SAME ratio league-wide
```

`shots faced` = opponent's SOG + this team's own blocks (SOG + blocks, since shot ATTEMPTS aren't
available from this endpoint — only shots-on-goal and blocks are). This is the SAME basis mismatch
`engine.py`'s own comment on `block_rate_ev` already documents ("a blocked shot is recorded on a
shot attempt, not a shot on goal... a higher default block probability is needed to match observed
per-game block totals"). Rather than overwrite the engine's constants with an absolute number on
the wrong basis, the index is measured RELATIVE to the SAME wrong-basis league average — the basis
mismatch cancels out in the ratio, exactly the same reasoning `compute_team_shot_rate_index`
already uses for PP/PK shot volume.

**Measured on real data** (1,312 games, 32 teams): league block rate 33.77% (blocks / (SOG +
blocks) faced), 14.19 blocks/game/team — both plausible real NHL figures. Mean index 0.9999 —
essentially exact, confirming proper normalization. Real spread: PHI (1.102x), VGK (1.098x), MTL
(1.091x) block the most relative to league average; NSH (0.867x) and CHI (0.869x) the least — a
meaningful ~27% top-to-bottom spread (1.102/0.867).

**No strength-state split available.** Unlike PP/PK shot volume (which the boxscore's per-goalie
splits do carry), blocked shots in this endpoint are a per-player SEASON-GAME TOTAL with no
strength-state breakdown at all. `block_index` is therefore ONE combined per-team factor, applied
uniformly to all three of the engine's existing strength-state constants — their STRUCTURAL
difference (higher on the penalty kill, lower on the power play) stays intact; only the per-team
SCALE on top of that structure is new.

## Wiring

`engine.py`: `st_home.get("block_rate_index", 1.0)`/`st_away.get("block_rate_index", 1.0)`, read
once per game, multiply the BLOCKING team's own probability (`p_blk_home`/`p_blk_away`) right
before the block roll, clamped to `[0.02, 0.95]`:

```
p_blk_away = max(0.02, min(0.95, p_blk_away * block_idx_away))
p_blk_home = max(0.02, min(0.95, p_blk_home * block_idx_home))
```

`scripts/build_nhl_special_teams_artifact.py` now writes `block_rate_index` as a third additional
column on the existing `team_special_teams_{season}.csv` (alongside the two shot-index columns
from the prior pass), sharing ONE read of the `boxscore` cache with the shot-index computation
(both parse the same 1,312 payloads, differently) rather than reading the cache twice.

## Verified the league-wide average did not shift

Ran the engine over 200 real team pairings, once with every team at the neutral index (1.0) and
once with real per-team indices active:

| | avg total blocks/game (both teams) |
|---|---|
| neutral index | 24.635 |
| real per-team index | 24.475 |

A ~0.6% difference — well within simulation noise, confirming the per-team layer redistributes
blocks BETWEEN teams (a heavy blocker gets more, a light one fewer) without shifting the
league-wide average, exactly as designed (the index is constructed to average to 1.0).

**What this does NOT do — stated plainly, not glossed over**: this does NOT calibrate the
ABSOLUTE block rate to real truth. The simulated per-team average (~12.2-12.3 blocks/game/team,
half of 24.5) is somewhat below the real measured 14.19/game/team — the base constants
(`block_rate_ev=0.45` etc.) remain the vendor's original, uncalibrated guess. Only RELATIVE
per-team differentiation was built this pass, matching the scope of the request ("per-team block
rates"), not an absolute-level truth calibration (which would need a different fix — likely
re-deriving the base constants against a true shot-ATTEMPT basis, not available from current data
sources).

## Reachability tested

`tests/test_hockeysim_engine.py::test_special_teams_block_rate_index_actually_changes_block_volume`
— `block_rate_index=1.8` produces measurably more HOME blocks than `block_rate_index=0.3` on
average (80 seeded runs), everything else held identical.

## What remains open

- **Absolute block-rate calibration** — as stated above, not attempted this pass.
- **Strength-state-specific per-team blocking** (does a team's PK unit block more per-team than
  its EV unit, relative to other teams' PK units?) — no data source distinguishes this.
- This completes the special-teams track this session set out to build: PP/PK goal conversion
  (per-team + league calibration), PP/PK shot volume (per-team + league calibration), and now
  blocked-shot tendency (per-team only — no league-wide truth-calibration target exists for the
  absolute rate).
