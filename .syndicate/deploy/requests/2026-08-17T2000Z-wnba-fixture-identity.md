# DEPLOY REQUEST - sweep ownership gate

**service:** refresh-worker AND live-odds-worker (both; the fix only works as a pair)
**sha:** see `main` @ the `sweep-ownership-gate` commit - **CUT DEPLOY BRANCHES FROM EACH LIVE SHA, NOT FROM `main`.** Both live SHAs were non-ancestors of `main` as of 18:00Z today (refresh-worker had 10+ commits absent from main, live-odds-worker 8). Deploying `main` reverts them.
**lane:** wnba-fixture-identity
**urgency:** normal - no outage. This has been the steady state for at least 30h and probably far longer.

## reason

`_live_refresh_loop_effective_sports` fell back to "every season-active sport"
whenever `SYNDICATE_LIVE_ODDS_REFRESH_SPORTS` was unset, ignoring BOTH
`SYNDICATE_ACTIVE_SPORTS` and the per-sport ownership flags. Measured over 30h:

```
refresh-worker    swept mlb, nfl, soccer, wnba    ACTIVE_SPORTS=nfl, MLB owner=false
live-odds-worker  swept NOTHING, any sport        ACTIVE_SPORTS=mlb,wnba,soccer, MLB owner=true
```

Both services' behaviour is the inverse of their config. The flags are set
correctly - `#129` already fought this race and recorded that live-odds-worker
is *"the sole MLB odds-refresh owner again, not just nominally excluded from a
race with another owner"* - but the sweep never read them, so refresh-worker
swept everything, won the shared unnamespaced pregame cadence marker, and
starved the designated owner permanently.

## verify - THE READING THAT PROVES IT

**Primary, and it is unambiguous because the current value is a hard zero:**
`ODDS_SWEEP_OUTCOME sport=<any>` appearing on **live-odds-worker**. It has
emitted **ZERO for every sport across 30h**. One line is proof.

**Secondary, on refresh-worker:** a new
`SWEEP_OWNERSHIP_EXCLUDED date=... kept=nfl dropped=mlb:... soccer:... wnba:...`
line, and `ODDS_SWEEP_OUTCOME sport=mlb|soccer|wnba` **ceasing** there.

**The trap:** do NOT accept "refresh-worker stopped sweeping" alone. That half
is satisfied by the gate simply breaking the sweep. **Both halves must hold -
one service stops AND the other starts** - or the result is less coverage, not
better ownership.

## rollback

Redeploy each service's current live SHA:
`POST /v1/services/<id>/deploys {"commitId": "<base>"}`. No env or config
change is involved, so rollback is code-only and immediate.

## risk

`SWEEP_OWNERSHIP_EXCLUDED` is printed whenever anything is dropped, so a
misconfigured service says so rather than going quiet. The gate excludes ONLY
on explicit config - absent `ACTIVE_SPORTS` and absent owner flags both keep
today's behaviour, and `_mlb_refresh_tick_owner_here` already defaults TRUE.
Weekly sports are deliberately NOT gated (see below).

**Cross-check before deploying:** `SYNDICATE_LIVE_ODDS_REFRESH_SPORTS` is unset
on both services today. If someone sets it, it overrides the season list and the
gate still filters it - intended, but worth knowing.
