# Deploy request — smaps reconciliation fix

    service:  refresh-worker
    branch:   deploy/smaps-anon-breakdown
    sha:      c7747a29        (rebased onto 32186e28, the sha live at 23:47:34Z)
    size:     2 files, +108/-10 — `memory_observability.py` + its test
    urgency:  LOW. Cosmetic. Nothing is blocked and nothing is broken.

## Why this is a request rather than a deploy

Three different sessions held the refresh-worker claim in 70 minutes
(`live-game-line-projection` 22:37, `coordination-session` 23:07,
`red-intelligence-tests` 23:31) and the live sha moved twice underneath a rebase
(`6f512ffa` -> `129395cc` -> `32186e28`). Racing for a window was costing a rebase
per cycle and losing. This is section 3 of `coordination-protocol.md` used as
intended: **agents prepare, the next deployer executes.**

## What it does

The smaps reader currently reconciles its PER-PROCESS anon total against cgroup
`anon`, which counts the whole CONTAINER. This worker runs 8-10 children holding
~504MB, so it reports `reconciles: false` on every single read — measured 27.0%
apart on its first production read. A guard that always fires is a guard nobody
reads.

After: it compares against `RssAnon` from `/proc/self/status` — same scope, same
bytes, counted a different way. Tolerance tightens 10%/64MB -> 3%/16MB. The
container figure is kept, renamed `cgroup_anon_mb_CONTAINER_SCOPE`, with the
difference exposed as `other_processes_anon_mb`.

## Blast radius

**Instrument only.** No board, projection, odds or product path. It changes what
a diagnostic compares itself against and nothing else. It cannot confound any
measurement lane — if your metric is board output, this is invisible to it.

## Verify after deploying

Next `SMAPS_ANON` line should carry `"reconciles": true` with
`process_rss_anon_mb` close to `total_anon_mb`, and `other_processes_anon_mb`
showing the children as a labelled figure rather than an unexplained gap.

## Rollback

Previous sha `32186e28`. The change is additive; reverting loses only the
corrected self-check.

## Tests

11 in `tests/test_smaps_breakdown.py`, 46 with `test_memory_watchdog`, all green
on this exact base. Both files byte-identical to the version tested on the two
earlier bases.
