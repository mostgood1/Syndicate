# Findings 2026-11-16 — the session-start hook ran past its 20 s timeout; now 2.5-5.8 s

Lane `session-start-hook-runtime`, todo `#822`, session 2f342db9. Change on main as `73398cdf4`, and
on the primary tree since the 01:57:41Z fast-forward (7:57 PM CST 11-16, `primary_tree_ff.py --apply`,
CLEAR, 2 behind).

## Verdict

- **Before** (primary tree, 7:38-7:42 PM CST): untraced 16.06 / 16.23 / 19.32 / 23.00 / 25.08 s, median
  19.3 s. That is against `"timeout": 20` in `.claude/settings.json`, so **3 of 5 runs went over**. A
  killed hook delivers no digest at all.
- **After** (primary tree, 7:58 PM CST): untraced 2.46 / 2.60 / 2.62 / 2.89 / 2.92 s, median 2.6 s.
- **Same-instant A/B** (the old hook, byte-identical to `51677774d`, the change's parent, run
  alternately with the new one on the same tree).
  The before/after pair above is CONFOUNDED BY HOST LOAD, so this is the fair comparison:
  - primary tree, 8:00 PM CST, 5 pairs: old 11.24 / 10.91 / 10.89 / 11.38 / 12.28 s, new 3.20 / 3.16 /
    2.73 / 5.43 / 2.88 s;
  - worktree, ~7:52 PM CST, 3 pairs: old 23.16 / 18.48 / 15.47 s, new 5.82 / 3.55 / 3.54 s.
  - Every pair's stdout is BYTE-IDENTICAL (`cmp`), at 2056 B on the primary and 1683 B in the worktree.
    stderr was 0 B on both sides. The primary pairs carried a live `BETTING CHANGES` line and a live
    `LEDGER INCOHERENT` verdict, so the betting job and a non-zero checker both went through the new path.
- **Max measured after the change: 5.82 s** (worktree) and 5.43 s (primary), against a target of ~12 s.
  - Under the HEAVIEST baseline load (old hook 35.4 s traced), the new hook is BELIEVED to stay under
    ~10 s, but that is NOT MEASURED. The extrapolation: old/new ran 3.5-4x apart in every same-instant
    pair; under load the old hook's cost grew mostly through its ~60 forks, and the new one has ~13.
    The host was not loaded on purpose to test it, because it is the live fleet.

## Where the time went (5 traced runs per side, `bash -x` with `PS4='+@${EPOCHREALTIME}@${LINENO}| '`)

The method: each trace line's duration is the next line's timestamp minus its own, summed by the hook's
line ranges. Python calls are attributed by the script named on the line. The tools are
`hookprof.py` and `sections.py` in this session's scratchpad. The traced and untraced runs were taken
minutes apart on a host whose load moves, so compare within a table, not across tables.

### Before (primary tree, 7:38-7:40 PM CST)

| section | median s | max s | runs |
|---|---:|---:|---|
| census (`lane_census.py --digest` + 2 greps) | 1.65 | 2.73 | 1.03 1.65 2.66 2.73 1.41 |
| rules (grep/sed/cut/tail/head pipelines) | 1.27 | 1.86 | 1.06 1.86 1.21 1.27 1.48 |
| header (`git rev-parse`) | 0.23 | 1.31 | 0.20 0.23 1.31 0.23 0.61 |
| obligations (2 greps) | 0.39 | 0.96 | 0.37 0.37 0.96 0.39 0.65 |
| **state_sizes (`wc` + `tr` per file: 30 forks)** | **4.42** | **13.73** | 3.57 4.42 11.07 13.73 3.65 |
| lanes/learnings sizes (+ `lane_census.py --budget-digest`) | 1.71 | 2.88 | 1.57 1.71 2.02 2.88 1.10 |
| coherence `check_lane_claims.py` | 2.71 | 4.42 | 1.32 1.21 3.03 4.42 2.71 |
| coherence `check_lane_invariants.py` | 2.97 | 6.82 | 2.72 2.97 6.82 2.94 3.70 |
| coherence `lane_identity_check.py` | 0.51 | 0.74 | 0.51 0.48 0.74 0.71 0.40 |
| coherence `state_key_check.py` | 0.47 | 0.81 | 0.35 0.32 0.47 0.81 0.64 |
| coherence `todo_id_reconcile.py --no-history` | 0.48 | 1.34 | 0.48 0.44 1.34 0.54 0.48 |
| coherence (loop/bash) | 0.02 | 1.76 | 0.02 0.01 0.02 1.76 0.01 |
| `primary_tree_ff.py --digest` | 0.41 | 0.84 | 0.39 0.38 0.84 0.44 0.41 |
| `betting_change.py digest` | 0.99 | 1.34 | 0.99 0.80 1.31 0.86 1.34 |
| closed lanes (grep) | 0.39 | 0.78 | 0.39 0.30 0.78 0.40 0.32 |
| emit (`printf\|wc\|tr`, `printf\|head`) | 0.46 | 0.93 | 0.46 0.93 0.49 0.33 0.39 |
| `primary_tree_ff.py --spawn` | 0.35 | 1.16 | 1.16 0.42 0.33 0.35 0.28 |
| **total (traced span)** | **19.58** | **35.39** | 16.60 18.49 35.39 34.79 19.58 |
| wall, outside bash | 19.73 | 35.55 | 16.77 18.70 35.55 34.92 19.73 |

### After (primary tree, 7:58 PM CST)

| section | median s | max s | runs |
|---|---:|---:|---|
| runner launch (one process substitution) | 0.04 | 0.04 | 0.04 x5 |
| sizes (ONE `wc` over every alarm file) | 0.12 | 0.13 | 0.12 0.13 0.11 0.13 0.11 |
| census (2 greps; the census is a runner job) | 0.30 | 0.31 | 0.30 0.29 0.26 0.31 0.31 |
| rules (unchanged pipelines) | 0.71 | 0.81 | 0.71 0.66 0.74 0.68 0.81 |
| header (`git rev-parse`) | 0.15 | 0.17 | 0.14 0.15 0.14 0.15 0.17 |
| **wait for the runner (all nine checks)** | 0.27 | 0.28 | 0.21 0.27 0.28 0.28 0.25 |
| obligations (2 greps) | 0.25 | 0.29 | 0.25 0.22 0.25 0.23 0.29 |
| state + lanes/learnings sizes (array lookups) | 0.01 | 0.01 | 0.01 x5 |
| coherence / primary_ff / betting (reads) | 0.00 | 0.00 | 0.00 x5 |
| closed lanes (grep) | 0.10 | 0.12 | 0.10 0.10 0.09 0.10 0.12 |
| emit (`LC_ALL=C` builtins) | 0.00 | 0.00 | 0.00 x5 |
| `primary_tree_ff.py --spawn` | 0.18 | 0.20 | 0.17 0.19 0.17 0.18 0.20 |
| **total (traced span)** | **2.10** | **2.31** | 2.04 2.06 2.10 2.10 2.31 |
| wall, outside bash | 2.18 | 2.39 | 2.13 2.14 2.18 2.18 2.39 |

### Each check when all nine start together (primary, ~8:01 PM CST, 5 runs)

| check | median s | max s |
|---|---:|---:|
| `check_lane_invariants.py` (the critical path) | 1.66 | 1.84 |
| `check_lane_claims.py` | 1.35 | 1.52 |
| `betting_change.py digest` | 0.58 | 0.68 |
| `todo_id_reconcile.py --no-history` | 0.52 | 0.58 |
| `lane_census.py --digest` / `--budget-digest` | 0.50 / 0.50 | 0.51 / 0.58 |
| `lane_identity_check.py` | 0.44 | 0.51 |
| `state_key_check.py` | 0.42 | 0.47 |
| `primary_tree_ff.py --digest` | 0.27 | 0.29 |
| **all nine done** | **1.67** | **1.85** |

## What the cost actually was

The brief's hypothesis was ten interpreter start-ups. That was HALF right.
- Interpreter start-up is 0.15-0.47 s each here (`python -c pass`, 3 runs).
- The larger and more VARIABLE cost was **forked helper processes**. Each one is 0.12-0.45 s on this host:
  a single `$(wc -c < f | tr -d ' ')` measured 0.237 s. The state-size loop forked 30 of them and took
  3.6-13.7 s, the largest single section and the one that grew most under load.
- `check_lane_invariants.py` is CPU-bound. cProfile: 4.47 of 5.85 s in
  `lane_claims.sections_are_disjoint` (46 calls -> 17,084 `_claims` -> 4,756 `_mask_backticked`).
  Running it concurrently hides it behind the bash work. It does not shorten it.

## The change (`73398cdf4`)

- `scripts/session_start_jobs.py` (NEW) starts every python check as its own child at once and waits
  for all of them, bounded by a 13 s deadline. It prints `KEY<TAB>STATUS<TAB>OUTPUT` per job, then
  `@@END<TAB>n`. OUTPUT is byte-identical to what `$(python ... | head -c N)` assigned under MSYS bash:
  the cap first, then NULs dropped, then trailing `\n` and `\r\n` stripped. Measured in Git Bash 5.2.37:
  `$(printf 'a\r\r\n\n')` gives `a\r`, and a lone trailing `\r` is kept.
- The hook launches it with `exec {fd}< <(python ...)` at the top. Each result is read where its serial
  call stood: CENSUS under OPEN LANES, WHERE in the lanes.md alarm, and the coherence loop, PRIMARY_FF
  and BETTING in their own places. The coherence list moved to the top (`COHERENCE_CHECKS`) so that
  the launch and the loop share one list.
- File sizes come from ONE `wc -c` into an associative array. The `for f in lanes.md:550000
  learnings.md:460000; do` line is unchanged, because `ledger_caps.py` parses it (its test: 7/7).
- Body byte length and cut use `local LC_ALL=C` builtins (`${#BODY}`, `${BODY:0:$BUDGET}`). They are
  byte-exact under a UTF-8 locale: measured 3 chars, 5 bytes, cut `61 e2`.
- **Every check still runs.** `--budget-digest` now runs every time (its text is still used only over
  the cap).

## Fail-open, verified

- `tests/test_session_start_jobs.py`: **29 passed**. It runs the REAL hook on a fixture tree of stub
  scripts and covers:
  - every result reaching its line (off != on);
  - PATH without python: exit 0, `(census unavailable)`;
  - the runner missing: exit 0, `[python checks NOT RUN: ...]`;
  - the runner dying with no `@@END`: exit 0, `[python checks: runner ended with no result ...]`;
  - each of the 8 check scripts missing in turn: exit 0, no traceback, the rest still reported;
  - runner unit tests for the MSYS strip cases, the cap, missing / timeout / non-zero, and
    concurrency (4 x 1.5 s sleeps finish in < 5 s).
- Real worktree with `PATH=/usr/bin` (no python): rc 0, stderr 0 B, no traceback, `(census unavailable)`.

## New, and loud on purpose

A check killed at the deadline goes to DIGEST NOTES as `NOT FINISHED, so not verdicts`. So does a missing
or dead runner. Before this change a hung check made the harness kill the whole hook, and a missing
`python` silently dropped every check. Neither case prints anything when things are healthy, so the
healthy output did not change by one byte.

## Leads (not followed)

- `lane_claims.sections_are_disjoint` is now the hook's critical path (1.7 s concurrent, 2.6-6.8 s
  serial under load). It also runs inside `lane-guard` on every Edit/Write. Memoising
  `_claimable_prefix` / `_mask_backticked` per section text looks like most of it. That file is
  lane-guard's parser, so it is its own lane.
- The rules section still forks ~10 times (0.7 s), but that cost overlaps the runner, so cutting it
  would buy little.
