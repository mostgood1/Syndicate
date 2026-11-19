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

## RESULT -- Arm A: no reading is due (A5 reads on 11-24); NBA SP-nested's joined combos will sit near A3's 200-combo floor at the window end. Arm B: NO CHALLENGER (FIT stop); the sim's edge against the venue's breakeven never beat breakeven, even in sample (run 2026-11-19 18:07Z = 12:07 PM CST, read-only; pre-registration on main `6c54babb1`, pushed 18:07:07Z)

Nothing in the method changed after the push. Both runs used the code and the dump named in the pre-registration.

### Arm A -- E4 Stage 2 under its own registration: funnel-only counts and a projection (no price, probability or outcome computed)

**Run.**
- `e4_stage2_combo_prices.py --a5 --window-start 2026-10-31 --window-end 2026-11-18 --funnel-only`, 17:59-18:07Z,
  rc 0.
- Fleet data root, nice 19 / ionice idle, fleet venv; peak RSS 0.79 GB under the 2.5 GB guard.
- 28 public leg-metadata GETs (5,771 cached) against this lane's copy of the cache. Fee multiplier read: 1.0 (upper
  bound), as on 10-30.
- **No R1, R2 or R3 was computed.** The registered read stays with task `e4-a5-pregame-print-read-1124` (11-24).

**Funnel, settlements 10-31..11-18 (19 days):**

| | NBA SP-nested | Soccer GL |
|---|---|---|
| shaped candidates (0 missing) | 924 | 3,938 |
| Stage 1 games available | 138 (141 sim files; 3 no outcome) | 189 (210 sim matches) |
| no two-sided book quote at the combo's line | 400 | 853 |
| no pregame print (every print in play) | 116 | 1,376 |
| player has no sim row | 180 | -- |
| game not matched / not in slot | 7 | 384 + 135 |
| other (no box score 22, DNP 3, PRA identity 1; clubs 3) | 26 | 3 |
| **joined and priced** | **195 combos / 86 games** | **1,187 combos / 122 games** |

- MLB: 0 shaped combos (the season ended), so both MLB cells will read INSUFFICIENT at any date.
- In the A3 window, NBA SP-nested joined 12 combos / 11 games in 26 days. Now it joins 195 / 86 in 19 days, about
  10.3 combos a day.

**Projection against A3's minimum n (>= 200 combos AND >= 20 games, per R2 TEST, i.e. per side).**
- The joined count is a CEILING for each side's test. A combo enters YES only with p_b - p_a >= 1 pp and a pregame
  print taken on YES; it enters NO only with p_a - p_b >= 1 pp and a NO print.
  - The side split needs probabilities, which funnel-only does not compute, so it is not projected here.
  - In the A3 run, all 12 NBA SP-nested combos fell on the YES side.
- **NBA SP-nested at the window end (settlements through 11-22, 4 more days at 10.3/day): about 236 combos / about
  104 games.**
  - **The YES test reaches 200 only if at least about 85% of joined combos qualify for YES.** So it may read
    INSUFFICIENT on 11-24.
  - The NO test will almost certainly read INSUFFICIENT.
  - Games are not the constraint (86 already).
- **The registered extension to 12-20 is unlikely to run.**
  - A5 §2 extends only if EVERY R2 test is INSUFFICIENT.
  - Soccer GL already joins 1,187 combos / 122 games. In A3, 46% of soccer combos fell on YES and 36% on NO, so both
    soccer tests are likely to clear 200.
  - If NBA YES falls short on 11-24, that reading stands.
- If the extension did run, NBA SP-nested would reach about 523 joined combos by 12-20 (32 more days). YES would
  then clear 200 if about 38% qualify.
- **What this means for S7:** the combos question is answered on 11-24 by its owner's task, not here. No new
  registration is proposed.
- If NBA reads INSUFFICIENT on 11-24, a further NBA-only window would need a NEW amendment, written before its data.
  That would be lane `e4-pregame-prints`' call, or the user's.

### Arm B -- the registered test (props, sim edge vs venue breakeven)

**Coverage actually used.**
- FIT: 2,396 orders / 246 events (10-02..11-07).
- TEST: 2,004 orders / 190 events (11-08..11-18), all Kalshi.
- The pre-registration's coverage section has the full table.

**FIT (all orders: -9.74% [-14.00, -5.49]):**

| T (pp) | kept orders / events | kept ROI [95%] | kept - all [95%] |
|---|---|---|---|
| **0** | 1,399 / 233 | **-12.51% [-18.33, -6.70]** | -2.77 [-6.74, +1.20] |
| 1 | 959 / 183 | -13.42% [-20.59, -6.25] | -3.68 [-9.22, +1.86] |
| 2 | 789 / 155 | -13.40% [-20.89, -5.91] | -3.66 [-9.79, +2.48] |
| 3 | 703 / 146 | -14.05% [-22.11, -5.99] | -4.31 [-11.22, +2.60] |
| 4 | 613 / 142 | -14.90% [-23.87, -5.93] | -5.16 [-13.12, +2.80] |
| 5 | 529 / 134 | -12.72% [-22.39, -3.05] | -2.98 [-11.74, +5.78] |
| 6 | 441 / 128 | -12.85% [-23.27, -2.43] | -3.11 [-12.84, +6.62] |
| 8 | 321 / 114 | -15.22% [-28.04, -2.40] | -5.48 [-17.72, +6.76] |
| 10 | 218 / 102 | -20.73% [-35.73, -5.73] | -10.99 [-25.61, +3.64] |

- **Every T is eligible, and every kept ROI is negative, with its upper bound below 0.** The best is T = 0, at
  -12.51%.
- **Verdict as registered: rule 1, FIT stop. NO CHALLENGER.** The sim's edge against the venue's breakeven does not
  beat breakeven even in sample. There is no forward test.
- At every T, the kept orders did worse than all FIT orders (kept - all is negative at all 9 T, none beyond noise).

**TEST, reported descriptively at T = 0 (as registered for a FIT stop).**

| set | orders / events | flat ROI [95%] |
|---|---|---|
| all | 2,004 / 190 | -4.57% [-8.84, -0.31] |
| kept (edge_pp >= 0) | 1,104 / 187 | -3.74% [-9.75, +2.26] |
| dropped | 900 / 177 | -5.59% [-11.88, +0.69] |

- Kept - all: +0.83 pp [-3.16, +4.82]. Kept - dropped: +1.85 pp [-7.02, +10.72]. Share kept: 55%.
- The bootstrap check on kept agrees: [-9.77, +2.21].
- Even had FIT not stopped, TEST would not have killed (upper bound +2.26), and nothing on TEST beats breakeven.

**Monotonicity (the edge-band read, descriptive).** Return does not rise with the sim's edge in either window:

| edge_pp band | FIT orders / events, ROI [95%] | TEST orders / events, ROI [95%] |
|---|---|---|
| < 0 | 997 / 191, -5.86% [-12.84, +1.12] | 900 / 177, -5.59% [-11.88, +0.69] |
| 0-2 | 610 / 166, -11.36% [-19.58, -3.15] | 547 / 156, +0.04% [-7.81, +7.90] |
| 2-4 | 176 / 83, -8.17% [-22.90, +6.57] | 142 / 75, -12.08% [-27.09, +2.92] |
| 4-6 | 172 / 83, -20.16% [-37.63, -2.69] | 120 / 64, -1.88% [-18.15, +14.38] |
| 6-10 | 223 / 94, -5.15% [-18.89, +8.60] | 175 / 79, -8.56% [-21.32, +4.19] |
| >= 10 | 218 / 102, -20.73% [-35.73, -5.73] | 120 / 60, -5.97% [-25.76, +13.82] |

- **Slope of return on edge_pp:**
  - FIT: **-0.21 pp per pp** [-0.88, +0.47];
  - TEST: **-0.09** [-0.87, +0.68].
- A sim edge that carried information at the venue's price would show a positive slope. Both point estimates are
  negative, and both intervals exclude a slope of about +1 (an edge that pays in full).
- **The orders where the sim disagrees most with the venue (>= 10 pp) lost most on FIT.**

**Slices (TEST, kept at T = 0; descriptive, deciding nothing):**

| slice | all | kept |
|---|---|---|
| live | 144 / 72, -13.68% [-24.49, -2.87] | 96 / 57, -9.30% [-21.68, +3.09] |
| ladder | 1,762 / 190, -4.06% [-8.42, +0.29] | 932 / 187, -3.50% [-9.95, +2.94] |
| paper twin | 98 / 69, -0.38% [-15.01, +14.24] | 76 / 62, +0.31% [-16.11, +16.72] |
| NBA | 777 / 88, -2.59% [-9.92, +4.74] | 407 / 87, +1.88% [-7.94, +11.69] |
| NFL | 248 / 27, -1.93% [-12.02, +8.17] | 137 / 27, +0.26% [-17.45, +17.97] |
| NHL | 979 / 75, -6.82% [-12.80, -0.84] | 560 / 73, -8.81% [-17.09, -0.53] |

- No kept slice's interval excludes 0 from above. NHL kept is below 0.
- With about 9 slices, roughly 0.45 would exclude 0 by chance under a true null. None is a sport or market switch.

### What it means

- **Props (Arm B): the sim's probability does not select winning prop orders at the venue's price.**
  - On 2,396 FIT orders, no threshold on the sim's edge vs the venue's breakeven made money (best -12.5%).
  - The return does not rise with the edge (slopes -0.21 FIT, -0.09 TEST).
  - This agrees with every earlier read:
    - `sim-stake-earned-profile`: the sim never beats the market's Brier in a prop cell;
    - the 10-02 backtests: the model is worse than the book in every sport;
    - S4: the in-play sim gets weight 0 against Kalshi.
  - **The board's sim, as it stands, is not the different selection source the program is looking for, on props.**
- **Combos (Arm A): open until 11-24, and it rests on soccer.**
  - The registered A5 read answers on 11-24.
  - Soccer GL will very likely have a verdict.
  - NBA SP-nested will sit near its floor on the YES side only.
  - MLB has no combos.
  - The 10-30 reading found no edge at the (contaminated) last print. R3 (no price) showed the sim's soccer joint
    beats independence, so soccer is where a combo edge, if any, would show first.
- **Untested, a lead and not a result:** a SIM-ONLY prop source, which would buy every venue prop quote where the sim
  clears the venue's breakeven, whether or not the consensus likes it.
  - It needs a new build: venue prop quotes from `book_quotes` `venue_direct` joined to the population ledger's `mp`,
    plus a row-level grader. The scorecard keeps per-game sums only.
  - Given this result, and the sim's record on props against the market's Brier, its prior is poor. It is not
    recommended ahead of the A5 read.
- **No challenger from S7 goes to the 12-08 window.** Nothing changes live, and nothing is queued.

### S7_RULE_JSON (recorded for completeness; the FIT stop means NO forward test reads it)

```json
{"t_pp": 0.0, "fit_end": "2026-11-08T00:00:00Z", "test_end": "2026-11-19T00:00:00Z", "forward_start": "2026-11-20T00:00:00Z", "forward_events": 150, "verdict": "NO CHALLENGER (FIT stop)"}
```

Scratch (not in git): `C:\tmp\s7cp\` -- `ledger.json` (dump), `report.txt` / `report.json`, `coverage.json`,
`a5_funnel_2026-11-18.json` + `a5_funnel.log`, the synthetic dry run `synth_report.txt`.
