# Audit — were any ledger conclusions drawn from a TRUNCATED `render_events.py` run?

`[2026-09-04, session c4287631, follow-on to lane render-events-nondict-reason]`

**Answer: no.** Every conclusion-bearing citation in `.syndicate/` and
`docs/ai_context/` used an invocation that provably could not truncate. One
citation is **not reproducible as written**; its finding independently
re-derives. Two unrelated defects surfaced and are recorded at the bottom.

The defect being audited: `render_events.py` assumed `details.reason` was a
mapping, so it raised mid-listing and left plausible partial output on stdout
with the traceback on stderr. Fixed in `ea4e3881`.

---

## Method — three gates, each MEASURED against the pre-fix binary

Not reasoned from source. The old file was checked out into the lane worktree
and run against production for each case below.

### Gate 1 — the poison set is bounded, and it is OLD

Every event on any service whose `details.reason` is not a mapping, i.e. every
event that could kill the old reader. Full unfiltered reads, 2026-09-04:

| service | events read | poison | kind | window of the poison |
|---|---|---|---|---|
| refresh-worker | 7,528 (76 pages, fully paged) | 9 | `auto_deploy_disabled` `"setting_change"` | 2026-07-01 .. 2026-07-17 |
| web | 10,000 (100 pages, **cap hit**) | 19 | `auto_deploy_disabled` — `"manual_deploy"` x10, `"setting_change"` x9 | 2026-06-25 .. 2026-07-17 |
| live-odds-worker | 8,102 (82 pages, fully paged) | 10 | `auto_deploy_disabled`, both strings | 2026-07-01 .. 2026-07-17 |

**38 poison events in total, and the last one anywhere is
`2026-07-17T19:52:29Z`.** The tool shipped 2026-08-16. **Any `--since` at or
after 2026-07-17T19:52:30Z was structurally immune** — which is nearly every
real use, because the idiom this repo actually writes is `--since <recent>`.

### Gate 2 — filtering removed the poison BEFORE anything rendered it

`_reason_detail` ran only over `selected`, i.e. after `--failures-only` /
`--type` / `--tail`. Measured on the old binary, refresh-worker, full window:

| invocation | exit | outcome |
|---|---|---|
| `--failures-only` | 0 | complete, 775 lines |
| `--type deploy_started` | 0 | complete, 1,538 lines |
| `--tail 20`, `--tail 500` | 0 | complete |
| `--json` (unfiltered) | 1 | **no stdout at all** — a caller gets a parse error, not a plausible answer |
| **bare text, unfiltered** | **1** | **288 rows then dead — the ONLY silent case** |

`--failures-only` is the form the FORBIDDEN rule, both scheduled tasks and every
brief actually prescribe. It never truncated.

### Gate 3 — even the silent case printed a COMPLETE, CORRECT summary

`kinds`, `last_failure` and the READ/EVENTS lines are computed over the whole
event list and printed **before** the first row. The crashed run's first 25
lines are **byte-identical** (`diff`, no output) to the fixed tool's — including
`748 oomKilled` in the kind counts and the `LAST FAIL` line.

So a conclusion is at risk only if it rested on the **row listing** of a bare
unfiltered text run — `| grep oomKilled`, `| tail` — and not on the summary.
**No brief does this.**

---

## Sites audited — 44 `render_events` references, 17 conclusion-bearing

| site | invocation | verdict |
|---|---|---|
| `handoff_2026-08-16_oom_22_kills.md:17` | `--failures-only --since 2026-08-16T19:55:41Z` | safe, gates 1+2 |
| `lanes_history.md:28` — 4 oomKilled in an afternoon | `--failures-only --since 2026-08-16T14:52:07Z` | safe, gates 1+2 |
| `log/2026-08-16.md:1514` — quiet 10:00-15:39Z | windowed; positive control cited | safe |
| `log/2026-08-16.md:1717` — 42 oomKilled, 806 events / 9 pages | window from 2026-08-08 | safe, gate 1 |
| `log/2026-08-27.md` §2 — 56-kill storm census | `--since 2026-08-15T00:00:00Z` | safe, gate 1 |
| `deploys_history.md:18565` — 0 `server_failed` 08-19..08-21, 132 events / 2 pages | `--since 2026-08-19` | safe, gate 1 |
| `deploys.md:15515` — `render_events` CLEAN, no `server_failed` | deploy-time window (Sept) | safe, gate 1 |
| `deploys.md:12757` — the forced-claim post-mortem | `--since <5 min ago>` | safe, gate 1 |
| `scheduled_task_oom_band.md:154` — STANDING instruction, unfiltered | `--since 2026-08-16T15:45:50Z` | safe, gate 1 |
| `scheduled_task_branch_overlap.md:39,101` — 42 kills; standing rule | `--failures-only` | safe, gate 2 |
| `candidate_2026-08-17_overview_floor_routing.md:109` | `--failures-only` (planned) | safe, gate 2 |
| `todo.md:14045` — 20 `earlyExit`, 0 kills on live-odds-worker | `--failures-only --since 2026-08-09` | safe, gates 1+2 |
| `todo.md:47285 / 47628 / 47663 / 47773` | `--failures-only` | safe, gate 2 |
| **`log/2026-08-27.md` §1** | **`--service refresh-worker`, bare** | **citation not reproducible — below** |

Also checked: `state.md`, `state_worker.md` and every `.syndicate/*.md` asserting
a kill count without naming the tool. All windows are 2026-08-19 or later —
gate 1 safe whatever was run.

**Scope limit, stated plainly:** this audits the runs that were CITED. A run
made and not written down cannot be found by any means available, and its
conclusion would carry no command to check. Every site here did cite one.

---

## The one citation defect

`log/2026-08-27.md` §1 ("THE OOM DEBT IS DISCHARGED") prints the command as

    scripts/render_events.py --service refresh-worker

bare — no `--failures-only`, no `--since` — and shows one output row,
`2026-08-16T04:46:44.460099Z oomKilled memoryLimit=4Gi`. **That run cannot have
produced that row.** Bare and unfiltered it dies at the 2026-07-01 poison event,
which sorts six weeks BEFORE the quoted line. The command is abridged or
reconstructed; it is not what ran.

**The finding itself is sound.** Re-derived 2026-09-04 with the fixed tool,
`--since 2026-08-15T00:00:00Z --end 2026-08-27T23:59:59Z`, fully paged, 15 pages:

| brief said | re-measured |
|---|---|
| 56 `oomKilled` | **56** |
| first `2026-08-15T00:04:47.024435Z` | **exact match** |
| last `2026-08-17T03:55:17.866663Z` | **exact match** |
| the `2026-08-16T04:46:44.460099Z` kill is real | **present** |
| 1,443 events | 1,459 — consistent, my window ends ~7h later |

And §2, the census the OOM-debt discharge actually rests on, carries its
`--since 2026-08-15T00:00:00Z` explicitly. **Nothing is retracted.** The lesson
is narrower and worth keeping: *cite the command you ran, with its flags* — an
abridged citation cost this audit its cheapest check and forced a full
re-derivation to clear a conclusion that was never in doubt.

---

## Two defects surfaced by the audit, unrelated to truncation

1. **`state_worker.md` asserts a zero that is no longer zero.** "34
   refresh-worker deploys since 2026-08-19T00:00Z. Zero `server_failed` in that
   whole span (EVENTS API, fully paged)" — true when written, **false now**:
   **5** `server_failed` since 2026-08-19, being four `{"evicted": false,
   "nonZeroExit": 1}` in four minutes on 2026-08-22 (19:30:36 / 19:31:38 /
   19:32:28 / 19:33:35Z) and one `oomKilled memoryLimit=4Gi` at
   2026-09-02T15:32:56Z. It is load-bearing — it is the "no measurement window
   exists" argument for `#387`. Line corrected in place with this measurement.

2. **`nonZeroExit` is an unbucketed failure reason and it is not rare.** It
   became visible only because the fix prints the raw shape of an unrecognised
   reason. Whether it is the same thing as `earlyExit` wearing a different key
   is **NOT established** — do not assume it.

   **SUPERSEDED, and the count above was too small.** This section originally
   said 10 occurrences and left the bucketing "for whoever owns the OOM lanes".
   The user decided it the same day (`[user decision 2026-09-04]`, lane
   `render-events-nonzeroexit-bucket`) and the full census is **67, not 10** —
   the 10 were only what fell inside the recent windows this audit happened to
   sample. Full unfiltered reads of all three services:

   | service | n | value | window |
   |---|---|---|---|
   | refresh-worker | 12 | `1` x12 | 2026-07-24 .. 2026-08-22 |
   | live-odds-worker | 17 | `1` x17 | 2026-07-31 .. 2026-08-27 |
   | **web** | **38** | **`137` x38** | 2026-06-15 .. 2026-07-09 |

   **`137` is `128+9` — SIGKILL** — and every one of web's 38 is a 137, while
   every one of the workers' 29 is a plain `1`. Those are not the same event
   wearing one name, so the bucket carries the CODE onto the row
   (`nonZeroExit=137 (128+9 = SIGKILL)`) rather than flattening them. A SIGKILL
   cohort on web is the shape an OOM triage looks for even where Render did not
   label it `oomKilled`; **that it IS an OOM is not established here** — the
   annotation reports the code, not a cause.

   Two further facts the census turned up: `nonZeroExit` **never** co-occurs
   with `oomKilled` / `earlyExit` / `unhealthy` / a true `evicted` (67/67 pair
   with `evicted: false` alone), so bucket order decides nothing silently; and
   **one of the 67 is a `job_run_ended`, not a `server_failed`**
   (2026-07-31T01:03:05.175631Z, `job-d9lv7vu417fc73dm37ng`) whose exit code was
   invisible on the row until now. `classify()` still, correctly, returns
   `job_run_ended` for it — a job failure is not a service failure.

Corroborations, no change needed: `state.md`'s "23 `server_failed` since
2026-08-26, `evicted: false` on all of them" for live-odds-worker re-measures at
**exactly 23**, and the raw reasons now visible confirm `evicted: false` on
every one. `state_worker.md`'s web `oomKilled 2026-09-03T01:46:58Z` matches to
the microsecond.
