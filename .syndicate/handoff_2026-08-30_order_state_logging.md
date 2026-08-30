# Handoff — the `leavesQuantity` instrument, ready to land

**Branch:** `handoff/polymarket-order-state-logging` (commit `d8b6c847`, off `origin/main`).
**To:** whoever holds `polymarket_us_orders.py` — currently the OPEN lane
`polymarket-yes-leg-binding`.
**From:** `polymarket-buy-limit-tick-floor` (session `6475567d`), lane now CLOSED.

**Not landed on main deliberately.** That file is your claim and you are mid-work
in it. I already made you resolve one conflict there today; not doing it twice.
Cherry-pick `d8b6c847` whenever it suits, or tell me to land it.

## What it adds

One line per order in the `per_order` branch of `ORDERS_READ`:

    [polymarket_us_orders] ORDER_STATE mode=per_order order=... slug='...'
      state='order_state_new' side=... action=... price={'value': '0.51'}
      cum='0' leaves='10.66' avgPx='0.0000'

`ORDERS_READ` was already printing `keys=[...]` — the NAMES of these fields and
never the VALUES. Both numbers were fetched on every poll and thrown away.

## Why it is the next reading

It separates the only two stories a resting order can tell, which nothing in
this system could distinguish:

    cum == 0 and leaves == ordered  ->  NEVER TOUCHED   (no size at our price)
    cum  > 0 and leaves  > 0        ->  PARTIAL, STUCK  (not enough size)

Different causes, different fixes.

## What has already been refuted, so nobody re-runs it

Three sessions proposed three mechanisms for Polymarket's unfilled orders on
2026-08-30. **Measurement killed all three:**

- **tick-size floor** — 0 of 9 quotes off-grid after deploying the "fix"; it
  never fired. The submit-time quote for `tsc-mlb-lad-det-2026-08-30-7pt5` was
  0.51 and we sent 0.51 (`price=0.51` at 17:00:45, 17:08:12, 17:12:57, 17:18:54,
  17:19:27). The 0.515 that story rested on was read 30 minutes LATER. Mine, and
  retracted in `learnings.md`.
- **stale ask** — the artifact was **44 seconds** old at submit
  (`fetched_at` 17:18:42, submit 17:19:27).
- **bidding a mid** — `prices[]` sums to **1.005–1.030 across 8 binary markets**,
  never exactly 1.0. That overround is an ASK signature; a mid or normalized
  probability sums to 1.

And the quote did not move: it sat at 0.51 through 17:24:52, five minutes after
we bid 0.51, and still no fill.

## The live hypothesis — untested, stated as a hypothesis

Per-market liquidity: the quote exists but has no resting size behind it at our
quantity. **Not size alone** — `sea-tor` filled 11.17 contracts at 0.435 while
`lad-det` rested at 10.66. `ORDER_STATE` is what tests it.

## Scope note

`per_order` branch ONLY. The book branch's comment says it logs shape "not
values" because it can carry orders that are not ours. That reasoning still
holds; I left it alone.
