# NFL game lines + player props backtest (as-of) — 2026-10-02

Lane `nfl-lines-props-backtest` (session 05b01a84). Measurement only: no deploy, no board change.
Harness `scripts/backtest_nfl_lines_props.py` (commit `b2f0ab3b`), same method and table shape as the
NHL props backtest (lane `nhl-player-props-projection`) and the NCAAF twin (lane `ncaaf-lines-props-backtest`).

**Status: PROPS COMPLETE. GAME LINES RUNNING** (864 games simulated as-of; section 2 is filled in when it lands).

## 0. Verdict up front

**No NFL player-prop market beats BOTH the player's own as-of average AND the de-vigged book. Not one,
in any season.** Every continuous market except interceptions is significantly WORSE than the book on
Brier and log-loss in the pooled 2023-2025 sample. Interceptions shows NO DIFFERENCE, which is not a win.
The lane's hypothesis holds for props. MEASURED_MARKETS-style gating: **nothing earns a probability or
edge on the board.** That matches what `measured_market_skill.py` already says (8 NFL prop entries,
all `VERDICT_LOSES`). This run REPLICATES it on the SHIPPED model, with game-clustered CIs, adds
log-loss, and covers 2023 + 2025 + 2026.

Anytime TD is **not** a candidate. Its shrinkage beats the player's raw average by a wide margin. It
still loses to the book's YES price **before** that price is de-vigged, in every historical season.

## 1. What the harness grades, and why the numbers are production's

- **Game lines:** `generate_smartsim2_nfl_projections.build_projection` is CALLED, with 300 seeds, over
  plays before the game's week, under the fleet refresh-worker's NFL env as READ 2026-10-02 from
  `/proc/<pid>/environ` (keys only):
  - `SYNDICATE_NFL_PPG_RATINGS=1`
  - `SYNDICATE_FOOTBALL_SEGMENT_DISTRIBUTIONS=1`
  - every other NFL model knob ABSENT, so code defaults apply: K=4 prior blend, level shrink 0.3, no
    diff correction, no drive priors, no blowout damping.

  The harness refuses to run if any other knob is set.

  **Fidelity: it reproduces production's own `smartsim2_projections_2026_wk4.csv` (written by the fleet
  2026-10-01 21:54Z) EXACTLY.** 16/16 games, every numeric field diff 0.0 (scores, margin, total, both
  sds, win rate), `rating_source` identical. Fleet code `5566d4ba` and `origin/main` carry no diff in
  the NFL model files.
- **Props:** the computed branch of `nfl_props_rows_for_week` is CALLED:
  `resolve_player_id_with_prior` → team check → `player_rate_with_prior` / `anytime_td_rate_with_prior`
  → `nfl_game_context_multiplier` → `_nfl_prop_model_probability`.

  **Selfcheck:** the harness writes one week in the production CSV contract and production returns
  the same probability for every (player, market, line). 0 mismatches over 8,976 rows:
  - 2024 wk5: 4,414 rows
  - 2025 wk12: 2,649 rows
  - 2026 wk2: 1,913 rows
- **Note on `scripts/backtest_nfl_props.py` (claimed by OPEN lane `layer2-triad-alignment`, NOT edited
  here):** its `_rate_from_log` does not apply production's zero-week imputation (`player_rate`,
  `SYNDICATE_NFL_PROP_ZERO_GAMES` absent = ON). It no longer grades the served estimator. This harness
  calls `player_rate` directly. Owed to that lane, not fixed here.

### A defect in my own first run, recorded because the selfcheck did NOT catch it

The first props run had the game-context multiplier at **exactly 1.0 on 100% of rows**. The cause was
the scratch root:

- It had no `upcoming_recs_*.csv`.
- `default_nfl_source_root()` probes for that unrelated file (the `#441` family) and fell through to a
  non-existent `source_artifacts/`.
- So `game_context()` read no schedule.

The production-equivalence selfcheck **still passed**, because harness and production code read the
same mis-resolved root. **An equivalence check proves the CODE matches. It says nothing about whether
the ENVIRONMENT matches.**

On the fleet, `nfl_source/` carries the `upcoming_recs` files, so production's multiplier IS live.

The harness now refuses to run when `game_context()` resolves nothing, and the reported numbers are
from the corrected run. Context is now non-1.0 on ~87% of historical rows. The rest:
- rushing_attempts and anytime_td sit at (0, 0) BY DESIGN.
- The 2026 week-2 rows are 1.0 by design: a player needs 2 prior weeks.

## 2. Game lines — PENDING (run in progress)

## 3. Coverage: per family, and the intersection each result rests on

| season | final scores (games/wks) | pbp (games/wks) | nflverse close, two-sided ML/spread/total | prop quotes (games/wks) | PROPS INTERSECTION |
|---|---|---|---|---|---|
| 2023 | 272 / 18 | 272 / 18 | 272 / 272 / 272 | 131 / 17 (wk9 absent; ~half the games per week) | **131 games, 17 wks** |
| 2024 | 272 / 18 | 272 / 18 | 272 / 272 / 272 | 235 / 18 | **235 games, 18 wks** |
| 2025 | 272 / 18 | 272 / 18 | 272 / 272 / 272 | 226 / 18 | **226 games, 18 wks** |
| 2026 | 48 / wks 1-3 | 48 / wks 1-3 | 48 / 48 / 48 | **16 / wk 2 only** | **16 games, 1 wk** |

Substrate, per family (substrate-rule):

- **render / fleet (production):**
  - `pbp_2026.csv` (written 2026-10-01 20:46Z)
  - `schedules_games.csv` (21:00Z)
  - `schedule_2026.csv`
  - `smartsim2_projections_2026_wk4.csv`
  - `upcoming_recs_*` (root marker only)

  All were copied 2026-10-02 ~22:39Z with sha256 in `C:\tmp\nflbt\root\nfl_source\FLEET_PROVENANCE.txt`.
- **checkout (untracked mirror in the primary tree):**
  - pbp 2022-2025 (nflverse, re-derivable).
  - prop quotes 2023-2025: `tracking/book_quotes/<s>_wk<N>.jsonl`, OddsAPI HISTORICAL snapshots at
    kickoff-10min, per `backfill_nfl_historical_props.py --offset-minutes 10`. An immutable external
    archive, so the checkout copy is the archive.
- **2026 in-season prop odds are the weakest family:**
  - Render's disk was never exported after the 2026-09-30 billing suspension.
  - The fleet was seeded from git, where every 2026 props CSV is a stub (fleet `wk1` = 6 bytes).
  - The ONLY surviving 2026 capture is the primary tree's untracked `oddsapi_player_props_2026_wk1.csv`
    (mtime 09-29). **It holds WEEK 2** (games 09-18..09-22Z), so it is the NFL-week-self-pins-to-1
    defect in a file name. Its capture time is not recorded; it is treated as pregame because every
    Sunday game is present.
  - **Weeks 1 and 3 of 2026 have no surviving prop prices anywhere.**
- 2022 is excluded:
  - Props: the OddsAPI historical archive starts 2023-05.
  - Game lines: production's K=4 prior-season blend touches EVERY 2022 week, so 2022 needs
    `pbp_2021`. It was fetched 2026-10-02 ~23:15Z on the user's instruction, with the production
    fetcher `scripts/fetch_nfl_pbp.py --season 2021 --only-season` (nflverse release, 47,651 REG
    plays), into the scratch root only. **2022 IS included for game lines.** It is still excluded for
    props (no prices).

## 4. Player props — results

Population: quoted (player, market, game) rows where the player resolves, passes production's team
check, has an as-of rate, and appears in the game's pbp.

Drops, counted (all seasons):
| reason | rows |
|---|---|
| player unresolved (mostly anytime-TD quotes on defenders and others absent from pbp; production refuses them too) | 11,952 |
| no pbp line for the player in the game (void: DNP is indistinguishable from played-and-zero in pbp) | 3,554 |
| player on the wrong team (refused) | 1,552 |
| no model rate | 1,186 |
| player team unknown (refused) | 912 |
| one-sided rows excluded | 849 |

Resolved: 32,038 of 51,194 player-market-games.

Book probability = proportional de-vig of ONE book's over/under. Rows are per book. CIs are 95%,
game-clustered bootstrap (1,000 reps).

### 4a. Historical 2023-2025 pooled (593 games, 53 weeks)

Probability vs the de-vigged book (positive dBrier = model worse):

| market | rows | games | Brier model | Brier book | dBrier model−book [CI] | dLogLoss model−book [CI] | EV-bet ROI [CI] | vs book |
|---|---|---|---|---|---|---|---|---|
| passing_yards | 13,492 | 583 | 0.2754 | 0.2396 | +0.0358 [+0.0270, +0.0465] | +0.1350 [+0.0976, +0.1785] | −12.6% [−18.3, −6.8] | WORSE |
| passing_attempts | 6,798 | 577 | 0.2793 | 0.2499 | +0.0295 [+0.0192, +0.0399] | +0.1017 [+0.0673, +0.1390] | −7.4% [−13.6, −1.4] | WORSE |
| passing_tds | 8,779 | 585 | 0.2381 | 0.2318 | +0.0063 [+0.0016, +0.0112] | +0.0139 [+0.0039, +0.0244] | −3.8% [−10.4, +3.0] | WORSE |
| rushing_yards | 26,634 | 588 | 0.2667 | 0.2415 | +0.0253 [+0.0199, +0.0308] | +0.0856 [+0.0670, +0.1047] | −4.7% [−8.2, −1.6] | WORSE |
| rushing_attempts | 9,863 | 581 | 0.2692 | 0.2479 | +0.0213 [+0.0145, +0.0292] | +0.0791 [+0.0551, +0.1049] | −1.7% [−6.1, +2.6] | WORSE |
| receptions | 43,091 | 589 | 0.2611 | 0.2384 | +0.0227 [+0.0184, +0.0270] | +0.0709 [+0.0576, +0.0833] | −5.8% [−8.7, −3.0] | WORSE |
| receiving_yards | 59,290 | 590 | 0.2633 | 0.2403 | +0.0230 [+0.0190, +0.0266] | +0.0756 [+0.0637, +0.0877] | −5.6% [−8.4, −2.8] | WORSE |
| interceptions | 6,557 | 584 | 0.2442 | 0.2412 | +0.0030 [−0.0001, +0.0059] | +0.0061 [−0.0004, +0.0120] | −7.1% [−15.0, +0.5] | NO DIFFERENCE |

Point accuracy, one row per (player, market, game). The baseline is the player's own as-of average =
production's estimator with the context multiplier OFF. **For NFL, "model vs own average" therefore
measures exactly one thing: the game-context term.**

| market | n | MAE model | MAE own-avg | dMAE vs own-avg [CI] | MAE book line | dMAE vs book line [CI] | dMAE vs last-4 avg [CI] |
|---|---|---|---|---|---|---|---|
| passing_yards | 1,110 | 65.30 | 65.70 | **−0.39 [−0.80, −0.02]** | 55.66 | +9.54 [+7.49, +11.75] | −2.19 [−3.81, −0.50] |
| passing_attempts | 1,092 | 8.12 | 8.17 | −0.05 [−0.12, +0.02] | 6.94 | +1.15 [+0.87, +1.45] | −0.12 [−0.31, +0.07] |
| passing_tds | 1,115 | 0.934 | 0.939 | −0.006 [−0.012, +0.000] | 0.933 | +0.001 [−0.024, +0.027] | −0.045 [−0.065, −0.023] |
| rushing_yards | 2,951 | 19.68 | 19.78 | −0.11 [−0.21, +0.00] | 17.91 | +1.86 [+1.46, +2.30] | −0.68 [−1.02, −0.35] |
| rushing_attempts | 2,383 | 3.40 | 3.40 | 0 (no context term by design) | 3.00 | +0.40 [+0.31, +0.49] | −0.01 [−0.08, +0.05] |
| receptions | 5,840 | 1.596 | 1.597 | −0.002 [−0.004, +0.000] | 1.529 | +0.068 [+0.047, +0.086] | −0.031 [−0.051, −0.011] |
| receiving_yards | 6,173 | 21.11 | 21.15 | −0.04 [−0.08, +0.01] | 19.76 | +1.38 [+1.14, +1.60] | −0.90 [−1.15, −0.64] |
| interceptions | 1,107 | 0.712 | 0.713 | −0.001 [−0.004, +0.002] | 0.694 | +0.018 [−0.003, +0.037] | −0.005 [−0.020, +0.011] |

What this table says:

- **The book line is a better point forecast than the model in 6 of 8 markets** (CI excludes 0).
  passing_tds and interceptions are ties.
- **The context term is real but tiny.**
  - Point: significant only for passing_yards (−0.39 yards).
  - Probability, vs own average:

    | market | dBrier vs own-avg [CI] |
    |---|---|
    | passing_yards | −0.0027 [−0.0045, −0.0008] |
    | passing_tds | −0.0014 [−0.0023, −0.0006] |

    Others are inside noise.
  - The gap to the book is ~10x larger than anything the context term closes.
- **Season-to-date beats last-4** in 5 of 8 markets, and is never worse. A more "recent" average is not
  the missing ingredient.
- **The model is biased LOW on every yardage market** (pooled bias −12.6 passing, −2.2 rushing, −3.0
  receiving yards). Pre-registered prior: `findings_2026-09-28_nfl_mean_bias.md` says the estimator is
  unbiased over all players and the apparent over-prediction there is selection. **On the QUOTED
  population the sign is the opposite (under-prediction).** That is the same mechanism, selection, in
  the other direction: books list players whose role is rising. Not chased here.

Per season, vs the book (dBrier verdict):

| market | 2023 (132 g) | 2024 (235 g) | 2025 (226 g) |
|---|---|---|---|
| passing_yards | WORSE | WORSE | WORSE |
| passing_attempts | no diff | WORSE | WORSE |
| passing_tds | no diff | no diff | WORSE |
| rushing_yards | WORSE | WORSE | WORSE |
| rushing_attempts | WORSE | WORSE | WORSE |
| receptions | WORSE | WORSE | WORSE |
| receiving_yards | WORSE | WORSE | WORSE |
| interceptions | no diff | WORSE | no diff |

Consistency with the one prior measurement (`log/2026-09-29.md`, 2024, scratch scripts, model version
unverified): receiving_yards +0.0226 there vs **+0.0240** here (2024, shipped model). It is the same
answer, now on the shipped code.

### 4b. Anytime TD (one-sided)

Only 385 rows (2023, 58 games) carry a NO price; 2024, 2025 and 2026 have none. So the book comparison
uses the YES price **with its vig still in it**. That overstates P(score) and should make the BOOK look
worse.

| group | rows | games | Brier model (shrunk rate) | Brier own raw avg | dBrier model−own [CI] | Brier book (vig-INCLUSIVE) | LogLoss model / book |
|---|---|---|---|---|---|---|---|
| 2023 | 15,882 | 132 | 0.1635 | 0.1824 | −0.0189 [−0.0248, −0.0135] | 0.1552 | 0.5045 / 0.4806 |
| 2024 | 24,549 | 235 | 0.1674 | 0.1923 | −0.0248 [−0.0294, −0.0200] | 0.1613 | 0.5144 / 0.4952 |
| 2025 | 26,964 | 226 | 0.1659 | 0.1951 | −0.0292 [−0.0348, −0.0237] | 0.1544 | 0.5106 / 0.4781 |
| **2023-25 pooled** | **67,395** | **593** | **0.1659** | **0.1910** | **−0.0252 [−0.0284, −0.0219]** | **0.1571** | **0.5106 / 0.4849** |
| 2026 wk2 | 1,720 | 16 | 0.1435 | 0.1591 | −0.0156 [−0.0275, −0.0038] | 0.1469 | 0.4583 / 0.4645 |

On the 385 de-viggable 2023 rows: model vs de-vigged book dBrier **+0.0119 [+0.0037, +0.0209]**, worse.

- **`#471`'s shrinkage is validated again:** it beats the player's raw own rate in every season.
- **It loses to even the vig-inclusive book price in every historical season**, so de-vigging cannot
  rescue it. Paired, game-clustered, model minus vig-inclusive book:

  | group | dBrier [CI] | dLogLoss [CI] |
  |---|---|---|
  | 2023 | +0.0083 [+0.0047, +0.0120] | +0.0239 [+0.0142, +0.0337] |
  | 2024 | +0.0062 [+0.0033, +0.0091] | +0.0192 [+0.0117, +0.0269] |
  | 2025 | +0.0115 [+0.0086, +0.0143] | +0.0326 [+0.0238, +0.0405] |
  | **pooled** | **+0.0088 [+0.0069, +0.0106]** | **+0.0257 [+0.0205, +0.0308]** |
- 2026 wk2 (16 games): dBrier −0.0034 [−0.0127, +0.0059], NO DIFFERENCE. That is one week, not a
  reversal.

### 4c. 2026 in-season (week 2 only: 16 games)

| market | rows | dBrier model−book [CI] | verdict |
|---|---|---|---|
| receptions | 442 | +0.0498 [+0.0179, +0.0854] | WORSE |
| receiving_yards | 563 | +0.0401 [+0.0148, +0.0692] | WORSE |
| passing_yards | 184 | +0.0455 [−0.0213, +0.1201] | no diff |
| passing_attempts | 97 | +0.0205 [−0.0485, +0.0948] | no diff |
| passing_tds | 171 | +0.0321 [−0.0071, +0.0832] | no diff |
| rushing_yards | 304 | +0.0020 [−0.0349, +0.0515] | no diff |
| rushing_attempts | 58 | +0.0840 [−0.0167, +0.1789] | no diff |
| interceptions | 94 | +0.0101 [−0.0139, +0.0286] | no diff |

Every point estimate is on the model-worse side. 16 games cannot clear a CI for most markets. This is
NOT a 2026 verdict; it is one week. Weeks 1 and 3 are unrecoverable (section 3).

## 5. What the daily scorecard covers, and what it misses

`run_weekly_backtests.py` re-runs `backtest_nfl_props.py` on Mondays. `_summ_nfl_props` keeps:
- MAE vs a CONSTANT per-market mean;
- synthetic-ladder Brier vs actual;
- an always-empty real-market section.

It has no book price, no de-vig, no CI, no own-average baseline, no anytime-TD-vs-price, and no game
lines at all. It also grades a rate function that has drifted from production (section 1). **It cannot
produce the verdict in this file.** This harness can, in ~15 min for props.

## 6. Disposition (no board change made)

- Props: every NFL prop market stays probability-WITHHELD / edge-free on the board on this evidence.
  The model's mean is displayable; its probability is not a price.
- The open question this does NOT answer: the 09-28 diagnosis says the residual is a
  distribution-family problem. This file says the MEAN already loses to the book line by 4-17% of MAE in 6
  markets (receptions 4%, receiving yards 7%, rushing yards 9%, rushing attempts 12%, passing
  attempts 15%, passing yards 17%). A better distribution cannot fix a worse centre.
