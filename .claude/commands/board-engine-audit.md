# Board / intelligence engine audit brief

Run in Claude Code. Read-only; findings to `.syndicate/`, fixes as separate
lanes. This is larger than the three audits of 2026-08-14 and **should not be
attempted in one pass** — see "Staging" below.

**Inputs — RE-VERIFY THESE FIRST, they are claims and not axioms.**
`audit_2026-08-14_models.md`, `audit_2026-08-14_ui.md`,
`audit_2026-08-14_ask_the_syndicate.md`. Each already found duplication from its
own angle; this audit's job is the engine underneath them and the pattern across
them.

**Spend the first ten minutes re-checking every "known already" item below.**
The 2026-08-14 run of this brief found **three of them did not hold**, and an
input marked "known" is precisely the one nobody checks. Corrections already
applied in place, with the originals struck rather than deleted:

- ~~`static/mlb/board.js` is byte-identical to the first 52 lines of
  `shared/game_board.js`~~ — **THAT FILE DOES NOT EXIST.** It was cited twice in
  this brief (as a duplicate and as dead code), which read as corroboration and
  was one stale fact counted twice.
- ~~devigging: 5 implementations~~ — **not reproducible.** A name-shaped pattern
  finds 4; a widened grep finds per-sport `market_anchoring.py` (NHL sim engine,
  soccer features) that the narrow one misses entirely. Whether sim-engine
  anchoring counts as a devig implementation is a semantic call, not a count.
- **HAZARD: `.claude/worktrees/` holds FULL REPO COPIES.** Any census, hash or
  grep that does not exclude `.claude/`, `vendor/`, `__pycache__` will
  triple-count and manufacture duplication findings. An unscoped `find` over
  `.claude/` also times out.

**Goal statement to test against.** The board is meant to deliver a **pregame**
and a **live** experience that surfaces betting edges from pregame sims and from
live sim/projection/model updates. Every finding below should end by answering:
does this help or hinder that?

**PRODUCT HIERARCHY — stated by the owner 2026-08-14. Read this before §9 or
§10; neither can be answered without it.**

- **Layer 1 is the KNOWN UNIVERSE**, pregame and live, and it is the **user's
  research surface** — the owner browses it directly. `/api/board/layer1` is,
  per its own handler docstring, "A PURE READ of the precomputed grid".
- **Layer 2 is Syndicate's CURATION of that same grid, and is the product core.**
  It is the thing to perfect.
- **There is no Layer 2 without Layer 1.** They share the ingestion and the grid.
  **Layer 1 is not a duplication finding and is not a deletion candidate.**

The 2026-08-14 run got this wrong: it measured that Layer 2 does not consume
Layer 1's *candidate-pool object* (`count=0` while Layer 2 built 256 rows on the
same cycle) and inflated that into "does Layer 1 earn its cost". Do not repeat
it. The measured topology is **three pipelines, not two**:

```
shared ingestion: odds capture -> book_quotes -> book_grid -> enrichment
                  (attach_game_state / attach_projections / attach_margin_model)
  |-- Layer 1 board   build_layer1_board       the universe + research surface
  `-- Layer 2         build_layer2_shortlist   the curated product core

separately: build_intelligence_overview (8 sports, HYDRATED)
            -> collect_candidates -> candidate_pool -> global_pool
            -> top_opportunities / by_sport / board_contract   (chat, portfolio)
```

The third path is the expensive one — it carries the 8-sport hydrated overview
that OOM-killed refresh-worker on 2026-08-14 — and it feeds **neither** board.
The live question is whether it still needs to hydrate eight sports when the
grid is already built for the other two surfaces. That is a bounded engineering
question, not a proposal to remove a product surface.

**Scoping rule.** Weeks of deliberate work are in here. Duplication is not
automatically waste — sports genuinely differ, and a fork made on purpose to
serve a real difference is a design choice. The audit's job is to **separate
intentional specialisation from drift**, not to flag every near-match. Where the
answer is unclear, record it as unclear rather than guessing.

---

## Staging — run as three passes, checkpoint between

Context runs out before this brief does. Each pass writes its own dated note and
the next pass reads it.

- **Pass 1 — Inventory.** Mechanical, greppable, no judgement. §1–§3.
- **Pass 2 — Semantics.** What the code *means*: concept ownership, pipeline
  topology, dead paths. §4–§7.
- **Pass 3 — Product.** Pregame vs live effectiveness, and the target shape.
  §8–§10.

Do not start a pass before the previous note is written.

**A 2026-08-14 run reached ~70% of this brief and its output is on disk.** Read
`.syndicate/audit_2026-08-14_board_engine_SYNTHESIS.md` FIRST — it carries the
five deliverables, and passes 1-3 are the working. §1, §2, §3 are complete
(import graph, config cross-reference, always-empty-return sweep). **What
remains: §5's main terms (`edge`/`value`/`EV`/`score` — two mechanical attempts
failed and are recorded, it must be done by READING from the UI backwards), §9,
and §10's target architecture.**

**§9 and §10 are BLOCKED ON INPUTS, not effort.** §9 needs the shadow candidate
ledger turned ON — while it is off, filter precision is structurally
unmeasurable, and that is itself the §9 finding. §10's target architecture needs
the §5 glossary, because "one owner per concept" cannot be written while `edge`
and `EV` have no established owner.

---

# PASS 1 — INVENTORY

## 1. Module census

- Every module in the board/intelligence path with line count, sorted
  descending. Flag anything over 1,000 lines. Known already:
  `mlb/cards_source.js` at 3,880, `ask_the_syndicate_data.py` past 3,200.
- Import graph for the board path. Cycles, and any module imported by more than
  ~10 others (a hub is usually a concept that wants splitting).
- Which modules are reachable from a live route, and which are reachable only
  from scripts or tests.

## 2. Duplication census

The explicit ask. Be systematic rather than impressionistic.

**Byte-level and near-identical files.** Hash every file in the board path;
report exact duplicates. Then near-duplicates above ~90% similarity. Known
already: ~~`static/mlb/board.js` is byte-identical to the first 52 lines of
`shared/game_board.js`~~ (**STRUCK — that file does not exist, see Inputs**);
`wnba/cards-parity.css` and `nba/cards_source.css` are
97.4% identical.

**Parallel implementations of one concept.** For each of these, list every
implementation, its call sites, and which one is canonical:

| concept | known count |
|---|---|
| devigging / no-vig fair value | ~~**5**~~ **DISPUTED — 4 by name; widened grep finds per-sport `market_anchoring.py` the pattern misses. Resolve the definition before the count.** |
| fair probability derivation | ≥2 (`_fair_probability`, projection paths) |
| edge / value computation | unknown — expect several |
| candidate ranking | unknown |
| freshness / staleness | ≥2 (`freshness_sla_seconds`, `is_fresh`, ad-hoc age checks) |
| market history / movement | `build_market_history_view`, `movement_velocity`, steam detector |
| card rendering | **5** |
| sport routing / inference | ≥2 (`_SPORT_HINTS`, `_fetchers_for_sport`) |

Extend the table with what you find. For each row, the deliverable is: canonical
implementation, call sites of the others, and whether the differences are
semantic or accidental.

**Copy-forked sport modules.** For each sport, which modules are shared and
which are sport-local. For each sport-local one, diff against its nearest
sibling and classify every difference as *legitimate sport semantics* or *drift*.

**Config duplication.** The web service carries 73 environment variables. For
each: read by what, default, current production value, and whether anything
still reads it. Same for hardcoded thresholds and magic numbers in the selection
path.

## 3. Dead code inventory

Five confirmed instances across the three prior audits, which suggests a
systematic problem rather than isolated neglect:

- `ask_the_syndicate_engine.py` — 335 lines, never executes in production
- `_build_artifact_response` — returned `None` on every observed call
- `power` devig — implemented, documented as better for props, called by nothing
- `_game_card_mlb.html` — reachable only via `?client=board`
- ~~`static/mlb/board.js` — byte-identical duplicate~~ **STRUCK 2026-08-14: THE FILE DOES NOT EXIST.** This was the second of two citations of one stale fact. **Re-verify the other four items in this list the same way before any reaches a deletion PR** — the 2026-08-14 run did, and found this one hollow.

Sweep for the pattern deliberately:

- Functions whose every observed return is `None` / `[]` / `{}`
- Branches gated on env vars that are absent in production
- Feature flags that are off and have been off since introduction
- Routes with no caller (grep the frontend and scripts for each endpoint)
- Fetchers, strategies or handlers registered but never dispatched to

For each: **evidence it is dead**, not a guess. A path that is dead because a
config value is absent is a different finding from one that is structurally
unreachable — say which.

---

# PASS 2 — SEMANTICS

## 4. Pipeline topology — trace it end to end

Name every stage between a raw book quote and a published board row. Do this
twice: **pregame** and **live**. For each stage: module, input, output, where
state persists, what triggers it, and what its latency is.

The measured funnel is known; the **stages** are not:

```
14,216  opportunities considered
   200  published to Layer 2 shortlist
   145  candidates in the snapshot chat reads
    12  evidence-pack ceiling
     5  rows returned to a user
```

For each narrowing step: what does the selecting, on what criterion, and is that
criterion configurable, hardcoded, or adaptive-but-inert? (The recommendation
engine's gate is known to collapse to `edge > 0` because every adaptive term
requires settled history that does not exist.)

**The question that matters:** are these five numbers five deliberate stages, or
one deliberate stage and four accidents of buffer sizes?

## 5. Concept ownership — the "confusion" half of the brief

Duplication of *code* is visible. Duplication of *meaning* is what actually
causes confusion, and it is the more likely source of the mess.

For each term below: every definition in the codebase, whether they agree, and
which is canonical. Then whether the UI, chat and artifacts use the same one.

`edge` · `value` · `EV` · `model_edge_pct` · `min_value_pct` · `fair
probability` · `market probability` · `confidence` · `score` · `model_skill` ·
`candidate` · `opportunity` · `selection` · `pick` · `recommendation` ·
`Layer 1` · `Layer 2` · `shortlist` · `board` · `snapshot` · `intelligence
state`

Known collisions to resolve:

- `confidence` is a scoring artefact in one place and read as P(outcome) in
  another
- `edge` is served with `market_probability: null` and `EV: null`, so the user
  sees a number checkable against nothing
- "board" means the freshly-built shortlist to the cards and a 2-hour-old
  persisted snapshot to chat

**Deliverable:** a glossary with one canonical definition per term, and a list of
every site that disagrees with it. This document is worth more than any single
code fix.

## 6. State and artifact topology

- Every artifact and persisted state object the board path writes or reads:
  writer, readers, cadence, TTL, declared freshness SLA, measured age.
- Which are hot (7,185 artifacts / 6.63 GB known) and which are orphaned — written
  and never read, or read by dead code only.
- `read_latest_intelligence_state` was measured at **7,346 s against a 60 s
  SLA**. Enumerate everything that reads it; chat is unlikely to be the only
  surface serving two-hour-old data.
- Where the same fact is stored in two places, and whether they can disagree.

## 7. The 50/50 pattern and its siblings

The fabricated coin-flip now has three confirmed sites (`_fair_probability`
→ 0.5, `game_board_contract` → 50.0, chat's 63 sightings). Treat this as a
**house pattern to eradicate**, not three bugs:

- Grep the whole codebase for absent-value-substituted-with-neutral-midpoint.
- Then the more general form: any default that makes missing data
  indistinguishable from measured data. Silent `except: pass`, `.get(k, <plausible
  value>)`, filters that silently no-op when they match nothing
  (`build_evidence_pack`'s already does this).
- Propose the invariant and where it should be enforced — contract layer, with a
  test.

---

# PASS 3 — PRODUCT

## 8. Pregame vs live — does the split exist?

The stated product is two experiences. Establish whether the code thinks so.

- Is there a clean pregame/live boundary, or one path with conditionals?
- What triggers the transition, and where is it recorded? (`odds_refresh_tracking`
  stamps a pregame→live close — is that the only marker?)
- Does the live path **reuse** pregame logic or **fork** it? If it forks, diff
  them; a drifted live fork is the most expensive kind of duplication here
  because it fails when nobody is watching.
- Live sims: do they exist, per sport? What is the input, the cadence, and the
  compute cost per update?
- **Latency budget, end to end**: book quote changes → ingested → sim/projection
  updated → candidate re-ranked → artifact published → UI reflects it. Measure
  each hop. A live edge product is defined by this number and it is currently
  unknown.
- What does the UI do on a live update — the 30 s poll does an `innerHTML` swap
  that destroys tab selection on four sports. Is there any push path, or is
  polling the whole live story?

## 9. Effectiveness against the goal

- For each sport: is there a live path at all, or only pregame? Expect gaps.
- Of the 200 published rows, how many are pregame and how many live?
- Are pregame and live edges computed against the same fair-value definition? If
  the live path prices against a different market snapshot than pregame, the two
  numbers are not comparable and should not share a column.
- Does anything close the loop — does a live edge that appeared and vanished get
  recorded? (Related: the shadow candidate ledger is off, so filter precision is
  structurally unmeasurable.)
- Where does the 86%-MLB byte concentration come from, and is the live path the
  reason? If live capture is the cost driver, that reframes the egress work.

## 10. Target shape and deletion list

Two deliverables, both concrete.

**Target architecture**, one page: the stages from §4 as they *should* be, with
one owner per concept from §5, and the pregame/live boundary drawn explicitly.
Note which sport differences are configuration and which justify separate code.

**Deletion list**, ranked, with evidence per line: file or function, why it is
believed unused, what would break if wrong, and how to verify before deleting.
Order by (confidence it is dead) × (lines removed). This is the output the
cleanup lane actually consumes.

---

## Output

Three dated notes in `.syndicate/`, one per pass, plus:

1. The glossary from §5 — canonical definition per term, disagreeing sites listed
2. The duplication table from §2 — concept, canonical implementation, other call
   sites, semantic-vs-accidental verdict
3. The deletion list from §10
4. The pregame/live latency table from §8
5. Ranked fix list, with anything user-visible or edge-affecting above anything
   structural

**No code changes in any pass.** If a one-line fix is found, record it and move
on — the value of this audit is the map, and a map built while editing is a map
built against a moving target.

## Method notes

- Prefer `[measured]` / `[from-code]` tagging as in the three prior audits.
- Prefer trusted-click Playwright over synthetic `el.click()` for any UI
  verification — the synthetic probe produced a wrong result that had to be
  retracted in the UI audit.
- Re-read the deployed SHA per service before starting each pass and scope claims
  to it. Local HEAD has diverged from the deployed tree at least twice.
- NBA, NHL and NCAAB are out of season; anything about them is code-only until
  October.
