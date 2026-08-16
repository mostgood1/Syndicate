# Ask the Syndicate without the LLM — what is capturable

> **AMENDED 2026-08-16 — see `.syndicate/plan_2026-08-16_ask_answer_substance.md`.**
> The headline table below scores each sport on **evidence produced**. Measured
> 2026-08-16, MLB scores 4/4 on that metric and the panel the user actually
> reads shows a bare player name and one number: `ask_bar.js` never reads
> `response.visuals`, so 7 tables and 3 charts of real sim output are discarded
> at render. **The table is not wrong; it is not the whole instrument.** Items
> 1–11 below all stand. What changes is the conclusion that MLB "proves the
> deterministic path can be genuinely good" — it proves the *evidence* is good,
> not the answer.

> **Standing decision, 2026-08-14, from the user: the LLM is not meant to be on.**
> `ANTHROPIC_API_KEY` stays absent. The deterministic snapshot path is the
> product, not a degrade.
>
> Follow-on to `.syndicate/audit_2026-08-14_ask_the_syndicate.md`. Read-only
> pass; no code changed. Measurements are against production
> (`syndicate-an21.onrender.com`, web `f9aa2399`) 2026-08-14 13:45–14:05 CDT.

---

## The headline

**MLB already proves the deterministic path can be genuinely good, and seven
sports get almost none of it.** The gap was never the LLM.

Measured — same questions, with and without an explicit `sport` in context, so
"the fetchers had nothing" and "the router never reached them" stay separable:

| sport | questions producing evidence | tables | charts | as_of |
|---|---|---|---|---|
| **mlb** | **4 / 4** | **14** | **4** | `2026-08-14` |
| ncaaf | 2 / 2 | 4 | 0 | `2026 week 1` |
| nba | 1 / 1 | 1 | 1 | `2026-04-30` (out of season, correct) |
| **nfl** | **0 / 2** | 0 | 0 | — |
| **wnba** | **0 / 2** | 0 | 0 | — |
| **soccer** | **0 / 3** | 0 | 0 | — |
| **nhl** | **0 / 1** | 0 | 0 | — |
| **ncaab** | **0 / 1** | 0 | 0 | — |

`collect_focused_evidence` builds real tables and charts and the route's own
comment says they are "deterministic and render even when the LLM path is
unavailable". On MLB that is 6 tables and a chart for a single player question —
a good answer, today, with no model in the loop. On five sports it is nothing,
**including with an explicit sport context**, so this is not only a routing
problem.

---

## Root causes, isolated per sport

Three distinct causes. They need three different fixes, and conflating them is
how this gets half-done.

**1 — No branch at all: `soccer`, `ncaab`.**
`_fetchers_for_sport` has no case; it falls to `return []`. Neither sport has a
`_SPORT_HINTS` entry either, so they cannot even be named. Soccer is **100 of
200 published board rows**. `[from-code + measured]`

**2 — Branch exists, entity matching too strict: `nfl`.**
Isolated in-process: `_nfl_teams_in_question` requires the **full** team name.

```
"Patriots vs Seahawks projection"              -> []
"What does the model project for the Patriots" -> []
"New England Patriots vs Seattle Seahawks"     -> ['New England Patriots', 'Seattle Seahawks']
```

`_nfl_matchup_evidence` returns `None` at `len(teams) < 2` before it ever opens
an artifact. Nobody types the full name. MLB's matcher handles "Cubs vs
Cardinals" fine — the difference is care, not data. `[measured, in-process]`

**3 — Branch exists, but only entity fetchers: `wnba`, `nhl`, `nba`.**
Both WNBA fetchers returned `None` for "What are the best WNBA points props?"
even with `context={"sport": "wnba"}` — they are player/matchup fetchers that
need a named entity, and a ranking question names none. MLB is the **only**
sport with a ranking-intent path (`_is_ranking_intent_question` →
`_mlb_top_candidates_evidence`), and that function is genuinely MLB-specific: it
requires `_detect_mlb_market()` and reads MLB artifact paths. `[measured]`

---

## The single highest-value fix, and it needs no new data

**A generic board-candidates fetcher, driven off `/api/board/layer2-shortlist`.**

That payload already carries, for every active sport, everything a ranking
answer needs — measured today: 200 rows across `mlb / nfl / soccer / wnba`, with
`sport`, `market`, `kind`, `player_name`, `home_team`, `away_team`, `line`,
`side`, `ev_pct`, `model_edge_pct`, `commence_time`, `league`, plus the whole
funnel (`opportunities_considered: 14,216`, `per_sport` availability counts).

Filtering and ranking a 200-row table is exactly what deterministic code is good
at and what an LLM over a 12-row prefix was always going to be bad at. One
fetcher, registered for **every** sport and for the no-sport case, closes the
`ranking` class — the most-asked and second-worst-scoring class in the baseline
(4/10) — for all four active sports at once.

It also fixes the divergence for free: chat and the cards would be reading the
same payload, so the 5.02%-vs-13.59% split cannot recur.

---

## What the decision changes about the fix list

Of the 12 items in the audit, **10 are unaffected** — they are deterministic-path
defects that have nothing to do with the LLM. Two change:

| # | item | status under "LLM off" |
|---|---|---|
| 1 | decide LLM on/off | **resolved** — off. Visibility half survives |
| 12 | raise the LLM rate limit | **dropped** — moot |
| 3 | stop answering out-of-scope with a board dump | **unchanged, now #1** |
| 11 | hedging + refusal rules on the deterministic path | **promoted** — every guardrail today lives in a system prompt that will never execute |

Nothing else moves. The one thing worth stating plainly: **the system prompt's
rules 5–8 (surface uncertainty, distinguish fact from projection, never fabricate
players or odds, flag staleness) are now permanently unenforced.** They were the
only place those rules existed. The deterministic path needs its own, and that is
a consequence of the decision rather than a pre-existing defect.

---

## Ranked plan — deterministic only

Each is a separate lane. Ordered by measured user-visible impact per unit of work.

1. **Generic board-candidates fetcher over the Layer 2 shortlist.** Closes the
   `ranking` class for all four active sports; removes the chat-vs-card
   divergence; needs no new data. Biggest single win.
2. **Gate the `market_summary` default.** `market_summary` is the resolved intent
   on **40 of 52** questions, including "What is the capital of France?" — which
   returns five betting opportunities. Require the question to contain a
   betting-domain token; otherwise decline. One condition fixes 5 of 8 refusal
   cases and is the difference between a tool that declines and a tool a user
   cannot trust.
3. **Add `soccer` and `ncaab` to `_SPORT_HINTS` and `_fetchers_for_sport`.**
   Soccer is half the published board and is currently unnameable.
4. **Nickname matching for NFL** (and audit the same function per sport).
   "Patriots" must resolve. Measured: this alone is why NFL produces zero
   evidence.
5. **Ranking fetchers for wnba / nhl / nba** — or, if fix 1 lands first, simply
   register the generic one and delete the need. Prefer that.
6. **Stamp `freshness.age_seconds` into every answer.** The snapshot chat serves
   was **7,346 s old against its own 60 s SLA**, self-labelled `stale`, and 41 of
   52 answers carried no as-of at all. On a live-odds product this belongs in the
   response.
7. **Fix the routing collisions** — `wnba` its own entry rather than a keyword
   inside `nba`; score `_SPORT_HINTS` matches instead of first-match-wins so
   `goals`/`shots`/`assists` stop being decided by list order; exact-match the
   sport filter in place of the substring test (`"nba" in "wnba"` is `True`);
   emit a reason when the filter matches nothing instead of silently returning
   every sport.
8. **Return `routed_sport` in the payload.** `None` on 52/52 today — neither a
   user nor the regression harness can see what the router assumed.
9. **Hedging and refusal rules on the deterministic path.** The responsible-
   gambling framing that passed the adversarial cases passed by accident of
   vocabulary in a generic board summary, not because anything checks.
10. **Log questions** — intent, routed sport, answer_source, latency, row count.
    Lean records only; `#374` and the 367 MB evaluation chunk are the cautionary
    precedents. Without this the taxonomy stays anecdote.
11. **Stop emitting `model_probability: 50.0`** (63 sightings in the baseline).
    Same fabricated coin-flip as the model and UI audits. Absent must render as
    absent.

---

## Dead code the decision creates

Per the standing rule about removing confirmed dead code rather than only
documenting it — but **not in this pass**, because two of these have a
production blast radius that needs its own decision:

**Safe to delete (code only, no deploy semantics):**

- `syndicate/blueprints/ask_the_syndicate_engine.py` — all 335 lines: the system
  prompt, `BRIEFING_SCHEMA`, `build_evidence_pack`, `_slim_candidate`,
  `generate_briefing`, the rate limiter, the client singleton.
- `generate_briefing` / `_apply_briefing_to_response` call sites in
  `ask_the_syndicate.py`.
- The 600 s response cache (`_query_cache_key`, `_read_cached_response`,
  `_store_cached_response`) — it caches **only** `answer_source == "llm"` and is
  therefore permanently inert.
- The `briefing` branch of `scripts/ask_syndicate_regression.py`'s
  `_answer_text` — though I would **keep** it: it costs nothing and makes the
  harness correct if this decision is ever revisited.

**Needs a separate decision — pushing these is a production change:**

- `anthropic>=0.116.0` in `requirements.txt`. Removing it shrinks the image;
  confirm nothing else imports it first.
- `ANTHROPIC_API_KEY`, `SYNDICATE_ASK_MODEL`, `SYNDICATE_ASK_LLM_MAX_CALLS`,
  `SYNDICATE_ASK_LLM_WINDOW_SECONDS` in `render.yaml`. **Editing `render.yaml`
  triggers `blueprint_sync`, which bypasses `autoDeploy: no` and rewrites the
  WHOLE env block on two live services.** Per CLAUDE.md this needs an explicit
  decision and a diff against each service's live `/v1/services/<id>/env-vars`
  first. Four keys are not worth a sync on their own — fold them into the next
  `render.yaml` change that has to happen anyway.

Whatever is deleted, **leave a comment saying the LLM path was removed by
decision on 2026-08-14**, not by accident. The reason this audit took as long as
it did is that a silent degrade is indistinguishable from a bug.

---

## Re-baselining

`scripts/ask_syndicate_regression.py` is unchanged and still the instrument.
Current baseline **20/52**, `answer_source: snapshot` 52/52 — which is now the
*expected* source, not a finding. Re-run after each lane:

```bash
py -3 scripts/ask_syndicate_regression.py --out reports/ask_regression/latest.json
```

Expected movement if the plan is followed in order: fixes 1–2 should take
`ranking` from 4/10 and `refusal` from 3/8 toward passing; fixes 3–5 should take
`lookup` (2/8) and `entity` (2/10). Anything that does not move a class score is
not done, whatever the diff looks like.
