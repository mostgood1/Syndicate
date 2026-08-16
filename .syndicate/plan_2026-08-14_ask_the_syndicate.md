# Ask the Syndicate audit → lane plan — 2026-08-14

> **AMENDED 2026-08-16 — see `.syndicate/plan_2026-08-16_ask_answer_substance.md`.**
> This plan is entirely about **routing** (which sport, which fetcher) and
> **aggregation** (M1). It contains no item about the *content of a single-pick
> answer*, which is where four measured user-visible defects live: a prop answer
> names neither the prop nor the side; the briefing says "top 5" and renders 3
> (client-side, invisible to the regression harness); a game side reads
> `home -1.5` with no team, price or book; and `bet_analysis.edge` publishes
> **EV** while `market_summary.edge` publishes **model edge**, so the same pick
> reads 14.0% in the briefing and 1.4% per-pick.
>
> Consequences: **M1 is half-credited** (fixed the pool, not the substance).
> **K8 is absorbed and made concrete** — `projection.model_skill` is the
> mechanism it was written to need. **L2 re-opens on `bet_analysis`**, as a
> units divergence rather than a pool divergence. **The exit rule "anything that
> does not move a class score is not done" is retired as the sole gate**: the
> harness scores the JSON and cannot see the panel, so it scores all four
> reports as nonexistent. Lanes K9/K2/K11/K3/K4/K5/K6 are unaffected.

Derived from `.syndicate/audit_2026-08-14_ask_the_syndicate.md`. Measured against
production web `f9aa2399`. Lane letters continue from `plan_2026-08-14_models.md`
(A–D) and `plan_2026-08-14_ui.md` (E–I).

> **SUPERSEDED IN PART, 2026-08-14 — the user has decided: the LLM is NOT
> meant to be on.** `ANTHROPIC_API_KEY` stays absent; the deterministic snapshot
> path is the product, not a degrade.
>
> **This plan's own reasoning is the justification for that decision** — see the
> section immediately below, which argues that enabling today would take bad
> inputs and make them *fluent*. The plan framed that as sequencing (gate, then
> enable). The decision makes it terminal.
>
> Consequences, applied inline below: **Lane N is VOID**. **Lane J shrinks to
> J2.** **Lane M is reframed from tools to handlers and moves UP.** **L1's
> hypothesis is REFUTED.** Everything in Lane K stands unchanged. See also
> `.syndicate/plan_2026-08-14_ask_without_llm.md`.

## The correction to the audit's item 1

The audit puts "decide whether the LLM path is meant to be on" first and calls it
blocking. Split that item, because the two halves point opposite ways.

**Making the degrade visible is urgent.** A silent fallback that has apparently
run for the life of the feature is how "answers aren't accurate enough" went
undiagnosed for months. Ship today.

**Turning the LLM on is currently the most dangerous single action available**,
and it should be gated, not expedited. Consider what the model would receive
today: an unordered 12-row prefix of a 145-row snapshot that is 2h02m stale
against its own 60 s SLA, with soccer unnameable, NBA questions answered from
WNBA data, and every unrouted ranking question hardcoded to an MLB-only
leaderboard. The LLM would not fix any of that. It would make it *fluent*.

Right now the failures are legible — a user sees five rows and a template
sentence and can tell it is generic. After enabling, the same wrong inputs come
back as a confident CIO-analyst briefing with a headline, a verdict and a
confidence score. **The silent degrade has been protecting you.** That is not an
argument for leaving it silent; it is an argument for fixing the inputs before
paying for eloquence.

Second reason to gate: `/api/syndicate/query` is **public and
unauthenticated**, and the LLM rate limit is 30 calls per 600 s **per process**
with `WEB_CONCURRENCY = 2`. The audit's own 52-call baseline would have breached
it. Setting the key on an unauthenticated endpoint with a per-process limiter is
an unbounded spend vector that does not exist today only because the key is
absent. The audit lists this at #12; it belongs before enablement, not after.

---

## Lane J — ~~make it visible and make it safe (ship first)~~ → J2 only

**Three of four items existed to make ENABLEMENT safe. Enablement is not
happening, so they drop.** Lane J is no longer the first ship; Lane K is.

- ~~**J1.** Return `llm_enabled: false` in every response.~~ **Near-pointless
  under the decision** — `answer_source: "snapshot"` is the designed and only
  mode, not a degrade to be flagged. What survives is one comment in the route
  saying so, folded into whatever lane touches it next, so nobody re-diagnoses
  this in three months.
- **J2. KEEP — and it is the whole of this lane now.** Log questions: intent,
  `routed_sport`, `answer_source`, latency, row count (drop `usage`, which is
  always `None`). Lean records only — `#374` and the 367 MB evaluation chunk are
  the cautionary precedents. Without this the question taxonomy stays anecdote;
  the regression set is a proxy built from the brief, not from traffic.
- ~~**J3.** Auth posture on `/api/syndicate/query`.~~ **Downgraded to ordinary
  hygiene.** Its urgency came from "not once each call bills". Calls never bill.
  Public and unauthenticated on a free, read-only endpoint is survivable.
- ~~**J4.** Shared LLM rate limiter.~~ **DROPPED.** It exists only to bound spend
  on a key that will not be set.

**Exit:** questions are logged.

---

## Lane K — stop wrong answers on the path that actually runs

None of this needs the LLM. All of it improves what users get **today**.

- **K1. SHIPPED 2026-08-14** (lane `ask-refusal-gate`). Gate the
  `market_summary` default on the question containing any betting-domain token;
  otherwise decline. `market_summary` was the resolved intent on **40 of 52**
  questions, including "What is the capital of France?", which returned five
  betting opportunities.

  **NUMBER CORRECTED — I claimed "fixes 5 of 8 refusal cases" here and in the
  audit, and that was wrong.** 3 of 8 refusal cases were already passing; 5 were
  failing; a lexical domain gate fixes **3 of those 5**. Measured across all 52
  cases: `market_summary` 40 → 37, `out_of_scope` 0 → 3, **3 cases changed, all
  3 correct, zero regressions.** Refusal class 3/8 → **6/8** pending the
  production re-measure.

  The two it does not fix, and why they need a different layer: F03 ("How many
  home runs did Babe Ruth hit against the Mets?" — dead player, no such
  matchup) needs **entity validation**; F05 ("Who won the game that hasn't been
  played yet tonight?" — impossible tense) needs **temporal validation**. Both
  borrow real domain vocabulary, so no word list can catch them.
- **K2.** Add `soccer` and `ncaab` to `_SPORT_HINTS` **and**
  `_fetchers_for_sport`. Soccer is 100 of 200 published rows and 3,297 available
  candidates, and is currently unnameable — no keyword, no fetcher branch, hits
  `return []`.
- **K3.** Fix the routing collisions: give `wnba` its own entry (it is a keyword
  inside `nba` today); score `_SPORT_HINTS` matches instead of returning on the
  first tuple, so `goals` / `shots` / `assists` stop being decided by list order;
  make `build_evidence_pack`'s sport filter an exact match rather than a
  substring (`"nba"` currently matches `"wnba"`); and **emit a reason when the
  filter matches nothing** instead of silently returning every sport.
- **K4.** Fix the two dispatch bugs: `nba` → `_wnba_focused_evidence`, and the
  no-sport ranking branch routing exclusively to `_mlb_top_candidates_evidence`
  — "biggest edges tonight" returns an MLB-only leaderboard by construction,
  whatever the slate holds.
- **K5.** Return `routed_sport` in the payload. `None` on 52/52 today, so neither
  a user nor the regression harness can see what the router assumed.
- **K6.** Put an as-of in every answer, sourced from `freshness.computed_at`.
  `visuals.as_of` only populates when a sport branch matches, so it is `None` for
  every soccer, ncaab and unrouted question — 41 of 52 answers carry no timestamp
  of any kind.
- **K7.** Stop emitting `model_probability: 50.0`. **Cross-plan** — same fix as
  model Lane A1 and UI Lane F1.
- **K8.** Give the deterministic path its own hedging and refusal rules. Every
  guardrail today lives in a system prompt that does not execute. The
  responsible-gambling framing that passed the adversarial cases passed *by
  accident of vocabulary* — the generic board summary happens to contain
  bankroll words. That is luck, and it will stop being lucky when K1 changes what
  the default path emits. **Under the decision this is permanent, not interim:
  those rules will never execute, so K8 is the only place they can live.**

### K9–K11 — the deterministic-coverage gaps (added 2026-08-14, measured)

The plan above covers routing. It does not cover the fetchers the routing
reaches. Measured on production, same questions with and without an explicit
`sport` in context — **`collect_focused_evidence` builds real tables and charts
with no LLM at all**, and on five sports it builds nothing:

| sport | questions producing evidence | tables | charts |
|---|---|---|---|
| mlb | 4/4 | 14 | 4 |
| ncaaf | 2/2 | 4 | 0 |
| nba | 1/1 | 1 | 1 |
| **nfl / wnba / soccer / nhl / ncaab** | **0/9** | **0** | **0** |

MLB proves the deterministic path can be genuinely good. Three distinct causes,
needing three different fixes — conflating them is how this gets half-done:

- **K9. NFL entity matching is too strict.** Isolated in-process:
  `_nfl_teams_in_question("Patriots vs Seahawks projection")` → `[]`;
  the full `"New England Patriots vs Seattle Seahawks"` → both teams.
  `_nfl_matchup_evidence` returns `None` at `len(teams) < 2` before it ever
  opens an artifact. Nobody types the full name. MLB handles "Cubs vs
  Cardinals" fine — the difference is care, not data. **Smallest fix with a
  whole sport behind it.**
- **K10. WNBA / NHL / NBA have entity-only fetchers.** Both WNBA fetchers
  returned `None` for "What are the best WNBA points props?" *with*
  `context={"sport": "wnba"}` — they need a named entity and a ranking question
  names none. MLB is the only sport with a ranking path
  (`_is_ranking_intent_question` → `_mlb_top_candidates_evidence`), and that
  function is genuinely MLB-specific (`_detect_mlb_market`, MLB artifact paths).
  **Prefer M1 over writing three more of these** — see Lane M.
- **K11. soccer / ncaab have no branch at all** — this is K2's other half.
  `_fetchers_for_sport` falls to `return []`, so even a correctly-routed soccer
  question gets nothing.

**Exit:** re-run the regression harness. Target is a large move on `refusal`,
`lookup` and `entity` (currently 3/8, 2/8, 2/10) with no LLM involved.

---

## Lane L — freshness, and a hypothesis worth testing

The snapshot chat reads is **7,346 s old against a 60 s SLA** — 122× — and the
platform labels it `stale` / `is_fresh: false` while serving it as an answer.

- **L1. HYPOTHESIS REFUTED 2026-08-14 — it is not live-odds-worker.** Measured
  via the Render env API:
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is **`true` on
  refresh-worker** (`srv-d91dpertqb8s73co8ls0`) and **`false` on
  live-odds-worker** (`srv-d91dpertqb8s73co8lt0`) and **`false` on web**.
  `SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS = 60` on all three — that is
  the 60 s the freshness block measures against.

  **Refuting the named suspect does not establish the cause.** What it does
  establish is where to look: the loop runs on refresh-worker, and
  `pipeline/intelligence_state.py:500-516` gates the board build behind
  `_board_build_has_memory_headroom()`. Refresh-worker is the service carrying
  `#423`'s open anon-memory lane and a `MEMORY_GUARD_ABORT` history.

  **So L1 is probably NOT an ask-layer lane at all.** Before opening one, check
  whether `anon-allocation-site`, `refresh-worker-anon-leak` or
  `layer2-board-freshness` already own it — and check what else reads
  `read_latest_intelligence_state`, because if the guard is skipping rebuilds
  then every one of those surfaces is stale too, not just chat.
- **L2.** Then either serve chat from the same board payload the cards read, or
  stamp `age_seconds` into every answer. Today chat says 5.02% while the board
  says 13.59% on the same slate. Note the audit's finding that the `jose fermin`
  selection was **the same divergence, not a hallucination** — a different pool,
  not an invented player. Fixing the pool fixes both symptoms.
- **L3.** Note for later: the 600 s response cache is inert today (LLM answers
  only). The moment the key is set it adds up to 10 minutes on top of an already
  stale snapshot. Fix L2 before the cache becomes live, and add key
  normalisation — "best bets tonight" and "Best bets tonight?" are separate
  entries today.

---

## Lane M — grounding: the only fix that changes the verdict

> **REFRAMED UNDER THE DECISION, AND PROMOTED.** M1–M4 are written as "tools",
> and a tool is something a model calls. With no model they are **handlers**:
> they always run, always return the same answer, cost nothing, and are
> testable. That is strictly better than a tool an LLM may or may not invoke.
>
> M gets *more* important, not less — there is no LLM to paper over a 12-row
> prefix, so the handler IS the answer. **M1 should ship second, right after
> K1**, and it subsumes K4's MLB-only-leaderboard bug and most of K10.
>
> The closing line below ("prefer widening the tool surface over widening the
> prompt") is now moot: there is no prompt.

Everything in K and L improves a fundamentally limited architecture. **M is what
makes the architecture able to answer the questions users actually ask.**

The funnel, measured at one instant: 14,216 considered → 200 published → 145 in
the snapshot chat reads → 12 evidence-pack ceiling → **5 rows returned**. A fixed
prefix of a pre-ranked list is not an aggregation primitive, so "every play with
an edge over 5 percent" cannot be answered correctly in principle.

- **M1.** Expose a filter/rank tool over the full candidate pool — by sport,
  market, edge, league — returning counts as well as rows. This is the structural
  fix for the `ranking` class (4/10, the class users ask most) and needs **no new
  data**: `/api/board/layer2-shortlist` already holds it.
- **M2.** Expose market history — `build_market_history_view` already computes
  opening/latest/closing, `movement_delta` and velocity. Unlocks "which totals
  moved most since open."
- **M3.** League scoping for soccer; rows already carry `league` (`#330`).
- **M4.** Per-sport slate listing from `active_sports` / `per_sport`, and
  `model_skill` per market (`#425`) so an answer can say whether the model behind
  a number has ever been measured.

Prefer widening the tool surface over widening the prompt. Note there is **no
tool surface at all** today, so a capability added by describing it in the prompt
would have no guardrail behind it and would not even execute.

**Needs new data, deferred:** CLV per sport/market — blocked on model plan Lanes
A and B. Historical prop accuracy beyond MLB hitters — blocked on the
archive-replay extension.

---

## Lane N — ~~enable the LLM (gated)~~ **VOID 2026-08-14**

**The user has decided the LLM is not meant to be on. This lane has no
destination and is not to be re-opened without an explicit reversal, logged.**

Its preconditions (J1–J4, K1–K5, L2, M1) were all worth doing on their own
merits and remain in the plan — N was never what justified them. Its one
genuinely lost item is N2, "the first measurement of the LLM path's quality that
will ever have existed": that measurement will now never exist, which is a cost
of the decision and worth naming rather than eliding.

The body below is kept for the record only. **Do not execute it.**

<details><summary>void — original Lane N</summary>

Preconditions, all of them:

- J1–J4 shipped (visible degrade, logging, auth posture, shared rate limit)
- K1–K5 shipped (no out-of-scope board dumps, 8 sports routable, no dispatch
  bugs)
- L2 shipped (chat and board read the same pool, or age is stamped)
- M1 shipped (aggregation is answerable at all)

Then:

- **N1.** Set the key on one service first and watch cost and latency against
  the p50 1.4 s / p90 6.9 s snapshot-path baseline.
- **N2.** Re-run `scripts/ask_syndicate_regression.py`. The harness already reads
  both `briefing` and `structured_response`, so this produces a genuine A/B
  against the 20/52 snapshot baseline rather than a fresh unanchored number.
  **This is the first measurement of the LLM path's quality that will ever have
  existed.**
- **N3.** Only after N2 reads well: revisit the evidence pack. `MAX_CANDIDATES =
  12` as an unordered prefix is a poor selection rule even once M1 exists — it
  should be a query result, not a slice.

</details>

---

## Execution order under the decision (supersedes the lane letters)

1. **K1** — gate the `market_summary` default. No preconditions, one condition,
   fixes 5 of 8 refusal cases. **New first ship**, replacing Lane J.
2. **M1** — board-candidates handler over `/api/board/layer2-shortlist`. Closes
   the `ranking` class for all four active sports, kills the 5.02%-vs-13.59%
   divergence, needs no new data, subsumes K4 and most of K10.
3. **K9** (NFL nicknames) → **K2/K11** (soccer + ncaab branches) → **K3/K5**
   (routing collisions, `routed_sport` in the payload).
4. Folded in, not laned separately: **K6** (as-of), **K7** (the 50.0 —
   cross-plan), **J2** (logging).
5. **K8** last, but not optional — and now permanent rather than interim.

Dropped: J1, J3, J4, Lane N, L3. Reassigned: L1 → the memory-guard lanes.

Every step re-measures with `scripts/ask_syndicate_regression.py` against the
**20/52** baseline. Anything that does not move a class score is not done,
whatever the diff looks like.

---

## Cross-plan

- **The 50.0 coin-flip is now three-for-three** — model (`_fair_probability`
  0.5), UI (`game_board_contract` 50.0), chat (63 sightings in 52 calls). This is
  no longer a pattern to watch. Promote UI Lane F4 from "grep and write it down"
  to a contract-level invariant with a lint or test behind it: **absent renders
  as absent, everywhere.**
- **Soccer is worst on all three audits.** 100 of 200 published rows; zero model
  comparison on any of them; two conflicting home-win numbers on the card; no
  draw slot in the probability bar; unnameable in chat; both draw questions fail.
  UI Lane G should probably be promoted from a lane to a small program spanning
  all three plans.
- **The regression harness is the best artifact any of the three audits
  produced.** Fetched-not-hardcoded truth, refusal scored as substance rather
  than wording, and it reads both answer shapes so it will not mis-score after
  enablement. Make it the template for UI Lane H rather than inventing a second
  style of probe.

## Explicitly not now

- **Setting `ANTHROPIC_API_KEY`.** See the correction above. This is the one item
  where moving fast makes the stated problem worse rather than better.
- **Prompt engineering on `SYSTEM_PROMPT`.** It is sport-neutral and clean; the
  MLB-shape problem is entirely in the routing and fetcher layers below it. Leave
  it alone until it has run at least once.
- **New capabilities described in the prompt.** No tool surface exists to back
  them.

## Carried open

- Real question distribution unknown until J2 lands; the regression set is a
  proxy built from the brief's taxonomy, not from traffic.
- `_build_artifact_response` returned `None` on every case tested, and it
  short-circuits **before** both `collect_focused_evidence` and
  `generate_briefing`. Its behaviour when it does return is untested — worth
  tracing before N1.
- NBA, NHL and NCAAB were out of season; their matrix rows reflect routing
  behaviour, not answer quality on a live slate. Same October re-measure as UI
  Lane H3.
