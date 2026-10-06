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
itself currently fails its replica assertion on main (flag OFF) — reported to lane nhl-game-lines-model.

## 7. Props backtest

(pending — base / C1 time-only / C2 time + shot re-fit; every 2nd regular-season date + all playoffs,
200 sims, `scripts/nhl_props_paired.py`)

## Leads

- Recency-weighted `committed_per_game` (the April residual).
- SH goals 0.38x real at every PP time — not a time effect.
- Engine goalie (`_starter_goalie` = max toi_proj) differs from the props starter (flagged) in ~1 of 5
  team-games on this population — told lane nhl-player-props-projection's session.
