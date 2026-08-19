# hockeysim special-teams SHOT-multiplier calibration

Truth: 1,312 regular-season games, `boxscore` endpoint (distinct from the `landing` feed
`historical_truth/` otherwise reads — the landing feed has no shot-by-strength-state
breakdown). Bulk-fetched by `scripts/fetch_nhl_boxscore_cache.py` this session (1,297 new
fetches, 0 failures; previously only 11/1,312 games were cached). Parsed by the new
`historical_truth/boxscore_shot_strength.py` module.

**Cross-validation the parser is trustworthy**: average simulated shots/game from this
endpoint (55.27) nearly matches the independently-sourced `landing` feed's SOG count
(55.66, `TruthMetrics.shots_per_game`) — two different endpoints, two different parsers,
close agreement. PP shots convert at a materially higher rate than average (14.88% of all
shots but 19.44% of all goals are on the power play) — matches known real hockey (power-play
offense has better shot quality).

Tool: `scripts/calibrate_nhl_special_teams_shot_mult.py`. Same method as the goal-multiplier
calibration (`docs/reports/hockeysim_special_teams_goal_cal_report.md`) — the REAL engine, not a
formula approximation — but with two methodology upgrades made necessary by what this run found:

## The interaction bug this calibration found and fixed

A first pass (sequential: fit `pp_shot_cal_mult` fully with `pk_shot_cal_mult` held at the
uncalibrated 1.0, then fit `pk_shot_cal_mult`) converged cleanly on paper but left a **~5%
gap in an independent verification run — at a 260,000-shot sample**, far larger than sampling
noise could explain at that scale.

**Root cause**: `pp_shot_share` and `sh_shot_share` share a denominator, `total_shots` (EV + PP +
SH shots). Uncalibrated (`pk_shot_cal_mult=1.0`), the engine over-produces SH shots by roughly
3x. Fitting `pp_shot_cal_mult` while that inflation is still present absorbs a chunk of the
denominator bias into the fitted value; once `pk_shot_cal_mult` is corrected afterward, SH shots
drop, `total_shots` shrinks, and the previously-fitted `pp_shot_cal_mult` no longer matches truth.

**Fix**: alternate the two fits jointly (3 outer rounds, each re-fitting `pp` against the OTHER's
current best `pk` estimate, and vice versa) instead of a single sequential pass. Also switched
from random team-pairing sampling to a full round-robin (every ordered pair of the 32 teams, 992
total) to remove a second, smaller source of sample-to-sample variance.

## Before (uncalibrated, both multipliers = 1.0)

| metric | target | measured (round 1, pk still at 1.0) |
|---|---|---|
| `pp_shot_share` | 0.1488 | 0.1514 |
| `sh_shot_share` | 0.0272 | 0.0755 — **~2.8x the real rate** |

## Convergence across joint rounds (992 pairings × 6 sims/pairing = 5,952 games/batch)

```
round 1: pp=0.9793  pk=0.3366
round 2: pp=0.9126  pk=0.3341   <- pp corrects further once pk is no longer the stale 1.0
round 3: pp=0.9108  pk=0.3369   <- stable; round 2->3 movement is 0.18%, not the round 1->2 6.7% jump
```

`pk_shot_cal_mult` was stable from round 1 (0.3366/0.3341/0.3369 — a ~0.003 spread across all
three rounds); `pp_shot_cal_mult` needed the joint re-fit to converge, moving from 0.9793 (biased
by the stale `pk=1.0` placeholder) to a stable ~0.91.

## After (`pp_shot_cal_mult=0.9108`, `pk_shot_cal_mult=0.3369`)

Final verification run, fresh seed, 318,093 simulated shots:

| metric | target | measured | note |
|---|---|---|---|
| `pp_shot_share` | 0.1488 | 0.1476 | close (0.0012 absolute) |
| `sh_shot_share` | 0.0272 | 0.0272 | exact |

## Applied profile overrides

- `pp_shot_cal_mult` = `0.9108`
- `pk_shot_cal_mult` = `0.3369`

Set in `syndicate/features/nhl/sim_engine/hockeysim/calibration_profile.py`'s
`NHL_CALIBRATION_PROFILE_DEFAULT`.

## Same direction as the goal multipliers — one likely root cause, not two

`pk_shot_cal_mult`'s correction (over-simulated ~2.8x) and `pk_goal_cal_mult`'s correction
(over-simulated ~2.2x, `hockeysim_special_teams_goal_cal_report.md`) point the same direction at
similar relative magnitude. Both scale the SAME rare event class — something the shorthanded
team does (shoots, scores) during a PP/PK segment — and both were fit independently against
independent truth sources (goals from the `landing` feed, shots from `boxscore`) yet landed on
similar-sized corrections. This is circumstantial, not proven, but suggests the segment-allocation
logic that decides how much offensive activity a shorthanded team gets (`engine.py`'s PP/PK
segment loop) has one shared bias upstream of both the shot-volume and goal-conversion
multipliers, rather than two unrelated miscalibrations. Not chased further this session — flagged
for whoever next touches the PK segment-allocation mechanism.

## A known methodology gap this calibration leaves behind

The goal-multiplier calibration (earlier this session) used the ORIGINAL sequential (not joint)
fit — it predates this discovery. Its own verification match was already reasonably tight (`pp_goal_share`
0.1971 vs 0.1944 truth, a gap of similar or smaller magnitude to what the FIXED shot calibration
now achieves), so there is no direct evidence it suffers the same bias — but it was never re-run
with the joint method to confirm that. Flagged as a documented gap, not a known error: cheap to
re-run, worth doing before trusting `pp_goal_cal_mult` past its current 1-decimal precision.

## What this does NOT cover

- **Per-team differentiation of the shot multipliers** — deliberately not attempted, same
  reasoning as the goal multipliers (`model_engine_standard.md` §4.4): they are league-wide
  correction constants layered on top of the already-per-team `pp_pct`/`pk_pct` signal (which
  governs GOAL conversion, not shot volume — there is currently no per-team shot-volume signal at
  all, unlike goals). Building genuine per-team PP/PK shot-rate differentiation is a separate,
  larger piece of work: a new `HockeyTeamFeatures` field plus a new consumption formula in
  `engine.py` (there is no existing per-team analog to `pp_pct` for shot volume to extend), not a
  calibration pass. The data now exists to support it (`TeamShotStrengthRates`,
  `historical_truth/boxscore_shot_strength.py`) if a future pass wants to build it.
- **Block rates** (`block_rate_ev`/`block_rate_pk`/`block_rate_pp_def`) — no truth target for
  blocked-shot rate by strength state exists in either the `landing` or `boxscore` parsers yet
  (player-level `blockedShots` exists in the boxscore but is not split by strength state).
