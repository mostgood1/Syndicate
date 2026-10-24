# Maker vs taker on our own live picks (Kalshi + Polymarket US): shadow counterfactual, 2026-10-24

Session 78880f41 (side session of the portfolio endpoint a21617bf). Lane `maker-vs-taker-shadow`.
SHADOW ONLY: no order, env, cap, restart or deploy change. Reads the fleet's live execution ledger,
Kalshi's PUBLIC trade prints and candles, and the fleet's own recorded Polymarket quotes. Runs at nice 19.

## How this differs from what exists

- `kalshi-maker-shadow` (lane `kalshi-maker-shadow-paper`, pre-reg `023f3978`) places paper bids on a
  CONSENSUS fair in three narrow quadratic cells (soccer totals/spreads, NCAAF segment totals). On
  2026-10-24 12:30Z it had 36 counted orders, 18 B-filled, 0 looks. It is untouched by this lane.
- `findings_2026-10-19_kalshi_maker_entry_paper.md` asked the same question on consensus-fair bids and
  found fills won 5.37pp below the close: adverse selection.
- **This study asks it on the positions we actually bought.** Every live taker fill is paired with the
  resting bid we could have posted at the same instant on the same contract.

## PRE-REGISTRATION (written and committed BEFORE any maker fill, maker P&L or maker CLV was computed)

What had been looked at when this was written: ledger field names; counts of live fills by venue, sport
and market; the taker outcome census (Kalshi 254 won / 325 lost / 32 open; Polymarket 53 / 94 / 4, 1 push);
the shapes of Kalshi's `/markets/trades`, `/historical/trades`, candlestick and `/historical/cutoff`
responses on 4 tickers; and that Polymarket US has no public trade-history endpoint (gateway `/book`
only). No counterfactual was run.

### Population

Live execution-ledger rows (`execution_ledger.full_history_orders()`, fleet keyvalue + archive):
`mode == live`, `status == filled`, venue `kalshi` or `polymarket`, `outcome in {won, lost}`. Excluded and
counted: pushes/unsettled, Kalshi `KXMVE*` combos, rows whose leg or instant cannot be read, rows with no
venue quote at the decision instant.

Cell = the live-cell-scorecard's axes (`scripts/live_cell_scorecard.py`, lane `live-cell-scorecard`,
reused not redefined): venue x sport x family x price bucket (<40c, 40-55c, 55-75c, 75c+) x phase
(in_game iff the row carries no `ev_pct`). Game cluster = that script's `game_of`.

### The counterfactual order

At t0 = the live order's `submitted_at`, on the same ticker and leg, same contract count:

- `bid_leg`, `ask_leg` at t0. Kalshi: the last 1-minute candle that ENDED at or before t0
  (`yes_bid.close`, `yes_ask.close`; NO leg = 1 - the opposite YES side). Polymarket: the last
  recorded `venue_odds` point at or before t0.
- **Policy I (PRIMARY), one tick inside:** `b = min(bid_leg + 0.01, fill_price - 0.01)`.
  **Policy J (reported), join:** `b = bid_leg`. Placed only if `0.01 <= b < fill_price`.
- **Rest window:** pregame [t0, min(t0 + 60 min, commence)] PRIMARY, cancelled at kickoff;
  reported: 15 min, and to kickoff with no limit. In-game [t0, t0 + 2 min] PRIMARY; reported 10 min.
- **Fill, PRIMARY = THROUGH (conservative):** Kalshi: the prints in the window in which a taker SOLD our
  leg (leg yes: `taker_side == no`; leg no: `taker_side == yes`) at our-leg price STRICTLY below `b`
  sum to at least our contract count. A print below our bid means the queue at `b` was exhausted.
  **Reported = TOUCH:** the same at `<= b` when `b` improved the bid, `< b` when it joined.
  Polymarket (no prints exist publicly): filled iff a recorded point in the window has `ask_leg < b`
  (THROUGH) / `<= b` (TOUCH). This is a weaker model and is reported separately, never pooled with
  Kalshi for a decision.
- **Fees.** Taker = the ledger's realised `pnl_dollars` (the real fee is in it). Maker, Kalshi: series
  `fee_type == quadratic` -> 0; `quadratic_with_maker_fees` -> `ceil_cent(0.07 x 0.25 x mult x C x P(1-P))`
  (`venue_fees.kalshi_maker_fee_dollars(allow_unverified_maker=True)`; the 0.25 fraction is third-party,
  flagged). Polymarket US maker: fee 0 and rebate 0 (the rebate is volume-tiered; assuming 0 is the
  conservative side).
- **Maker P&L:** filled -> `C x (win ? 1 - b : -b) - maker_fee`; unfilled -> 0.
  **Hybrid H (reported):** unfilled at window end -> take at that instant's `ask_leg` plus taker fee
  (pregame Kalshi only).

### Statistics

- Per position: `delta = maker_pnl - taker_pnl` (dollars). Per cell: n, games, fill rate, taker and
  maker P&L and ROI, mean delta.
- **Adverse selection:** taker per-contract result `(win - fill_price)` on the positions the bid WOULD
  have filled vs the ones it would not, and `win - mid_t0` on maker fills. Negative filled-minus-unfilled
  = the resting bid is picked off on the bets that lose.
- **CLV (pregame):** leg mid at commence (last candle at or before kickoff) minus price paid, taker vs
  maker fills.
- Game-clustered bootstrap, 2,000 draws, seed 20261024, 90% CIs (the live-cell-scorecard's level).

### Out-of-sample split and the decision rule (fixed now)

- **DISCOVER:** `submitted_at` before 2026-10-01T00:00Z. **CONFIRM:** on or after it.
- Primary configuration only: policy I, 60-min / 2-min rest, THROUGH fills, Kalshi prints.
- **MAKER BEATS TAKER in a cell** iff CONFIRM mean delta per position has a game-clustered 90% CI lower
  bound > 0 AND the DISCOVER point estimate is > 0 AND CONFIRM has >= 10 games. Decided per cell;
  pooled numbers are reported, never decided on.
- **Falsified for a cell** iff the CONFIRM 90% CI upper bound on mean delta is <= 0.
- A go-live design is proposed ONLY for cells that pass. It is a recommendation to the user via the
  coordinator; nothing reads it.

## DEVIATION D1 (2026-10-24 ~22:40Z, written BEFORE the full run; outcome-blind)

**What forced it.** A 77-row smoke run of the code showed that every Aug–Sep live row is
`source == venue_rebuild`. That is 551 of the 704 settled live fills: Kalshi 420, Polymarket 131.
Those rows were rebuilt from venue settlements on 10-02, and their `submitted_at` is the SETTLEMENT
instant. At that instant the book is dead: Kalshi candles show bid 0 / ask 1. They have no
`commence_time` and no `requested_price`. **They carry no order instant, so no counterfactual bid can be
placed for them.** Only **153** settled live fills have a real instant: Kalshi 136, Polymarket 17, all
from 10-19 to 10-24. The pre-registered 10-01 split leaves nothing in DISCOVER.

What was seen from the smoke: those 45 simulated rows (35 rebuilt and junk). Of the 10 valid pregame
Kalshi rows, the bid filled 0 of 10 under THROUGH. No other maker number was looked at.

**Amendments (fixed now):**

1. **Drop** `source == venue_rebuild`, and any row without `commence_time`. Count both in the drops.
2. **Instant validity:** a row counts only if the venue ask on its leg at t0 is within 2c of the price we
   paid. Otherwise drop it as `instant_quote_mismatch`. This filter is blind to the outcome. It removes
   rows whose t0 is not when that price was available.
3. **Two populations, each reported and decided on its own:**
   - `live`: the pre-registered one, after drops 1-2.
   - `paper`: `paper:kalshi` and `paper:polymarket` plan rows with a `venue_ticker`, deduped by
     `position_key`. These are the same plan's picks, recorded at the instant the plan priced them;
     955 are settled, 10-02 to 10-24. The `:ladder` books are excluded, because they come from a
     different selection.
4. **Split rule, applied per population:** if DISCOVER (before 10-01) holds less than 30% of the
   population's simulated positions, the split moves to the first date D (00:00Z) such that at
   least 50% of those positions were submitted before D. D is computed from submission dates
   alone, and the report prints it.
5. Everything else stands as pre-registered: policy I, rests, THROUGH, fees, the statistics and the
   decision rule.

## Results (run 2026-10-24 22:26-22:40Z on the fleet, nice 19; code = this lane's `scripts/maker_vs_taker_shadow.py`)

### Answer

**Maker does NOT beat taker out of sample in any cell, so no go-live design is proposed.** No cell
passes the pre-registered rule in either population. One cell is FALSIFIED: live Kalshi spreads,
CONFIRM delta -$2.50/position [-3.51, -1.49], 10 games. Every other cell has a CI that spans 0.

Before kickoff, a resting bid that fills is cheaper than the ask by about 4-5% of stake (one tick plus
the taker fee). No measurable adverse selection was found before kickoff.

In play, fills are adversely selected.

**The cap that matters:** even a fill on every position saves only about 4-5% of stake, and the live
taker book loses about 17-21%. Execution cannot turn these picks profitable. The selection is the
problem.

### Date coverage (stated first, as pre-registered)

| population | positions simulated | games | dates | window | split (D1) | discover / confirm |
|---|---|---|---|---|---|---|
| live Kalshi | 101 | 39 | 6 | 10-19..10-24 | 2026-10-22 | 60 / 41 |
| live Polymarket | 9 | 8 | 4 | 10-20..10-23 | 2026-10-22 | 5 / 4 |
| paper Kalshi | 384 | 139 | 22 | 10-02..10-24 | 2026-10-11 | 231 / 153 |
| paper Polymarket | 121 | 54 | 18 | 10-02..10-24 | 2026-10-11 | 64 / 57 |

- **Live drops:** venue_rebuild with no order instant 552; no commence 34; unsettled 30; leg unresolved 22;
  no quote at t0 16; instant/quote mismatch 5.
- **Paper drops:** duplicate position 342; no ticker 259; unsettled 184; no quote 111; leg unresolved 35;
  mismatch 20.
- **Quote sanity:** at t0 the ask on our leg was within 1c of the price we paid for 110 of 110 live
  and 500 of 505 paper positions.
- **Fee types on Kalshi:** quadratic 49 / 258; quadratic_with_maker_fees 52 / 126. The maker fee on the
  latter is priced at 0.25 x taker, a third-party figure.
- **The -18% live record is mostly unreachable here.** 551 of 704 settled live fills, all of Aug-Sep,
  are venue-rebuilt and carry no order instant.

### Primary configuration (inside one tick, rest 60 min pregame / 2 min in play, THROUGH fills)

| cell | split | n | games | fill | taker ROI | delta $/pos [90% CI] | verdict |
|---|---|---|---|---|---|---|---|
| live Kalshi pregame | confirm | 39 | 18 | 10% | -23.4% | +0.84 [-0.53, +1.95] (discover +0.11) | NOT SHOWN |
| live Kalshi spread | confirm | 10 | 10 | | | **-2.50 [-3.51, -1.49]** | **FALSIFIED** |
| paper Kalshi pregame | confirm | 115 | 52 | 9% | +7.2% | -0.31 [-2.26, +1.67] (discover +0.67) | NOT SHOWN |
| paper Kalshi in play (2 min) | confirm | 38 | 18 | 13% | -20.2% | +3.41 [-0.09, +8.09] (discover +6.61) | NOT SHOWN |
| paper Polymarket pregame | confirm | 36 | 13 | 6% | +5.0% | -0.44 [-3.86, +2.35] (discover +2.77) | NOT SHOWN |

Every sport, family, bucket and full-cell row in `report_{live,paper}.md` is INSUFFICIENT (fewer than 10
CONFIRM games) or NOT SHOWN, apart from the falsified row above.

**Delta is mostly "did not bet".** At 60 minutes the bid fills only 7-10% of the time. The positive
deltas come from unfilled positions, where the counterfactual is "no bet" on picks that lose as taker.
That is a selection effect, not an execution one, and the pre-registered delta cannot tell the two apart.

### What execution alone is worth (pregame, resting to kickoff: the fill-rate ceiling)

| population | fill | saved on filled positions, % of stake | maker book ROI [90% CI] | taker ROI [90% CI] |
|---|---|---|---|---|
| live, both venues | 48/106 (45%) | +4.0% | -15.3% [-40.4, +15.7] | -20.8% [-37.4, -1.2] |
| paper Kalshi | 142/321 (44%) | +4.5% | +2.2% [-18.2, +22.1] | -0.8% [-15.7, +13.2] |
| paper Polymarket | 15/87 (17%) | +5.7% | +5.7% [-51.8, +63.3] | -23.5% [-49.8, +1.3] |

- **The saving is mechanical, not a finding.** It is a tick plus the fee: Kalshi's taker fee is about
  1.75c at 50c, and Polymarket's 0.0695·p(1-p) about 1.7c. So its tight CI is not evidence about outcomes.
- **Adverse selection before kickoff.** The quantity is the taker per-contract result (win - price) on
  positions the bid WOULD fill, minus the same on positions it would not:

  | population | difference [90% CI] |
  |---|---|
  | live | -2.2c [-18.2, +17.9] |
  | paper | +3.2c [-4.0, +10.4] |

  Neither is measurable.
- **In play (2-min rest, paper):** maker fills lost -16.6c per contract, win - bid [-31.1, -0.1],
  17 fills. This
  replicates the in-game-trading and 10-19 findings: do not rest bids in play.
- **CLV is uninformative.** Taker -0.8 to -1.2c, maker fills -0.1 to -1.5c, both against the Kalshi
  mid at kickoff.

### Recommendation (taken to the coordinator as a user decision)

1. **Do not build live maker entry now.** It fails the pre-registered out-of-sample rule, and its
   ceiling (about 4-5% of stake on about 45% of positions) cannot cover a book that loses about 17-21%
   on selection.
2. **Keep it cheap to re-decide.** Kalshi prints are public and permanent, and Polymarket quotes are
   already recorded. So this counterfactual re-runs on any later window with no forward recorder and no
   fleet job: `run.sh` = `dump` + `simulate`. Re-run when CONFIRM reaches >= 30 games per cell.
3. **If a future run passes a cell,** the design to bring is:
   - an env switch defaulting to off;
   - pregame only;
   - post `min(bid + 1c, ask - 1c)` with `expiration_ts = commence` (`order_body_v2` already
     supports this) and the existing kickoff cancel;
   - never re-price, no taker fallback (hybrid H added nothing: +$0.03/pos [-0.00, +0.06] live);
   - no in-play resting bids.

### Caveats

- **THROUGH is conservative on queue position.** TOUCH changed fill rates by 0-6 points. Our sizes are
  1-20 contracts, so print volume was rarely the limit.
- **Polymarket fills come from asks recorded every 3-5 min and capped at the last 48 points.** That
  undercounts fills and drops early points (no_quote 42 + 6).
- **The paper population is the plan's picks under its 10-02..10-24 configurations,** which are not
  today's live gates.
