# NBA matchup signals v1 -- five pre-registered signals tested on 2025-26: none supported; a general UNDER lead -- 2026-10-13

Lane `signal-engine-nba` (session 9e18a0e7). H1-H5 committed to the lane (`f6710082`) before any outcome was read.
Engine: `syndicate/features/shared/matchup_signals.py` (registry, as-of tables, lift stats), `scripts/build_nba_signals.py`,
`scripts/signal_lift.py` (`cf09f4b1`).

## Data

- Lines: `backfill/nba_props_2025_26/asof/props_odds_hist/<date>.csv` (OddsAPI historical, one snapshot ~45 min
  pre-tip, 8 US books), regular season 2025-10-21..2026-04-12, markets points / rebounds / assists / threes / PRA / PR /
  PA / RA. One line = (event, market, player, point); fair = median per-book SHIN de-vig over two-sided books.
- Outcomes: stats.nba `playergamelogs_2025-26_Regular_Season.json` (26,651 player-games). No integer-line pushes occurred
  in the joined set; 12,368 lines dropped for no outcome (DNP / name miss).
- Signals: as-of tables `nba_source/signals/2025-26/<date>.jsonl` (164 dates, 26,651 rows; starts known 20,608 via the ESPN
  log; spread known 25,742 via the OddsAPI game snapshots).
- **369,912 lines joined.** Windows: DISCOVER 2025-10-21..2026-01-31, CONFIRM 2026-02-01..2026-04-12. CIs bootstrap over
  games (events). Lines include alternate points for the same player-market, so rows are correlated within a game; the
  game-clustered CI accounts for that, the raw n overstates the sample.

## Results (residual = hit rate - Shin probability on the signal's side; "base" = eligible lines where it did not fire)

| signal (side) | DISCOVER residual [95% CI] | CONFIRM residual [95% CI] | confirm fired n / games | confirm base residual | confirm hit-rate lift vs base | verdict |
|---|---|---|---|---|---|---|
| minutes_trend_up (over) | -0.79% [-2.86, +1.37] | -1.70% [-4.04, +0.47] | 23,124 / 441 | -1.91% | +0.16 pts | NOT SUPPORTED |
| minutes_trend_down (under) | +0.06% [-2.41, +2.21] | -0.61% [-2.76, +1.58] | 18,510 / 418 | +2.28% | -2.82 pts | NOT SUPPORTED |
| start_promotion (over) | -1.37% [-5.02, +2.08] | +0.66% [-3.35, +4.78] | 6,712 / 276 | -1.97% | +2.40 pts | NOT SUPPORTED |
| b2b (under) | **+3.37% [+0.89, +5.84]** | +2.69% [-0.91, +5.85] | 12,842 / 145 | +2.46% | +0.17 pts | NOT SUPPORTED |
| blowout_risk (under) | +0.79% [-1.91, +3.54] | +2.95% [-0.03, +6.04] | 14,473 / 163 | +2.53% | +0.45 pts | NOT SUPPORTED |

BH (q = 0.10) on the confirm p-values: none survive.

## Reading

1. **Role and minutes changes are priced.** Minutes-trend and promotion lines move with the role: the residual is ~0 and
   the hit-rate lift vs comparable lines is ~0. A trend-down player's UNDER actually hit 2.8 pts LESS often than other
   unders -- the market over-corrects slightly, if anything. Consistent with the outside evidence (minutes are the base
   layer every book prices first).
2. **B2B and blowout look positive but are not specific.** In CONFIRM their fired residual (+2.7%, +3.0%) is matched by the
   eligible-but-not-fired baseline (+2.5%): heavy-minutes UNDERS beat the market in Feb-Apr whether or not the team was on
   a back-to-back or the spread was lopsided.
3. **LEAD (not pre-registered; a candidate for its own test):** across eligible lines the UNDER side carries a positive
   residual and the OVER side a negative one (base residuals: unders +1.4% to +2.3%, overs -1.3% to -2.0%), strongest on
   heavy-minutes starters late in the season. That is the "books shade overs / public over bias" effect the external
   research rated plausible-but-unproven. It must be tested properly before anything uses it: main line only (one point
   per player-market), one row per player-game, pre-registered windows, and against the realized close where available.

## Registry

All five set to `status="null"` with their evidence (`matchup_signals.REGISTRY`). Nothing consumes the registry yet; when
the board surfaces success indicators, a null signal is shown as research (labelled "tested: no edge"), never as an edge.

## Next (NBA)

- The UNDER lead as its own pre-registered test (H6), on main lines, before the 10-20 opener.
- Teammate-out PRICE lag, using the timestamped injury log now collecting (`news/nba/injuries/`), from 10-20.
- Pace-adjusted defense vs position and opponent-allowed rebound / three-point-attempt / assist opportunity.
- Forward tables for 2026-27 from `player_game_log_2026.csv` (needs a daily job entry; `scripts/local_production.py`
  SCHEDULED_JOBS is claimed by other lanes -- ask before adding).
