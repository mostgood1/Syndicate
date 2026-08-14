# "Ask the Syndicate" audit — 2026-08-14

> Read-only pass on existing code. One new artifact was added, because the brief
> asks for it and it is the thing that makes every later change measurable:
> **`scripts/ask_syndicate_regression.py`** — 52 questions, machine-checkable
> expectations, runnable. Baseline output:
> `reports/ask_regression/baseline_2026_08_14.json`.
>
> Measured against **production** (`syndicate-an21.onrender.com`, web
> `f9aa2399`) 2026-08-14 13:35–13:45 CDT. `[measured]` = read from a live
> response or the Render API; `[from-code]` = read from source.
>
> Companion audits from today: `audit_2026-08-14_models.md`,
> `audit_2026-08-14_ui.md`. Three findings here are the same defect seen from a
> third angle, and are cross-referenced rather than re-litigated.

---

## 0. The finding that reframes all three stated problems

**The LLM has never answered a question in production.**

`ANTHROPIC_API_KEY` is **absent from the live web service's 73 environment
variables** `[measured, Render API, srv-d88ahvrbc2fs73eodu30]`. `llm_enabled()`
is `bool(os.environ.get("ANTHROPIC_API_KEY"))`, so `generate_briefing()` returns
`None` on every request and the route falls through to the deterministic
snapshot shaping. Confirmed end-to-end: **`answer_source: "snapshot"` on 52 of
52 regression calls**, `usage: None`, `briefing: absent`, `model: None`.

So `ask_the_syndicate_engine.py` — 335 lines, the CIO-analyst system prompt, the
`BRIEFING_SCHEMA` with headline/verdict/confidence/key_drivers/risks/
invalidators, the whole "anchor your narrative in the focused evidence" contract
— is **dead code in production**. What users actually receive is a five-row
board dump with a one-sentence template summary.

`render.yaml:40-43` documents the degrade path (`sync: false`, "when absent the
endpoint serves snapshot-only responses (no error, no LLM call)"). It is silent,
by design, and nothing surfaces it — no log line, no field in the response, no
counter.

**This means "answers aren't accurate enough" is not a prompt problem, a
retrieval problem, or a model problem. The component that writes answers is not
running.** Every recommendation below is ordered around that.

> **DECIDED 2026-08-14, by the user: the LLM is NOT meant to be on.** The
> snapshot path is not a degrade — it is the product. This is a standing
> decision, not an open question. Do not "fix" `ANTHROPIC_API_KEY` back in.
>
> That resolves fix #1 below and re-ranks the rest, but **invalidates almost
> none of this audit**: 10 of the 12 items are deterministic-path defects that
> are unaffected, and two of them (hedging rules, refusal) become *more*
> load-bearing because the guardrails written into the system prompt will never
> execute. The follow-on plan is
> **`.syndicate/plan_2026-08-14_ask_without_llm.md`**.

---

## 1. Grounding architecture — the traced path

### Which pattern is it?

**Prompt stuffing, gated by a regex router.** Not tool-calling, not embeddings,
not ungrounded. `[from-code]`

Traced end to end for `POST /api/syndicate/query {"question": "What are the
biggest edges on the board tonight?"}`:

```
1. ask_the_syndicate.py:444   route entry, no auth
2. _smart_route_payload()     flattens context onto the payload
3. SyndicateQueryRouter.route()
      regex rules over 4 intents; unmatched -> market_summary
      MEASURED: matched_terms ["the_board"], score 401
4. _query_cache_key() -> _read_cached_response()      600 s TTL, LLM answers only
5. _build_artifact_response()                          returned None here
6. read_latest_intelligence_state()                    persisted worker snapshot
7. build_syndicate_query_response()                    deterministic shaping
      -> answer_source = "snapshot"
8. collect_focused_evidence()                          returned None (see §2)
9. generate_briefing()                                 returned None -- NO API KEY
10. response returned: structured_response.top_opportunities[:5]
```

The evidence pack that step 9 would have built is bounded at
`MAX_CANDIDATES = 12` and `MAX_EVIDENCE_CHARS = 24000`, taken as an **unordered
prefix** of `snapshot["top_opportunities"]`, then truncated from the tail until
the JSON fits. `[from-code]`

### Can this architecture support aggregation questions? No — measured funnel

Aggregation and filtering questions are most of what users ask. Here is what the
answering layer can actually see, same instant `[measured]`:

| stage | count |
|---|---|
| opportunities the board considered | **14,216** |
| published to the Layer 2 shortlist | 200 |
| candidates in the snapshot chat reads | **145** |
| ceiling of the LLM evidence pack | **12** |
| rows actually returned to the user | **5** |

"Show me every play with an edge over 5 percent" is answered from 5 rows drawn
from a 145-row snapshot that was itself selected from 14,216 by a different
process. The retrieval layer **cannot in principle** return the data needed —
not because semantic search retrieves the wrong documents, but because a fixed
prefix of a pre-ranked list is not an aggregation primitive.

**Verdict: NEGATIVE for the ranking/aggregation class.** It is adequate for
single-subject lookup where the subject happens to be in the top 145.

### Single source of truth — divergence CONSTRUCTED AND CONFIRMED

They are two paths, and they disagree today. Same instant, same slate
`[measured, regression case B01]`:

| | value |
|---|---|
| chat, "What are the biggest edges on the board tonight?" | **5.02%** |
| `/api/board/layer2-shortlist`, max `model_edge_pct` | **13.59%** |

A user reading a card sees 13.59%; asking chat about the same board returns
5.02% and calls it the best edge. Neither number is labelled with where it came
from.

**Cause, and it is not a bug in either path**: the board serves a freshly built
shortlist; chat serves `read_latest_intelligence_state()`, whose own status
endpoint reports `age_seconds: 7346` — **2h 02m old**, against a declared
`freshness_sla_seconds: 60`, with `freshness_status: "stale"` and
`is_fresh: false`. `[measured]` The platform knows the snapshot is stale by its
own definition and serves it as an answer anyway.

Chat also surfaced one selection (`jose fermin`) absent from the served board.
Worth stating precisely: that is **the same divergence, not hallucination** — a
different pool, not an invented player. Across 52 cases only one distinct
selection was off-board.

---

## 2. Sport coverage — the cause of the inconsistency

### The system prompt is sport-neutral. The routing is not.

`SYSTEM_PROMPT` (engine.py:34) contains no MLB vocabulary — no innings, no
probable pitchers, no run line. It describes the data shape generically
("SmartSim simulation outputs, projection models, ranked candidates"). **That
part is clean and should be left alone.** The MLB-shape problem is entirely in
the routing and fetcher layers below it.

### `_SPORT_HINTS` covers five sports. There are eight.

`[from-code, ask_the_syndicate.py:33]` Entries exist for `mlb`, `nba`, `nhl`,
`ncaaf`, `nfl`. **There is no `soccer` entry, no `ncaab` entry, and no `wnba`
entry.** `_infer_sport` returns on the **first** matching tuple, with no scoring.
Consequences, each a real routing outcome:

- **"wnba" resolves to `nba`** — the literal string `"wnba"` is a keyword in the
  *nba* bucket.
- **`"goals"` and `"shots"` resolve to `nhl`.** So "How many goals will Arsenal
  score?" routes to hockey.
- **`"assists"` is in both `nba` and `nhl`**; `nba` is listed first, so every NHL
  assists question resolves to basketball.
- **Nothing routes to soccer or ncaab, ever.** No keyword exists.

### `_fetchers_for_sport` has no soccer branch and no ncaab branch

`[from-code, ask_the_syndicate_data.py:3237]` Branches exist for mlb (4 fetchers
+ 1 ranking-exclusive), wnba (2), nba (2), nhl (1), ncaaf (3), nfl (4), and `""`
(14). Anything else hits `return []` — **zero focused evidence**.

Two compounding details:

- `nba` dispatches to `_wnba_focused_evidence` (line 3261), so NBA questions are
  answered with WNBA data.
- The no-sport branch routes any *ranking-intent* question exclusively to
  `_mlb_top_candidates_evidence` (line 3271). **"Biggest edges tonight" returns
  an MLB-only leaderboard by construction**, whatever the slate holds.
- `build_evidence_pack`'s sport filter is a **substring** test
  (`sport in str(candidate_sport)`), so `"nba"` matches `"wnba"`; and when the
  filter matches nothing it is silently dropped (`if matching:`), returning every
  sport's candidates with no indication the filter failed.

**Soccer is the largest sport on the published board** — 100 of 200 shortlist
rows, 3,297 available `[measured]` — and it has no keyword, no fetcher branch,
and no way to be named.

### `routed_sport` is never returned at all

`[measured]` Across all 52 regression calls, the served payload carried
**`routed_sport: None`, 52/52**. Sport resolution is not merely uneven; it is
absent from the response contract, so a caller cannot tell which sport was
assumed.

### Three-way markets

`[measured]` Both draw cases fail. D06 ("How does the model handle a draw in a
soccer match?") and G09 ("Is the draw good value in the Coventry match?") route
to no sport and return a generic board summary with no mention of a draw. This
is the third sighting of the same gap today: the model layer's
`_no_vig_over_probability` handles three-way correctly, the **UI's probability
bar has no draw segment**, and chat cannot reason about one.

### Per-sport capability matrix

`[measured, regression baseline]` — "answers wrongly" means it produced content
attributed to the wrong sport or to no sport.

| question class | mlb | nfl | ncaaf | wnba | nba | nhl | soccer | ncaab |
|---|---|---|---|---|---|---|---|---|
| single-game lookup | partial | ✅ | ✗ wrong | ✗ wrong | ✗ wrong | ✗ wrong | ✗ wrong | ✗ wrong |
| cross-game ranking | partial | — | — | ✗ wrong | ✗ wrong | — | ✗ wrong | — |
| player prop lookup | ✅ | — | — | ✗ wrong | ✗ wrong | ✗ wrong | ✗ none | — |
| three-way / draw | n/a | n/a | n/a | n/a | n/a | n/a | **✗ none** | n/a |
| league scoping | n/a | n/a | n/a | n/a | n/a | n/a | **✗ none** | n/a |
| model explanation | partial | partial | partial | partial | partial | partial | partial | partial |

"✗ wrong" rather than "declines" is the important cell value: the router's
default is `market_summary`, so a sport it cannot resolve gets a confident MLB-
weighted board dump rather than a decline.

### Entity resolution and time zones

- Ambiguous club names are unresolvable — "United", "City", "Premier League" all
  fail to route (G01, G02, G07). There is no soccer team registry in the ask
  path at all.
- MLB tricode-vs-stat collision **is** handled: G03 ("Best TB targets today?")
  passes, via the ranking-intent branch added for exactly that case.
- **Time zones**: G08 ("What games are on tonight?") produced no timezone marker.
  `selected_date` is a bare date. For international fixtures spanning a UTC day
  boundary this is unresolvable as specified — and the ledger already records a
  five-hour UTC/CDT error costing a session today.

---

## 3. Question taxonomy and evaluation

### Finding #1, as the brief predicts: questions are not logged

`[measured]` No request log, no ledger write, no counter, no persisted question
text anywhere in the ask blueprint family. `grep` for logging around the
question in `ask_the_syndicate.py` returns nothing. So the real distribution of
question classes is **unknown**, and any claim about "what users ask" is
anecdote. This is why the regression set exists.

Per-response `usage` (`input_tokens`, `output_tokens`,
`cache_read_input_tokens`) *is* captured and returned — and, since nothing is
logged, never aggregated.

### The regression set — checked in and runnable

`scripts/ask_syndicate_regression.py`. 52 cases across 7 classes and 8 sports,
including the deliberately hard ones the brief asks for: ambiguous club names,
games that do not exist, three-way markets, and questions the data genuinely
cannot answer.

Design decisions worth knowing before trusting its output:

- **Expected numbers are fetched, not hardcoded.** `_load_truth()` pulls
  `/api/board/layer2-shortlist` and `/api/portfolio/summary` once per run. A
  baked-in expected value would rot with the slate and then fail for the wrong
  reason — and fetching makes every numeric check a same-instant A/B between
  chat and the board.
- **Refusal is scored as substance, not wording.** `_looks_like_refusal` requires
  the answer to be content-free; producing a ranked list while hedging is scored
  as overreach, not as a partial pass.
- **The scorer reads both answer shapes** (`briefing` and `structured_response`),
  so it will not silently score the LLM path as empty once the key is set.

```bash
py -3 scripts/ask_syndicate_regression.py --out reports/ask_regression/latest.json
```

### Baseline `[measured 2026-08-14]`

**20 / 52 passed. `answer_source: snapshot` on 52/52.**

| class | passed | note |
|---|---|---|
| advice | 4/5 | fails only on certainty language |
| explain | 4/6 | |
| ranking | 4/10 | the class users ask most |
| refusal | 3/8 | **5 of 8 answered a question it cannot answer** |
| lookup | 2/8 | 6 failures are sport routing |
| entity | 2/10 | 8 failures are sport routing |
| history | 1/5 | |

Most common findings across the run:

| count | finding |
|---|---|
| 63 | `model_probability` **exactly 50.0** — the fabricated coin-flip |
| 41 | no as-of stated anywhere in the answer |
| 34 | an `edge` shown with `market_probability: null` |
| 31 | a selection not present on the served board (1 distinct) |
| 8 | declined a question the data can answer |
| 8 | expected soccer, resolved no sport |
| 5 | should have declined and did not |
| 3 | `model_probability` degenerate (0.0 / 100.0) |

**The most-common class and the most-failing class are not the same list**, and
the gap is the priority order: `ranking` is both common and failing; `refusal`
fails hardest.

### The refusal failure, concretely

`market_summary` was the resolved intent on **40 of 52** questions — the
router's default for anything unmatched. So:

> **Q: "What is the capital of France?"**
> A: five betting opportunities, "Showing the top 5 opportunities on today's
> board. Best edge 4.9%."

Identical output for "What is the weather at the stadium right now?" and "What
is my account balance and betting history?". The router's own comment explains
why the default is `market_summary` — `bet_analysis` dead-ended on vague
questions and returned "No structured answer came back." That fix was right for
vague *betting* questions and turned every *out-of-scope* question into a
confident board dump. A user cannot distinguish the two modes, which is exactly
the failure the brief weights most.

---

## 4. Freshness

- **Snapshot age: 7,346 s (2h 02m) against a 60 s SLA**, self-labelled
  `freshness_status: "stale"`, `is_fresh: false`. `[measured]` Chat answers from
  this. The board does not.
- **Answers state no as-of.** 41 of 52 carried no timestamp of any kind. The
  `visuals.as_of` field exists but is only populated when `collect_focused_evidence`
  returns — which requires a sport branch to match (§2), so it is `None` for every
  soccer, ncaab and unrouted question. For a live-odds product this belongs in
  the response, not a footnote.
- **Response cache: 600 s TTL** (`SYNDICATE_ASK_CACHE_TTL_SECONDS`), keyed on
  question + payload + intent, **applied only when `answer_source == "llm"`**.
  Since the LLM never runs, the cache is currently inert — but the moment the API
  key is set it adds up to 10 minutes on top of an already-2-hour-stale snapshot.
- **The publish-guard question**: no. `#394`'s checksum guard skips *re-uploading
  an unchanged artifact*; chat reads the persisted snapshot through
  `read_latest_intelligence_state`, not through the publish path, and a skipped
  upload leaves the on-disk artifact in place. A correctly-skipped publish cannot
  be read as staleness here. The staleness measured above has a different cause —
  snapshot rebuild cadence, not transport.

---

## 5. Confidence and framing

- **Chat has confidence values and uses them as decoration.** Served rows carry
  `confidence: 70.0 / 50.0 / 85.0 / 100.0` alongside `edge`. Nothing in the
  answer distinguishes a 50 from a 100 in language, and the summary sentence
  ("Best edge 4.9%") reports only the point estimate.
- **`market_probability: null` and `EV: null` on every served row** `[measured]`,
  while `edge` is populated. The user is shown a number they cannot check
  against anything.
- **The threshold question, answered: chat surfaces edges the UI's own gate
  would not.** The board's published floor is a per-family, hold-calibrated value
  floor (`min_value_pct`, negative). Chat applies **no threshold at all** — it
  emits the top 5 of whatever the snapshot holds. And per
  `audit_2026-08-14_models.md`, the recommendation engine's own gate is
  `edge > 0` with every adaptive term inert (0 settled records), priced against a
  **vigged** book price. So the answer to "should chat surface an edge only where
  the UI's threshold would" is: **there is no meaningful threshold on either
  side to align to yet.**
- **The 50.0 problem is a platform-wide default, not a chat bug.** 63 sightings
  here; the model audit found `_fair_probability` falling through to 0.5; the UI
  audit found `away_pct`/`home_pct` defaulting to 50.0. Same fabricated
  coin-flip, three surfaces.
- **Certainty language**: 1 of 52 (E04, "Give me a lock for tonight" — the answer
  echoed "lock"). The system prompt's rule 7 forbids fabrication and rules 5–6
  require surfacing uncertainty; since the prompt never runs, none of that is in
  force today. The deterministic path has **no hedging rules of its own**.
- **Responsible-gambling framing**: holds under the adversarial phrasings tested
  (E01 "how much should I put on this", E03 "I'm down $2000, what gets it back")
  — but it holds because the generic board summary happens to contain
  bankroll/risk vocabulary, not because anything checks. That is luck, not a
  guardrail.
- **Jurisdiction**: not considered anywhere. The endpoint is **public and
  unauthenticated** (`/api/syndicate/query`, no token) and returns identical
  content regardless of origin.

---

## 6. Cost and latency `[measured, n=52]`

- **Latency: p50 1.4 s, p90 6.9 s, max 10.9 s.** Zero transport errors.
- **LLM token cost today: $0** — the LLM never runs. What the numbers would be:
  each call sends ≤24,000 chars of evidence (~6k tokens) + a ~600-token system
  prompt to `claude-haiku-4-5`, capped at 2,048 output tokens.
- **The rate limiter is real and tight**: `SYNDICATE_ASK_LLM_MAX_CALLS = 30` per
  `SYNDICATE_ASK_LLM_WINDOW_SECONDS = 600` — **per process**, and web runs
  `WEB_CONCURRENCY = 2`. At 10× volume most traffic silently degrades to the
  snapshot path, which is indistinguishable in the response from the current
  state. **This baseline run alone (52 calls in ~4 minutes) would have exceeded
  the cap.**
- **Caching**: 600 s, exact-match on question + payload + intent, LLM answers
  only. No normalisation, so "best bets tonight" and "Best bets tonight?" are
  separate entries.

---

## 7. Expansion — ranked against measured failures, not ideas

Against the baseline, the frequent-and-failing classes are `ranking` (4/10) and
`refusal` (3/8), then `lookup`/`entity` (both routing).

**Answerable purely by exposing a tool over data that already exists** — no new
data, no new pipeline:

| capability | data that already exists |
|---|---|
| filter/rank the whole candidate pool | `/api/board/layer2-shortlist` — 14,216 considered, 200 published |
| "which totals moved most since open" | `build_market_history_view` — opening/latest/closing, movement_delta, velocity |
| league scoping for soccer | rows already carry `league` (`#330`) |
| per-sport slate listing | `active_sports` + `per_sport` on the board payload |
| model skill for a market | `model_skill` on every projection (`#425`) |
| board freshness | `freshness.age_seconds`, already computed and already read |

**Needs new data**: CLV per sport/market (blocked on `audit_2026-08-14_models.md`
fix #1–2); historical prop accuracy beyond MLB hitters.

**Prefer widening the tool surface over widening the prompt** — and note that
today there is *no* tool surface at all. A capability added by describing it in
the system prompt would have no guardrail behind it and, right now, would not
even execute.

---

## 8. Ranked fix list

The grounding verdict is negative for the aggregation class, so it goes at the
top, as the brief specifies. Each item is a separate lane.

1. ~~Decide whether the LLM path is meant to be on.~~ **DECIDED 2026-08-14: OFF,
   deliberately.** What survives of this item is the *visibility* half, and it
   still matters: the response should say `answer_source: "snapshot"` is the
   designed mode rather than leaving a reader to infer a failure, and the dead
   LLM scaffolding should be removed so nobody re-diagnoses this in three
   months. See `plan_2026-08-14_ask_without_llm.md`. **No longer blocks
   anything.**
2. **Serve chat from the same board payload the cards read**, or stamp the
   snapshot's `age_seconds` into every answer. Today chat says 5.02% while the
   board says 13.59%, from a snapshot the platform itself labels stale at 122×
   its SLA.
3. **Stop answering out-of-scope questions with a board dump.** `market_summary`
   is the default for 40 of 52 questions including "What is the capital of
   France?". Gate the default on the question containing *any* betting-domain
   token; otherwise decline. 5 of 8 refusal cases fixed by one condition.
4. **Add `soccer` and `ncaab` to `_SPORT_HINTS` and `_fetchers_for_sport`.**
   Soccer is 100 of 200 published board rows and is currently unnameable. This
   is the single largest coverage gap.
5. **Fix the routing collisions**: give `wnba` its own entry (it is currently a
   keyword inside `nba`); score `_SPORT_HINTS` matches instead of returning on
   the first tuple, so `goals`/`shots`/`assists` stop being decided by list
   order; make `build_evidence_pack`'s sport filter an exact match, not a
   substring; and **emit a reason when the filter matches nothing** instead of
   silently returning every sport.
6. **Return `routed_sport` in the payload.** It is `None` on 52/52 today, so
   neither a user nor this regression harness can see what the router assumed.
7. **Expose an aggregation tool over the full candidate pool** rather than a
   12-row prefix — filter by sport/market/edge/league and return counts. This is
   the structural fix for the `ranking` class and needs no new data.
8. **Log questions.** Intent, routed sport, answer_source, latency, usage,
   row count. Without it the taxonomy stays anecdote and item 1's degrade stays
   invisible. Lean records only — `#374` and the 367 MB evaluation chunk are the
   cautionary precedents.
9. **Put an as-of in every answer**, sourced from `freshness.computed_at`, not
   only from `visuals.as_of` (which is `None` for every unrouted question).
10. **Stop emitting `model_probability: 50.0` as a value.** Same fabricated
    coin-flip as the model and UI audits. Absent must render as absent.
11. **Give the deterministic path its own hedging and refusal rules.** Every
    guardrail today lives in a system prompt that does not execute; the
    responsible-gambling framing that passed did so by accident of vocabulary.
12. **Raise or share the LLM rate limit before enabling it.** 30 calls / 600 s
    per process × 2 workers; this audit's own 52-call baseline would have
    exceeded it, and the excess degrades invisibly.

---

## Open / unverified

- The real question distribution is **unknown** (item 8). The regression set is
  a proxy built from the brief's taxonomy, not from traffic.
- `_build_artifact_response` returned `None` on every case tested; its behaviour
  when it *does* return is untested here and it short-circuits before both
  `collect_focused_evidence` and `generate_briefing`.
- The LLM path's answer quality is **unmeasured** — it has never run. The
  baseline scores the snapshot path only. Re-run the harness after item 1 to get
  the first real comparison.
- NBA, NHL and NCAAB were out of season; their matrix rows reflect routing
  behaviour, not answer quality on a live slate.
