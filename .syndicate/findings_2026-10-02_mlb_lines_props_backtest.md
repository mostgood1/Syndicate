# MLB game lines + player props — AS-OF backtest `[2026-10-02, lane mlb-lines-props-backtest, NO DEPLOY]`

Script: `scripts/backtest_mlb_lines_props.py` (tests: `tests/test_backtest_mlb_lines_props.py`, 12 pass).
Method mirrors NHL (`nhl-player-props-projection`, deploys.md 2026-10-02 21:38Z): per market n, bias, MAE
vs actual, dMAE vs a naive AS-OF baseline with a game-clustered bootstrap CI (1,000 draws, seed 7), and
Brier / log-loss vs the de-vigged book on the SAME rows with a paired game-clustered CI. Verdict rule
copied from NHL (`INSUFFICIENT_N` < 200, `MODEL_BETTER` if CI upper < 0, `MODEL_WORSE` if lower > 0).

## Headline

**No MLB pregame market earns a probability or edge: 0 of the 23 markets with two-sided book rows
beat both the as-of baseline and the book.** Ten are significantly WORSE than the de-vigged book:

- full-game total
- F5 moneyline
- F5 total
- first-inning total
- hitter hits
- hitter total bases
- hitter HR
- pitcher strikeouts
- pitcher outs
- pitcher hits allowed

None is better than the book. The other 13 are at parity: no difference, or too few rows to
tell. This is the NHL result again — keep MLB **mean-only**, the
equivalent of an empty `MEASURED_MARKETS`.

## Substrate and coverage — read before the numbers

- **Production is the local fleet** (`/home/amyn/syndicate-prod/data`, WSL; Render suspended
  2026-09-30, `docs/ai_context/local_production_runbook.md`). The script read that data root.
- **For 05-28..07-12 the fleet's bytes ARE the git mirror**: the fleet bootstrapped from it, and all
  44 sim dates are git-tracked. July 13 – Sept 29 sims lived only on Render's disk, which is
  unreachable while suspended. **The full regular season cannot be backtested from stored model
  output.** Recovering it needs the Render export, which means unsuspending web: a billing decision.
- Outcomes and baselines come from MLB StatsAPI (public, immutable, cached): the season schedule
  with linescores, and the regular + postseason game log of every modelled player, keyed by gamePk
  (doubleheader-safe).

| family | dates | window |
|---|---|---|
| per-game sims, simulated PREGAME | 43 | 05-28..10-01 (41 regular + 2 postseason) |
| game-line snapshots | 49 | 05-28..10-03 |
| hitter-prop snapshots | 50 | 05-28..10-03 |
| pitcher-prop snapshots | 50 | 05-28..10-03 |
| final outcomes | 50 | 05-28..10-01 |
| **intersection, game lines** | **42** | |
| **intersection, props** | **42** | |

**As-of enforcement, with every drop counted:**

- **Model.** `daily_summary` is NOT used. It is rewritten after games (findings 09-14: 326/326
  re-sims). Each per-game `sims/<date>/sim_*.json` records `schedule.status` at sim time. Kept:
  510 Scheduled/Pre-Game/Warmup. Dropped: 32 Final, 15 In Progress, 1 Suspended, 1 Delayed, plus 5
  duplicate pks. That leaves **504 regular-season games** and 1 postseason game.
- **Book.** The latest snapshot with `retrieved_at` (UTC, `datetime.utcnow()` in the vendor
  fetcher) strictly before that game's first pitch.
  - Game lines: 73 games had no pregame quote.
  - Props: 205 hitter and 10 pitcher quotes were dropped as taken after first pitch.
- **Baselines.** Built from games strictly before the slate date.
  - Props: the player's season-to-date per-game average, and the player's own empirical rate of
    clearing the line, Laplace-smoothed. Requires ≥5 prior appearances (120 hitter and 116
    pitcher player-games had fewer).
  - Game lines: the two teams' as-of runs scored/allowed per segment, plus the league as-of home
    margin and spread, scored with a normal approximation.
- **Voids.**
  - 1,869 priced hitter lines and 83 pitcher lines were for players who did not appear (the
    `prop_player_not_in_boxscore` class from findings 09-28). They were voided, not graded.
  - Pushes were excluded and counted.
  - Name join (book → model lineup on the same date): 2,772 hitter and 236 pitcher quote-names were
    unmatched across all snapshot docs. Those are mostly players outside the projected lineups.
  - 9,361 hitter lanes were one-sided (HR overwhelmingly) and were excluded.
- **Book = one bookmaker per game** (DraftKings 288, FanDuel 177, other 46 game-date records). This
  is a single-book de-vig, not a consensus close. Best-price grading is not possible in this window:
  multi-book `book_quotes` exist on the fleet only from 09-15.

## Results — 2026 regular season (41 dates, 504 games; book rows as stated)

### Game lines

| market | rows (book) | dBrier vs as-of baseline [CI] | Brier model / book | dBrier vs book [CI] | verdict vs book | EV>0 flat ROI [CI] |
|---|---|---|---|---|---|---|
| full ML | 504 (431) | -0.0019 [-0.0084, +0.0044] | 0.2479 / 0.2453 | +0.0027 [-0.0055, +0.0109] | NO_DIFFERENCE | +1.8% [-10.3, +12.6] n=362 |
| full run line | 431 | -0.0054 [-0.0120, +0.0018] | 0.2401 / 0.2412 | -0.0011 [-0.0077, +0.0061] | NO_DIFFERENCE | +4.3% [-6.4, +14.5] n=304 |
| full total | 415 | +0.0081 [-0.0030, +0.0201] | 0.2624 / 0.2502 | **+0.0123 [+0.0027, +0.0229]** | **MODEL_WORSE** | -10.1% [-20.8, +0.1] n=341 |
| F5 ML (2-way, ties void) | 430 (366) | +0.0029 [-0.0042, +0.0102] | 0.2537 / 0.2440 | **+0.0097 [+0.0014, +0.0181]** | **MODEL_WORSE** | -8.9% [-22.4, +4.0] |
| F5 run line | 418 | +0.0034 [-0.0047, +0.0104] | 0.2552 / 0.2472 | +0.0080 [-0.0002, +0.0152] | NO_DIFFERENCE | -4.9% [-16.1, +6.1] |
| F5 total | 423 | +0.0085 [-0.0019, +0.0195] | 0.2603 / 0.2473 | **+0.0130 [+0.0040, +0.0229]** | **MODEL_WORSE** | -8.8% [-19.8, +2.4] |
| F3 ML / RL / total | 264(212) / 431 / 275 | ~0 | 0.2527/0.2444, 0.2485/0.2443, 0.2535/0.2450 | +0.0083 / +0.0042 / +0.0086, CIs span 0 | NO_DIFFERENCE | all negative |
| F1 3-way ML | 431 | -0.0169 [-0.0325, -0.0005] | 0.1985 / 0.1969 | +0.0016 [-0.0027, +0.0064] | NO_DIFFERENCE | n/a |
| F1 run line | 419 | -0.0089 [-0.0207, +0.0035] | 0.1618 / 0.1605 | +0.0013 [-0.0031, +0.0063] | NO_DIFFERENCE | +1.0% [-12.0, +15.7] |
| F1 total (NRFI/YRFI) | 431 | +0.0003 [-0.0205, +0.0202] | 0.2556 / 0.2461 | **+0.0095 [+0.0027, +0.0167]** | **MODEL_WORSE** | **-15.5% [-26.3, -5.2]** n=324 |

Means vs the team as-of baseline (504 games):
- Full total: bias **-0.93 runs** (model low in this window). dMAE -0.020 [-0.105, +0.056].
- F5 total: bias -0.64. dMAE -0.005 [-0.061, +0.050].
- First-inning total: dMAE **-0.034 [-0.049, -0.018]**, MODEL_BETTER on the mean.
- First-inning margin: dMAE -0.026 [-0.041, -0.012], also MODEL_BETTER on the mean.
- Every other segment's mean: NO_DIFFERENCE.

### Player props

| market | point n | bias | dMAE vs season avg [CI] | priced rows | dBrier vs own as-of rate [CI] | Brier model / book | dBrier vs book [CI] | EV>0 ROI [CI] |
|---|---|---|---|---|---|---|---|---|
| hits | 7,982 | +0.105 | +0.0008 [-0.0044, +0.0062] | 6,824 | -0.0027 [-0.0053, -0.0002] | 0.2360 / 0.2326 | **+0.0034 [+0.0016, +0.0051]** | -2.3% [-5.3, +0.6] n=4,183 |
| total bases | 7,982 | -0.083 | +0.0013 [-0.0060, +0.0088] | 6,634 | -0.0033 [-0.0058, -0.0008] | 0.2448 / 0.2406 | **+0.0042 [+0.0024, +0.0059]** | **-3.6% [-6.1, -0.9]** n=4,391 |
| home runs | 7,982 | -0.061 | -0.0253 (MAE artifact, see below) | 1,221 | **+0.0064 [+0.0022, +0.0110]** | 0.1597 / 0.1488 | **+0.0108 [+0.0065, +0.0154]** | **-6.1% [-9.2, -3.1]** n=1,065 |
| RBI | 7,982 | -0.005 | **+0.0087 [+0.0050, +0.0122]** | 5,423 | -0.0033 [-0.0054, -0.0010] | 0.2129 / 0.2119 | +0.0010 [-0.0004, +0.0026] | -3.8% [-8.8, +1.1] |
| runs | 7,982 | -0.022 | **+0.0043 [+0.0008, +0.0075]** | 4,596 | -0.0071 [-0.0097, -0.0042] | 0.2367 / 0.2358 | +0.0009 [-0.0014, +0.0034] | -1.6% [-7.1, +3.4] |
| H+R+RBI | 7,982 | +0.078 | **+0.0257 [+0.0154, +0.0353]** | 0 graded | — model distribution was DEAD in this vintage (6,053 rows, `#429`) | — | — | — |
| pitcher strikeouts | 802 | +0.42 | **+0.128 [+0.060, +0.203]** | 849 | +0.0117 [-0.0040, +0.0289] | 0.2769 / 0.2451 | **+0.0317 [+0.0185, +0.0462]** | -3.8% [-11.3, +3.4] |
| outs | 802 | **+4.75** | **+2.14 [+1.91, +2.38]** | 778 | **+0.1296** | 0.3809 / 0.2446 | **+0.1362 [+0.1083, +0.1665]** | **-12.6% [-20.7, -5.4]** |
| earned runs | 802 | +0.43 | **+0.112 [+0.056, +0.168]** | 680 | -0.0085 [-0.0205, +0.0031] | 0.2512 / 0.2473 | +0.0039 [-0.0026, +0.0108] | -1.3% [-10.0, +8.0] |
| hits allowed | 802 | +1.76 | **+0.593 [+0.482, +0.711]** | 713 | **+0.0376** | 0.3083 / 0.2482 | **+0.0601 [+0.0417, +0.0780]** | **-9.6% [-17.2, -2.0]** |
| walks allowed | 802 | +0.11 | -0.028 [-0.056, +0.002] | 338 | -0.0279 [-0.0440, -0.0118] | 0.2424 / 0.2429 | -0.0005 [-0.0101, +0.0089] | +5.7% [-8.1, +19.0] |

Point n for pitchers is 802 starts over 483 games.

**Readings that are not obvious from the table:**

1. **Hitter props beat the player's own rate, and still lose to the book.** On the proper score,
   hits, TB, RBI and runs all beat the player's as-of clearing rate (CIs below 0). On the MEAN,
   none beats the season average: hits and TB tie it, RBI and runs are worse. Against the book,
   hits and TB lose and RBI and runs tie. So the model knows more than the player's history and
   less than the price. That is the 08-17 result (market wins hits/runs/TB), now on 6× the rows
   and as-of.
2. **HR "MODEL_BETTER" on MAE is an artifact.** MAE is minimised by the median (0). The model's
   `hr_mean` is 0.055 per lineup batter, against roughly double that actual, so under-prediction
   wins MAE. On Brier the model loses to both the baseline and the book. The gate therefore judges
   both legs on Brier only.
3. **Pitcher length is the dominant defect in this engine vintage.** Model starter `outs_mean` was
   20.5 against **15.8 actual** (1,571 starts). Outs, hits allowed, strikeouts and ER all inherit
   it. This is the "starter length" root cause the 09-14 findings name; the 09-04 refit addressed
   it after this window.
4. **First-inning total: the mean beats the team baseline and the price beats the mean.** YRFI/NRFI
   flat ROI is -15.5%, CI wholly below 0. This contradicts the 09-14 proposal's premise ("first-
   inning mean worse than a constant", post-game, post-refit, different baseline). Both can be
   true across vintages. Neither earns a probability.

## Postseason (reported separately, as asked)

Two fleet-produced dates (09-30, 10-01). After the pregame filter, **1 game** carries a full
join. Every market is `INSUFFICIENT_N`. Nothing can be said about the postseason.

## Live (separate; not re-graded here)

No new live grading in this lane. These are the existing live measurements, quoted from the
ledger and not re-derived:

- **Live game lines** (findings 09-14): h2h full LOSES, +0.0102 [+0.0009, +0.0205] over 176 games.
  F5, totals and spreads are parity.
- **Live props** (lane `mlb-live-prop-grader`): no two-sided price exists (0% two-sided keys), so
  there is no market comparison. Graded vs a constant: overconfident, and ROI falls as claimed EV
  rises.

**Live stays as it is; none of it earns a probability on this evidence either.**

## Inventory — what was already measured (from origin/main, 2026-10-02)

| market | prior measurement | window / n | as-of? | this lane |
|---|---|---|---|---|
| full ML / RL / total, F5, F3, F1 vs close | `measured_market_skill.py:328-406` (09-14) | 08-31..09-13, 124-188 games | **no** — post-game re-sims | as-of re-measure, 504 games |
| best-price regrade | `reports/mlb_regrade/best_price_regrade.json` | 07-07..08-05, 26 dates | no | not gradeable (single book in window) |
| F5 skill vs climatology | findings 09-07 first5_skill | 1,015 games | no | — |
| hitter means vs constant | `mlb_prop_calibration.py:44-60` | 08-01..08-14, 2,487 | no | now vs the player's own as-of average |
| hits / runs / TB vs market | `reports/phase7/mlb_props_vs_market.json` (08-17) | 06-15..06-27, 12 dates | no | 42 dates, as-of |
| HRR vs market | 09-14 | 09-06..09-13, 1,266 | no | ungradeable here (dead dist) |
| RBI, HR vs market | — | — | UNTESTED | **first measurement** |
| pitcher K / outs / ER / H / BB vs market | 09-14 | 8 dates, ~190 starts | no | as-of, 680-849 rows |
| SB, singles, doubles, walks, hitter K | — | — | not priced in the captured odds | not priceable |
| team totals, alternate lines | — | — | no quotes captured | not priceable |

## Gate list vs what the board serves TODAY

**What is served today**, from code — the fleet board has no MLB slate on 10-02, `sweep_state no_slate`:

- MLB props carry `model_prob_over` and an edge:
  - pitcher props via `_dist_prob_over`, `prop_projections.py:687`;
  - HR via `:726`;
  - hitter buckets, calibrated-or-raw, via `:768`.
- Game lines carry the same, via `project_game_market` (`:980-1053`).
- Money is protected: the `[portfolio-sim-sizing-gate]` sizes nothing that is not `beats_market`,
  and no MLB market is. So the exposure is the displayed probability/edge and its ranking, not
  stakes.

| market | backtest gate | served today | contradiction |
|---|---|---|---|
| every MLB game line (full, F5, F3, F1) | MEAN_ONLY | probability + edge | **yes: probability served** |
| hitter hits, TB, HR, RBI, runs, HRR | MEAN_ONLY | probability + edge | **yes** |
| pitcher K, outs, ER, H allowed, BB | MEAN_ONLY | probability + edge | **yes** |

**Verdict labels the as-of backtest contradicts** (`measured_market_skill.py`). Each is labelled
`VERDICT_PARITY` today, but the as-of backtest has the model significantly WORSE than the book:

- full total (`:344`)
- F5 h2h (`:352`)
- F5 total (`:368`)
- first-inning total (`:400`)
- pitcher strikeouts (`:432`)
- pitcher hits allowed (`:441`)

The caveat: different engine vintage (May–July vs post-09-08). The 09-14 numbers are post-game
upper bounds, so a "parity" there cannot rescue the market. Hitter hits/TB/HR carry NO market
verdict in that table, and here they lose.

## What this does NOT establish

- **It does not measure the CURRENT engine.** The sim was refit 09-01, ~09-05 and 09-08. Every
  stored as-of projection predates all three. This is evidence about the May–July engine, and the
  only as-of evidence that exists.
  - A "worse" here does not prove the current engine is worse.
  - Nothing measures the current engine as-of either: its stored projections are post-game
    re-sims (09-14). The `daily_summary` first-pitch freeze proposed 09-14 is still not on main.
    It is the precondition for ever measuring the current engine.
- The book is a single bookmaker's snapshot, not a consensus close, and not best price.
- 42 of ~180 regular-season dates.

## Decisions for the user (nothing changed; no deploy)

1. **Make MLB mean-only on the board, NHL-style.** Withhold `model_prob_over`/edge for every MLB
   pregame market. Prop paths are in `prop_projections.py`, which lane `mlb-doubleheader-e2e`
   holds (goal MET), so it needs a release or a loan.
2. **Re-label the six `VERDICT_PARITY` entries above to `VERDICT_LOSES`**, or annotate them with
   this as-of reading.
3. **Freeze `daily_summary`/sims at first pitch** (09-14 proposal) so the current engine can ever be
   measured as-of.
4. **Recovering 07-13..09-29 needs Render unsuspended long enough to export.** That is a billing
   call.
