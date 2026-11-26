# Portfolio monitor -- 2026-11-25 (lane portfolio-monitor, session 69d80317)

Counts and percentages only (public repo).

## Today's rollup row is marked `partial` (10:12 AM CST)

User 11-25: "mark today's rollup row as partial". This follows H-R1 (findings_2026-11-24_portfolio_monitor.md). Tooling only.
- `scripts/portfolio_watch/build_history.py`: every row carries `partial`, which is true while the row's date is today in CST. Until midnight, its rolling windows have dropped a full old day for only part of this one.
- `build_dashboard.py`: the history table's Day column reads "<date> (partial)".
- Test: `test_todays_rollup_row_is_partial_and_earlier_days_are_not`; 8 of 8 Portfolio Watch tests pass.
- Installed in the run copy at `C:\SyndicateProd\portfolio_watch` (backup in `backup_before_partial_1125\`) and rebuilt at 10:10 AM CST: 111 rows, 0 partial. That is correct: no 11-25 bet has graded yet, so the newest row is 11-24, now a complete day.
- **11-24 as a complete day:** 8 bets on 5 events. Its 30-day window (10-26..11-24) reads -6.45% [-11.97, -0.93] on 1,642 bets, still wholly below 0. So r30_negative stands on a settled day, not only on a partial one.
- Not changed: dash_chk still reads the LAST row (fleet-watcher's code). It can skip rows with `partial: true`.
- Owed: the first rebuild after an 11-25 bet grades should show the 11-25 row as partial.

## Slow exit tick failed its save 50 times, 7:19-11:55 PM CST 11-24 -- HYPOTHESES (10:14 AM CST)

Routed here by the fleet-watcher, on the user's 11-25 ~9:30 AM CST "yes, send the exit failure to the portfolio session". The owners are gone: `kalshi-exit-path` (session b4e23404) and `hold-value-exits` (ffd41dea, archived 11-20). So this is diagnosis only, read-only; any change needs a loan of `execution_exits.py` and the user's yes.

**The report.**
- live-odds-worker logged `EXIT_TICK_FAILED KeyValuePayloadTooLarge` on every slow exit tick from 01:19:02Z to 05:55:04Z 11-25 (50 ticks).
- The exits record (`reports/intelligence/execution_exits.json`) was 8,399,089-8,402,780 B against the 8,388,608 B cap.
- The caller was `execution_exits.py:288 <- :1625 <- :1439`, and `watch` made up about 6.6 MB of it.
- It cleared on its own at ~06:0xZ.

**H-X1 (question 1): no live exit was sent in the window, so none was sent twice.**
- `place_exit` saves the whole record BEFORE it sends (`execution_exits.py:1191`, "WRITE-AHEAD"). That save is outside the send's `try`.
- With the record over the cap, the save raises, and the send is never reached.
- The reported caller chain ends at the tick's FINAL save (:1625), not at the write-ahead. So no tick even got as far as a live send.
- What the failure did lose is each tick's watch updates and new PAPER exit rows.
- Falsification, any one of these: an `EXIT_LIVE` line in 01:19-05:55Z; a `KEYVALUE_WRITE_REJECTED` caller through :1191; a live exit row or venue sell order submitted in the window.

**H-X2 (question 2): `watch` holds one row per position, live AND paper, for the retention window.**
- That window is `lookback_days()` 3 + pad 2, by position date, so `watch` grows with the paper book's daily position count.
- The evening slate pushed it over the cap.
- At midnight CST the tick's `today` rolled, the retention floor moved one day, and `_prune_watch` archived a day of rows. That is the ~06:0xZ "cleared on its own".
- Falsification, any one of these: `watch` rows not concentrated in the retention window; paper rows not most of them; no `pruned` > 0 on the first good tick.

### RESULT (10:18 AM CST): H-X1 and H-X2 CONFIRMED. No live exit was sent or blocked in the window, and the record will cross the cap again today

**Question 1: no live exit went out 01:19-05:55Z, and none was sent twice.** Read-only greps of `~/syndicate-prod/logs/live-odds-worker.log`:
- `EXIT_TICK_FAILED KeyValuePayloadTooLarge`: 50 in the window.
- `KEYVALUE_WRITE_REJECTED` for the exits record, 00-06Z: 52, every one with the SAME chain, `:288 <- :1625 <- :1439`, the tick's final save. 0 came through `place_exit`'s write-ahead (:1191).
- `[execution_exits] EXIT_LIVE` lines from 00:00 to 06:59Z: 0. The last before the window was 23:34:15Z 11-24 (take_profit+model_fair, filled), and the ok ticks up to 01:13Z saved it.
- **Also 0 blocked:** a live position whose rule qualified would have reached the write-ahead, failed there, and left a :1191 chain. None appears. The failures lost each tick's watch updates and new PAPER exit rows, and nothing else.
- So the "forgotten live exit" risk could not happen while the record was over the cap. The write-ahead fails first, and the exit is refused without being sent.

**Question 2: why `watch` is that big.** Measured on the fleet at 16:14Z (read-only, live-odds-worker's environ, nice 19, the store's own compact serialization):

| | |
|---|---|
| record | 8,081,801 B of 8,388,608 (96.3%) |
| `watch` | 5,938,260 B, 8,170 rows, ~727 B each |
| `exits` | 2,142,704 B, 2,850 rows (2,759 paper, 91 live) |
| watch rows by mode | paper 7,909 (5.53 MB), live 261 (0.18 MB) |
| watch rows by position date | 11-20 875, 11-21 1,864, 11-22 1,562, 11-23 715, 11-24 971, 11-25 674, 11-26..11-30 1,509 (future games) |
| watch rows by last seen | <1 h 332, 1-6 h 341, 6-24 h 788, 1-3 d 2,670, >3 d 4,039 |

- The last tick saw 249 open positions. So **6,709 rows (4.7 MB, 79% of `watch`) were last seen over a day ago**: positions already graded or closed, kept until their position date leaves the retention window (3 + 2 days).
- No exit rule reads a watch row. They feed only `_update_watch`'s high-water mark and the report at :1747, which already merges in the archive.
- The midnight-CST prune is what cleared it: `watching` went from 8,291 (00:14Z) to 7,655 (06:57Z).

**Tonight: it will cross again.** Size per the store's `KEYVALUE_WRITE_LARGE` lines, 11-25:

| 06:01Z | 08:16Z | 10:27Z | 12:40Z | 13:50Z | 14:53Z | 15:58Z |
|---|---|---|---|---|---|---|
| 7,600,753 | 7,666,001 | 7,783,527 | 7,825,899 | 7,935,947 | 8,005,758 | 8,070,047 |

- The last three hours grew 64-110 KB an hour, with about 307 KB left at 16:14Z.
- At that pace it crosses around 19-21Z (1-3 PM CST), and the evening slate adds rows faster.
- Once over, every slow tick fails until the 06:00Z 11-26 prune moves out 11-20's 875 rows.
- While over the cap, no live exit can be sent, because the write-ahead refuses first.

**Options (the owning lanes' sessions are gone, so each needs the user's yes):**
- **A, structural.** `_prune_watch` also archives rows not seen by a tick for 24 h. Rows are moved, never dropped, and the reader at :1747 already merges the archive. At 16:14Z that leaves about 1,461 rows: a ~3.4 MB record.
  - Not a betting change, since no rule reads a watch row.
  - Needs a loan of `execution_exits.py` from `kalshi-exit-path`, a test, a fleet ff, and a live-odds-worker restart behind claims and preflight.
- **B, headroom.** Raise `SYNDICATE_KEYVALUE_MAX_BYTES` for the live-odds-worker role only. No code change, but a drained full `down`/`up`, and the record keeps growing.
- **C, wait.** It breaks this afternoon or evening and clears at midnight CST. Live exits are blocked while it's broken.

## The exits record crossed at 4:31 PM CST, and one live exit was sent while it sat at the cap — HYPOTHESES (9:09 PM CST)

Readings at 03:09Z 11-26 (read-only, `live-odds-worker.log` .2/.1/current and the record itself):
- The first rejection of `execution_exits` today was 22:31:50Z (4:31 PM CST), not 1-3 PM as projected. 54 rejections since, all from `execution_exits.py:288` (`_persist`).
- One live exit was sent inside that window: 01:26:14Z (7:26 PM CST), rule `take_profit+model_fair`, status `submitted`.
- The record on disk is 8,388,485 B against the 8,388,608 cap (123 B under), and its `last_tick` is 01:26:12Z.

- **H-X3.** That exit's write-ahead save (:1191) fit by about 123 B, the send went out, and every save after it failed. If so, the record holds the exit as written ahead, without its post-send result. Falsification: the record's row for that exit carries the venue's response, or a save later than 01:26:14Z succeeded.
- **H-X4.** What the next tick does with a written-ahead row whose result was never saved decides the risk. It may reconcile against the venue, re-send (a double sell), or block that position's later exits. Falsification: the code path for such a row, read in the fleet's own `execution_exits.py`.
- This corrects the 10:18 AM claim that "sent but forgotten" cannot happen. It cannot happen while the record is over the cap, but it can happen when the write-ahead fits by a few bytes and the save after the send does not.

### RESULT (9:14 PM CST): H-X3 confirmed for the 7:27 PM sell, not the 7:26 PM one; no live exit has gone out since 7:27 PM

The record's last four successful saves (`KEYVALUE_WRITE_LARGE`, caller chain), then the record itself, read through the worker's own `read_json_file`:

| time (CST) | save | size | |
|---|---|---|---|
| 7:26:13 PM | write-ahead (:1191) | 8,388,261 | sell 1 sent 7:26:13 |
| 7:26:14 PM | after the send (:1216) | 8,388,358 | sell 1's venue answer saved |
| 7:26:14 PM | tick end (:1625) | 8,388,201 | |
| 7:27:54 PM | write-ahead (:1191) | 8,388,485 | sell 2 sent 7:27:54; **last save that fit** |
| 7:27:55 PM | after the send | 8,388,617, **rejected by 9 B** | sell 2's venue answer lost |

- Sell 1 is on disk as `dead` (an immediate-or-cancel that did not fill), with its order id. The next tick's reconcile marked it.
- **Sell 2 is on disk as `submitted` with no order id.** That is the one unreconciled live exit, so H-X3 holds for it. Its result exists only at the venue.
- These are fast-exit DISPATCH ticks. A dispatch tick starts from the last saved record and adds only its own entry, so it fits where the slow tick (8.43-8.45 MB) cannot. That is how sells were still sent while the record sat at the cap.

**H-X4, read in the fleet's own code (`~/Syndicate` at e37a9697f):**
- **No double sell.** `place_exit` refuses an entry whose row is `submitted` (`duplicate`). The send carries `client_order_id = exit_idempotency_key(entry_key)`, and `EXIT_SUBMIT` shows only these 2 sends from 4 PM to 9:09 PM.
- **Every new live exit is blocked.** `unreconciled_exits` on disk is 1, so `place_exit` refuses new exits (`unreconciled_exits`). A tick that reconciles the row in memory and then sends would first need a write-ahead save, and that is over the cap too.
- 4 dispatches triggered after 7:27 PM ended in `KeyValuePayloadTooLarge` with no send: 7:59, 8:15, 8:42 and 8:50 PM. The 8:50 PM one was sell 1's entry again, after its first try did not fill. Those positions now ride toward settlement unless a later trigger fires once saves work again.
- **When it clears.** The 06:00Z (midnight CST) prune moves 11-20's 875 watch rows (~0.64 MB) out, which should bring the record under the cap. The first tick after that reads sell 2 back from the venue. With no order id, it reads it from the newest 100 orders on the account (`fetch_orders(limit=100)`, matched on `client_order_id`).
  - If more than 100 newer orders exist by then, the row stays `submitted`, and every new live exit stays blocked until someone reconciles it by hand.
  - Settlement also defers that entry's grade while the row is `submitted`.
- **Correction to the 10:18 AM section.** "No live exit can be sent while over the cap" holds for the slow tick, not for dispatch ticks, which start from the smaller saved record. "Sent but forgotten cannot happen" was wrong at the margin, and it happened at 7:27 PM.

What option A changes here: with rows unseen for 24 h archived (~3.4 MB), neither the slow tick nor a dispatch tick comes near the cap, so the save after a send cannot be the one that fails.
