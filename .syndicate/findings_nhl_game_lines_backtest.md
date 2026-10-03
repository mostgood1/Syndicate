# Findings: NHL game lines backtest (lane `nhl-lines-backtest`, session 9ed26377, 2026-10-02)

Full report: `docs/reports/nhl_game_lines_backtest_2026-10-02.md`. Harness: `scripts/backtest_nhl_game_lines.py`.

**Substrate.**
- Projections are a RE-SIM of `origin/main` production code (`predict_game`, anchor 0.35) over the
  as-of roots of lane `nhl-player-props-projection` (`C:/tmp/nhlprops/bt/roots`, read-only).
- Finals come from NHL API boxscores and landings: the primary checkout's untracked mirror plus
  api-web. All 1,475 games pass the identity reg + OT + SO credit == final.
- The book is the production fleet's `nhl_source/tracking/book_quotes`, last quote per book with
  `captured_at` <= commence. No 2025-26 pregame projection survives on production, so nothing was
  "recovered".

## Readings (2025-26 regular season, n=1,132 games / 143 dates, date-clustered bootstrap 95% CI)

- **Gate checks passed:** leak check 187/187 roots (team_rates games == 2x games strictly before the
  date); 0 degenerate dates; replica == production probabilities on every game (asserted); lineups
  off == on for the game lambdas, with xG removed as the positive control.
- **Every market TIES its naive as-of GF/GA baseline:**

  | market | dMAE / dBrier vs GF/GA [95% CI] |
  |---|---|
  | total MAE | -0.005 [-0.034, +0.024] |
  | margin MAE | -0.005 [-0.032, +0.021] |
  | ML Brier | -0.0036 [-0.0077, +0.0005] |
  | PL home -1.5 | -0.0003 [-0.0039, +0.0032] |
  | OVER 5.5 | -0.0014 [-0.0058, +0.0032] |
  | OVER 6.5 | -0.0017 [-0.0063, +0.0028] |
  | P1 over 0.5 | +0.0001 |
  | P1 over 1.5 | +0.0012 |

  ML does beat points%-log5 (-0.0044 [-0.0085, -0.0002]) and the constant home rate
  (-0.0053 [-0.0086, -0.0019]).
- **Regulation tie, model 0.160 vs actual 0.2465 [0.221, 0.272].** Same in every arm: playoffs
  0.157/0.268, preseason 0.159/0.241, 2026-27 0.157/0.25. The tie Brier is worse than the baseline's
  (+0.0007 [+0.0001, +0.0012]).
- **Totals: the model over-projects REGULATION goals, +0.358 [+0.217, +0.498].** `game_market_sim`
  computes p_over on regulation goals, while books settle full game with the SO credit; the two errors
  cancel. At 6.5 the served p reads 0.450 vs frequency 0.463, but OT-corrected it is 0.498: over-biased.
  At 5.5 it is 0.608 vs 0.569: over-biased.
- **vs the book:**
  - 2025-26: NOT RUN. The checkout's OddsAPI key is DEACTIVATED (HTTP 401, 0 credits spent), and
    reading production's key was refused by the auto-mode classifier.
  - 2026-27 (11 games / 2 dates, production close, anecdotal at 2 clusters): the book beat raw ML
    (+0.023 Brier), served ML (+0.015), PL (+0.012) and served OVER (+0.026).

## Production defect found (not fixed: not this lane's file)

- `features/market_lines.py::load_market_lines` takes `total_line = median(every totals point
  captured)`. The fleet's `odds/team/date=2026-10-02/oddsapi.csv` mixes books, alternates and in-play
  quotes (VAN-EDM: 15 points, 6.0..16.5). It also holds a game that commenced 2026-10-01T23:10Z.
- Result: `predictions_*` price lines no book quotes (5.75 / 6.25 / 9.0 / 9.5 on fleet 09-30..10-04),
  and over/under odds are averaged across different lines.
- The `oddsapi.csv` captures carry NO timestamp (`book_last_update` empty on 5,343/5,343 rows), so they
  can never prove a pregame close.

## Framing (user decision; supersedes the earlier "Gate" section)

- USER DECISION 2026-10-02 (~7:05 PM CT, relayed by the NCAAF backtesting session, and consistent with the user's own "we can't just ignore game lines" to this session): "every line is its own decision. we should have a model that is accurate that then helps inform each decision". A market-wide gate is forbidden. These numbers are the DIAGNOSIS for a model-accuracy plan (lane `nhl-game-lines-model`), NOT a recommendation to withhold any market. Per-line decisions stay with per-line scoring.
- **WITHDRAWN:** "game-line MEASURED_MARKETS = empty" and "the board's ML/PL/totals probability + edge is
  CONTRADICTED -> withhold". That was a market-wide exclusion.
- **Served today, as context** (`game_projections.py:232-311`; read 2026-10-02 22:34:39Z, 8 of 19 game
  rows with a probability): ML anchored probability + edge, PL home -1.5 probability + edge, totals at the
  priced line probability + edge.
- **Deliverable:** a ranked model-accuracy plan, each defect with evidence, fix and measured impact, in
  `docs/reports/nhl_game_lines_model_experiments_2026-10-02.md` (lane `nhl-game-lines-model`).

## Accuracy plan (lane nhl-game-lines-model, 2026-10-03)

- Ranked fixes with measured impact: `docs/reports/nhl_game_lines_model_experiments_2026-10-02.md`.
- #1, the totals line, is fixed by the modal pregame line from the quote log; 24/31 fleet games are mispriced today.
- #2-#5 ship as one change: pace rescale + OT/SO + tie mass + empty net. Settled bias goes +0.272 -> -0.016; tie Brier improves.
- #7: Daily Faceoff confirmed starters (99.9% when pregame-provable).
- #8: ML has no information beyond team averages yet. GSAx goalie is next.
