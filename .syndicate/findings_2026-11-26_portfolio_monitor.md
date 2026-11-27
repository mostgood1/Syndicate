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

**Alignment reader FIX (user 11-26, this session's chat: "Yes, fix it"):**
- What changed: `scripts/portfolio_alignment_reader.py` runs its work under `contextlib.redirect_stdout(sys.stderr)` and writes only the JSON document to the real stdout. The work moved into `read_alignment(pid, date)` and the environ read into `fleet_environ(pid)`. Nothing else changed.
- Test: `test_the_readers_stdout_is_its_json_even_when_the_fleet_code_prints` passes, and the file runs 29 passed. With the redirect disabled, the test fails with production's error (`Expecting value: line 1 column 2 (char 1)`), so off != on.
- **Live reading at 9:55 PM CST (03:55:44Z 11-27):** the merge warning WAS printing (cards 4,228 of 4,383). The fixed reader gave rc 0, 1,110,512 bytes of stdout that parse as JSON, and 284 bytes of stderr holding the two merge lines. The full probe at 03:55:57Z rendered the ALIGNMENT section: board 4,256 rows, 60 Suggested, 1 of 60 bought today.
- **Still to confirm:** the scheduled Portfolio Watch runs use the PRIMARY tree's `scripts/`, which is current only after the primary tree's fast-forward. The reading that confirms it: a scheduled reading with alignment ok while the merge is short.
- **CONFIRMED in the scheduled runs `[read 2026-11-27 12:27 AM CST, 06:27Z]`:** the primary tree took the fix at 10:05:57 PM CST (`f9b72e447`, 04:05:57Z). Every scheduled Portfolio Watch reading on it rendered alignment: 4 of 4 (04:34, 05:04, 05:34, 06:04Z). The merge was short throughout that window: refresh-worker's log carries 55, 50 and 54 `LAYER2_CARD_SHARD_MERGE` lines in the 04:30, 05:00 and 05:30Z half hours, and the latest read 4,365 of 4,554 cards at 06:26Z. On the old code the three readings before it failed in the same condition (02:34, 03:04, 03:34Z; 46-53 lines per half hour). The 04:04:21Z reading, still on the old code, was ok, which fits the old failure rate of 25 in 153.

## DAILY SUMMARY — Thu 11-26 (Central), written Fri 11-27 2:05 AM CST by the daily learning review

Sources: `daily_rollup.json` and `performance.json` built from the 1:34 AM CST 11-27 watch reading (ledger saved
07:34:02Z), and the 48 watch readings dated 11-26 CST. Every 11-26 game is graded: 0 started and unsettled, 0 late.
The 11-25 review did not run (the network outage), so 11-25 has no summary of its own; its row is quoted here.
Thanksgiving slate, and the third day since CHANGE P (live EV floor off), so volume is not comparable with pre-11-24.

**Performance.**
- **11-26: 4 graded bets / 2 games, ROI +6.34% [-9.7, +22.4].** Won 75.0% against a 66.7% breakeven. Too small to
  read. (11-25: 11 bets / 7 games, +55.7% [+20.5, +90.9], won 63.6% vs 61.9%; also too few games to mean much.)
- **7 d: 213 bets / 124 games, -0.24% [-13.3, +12.8]** (11-24: -2.55% on 177 games); won 52.6% vs 61.1% breakeven.
- **30 d: 1,588 bets / 711 games, -8.16% [-13.8, -2.54]**, beyond noise and the worst 30 d reading since 11-20
  (rollup r30: 11-21 -4.93, 11-22 -4.76, 11-23 -5.14, 11-24 -6.37, 11-25 -7.49, 11-26 -8.16). All-time: 2,397 bets /
  1,290 games, -10.26% [-17.1, -3.42].
- **Fee-net CLV:** 30 d -0.63 pp (622 bets / 422 games with a priced close; gross +1.11, beat close 60.6%, se 0.22;
  wins minus close -4.4 pp, z -2.14); 7 d -2.17 pp (99 / 73; gross -0.41, beat close 43.4%, se 0.31); 11-26 alone
  +1.29 pp on 3.
- **Fees: 2.14% of stake on 11-26, 2.98% over 7 d, 3.90% over 30 d** (11-26 before fees +8.48%).
- **Gate: 12 of 800 events** since BC-071 (CHANGE P, 11-24 2:30 AM CST = 08:30:37Z): 20 bets, ROI +28.0% (lower
  -4.64%), excess wins +0.2. Conditions 1-3 fail, 4 passes. 2 deploys.md loads are still unclassified (the GATE
  anomaly on 48 of 48 readings).

**30-day slices beyond noise (95% range excludes 0):**
- totals -13.63% [-25.4, -1.83] (354 bets / 278 games; won 43.8% vs 49.3%, -19.5 excess wins).
- EV band 2-5 -11.09% [-19.0, -3.17] against a predicted +4.12% (1,040 / 556).
- price 0.30-0.45 -14.28% [-26.5, -2.10] (205 / 141).
- path model_edge -10.57% [-17.9, -3.27] (1,240 / 629).
- **Kalshi -6.84% [-13.0, -0.71]** (1,085 / 591), back beyond noise (11-24: -5.31% incl. 0).
- stake Q1 (6.4% of $) -11.46% [-21.9, -1.04] and **Q4 (61.8% of $) -9.21% [-17.4, -1.01]**; Q2 -8.56% and Q3
  -4.13% include 0.
- Passing TDs -66.3% on 10 bets / 10 games: too few to read.
- Noise: Polymarket -12.95% [-26.2, +0.34], NCAAF -14.79% [-30.2, +0.57], totals_alt -18.04% [-37.0, +0.91],
  h2h +4.75% [-6.9, +16.4].

**Operations (48 readings).**
- Anomaly kinds, by readings flagged: GATE 48; BANNER not ok 17, WORKER STATE stale 17, BALANCES stale 15 (all in
  1:04-11:04 AM CST: the 11-hour network outage that ended with the 11:11 AM reboot; findings above); PLAN stale 1;
  WEB 1. Nothing after the reboot except GATE.
- Endpoint reads over 2 s: 1 (plan); over 3 s: 0.
- Plan commits: 40 in the probe's 6 h series dated 11-26 UTC (02:07-06:03Z), max gap 22.6 min.
- Orders 11-26: 8, of which 7 filled and 1 did not (11-25: 22 / 21 / 0).

**Studies and window reads (this run).**
- **S5 price-band forward test: NO-GO.** Forward set (selected >= 11-19): 271 graded bets / 150 games; dropping the
  fitted band (.55-.70) gives D = -4.70 pp [-13.6, +4.28]. The rule was GO iff the lower bound > 0. S5 ends; nothing
  changes live. Recorded in `findings_2026-11-18_s5_price_band_map.md`.
- **F27 Kalshi sport scope, +24 h BACKSTOP (the 11-25 task left no Log line): PASS on both.** P1: 12,320 Kalshi rows
  since the load, `differ=0`. Replay on the 11-27 board (5,579 rows): `report_pairs_equal_off=True`,
  `lost_by_on_own_sport=0`, `gained_by_on_other_sport=0` (939 matched in every mode). +7 d is due after 12-01 5:00 AM CST.
- **CHANGE N, Polymarket stale cancel SHADOW:** daily lines for 11-25 and 11-26 are in its Log. Both days: 0
  would-cancel, 0 untouched >= 15 min (of 22 and 16 orders), `cancel_stale=0 cancel_sent=0`. The +3 d S1-S3 reading
  (task `pm-stale-shadow-reading-1127`, 9:45 AM CST) is not yet due; its backstop is the next run.
- **CHANGE P, live EV floor OFF:** `live_ev_floor_on_lines=0` on 11-26. 11-25 is NOT COVERED by the kit: the
  refresh-worker log starts 15:44Z 11-25 and shows 0 plan writes, so its 0 is not evidence. Ledger counts: 11-25
  pregame 19 (Kalshi 12, Polymarket 7), in-play 3 (Kalshi 3); 11-26 pregame 6 (Kalshi 6), in-play 2 (Kalshi 2).
  The kit counted 3 orders on 11-26 against the ledger's 8. Pregame has been 8, 19, 6 a day against the registered
  0-2: no floor lines, so not a defect, but the P-F prediction is not holding. That is for an interactive session.
- S6 ended 11-23 (NO-GO); S8 finished (LOOK 2 PASS 11-26); the 11-24 window fields were read 11-24.

### What the data teaches (11-26)
- **The 30 d slide is the window, not new losses.** r30 fell from -4.93% to -8.16% over 11-21..11-26 while the last
  7 days sit at -0.24% on 124 games and 11-25/11-26 were both positive. Late-October winning days are leaving the
  window. Read the 7 d and the gate, not the r30 trend, for whether anything changed since 11-24.
- **The close-beat decline is in its fourth reading and is now gross, not just fees.** 7 d fee-net CLV went -0.99 →
  -1.18 → -1.26 → -2.17 pp (11-22, 11-23, 11-24, 11-26; 73 games, se 0.31), and 7 d gross CLV is -0.41 pp with
  beat-close 43.4% against 60.6% over 30 d. The near-zero 7 d ROI is then luck against the close, not edge.
- **The stake-quartile signal flips day to day.** On 11-24 Q1/Q2 were the beyond-noise losers and Q4 included 0;
  today Q4 (61.8% of $) is -9.21% [-17.4, -1.01] again and Q1 -11.46%. Both tails lose, the middle (Q3) is least bad.
  That is a U-shape across 397 bets a quartile, not a "big stakes lose" rule.
- **Persistent since 11-17/11-20, still beyond noise:** totals (-13.6% on 278 games), EV 2-5 (realised -11.1% vs
  claimed +4.1% on 556 games), price 0.30-0.45 (-14.3% on 141 games), Kalshi (-6.8% on 591 games). Fees 3.90% of
  stake are 48% of the 30 d loss.
- **CHANGE P cut live volume to 11 / 22 / 8 orders a day** (11-24 after the load, 11-25, 11-26) from ~59 a day. The
  gate has 12 of 800 events after 3 days, so at ~4 events a day it would take about six months.

**One optimization lead (pre-registrable, offline, changes nothing live).**
- *Hypothesis:* the stake sizer feeds claimed EV straight into Kelly. EV 2-5 is overstated by ~15 pp. So the U-shape
  comes from the overstatement being largest at the extremes of the claimed edge (small stakes on thin edges, big
  stakes on the biggest claimed edges). Shrinking claimed EV by a fitted factor before sizing would lift ROI on stake.
- *Data:* the 30 d graded live bets in the newest `live_all.json` (`ev_pct`, `requested_stake_dollars`, outcome,
  fill price, fees). Fit one shrink factor k in [0, 1] on bets selected 10-28..11-17. Recompute each bet's Kelly
  stake from k × claimed EV (bets whose shrunk stake falls below the venue minimum drop out). Compare stake-weighted
  ROI against the actual stakes on bets selected 11-18..11-26, as a paired difference clustered by game. Then do a
  forward copy on bets selected from 11-27 once it reaches 150 games.
- *Decision rule:* GO (name a shrunk-EV sizing challenger for a later betting-change window) iff the held-out paired
  difference has a 95% lower bound > 0 AND the forward copy's difference is > 0. Otherwise KILL. k is fitted once on
  the fit window and frozen; the windows are frozen as written here.
