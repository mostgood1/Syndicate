# Deploy request — the odds-sweep ownership gate (BOTH workers)

```
service:  refresh-worker AND live-odds-worker  (both; refresh-worker first)
sha:      `20025cc4` ("the odds sweep now honours the ownership flags the tick
          already honours"), on origin/main. CUT EACH ON THAT SERVICE'S OWN LIVE
          SHA -- refresh-worker 8c0bd8e6, live-odds-worker abc9987515. DO NOT
          deploy main's tree; the three lineages diverge.
reason:   refresh-worker sweeps mlb/wnba/soccer while owning only nfl, wins the
          shared cadence marker, and starves the designated owner.
verify:   `SWEEP_OWNERSHIP_EXCLUDED` on refresh-worker naming the dropped sports,
          AND an MLB pregame sweep appearing on live-odds-worker. Two-sided --
          see below.
rollback: redeploy 8c0bd8e6 / abc9987515 respectively. Code-only, no env.
urgency:  ELEVATED but not an incident -- it blocks a measurement already
          scheduled for 2026-08-19 07:00 CT. Ideally live before 08-18 slate.
```

**NOT MY CODE.** `20025cc4` is another session's work (the lane that authored
`7c4439f4` / `dca1cfbc`). I am requesting its deployment, not claiming it. If
that session is active it should be asked first — I could not reach it.

## Why this is undeployed and nobody noticed

**Measured 2026-08-17 ~19:2xZ, by CONTENT against each service's live SHA (not
ancestry):**

    refresh-worker     live=8c0bd8e6    _sweep_ownership_exclusion present = FALSE
    live-odds-worker   live=abc9987515  _sweep_ownership_exclusion present = FALSE

The fix is on `main` and **running on neither worker**. The defect it fixes is
therefore still live in production right now.

## What it fixes

`_live_refresh_loop_effective_sports` fell back to "every season-active sport"
whenever `SYNDICATE_LIVE_ODDS_REFRESH_SPORTS` was unset, ignoring BOTH
`SYNDICATE_ACTIVE_SPORTS` and the per-sport ownership flags. Measured over 30h
by the authoring lane:

    refresh-worker    swept mlb, nfl, soccer, wnba   (ACTIVE_SPORTS=nfl,
                                                      MLB_REFRESH_TICK_OWNER=false)
    live-odds-worker  swept NOTHING, for any sport   (ACTIVE_SPORTS=mlb,wnba,soccer,
                                                      MLB_REFRESH_TICK_OWNER=true)

The non-owner sweeps, wins the shared unnamespaced cadence marker, and starves
the designated owner.

## Verify, in full — two-sided, and both halves are needed

**On refresh-worker**, the gate emits by design (it refuses to drop a sport
silently):

    [live_refresh_loop] SWEEP_OWNERSHIP_EXCLUDED date=<D> kept=<...> dropped=mlb:SYNDICATE_MLB_REFRESH_TICK_OWNER=false wnba:not_in_SYNDICATE_ACTIVE_SPORTS ...

PASS half 1 = that line appears and `dropped` names mlb.

**On live-odds-worker**, the point of the fix is that the owner stops being
starved. PASS half 2 = an MLB pregame sweep actually runs there
(`PREGAME`/`FIXTURE_CADENCE` lines for `sport=mlb`) in a window where previously
only refresh-worker swept.

**Half 1 alone is not sufficient.** It proves the non-owner stopped; it does not
prove the owner started. The whole failure mode was that one service's silence
looked like health.

## Why it is time-sensitive

Scheduled task `outs-props-coverage-check` fires **2026-08-19 07:00 CT** to
measure the fixture-aware cadence flip (live on live-odds-worker since
2026-08-17 ~18:3xZ). **That measurement is uninterpretable while the starvation
is live:** a weak result cannot be told apart from the owner never having been
allowed to sweep. The task carries a Gate B that will correctly report
INCONCLUSIVE rather than FAIL — but an INCONCLUSIVE costs a day and the slate.

Deploying this before the 08-18 slate converts that scheduled read from
"probably inconclusive" into a real measurement.

## Risk

- **Code-only.** No env, no `render.yaml`, so no `blueprint_sync`.
- **refresh-worker is the OOM-sensitive service** (`#449`) and owns the MLB daily
  sim — check for an in-flight sim before firing, and pick the window.
- **Expected effect is a REDUCTION in work**: refresh-worker stops sweeping three
  sports it does not own. OddsAPI spend should fall, not rise. That is the safe
  direction against a cap at ~62.7% with MLB at 93% of spend.
- **Weekly sports are deliberately NOT gated** by this change — the authoring
  lane's docstring records that gating them broke
  `test_run_tick_claims_weekly_sports_on_game_days` and would reintroduce the
  24-hour NFL capture gap measured 2026-08-07. Do not "improve" that on the way
  past.
- An empty `kept` is a legitimate answer for a service whose owned sports are all
  out of season, and is logged rather than silent.

## Related, and deliberately NOT requested

Namespacing the cadence marker was **considered and rejected in code** by the
authoring lane: *"That would treat the symptom and leave an ungated sweep running
on the wrong service; the ownership flags are the intended mutex."* With this
gate deployed the shared marker becomes a safety net — if the gate regresses, a
shared marker throttles the stray sweep instead of allowing two independent
ones. **Do not namespace the marker as part of this deploy.**

Requested by lane `convergence-phase7-crps` (`#440` Phase 7), which is blocked on
the measurement rather than on the code.
