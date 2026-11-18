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
- Correction: the lane status said the widening happened at "19:30Z". The fleet clock read 19:13:44Z at the baseline, so it
  was ~19:05Z.
