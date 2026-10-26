# Syndicate Fair v1 — PRE-REGISTRATION `[2026-10-26 ~18:00Z, lane syndicate-fair-v1, written and committed BEFORE ANY FIT]`

Decision Engine Phase 1 (`#736`; plan `docs/ai_context/plan_syndicate_decision_engine.md` §3 L1 and §8 Phase 1;
brief `.syndicate/brief_2026-10-26_decision_engine_owners.md` § `fair-price-v2`). OFFLINE research build: nothing is
wired into the board, the DecisionRecord or any order path, and nothing here touches `#704`'s staked probability.

**What had been looked at when this was written:** extraction counts, per-family row / game / date counts, and the
baseline parity check (below). **No model had been fitted, no log loss computed for any fair, and no outcome joined
to any fair.** The code that implements this document is `scripts/syndicate_fair_fit.py` +
`syndicate/features/shared/syndicate_fair.py` (lane branch); the findings record the code SHA that produced them.

## 1. Data

- **Quotes:** the fleet's `~/syndicate-prod/data/<sport>_source/tracking/book_quotes/*.jsonl[.gz]` (the per-slate
  change log, one row per price change), read-only at `nice -n 19 ionice -c3`. Extracted 2026-10-26 17:46–17:51Z by
  `syndicate_fair_fit.py extract` into per-(line, book, side) snapshots.
- **Stage-1 window:** kickoffs `2026-09-30T00:00Z <= commence < 2026-10-26T08:00Z`.
- **Outcomes:** the fleet web's public `GET /api/board/game-chips?date=<Central date>`, final states only, matched by
  `layer2_live_scorecard.match_chip` and settled by its `grade` (soccer 1X2 draws included).
- **No OddsAPI call** is made by anything in this lane.

## 2. Population

- **Line** = (event, market, segment, player, line point), with spreads framed on the home line (the same identity as
  `fair_price_eval.group_key`). `"line": NaN` is read as no line.
- **Outcome set** must be exactly {home, away}, {home, away, draw}, {over, under} or {yes, no}. One-sided markets
  (soccer player props, NCAAF anytime TD) cannot be de-vigged and are out.
- **Decision snapshots:** T−24h, T−6h, T−2h, T−30m before the event's final commence time (a moved game uses its
  later time). At each, every book's latest price change at or before the snapshot for every outcome; the newest of
  them must be ≤ 12h old. Each book is de-vigged against itself by production Shin (`opportunity_signals.devig`).
  **A row needs ≥ 2 such books.** One row = (line, snapshot).
- **Family** = sport × season phase (`season_phase.season_phase` on the game's US-Central date) × kind (game/prop).
  Preseason families are reported and never gated, and no fit pools phases (`learnings.md`, season-phase models).
  **13 families are gated:** mlb-postseason {game, prop}; nba-regular {game, prop}; ncaaf-regular {game, prop};
  nfl-regular {game, prop}; nhl-regular {game, prop}; soccer {game}; wnba-postseason {game, prop}.

## 3. Targets

- **(a) Sharp close:** Pinnacle's last pregame price for every outcome with `captured_at <= commence`, the newest ≤ 12h
  before commence, de-vigged by POWER (the board's sharp-anchor method, `layer2_board._ANCHOR_DEVIG_METHOD`).
- **(b) Otherwise the Shin consensus close:** every book's close pair on the same rule; median of per-book Shin,
  renormalised; ≥ 2 books.
- **(c) The outcome:** full-game h2h / spreads / totals game lines, settled by the final score; pushes dropped.

**The fit's objective is (a)/(b) only. (c) is the independent judge (G2) and is never fitted.** This narrows the
plan's "fitted to … (i) the sharp close … and (ii) the outcome": 25 days of outcomes cannot fit hundreds of weights
per family without the outcome read becoming in-sample. Fitting to outcomes is left to a v2 once there is enough.

## 4. Model (`syndicate_fair.py`)

- Per-book Shin probability vectors p_b, pooled log-linearly: `log p_fair(o) = Σ_b π_b log p_b(o) − log Z`,
  `π_b = w_b / Σ w`. For a two-way line this is exactly the plan's `logit p_fair = Σ w_b logit p_b / Σ w_b`.
- `log w_b = θ[b] + θ[b,mfam] + θ[b,tts] + θ[b,mfam,tts] + θ[age] + θ[b,age]`; mfam ∈ {h2h, spreads, totals,
  game_other, prop} (full-game main markets; segments/alts/3-way-regulation/team totals; player markets);
  tts = the snapshot; age ∈ {<15m, 15m–1h, 1h–3h, 3h–12h}, the time since the book last changed this price.
- Objective: mean cross-entropy to the close target + λ‖θ‖², L-BFGS-B, ≤ 300 iterations. **θ = 0 is equal weights;
  the ridge shrinks every term toward it.** One model per family.

## 5. σ_fair

On each outcome's one-vs-rest logit: `σ² = D²·Σπ² + r²_cell`. D² is the π-weighted spread of the books' logits around
the pooled logit (×Σπ² = the pooled logit's variance if the books were independent). r²_cell is fitted per
(mfam, tts) on the training rows: the mean squared residual to the close not explained by the dispersion term,
floored at 0. A cell with no training residual takes the largest fitted one.

**Calibration check (reported, not gated):** the share of held-out closes whose logit lies within ±1σ of the fair's
(nominal 68.3%; read as calibrated within [0.60, 0.76]) and within ±2σ (nominal 95.4%). Two-way lines score outcome 0;
3-way lines score each outcome.

## 6. Validation — walk-forward by date

- Test date d = the UTC commence date. **Training = the family's rows with a close target and commence before
  00:00Z of d−1**, so every training close precedes the earliest T−24h decision on d.
- A family is first tested once its training has ≥ 5 UTC dates and ≥ 30 games.
- λ ∈ {1e−5, 1e−4, 1e−3, 1e−2}, chosen at EVERY refit by inner validation on the last 2 training dates (fit on the
  rest), then refit on all training rows with the chosen λ. r²_cell is refit at every refit.

## 7. The gate — per family, never pooled

Per held-out row, Δ = CE(v1) − CE(Shin consensus) (cross-entropy to the target; lower is better). The family's mean Δ
has a 95% CI from 2,000 game-clustered bootstrap resamples (seed 20261026). The baseline is
`layer2_board._consensus_fair(cells, sides, method="shin")` on the same books at the same snapshot; parity was
checked on 3,125 sampled rows before this registration: **0 mismatches** (tolerance 1e−9).

- **G1 (close target):** PASS requires the CI upper bound < 0.
- **G2 (outcome; a harm guard):** if ≥ 30 held-out games carry an outcome and Δ's CI LOWER bound is > 0, the family
  FAILS whatever G1 says.
- **UNDERPOWERED** (no verdict) when G1 rests on < 30 held-out games or < 3 test dates.
- Verdicts: `PASS`, `PASS (outcome unmeasured)`, `FAIL`, `FAIL (worse on outcomes)`, `UNDERPOWERED`.
- **Multiplicity:** reported beside each verdict, not part of it: whether G1's CI at 1 − 0.05/13 also lies below 0.
- **No breakdown** (by target source, snapshot, market family) can pass a family.

## 8. A mechanical component, stated before the data

On sharp-target rows Pinnacle is both an input and the target, so a fair that leans on Pinnacle's current price will
sit close to Pinnacle's close partly by construction. That is the E1 claim itself (a sharp-weighted fair tracks the
sharp close), but it is not independent evidence. **The non-mechanical evidence is the consensus-target split and G2,
and the findings report all three.** The gate stays as the plan wrote it.

## 9. Reported, not gated

- The **equal-weight logit pool** vs Shin, to separate the pooling form from the learned weights.
- The **fitted weights** from each family's last refit (relative to an equal vote = 1.0).
- **Engine read** (in-sample, descriptive): per book × snapshot on two-way rows, β = Σxy / Σx², with
  x = logit(book) − logit(Shin consensus now) and y = logit(close) − logit(Shin consensus now). β = 1: the close moves
  all the way to the book; β = 0: its disagreement is noise. Against (i) the target and (ii) the consensus close;
  game-clustered 95% CI; cells with ≥ 200 rows.
- Coverage, and the n / games / test dates every number rests on.

## 10. Recommendation rule

- **≥ 1 family PASS or PASS (outcome unmeasured)** → recommend writing `p_fair_v1` and `σ_fair_v1` into the
  DecisionRecord in SHADOW for those families only; other families keep the Shin consensus; the basis is stamped per
  row. No staking change, no board change: the Phase-2 edge gate governs money.
- **0 families pass** → do not wire; continue to stage 2.
- A passing family whose 1σ coverage is outside [0.60, 0.76] is wired with σ flagged uncalibrated, and σ shrinks no
  edge until it is recalibrated.

## 11. Stage 2 — the forward read, registered now

The same code (the stage-1 code SHA; the scored logic unchanged) and the same constants, with the walk-forward
continuing; the gate is re-read on test dates with kickoffs `2026-10-26T08:00Z <= commence < 2026-11-23T08:00Z` only.
**Read on or after 2026-11-24.** It is the first read for the NBA regular season (stage 1 cannot test it: its 5th
training date is 10-24) and the first with Pinnacle on NBA / NFL / soccer game lines (present only from 10-25).
Stage 1 and stage 2 are read separately and never pooled.

## Coverage measured before this registration (no fair computed)

Fleet `book_quotes`, per sport (UTC commence dates in the window, events, books seen, Pinnacle):

| sport | events | books | Pinnacle on game lines |
|---|---|---|---|
| MLB | 34 | 38–40 | every event, all window |
| NCAAF | 235 | 30–33 | every event, all window |
| NFL | 58 | 12–14; 34 from 10-25 | 10-25/26 only (11 events) |
| NBA | 110 (preseason to 10-19) | 6–12 | 10-25/26 only (7 events) |
| soccer | 374 | 10–15; 34–38 from 10-25 | 10-25/26 only (11 events) |
| NHL | 179 | 12–14 | none (Pinnacle quotes NHL **props**) |
| WNBA | 16 | 14–16 | none |

Per family, after the population rules (rows = line × snapshot):

| family | rows | games | dates | sharp-close rows | consensus-close rows | outcome rows | dates: close ∩ outcome | sharp ∩ outcome |
|---|---|---|---|---|---|---|---|---|
| mlb·postseason·game | 3,885 | 33 | 20 | 1,355 | 2,420 | 434 | 19 | 19 |
| mlb·postseason·prop | 11,093 | 33 | 20 | 0 | 10,832 | 0 | 0 | 0 |
| nba·preseason·game *(not gated)* | 1,794 | 66 | 15 | 0 | 1,640 | 1,258 | 11 | 0 |
| nba·regular·game | 27,475 | 43 | 7 | 1,289 | 25,773 | 1,016 | 7 | 2 |
| nba·regular·prop | 20,618 | 43 | 7 | 788 | 19,437 | 0 | 0 | 0 |
| ncaaf·regular·game | 15,806 | 235 | 19 | 3,845 | 11,580 | 7,590 | 19 | 19 |
| ncaaf·regular·prop | 6,428 | 159 | 19 | 0 | 5,694 | 0 | 0 | 0 |
| nfl·regular·game | 3,771 | 58 | 15 | 113 | 3,613 | 1,062 | 15 | 2 |
| nfl·regular·prop | 14,114 | 58 | 15 | 0 | 13,298 | 0 | 0 | 0 |
| nhl·preseason·game *(not gated)* | 547 | 37 | 7 | 0 | 535 | 484 | 7 | 0 |
| nhl·preseason·prop *(not gated)* | 3,482 | 37 | 7 | 3,261 | 204 | 0 | 0 | 0 |
| nhl·regular·game | 2,154 | 141 | 21 | 0 | 2,105 | 1,984 | 21 | 0 |
| nhl·regular·prop | 22,620 | 141 | 21 | 15,089 | 7,234 | 0 | 0 | 0 |
| soccer·regular·game | 12,201 | 372 | 20 | 125 | 11,937 | 4,568 | 20 | 2 |
| wnba·postseason·game | 5,454 | 14 | 12 | 0 | 5,310 | 372 | 12 | 0 |
| wnba·postseason·prop | 4,974 | 14 | 12 | 0 | 4,776 | 0 | 0 | 0 |

**Expected before any fit, from coverage alone:** nba-regular (both kinds) is UNDERPOWERED in stage 1 by the
training rule; mlb and wnba (≤ 33 games across the whole window) very likely are too. The sharp-close target is
material only for MLB, NCAAF and NHL props in stage 1. Every other family is judged mostly against the consensus close.

**Found while extracting, not a result:** the change log stores `"line": NaN` on NBA/WNBA/NHL h2h and yes/no rows, and
NaN ≠ NaN, so as a key part it made every quote row its own line (667,804 NHL h2h "lines" for 179 events). Fixed here
by reading NaN as no line. `fair_price_eval.group_key` (lane `fair-price-v2`) has the same shape (`_f` returns nan);
recorded as a lead for that lane, not edited.

## Amendment A1 — `[2026-10-26 18:07Z, after the stage-1 verdicts, BEFORE any stage-2 data is read and BEFORE the post-hoc lambda diagnostic returned]`

**Why:** at stage 1 the inner validation chose λ = 1e−5, the registered grid's LOWER EDGE, at nearly every refit
(NCAAF game 13/13, NHL props 15/15, NFL 7/7), and every family's fitted weights except NHL props sit within about
0.7–1.3× an equal vote. A boundary choice says the grid was too strong for this loss scale: per-row cross-entropy
differences are ~1e−5 nats, so a ridge of 1e−5·θ² prices a weight change at the size of the whole achievable gain.
That is a defect in this registration, found by its own output.

**Change, stage 2 only. Stage 1's verdicts stand as read.** Stage 2 reads TWO arms on the same rows, each with its own
per-family verdict by §7, never pooled with each other:
- **Arm A, primary: v1 exactly as registered** (λ ∈ {1e−5, 1e−4, 1e−3, 1e−2}). This is the gate.
- **Arm B, secondary: v1.1**, identical except λ ∈ {1e−8, 1e−7, 1e−6, 1e−5}. It may pass a family only alongside
  A's read, and a B-only pass is reported as a lead for a v2 registration, not as a gate pass.

Nothing else changes: targets, population, families, snapshots, σ, the 30-game / 3-date floors, the window
(`2026-10-26T08:00Z <= commence < 2026-11-23T08:00Z`) and the read date (on or after 2026-11-24).
