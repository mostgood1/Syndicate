# Future-dated live orders: scope, design, measured survival (2026-10-20)

Lane `future-dated-live-orders-scope`, session 0ffeb586 (side session of caps-revamp, 332cb014). **Scope only, no code.**
Read-only on the fleet: no env, cap, restart or deploy change. Fleet code `d3878d69`. Reads 2026-10-20 ~13:00-13:30Z
(8:00-8:30 AM CDT) under refresh-worker's `/proc` environ, at `nice 19`. Scripts are in this session's scratchpad:
`fwd_probe.py`, `fwd_survival.py`, `dup_live_equiv.py`, `surv2.py`, `plans_probe.py`, `venue_fwd_rows.py`.

## Answer first: the premise is half right, and the half that is wrong matters more

1. **Live ALREADY places forward-dated orders.** Today's slate is not today's games. The Layer 2 shortlist for
   date D keeps rows up to `slate_window_days - 1` days out: **6 days for NFL, NCAAF and soccer**, 0 for the rest
   (`layer2_board._sport_horizon_days`, `layer1_board._SLATE_WINDOW_DAYS`). The live plan is committed over that
   shortlist with **no game-date filter anywhere** (`pipeline/portfolio_commit.py:1589` `run_portfolio_commit`,
   `:189` `commit_live_venue_plan`). Measured on the fleet now: the 10-20 shortlist holds 5,213 rows for game days
   10-20..10-26, and Suggested rows on 10-20 (42), 10-22 (2), 10-23 (1) and 10-24 (8). The 10-19 live plan's only
   position, the one refused 14 times `over_max_order_dollars`, was **DEL -3.5 kicking off 10-20**: a forward row.
   What "the executor runs today's date only" really restricts is which PLAN is read, not which games are bet.
2. **So the double-order risk is not a future-design risk. It exists in live today, latent only because volume is
   near zero.** `idempotency_key` hashes `selected_date` (`execution_ledger.py:588-607`), and nothing else in the
   path compares an order with the same bet on an earlier slate: `_blocking_record_for` (`execution_ledger.py`)
   matches the key only (`execution_ledger.py:1772`), `check_order` (`execution_guard.py:850`) has no exposure-per-bet check. A Saturday NCAAF
   game Suggested on Thursday's, Friday's and Saturday's slates is three live orders. Measured on paper (the same code
   path), restricted to what live would do (an order placed while its slate was today): **5.8% of Kalshi positions
   and 5.0% of Polymarket positions were ordered on more than one slate; that was 8.0% / 8.8% of staked dollars;
   one position was ordered 4 times.** Detail below. **This is the one finding here I would act on regardless of the
   rest of the decision.**
3. **The 8 forward Polymarket sides are not blocked by their date. They are blocked by the +2% Suggested floor.**
   I re-derived them on the 10-20 shortlist: 7 Polymarket sides positive after the fee, **all forward (10-22..10-24
   NCAAF), every one `ev_net_of_fee_below_min`**, net +0.18% to +1.80% (the totals under 61.5 @+108 is +1.80%,
   spreads home -20.5 @+108 is +1.30% and also `single_book_fair`). They already reach the plan's INPUT; they fail
   the gate. Kalshi: 77 forward sides positive after the fee, 2 of them Suggested (both 10-24 NCAAF, ~+3.5% net),
   and those two are in the plan input today (the 10-20 Kalshi live plan has `rows_in=13`, 0 positions, refusals
   `below_min_ev_pct` 5 / `net_of_fee` 5). Running the executor on FUTURE slate dates would add almost nothing:
   the 10-21 plan is the 10-20 plan's games plus one more day of horizon. **The lever for these sides is the 0..+2%
   band (user decision 10-13, `min-ev-tuner-shadow`), not the date.**

## 1. Every place the date keys the live path (file:line on `d3878d69` = this worktree's base)

| hop | what keys on the date | effect for a forward bet |
|---|---|---|
| shortlist | `select_shortlist` horizon, `layer2_board.py:5714`, `_within_horizon :5604`, `_sport_horizon_days :5548` | keeps games D..D+6 for nfl/ncaaf/soccer, D only for the rest. Lane `layer2-next-day-horizon` is moving the anchor to the board's own date |
| plan write | `run_portfolio_commit(selected_date)` `portfolio_commit.py:1589`, called per build date from `intelligence_state.py:7682`; live plan file `portfolio_live_plan_<venue>_<date>.json` `:129` | one plan per SLATE date; no game-date filter, so the same game sits in up to 7 consecutive slates' plans |
| plan read | `read_placeable_plan_for_venue(normalized, scope)` `execute_portfolio.py:444`; `read_live_portfolio_plan_for_venue :141` | the executor reads ONE slate's plan |
| executor | `_run_execution_tick` -> `run_execution(central_today_iso(), venue_scope=venue)` `run_live_odds_refresh_worker.py:2612` | only today's slate is ever placed; `OrderRequest.selected_date = today` (`execute_portfolio.py:165`) |
| idempotency | `idempotency_key` = sha1(position_key, **selected_date**, venue, sport, event_id, market, side, line, player) `execution_ledger.py:588`; legacy key `:610` same | **same bet on two slates = two keys = two orders** |
| position identity | `position_key` = identity tuple + side + line + book, **no date, no commence_time** (`shared/portfolio_commit.py:148, :893`) | the right key for "place once"; but a LINE move makes a new position_key (see risks) |
| day caps | `spent_today(selected_date, ...)` `execution_guard.py:514`, used by `check_order :890-919` and seeded in the executor `execute_portfolio.py:535` | because the executor only ever places today's slate, `selected_date == placement day` for every live order. **Caps already charge the day of placement.** This stays true only while the executor reads today's slate alone |
| balance | `_venue_available_dollars`, `_live_stake_since` (stamp-relative, not date-keyed) | not date-keyed; a forward order ties capital up for up to 6 days before it can settle |
| Polymarket order | `_refuse_after_commence` `polymarket_us_orders.py:1037`; GTD expiry at `commence_time` `:737` | pregame-only by construction; a forward order rests up to 6 days and the venue expires it at kickoff |
| Kalshi order | `time_in_force = good_till_canceled` `kalshi_orders.py:340, :523`; no commence check in the builder | **a forward Kalshi order that rests is NOT pregame-only**: it can fill after kickoff at its pregame price. Stale-cancel (`execution_ledger.py ~:3530`, `SYNDICATE_EXECUTION_CANCEL_STALE` default on) cancels on PRICE DRIFT past a band, not at kickoff |
| exit watcher | `execution_exits.py:106` `_DEFAULT_LOOKBACK_DAYS = 3`, filter `selected_date < floor` `:397`, watch eviction `:1117` | a fill placed 4-6 days before its game leaves the exit watcher's window before kickoff |
| live settlement | `venue_settlement.settle_from_venue` reads the venue's own settlement per order | not date-gated; `selected_date` is only a grouping label (`:892`, `:991`) |
| paper settlement | `settle_orders(selected_date)` `paper_settlement.py:412`, today + yesterday from `intelligence_state.py:7775`, then `dates_needing_settlement` stragglers `_STRAGGLER_MAX_AGE_DAYS=14`, `_MAX_DATES=6` (`:892`) | a forward row is graded via the straggler path. Measured: forward paper rows settle at the same rate as same-day (Kalshi 379 of 463 forward vs 390 of 465 same-day) |
| CLV | `order_clv.clv_for_orders(orders, date=selected_date)` -> `compute_clv_for_date(date, sport)` reads openings by `selected_date` | works for forward rows (the opening is recorded under the slate it was published on) |

## 2. Design: a forward bet is placed ONCE, however many slates plan it

Do **not** run the executor on future slate dates. It buys one extra day of horizon and multiplies the duplicate
problem. Keep "the executor places today's slate" and make the bet, not the slate, the unit of identity.

**D1. Cross-slate dedupe (the safety fix; needed now, independent of anything else).** Before `check_order`, the
executor asks the ledger: is there a LIVE order on this `venue` with this `position_key` (or its
`legacy_position_key`) that may be held at the venue, on ANY `selected_date`? If so, refuse by name,
`already_held_other_slate`, with nothing written, and count it in `refused`. "May be held" is
`_blocks_a_new_attempt` (`execution_ledger.py`), reused rather than restated: only `rejected` and a
paused-exchange `failed` free the bet; `submitted`, `filled` and `failed` block.
- Seam: a new `held_position_for(request)` in `execution_ledger.py` next to `_blocking_record_for`, called from
  `execute_portfolio.py` beside the `no_venue_ticker` refusal (before the trim and before `check_order`), live only.
  Paper unchanged, so the paper book stays comparable with its history (or a separate flag for paper, decided later).
- Scan cost: one pass over the live rows already loaded for `spent_today`; live has ~550 rows.
- Why `position_key` and not a new key: it is already the bet's identity, already date-free and commence-free
  (the 2026-08-30 commence-time duplicate fix), and already on every ledger row.
- Why not change `idempotency_key`: removing `selected_date` from it would re-key every open order at once, the
  failure `_legacy_idempotency_key` exists to prevent. A separate, additive refusal cannot re-key anything.
- Top-ups are out of scope: if the later slate wants a BIGGER stake on the same bet, D1 still refuses. Adding to a
  held position is a sizing decision with its own risk, and the user has not asked for it.

**D2. Caps charge the day of placement.** True today by construction (executor places today's slate only, so
`selected_date == placement day`). Make it explicit rather than incidental: `spent_today` filters on the CT date of
`submitted_at` instead of `selected_date`, with `selected_date` as the fallback for a row with no stamp (the
`_order_age_hours` precedent). Under today's executor this is a no-op, which is exactly what its reachability test
must show (below). It only matters if anyone later points the executor at another slate.

**D3. Pregame-only for forward Kalshi orders.** Polymarket is already pregame-only (refuse after commence, GTD at
kickoff). Kalshi is not. Two options, user's choice:
- (a) refuse a Kalshi build when `now >= commence_time` for a row the plan marked pregame (mirror of
  `_refuse_after_commence`), AND cancel any resting live Kalshi order at kickoff in the reconcile tick (a sibling of
  the stale-cancel, keyed on `commence_time` not drift). Kalshi's V2 body has no good-till-date field we use today;
  if the API offers `expiration_ts`, set it to `commence_time` instead of cancelling.
- (b) accept GTC for forward Kalshi orders. Not recommended: a 6-day resting order is the case the Polymarket
  2026-09-11 decision ("EXPIRE AT KICKOFF") was made for.
In-play cells (`nfl:prop`, `ncaaf:totals`) are a deliberate in-play path and stay untouched; D3 applies only to an
order placed while the game is pregame.

**D4. Exit watcher lookback.** `SYNDICATE_EXIT_LOOKBACK_DAYS` (default 3) counts from `selected_date`. For a
forward fill, count from `commence_time` instead (keep the position while `commence_time >= today - lookback`).
Owned by lane `kalshi-exit-path`; hand over, do not take.

**D5. Kalshi shard routing and capital.** Unchanged: `_shard_available_dollars` reads the market's
`exchange_index`. NCAAF/NFL/soccer forward rows will draw on whichever shard holds football/soccer; a forward order
holds that shard's cash for up to 6 days, which compounding-bankroll's capital read already sees (positions are
part of capital, cash is what the guard checks). Worth a line in the watchdog's low-balance alert, nothing more.

**D6. (Optional, only if the user wants MORE forward volume.)** The forward population is gated by the same +2%
Suggested floor as today's. The forward Polymarket sides measured above all sit at +0.2..+1.8% net. That is the
10-13 "one definition" decision and the `min-ev-tuner-shadow` lane's question, per cell. Not part of this build.

## 3. How often does the forward edge survive to kickoff?

**Short answer: against the close, it survives** (same-book CLV +0.96% Kalshi, +1.99% Polymarket, 53% / 61% beat the close, section d). **In the plan, it mostly does not** (9-11% of forward bets are re-planned on game day, a lower bound because a line move changes the key). Realised ROI does not separate forward from same-day.

**Population and coverage.** Paper ledger (live doc 3,000 rows + archive; 10,414 rows total), `mode=paper`. Every
paper row carries `submitted_at` and `commence_time`. Placement days 2026-10-02..10-19 (**18 days**); selected
dates ..10-21; game days ..10-21. All of it is October: the paper ledger with both stamps begins 10-02. Live has
1 order this month (Thornton) and 552 older live rows with no `commence_time`/`submitted_at` pair, so live cannot
answer this. "Forward" = game CT date > placement CT date. Books: `paper:kalshi` and `paper:polymarket` (paper2's
venue-scoped books, the closest thing to the live plan) and `paper` (unrestricted) for context.

**(a) Is the same bet still in the plan on game day?** Live-equivalent subset (orders placed while their slate was
today). A forward-first position "survives" if the same `venue + position_key` is ordered again on the game day's
own slate; eligible only if that venue's book placed anything on the game day.

| book | forward-first | eligible | survived to game-day plan | by lead (1d / 2d / 3d+) | game days |
|---|---|---|---|---|---|
| paper:kalshi | 199 | 190 | **21 (11.1%)** | 4/45, 5/36, 12/109 | 16 |
| paper:polymarket | 93 | 90 | **8 (8.9%)** | 2/15, 0/10, 6/65 | 10 |
| paper | 1,142 | 1,057 | 70 (6.6%) | 15/263, 17/192, 38/602 | 17 |

**Read this as a lower bound on edge survival, not the survival rate.** `position_key` includes the LINE, so a
spread that moved from -3.5 to -4.5 is a "different" position and reads as not surviving even if the edge is
still there. The game-day plan is also capped (`max_positions=25`) and re-ranked every build. What this DOES
measure is the D1 exposure: ~9-11% of forward bets would be ordered again on game day without D1, plus the
intermediate slates (2-3 slate repeats in the duplicate table below).

**(b) Did the dropped ones do worse?** Settled ROI of the FIRST order (paper fills at the plan price, fee-inclusive
fill fields): Kalshi survivors n=16 **+33.0%**, dropped n=120 **+5.7%**; Polymarket survivors n=5 -1.3%, dropped
n=56 -3.0%. Small n; it does not show that "fell out of the plan" means "the edge was gone".

**(c) Forward vs same-day, settled ROI (all paper rows, per order):**

| book | same-day n / stake / ROI | forward n / stake / ROI | mean EV at entry (same / fwd) |
|---|---|---|---|
| paper:kalshi | 390 / $4,650 / **-7.76%** | 379 / $4,538 / **-1.69%** | +3.80% / +3.83% |
| paper:polymarket | 244 / $3,778 / **-13.38%** | 163 / $2,260 / **-17.45%** | +4.03% / +3.77% |
| paper | 2,128 / $19,856 / -3.65% | 1,952 / $16,662 / -2.35% | +3.71% / +3.32% |

Forward is not worse than same-day on Kalshi or the unrestricted book; it is worse on Polymarket (n=163,
12 game days). Every one of these is negative against a +3.3..+4.0% EV at entry, which is the existing
`published-negative-ev` / EV-overstatement finding, not something forward-dating adds. ~3 weeks of one sport mix
(NCAAF/NFL dominate the forward rows: Kalshi eligible 135 NCAAF, 50 NFL, 5 soccer) cannot separate a 6-point ROI gap
from noise.

**(d) CLV (entry vs close)** -- `order_clv.clv_for_orders` per slate date over every paper:kalshi and
paper:polymarket row (the repo's own join; entry = paper fill price; scope never pooled). Headline = SAME-BOOK only:

| book | bucket | resolved / orders | same-book n | mean CLV | median | beat close |
|---|---|---|---|---|---|---|
| paper:kalshi | forward | 284 / 463 (61%) | 274 | **+0.96%** | +0.94% | 146/274 (53%) |
| paper:kalshi | same-day | 169 / 465 (36%) | 112 | +0.40% | 0.00% | 53/112 (47%) |
| paper:polymarket | forward | 102 / 200 (51%) | 101 | **+1.99%** | +1.13% | 62/101 (61%) |
| paper:polymarket | same-day | 98 / 253 (39%) | 59 | +4.95% | +0.98% | 33/59 (56%) |

The rest is `no_close_for_market`. `book_agnostic_close` / `different_book_close` rows (n=1..53) read +2.6..+5.6% and
are excluded from the headline for `order_clv`'s stated reason (best-of-N vs single draw, biased up).
**Reading:** a forward entry beats its own book's close slightly more often than not, by about +1% (Kalshi) and +2%
mean / +1.1% median (Polymarket). The edge does not vanish between a forward placement and kickoff; it is also far
smaller than the +3.8% EV claimed at entry, which is the known EV-overstatement, not a forward effect. The
Polymarket same-day mean (+4.95%) is carried by a tail (median +0.98%). Coverage: placements 10-02..10-19, 18 days,
NCAAF/NFL heavy; one close per order, so CLV here is per order, not per independent game.

**(e) Cross-slate duplicates, live-equivalent** (`dup_live_equiv.py`; the D1 exposure):

| book | orders | positions | on >1 slate | extra orders | extra stake | slates per position |
|---|---|---|---|---|---|---|
| paper:kalshi | 681 | 642 | 37 (5.8%) | 39 | $612 of $7,628 (8.0%) | 1:605, 2:35, 3:2 |
| paper:polymarket | 359 | 338 | 17 (5.0%) | 21 | $465 of $5,307 (8.8%) | 1:321, 2:14, 3:2, 4:1 |
| paper | 3,500 | 3,330 | 160 (4.8%) | 170 | $2,370 of $30,875 (7.7%) | 1:3170, 2:151, 3:8, 4:1 |

By sport, the Kalshi repeats are NCAAF 29, NFL 8; Polymarket NCAAF 12, NFL 3, soccer 2. Counting every paper slate
including next-day builds (which paper places and live does not) the rate is 19-24%; that is the upper bound if the
executor were ever pointed at future slates, and the reason D1 forbids doing so without it.

## 4. Risks, and the reachability tests the build needs

Risks:
- **R1 Double order (exists now).** Covered by D1. Until D1 ships, every live NCAAF/NFL/soccer fill is exposed to a
  repeat on the next slate.
- **R2 Kalshi resting through kickoff.** Covered by D3. Today's live volume is ~1 order, so it is unexercised, not safe.
- **R3 Line moves defeat D1.** A new line is a new `position_key`, so D1 lets "home -3.5" on Thursday and "home -4.5"
  on Saturday both through. That is two different bets at two prices, defensible, but it is correlated exposure on
  one game. If the user wants one bet per GAME-SIDE, D1 keys on `(venue, sport, event_id, market, side, player)`
  without the line instead. User's call; I would start with `position_key` (exact) and count how often the coarser
  key would also have fired, from the refusal log, before tightening.
- **R4 Far-dated venue books are thin.** `findings_2026-10-19_polymarket_side_price_mirroring`: in far-dated
  Polymarket captures both legs sit at the cap (median sum 1.98). Every forward Polymarket order is GTD and
  `_refuse_after_commence`d, so the worst case is no fill, but a "+EV" side priced off a one-sided book is a
  stale-quote risk. `single_book_fair` already refuses one of the 7 measured sides.
- **R5 Capital lock-up.** A forward fill holds venue cash up to 6 days. With caps at ~$122/day Kalshi, a Thursday
  NCAAF fill reduces Friday's available shard cash. The guard sees it (balance stamp); the cost is opportunity.
- **R6 Settlement and exits.** Paper settles forward rows fine (stragglers). Live settles from the venue, not by
  date. The exit watcher's 3-day lookback is the one date bug (D4).
- **R7 Edge decay is small on CLV, unknown on ROI.** Forward same-book CLV is +0.96% (Kalshi, n=274) and +1.99% (Polymarket, n=101), so the edge mostly survives to the close; realised ROI is negative for both buckets, and three weeks of NCAAF/NFL-heavy paper cannot separate forward from same-day on ROI.

Reachability tests (`off != on`, per the model-engine standard; one per mechanism, each asserting the branch ran):
- **T1 (D1):** a ledger with a filled LIVE order for `position_key=P, selected_date=D-1`; today's plan holds P.
  Flag off -> `place_order` is called (the double order happens, asserted through the submitter double's call count).
  Flag on -> `refused == {"already_held_other_slate": 1}`, submitter called 0 times, no ledger row written.
  Plus: a `rejected` row for P does NOT block; a `submitted` row does; a different venue does not; a paper row does not.
- **T2 (D2):** an order whose `submitted_at` is D but `selected_date` is D+1. Off -> `spent_today(D)` excludes it;
  on -> includes it. And the no-op claim: over today's real ledger, the on/off totals are equal (asserted, not
  assumed), because every live row has `selected_date == submitted_at` CT date.
- **T3 (D3):** a Kalshi request with `commence_time` in the past and a pregame plan row: off -> builds; on ->
  `OrderBuildError("game_started")`. A resting live Kalshi row past kickoff: off -> not cancelled; on -> `cancel_order`
  called once.
- **T4 (D4):** a fill with `selected_date = today-5`, `commence_time = today+1`: off -> `outside_lookback`; on -> watched.
- **Fleet reading after D1 ships:** a `REFUSED ... already_held_other_slate` line (or `refused` key) on a slate where
  the ledger already holds that position. With live volume ~0 this may take days; schedule the reading, do not
  wait in a session.

## What I would recommend (the decision is the user's)

1. **Build D1 now, flag default ON for live**, as a safety fix. It touches `pipeline/execute_portfolio.py` (claimed
   by lane `caps-revamp`, trim step only) and `execution_ledger.py`; coordinate the claim.
2. Build D3 with it (Kalshi pregame orders expire at kickoff) if forward Kalshi orders are wanted at all.
3. D2 and D4 are cheap and belong in the same change set; D4 goes through `kalshi-exit-path`.
4. Do not point the executor at future slates. More forward volume comes from the EV band (D6), which is the
   min-ev-tuner question.

## Believed, not verified

- The 7 Polymarket / 77 Kalshi forward sides use the board's captured `book_prices` and my own fee arithmetic
  (`venue_fees.polymarket_fee_dollars` / `kalshi_taker_fee_dollars`, 0.07 multiplier where the series was unknown);
  the board's own `ev_net_of_fee_below_min` agrees on every one I printed.
- Paper fills at the plan price with no queue, so paper says nothing about whether a far-dated venue order fills.
- The survival measure is keyed on `position_key` and undercounts survival across line moves (above).
