# NHL hockeysim power-play TIME — lane `nhl-pp-time` (2026-10-05)

Scope (user decision 2026-10-05): team PP **time** only. The PP1/PP2 share is lane `nhl-elite-pp-onice`'s
("Per-player PP time"); the two flags compose.

## 1. Re-derivation (before any change)

Population: lane `nhl-elite-pp-onice`'s 45 slates (2025-26 regular season, `bt_scratch` as-of roots,
`random.Random(11)` over Nov-Apr), 345 games / 690 team-games, 40 sims per game, production engine
(main, default config). Real side: **official NHL stats `team/powerplaytime?isGame=true`**
(`timeOnIcePp`, `powerPlayGoalsFor`); team goals / SOG / PP SOG / SH SOG from cached play-by-play
(regulation + OT, no shootout). CIs: game-clustered bootstrap, 1,000 draws.
Tool: `scripts/nhl_pp_time_engine_measure.py` (engine-direct) + `--rescore`.

| per team-game | sim | real | ratio [95% CI] |
|---|---|---|---|
| PP minutes | 6.84 | 4.66 | **1.468 [1.407, 1.530]** |
| PP goals | 0.623 | 0.570 | 1.093 [0.988, 1.223] |
| PP SOG | 4.13 | 4.05 | 1.019 [0.963, 1.078] |
| SH SOG | 0.756 | 0.739 | 1.023 [0.931, 1.128] |
| SH goals | 0.031 | 0.081 | 0.377 [0.296, 0.501] |
| goals | 3.33 | 3.07 | 1.087 [1.045, 1.130] |
| SOG | 27.06 | 27.74 | 0.976 [0.961, 0.992] |

1.47x re-derived. (A first attempt used pbp `situationCode` intervals and read real PP 5.14 min:
it credits an expired PP until the next play. The official field agrees with the skater-TOI/5
definition the other lane used, 4.74 season-wide.)

## 2. Mechanism, file:line

- `engine.py` PP segment sampler (`simulate_period_with_lines`, block after the faceoff-lineup
  reads): `pp_frac_total = (h_comm + a_comm) x 120 s / 3600 s`, split `a_comm/(h+a)` — every committed
  minor = 120 s of PP for the opponent. Each of ~30 segments/period is PP with that probability,
  independently; a PP goal ends nothing.
- OT: the same branch divides by the OT window (300 s), so `(h+a) x 120 / 300` hits the **0.45 cap**:
  ~45% of OT is a PP. Sim OT PP 0.22 min/team-game vs real ~0.05 (OT carries 1.0% of real PP time).
- Input: `committed_per_game` = all `MIN` penalties per game (`nhl_statsweb_loader.py:234-243` ->
  `special_teams_builder.py:94`), as-of. Coincidental minors are counted (0.49/team-game in 2025-26).
- Sim PP = opponent as-of committed x 2 min (6.60) + OT (0.22) = 6.82 ~ measured 6.84. **H1 supported.**
- Real per minor: 0.733 x 120 s = 88.0 s (2025-26), 0.741 = 88.9 s (2024-25). PP opportunities 2.879 vs
  minors 3.236 per team-game; 98-100 s per opportunity every month.
- Not double counted: one team-level rate drives segments; no per-player penalty term exists.
- PK time is symmetric by construction (one segment = one side's PP and the other's PK): sim PK
  6.80 vs PP 6.84 min/team-game.

## 3. Compensation (H2)

PP and SH shot COUNTS were right at 1.47x the time, so the per-minute multipliers
(`pp_shot_cal_mult` 0.9108, `pk_shot_cal_mult` 0.3369, fitted to strength-state SHARES with the
inflated time) were absorbing it. Time-only fix (`per_minor`, 88.9 s, out of sample):
PP goals 0.623 -> 0.453 (-27%), PP SOG 0.74x real, SH SOG 0.75x. **H2 supported.**

## 4. The fix (landed default-off, b6da3211)

`SimConfig.pp_time_model` = `"minors_2min"` (default, byte-identical — verified on 712 team-games'
sim fields) | `"per_minor"` (`pp_seconds_per_minor` per committed minor; OT at the regulation rate).
Kill switch: env `SYNDICATE_NHL_PP_TIME_MODEL=minors_2min`. Reachability: `tests/test_hockeysim_pp_time.py`
(off != on; env switch restores the legacy event stream exactly).

Time-only, 88.9 s: PP 4.99 vs 4.66 = **1.071 [1.026, 1.116]** — the pre-registered +/-5% is NOT met.
The residual is seasonal: real PP time falls through the season (Oct 5.36 -> Apr 4.33 min/team-game)
and the as-of season-to-date committed rate lags; sim/real by month Nov 1.05, Dec 1.03, Jan 1.08,
Feb 1.02, Mar 1.04, **Apr 1.26**.

## 5. Re-fit (decided before any props backtest)

Fitted on the Nov-Dec dates (230 team-games), Jan-Apr held out: k_pp_shot 1.361 (holdout 1.343),
k_pk_shot 1.374 (holdout 1.310), k_pp_goal 0.770 (holdout 1.017 — unstable). Arm C2 =
per_minor 88.9 + `pp_shot_cal_mult` 1.2399 + `pk_shot_cal_mult` 0.4630; PP goal conversion unchanged.

## 6. Game lines

Inert by construction: game-line lambdas come from `projection.py` -> `market_anchoring` ->
`adapters` -> `game_market_sim`, none of which imports `engine.py`. Verified: production
`predict_game` byte-identical flag on/off, 83 games (10 dates Jan-Mar 2026). The game-lines harness
failed its replica assertion because production defaults to the calibrated game sim since 7865b26e (not GSAx/score-adj); fixed by lane nhl-game-lines-model.

## 7. Props backtest (paired, production af737b31+ engine = per-player PP minutes)

Runs: `scripts/backtest_nhl_props.py` roots/inputs, driven in-process (memory), every 3rd 2025-26
regular-season date from 11-01 (48 dates, 13,161 skater-games, 523 starter-goalie games) + all 44
playoff dates (2,769 / 145), 200 sims, same seeds. Scored by `scripts/nhl_props_paired.py`
(empirical sim P(over), game-clustered CIs). Arms (profiles via SYNDICATE_CALIBRATION_PROFILE_PATH_NHL):
- C1 time-only: per_minor 88.9 s.
- C2: C1 + pp_shot_cal_mult 1.2418 / pk_shot_cal_mult 0.4368 (re-fit on the current engine, Nov-Dec;
  k_pp 1.363 holdout 1.297, k_pk 1.297 holdout 1.362).
- C3 (pre-registered after C2's engine measure): C2 + ev_shot_scale 0.9267 / ev_goal_scale 1.003
  (Nov-Dec fit so team SOG and goals equal production's; holdout 0.932 / 0.998).

Engine measures (current engine, 386 games / 772 team-games), sim / real ratio:

| | production | C1 | C2 | C3 |
|---|---|---|---|---|
| PP min | 1.494 | 1.087 | 1.088 | 1.086 |
| PP goals | 1.046 | 0.757 | 1.040 | 1.036 |
| PP SOG | 1.038 | 0.755 | 1.032 | 1.028 |
| team SOG | 0.979 | 0.995 | 1.040 | 0.977 |
| team goals | 1.078 | 1.085 | 1.145 | 1.079 |

### regular (Brier d x1000 vs production, game-clustered 95% CI; W = worse, B = better)

| market@line | segment | n | production Brier | C1 time-only | C2 +shot re-fit | C3 +EV level |
|---|---|---|---|---|---|---|
| SOG@1.5 | all | 13161 | 0.2151 | +0.60 [-0.16,+1.31] | +0.97 [+0.16,+1.80] W | +0.10 [-0.61,+0.79] |
| SOG@2.5 | all | 13161 | 0.1516 | -0.35 [-0.95,+0.20] | +0.18 [-0.53,+0.85] | -0.32 [-0.84,+0.21] |
| SOG@3.5 | all | 13161 | 0.0861 | -0.30 [-0.68,+0.08] | -0.07 [-0.50,+0.35] | -0.35 [-0.71,-0.01] B |
| GOALS@0.5 | all | 13161 | 0.1265 | -0.03 [-0.46,+0.39] | +0.19 [-0.28,+0.71] | -0.32 [-0.76,+0.16] |
| ASSISTS@0.5 | all | 13161 | 0.1775 | +1.30 [+0.72,+1.90] W | +1.44 [+0.74,+2.15] W | +0.96 [+0.35,+1.54] W |
| POINTS@0.5 | all | 13161 | 0.2090 | +1.23 [+0.36,+1.97] W | +1.61 [+0.72,+2.56] W | +0.89 [+0.11,+1.66] W |
| POINTS@1.5 | all | 13161 | 0.0770 | +0.26 [-0.07,+0.61] | +0.25 [-0.12,+0.61] | +0.17 [-0.20,+0.49] |
| BLOCKS@1.5 | all | 13161 | 0.1368 | -1.44 [-1.97,-0.91] B | +1.04 [+0.48,+1.56] W | +0.46 [-0.06,+0.94] |
| SOG@1.5 | elite | 1141 | 0.1907 | +0.71 [-1.42,+2.81] | -1.56 [-3.79,+0.79] | +0.07 [-1.81,+2.03] |
| SOG@2.5 | elite | 1141 | 0.2437 | -0.81 [-3.47,+1.80] | -1.34 [-4.57,+2.01] | -2.39 [-5.23,+0.21] |
| SOG@3.5 | elite | 1141 | 0.2020 | -0.04 [-2.38,+2.43] | -0.10 [-2.90,+2.51] | -0.11 [-2.30,+2.11] |
| GOALS@0.5 | elite | 1141 | 0.2210 | -0.99 [-3.70,+1.44] | -1.08 [-3.73,+1.61] | -1.29 [-3.69,+1.13] |
| ASSISTS@0.5 | elite | 1141 | 0.2516 | +2.09 [-0.71,+4.89] | -0.81 [-3.50,+1.85] | +0.62 [-2.02,+3.53] |
| POINTS@0.5 | elite | 1141 | 0.2314 | +1.97 [-1.10,+5.05] | -0.81 [-3.81,+2.35] | +2.03 [-0.81,+5.03] |
| POINTS@1.5 | elite | 1141 | 0.1954 | +2.48 [+0.03,+5.14] W | +0.29 [-2.04,+2.54] | +0.57 [-1.53,+2.88] |
| BLOCKS@1.5 | elite | 1141 | 0.0952 | -0.06 [-1.32,+1.23] | +1.39 [+0.10,+2.75] W | +0.20 [-1.07,+1.43] |
| SAVES@22.5 | goalie starter | 523 | 0.3037 | -1.44 [-5.72,+2.85] | +0.50 [-8.06,+9.03] | +2.67 [-1.04,+6.52] |
| SAVES@25.5 | goalie starter | 523 | 0.2726 | +2.53 [-2.32,+7.16] | +5.70 [-2.63,+14.90] | +3.36 [-0.23,+6.93] |
| SAVES@28.5 | goalie starter | 523 | 0.1986 | -2.41 [-5.25,+0.58] | +3.72 [-2.46,+10.01] | +0.63 [-1.97,+3.26] |

### playoff (Brier d x1000 vs production, game-clustered 95% CI; W = worse, B = better)

| market@line | segment | n | production Brier | C1 time-only | C2 +shot re-fit | C3 +EV level |
|---|---|---|---|---|---|---|
| SOG@1.5 | all | 2769 | 0.2139 | +0.80 [-0.68,+2.32] | -0.13 [-1.92,+1.76] | -0.87 [-2.42,+0.79] |
| SOG@2.5 | all | 2769 | 0.1559 | -0.79 [-2.13,+0.35] | -0.14 [-1.60,+1.18] | -0.88 [-2.03,+0.22] |
| SOG@3.5 | all | 2769 | 0.0923 | -1.24 [-2.10,-0.42] B | -0.79 [-1.87,+0.21] | -1.11 [-1.79,-0.39] B |
| GOALS@0.5 | all | 2769 | 0.1238 | -0.16 [-1.11,+0.85] | -0.02 [-0.96,+0.96] | -0.17 [-1.15,+0.88] |
| ASSISTS@0.5 | all | 2769 | 0.1717 | +1.24 [-0.21,+2.75] | +1.16 [-0.36,+2.66] | +0.55 [-0.87,+1.91] |
| POINTS@0.5 | all | 2769 | 0.2097 | +1.40 [-0.31,+3.21] | +2.24 [+0.46,+4.11] W | +0.72 [-0.89,+2.38] |
| POINTS@1.5 | all | 2769 | 0.0744 | +0.14 [-0.53,+0.79] | +0.77 [+0.10,+1.35] W | +0.47 [-0.19,+1.05] |
| BLOCKS@1.5 | all | 2769 | 0.1448 | -1.83 [-2.90,-0.72] B | -0.95 [-2.11,+0.31] | +0.24 [-0.97,+1.41] |
| SOG@1.5 | elite | 376 | 0.2031 | +3.38 [-0.29,+7.13] | +2.35 [-1.45,+6.15] | +0.89 [-2.57,+4.37] |
| SOG@2.5 | elite | 376 | 0.2475 | +1.30 [-3.14,+5.84] | +1.10 [-4.18,+6.67] | -2.59 [-7.04,+1.79] |
| SOG@3.5 | elite | 376 | 0.2089 | -1.70 [-5.64,+2.30] | -1.97 [-7.00,+3.12] | -4.50 [-8.49,-0.90] B |
| GOALS@0.5 | elite | 376 | 0.1952 | +0.69 [-3.76,+4.78] | +0.53 [-3.27,+3.77] | +0.77 [-3.27,+4.40] |
| ASSISTS@0.5 | elite | 376 | 0.2457 | +1.40 [-3.64,+6.77] | -1.92 [-6.45,+2.72] | +1.82 [-2.88,+6.57] |
| POINTS@0.5 | elite | 376 | 0.2388 | +0.71 [-5.31,+6.56] | -0.07 [-4.88,+4.73] | +0.44 [-4.34,+5.06] |
| POINTS@1.5 | elite | 376 | 0.1782 | -1.46 [-5.09,+2.52] | -0.34 [-3.90,+2.83] | +0.93 [-2.36,+4.12] |
| BLOCKS@1.5 | elite | 376 | 0.1245 | -1.44 [-3.96,+0.89] | -0.49 [-2.98,+1.88] | +1.09 [-1.28,+3.35] |
| SAVES@22.5 | goalie starter | 145 | 0.2310 | -4.83 [-12.94,+3.12] | -8.11 [-22.68,+6.74] | -5.06 [-12.56,+2.74] |
| SAVES@25.5 | goalie starter | 145 | 0.2581 | -7.27 [-14.77,+0.62] | -4.49 [-20.60,+12.07] | -2.88 [-9.91,+4.56] |
| SAVES@28.5 | goalie starter | 145 | 0.2122 | -5.90 [-13.55,+1.09] | -6.66 [-22.14,+7.28] | +0.51 [-4.36,+5.44] |

Reading: C3 is the only arm that fixes PP time and keeps the team level; it is better on SOG@3.5
(regular and playoffs) and WORSE on ASSISTS@0.5 (+0.00096 [+0.00035, +0.00154]) and POINTS@0.5
(+0.00089 [+0.00011, +0.00166]) in the regular season. Null false-WORSE rate: 14 lines x 2 phases at
~2.5% each -> ~0.7 expected by chance; ASSISTS@0.5 is consistent across C1/C2/C3, so it is not noise.
Likely absorber: assist attribution (`assist_share`, position power 1.5) was fitted under the old PP
time. Nothing enabled.

## 8. PK units (found, not fixed)

PK1 skaters ~88% of team PK time (6.0 sim vs 2.1-2.5 real PK min/game), PK2 0.15 vs 0.42 share, skaters
outside the PK units 0 vs 0.06-0.14 -- the fixed-unit defect PP had before af737b31.

## Leads

- Recency-weighted `committed_per_game` (the April residual).
- SH goals 0.38x real at every PP time — not a time effect.
- Engine goalie (`_starter_goalie` = max toi_proj) differs from the props starter (flagged) in ~1 of 5
  team-games -- cosmetic: SAVES are credited to the flagged starter (props_boxscore), so no priced number moves.
