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
- **H2** the heartbeat itself blocks: gunicorn 21's `WorkerTmp.notify` is an `os.utime` on a temp file in
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
