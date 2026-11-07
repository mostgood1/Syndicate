# Basketball interval-projection replay backtest — the bar Phase 2 must beat

`[2026-11-07, lane basketball-interval-backtest, session c2fd17f8, todo #765]`

**What this is.** Phase 2 step 1 of the interval-projection plan (user 2026-11-07): before any game-shape input
(observed pace, shooting %, shot mix, end-game scenarios) goes into the native engine, a READ-ONLY replay harness
that scores every interval projector on the same games. Measurement only: no engine, re-sim or served-code edit, no
deploy, college segment pricing stays off (`SYNDICATE_COLLEGE_LIVE_SEGMENT_PRICING`, #763).

**Code.** `syndicate/features/shared/basketball_interval_backtest.py` (state rebuild, projectors, scoring, the paired
ship gate), `scripts/backtest_basketball_intervals.py` (read-only loaders, coverage, walk-forward NCAAB priors,
resumable worker pool, report), `tests/test_basketball_interval_backtest.py` (22 tests, an off != on test per
variant). On main as `4264deceb`..`c7ba7a01c`. Outputs in WSL `~/bball_iv/runs/<run>/` (`results.jsonl`,
`report.json`, `report.md`), all at `nice -n 19`.

## Headline

1. **The bar for every Phase 2 change is `pregame_rate`, not the engine.** It means the pregame line spread over the
   regulation time left. On 132 NBA 2026-27 regular-season games, today's live re-sim does not beat it in ANY
   segment at ANY checkpoint, for total or margin. Every cell is n.s. or worse: worse on the full-game total at
   the tip (+0.88 ± 0.78) and at 12m (+0.93 ± 0.67), and on h1 and q3 at the tip. The NBA tick is worse than the
   line in 9 of 23 total cells and better in none. This confirms, on a new population, the ledger's NBA live
   gate "regular-season NOT PASSED" (`state_basketball.md [nba-live-native-p3]`).
2. **Observed game pace HURTS on NCAAB, replicating #535 at 18x the sample** (5,032-5,278 regular-season games
   against the WNBA study's 282). On the full-game total at minute 10 / 20 / 30 / 38, these all lose to the line
   beyond 1.96 SE at every point:
   - the scoring rate pooled with the line (`pooled_rate_k1200`): +1.63 / +1.11 / +0.46 / +0.08;
   - pace pooled toward the prior (`pooled_pace_k60`): +0.72 / +0.59 / +0.46 / +0.12;
   - efficiency pooled toward the line (`pooled_efficiency_k60`): +1.50 / +0.93 / +0.18 at 10 / 20 / 30, and
     barely better at 38 (-0.03 ± 0.02).

   Pace pooled toward the prior wins only on the first-half total at 10m (-0.06 ± 0.04). A Phase 2 pace input has
   to pool much harder than these defaults, or not enter at all.
3. **The arithmetic's real error is SHAPE, and that is the Phase 2 lever.** In NCAAB regular season, the line split
   evenly over time misallocates the halves:
   - at the tip, first-half total bias +4.35 and second-half -5.01 (5,278 games);
   - every projector's full-game total runs about 4 points LOW at minute 38 (pregame_rate -4.30). That is end-game
     fouling plus overtime, and the arithmetic projects neither.

   NBA shows the same in Q4: the line share projects Q4 +2.82 HIGH at the tip, and the full-game total is -2.26 at
   45.6m. The men's half split (`H1_SHARE` 47.43%, `SYNDICATE_NCAAB_HALF_SPLIT`) and the default-off end-game
   mechanisms are exactly these shapes. They are what Phase 2 should test first, against this table.
4. **The old bars are already beaten by trivial baselines.** The old NCAAB app's quoted full-game total MAE was
   25.97 / 16.75 / 10.64 / 4.67 at minute 10 / 20 / 30 / 38. Its own definition (`proj_pace`, reproduced here as
   `naive_pace`) scores 21.02 / 13.60 / 9.20 / 5.21 on its window (2026-02-01..02-12, 522 games, 41,238 snapshots
   against its 33,932, so not the identical population). The line scores 12.17 / 10.37 / 8.39 / 5.12 on the same
   bins. The old NBA pregame quarter MAE was 8.53 (n=464). On the 2026-27 regular season, at the tip:

   | projector | Q1 | Q2 | Q3 | Q4 | games |
   |---|---|---|---|---|---|
   | line share | 6.71 | 7.01 | 7.16 | 7.42 | 132 |
   | the re-sim's pregame number | 6.73 | 7.16 | 7.40 | 7.27 | 132 |
   | the tick ladder | 6.79 | 7.36 | 7.46 | 7.47 | 132 |
   | walk-forward league rate, no game information (2025-26) | 6.73 | 6.83 | 7.10 | 7.67 | 1,230 |
5. **The replay IS today's live re-sim.** Production's own recorded NBA live re-sim (`live_resim_history/<date>.jsonl`,
   the tick nearest each checkpoint within +-60 s) and the replay re-sim have near-identical full-game errors on the
   same games:

   | checkpoint | games | total MAE, production | total MAE, replay | margin MAE, production | margin MAE, replay |
   |---|---|---|---|---|---|
   | 12m | 122 | 14.71 | 14.61 | 11.60 | 11.42 |
   | 24m | 131 | 12.14 | 11.92 | 9.37 | 9.30 |
   | 36m | 130 | 7.93 | 8.02 | 6.96 | 6.86 |
   | 45.6m | 128 | 5.12 | 5.18 | 3.06 | 3.16 |

   Mean |production - replay| on the total is 2.50 / 2.11 / 1.68 / 1.54 points, about what 100-sim noise plus a
   +-60 s state offset gives.
6. **The shipped naive module is `naive_pace`.** `basketball_interval_projection.project_interval` projects pace x
   points per possession, which is points per minute: the possession estimate cancels. Its projections equal
   `naive_pace` to rounding on every league, so it is not an independent baseline. The pace / efficiency split only
   matters once one side is pooled (`pooled_pace`, `pooled_efficiency`).

## The college re-sim — NCAAB 2025-26 regular season, 282 paired games (`ncaab2026_resim`)

A seeded sample of 400 games from all phases. Refused before the re-sim, by name:
- 43 with no team prior (season start);
- 48 where a team had < 5 prior games;
- 1 `pbp_final_mismatch`.

Re-simmed: 285 regular-season games, 282 of them with a close and therefore paired against the line. Tournaments:
16 conference and 7 NCAA tournament games, reported apart in `report.rescored.md` and too thin to read.

**Paired gate vs `pregame_rate`** (mean |error| difference, negative = the re-sim is better, ± 1.96
game-clustered SE, 282 games):

| segment | 0m | 10m | 20m | 30m | 38m |
|---|---|---|---|---|---|
| full total | +0.77 ± 0.80 n.s. | -0.57 ± 0.63 n.s. | **-0.78 ± 0.45 better** | **-0.88 ± 0.26 better** | **-0.38 ± 0.15 better** |
| h1 total | **+1.62 ± 0.36 worse** | **+0.56 ± 0.21 worse** | -- | -- | -- |
| h2 total | **-0.83 ± 0.42 better** | **-0.74 ± 0.43 better** | **-0.78 ± 0.45 better** | **-0.88 ± 0.26 better** | **-0.38 ± 0.15 better** |
| full margin, raw | **+0.49 ± 0.40 worse** | +0.31 ± 0.32 n.s. | **+0.27 ± 0.22 worse** | +0.04 ± 0.14 n.s. | +0.02 ± 0.09 n.s. |
| full margin, anchored (production) | +0.00 (= the close) | +0.06 ± 0.20 n.s. | +0.13 ± 0.14 n.s. | +0.00 ± 0.12 n.s. | +0.02 ± 0.09 n.s. |

MAE (bias) of the re-sim:

| segment | 0m | 10m | 20m | 30m | 38m |
|---|---|---|---|---|---|
| full total | 13.92 (+5.14) | 11.86 (-0.09) | 10.92 (-3.19) | 8.80 (-4.80) | 6.43 (-4.29) |
| h1 total | 10.94 (+8.44) | 6.25 (+3.15) | -- | -- | -- |
| h2 total | 10.86 (-3.30) | 10.95 (-3.23) | 10.92 (-3.19) | 8.80 (-4.80) | 6.43 (-4.29) |

The line on the same population, full-game total: 12.95 (-1.21) / 12.09 (-5.23) / 11.29 (-6.32) / 9.31 (-6.56) /
6.51 (-5.02), over 348 games. This sample's games score higher than the season's (-5 to -6.6 bias against
-4.2 to -5.3 on all 5,278).

**What it says.**
- The college engine already carries part of the SHAPE that the line's even split misses. Its second half is
  heavier, so it beats the line on h2 and on the in-game full total from minute 20.
- Its FIRST half is mis-shaped: +8.4 high at the tip against the line's +5.1. That is the half split
  (`H1_SHARE` 47.43%, `SYNDICATE_NCAAB_HALF_SPLIT`, default off and absent on the fleet). It is Phase 2's first
  candidate, with a pre-registered gate of "h1 total improves; h2 / full do not regress".
- Its end-game deficit remains: -4.3 at minute 38, the default-off end-game fouling mechanisms
  (`SYNDICATE_NCAAB_LIVE_MECHANISMS`).
- The anchored margin (what production serves) ties the line everywhere. The raw margin loses at the tip.

**Today's fleet config IS what was replayed** (`/home/amyn/syndicate-prod/local_production.env`, read 2026-11-07,
allowlisted flags only):
- ABSENT, so the code defaults apply: `SYNDICATE_NCAAB_HALF_SPLIT` (off), `SYNDICATE_NCAAB_LIVE_MECHANISMS` (off),
  `SYNDICATE_NCAAB_EXACT_TARGET` (off), `SYNDICATE_COLLEGE_PRIOR_CALIBRATION` (on), `SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR`
  (on), `SYNDICATE_NBA_LIVE_MECHANISMS` (off), `SYNDICATE_NBA_TEAM_INPUTS` (on), `SYNDICATE_COLLEGE_LIVE_SEGMENT_PRICING` (off).
- `SYNDICATE_NBA_LIVE_RESIM_SIMS=100`, the same as here.
- NCAAB production runs the default 200 sims; this replay ran 100, so its re-sim errors carry a little more Monte
  Carlo noise than production's.

## For Phase 2: how to use this

- Run a candidate as one more projector on the SAME runs. Re-sim variants: `--projectors resim,resim_mech
  --mechanisms '<json>'`, or a new `Projector` in `basketball_interval_backtest.py`.
- Read `paired_delta` against `pregame_rate` AND against `resim`. A change ships only where it is "better" beyond
  1.96 game-clustered SE and regresses no other segment.
- Give each run its own `--out`. Results resume by game id, so a new projector added to an existing run's
  `--out` would skip every finished game. The same `--sample` / `--seed` picks the same games. A re-sim costs
  ~14 s/game at 100 sims and nice 19.

## Runs and coverage

Every run prints per-family coverage first; the numbers rest on the intersection.

| run | league / season | families -> intersection | games scored | projectors |
|---|---|---|---|---|
| `nba2027_resim` | NBA 2026-27 regular | games 17 dates, pbp 17, engine inputs 24, smart sim 32 -> **17 dates (10-20..11-06)** | **132** of 132 with persisted pregame inputs | all + `resim` + `nba_tick` |
| `ncaab2026_all` | NCAAB 2025-26, all phases | corpus 147, games 147, pbp 147, player box 166 -> **147 dates (2025-11-03..2026-04-06)** | **6,257** (12 `pbp_final_mismatch`); line on 5,278 regular | arithmetic, every 30 s |
| `ncaab2026_resim` | NCAAB 2025-26, seeded sample 400 (all phases interleaved) | as above | see the college table | all + `resim` / `resim_anchored` |
| `nba2026_all` | NBA 2025-26, all phases | games 229, pbp 229 -> **229 dates** | **1,391** (1,230 regular) | arithmetic; no line or pregame inputs that season |
| `wnba2026_all` | WNBA 2026, all phases | games 136, pbp 136 -> **136 dates** | **373** (318 regular for `league_rate`) | arithmetic; a line on 15 games, pregame inputs on 6 (so the WNBA re-sim is not read) |

Code per run (each run copied the code to WSL before it started, with the commit stamped in its report):
- The three arithmetic runs are at main's `c7ba7a01c` (`31abe81f6` before the rebase onto main).
- The two re-sim runs are at main's `acdff2fee` (`30418d0d0` before the rebase). That predates
  `interval_projection`'s tip refusal (`c7ba7a01c`), so they were re-scored without that projector's tip rows
  (`report.rescored.*`); NBA 2026-27 had 0 such rows.

The rebase changed only the SHAs: the content is identical.

## Tables: NBA 2026-27 regular season, 132 games — MAE (bias), [132] in every cell

Error is projection minus actual; positive bias = projects HIGH.

| projector | segment | 0m | 12m | 24m | 36m | 45.6m |
|---|---|---|---|---|---|---|
| pregame_rate | full total | 14.22 (+2.87) | 13.48 (+1.98) | 11.99 (+2.07) | 7.90 (+1.70) | 5.19 (-2.26) |
| resim | full total | 15.10 (+2.52) | 14.41 (+1.77) | 12.01 (+1.96) | 8.03 (+1.77) | 5.10 (-1.74) |
| nba_tick | full total | 15.55 (+1.86) | 14.50 (+1.16) | 12.46 (+1.33) | 7.97 (+1.23) | 5.81 (+1.20) |
| pooled_pace_k60 | full total | 14.22 (+2.87) | 13.62 (+0.87) | 11.70 (+0.31) | 7.78 (+0.56) | 5.25 (-2.64) |
| naive_pace | full total | -- | 24.45 (-0.67) | 14.91 (+1.27) | 8.31 (+1.31) | 5.26 (-2.53) |
| pregame_rate | h1 total | 9.48 (+0.80) | 7.01 (-0.09) | -- | -- | -- |
| resim | h1 total | 9.96 (+0.76) | 7.25 (-0.06) | -- | -- | -- |
| pregame_rate | h2 total | 11.99 (+2.07) | 11.99 (+2.07) | 11.99 (+2.07) | 7.90 (+1.70) | 5.19 (-2.26) |
| resim | h2 total | 12.25 (+1.76) | 12.19 (+1.83) | 12.01 (+1.96) | 8.03 (+1.77) | 5.10 (-1.74) |
| pregame_rate | q4 total | 7.42 (+2.82) | 7.42 (+2.82) | 7.42 (+2.82) | 7.42 (+2.82) | 4.28 (-1.14) |
| resim | q4 total | 7.27 (+2.37) | 7.29 (+2.38) | 7.27 (+2.33) | 7.33 (+2.38) | 4.29 (-1.15) |
| pregame_rate | full margin | 10.94 (+0.86) | 11.15 (+0.89) | 9.13 (-0.57) | 6.85 (+1.20) | 3.16 (+0.47) |
| resim | full margin | 11.40 (+0.10) | 11.27 (+0.75) | 9.30 (-0.54) | 6.87 (+1.19) | 3.17 (+0.54) |
| pregame_rate | q4 margin | 6.76 (+1.26) | 6.76 (+1.26) | 6.76 (+1.26) | 6.76 (+1.26) | 3.12 (+0.53) |
| resim | q4 margin | 6.70 (+1.06) | 6.79 (+1.19) | 6.77 (+1.27) | 6.77 (+1.23) | 3.12 (+0.59) |

The NBA line here is the smart sim's `market` at sim time, not the close; its +2.87 tip bias is an early-season
NBA line running over the finals.

## Tables: NCAAB 2025-26 regular season — MAE (bias) [games]

| projector | segment | 0m | 10m | 20m | 30m | 38m |
|---|---|---|---|---|---|---|
| pregame_rate (ESPN BET close) | full total | 13.41 (-0.66) [5278] | 12.05 (-4.16) | 10.36 (-5.01) | 8.32 (-5.27) | 5.61 (-4.30) |
| league_rate | full total | 15.59 (+0.65) [5694] | 13.23 (-3.07) | 10.79 (-4.14) | 8.24 (-4.62) | 5.36 (-3.92) |
| pooled_rate_k1200 | full total | 13.41 (-0.65) [5278] | 13.68 (-7.66) | 11.46 (-7.18) | 8.78 (-6.20) | 5.69 (-4.43) |
| pooled_pace_k60 | full total | 13.37 (-0.55) [5032] | 12.75 (-6.31) | 10.93 (-6.39) | 8.79 (-6.20) | 5.78 (-4.57) |
| pooled_efficiency_k60 | full total | 13.37 (-0.55) [5032] | 13.53 (-5.62) | 11.28 (-5.85) | 8.51 (-5.27) | 5.63 (-4.28) |
| naive_pace = interval_projection | full total | -- | 22.25 (-14.26) [5855] | 13.82 (-8.92) | 9.15 (-6.35) | 5.46 (-4.10) |
| pregame_rate | h1 total | 8.85 (+4.35) | 5.66 (+0.85) | -- | -- | -- |
| pregame_rate | h2 total | 10.36 (-5.01) | 10.36 (-5.01) | 10.36 (-5.01) | 8.32 (-5.27) | 5.61 (-4.30) |
| pregame_rate | full margin | 8.98 (+0.13) | 8.14 (+0.35) | 7.02 (+0.31) | 5.44 (+0.26) | 2.85 (+0.10) |
| naive_pace | full margin | -- | 19.22 (+1.19) | 11.30 (+0.65) | 6.72 (+0.44) | 2.95 (+0.17) |

Same population, the old app's 2-minute bins over every 30 s snapshot (`report.md` holds the full curve):
pregame_rate 11.95 / 10.38 / 8.09 / 4.90, league_rate 13.05 / 10.76 / 8.00 / 4.66, naive_pace
21.40 / 13.80 / 8.81 / 4.72 at minute 10-12 / 20-22 / 30-32 / 38-40. Conference, NCAA and other postseason are
reported apart in each run's `report.md` (298 / 66 / 38 games) and are never pooled with the regular season.

## Method

**Substrate: the fleet's production data root, `/home/amyn/syndicate-prod/data`, read-only** (`CLAUDE.md`: the
repo's `data/` is a lossy mirror). Families, per league:

| family | path under `<league>_source/data/` | used for |
|---|---|---|
| finals + phase | `processed/rotation_stints/games_<date>.csv` | official finals, season type, `score_match` |
| box | `processed/rotation_stints/player_checks_<date>.csv` | names, starters (period-1 five), box PF |
| event log | `processed/pbp_events/<season>/<event_id>.jsonl.gz` | the typed ESPN log P2 writes (`basketball_pbp.PbpEvent`) |
| NCAAB corpus | `pbp_corpus/pbp_corpus_2026.jsonl.gz` + `processed/player_game_box_2026.csv` | team ids, neutral site, ESPN BET close, walk-forward ratings and player priors (the P4 backtest's inputs) |
| NBA/WNBA pregame | `processed/engine_inputs/<date>/<H>_<A>.pkl`, `processed/smart_sim_<date>_<H>_<A>.json` | the inputs production persisted for the live re-sim; the line at sim time and the tick's 3-minute ladder |

Each run prints per-family date coverage and the intersection before any number (tables above).

**State.** Every 30 s of regulation clock, the state is rebuilt from the log PREFIX with the production builders:
score per period, period, clock (a period boundary is the next period's tip, the live path's rule), team fouls in
the current foul bucket (`basketball_live_state._team_fouls`), possession after the last informative play
(`_possession_after`), box counts (FGA / 3PA / FTA / TOV / OREB, makes), and for the re-sims the on-floor fives from
`basketball_pbp.reconstruct_from_events` ON THE PREFIX (so a period-start five is inferred only from plays already
logged, as live) and player fouls (`personal_fouls`).

**Actuals** follow the book convention both live re-sims use: the full game and the second half include overtime;
a quarter and the first half do not. A game whose log does not sum to the official final is refused
(`pbp_final_mismatch`), never scored.

**Checkpoints.** `0m` (the tip: the pregame number) and the bar's four points, minute 10 / 20 / 30 / 38 of a 40-minute
game; NBA uses the same fractions of 48 minutes (12 / 24 / 36 / 45.6). The error CURVE is also kept per 5% of
regulation over every 30 s snapshot (the old NCAAB app's 2-minute bins). A segment already settled at a snapshot is
never asked for.

**The ship gate** (`paired_delta`): candidate vs baseline on the same games and cells only, mean |error| difference
(negative = candidate better) with a GAME-CLUSTERED standard error; "better" / "worse" only beyond 1.96 SE.

## Projectors

| name | what | fidelity |
|---|---|---|
| `naive_pace` | points so far / elapsed x time left (segment: segment so far + the game's rate x its time left) | exactly the old NCAAB app's `proj_pace` on the full game |
| `interval_projection` | `basketball_interval_projection.project_interval` for the current period, its pace x ppp after; margin carried | the shipped module, called. It is algebraically `naive_pace`: pace x ppp = points per minute, the possession estimate cancels |
| `league_rate` | walk-forward league regulation scoring rate (games dated before, >= 30) x time left; margin carried | #535's league-constant finding |
| `pregame_rate` | segment so far + the pregame line x the share of regulation left | NCAAB: ESPN BET close (corpus). NBA: the smart sim's `market` at sim time, NOT the close |
| `pooled_rate_k1200` | PHASE 2 HOOK: scoring rate pooled between the line and the game, 1,200 prior-seconds of weight | k=0 is `naive_pace`, k->inf is `pregame_rate` (tested) |
| `pooled_pace_k60` | PHASE 2 HOOK: possessions pooled toward the prior pace (60 prior possessions); ppp from the line | prior pace: NCAAB walk-forward team prior, NBA the persisted cfg `possessions_per_game` |
| `pooled_efficiency_k60` | PHASE 2 HOOK: points per possession pooled toward the line's; pace from the prior | as above |
| `resim` | today's live re-sim resumed from the replay state, 100 sims | see below |
| `resim_anchored` | college only: `resim` with production's market anchor (`anchor_result`, offset = close - this game's tip sim, scaled by regulation left) | anchors to the ESPN BET close; production anchors to the book_quotes consensus close |
| `nba_tick` | NBA only: the ported tick's `_scope_projection` arithmetic through its own `_live_interp_cum_p50` on the smart sim's 3-minute ladder | totals only; the tick's recent-window pace/efficiency adjustments are NOT replayed (they need its live tuning file) |

**The re-sim, college.** `ncaab/live_resim.build_engine_inputs` + `resim_live_game` with `league="ncaab"`,
WALK-FORWARD: team ratings from corpus box rows dated < D (`ncaab_corpus_baseline.walk_forward_priors`), player
priors from player box rows < D (`compute_priors`, the producer's function), and production's daily prior
calibration REFIT for each date (`prior_calibration.fit` over D-21..D-1 against the close, >= 60 closes, else finals
>= 80), applied exactly as `live_team_model._calibrated` (pinned by a test). Games where either team has < 5 prior
games are not re-simmed (the P4 backtest's rule). Run at the tip + the four checkpoints; the t=0 projection reuses
the anchor's tip sim (same seed).

**The re-sim, NBA.** `nba/live_resim.load_engine_inputs` (production's persisted pregame kwargs) + `resim_live_game`
through `_engine_for_league_local` with the pregame's league-params overrides — the same engine object production
resumes. `SYNDICATE_NBA_TEAM_INPUTS` absent (= on, production's default), live mechanisms off (production). Names
mapped with `map_state_names`. One difference from live: an incomplete five is resumed with a sampled lineup here,
where production refuses that tick (`on_floor_incomplete`).

**Sim count: 100** — production NBA's count (`SYNDICATE_NBA_LIVE_RESIM_SIMS=100` on the fleet) and both re-sims'
floor (`MIN_SIMS`). Measured cost at nice 19 on the shared host: an NCAAB 100-sim resume ~9.6 s at the tip, 7.3 s at
the half, 2.5 s at H2 10:00 (~14 s per game over tip + 4 checkpoints); every-30 s re-sims would be ~400 s per game.

**Not done here (named, not hidden).** Shot mix is an extension point (`ReplayState.counts` carries 3PA/FGA and
makes per side), not a registered variant. `resim_mech` (the default-off end-game mechanisms) is wired and tested
(`--projectors resim_mech --mechanisms '<json>'`) but not run: which mechanism values to test is Phase 2's
pre-registration, not this harness's. WNCAAB has no play-by-play store on the fleet (`build_basketball_rotation_stints.py`
does not run for it), so it is not replayed.

## CORRECTION 23:50Z 11-07 (5:50 PM CST) -- the NCAAB re-sim scored here ran with production's switches OFF

- **What the findings got wrong:** they state `SYNDICATE_NCAAB_HALF_SPLIT` (and the mechanisms) are ABSENT on the fleet. That holds for refresh-worker only. live-odds-worker, the process that launches the college pregame sims and runs the NCAAB live re-sim, has `SYNDICATE_NCAAB_HALF_SPLIT` and `SYNDICATE_NCAAB_EXACT_TARGET` truthy and `SYNDICATE_NCAAB_LIVE_MECHANISMS` non-empty (read from /proc environ as booleans only, 22:5xZ).
- **Production's pregame sims:** all 177 with a dist 11-03..11-07 carry `provenance.halfSplit: True`.
- **Production h1 against 147 real finals:** +1.27 projected minus actual (sd 10.29, n.s.), h2 -0.78, full +0.50. Projected h1 share 0.4761 vs actual 0.4695.
- **Which statements stand:**
  - The re-sim h1 / h2 / end-game statements above describe the engine with the switches off. They need a re-run with live-odds-worker's switches before they decide anything.
  - The `pregame_rate` bar, the NBA rows and the pace / efficiency results do not depend on these switches.
