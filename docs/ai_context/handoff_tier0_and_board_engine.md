# Handoff — Tier 0 shipping + the board-engine program

Written 2026-08-14 ~21:30Z by session `layer2-freshness` at close.
**Self-contained: assume zero context.** Read this, then
`.syndicate/plan_2026-08-14_program.md`, then start.

---

## THE ONE THING TO DO FIRST

**Ship `086702ae` (branch `memory/overview-sum-to-max`) to refresh-worker.**

refresh-worker OOM-killed at **2026-08-14 20:03:11Z** and **nothing is deployed
to prevent the next one.** The kill is fully diagnosed:

    20:02:26  OVERVIEW_SPORT_BEGIN mlb force_refresh=True skip_game_hydration=False
    20:02:26  anon 343MB      <- worker had been up 13 minutes
    20:02:46  anon 522MB
    20:02:48-57  nba, wnba, nfl, ncaaf, ncaab, nhl, soccer   <- all eight held at once
    20:03:11  oomKilled memoryLimit 4Gi

**A 522MB worker died in 25 seconds inside one hydrated overview pass.** The
floor plays no part — there was no time to accumulate one. Peak = SUM across
eight sports is sufficient on its own to cross 4GiB, and `086702ae` turns that
into MAX-of-one-sport.

Gate: `tests/test_intelligence_state.py` **223 passed / 10 subtests**. The one
failure is PRE-EXISTING (proven by stashing the diff and re-running) — it asserts
`force_refresh=True` on a call site `#387` removed earlier that day.

**Measurement that makes it official** — a baseline now exists because of the
kill: one hydrated pass, `OVERVIEW_SPORT_BEGIN mlb` -> peak. Before: 522MB ->
dead in 25s. After: should track one sport and never approach 4GiB.

---

## WHAT IS DEPLOYED VS NOT

| commit | where | state |
|---|---|---|
| `530fc5d8` | in the live refresh-worker commit | **DEPLOYED + VERIFIED.** Layer 2 fast path. 3h clean window: 37 refreshes = 11.9/hr vs 1.7 baseline, longest gap 11.8 min vs 104.7, 96 guard refusals, `LAYER2_GUARD_SKIP` 0, no OOM. |
| `086702ae` | branch `memory/overview-sum-to-max` | written, tested, **NOT on main, NOT deployed** |
| `9ec20a06` | branch `odds/pregame-cooldown-per-sport` | written, tested, **held deliberately** |
| `0ddecded` | local only | `#427` build-time estimator; operator script, no deploy needed |

**`9ec20a06` is held on purpose**: it changes odds cadence and would confound
`soccer-odds-coverage`'s per-league measurement. It needs that lane's sign-off
and a call on OddsAPI spend against the 5M cap. It is the direct fix for
"candidates that are no longer bettable" — MLB prices go from <=2h stale to
<=30 min.

---

## DEPLOY COORDINATION — a train was proposed and never answered

A freeze notice is at the top of `.syndicate/state.md`. Two model-audit sessions
were messaged with a train proposal; **neither replied**, and refresh-worker took
another deploy at 20:54 anyway.

The train's justification, if you want to reuse it: `learnings.md` says one
substantive change per deploy *while diagnosing*, and that rule is about changes
contending for the SAME metric. Model-audit's metric is shortlist composition;
the memory metric is peak MB. Disjoint. A train with named metric ownership
preserves attribution and beats four deploys in four hours.

**If nobody answers, ship `086702ae` alone.** Another kill costs more than the
attribution ambiguity.

**HOW TO DEPLOY — there is no idle window.** MLB sims run near-continuously with
60-90s lulls. `deploy_preflight.py --service refresh-worker` returns HOLD on
almost every read. The method that worked (zero jobs killed): poll the gate every
10s and fire the POST **in the same step** as the CLEAR. And a first CLEAR is
often just a lull between sims — confirm with spaced samples before trusting it.

---

## TRAPS THAT COST THIS SESSION REAL TIME

1. **Compare deploy IDENTITY (SHA), not timestamps.** A watcher declared "A
   DEPLOY INTERVENED" on a 66ms difference — the same deploy, my constant just
   lacked fractional seconds. It nearly threw away a clean 3h window.
2. **`git commit -- <paths>`, always.** 8+ files are staged by another session in
   the shared index. `git add` + `&&` + `commit` swept 32 of their files into my
   commit; the inspection step was in the same chain so it printed and was
   immediately obsoleted. Recovered with `git reset --soft HEAD~1`.
3. **Never derive a lane's claims from a regex over `lanes.md`.** The negations
   (`NOT claimed, deliberately`, `Collision check ... claimed elsewhere`) read as
   claims and nearly produced a false accusation against a disciplined lane.
4. **`.claude/worktrees/` holds FULL REPO COPIES.** Any unscoped `find`/`rglob`
   triple-counts and times out.
5. **Re-verify an audit's "known already" inputs.** Three of four did not survive
   checking. `static/mlb/board.js` was cited twice as confirmed — it does not
   exist. Two citations of one stale fact read as corroboration.
6. **A single sample of a bursty quantity is not a measurement.** Three wrong
   root causes in one evening, all this shape. The fix was to stop reading logs
   and read the artifact's full distribution.

---

## STATE OF THE PROGRAM

`.syndicate/plan_2026-08-14_program.md` is the sequencing document — Tier 0
through Tier 6. It is current and good. Two notes:

- **Tier 0's "board-engine brief: three edits owed" is DONE.**
  `.claude/commands/board-engine-audit.md` (269 -> 337 lines) now carries the
  layer hierarchy, the three-pipeline topology, and the stale items struck in
  place. One less thing in Tier 0.
- **Tier 0's shadow-ledger line is the cheapest item in the program** and gates
  the audit's §9. It needs no coordination. Turn it on.

### The layer hierarchy — do not re-derive this wrong

    shared ingestion: odds capture -> book_quotes -> book_grid -> enrichment
      |-- Layer 1 board   the KNOWN UNIVERSE + the owner's research surface
      `-- Layer 2         Syndicate's CURATION. THE PRODUCT CORE.

    separately: build_intelligence_overview (8 sports, HYDRATED)
                -> collect_candidates -> candidate_pool -> global_pool
                -> top_opportunities / by_sport / board_contract  (chat, portfolio)

**Layer 1 is not a deletion candidate.** There is no Layer 2 without it. This
session got that wrong once — it measured that Layer 2 does not consume Layer 1's
*candidate-pool object* and inflated it into "does Layer 1 earn its cost".

**The correct reading of that same measurement:** L1 `count=0` on 3 of 5 builds
means **the research surface is dark ~60% of the time** — an outage, hidden
because the curated product kept working off the shared grid. That is Tier 4.

**The third pipeline is the deletion candidate**, not Layer 1.

---

## AUDIT STATE

`.syndicate/audit_2026-08-14_board_engine_SYNTHESIS.md` — **read this one**, it
carries the five deliverables. Passes 1-3 are the working.

§1, §2, §3 complete. §5 has the distinctive terms only. §9 and §10 blocked on
**inputs, not effort**: shadow ledger ON, and the glossary built by READING (two
mechanical attempts failed and are recorded — do not try a third).

Sharpest finding: **42 sites define or convert a probability.** The
`edge`/`EV`/`confidence` collisions are probably one substrate problem, not three
bugs. Tier 3a's differential test over one price grid turns that cleanup into a
bug hunt and establishes an owner by evidence.

---

## LANE HYGIENE — needs an owner decision

- **Two live sessions share one lane slug** (`recommendation-lane-correctness`).
  `lane-guard` matches on slug, so neither is protected from the other.
- **~6 OPEN lanes are orphaned** — owner session gone, file claims still held.
  This is why `.current-lane` thrashed all evening and why a cross-lane override
  was needed for `live_refresh_loop.py`.

Not swept, deliberately: closing other lanes' work is the owner's call, and two
carry unfinished measurement obligations.
