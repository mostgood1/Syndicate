# Mirror — scheduled task `branch-overlap-baseline-watch`

**This file is the CANONICAL text of the task prompt.** The live task lives at
`~/.claude/scheduled-tasks/branch-overlap-baseline-watch/SKILL.md`, which is
**outside this repo and not under version control on any machine**. Same
treatment, and same reason, as `scheduled_task_clamp_watch.md`.

**It is a COPY, and copies drift.** If you change the live task, update this file
in the same pass. If they disagree, the live task is what actually runs —
reconcile deliberately, do not assume this one is current.

Created 2026-08-15 (local) as Phase 0 measurement 4 of
`.syndicate/plan_2026-08-16_sim_scheduling.md` (`#440`), lane
`sim-engine-phase0-census`. Cron `45 19,22,1 * * *` (local), notify on completion.

**Cron changed 2026-08-16 (local): `15 */4 * * *` → `45 19,22,1 * * *`.** The old
grid fired at 00:15/04:15/08:15/12:15/16:15/20:15 and so spent three of six daily
samples on hours where the failure does not happen. An OOM census over
2026-08-09..08-16 (`scripts/render_events.py --failures-only`) found **42
`oomKilled` events on refresh-worker, 41 of them between 15:00 and 23:59 local**
(29 on 08-14 alone; one outlier at 00:0x). The three retained runs cover
14:45–19:45, 17:45–22:45 and 20:45–01:45 — continuous 14:45–01:45 local, with the
kill band double-covered and ~15 min of margin at the leading edge for dispatch
jitter. Sampling frequency drops 6/day → 3/day while coverage of the band that
matters goes up.

**Why it is scheduled rather than run once.** Phase 1 changes soccer's refresh
cadence and its success claim is "the overlap fell". That is only checkable
against a BEFORE distribution. One evening's snapshot is not a distribution, and
the lane's handed-down 2026-08-16 table had already gone stale — the first run of
this watcher read **4096.0 MB (100.0% of cap)** where that table said 3,972 MB
(97.0%).

Recreate the live task from this file with the `schedule` skill or
`create_scheduled_task`.

---

---
name: branch-overlap-baseline-watch
description: Sample refresh-worker for soccer/MLB branch overlap and worst combined container memory; append to the Phase 1 baseline.
---

Take one sample of the Syndicate branch-overlap baseline. Run from `C:\Users\tempadmin\OneDrive\Coding\Syndicate`.

BACKGROUND (you start fresh with no memory of the session that created this):
The Syndicate plan `.syndicate/plan_2026-08-16_sim_scheduling.md` (pinned as `#440` in `docs/ai_context/todo.md`) will change soccer's pregame refresh cadence so that soccer stops running concurrently with MLB's evening memory peak on the `refresh-worker` service. Phase 1 is that change. It has NOT shipped yet.

This task exists to build the BEFORE baseline that Phase 1 will be judged against. A single evening's snapshot is not a baseline, and a handed-down baseline expires — so this samples on a schedule and appends, building a distribution.

STEP 1 — run the instrument (read-only; reads Render's logs API, touches no worker):

```bash
py -3 scripts/watch_branch_overlap.py --hours 5
```

It appends one JSON record per run to `reports/branch_overlap/baseline.jsonl` and prints an hour table. The 5-hour window against the 19:45/22:45/01:45 local cadence overlaps heavily on purpose — a gap in the baseline is worse than a duplicated hour, and those three windows are chosen to tile 14:45–01:45 local continuously. That band is where the failure lives: 41 of 42 refresh-worker OOM kills over 2026-08-09..08-16 landed between 15:00 and 23:59 local. Do not "helpfully" widen or shift the window; the hours are the point.

STEP 2 — read the output honestly. Three outcomes are DIFFERENT and must not be reported the same way:
- Exit code 2 with "NO LOG LINES RETURNED" → the reader failed. NOT a measurement. Say so.
- Exit code 2 with "LOG LINES PRESENT BUT NO SAMPLES PARSED" → the emitter is off or the log format changed. NOT a measurement. Say so, and check whether `scripts/render_logs.py` still supports `--width` (the script passes `--width 200000`; that tool's default of 200 truncates every sample mid-key and silently yields zero parsed samples — this exact failure already happened once).
- Exit code 0 → a real reading, even if `TOTAL both-branches-live samples` is 0. Zero overlap in an off-peak window is a fact, not a failure.

STEP 3 — report briefly:
- the COVERED window and sample count (not the requested window — they differ, and only the covered one is evidence)
- the hour table
- `WORST container (any sample)` and `WORST container while BOTH live`
- whether worst container reached `container_memory_max_mb` (4096.0 MB on refresh-worker)

STEP 4 — ESCALATE only on this condition: if `WORST container (any sample)` is at or above 4000 MB, say so prominently at the top of your report. On 2026-08-15 this read **4096.0 MB = 100.0% of cap** in three separate hours, against a previously recorded baseline of 3,972 MB / 97.0%. Since then 4096.0 has been the reading in every record — treat it as the current normal, not as news, and report the hour table and the both-live share as the informative parts.

IMPORTANT INTERPRETATION LIMITS — do not overstate:
- `container_memory_mb` is cgroup `memory.current`, which INCLUDES page cache. A high value is NOT by itself a leak or an imminent OOM. Split anon vs inactive_file before calling it either. This mistake has been made in this repo before.
- **At-cap is not a kill.** Measured 2026-08-16: a 5-hour window with `WORST container = 4096.0 MB` contained **zero** OOM events. Reclaim succeeding at the cap is exactly what page cache looks like. Never report an at-cap reading as if a kill happened.
- Never conclude "no OOM occurred" from a log search. Kills are EVENTS and appear in Render's events API, not in logs. The read-only tool for that is `py -3 scripts/render_events.py --service refresh-worker --failures-only --since <ISO>`; running it to state whether a kill did or did not occur in your covered window is in scope and does not make this a diagnosis.
- There is a separate open work lane `refresh-worker-oom-recurrence` owned by another session that owns diagnosing refresh-worker memory. This task MEASURES; it does not diagnose and must not change any code or config.

DO NOT: deploy anything, edit any file other than the appended `reports/branch_overlap/baseline.jsonl`, or open/close any work lane.

This task is mirrored at `.syndicate/scheduled_task_branch_overlap.md` in the repo, which is CANONICAL. If you change this prompt, update that file in the same pass.
