# The NBA live margin, anchored to the closing line (todo #780; lane nba-live-margin-anchor)

- **User** 2026-11-13 "Build it now", after the trace
  (`.syndicate/findings_2026-11-13_nba_live_anchor_trace.md`) found the engine adds noise to its market-anchored
  target, and the live re-sim carries that noise into the game.
- **Hypothesis and falsification,** committed before building (`64b3e45cc`):
  - **Hypothesis:** anchoring cuts the live moneyline's model - market gap by at least half, mostly early.
  - **Predicted:** the NBA spreads scale falls from 2.02 to 1.2-1.6.
  - **Falsified if:** anchored is not below raw on outcomes, or is worse in any band, or the anchor is found for
    fewer than 90% of games.
- **Verdict: CONFIRMED,** every falsification check passed. Nothing is loaded; loading is the user's decision.

## The rule (`syndicate/features/nba/live_resim.py`, "margin anchor")

- **The shift:** the live FULL-GAME margin histogram moves by (closing consensus home margin - the pregame SmartSim
  margin mean) x the share of regulation still to play, and P(home) is re-derived from it. A shifted 0 counts half
  to each side.
- **This is college's rule** (`ncaab/live_resim.py` "margin anchor"), and it reuses college's quote reader,
  closing-line rule, join key and histogram shift.
  - The close: each book's last full-game home spread before the commence, median across books.
  - The pregame margin: `score.margin_mean` of `smart_sim_<date>_<HOME>_<AWAY>.json`.
- **Untouched:** WNBA, segments, totals, live props (the player remainders) and `overtime_prob`.
- **No anchor = today's raw numbers,** with `marginAnchorRefusal` (`no_pregame_sim_margin` / `no_closing_spread`).
  It is not a refusal, which would also take the game's live props down.
- **The switch:** `SYNDICATE_NBA_LIVE_MARGIN_ANCHOR=off` (absent = on).
- **What the lane carries:** `rawModelHomeWinProb` + `marginAnchor`. The history rows carry `p_home_raw` +
  `margin_anchor`. The tick line ends `anchored=N anchor_missing={...}`.
- **The spreads scale follows the lane** (the standard's 4.4 two-part change):
  - The join's hit carries `margin_anchored`.
  - `spreads_prob_scale(sport, anchored=...)` gives NBA 1.57 on an anchored lane and 2.02 on a raw one.
  - The anchor runs in live-odds-worker and the join in refresh-worker, so the two can load in either order and each
    lane still gets the k of its own kind.
  - College lanes are always anchored and their table was fitted that way, so they have no anchored entry.

## The replay (fleet, read-only, the module's own functions on every recorded tick)

`scripts/replay_nba_live_margin_anchor.py` over `live_resim_history` 10-21..11-12. Output:
`C:\tmp\livegrade\load780\replay_anchor_1113.txt`.

**Coverage:** 171 of 171 games have an anchor. The offset averages +0.29, mean absolute 2.42 points; 10 books is
the median.

**Moneyline, against the final** (7,895 ticks / 160 games, the join's Agresti-Coull estimator):

| share of regulation left | ticks | Brier raw | anchored | anchored - raw |
|---|---|---|---|---|
| all | 7,895 | 0.1419 | 0.1355 | **-0.006 +- 0.005** |
| tip (> 0.85) | 746 | 0.2152 | 0.2001 | **-0.015 +- 0.009** |
| early (0.60-0.85) | 1,699 | 0.2025 | 0.1914 | **-0.011 +- 0.008** |
| mid (0.25-0.60) | 3,177 | 0.1418 | 0.1361 | **-0.006 +- 0.005** |
| late (< 0.25) | 2,273 | 0.0728 | 0.0718 | -0.001 +- 0.002 |

**Moneyline, against the market** (the ledger's h2h states at the same game and instant, 3,898 / 160 games):

| | raw | anchored |
|---|---|---|
| model - market, all | +0.016 +- 0.010 | **+0.008 +- 0.006** (halved) |
| tip | +0.043 +- 0.015 | +0.024 +- 0.009 |
| early | +0.029 +- 0.014 | +0.017 +- 0.008 |
| mid | +0.010 +- 0.011 | +0.003 +- 0.007 |
| late | +0.002 +- 0.007 | +0.000 +- 0.006 |
| first state >= 10 pp from the market | 49 of 160 | 33 of 160 |

**Spreads** (21,713 ledger states / 160 games, re-priced through the join's own `price_distribution_market`):

| | raw | anchored |
|---|---|---|
| Brier, anchored - raw | | **-0.009 +- 0.007** |
| model - market, k = 1 | +0.001 +- 0.014 | -0.008 +- 0.010 |
| k fitted (walk-forward, last 4 steps) | 2.147 (2.15-2.44) | **1.568 (1.55-1.68)** |
| walk-forward gain of k vs k = 1 | -0.008 +- 0.008 | -0.003 +- 0.004 |
| model at its k - market | -0.006 +- 0.007 | **-0.011 +- 0.007** (in-sample k) |

## What remains

- **The moneyline still trails the market** by +0.008, concentrated early (+0.024 at tip). The anchor fixes the
  starting margin. What remains is the re-sim's early update, plus the market's information (e.g. late scratches).
- **The NBA spreads k (1.57)** rests on a replay of 20 dates. Re-fit it once anchored lanes exist in the ledger.

## Tests

- `tests/test_nba_live_margin_anchor.py`, 28. Reachability first: off != on through `build_live_lens_snapshot`,
  and the anchored moneyline through the board join.
- Then:
  - the math: the shift, the regulation share, the tie rule, at tip = the market, overtime = no shift;
  - the named no-anchor paths, which keep the lane and its props;
  - WNBA untouched; the switch; the feed-orientation flip; the cache;
  - the history row and the tick line;
  - the spreads k by lane kind, with the switches winning.
- 11 source mutations, each caught. 1,863 pass across the 94 test files that load the join, the ledger or the NBA re-sim.
- `test_nba_live_resim_midnight.py`'s tick-line test now checks every existing field in place, then the anchor
  counts after them.

## Loading (the user's decision)

1. **The anchor:** a fleet ff + a claimed live-odds-worker restart. The NBA re-sim loop runs there.
2. **The anchored k:** the same ff + a claimed refresh-worker restart. The join runs there.

Either order is safe; each lane gets its own kind's k.

**Expected on load:**
- `NBA_LIVE_RESIM_TICK ... anchored=N anchor_missing=-` with N equal to the fresh lanes.
- Lanes carry `marginAnchor` with `appliedOffset` = offset x share left.
- NBA spreads ledger rows read `prob_scale` 1.57.

**Falsified on the fleet if:**
- an NBA game with a pregame artifact and a close shows `anchor_missing`;
- an anchored lane's `rawModelHomeWinProb` is not the sim's own;
- the NBA live moneyline's model - market Brier over the first week is not below the raw replay's +0.016.
