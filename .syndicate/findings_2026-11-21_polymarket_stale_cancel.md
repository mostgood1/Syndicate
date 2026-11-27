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

`C:\tmp\w1208_pmstale\kit_env_pmstale.sh` (`check | apply <shadow|on> | restore <backup>`) and
`kit_selftest_pmstale.sh`. Same pattern as `C:\tmp\w1124_851\`: a role-scoped line, backup first, idempotent, prints
only this key. Self-test result: see the log below.

**Changed 11-23, before any load:**
- `apply` now needs the value. It used to default to `on`, so a bare `apply` could have written the betting change.
- `apply on` over the shadow line promotes it in place. That is the 12-08 load once the shadow is in. Before, it read
  `already_present` and would have left the shadow line.
- Any other line of this key is refused (`CONFLICT`, rc 5).
- The old copy is `kit_env_pmstale.before_shadow_1123.sh`.

## Shadow load: CHANGE N of the 11-24 window batch

User, typed in this session, 11-23 about 8:00 AM CST: **"load the polymarket stale cancel in shadow before 12-08"**.

- **Vehicle.** It rides the drained full `down`/`up` of the 11-24 window batch (task `nfl-level-refit-load-1120`, fires
  11-24 2:15 AM CST) as CHANGE N. That costs no extra restart. The batch's ff carries `7bc613347` anyway, so it needs
  none of its own.
  - CHANGE M was already taken that morning by the rail monitor's #860 (8:07 AM CST). N anchors after M in every step.
  - The batch prompt's pre-edit copy is `C:/tmp/w1124_pmshadow/SKILL.before_M.md`. The edit script is `add_n.py`,
    hash-guarded.
- **Line and role.** One role-scoped line, `LIVE_ODDS_WORKER__SYNDICATE_POLYMARKET_STALE_CANCEL=shadow`.
- **Not a betting change**, so no window gates it.
  - In shadow the pass calls `cancel_order(execute=False)`: a GET and a `CANCEL_DRY_RUN` line.
  - It remembers nothing (`_CANCELLED` grows only in `on`).
  - The executor discards its return value.
  - Only this pass calls the Polymarket `cancel_order` (grep, 11-23). So any `CANCEL_SENT` in live-odds-worker's log
    would be this pass.
- **Droppable.** A failed N step drops N only.
  - If the batch does not load N, N needs another drained full `down`/`up` before 12-08. That is the user's call; the
    reading task and the daily review say so.
- **Instrument.** `C:/tmp/w1208_pmstale/pmstale_shadow_read.sh <from_utc> [to_utc]` is read-only. It reads
  live-odds-worker's current and rotated logs, only lines that START with a timestamp followed directly by the marker.
  - It counts the pass's lines (`WOULD_CANCEL`, `CANCEL_*`, `PASS`, hook failures) and gives S1-S3.
  - It also counts the population: Polymarket orders the venue showed `NEW` with cum 0 at least 15 min after creation.
  - Self-tested 11-23 on a synthetic log: every expected count matched, a memory line quoting the pattern was ignored,
    and a window older than the logs reads `covered=NO`.
- **Pre-load baseline, 11-23 8:05 AM CST.** The logs reach back to 11-19 22:29Z.

  | window | Polymarket orders with a venue state read | rested untouched >= 15 min | later |
  |---|---|---|---|
  | 11-19 22:30Z to 11-23 14:05Z (3.6 days) | 104 | 1 (the 11-21 case, about 12.3 h) | expired unfilled |
  | 11-22 14:00Z to 11-23 14:05Z (24 h) | 37 | 0 | n/a |

  The instrument finds the known case. The shadow should see about one WOULD_CANCEL a day or fewer.
- **Readings:**
  - At load (batch step 9): live-odds-worker's environ reads `shadow`. `cancel_stale=0`, `cancel_sent=0` and
    `hook_failed=0` since the up.
  - +3 d: task `pm-stale-shadow-reading-1127` (11-27 9:45 AM CST, read-only): S1-S3 from the load.
  - The daily `portfolio-learning-review` runs these until 12-08:
    - a one-line daily tally (logs rotate after about 3.5 days, so the tally keeps the whole period);
    - the +3 d backstop;
    - a summary on its first run after 12-07 5:00 AM CST, for the user's 12-08 decision.
- **Kill rule in shadow.** Any `cancel_stale` or `cancel_sent` above 0 is a defect: a live venue write nobody approved.
  It is reported first. The revert (remove the line, plus a drained `down`/`up`) needs the user's yes.
- **The 12-08 `on` load** is unchanged: the window, the user's final yes, and the P1-P5 above.
  - S2 or S3 failing in the shadow means `on` should not load until it is understood.

## Log

- 11-21: built; 43 new tests and 126 existing pass; this pre-registration was written before any load.
- 11-21 12:16 PM CST, kit self-test (dummy file, in WSL):
  - a bad value is refused (rc 2);
  - `apply on` backs up first and appends exactly one role-scoped line;
  - a second apply is idempotent (`already_present`);
  - `restore` returns the file byte-for-byte;
  - `apply shadow` appends the shadow line;
  - the real `local_production.env` is unchanged (`real_file_unchanged=yes`), and every role reads the key ABSENT.
- 11-23 8:09 AM CST: the kit was changed and re-self-tested (dummy file, in WSL). All of these held:
  - `apply` with no value, or a bad one, is refused (rc 2) and the file is unchanged;
  - `apply shadow` appends one line;
  - a second apply reads `already_present`;
  - `apply on` promotes shadow to on in place;
  - `apply shadow` over `on` reads `CONFLICT` (rc 5);
  - the two restores step back, the last one byte-identical to the original;
  - mode 600 is kept;
  - the real file is unchanged and every role reads the key ABSENT.
- 11-23 8:16 AM CST: queued the SHADOW load as CHANGE N of the 11-24 window batch, on the user's "load the polymarket
  stale cancel in shadow before 12-08".
  - Reader self-tested. Baseline: 1 of 104 orders untouched >= 15 min over 3.6 days; 0 of 37 in the last 24 h.
  - The 43 tests pass (17 s).
  - The +3 d task and the daily-review items are scheduled.
  - Nothing is loaded: the fleet is at `b07e808823`, which lacks `7bc613347`.
- 2026-11-24 CST (shadow day 1, from SHADOW LOADED 08:30:36Z to 11-25 06:00:00Z; read 11-25 2:05 AM CST = 08:05Z by the
  daily learning review): would_cancel 0, distinct orders 0; S2 outcomes none, mismatch_refusals 0; S3 later states
  none; untouched_15m_orders 0 of 19 polymarket_orders_with_state_lines; covered yes; cancel_stale 0, cancel_sent 0.
- 2026-11-25 CST (06:00Z 11-25 to 06:00Z 11-26; read 11-27 2:00 AM CST = 08:00Z by the daily learning review, the
  11-25 run having failed in the outage): would_cancel 0, distinct orders 0; S2 outcomes none, mismatch_refusals 0;
  S3 later states none; untouched_15m_orders 0 of 22 polymarket_orders_with_state_lines; covered yes; cancel_stale 0,
  cancel_sent 0.
- 2026-11-26 CST (06:00Z 11-26 to 06:00Z 11-27; read 11-27 2:00 AM CST = 08:00Z): would_cancel 0, distinct orders 0;
  S2 outcomes none, mismatch_refusals 0; S3 later states none; untouched_15m_orders 0 of 16; covered yes;
  cancel_stale 0, cancel_sent 0.
- **2026-11-27 +3 d shadow reading** (read 15:45Z = 9:45 AM CST 11-27; task pm-stale-shadow-reading-1127; READ-ONLY).
  - Loaded: live-odds-worker boot 2026-11-24 08:30:36Z (2:30 AM CST), 11-24 window batch. `kit_env_pmstale.sh check`
    at 15:45Z: live-odds-worker `SYNDICATE_POLYMARKET_STALE_CANCEL=shadow`, refresh-worker and web ABSENT,
    `lines_pmstale_on=0`, `lines_pmstale_shadow=1`.
  - Window 08:30:36Z 11-24 .. 15:41:54Z 11-27 (about 3.3 days); `covered=yes` (earliest log line 11-23 10:01Z);
    22,946 live-odds-worker log lines in the window, 6 log files.
  - would_cancel 0 (0 distinct orders); cancel_stale 0, cancel_sent 0, cancel_failed 0, hook_failed 0, scope_exceptions 0.
  - S1 PASS (max 0 a CST day, limit 3). S2 n/a (no WOULD_CANCEL; mismatch_refusals 0). S3 n/a (no WOULD_CANCEL).
  - Population: untouched_15m_orders 0 of 26 polymarket_orders_with_state_lines (baseline 1 of 104 over 3.6 days pre-load).
    So this is a quiet PASS: nothing rested untouched >= 15 min. `pass_lines_by_mode={}`: the pass writes no line when
    it finds nothing, so this reading cannot itself show the pass is running; with 0 candidate orders that cannot matter yet.
  - S2 (the client id / slug match against the venue) is still UNTESTED: no order has reached the dry-run cancel. The
    12-08 `on` load would rest on a cancel call never exercised in production. Order flow is thin (26 orders in 3.3 days,
    cf. lead venue-order-family-census 11-27: polymarket placed 0 in 24 h).
