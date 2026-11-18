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
