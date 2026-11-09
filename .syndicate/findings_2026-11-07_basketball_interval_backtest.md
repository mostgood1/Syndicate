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
1. **Test the existing default-off fields** with no engine edit, on the same games, seeds and checkpoints. Read
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
