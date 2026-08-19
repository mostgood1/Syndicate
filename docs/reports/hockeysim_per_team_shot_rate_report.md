# hockeysim per-team PP/PK shot-rate differentiation

A NEW mechanism, not a calibration of an existing one — the last gap flagged across the two shot/
goal calibration reports: before this, the engine's PP/PK SHOT-volume formula
(`pp_mult_shots`/`pk_mult_shots`, `engine.py`) had NO per-team component at all. `pp_pct`/`pk_pct`
already differentiate GOAL conversion per team; `cal_pp_sh_mult`/`cal_pk_sh_mult`
(`hockeysim_special_teams_shot_cal_report.md`) are LEAGUE-WIDE calibration constants. Shot volume
itself was identical for every team.

## The new signal

`historical_truth/boxscore_shot_strength.py::compute_team_shot_rate_index` — for each team:

```
pp_shot_index          = (team's PP shots / team's PP opportunities) / the SAME ratio league-wide
pk_shot_index_allowed  = (team's PK shots-against / team's PK opportunities) / the SAME ratio league-wide
```

Deliberately normalized by OPPORTUNITY count (from `special_teams_builder`'s penalty-derived
`pp_opportunities`/`pk_opportunities`), not raw per-game shot count — a raw count conflates "how
often this team is on the power play" (already captured by `committed_per_game`) with "how many
shots it generates once there," which is the genuinely new, independent signal this carries.
Below `MIN_OPPORTUNITIES_FOR_SHOT_INDEX` (15, same floor as `special_teams_builder`'s `pp_pct`),
falls back to the neutral `DEFAULT_SHOT_INDEX` (1.0) rather than publish a noisy ratio.

**Measured on real data** (1,312 games, 32 teams): mean `pp_shot_index` 1.0056, mean
`pk_shot_index_allowed` 1.0056 — both close to 1.0 by construction (every team is measured
against the same league-wide reference ratio). Real spread: NJD generates the most shots per PP
chance (1.237x league average), MTL the fewest (0.802x) — a meaningful ~54% top-to-bottom spread.
EDM appears near the top of `pp_shot_index` (1.137x) — consistent with Edmonton's independently-
measured elite PP GOAL rate (`hockeysim_special_teams_goal_cal_report.md`: 27.5% PP%, the league's
best) — a team known for an elite power play shows up as both shot-heavy AND efficient, in two
unrelated data sources.

## Wiring

`engine.py`: `st_home.get("pp_shot_index", 1.0)` / `st_away.get("pk_shot_index_allowed", 1.0)`
(and the symmetric pair) multiply directly into `home_factor`/`away_factor` alongside the
existing `pp_mult_shots`/`pk_mult_shots`, read ONCE per game (not per-segment, since neither
value changes within a game):

```
if seg_is_home_pp:
    home_factor *= pp_mult_shots * pp_shot_idx_home
    away_factor *= pk_mult_shots * pk_shot_idx_away
elif seg_is_away_pp:
    away_factor *= pp_mult_shots * pp_shot_idx_away
    home_factor *= pk_mult_shots * pk_shot_idx_home
```

`scripts/build_nhl_special_teams_artifact.py` now writes `pp_shot_index`/`pk_shot_index_allowed`
as two ADDITIONAL columns on the SAME `team_special_teams_{season}.csv` artifact (not a second
file) when a `boxscore` cache is present; degrades to the neutral default when it is not (the
"never break" discipline every other loader in this package follows).

## Verified the existing global calibration did not need re-fitting

`pp_shot_cal_mult`/`pk_shot_cal_mult` (`hockeysim_special_teams_shot_cal_report.md`) were fit
BEFORE this mechanism existed, i.e. with every team implicitly at the neutral shot index. Because
the new per-team indices are, by construction, measured against the SAME league-wide reference
ratio (mean ≈ 1.006 across 32 real teams), re-running the full round-robin simulation WITH real
per-team indices active should reproduce the same league-wide aggregate the global fit already
matched — verified, not assumed:

| metric | truth | simulated with real per-team indices | simulated at the original calibration (no per-team layer) |
|---|---|---|---|
| `pp_shot_share` | 0.1488 | 0.1478 | 0.1476 |
| `sh_shot_share` | 0.0272 | 0.0279 | 0.0272 |

(992 round-robin pairings × 3 sims, 158,826 total simulated shots.) Both readings land within the
same small margin of truth — the per-team layer changes WHICH team gets more/fewer shots in a
given matchup, not the league-wide average, exactly as designed. No re-calibration needed.

## Reachability tests

- `tests/test_hockeysim_engine.py::test_special_teams_pp_shot_index_actually_changes_shot_volume`
  — `pp_shot_index=1.8` produces measurably more HOME shots than `pp_shot_index=0.4` on average
  (80 seeded runs), everything else held identical.
- `tests/test_hockeysim_loaders.py::test_load_team_special_teams_map_reads_shot_index_when_present`
  — the artifact's two new columns actually reach `HockeyTeamFeatures.special_teams`.
- `tests/test_hockeysim_boxscore_shot_strength.py` — the index computation itself: neutral below
  the opportunity floor, correctly directional for a real above-average generator, and the
  league-mean-≈1.0 property on a synthetic 4-team round-robin.

## What this does NOT cover

- **Block rates** (`block_rate_*`) — still no per-team or truth-calibrated signal at all; the
  boxscore's player-level `blockedShots` is not split by strength state.
- **Faceoff-driven PP/PK shot-share effects** — `engine.py`'s existing faceoff multiplier
  (`_faceoff_multipliers`) is EV-only by default (`faceoff_ev_only=True`) and untouched by this
  pass; not evaluated for interaction with the new per-team shot index.
- **A second re-fit pass on a wider sample** — the verification above used a moderate sample
  (158,826 shots); the numbers are stable and close to truth, but a larger confirmatory run
  (matching the ~318K-shot scale of the original calibration's own final verification) would be
  cheap insurance before treating the "no re-fit needed" finding as fully closed.
