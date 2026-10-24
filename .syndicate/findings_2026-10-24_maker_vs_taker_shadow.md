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

## Results

(not yet run)
