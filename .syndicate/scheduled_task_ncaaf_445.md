# Scheduled task mirror — `ncaaf-445-relaunch-check`

Canonical mirror of a scheduled task, kept here because the task itself lives
outside the repo at
`C:\Users\tempadmin\.claude\scheduled-tasks\ncaaf-445-relaunch-check\SKILL.md`
and is therefore invisible to anyone reading the ledger.

| | |
|---|---|
| fires | **2026-08-17 13:50 CT** (18:50Z), ONE TIME, then auto-disables |
| created | 2026-08-16 by lane `sim-scheduling` |
| verifies | `#445` — NCAAF SmartSim2 projections reaching the CFBD fallback |

## Why this exact time, and not sooner

`#445`'s fix went live on refresh-worker at **2026-08-16 20:33:23Z**. The last
NCAAF projection launch was **~2026-08-16 18:33Z — two hours BEFORE the fix**.
Measured on `a9e5d3d6`:

    SEASON_PROJECTION_ARTIFACT_MISSING sport=ncaaf artifact_missing_after_launch
      since_launch_seconds=12588 interval_seconds=86400
      path=/opt/render/project/data/ncaaf_source/data/smartsim2_projections_2026_wk1.csv

A 24h gate on an 18:33Z launch puts the first run of the FIXED code at
**~2026-08-17 18:33Z**. The task fires 17 minutes later.

**Two hypotheses were tested and BOTH refuted** before settling on this:
- NOT `#341` starvation — `season_projections` reaches ncaaf on nearly every tick.
- NOT "ran and quietly passed" — the artifact is still absent.

## The robust signal

Not the launch line (lossy logs drop it), but **`since_launch_seconds` RESETTING
to a small value**, which proves a new launch occurred.

## Outcomes the task must distinguish

1. CONFIRMED FIXED — `ENGINE_SCHEDULE_ABSENT` present, no crash, and
   `SEASON_PROJECTION_ARTIFACT_MISSING` STOPS.
2. FIXED BUT A NEW DEFECT — fallback reached, still no artifact. **The CFBD
   fallback has never executed in production**, so this is a live possibility.
   New ticket, do not reopen `#445`.
3. NOT FIXED — old crash line returns. Check the live SHA still carries the fix
   first; this service has silently reverted a fix before.
4. INCONCLUSIVE — no reset, so no new launch. Not a pass and not a fail.

## Caveats written into the task

- `render_logs.py` needs `--width 200000`; a truncated `86400` was once read as
  `8640`, a 10x error.
- Never compute a count or rate from `render_logs.py` — a requested 3-minute
  window has returned 0.23s of logs. Presence only.
- Commit by plumbing on a freshly fetched `origin/main`; never `git add` in the
  shared index. This session lost a commit outright to a concurrent branch
  rewrite, and lost `deploys.md` rows written between an append and a
  `hash-object`.
- Scheduled tasks only run while the app is open; if closed, it runs on next
  launch — so a late run is expected, not a failure.
