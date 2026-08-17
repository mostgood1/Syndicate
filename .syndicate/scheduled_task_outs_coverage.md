# Scheduled task — `outs-props-coverage-check`

**Fires once: 2026-08-19 07:00 CT (12:00Z). Reads date 2026-08-18.**
Matches the `grading-freeze-payload-check` convention — fire the morning after,
read the previous date, so the slate is complete and outcomes exist.

## What it measures

The EFFECT of the 2026-08-17 ~18:3xZ cadence flip
(`SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE=true` on live-odds-worker
`srv-d91dpertqb8s73co8lt0`, single-key endpoint, own live SHA `abc9987515`).
That deploy's gate was verified RUNNING; **its effect was never measured.** This
task is the assigned reader that discharges it.

## The defect under test

MLB pitcher-props are usually fetched AFTER the slate (`retrieved_at`
02:00-05:00Z the FOLLOWING day). Books pull player-prop markets once games end,
so a post-slate fetch archives an empty market. **12 of 29 dates archived ZERO
pitchers; only 5 of 29 carried >=8 pitchers with an `outs` line.**

## Verdicts

| verdict | condition |
|---|---|
| **PASS** | 08-18 props `retrieved_at` precedes first pitch **AND** >=8 pitchers carry an `outs` line |
| **FAIL** | still post-slate, or <8 pitchers → recommend rollback, do not deploy |
| **VOID** | Gate A unproven |

**Gate A runs FIRST:** prove the flag is still `true`, that no deploy since
2026-08-17T18:40Z reverted it, and that `FIXTURE_CADENCE` lines exist during
08-18 daytime. Without it a rollback or restart would be scored as the mechanism
failing. `[the "confirm the code ran" rule]`

## Constraints written into the task

- Report a **rate with its denominator**, never a bare count.
- Any betting hit rate **must** print the side-blind baseline (ALWAYS OVER /
  ALWAYS UNDER) beside it. A grade on 148 starts read as a +12.40% model edge
  when ALWAYS OVER returned +8.16% with no model, on a 1.49 SE spread.
- One slate is not a verdict.
- **The companion fix is NOT deployed.** The monotone props seal (`bafb4fb2`) is
  on `main` and needs a refresh-worker ship. On 08-18 the cadence half is live
  and the seal half is not, so a good pregame capture can still be overwritten
  by a later thin fetch. A FAIL may be the missing seal rather than the cadence —
  the task says so explicitly.
