# The NFL Fantasy Football projection engine

> Written 2026-08-21, `lane nfl-fantasy-projections`. This is the document
> `docs/ai_context/model_engine_standard.md` §2 requires: the full pipeline
> trace with file:line at each hop, plus the reuse flags, the substrate rules,
> and what has and has not been measured.

## What it is

An ESPN-scoring projection engine for QB / RB / WR / TE / K / D-ST, producing
both **season totals** (for a draft) and **per-week** projections (for start-sit
and waiver claims). Served at `/nfl/fantasy`, JSON at
`/nfl/api/fantasy/projections` and `/nfl/api/fantasy/draft-board`.

## The model in one paragraph

Fantasy points are opportunity × efficiency, and the two behave completely
differently, so the engine never mixes them. **Opportunity is a closed system
per team**: a team has so many plays, so many are passes, and each targets
exactly one player, so every projection is a *share* of a pool and the shares
normalise so the team's season is exactly consumed. **Efficiency is shrunk hard**
toward a position mean by the player's own sample size. The closed-pool property
is what makes roster change work without special cases — a departed WR1 leaves
the denominator and everyone else rises automatically.

## Pipeline trace

```
scripts/build_nfl_fantasy_usage.py                    (WORKER job, never a route)
  -> fantasy_usage.build_season_game_lines            fantasy_usage.py:~300
       reads  tracking/nflverse/pbp/pbp_{season}.csv  via sources.nfl_pbp_path (`#441`)
       writes nfl_source/fantasy/nfl_fantasy_usage_{season}.json   (~4.7 MB/season)
              carries BOTH season totals and the per-game lines they sum from;
              tests/test_nfl_fantasy.py asserts that identity

scripts/fetch_nfl_rosters_depth_charts.py             (WORKER job)
       writes tracking/nflverse/roster/roster_{season}.csv
              tracking/nflverse/depth_charts/depth_charts_{season}.csv

scripts/nfl_fantasy_input_checklist.py --write        (GATE, exits non-zero)
       writes nfl_source/fantasy/nfl_fantasy_input_report_{season}.json

blueprints/nfl.py:fantasy / api_fantasy_projections   (WEB, request path)
  -> features/nfl/fantasy.build_fantasy_payload       fantasy.py:~130
    -> fantasy_projection.project_season              fantasy_projection.py:~1840
      -> league_rates(history_seasons)                  population means + role curves
      -> role_priors(season)                            depth-rank + rookie priors
      -> player_history(season)                         multi-season shares/efficiency
      -> project_team(season, team, ...)                per team:
           team_volume()                                  pool size, from market lines
           _apply_role_curve()  [strength 0.0 by default — measured, see below]
           _expected_games()                              games from ROLE, not position
           _normalise_games_weighted()                    close the pool
    -> fantasy_draft_board.build_draft_board            VOR + tiers
```

## Substrate rules

`tracking/` is **gitignored**, so on Render the pbp/roster/depth-chart files live
only on the mounted disk. Every read resolves through
`sources._resolve_nfl_tracking_path`, which searches candidate roots **per file**
— the `#441` fix. A zero row count from a local checkout is **UNMEASURED**, not a
production fact; the checklist prints that in those words rather than `0%`.

All engine inputs are allowlisted in `artifact_publisher.HOT_ARTIFACT_PATTERNS`,
so they can be audited through `/api/ops/artifacts/*`:

```
nfl_source/fantasy/nfl_fantasy_usage_*.json
nfl_source/fantasy/nfl_fantasy_news_*.json
nfl_source/fantasy/nfl_fantasy_input_report_*.json
nfl_source/tracking/nflverse/roster/roster_*.csv
nfl_source/tracking/nflverse/depth_charts/depth_charts_*.csv
```

## Reuse flags — the rebuild procedure

`SYNDICATE_NFL_FANTASY_USAGE_STRICT=1` disables the pbp fallback in
`load_season_usage`, so a web service that would otherwise silently parse
100 MB of play-by-play inside a request handler fails loudly instead. **Set it
on the web service.**

**A new usage field requires a REBUILD, not just a deploy.** `load_season_usage`
reads the published artifact whenever it exists; a field added to
`PlayerSeasonUsage` will read as its default forever until
`build_nfl_fantasy_usage.py --force` regenerates the JSON. This is the local
equivalent of MLB's `--use-roster-artifacts` trap (`model_engine_standard.md` §3).

## Why not smartsim2

Syndicate has an NFL game simulator and this engine deliberately does not use it
for scoring environment. `state.md [football-smartsim2]`, over 751 clean
out-of-sample games:

```
actual = a + b*market + w*(model - market)
b = +0.990  CI [0.909, 1.076]    the closing line is unbiased
w = -0.028  CI [-0.130, +0.069]  the model's deviation carries NO information
```

Team scoring comes from posted spreads and totals instead — free and local in
the nflverse schedule. Coverage measured 2026-08-21: **112 of 272** 2026 games
carry a line, all 32 teams appear in 6–9 of them, and the remaining 160 games are
projected from a market-fitted team rating. Every row says which fed it.

## What is measured

`reports/nfl_fantasy_backtest.json` — projects 2025 from 2022-2024 only, grades
against real 2025 ESPN PPR, on **one common 258-player set for every method**
(grading each method over its own set was a real defect in the first version and
made the MAEs incomparable).

| | baseline "last year" | engine | |
|---|---|---|---|
| season MAE | 49.62 | **47.95** | better |
| season Spearman | 0.6983 | **0.7349** | better |
| per-game MAE | 3.69 | **3.58** | better |
| per-game Spearman | 0.6072 | **0.6244** | better |

The engine wins **rank correlation at every position**. TE is the standout
(MAE 39.9 → 32.1, ρ 0.65 → 0.79). It is **worse on RB and WR season MAE**
(53.2 vs 49.9, 53.6 vs 49.9) with a **+8.2 point over-projection bias** — a real
cost, stated rather than hidden. For drafting, rank is the operative metric; for
"how many points will he score", the baseline is competitive at RB/WR.

**Bounds on that result.** One season, n=258. The market-environment path cannot
be honestly graded on a completed season (its lines are in-season closing lines,
i.e. hindsight), so the headline run has it OFF and the market-on run is
reported as a contaminated upper reference, never as a result.

`reports/nfl_fantasy_calibration.json` — constants selected on **2024 only**.
3 of 9 are FITTED; 6 moved the objective by less than noise and are labelled
UNFITTED at their defaults rather than shipped as tuned, following the precedent
where three of seven prop-model constants were left at safe values.

**`role_curve_strength` fitted to ZERO.** Pulling each team's opportunity split
toward the league-average shape was the single largest accuracy loss in the
engine (fit MAE 51.11 → 49.34 when switched off). Real teams are not the average
team. The *other* half of the same curve — `role_games_curve`, which sets
expected games from role — is load-bearing and stays on. The two were built
together and are easy to confuse.

## Five defects found during the build

Every one was silent, produced plausible numbers, and would have passed a test
suite. Each is recorded in the docstring of the function that carries it.

1. **Role prior fitted only over players who PLAYED.** Skipping zero-usage
   rostered players priced a rank-2 QB at a 0.466 pass share; because shares
   normalise within a team, that crushed the *starter* — Josh Allen at 12.09 PPR
   points per game against a real figure near 24.
2. **Rookie prior fitted against a reference cell that cannot exist.** It
   expressed rookie share as a ratio to a position/rank cell, but nflverse
   publishes depth charts for the current season only, so past-season players all
   fall into the catch-all bucket. Produced a 3.24× round-one multiplier and put
   four rookies atop the overall board.
3. **Expected games taken from the POSITION mean.** A backup QB drew 14.3 games
   at a backup's (correctly high) while-active share, and the normalisation took
   those attempts from the starter.
4. **Role curve measured in season-total share while player history used
   while-active share** — two different quantities, silently blended, and it
   double-counted availability.
5. **Depth-chart snapshot taken as `max(dt)`.** For 2025 that is 2026-03-14,
   *after* the season the backtest was grading. The leak ran in the flattering
   direction. Now cut at `PRESEASON_CUTOFF`.

## Known-unused inputs

The gating checklist reports these as **populated but not consumed** — dead
weight, not defects, and it will keep reporting them every run:
`rec_air_yards`, `rz_carries`, `gl_targets`. They are collected because they are
cheap and are the obvious next modelling inputs (aDOT, and the symmetric
red-zone/goal-line pair).

## News / injury layer — OFF by design

`fantasy_news.py` reads the nflverse injury report (structured, scales
*availability*) and ESPN's public news feed (unstructured keywords, scales
*opportunity share*). It ships **off** and its weights are **reasoned, not
fitted**:

- it is a **mechanism** added to an engine whose shares were fitted without it
  (`model_engine_standard.md` §4.4 — two mechanisms added to a calibrated engine
  produced a negative interaction in 4 of 4 markets), and
- no archived historical news exists locally, so nothing in this repo can
  currently grade the keyword weights.

Enable per request with `?news=1`. A reachability test asserts `off != on` so it
cannot become quietly inert either.

**Note the interaction that is easy to mis-test:** a share promotion and an
availability cut of reciprocal size leave the season total *exactly* unchanged,
because the pool is normalised on `share × games`. That is correct — 25% more
usage across 20% fewer games is the same accumulation — but it reads as "the
feature is inert". The tests exercise the two mechanisms separately for this
reason.

## Commands

```powershell
python scripts/build_nfl_fantasy_usage.py --seasons 2022,2023,2024,2025
python scripts/fetch_nfl_rosters_depth_charts.py --seasons 2022,2023,2024,2025
python scripts/nfl_fantasy_input_checklist.py --season 2026 --write
python scripts/backtest_nfl_fantasy_projections.py --season 2025
python scripts/calibrate_nfl_fantasy_projections.py --fit-season 2024
python -m pytest tests/test_nfl_fantasy.py
```
