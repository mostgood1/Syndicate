# Model audit → lane plan — 2026-08-14

Derived from `.syndicate/audit_2026-08-14_models.md`. Findings scoped to web
`f9aa2399`; local HEAD `0a18d901` had diverged at audit time. Re-read deployed
SHA per service before starting any lane.

## USER DECISIONS — 2026-08-14 ~21:5x CDT (02:5xZ)

Both were blocking a lane. Recorded here because they are product decisions, not
engineering ones, and the next session must not re-take them.

**1. CLV opening capture → (a).** Record a compact opening snapshot going
forward: one small JSONL per date, first-sighting-only per `market_id` (sport,
market, side, price, bookmaker, books_quoting, fair_prob, model_prob,
captured_at). Bounded by distinct market_ids/day (~3.4k for MLB), so kilobytes.
**(b) is REJECTED** — do not raise the 256 MB `SKIP_OVERSIZED_LEDGER_CHUNK`
ceiling to recover 08-05/08-06. That guard exists for OOM reasons on the 4 GB
worker, and `#435` has refresh-worker being OOM-killed every 16–22 minutes.
Consequence to state plainly wherever Lane B's status is read: **the first real
CLV number is ~24h out, not today.** Per program Tier 1, stamp fetch cadence /
quote age on every record alongside B2's pricing version.

**2. Soccer shortlist → BUILD THE SOCCER MODEL.** Not "publish with the EV
hidden", not "accept ~0 rows". So:
- **A3's uninformative-EV rule stays as it is — do not weaken it.** It keys on
  `fair_method == "book_margin_model"` and therefore **self-heals**: once soccer
  has two-sided quotes and a real model the fair becomes `consensus`, the rule
  stops firing, and rows return with a real EV. No code change.
- **The ~0-row soccer state is the accepted INTERIM, not the destination.** Do
  not let A3's closure be read later as "soccer is meant to be empty".
- Opened as its own lane, `soccer-model-coverage`. Its first task is **not**
  raising coverage: it is settling the 250x endpoint disagreement this plan's
  Lane A already recorded (`layer1` 29.6% vs `layer2-shortlist` 0.1%,
  `rows_with_model_edge: 0`, `unmatched_match_rows: 8,393` against
  `matches_in_source: 4`). If the defect is the layer2 join rather than
  projection coverage, raising coverage fixes nothing.
- This makes **"soccer pregame first" in the archive-replay order load-bearing
  for another session.** If you change that ordering, say so in the lane.

## Ordering principle

The audit ranks CLV first because it unblocks every other question. That is
right as an epistemics argument and wrong as a schedule. Two reasons to run A
and B in parallel instead of in series:

- Lane A's defects have a **known sign**. They do not need a measurement to
  justify, and they are shipping to users every day the lane is not done.
- If CLV starts before A lands, the first weeks measure a lane already known to
  be broken, and every number gets re-taken afterward.

So: A and B start together, B carries a version flag so the fix boundary stays
visible in the data, C starts now for lead-time reasons only, D is filler.

---

## Lane A — recommendation lane correctness

**Goal:** stop publishing rows that are wrong for reasons already established.

**Why now:** the audit's fixes 3 and 4 plus the inert gate are not three
independent bugs. Composed, they are a longshot selector. `_fair_probability`
falls back to 0.5; `_repriced_probabilities` compares it to a raw vigged price;
the threshold is `edge > 0`. A 0.5 default against a +300 side manufactures
roughly a 25-point edge; against a −200 favourite it manufactures almost none.
The fabricated edge is therefore **largest exactly where there is no model** —
143 of 200 published rows, including all 90 soccer rows.

### A0 — confirm or kill the adverse-selection theory (do this first, ~30 min)

Pull the price distribution of the 143 model-free published rows against the 57
with `model_edge_pct`. If the model-free set skews plus-money, the shortlist is
not merely optimistic, it is inverted, and this lane is urgent rather than
merely correct. Record the result either way — it changes the severity, not the
work.

### A1 — exclude, don't invent

`recommendation_engine._fair_probability`: the fallback chain
`fair_probability → model_probability → confidence → score/100 → 0.5` ends in
two errors. Drop the `0.5` terminal and drop `confidence` (a scoring artefact,
not P(outcome)). A candidate with no model probability is **excluded**, not
priced as a coin flip.

### A2 — price against no-vig fair

`_repriced_probabilities` calls `_parse_american_odds(current_odds)` — the raw
vigged price. `#238` already fixed this in `prop_projections`,
`nfl_game_projections`, `soccer_projections`, `quote_enrichment`, all of which
label output `edge_priced_against: "no_vig_fair"`. Apply the same treatment and
the same label here. Median hold 6.25% → edges currently overstated by ~3.1
points against a 0.0 threshold.

### A3 — resolve the negative-edge rows

31 of 57 model comparisons are negative: the board publishes rows its own model
disagrees with. Two defensible options, pick one:

- exclude them from the shortlist, or
- keep them but stop rendering `model_edge_pct` on them

Publishing the row *and* showing the negative model edge is the one combination
that cannot be explained to a user.

### A4 — make the gate read skill

`filter_candidates` and `layer2_board` do not read the projection layer's
`model_skill` declaration. Wire it. Note the gate's adaptive terms stay inert
until Lane B produces settled/CLV history — that is expected, not a blocker.
This step is about the shortlist knowing what the projection layer already
knows.

**Exit criteria**

- No published row derives its fair probability from the `0.5` terminal or from
  `confidence`
- Every recommendation-lane edge is computed against no-vig fair and labelled
- Zero published rows carry a negative `model_edge_pct` (or the field is hidden
  on them)
- A0 result recorded in `.syndicate/`

**Dependencies:** none. Everything is in one module family.

---

## Lane B — start the CLV clock

**Goal:** a non-zero denominator, per sport and market, without waiting on
settlement.

### B1 — settlement-free CLV job

Join the recommendation's own `quote` (opening) to `market_state`'s stamped
`closing_price`, keyed by market id. `odds_refresh_tracking` already stamps the
close at the real pregame→live transition. No dependency on grading, outcomes,
`settle_result`, or the 367 MB chunk path.

Keep `evaluation_settlement`'s existing guard: prefer the stamped close only
when `history_points > 0`, so `build_market_history_view`'s no-history fallback
cannot relabel an opening price as a close and produce a fake zero.

### B2 — version-stamp every record

**Not in the audit; add it.** Stamp each CLV record with the deployed SHA or a
simple `pricing_version` flag. Lane A will land mid-window, and without the
stamp the fix boundary is invisible — you would be averaging pre- and post-fix
behaviour and reading the mean as a result.

### B3 — unify devigging

Two orderings are live: `opportunity_signals`' per-book devig → median, and
`book_grid`'s mean-of-implied → devig. The first has the better documented
argument (aggregating raw prices "silently launders a line-shopping edge into
the fair price"). Collapse to one function.

This belongs in Lane B rather than later: CLV *can* be captured without it, but
cross-sport comparison is uninterpretable while two orderings are unevenly
distributed across producers, and comparison is the entire point of the
measurement.

While here: `power` devig is implemented, documented as better for props, and
called by nothing. Either adopt it at prop call sites or record why not.

**Exit criteria**

- `clv_pct` populated for a non-zero count per sport × market, visible in ops
- Every record carries a pricing version
- One devig function, one central statistic, all call sites converted

**Dependencies:** none on Lane A. B2 is what keeps them independent.

---

## Lane C — sharp reference price — **CLOSED 2026-08-15. WE ALREADY HAVE ONE.**

**No sourcing work is needed. The audit's premise was stale, not wrong-at-the-time.**

The audit recorded "no Pinnacle, Circa or exchange in the feed" and this plan
promoted it to a lane on the reasoning that beating a consensus of eleven soft
books is a materially lower bar than beating a sharp close — and could read
positive where no exploitable edge exists. **That reasoning stands. The premise
does not.** `[measured 08-15 from data/mlb_source/tracking/book_quotes/]`

| dates | distinct books | pinnacle rows | shard size |
|---|---|---|---|
| 07-28 .. 08-05 | **11** | **0** | ~13 MB/day |
| 08-09 | **37** | **2,604** | **217 MB/day** |

The feed widened between 08-05 and 08-09 — almost certainly the lost-books
capture fix — and nobody re-read the caveat afterwards. Present now:
`pinnacle`, `betfair_ex_eu`, `matchbook`, `novig`, `prophetx`, plus `kalshi` /
`polymarket` as prediction markets.

- **MLB GAME LINES: 102 of 102 markets carry a sharp quote = 100%.**
- **PROPS: 0%.**

**What this changes, and it is the most consequential correction in this plan:**

- **Lane B can take game-line CLV against a genuine sharp close.** The standing
  caveat — that a positive number might endorse a losing strategy — no longer
  applies to game lines. This is the strongest evaluation position the platform
  has ever had.
- **Prop CLV remains a soft-consensus measurement and MUST be labelled as
  such.** Do not let one `clv_pct` field mix the two; a sharp-referenced number
  and a soft-referenced one are not the same statistic and averaging them
  produces something with no interpretation at all.
- **It reinforces the "do not thin odds capture" position.** The 13 MB → 217 MB
  jump is what buying the sharp reference cost. Narrowing the book set to
  reclaim bytes would delete it — and price shopping was independently measured
  at **+2.79 ROI points**. The answer to the bytes is the storage-format work
  (delta/columnar), which preserves every movement.

**Caveats, stated rather than buried:** read from the git-tracked mirror, which
is lossy, and only ONE post-widening date exists locally (08-09). **Confirm
against production before publishing a sharp-referenced CLV number**, and
re-read whether the 37-book set is still current — this lane exists because a
book-set fact went stale once already.

---

## Lane D — hygiene

Small, independent, no sequencing constraints.

- **D1.** Mark `data/soccer_source/*/validation/*_backtest_*.csv` as not
  citable. `_load_team_ratings` computes one rating set from the full season and
  applies it to matches inside that season, so a Sept 2025 match is predicted
  using xG through May 2026. Production is unaffected — `build_soccer_artifacts`
  predicts forward — but the validation numbers are optimistic by an unmeasured
  amount.
- **D2.** Give `compute_team_ratings` a required as-of date; make callers pass
  the match date. Same change fixes `build_usage_profiles` in the
  starter-awareness backtest.
- **D3.** Deploy `mlb_prop_calibration` (`aac18260`). The only measured skill
  numbers in existence are not being served, so every MLB prop row still reads
  `unmeasured`.
- **D4.** Split the MLB prop de-bias fit from its scoring window (fit on dates
  1–7, score on 8–14). Half-hour change; makes the published verdict
  out-of-sample.
- **D5.** Add deployed-SHA-per-service output to `/preflight`. Third time deploy
  drift has affected this project; the audit itself had to caveat its
  commit-scoped claims.

---

## Parallel infra — storage format, not volume

Odds capture is 65.7% of platform bytes and ~97% MLB; one day of
`mlb_source/tracking/book_quotes` is 329.5 MB. It is also the **only** record of
line movement, which `build_market_history_view`, the steam detector,
`movement_velocity`, and Lane B all read.

The apparent tradeoff between cutting bytes and keeping movement history is
mostly false. Full-state JSONL snapshots at 60s intervals re-record quotes that
did not change. Delta encoding, dropping unchanged book rows, or columnar
storage cuts this by a large multiple while preserving every movement.

Safe to run alongside Lane B because it changes representation, not capture.

---

## Policy decisions

**Freeze breadth.** 69 sport × market pairs ship predictions; 2 have a backtest.
No new pair ships until it has archive-replay coverage. Without the freeze the
ratio worsens while it is being fixed.

**Decide what the product is.** With 143 of 200 rows carrying no model, Syndicate
is currently a market-EV screener presented as a model-driven pick service. Both
are legitimate products; devigged consensus is an honest and useful projection.
What does not hold is the present state, where a user cannot tell which row is
which. The projection layer already treats `unmeasured` as first-class and does
this well — the gap is that the shortlist does not read that declaration (Lane
A4).

**Extend archive-replay, in board-presence order.** Read the published artifact
for date D, join to the outcome — PIT-safe by construction and portable. Order:
soccer pregame (90 of 200 rows, 0% model comparison) → WNBA props → MLB pitcher
props → NHL → NBA. Starts after A and B, not alongside.

---

## Explicitly not now

- **Cadence thinning.** Cadence is already sport-aware; it is set by liveness
  and cost, not line-movement speed. Measure movement speed per sport first, and
  measure CLV before that.
- **Any reduction in MLB odds capture.** 86% of bytes and the only sport with a
  measured model. Thinning before CLV exists destroys the evidence that would
  justify the thinning.
- **Turning on the settlement autorun.** `matched: 0` was measured independently
  of the flag; flipping it settles zero and spends memory.
- **Turning on the shadow candidate ledger.** Correct eventually — filter
  precision is structurally unmeasurable without it — but its records are only
  worth grading once Lane B exists.

---

## Carried open questions

- MLB sim **model-side** as-of-ness is UNKNOWN. The backtest is PIT-safe by
  replay, which says nothing about the model's own inputs.
- NBA / NHL / NCAAB feature point-in-time status UNKNOWN — no harness reaches
  them.
- NHL and soccer market anchoring make those engines' market-relative evaluation
  partly circular. Quantify before believing any CLV number for them.
- refresh-worker's deployed commit was not re-read; `mlb_prop_calibration`
  absence is confirmed for **web** only.
