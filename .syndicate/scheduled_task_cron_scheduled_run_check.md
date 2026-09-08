# SCHEDULED TASK — read the two cron runs of 2026-09-09

`syndicate-cron-scheduled-run-check`, one-shot, fires **2026-09-09 04:30 local
(09:30Z)**. Task file: `C:\Users\tempadmin\.claude\scheduled-tasks\syndicate-cron-scheduled-run-check\SKILL.md`.
Owed by lane `render-cron-failures` (session e371dfde).

## Why a scheduled task and not a watcher

The runs are ~9 and ~10 hours after the session that owes the reading. A
`Monitor` lives only as long as its session, so it cannot carry that. This can.

## Why 04:30 local rather than at the runs

`sim-input-reports` fires 07:00Z (02:00 local); `ci-suite` fires 08:00Z
(03:00 local) and takes **~50 min**, finishing ~08:50Z. 09:30Z leaves ~40 min of
margin.

**LATENESS IS TOLERABLE HERE, BY DESIGN.** `lastRunAt` is DISPATCH, not
execution — Modern Standby on this machine once stalled a scheduled Bash call by
9h13m. The check reads the Render **events API** after the fact, so it produces
the same answer whenever it actually runs. Do not read a late fire as a failed
check; read the artifact, not the timestamp.

## UPDATED 2026-09-08 22:0xZ — expect 15 failures, not 19

`#648`'s 4 STALE TESTS were repaired (`510b692e`) **and deployed**
(`dep-dag8d6h5efls73fi338g`, live 22:07:15Z, behind claim + `CLEAR` preflight).

**The deploy is the load-bearing half.** The cron runs its LAST DEPLOY, not
`main`, and `autoDeploy = no` — so pushing the repairs would have changed
nothing and the task would have read 19 against an expectation of 15. Checked
before deploying: `point_estimator` appeared **0** times in the test file at the
then-live `c208b5ef` and **1** on `origin/main`.

Reading guide for the task: **15** = the repairs landed; **19** = they did not
take, so check the run's commit is `510b692e` or later before calling it a
regression; anything else = report the number and the names, do not assume.

## What it must find

- `sim-input-reports` `crn-dafj4ie7bikc738q9ol0` → `successful`, and the
  READ-BACK block printing `nhl_source ... alarms=21` — the int that threw
  `TypeError: object of type 'int' has no len()` on three prior runs.
- `ci-suite` `crn-dafg4h0u01pc73aavs6g` → `unsuccessful` / `nonZeroExit: 1`,
  **and that is correct**. It must have COMPLETED (no `oomKilled`), 9 fast steps
  `rc=0`, `collected=` near 16418 with ~19 failures in ~3000s.

## The trap it is explicitly told to refuse

`ci-suite`'s daily red is 19 cause-known failures (`#648`): 15 a memory floor the
2 GB runner cannot reach, 4 stale tests owned by other lanes, **0 regressions**.
The task is instructed NOT to regenerate `tests/pytest_baseline.json` to make it
green — that would bake a HOST property into a commit-level gate.

## If the red changes shape

Two workers were deployed at `d3c7ee7c` on 2026-09-08 evening by lane
`pricing-plane-v1`. Suspicion order: those deploys first, then `#648`.

## What it writes

One append-only section in `.syndicate/deploys.md` with the actual readings, and
the `render-cron-failures` lane block edited **in place** with its goal restated
verbatim plus `GOAL: MET` or `GOAL: NOT MET`. It is read-only against Render —
no deploys, no start-command changes, no triggered runs.
