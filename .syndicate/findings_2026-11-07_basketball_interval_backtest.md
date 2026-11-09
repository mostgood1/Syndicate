# Basketball interval-projection replay backtest — the bar Phase 2 must beat

`[2026-11-07, lane basketball-interval-backtest, session c2fd17f8, todo #765]`

**What this is.** Phase 2 step 1 of the interval-projection plan (user 2026-11-07): before any game-shape input
(observed pace, shooting %, shot mix, end-game scenarios) goes into the native engine, a READ-ONLY replay harness
that scores every interval projector on the same games. Measurement only: no engine, re-sim or served-code edit, no
deploy, college segment pricing stays off (`SYNDICATE_COLLEGE_LIVE_SEGMENT_PRICING`, #763).

**Code.** `syndicate/features/shared/basketball_interval_backtest.py` (state rebuild, projectors, scoring, the paired
ship gate), `scripts/backtest_basketball_intervals.py` (read-only loaders, coverage, walk-forward NCAAB priors,
resumable worker pool, report), `tests/test_basketball_interval_backtest.py` (24 tests, an off != on test per
variant). On main as `4264deceb`..`c7ba7a01c`, plus `8c1378e9a`, which records the college engine switches per game. Outputs in WSL `~/bball_iv/runs/<run>/` (`results.jsonl`,
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
   45.6m. The men's half split (`H1_SHARE` 47.43%, `SYNDICATE_NCAAB_HALF_SPLIT`) and the end-game mechanisms
   (`SYNDICATE_NCAAB_LIVE_MECHANISMS`) are exactly these shapes, and **production already runs both** on
   live-odds-worker (re-measured 2026-11-08, below). With them on, the college re-sim's h1 is +2.15 at the tip
   (the line +5.11), and its full total is -2.67 at minute 38 (the line -5.02). What is left is the second half:
   h2 -2.02 at the tip and -3.46 at minute 30.
   That late remainder is mostly OVERTIME: in games that end in regulation the re-sim is unbiased at minute
   38 in two samples. The sims under-produce regulation ties (section PHASE 2 STEP 3, 2026-11-08).
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

## The college re-sim — NCAAB 2025-26 regular season, 282 paired games, production's switches ON (`ncaab2026_resim_prod`)

`[re-run 2026-11-08 00:06-00:49Z (6:06-6:49 PM CST 11-07), lane ncaab-interval-resim-prod-switches, code 8c1378e9a]`

**Why this section was re-run.** Its first version (`ncaab2026_resim`, code `acdff2fee`) replayed the college
engine with all three of production's college switches OFF. live-odds-worker launches the college pregame sims
and runs the NCAAB live re-sim, and it runs with all three:
- `SYNDICATE_NCAAB_HALF_SPLIT` on;
- `SYNDICATE_NCAAB_EXACT_TARGET` on;
- `SYNDICATE_NCAAB_LIVE_MECHANISMS` set, with four fields: `endgame_extend_possessions`,
  `endgame_foul_max_deficit`, `endgame_foul_p_by_deficit`, `endgame_foul_window_s`.

They sit in `local_production.env` under a role prefix (`LIVE_ODDS_WORKER__<key>`), and the first reading grepped
the file for the plain names. refresh-worker and web carry none of the three.

The re-run copied the three keys from live-odds-worker's `/proc/<pid>/environ` into the replay env. The values
were never printed. Everything else matches the first run:
- the same 400-game sample and seed, and the same walk-forward priors;
- no sim-path code change between the two runs, or against the fleet's `79c8aac12`;
- the fleet's newer `af4244afd` runs the re-sim draws in 2 worker processes, but it calls the same
  `resim_live_game` with the same seed.

**Proof the switches reached the engine.** The provenance is read off each game's engine inputs, not off the env
(`report.md`, `engine_provenance`). All 308 re-simmed games (285 regular season, 23 tournament) carry:
- `halfSplit`: the `quarters` targets are set;
- `exactTarget`: the bound engine's `exact_target_calibration`;
- three cfg fields off their defaults: `endgame_extend_possessions`, `endgame_foul_p_by_deficit`,
  `endgame_foul_window_s`.

The fourth configured field, `endgame_foul_max_deficit`, carries its default value, so it changes nothing.
Refusals are as in the first run: 91 `no_walk_forward_inputs` (43 games with no team prior, 48 with a team on
fewer than 5 prior games) and 1 `pbp_final_mismatch`.

**Paired gate vs `pregame_rate`, switches ON.** The mean |error| difference; negative means the re-sim is better.
± is 1.96 game-clustered SE, over 282 games.

| segment | 0m | 10m | 20m | 30m | 38m |
|---|---|---|---|---|---|
| full total | +0.23 ± 0.45 n.s. | -0.41 ± 0.48 n.s. | **-0.97 ± 0.57 better** | **-1.22 ± 0.40 better** | **-0.98 ± 0.33 better** |
| h1 total | **-0.93 ± 0.41 better** | -0.01 ± 0.23 n.s. | -- | -- | -- |
| h2 total | **-0.94 ± 0.54 better** | **-0.89 ± 0.56 better** | **-0.97 ± 0.57 better** | **-1.22 ± 0.40 better** | **-0.98 ± 0.33 better** |
| full margin, raw | +0.13 ± 0.34 n.s. | +0.18 ± 0.30 n.s. | +0.06 ± 0.20 n.s. | +0.04 ± 0.14 n.s. | +0.10 ± 0.12 n.s. |
| full margin, anchored (production) | +0.00 (= the close) | **+0.24 ± 0.20 worse** | +0.11 ± 0.15 n.s. | +0.03 ± 0.13 n.s. | +0.10 ± 0.12 n.s. |

The same gate with the switches OFF, as first published:

| segment | 0m | 10m | 20m | 30m | 38m |
|---|---|---|---|---|---|
| full total | +0.77 ± 0.80 n.s. | -0.57 ± 0.63 n.s. | **-0.78 ± 0.45 better** | **-0.88 ± 0.26 better** | **-0.38 ± 0.15 better** |
| h1 total | **+1.62 ± 0.36 worse** | **+0.56 ± 0.21 worse** | -- | -- | -- |
| h2 total | **-0.83 ± 0.42 better** | **-0.74 ± 0.43 better** | **-0.78 ± 0.45 better** | **-0.88 ± 0.26 better** | **-0.38 ± 0.15 better** |
| full margin, raw | **+0.49 ± 0.40 worse** | +0.31 ± 0.32 n.s. | **+0.27 ± 0.22 worse** | +0.04 ± 0.14 n.s. | +0.02 ± 0.09 n.s. |
| full margin, anchored | +0.00 (= the close) | +0.06 ± 0.20 n.s. | +0.13 ± 0.14 n.s. | +0.00 ± 0.12 n.s. | +0.02 ± 0.09 n.s. |

**ON vs OFF, paired by game.** Negative means the switches help. 285 games; the anchored margin is on 282.

| segment | 0m | 10m | 20m | 30m | 38m |
|---|---|---|---|---|---|
| full total | -0.57 ± 0.60 n.s. | +0.16 ± 0.29 n.s. | -0.20 ± 0.22 n.s. | **-0.35 ± 0.20 better** | **-0.61 ± 0.23 better** |
| h1 total | **-2.60 ± 0.63 better** | **-0.60 ± 0.37 better** | -- | -- | -- |
| h2 total | -0.12 ± 0.23 n.s. | -0.17 ± 0.23 n.s. | -0.20 ± 0.22 n.s. | **-0.35 ± 0.20 better** | **-0.61 ± 0.23 better** |
| full margin, raw | **-0.34 ± 0.28 better** | -0.14 ± 0.23 n.s. | **-0.21 ± 0.16 better** | +0.00 ± 0.13 n.s. | +0.10 ± 0.10 n.s. |
| full margin, anchored | +0.00 | +0.18 ± 0.21 n.s. | -0.02 ± 0.15 n.s. | +0.03 ± 0.12 n.s. | +0.07 ± 0.09 n.s. |

**MAE (bias).** Over 285 re-sim games; the line is over 348 games of the same sample.

| segment | 0m | 10m | 20m | 30m | 38m |
|---|---|---|---|---|---|
| full total, switches ON | 13.35 (+0.13) | 12.02 (-1.99) | 10.72 (-1.80) | 8.45 (-3.46) | 5.82 (-2.67) |
| full total, switches OFF | 13.92 (+5.14) | 11.86 (-0.09) | 10.92 (-3.19) | 8.80 (-4.80) | 6.43 (-4.29) |
| full total, the line | 12.95 (-1.21) | 12.09 (-5.23) | 11.29 (-6.32) | 9.31 (-6.56) | 6.51 (-5.02) |
| h1 total, switches ON | 8.34 (+2.15) | 5.65 (-0.15) | -- | -- | -- |
| h1 total, switches OFF | 10.94 (+8.44) | 6.25 (+3.15) | -- | -- | -- |
| h1 total, the line | 9.12 (+5.11) | 5.46 (+1.08) | -- | -- | -- |
| h2 total, switches ON | 10.74 (-2.02) | 10.78 (-1.85) | 10.72 (-1.80) | 8.45 (-3.46) | 5.82 (-2.67) |
| h2 total, switches OFF | 10.86 (-3.30) | 10.95 (-3.23) | 10.92 (-3.19) | 8.80 (-4.80) | 6.43 (-4.29) |
| h2 total, the line | 11.29 (-6.32) | 11.29 (-6.32) | 11.29 (-6.32) | 9.31 (-6.56) | 6.51 (-5.02) |
| full margin raw, switches ON | 9.30 (-0.22) | 8.19 (-0.23) | 7.30 (-0.50) | 5.29 (+0.06) | 2.82 (+0.01) |
| full margin raw, switches OFF | 9.64 (-1.13) | 8.33 (-0.84) | 7.50 (-1.17) | 5.29 (-0.29) | 2.73 (-0.07) |
| full margin, the line | 9.06 (-0.48) | 7.86 (-0.28) | 7.28 (-0.44) | 5.31 (-0.11) | 2.69 (+0.03) |

This sample's games score higher than the season's: the line's bias here is -5 to -6.6, against -4.2 to -5.3 on
all 5,278 games. Read each bias against the line's bias on the same games. Tournaments (16 conference, 7 NCAA) are
reported apart in the run's `report.md` and are too thin to read.

**What it says.** This is production's engine as it runs, so these rows are decision-grade.
- **It beats the line on the totals.** It is better on h2 at every checkpoint, on the full total from minute 20
  (-0.97 / -1.22 / -0.98), and on h1 at the tip (-0.93 ± 0.41). It ties the line on h1 at 10m and on the full
  total at 0m and 10m.
- **Production's first half is not mis-shaped.** The first run's +8.44 at the tip was the half split switched off.
  With it on, the bias is +2.15, against the line's +5.11 on the same games, and the switches cut h1 tip MAE by
  2.60 ± 0.63. That matches production's +1.27 against 147 real 2026-27 finals 11-03..11-07, which is a different
  season and population.
- **The end-game deficit shrinks but is not gone.** At minute 38 the full total runs -2.67 with the mechanisms
  and -4.29 without them (|err| better by 0.61 ± 0.23). The line runs -5.02 on the same games, so about 2.7 points
  of end-game scoring (fouling and overtime) is still not projected.
- **The remaining shape error is the in-game second half:** h2 -2.02 at the tip, -1.80 at 20m and -3.46 at 30m.
  Phase 2's NCAAB candidates should aim there.
- **Margin.** The raw margin now ties the line everywhere; the switches removed its losses at the tip and at 20m.
  The anchored margin, which is what production serves, also ties except at 10m, where it is worse by
  +0.24 ± 0.20. That is one marginal cell among the 22 gated here, so it may be chance until it replicates.
- **Noise.** This replay ran 100 sims against production's default 200, so its re-sim errors carry a little more
  Monte Carlo noise than production's.

**The fleet config that was replayed** (corrected 2026-11-08; read from each process's environ, key names and
booleans only):
- live-odds-worker runs the half split, the exact target and the end-game mechanisms (above).
- Both workers lack these keys, so the code defaults apply: `SYNDICATE_COLLEGE_PRIOR_CALIBRATION` (on),
  `SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR` (on), `SYNDICATE_NBA_LIVE_MECHANISMS` (off), `SYNDICATE_NBA_TEAM_INPUTS`
  (on) and `SYNDICATE_COLLEGE_LIVE_SEGMENT_PRICING` (off).
- `SYNDICATE_NBA_LIVE_RESIM` and `SYNDICATE_NBA_LIVE_RESIM_SIMS` are identical on both workers, and
  `_SIMS=100` is the same as this replay. So the NBA rows stand as first written.

## For Phase 2: how to use this

- Run a candidate as one more projector on the SAME runs. Re-sim variants: `--projectors resim,resim_mech
  --mechanisms '<json>'`, or a new `Projector` in `basketball_interval_backtest.py`.
- Read `paired_delta` against `pregame_rate` AND against `resim`. A change ships only where it is "better" beyond
  1.96 game-clustered SE and regresses no other segment.
- Give each run its own `--out`. Results resume by game id, so a new projector added to an existing run's
  `--out` would skip every finished game. The same `--sample` / `--seed` picks the same games. A re-sim costs
  ~14 s/game at 100 sims and nice 19, or ~17 s/game with production's college switches on.
- **A college re-sim run must carry live-odds-worker's three switches in its env.** Copy
  `SYNDICATE_NCAAB_HALF_SPLIT`, `_EXACT_TARGET` and `_LIVE_MECHANISMS` from that process's `/proc/<pid>/environ`,
  never by printing them. Before reading any college row, check `report.md`: "College engine switches in the
  replay env", and the per-game `engine_provenance` (read off the engine inputs). A run without them replays an
  engine production does not run. The NCAAB baseline for Phase 2 is `ncaab2026_resim_prod`.

## Runs and coverage

Every run prints per-family coverage first; the numbers rest on the intersection.

| run | league / season | families -> intersection | games scored | projectors |
|---|---|---|---|---|
| `nba2027_resim` | NBA 2026-27 regular | games 17 dates, pbp 17, engine inputs 24, smart sim 32 -> **17 dates (10-20..11-06)** | **132** of 132 with persisted pregame inputs | all + `resim` + `nba_tick` |
| `ncaab2026_all` | NCAAB 2025-26, all phases | corpus 147, games 147, pbp 147, player box 166 -> **147 dates (2025-11-03..2026-04-06)** | **6,257** (12 `pbp_final_mismatch`); line on 5,278 regular | arithmetic, every 30 s |
| `ncaab2026_resim` | NCAAB 2025-26, seeded sample 400 (all phases interleaved) | as above | 399; re-sim on 285 regular | all + `resim` / `resim_anchored`, college switches OFF (superseded) |
| `ncaab2026_resim_prod` | the same 400 games and seed | as above | 399; re-sim on 285 regular (282 paired) | all + `resim` / `resim_anchored`, **live-odds-worker's three college switches ON** (the college table) |
| `nba2026_all` | NBA 2025-26, all phases | games 229, pbp 229 -> **229 dates** | **1,391** (1,230 regular) | arithmetic; no line or pregame inputs that season |
| `wnba2026_all` | WNBA 2026, all phases | games 136, pbp 136 -> **136 dates** | **373** (318 regular for `league_rate`) | arithmetic; a line on 15 games, pregame inputs on 6 (so the WNBA re-sim is not read) |

Code per run (each run copied the code to WSL before it started, with the commit stamped in its report):
- The three arithmetic runs are at main's `c7ba7a01c` (`31abe81f6` before the rebase onto main).
- The two re-sim runs are at main's `acdff2fee` (`30418d0d0` before the rebase). That predates
  `interval_projection`'s tip refusal (`c7ba7a01c`), so they were re-scored without that projector's tip rows
  (`report.rescored.*`); NBA 2026-27 had 0 such rows.
- `ncaab2026_resim_prod` is at main's `8c1378e9a` (`f315df356` before the rebase onto main, and the SHA its report
  stamps; the content is identical): `c7ba7a01c` plus the per-game switch provenance. It is not re-scored,
  because that code already refuses the tip.

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
the anchor's tip sim (same seed). Production's college switches are read from the replay process's env by
production's own readers (`build_engine_inputs`, `ncaab_engine`). The decision-grade run (`ncaab2026_resim_prod`)
carried live-odds-worker's three; the first run carried none.

**The re-sim, NBA.** `nba/live_resim.load_engine_inputs` (production's persisted pregame kwargs) + `resim_live_game`
through `_engine_for_league_local` with the pregame's league-params overrides — the same engine object production
resumes. `SYNDICATE_NBA_TEAM_INPUTS` absent (= on, production's default), live mechanisms off (production). Names
mapped with `map_state_names`. One difference from live: an incomplete five is resumed with a sampled lineup here,
where production refuses that tick (`on_floor_incomplete`).

**Sim count: 100** — production NBA's count (`SYNDICATE_NBA_LIVE_RESIM_SIMS=100` on the fleet) and both re-sims'
floor (`MIN_SIMS`). Measured cost at nice 19 on the shared host: an NCAAB 100-sim resume ~9.6 s at the tip, 7.3 s at
the half, 2.5 s at H2 10:00 (~14 s per game over tip + 4 checkpoints); every-30 s re-sims would be ~400 s per game.

**Not done here (named, not hidden).** Shot mix is an extension point (`ReplayState.counts` carries 3PA/FGA and
makes per side), not a registered variant. `resim_mech` (mechanisms set on top of the env's, `--mechanisms '<json>'`)
is wired and tested but not run. Production's own end-game mechanisms are already in `ncaab2026_resim_prod` through
the env, and which further values to test is Phase 2's pre-registration, not this harness's. WNCAAB has no play-by-play store on the fleet (`build_basketball_rotation_stints.py`
does not run for it), so it is not replayed.

## CORRECTION 23:50Z 11-07 (5:50 PM CST) -- the NCAAB re-sim scored here ran with production's switches OFF

- **What the findings got wrong:** they state `SYNDICATE_NCAAB_HALF_SPLIT` (and the mechanisms) are ABSENT on the fleet. That holds for refresh-worker only. live-odds-worker, the process that launches the college pregame sims and runs the NCAAB live re-sim, has `SYNDICATE_NCAAB_HALF_SPLIT` and `SYNDICATE_NCAAB_EXACT_TARGET` truthy and `SYNDICATE_NCAAB_LIVE_MECHANISMS` non-empty (read from /proc environ as booleans only, 22:5xZ).
- **Production's pregame sims:** all 177 with a dist 11-03..11-07 carry `provenance.halfSplit: True`.
- **Production h1 against 147 real finals:** +1.27 projected minus actual (sd 10.29, n.s.), h2 -0.78, full +0.50. Projected h1 share 0.4761 vs actual 0.4695.
- **Which statements stand:**
  - The re-sim h1 / h2 / end-game statements above describe the engine with the switches off. They need a re-run with live-odds-worker's switches before they decide anything.
  - The `pregame_rate` bar, the NBA rows and the pace / efficiency results do not depend on these switches.

## RE-RUN DONE 00:49Z 11-08 (6:49 PM CST 11-07) -- the college rows above now carry production's switches

`[lane ncaab-interval-resim-prod-switches, session c2fd17f8, code 8c1378e9a, run ncaab2026_resim_prod]`

- **The correction checks out.** Read from each process's environ (booleans and field names only):
  - live-odds-worker has the half split and the exact target truthy, and the mechanisms parse (through
    production's `live_mechanisms_from_env`) to 4 fields;
  - refresh-worker and web have none of the three;
  - the keys come from `local_production.env` as `LIVE_ODDS_WORKER__<key>`.
- **The re-run:** the same 400 games and seed, with the three keys copied into the replay env. All 308
  re-simmed games carry `halfSplit`, `exactTarget` and the end-game cfg fields, read off their engine inputs.
- **Corrected rows, 282 paired regular-season games** (the full tables are in the college section above):
  - h1 tip bias +2.15 (was +8.44). Against the line: -0.93 ± 0.41 better (was +1.62 worse).
  - Full total at the tip +0.13 (was +5.14). Against the line: n.s. at 0m / 10m, better from minute 20
    (-0.97 / -1.22 / -0.98).
  - h2: better than the line at every checkpoint (-0.89 to -1.22).
  - Minute 38: -2.67 (was -4.29; the line -5.02). The switches improve it by 0.61 ± 0.23.
  - The anchored margin ties the line except at 10m (+0.24 ± 0.20 worse, one marginal cell of 22).
- **What stands unchanged:** the `pregame_rate` bar, the NBA rows (no NBA switch differs between the workers), and
  the pace / efficiency results.
- **Superseded:** "+8.4 high at the tip" and "the half split is Phase 2's first candidate" (production runs it).
  The "~4 low at minute 38" applies to the arithmetic projectors only; the production re-sim is -2.7 low.

## PHASE 2 STEP 3 (NCAAB): where the production re-sim's late deficit comes from; the first mechanism refit does NOT confirm

`[2026-11-08 16:55-19:35Z (10:55 AM-1:35 PM CST), lane ncaab-late-gap-decomposition, session c2fd17f8, read-only, nice 19]`

**Verdict.**
1. In games that end in regulation, the production NCAAB re-sim is UNBIASED at minute 38, in two independent
   samples: +0.47 ± 0.61 (257 games) and +0.49 ± 0.59 (247).
2. Most of the late deficit is OVERTIME. The sims under-produce regulation ties: in games within 3 at minute 38
   they give 12.8% OT, against the season's 19.1%. Both samples are also OT-rich by chance, which inflates the gap.
3. Raising the end-game foul probability (variant B) looked better in-sample at minute 38. On a fresh sample it
   does not improve any total, and it makes the minute-38 margin worse. **Production's E1 stays.**

**Method.** Residual = actual − projected; POSITIVE means the projection ran LOW. The bucket is |margin| at the
checkpoint.
- A scratch replay (`otsplit`) re-ran the production re-sim at minutes 30 and 38 for sample 1's 285 regular-season
  games, with the same seeds and live-odds-worker's three switches.
- It wraps the engine call to record each sim's regulation points and overtime points separately.
- **Fidelity:** it reproduces the harness's stored re-sim total on 285 of 285 games at both checkpoints
  (max |diff| 0.0000).

**Sample 1, minute 38** (285 games):

| | 0-3 | 4-6 | 7-10 | 11-19 | 20+ | all |
|---|---|---|---|---|---|---|
| games | 61 | 54 | 54 | 62 | 54 | 285 |
| total residual | +5.06 ± 3.34 | +2.10 ± 1.57 | +5.38 ± 2.95 | +0.79 ± 1.31 | +0.02 ± 0.95 | +2.67 ± 1.04 |
| regulation residual | -0.16 ± 1.18 | +1.37 ± 1.12 | **+3.22 ± 1.54** | +0.79 ± 1.31 | +0.02 ± 0.95 | **+1.01 ± 0.57** |
| overtime residual | +5.21 ± 3.26 | +0.73 ± 1.52 | +2.16 ± 2.34 | 0.00 | 0.00 | +1.66 ± 0.90 |
| sims' OT share | 0.128 | 0.055 | 0.010 | 0.000 | 0.000 | 0.040 |
| this sample's OT rate | 0.311 | 0.093 | 0.074 | 0.000 | 0.000 | 0.098 |
| **season OT rate**, games with a close (5,278) | **0.191** | 0.074 | 0.019 | 0.001 | 0.000 | 0.056 |

**Sample 1, minute 30** (285 games):

| | 0-3 | 4-6 | 7-10 | 11-19 | 20+ | all |
|---|---|---|---|---|---|---|
| games | 70 | 45 | 61 | 68 | 41 | 285 |
| total residual | +2.94 ± 2.80 | +2.68 ± 3.26 | +1.62 ± 2.84 | +6.46 ± 2.56 | +2.96 ± 2.11 | +3.46 ± 1.26 |
| regulation residual | -0.09 ± 1.86 | -0.18 ± 2.18 | +0.83 ± 2.46 | **+4.21 ± 2.07** | **+2.96 ± 2.11** | +1.56 ± 0.99 |
| overtime residual | +3.03 ± 2.24 | +2.86 ± 2.95 | +0.78 ± 1.30 | +2.25 ± 2.06 | 0.00 | +1.90 ± 0.92 |
| sims' OT share | 0.053 | 0.040 | 0.028 | 0.009 | 0.000 | 0.027 |
| **season OT rate**, games with a close | **0.115** | 0.087 | 0.052 | 0.025 | 0.001 | 0.056 |

**Sample 2 replicates it** (`ncaab2026_oos_B`, seed 20261108, 272 regular-season re-sim games; total residual
including OT, from the harness rows):
- **Minute 38:**
  - games that end in regulation +0.49 ± 0.59 (247);
  - games that go to OT +20.70 (25);
  - trailing-by-7-10 +4.00 ± 2.11.
- **Minute 30:**
  - games that end in regulation +0.71 ± 1.05;
  - 11-19 +2.90 ± 2.04 and 20+ +1.59 ± 2.67. The blowout direction replicates; its size is uncertain.

**What it says.**
- **Both samples are OT-rich by chance, and the draw itself is fair.**
  - The samples hold 33 / 400 and 30 / 400 OT games. The pool they are drawn from holds 326 / 6,269 (5.2%).
  - Re-drawing with the run's own seeds gives back exactly the run's game ids.
  - Over 2,000 other seeds the OT count averages 21.0 ± 4.3. A count of 33 or more appears 9 times (0.45%);
    30 or more appears 59 times (3%).
  - The re-sim eligibility pool (regular season, a close, both teams with ≥ 5 prior games) runs 5.8% OT
    (258 / 4,476). So this is not a population effect.
- **Regulation: the re-sim is close, except in two places.**
  - At minute 38 the regulation residual is +1.01 ± 0.57. Almost all of it is the trailing-by-7-10 bucket
    (+3.22 ± 1.54). That is where real teams foul hardest: +5.68 points over the line's time share in the last
    2:00, against +2.51 at 0-3.
  - At minute 30 the regulation gap is in BLOWOUTS (sample 1: 11-19 +4.21, 20+ +2.96; smaller in sample 2). Real
    games with 11+ margins score +4.8 / +3.2 over the line's share in the last ten minutes.
- **Overtime: the sims under-produce regulation ties.**
  - Within 3 at minute 38, the sims give 12.8% OT against the season's 19.1% (n = 1,131, ± 2.3 pp).
  - At minute 30 they give about half the season's rate in every bucket.
- **Weighted to the season's margin mix** (bucket shares at minute 38: 19.6 / 14.6 / 16.4 / 22.7 / 26.7%), the
  expected late gap is about +0.9 regulation and +0.6 OT, roughly 1.4 points rather than the sample's 2.67. This
  assumes the sims' per-bucket OT shares carry over to the season.

**The refit, step 1: three variants of the existing end-game mechanisms.** They were pre-registered before the
run, then scanned at minutes 30 and 38 on sample 1's games and seeds (`mechscan`), on top of production's E1:
- **A:** the trailing-by-7-10 foul probability goes 0.6 → 0.9 (`endgame_foul_p_by_deficit` `[0.25, 0.5, 0.9]`).
- **B:** 4-6 goes 0.5 → 0.7 and 7-10 goes 0.6 → 0.9 (`[0.25, 0.7, 0.9]`).
- **C:** `blowout_bench_rest` on.

Gate: paired |err| better than production beyond 1.96 SE at minute 30 AND minute 38, with no bucket worse.

| variant | 30m, all | 38m, all | 38m, 7-10 | 38m regulation residual | bucket worse? |
|---|---|---|---|---|---|
| A | -0.04 ± 0.10 n.s. | -0.04 ± 0.08 n.s. | **-0.27 ± 0.22 better** | +1.01 → +0.78 | none |
| B | -0.03 ± 0.11 n.s. | **-0.12 ± 0.10 better** | **-0.29 ± 0.28 better** | +1.01 → +0.57 | none |
| C | -0.02 ± 0.05 n.s. | -0.01 ± 0.02 n.s. | 0.00 | unchanged | none |

No variant passed. B was better at minute 38 only, and it had been chosen after looking at this sample's buckets.

**The refit, step 2: B out of sample.** Fresh seed 20261108, a full harness run with `resim` (production) and
`resim_mech` (B), every segment and checkpoint.
- Pre-registered: the primary gate is the full total at minute 38; the secondary is that no segment ×
  checkpoint gets worse.
- 272 regular-season games, 17 of them shared with sample 1. Excluding those 17 changes no verdict.

| B vs production | 0m | 10m | 20m | 30m | 38m |
|---|---|---|---|---|---|
| full total | -0.02 ± 0.18 n.s. | -0.06 ± 0.18 n.s. | -0.07 ± 0.15 n.s. | -0.02 ± 0.12 n.s. | **-0.01 ± 0.10 n.s.** |
| h1 total | -0.08 ± 0.14 n.s. | -0.03 ± 0.11 n.s. | -- | -- | -- |
| h2 total | +0.08 ± 0.17 n.s. | +0.09 ± 0.16 n.s. | -0.07 ± 0.15 n.s. | -0.02 ± 0.12 n.s. | -0.01 ± 0.10 n.s. |
| full margin, raw | **-0.26 ± 0.18 better** | -0.01 ± 0.15 n.s. | +0.02 ± 0.13 n.s. | -0.01 ± 0.10 n.s. | **+0.08 ± 0.06 worse** |
| full margin, anchored | +0.00 | +0.09 ± 0.21 n.s. | +0.09 ± 0.15 n.s. | +0.00 ± 0.11 n.s. | **+0.08 ± 0.06 worse** |

- **B fails both gates.** It moves the minute-38 bias the right way (-2.34 → -1.91) without reducing |error|,
  and it costs margin at minute 38. Its in-sample gain was selection plus noise. Production E1 stays as it is.
- More foul probability alone does not fix the trailing-by-7-10 gap: B left that bucket +2.37 low in regulation
  even in-sample. What the trailing team does with its own possessions (quick threes, timeouts) is not modelled.
- **C (`blowout_bench_rest`) is inert on NCAAB totals.** The blowout gap needs a different input: the measured
  second-half scoring rate by margin state (1.010 / 1.059 / 1.052 / 1.047 of the prior's rate at
  0-5 / 6-10 / 11-19 / 20+, `ncaab_live_tier.md`).

**Production re-sim vs the line, both samples pooled** (535 regular-season games, deduplicated). This is the most
precise read so far, and it supersedes the single-sample gate in the college section for every cell it covers:

| production re-sim vs `pregame_rate` | 0m | 10m | 20m | 30m | 38m |
|---|---|---|---|---|---|
| full total | **+0.53 ± 0.34 worse** | -0.20 ± 0.35 n.s. | **-0.68 ± 0.41 better** | **-1.06 ± 0.28 better** | **-0.97 ± 0.24 better** |
| h1 total | **-0.57 ± 0.31 better** | +0.09 ± 0.16 n.s. | -- | -- | -- |
| h2 total | **-0.64 ± 0.40 better** | **-0.69 ± 0.40 better** | **-0.68 ± 0.41 better** | **-1.06 ± 0.28 better** | **-0.97 ± 0.24 better** |
| full margin, raw | **+0.33 ± 0.26 worse** | +0.18 ± 0.22 n.s. | **+0.17 ± 0.15 worse** | -0.00 ± 0.10 n.s. | +0.06 ± 0.08 n.s. |
| full margin, anchored (served) | +0.00 | +0.09 ± 0.15 n.s. | +0.04 ± 0.11 n.s. | -0.04 ± 0.09 n.s. | +0.05 ± 0.08 n.s. |

- **Replicated:** better than the line on h2 at every checkpoint and on the full total from minute 20, and better
  on h1 at the tip.
- **Not replicated:** sample 1's full total at the tip was n.s. Pooled, it is worse (+0.53 ± 0.34): the h1 gain
  and the h2 gain at the tip do not add up to a full-game gain. Sample 1's anchored-margin loss at 10m was also
  chance (pooled: n.s.).

**For Phase 2 (NCAAB), in order:**
1. **The OT / regulation-tie probability in close games.** It is the largest measured piece: about 0.6 points a
   game at minute 38, season-weighted, and it also bears on win probability in close games. The engine
   under-produces ties in the last minutes. Before building anything, measure the sims' end-of-regulation margin
   distribution against real games, conditioned on margin and clock. It needs a new end-game mechanism (for
   example, a trailing-by-3 team taking threes, or a tied team holding for the last shot). That means a loan of
   `engine.py` (lane `basketball-scenario-calibration`) and a refit of the rates the mechanism absorbs.
   **Measured 2026-11-08 23:13Z: see PHASE 2 STEP 3b below, whose revised order supersedes this item.**
2. **Blowout late scoring** (11+ margins, minutes 30-40), from the measured margin-state scoring rate.
3. **Trailing-by-7-10 end-game scoring.** The foul rate is not the lever (B). Look at the trailing team's own
   possessions.

## PHASE 2 STEP 3b (NCAAB): the sims' end-of-regulation margin against real games — the tie deficit is BOTH too much late spread and too little mass on a tie

`[2026-11-08 21:27-23:13Z (3:27-5:13 PM CST), lane ncaab-regulation-tie-shape, session c2fd17f8, read-only, nice 19]`

**Verdict.** The pre-registered hypothesis was SHAPE alone (lane block, pushed `605e2574f` before any run). The data
say BOTH, so the SHAPE-only hypothesis is falsified.
1. **SPREAD.** From minute 30 to minute 37 the sims' late margin moves 16-27% more than real games' does. From
   minute 30 to 38, sim leaders also EXTEND their leads by the end of regulation (+0.2 to +1.2 points) where real
   leaders hold (-0.5 to +0.1). By minute 39 the spread is right.
2. **SHAPE.** Real games put 2.5-3.0 times as much probability on a regulation tie as on a one-point finish either
   way. The sims put 1.6-1.9 times as much. The gap is beyond 1.96 SE at minute 30, at 34 (just), and at every checkpoint
   from minute 37 on. It is not at minute 36.
3. **Size.** Weighted to the season's margin mix, the sims send 1.8% too few of all games to overtime from minute 38,
   and 3.1% too few from minute 30. A real overtime adds 24.6 points (258 OT games in the pool), so that is about
   **0.44 points a game of total at minute 38 and 0.76 at minute 30**. Step 3's rough estimate was 0.6.

**Method.**
- **Sims:** the production NCAAB re-sim (live-odds-worker's three switches, read from its environ, never printed) on
  the 540 pooled regular-season re-sim games of `ncaab2026_resim_prod` and `ncaab2026_oos_B`, with the harness's
  seeds, at 8 checkpoints (30, 34, 36, 37, 38, 38.5, 39, 39.5 minutes) and 100 sims each. A wrapper records each
  sim's end-of-regulation margin. Code snapshot `~/bball_iv/code3`: its engine, resume and league files match the
  fleet's HEAD `582c24637` line for line. The only re-sim difference is a timestamp field.
- **Real:** the re-sim eligibility pool (regular season, a close, both teams with 5 or more prior games, PBP final
  matching, events file) — 4,472 games. The margin at the checkpoint and at the end of regulation come from the
  play-by-play events.
- **Checks:**
  - The replay state's margin equals the events' margin at 4,320 of 4,320 game-checkpoints.
  - A sim goes to OT exactly when its regulation ends tied, 4,320 of 4,320.
  - A real game goes to OT exactly when its regulation ends tied, 5,865 of 5,865.
- **Leader frame:** X = the end-of-regulation margin from the side leading at the checkpoint (the home side when
  tied), and D = X − |m|. The **tie ratio** is P(X=0) / mean(P(X=+1), P(X=−1)). Every ± is 1.96 × a bootstrap SE over
  games (1,000 draws). "Season" means the real pool; the sims' games are drawn from that same pool.

**P(regulation ends tied), and the late margin's spread**, wide buckets of |m| at the checkpoint:

| checkpoint | 0-3: season / sims (pp gap) | 4-6: season / sims (pp gap) | SD ratio sims/season, 0-3 / 4-6 | tie ratio 0-3, season / sims | mean D 0-3, season / sims |
|---|---|---|---|---|---|
| 30m | 11.3 / 5.5 (**-5.8 ± 2.0**) | 8.6 / 4.0 (**-4.5 ± 2.1**) | **1.27** / **1.20** | 2.66 / 1.61 | -0.09 / +0.50 |
| 34m | 12.9 / 7.7 (**-5.2 ± 2.2**) | 9.8 / 5.5 (**-4.3 ± 2.2**) | **1.23** / **1.17** | 2.62 / 1.89 | -0.19 / +0.21 |
| 36m | 14.9 / 9.8 (**-5.1 ± 2.4**) | 10.0 / 6.1 (**-3.9 ± 2.2**) | **1.26** / **1.16** | 2.49 / 1.92 | -0.11 / +0.40 |
| 37m | 16.2 / 11.2 (**-5.1 ± 2.5**) | 8.7 / 6.3 (**-2.4 ± 2.1**) | **1.22** / **1.18** | 2.62 / 1.93 | -0.10 / +0.41 |
| 38m | 18.5 / 12.9 (**-5.6 ± 2.5**) | 7.3 / 5.6 (-1.6 ± 2.0) | 1.09 / **1.16** | 3.01 / 1.77 | -0.02 / +0.30 |
| 38.5m | 18.9 / 14.3 (**-4.6 ± 2.5**) | 7.3 / 4.7 (**-2.6 ± 2.0**) | 1.10 / 1.09 | 2.65 / 1.85 | +0.17 / +0.41 |
| 39m | 20.0 / 15.4 (**-4.6 ± 2.6**) | 5.5 / 3.7 (-1.8 ± 1.8) | 1.04 / 1.08 | 2.61 / 1.84 | +0.22 / +0.30 |
| 39.5m | 21.1 / 17.3 (**-3.8 ± 3.0**) | 3.5 / 1.6 (**-1.9 ± 1.5**) | 0.96 / 1.02 | 2.60 / 1.65 | +0.33 / +0.16 |

- **Season n per cell:** 0-3 has 961-1,124 games and 4-6 has 603-782. The sims' cells have 75-142 games each.
- **SD ratio interval:** ± 0.04-0.06 throughout. **Bold** means beyond 10% with the interval excluding 1, the
  pre-registered SPREAD test.
- **Tie ratio intervals:** season ± 0.5-0.8, sims ± 0.13-0.29.
- **7-10 drift:** real leaders give back 0.1-0.5 points; sim leaders add 0.9-1.2 (for example 30m: -0.42 vs
  +1.21).

**What it says.**
- **The excess spread is inside each game, not between games.** The sims' within-game SD alone (7.98 at 30m, 0-3)
  is larger than the real total SD (6.55). The between-game part (team strength) is 2.4. A rough split of the 0-3
  tie deficit, scaling the sims' P(tie) by the SD ratio:
  - spread is about 1.5 of 5.8 pp at 30m and 2.6 of 5.1 at 36-37m;
  - shape is the rest: 4.4 of 5.6 at 38m and nearly all of it in the last minute.
- **Where the shape gap sits:**
  - **Tied with under a minute left: the sims are right.** 39m: 27.0% vs 26.8%; 39.5m: 46.7% vs 40.7% (n.s.).
  - **Trailing by one or two late: the gap is there.** Real games end tied far more often:
    - down 2 at 39m: 22.1% vs 13.5% (-8.7 ± 4.8);
    - down 2 at 39.5m: 23.1% vs 15.6% (-7.5 ± 4.7);
    - down 1 at 39m: 19.6% vs 13.7%.
  - **With 30 s left and a 1-3 lead,** the sims leave the leader ahead by exactly 1 in 15.4% of games against a real
    9.3%. Real leaders more often finish 4-6 up (fouled, free throws) or the game ties. The sims under-produce
    events in the last possessions on both sides.
- **Engine read** (`engine.py`, no edit):
  - Each period's possessions are pre-counted.
  - The next possession switches team with probability 0.85, else a coin flip.
  - The only trailing-team rule is a bump to 3-point rate. There is no last-shot logic: no going for 2 to tie, no
    holding the ball when tied.
  - The catch-up lever `score_effect_k` (shot and FT make probability scaled by the lead against the expected lead)
    exists, default off, and production does not set it.
    - NBA: k = 0.002 brought the margin SD from 18.89 to 14.91 against a real 14.00 (`state_basketball.md`).
    - The user accepted it as a PROPOSAL on 2026-10-10. It is not enabled.
- **What it does to the projection:**
  - Totals: about 0.44 points a game of overtime are missing at minute 38, and 0.76 at minute 30.
  - Probabilities: the over-wide spread makes the late win probability and margin distribution too uncertain.
  - The P(leader loses) differences are inside the intervals (for example 30m 0-3: 34.9 real vs 37.8 sims,
    ± 2.9 / 2.1). So the excess spread mostly fattens BOTH tails, and the leader's extension offsets it.

**Lever follow-up: neither existing lever fixes the spread.** This was diagnostic and pre-registered in the lane
block (`0f8db1dd8`) before the run.
- **What ran:** two EventSimConfig fields, each on top of production's E1, at minutes 30, 36 and 38, on the same
  540 games and seeds.
- **Provenance:** each variant carried its own field plus E1, on 540 of 540 games.
- **Paired change:** the variant's P(tie) minus production's, on the same game and seed.

| 0-3 bucket | SD ratio at 30m / 36m / 38m | mean D at 30m (real -0.09) | 7-10 mean D at 30m (real -0.42) | paired change in tie %, 30m / 36m / 38m |
|---|---|---|---|---|
| production | 1.27 / 1.26 / 1.09 | +0.50 | +1.21 | -- |
| SE: `score_effect_k` 0.002 | 1.26 / 1.25 / 1.08 | +0.27 | +0.77 | -0.2 ± 0.5 / +0.2 ± 0.7 / +0.2 ± 0.6 |
| ALT: `possession_alternation` 1.0 | 1.23 / 1.21 / 1.04 | +0.37 | +1.21 | +0.1 ± 0.6 / +0.3 ± 0.9 / +0.6 ± 0.8 |

- **SE is falsified as the spread fix.**
  - It moved the SD ratio 0.01 of a 0.27 gap; the pre-registered test needed a third of it. 4-6 and 7-10 moved by
    0.01-0.03.
  - It does what it is built to do on the DRIFT: about halfway toward real at 30m (+0.50 to +0.27; 7-10: +1.21 to
    +0.77).
  - But it is far too weak per possession to tighten the spread. The factor is about 1% per 5 points of
    deviation. NBA's k was fitted on full-game margin SD.
- **ALT is small, as predicted:** 3-5% off the SD, with the shape unchanged. Possessions repeating by coin flip are
  a real but minor source.
- **No variant moves the tie rate:** every paired change is within ±0.9 pp.
- **The spread's source is still unidentified.** It is not team strength: the between-game part is 2.4, and the
  sims' within-game SD alone exceeds the real total. Next to measure, from the sims' rest-of-game box against the
  real play-by-play over the same window:
  - possessions per team in the last 10 minutes, and how unequal they are;
  - the spread of points per possession: 3-point share, offensive-rebound chains (up to 5 shots per possession),
    and free-throw trips.

**For Phase 2 (NCAAB), revised order** (this supersedes item 1 of step 3's list):
1. **End-game decision rules for the last possessions.** This is the SHAPE part: about 4 of the 5-6 pp tie
   deficit in close games from minute 38.
   - What to model: a trailer down 2 plays for 2 to tie; a 1-3 lead turns into free throws for the leader; the
     team with the ball when tied holds it.
   - It needs a loan of `engine.py` (lane `basketball-scenario-calibration`) and a refit of the E1 foul rates the
     rules absorb.
   - Gate: first P(tie) and the tie ratio by state against the tables above, then the harness totals and margin
     gate.
2. **Find the spread source before choosing a lever** (diagnostic, no engine edit): the box comparison above. A
   wider catch-up k is a candidate only after that; k = 0.002 is not enough.
   **Measured 2026-11-09 00:00Z: see PHASE 2 STEP 3c below.**
3. Blowout late scoring and trailing-by-7-10 scoring (step 3's items 2 and 3) are unchanged. The spread finding
   bears on both, so re-read them after item 2.

**Scratch:**
- Scripts, in the session scratchpad: `tieshape.py`, `tiereal.py`, `tieanalyze.py`, `tieextra.py`,
  `otpoints.py`, `leverscan.py`, `leveranalyze.py`.
- Outputs: `~/bball_iv/runs/ncaab2026_tieshape/{sims,real,levers}.jsonl`.

## PHASE 2 STEP 3c (NCAAB): where the over-wide late margin spread comes from — the sims put late scoring variance in the wrong place

`[2026-11-08 23:26Z-11-09 00:00Z (5:26-6:00 PM CST), lane ncaab-late-spread-source, session c2fd17f8, read-only, nice 19; user "Yes, find the source"]`

**Verdict.**
- **Per team, the late scoring variance is about right:** +8% from minute 30, -6% from minute 36.
- **Real games share a fifth to a third of it between the two teams; the sims share almost none.** Both teams'
  points rise and fall together in real games (correlation 0.22 from minute 30, 0.32 from minute 36). In the sims
  they are independent (0.02, 0.03).
- **So the team-specific part is 33-36% too large, and the margin carries all of it.** The margin is a difference:
  its variance is twice the team-specific variance.
- **The same misplacement makes the late TOTAL too narrow:** 90% of real variance from minute 30, 73% from minute 36.
- **In real games the shared part is entirely the possession count.** Given the window's total possessions, the
  two teams' points are uncorrelated (partial correlation 0.01 / -0.01).

**The pre-registered hypothesis (PER-POSSESSION, lane block `cb875abd8`) is FALSIFIED as framed.**
- Its first clause fails. The possession differential is not within 25% of real: SD 2.83 vs 1.17 by the shared
  estimator, and the sims' true SD is 1.88.
- Its 60% threshold (59% / 53%) was read off an estimator split that turned out unreliable for the sims (below).
- The source sits in a channel I did not pre-register: how the variance is placed. It is an identity, not a fit,
  and it replicates in both samples, at both checkpoints and in every margin bucket.

**Method.**
- **Replay:** the production re-sim (live-odds-worker's switches, never printed) on the same 540 games and seeds as
  step 3b, at minutes 30 and 36, 100 sims each.
- **Instrumentation:** a scratch engine copy (`~/bball_iv/code4`) adds three RNG-neutral lines under
  `record_events`:
  - a POSS marker at each possession, carrying the offense, the clock, and the cumulative team box and score;
  - a PEND marker after each period;
  - no cap on the event list.
- **Production code is untouched.**
- **Fidelity:** regulation-margin histograms identical to step 3b's in 1,080 / 1,080 game-checkpoints. Window points
  reconcile to the engine's period scores in 108,000 / 108,000 sims.
- **Real side:** the 4,472-game pool, each team's box over the same window (`bib._counts` on the window's events).
- **Intervals:** ± is 1.96 × a bootstrap SE over games.

**Where the variance sits** (estimator-free; per team, checkpoint to the end of regulation):

| | from 30m: real | sims | from 36m: real | sims |
|---|---|---|---|---|
| points per team | 20.47 | 19.91 | 9.00 | 8.40 |
| Var(points), per team | 30.44 | 32.76 | 14.30 | 13.38 |
| Cov(home, away) | 6.82 ± 0.91 | 0.72 ± 0.40 | 4.51 ± 0.48 | 0.34 ± 0.14 |
| correlation | 0.224 ± 0.027 | 0.022 ± 0.012 | 0.315 ± 0.028 | 0.026 ± 0.011 |
| team-specific part (Var - Cov) | 23.62 | **32.04** (+36%) | 9.79 | **13.04** (+33%) |
| Var(margin change) = 2 × team-specific | 47.23 ± 1.90 | 64.09 ± 1.06 | 19.58 ± 0.81 | 26.07 ± 0.47 |
| Var(window total) = 2 × (Var + Cov) | 74.52 | **66.97** (0.90×) | 37.62 | **27.44** (0.73×) |

**It is real, it is everywhere, and it is the possession count.**
- **Replication** (correlation of the two teams' points, each sample's games against the SAME games' real outcomes):

  | sample | from 30m: sims | from 30m: real | from 36m: sims | from 36m: real |
  |---|---|---|---|---|
  | 1 | 0.029 ± 0.017 | 0.254 ± 0.104 | 0.022 | 0.332 ± 0.098 |
  | 2 | 0.013 ± 0.017 | 0.201 ± 0.118 | 0.029 | 0.307 ± 0.114 |

- **By |margin| from 30m:** real 0.15-0.25 in every bucket (0-3: 0.253; 11-19: 0.227; 20+: 0.147), sims -0.02 to
  +0.05. So it is not an end-game-fouling effect confined to close games.
- **Possessions:**
  - The two teams' window possessions correlate 0.87 in real games, against 0.20 in the sims by the same estimator
    (0.34 by the sims' true counts).
  - Shared possession variance: real 4.47, sims 0.89 by the true counts.
  - With total possessions held fixed, the points correlation vanishes in real games (0.014) and goes slightly
    negative in the sims (-0.06).

**What the sims do inside the team-specific part** (from minute 30; real box from the play-by-play):

| per team, window | real | sims |
|---|---|---|
| FTA per FGA | 0.576 | **0.289** |
| OREB per missed FG | 0.363 | 0.190 |
| 2P% | 0.537 | 0.468 |
| 3P% | 0.324 | 0.346 |
| 3PA share | 0.389 | 0.405 |
| TOV per possession | 0.149 | 0.156 |
| FT% | 0.734 | 0.751 |

- **Free throws.** The sims take HALF the real late free throws: 0.29 vs 0.58 per FGA from minute 30, 0.38 vs 0.75
  from minute 36. Points move toward made threes.
- **OREB caveat:** real "offensive rebounds" include team and free-throw rebounds, so that row is partly
  definitional.
- **Per-possession outcomes are too variable.** The sims' points per possession are 0 / 1 / 2 / 3 / 4+ in 52.7 /
  2.9 / 29.0 / 14.8 / 0.6%. That is a mean of 1.078 and a variance of 1.459.
  - E[possessions] × that variance is 26.95, which alone exceeds real's whole team-specific variance (23.62).
  - Taking the two pools' between-game strength spread as equal, and real's unshared possession variance as 0.68 at
    most, real's per-possession variance comes out near 1.08. So the sims' would be about 35% too high.
  - This is INFERRED. The real per-possession distribution is not measured yet; the next step measures it.
  - **WITHDRAWN in step 3e below (2026-11-09):** measured real variance is 1.308 from 30m, so the sims are 11.5% too dispersed, not 35%. The inference assumed independent real possessions.
- **Possession imbalance.**
  - The sims' coin-flip alternation (2.69 repeats per team-window from minute 30) gives a true SD of home-minus-away
    possessions of 1.88. Real is at most 1.17, the estimator's SD, which includes its own noise.
  - Measured directly in step 3b: alternation 1.0 removes 3-5% of the margin SD. It is the smaller piece.
- **Pace, not the source.**
  - The sims' TRUE possessions are 18.48 per team from minute 30 (1.85 a minute) and 7.67 from 36 (1.92). The
    estimator reads real at 17.74 and 7.67.
  - The re-sim's pace input averages 69.92 against the same 285 games' real 68.30 (+2.4%; per-game correlation
    0.52).
  - The first-pass split's "14% more possessions" was the possession ESTIMATOR overcounting the sims by 10%
    (20.26 vs 18.48), so that split (59% per-possession / 35% possession) is withdrawn.
- **Engine read** (`engine.py`, no edit). Each period's possessions are counted at the period start: the pace input ×
  the time left, with 6% shared jitter. They are then split by the 0.85-plus-coin-flip alternation. Only E1 adds
  possessions, in the last 120 s. Whether real games' shared possession variation is between-game pace or in-game
  state is not yet separated.

**What it means for the projections:**
- **Margins:** late margin and win-probability distributions are too wide, as step 3b found.
- **Totals:** late totals' distributions are too NARROW (73-90% of real variance), so late over/under
  probabilities are overconfident.
- **Means:** neither moves the means. Mean points from minute 30 run 0.55 per team low, consistent with step 3.

**Next for NCAAB, both diagnostic first, against these tables:**
1. **DONE in step 3d below** (2026-11-09 02:21Z): no existing setting fixes it; jitter supplies the shared part from 30m only.
   **Test the existing default-off fields** with no engine edit, on the same games, seeds and checkpoints. Read
   team-specific variance, covariance, total variance, margin SD and tie rate.
   - The fields: E2's bonus free throws (`bonus_nonshoot_foul_per_poss` 0.08, `bonus_second_half_mult` 1.5);
     alternation 1.0; and `possessions_jitter` for shared pace variance.
   - E2 was rejected on point accuracy (`ncaab_live_tier.md` §E2: margin MAE +0.23 at H2 10:00). It was never
     measured on the distribution, which is the open question here.
2. **Segment real play-by-play into possessions** (production `_possession_after`) to measure the real
   per-possession outcome distribution. That confirms or refutes the inferred 35%.
3. **The end-game decision rules from step 3b are unchanged** (they need an `engine.py` loan). The late free-throw
   deficit is common to both findings: real leaders extend and real games tie through free-throw trips.

**Scratch:**
- Scripts, in the session scratchpad: `make_code4.py`, `spreadsrc.py`, `spreadreal.py`, `spreadanalyze.py`,
  `pacecheck.py`, `spreaddirect.py`, `spreadcov.py`.
- Outputs: `~/bball_iv/runs/ncaab2026_tieshape/spread_{sims,real}.jsonl`.

## PHASE 2 STEP 3d (NCAAB): no existing setting fixes the misplaced late variance — possession jitter supplies the shared part from minute 30 only; per-possession variance is the remaining piece

`[2026-11-09 01:23Z-02:21Z (7:23-8:21 PM CST 11-08), lane ncaab-spread-existing-levers, session c2fd17f8, read-only, nice 19; user "Yes, test them"]`

**Verdict.**
- **No existing setting fixes it.** All three together close 30% of the team-specific excess from minute 30 and
  44% from minute 36. The SD of the margin change goes from 1.165× real to 1.118× (30m) and from 1.154× to 1.089×
  (36m). The three arms' effects on the team-specific part add up: -2.52 together against -2.48 summed (30m).
- **`possessions_jitter` 0.12 supplies the missing SHARED variance from minute 30, but not from minute 36.**
  - From 30m: Cov(home, away) goes 0.71 → 5.00 (real 6.82), closing 70% of the gap.
  - From 36m: 0.34 → 1.11 (real 4.51), closing 18%.
  - Jitter scales with the time left squared; the real shared variance does not. Real Cov from 36m is 66% of the
    30m value with 40% of the time left. So the last minutes' shared variance is game STATE, not pace uncertainty.
- **Jitter alone makes the late total too WIDE from 30m:** Var(total) 84.0 against real 74.5 (base 66.9). The
  team-specific part is still 36% high, and the shared part now sits on top of it. The two have to be fixed
  together; jitter is not a standalone fix.
- **Strict alternation (1.0) is the only arm that narrows the margin without moving the means:** Var(margin
  change) -5.7% / -6.6%, mean points -0.03 / +0.01.
- **E2 bonus free throws fix the free-throw RATE and the late MEAN, not the spread.**
  - FTA per FGA 0.289 → 0.466 (real 0.575).
  - Late points per team from 30m +0.48 ± 0.05, which closes 87% of the mean gap.
  - Per-possession variance only 1.459 → 1.398 (-4%), so team-specific -1.9% / -3.7%.
- **Tie rate:** no arm moves it by more than 0.3 points.
  - Real: 5.77% of the pool's games end regulation tied, and 8.91% ± 2.42 of these same 539 games.
  - Sims: from 30m, base 2.65% and the arms 2.77-2.92%. From 36m, base 3.53% and the arms 3.53-3.69%.

**Pre-registered hypothesis EXISTING-FIELDS (lane block `7af9dd1d0`, before any arm ran): one clause FALSIFIED, the
rest hold.**

| clause | predicted | measured (30m / 36m) | |
|---|---|---|---|
| (a) JIT12 Cov(home, away) from 30m | 3.5-6.0 | 5.00 | holds |
| (a) JIT12 Cov from 36m | under 1.5 | 1.11 | holds |
| (a) JIT12 Var(margin change) | moves under 5% | -0.1% / -0.8% | holds |
| (b) E2 team-specific part | -4% to -12% at both | -1.9% / -3.7% | **below the range** (right direction, inside the 2× tolerance) |
| (b) E2 FTA per FGA from 30m | 0.45-0.70 | 0.466 | holds |
| (b) E2 mean window points per team | +0.4 to +1.2 | +0.48 (30m) | holds |
| (c) ALT1 Var(margin change) | -4% to -10% | -5.7% / -6.6% | holds |
| (c) ALT1 Var(total) | within 10% | +0.9% / +0.3% | holds |
| (c) ALT1 Cov(home, away) | within 10% | **+150% / +133%** (0.71 → 1.78; 0.34 → 0.79) | **FALSIFIED** |
| (d) ALL team-specific part | at least 10% above real | +25% / +19% | holds |

- **Why (c)'s Cov clause failed.**
  - The identity is Cov(N_h, N_a) = (Var(T) - Var(dN)) / 4, with T the total and dN the difference of the two
    teams' possessions.
  - The coin-flip split's imbalance is negatively shared. Removing it takes the true SD(dN) from 1.88 to 0.71.
  - That raises Cov(N_h, N_a) by about (3.53 - 0.50) / 4 = 0.76 possessions², or 0.88 points² at the sims'
    1.078 points per possession. Measured: +1.07.
  - The identity predicted it; the pre-registration did not apply it.
- **The falsification test's other triggers did not fire.**
  - JIT12 closed 18% of the 36m covariance gap, not half or more.
  - ALL leaves the team-specific part 25% above real from 30m, not within 10%.

**Method.**
- **Same setup as step 3c:**
  - the code4 copy with RNG-neutral possession markers;
  - the production re-sim with live-odds-worker's three switches (never printed);
  - the same 540 games, seeds and checkpoints (30m, 36m), 100 sims each.
- **Arms, each on top of production E1 via `Resim(mechanisms=...)`:**
  - E2: `bonus_free_throws` true, `bonus_nonshoot_foul_per_poss` 0.08, `bonus_second_half_mult` 1.5. That is
    `ncaab_live_tier.md` §E2's config, as recorded in `ncaab_bt_e2.json`.
  - ALT1: `possession_alternation` 1.0 (default 0.85, otherwise a coin flip).
  - JIT12: `possessions_jitter` 0.12 (default 0.06). 0.12 was set before the run: it is the value that brings the
    sims' total-possession variance from 30m up to the real estimator's 19.2.
  - ALL: the three together.
- **Base:** step 3c's run (same copy, seeds and tasks).
- **Reachability, every arm:**
  - provenance `cfgFields` name its fields in 540 / 540 games;
  - margin histograms differ from the base in 1,080 / 1,080 game-checkpoints;
  - window points reconcile in 108,000 / 108,000 sims.
- **Intervals:** paired arm minus base, 1.96 × a bootstrap SE over games.
- **Real column:** the 4,472-game pool, step 3c's reference. These same 539 games agree with it within their
  interval on every row except the tie rate.

**From minute 30 to the end of regulation** (per team, window; ± in the paired table below):

| | real | base | E2 | ALT1 | JIT12 | ALL |
|---|---|---|---|---|---|---|
| points | 20.47 | 19.91 | 20.39 | 19.89 | 19.92 | 20.41 |
| Var(points) | 30.44 | 32.76 | 32.24 | 31.99 | 37.00 | 36.02 |
| Cov(home, away) | 6.82 | 0.71 | 0.80 | 1.78 | 5.00 | 6.50 |
| correlation | 0.224 | 0.022 | 0.025 | 0.056 | 0.135 | 0.180 |
| team-specific part (Var - Cov) | 23.61 | 32.05 | 31.44 | 30.21 | 32.00 | **29.52** |
| Var(margin change) | 47.23 | 64.09 | 62.88 | 60.42 | 64.00 | 59.05 |
| SD(margin change), × real | 1 | 1.165 | 1.154 | 1.131 | 1.164 | 1.118 |
| Var(window total) | 74.52 | 66.94 | 66.08 | 67.54 | **84.00** | **85.04** |
| FTA per FGA | 0.575 | 0.289 | 0.466 | 0.289 | 0.289 | 0.467 |
| true SD(home - away possessions) | ≤ 1.17 | 1.88 | 1.87 | 0.71 | 1.87 | 0.71 |
| true Var(total possessions) | 19.2 (estimator) | 7.08 | 7.33 | 7.15 | 21.57 | 21.85 |
| variance of points per possession | ~1.08 (inferred, 3c) | 1.459 | 1.398 | 1.459 | 1.459 | 1.399 |

**From minute 36:**

| | real | base | E2 | ALT1 | JIT12 | ALL |
|---|---|---|---|---|---|---|
| points | 9.00 | 8.40 | 8.67 | 8.40 | 8.39 | 8.67 |
| Var(points) | 14.30 | 13.38 | 12.97 | 12.97 | 14.04 | 13.22 |
| Cov(home, away) | 4.51 | 0.34 | 0.42 | 0.79 | **1.11** | 1.60 |
| correlation | 0.315 | 0.025 | 0.032 | 0.061 | 0.079 | 0.121 |
| team-specific part | 9.79 | 13.04 | 12.56 | 12.18 | 12.94 | **11.61** |
| Var(margin change) | 19.58 | 26.08 | 25.11 | 24.36 | 25.87 | 23.23 |
| SD(margin change), × real | 1 | 1.154 | 1.132 | 1.116 | 1.150 | 1.089 |
| Var(window total) | 37.62 | 27.43 | 26.78 | 27.52 | 30.30 | 29.64 |
| FTA per FGA | 0.746 | 0.376 | 0.626 | 0.377 | 0.376 | 0.630 |
| true SD(home - away possessions) | - | 1.32 | 1.32 | 0.71 | 1.32 | 0.71 |
| true Var(total possessions) | 10.5 (estimator) | 2.66 | 2.71 | 2.68 | 5.08 | 5.13 |
| variance of points per possession | - | 1.441 | 1.359 | 1.442 | 1.440 | 1.357 |

**Paired, arm minus base** (1.96 × bootstrap SE over games):

| arm | team-specific | Cov | Var(margin change) | Var(total) | points per team | tie % |
|---|---|---|---|---|---|---|
| E2, 30m | -0.60 ± 0.52 | +0.09 ± 0.38 | -1.21 ± 1.03 | -0.86 ± 1.10 | +0.48 ± 0.05 | +0.27 ± 0.21 |
| ALT1, 30m | -1.84 ± 0.50 | +1.07 ± 0.38 | -3.67 ± 1.01 | +0.60 ± 1.12 | -0.03 ± 0.04 | +0.12 ± 0.19 |
| JIT12, 30m | -0.04 ± 0.48 | +4.29 ± 0.38 | -0.09 ± 0.96 | +17.06 ± 1.22 | +0.01 ± 0.04 | +0.21 ± 0.18 |
| ALL, 30m | -2.52 ± 0.50 | +5.78 ± 0.45 | -5.04 ± 0.99 | +18.10 ± 1.38 | +0.50 ± 0.05 | +0.21 ± 0.20 |
| E2, 36m | -0.49 ± 0.20 | +0.08 ± 0.16 | -0.97 ± 0.41 | -0.65 ± 0.48 | +0.27 ± 0.03 | +0.16 ± 0.23 |
| ALT1, 36m | -0.86 ± 0.20 | +0.45 ± 0.15 | -1.72 ± 0.40 | +0.08 ± 0.46 | +0.01 ± 0.03 | +0.08 ± 0.22 |
| JIT12, 36m | -0.10 ± 0.19 | +0.77 ± 0.14 | -0.21 ± 0.39 | +2.87 ± 0.45 | -0.01 ± 0.03 | +0.00 ± 0.20 |
| ALL, 36m | -1.43 ± 0.22 | +1.27 ± 0.16 | -2.85 ± 0.43 | +2.21 ± 0.49 | +0.27 ± 0.03 | +0.15 ± 0.22 |

- **E2's points per possession** (sims, from 30m), as 0 / 1 / 2 / 3 / 4+:
  - base: 52.7 / 2.9 / 29.0 / 14.8 / 0.6%;
  - E2: 50.0 / 4.6 / 31.3 / 13.6 / 0.6%.
  - Free-throw trips move mass from 0 and 3 to 1 and 2. That is a 4% cut in variance; the inferred real level
    needs about 26%.
  - **REPLACED in step 3e below (2026-11-09):** measured real variance is 1.308, so E2 closes 40% of a 0.151 gap.
- **Tie rate, real pool against these games:** the 539 games carry more regulation ties than the pool (8.91% ± 2.42
  vs 5.77% ± 0.69). The sims' base rate is 2.65% from 30m either way, so the deficit is 3.1 to 6.3 points.

**What it means for the projections (nothing ships from this lane):**
- **The late-variance error now splits into three measured pieces.**
  1. **Shared possession variance.**
     - From minute 30, a pace-uncertainty knob reaches it (jitter).
     - From minute 36 it does not: real 4.51 against 1.11 with jitter doubled.
     - Step 3c's buckets put the real shared correlation from 36m highest when the margin is 7-19 (0.373) and
       lowest at 20+ (0.076). That fits trailing teams speeding up and fouling across the last 4 minutes, well
       before E1's 120-second window. This is a HYPOTHESIS, not measured here; it needs an `engine.py` mechanism.
  2. **Possession imbalance.** Alternation 1.0 removes it: -5.7% / -6.6% of the margin-change variance, with no
     mean change. It is an existing field, so it could go to the harness's paired point-accuracy gate with no
     engine edit.
  3. **Per-possession variance.** This is the largest piece left. E2 removes 4% of it, and the inferred gap is
     about 26%. The real per-possession distribution has to be measured before any mechanism is built.
- **E2 is no longer just "rejected".** It fixes the late free-throw rate and the late mean from 30m (+0.48 per
  team, 87% of the gap). Its rejection was on early-game totals and margins (tip and H2 10:00).
  - A late-only bonus rate, for example `bonus_second_half_mult` with a lower first-half base, is a refit
    candidate.
  - Not tested here: refitting E2 interacts with E1 and the exact-target solve (`solver_bonus_trip_share`).
- **Do not raise `possessions_jitter` on its own.** It fixes the 30m total's narrowness only by over-shooting it
  (84 vs 74.5) while the team-specific excess stands. From 36m it leaves 82% of the shared gap.

**Next for NCAAB:**
1. **Segment real play-by-play into possessions** (production `_possession_after`) to measure the real
   per-possession outcome distribution and its variance. That decides piece 3.
2. **Alternation 1.0 through the harness's paired gate** on point accuracy: an existing field, no engine edit.
   It is optional and cheap.
3. **Mechanisms for pieces 1 and 3, plus step 3b's end-game decision rules.** Each needs an `engine.py` loan from
   lane `basketball-scenario-calibration`, and an E1 refit afterwards (model_engine_standard.md: mechanism vs
   estimator).

**Scratch:**
- Scripts, in the session scratchpad: `spreadlevers.py`, `run_spreadlevers.sh`, `leversanalyze.py`.
- Output: `~/bball_iv/runs/ncaab2026_tieshape/spread_levers.jsonl` (2,160 game-arm rows). Log:
  `~/bball_iv/runs/ncaab2026_spreadlevers.log` (DONE 2160 jobs in 2,877 s).

## PHASE 2 STEP 3e (NCAAB): real per-possession scoring, measured — the sims are 11-15% too dispersed, not 35%; real late outcomes vary LESS than independent possessions would

`[2026-11-09 14:00Z-14:10Z (8:00-8:10 AM CST), lane ncaab-real-possession-outcomes, session c2fd17f8, read-only, nice 19; user "Yes, measure it"]`

**Verdict.**
- **Real late possessions are less dispersed than the sims' (11-15%), but not by the 35% step 3c inferred.**
  - Variance of points per possession, from minute 30: real 1.308 ± 0.005 against the sims' 1.459, so the sims
    are 11.5% too dispersed.
  - From minute 36: 1.259 ± 0.007 against 1.441, 14.5% too dispersed.
- **That is about a third of the sims' team-specific excess.** The rest is extra and unevenly split possessions,
  plus a piece that only the real side has.
- **The piece only the real side has (INFERRED).**
  - Treat each real possession as an independent draw from the real distribution. That alone predicts the whole
    of real games' measured team-specific variance (23.42 against 23.61 from 30m; 10.00 against 9.79 from 36m),
    leaving NO room for teams differing in strength.
  - Teams do differ: in the sims that part is 3.08 / 0.91. So real late outcomes vary about 3 / 1 points² LESS
    than independent possessions plus team strength would give.
  - That points to real games pulling back toward something within the window, such as score effects or
    mean reversion. The sims have none of it: their closure is exact (+0.12 / +0.15).
  - This piece is INFERRED. It rests on the sims' between-game spread standing in for the real one.
  - **MEASURED in step 3f below (2026-11-09), from real margins alone:** at least 2.51 ± 0.92 from 30m (30% of the excess) and at least 0.59 ± 0.42 from 36m (18%).
- **The real outcome mix.** Real possessions score 0 less often (45.5% vs 52.7%) and 3 less often (12.4% vs
  14.8%), and score 1 and 2 more often (6.3% vs 2.9%; 35.5% vs 29.0%). 24.6% of real late possessions include a
  free throw. Real points per possession average 1.157 against the sims' 1.078.
- **E2 bonus free throws close 40% of the per-possession variance gap** (1.459 → 1.398) and move every outcome
  class toward real. In step 3d that looked like 4% of an inferred 26% gap.

**Pre-registered hypothesis PER-POSS-VAR (lane block `110e34ed2`, before any segmentation): NOT SUPPORTED; its
falsification line was not crossed.**

| clause | predicted | measured | |
|---|---|---|---|
| real per-possession variance from 30m | 0.95-1.20 | 1.308 ± 0.005 | **outside the range** |
| falsification line | at least 1.32 falsifies | 1.308 (upper bound 1.313) | not crossed |
| "the bulk of the team-specific excess" | most of +8.4 | about +2.8 of +8.4 | **fails** |
| 1-point possessions, real | at least 2 × the sims' 2.9% | 6.3% | holds |
| 3-point possessions, real | under 12% | 12.4% | **narrowly fails** |

- The value fell in the gap the pre-registration left between its range and its falsification line.
- The prior stated in the lane (1.2-1.37 from the box rates) was right. Step 3c's 35% inference was wrong: it
  assumed real possessions are independent, and the closure below contradicts that.

**Method.**
- **Segmentation.** Production's PBP event stream (`read_events`, the harness's own), 4,472 pool games, regulation
  only, into possessions as the engine defines them:
  - one team's spell with the ball, offensive-rebound chains and free-throw trips inside it;
  - and-one free throws credited to the basket's possession.
  - ESPN's college feed has NO last-free-throw flag (0 of 12,145 free throws in 300 games), so a control change is
    read off the next informative play: a defensive or dead-ball rebound, a steal, or the other team's shot,
    turnover or free throw.
  - Both orders of steal / turnover and offensive-foul / turnover pairs attach to one possession.
- **Window.** Possessions with an action (shot, free throw, turnover, offensive foul) after the checkpoint; points
  after the checkpoint. "Empty" possessions (a rebound or steal, then the buzzer) are excluded: 0.32 per
  team-window from 30m.
- **Validation gates, read before the result:**
  - credited points equal regulation points in 4,472 / 4,472 games;
  - window points equal box points in 8,944 / 8,944 team-windows;
  - segmented possessions per team-window from 30m: 17.69 against the estimator's 17.74 (-0.3%; per-window
    correlation 0.955). From 36m: 7.71 against 7.67;
  - two games' last 3 minutes read by hand (scratch `poss_real_sample.txt`), every possession right.
- **Sims:** step 3c's base and step 3d's E2 rows (`h_pp` / `a_pp` and the true possession counts from the code4
  markers).
- **"Within-window variance":** each team-window's own sample variance, pooled. It strips the between-game spread
  of the mean; it differs from the pooled variance by under 0.01.

**Points per possession, from minute 30 to the end of regulation:**

| | 0 | 1 | 2 | 3 | 4+ | mean | variance | within-window | possessions per team | with a free throw |
|---|---|---|---|---|---|---|---|---|---|---|
| real, pool (4,472) | 45.5% | 6.3% | 35.5% | 12.4% | 0.3% | 1.157 | 1.308 | 1.300 | 17.69 | 24.6% |
| real, the replay's 540 | 45.6% | 6.3% | 35.3% | 12.6% | 0.3% | 1.157 | 1.313 | 1.309 | 17.69 | 24.6% |
| sims, base | 52.7% | 2.9% | 29.0% | 14.8% | 0.6% | 1.078 | 1.459 | 1.450 | 18.48 | - |
| sims, E2 | 50.0% | 4.6% | 31.3% | 13.6% | 0.6% | 1.103 | 1.398 | 1.388 | 18.49 | - |

**From minute 36:**

| | 0 | 1 | 2 | 3 | 4+ | mean | variance | within-window | possessions per team | with a free throw |
|---|---|---|---|---|---|---|---|---|---|---|
| real, pool | 43.7% | 7.9% | 36.7% | 11.4% | 0.3% | 1.168 | 1.259 | 1.251 | 7.71 | 29.5% |
| real, the replay's 540 | 44.2% | 7.8% | 36.3% | 11.3% | 0.3% | 1.158 | 1.265 | 1.265 | 7.71 | 29.0% |
| sims, base | 51.2% | 4.0% | 29.5% | 14.7% | 0.6% | 1.095 | 1.441 | 1.427 | 7.67 | - |
| sims, E2 | 47.5% | 6.4% | 32.4% | 13.1% | 0.6% | 1.129 | 1.359 | 1.345 | 7.68 | - |

**Closure of the team-specific variance** (Var - Cov of window points, per team):
- **A** = E[N] × within-window variance: the independent-possession noise.
- **B** = mean² × (Var(N) - Cov(N_h, N_a)): the unshared possession count.
- **between** = the team-specific spread of the per-game expected points. It is measured for the sims from each
  game's 100 sims. For real games it is unknown, and the sims' value stands in.
- **rest** = measured - A - B - between.

| from 30m | measured | A | B | between | rest | E[N] | Var(N) | Cov(N_h, N_a) | mean | within var |
|---|---|---|---|---|---|---|---|---|---|---|
| real, pool | 23.61 ± 0.95 | 23.00 | 0.42 | 3.08 (sims' value) | **-2.88** | 17.69 | 4.77 | 4.46 | 1.157 | 1.300 |
| real, the replay's 540 | 22.83 | 23.16 | 0.41 | 3.08 (sims' value) | -3.81 | 17.69 | 4.63 | 4.32 | 1.157 | 1.309 |
| sims, base | 32.04 | 26.80 | 2.05 | 3.08 | +0.12 | 18.48 | 2.65 | 0.89 | 1.078 | 1.450 |
| sims, E2 | 31.44 | 25.68 | 2.13 | 3.28 | +0.35 | 18.49 | 2.71 | 0.95 | 1.103 | 1.388 |

| from 36m | measured | A | B | between | rest | E[N] | Var(N) | Cov(N_h, N_a) | mean | within var |
|---|---|---|---|---|---|---|---|---|---|---|
| real, pool | 9.79 ± 0.40 | 9.64 | 0.36 | 0.91 (sims' value) | **-1.12** | 7.71 | 2.73 | 2.46 | 1.168 | 1.251 |
| real, the replay's 540 | 9.36 | 9.75 | 0.35 | 0.91 (sims' value) | -1.65 | 7.71 | 2.70 | 2.44 | 1.158 | 1.265 |
| sims, base | 13.04 | 10.94 | 1.04 | 0.91 | +0.15 | 7.67 | 1.10 | 0.23 | 1.095 | 1.427 |
| sims, E2 | 12.55 | 10.33 | 1.11 | 0.95 | +0.16 | 7.68 | 1.11 | 0.24 | 1.129 | 1.345 |

- **The method checks out on the sims.** Their within-game team-specific variance, measured directly per game over
  100 sims, is 28.97 against A + B = 28.84 (base), and 28.16 against 27.81 (E2).
- **Real A + B is known tightly (± 0.12 from 30m).** Measured real is 23.61 ± 0.95. So the real rest is +0.19 ± 0.96 minus
  the real between-game spread, which cannot be negative. With the sims' value (3.08) it is -2.88; a spread
  above about 1.2 makes it negative beyond the interval.

**Where the sims' excess team-specific variance sits** (base minus real, from 30m: +8.43; from 36m: +3.25):

| piece | from 30m | from 36m |
|---|---|---|
| per-possession dispersion (sims' within variance - real's) × sims' E[N] | +2.77 (33%) | +1.35 (41%) |
| more possessions in the sims (18.48 vs 17.69) × real's within variance | +1.03 (12%) | -0.05 (0%) |
| unshared possession count, B (coin-flip imbalance) | +1.63 (19%) | +0.68 (21%) |
| rest: real's within-game pull-back, INFERRED (sims' +0.12 vs real's -2.88) | +3.00 (36%) | +1.27 (39%) |

**Corrections to steps 3c and 3d:**
- **Step 3c's "per-possession outcomes about 35% too variable" is WITHDRAWN.** Measured: 11.5% from 30m, 14.5%
  from 36m. The inference assumed equal between-game spread and independent real possessions; the second
  assumption fails.
- **Step 3d's "E2 removes 4% of it, and the inferred gap is about 26%" is REPLACED.** E2 removes 40% of the measured
  gap of 0.151 (1.459 → 1.398 against real 1.308; the sims sit 11.5% above real).
- **Step 3c's "pace is not the source" stands, with a measured size.** True possessions from 30m: real 17.69,
  sims 18.48 (+4.5%), which is 12% of the excess. From 36m they are equal. Real possessions are 7.3% MORE
  efficient (1.157 vs 1.078); the sims' extra possessions do not make up the difference, so the mean runs 0.56
  per team low.

**What it means (nothing ships from this lane):**
- **The largest single piece is a within-game pull-back** in real games that the sims do not have (inferred,
  36-39%).
  - `score_effect_k` is the existing engine field for exactly this: each shot's make probability scales with
    clip(1 - k × dev, 0.85, 1.15), where dev is the lead now minus the expected lead to date.
  - Step 3b's scan tried only k = 0.002, the NBA proposal, which moves a make probability by about 1% at a 5-point
    deviation. It was inert on the spread.
  - A scan of larger k is a diagnostic with no engine edit, read against this closure (rest and the team-specific
    part). Step 3b already measured that k does not move the tie rate.
  - The pull-back can also be tested directly on the real margins: regress the real late residual (actual minus
    the 36m re-sim mean) on the 30m-36m margin change, or on the deviation from the pregame expectation.
- **Per-possession dispersion (33-41%) is an outcome-mix error:**
  - too many empty and 3-point possessions;
  - too few 1- and 2-point possessions;
  - 24.6-29.5% of real late possessions carry a free throw.
  - E2 closes 40% of it, and its first-half rate is what failed the earlier point-accuracy gate. So a late-weighted
    bonus rate is the refit candidate, together with E1 and the exact-target solve.
- **The unshared possession count (19-21%):** alternation 1.0 (step 3d: -1.84 of the team-specific part from
  30m).

**Next for NCAAB:**
1. **Test the pull-back directly**, real margins only: is the late residual negatively related to the recent run or
   to the deviation from pregame?
2. **Scan `score_effect_k`** (for example 0.005 / 0.01 / 0.02, existing field) with alternation 1.0 against this
   closure.
3. **The mechanisms** (outcome mix: a late bonus rate refit; end-game decisions) need an `engine.py` loan and an E1
   refit.

**Scratch:**
- Scripts, in the session scratchpad: `possprobe.py`, `possreal.py`, `run_possreal.sh`, `possanalyze.py`.
- Outputs: `~/bball_iv/runs/ncaab2026_tieshape/poss_real.jsonl` (4,472 games) and `poss_real_sample.txt`.

## PHASE 2 STEP 3f (NCAAB): the within-game pull-back, measured on real margins alone — at least 30% of the sims' excess from minute 30, at least 18% from minute 36

`[2026-11-09 14:14Z-14:21Z (8:14-8:21 AM CST), lane ncaab-real-pullback, session c2fd17f8, read-only, nice 19; the user's "yes" in the parent session local_8c13723c, relayed]`

**Verdict.**
- **Real late margins pull back within the game, and it is measurable without the sims.**
  - The lower bound needs no assumption: 2.51 ± 0.92 points² (team-specific units) from minute 30, which is 30%
    of the sims' 8.43 excess. From minute 36 it is 0.59 ± 0.42, 18% of 3.25.
  - Step 3e had inferred 3.00 (36%) and 1.27 (39%) by borrowing the sims' between-game spread. From 30m the
    measurement nearly reaches the inferred value; from 36m it sets a lower floor.
- **The direct read is a give-back of recent runs.**
  - From 30m: of each point the margin moves over minutes 30-35, 0.095 ± 0.030 comes back over minutes 35-40,
    beyond what the close, the margin and the pace at minute 30 predict.
  - From 36m: of each point of the 36-38 run, 0.107 ± 0.032 comes back in 38-40.
- **The split-window residual covariance agrees:** -2.24 ± 0.69 (30m) and -0.97 ± 0.30 (36m). If the predictor's
  errors do not anti-correlate across the two parts (both share any miss of team strength), these are lower bounds
  too: at least 2.24 (27%) and at least 0.97 (30%).
- **So most of step 3e's "rest" piece is real pull-back.**
  - From 30m: at least 2.5 of the 3.0 piece. The remainder, at most 0.4, is the sims spreading expected margins
    wider across games than real games do.
  - From 36m: at least 0.59 of the 1.27 piece, and at least 0.97 under the split-window assumption.
- **Side finding: the re-sim's own expected late margin change is spread too wide across games.**
  - Real margin change regressed on the re-sim's per-game mean gives a slope of 0.68 ± 0.22 from 30m and
    0.38 ± 0.29 from 36m (535 replay games).
  - The re-sim mean predicts real late margins less well than a two-variable line-plus-margin regression: R² 0.048
    against 0.094 from 30m, and -0.024 against 0.012 from 36m.

**Pre-registered hypothesis PULL-BACK (lane block `d01ca8283`, before any fit): every clause HOLDS; the
falsification test did not fire.**

| clause | predicted | measured | |
|---|---|---|---|
| p_lb from 30m | at least 1.0 (central 1-3) | 2.51 ± 0.92 | holds |
| p_lb from 36m | at least 0.4 (central 0.5-1.3) | 0.59 ± 0.42 | holds |
| split-window residual Cov, 95% interval below 0 | negative | -2.24 ± 0.69 / -0.97 ± 0.30 | holds |
| run coefficient (later change on the earlier change, given pre-window information) | negative | -0.095 ± 0.030 / -0.107 ± 0.032 | holds |

**Method.**
- **Data:** the 4,472 pool games. 4,439 have a pregame close in their corpus record (the harness's `_close`);
  33 do not.
- **Scores:** regulation scores at minutes 30, 35, 36, 38 and 40 from the play-by-play. Margins agree with step 3b's
  `real.jsonl` in every game.
- **Inputs reconcile with steps 3c and 3e on these 4,439 games:**
  - Var(dM)/2 is 23.60 / 9.81 (step 3c: 23.61 / 9.79);
  - A + B is 23.41 / 10.00 (step 3e: 23.42 / 10.00).
- **The bound:**
  - Within-game noise has mean zero given anything known before the window. So for any predictor f of that
    information, Var(dM - f) = within + Var(f's error), which is at least the within variance.
  - Hence p_lb = (A + B) - Var(dM - f)/2 is at most the true pull-back.
  - A + B is step 3e's independent-possession prediction, built from real possessions only.
  - f is OLS, cross-fitted over 2 random folds by game, so no in-sample fit flatters it.
- **Features:**
  - "line + margin": the close's home margin and the margin at the checkpoint.
  - The full set adds: the close's total; scoring pace so far against the close (points minus the total × the
    elapsed share); the margin's deviation from the line to date; and the margin beyond 11 and beyond 20 points.
- **Split window:** 30-35m against 35-40m, and 36-38m against 38-40m. Both parts are residualised on the full
  pre-window set, cross-fitted.
- **Intervals:** 1.96 × a bootstrap SE over games. A + B and the residual variance are drawn together; residuals
  are fixed after the cross-fit.

**The bound by predictor:**

| predictor f, cross-fitted | from 30m: V_f = Var(dM - f)/2 | p_lb | share of the sims' excess | R² | from 36m: V_f | p_lb | share | R² |
|---|---|---|---|---|---|---|---|---|
| none | 23.60 | -0.19 ± 1.02 | -2% | 0 | 9.81 | +0.19 ± 0.44 | +6% | 0 |
| line + margin | 21.02 | +2.39 ± 0.93 | +28% | 0.109 | 9.42 | +0.58 ± 0.42 | +18% | 0.039 |
| full pre-window set | **20.90** | **+2.51 ± 0.92** | **+30%** | 0.114 | **9.41** | **+0.59 ± 0.42** | **+18%** | 0.041 |

- **The replay's 535 games**, where the re-sim's per-game mean margin change (a point projection made at the
  checkpoint) is a further predictor:

  | predictor | from 30m: p_lb | R² | from 36m: p_lb | R² |
  |---|---|---|---|---|
  | the re-sim mean, as is | +1.88 ± 2.56 | 0.048 | +0.48 ± 1.25 | -0.024 |
  | full set only | +2.93 ± 2.37 | 0.094 | +0.81 ± 1.15 | 0.012 |
  | full set + the re-sim mean | +3.01 ± 2.39 | 0.098 | +0.88 ± 1.14 | 0.019 |

  - The re-sim mean adds almost nothing beyond the line and the state.
- **Raw split-window covariance**, before residualising: -0.89 (30m) and -0.80 (36m). Residualising removes the
  shared team-strength part, which is positive, so the residual covariance is more negative.

**Where the sims' excess team-specific variance now sits** (step 3e's table, with the inferred piece replaced by
measured bounds):

| piece | from 30m | from 36m |
|---|---|---|
| per-possession dispersion | +2.77 (33%) | +1.35 (41%) |
| more possessions in the sims | +1.03 (12%) | -0.05 (0%) |
| unshared possession count (coin-flip imbalance) | +1.63 (19%) | +0.68 (21%) |
| **real within-game pull-back, MEASURED lower bound** | **at least +2.51 (30%)** | **at least +0.59 (18%); at least +0.97 (30%) by the split window** |
| the sims' own structure (no pull-back; noise level) | +0.12 | +0.15 |
| the sims' expected margins spread wider across games than real (what is left) | at most +0.38 (5%) | at most +0.51 (16%); at most +0.13 by the split window |

**What it means (nothing ships from this lane):**
- **The engine needs margin reversion inside the game.** The give-back is about 0.10 of each point of a recent
  run, beyond the state at the checkpoint.
- **`score_effect_k` is the existing field for it.** It keys on the lead now minus the expected lead to date, and a
  run moves exactly that.
  - **TESTED in step 3g below (2026-11-09):** k 0.005 with alternation 1.0 halves the late margin-spread gap and passes the harness gate; k 0.01 adds nothing and costs win probability.
  - Rough size (INFERRED, back-of-envelope): the give-back over about 9 possessions a team, at about 1.1 points a
    possession, means 2 × 9 × 1.1 × k ≈ 0.095 per point of deviation. That gives k ≈ 0.005, rather more as the
    deviation decays.
  - Step 3b scanned only k = 0.002, the NBA proposal: 2-3× smaller.
- **The calibration slope (0.68 / 0.38) says the re-sim also over-reacts across games** in its expected late margin
  change. Pull-back inside the sims would shrink that spread as well, so read the slope again after a k scan.

**Next for NCAAB:**
1. **Scan `score_effect_k`** (0.005 and 0.01; existing field, no engine edit), with `possession_alternation` 1.0.
   Read against:
   - step 3e's closure;
   - this step's run coefficients (targets -0.095 / -0.107, measured the same way on the sims' paths);
   - the calibration slope.
2. **Then the mechanisms**: a late-weighted bonus refit for the outcome mix, and step 3b's end-game decisions. Each
   needs an `engine.py` loan and an E1 refit.

**Scratch:**
- Scripts, in the session scratchpad: `pullreal.py`, `run_pullreal.sh`, `pullanalyze.py`, `pullslope.py`.
- Output: `~/bball_iv/runs/ncaab2026_tieshape/pull_real.jsonl` (4,439 games).

## PHASE 2 STEP 3g (NCAAB): `score_effect_k` with strict alternation — k 0.005 halves the late margin-spread gap and passes the harness gate; k 0.01 adds nothing and costs win probability

`[2026-11-09 15:19Z-18:46Z (9:19 AM-12:46 PM CST), lane ncaab-score-effect-scan, session c2fd17f8, read-only, nice 19; the user's "yes" in the parent session local_8c13723c, relayed; jobs detached on the user's "Yes, detach them" here]`

**Verdict.**
- **k 0.005 with `possession_alternation` 1.0 (SE5_ALT) halves the late margin-spread gap with no point-accuracy
  cost.**
  - From 30m: SD(margin change) goes from 1.172× real to 1.090×. The team-specific variance drops 13.5%, about
    half of the gap to real.
  - From 36m: 1.159× to 1.095× (-10.8%).
  - The harness gate passes. Full and h2 totals tie production at every checkpoint, and the margin ties or improves.
    It improves at the tip: -0.24 ± 0.22.
  - Unregistered extra read: CRPS of the regulation margin improves -0.110 ± 0.099 from 30m.
- **k 0.01 (SE10_ALT) adds no further narrowing** (team-specific -14.0% vs -13.5%) and costs elsewhere:
  - win-probability Brier +0.0043 ± 0.0037 from 36m;
  - margin |err| +0.28 ± 0.21 at 10m against SE5_ALT.
- **Why the larger k stops paying.** The field reverts toward the PREGAME target: dev = lead − target margin ×
  elapsed share. That does produce within-game pull-back:
  - own pull-back 3.55 (k 0.005) and 5.92 (k 0.01) from 30m, against real games' measured floor of 2.51;
  - run slope -0.075 / -0.128, against real's ≤ -0.095.

  But it also makes each game's expected late change depend on where the game stands against the line. That widens
  the across-game spread of expected margins:
  - the team-specific between-game part goes 3.12 → 4.33 → 6.53, against real's ≥ 2.70;
  - step 3f's calibration slope (0.68) already said that spread is too wide.

  Real games give back RECENT runs (step 3f). So a run-keyed reversion is the engine change this points to. It is a
  hypothesis and needs an `engine.py` loan.
- **What is still open.**
  - Per-possession dispersion is untouched: 1.46 vs real 1.30.
  - The shared covariance rises but stays short: 0.35 → 2.87 against real 6.82.
  - Late totals stay narrow: Var(total) 67.6 vs 74.5 from 30m, 27.8 vs 37.6 from 36m.
  - The tie rate rises only +0.28 points (2.71% → 2.99%), against real's 5.77%.

**Pre-registered hypothesis SCORE-EFFECT (lane block `09ca1af93`, before any arm ran): every clause HOLDS; the
falsification test did not fire.**

| clause | predicted | measured | |
|---|---|---|---|
| (a) reachable | fields named, histograms differ | 540/540 games per arm; 1,080/1,080 game-checkpoints | holds |
| (b) SE5_ALT run slope from 30m | -0.05 to -0.15 | -0.075 ± 0.009 | holds |
| (b) SE5_ALT team-specific vs base | -8% to -16% | -13.5% | holds |
| (b) SE5_ALT SD(margin change) / real | 1.06-1.13 | 1.090 (30m), 1.095 (36m) | holds |
| (c) SE10_ALT run slope from 30m | -0.10 to -0.30 | -0.128 ± 0.010 | holds |
| (c) SE10_ALT team-specific vs base | -12% to -25% | -14.0% | holds |
| (d) mean window points per team | moves at most 0.2 | +0.084 / +0.082 (30m) | holds |
| (d) regulation tie rate | moves at most 1 point | +0.28 / +0.53 points | holds |
| (e) SE5_ALT gate | totals and margin improve or tie everywhere | ties everywhere; margin -0.24 ± 0.22 at the tip | holds |
| (e) SE10_ALT margin at 30m / 38m | improves or ties | +0.06 ± 0.31 / -0.00 ± 0.10 | holds |

**Setup.**
- **Production as loaded now.** live-odds-worker's three switches (field names only). The base carries 7
  mechanism fields, including #768's `blowout_margin`, `blowout_q4_margin` and `solver_endgame_pts_per_team`
  (loaded 05:13Z today).
- **BASE vs step 3c's old base (pre-#768):** team-specific +0.37, Cov -0.37, Var(margin change) +0.75 from 30m.
  This is within noise, so steps 3c-3f's sim tables still describe production.
- **Code.**
  - `~/bball_iv/code5`: a clean export of `09ca1af93`, used for the gate.
  - `~/bball_iv/code6`: code5 plus the RNG-neutral possession markers, used for the replay. Both are scratch.
- **Replay:** 540 games, the same seeds, checkpoints 30m and 36m, 100 sims, four arms (BASE, ALT1, SE5_ALT,
  SE10_ALT). Window points reconcile in 432,000 / 432,000 sims.
- **Run give-back:** within-game slope of the change after the split (35m / 38m) on the change before it, demeaned
  per game over its 100 sims. Real (step 3f) is a cross-game regression with pre-window controls, an upper bound on
  real's within-game slope.
- **Gate:** the #765 harness: 400 games, seed 20261107, `resim` (production) vs `resim_mech` (the arm).
  - Read with `scripts/ncaab_blowout_harness_read.py`.
  - 399 of 400 scored (1 `pbp_final_mismatch`); 285 regular season.
  - Pairing check: production `resim` is identical across the two runs (max difference 0.0000 over 3,696 rows). It
    differs from 11-08's #768 runs (5.73), as it should: production changed at 05:13Z.
- **Interruptions.** The first launch, at about 15:21Z, died with two session restarts. The relaunch at 17:07Z ran
  as `systemd-run --user` units and resumed from 253 replay rows and 30 games per gate. The seeds are per game, so a
  resumed game is the same game.

**Replay, from minute 30** (per team, window; real = the 4,472-game pool):

| | real | BASE | ALT1 | SE5_ALT | SE10_ALT |
|---|---|---|---|---|---|
| team-specific (Var - Cov) | 23.61 | 32.42 | 30.30 | **28.04** | 27.87 |
| Cov(home, away) | 6.82 | 0.35 | 1.77 | 2.87 | 3.00 |
| Var(margin change) | 47.23 | 64.83 | 60.59 | 56.07 | 55.74 |
| SD(margin change), × real | 1 | 1.172 | 1.133 | **1.090** | 1.086 |
| Var(window total) | 74.52 | 66.23 | 67.68 | 67.56 | 67.75 |
| run slope (35-40m on 30-35m) | ≤ -0.095 ± 0.030 | 0.000 | -0.000 | **-0.075** | -0.128 |
| within-game Cov(d1, d2) | ≤ -2.24 | 0.00 | -0.00 | -1.81 | -2.92 |
| own pull-back = A + B - within-game team-specific | ≥ 2.51 | -0.40 | -0.18 | 3.55 | 5.92 |
| between-game team-specific (measured - within) | ≥ 2.70 | 3.12 | 3.03 | 4.33 | 6.53 |
| regulation tie % | 5.77 | 2.71 | 2.74 | 2.99 | 3.24 |
| points per team | 20.47 | 20.00 | 19.98 | 20.08 | 20.08 |
| per-possession variance | 1.30 | 1.45 | 1.45 | 1.46 | 1.46 |

**From minute 36:**

| | real | BASE | ALT1 | SE5_ALT | SE10_ALT |
|---|---|---|---|---|---|
| team-specific | 9.79 | 13.16 | 12.21 | **11.74** | 11.76 |
| Cov(home, away) | 4.51 | 0.21 | 0.72 | 1.07 | 1.03 |
| SD(margin change), × real | 1 | 1.159 | 1.117 | **1.095** | 1.096 |
| Var(window total) | 37.62 | 27.16 | 27.30 | 27.78 | 27.63 |
| run slope (38-40m on 36-38m) | ≤ -0.107 ± 0.032 | -0.003 | -0.011 | -0.049 | -0.070 |
| own pull-back | ≥ 0.59 (≥ 0.97 split window) | -0.21 | -0.06 | 0.70 | 1.14 |
| between-game team-specific | ≥ 0.38 | 0.94 | 0.87 | 1.12 | 1.54 |
| regulation tie % | 5.77 | 3.46 | 3.56 | 3.78 | 3.90 |

- **Paired, arm - BASE, team-specific:**
  - ALT1: -2.12 ± 0.53 (30m), -0.95 ± 0.20 (36m).
  - SE5_ALT: -4.38 ± 0.62 and -1.42 ± 0.20.
  - SE10_ALT: -4.55 ± 0.87 and -1.40 ± 0.24.
- **From 36m both k fall short of real's run give-back** (-0.049 / -0.070 against ≤ -0.107). Their own pull-back
  (0.70 / 1.14) brackets the real floor.

**Harness gate**, regular season, 285 games. |err| arm - production, ± 1.96 SE; negative = nearer the final:

| checkpoint | SE5_ALT full total | h2 total | margin | SE10_ALT full total | h2 total | margin |
|---|---|---|---|---|---|---|
| 0m (tip) | +0.10 ± 0.24 | -0.03 ± 0.18 | **-0.24 ± 0.22** | +0.07 ± 0.25 | +0.06 ± 0.20 | -0.20 ± 0.20 |
| 10m | -0.01 ± 0.19 | +0.01 ± 0.17 | -0.06 ± 0.34 | +0.01 ± 0.22 | -0.02 ± 0.18 | +0.23 ± 0.47 |
| 20m | +0.08 ± 0.17 | +0.08 ± 0.17 | -0.06 ± 0.34 | -0.09 ± 0.18 | -0.09 ± 0.18 | +0.15 ± 0.48 |
| 30m | -0.05 ± 0.14 | -0.05 ± 0.14 | -0.05 ± 0.22 | -0.01 ± 0.14 | -0.01 ± 0.14 | +0.06 ± 0.31 |
| 38m | -0.04 ± 0.08 | -0.04 ± 0.08 | -0.05 ± 0.07 | +0.01 ± 0.09 | +0.01 ± 0.09 | -0.00 ± 0.10 |

- **The totals' MEAN shifts up** (SE5_ALT / SE10_ALT): +0.57 / +1.03 at the tip, +0.48 / +0.76 at 10m, +0.19 /
  +0.26 at 30m.
  - In-game this works against production's low bias (-1.86 at 10m, -3.30 at 30m).
  - At the tip it moves production's +0.17 to +0.74 / +1.19. |err| still ties.
  - #768 re-centred a +0.39 tip shift before its load, which is the §4.4 re-fit of the engine standard.
- **SE10_ALT against SE5_ALT directly:** margin |err| +0.28 ± 0.21 at 10m, +0.21 ± 0.22 at 20m.

**Probabilistic read** (added after the pre-registration; the harness has no distribution to score). Each arm's
100-sim regulation-margin distribution against the real regulation margin, 540 games, paired arm - BASE; negative
is better:

| | CRPS 30m | CRPS 36m | log score 30m | Brier home ahead 30m | Brier home ahead 36m |
|---|---|---|---|---|---|
| ALT1 | -0.038 ± 0.054 | -0.024 ± 0.035 | -0.028 ± 0.152 | +0.0008 ± 0.0032 | -0.0004 ± 0.0028 |
| SE5_ALT | **-0.110 ± 0.099** | -0.044 ± 0.052 | -0.051 ± 0.160 | +0.0020 ± 0.0039 | +0.0016 ± 0.0030 |
| SE10_ALT | -0.045 ± 0.142 | -0.019 ± 0.071 | -0.034 ± 0.167 | +0.0061 ± 0.0060 | **+0.0043 ± 0.0037** |

- BASE CRPS is 3.844 (30m) and 2.528 (36m), so SE5_ALT's gain from 30m is 2.8%.
- Win-probability Brier moves the wrong way for both k, beyond the interval only for k 0.01 from 36m. That fits a
  reversion toward the pregame target.

**What it means:**
- **SE5_ALT is the first change in this series that both narrows the late margin and passes the gate.**
  - **PREPARED in step 3h below (2026-11-09):** load RC46 (adds `solver_endgame_pts_per_team` 0.46); its tip shift is -0.02 and it keeps the gain. Not loaded.
  - Candidate load: live-odds-worker's `SYNDICATE_NCAAB_LIVE_MECHANISMS` + `"score_effect_k": 0.005,
    "possession_alternation": 1.0`.
  - It is a production change and the user's decision.
  - Before loading, decide whether to re-centre its +0.57 tip total first (#768's precedent).
  - Read its live effect on the next slates.
- **k beyond 0.005 is not the way to close the rest.** The next engine step is a run-keyed reversion (`engine.py`
  loan), measured against step 3f's run coefficients and this step's between-game spread.
- **Still open:** the outcome mix (per-possession dispersion 1.46 vs 1.30; a late-weighted bonus refit), the late
  shared variance and the tie rate.

**Scratch:**
- Scripts, in the session scratchpad and in WSL `~/bball_iv/k_scan/`: `spreadk.py`, `kanalyze.py`, `kprob.py`,
  `run_gate_se05.sh`, `run_gate_se10.sh`, `make_code6.py`.
- Runs:
  - `~/bball_iv/runs/ncaab2026_tieshape/spread_k.jsonl` (2,160 game-arm rows);
  - `~/bball_iv/runs/ncaab2026_se05_alt/` and `ncaab2026_se10_alt/` (`results.jsonl`, `report.md`).

## PHASE 2 STEP 3h (NCAAB): the load, PREPARED — k 0.005 + strict alternation with the tip re-centred (`solver_endgame_pts_per_team` 0.2 -> 0.46); NOT loaded

`[2026-11-09 18:55Z-20:25Z (12:55-2:25 PM CST), lane ncaab-score-effect-load, session c2fd17f8; user "Yes, prepare it" here, and "yes proceed" in the parent session (relayed): PREPARE ONLY. The env edit and the drained down/up need the user's explicit yes]`

**Verdict.**
- **Load the RE-CENTRED variant, RC46:** `score_effect_k` 0.005 + `possession_alternation` 1.0 +
  `solver_endgame_pts_per_team` 0.46.
- **It keeps all of step 3g's distribution gain and removes the mean drift:**

  | | plain k 0.005 | RC46 |
  |---|---|---|
  | SD(margin change) / real from 30m (base 1.172) | 1.090 | 1.092 |
  | SD(margin change) / real from 36m (base 1.159) | 1.095 | 1.095 |
  | team-specific variance vs base | -13.5% | -13.2% |
  | mean window points per team | +0.084 | -0.003 |
  | CRPS from 30m | -0.110 ± 0.099 | -0.121 ± 0.096 |
  | win-probability Brier from 30m | +0.0020 | +0.0002 |

- **The harness gate passes and the tip is re-centred.** Totals and margin tie production at every checkpoint. The
  tip total shift is -0.02 ± 0.11, against plain's +0.57.
- **The re-centre costs nothing measurable in-game.** Against plain, |err| ties everywhere: +0.07 ± 0.10 at 30m,
  -0.07 ± 0.17 at 10m.
  - #768 found that 0.6 did cost in-game. 0.46 is a smaller step, and here the score effect's own upward shift
    absorbs it.
- **Why re-centre at all.** The same key feeds the men's PREGAME sims, and they price NCAAB full-game totals.
  - `build_engine_inputs`, `ncaab/live_resim.py:360`, puts the mechanisms into every college engine call.
  - #768's load triggered a one-time men's pregame re-sim (`COLLEGE_PREGAME_SIM_LAUNCHED pregame_games=60`).
  - `state_basketball.md [college-basketball-boards]`: "Totals are served from the sim".
  - So plain k 0.005 would have moved published pregame totals by +0.57.

**The re-centre, measured on the harness the way #768 did its +0.39:**
- **Value.** #768's probe measured the tip falling about 2.2 per point of the field, so offsetting +0.57 takes
  about +0.26: 0.2 -> 0.46.
- **Run `ncaab2026_se05_rc46`:**
  - the same 400 games and seed (20261107) as the plain run, from clean code `09ca1af93`;
  - `resim` (production) vs `resim_mech` = RC46;
  - 399 of 400 scored (1 `pbp_final_mismatch`), 285 regular season;
  - 3,239 s as a `systemd-run --user` unit, done 20:11:49Z;
  - production `resim` identical to the plain run's (max difference 0.0000 over 3,696 rows).
- **Full-game total, all 285 games.** |err| RC46 - production ± 1.96 SE, with the mean shift beside it:

| checkpoint | full total |err| | shift | h2 total |err| | margin |err| |
|---|---|---|---|---|
| 0m (tip) | +0.06 ± 0.22 | **-0.02 ± 0.11** (plain +0.57) | +0.12 ± 0.18 | -0.10 ± 0.21 |
| 10m | -0.08 ± 0.19 | +0.09 ± 0.10 | -0.09 ± 0.18 | -0.07 ± 0.33 |
| 20m | +0.08 ± 0.18 | +0.03 ± 0.09 | +0.08 ± 0.18 | -0.04 ± 0.35 |
| 30m | +0.02 ± 0.13 | +0.01 ± 0.07 | +0.02 ± 0.13 | -0.09 ± 0.21 |
| 38m | -0.07 ± 0.07 | +0.06 ± 0.04 | -0.07 ± 0.07 | -0.06 ± 0.07 |

- **Replay of RC46** (`spread_k_rc.jsonl`, 540 games × 30m / 36m × 100 sims; 10 min as unit `kscan-replay-rc`):
  - fields named in 540/540 games;
  - histograms differ from the base in 1,080/1,080 game-checkpoints;
  - window points reconcile 108,000 / 108,000.
  - Paired RC46 - base: team-specific -4.28 ± 0.63 (30m) and -1.41 ± 0.21 (36m); run slope -0.067 and -0.045;
    tie rate +0.24 points; CRPS -0.055 ± 0.051 from 36m.

**The exact change (not made):**
- **File and key:** `~/syndicate-prod/local_production.env`, key `LIVE_ODDS_WORKER__SYNDICATE_NCAAB_LIVE_MECHANISMS`.
  There is 1 line, unquoted, at line 109 of 202 on 11-09.
- **From** #768's 7 fields: `{"endgame_foul_window_s": 120, "endgame_foul_max_deficit": 10,
  "endgame_foul_p_by_deficit": [0.25, 0.5, 0.6], "endgame_extend_possessions": true, "blowout_q4_margin": 999,
  "blowout_margin": 999, "solver_endgame_pts_per_team": 0.2}`.
- **To** 9 keys: `{"endgame_foul_window_s": 120, "endgame_foul_max_deficit": 10, "endgame_foul_p_by_deficit": [0.25,
  0.5, 0.6], "endgame_extend_possessions": true, "blowout_q4_margin": 999, "blowout_margin": 999,
  "solver_endgame_pts_per_team": 0.46, "score_effect_k": 0.005, "possession_alternation": 1.0}`.
  - Men's only; wncaab untouched.
- **Tool:** `~/bball_iv/k_scan/env_load_k.py --variant rc46`.
  - It refuses unless there is exactly one key line and its value equals the 7 fields.
  - It backs up to `local_production.env.bak-ncaab-score-effect-<UTC>`.
  - It keeps the old value on a comment line and keeps the quoting.
- **Dry run 11-09, after 19:17Z:** sha8 `4a316bd1` -> `7a94249e`, 202 -> 203 lines, PASS.
- **Read-only checks:**
  - The fleet's own code at the time (HEAD `564f8dbde`) parses the new value to 9 keys, with `score_effect_k`
    0.005, `possession_alternation` 1.0 and `solver_endgame_pts_per_team` 0.46 on the `EventSimConfig`.
  - live-odds-worker's live value equalled #768's 7 fields just before 19:17Z (boolean check, pid 374416).

**Runbook for the load** (#768's 05:13:12Z deploys.md entry is the template; memory
`project_fleet_env_change_recipe`). Only after the user's explicit yes:
1. **Preconditions:**
   - lane `ncaab-blowout-off-live-read` has recorded #768's live reading in deploys.md (a verdict, not
     INSUFFICIENT), so the two changes are not confounded;
   - between slates: `check_deploy_safety` QUIET, no live games.
2. **Claims:** web, refresh-worker and live-odds-worker under holder `ncaab-score-effect-load`, `--ttl 7200`. Gate
   on the acquire exit code; never grep it.
3. **Drain:** `--drain --drain-owner ncaab-score-effect-load`.
4. **Baseline:** live-odds-worker `/proc/<pid>/environ` parses to `ncaab_live_mechanisms_keys=7`. Record the time.
5. **Fleet preflights from a worktree at origin/main:** `--target fleet --target-commit <fleet HEAD> --reinject-env`.
   - live-odds-worker: `--expect ncaab_live_mechanisms_keys=9 --baseline ncaab_live_mechanisms_keys=7
     --baseline-read-at <UTC>`.
   - web and refresh-worker: `--no-expectation "env unchanged for this role; full down/up for live-odds-worker's
     env"`.
   - Poll all three until CLEAR together.
6. **The change:** marker; `env_load_k.py --variant rc46` (not dry-run); `local_production.py down`; then
   `Start-ScheduledTask SyndicateLocalProduction`.
7. **Verify (config):**
   - the new live-odds-worker environ parses to 9 keys, with `score_effect_k=0.005`,
     `possession_alternation=1.0` and `solver_endgame_pts_per_team=0.46`;
   - healthz 200 and 0 Tracebacks in all three role logs;
   - `NCAAB_LIVE_RESIM_TICK` clean;
   - `COLLEGE_PREGAME_SIM_LAUNCHED`: the one-time men's pregame re-sim, since `inputs_key` carries the mechanism
     names.
8. **Close:** clear the marker; `--undrain`; release the claims with `--token`; write the deploys.md entry
   (measurement, owed reading, revert).

**Expected readings (pre-stated):**
- **Config:** 9 keys (baseline 7).
- **Reachability:** on the first live NCAAB games, the lens `inputs.mechanisms` names `score_effect_k` and
  `possession_alternation`.
- **Effect.** On the first post-load slate's completed games, re-sim states at minutes 30 and 36 on the old
  7-field config and on the new one, paired; the replay's method on 2026-27 games:
  - served / old SD of the regulation margin about 0.93 from 30m and about 0.94 from 36m;
  - FALSIFIED if outside 0.88-0.98;
  - mean total shift +0.0 to +0.1 in-game, about 0 at the tip.
- **Live totals:** `ncaab_live_totals_bias.py`, split at the load: model − line moves by less than ±0.2. RC46's
  in-game shifts are +0.01 to +0.09.

**Revert:** `env_load_k.py --revert <backup>`, then the same drained down/up.

**Not decided here:** WNCAAB, which runs no live mechanisms (`live_mechanisms_from_env` applies to the men's league
only).

**Scratch:**
- Scripts in WSL `~/bball_iv/k_scan/`: `env_load_k.py`, `spreadk_rc.py`, `run_gate_se05rc46.sh`, plus the session
  scratchpad's `kanalyze_rc.py` and `kprob_rc.py`.
- Runs: `~/bball_iv/runs/ncaab2026_se05_rc46/`, `ncaab2026_tieshape/spread_k_rc.jsonl`.
