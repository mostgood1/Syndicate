# hockeysim special-teams goal-multiplier calibration

Truth: 1,312 games, season 20252026, 2025-10-07..2026-04-16 (source `nhl_statsweb_landing`) —
the same cache Phase 3/3b used.

Tool: `scripts/calibrate_nhl_special_teams_goal_mult.py`, proportional-correction search over the
REAL engine (not a formula approximation), synthetic-but-neutral rosters, real per-team `pp_pct`/
`pk_pct` (`team_special_teams_latest.csv`), league-average base rates (`goals_per_60`=3.1269,
`shots_per_60`=27.8323, both derived from this same truth snapshot). Final verification run:
50 team pairings × 40 sims = 2,000 games, 12,862 simulated goals.

## Before (uncalibrated, `pp_goal_cal_mult=1.0`, `pk_goal_cal_mult=1.0`)

| metric | target | measured | note |
|---|---|---|---|
| `pp_goal_share` | 0.1944 | 0.1938 | already close — the `pp_pct` mechanism + existing `pp_shots_mult=1.4` were doing their job |
| `sh_goal_share` | 0.0250 | 0.0538 | **more than double the real rate** |

## After (`pp_goal_cal_mult=1.0`, `pk_goal_cal_mult=0.4645`)

| metric | target | measured | note |
|---|---|---|---|
| `pp_goal_share` | 0.1944 | 0.1971 | within noise band |
| `sh_goal_share` | 0.0250 | 0.0246 | matches |

## Search convergence

```
pp_goal_cal_mult (target 0.1944):
  iter 0: mult=1.0000 -> measured=0.1938 -> next=1.0029
  iter 1: mult=1.0029 -> measured=0.1946 -> next=1.0021
  iter 2: mult=1.0021 -> measured=0.1946 -> next=1.0013
  iter 3: mult=1.0013 -> measured=0.1942 -> next=1.0021
  -- oscillates within [1.0013, 1.0029], statistically indistinguishable from 1.0.
  ADOPTED: 1.0 (no correction; the fitted value is noise, not signal).

pk_goal_cal_mult (target 0.0250, using the fitted pp_goal_cal_mult):
  iter 0: mult=1.0000 -> measured=0.0538 -> next=0.4649
  iter 1: mult=0.4649 -> measured=0.0251 -> next=0.4634
  iter 2: mult=0.4634 -> measured=0.0249 -> next=0.4646
  iter 3: mult=0.4646 -> measured=0.0250 -> next=0.4645
  -- converged, stable to 3 decimal places across iterations 1-3.
  ADOPTED: 0.4645.
```

## Applied profile overrides

- `pp_goal_cal_mult` = `1.0` (no change from neutral — measured correction was noise-level)
- `pk_goal_cal_mult` = `0.4645`

Set in `syndicate/features/nhl/sim_engine/hockeysim/calibration_profile.py`'s
`NHL_CALIBRATION_PROFILE_DEFAULT`.

## Why `pk_goal_cal_mult` specifically, and why it was so far off

`cal_pk_gl_mult` scales the DEFENDING (shorthanded) team's own goal-scoring chance during a PP/PK
segment — i.e. shorthanded goals, a distinct and much rarer event than the primary PP-goal event
`cal_pp_gl_mult` governs. The uncalibrated formula (`p_goal_away = p_goal_away * (0.9 * pk_pct) *
cal_pk_gl_mult`, `engine.py:1000`) used `0.9 * pk_pct` (typically ≈0.9 × 0.8 ≈ 0.72) as its base
scale — a value evidently tuned for some OTHER purpose (or carried over from the absorbed vendor
engine without this specific check) rather than fit against the real shorthanded-goal rate, which
this session's truth-parser extension (`sh_goals_home`/`sh_goals_away`, `historical_truth/
contracts.py`) made measurable for the first time. `sh_goal_share` did not exist as a truth metric
before this pass.

## What this does NOT cover

- **`pp_shot_cal_mult`/`pk_shot_cal_mult`** — no truth target exists for PP/PK shot VOLUME
  specifically (only goal counts are parsed from the landing feed; shot-by-strength-state data
  lives in the separate `boxscore` endpoint, verified to exist but only 11/1,312 games cached
  locally — `hockeysim_engine_reference.md` §5).
- **`block_rate_ev`/`block_rate_pk`/`block_rate_pp_def`** — no truth target for blocked-shot rate
  by strength state exists in the current parser either.
- **Per-team differentiation in the multipliers themselves** — deliberately not attempted.
  `pp_goal_cal_mult`/`pk_goal_cal_mult` are LEAGUE-WIDE correction constants layered on top of the
  already-per-team `pp_pct`/`pk_pct` signal; making them per-team too would double-count against
  that signal (`model_engine_standard.md` §4.4).
