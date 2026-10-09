# Full-suite baseline on Windows — what a single pass can and cannot establish

Lane `suite-baseline-flakiness`, session 4ab694ed. Runs on 2026-10-07/08/09.

## 1. Collection: one bad file takes the whole suite to zero

MEASURED 2026-10-07, sparse worktree, with 42 of 43 `--ignore` args in place:

    22003 tests collected, 1 error in 150.34s
    !!!!! Interrupted: 1 error during collection !!!!!

22,003 tests collect and **none execute**. pytest treats a collection error as
fatal, so a single uncollectable file is not "one red test" — it is a total
outage of the suite. Worth knowing before reading any "N errors" headline.

The 43 uncollectable files in a SPARSE worktree split as:

| cause | n | what it is |
|---|---|---|
| `No module named 'vendor'` | 30 | sparse tree has no `vendor/` |
| `No module named 'sim_engine'` | 8 | same (vendor module) |
| `No module named 'wnba_betting'` | 4 | same (vendor module) |
| `No module named 'fcntl'` | 1 | a real Windows defect |

42 of 43 are sparseness, and all 42 are present and collectable in the primary
tree. The primary tree collected **22,477 tests with 0 errors**.

### The fcntl one was real (now fixed upstream, by its own lane)

`tests/test_web_worker_fast_healthz.py:28` imported `syndicate.web_worker`,
which at `:55` did `from gunicorn.workers.gthread import ThreadWorker` at module
scope -> `gunicorn/util.py:8  import fcntl`. The file ALREADY had the right idea
— its docstring says the classifier tests "run everywhere" and lines 32-37 are a
`try: import fcntl` guard — but the guard sat four lines BELOW the import that
killed collection. Fixed by lane `web-restart-healthz` (not me): pure helpers
moved to `syndicate/web_healthz.py` (imports only `os`), test imports from there.
VERIFIED STRUCTURALLY on origin/main. Their runtime numbers (20 passed /
7 POSIX-skipped) are THEIRS — I did not reproduce them.

## 2. The sparse-worktree run (the one that completed)

    331 failed, 21257 passed, 314 skipped, 1 xfailed, 11 warnings, 191 errors,
    528 subtests passed in 37755.48s (10:29:15)

Tree `b1d9ce0f` (44 behind by the end), 22,003 of 22,477 tests, one process,
serial. **Do not quote the 331/191 as a defect count.** See section 3.

## 3. A large share of failures are RUN-DEPENDENT, not real and not data gaps

Per-file isolated re-runs (whole file, fresh process, sequential, parametrize ids
normalised) of the 23 files failing as of a 31.3% snapshot:

    REPRODUCED      92   failed in the long run AND alone
    NOT REPRODUCED  56   failed in the long run, passed alone
    ONLY ISOLATED   41   passed in the long run, failed alone

Two populations, split by FILE:

- **STABLE (13 files)** — identical sets both times. `test_archives.py` 32/32,
  `test_bet_status_ncaaf.py` 10/10, `test_ask_sport_coverage.py` 4/4, ...
- **UNSTABLE (8 files)** — the set CHANGES between runs.
  `test_inplay_board_cadence.py`: **7 one run, 9 the other, ZERO overlap**.
  `test_execution_multi_venue.py`: exactly 1 each time — **a different test**.
  Also `test_intelligence.py` (40 vs 38, only 14 shared),
  `test_football_sim_engine.py`, `test_http_compression.py`,
  `test_fotmob_match_id.py`, `test_formatter.py`,
  `test_football_calibration_artifacts.py`.

Zero overlap refutes "pollution masked it" as a story; the mechanism is
nondeterminism, and these are thread / lock / launcher / socket / HTTP tests on a
host that was at 100% CPU.

The completed run's 514 named FAILED/ERROR lines across 91 files classify as:

| group | failures | files | worth |
|---|---|---|---|
| stable | 77 | 13 | real signal; names say data-dependent |
| unstable | 70 | 6 | a single pass says nothing |
| **never isolated** | **367** | **72** | **unknown** |

The isolation study was built from a 31.3% snapshot, so it only ever covered 23
files. The run went on to fail in 72 files nobody examined — `ncaaf_lines_autorun`
(25), `odds_refresh_tracking` (24), `wnba_live_refresh_autorun` (22),
`venue_poll_loop` (19) — autorun/refresh/poll-loop families, the same shape as
the files that PROVED unstable. BELIEVED, NOT ESTABLISHED.

## 4. Priority is the throughput lever, and the fleet owns the host

A/B with two simultaneous Idle controls, 30 s window, 2026-10-07:

| process | priority | CPU |
|---|---|---|
| 46348 | Normal | **94% of one core** |
| 48636 | Idle | 30% |
| 13992 | Idle | **1%** |

Later, with the fleet holding ~11 of 12 cores: the Idle run took **0.0 s of CPU
over 30 s** — total starvation. `learnings.md` already recorded the other side:
host at 100% starved the VM to 2-3.6 of 12 cores and blew the board's shortlist
step from ~120-230 s to 1,924 s. Windows sees the whole fleet as ONE Normal
process, so an Idle run yields to it completely and a Normal run competes with it
directly. USER DECISION 2026-10-07: stay at Idle, accept it may not finish.

## 5. Dead ends, so nobody repeats them

- **`xdist -n 3 --dist loadfile` "deadlocks" this suite — WRONG.** Controller and
  3 workers at 0.00 s CPU for 8.5 min looked like an execnet hang. It was CPU
  starvation at Idle on a saturated host. I asserted the mechanism, then built an
  entire args-file sharding scheme on it, which crawled identically.
- **Args-file sharding / `shard_plugin` / bin-packing to 1.0001 imbalance** —
  correct work, irrelevant: there was no spare CPU to parallelise into.
- **BelowNormal fixes I/O priority — refuted.** 0.09 s vs Idle controls at
  0.13-0.20 s. (That test was also too weak to prove anything: one 20 s window,
  no matched controls.)
- **Counting progress characters to get live pass/fail totals — unreliable here.**
  160 progress lines are interrupted mid-line by test debug dumps
  (`PROCESS_ENUM_DEBUG`, `ALL_PROCESS_MEMORY`), so a char count UNDERCOUNTS and
  silently. Use pytest's own summary line.

## 6. Open: the primary-tree run

Started 2026-10-08 08:27:49 in the primary tree at `4d9f4ade` (60 behind), one
process at Idle, no ignores. At **99%** as of 2026-10-09 11:33 — ~27 h wall,
69,503 s CPU, repeatedly starved to 0% while the fleet held the host. NOT
FINISHED; no summary line yet. It is the run that can settle section 3, because a
complete checkout removes the data-dependent class outright.

Output lives at `C:/tmp/a1-draft/final_pr.txt` (worktree run: `final_wt.txt`,
117 MB; per-file isolation results: `C:/tmp/a1-draft/rerun/*.txt`).
