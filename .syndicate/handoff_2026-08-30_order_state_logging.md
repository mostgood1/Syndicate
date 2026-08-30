# Handoff — the `leavesQuantity` instrument, ready to land

**Branch:** `handoff/polymarket-order-state-logging` (commit `d8b6c847`, off `origin/main`).
**To:** whoever holds `polymarket_us_orders.py` — currently the OPEN lane
`polymarket-yes-leg-binding`.
**From:** `polymarket-buy-limit-tick-floor` (session `6475567d`), lane now CLOSED.

## ACTION REQUESTED: ship this with your next deploy

**The user has asked that you carry this in YOUR deploy rather than me taking a
second one.** One deploy, not two, and it is your file.

**Not landed on main deliberately.** That file is your claim and you are mid-work
in it. I already made you resolve one conflict there today; not doing it twice.

    git fetch origin
    git cherry-pick d8b6c847          # or: git merge origin/handoff/polymarket-order-state-logging
    # then land on main and deploy live-odds-worker as you would normally

The service is FREE — I released the `live-odds-worker` claim at 19:2xZ and hold
nothing. `live-odds-worker` currently runs `cc75e1f2`, which already carries your
`8b0d27df`. `refresh-worker` and `web` are still on `165c448f` (an MLB sim was in
flight and I would not kill it).

Conflict risk is low: the change adds one module-level helper above
`round_price_to_tick` and one call line inside the `per_order` branch of
`ORDERS_READ`. It touches nothing in `_resolve_outcome_side`, `order_body`'s
`outcomeSide`, or `_polymarket_resolve_market`.

### The test subject is already waiting

`tsc-mlb-phi-laa-2026-08-30-7pt5` — submitted 19:32:33 at 0.485 against an
on-grid quote of 0.485, `status=submitted`, still `filled=0` eight minutes
later. A known order, at a known price, resting right now. The first
`ORDER_STATE` line for it answers the question outright:

    cum='0'   leaves='<ordered>'   -> NEVER TOUCHED
    cum>'0'   leaves>'0'           -> PARTIAL, STUCK

### Your YES-leg fix is still unverified, and NOT because it failed

30 minutes of watching, zero `POLYMARKET_YES_LEG` lines — but no h2h candidate on
a team-named market ever appeared. The only h2h in the window was
`atc-mls-stl-dal`, outcomes `['Yes','No']`, refused `team_side_not_in_outcomes`.
Not-yet-exercised, NOT inert. Your own warning was right and it still stands.

### One correction you should have: the kill switch is not free

`SYNDICATE_POLYMARKET_YES_LEG_CORROBORATE` is read per-call and defaults
correctly (execute_portfolio:580) — the code is right. But a running process's
environ is fixed at start and a Render restart does not re-inject env vars, so
standing the gate down costs a full deploy cycle, not minutes. Worth knowing
before you rely on it as a fast abort.

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
