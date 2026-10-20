# Kalshi maker shadow (PAPER ONLY): pre-registration, 2026-10-20

Session f3969374 (side session of a541bac4). Lane `kalshi-maker-shadow-paper`. Times Central (CDT = UTC-5).

**Written and committed BEFORE the shadow existed, ran, or recorded a single order.** Nothing below was
fitted to shadow data: there is none. The rule, the population and the stop rule come from
`findings_2026-10-19_kalshi_maker_entry_paper.md` (lane `kalshi-maker-entry-paper`, on main at 703bab8c),
which found maker entry NO-GO overall and named this shadow as the one defensible follow-up.

## Why a shadow, and why graded on outcomes

The 10-19 study's pre-registered falsifier (CLV against the consensus close) passed at +3.75%, and
settlement contradicted it: filled orders won **5.37pp less** than the close predicted [-9.48, -0.91],
unfilled +1.40pp. The fill is adversely selected beyond the close, so **CLV is blind for maker fills.**
That miscalibration sat in MLB and WNBA props (now out of season). Soccer (134 fills / 89 events, +1.91pp,
ROI +16.4% [-9.4, +43.5]) and NCAAF 1H totals (27 fills, +6.79pp) were not miscalibrated, but their CIs
span zero. This shadow collects those cells forward and is graded **only on settled outcomes**.

## NO LIVE ORDERS -- by construction, not by flag

- The shadow module and both scripts import no order, execution, portfolio or credential module, and make
  only unauthenticated `GET`s to Kalshi's PUBLIC endpoints (`/series/<s>`, `/markets/trades`,
  `/markets/<ticker>`). A test parses their imports and HTTP calls and fails on anything else.
- There is **no env flag, mode or argument** that changes this. Turning the shadow "live" would need new
  code, a new lane and the user's decision. A GO below is a recommendation to the USER for a live pilot
  decision; nothing reads the verdict.

## Where it runs (worker-owned)

An hourly supervisor job on the fleet (`scripts/local_production.py` `SCHEDULED_JOBS`,
`kalshi-maker-shadow`, `every_minutes=60`), at `nice 19`. No request-path code: web reads nothing it
writes. A daily job (`kalshi-maker-shadow-eval`) runs the evaluation and writes its report.

Hourly, not daily, is measured, not taste. `venue_odds` keeps the LAST 48 points per ticker, appended on
ask moves. On 10-20 (fleet, 12:49Z), 66-93% of game-day soccer and NCAAF markets were at the 48 cap, and the
busiest 2-hour windows held 48 points (in play), so a daily replay would only see the last few hours.
The most points in any 1-hour window was 39 (NCAAF, 10-17/18), under the cap, so an hourly run that scans
only points newer than its last scan loses nothing pre-commence.

Store: `<SYNDICATE_DATA_ROOT>/reports/intelligence/kalshi_maker_shadow/` -- `orders_<game_date>.json` (one
record per ticker-leg), `series_fees.json` (live `GET /series` cache), `runs.jsonl` (one line per run),
`evaluation_<date>.json` and `looks.json` (the evaluation).

## The rule (verbatim from the 10-19 study; NOT re-tuned)

**Population.** Every (Kalshi ticker, leg in {yes, no}) that the PRODUCTION join
(`kalshi_board_join.join_kalshi_to_board`, the fleet's flags) pairs to a sportsbook bet built from that
sport's `book_quotes`, where:

1. the series' live `fee_type == "quadratic"` (maker fill free), read from `GET /series/<s>`; a series
   that cannot be read is skipped and counted, never assumed;
2. the cell is one of: **soccer `totals`**, **soccer `spreads`** (any segment the join yields), or
   **NCAAF `totals` on a quarter/half segment** (`segment != full`);
3. the decision is PREGAME.

**Fair.** Consensus at instant t: for each sportsbook with BOTH sides of the same bet quoted at or before
t (last value carried forward, `captured_at`), proportional de-vig; the fair is the mean across books;
>= 2 books or no fair. Exchanges excluded. **Consensus close** = the same quantity at the game's LATEST
captured `commence_time`.

**Decision instants.** The leg's recorded Kalshi points with `ts` in [commence - 24h, commence - 10 min].
Each run evaluates, in order, only the points newer than the leg's last scanned point; the FIRST point that
passes places ONE resting bid for that (ticker, leg). Never re-priced; cancelled at commence.

    b = min( best_bid_leg + 0.01,  floor_to_cent(fair_t / 1.02),  ask_leg - 0.01 )

placed iff `0.03 <= b <= 0.97` (b <= floor(fair/1.02) makes `fair/b - 1 >= +2%` automatic; maker fee 0).
`best_bid_leg` is `yes_bid` / `no_bid` at that point, absent = 0.

**Fill models.**
- **B, PRIMARY (venue trade prints)** -- `GET /markets/trades` for the ticker, read after commence: filled
  at `b` by the first print after placement and before commence in which a taker SOLD our leg at `<= b`
  (leg yes: `taker_side == "no"` and yes price `<= b`; leg no: `taker_side == "yes"` and no price `<= b`).
  If `b` did not improve the best bid at placement (we joined the queue), the print must be strictly `< b`.
- **A, secondary (recorded asks)** -- filled at the first later recorded point before commence whose ask on
  our leg is `<= b`. Reported, never decision-bearing.

**Recorded per order:** placement instant, `b`, bid/ask/Kalshi mid at placement, fair at placement and its
book count, `observed_at` (the run that recorded it), commence at placement and the final commence, fill A
and fill B instants, fair at each fill, consensus close, Kalshi `result` and `status`.

## Population for the decision (fixed now)

An order counts iff ALL of:
1. **recorded forward**: `observed_at < commence` (a run that catches up after the game started records
   the order, flagged `late_observed`, excluded);
2. **valid placement**: placement instant `<= final commence - 10 min` (an OddsAPI kickoff revision after
   placement voids it: `void_reason = commence_revised`);
3. **settled**: Kalshi `result in {yes, no}` (void/scalar excluded and counted);
4. **has a consensus close**;
5. **not a mis-paired series** (fixed rule, pre-outcome information only): a series whose title marks a
   women's competition (`women`, `femminile`, `frauen`, `feminine`, `feminin`, `(w)`), OR whose placed
   orders have `|fair - Kalshi mid| > 10pp` at placement on more than half of >= 5 orders, is excluded and
   NAMED in the report. (10-19: `KXSERIEAWGAME` paired women's Serie A to men's Serie A rows.)

## Statistics

- `win` = 1 if Kalshi `result` == our leg. Per order: **`win - fair_close`** (pp) and **ROI per $1 =
  `win / b - 1`** (maker fee 0, flat $1 per order).
- Event-clustered bootstrap (cluster = board `event_id`), 2,000 draws, seed 20261020.
- Reported every day: placed, filled (A and B), fill rate, `win - fair_close` for **filled AND unfilled**
  orders, ROI on fills, adverse selection `fair_at_fill - fair_at_placement`, per cell and pooled.

## STOP RULE (fixed now, per cell; primary fill model B)

Cells: `soccer:totals`, `soccer:spreads`, `ncaaf:segment_totals`. Each cell is decided on its own. Pooled
numbers are reported, never decided on: a GO is per line, never market-wide.

**Looks.** A decision is taken ONLY at a look: the first daily evaluation at which the cell's count of
counted, B-filled orders reaches **200**, **400**, then **600**. Its n and result are frozen in
`looks.json`. Daily numbers between looks are descriptive and labelled "not a look".

- **GO** at a look iff, on the cell's B-filled orders:
  - `win - fair_close` CI lower bound **> -1pp**, AND
  - ROI CI lower bound **> 0**, AND
  - >= 50 distinct events;
  with a **99% CI at the 200 and 400 looks** and a **95% CI at the 600 look** (the interim looks pay for
  being early).
- **STOP, NO-GO (futility)** at any look iff (95% CI) the ROI upper bound **< 0** OR the
  `win - fair_close` upper bound **< -1pp**.
- **Otherwise CONTINUE.** At the 600 look, anything short of GO is **NO-GO, not shown**.
- **Calendar stop: 2027-01-31** (end of the college bowl season). A cell that has not reached 600 by then
  takes its final look at whatever n it has (95% CI, same bars) if n >= 200; under 200 it is
  **INSUFFICIENT** -- reported as "not shown", never as "no".

Sizing, so the bar is understood up front: per-order SD of `win - fair` is ~0.5 and of ROI ~1.1 at
b ~ 0.45, so at n = 600 (design effect ~1.2) the 95% half-widths are ~4.4pp and ~9.6%. **A GO needs a point
estimate of roughly +3.4pp vs the close AND ROI near +10%.** The 10-19 soccer read (+1.9pp, ROI +16%)
would not clear it as it stands. The bar is deliberately strict: it is money, and the same study showed a
passing test hiding a -9% ROI.

**Model A, the unfilled orders and the pooled population are reported beside every look and decide
nothing.** If B-filled and A-filled disagree in sign on `win - fair_close` at a look, the report says so.

## What a verdict does

Nothing automatic. GO is a recommendation to the user to decide on a LIVE maker pilot for THAT cell, which
would be a new lane with its own caps. NO-GO stops recording that cell (an edit, logged here).

## Known limits, stated before the data

- Fill B ignores queue position beyond the improve/join rule, and our order never existed: a real order
  would change the queue and might be the print. Fill A sees only ask-change points.
- Flat $1 stakes. The fair is the consensus mean, not the board's own fair (10-19: within 0.07pp median).
- `book_quotes` arrive with capture lag; the fair at t uses only rows captured at or before t.
- The 48-point cap still bounds any leg whose first decision instant came before the shadow's first run.
