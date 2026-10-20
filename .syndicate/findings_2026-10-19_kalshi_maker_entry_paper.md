# Kalshi maker entry (resting bid) vs taker entry: a pre-registered paper study, 2026-10-19

Session 2636b326 (side session of 85438607). Lane `kalshi-maker-entry-paper`. READ-ONLY on the fleet:
no env, cap, order, restart or deploy change. Research jobs at `nice -n 19`. Times Central (CDT = UTC-5).

Question (from `findings_2026-10-19_live_execution_empty_plan_funnel.md`, fix 2): the taker fee at the
venue's own ask is what empties the live plan (533 of 556 Kalshi-quoted sides <= 0 EV net on 10-19, 0 at
>= +2% net, 41 at >= +2% gross). **Does entering as a MAKER (a resting bid, no fee on `quadratic`
series) produce positive-EV positions per line where taker entry produces none, after adverse selection?**

## Answer: NO-GO for live maker entry. The pre-registered test passes, but the falsifier turned out to be blind

1. **As pre-registered (CLV against the consensus close, fill model A), H1 holds.** 2,695 resting bids,
   554 filled (20.6%). Realised edge vs the close was **+3.75% [+2.62, +5.16]**, 151 events. Without three
   mis-paired series (below) it was +3.21% [+2.43, +3.96]. Five sport x market cells meet the per-line GO
   bar. Fill model B (trade prints): 36.7% filled, +9.32% [+5.34, +15.40].
2. **Settlement contradicts it, and says why.** This check was not pre-registered. Over all 2,676 settled
   orders, the consensus close is calibrated: 1,325 wins against 1,324.7 expected. **Filling splits that
   calibrated population into losers and winners.** Filled orders won **5.37pp less** than the close
   predicted, [-9.48, -0.91] (model A; model B -3.24pp [-5.73, -0.80]). Unfilled orders won 1.40pp more.
   Realised ROI on fills: **A -9.2% [-21.2, +4.7]; B -4.0% [-11.4, +3.6]; edge-capped B -7.0% [-13.5,
   -1.2]**. The counterparties who sell into our bid know something the sportsbook close does not. So
   CLV against the consensus close is **not a valid falsifier for maker fills**. The pre-registered decision
   rule could not see the adverse selection that decides P&L.
3. **The direct question, even on the CLV basis: no.** On lines where the taker never reached +2% net (the
   lines the live plan never sees), maker fills realised **+0.79% [+0.24, +1.36]**, under the 2% floor
   before the outcome-level selection above. Where the taker never reached 0, they realised **+0.44%
   [-0.19, +1.04]**. The maker's CLV edge concentrates on lines where the TAKER also had >= +2% at some
   instant: +6.92%, 218 fills. Those taker entries lose against outcomes too: 360 entries, -4.34pp against
   the close [-9.22, +1.69], ROI -8.2% [-23.7, +11.7].
4. **The evidence is from sports that are now over.** MLB (postseason props, 26 events) and WNBA (9 events)
   are 70% of the fills, and they carry the miscalibration: filled MLB -8.43pp [-14.87, -1.83], ROI
   -20.4% [-36.6, -2.0]; WNBA -9.39pp [-15.87, -1.21]. Soccer (134 fills, 89 events, +1.91pp, ROI +16.4%
   [-9.4, +43.5]) and NCAAF 1H totals (27 fills, +6.79pp) are not miscalibrated, but their CIs span zero.
   Today's slate has no other quadratic population: the production join reaches **0** quadratic NBA or
   NFL legs. NFL props/segments are `unmapped_series` (9,236), and NBA's joined legs are all maker-fee
   full-game series.

**Recommendation:** do not build live maker entry on this evidence. The one defensible follow-up is a
PAPER maker shadow, graded on OUTCOMES rather than CLV, scoped per line to soccer totals/spreads and
NCAAF segment totals: the two cells where fills were not adversely selected. It needs weeks of settled
fills to resolve +/-5pp.

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

## RESULTS (computed after the pre-registration was on main at `2eac1e10`)

Run 6:31 to 7:00 PM CT 10-19 [23:31Z to 00:00Z]. Fleet code `affc9a7b` (the join), data root
`~/syndicate-prod/data`, `nice -n 19`. Scripts and raw reports are in the session notes folder
`side-session-notes/local_85438607-.../kalshi_maker_entry_paper/` (`maker_study.py` extracts on the fleet,
`analyze.py` holds the pre-registered rules, `robust.py` / `calib.py` the declared extra cuts).

### Per-family date coverage (game dates 09-30..10-19; the result rests on 20 dates)

| sport | venue_odds kalshi dates | book_quotes commence dates | intersection | joined legs | quadratic legs | with a fair at a decision instant |
|---|---|---|---|---|---|---|
| mlb | 19 (09-30..10-19) | 18 (09-30..10-18) | 17 | 5,678 | 5,660 | **1,610** on 15 dates, **27 events** |
| wnba | 8 | 10 | 7 | 1,415 | 1,397 | **608** on 7 dates, **9 events** |
| soccer | 16 | 14 | 11 | 1,402 | 1,182 | **319** on 11 dates, 111 events |
| ncaaf | 14 | 14 | 12 | 9,790 | 1,154 | **158** on 11 dates, 72 events (1H totals only) |
| nba | 14 | 15 | 14 | 2,852 | **0** (joined legs are all maker-fee game series) | 0 |
| nfl | 9 | 11 | 6 | 914 | **0** (props/segments `unmapped_series` 9,236) | 0 |
| nhl | 20 | 20 | 20 | **0** (`recognised_but_no_board_market` 1,715, `unmapped_series` 1,381) | 0 | 0 |

`clv_price_trail` covers 10-17T00..10-21 only. Of the 9,393 quadratic legs, 3,522 had no Kalshi point
inside [commence - 24h, commence - 10 min]. Another 3,176 had points but fewer than 2 books two-sided.

### Fee types (live `GET /series`, 23:06Z, 122 series, 0 failures)

Every NCAAF/NFL/NBA full-game game/spread/total series is `quadratic_with_maker_fees`, as are the
NHL/MLB/WNBA game series and the EPL-tier soccer game series. Everything else is `quadratic`, including
every prop, every segment (quarter/half/F5) series, `KXMLBSPREAD`/`KXMLBTOTAL`, `KXNHLSPREAD`, soccer
spreads/totals, `KXUELGAME`/`KXUECLGAME`, and `KXWNBASPREAD`/`KXWNBATOTAL`. The 10-19 funnel's 214 NCAAF
Kalshi sides are mostly maker-fee series.

### Primary and variants (quadratic; R1 = without the 3 mis-paired series)

| config | placed | filled | rate | realised edge vs close | c/contract | adverse sel. at fill | fair drift to close: filled / unfilled |
|---|---|---|---|---|---|---|---|
| **A, bid+1c, +2% (as registered)** | 2,695 | 554 | 20.6% | **+3.75% [+2.62, +5.16]** | +0.77c | -0.54pp | -1.19pp / +0.30pp |
| A R1 | 2,692 | 551 | 20.5% | +3.21% [+2.43, +3.96] | +0.70c | -0.55pp | -1.20 / +0.30 |
| A R1, 0.15 <= b <= 0.85 | 2,511 | 535 | 21.3% | +2.43% [+1.72, +3.06] | +0.66c | -0.56pp | |
| A edge-capped bid | 2,692 | 751 | 27.9% | +2.42% [+1.74, +3.01] | +0.51c | -0.48pp | |
| A floor 0% | 2,692 | 734 | 27.3% | +2.20% [+1.56, +2.77] | +0.39c | -0.37pp | |
| **B (trade prints), bid+1c, +2%** | 2,692 | 989 | 36.7% | +9.32% [+5.34, +15.40] | +1.80c | -0.25pp | -0.58 / +0.33 |
| B R1, 0.15 <= b <= 0.85 | 2,511 | 964 | 38.4% | +4.40% [+3.71, +5.10] | +1.56c | | |
| B edge-capped | 2,692 | 1,260 | 46.8% | +3.25% [+2.87, +3.58] | +1.12c | | |
| secondary: maker-fee series, 0.25 UNVERIFIED (A) | 652 | 163 | 25.0% | +2.16% [+0.88, +3.42] | +1.05c | -0.76pp | |

The percent mean is tail-heavy: legs bid at 4 to 7c (F5 "1+ runs" NO) reach +30% to +90%. The c/contract
and price-band rows are the robust readings. The ex-ante EV at placement averaged +6.3% (A). About 60% of it
survives to the close on the CLV basis.

Per-line cells under the pre-registered bar (A, >= 30 fills, >= 10 events, CI lower > 0): **GO** for
`mlb:batter_hits` (+2.37%, 38 fills/16 events), `mlb:strikeouts` (+2.87%, 46/21), `mlb:totals:first5`
(+8.67%, 45/13), `soccer:h2h` (+9.75% [+0.67, +23.6], 42/27; 3 of its fills are the mis-paired women's
series), `soccer:totals` (+1.08% [+0.24, +1.90], 76/65). Every other cell is insufficient. **Every GO
cell except soccer's is in a sport whose fills are miscalibrated on outcomes (next section).**

### Settlement, calibration and P&L (NOT pre-registered; Kalshi `GET /markets/<ticker>` `result`)

| subset | settled n / events | wins | E[consensus close] | E[Kalshi pre-close mid] | wins - close, per order | ROI per $1 |
|---|---|---|---|---|---|---|
| A filled | 548 / 151 | 198 | 227.4 | 218.3 | **-5.37pp [-9.48, -0.91]** | -9.2% [-21.2, +4.7] |
| A unfilled | 2,128 / 218 | 1,127 | 1,097.3 | 1,099.6 | +1.40pp [+0.22, +2.44] | |
| B filled | 984 / 161 | 418 | 449.9 | 440.2 | **-3.24pp [-5.73, -0.80]** | -4.0% [-11.4, +3.6] |
| B unfilled | 1,692 / 208 | 907 | 874.8 | 877.6 | +1.90pp [+0.31, +3.42] | |
| A filled mlb | 261 / 26 | 89 | 111.0 | 106.1 | -8.43pp [-14.87, -1.83] | -20.4% [-36.6, -2.0] |
| A filled wnba | 126 / 9 | 37 | 48.8 | 46.8 | -9.39pp [-15.87, -1.21] | -18.9% [-42.3, +10.0] |
| A filled soccer | 134 / 89 | 57 | 54.4 | 53.0 | +1.91pp [-5.56, +8.94] | +16.4% [-9.4, +43.5] |
| A filled ncaaf | 27 / 27 | 15 | 13.2 | 12.4 | +6.79pp [-11.99, +25.71] | +17.8% [-22.0, +57.7] |
| B edge-capped filled | 1,255 / 162 | 538 | 578.0 | | | **-7.0% [-13.5, -1.2]** |
| taker >= +2% net entries | 360 / - | 112 | 127.6 | | -4.34pp [-9.22, +1.69] | -8.2% [-23.7, +11.7] |

**Kalshi's own pre-kickoff mid over-predicts the filled orders too** (218.3 against 198 wins). The
selection survives Kalshi's own close as well as the books'. It is information that arrives after the
close or that neither market priced, and the fill selects on it. This holds within MLB and WNBA props; it
is not shown for soccer or NCAAF.

### Fair-basis check (pre-registered robustness): `clv_price_trail`

On 188 placed orders (54 events) inside the trail's window, the board's own fair minus this study's
consensus fair at placement is median **+0.07pp** (p10 -0.88, p90 +1.21). The study's fair is the board's
fair to within a point. The result is not an artefact of a different fair.

## Corrections made during the run (all before any outcome was read)

- **`commence_time` must be the LATEST captured value.** The first extraction kept each event's
  first-seen `commence_time`. OddsAPI revises college kickoffs: OSU@IND 10-17 carried a placeholder 23:30Z
  against a real 16:00Z, so in-play Kalshi prices (0.42 to 0.86 to 0.01 in two hours) were read as
  pregame. 17,361 of 22,051 legs' events had more than one commence value. That first pass is discarded.
  Its numbers (+4.38% A) were never used.
- **Mis-paired series, excluded in R1 and named here:** `KXSERIEAWGAME` (Serie A Femminile) pairs to men's
  Serie A board rows: 70% of its instants are off by more than 10pp, and its 3 fills show +103% "edge".
  `KXEREDIVISIEWGAME` (women's Eredivisie) and `KXBBLGAME` (basketball Bundesliga) are excluded by the
  same rule. **This is the PRODUCTION join** (`kalshi_board_join` at `affc9a7b`, the fleet's live flags),
  so the live plan could pair them the same way. Recorded as a lead.

## Believed, not verified

- Fill model A sees only ask-change points (`venue_odds` appends on an ask move and keeps the last 48).
  Model B uses venue trade prints and ignores queue position beyond the improve/join rule.
- Stakes are flat $1 per order. A Kelly-sized book would weight the long shots differently.
- The settlement read is unregistered and noisy. Its CIs come from 151 to 161 events, 35 of them MLB and
  WNBA. The pooled filled-vs-close miscalibration excludes zero in both fill models. The per-sport split is
  suggestive, not decisive.
