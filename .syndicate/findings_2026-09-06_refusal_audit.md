# Every suppression on the board, and whether it has evidence behind it

`[2026-09-06, lane ncaaf-live-resim-wire — user: "we need to stop globally
throwing things out"]`

**THE HEADLINE CORRECTION, and it reframes the whole question.** The gates are
not blocking +EV betting, because **market-derived EV is already primary and
already ungated.** The board sorts on
`blended_score(ev_pct=market_EV, model_edge=capped_sim_term)`, and
`layer2_board.py:1138` states outright that `blended_score` **CAPS the model's
influence**. That is `[2026-08-31, user decision: "rank on edge, flip the
default"]` — EV first, sim as a bounded augment. Every gate audited below sits on
the MODEL term, i.e. on the augment half only.

So "stop throwing things out" and "rank on EV, augment with the sim" are already
the shipped architecture. What follows is what each remaining gate actually
costs.

---

## The market layer is further along than `plan_oddsjam_class_board.md` says

That plan (research 2026-08-06) recorded `sharp anchor: none captured` and
`de-vig / fair probability: no — does not exist anywhere in the codebase`.
**Both are now stale.**

| | plan said | actually now |
|---|---|---|
| sharp anchor | none captured | `pinnacle`, `novig`, `prophetx`, `kalshi`, `polymarket` all in `book_shortlist.DEFAULT_BOOKS` |
| de-vig | does not exist | `opportunity_signals` (`#238`) + `layer2_board._fair_by_side`, de-vig WITHIN a book then median ACROSS books (`#384`) |
| market EV published | — | `ev_vs_fair_pct`, served to the board's EV column (`intelligence.html:3009`) |
| books recorded | 11 | 36 in `book_prices`; the shortlist is a filter on SELECTION, never on FETCH |

Anyone planning from that doc will under-build. It needs a correction pass.

---

## The four kinds of refusal, ranked by how much evidence stands behind them

### 1. WELL-EVIDENCED — leave shut

**`live_edge_policy` (`#340`)** — a PREGAME projection may not be priced against
a live market. Measured: an event with commence 16:07 carried quotes at 17:35
(away −500) while the sim still said 0.495, producing **a +23-point "edge" on a
coin-flip game**; game-market edges spread **−55 to +54**. And it RANKS, so it
does not merely display wrong, it sorts to the top.

**The asymmetry that matters:** the fix for this suppression is never to relax
it — it is to make the projection LIVE-AWARE, which is exactly what the NCAAF
live re-sim does. Opening the gate and fixing the model are opposite moves.

**NCAAF margins** — `NCAAF_MEASURED_SKILL`, 2,233 games, clean out-of-sample
(2023 SP+ → 2024): model MAE 15.775 vs market 12.212, **loses by 3.563 points at
t = 17.20**. `market_fair_prob_over` is written only in the totals branch, never
for h2h, so every NCAAF live h2h row refuses `no_two_sided_market_price`. That
refusal is correct. `[user decision 2026-09-06: keep the suppression]`

### 2. THE INVERSE PROBLEM — a sport gated too LITTLE

**NFL regular season has no skill gate at all**, and it is the one place tonight's
evidence says a gate is now owed.

`nfl_preseason_calibration.skill_note` returns **None** unless the profile is
`nfl_preseason_v1`, so the 146-game preseason measurement (margins correlation
**−0.047**, "moneyline probabilities are uninformative") never touches a
regular-season row. Those rows are stamped `unmeasured`, which was the honest
answer under `#425` — **and stopped being true on 2026-09-06.**

Measured this session, walk-forward, 816 games, train 2023-24 / test 2025 (272
test games): **test MAE 10.495 vs market 9.722, t = +3.34**, model closer on
118/272 (43.4%). NFL regular-season margins are now measured, they lose to the
closing line, and nothing gates them. The season started this week.

This is the asymmetry to fix: NCAAF loses by more and is gated; NFL loses and is
not.

### 3. ARBITRARY — no measurement either way

`board_enrichment.py:1621`
`_LIVE_GAMELINE_SPORTS = {"mlb", "wnba", "soccer", "ncaaf"}`.
**NHL, NBA, NFL and NCAAB publish ZERO live game-line edges** — refused by name
(`"no live re-sim wired for <sport>"`) before `price_moneyline` is reached. All
eight sports ARE called (`run_refresh_worker.py:5647` →
`book_grid_artifact.py:318`), so this is an allowlist, not an absence.

Fails closed and says so, which is the right shape. But nothing measured put
those four outside it — for most of them there is simply no live re-sim to wire.
`_LIVE_PROP_SPORTS = {"mlb", "wnba", "soccer"}` is the same shape.

### 4. MERELY UNFITTED — opens the moment someone measures it

**Soccer's analytic over-2.5 line** refuses `ANALYTIC_UNCALIBRATED` only because
no calibration error has been fitted. Soccer is in neither
`ANALYTIC_LIVE_STD_ERR_BY_SPORT` nor `..._BY_MARKET`.

WNBA had the identical blanket refusal — measured on production 2026-08-21,
`rows_live_gameline_considered: 194, priceable: 0` — until `#481` fitted 0.054
and `#499` fitted 0.150 for totals. **That is the template**: the refusal is not
a policy, it is a missing number, and fitting it opens the gate honestly.

---

## The one thing genuinely thrown out wrongly, and it needs no model

`#238`: every EV the platform showed was computed against a **vigged** price.
Measured on the production MLB shard 2026-08-06, 122,023 rows / 11 books:

    median two-sided hold 6.25%    p10 3.27%    p90 7.36%

A 6.25% hold inflates one side's implied probability by ~3.1pp, so **rows sitting
just under an edge threshold were discarded while genuinely +EV**. That is
throwing things out, it is measured, and it is entirely model-independent.

`opportunity_signals` fixes it and `ev_vs_fair_pct` carries the corrected number.
**OWED: confirm the corrected basis is applied everywhere, not only on L2-A
rows.** `layer2_board.py:2924` maps `ev_pct → ev_vs_fair_pct` deliberately for
L2-A because there `ev_pct` IS measured against the consensus no-vig line — the
comment is careful that this is "same name, different provenance". Legacy
candidates elsewhere may still carry the vigged basis under the same field name.
That is exactly the kind of same-name/different-meaning join this repo has been
bitten by before, and it is where the remaining +EV volume is.

---

## What this says about the strategy

"Look at EV and augment it with the sim once the sims are confirmed working" is
already the shipped design, already a user ruling, and already capped in the
right direction. The open work is therefore NOT gate removal. It is:

1. **Finish the market layer** — the `#238` basis everywhere; then arbitrage,
   middles and low-hold, none of which are written and none of which need a
   model at all.
2. **Fit what is merely unfitted** (soccer analytic), the `#481`/`#499` way.
3. **Gate NFL regular season**, which tonight's backtest now obliges.
4. **Earn the augment.** The sim's cap lifts when it is validated end-to-end.
   Tonight's evidence says not yet for football: an exact `1.0` published at
   10-3 in the SECOND QUARTER (WIS @ ND, 2026-09-06), NCAAF at t=17.2, NFL at
   t=3.34.
