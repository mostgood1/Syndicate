# Deploy requests — THIS QUEUE IS RETIRED (2026-08-18)

**Nobody drains this directory. Do not add to it.**

The coordinator session that consumed these requests is retired — see
`.syndicate/coordinator.md` for why, and `CLAUDE.md` → "Before any deploy" for
what replaced it. In short: deploys are now self-serve behind two locks you take
yourself.

```bash
python scripts/deploy_claim.py acquire --service <svc> --holder <lane>
python scripts/deploy_preflight.py --service <svc> --holder <lane>
# then deploy, then record the measurement, then release the claim
```

## The two requests left pending here are now their own lane's to execute

Neither was ever granted; `../grants/` was empty when the role was retired.

| file | lane | still owed |
|---|---|---|
| `20260818T151633Z-convergence-phase7-crps.md` | `convergence-phase7-crps` | unread by anyone — the owning lane should re-read it and decide |
| `20260818T154432Z-football-model-owner.md` | `football-model-owner` | **yes.** Two-part, ordering-critical, 11-day clock to the 2026-08-29 NCAAF opener |

**The football one carries a constraint that outlives the queue, so it is
repeated here rather than left to be rediscovered:** deploy web `752a866d`
FIRST or together with setting `CFBD_API_KEY` on refresh-worker. Key-alone is
the one combination to avoid — it makes the board serve 16 of 51 games while
`verify:` passes, because the pre-`752a866d` `[:16]` cap would cut the newly
populated slate straight back down.

## What was worth keeping from the request format

The `verify:` field. Name the READING that proves the deploy worked, not the
thing you intend to watch. "Watch the memory profile" is not a verification;
"`LEDGER_CHUNKS_ACCEPTED` falls below 830,832,574 within one bundle" is. That
discipline moves to the measurement row in `.syndicate/deploys.md`, which is
where it always ended up anyway.
