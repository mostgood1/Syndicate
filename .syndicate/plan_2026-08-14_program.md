# Syndicate — program sequencing, 2026-08-14

Consolidates `plan_2026-08-14_models.md` (lanes A–D),
`plan_2026-08-14_ui.md` (E–I), `plan_2026-08-14_ask_the_syndicate.md` (J–N)
and the board-engine audit (Passes 1–3 + SYNTHESIS).

**This is not lanes O onward.** The board-engine findings cut across the three
existing plans rather than adding to them: they reorder A–N, correct three items
inside them, and add two product decisions that sit above all of it. Lane letters
below refer to the existing plans.

---

## TIER 0 — ship what is already written (hours, not days)

Four pieces of work are finished, tested, and not running. Nothing else in the
program has a better return than deploying them.

| # | what | where | fixes |
|---|---|---|---|
| 0.1 | pregame relaunch cooldown keyed per sport | branch `odds/pregame-cooldown-per-sport` `9ec20a06` | MLB fetch cadence ~121.6 min → board prices up to 2h stale |
| 0.2 | overview memory cutover | branch `memory/overview-sum-to-max` `086702ae` | 522 MB worker dying in 25s inside one 8-sport hydrated pass |
| 0.3 | MLB prop calibration | `aac18260` (model plan D3) | the only measured skill numbers in existence are not served |
| 0.4 | push the ops kit | `74d38daa`, local only since Aug 13 | `.syndicate/` invisible to the other session and to any scheduled job |

**0.1 carries a cost:** it raises OddsAPI call volume. Measure calls against the
5M cap, not just cadence.

**0.2 is probably the answer to a two-week-old question.** The chronic
`live-odds-worker` restarts, instance count dropping to 0, and pegged CPU have
been treated as an infra problem since Aug 12. A 522 MB worker dying in 25s
inside the Layer 1 hydrated overview is a code cause with a written fix. Deploy
it, then re-read the restart graph before doing any further infra work.

**Also Tier 0, one line of config:** turn on the shadow candidate ledger
(`SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED`). Filter precision is structurally
unmeasurable while it is off, and it is the stated blocker on the board audit's
§9. It accrues value only by running, so it should start now even though nothing
reads it yet.

---

## TIER 1 — start the clocks

Everything here produces data that only accumulates with wall-clock time. Late
starts cannot be recovered.

- **Model Lane B** — settlement-free CLV (recommendation `quote` → `market_state`
  stamped `closing_price`), with B2's pricing-version stamp.
  **CORRECTION from the board audit:** also stamp **fetch cadence / quote age**
  on every CLV record. With MLB odds refreshed every ~121.6 min, an "opening"
  price may be up to two hours off the real open, and a CLV number computed
  without that context is not interpretable. This correction applies whether or
  not 0.1 has shipped.
- **Ask Lane J2** — question logging (intent, routed sport, answer_source,
  latency, usage, row count). Lean records; `#374` and the 367 MB evaluation
  chunk are the precedents.
- **Ask Lane J1** — `llm_enabled: false` in every response plus a log line on the
  degrade path.

---

## TIER 2 — known-sign correctness, no measurement required

Run in parallel with Tier 1. Every item has a known-wrong current behaviour;
none needs a metric to justify.

- **Model Lane A** (A0 diagnostic first, then A1–A4) — the recommendation lane's
  0.5 fallback, `confidence`-as-probability, vigged pricing, negative-model-edge
  rows.
- **Ask Lane K1** — gate `market_summary` on the question containing a
  betting-domain token. Cheapest high-value fix in the program: 5 of 8 refusal
  failures, and it stops "what is the capital of France" returning five picks.
- **Ask Lane K2–K5** — soccer and ncaab routable; wnba its own entry; scored
  matching; `routed_sport` returned.
- **UI Lane E** — NCAAF blank tab, box-sizing overflow on four sports, mobile
  stacking, tab selection surviving the poll.
- **Model Lane D** — hygiene (D1 soccer CSVs not citable, D2 as-of date on
  `compute_team_ratings`, D4 out-of-sample prop scoring, D5 deployed-SHA in
  `/preflight`).

**D5 deserves promotion.** Deploy drift has now affected four audits: local HEAD
diverged twice, all three service SHAs moved *during* the Pass 1 session, and the
working tree matched none of them. Every finding in this program is scoped to a
moving target until `/preflight` prints deployed SHA per service by default.

---

## TIER 3 — the probability substrate

**CORRECTION to UI Lane F and Ask K7.** Those treat the fabricated coin-flip as
one defect in three places. The board audit measured the real surface: **40 sites
substituting 0.5 for a probability, 3 substituting 50.0.** But the 40 are not 40
instances of one bug:

- `drive_priors.py`'s `(success_rate or 0.5) - 0.5` is a **centered prior** —
  0.5 is the genuine neutral point of a rate
- `faceoff_win_pct: float = 0.5` is a legitimate sim-contract default
- `0.5 * (1.0 + math.erf(...))` is the **normal CDF** — not a default at all

Enforcing the invariant indiscriminately would break sim engines. **Triage
first.** The defect is only where 0.5 substitutes for a probability that reaches
a user or feeds an edge calculation. The 3 sites at 50.0 in
`game_board_contract` are unambiguous and can go now.

Similarly, the **240 bare `except: pass`** are a hygiene backlog, not a board
correctness finding. Folding them in dilutes an otherwise well-aimed invariant.
Leave them out of this tier.

### 3a. Differential-test before consolidating

42 sites define or convert a probability: 18 prob↔odds conversions (Pass 1),
9 `implied_probability`, 11 `confidence`, 4 `fair_probability`.

Run the pure ones — the 18 conversions and the 9 `implied_probability`
functions — over one price grid: 0, ±100, ±150, ±10000, `None`, `""`, `"+150"`
as a string, decimal odds arriving where American is expected. **Any
disagreement is a live pricing bug**, and the survivor is the canonical
implementation, identified by evidence rather than by preference.

This turns a cleanup into a bug hunt and produces the one thing the glossary
needs: an owner per concept, established rather than asserted.

### 3b. Then the invariant

*A probability, edge or EV not computed from data must be `None`, never a
number.* Enforce at `game_board_contract` — 28 importers, the one choke point
every card passes through — plus one test that a `None` probability reaches the
card as `None`.

---

## TIER 4 — Layer 1 reliability (REVISED — was "the Layer 1 decision")

**Superseded by the hierarchy correction of 2026-08-14.** This tier previously
proposed gating Layer 1 off to see whether anything user-visible changed. That
was built on a wrong premise and is withdrawn.

**The stated hierarchy:** Layer 1 is the **known universe** — pregame and live —
and the user's research surface. Layer 2 is Syndicate's **curation** of it and is
the product core to perfect. There is no Layer 2 without Layer 1.

### The same measurements, read correctly

Every number is unchanged. Their meaning inverts.

| measurement | old reading | correct reading |
|---|---|---|
| L1 `count=0` on 3 of 5 builds | evidence it isn't earning its cost | **the research surface is dark ~60% of the time** |
| L2 doesn't consume L1's output | evidence of redundancy | why the outage went unnoticed |
| L1 costs 498.7s / 3h | overhead on a legacy path | the cost of a product surface — an optimisation question |
| the overview OOMs the worker | a reason to cut it | **a P0 on a product surface** |

`count=0` on three of five builds is not a deletion argument. It is an outage
that has been running long enough to be measured, on the surface users research
from, hidden because the curated product kept working off the shared grid.

### Resolving the apparent contradiction

"There is no Layer 2 without Layer 1" and "Layer 2 does not consume Layer 1's
output" are both true, and the measured topology reconciles them:

```
shared ingestion → grid → ┬→ Layer 1 board      (known universe)
                          └→ Layer 2 shortlist  (curation)
                          
                    candidate_pool → (serves neither)
```

They are **siblings off the shared grid**, not sequential. The necessity is
conceptual — curation needs a universe to curate from — while the runtime
coupling is to the grid. That is precisely the mechanism by which L1 can fail
without L2 noticing, and it is worth stating explicitly in §10's architecture,
because a reader who assumes a runtime dependency will draw the wrong diagram.

**Consequence for §10:** the hierarchy was the missing input that blocked the
target architecture. It is no longer blocked on this axis — only on the glossary.

### Work

- **4.1 — Diagnose the `count=0` builds.** Is it the OOM (0.2), or an
  independent failure? Deploy 0.2 first, let the restart graph settle, then
  re-measure L1 build success rate. Do not run other L1 changes in the same
  window.
- **4.2 — Instrument L1 build success as a first-class metric.** A surface that
  can be dark 60% of the time without anyone noticing needs an alarm, not a
  quarterly audit. This is the scheduled-brief use case.
- **4.3 — Then optimise, not amputate.** 498.7s per 3h and the hydrated
  8-sport pass are worth reducing on their merits; the question is how to make
  the known universe cheap and reliable, not whether to have one.
- **4.4 — The deletion candidate moves.** The separate `candidate_pool` path
  that serves neither board is now the thing to investigate for removal. It was
  the third pipeline all along; the two-layer framing hid it.

---

## TIER 5 — the live product decision

**The stated premise — "pregame and live board experience" — does not currently
hold.** No live game-line projection exists (`predictions.full` is the pregame
sim), only props have a live tier, and `rows_live_edged` has been 0 on every
build to date.

The unusual part is the asymmetry: **91 modules carry a pregame/live
discriminator and 16 are named `live`**, against zero live edges published. That
is extensive machinery that does not terminate in a product.

Before building more live capability, answer one question per named module: is
this **scaffolding awaiting a projection**, or an **abandoned approach still
costing compute**? Sixteen modules is a bounded read.

Then the product decision, which is yours and not an engineering call:

- **Build the live game-line projection**, making the premise true — a real
  scope, and it needs the latency budget below before it can be specified.
- **Or declare the product pregame-first** with a prop-only live tier, which is
  honest, already mostly built, and lets Tier 4's savings fund Tier 3.

**Either way, measure this first:** quote change → UI reflects it, end to end.
It is the number a live edge product is defined by and it is still unmeasured.
Note that stage 1 alone currently puts a floor of ~121.6 min on it, so 0.1 is a
prerequisite for the measurement meaning anything.

---

## TIER 6 — structural, after the above

- **The seven-in-one import cycle.** Seven of the 24 cycles are the same shape,
  once per sport: `game_board_contract → simulation_adapter → <sport>/cards →
  game_board_contract`. One dependency inversion — sport cards register with the
  contract instead of the contract reaching into each sport — fixes all seven and
  explains why `game_board_contract` is a 28-importer hub.
- **UI Lane I** — card consolidation, MLB migrating onto the generic template
  last.
- **Ask Lane M** — the aggregation tool surface. The only fix that changes the
  chat grounding verdict from negative.
- **Ask Lane N** — LLM enablement, still gated on J, K, L and M.
- **UI Lane G** — soccer end-to-end. Worst sport on three of four audits.

---

## Finishing the audit — only two items are worth it

The board audit self-assesses at 45–50%. The remaining half is not uniformly
valuable.

**Worth doing:**
1. **The glossary, built by reading**, from the UI backwards. Tier 3a makes this
   much cheaper by settling ownership of the probability substrate first — do
   3a, then the glossary.
2. **The live path traced on an actual live slate**, which Tier 5 needs anyway.

**Not worth doing now:** classifying the 18 sport-fork pairs as semantics vs
drift; refining the config cross-reference; the 164-module static reachability
list (dynamic imports and thread targets are not followed, so it is not
evidence); the 136-route shortlist.

**Blocked, not deferred:** §9 effectiveness, until the shadow ledger has run
(Tier 0). §10 target architecture, until the glossary is real.

---

## Corrections to record in the existing plans

- **UI plan** — strike both citations of `static/mlb/board.js`. It does not
  exist.
- **UI plan Lane F / Ask Lane K7** — rescope per Tier 3 above; the 0.5 surface is
  over-counted and includes legitimate sim priors.
- **Model plan Lane B** — add the fetch-cadence stamp per Tier 1.
- **This plan, Tier 4** — rewritten after the layer hierarchy was stated. The
  original "gate Layer 1 off and see what breaks" is withdrawn.
- **Board-engine brief** — three edits owed: add the layer hierarchy to the goal
  statement (§10 cannot draw a target architecture without knowing which surface
  is the product); insert the measured three-pipeline topology as an input; and
  annotate rather than delete the three stale "known already" items so the
  correction stays visible.
- **All plans** — the instruction to treat prior audit findings as established
  and not re-derive them was wrong. Three of the four briefs' supplied "known"
  inputs did not survive checking. Re-verify before acting. `learnings.md` now
  carries the general rule: spend the first ten minutes of any audit
  re-verifying the inputs it tells you not to re-derive.
- **Movement and steam work generally** — the 23 movement implementations,
  `movement_velocity` and the steam detector are computing on a signal sampled
  roughly every two hours. Nothing in that family should be trusted or extended
  until 0.1 has shipped and the real sampling interval is known.

---

## Decisions only you can make

Listed together because they gate large amounts of work and none is an
engineering question.

1. ~~Does Layer 1 stay?~~ **ANSWERED 2026-08-14: yes — it is the known universe
   and the research surface.** Replaced by an engineering question, not a
   product one: what reliability does the research surface need, and what does
   it cost to get there (Tier 4)?
2. **Is the product pregame-first, or does live game-line projection get built?**
   (Tier 5.) **Note the correction raises the stakes:** Layer 1 is specified as
   pregame *and* live, so the missing live game-line projection is a gap in the
   research surface too, not only in the curated board.
3. **Market-EV screener or model-driven picks?** 143 of 200 published rows carry
   no model. Both are legitimate products; the current state, where a user cannot
   tell which row is which, is not. (Models plan.)
4. **Is a sharp reference price obtainable?** Model plan Lane C — sourcing, not
   engineering, and it determines whether CLV numbers mean anything.
