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

## H6 -- the UNDER effect, tested as pre-registered (`804f11d5`; script `scripts/nba_unders_test.py`, `9365082e`)

Main lines only (per event-market-player: the point quoted by the most books), one row per player-game-market, Shin fair,
2025-26 regular season. 132,129 main lines, 127,657 graded (4,472 no outcome, 0 pushes).

| test | DISCOVER residual [95% CI] | CONFIRM residual [95% CI] | CONFIRM ROI at best price [CI] | CONFIRM ROI at median price | verdict |
|---|---|---|---|---|---|
| H6a all main lines (n 81,395 / 46,262; 721 / 488 games) | **+1.01% [+0.38, +1.57]** | **+1.61% [+0.78, +2.35]** | -0.75% [-2.31, +0.70] | -3.25% | **SUPPORTED** |
| H6b prior-10 MIN >= 30 (n 28,337 / 15,883) | +0.12% [-0.95, +1.34] | **+2.58% [+1.08, +4.07]** | +1.37% [-1.54, +4.32] | -1.53% | SUPPORTED (bar met; discover ~0 -- a late-season effect) |

Sensitivity: the residual is the same under a multiplicative fair (+1.04% / +1.63%), so it is not an artifact of the de-vig.
Discover ROI at best price: H6a -1.84% [-2.96, -0.73], H6b -3.07%.

CONFIRM by market (BH q = 0.10 survivors marked *): threes +2.90% [+1.49, +4.05]* (ROI best +2.68%), rebounds+assists
+2.70%* (+0.71%), rebounds +1.73%* (+0.46%), assists +1.72%* (-0.52%), PRA +1.41%* (-1.56%), points+rebounds +1.13%*,
points+assists +1.06%*, points +0.53% [-0.53, +1.58] (-2.15%).

**Reading.** The market under-rates NBA prop unders by ~1-1.6 probability points, in both halves of the season and under
both de-vig methods -- the first matchup-side effect in this programme to pass a pre-registered bar. It is SMALLER than
the hold: blind unders lose ~1% at the best of 8 US books and 3-4% at the median book. So it is a LIKELIHOOD adjustment
(the board's p_under should be ~1-1.6 pts higher than the Shin fair says), not a stand-alone bet. It becomes value only
in combination: best-price shopping, the strongest markets (threes, rebounds, rebounds+assists), heavy-minutes starters
late in the season, and other signals. Registered as `nba.under_bias`, status `supported`.

**Limits.** One season; 8 US books at one snapshot ~45 min pre-tip (no sharp book, no close); per-market and the min-30
cut are secondary (BH applied to markets). Next-season confirmation runs forward from the 10-20 opener on the live quote
logs.

## H7 grader + a 2025-26 dry run (2026-10-13 23:06Z) -- a format / join check, NOT evidence

Grader: `scripts/grade_h7_nba_unders.py` (tests `tests/test_grade_h7_nba_unders.py`; three mutation checks -- per-row
cutoff, stale change-log point, snapshot carry-forward -- each fail a test). It reads the registration literally: each
book's LAST quote at or before the SCHEDULED tip minus 45 min (earliest commence per event -- OddsAPI rewrites
commence_time to the actual start in play, measured 02:00:00Z -> 02:10:53Z on 2026-10-05), main line by two-sided book
count, best price over the 16 US books, prior-10 MIN >= 30 from the as-of table (a date the daily job missed is rebuilt
with `build_as_of`, counted `signal_tables_rebuilt`), voids for push / DNP, INTERIM before 2027-04-11.

Pointed at 2025-26 (backfill snapshots ~T-49 min, the season's own log and tables) the joins are clean: 64,083 main
lines, 21,844 graded, 2,059 without a table row (early season), 180 on another slate date. The same rule, by window:

| 2025-26 window (in-sample; H7 was SELECTED on this season) | n / games | ROI at best US price [95% CI] | residual vs Shin [CI] |
|---|---|---|---|
| 2025-10-21..2026-01-31 | 14,043 / 704 | **-3.54% [-5.62, -1.30]** | -0.25% [-1.31, +0.91] |
| 2026-02-01..2026-04-12 | 7,801 / 471 | **+2.76% [-0.20, +5.47]** | +3.14% [+1.65, +4.56] |
| full season | 21,844 / 1,175 | -1.29% [-3.04, +0.49] | +0.96% [+0.07, +1.84] |

By market, full season: threes +1.22%, rebounds -0.65%, rebounds+assists -1.91%, assists -3.75% [-6.15, -1.44].

**Reading.** On heavy-minutes players the under effect was ENTIRELY a Feb-Apr phenomenon in 2025-26 (zero residual
Oct-Jan). H7's bar is a FULL-season ROI CI above 0, which its own selection season fails (-1.29%). So H7 as registered is
expected to fail even if 2025-26 repeats exactly; it tests "the effect is now season-long", not "the effect repeats".
H7 is NOT amended here. A late-season variant, if wanted, must be registered as its own hypothesis before 2027-02-01's
first outcome, with a multiplicity correction across the two.

## H7-late registered (2026-10-13 23:11Z, user decision) -- and what the family rule would have said in-sample

H7-late = the H7 bet on games 2027-02-01..2027-04-11 only. Adding it made {H7, H7-late} one family, so H7's single-test
bar was REPLACED (before any 2026-27 outcome) by Holm at family-wise one-sided alpha 0.025 on bootstrap p-values
(B 2000, seed 20261013) -- this supersedes "H7 is NOT amended" above. Read once, at the final read 2027-04-11.

The same rule on 2025-26 (in-sample, the selection season): H7 p 0.925 (ROI -1.29%), H7-late p 0.030 (ROI +2.76%
[-0.08, +5.46], 7,801 bets / 471 games). Neither passes; H7-late would fail even alone at 0.025. If the true late-season
ROI equals that in-sample estimate (likely an overstatement), the chance of passing is ~0.4. The residual (secondary)
is the far more sensitive measure -- in-sample late +3.14% [+1.65, +4.56] -- but money is the ROI, so ROI stays the bar.
