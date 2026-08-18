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
| `20260818T151633Z-convergence-phase7-crps.md` | `convergence-phase7-crps` | **yes, and the lane is LIVE** — it held the web claim at 21:46Z. Three-part and ORDERING-CRITICAL (see below). Its own to execute. |
| `20260818T154432Z-football-model-owner.md` | `football-model-owner` | ~~yes~~ **NO — ask discharged 2026-08-18 21:43:32Z.** `verify:` still pending. |

**Football: DISCHARGED, and the ordering constraint was honoured.** `CFBD_API_KEY`
is SET on refresh-worker (`deploys.md` 21:43:32Z, key count 105 → 106). Web
`841b6d84` — carrying the `[:16]` cap fix — went live at 20:31:26Z, *ahead* of
the key, so key-alone never happened. **`verify:` has NOT passed yet:** baseline
is `0 of 51` games with a non-null `predictions.home_mean`, PASS is `51 of 51`,
due within one autorun cycle (≤24h from 21:43Z). Discharged ≠ verified.

**Convergence: the constraint that outlives the queue is that CODE ALONE IS
INERT.** Shipping the push and nothing else produces a silent no-op that reads
as a working feature. All three steps or none: (1) deploy code to
refresh-worker, (2) `publish_hot_artifact` for
`conditional_mix_2026.json` — it is **gitignored so it does not travel with the
push**, and it cannot be rebuilt on the worker because its input corpus
(`vendor/*/data/raw/statcast/`) is gitignored too, (3) **rebuild rosters** —
`--use-roster-artifacts` defaults ON, so any date with existing `roster_objs/`
reuses profiles serialised before these fields existed, and without the rebuild
steps 1 and 2 change nothing.

## What was worth keeping from the request format

The `verify:` field. Name the READING that proves the deploy worked, not the
thing you intend to watch. "Watch the memory profile" is not a verification;
"`LEDGER_CHUNKS_ACCEPTED` falls below 830,832,574 within one bundle" is. That
discipline moves to the measurement row in `.syndicate/deploys.md`, which is
where it always ended up anyway.
