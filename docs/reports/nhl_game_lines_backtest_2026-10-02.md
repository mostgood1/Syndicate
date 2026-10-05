# NHL game lines backtest — 2026-10-02 (lane `nhl-lines-backtest`)

Companion to the props backtest (lane `nhl-player-props-projection`, deploys 2026-10-02 21:38Z). Same template:
as-of inputs, n / MAE / bias vs the actual, dMAE or dBrier vs a naive as-of baseline with a bootstrap CI,
Brier/log-loss vs the de-vigged book.

> **USER DECISION 2026-10-02 (~7:05 PM CT, relayed by the NCAAF backtesting session, and consistent with the user's own "we can't just ignore game lines" to this session): "every line is its own decision. we should have a model that is accurate that then helps inform each decision". A market-wide gate is forbidden. These numbers are the DIAGNOSIS for a model-accuracy plan (lane `nhl-game-lines-model`), NOT a recommendation to withhold any market. Per-line decisions stay with per-line scoring.**
>
> An earlier version of this report applied a gate ("a market earns a probability or an edge only if it
> beats the baseline AND the book") and recommended withholding three markets. That rule was a
> market-wide exclusion and is withdrawn. The ranked fixes are in
> `docs/reports/nhl_game_lines_model_experiments_2026-10-02.md`.

Harness: `scripts/backtest_nhl_game_lines.py` (`actuals` / `odds` / `probe-periods` / `sim` / `score`).
Machine-readable result: `C:/tmp/nhllines/report.json` (scratch; regenerate with the commands at the end).

## TL;DR

- **Accuracy today: the model adds nothing over a team goal average.** Every market's model ties its naive as-of baseline over the
  2025-26 regular season (n=1,132). The one exception is the moneyline, which beats points%-log5 and a
  constant home rate but ties the GF/GA baseline. The leg against the book **could not be run for 2025-26**:
  the OddsAPI key in the checkout is deactivated (HTTP 401 `DEACTIVATED_KEY`, 0 credits spent).
  On the 11 games that do have a
  provable pregame close (2026-27 openers), the raw and the served model are both worse than the book.
  At 2 dates that is anecdote, not a verdict.
- **What the board serves today** (moneyline anchored `p_home_ml` + edge, puck line home −1.5 + edge,
  totals at the priced line + edge) is recorded in §6 as context for the accuracy plan. Nothing is
  proposed for removal: each line is its own decision, and the work is to make the model accurate.
- **Three engine and pipeline defects, found and measured, none fixed here:**
  1. **Totals settle on regulation goals.** `game_market_sim` has no OT, so `p_over` counts regulation
     goals only. Books settle full game, with the shootout winner credited a goal. Two errors cancel: the
     model OVER-projects regulation goals by **+0.36 [+0.22, +0.50]** per game, and the regulation-only
     settlement drops the OT goal. The served p_over looks better calibrated than the model is.
  2. **Regulation ties are badly under-predicted.** The model gives 0.160; the actual rate is
     **0.2465 [0.221, 0.272]** (n=1,132). The miss holds in every arm (playoffs 0.157 vs 0.268; 2026-27
     0.157–0.159 vs 0.24–0.25). Independent Poisson per period cannot produce hockey's tie mass. A
     regulation 3-way market must not be added on this engine, and ML's 50/50 tie split inherits the error.
  3. **The production totals line is a median of every point captured**
     (`features/market_lines.py::load_market_lines`). Captures mix books, alternates, and in-play quotes:
     on the fleet's 2026-10-02 `oddsapi.csv`, VAN–EDM carries 15 distinct points from 6.0 to 16.5. So the
     sim prices lines no book hangs (5.75, 6.25, 9.0, 9.5 in the fleet's predictions files). That is why
     the board refused a probability on 6 NHL totals rows in the 2026-10-02 read ("hockeysim priced only 6.0").

## 1. What was already measured (before this lane)

| market | n / window | metric | model vs ref | verdict | inputs | source |
|---|---|---|---|---|---|---|
| ML home | 15 g, 12 dates, 2026-03-01..06-11 | Brier | 0.2905 vs market 0.2769 | market wins, unpowered | as-of, **anchored blend** | `hockeysim_market_backtest_report.md:137-145` |
| Total O/U | 15 g, same | Brier | 0.2102 vs 0.2378 | "model beats market", explicitly not evidence | as-of, raw | same `:140,147-157` |
| PL −1.5 | 3 g (local) | Brier | 0.2146 vs 0.2133 | market wins | anchored | same `:141` |
| Home win, Elo vs constant | 1,312 g, 2025-26 | Brier | Elo 0.2506 vs const 0.2495 | Elo blend weight stays 0 | as-of Elo | `hockeysim_engine_reference.md:1490-1515` |
| home win %, period shares | 1,312 g | aggregate norm-error | fit to truth | calibration, **in-sample**, not per-game | in-sample | `hockeysim_phase3b_calibration_report.md` |
| First-10-min goal (vendor) | script only | Brier/LL | **no result recorded** | — | — | `vendor/.../first10_eval.py` |

**Untested before this lane:** the pure-model (`_raw`) ML and puck line, regulation 3-way, P1 lines, the
away −1.5 side, over and under bias separately, and anything with a CI. The `calibration/` package
(`simulator_evaluator.py`, `evaluation_metrics.py`, `profile_calibration.py`) evaluates league-aggregate
rates against the truth snapshot. It runs no per-game probability test.

**The daily scorecard (`daily-accuracy`, `scripts/publish_model_scorecard.py` →
`shared/model_scorecard.py`)** does include NHL. Its settler covers h2h, spreads, totals, regulation 3-way
and p1–p3, settling ML/PL/totals full game and 3-way on 60 minutes. What it **misses** for NHL lines:
- **No rows.** The recorder wrote no NHL board parts in the windows read (state_model.md:30).
- **It grades the BOARD's edge rows (`p_model = fair + model_edge_pct`), i.e. the anchored blend.** It
  never grades hockeysim's raw probability.
- **No P1 or 3-way odds are captured.** Production fetches with explicit `h2h,spreads,totals`
  (`local_nhl_odds.py:431-436`, `refresh_nhl_oddsapi.py:133`), so those settler branches can never fill.
- **No naive-baseline comparison exists**, so "beats the book" would be read without "beats a team
  average".

## 2. Method

- **Model = production code, unmodified, run as-of.** For each date, `build_slate_features(date, root)`
  is run on the props lane's per-date as-of root (`C:/tmp/nhlprops/bt/roots/<date>`, written by
  `backtest_nhl_props.py::run_date`; read-only here). The closing market is injected, then
  `build_nhl_artifacts.predict_game` runs at anchor weight 0.35, the production default. A seed-exact
  replica of `simulate_from_period_lambdas` is **asserted equal** to production's `p_home_ml_raw`,
  `p_home_pl_-1.5_raw`, served `p_home_ml` and `p_over` on every game. That lets the 3-way, away −1.5,
  P1 and OT-corrected numbers be read off the same draws production made.
- **Re-simulated, not recovered.** No 2025-26 pregame projection survives on production: Render is
  suspended, and the fleet's `nhl_source/data/processed` holds only 2026-09-30..10-04. The local
  mirror's `predictions_*.csv` are of unknown vintage and include backfilled copies
  (lane `nhl-sim-artifact-backfill-fabricates`). **Every number below is a re-sim with as-of inputs.**
- **Leakage check (passed):** in all **187/187** roots, `team_rates_2025-2026.csv` games = 2 × the
  regular-season games strictly before the date. **0 degenerate dates** (no slate with a single constant
  total; the fleet's 5.9134 failure does not occur in the as-of roots).
- **Roots named:** the run above used `C:/tmp/nhlprops/bt/roots` (lineups built BEFORE `4247a6ea`, the PP/PK-shape and dress-by-total-TOI fix). Re-run on `C:/tmp/nhlprops/bt_after/roots` (lineups ON the fix): **0 of 1,288 games differ** in period lambdas, raw or served probabilities (2026-10-02 ~23:40Z). Every number here holds for both lineup versions.
- **Reachability:** removing lineups leaves the game lambdas byte-identical. Removing team xG changes
  them (positive control). Game lines depend only on the team season files, so the lineup-code version
  that wrote the roots does not matter here.
- **Settlement:** ML, puck line and totals settle on the final score, with the SO winner credited one
  goal (book convention). The 3-way settles on 60 minutes; P1 on period 1. The parse is proven per game:
  regulation + OT + SO credit equals the final score on **1,475/1,475** games.
- **Baselines (as-of, strictly before the date):**
  - (a) Team GF/GA rates, shrunk toward league with k=10, form multiplicative team lambdas. They are split
    into periods by the as-of league P1 share and run through the **same replica sim**, so the baseline
    differs from the model only in its inputs.
  - (b) ML only: points% log5 plus the as-of league home edge.
  - (c) ML only: the constant as-of home win rate.
- **CIs:** 2,000-rep bootstrap, **clustered by date**. No verdict is given below n=100.

## 3. Coverage: what each result rests on

| arm | window | finals | as-of projections | book close | **intersection** | substrate |
|---|---|---|---|---|---|---|
| 2025-26 regular | 2025-10-07..2026-04-16 | 1,312 g / 167 d | 1,132 g / 143 d (from 11-01) | **0** | vs baseline **1,132 / 143**; vs book **0** | finals: NHL API boxscores + landings in the primary checkout's **untracked** `data/nhl_source` mirror, every game passing the score identity; projections: re-sim (code at this worktree's `origin/main`) |
| 2026 playoffs | 2026-04-18..06-14 | 82 / 44 | 82 / 44 | **0** | 82 / 44 vs baseline | landings fetched from api-web.nhle.com |
| 2026-27 preseason | 09-19..09-26 | 65 / 8 | 58 / 7 | 0 (no fleet quote log before 09-30) | 58 / 7 vs baseline | api-web |
| 2026-27 regular | 09-29..10-01 | 16 / 3 | 16 / 3 | **11 / 2** | **11 / 2** | close = **production** `nhl_source/tracking/book_quotes` (fleet), last pregame quote per book (`captured_at` ≤ commence), 11 books |

**Not used, on purpose:** the playoff `oddsapi.csv` files in the local mirror (19 dates, partly
git-tracked) and the fleet's `odds/team/date=*/oddsapi.csv`. **None** of their 5,343 rows carries
`book_last_update`, and the fleet's 10-02 file holds in-play totals. They cannot prove a pregame close,
and an in-play "close" would make the book look better than it was.

## 4. Results: 2025-26 regular season (n=1,132 games, 143 dates)

Point markets (MAE, lower is better; dMAE = model − baseline):

```
total (settled, full game)  MAE 1.837 vs base 1.842  dMAE -0.0051 [-0.0338,+0.0235]  bias +0.111 [-0.029,+0.247] (base -0.123)  NO DIFFERENCE
total (regulation goals)    MAE 1.896 vs base 1.872  dMAE +0.0243 [-0.0050,+0.0538]  bias +0.358 [+0.217,+0.498] (base +0.124)  NO DIFFERENCE
goal margin (full game)     MAE 2.163 vs base 2.168  dMAE -0.0049 [-0.0317,+0.0206]  bias +0.008 [-0.146,+0.155]                NO DIFFERENCE
P1 total goals              MAE 1.055 vs base 1.054  dMAE +0.0009 [-0.0085,+0.0104]  bias +0.084 [+0.013,+0.157]                NO DIFFERENCE
```

Probability markets (Brier; dBrier = model − reference, negative is model better):

```
ML home (raw)             Brier 0.2447  meanP .521 freq .521 | vs GF/GA -0.0036 [-0.0077,+0.0005] NO DIFF | vs pts%-log5 -0.0044 [-0.0085,-0.0002] BETTER | vs const -0.0053 [-0.0086,-0.0019] BETTER
REG 3-way home in 60      Brier 0.2366  meanP .441 freq .400 | vs GF/GA -0.0010 [-0.0049,+0.0027] NO DIFF
REG 3-way tie after 60    Brier 0.1933  meanP .160 freq .246 | vs GF/GA +0.0007 [+0.0001,+0.0012] WORSE
REG 3-way away in 60      Brier 0.2255  meanP .399 freq .353 | vs GF/GA -0.0047 [-0.0085,-0.0011] BETTER
PL home -1.5              Brier 0.2064  meanP .291 freq .303 | vs GF/GA -0.0003 [-0.0039,+0.0032] NO DIFF
PL away -1.5              Brier 0.1937  meanP .256 freq .270 | vs GF/GA -0.0020 [-0.0049,+0.0008] NO DIFF
OVER 5.5 (served, reg)    Brier 0.2460  meanP .608 freq .569 | vs GF/GA -0.0014 [-0.0058,+0.0032] NO DIFF
OVER 6.5 (served, reg)    Brier 0.2478  meanP .450 freq .463 | vs GF/GA -0.0017 [-0.0063,+0.0028] NO DIFF
OVER 6.5 (OT-corrected)   Brier 0.2487  meanP .498 freq .463 | vs GF/GA -0.0008 [-0.0056,+0.0038] NO DIFF
P1 over 0.5               Brier 0.1451  meanP .843 freq .824 | vs GF/GA +0.0001 [-0.0010,+0.0011] NO DIFF
P1 over 1.5               Brier 0.2494  meanP .554 freq .542 | vs GF/GA +0.0012 [-0.0016,+0.0040] NO DIFF
P1 3-way tie              Brier 0.2286  meanP .322 freq .352 | vs GF/GA -0.0002 [-0.0011,+0.0008] NO DIFF
```

**Over and under bias, separately** (2025-26 regular; under = complement, push-free half lines):
- At 5.5 the model leans **OVER**: mean P(over) 0.608 vs frequency 0.569 (+3.9 pts). Mean P(under) is
  0.392 vs 0.431, so the under is under-priced by the same 3.9 pts.
- At 6.5 the served (regulation-only) p reads 0.450 vs 0.463, 1.3 pts under. That is an artefact of
  the cancellation in §TL;DR: with the OT goal restored, the model reads 0.498 vs 0.463, 3.5 pts OVER.
  Read honestly, **the model is over-biased at both standard lines.**

**ML reliability (raw):** p spans only 0.307–0.723 (sd 0.066), and the deciles track the outcomes
(0.46/0.47, 0.55/0.54, 0.63/0.67). The model is directionally sound but compressed. The Brier gain over
points% is real (CI excludes 0); the gain over a GF/GA team average is not.

## 5. Playoffs (n=82) and 2026-27 (n=58 preseason, 16 regular): no verdicts below n=100

- **Playoffs:** every market ties its baseline, with no verdict at n=82. Total bias is **+0.65
  [+0.20, +1.06]**: the regular-season rates over-project playoff scoring. The tie rate is 0.157
  (model) vs 0.268 (actual).
- **2026-27 preseason:** total bias **+0.92 [+0.58, +1.38]**, from prior-season inputs on preseason
  rosters. That is expected, and it is a reason **not to price preseason**.
- **2026-27 vs the production close (11 games, 2 dates; CIs over 2 clusters are not meaningful, so
  ANECDOTAL):**
  - ML raw Brier exceeds the book's by +0.023; ML served (anchored) by +0.015.
  - PL home at the book line: +0.012.
  - OVER at the close, served regulation-only p: +0.026; OT-corrected p: +0.005.
  - The book was better in every comparison. This agrees with the prior n=15 reading and is not a
    verdict either.

## 6. What the board serves today (context, not a gate)

Served treatment comes from `syndicate/features/nhl/game_projections.py:232-311`, read against the
fleet's `/api/board/layer2-shortlist` at **2026-10-02 22:34:39Z**:
- 19 NHL game rows, 19 projected, **8 with a probability**.
- Refusals: 5 "no cover probability at 1.5", 6 totals "no over probability at <line>".
- Every row carries `model_skill.state = "unmeasured"`.

| market | served today | what the accuracy evidence says | fix (ranked plan) |
|---|---|---|---|
| Moneyline | anchored probability + edge | ties the GF/GA baseline; regulation ties split 50/50 on a tie rate that is 8.6 pts too low | OT/SO + tie mass + information (confirmed goalie) |
| Puck line home −1.5 | probability + edge | ties the baseline; no empty-net effect on margins | empty net + tie mass |
| Puck line +1.5 / away side | projection only (refused) | the away −1.5 side is the same draw | price both sides from the same distribution |
| Totals at the priced line | probability + edge | regulation-only settlement; +0.36 regulation over-bias; the priced line is the median of every captured point | regulation rescale + full-game settlement + modal-line consensus |
| Projected total / margin | means shown | MAE equals the baseline's | same fixes; `model_skill` should read "measured", not "unmeasured" |
| Regulation 3-way | not served | tie mass miscalibrated | tie mass |
| P1 / period lines | goal means only | ties the baseline; no P1 odds captured | capture P1 odds; same machinery |

## 7. What would change the verdict

1. **The 2025-26 vs-book leg.** It needs an active OddsAPI key for the historical endpoint. The run is
   already written and capped (`odds --execute --max-credits 30000`, est. 26,220 credits for 874 start
   slots, quota attributed `nhl`), and so is the period/3-way probe (`probe-periods --events 5`).
   It is **blocked**: the checkout's key is deactivated, and reading production's key was refused by
   the auto-mode classifier. It needs a key you supply as `ODDS_API_KEY` in the environment.
2. The model must become accurate before any vs-book reading means much: on this evidence it adds
   nothing over team goal averages. The ranked fixes (OT in the game-market sim, the over-bias, tie mass,
   the totals-line consensus, confirmed starting goalies) are measured in the experiments report. Each is a mechanism change to a calibrated engine,
   so under `model_engine_standard` §4.4 the rates absorbing it must be re-fit.

## Reproduce

```
py -3 scripts/backtest_nhl_game_lines.py actuals                       # needs the props roots at --roots
py -3 scripts/backtest_nhl_game_lines.py odds                          # dry run; --execute spends
py -3 scripts/backtest_nhl_game_lines.py sim --quote-log C:/tmp/nhllines/captured/bq
py -3 scripts/backtest_nhl_game_lines.py score --report <md>
```
The roots come from `scripts/backtest_nhl_props.py` (lane `nhl-player-props-projection`), on origin/main as of `9a7f0d2f`.

## Regulation 3-way vs book (2026-10-05; user: "pull the 3-way odds backfill")

- **Pull:** `backtest_nhl_game_lines.py odds3way`, OddsAPI historical per-event `h2h_3_way` at the same snapshot as the other closes (3 min before start). 1,410/1,410 games (regular, playoffs, 2026-27 regular), 13,980 + ~130 credits; header remaining 4,403,965 afterwards. Proportional 3-way de-vig per book, mean over books quoting all three (5.4 books/game regular season).
- **Model:** production form -- the stored as-of `predict_game` lambdas through production's own calibrated game-market sim (`NHL_GAME_MARKET_CALIBRATION`, `game_seed`, 20k sims). Script: `scripts/nhl_game_lines_3way_vs_book.py`.
- **2025-26 regular, n=1,132 games / 143 dates** (the sim roots start 11-01; 180 October games have no model row):
  - production - book: Brier3 **+0.0014 [-0.0043, +0.0069]**, LL3 +0.0017 [-0.0066, +0.0093] -- **parity**. Per outcome, home +0.0015, tie -0.0005, away +0.0004; every CI spans 0.
  - the pre-2026-10-03 legacy sim - book: Brier3 **+0.0120 [+0.0050, +0.0182]** (worse), LL3 +0.0260 [+0.0137, +0.0372], driven by the tie (+0.0069 [+0.0040, +0.0098]). The shipped sim fixes (7865b26e) closed this gap.
  - Tie rate: actual 0.246, book 0.223, production 0.257, legacy 0.160. The book prices the 60-minute tie below its realised rate, but no Brier difference on the tie (-0.0005 [-0.0023, +0.0012]): not an edge.
- **Playoffs, n=82** (below min-n 100, no verdict): production - book Brier3 -0.0104 [-0.0274, +0.0061].
- **2026-27 regular, n=16:** no verdict.
- **Period lines:** P1 markets came back on 1 of 5 probed events (opening night only); not priced at scale in the historical archive, so not pulled.
