# Ask the Syndicate — answer substance — 2026-08-16

Supersedes parts of `plan_2026-08-14_ask_the_syndicate.md` and
`plan_2026-08-14_ask_without_llm.md`. Written from four user reports against the
live inline quick-ask panel, then measured against production
(`syndicate-an21.onrender.com`) 2026-08-16 ~17:2xZ. Lane: `ask-answer-substance`.

> **The standing decision holds: the LLM is not meant to be on.** Nothing here
> reverses that, and nothing here needs it. Every fix below is a field the
> deterministic path already has and does not publish.

---

## The correction the two prior plans need

Both prior plans measure the deterministic path by **whether evidence was
produced**. `plan_2026-08-14_ask_without_llm.md` opens with a table scoring each
sport on "questions producing evidence / tables / charts", and its headline
reads:

> "MLB already proves the deterministic path can be genuinely good, and seven
> sports get almost none of it. The gap was never the LLM."

**That table is correct and the conclusion drawn from it is wrong, because it
measures production and the user experiences delivery.** Measured today on a
real MLB prop question ("Ryan Johnson over 2.5"), the served payload carries:

| what exists in the response | what the panel shows |
|---|---|
| 7 tables — *SmartSim game outlook*, *Starter sim projections* (Ryan Johnson ER mean **3.95**), *Last 5 starts*, *Opposing lineup Statcast approach*, *BvP vs today's lineup*, *simulated probabilities vs the lineup* | nothing |
| 3 charts — *Simulated total runs*, *Simulated strikeouts* (full distribution, 11 buckets), *Actual strikeouts, last 5 starts* | nothing |
| `top_candidate.sim_projection = 3.951`, `line = 2.5`, `side = "over"`, `market = "earned_runs"` | `Ryan Johnson` |
| `model_edge_pct = 14.01`, `quote.price = -101`, `quote.bookmaker = "draftkings"`, `books_quoting = 2`, `fair_price = -104` | `Edge 1.4%` |

`syndicate/static/shared/ask_bar.js:180-274` (`renderBriefingCompact`) never
reads `response.visuals` at all. That is deliberate — its comment says the panel
is "not a replacement for the standalone page's deep-dive view (tables/charts/
drivers/risks)". The decision was reasonable when the panel was a sidebar
afterthought. It is now the surface the user actually uses, and under it **MLB
scores 4/4 on the plan's metric while showing the user a name and one number.**

**So the plan's sport-coverage table is not wrong, it is not the whole
instrument.** Adding soccer and ncaab to the router (`ask-sport-coverage`, in
flight) makes five more sports score the way MLB scores. It does not make any of
them *answer better*, because MLB's own answer is thin at the point of delivery.
This plan is the missing half.

---

## The four reports, each measured

### 1 — A prop answer names neither the prop nor the side

**Confirmed.** `_bet_analysis_schema` (`ask_the_syndicate_adapter.py:301-323`)
publishes `selection = top.get("selection")`, which on a layer2-sourced
candidate is the bare `player_name`. The same dict it is reading carries
`market`, `line` and `side`.

Served: `"selection": "Ryan Johnson"`. Available on `explanation.top_candidate`:
`market: "earned_runs"`, `line: 2.5`, `side: "over"`.

The adapter **already has the function that does this job** —
`_board_row_selection` at `:496`, which renders `"Ryan Johnson over 2.5"`. It is
wired to `market_summary` only. `bet_analysis` never calls it.

### 2a — The briefing says "top 5" and renders 3

**Confirmed, and it is purely client-side.** The server returns exactly 5 and
the sentence is generated from the rows it returned
(`_board_summary_sentence:462`, `f"Showing the top {len(items)} …"`). Served
today: `"Showing the top 5 opportunities on today's board in MLB. Best edge
14.8%."` with `len(top_opportunities) == 5`.

`ask_bar.js:191` and `:237` both `.slice(0, 3)`.

**Why neither plan caught this:** `scripts/ask_syndicate_regression.py` scores
the JSON payload. It has no view of the panel. A truncation that only exists in
the renderer is invisible to the entire instrument both plans are built on — and
both plans end with "anything that does not move a class score is not done."
That rule, applied literally, would have scored this defect as nonexistent.

### 2b — The briefing does not say which way to take the bet

**Confirmed for game sides, already correct for props.** Served rows include
`"home -1.5 (Philadelphia Phillies @ Minnesota Twins)"`. `home` is a convention,
not a team; a reader has to know that home is the second name to place it. No
price and no book appear at all, so the row is not actionable even once decoded.

`_board_row_selection:512-515` renders `f"{side} {line} ({matchup})"`.

**This is not mine to re-derive.** `layer2_board._pick_label:1125` is the
reviewed owner of side→team, including the case that matters most — a lay market
is a bet *against* the named team and must say so. And `learnings.md:933`
(FORBIDDEN: never treat equality of a LABEL as identity of a BET) plus the
CLOSED `spread-line-sign-convention` lane are exactly about getting this wrong.
The fix is to **reuse that convention and pin it with a test**, not to write a
second one in the adapter.

### 3 — The logic is edge-only

**Confirmed, and worse than "edge-only": the one number it does publish is the
wrong quantity.**

`bet_analysis` reads `edge` from `adjusted_edge or edge or price_edge_pct`. On a
layer2 candidate `edge` is the **EV fraction**, not the model edge. The row also
carries `model_edge_pct`, which is what the board and the briefing use.

Measured on the same pick, same instant, same endpoint:

| surface | Ryan Johnson over 2.5 |
|---|---|
| briefing (`market_summary`) | **edge 14.01** (percent, from `model_edge_pct`) |
| per-pick (`bet_analysis`) | **edge 0.013913** (fraction, from `ev_pct/100`) → panel renders **1.4%** |

**Ask contradicts itself by a factor of ten on one pick, inside one feature.**
Two further field-selection misses on the same object:

- `market_probability: null` while `quote.fair_probability = 0.5095` is present.
  The harness already emits `edge_without_market_probability` as a *warning* for
  this — a defect its own instrument has been reporting to nobody.
- `EV: null` while `ev_pct = 1.3913` is present. It looks for
  `expected_value`/`ev_current`/`ev`; the field is called `ev_pct`.
- `confidence: 70.0` is `top["confidence"] = 0.7`, which is **`book_confidence`**
  — a price-reliability term — published under a name a reader will take as
  model confidence.

**A units defect in the published contract, worth fixing explicitly:** `edge` is
a **percent** on `market_summary` rows and a **fraction** on `bet_analysis` rows,
from the same endpoint. `ask_bar.js:260` multiplies by 100 for `bet_analysis` and
does not render edge for `market_summary`, so the panel is accidentally
consistent while the API is not. The regression harness guesses the scale from
the magnitude (`max(claimed) * 100 if max(claimed) < 1.5`), which cannot survive
a genuine sub-1.5% edge.

**What "good" looks like, per the user: the MLB game lens.** Its narrative is
built at `vendor/mlb_bettingv2/tools/web/flask_frontend.py:15232-15244`:

```python
f"The live total still leans {selected_side} because the projection sits at "
f"{float(projected_total):.2f} against {float(live_total_line):.1f}."
```

plus outs remaining, runs already scored, and whether both starters are still in.
It is **deterministic string assembly over fields the row already carries** — no
model, no LLM. Ask has every analogue on its own rows and generates no sentence
at all: `recommendation` is `null` on 5 of 5 briefing rows and on the per-pick
answer, because `_candidate_prose:108` looks for a `detail`/`writeup` field that
layer2 rows do not have. **Ask does not need a prose source; it needs a prose
generator, the same one the game lens already proves out.**

Fields available for it on every row, measured on the live shortlist (108 rows):

| field | coverage | use |
|---|---|---|
| `projection.projected` / `sim_projection` | 86/108 | "the sim projects 3.95 ER against a line of 2.5" |
| `projection.model_skill.{status,verdict}` | 88/108 | "this model is **unmeasured** — never backtested" vs "measured, biased high ~31%" |
| `projection.basis`, `.source` | ~all | `game_simulation` vs `hitter_threshold` — what produced it |
| `quote.{price,bookmaker,books_quoting,book_age_seconds}` | all | the bet you can actually place, and how stale |
| `game.{state,status_token,away_score,home_score}`, `is_live` | all (6 live now) | the game-situation half of the lens |
| `model_edge_pct` | 70/108 | the edge, correctly named |

**Do not use `score.sim_component`.** It is `0.0` on 108 of 108 served rows —
that is the open goal of lane `layer2-board-quality`, not a signal to publish.
`projection.projected` is the sim term that is actually populated.

**`model_skill` is the item with the most upside and the least code.** A user
asked to trust a number is entitled to know that `"status": "unmeasured"`,
`"verdict": "model never backtested — projection is unvalidated"` — which is what
88 of 108 rows say about themselves, and what no answer has ever said out loud.
It also discharges the one obligation the LLM decision created: rules 5–8 of the
dead system prompt (surface uncertainty, distinguish fact from projection, flag
staleness) had no home on the deterministic path. `model_skill` is the home.

### 4 — Reconciling with the prior plans

| prior item | status |
|---|---|
| K1 gate `market_summary` | shipped, unaffected |
| M1 board-candidates handler | shipped, and **half-credited**. It fixed the *pool* (chat and board read one source) and left the *substance* — its rows come back with `recommendation: null`, no price and no book |
| K9 / K2 / K11 / K3 / K4 / K5 / K6 | in flight under `ask-sport-coverage`, unaffected, **not overtaken** — but they widen coverage of an answer this plan is still repairing |
| K7 stop emitting `model_probability: 50.0` | unaffected, still cross-plan |
| K8 hedging + refusal rules on the deterministic path | **absorbed and made concrete.** `model_skill` is the mechanism K8 was written to need |
| L2 chat/board divergence | **re-opened in a new place.** M1 closed it for the briefing; `bet_analysis` still diverges from the board on the same pick, by units rather than by pool |
| "anything that does not move a class score is not done" | **retired as the sole exit rule** — see below |

---

## The predicate problem, stated plainly

`scripts/ask_syndicate_regression.py` **cannot measure any of the four reports.**
`_score` checks refusal, sport routing, hallucinated selections, certainty
language, fabricated 50/50s, board-table presence and edge-vs-board on ranking
cases. Nothing checks whether a selection names a market, a line or a side;
whether a price and a book are present; whether `edge` is the quantity it claims;
or whether any sim term appears. And it never renders the panel.

So both prior plans' exit rule would score this entire lane as **"not done"**
while every user-visible defect was fixed. Two consequences:

1. **The harness is not edited by this lane.** `ask-sport-coverage` is judged by
   it and editing it is marking someone else's exam. New assertions go in
   `tests/test_ask_answer_substance.py` against a captured production row.
2. **Non-regression on the harness is a floor, not the goal.** Target: no class
   regresses from 38/52. Expect new *warnings* (`selection_not_on_board` fires on
   any selection longer than a bare player name — `_score:405-414`); warnings do
   not fail (`result["passed"] = not result["failures"]`).

**Item for whoever owns the harness next:** promote
`edge_without_market_probability` from warning to failure, and add a
selection-shape check. It has been correctly reporting a real defect into a
warnings list nobody read.

---

## Order of work

Files: `ask_the_syndicate_adapter.py` and `ask_bar.js` only. Both unclaimed.
`ask_the_syndicate_data.py` / `_router.py` / `_the_syndicate.py` stay untouched —
held by `ask-sport-coverage`, and this lane needs nothing new from them.

1. **`bet_analysis` reads the fields it already holds.** `selection` via
   `_board_row_selection`; `edge` from `model_edge_pct`; `market_probability`
   from `quote.fair_probability`; `EV` from `ev_pct`; drop `book_confidence`
   from the `confidence` slot or rename it honestly. Add `line`, `side`,
   `market`, `price`, `bookmaker`, `books_quoting` as first-class fields rather
   than leaving them buried in `explanation.top_candidate`.
   *Closes report 1 and the ten-fold self-contradiction in report 3.*
2. **Fix the `edge` units split.** `bet_analysis` emits `edge_pct` alongside
   `edge`, both percent, matching what `_board_top_opportunities` already does.
   Update `ask_bar.js:260` in the same change — it currently multiplies by 100.
   *One field, one unit, across both schemas.*
3. **A deterministic reason generator**, modelled on `_game_lens_total_market`:
   projection vs line, side, price and book, `model_skill.status`, and the
   game-situation clause when `is_live`. Fills `recommendation` for rows that
   have no `detail` prose — which is all layer2 rows.
   *Closes report 3 and gives K8 a home.*
4. **Name the team on game sides.** Reuse `layer2_board._pick_label`'s
   convention, including its lay-market rule, and pin it with a test so the two
   cannot drift.
   *Closes report 2b. Respects `learnings.md:933`.*
5. **Panel renders what the answer contains.** Drop the `slice(0, 3)` to match
   the sentence; render the new fields; surface the top sim table and the
   distribution chart, or a link to them, instead of discarding `visuals`
   entirely.
   *Closes report 2a and delivers what report 3 asked for.*

Exit: the assertions in the lane entry, the new test file, harness
non-regression against 38/52, and the panel re-read in a browser — because items
2a and 5 are client-side and no server test can see them.

## Status, 2026-08-16 ~18:0xZ — steps 1–5 built, verified locally, NOT deployed

All five ordered steps are implemented in `ask_the_syndicate_adapter.py` and
`ask_bar.js`, with `tests/test_ask_answer_substance.py` (31 tests) built on
verbatim production rows. 189 tests green across all four ask suites. Verified
by replaying the captured production payloads through the new code and by
seeding the real panel in a browser and reading the rendered DOM.

The 22 `test_layer2_*` failures in the same run are **pre-existing and belong to
`layer2-board-quality`** — confirmed by stashing this lane's two files and
re-running: they fail identically at HEAD.

**Not done, and it is the exit criterion:** the regression harness re-measure.
It reads a live deployment; local has no board and production runs the old code,
so running it now would measure the wrong thing either way. Deferred to a
`/preflight`-gated deploy.

**New defect this work exposed, handed to `ask-sport-coverage`:** the M1
evidence table still labels a game side `home -1.5 (Philadelphia Phillies @
Minnesota Twins)` while the headline above it in the same answer now reads
`Minnesota Twins -1.5`. `_board_row_label` in `ask_the_syndicate_data.py` is
that lane's file. Two labels for one row in one answer is worse than two wrong
ones, so this should not sit long.

## Carried open

- **`score.sim_component` is 0.0 on 108/108 rows.** Owned by
  `layer2-board-quality`. When it becomes non-zero it is a better sim term than
  `projection.projected` and step 3 should read it.
- **`movement_not_tracked: true`** on the pick measured, with an empty
  `movement.history`. M2 (market history in the answer) stays blocked on line
  movement actually being tracked for these rows.
- **22 of 108 rows carry no `projection.projected`, 38 no `model_edge_pct`.**
  Step 3 must degrade to the quote-and-freshness clause rather than assert a sim
  term it does not have. Absent renders as absent.
- **A team side's projection is still unpublishable.** `projection.projected` on
  a spreads row is a run margin (`basis: "full/run_margin_dist"`) whose sign
  convention against the handicap is pinned nowhere in this payload, so
  `_sim_terms` drops it and the reason generator writes no projection clause for
  those rows. That is the safe answer, not the right one — pin the convention
  (per sport, per market family, with a test, per `learnings.md:933`) and a
  whole class of game-line answers gains its sim term.
- **`model_skill` does not reach the per-pick path.** The `bet_analysis`
  candidate is a FLATTER shape with no `projection` dict, so
  `model_skill_status` comes back `null` there while the briefing rows carry it.
  The per-pick answer is therefore the one place that does NOT warn that the
  model is unvalidated. The flattening happens in `ask_the_syndicate_data.py`
  (`ask-sport-coverage`'s file), so this is a handoff, not a gap in the adapter.
