# Polymarket stale cancel — build + PRE-REGISTRATION (lane `polymarket-stale-cancel`, 11-21)

The user's words, relayed verbatim by the fleet-watcher (via the NCAAF backtesting session):
- 11-21 ~11:10 AM CT: "yes, add the Polymarket stale cancel to the 12-08 queue"
- 11:58 AM CT: "yes, ask the portfolio session to build it"

That covers **building and queueing, not loading**. It is a **BETTING CHANGE**, because it changes which live bets are
held and lets the executor re-place a bet. It loads only in the **Tue 12-08 window (2-7 AM CST)**, on the user's final
yes in this session's chat. Counts and percentages only (the repo is public).

## Why

- **The case (11-21):** order `ac07e83e`, an NBA alternate spread on Polymarket, was sent at 12:50Z as a taker costing
  0.56. It rested untouched (`ORDER_STATE_NEW`, cum 0) until its good-till-date expiry at 01:10Z. That held its
  idempotency key for about 12 h, so the bet could not be re-evaluated at a price that existed.
  (`findings_2026-11-21_portfolio_monitor.md`, 10:00 AM.)
- **Kalshi's pass doesn't cover it:** `execution_ledger.cancel_stale_resting_orders` is Kalshi-only (Kalshi cancel,
  Kalshi tickers). It also runs **only from the live-odds-worker boot dump** (`_live_ledger_at_boot`, one call), so it
  isn't a periodic pass on Kalshi either. The executor's per-tick reconcile in `pipeline/execute_portfolio.py` is the
  only per-tick read of what rests.

## Baseline, measured before predicting

The live-odds-worker log window 11-20 16:02Z - 11-21 18:06Z (about 26 h; one rotation back) has `ORDER_STATE` lines for
**51** Polymarket orders. **50** were never seen resting untouched, and **1** (the one above) rested untouched for
**>= 4 h**. The ledger cannot give a longer baseline: its payload lists only filled and open Polymarket orders (644
filled, 2 open over 55 dates), and submit-to-fill times exist only since 11-19 (21 orders).

**What to expect:** about one order a day. There is no ROI prediction. A population of about one a day cannot show a
money effect in two weeks, and claiming one would be noise.

## What was built (default OFF)

- **Code:**
  - `syndicate/features/shared/polymarket_stale_cancel.py` (new).
  - `pipeline/execute_portfolio.py`: one guarded call after the per-tick Polymarket reconcile, in the Polymarket-scope
    run only.
  - `tests/test_polymarket_stale_cancel.py`: 43 pass. The 126 existing executor, kickoff-cancel and maker-pilot tests
    also pass.
- **Switch:** `SYNDICATE_POLYMARKET_STALE_CANCEL` = `off` (absent, blank and unknown all read OFF) | `shadow` | `on`.
  - Only live-odds-worker runs live execution, so the kit sets the role-scoped
    `LIVE_ODDS_WORKER__SYNDICATE_POLYMARKET_STALE_CANCEL`.
  - Tuning keys: `..._MAX_AGE_SECONDS` (900) and `..._PRICE_BAND` (0.01). The per-pass cap is the shared
    `SYNDICATE_EXECUTION_MAX_CANCELS` (3).
- **Rule:** cancel only when ALL of these hold:
  - it is a taker order;
  - it is >= 900 s since our submit;
  - the venue reads it untouched (cum 0, leaves > 0, not terminal);
  - our side's ask is >= 0.01 above what a contract costs us, both on our side's scale (NO costs 1 - wire price; the
    NO ask is 1 - best YES bid).
  - NO PRICE, NO CANCEL.
- **How the cancel is made:** through `polymarket_us_orders.cancel_order`, naming the order's own client id
  (= idempotency key) and market slug. It reads first and refuses a filled, cancelled or expired order, or a mismatch.
- **What a cancel changes:** only an ACCEPTED cancel is remembered, and a failed one changes nothing. The ledger moves
  only when the next reconcile reads the venue.
- **The decision this overrides:** `cancel_order`'s docstring says nothing should call it in a loop (built for an
  operator retiring one leg of a duplicate pair). The user's request overrides that for this one narrow case. The pass
  makes no duplicate-leg judgement: it names one order we placed.

## The cancel route has never run against the live venue

`cancel_order`'s own docstring says the first real cancel is the probe. Hence:

**Recommended (the user's call): a SHADOW load before the window.**
- `shadow` reads, decides, and calls `cancel_order(execute=False)`: GETs and a log line, no venue write.
- It is **not a betting change**, so it may load outside a window. It is still an env change, so a drained `down` /
  `up` (`kit_env_pmstale.sh apply shadow`).
- **Shadow predictions (3 days):**
  - S1: `WOULD_CANCEL` fires on <= 3 orders a day.
  - S2: every `WOULD_CANCEL` is followed by `CANCEL_DRY_RUN` (not `CANCEL_REFUSED`), i.e. the client id and slug we
    pass match the venue's. A `client_order_id_mismatch` means the key mapping is wrong, and it must be fixed before
    12-08.
  - S3: for every `WOULD_CANCEL` order, a later `ORDER_STATE` still reads NEW, or the order expires unfilled at
    kickoff. If the orders it would cancel go on to FILL, the rule is cancelling fillable orders: rethink before 12-08.

## 12-08 window load: predictions and kill rules

Read at the window +24 h and +7 d, from the live-odds-worker log (`[polymarket_stale_cancel]`,
`[polymarket_us_orders] CANCEL_*`, `ORDER_STATE`) and the ledger.

- **P1, the route works.** The first `CANCEL_STALE` returns `CANCEL_SENT`, and within 2 Polymarket reconcile passes
  (about 10 min) the order reads cancelled and its ledger row leaves `submitted`. **KILL** (restore the kit, drained
  `down`/`up`) if the first send errors or the order still reads NEW after 2 passes.
- **P2, scope.**
  - Every cancel is a taker order, >= 900 s old, with a readable book showing drift >= 0.01: 0 exceptions.
  - None is read FILLED or partly filled at the next reconcile.
  - **KILL** on any exception.
- **P3, rate.** <= 3 cancels a day over the first 7 days (baseline: about 1 untouched-resting order a day). Above that,
  REVIEW: the rule is catching orders the baseline did not see.
- **P4, no churn.** No position is cancelled more than twice in a CST day (cancel, re-place, rest, cancel). **REVIEW /
  KILL** if any position cycles 3 or more times.
- **P5, the key frees.** For every cancelled order, the next tick either re-places that position (`prior_attempts`
  grows) or the plan no longer holds it. Count both; there is no prediction of which.

**Revert:** `kit_env_pmstale.sh restore <backup>` plus a drained `down`/`up`. Absent is OFF, so removing the line is the
whole revert. The gate's clock: a `yes` betting change restarts the 800-event count, so the window load carries
`--betting-change yes`.

## Kit

`C:\tmp\w1208_pmstale\kit_env_pmstale.sh` (`check | apply [on|shadow] | restore <backup>`) and
`kit_selftest_pmstale.sh`. Same pattern as `C:\tmp\w1124_851\`: a role-scoped line, backup first, idempotent, prints
only this key. Self-test result: see the log below.

## Log

- 11-21: built; 43 new tests and 126 existing pass; this pre-registration was written before any load.
- 11-21 12:16 PM CST, kit self-test (dummy file, in WSL):
  - a bad value is refused (rc 2);
  - `apply on` backs up first and appends exactly one role-scoped line;
  - a second apply is idempotent (`already_present`);
  - `restore` returns the file byte-for-byte;
  - `apply shadow` appends the shadow line;
  - the real `local_production.env` is unchanged (`real_file_unchanged=yes`), and every role reads the key ABSENT.
