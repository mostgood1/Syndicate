# Findings -- lane `s7-combos-props`: study S7 of the profit learning program (2026-11-19)

Plan: `.syndicate/plan_2026-11-18_profit_learning_program.md`, study S7 ("correlation products and props"). Asked for
by the user 2026-11-19 ~11:50 AM CST ("Start S7"). Read-only: this lane changes no live code, env or fleet state and
deploys nothing. Counts, percentages and intervals only (the repo is public). Not financial advice; no result
guarantees future returns. A GO only names a challenger for a betting-change window (12-08 at the earliest).

## PRE-REGISTRATION (written 2026-11-19 ~18:10Z = 12:10 PM CST, before any outcome number is computed)

### Arm A -- combos: E4 Stage 2 under its own registration

**What the registration allows today.** E4 Stage 2 is registered in
`findings_2026-10-26_e4_combo_correlation_preregistration.md` (A3 + A4, then A5 + A6).
- **A3 / A4** fix the window to Stage 1's games, 09-30..10-25 ("No window extension: games after 10-25 have no
  Stage 1 join and are not used"). Re-running it would reproduce the 10-30 result exactly. The 3 more weeks of NBA
  cannot enter it.
- **The NBA weeks enter only through A5** (lane `e4-pregame-prints`): the last PREGAME print on the side bought,
  settlements D0 (10-31) .. 2026-11-22, **"Read on or after 2026-11-24"**, one registered extension to 12-20 if every
  R2 test is INSUFFICIENT.
  - The read is armed as the one-time task `e4-a5-pregame-print-read-1124` (Tue 11-24 10:15 AM CST), which records it
    in lane `e4-pregame-prints`.
  - A read of R1 / R2 / R3 today would be an early look the registration forbids.
- **So S7 computes no A5 price, probability, outcome or reading.** It runs only what A5 §3 allows before the read:
  `e4_stage2_combo_prices.py --a5 --funnel-only`. That writes join counts per cell, and nothing else.
  - Window: 2026-10-31 .. 2026-11-18.
  - Its own copy of the leg cache (`C:\tmp\s7cp\e4cache`), so the 11-24 task's cache is untouched.
- From those counts, S7 projects each cell's joined combos and games to the window end (11-22) and to the extension
  (12-20), at the measured daily rate, against A3's minimum n (>= 200 combos AND >= 20 games).
- **No new cell or rule is registered for Arm A.**

### Arm B -- props: does a per-line sim-edge rule at the venue's own price beat breakeven, fee-net?

**Question.** Among pregame Kalshi / Polymarket PLAYER-PROP orders, do the orders whose sim probability exceeds the
venue's own breakeven (price + fee) by at least T, with T fitted on earlier orders, return more than breakeven,
fee-net, on later orders?

**Why this population.** The survey (coverage below) found exactly one family that carries, for props, a model
probability AND a venue price at decision time AND an outcome: the execution ledger's venue prop orders (live, paper
twin, paper ladder). The ladder is about 80% of them.
- **The population ledger cannot carry this test today.** It records the venue as the priced book on few pregame
  prop rows: on 11-10 + 11-15 there were 128 NFL pregame and 0 NBA or NHL pregame venue-priced prop rows, against
  35,950 sportsbook-priced pregame prop rows.
  - The scorecard keeps per-game sums, not row-level grades.
  - A sim-only selection over every venue prop quote would need a venue-quote join (`book_quotes` `venue_direct`) and
    a row grader. That is a new build, not this test.
- **So the rule here is a sim filter on the venue prop orders the consensus trigger placed.** It is not a sim-only
  source.

**Already seen before this registration, stated so the overlap is visible.**
- **`sim-stake-earned-profile`** (refits 11-01, 11-12, 11-18; `findings_2026-10-22_sim_stake_earned_profile.md`):
  - the Brier of the sim's probability against the market's, on settled portfolio-book orders through 11-17,
    including NBA player points / assists / rebounds / threes, NHL SOG / assists / points and NFL receptions;
  - mostly sportsbook prices, and no ROI;
  - 11-18: no cell where a fitted sim weight beats the market on the hold-out.
- **Cheat sheets, 11-13** (10-15..11-12, best sportsbook price, not fee-net): "Sim vs the line" NBA +8.0%
  [+2.1, +14.0]; NHL / NFL null.
- **`findings_2026-10-24_live_cell_scorecard.md`** (venue price, fee-net, consensus selection, before 10-24):
  - ladder Kalshi NBA props -13.1%;
  - live Kalshi NBA props -34.8%;
  - paper Kalshi MLB props -26%.
- **S6** (11-19): pooled venue outcomes by price and claimed EV, FIT 10-25..11-07 and TEST 11-08..11-18. It covers
  every market (props included), but not split by model edge.
- **Portfolio readings** (11-18 / 11-19): the live book's prop markets lose over 30 days (ASSISTS -11.7%,
  Receptions -13%).
- **Older reads:**
  - `prop_fair_side_lean` (NBA over-lean; sportsbook);
  - `sim_gap_ev_study` (09-30..10-14, sportsbook, gross: within an EV band, sim FOR does not beat AGAINST);
  - the 10-02 lines/props backtests (model worse than the book in every sport).
- **No prior file has scored the sim's probability against the VENUE's breakeven, fee-net, on the venue's own
  prop orders.**
- **But the sim's probability has been graded against outcomes on overlapping prop lines through 11-17.** So the
  historical TEST (11-08..11-18) is contaminated and **can only KILL**. **A GO can come only from the forward test.**

**Instrument.** `scripts/s7_prop_model_edge.py` (this lane; 15 tests in `tests/test_s7_prop_model_edge.py`).
- It reuses S1's `population`, `study_row`, `flat`, `clustered_diff` and `SLICES` unmodified, and S6's
  `price_terms` unmodified.
- **Substrate:** the fleet ledger dump (`live_cell_scorecard.py dump`, 2026-11-19 18:02:29Z,
  `live_document_read_ok=True`, 57,423 rows, newest submit 17:59:17Z). It was read at nice 19 with the fleet venv and
  the refresh-worker state env, under a guard that would kill the job below 2.5 GB available; peak RSS 0.78 GB.
- **Dry run without outcomes:** before this was pushed, `report` ran once on a copy of the dump whose outcomes and
  P&L were replaced by seeded synthetic ones (won ~ Bernoulli(breakeven), so the true ROI is 0). It checked that the
  path runs, and it measured the null's interval widths (power, below). No real outcome was read.

**Population.**
- S1's population, unchanged:
  - settled (won / lost / push), filled, staked orders with an event_id;
  - live `kalshi` / `polymarket`, the paper twin `paper:<venue>` and the ladder `paper:<venue>:ladder`;
  - pregame (`phase_of` pregame AND submit < commence);
  - paper rows deduplicated per (venue, position_key), first submit kept; live rows never deduplicated.
- Restricted to player props (`live_cell_gate.family_of == "prop"`).
- The order must have a model probability, below.

**Definitions (all known at submit).**
- `q` = the requested contract price. `be` = q + the fee per contract (S6 `price_terms`).
- `fair` = q x (1 + ev_pct/100).
  - `ev_pct` is the trigger's GROSS EV at the venue's price (`venue_scope.scope_rows_to_venue`).
  - This is the sizer's own reconstruction (`portfolio_commit`).
- `p_model` = fair + model_edge_pct/100, the board's sim probability for the side.
- **`edge_pp` = 100 x (p_model - be)**: the sim's edge against the venue's breakeven, fee included.
- Orders with no `ev_pct`, no `model_edge_pct`, or a fair or p_model outside (0, 1) are dropped and counted.

**Windows (by submit time, UTC).**
- **FIT:** before 2026-11-08T00:00Z (first prop order 10-02).
- **TEST:** 2026-11-08T00:00Z to before 2026-11-19T00:00Z (through 11-18), settled by the dump.
- **FORWARD:** submitted from 2026-11-20T00:00Z on. 11-19 is a gap day.

**Rule (one, fixed).**
- Keep an order iff `edge_pp >= T`.
- T from {0, 1, 2, 3, 4, 5, 6, 8, 10} pp, chosen on FIT only:
  - among the T whose kept set has >= 200 orders and >= 50 events, take the largest FIT flat ROI;
  - ties go to the smaller T.
- No sport, market, book or venue term (learnings 2026-10-05 PRIME DIRECTIVE).

**Outcome.** Fee-net flat ROI per order: mean of `pnl_dollars / fill_stake_dollars`, in percent (S1's). Pushes stay
in at 0.

**Decision metric.** **D = flat ROI(kept) - 0**: breakeven is the benchmark, because the question is whether the
rule makes money, not whether it loses less.
- The 95% interval is S1's event-clustered interval (cluster = event_id, +-1.96 SE).
- A seeded event-cluster bootstrap is printed as a check; it is not the registered interval.

**Rules, in order.**
1. **FIT stop:** if no T is eligible, or the best eligible T's FIT kept ROI is <= 0, the sim edge does not beat
   breakeven even in sample. Verdict **NO CHALLENGER**; no forward test. TEST is reported at that T, descriptively.
2. **Early KILL:** on TEST (11-08..11-18), if the kept ROI's 95% upper bound < 0. No forward test.
3. **Otherwise FORWARD TEST.** T is frozen as committed with the result (the `S7_RULE_JSON` block;
   `s7_prop_model_edge.py forward --rule-from` this file).
   - Set: population orders submitted from 2026-11-20T00:00Z, settled, with `edge_pp >= T`.
   - Read at the first reading where kept orders cover >= 150 distinct events. The decision set is the kept orders
     on the first 150 events by first submit.
   - **GO iff the kept flat ROI's 95% lower bound > 0. Otherwise NO-GO.**
4. A positive TEST decides nothing by itself (the window is contaminated, above).
5. A GO names a challenger for a betting-change window (12-08 at the earliest; paper first if the user prefers).
   It changes nothing live; the user decides.

**Reported beside, deciding nothing:**
- the FIT T table (kept orders / events, ROI, D vs all);
- on TEST: all, kept and dropped, kept minus all, kept minus dropped, and the share kept;
- the edge-band table (<0, 0-2, 2-4, 4-6, 6-10, >=10 pp) on FIT and TEST, and the slope of return on edge_pp
  (event-clustered), which is the monotonicity read;
- slices: live, paper twin + ladder, paper twin, ladder, Kalshi, Polymarket, and per sport.
- No slice is a finding on its own, and none is a sport or market switch.

**Known limits, stated before the run.**
- **The population is the consensus trigger's prop orders.** A sim-only source over every venue prop quote is not
  testable from today's data (above).
- **`model_edge_pct` is None past +-15 points** (`layer2_board._MODEL_EDGE_MAX_POINTS`), so the sim's largest
  disagreements are censored. 611 prop orders are dropped as `no_model_edge`; that count includes rows with no sim.
- **The rule rarely fires on NBA.** This is a property of the sim's output at submit, not an outcome: NBA prop
  orders' edge_pp sits near 0. At T = 2, FIT keeps 17 NBA orders of 760, and TEST keeps 12 of 777. Any T >= 1 in
  effect selects NHL and NFL lines (and, in FIT, MLB and WNBA). It is not a sport term, but the reader should know it.
- **FIT and TEST differ in mix.**
  - FIT holds MLB (postseason) and WNBA, which TEST and FORWARD do not.
  - TEST is Kalshi-only, while FIT holds 127 Polymarket orders.
  - 10-02..10-19 hold only the paper twin; the ladder starts 10-20.
- **Paper fills are assumed at the requested price** (no depth or slippage); live fills are real.
- The ladder places several orders per event (about 10 per event in TEST), so the event count, not the order count,
  sets the interval widths.

**Power, from the synthetic null (outcomes replaced; stated before any real number).**
- At T = 2, the TEST kept ROI's interval was +-7.2 pp on 557 orders / 111 events. The FIT kept intervals ran +-5.8 pp
  (T = 0, 233 events) to +-15.4 pp (T = 10, 102 events).
- Scaled to 150 forward events, the half-width is about +-6 to +-9 pp for T <= 4, rising to about +-13 pp at
  T = 10. **So a GO needs a kept ROI of roughly +6% to +13% or more, depending on T.** Real outcomes are correlated
  within a game, so the true width is likely larger.
- **Forward timing:** TEST's kept events per day were 17.0 at T = 0, 10.1 at T = 2, 8.8 at T = 5-6 and 5.5 at T = 10.
  At those rates, 150 events take about 9 days (T = 0) to 27 days (T = 10). **The reading falls between about 11-30
  and 12-18 (games settled), depending on T.** The exact date follows from the T chosen.

## Coverage, measured before this pre-registration was pushed (counts only, no outcome)

**Arm B: per-family date coverage and the intersection.**
- Every family here comes from one source, the ledger dump: the venue prop orders, their model probability, and the
  venue's settlement.
- Orders: 48 submit dates, 10-02..11-19, with no prop order on 10-19. Orders with a model probability cover the same
  dates.
- **Intersection: 47 dates.** FIT is 36 dates (10-02..11-07), TEST 11 dates (11-08..11-18), and 11-19 is the gap.

| window | orders | events | ladder K / PM | twin K / PM | live K / PM |
|---|---|---|---|---|---|
| **FIT** | **2,396** | **246** | 1,796 / 43 | 327 / 78 | 146 / 6 |
| **TEST** | **2,004** | **190** | 1,762 / 0 | 98 / 0 | 144 / 0 |
| gap (11-19) | 43 | 9 | 37 / 0 | 2 / 0 | 4 / 0 |

**By sport (orders / events):**
- FIT: NBA 760 / 92; NHL 565 / 50; MLB 541 / 29; NFL 410 / 65; WNBA 120 / 10.
- TEST: NHL 979 / 75; NBA 777 / 88; NFL 248 / 27.

**By sport x stat (orders FIT / TEST):**
- NHL: assists 325 / 550; points 141 / 217; goals 99 / 212.
- NFL: receptions 360 / 211; passing TDs 50 / 37.
- NBA: threes 264 / 253; assists 188 / 197; rebounds 143 / 169; points 132 / 116; steals 17 / 26; blocks 16 / 16.
- MLB (FIT only): hits 162; H+R+RBI 138; RBI 108; total bases 68; outs 21; strikeouts 17; earned runs 13; hits
  allowed 8; home runs 3; walks allowed 3.
- WNBA (FIT only): points 61; rebounds 44; threes 8; assists 7.

**Per submit date (orders: ladder / twin / live):**
- 10-02..10-18, twin only: 2, 16, 10, 14, 24, 61, 27, 12, 22, 34, 33, 12, 5, 8, 2, 3, 4.
- 10-20 12/0/8; 10-21 70/9/17; 10-22 71/7/13; 10-23 72/3/10; 10-24 119/8/8; 10-25 112/0/10; 10-26 149/6/3;
  10-27 131/14/1; 10-28 76/7/3; 10-29 75/6/5; 10-30 61/3/2; 10-31 69/4/6; 11-01 114/6/6; 11-02 120/12/12;
  11-03 158/11/15; 11-04 75/4/4; 11-05 150/11/14; 11-06 77/3/4; 11-07 128/2/11.
- TEST: 11-08 162/16/21; 11-09 145/7/9; 11-10 154/12/18; 11-11 184/7/9; 11-12 227/12/24; 11-13 120/4/7;
  11-14 225/11/14; 11-15 161/4/19; 11-16 123/4/5; 11-17 137/10/15; 11-18 124/11/3.

**Feature distribution (edge_pp; a feature, not an outcome).**
- p10 / p25 / p50 / p75 / p90: FIT -7.43 / -1.30 / +0.26 / +4.15 / +9.45; TEST -5.98 / -0.97 / +0.14 / +2.78 / +7.74.
- Mean breakeven: FIT 0.558, TEST 0.583.
- Kept by T, orders / events:

| T (pp) | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 8 | 10 |
|---|---|---|---|---|---|---|---|---|---|
| FIT | 1,399 / 233 | 959 / 183 | 789 / 155 | 703 / 146 | 613 / 142 | 529 / 134 | 441 / 128 | 321 / 114 | 218 / 102 |
| TEST | 1,104 / 187 | 681 / 140 | 557 / 111 | 481 / 102 | 415 / 101 | 349 / 97 | 295 / 97 | 188 / 80 | 120 / 60 |

- All nine T values meet the FIT floor (200 orders, 50 events).

**Drops (all windows).**
- ladder: in game 4,830; duplicate position 4,380; unsettled 2,514.
- paper twin: in game 523; duplicate 427; unsettled 70.
- live: no event_id 552; in game 422; not filled 118; unsettled 72; no times 30; no stake 2.
- not a prop: 16,341.
- prop with no model edge: 611.

**Arm A: the store's shaped counts for 10-31..11-18** (from the funnel's store pass; tickers only, no price):
- NBA SP-nested: 924 shaped, 0 missing.
- Soccer GL: 3,938 shaped, 0 missing.
- MLB: 0 (the season ended).
- NBA SP-disjoint: 9,383, not a passing shape. They are counted as not read, and are never tested.
- Joined counts follow with the result.
