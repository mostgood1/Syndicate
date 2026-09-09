# `render.yaml` env drift — what a `blueprint_sync` would ACTUALLY do, and the guard defect found on the way

`[2026-09-09, lane render-yaml-env-drift, session b56b699e — read-only on production; one guard fix landed]`

## 1. The headline correction: it is 3 reversions, not 166 deletions

`learnings.md` 2026-09-08 states that a `blueprint_sync` **"would DELETE 166 live
env vars"**, counting the keys that are live-but-undeclared (33 + 77 + 56).
**That framing is contradicted by this repo's own enumeration tool**, and the
contradiction is load-bearing because the two readings differ by two orders of
magnitude in blast radius.

`scripts/audit_blueprint_drift.py`'s docstring records the measurement:

> The 2026-08-08 sync took refresh-worker from 92 to 93 keys while the blueprint
> declared 84. A full replace would have driven it DOWN to 84. So a sync UPSERTS
> declared keys and leaves live-only keys alone.

Measured live, 2026-09-09 ~22:0xZ (read-only, GETs only):

| service | declared | live | live-only (untouched by a sync) | pinned kill switches |
|---|---|---|---|---|
| syndicate (web) | 52 | 85 | 34 | 2 |
| refresh-worker | 84 | 166 | 82 | 9 |
| live-odds-worker | 76 | 134 | 58 | 8 |

**TOTAL live values a sync would revert right now: 3 — and all three are the same
key.** `ODDS_API_KEY`, live `dca4bdaa…` against blueprint `77ae1c35…`, on all
three services simultaneously.

**I propagated the wrong framing before checking it.** Earlier in this session I
told the user a sync would delete `GUNICORN_CMD_ARGS` and take web's access log
and OOM fix with it. `GUNICORN_CMD_ARGS` is undeclared and live-only, so on the
measured semantics it is not at risk. Recorded because the `learnings.md`
sentence is quotable, alarming, and — if the upsert reading holds — wrong.

**NOT settled, and deliberately not treated as settled:** the upsert reading
rests on ONE observation of ONE sync. It has not been checked against Render's
documented behaviour. See the lane's falsification test.

## 2. A third reading arrived mid-lane and weakens the alarm further

`.syndicate/findings_2026-09-09_execution_caps_are_stored_not_env.md` (lane
`segments-joint-v1`, same day) establishes that **a stored settings store
overrides the environment entirely** for the execution caps, and has since
2026-09-04T13:21:37-05:00 — `max_order_dollars` env 10 vs **35.01 in force**,
`max_day_dollars_all_venues` env 40 vs **251.01 in force**, every field sourced
`"stored"`.

So the specific horror in the `learnings.md` entry — that a sync would rewrite a
live-money configuration via `MAX_ORDER_DOLLARS` and friends — is weakened twice
over: those keys are undeclared (a sync leaves them), **and they are not the
values in force even when present.**

## 3. The fix for `ODDS_API_KEY` is `sync: false`, NOT the live value

**This repository is PUBLIC** (`github.com/mostgood1/Syndicate`). The blueprint
carries the stale key as a literal at three sites (lines 37, 290, 763). Pasting
the working key in to "fix the drift" would publish a live credential.

Measured, 2026-09-09:

- live key `dca4bdaa…` — **0 tracked files at `origin/main`, 0 local report files.** Clean.
- stale key `77ae1c35…` — **5 tracked files**: `render.yaml`, `reports/ops_jobs.json`,
  `reports/intelligence/status_response_cache.json`, and two daily-update run
  manifests. The report JSONs contain `"ODDS_API_KEY": "77ae1c35…"` — they
  **serialise the whole env dict**, so this is a recurring leak mechanism, not a
  one-off. Anything that commits those reports republishes whatever key is live.

User decision, 2026-09-09: the old key is already revoked/dead, so the exposure
is cleanup rather than an incident — **but the mechanism that wrote it there is
untouched and would leak the next key the same way.**

`sync: false` is already used 18 times in this same file (`ANTHROPIC_API_KEY` sits
directly below `ODDS_API_KEY` and uses it). It closes all 3 reversions and keeps
the secret out of git.

## 4. THE GUARD DEFECT — found because it blocked this lane's edit

### 4a. A bare-negation prohibition was read as a claim (FIXED, landed `c1654528`)

`render.yaml` was reported held by `bandwidth-controlled-transfer` — the lane
whose `Files:` bullet exists to swear off it: *"No production code, no deploy, no
`render.yaml` — this lane cannot cause a `blueprint_sync`"*. `_claimable_prefix`
cuts at the first entry of `_DISCLAIMER_MARKERS`, and the bare negation was not
one, so the negated path survived as a claim.

**This is the second occurrence of the same bug on the same file.** Commit
`f57a02f2` (2026-09-03) added `never` for exactly this, after two lanes writing
"**never `render.yaml`**" were reported as contesting it.

Not fixed with the obvious bare `"no "`: measured over all **2,186** `- Files:`-block
lines in `lanes.md` + `lanes_closed.md` + `lanes_history.md`, bare `"no "` changes
13 lines and **5 lose a real claim** (e.g. *"(`_meta` HRR note only — no
coefficient changes), `scripts/fit_mlb_prop_calibration.py`"* drops the file it is
claiming). Losing a claim is the worse direction. The five markers shipped
instead change **4 lines of 2,186**, all genuine disclaimers; the OPEN-lane claim
map goes 70 → 69 paths, the sole difference being `render.yaml` released.

### 4b. THE BIGGER ONE, UNFIXED: the guard enforces a 726-commit-stale ledger

`lane-guard.py` resolves its root as `CLAUDE_PROJECT_DIR` — the **PRIMARY tree** —
and reads `.syndicate/lanes.md` from that tree's WORKING COPY. That tree is
**726 commits behind `origin/main`**. So the guard is enforcing the lane table as
it stood roughly two days ago. Measured with the same parser against both copies:

| | pushed ledger | what the guard enforces |
|---|---|---|
| OPEN lanes | 15 | 14 |
| claimed paths | 69 | 78 |

**SILENT GAPS — 11 paths that a currently-OPEN lane claims and the guard does not
protect at all.** This is the direction the lane system exists to prevent: two
sessions editing one file with no warning. Four lanes are running entirely
unguarded — `heap-roots-parallel-flake`, `mlb-stop-publishing-edges`,
`segments-joint-v1`, `render-yaml-env-drift` — including the production file
`syndicate/features/shared/board_enrichment.py` and
`syndicate/features/shared/memory_observability.py`.

**FALSE BLOCKS — 20 paths still protected for 3 lanes that are closed**
(`render-cron-failures`, `mlb-live-segment-pricing`,
`lead-deferral-and-lane-census`), among them 6 `vendor/mlb_bettingv2/sim_engine/`
files and `render.yaml` itself. `render-cron-failures` **CLOSED 2026-09-08** and
is archived in `lanes_history.md`; it is what blocked this lane's edit, a day
after closing.

**How it was found:** the guard refused the `render.yaml` edit and named a holder
my own collision check had not — my check read `origin/main`, the guard read the
primary tree. Neither number was wrong; they are answers about different files.

**NOT FIXED, and deliberately not fixed unilaterally.** The repair is to refresh
the primary tree's `.syndicate/lanes.md`, and that working copy holds **143 lines
`origin/main` does not** — inspected and consistent with older, untrimmed
versions of blocks main has since trimmed or archived, but every session on this
machine reads that file, and `learnings.md` already carries one incident where a
stale prefix clobbered 1,125 lines. It needs a decision, not an inference.

## 5. Owed

1. **Decide the primary-tree ledger refresh** (4b). Until then the guard is
   simultaneously blocking closed work and protecting nothing for four live lanes.
2. **`sync: false` on the three `ODDS_API_KEY` sites** — written, blocked on 4b.
   Committing is safe; PUSHING fires the sync and needs an explicit decision plus
   all three service locks.
3. **The report JSONs that serialise the env dict.** Untouched. It is the
   mechanism, and it will leak the next key.
4. **Settle upsert-vs-delete** against Render's documented semantics, so the
   `learnings.md` entry is either corrected or vindicated rather than left as two
   ledger entries that contradict each other.
