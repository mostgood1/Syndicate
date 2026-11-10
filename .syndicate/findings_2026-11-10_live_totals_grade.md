# Live full-game totals: the board's priced edges graded against finals (todo #780)

2026-11-10, read 22:59-23:10Z (4:59-5:10 PM CST). Session 8062940b. READ-ONLY. User: "Yes, grade them".
Script: `scripts/live_totals_grade.py`. It runs on the fleet host and reads `~/syndicate-prod/data/<sport>_source/data/live_gameline_ledger/`. ESPN finals are cached in `C:\tmp\livegrade\espn`.

## Population

- **Rows:** PRICED (`priceable`) full-game totals rows in the live gameline ledgers, every date on the fleet's disk.
- **One unit per re-sim state:** a distinct (event_id, `live_state_as_of`, line). Repeated board builds of the same state collapse into it.
- **Grading:** against ESPN finals. A game is matched by team names on the ledger's Central date and the next ESPN date.

| sport | ledger dates | graded states / games | dropped |
|---|---|---|---|
| NCAAB | 11-02..11-09 (8) | 19,420 / 287 | 38 of 325 games unmatched |
| WNCAAB | 11-03..11-10 (8) | 2,657 / 53 | 6 of 59 unmatched |
| NBA | 10-20..11-09 (20) | 12,633 / 144 | 9 of 153 unmatched |
| NCAAF | 10-02..11-07 (21) | 49,676 / 252 | 0 unmatched; 2 games had a score above the final |

- **NFL:** 0 priced full-game totals rows on 30 dates.
- **MLB:** 19 rows and **NHL:** 0 rows, both too few to grade.
- **Direction check:** the model's side agrees with model mean vs line on 96.6-99.9% of states. So `model_home_win_prob` on a totals row is P(over).

## Result 1: the claimed edge does not survive against a FRESH quote

The claim is the model's probability for its side minus the market's no-vig fair. Realised is hit rate minus fair. Both carry game-clustered 95% intervals.

| sport | all states: claimed / realised | quote <= 30 s: claimed / realised | quote > 300 s: realised | Brier model - market |
|---|---|---|---|---|
| NCAAB | +0.179 / +0.027 +- 0.035 | +0.162 / **+0.014 +- 0.054** | +0.078 +- 0.038 | **+0.024 +- 0.015 (model worse)** |
| WNCAAB | +0.186 / +0.149 +- 0.101 | +0.173 / +0.014 +- 0.143 | +0.215 +- 0.103 | -0.016 +- 0.045 |
| NBA | +0.192 / +0.094 +- 0.051 | +0.182 / **-0.001 +- 0.136** | +0.150 +- 0.042 | -0.001 +- 0.021 |
| NCAAF | +0.225 / +0.062 +- 0.035 | +0.206 / **-0.019 +- 0.054** | +0.128 +- 0.029 | +0.017 +- 0.016 |

- **Realised edge rises with quote age in every sport.** It is ~0 at <= 30 s and largest at > 300 s. It also rises late in games (score >= 90% of the line).
- **That is the line not having moved yet,** or a market the book has suspended, and neither can be bet at that price.
- **The board prices quotes this old:** the ceiling is `live_gameline_join._DEFAULT_MAX_QUOTE_AGE_SECONDS` = 600 s for every sport except MLB (120 s).
- **Quote age definition:** `quote_age_seconds` is the quote's age at the board build, e.g. recorded 23:07:55.5Z minus quote 23:07:06.1Z = 48.6 s.

**ONE BET PER GAME** (the game's first state with |edge| >= 10 pp; the decision-level view):

| sport | games | hit | model claimed | -110 break-even |
|---|---|---|---|---|
| NCAAB | 286 | 0.514 +- 0.058 | 0.657 | 0.524 |
| NBA | 144 | 0.514 +- 0.082 | 0.646 | 0.524 |
| NCAAF | 252 | 0.508 +- 0.062 | 0.701 | 0.524 |
| WNCAAB | 53 | 0.585 +- 0.133 | 0.655 | 0.524 |

- **Fresh quote and score < 75% of the line:**
  - NCAAB 0.535 +- 0.078 (157 games);
  - NBA 0.583 +- 0.139 (48);
  - NCAAF **0.439 +- 0.064 (230), below 0.5**;
  - WNCAAB 0.643 +- 0.177 (28).
- **One cell looks positive:** fresh quote with |edge| >= 20 pp in NCAAB, 0.590 +- 0.083 over 134 games.
  - It was found after reading about a dozen cells, so it is a hypothesis to pre-register on unseen nights, not a result.
  - The same cell in NBA reads 0.484 (31 games) and in NCAAF 0.520 (196).

## Result 2: engine read — the mean is no better than the line, and the spread is too narrow

The table splits each sport by progress (score so far / line) into the first and last buckets. RMSE is the error against the final. The implied sd is (model mean - line) / z(P over), the median over states.

| sport | bucket | final - model mean | model RMSE | line RMSE | implied sd | actual error sd |
|---|---|---|---|---|---|---|
| NCAAB | < 0.25 | +1.41 | 16.17 | 15.25 | 14.46 | 16.11 |
| NCAAB | >= 0.75 | +2.23 | 7.82 | 8.40 | 5.90 | 7.49 |
| NBA | < 0.25 | +1.44 | 19.51 | 17.54 | 16.76 | 19.46 |
| NBA | >= 0.75 | +0.73 | 8.63 | 9.05 | 6.34 | 8.60 |
| NCAAF | < 0.25 | -0.06 | 16.44 | 15.68 | 12.59 | 16.44 |
| NCAAF | >= 0.75 | -0.31 | 7.42 | 8.22 | 6.33 | 7.41 |
| WNCAAB | >= 0.75 | +0.31 | 6.62 | 6.77 | 5.14 | 6.61 |

- **MEAN.**
  - Early in games the model's live total is 5-11% WORSE than the line.
  - Mid-game the two are about equal.
  - Late in games the model is a little better, but the late "line" includes the stale quotes above. So "better late" is not shown.
  - NCAAB runs 1.4-2.8 points low (#768). Its fix loaded 11-09 05:13Z, so most of this sample predates it.
- **SPREAD.** The model's implied uncertainty is 10-30% narrower than its own error:
  - NCAAB late 5.9 vs 7.5;
  - NBA late 6.3 vs 8.6;
  - NCAAF early 12.6 vs 16.4.
- **Together:** a 3-4 point disagreement that carries about no information, divided by too small an sd, prints as a 15-20 pp edge.

## What this does NOT say

- **Not a real-money P&L.** The in-play entry path that is live on the fleet works differently:
  - `LIVE_ODDS_WORKER__SYNDICATE_INPLAY_ENTRIES=on`, line 181 of `local_production.env`. It was read from live-odds-worker's environ at 23:0xZ.
  - It prices from the books' CONSENSUS fair against Kalshi, not from these model probabilities (`inplay_entries_paper.py`; entries_live places only what that rule books).
  - Not checked: whether `/portfolio`'s live plan ever takes a live game-line totals row.
- **Not proof the live engine is useless.** The mean is competitive mid-game. The NCAAB bias fix and the 11-10 midnight fix (#774) are mostly not in this window.
- **Selection:** since 11-07 16:29Z the college quote-order gate removes rows whose quote predates the last score change. That makes later NCAAB rows a selected subset.

## Candidate fixes (none made)

1. **Stop pricing live totals against old quotes.** Give basketball and football a per-sport ceiling of about 30-60 s in `_MAX_QUOTE_AGE_BY_SPORT`. That would remove the stale-quote "edges" from the board.
2. **Fit the live totals spread to its measured error, per sport.** This is an estimator fit, not a new mechanism (`model_engine_standard.md`). It makes the claimed probabilities honest. It does not create edge.
3. **Pre-register the one positive cell** (NCAAB fresh quote, |edge| >= 20 pp) and grade it on unseen nights before anything is staked on it.
