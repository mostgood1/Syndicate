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
