# Deploy request — MLB conditional pitch mix + sweeper mapping fix

service: refresh-worker (the sim runs there). Web unaffected.
sha: 768f5d39  (lane commits c2030c72, f4d9e865, 7c64ee57 and neighbours)
lane: convergence-phase7-crps  (`#440`)
urgency: **LOW. Nothing is on fire and no measurement deadline depends on this.**
         An in-flight MLB sim outranks it. Bundle it whenever convenient.

## THIS IS A THREE-PART DEPLOY AND CODE ALONE IS INERT

Read this before scheduling — shipping only the code produces a silent no-op
that will look like a working feature.

1. **Push + deploy the code** to refresh-worker.
2. **PUBLISH THE ARTIFACT.** `data/mlb_source/source_artifacts/data/
   conditional_mix/conditional_mix_2026.json` (0.48 MB) is **gitignored**, so it
   does NOT travel with the push. It IS allowlisted in `HOT_ARTIFACT_PATTERNS`
   (`artifact_publisher.py:67`), so `publish_hot_artifact` is the route.
   **It also cannot be rebuilt on the worker** — the builder's input corpus
   (`vendor/*/data/raw/statcast/`) is gitignored too and is not there.
3. **REBUILD ROSTERS.** `--use-roster-artifacts` defaults ON, so any date with
   existing `roster_objs/` reuses profiles serialised before these fields
   existed. Without a rebuild, steps 1 and 2 change nothing.

I can do step 2 myself if you would rather — say the word and I will run it
rather than have you carry it.

## What ships

- **Sweeper mapping fix (the part I would ship even alone).** `ST` is 8.20% of
  2026 pitches and mapped to `OTHER` or was DROPPED in all three
  code->PitchType maps. **34.5% of pitchers (161/466) were losing a pitch type
  carrying ~23.8 usage points** — often their primary breaking ball. One map now
  (`sim_engine/data/pitch_codes.py`).
- **Conditional pitch mix**: pitch selection by count bucket x batter hand.
- `GameConfig.crn_pa_seeding` — **BROKEN, default OFF, marked in place.** It
  ships as dead code. It must NOT be enabled.

## HONEST STATUS: no market gain was demonstrated

- **Mechanism validated**, out-of-sample, no RNG: 395/512 pitchers (77.1%) better
  than the season vector; log-loss -6.21%.
- **Market: NO detectable effect.** Two seed pairs at 1920 sims gave -0.00097 and
  +0.00001 against a measured noise floor of 0.00064.
- So the case for shipping is **correctness** (the sweeper hole is a real data
  defect) plus a better-behaved engine — **not** an edge. If you would rather not
  ship a behaviour change with no measured payoff, that is a defensible call and
  I will not argue it.

## verify: (the READING, not the thing to watch)

After all three steps, on a date whose rosters were rebuilt:

  `py -3 scripts/sim_input_checklist.py --publish` on the worker, then read
  `data/sim_input_report/sim_input_report_*.json`:

  **PASS = `pitcher.conditional_arsenal` population > 0% (expect ~100%, it was
  80/80 locally) AND `conditional_arsenal_source` = `statcast_conditional_mix`.**

  **0% means step 2 or step 3 did not happen** — that is the specific failure
  this request exists to prevent, and it is indistinguishable from "deployed
  fine" without this reading.

## rollback

Revert the code commits. The artifact is additive and inert without the code —
no need to remove it. `crn_pa_seeding` is already off.
