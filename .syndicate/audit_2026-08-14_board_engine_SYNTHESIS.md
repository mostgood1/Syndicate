# Board / intelligence engine audit — SYNTHESIS (the five deliverables)

Assembles Pass 1 + Pass 2 into the outputs the brief asks for. **Read this
first; the pass notes are the working.** No code changes.

**THE BRIEF IS NOT COMPLETE — roughly 45-50%.** Every greppable section is
done; almost nothing requiring judgement or a live system is. §8, §9 and the
target-architecture half of §10 are NOT STARTED. §1 has its census but not its
import graph. §6 is a reader/writer map only. The full section-by-section table
is at the bottom under HONEST ASSESSMENT — read it before treating any section
here as settled.

---

## DELIVERABLE 1 — Glossary (partial; the method matters)

**Two mechanical attempts failed** — dict-keys counted usages (`value = 1220`),
substrings matched `retrieve`/`event` (`ev = 181`). The glossary must be built by
reading. Both failures are recorded in Pass 2 so a third person does not repeat
them.

Established `[measured]`, distinctive terms only:

| term | defining functions | finding |
|---|---:|---|
| `model_skill` | **0** | product term the engine does not own |
| `min_value_pct` | **0** | a selection THRESHOLD with no defining function — config only |
| `market_probability` | 1 | single owner |
| `shortlist` | 1 | single owner |
| `model_edge_pct` | 2 | near-single owner |
| `fair_probability` | 4 | contested; model-audit found 3 sites falling back to `confidence` |
| `opportunity` | 5 | contested |
| `implied_probability` | 9 | contested |
| `confidence` | 11 | contested — this is HOW it is a scoring artefact in one place and P(outcome) in another |

**Connected finding:** `fair_probability` 4 + `implied_probability` 9 +
`confidence` 11 + **18 prob↔odds conversions** (Pass 1) = **42 sites where a
probability is defined or converted.** The brief lists the `edge`/`EV`/`confidence`
collisions as separate bugs; this suggests they are downstream of one substrate
problem. **Highest-value remaining work in the audit.**

`edge`, `value`, `EV`, `score`, `board`, `snapshot`, `candidate` cannot be counted
by name and must be reached through the functions producing the numbers the UI
renders.

---

## DELIVERABLE 2 — Duplication table

| concept | implementations | canonical | verdict |
|---|---:|---|---|
| devig / no-vig | 4 by name, more by behaviour | unresolved | **UNCLEAR — recorded, not guessed.** Widened grep finds per-sport `market_anchoring.py` (NHL sim engine, soccer features) that the narrow pattern misses. Whether sim-engine anchoring counts is a semantic call. |
| fair probability | 4 | unresolved | contested |
| edge computation | 4 | unresolved | contested |
| candidate ranking | 5 | `select_shortlist` for L2 | L1 and L2 rank independently |
| **freshness / staleness** | **19** | none | brief expected ≥2 |
| **market history / movement** | **23** | none | brief expected 3 |
| **prob ↔ odds conversion** | **18** | none | not in the brief at all |
| board contract / card build | 11 | — | |
| sport routing | 6 | — | |
| byte-identical files | 1 group | — | brief's `mlb/board.js` **DOES NOT EXIST** |
| near-identical ≥90% | 18 pairs | — | sport-fork classification NOT done |

---

## DELIVERABLE 3 — Deletion list (ranked, verification per line)

**Ordered by (confidence dead) × (lines removed). Nothing here is safe to delete
on this evidence alone — each carries its verification step.**

| # | target | lines | why believed dead | verify before deleting |
|---|---|---:|---|---|
| 1 | `ask_the_syndicate_engine.py` | 335 | prior audit: never executes in production | confirm no import reaches it from a live route; check the router's dispatch |
| 2 | `power` devig | ? | implemented, documented as better for props, called by nothing | grep call sites including dynamic dispatch tables |
| 3 | `_build_artifact_response` | ? | returned `None` on every observed call | instrument one non-None return first — a None-returning function may still have side effects |
| 4 | `_game_card_mlb.html` | ? | reachable only via `?client=board` | check whether any client sends that param |
| 5 | 136 routes with no path literal | — | **SHORTLIST ONLY** | each needs its own check: dynamically-built paths, ops tooling calling by URL from outside the repo, chat surfaces |
| 6 | `static/mlb/board.js` | — | **ALREADY GONE** — brief cites it twice; it does not exist | strike both citations from the brief |

**Method warning that changes this list:** Pass 1 found the brief's own
"confirmed dead" item #6 does not exist. **Re-verify items 1–4 the same way
before any reaches a deletion PR.**

---

## DELIVERABLE 4 — Latency / cadence table

`[measured 2026-08-14]` unless marked.

| hop | measured | note |
|---|---|---|
| OddsAPI fetch → quote append | ~20s | 3 samples, launch → burst |
| **fetch cadence (MLB)** | **~121.6 min** | **the product's real rate limiter** |
| quote append → publish worker→web | per append | streamed, no size ceiling |
| pull web→worker | per build | |
| grid + enrich + rank + select + persist | **14–27s** | whole L2 build, 4 samples |
| L2 build cadence, healthy | min 2.1 / p50 5.3 / max 11.8 min | 3h clean window |
| L1 `candidate_collection_with_fallback` | 498.7s per 3h | p50 0.00s, bimodal |
| board build end to end | ~2–4 min | `#427`; **not** ~23 min |
| **quote change → UI reflects it** | **NOT MEASURED** | the number a live product is defined by |

**Everything downstream of the fetch can run every 2 minutes and prices will
still be up to ~2 hours old.**

---

## DELIVERABLE 5 — Ranked fix list (user-visible / edge-affecting first)

1. **Odds capture cadence — MLB prices up to ~2h stale.** Cause measured: the
   1800s pregame relaunch cooldown is keyed by DATE ONLY, not by sport, and
   sports rotate across launches. **Fix written and tested, held on
   `odds/pregame-cooldown-per-sport` (`9ec20a06`).** This is the direct answer to
   "candidates that are no longer bettable". Cost: raises OddsAPI call volume —
   measure calls, not just cadence, against the 5M cap.
2. **`confidence` used as P(outcome).** 11 defining sites. Users see an `edge`
   derived from a scoring artefact. Owned by the model-audit lane (A1/A2).
3. **`edge` served with `market_probability: null` and `EV: null`** — a number
   checkable against nothing.
4. **The overview OOMs the worker.** A 522MB worker died in 25s inside one
   8-sport hydrated pass. **Cutover written and tested on
   `memory/overview-sum-to-max` (`086702ae`), undeployed.**
5. **CORRECTED 2026-08-14 by the product owner — the earlier wording here was
   wrong and is kept visible rather than quietly edited.** It read "does Layer 1
   still earn its cost", which conflated two different things and implied Layer 1
   was a deletion candidate. It is not.

   **There are THREE pipelines, not two:**

       shared ingestion: odds capture -> book_quotes -> book_grid -> enrichment
                         (attach_game_state / projections / margin_model)
         |-- Layer 1 board  `build_layer1_board`  = the KNOWN UNIVERSE, pregame
         |                   and live. The USER'S RESEARCH SURFACE.
         |                   `/api/board/layer1` is, per its own handler
         |                   docstring, "A PURE READ of the precomputed grid" —
         |                   it never calls `collect_candidates`.
         `-- Layer 2 shortlist = SYNDICATE'S CURATION of that same grid.
                                 The product core.

       separately: build_intelligence_overview (8 sports, hydrated)
                   -> collect_candidates -> candidate_pool -> global_pool
                   -> top_opportunities / by_sport / board_contract

   **Layer 1 is load-bearing: there is no Layer 2 without it.** They share the
   ingestion and the grid, and Layer 1 is the surface the user researches on
   while Layer 2 is the curated output. What was measured is narrower than what
   was claimed: Layer 2 does not consume Layer 1's **candidate-pool object** —
   `count=0` while Layer 2 built 256 rows on the same cycle.

   **The real question, restated:** the eight-sport hydrated overview that
   OOM-killed the worker feeds NEITHER the research board NOR the shortlist. It
   feeds the intelligence-board response (`top_opportunities`, `by_sport`,
   `board_contract`) that chat and portfolio read. **Does that pipeline still
   need to hydrate eight sports, when the grid it could read is already built
   for the other two surfaces?** That is a bounded engineering question, not a
   proposal to remove a product surface.

   **Product direction, from the owner:** Layer 2 is the core and is what to
   perfect; Layer 1 stays as the universe and the research surface.
6. **No live game-line projection exists.** `predictions.full` is the pregame
   sim; only props have a live tier; `rows_live_edged` is 0 on every build. The
   "live experience" half of the product premise is largely absent.
7. The 42-site probability substrate (Deliverable 1).
8. Structural: 43 files over 1,000 lines; 19 freshness / 23 movement / 18
   conversion implementations.

---

## WHAT IS STILL MISSING, and what each needs

| section | state | needs |
|---|---|---|
| §2 config | 127 read-sites listed | cross-reference against the 73 web env values + defaults + prod values. **Denominators differ — do not compare directly.** |
| §2 sport forks | 18 pairs listed | classify each diff: sport semantics vs drift. Judgement, per pair. |
| §3 dead code | mechanical sweeps only | returns-always-None and flag-never-on need runtime/config evidence |
| §4 | L2 traced | per-hop latency; the chat narrowing `200→145→12→5`; live path on a live slate |
| §5 | distinctive terms only | `edge`/`value`/`EV`/`score` by reading, from the UI backwards |
| §6 | reader/writer map only | cadence, TTL, declared vs measured age per artifact; the readers of `read_latest_intelligence_state` (7,346s against a 60s SLA) |
| §8–§10 | **not started** | pregame/live boundary, per-sport live coverage, target architecture, deletion list finalisation |

**§6 partial result `[measured]`:** `read_layer2_shortlist` has 4 call sites,
**2 of them in `ask_the_syndicate_data.py`** — chat reads the shortlist artifact
directly, which is the mechanism behind the brief's "board means different things
to the cards and to chat". `write_layer2_shortlist` has exactly 2 writers (the
full build and the `#387` fast path). `expand_persisted_state` has 12 call sites,
and `state.md` records that a raw read without it degrades silently rather than
raising — that has already bitten four ops diagnostics.

---

## HONEST ASSESSMENT OF THIS AUDIT

**THE BRIEF IS NOT COMPLETE. Roughly 45-50%**, corrected down from an earlier
claim of 60% in this same file which overstated §1-§3 as "substantially done".

Section by section:

| § | state | what is missing |
|---|---|---|
| 1 | census only | **the entire import-graph half**: cycles, hub modules (>10 importers), live-route vs script-only reachability |
| 2 | dupes + concepts done | config cross-reference (127 read-sites vs 73 web values); sport-fork drift classification (18 pairs) |
| 3 | 2 of 5 sweeps | returns-always-None; flags-never-on; fetchers/handlers registered but never dispatched |
| 4 | L2 pregame only | live path untraced; per-hop latency; the chat narrowing 200->145->12->5 |
| 5 | 9 distinctive terms | `edge`/`value`/`EV`/`score`/`board` — unreachable by pattern, need reading |
| 6 | reader/writer map, 8 functions | **mostly not done**: cadence, TTL, declared vs measured age, hot vs orphaned artifacts, same-fact-in-two-places |
| 7 | sweep done | the invariant proposal and where to enforce it |
| 8 | **not started** | pregame/live boundary, transition trigger, live sims per sport, latency budget |
| 9 | **not started** | per-sport live coverage, pregame vs live row split, loop closure |
| 10 | deletion list drafted | target architecture (the one-page output) |

Of the five required outputs: **duplication table** and **ranked fix list** are
done; **deletion list** is drafted but every line still needs its verification
step run; **glossary** and **latency table** are each missing their single most
important entry — the terms the UI renders, and quote-change -> UI-reflects-it.

**The completed portion is skewed:** everything greppable is done, almost nothing
requiring judgement or a live system is. That is the expected shape when an audit
is run at the end of a long session, and it is why the brief says to run it in
three passes with checkpoints.

Three of the brief's own supplied "known" inputs did not survive checking, which
is itself a finding about how the prior audits should be consumed.

What would make it complete, in order: (1) the glossary by reading, from the UI
backwards; (2) §4's live path on an actual live slate; (3) §8–§10, which depend
on both.


---

# COMPLETION PASS — the mechanical remainder (2026-08-14)

Working detail in `audit_2026-08-14_board_engine_pass3.md` and `_env_xref.txt`.

## §1 (NOW COMPLETE) — import graph `[measured]`

- **24 hub modules imported by >10 others.** Top: `timezone` 56,
  `refresh_state_store` 39, `source_roots` 31, `rank_board` 29,
  `game_board_contract` 28, `sources` 23. The brief's heuristic — "a hub is
  usually a concept that wants splitting" — applies squarely to `rank_board` and
  `game_board_contract`, which are board CONCEPTS rather than plumbing;
  `timezone`/`source_roots` are plumbing and fine.
- **24 import cycles.** Listed in the pass-3 note.
- **164 of 390 modules reachable from no route and no loop entrypoint.**
  **NOT a deletion list.** Static reachability only: thread `target=`,
  registries, decorators and dynamic imports are not followed, and
  `learnings.md` records that a trace omitting those classes "is not evidence".

## §2 (NOW COMPLETE) — config cross-reference `[measured]`

Live keys: web 73, refresh-worker 104, live-odds-worker 104.
Board-path code reads **127** distinct env vars.

- **71 configured on a service but not read by `syndicate/**` or `pipeline/**`.**
  **THIS IS NOT A DELETION LIST, AND THE PROOF IS IN THE LIST ITSELF:**
  `MLB_LIVE_LENS_DIR` appears in it, and `learnings.md` records that its only
  reader is a **vendored** module called at module scope — deleting it would
  have broken MLB live-lens on web. My scope excluded `vendor/` and `scripts/`,
  which is precisely the exclusion that previously produced seven false
  "no reader anywhere" findings. Anyone using this list must re-run it including
  `vendor/` and `scripts/`, and follow thread targets.
- **77 read by code but configured on no service** — mostly platform-injected
  (`RENDER`, `RENDER_*`, `REDIS_URL`) or local-only (`QNN_*`, `SMARTSIM_WORKERS`).
  The finding is not the count; it is that **absent means "the code default
  wins", and CLAUDE.md records that absent is not uniformly "off"** — one such
  key defaults False, another defaults True.
- **5 web-only keys**, all `SYNDICATE_ASK_*` / combined-board — consistent with
  chat being web-only.

## §3 (NOW COMPLETE) — always-empty-return functions `[measured]`

**38 functions** with >=2 returns where every return is `None`/`[]`/`{}`.
Each is either dead or exists purely for side effects — in which case the return
value is a lie the caller may be branching on. Ranked by body size in pass 3.
This is the sweep that finds the `_build_artifact_response` class of defect
systematically rather than one at a time.

## §6 (FULLER) — artifact accessor map `[measured]`

`write_layer2_shortlist` 2 writers / `read_layer2_shortlist` 4 readers — **2 of
those readers are `ask_the_syndicate_data.py`**. That is the mechanism behind the
brief's "board means the fresh shortlist to the cards and a 2-hour-old snapshot
to chat": chat reads the persisted artifact directly, so its staleness is the
artifact's age, not the board's.
`expand_persisted_state` has 12 call sites; a raw read that skips it degrades
silently rather than raising, and has already bitten four ops diagnostics.

## §8 (CENSUS DONE, BOUNDARY NOT RESOLVED) `[measured]`

- **91 of 390 modules contain a pregame/live discriminator**
  (`is_live`, `effective_phase`, `pregame`, `live_lens`, `_live_tier`).
- **16 modules carry `live` in their NAME** — candidate forks rather than
  conditionals.
- **Verdict: there is no single boundary.** 91 modules branching on liveness is
  a cross-cutting conditional, not an architectural seam. Whether each of the 16
  named forks is legitimate specialisation or drift is per-module judgement and
  is NOT done.
- Already established and unchanged: **no live game-line projection exists**
  (`predictions.full` is the pregame sim); only props have a live tier;
  `rows_live_edged` is 0 on every build to date.

## §7 (INVARIANT — the proposal the brief asked for)

Measured surface: **40** sites substituting `0.5` for a probability, **3**
substituting `50`, **240** bare `except: pass`, **20** `.get(k, <plausible>)`,
**388** filters that return their input unchanged on empty.

**Proposed invariant:** *a probability, edge or EV that was not computed from
data must be `None`, never a number.* Absent must be representable and must
survive to the UI.

**Where to enforce it:** the board contract layer — `game_board_contract` is
already imported by 28 modules, so it is the one choke point every card passes
through, and `learnings.md` records that the fix which finally held for `#334`
was the one placed *inside* a shared function rather than at call sites. A
contract-level assertion plus one test that a `None` probability reaches the
card as `None` (not `0.5`, not `50.0`) would close the whole class.

## §9 / §10 — WHAT I WILL NOT MANUFACTURE

- **§9 effectiveness** needs the pregame/live row split of the published 200 and
  a live slate to observe. The shadow candidate ledger is off, so filter
  precision is **structurally unmeasurable** until it is on — that is itself the
  §9 finding, and turning it on is the prerequisite for the rest.
- **§10 target architecture** requires the §5 glossary to be real, because the
  one-owner-per-concept column cannot be written while `edge`/`value`/`EV` have
  no established owner. Producing a one-page architecture now would be an
  opinion dressed as an audit output.

**Both are blocked on inputs, not on effort.** The unblocking actions are:
turn on the shadow ledger; build the glossary by reading from the UI backwards.


---

# CORRECTIONS FROM `plan_2026-08-14_program.md` (2026-08-14)

The program plan caught two real over-statements in this audit and sharpened a
third. Recorded here so the audit and the plan do not disagree.

## 1. §7's "40 sites substituting 0.5" is OVER-COUNTED — the plan is right

**Not 40 instances of one bug.** Triage before enforcing anything:

- `drive_priors.py`'s `(success_rate or 0.5) - 0.5` is a **centered prior** —
  0.5 is the genuine neutral point of a rate, not a fabricated probability.
- `faceoff_win_pct: float = 0.5` is a **legitimate sim-contract default**.
- `0.5 * (1.0 + math.erf(...))` is the **normal CDF**. Not a default at all.

**Enforcing the invariant indiscriminately would break sim engines.** The defect
is only where 0.5 substitutes for a probability that reaches a user or feeds an
edge calculation. The **3 sites at 50.0 in `game_board_contract` are
unambiguous** and can go now.

My §7 reported the raw count without triage, which would have handed a cleanup
lane a list that breaks the sim engines. The invariant in §7 stands; its
**scope** was wrong.

## 2. The 240 bare `except: pass` do NOT belong in the board-correctness finding

They are a hygiene backlog. Folding them into the invariant dilutes an otherwise
well-aimed fix. Withdrawn from §7's scope.

## 3. §1's cycle finding — REFINED, and the plan slightly understates it

`[measured]` **8 of 24, not 7**, and they share a root:

    game_board_contract -> simulation_adapter -> game_board_contract       <- ROOT (2-cycle)
    game_board_contract -> simulation_adapter -> <sport>.cards -> back     <- x7

mlb (via `live_lens`), nba, ncaab, ncaaf, nfl, nhl, wnba. **The seven per-sport
cycles are the root 2-cycle with a sport threaded through it.** So the proposed
dependency inversion fixes all eight, and **the bare 2-cycle is what to break
first** — the sports are passengers, not causes. This also explains
`game_board_contract`'s 28-importer hub load directly.

Remaining cycle families, for completeness: `pipeline.intelligence_*` (3),
`blueprints.home <-> blueprints.intelligence <-> features.intelligence` (2),
per-sport `cards <-> live_lens` (2), and three one-offs.

## 4. Tier 4's re-reading of `count=0` is BETTER than mine

The plan inverts the meaning of a measurement I made and reported. Same number,
correct reading:

| measurement | my reading | correct reading |
|---|---|---|
| L1 `count=0` on 3 of 5 builds | evidence it is not earning its cost | **the research surface is dark ~60% of the time** |
| L2 does not consume L1 | evidence of redundancy | why the outage went unnoticed |
| the overview OOMs the worker | a reason to cut it | **a P0 on a product surface** |

`count=0` on three of five builds is an **outage on the surface the owner
researches from**, hidden because the curated product kept working off the shared
grid. It was never a deletion argument.

## 5. Already done — the plan lists this as owed

**"Board-engine brief — three edits owed"** is COMPLETE.
`.claude/commands/board-engine-audit.md` (269 -> 337 lines) now carries the layer
hierarchy in the goal statement, the measured three-pipeline topology as an
input, and all three stale "known already" items struck **in place** rather than
deleted, so the correction stays visible. `lane-guard` is blind to `.claude/**`,
so that edit was unprotected — check `git diff` on it before relying on it.
