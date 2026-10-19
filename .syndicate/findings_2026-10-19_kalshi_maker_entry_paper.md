# Kalshi maker entry (resting bid) vs taker entry: a pre-registered paper study, 2026-10-19

Session 2636b326 (side session of 85438607). Lane `kalshi-maker-entry-paper`. READ-ONLY on the fleet:
no env, cap, order, restart or deploy change. Research jobs at `nice -n 19`. Times Central (CDT = UTC-5).

Question (from `findings_2026-10-19_live_execution_empty_plan_funnel.md`, fix 2): the taker fee at the
venue's own ask is what empties the live plan (533 of 556 Kalshi-quoted sides <= 0 EV net on 10-19, 0 at
>= +2% net, 41 at >= +2% gross). **Does entering as a MAKER (a resting bid, no fee on `quadratic`
series) produce positive-EV positions per line where taker entry produces none, after adverse selection?**

## PRE-REGISTRATION (written and committed BEFORE any fill, close or edge was computed)

What had been looked at when this was written: file SHAPES only (field names, families, point counts,
series fee types). No fair value, fill, close or edge had been computed on any row.

### Data (all fleet, `~/syndicate-prod/data`, read-only)

- **Kalshi book history:** `reports/intelligence/venue_odds/kalshi__<sport>__<date>.json`
  (`venue_daily_odds.record_daily_odds`). Per ticker: `points[]` of `{ts, yes (ask), no (ask), yes_bid,
  no_bid, bid_size, ask_size, volume, ...}`, appended **only when an ask moved**, capped at the LAST 48
  points (fewer under the byte budget). History is complete from the first RETAINED point onward and
  unknown before it.
- **Sportsbook prices (fair):** `<sport>_source/tracking/book_quotes/*.jsonl[.gz]`, the append-on-change
  quote log. Exchange books are excluded from the fair.
- **`clv_price_trail`** (`reports/intelligence/clv_price_trail/*.jsonl`, hourly, 10-17 onward only): a
  robustness check on the fair where it overlaps. It is not the primary fair: it covers only 4 days.
- **Fee type per series:** read live from Kalshi `GET /series/<ticker>` at 2026-10-19T23:06Z
  (`scripts/read_kalshi_fee_params.py`, 122 series, 0 failures).

Per-family date coverage and the intersection are reported first in the results, with the number of
dates the result rests on.

### Population

Every (Kalshi ticker, leg in {yes, no}) such that:
1. the series' live `fee_type == "quadratic"` (maker fill free: the one maker case with evidence,
   `venue_fees.kalshi_maker_fee_dollars`). `KXMLBBGAME` is excluded: it is Mobile Legends, not MLB.
2. it pairs to a sportsbook bet through the PRODUCTION join, `kalshi_board_join.join_kalshi_to_board`,
   run against pseudo-board rows built from that sport's sportsbook `book_quotes` (one row per event,
   market, segment, selection, line, player). The ticker's leg -> board side mapping is the join's own
   `kalshi_side` / `board_side`.
3. the game has started before the study ran (closed), and the decision is PREGAME.

Secondary population, reported separately and never pooled with the primary: the same on
`quadratic_with_maker_fees` series, charged `MAKER_FRACTION = 0.25` of the taker rate. **That fee is
UNVERIFIED** (no fill of ours has ever measured it), so any result there is conditional on it.

### Fair value

Consensus at instant t: for each sportsbook with BOTH sides of the same bet (same line) quoted at or
before t (last value carried forward), proportional de-vig; the fair is the mean across books. At least 2
books, or the instant has no fair. Exchanges (kalshi, polymarket, prophetx, novig, betfair*, smarkets,
matchbook) are excluded. The **consensus close** is the same quantity as of the game's `commence_time`.

### Decision instants and the maker price rule

Decision instants are the leg's recorded points with `ts` in [commence - 24h, commence - 10 min]. At each
instant, in order, the gate is evaluated; the FIRST instant that passes places ONE resting bid for that
(ticker, leg). The order is never re-priced and is cancelled at commence.

    b = min( best_bid_leg + 0.01,  floor_to_cent(fair_t / 1.02),  ask_leg - 0.01 )

placed iff `0.03 <= b <= 0.97` and `fair_t / b - 1 >= 0.02` (the Suggested floor, +2% net; the maker fee
is 0 on this population). `best_bid_leg` is `yes_bid` / `no_bid` at that point; absent counts as 0.

Variant (reported, not primary): **edge-capped bid**, `b = min(floor_to_cent(fair_t / 1.02), ask - 0.01)`,
the highest bid the EV floor allows. Variant floor: +0% instead of +2% (the commit gate's own floor).

### Fill models

- **A, primary (recorded, conservative):** filled at `b` at the first later recorded point, before
  commence, whose ask on our leg is `<= b`. A locked or crossed book cannot exist, so an ask at or below a
  resting bid means the bid was taken. CONSERVATIVE in fill rate, and biased TOWARD adverse selection:
  it sees only fills where the whole book moved down through us, and misses a taker selling into our bid
  while the ask stays put.
- **B, secondary (venue trade prints):** Kalshi's public `GET /markets/trades` for the ticker: filled at
  `b` by the first print after placement and before commence in which a taker SOLD our leg at a price
  `<= b` (leg yes: `taker_side == "no"` and `yes_price <= b`; leg no: `taker_side == "yes"` and
  `no_price <= b`). When `b` did not improve the best bid at placement (we would join a queue), a print
  must be strictly `< b`. Measured only if the endpoint still serves prints for closed markets.
  If it does not, B is reported as unmeasurable.

### Outcomes and the falsifier

Per filled order:
- **realised edge vs close** = `fair_close_leg / b - 1` (per $1 staked; maker fee 0). This is the
  FALSIFIER.
- **adverse selection** = `fair_at_fill - fair_at_placement` (pp), and `fair_close - fair_at_placement`
  for filled versus unfilled orders.
- ex-ante EV at placement, which is >= 2% by construction, so realised / ex-ante is the share of the edge
  that survives selection.

Statistics: event-clustered bootstrap (cluster = the board `event_id`), 2,000 draws, 95% CI. Cells are
sport x market (segment kept in the market name).

**Decision rule, fixed now:**
- **H1 (maker works):** under fill model A, the pooled mean realised edge of fills is > 0 with the CI
  lower bound > 0.
- **Falsified:** the CI upper bound is <= 0. Fills lose to the close: adverse selection eats the edge.
- **Inconclusive:** anything else, reported as inconclusive with its n.
- **Per-line GO:** a sport x market cell is GO only with >= 30 fills across >= 10 events and a CI lower
  bound > 0. A cell short of that is "insufficient", never "no".
- **Taker comparison on the same instants:** taker EV at the ask net of `venue_fees.taker_fee_per_contract`
  (the leg's series multiplier). Count the legs with taker net EV >= 0 / >= 2% at any instant, and their
  realised edge vs close. "Maker yields +EV where taker yields none" is answered as: the count of legs
  maker-filled with realised edge > 0 whose taker net EV was < 0 at every instant, and the pooled realised
  edge on exactly that subset.

No order, env, cap or deploy change follows from this study by itself. A GO is a recommendation for a
paper-mode build, not for live.
