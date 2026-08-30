# Handoff — Polymarket YES-leg binding: SCOPE GRANTED, and a rebase you must do first

**To:** the session working `#595` step 3 / lane `polymarket-yes-leg-binding`
(display title "Layer 2 board opportunities and scoring", session `local_4465737c`).
**From:** lane `polymarket-buy-limit-tick-floor`, session `6475567d` (syndicate-04).
**Why this is a file and not a message:** two SendMessage attempts failed —
`local_4465737c...` and the display title are both unreachable as agent names,
and the id on the lane block (`5611932c`) is not in the session roster even with
archived included. I will not guess at a `syndicate-XX` name and send a rebase
instruction to the wrong lane.

## Answer: (b). Take them.

Take `_resolve_outcome_side` and `_polymarket_resolve_market`. I keep
`order_body`'s tick work, which is DONE and landed. Your evidence on the YES-leg
question is stronger than anything I have, and I have no further plans in those
two functions. I am not blocking you.

## REBASE FIRST — `db2252b0` is on origin/main and touches all three files

Landed 2026-08-30, including the exact function you asked for.

### Inside `_polymarket_resolve_market` — this is what will conflict

- `tick` / `min_qty` resolution MOVED UP out of the tail, to just below
  `fetched_at`, into locals `tick_value` / `min_qty_value`.
- The price is snapped to the tick BEFORE the slippage check, so the guard
  judges the price actually sent. It previously checked the raw quote and let
  up to a full tick past a tolerance whose default is 3 cents.
- The tail collapsed to `return (slug, price, tick_value, min_qty_value, outcome_index)`.
- `POLYMARKET_ARTIFACT_PRICE` gained `quoted=`, `tick=`, `snapped=`.
- New line `POLYMARKET_TICK_UNREADABLE` — an unreadable tick leaves the quote
  untouched and lets `order_body` raise, which is the right place for it.

Your corroboration gate still lands naturally there: `slug`, `outcomes`,
`resolution` and `_side_for_team` are all still in scope and I moved none of them.

### In `order_body` / the helper, if you call them

- `round_price_to_tick(price, tick)` now takes a REQUIRED keyword-only
  `direction` — `"up"` or `"down"`. **No default.** Two positional args raise
  `TypeError`; an unknown value raises `OrderBuildError("tick_direction_unknown")`.
- `outcomeSide` at ~:484 is UNTOUCHED. Yours.
- Two new refusals near the price block: a sub-tick quote is refused explicitly
  (it used to fall out for free by flooring to zero), and
  `price_out_of_range_after_snap` (a ceil can leave (0,1): 0.995 on a 0.01 tick).

Why it changed: the helper floored a BUY, putting our bid under the venue's own
ask. `tsc-mlb-lad-det-2026-08-30-7pt5` quoted 0.515 on a 0.01 tick, sent as
`submitted_limit=0.51`, `filled=0.0`. The floor's rationale treated the limit as
the price paid; it is a CAP, and this venue price-improves — `C4N3GPYA4GNQ` was
submitted at 0.51 and filled at `avgPx=0.4900`.

## On your point 5 (cle-laa graded `won` on BOTH sides) — a lead, not a finding

`position_key()` in `portfolio_commit.py` hashes an identity field set the owner
CHANGED in `ec56b7ef`: `commence_time` was removed, with
`_LEGACY_POSITION_IDENTITY_FIELDS` / `legacy_position_key()` added for the old
shape. Two rows for one game minted under different key generations is a
mechanism that yields exactly that pair, and their grades would then be computed
independently — which is how both can read `won`. **I have not tested this
against `cle-laa`.** Your conclusion holds either way: use venue `held_side`,
not ledger `outcome`.

## One caution on your design, which I still think is correct

The gate REFUSES on disagreement, and your own sample has `outcomes` reversed vs
slug on 4 of 9. If that rate holds, a large share of moneylines will keep not
placing — the failure moves from *wrong side* to *no order*. That is the right
direction for money, but it will not read as "moneylines fixed" on the board.
State the expected refusal rate up front so it is not mistaken for a regression.

## A third cause, owned by neither of us

My fix explains only 2 of the 3 orders resting on 08-30. The third
(`tsc-lal-cel-ath-2026-08-30-2pt5`) was quoted 0.44, sent 0.44 — already on the
tick grid — and rested anyway. The slate row carries `prices[]`, one probability
per outcome, and NO bid/ask/book, while Kalshi prices off an explicit
`no_ask_dollars`. So we may be bidding a mid, which never crosses. Fixing it
needs a live orderbook read in `polymarket_us_markets.py`, held by
`live-venue-order-placement`. Flagged so it does not fall between us.

## Deploy

`db2252b0` is landed but NOT deployed — `autoDeploy` is off and the order path
runs on live-odds-worker. The deploy decision is open with the user. If you want
your YES-leg fix in the same deploy, say so and I will hold.
