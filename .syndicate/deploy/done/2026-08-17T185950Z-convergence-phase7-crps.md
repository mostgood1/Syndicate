# Deploy request — monotone pregame props seal

```
service:  refresh-worker
sha:      the seal is on origin/main (7c4439f4 at filing), commit bafb4fb2.
          CUT IT ON refresh-worker's OWN LIVE SHA 8c0bd8e6 (dep-da1kftnqj5pc73d8vvj0,
          live 2026-08-17T17:48:53Z). DO NOT deploy main's tree -- state.md:
          the three services run separate lineages and main never received
          21/52/40 of their commits.
reason:   the pregame pitcher-props seal could never improve a thin capture and
          could downgrade a good one; both directions are now monotone.
verify:   on the first full post-deploy date D, the FROZEN doc must beat the LIVE
          doc it was copied from. See "verify, in full" below -- one reading,
          next morning.
rollback: redeploy 8c0bd8e6. Code-only change, no env, no render.yaml.
urgency:  NONE. Nothing is blocked and no incident is open on this.
```

## What it changes

`_freeze_oddsapi_pregame_markets` in `scripts/refresh_mlb_oddsapi.py`. The two
branches were each wrong in one direction:

- **clock UNKNOWN** was first-write-wins → the first pass of the day sealed
  whatever existed and could **never improve**. 2026-08-08 sealed 1 pitcher and
  2026-08-09 sealed 2, permanently.
- **clock KNOWN** re-copied **unconditionally** while pregame → a later thinner
  fetch could **downgrade** a good seal.

Now: a poorer doc never replaces a richer one; a strictly richer one always may.
Monotonicity is self-protecting against the case first-write-wins was defending —
a post-slate doc is empty, so it scores lower and cannot overwrite a real
pregame seal even with no clock to prove pregame-ness.

Richness counts **priced sides**, not bytes or players: a line with no odds is
not gradeable, and a doc can grow in bytes while carrying fewer usable markets.

## Verify, in full — the reading, not the thing to watch

Take it the **morning after** the first full post-deploy date `D`.

    frozen = oddsapi_pitcher_props_<D>_pregame.json     (the seal)
    live   = oddsapi_pitcher_props_<D>.json             (same date, unfrozen)

count = pitchers carrying an `outs` line, in each.

**PASS:** `count(frozen) >= 8` **AND** `count(frozen) > count(live)`.

The second clause is the seal-specific half and the one that matters. By the
next morning the live doc has collapsed post-slate (books pull player props when
games end — measured: 12 of 29 dates archive ZERO pitchers). The seal must NOT
have followed it down. Under the old code it could, or it could be stuck thin
from the first pass.

Baseline to beat: **only 5 of 29 historical dates carried >=8 pitchers with an
outs line.**

`py -3 scripts/grade_production_outs_betting.py` reads both. Path quirk it
already documents — the two families sit under DIFFERENT stream roots:
odds `mlb_source/data/daily/snapshots/<D>/...`,
rosters `mlb_source/source_artifacts/data/daily/snapshots/<D>/...`.

## Dependency, stated so a VOID is not read as a FAIL

**The seal can only be observed if a PREGAME capture happened at all.** That is
the other half, already live: `SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE=true` on
**live-odds-worker** since 2026-08-17 ~18:3xZ (gate verified running; effect
measured by scheduled task `outs-props-coverage-check`, fires 2026-08-19 07:00
CT for date 08-18).

- Cadence FAILs → there is no pregame capture to seal → this reading is **VOID,
  not FAIL**.
- Cadence PASSes → this reading is meaningful.

**Ideally deploy AFTER 2026-08-19's cadence result is in.** Nothing breaks if it
ships sooner; the reading is just uninterpretable until cadence is known good.

## Risk

- **Code-only.** No env var, no `render.yaml`, so no `blueprint_sync`.
- Touches one function on a path that runs inside the odds refresh. It cannot
  make the seal worse than today in either direction — every branch either
  keeps the current behaviour or strictly improves the sealed content.
- 33 tests pass, including the other lane's existing suites
  (`test_oddsapi_pregame_freeze`, `test_season_betting_cards_odds_paths`) so the
  2026-08-08 freeze repair is intact. Two tests drive the real freeze over a
  temp tree rather than re-stating its rule.
- **refresh-worker is the OOM-sensitive service.** This adds one small JSON read
  per props file per freeze pass — bounded, but that service is the one under
  `#449`, so pick the window accordingly. Deploys also kill in-flight sims;
  refresh-worker owns the MLB daily sim, so check for one before firing.

## Claim note

`scripts/refresh_mlb_oddsapi.py` was claimed read-only by OPEN lane
`grading-blocker-settled-zero`, whose own header marks it **ORPHANED, no live
owner**. One function taken, props branch only, nothing on the
grading/settlement path it cares about. Reassignment logged in `lanes.md` with a
revert instruction; notice relayed to the coordinator session.

Requested by lane `convergence-phase7-crps` (`#440` Phase 7).
Evidence: `.syndicate/deploys.md`, "2026-08-17 — ARCHIVED LINE COVERAGE
DIAGNOSED" and the commit message for `bafb4fb2`.


---

## EXECUTED by the coordinator 2026-08-17 20:29-20:37Z

Deployed. refresh-worker `69607619` (live 20:35:44Z), live-odds-worker `9773713f` (live 20:36:50Z), each cut on that service's OWN live SHA. **MEASUREMENT PENDING the next sweep cycle** - see `deploys.md` under this date. Do not read this as verified.
