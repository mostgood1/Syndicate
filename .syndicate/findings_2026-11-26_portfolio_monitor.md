# Portfolio monitor findings, 2026-11-26 (lane `portfolio-monitor`)

Public repo: counts and percentages only. No dollars, balances, order ids or row-level live trades.

## Two fleet items from the fleet-watcher (user ~11:35 AM CST: "yes, send both to the portfolio session") -- HYPOTHESES (11:55 AM CST)

### Item 1: the 11:12 AM CST full restart
- First evidence, before the hypotheses: the Windows System log shows a WINDOWS reboot, not a WSL-only one. The machine left Modern Standby at 11:09:26. At 11:10:07 `User32` 1074 logged a restart started from the Start menu (`StartMenuExperienceHost.exe`) on behalf of the signed-in user, reason "Other (Unplanned)". Then `EventLog` 6006 at 11:10:20, `Kernel-General` 13 (shutting down) at 11:10:26, 12 (started) at 11:10:47, and 6005 at 11:11:00. Restart Manager logged "Machine restart is required" three times at 11:02 AM. The fleet-watcher's "no 6005/6006/41" was a miss.
- **H-B1.** A person at the machine restarted Windows by hand; nothing in the repo or the watchdog did. The `SyndicateLocalProduction` task then brought the fleet up at its boot or logon trigger. Falsification: a `RECOVERY_START` in `watchdog.log`, a `wsl --shutdown` or `shutdown.exe` from a script or task, or a Windows Update restart event (WU 1074 reason "Operating System: ... (Planned)").
- **H-B2.** The restart loaded no code a role was not already running: each role's code before the reboot was `e37a9697f`, the fleet HEAD from 11-25 7:54 AM CST until the 11:27 AM ff. If so it is not a betting change, and its record is an incident note, not a load. Falsification: a role whose last boot before 11:10 AM predates the 11-25 7:54 AM ff, with betting-relevant code in between.

### Item 2: the hourly stale execution heartbeat
- **H-E1.** The live-odds-worker loop that stamps `execution_state.json` (`record_execution_state`, every execution tick) is blocked for 25-55 min about once an hour by something that runs inline in the same loop, so the execution tick (orders, settlement, balance reads) does not run in that window. Falsification: the worker's log shows execution ticks (or their order/settlement/balance work) inside a stale window.
- **H-E2.** The tick runs, but the stamp is not written on every pass (for example only on a branch that is skipped when there is nothing to do), so the heartbeat reads stale while the work goes on. Falsification: no execution-tick activity at all in the stale windows (then H-E1).

### RESULT (12:01 PM CST): one cause for both items -- the machine lost its network for 11 hours

**The machine's Wi-Fi dropped at 12:13:57 AM CST and stayed down until 11:11:07 AM, after the hand restart.**
- WLAN-AutoConfig 8003 at 00:13:57 says "The network is disconnected by the driver" (adapter: the built-in Qualcomm FastConnect 7800). There is no reconnect attempt (8000/8001) until 11:11:07, after the reboot. NCSI shows the adapter losing Internet capability at 00:13:57 and getting it back at 11:11:08.
- Inside WSL, the first `Temporary failure in name resolution` came at 06:14:14Z (live-odds-worker) and 06:14:32Z (refresh-worker), 17 s after the drop. The rate was about 750 an hour in live-odds-worker and 200 an hour in refresh-worker every hour from 06Z to 16Z, ending with the last one at 17:10:05Z.
- The machine went into Modern Standby at 3:33:30 AM, after the drop, so standby did not cause it, and it woke at 11:09:26. The ESPN tracebacks at 10:36-11:05 AM were a slice of this outage, not a separate one. My 17:40:07Z deploys.md entry said otherwise and is corrected in deploys.md.

**Item 1 (the 11:12 AM restart): H-B1 MET.**
- A person at the machine restarted Windows: it woke from Modern Standby at 11:09:26, and a Start-menu restart followed 41 s later (`User32` 1074, "Other (Unplanned)").
- Nothing in the repo or the watchdog did it: there is no `RECOVERY_START`, and the watchdog's 11:11 run never ran because Windows was rebooting. The `SyndicateLocalProduction` task brought the fleet up at 11:12 (refresh-worker 17:12:09Z, live-odds-worker 17:12:10Z).
- **H-B2 FALSIFIED in part.**
  - live-odds-worker loaded nothing new: it self-recycles about every 24,200 s, and its boots at 14:41Z 11-25, 09:32Z and 16:16Z 11-26 all ran `e37a9697f`.
  - **refresh-worker had not restarted since 08:30:37Z 11-24 (the window batch, `672a18e87`), so the reboot loaded `672a18e87..e37a9697f` into it.**
  - Runtime code in that range: `cf12ae61f`, the NCAAF live margin anchor, default off, with `SYNDICATE_NCAAF_LIVE_MARGIN_ANCHOR` unset on refresh-worker. `d25f49964`, `SYNDICATE_LAYER2_ONE_MODEL_NUMBER`, default off and unset ("Betting change while OFF: no"). `6ca19e36c`, display only for the cheat sheets. `322094343`, `76a006f45` and `e37a9697f`, web gunicorn only. Plus web pages and scripts.
  - Each is a ride-along of BC-072/BC-073, both "no". **Not a betting change.** Recorded in deploys.md as an unplanned load.

**Item 2 (the hourly stale heartbeat): the stall was the outage.**
- **H-E2 is falsified.** The stamp was written on every tick, but ticks were rare: 24 execution ticks from 06:00 to 17:10Z, in pairs about 3 min apart (one per venue) with gaps of 52.6-58.7 min between pairs.
- **H-E1 holds for the mechanism, not the cause.** With no DNS, every outbound call failed slowly:
  - exit quotes: `quoted=0 quote_errors=27`, all 196 positions unquoted;
  - the venue reconcile: Kalshi `RECONCILE_READ_FAILED` with 29 candidates, Polymarket with 16, about 2.7 min per venue;
  - balances `auth_error`, and settlement errors.
- One loop pass took about 55 min, and the execution tick runs once per pass.
- Every tick from 06Z to 16:15Z came back `EXECUTION status=blocked reason=unreconciled_orders`, one per venue per hour. The one order it could not read back blocked all runs, because the venue could not be reached.
- **What the live book lost:** from 12:14 AM to 11:11 AM CST, 0 live orders, settlement and balance reads, and 0 exit quotes. refresh-worker's odds capture also failed (about 200 DNS failures an hour).
- Since the reboot it is back to normal: 8 execution ticks per venue at 17Z, all `status=ok`, with the unreconciled block cleared.

**Routing:**
- **The host is the user's call:** a wired connection, the Wi-Fi adapter's power settings and its driver.
- **The watchdog.** It flagged the symptom (the heartbeat) for 10 hours and never named the cause. `scripts/execution_watchdog.py` belongs to the OPEN lane `kalshi-cancel-alert` (owner session bf65f720). A lost-internet check, a DNS lookup of a venue host from WSL, would name it. A Windows-side reconnect after N minutes would be standing automation and needs the user's OK.

**User decision, 6:29 PM CST (this session's chat): "Leave it"** -- answering "Should I add a lost-internet alert to the watchdog?". No watchdog change, no loan from `kalshi-cancel-alert`, no Windows-side reconnect. The host fix (wired connection, Wi-Fi adapter power settings, driver) stays with the user.

## Reading, 6:30 PM CST (00:30:03Z 11-27), log window 440 min (since the 11:11 AM reboot)

- **Endpoints:** 8 of 8 returned 200. Web had 0 worker timeouts. The banner is ok: mode live, armed, state 223 s old.
- **Plan:** 5.0 min old. Board 4,608 -> suggested 59 -> sized 25 -> positions 11, with 16.4% of the ceiling used. There were 53 plan commits for tonight in 6 h, with a max gap of 13.9 min.
- **Execution since the reboot:**
  - Kalshi: 72 live ticks, 4 placed, 0 failed. Its refusals were mostly `already_held_other_slate` 63.
  - Polymarket: 72 ticks, 0 placed, 0 failed.
  - Orders today: 4 (3 filled, 1 submitted). The one resting order is 417 min old, a maker-pilot post before its kickoff. The probe's overdue rule did not name it, so it is resting as designed.
- **Ledger and caps:**
  - unknown_submits 0, unreconciled 0, grade_conflicts 0. Settlement: 0 late.
  - Kalshi used 7.4% of its day dollar cap.
- **Gate:** 10 of 800 events since BC-071 (08:30:37Z 11-24).
  - The standing `GATE` anomaly is 2 unclassified loads, 17:58:30Z 11-18 and 04:46:22Z 11-19. Both are other lanes' and both predate the clock start, so this count is unaffected.
- **Performance (ROI on stake net of fees, event-clustered 95%):**
  - last 7 days: 0.24% [-11.49, 11.96] on 263 bets / 148 events, inside noise;
  - last 30 days: -7.51% [-13.19, -1.83] on 1,610 / 723, loses beyond noise;
  - all: -10.3% [-17.16, -3.45] on 2,389 / 1,288.
  - Fee-net CLV last 7 days is -1.53 pp (se 0.5). The 30-day signals are unchanged: totals, model_edge, the EV 2-5 band (predicted 4.12% vs realised -9.89%), the .30-.45 price band, and the top stake quartile.
- **The outage's cost to the live book** (from the 11-26 RESULT above): 0 orders from 12:14 AM to 11:11 AM CST. No settlement was late after it.

### NEW: the alignment half of the reading fails whenever the board warns about its card merge

- **Hypothesis (written at 6:32 PM, after the first measurement below, so not blind):** `portfolio_alignment_reader.py` runs on the fleet and imports `pipeline.intelligence_state`. `read_layer2_shortlist` -> the card-shard merge prints `[intelligence_state] LAYER2_CARD_SHARD_MERGE ...` to stdout whenever `missing or overflow or len(merged) != total` (`pipeline/intelligence_state.py:3402`). That line lands ahead of the reader's one JSON document, so the probe's `json.loads` fails with "reader output not JSON (rc 0)".
- **Falsification:** if the failing runs' stdout starts with `{`, or the passing runs printed the same line, the hypothesis is wrong.
- **Measured:**
  - Re-run at 00:3xZ: rc 0, 1,185,032 bytes of stdout, 0 of stderr. The stdout starts with `[intelligence_state] LAYER2_CARD_SHARD_MERGE date=2026-11-26 loaded=['ncaab', 'ncaaf', 'nfl', 'soccer'] missing=[] cards=4483/4665 unplaceable=0`, then a second `[intelligence_s...` line, then the JSON.
  - Across Portfolio Watch's 388 stored readings, the alignment half failed **25 of 153** that ran it (16.3%), all with this one error, first at 05:04Z 11-24. Today it failed 04:34-07:34Z and 17:34-23:34Z, and was ok in between and at 00:04Z.
  - So it is intermittent with the board's merge state, not a fleet change. The print dates from 2026-08-31 (`0763c85ba`), and it fires only when the merged card count falls short of the index.
- **Effect:** monitoring only. In those readings the purchaser-vs-board-vs-rail counts are missing, and nothing about the book is wrong.
- **Fix (owner: this lane, `scripts/portfolio_alignment_reader.py`):** route stdout to stderr while the reader works, and write only the JSON document to the real stdout. It is a few lines plus a test, and it waits on the user's yes.
- **Lead, not followed:** tonight's merge placed 4,483 of the index's 4,665 cards (182 short, 3.9%), with no shard missing. The ledger's board notes (`findings_2026-11-19_board_read_cold_share.md`) list this line as part of the normal cold-read path; whether a short merge loses Suggested rows is the board's question, not this lane's.
