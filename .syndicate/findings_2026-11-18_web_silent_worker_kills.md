# Web's silent worker kills — findings (lane `web-silent-worker-kills`)

Started 2026-11-18 ~01:25Z (7:25 PM CST 11-17) on the user's "fix the silent web worker kills". Handed over from the
portfolio monitor (finding F3, `.syndicate/findings_2026-11-17_portfolio_monitor.md`, Readings 4-9).

## The symptom

- gunicorn `WORKER TIMEOUT` kills of a web worker that was alive and serving: the master killed it because its
  heartbeat was 60 s old (`--timeout 60`).
  - 0 a day on 11-12..11-16 (~1,550 worker boots).
  - On 11-17: 15:23:37Z (pid 4012882), 16:38:10Z (4032063), 16:49:49Z (4035235) and 21:36:36Z (19708). 16:13:23Z
    was a self-inflicted `/api/portfolio/paper` GET; that page has since been retired.
  - None since 21:36Z, as of 00:59Z 11-18.
- None of them has the `WEB_WORKER_MEMORY_RECYCLE` / `WEB_WORKER_DRAINED` lines of the older drain-path kills: 5 of
  6 kills 10-31..11-11 died in `DrainingThreadWorker.run`'s un-heartbeated `futures.wait(..., graceful_timeout)`
  after a memory recycle. These workers were in their normal loop.
- Each kill took **one** worker of the two.

## Hypotheses (written into the lane before any test)

- **H1** the worker's main loop blocks in the fast `/healthz` or accept path.
- **H2** the heartbeat itself blocks: gunicorn's `WorkerTmp.notify` writes metadata on a temp file in
  `worker_tmp_dir`, the system tmp on the WSL disk, and an I/O stall holds it past 60 s.
- **H3** GIL starvation: another thread in the same process holds the GIL in one long C call.

## Tests (read-only, 2026-11-18 01:29Z)

- **The heartbeat files are disk-backed.** `/proc/<pid>/fd` of both web workers (80731, 85631) show
  `/tmp/wgunicorn-* (deleted)`. `/tmp` is on `/dev/sdd` ext4 (`discard`, `data=ordered`), which is the
  `ext4.vhdx`. `/dev/shm` is tmpfs (7.7 G, unused). No `TMPDIR`/`TEMP`/`TMP` in the arbiter env. H2's
  precondition is true.
- **But H2 does not fit the kills.**
  - Each kill took ONE worker, while both heartbeat files sit on the same filesystem. A stall long enough to
    miss the heartbeat would have stopped both at once, so both would have been killed together.
  - The C: drive (if it fills, the vhdx cannot grow) was at 1.6 GB free only until ~10:15 AM CST (16:15Z) on
    11-17, per memory `project_c_drive_space_levers`: 37 GB at ~10:15 AM, 108 GB at 12:40 PM, 130+ later. So
    3 of the 4 kills (16:38, 16:49, 21:36Z) came with C: at 37-130 GB free. Only 15:23Z fits a full disk.
  - Pressure now (one sample, not the kill windows): io some 0.55%, full 0.08%; memory ~1%; cpu some 33%.
  - dmesg since the VM's boot (14:09:59 CST, after an unclean stop: "18 orphan inodes deleted"): no blocked or
    hung-task lines. Not evidence either way: hung-task reports start at 120 s, so a 60-120 s stall prints
    nothing.
- **H1 is unlikely by construction.**
  - `syndicate/web_worker.py`'s main loop only `select`s with a 1 s timeout and accepts on non-blocking sockets.
  - The fast `/healthz` answer is `MSG_PEEK` + a non-blocking `recv` + `sendall` under `settimeout(2.0)`, so at
    most ~2 s.
  - The locks it takes (`self._lock`, future conditions) are held for microseconds by gunicorn's own code.
- **H3 cannot be read from the logs.**
  - Response compression is not a candidate: `http_compression.py` only DECODES gzip on outbound fetches.
  - Candidates are long C calls with the GIL held: very large `json` work, sorts, regexes, pandas/C-extension
    work, a full GC over a large heap.
  - Separating H1 from H3, and naming the thread, needs a stack capture of a stalled worker. Kills are rare
    (4 in one day, then none), so a hand-run py-spy will not catch one.

## What was built: a loop-stall black box (not yet the fix)

- `gunicorn.conf.py` `post_worker_init` -> `install_loop_stall_dump(worker)` wraps `worker.notify`. Every
  heartbeat re-arms `faulthandler.dump_traceback_later`, at most every 5 s.
- If the loop does not turn for `stall_dump_seconds()` (40 s by default; always at least 10 s inside the master's
  `cfg.timeout`), the C watchdog writes EVERY thread's Python stack to fd 2 (web.log) without needing the GIL,
  about 20 s before the master's kill.
- The dump starts `Timeout (0:00:40)!`. Each worker prints `WEB_LOOP_STALL_DUMP_ARMED {"pid", "dump_after_s",
  ...}` at boot. Switch: `SYNDICATE_WEB_LOOP_STALL_DUMP_SECONDS` (0 disables).
- A HUP re-reads `gunicorn.conf.py`, so `local_production.py reload-web` loads it with no full restart.
- Tests: 6 new in `tests/test_gunicorn_conf.py`, including a real faulthandler dump fired by a starved loop
  (reachability, off != on). Results: 25 passed / 2 skipped on Windows (those 2 need `grp`); **27 passed** on the
  fleet's Linux Python.
- Read the next dump to see which thread held the loop, then fix that, under this lane.

## Deployed 2026-11-18 01:46:27Z (7:46 PM CST 11-17)

- On main `3920a2d4d`; the fleet checkout fast-forwarded from `64daca46f` at 01:46:27Z, then `reload-web` (rolling HUP,
  0 failures, healthz 200 throughout). New workers 102762/102763 each logged `WEB_LOOP_STALL_DUMP_ARMED`
  (`dump_after_s` 40, `kill_timeout_s` 60). Entry and readings: `deploys.md`, the 01:46:27Z entry.
- **How to read a dump.** Search web.log for `Timeout (0:00:40)!`. The block that follows lists every thread, the
  current one first. Look for the thread that is NOT in `selectors`/`threading.wait`/`queue.get`: that is the one
  holding the GIL (H3) or blocked in a syscall (H1/H2: then the main thread itself is in that call).
  - If `WORKER TIMEOUT` follows ~20 s later, the stall was the kill.
  - If the dump came from a worker that had logged `WEB_WORKER_MEMORY_RECYCLE` and is draining, it is the older
    drain-path stall (`futures.wait(..., graceful_timeout)` does not heartbeat), not the 11-17 mode.

## Reading 1: overnight, 2026-11-18 01:46:27Z - 12:37:58Z (7:46 PM - 6:37 AM CST)

- web.log: **0 `WORKER TIMEOUT`, 0 stall dumps, 0 `WEB_LOOP_STALL_DUMP_ERROR`**.
- 161 worker boots and 161 `WEB_LOOP_STALL_DUMP_ARMED` lines, every pid armed. Per hour (UTC): 01h 8, 02h 35,
  03h 33, 04h 34, 05h 35, 06h 9, 07h 2, 08h 2, 09-11h 0. The evening's ~35 boots an hour are memory recycles.
  - Counting trap, met here: a `substr($0,1,19) >= "2026-11-18T01:46"` filter also passes web.log.1's lines that
    start with `[` (no supervisor timestamp), because `[` sorts after `2`. That gave a false "251 boots / 161 armed"
    and a 10-01 WORKER TIMEOUT. Filter on `^2026-11-18T` instead.
- The window ended at the planned vhdx compaction: WSL was terminated 12:37:58Z and the fleet was back at 12:44:40Z on
  `09eddabf2`, still carrying the black box. The new workers 622/623 armed.
- Not a verdict. The 11-17 kills fell 15:23-21:36Z (9:23 AM - 3:36 PM CST), and this window was the evening and the
  night. The daytime window is the one that matters.

## H4, from the portfolio monitor (written 2026-11-18 16:25Z / 10:25 AM CST, before its test)

- The peer's reading (web.log, 11-18): worker 23086 served a `POST /api/intelligence/query` from `Python-urllib` (a script,
  not a browser) 16:22:07-16:22:25Z: 25,945 ms, 3.7 MB, `QUERY_STAGE_MS` rows=4906, board_read 13,216 ms. A
  `GET /api/portfolio/live` in the same worker at the same time took 25,163 ms (normally 0.2-1.7 s). Then a
  `GROWTH_EPISODE` to 1,161 MB and a hard memory recycle (drained, in_flight 0). No stall dump: the loop never went 40 s
  without a heartbeat.
- **H4:** the 11-17 kills were a heavy request of this shape (a script's large intelligence query, or another request doing
  seconds-long work) in the killed worker, long enough to starve its main loop past 60 s.
- **Falsification:** H4 is falsified for a kill if the killed pid started no long or large request in the 120 s before its
  kill: no intelligence query / `QUERY_STAGE_MS` line, no response over 10 s, only ordinary fast requests.
- By construction a Python-level request cannot keep the main thread off the GIL for 60 s (the interpreter forces a switch
  every 5 ms). Only one long C call, a full GC over a large heap, or the host starving the process of CPU can. The 25 s
  request that left no dump fits that: the loop kept turning.

## H4 tested (2026-11-18 16:27-16:31Z / 10:27-10:31 AM CST, read-only, web.log)

- **Long requests ran without kills.** `POST /api/intelligence/query` took 20 s or more 30 times: 11 on 11-17 (max 54.4 s,
  23:09:03Z) and 19 on 11-18 up to 16:22Z (max 48.6 s, 01:07:50Z). None was followed by a kill. None ran past 60 s either,
  so this alone does not rule out "a request stalls the loop for as long as it runs".
- **The kill windows show no long request.** In the 120 s before each 11-17 kill, the requests that finished (from either
  worker) were `/wnba/api/live_player_boxscore` (3-8 s), `/api/ops/version` and `/syndicate`. But an access line is written
  when a request FINISHES, so a request still in flight at the kill leaves no line. The log cannot rule one out.
- **The overlay warmer does not tell killed workers from survivors.** On 11-17, 289 of 293 boots started
  `COMBINED_BOARD_OVERLAY_WARMER`.
  - Two kills came 67 s and 74 s after their worker's first combined-board read, and two came 6.5 min and 31 min after it.
  - The warmer's rebuilds run in a web thread: `build_s` max 136.6 s and 53 of 874 at 30 s or more on 11-17; max 82.0 s
    and 42 of 631 on 11-18.
- **The 4,906-row client is `scripts/build_cheat_sheets.py`** (task `SyndicateCheatSheetPicks`, every 15 min: 10:22, then
  10:37 AM CST). Its body is the only one with `slim_aliases` False + `drop_row_diagnostics` + `row_refs`, matching the
  logged `"slim": false, "drop": true, "refs": true`. It is not the Layer 2 rail probe, which sends `slim_aliases` True.
- **Verdict: H4 is not supported as the kill mechanism, but not falsified.** A Python-level request cannot hold the main
  thread off the GIL for 60 s; only one long C call, a full GC, or CPU starvation can. The 25 s portfolio read beside the
  16:22Z query is a web-capacity matter (a 13 s `board_read` in a request thread), outside this lane.
- **Correction to H2.** The fleet's gunicorn `WorkerTmp.notify` is an `os.fchmod` that toggles the unlinked tmp file's
  mode, and `last_update()` reads `st_ctime`, which the master compares with `time.time()`. It is not `os.utime`. It is
  the same disk, so H2's precondition is unchanged.

## A continuous instrument: heartbeat-age sampler (from 16:31Z 11-18, 9 h cap)

- The dump fires only at a 40 s stall, which is rare. To see shorter stalls, a read-only sampler (session scratchpad
  `wsk_hb_sampler.py`, nice 19) `stat`s each worker's heartbeat file once a second, through the master's
  `/proc/<master>/fd`, so it reads exactly what the master reads. It prints every heartbeat gap of 3 s or more at its peak,
  plus an hourly max.
- A normal loop reads 0.2-0.8 s, measured at 16:30Z.
- If heavy requests or warmer rebuilds stall the loop for seconds, the gaps will line up with them in web.log. The 60 s
  kills would then be the tail of that distribution, and H4/H3 gets a dose-response test without waiting for a kill.

## H5, written 2026-11-18 ~19:00Z (1:00 PM CST), before its test

- Two of the four 11-17 stalls began about 60 s before the kill, at ~15:22:37Z and ~16:37:10Z. Those are the
  `:22`/`:37` slots of the 15-minute `SyndicateCheatSheetPicks` run, whose board query is the 4,906-row,
  `slim_aliases`-False POST.
- **H5:** the killed worker was serving the cheat-sheet picks board query when its loop stopped.
- **Falsification:** H5 is false for a kill if the picks run for that slot finished its board read normally, or did not
  run then. The kills fell at 09:23, 10:38, 10:49 and 15:36 CST.

## H5 tested (2026-11-18 ~19:00-19:15Z, read-only): CONFIRMED for 2 of the 4 kills

- `~/syndicate-prod/logs/cheat_sheet_picks.log` has no timestamps. On 11-17, 2 of its 96 runs failed the board read with
  `RemoteDisconnected: Remote end closed connection without response`, the error a client gets when the server process dies
  mid-request (log lines 14280 and 14294).
- **Timed by process id.** The task's processes share one pid space with the web workers, so the web workers' boots
  bracket each run:
  - the run two before failure #1 (pid 4031795) started 16:06:01-16:10:35Z, which is the 16:07Z slot;
  - the run after failure #2 (pid 4042014) started 16:49:53-16:53:06Z, which is the 16:52Z slot.
  - So failure #2 was the **16:37Z** run (10:37 AM CST) and failure #1 the **15:22Z** run (9:22 AM CST). Each matches a kill
    whose stall began ~60 s before it: 15:23:37Z (pid 4012882) and 16:38:10Z (pid 4032063).
- **What that request was.** The picks board query: `POST /api/intelligence/query`, `slim_aliases` False, ~5,000 cards.
  Then it was a **~62 MB JSON response** (decoded; ~11 MB gzip on the wire).
  - Since `row_refs` reached the picks run on 11-18 it is ~20.5 MB decoded (3.7 MB wire), last 6 runs.
- **The other two kills are not the picks run.** At 16:49:49Z the next run (16:52Z) came after it; at 21:36:36Z the stall began
  before the 21:37Z run. What those workers served is not in the log: a request killed in flight leaves no access line. The
  board page also sent ~62 MB responses until `5db26434e` (18:58Z 11-17). That makes it a candidate, but it is not shown.
- **Not yet named: how serving a big response stopped the main loop for 60 s.** Normal GIL switching rules out Python-level
  work. One GIL-holding C call over ~60 MB (json encoding), or page-fault stalls while it holds the GIL, would fit, as would
  "one worker of two" (only the worker serving it stalls). The stall dump would name it.
- **Since the picks read shrank: 0 kills** (21:36Z 11-17 to ~19:15Z 11-18, ~21.5 h, including 15:00-19:15Z of today's daytime
  window). This is believed, not a verdict.

## Recycle storm and the double-recycle hole (2026-11-18 16:48-18:48Z, portfolio monitor's report, checked here)

- Since 16:48Z (10:48 AM CST) web workers hard-recycle every 3-10 min, after 5-35 requests, at anon 830-1,020 MB against limits
  of ~630 MB.
  - Example: 18:36:06-18:36:35Z, three 20 MB-on-the-wire board-query responses (8-10 s each), then a hard recycle at
    1,011.8 MB.
- **Both workers went at once at 18:48Z.** 209505 hard-recycled at 18:48:01.6Z and 206403 at 18:48:03.3Z.
  - `gunicorn.conf.py` defers a recycle when the sibling recycled within `spacing_s` (90 s), but only `if not hard`, so two
    hard recycles can coincide.
  - The replacements booted at 18:48:09.4Z and **18:48:31.0Z**: 28 s for the second.
  - So web had no booted worker for ~6 s, and one worker for ~28 s. The heartbeat sampler shows the hole as a 27.2 s gap.
- **The master's respawn is slow.** Exit to replacement boot is 10.5 s at 17:15:39 -> 17:15:49.7Z, 4.4 s at 16:48:10.9 ->
  16:48:15.3Z, and 28 s at 18:48:03 -> 18:48:31Z. Elsewhere it is 1-3 s.
- **Serving workers stall too.** Heartbeat gaps up to 11.7 s (16:52:08Z, the 10:52 AM CST picks slot) and 5.9 s (17:13:21Z)
  came with no recycle nearby.
- The recycle path is outside this lane's declared files, and no OPEN lane holds it (checked origin/main lanes.md 19:05Z).

## Fix 1, the double-recycle hole: LOADED 2026-11-18 19:14:22Z (`db6a395ed`)

- A hard recycle now waits `SYNDICATE_WEB_WORKER_HARD_RECYCLE_SPACING_SECONDS` (30 s) after another worker's recycle,
  re-checking on every request. Only `SYNDICATE_WEB_WORKER_EMERGENCY_MARGIN_MB` (600) above the hard limit skips the wait.
- Loaded by ff + reload-web, with 0 failures. Both new workers logged `hard_spacing_s` 30.
- Baseline: 24 doubles on 11-18 before the load, every one hard. The second worker was 173-462 MB over its limit, so with
  the 600 MB emergency margin none of them would have gone at once.
- Owed: doubles since 19:14:22Z, which should be 0 apart from `"emergency": true` recycles, and the first hard hold's
  `hard_deferred_s`. Entry: deploys.md 19:14:22Z.
- Reading 1, 21:31:49Z (3:31 PM CST): the first hard hold behaved as designed.
  - 21:30:09Z pid 264694 recycled; its replacement booted 21:30:11.9Z.
  - 21:30:14Z pid 253224 (1,021.5 MB, 381 MB over its limit) was held 4.8 s after that recycle, kept serving, and went
    31.0 s later on its next request, with 0 abandoned. Its replacement booted 21:30:50.4Z.
  - Without the hold it would have gone 2.2 s after the first replacement booted, the 18:48Z shape.
  - Since the load: 0 doubles under 30 s in 10 recycles (~2.9 expected at 11-18's pre-load rate, P(0) ~ 0.06). Also
    0 WORKER TIMEOUT, 0 dumps, 0 guard errors.
  - Still owed: the 11-19 full-day count.
- Reading 2, 22:11Z (4:11 PM CST): the second hold lasted 339.6 s, not < ~35 s as predicted.
  - 22:01:06Z both workers crossed the hard line in one burst, 0.6 s apart. 268195 went; 268065 was held.
  - A held worker leaves on its next request, and 268065's next came 5 min 10 s later. Each worker here sees an app
    request only every few minutes.
  - Harmless as seen: +2.7 MB over the hold, a drain with 0 abandoned, no WORKER TIMEOUT.
  - Since the load: 0 doubles under 30 s in 12 recycles.
- The day counter for the owed reading is scratchpad `wsk_day.py` / `wsk_day.sh`. Its `silent_kills` counts 5 on 11-17:
  the lane's 4 plus 16:13:23Z, the self-inflicted `/api/portfolio/paper` GET named above.
- Reading 3, 2026-11-19 01:05Z (7:05 PM CST 11-18), checked against the portfolio monitor's F14 (its findings, reading 51):
  - F14's 01:03:21Z pair re-derived: 392526 recycled at 1,202 MB (limit 625); 0.1 s later 394203 (1,230 MB, limit 618)
    was held. The hold ordered the exits; it cannot stop both workers being over the line at once.
  - Since the load (19:14:22Z, 5.85 h): 41 recycles (37 hard, 0 emergency), 0 doubles under 30 s, 9 holds, 0 WORKER
    TIMEOUT, 0 dumps, respawn p50 3.6 s / max 15.8 s.
  - Holds ran 8.8, 13.1, 20.4, 29.6, 31.0, 180.9, 339.6 and 1,000.9 s. Each ended on the held worker's next 1-3 requests.
    1,000.9 s: 276452 went from request 10 to 11 in 16.7 min, so it served nothing in between.
  - Peaks climb through the day: max 1,323 MB at 00:14:48Z, 63 MB under that worker's emergency line (limit + 750).
    Past that line a hard recycle skips the hold by design, so doubles can come back on the evening slate. That is
    the emergency valve working, not the hole; the growth itself belongs to the endpoints, not to this lane.
  - Latent instrument flaw, not yet fired (`gunicorn.conf.py` `decide_recycle`):
    - The below-limit branch clears `_syndicate_hard_pending` but not `_syndicate_hard_deferred_at`.
    - A worker held, then dipping below its limit, then held again would log no second DEFERRED line, and its
      `hard_deferred_s` would count from the first hold.
    - Behaviour is unaffected. 0 of the 8 completed holds were exposed: a dip resets the pending flag, so the next
      non-5th request would have skipped the check, and every one recycled within 1-3 requests.
    - Fix: clear it in that branch, at the next web load.
- Reading 4: the heartbeat sampler's full run, 2026-11-18 16:30:52Z - 11-19 01:29:51Z (9 h at 1 Hz, read-only).
  - 130 gaps >= 3 s: 89 at 3-5 s, 33 at 5-10 s, 6 at 10-20 s, 2 at 20-40 s.
  - Both 20-40 s gaps came before the fix: 18:48Z 27.2 s (the double) and 18:54Z 25.7 s. None reached 40 s (the dump
    threshold) or 60 s (the kill line), which matches 0 dumps and 0 WORKER TIMEOUT.
  - After the fix, all 5 gaps >= 8 s sit in a worker's exit-to-replacement window, not on a serving worker (log lines
    matched by time):
    - 00:42Z, 18.4 s: 374502 drained with 1 request still in flight, waited 13.5 s at `web_worker.py:105`, then its
      replacement booted 5.5 s after it exited.
    - 01:03Z and 01:07Z, 14.9 / 15.4 s: the master took 15.8 s from `Worker exiting` to `Booting worker`.
    - 00:36Z and 00:26Z, 8.7 / 8.4 s: the same window. The 00:36Z respawn took 6.4 s.
  - Before the fix, 16:52Z 11.7 s was a serving worker at a picks slot (H5, above). The other pre-fix gaps >= 8 s were
    not classified.
  - Lead, not this lane's goal metric: evening respawns take 6-16 s, against p50 1.7-3.9 s.
    - That path is all gunicorn's master (reap, `WorkerTmp` create in /tmp, fork); none of our hooks runs in it.
      Cause unknown: H2's disk path or host CPU. Web runs on one worker meanwhile.
  - Also noted: `web_worker.py:105`'s `futures.wait(..., graceful_timeout)` (30 s on the fleet), and the interpreter
    joining executor threads at exit, are un-heartbeated. That is the old drain-path kill mode.
    - A kill there logs a recycle first, so it is not "silent".
    - `wsk_day.py`: every WORKER TIMEOUT on 11-17 was silent; 0 of any kind 11-18 / 11-19 so far.
- Correction: the lane status said the widening happened at "19:30Z". The fleet clock read 19:13:44Z at the baseline, so it
  was ~19:05Z.

- Reading 5: the full UTC day 11-19 (counted 2026-11-20 00:05:51Z / 6:05 PM CST, `wsk_day.py`). **Fix 1 MET.**
  - Doubles < 30 s: **0 of 184 recycles** (149 hard, 0 emergency). Before: 24 of 219 on 11-18 up to the load, 28 of 277
    on 11-17, 305 of 4,070 on 11-01..11-16 (19 a day). 14-20 were expected at the old 7.5-11.0% share.
  - 25 holds; 24 ended in that worker's own recycle (held 8.2 / 41 / 405.6 s min / median / max). The 25th left through
    lane `board-split-memory-guard`'s drained full `down`/`up` at 17:00:15Z, drained with 0 abandoned.
  - 0 emergency recycles, 0 `WORKER TIMEOUT`, 0 stall dumps. Respawn max 15.8 s.
  - Silent kills per day (the goal metric) and every `WORKER TIMEOUT` behind them:

    | window | silent kills | all WORKER TIMEOUT |
    |---|---|---|
    | 11-01..11-16 (16 days) | 0 | 5 (each after a recycle: the drain-path mode) |
    | 11-17 | 5 (4 counted; the 5th was the self-inflicted paper GET) | 5 |
    | 11-18 | 0 | 0 |
    | 11-19 | 0 | 0 |

  - Two zero days look like the 16 before 11-17. They are not evidence about the 11-17 mode, whose stall is still unnamed:
    it needs a dump. The drain-path kills (5 in 16 days before) are also at 0 since the load. Not yet a rate: at 5 in 16
    days, about 0.4 would have been expected in the 1.2 days since the load.

- Reading 6, 2026-11-20 9:36 AM CST (15:36Z), read-only (`wsk_day.py`, web.log):
  - Since the load (19:14:22Z 11-18 - 15:28Z 11-20, 44 h): 302 recycles, 0 doubles < 30 s, 0 emergency, 0 `WORKER TIMEOUT`,
    0 stall dumps. The dump watch reached its 31 h cap at 05:55:55Z 11-20 with nothing; restarted 05:56Z and again 15:32Z
    (the session had ended in between: 05:56-15:32Z checked from the log instead, 12 recycles, 0 timeouts, 0 dumps).
  - One overnight hold lasted 3,676.8 s (pid 1348221, held 06:59:08Z at 838.6 MB, recycled 08:00:25Z at 843.8 MB): +5.2 MB in
    61 min. Harmless; at night a worker sees a request every several minutes (11 an hour 07-10Z), and a hold ends on one.
  - The hold-timer flaw from Reading 3 is fixed on main, `ed5ed7581` (instrument only: the recycle decision never reads that
    field). New test fails without it (1031.0 vs 31.0); 33 passed / 2 skipped on Windows, 35 on the fleet's Linux Python.
    It loads at the next web reload by anyone; betting change no.
  - The picks board query is now ~4.2-4.8 MB on the wire in 5-10 s (6,158 cards), against ~11 MB / ~62 MB decoded on 11-17.
    A browser board query at 15:30:56Z took 26.2 s with EVERY stage ~3x its usual time (board_read 15.9 s vs ~6 s,
    drop_row_diagnostics 2.3 vs 0.4 s): the whole worker was slowed, not one step, which is what CPU or GIL contention
    looks like.
  - Started `wsk_thread_sampler.py` (scratchpad, 2 h from 15:32Z, read-only /proc): while a worker's heartbeat is >= 2.5 s
    old it records every thread's state, CPU ticks, major faults, context switches and kernel wait channel each second.
    It tells H3 (main thread waiting on futex while one other thread burns ~100 ticks/s) from H2 (main thread in D) and
    from CPU starvation, on stalls far shorter than the 40 s dump. py-spy is in the venv but ptrace_scope is 1, so it
    cannot attach to the workers without root.

## H3 CONFIRMED as the mechanism class (2026-11-20 10:06 AM CST (16:06Z); read-only)

- **The sampler caught two serving-worker stalls in 25 min** (`wsk_thread_sampler.py`, scratchpad, from 15:32Z 11-20: while a
  worker's heartbeat is >= 2.5 s old it reads every thread's /proc state, CPU ticks, major faults, context switches, wchan):
  - 15:39:44Z pid 1792398 (913 MB anon): 12.9 s. 15:41:40Z pid 1794045 (522 MB): 9.1 s.
  - Each second of both: ONE thread `R`, ~100 ticks/s (a full core), **0 voluntary context switches**. MAIN `S` in
    `futex_do_wait` with ~185-200 voluntary switches/s: it wakes every ~5 ms (the GIL switch interval) to ask for the GIL and
    never gets it. 0 major faults, no `D` state anywhere.
  - So one thread held the GIL inside ONE C-level call (Python honours the 5 ms drop request only between bytecodes). That is
    H3. H2 (the heartbeat blocked on I/O), CPU starvation and paging are excluded for these two stalls.
- **The holder was a request thread, not the overlay warmer.** In 1794045 the busy tid 1795998 started 15:40:22Z. The warmer is
  tid 1795245 (started 15:37:00Z = `COMBINED_BOARD_OVERLAY_WARMER_STARTED` 15:37:01.7Z), and it slept in `hrtimer_nanosleep`.
- **Both stalls sit inside `board_read` of a browser `POST /api/intelligence/query`** (the board page):
  - 15:39:34-15:40:13Z: 38,969 ms, `board_read` 28,001 ms.
  - 15:41:38-15:42:04Z: 27,080 ms, `board_read` 20,316 ms.
  - Both on the cold path (the same queries 23-25 s later read 8.3 and 1.3 ms).
  - This joins H5: two 11-17 kills fell on the picks run's board query, when its response was ~62 MB. Same request, a 3x bigger
    board, and the same kind of stall past 60 s is a silent kill.
- **Repro of the cold read, in a separate process** (`wsk_repro_board_read.py` under `py-spy record --gil`, nice 19):
  - Setup: web's env minus the service markers, so no warmer arms. It reads Redis and files only. 3 cold reads; the last ran
    with gc disabled.
  - `read_s` 28.0 / 19.0 / 17.2. Longest single GIL hold 0.77 / 2.07 / 0.84 s.
  - Run 1's 2.07 s was a gen2 collection: 6 gen2 = 6.64 s of a 19 s read, max 2.067 s. Run 0: 18 gen2 = 3.68 s, max 0.59 s,
    at 613 MB. So a full collection's cost grew with the heap (613 -> 794 MB).
  - GIL samples: `json` `raw_decode` 1,176 of 3,314 (35%). By call site: `_merge_layer2_shards` 396, `_hydrate_layer2_cards` 391,
    the state's `_decompress_oversized_values` 202, `game_chip_detail` 109. CSV play-by-play reads (`player_stats.py:93`) 150.
- **Not named yet: which single call ran 9-13 s in production.** The repro's decodes each stay under ~1 s. Its longest hold is a
  full GC, and that grows with the heap.
  - Lead, not proven: in a production worker, whose heap also holds the whole app and other cached boards, a gen2 collection
    inside the cold read runs 9-13 s.
  - Test: log every collection >= 0.5 s in web (`gc.callbacks`: generation, pause, triggering thread) and lower the stall dump to
    ~10 s, so the next board use names it. Both are instruments, betting change no; they need a web load.
- For lane `board-read-cold-share`: the cold read costs 17-28 s even in an idle side process, and 35% of its GIL time is `json`
  decoding of layer-2 shards and the state.

## THE DUMP LANDED: 2026-11-20 16:08:10Z (10:08 AM CST), recorded 2026-11-20 10:22 AM CST (16:22Z)

- **`Timeout (0:00:40)!` in pid 1796235** (546.9 MB anon); scratchpad watcher `wsk_dump_watch.sh`.
  - The thread holding the loop was a gthread request thread in `json.loads` (`raw_decode`). Its stack, innermost first:
    - `_decompress_oversized_values` (`pipeline/intelligence_state.py:4613`)
    - `_expand_persisted_state` (4671)
    - `_read_state_payload` (4988)
    - `_read_single_date_response_for_combining` (10393)
    - `read_combined_intelligence_response` (10498)
    - `intelligence_query_api` (`syndicate/blueprints/intelligence.py:2927`)
  - MAIN was in `selectors.select` (`web_worker.py:88`), waiting to retake the GIL. The overlay warmer was asleep (10239).
- **The request: the cheat-sheet picks run's board query** (`Python-urllib`, the 10:07 AM CST slot).
  - 82,118 ms in all; `board_read` 64,308 ms; 6,237 rows; 4.8 MB on the wire.
  - No `WORKER TIMEOUT` followed, so the stall ended between 40 and 60 s.
  - This is H5's request shape: two 11-17 kills were this run's board read.
- **The sampler in the same window**, GAP 16:07:35.3-16:08:16.5Z (peak 43.4 s):
  - thread 1796264 `R` at 99-109 ticks/s with 0 voluntary switches, every second;
  - MAIN `S` on futex, ~200 wakeups/s;
  - anon exactly 546,936 KB for 15+ s.
- **What that decode is.** The state's compressed values. The only large one is 11-21's `layer2_shortlist`: 5.2 MB base64,
  39.9 MB of JSON. The others are 0.5-0.8 MB and take ~0.01 s.
  - Side process (`wsk_decode_probe.py`, the keyvalue copy, read-only): `json.loads` takes 0.31 s with gc off and 1.10 s with gc
    on (3 gen2 = 0.24 s). On a padded heap: 2.0 s.
  - Production took 40x or more as long, at a full core.
- **Excluded so far:**
  - tracemalloc: no `TRACEMALLOC_INIT`, and `SYNDICATE_TRACEMALLOC_DIAG` is not in web's env;
  - PYTHON* debug env: only PYTHONPATH / UNBUFFERED / IOENCODING are set;
  - GC tuning: no `gc.set_threshold` / `gc.freeze` in the code;
  - a CPU quota: the cgroup has no `cpu.max`, and `cpu.pressure` some is ~1%;
  - paging: 0 major faults.
  - An ordinary full collection takes 0.52 s at 5.25M tracked objects on this host (`wsk_gc_scale.py`). A 40 s pause would need
    roughly 400M objects, which a 547 MB worker cannot hold, unless the collector itself is pathological.
- **Not yet separated:**
  - (a) a pathological GC pause inside the decode;
  - (b) the decode itself;
  - (c) the host starving that vCPU. The Windows host was 79-88% busy at 16:14Z, and Hyper-V reports no steal to the guest.
- **Instruments that separate them** are on this lane's worktree branch, commit `edaa3417d`. They are NOT on main; that waits for
  the user's go. Both are instruments only: nothing changes which request is served or when a worker recycles.
  - `WEB_LOOP_STALL`: the gap, plus the process CPU spent in it.
  - `WEB_GC_PAUSE`: every collection of 0.25 s or more, with its generation, wall pause, thread CPU and thread.
  - Tests: 39 passed / 2 skipped on Windows, 41 on the fleet's Linux Python.
  - The picks run reproduces the cold read every 15 min, so one web load answers within the hour.
- **Lead for the fix, whichever multiplier it is:** every cold board read decodes the 40 MB `layer2_shortlist`, and the board
  query may not use it. That code is in `pipeline/intelligence_state.py` (lane `board-read-cold-share` holds that file's
  combined-board read).

## Instruments live, then the decode fix live (2026-11-20 11:41 AM CST (17:41Z))

- **Deploys** (user "Yes, both"): instruments `3c8ba5b14` at 17:03:49Z (BC-054 no); the decode skip `eeeb62a63` at 17:38:47Z
  (BC-055 no). deploys.md has both entries.
- **The second dump of the day, 17:04Z, was the reload's own drain.** Old worker 1803108 had a 73.3 s board query in flight
  (`board_read` 58.4 s). It waited un-heartbeated in `futures.wait`, then in the interpreter-exit join, while a request thread
  serialized the response (`json_safety.json_safe_value`). The request finished (200); 0 `WORKER TIMEOUT`.
- **The instruments' first 35 min (17:03:49-17:38:47Z, before the fix):**
  - **302 `WEB_GC_PAUSE`, every one a full (gen 2) collection that collected nothing:**
    - in the overlay warmer's thread: 242, 236.7 s in all, max 4.19 s;
    - in request threads: 56, 36.5 s in all, max 1.66 s;
    - MainThread: 4.
  - About 273 s of whole-worker pauses in 35 min of wall time, roughly 13% (the two workers overlap, so this is the
    order of magnitude, not a precise share).
  - `thread_cpu_s` equals `pause_s` each time: real CPU work, not a starved host. The sampler's 3-4.2 s heartbeat gaps line
    up one for one (17:27:45Z: a 4.19 s GC and a 4.2 s gap).
  - 0 `WEB_LOOP_STALL` (no gap >= 5 s). Cold `board_read` 13.7 s p50 (n=6, max 58.4 s, which was the in-flight one).
- **What this says about the 40 s holds.** A full collection runs whenever enough new objects have piled up since the last
  one (more than a quarter of the long-lived count). The warmer rebuilds the board every few seconds, so a full collection
  over the whole heap follows almost every rebuild. It finds nothing, because the old board was already freed by reference
  counting.
  - Decoding 40 MB inside one `json.loads` creates ~10^6 containers, so several of these 1-4 s collections can run inside
    that ONE C call. That is the leading explanation for the 40x slowdown. It is not yet proven: no big decode has run
    under the instruments.
  - The decode skip removes the biggest single trigger. The rest is a GC-tuning question: `gc.freeze()` after boot, a
    higher gen-2 threshold, or both. That is a separate change for the user to decide, after the fix's reading.
- **Owed:** the decode skip's first-hour reading (`wsk_fix_reading.py`, waiter until 18:41Z): `STATE_DECODE_SKIPPED` on cold
  reads, cold `board_read` vs 13.7 s p50, GC pauses vs the 302 above, dumps and kills.
- **The decode skip's first hour (2026-11-20 12:42 PM CST (18:42Z); 17:38:47-18:41:34Z vs the 35 min before on the instruments):**
  - 156 `STATE_DECODE_SKIPPED`.
  - Cold `board_read` p50 3.0 s (n=10, max 7.0 s) vs 13.7 s (n=6, max 58.4 s).
  - GC pause time 2.9 s a minute vs 7.9 (-64%); the warmer thread's longest pause 1.66 s vs 4.19 s.
  - 0 loop stalls >= 5 s, 0 new dumps, 0 `WORKER TIMEOUT`.
  - So the warmer's every-few-seconds rebuild had been decoding the 40 MB shortlist too. The remaining full GCs (308 an hour,
    max 2.65 s, all collecting nothing) are the GC-tuning question, a separate decision.

## 2026-11-20 2:20 PM CST (20:20Z) -- THE 20:01:56Z KILL WAS MY INSTRUMENT: the `WEB_GC_PAUSE` hook self-deadlocked a worker's stdout

- **The dump (20:01:3xZ, pid 1860718)** put every thread at `scripts/local_logstamp/sitecustomize.py:47`, the `with self._lock` of
  `StampedStream.write`:
  - the overlay warmer was INSIDE that lock, in its `STATE_DECODE_SKIPPED` print -> `_stamp` -> `datetime.now()`. A full
    collection fired there. `on_gc` -> `_log` -> `print` -> `write` -> the same lock, same thread: `threading.Lock` is not
    reentrant, so it waits on itself forever;
  - a request thread at the same print, the access logger, the live-rail request and a board query all queued on the lock;
  - the MAIN thread in `_answer_healthz` -> `print("WEB_FAST_HEALTHZ_ACTIVE")`, its first fast healthz (~20:00:55Z). That
    stopped the heartbeat, and the master killed it at 20:01:56Z (62 s).
- **Timeline:**
  - 1860718's last pid-tagged line was 19:46:33.9Z (booted 19:44:32Z). Its threads were probably stuck from about then.
  - web.log had 0 lines from any web process 19:57:23-20:01:34Z, and 1 request 20:01:59-20:03:01Z.
  - The other roles logged normally (refresh-worker 198-689 lines a minute), so this was not a host freeze.
  - The other worker (1861480) served its 5th and last request at 20:03:02Z and recycled normally. It was not deadlocked
    (its stdout still wrote), so I read its silence as clients stuck on 1860718's connections. That is inferred, not measured.
- **Why a kill at all was luck:** the main loop prints only once per worker (its first fast healthz) or after a >= 5 s
  gap. A deadlocked worker that had already printed that line would heartbeat forever, accepting connections it never
  answers, with no kill, no recycle (`post_request` sits behind the access-log print) and no dump.
- **Fix `0d20a6919`, LOADED 20:13:38Z (BC-056 no):**
  - the callback only appends to a bounded deque; the heartbeat writes the lines (`written_after_s`);
  - reproduced in a test with the real `StampedStream` + real `gc.callbacks` + a real `gc.collect()` inside the locked stamp:
    HEAD's hook is stuck after 5 s with 0 bytes written, the fix completes;
  - at +2.5 min: 24 lines, all written by the heartbeat (max 1.03 s late), 0 dumps, 0 kills.
- **Kills per day:** 11-20 has 1 `WORKER TIMEOUT`, and it is this instrument defect, not the decode mechanism that
  `eeeb62a63` fixed. 0 on 11-18 and 11-19.
- **Lesson** (learnings.md 11-20): a gc callback, `__del__`, weakref finalizer or signal handler in a fleet role must never
  print. Every role's stdout/stderr is a `StampedStream` with a non-reentrant lock, and a collection can fire inside it.

## 2026-11-21 10:15 AM CST (16:15Z) -- 20 h on `0d20a6919`, 22.6 h on `eeeb62a63`: both hold; kills per day still owed

Read-only, nice 19. Full numbers are in deploys.md, under "reading 2" of the 17:38:47Z and 20:13:38Z web entries.

- **0 dumps, 0 kills, 0 Traceback since the GC fix loaded.**
  - Every one of the 78 workers booted since is accounted for:
    - 75 left by their own recycle line;
    - 1 was retired by the reload;
    - 2 are live and logging.
  - The same check finds the 20:01:56Z kill in the pre-fix window, so it is not blind to the outcome.
- **The 3 main-loop stalls (>= 5 s) are full collections.** Each matches a generation-2 pause on a request thread of the same worker, in the same second: 7.14 s, 10.60 s and 6.60 s.
  - The longest stall, 10.85 s, is under the 40 s dump and the 60 s kill.
  - 3,260 of 3,273 full collections collected nothing; 1,912 s of pause in 19.9 h.
  - This is what a `gc.freeze()` after warm-up, or a higher gen-2 threshold, would remove. Held on the user's "Watch kills first".
- **The decode fix holds over 22.6 h.**
  - Cold board reads over 20 s: 0 of 156. Before, 1-6 a day (1 of 243 to 6 of 340).
  - p90 4.4-4.7 s, against 6.2-9.9 s.
  - Fewer board queries since, so this is not a same-instant A/B.
- **Kills per day** (CST): 0 x5, **4** (11-17), 0, 0, 1 (the instrument, 11-20), 0 so far on 11-21.
  - The mechanism killed on 1 day in 8 before the fix, so one clean day says little.
  - The lane closes on several clean days, read with the direct measures above.

## 2026-11-21 10:20 AM CST (16:20Z) -- the slow /api/portfolio/live reads at 9:04 / 9:34 AM (Portfolio Watch): old oversized workers, not kills

The Portfolio Watch lane passed this on: 4,134 ms at 9:04 and 3,149 ms at 9:34 AM CST, against 255 ms at 8:34. Read-only from web.log, nice 19.

- **Not a kill and not my fixes.** 0 dumps, 0 `WORKER TIMEOUT`, 0 main-loop stalls in either window.
- **9:04: the read went to the worker that had done nothing for 30 min.**
  - The read was served by 2255047. Its `WEB_WORKER_MEMORY_RECYCLE` follows the access line by 5 ms.
  - That worker was 60 min old with 949 MB anon, against a 627 MB limit.
  - Its hard recycle was deferred at 8:34:03 (1,206 MB, the other worker had just recycled). It wrote no line of any kind after that until this read, 30 min later; its request count went from 5 to 7.
  - Neither worker logged a collection over 0.25 s from 9:03 to 9:05. **Cause not named.**
  - Swap is unlikely: at 10:14 the live 70-min worker held 1,277 MB resident and 10 MB in swap. That reading was taken an hour later, so it does not cover 9:04.
- **9:34: a 1.97 s full collection on the request thread of the worker that served the read** (2275430, 30 min old).
  - That collection freed nothing, and used only 0.32 s of CPU. So about 1.65 s of it the thread was not running: host CPU contention or page faults.
  - That is about 2 s of the 3.1 s read.
- **Why :04 / :34 always sees the oldest, largest workers.** In all 4 recycles in these windows, the recycle fired in the same second as the probe's burst:
  - each of the 4 came 0-5 ms after a probe request;
  - each replacement boots seconds after the probe;
  - the 2 emergency recycles came at 1,796-1,799 s of age, and the other 2 at 48 and 60 min;
  - so the next probe lands on the oldest, largest worker each time.
- The workers reached 1.2-1.45 GB anon in about 30 min by day, with 5-10 requests each. The growth runs with the board-overlay warmer, whose thread logs the full collections (up to 1.66 s each).
- Bearing: this is the same full-collection cost the held GC-tuning question is about. It now has a user-visible latency of about 2-4 s on the portfolio reads. Recorded, not acted on (user "Watch kills first").

## 2026-11-21 11:04:54 AM CST (17:04:54Z) -- a dump from an EXITING worker: ~55 s inside CPython's own shutdown; fix on main, not loaded

- **The dump:** `Timeout (0:00:40)!` followed by ONE thread, `<no Python frame>`.
  - A serving worker's dump lists the main loop, 4 request threads and the warmer.
  - One thread means the interpreter had already deleted the other thread states, which happens past atexit in `Py_FinalizeEx`.
  - No frame means the thread was in C: the final collection and the module teardown.
- **Whose:** 2300114.
  - It recycled normally at 17:04:19.478Z (1,289 MB anon, 52 min old) and logged `Worker exiting` at 17:04:19.987Z.
  - Its last heartbeat re-arm can only have fallen at 17:04:14.5-15.0Z for the 40 s timer to fire between the 17:04:50.863Z line and the watch's 17:04:54Z read.
  - Its replacement 2337523 booted at 17:05:15.731Z: about 55 s spent exiting.
  - The master's 60 s kill would have fired at about 17:05:19Z. There was no `WORKER TIMEOUT`, so it was not a kill.
- **The other worker:** 2319994 (1,351 MB) recycled at 17:03:46Z and exited in about 10 s; its replacement 2336943 booted at 17:04:21.7Z.
  - The hard-recycle spacing (30 s, timed from the last recycle DECISION) let 2300114 go 33 s later, while 2319994 was still being replaced.
  - So web had no accepting worker from about 17:04:19.9Z to 17:04:24.6Z, and one worker until about 17:05:18Z.
- **How rare** (`wsk_exit_times.py`, 10-31..11-21):
  - Exit to replacement boot over 5,296 unambiguous exits: median 1.5 s, p90 3.2 s, p99 9.2 s; 3 over 30 s.
  - 5 exits were KILLED in this shutdown, 30-60 s after `Worker exiting`: 10-31, 11-06 x2, 11-08, 11-11. None since 11-11 until this near miss.
- **Fix `b07e80882` (on main, NOT loaded).**
  - A `worker_exit` hook calls `os._exit(0)` after flushing stdio. It acts only when `DrainingThreadWorker.run` RETURNED and no request future is running; anything else takes the stock exit and says why.
  - web's only atexit work releases flock()s, which the kernel releases with the fds.
  - Switch: `SYNDICATE_WEB_WORKER_FAST_EXIT`.
  - Tests: 60 passed under the fleet venv, including a real gunicorn with the real conf recycling every 5 requests. An app atexit handler never runs with the switch on, and runs in every exiting worker with it off.
- **Load is held on a ride-along.**
  - The ff from 0d20a6919 carries 28 commits.
  - One of them is `64cd634f4` (lane `kalshi-no-grade-check`: grade_check only, not a betting change), whose lane waits for the user's yes to load it.
  - #859 (`b2ff241ae`) is inert: `SYNDICATE_NCAAF_LIVE_ENDGAME` absent = off, and no env layer names it.

## 2026-11-21 2:20 PM CST (20:20Z) -- the 24-hour reading: 0 kills on 11-21, the instrument fix holds 24 h, and the fast exit holds 11 of 11

Read-only, nice 19, from the fleet's `~/syndicate-prod/logs/web.log`. Scratchpad scripts: `wsk_kills_cst.py`, `wsk_24h_reading.sh`, `wsk_loopstalls24.sh`, `wsk_stall_context.sh`, `wsk_fastexit_reading.sh`. The deploy-side readings are in `deploys.md` (the 20:13:38Z 11-20 and 18:07:33Z 11-21 entries).

- **Kills per CST day** (read 20:14:02Z; kill = `WORKER TIMEOUT`; silent = no memory recycle first):

  | CST day | kills | silent | stall dumps | recycles | boots |
  |---|---|---|---|---|---|
  | 11-12 | 0 | 0 | 0 | 209 | 211 |
  | 11-13 | 0 | 0 | 0 | 421 | 429 |
  | 11-14 | 0 | 0 | 0 | 450 | 460 |
  | 11-15 | 0 | 0 | 0 | 326 | 326 |
  | 11-16 | 0 | 0 | 0 | 248 | 248 |
  | 11-17 | 5 | 5 | 0 | 284 | 301 |
  | 11-18 | 0 | 0 | 0 | 174 | 182 |
  | 11-19 | 0 | 0 | 0 | 160 | 162 |
  | 11-20 | 1 | 1 | 3 | 100 | 107 |
  | 11-21 (to 2:14 PM) | 0 | 0 | 1 | 44 | 46 |

  - 11-17's 5 = the goal's 4 (9:23, 10:38, 10:49 AM, 3:36 PM CST) plus 10:13 AM, which this lane caused.
  - 11-20's 1 (2:01:56 PM CST) is the `WEB_GC_PAUSE` hook deadlock, fixed by `0d20a6919`.
  - 11-21's one dump is the exiting worker (section above), fixed by `b07e80882`. It was not a kill.
  - Recycles per day fell from 209-450 (11-12..16) to 100-174 (11-18..20). The fall began before `eeeb62a63` loaded (17:38Z 11-20), and this reading does not attribute it.
- **`0d20a6919` at 24 h: MET.**
  - 0 dumps at `sitecustomize.py:47`, 0 `WORKER TIMEOUT`, 0 Traceback.
  - 105 workers booted: 100 left by their own recycle line, 3 were retired by the two reloads (each with `Worker exiting`), 2 live, 0 killed, 0 unaccounted.
  - 4,251 `WEB_GC_PAUSE` lines, all with `written_after_s` (median 0.09 s, max 3.16 s), 0 dropped.
- **Main-loop stalls >= 5 s: 5 in 24 h, max 10.85 s** (the dump fires at 40 s, the kill at 60 s). Four of them sit on a full collection that collected nothing: 7.14 s, 10.60 s, 6.60 s on request threads, and 4.80 s on the board warmer.
  - The fifth (18:10:14Z, pid 2389309) is a 5.42 s gap at 1.01 CPU per wall second with no GC pause line inside it. It came right after three full collections of 0.98-1.40 s on one request thread. Something held the GIL for 5.4 s; it is not named.
- **Full collections:** 4,223 of the 4,240 generation-2 pauses collected nothing; 2,797 s of pause in 24 h across two workers. 10 AM-1 PM CST ran 222-239 s an hour, about 3% of the two workers' wall time.
  - This is the lever for the slow reads and the loop stalls. It is not a kill cause on this reading, and it stays held on the user's "Watch kills first".
- **`b07e80882` at +2.1 h:** 11 of 11 new-config exits took `WEB_WORKER_FAST_EXIT` within 5 ms of `Worker exiting`. Replacements booted 0.18-0.84 s later (median 0.29 s; before, median 1.5 s and p99 9.2 s). 0 stock exits, dumps or kills.
- **Not established:** whether 11-17's four silent kills were all the 40 MB decode. The 11-20 dumps named that mechanism for the cold read, and kills have stayed at 0 since (bar the instrument). The 11-17 kills left no dump: the dump instrument went in later.
- **Next:** kills per CST day for the coming days, with the dump watch (`bgeqza0oy`, to ~18:26Z 11-22) catching any stall at 40 s. Then the goal verdict.

## 2026-11-22 12:30 PM CST (18:30Z) -- the day reading: 0 kills on 11-21 (whole day) and on 11-22 to 12:30 PM; the fast exit holds 83 of 83; the longest collection grew to 18.6 s

Read-only, nice 19. Scratchpad scripts: `wsk_day_reading.sh` (fired 18:30:00Z), `wsk_fastexit_day.py`, `wsk_quiet_check.sh`, `wsk_quiet_check2.sh`. The deploy-side reading is in `deploys.md` (the 18:07:33Z 11-21 entry, reading 3).

- **Kills per CST day:** 0 x5 (11-12..16), 5 (11-17), 0 (11-18), 0 (11-19), 1 (11-20, the instrument), **0 (11-21, whole day)**, **0 (11-22 to 12:30 PM)**.
  - 11-21's one stall dump is the exiting worker at 11:04 AM, which `b07e80882` then fixed. Since that load: 0 dumps; the 24-h dump watch ended `NO_DUMP within cap`.
  - Recycles: 85 on 11-21, 31 on 11-22 to 12:30 PM.
- **Fast exit at +24.4 h:** 83 of 83 new-config exits fast, 0 stock. Next boot median 0.23 s, p99 0.84 s, 0 over 2 s.
- **Workers:** 72 booted since 20:14Z 11-21; all accounted for (70 by their own recycle line, 2 live), 0 killed.
- **Main-loop stalls >= 5 s: 7 since 20:14Z 11-21, max 19.09 s.** The longest is an 18.57 s generation-2 collection that freed nothing (6:22 PM CST 11-21, request thread, 18.1 s CPU). 5 of the 7 sit on a collection of 5.65-18.57 s; two at 6:10 PM CST on one worker have no collection line.
  - The longest collection was 10.60 s in the previous 24 h. A full collection's cost grows with the number of live objects, so this is the one path seen on these readings that could still reach the 40 s dump and the 60 s kill.
  - Collections: 3,220 of 3,232 generation-2 pauses freed nothing; 2,382 s of pause in 22.3 h; 6-9 PM CST ran 246-285 s an hour.
  - Not tuned: held on the user's "Watch kills first".
- **A false alarm, recorded so nobody chases it:** web.log had no line from 18:25:55Z to 18:30:36Z, read at 18:30:36Z.
  - Quiet stretches are normal on a slow Sunday: 93 gaps of 120 s or more on 11-22 UTC, up to 1,631 s (09:07-09:34Z).
  - Both workers sat in `do_epoll_wait` / `futex_do_wait`, and healthz answered in under 1 ms.
  - A real request (`GET /`) returned 200, but took 10.5 s on a worker 7 min old. That is not attributed here.
  - Silence alone does not tell: the 11-20 deadlock also silenced all of web. What tells is a real request being served, and the stall dump (re-armed only by a running main loop) not firing.

## 2026-11-23 8:50 AM CST (14:50Z) -- GC tuning loaded (`05a2ce65e`, user "Tune GC next"): web workers start no full collection on their own; +30 min MET

Read-only readings at nice 19. Scratchpad scripts: `wsk_gctune_base.sh`, `wsk_gctune_reading.sh` / `.py`, `wsk_firstcycle.py`. Deploy entry: `deploys.md` `## 2026-11-23 14:17:09Z` (BC-058 no).

- **Kills per CST day:** 0 x5 (11-12..16), 5 (11-17), 0, 0, 1 (11-20, the instrument), 0 (11-21), **0 (11-22, whole day: 0 dumps, 102 recycles)**, 0 (11-23 to 8:49 AM).
- **Why tune, from the three days before:**
  - Full (generation 2) collections of 0.25 s or more, per CST day on 11-20 / 11-21 / 11-22: 3,344 / 3,830 / 4,262, totalling 1,910 / 3,039 / 2,364 s of pause.
  - Main-loop stalls of 5 s or more: 2 / 9 / 2, max 10.85 / 19.09 / 8.37 s.
  - They freed 7,079 objects in all, over 11,989 logged since 11-20 17:03Z. The two 470-514-object ones recur at the picks-run minutes (:03 / :22 / :43); what they hold is not measured.
  - Web runs CPython **3.11** (`/usr/bin/python3.11`), whose full collection walks the whole heap whenever the survivors since the last exceed a quarter of the long-lived count.
- **The 18.57 s one (6:22 PM CST 11-21) names a second lever, not taken here.**
  - Worker 2641469 was 79 min old at 1,199 MB against a 634 MB limit, and had served 10 requests.
  - The memory guard checks only in `post_request` (every 5th request), so a quiet worker's heap, and with it every full collection's cost, has no bound.
  - 34 s before it, an 8.66 s generation-1 collection hit the same worker. Young collections stay on, so a stall of that kind is still possible.
- **The change:** threshold 2 set to 2**31-1 in `post_fork`, with young collections unchanged. Switch `SYNDICATE_WEB_GC_AUTO_FULL`. Proof lines are `WEB_GC_TUNED`, plus `gc_collections` on `WEB_WORKER_FAST_EXIT`.
- **+30 min (14:47:30Z):**
  - 4 of 4 new workers tuned.
  - 0 `WEB_GC_PAUSE` lines of any generation from tuned workers, against 22 full ones (22.1 s, max 9.95 s) in the 30 min before.
  - The 2 tuned workers that exited counted `[4409, 401, 0]` / `[6912, 629, 0]` collections per generation: 0 full ones.
  - 0 stalls of 5 s or more, against 1 (10.0 s) before. 0 dumps, kills or Tracebacks.
  - Memory cost, early: the first-cycle tuned workers recycled soft at 485 / 823 s and 648 / 638 MB. The first-cycle workers of the 4 earlier reloads went at 156-1,510 s, 7 of 8 hard, at 760-1,190 MB. Not worse so far.
- **Owed:** the overnight reading, before the 11-24 window batch's drained down/up (08:15Z). It is the comparison against 11-20..11-22 for:
  - full collections and their pause;
  - stalls of 5 s or more;
  - recycles per hour and median age at recycle (the cost of old cycles that are no longer collected);
  - kills and dumps.
  The batch changes web's env (CHANGE F, the shared board copy), so later readings are confounded.
