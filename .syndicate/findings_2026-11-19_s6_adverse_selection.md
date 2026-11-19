# Findings -- lane `s6-adverse-selection`: study S6 of the profit learning program (2026-11-19)

Plan: `.syndicate/plan_2026-11-18_profit_learning_program.md`, study S6. Asked for by the user 2026-11-19 ~7:50 AM CST
("Start both"). Read-only: this lane changes no live code, env or fleet state, and deploys nothing. Counts and
percentages only (the repo is public). Not financial advice; no result guarantees future returns.

## PRE-REGISTRATION (written 2026-11-19 14:06Z = 8:06 AM CST, before any outcome number is computed)

**Question.** Can a filter built from entry-time features, fitted on earlier orders, pick out the orders that lose,
so that dropping them raises fee-net flat ROI out of sample against the champion (all orders) on the same dates?

**Already seen before this registration, stated so the overlap is visible.**
- **S1** (`findings_2026-11-18_s1_freshness_study.md`, orders 10-25..11-17):
  - flat ROI by Pinnacle and consensus capture age on FIT (10-25..11-07) and TEST (11-08..11-17). Freshness did not
    generalise (fresh-only minus all on TEST +0.21 pp [-2.82, +3.24]);
  - **its EXPLORATORY venue-move section, the motivation for this study's `vmove` feature:** toward the reference
    -6.07%, flat -4.21%, away +6.54%; toward minus away -12.6 pp [-28.2, +2.9] (747 vs 301 orders), the same sign in
    S1's FIT and TEST. The venue quote covered 34% of orders.
- **The 11-18 portfolio findings** (`findings_2026-11-18_portfolio_monitor.md`):
  - close calibration: picks calibrated against the de-vigged close on the 40% with a two-sided close; the
    favourite-longshot hypothesis FALSIFIED;
  - consensus vs venue: picks win 7.8 pp less than the consensus and 5.9 pp less than the venue's own fair (388 bets /
    272 games); the claimed-edge 2-4 pp group won 8.6 pp less than the consensus.
- **S5** (live price bands): the band that was worst on 08-06..10-31 (.55-.70) was the best on 11-01..11-17.
- **Test B** looks (P1 by a 2-minute capture age) and the 11-18 product-optimization hand-off (paper orders admitted at
  5-7% EV returned -3.60%; realised-on-admitted-EV slope -0.74 [-3.00, +1.48]).
- **So the historical TEST window (11-08..11-18) has been looked at for the age, venue-move, price and EV features.**
  Only 11-18 is unseen by all of them. The historical TEST can therefore only KILL; **a GO can come only from the
  forward test** on orders not yet placed.
- Nothing has been looked at for book count, dispersion or time to start, and no multivariate model has been fit.

**Instrument.** `scripts/s6_adverse_selection.py` (this lane; 9 tests in `tests/test_s6_adverse_selection.py`).
- It reuses S1's instrument unmodified: `population`, `reference_ages`, `index_beats`, `flat`, `clustered_diff`,
  `bootstrap_diff`, `study_row`, `SLICES`. From Test B (`pinnacle_edge_deciles.py`, unmodified): `load_heartbeats`,
  `load_quotes`, `quote_key`, `implied`, `devig`, `contract_price`.
- **Substrate:** the fleet ledger dump (`live_cell_scorecard.py dump`, 2026-11-19 13:59:44Z,
  `live_document_read_ok=True`, 57,133 rows, newest submit 2026-11-19T13:58:37Z), joined on the fleet 13:59-14:03Z
  (refresh-worker state env, fleet venv, nice 19, under a guard that would kill the job below 2.5 GB of fleet memory
  available; it never fired, peak RSS 1.2 GB): `S6_JOIN orders=21395 pin_known=14199 cons_known=18222
  books_known=20942 vmove_known=7156`. Fetch heartbeats and `book_quotes` shards were read from the fleet's data root.
- **Dry run without outcomes:** before this was pushed, the whole report path ran once on a copy of the rows whose
  outcomes were replaced by seeded synthetic ones (won ~ Bernoulli(breakeven)). It checked that the code runs; no
  real outcome was read. The lambda grid was widened from {1..1000} to {1..100000} after that dry run, because the
  synthetic null chose the grid's edge.

**Population (S1's, unchanged).**
- Settled (won / lost / push), filled, staked orders with an event_id at a venue: live `kalshi` / `polymarket`,
  `paper:<venue>` (the twin) and `paper:<venue>:ladder`. Pregame only (`phase_of` pregame AND submit < commence).
- Paper rows deduplicated per (venue, position_key), first submit kept; live rows never deduplicated.
- Excluded: `paper` (the sportsbook paper book), `paper:prophetx`, `paper:novig`.

**Windows (by submit time, UTC).**
- **FIT:** from the first fetch heartbeat (2026-10-25T18:36:27Z) to before 2026-11-08T00:00Z.
- **TEST:** 2026-11-08T00:00Z to before 2026-11-19T00:00Z (through 11-18), settled by the dump.
- **FORWARD:** submitted from 2026-11-20T00:00Z on. 11-19 is a gap day: the model is frozen today.

**Outcome.** Fee-net flat ROI per order: mean of `pnl_dollars / fill_stake_dollars`, in percent (S1's).

**Features (all known at submit; each is a property of the LINE).** No sport, market or book term is used
(learnings 2026-10-05 PRIME DIRECTIVE).

| feature | definition |
|---|---|
| `pin_age` | log1p(Pinnacle capture age at submit, minutes) -- S1's primary reader |
| `cons_age` | log1p(sportsbook-consensus capture age, minutes) -- S1's secondary reader |
| `n_books` | sportsbooks (not kalshi / polymarket) with a two-way quote at OUR line in `book_quotes` as of submit (0 allowed; missing when the side cannot be flipped, the market is soccer h2h (three-way), or no shard exists for the order's dates) |
| `disp` | the range of those books' de-vigged fairs, pp (needs >= 2 books) |
| `t_start` | log1p(hours from submit to commence) |
| `price` | logit of the requested contract price |
| `vmove` | our venue's own logged quote on our side and line, from the reference fetch to submit: +1 moved toward the reference fair, -1 away, 0 flat. S1's exploratory definition, with one extension for coverage: the reference fetch is the Pinnacle capture, else the consensus capture. Reference fair: Pinnacle's two-way at submit, else the consensus median |
| `ev` | the trigger's own `ev_pct` at submit, clipped to [-10, 30] |


**Missing values.** Each feature is standardised by its FIT mean and SD over the orders that have it, clipped to
+-4 SD. A missing value is set to the FIT mean (0 after standardising), so it contributes nothing. There are no
missingness indicators, because those would encode the sport (NCAAB has no Pinnacle at all). A feature with fewer
than 30 FIT values or SD 0 is dropped.

**Model (one, fixed).**
- **Label:** won (1) or lost (0); pushes are left out of the fit and kept in every ROI.
- **L2 logistic regression with an offset:** P(won) = sigmoid(logit(breakeven) + b0 + beta . x), where breakeven =
  the requested contract price + the fee per contract. The offset makes the label "won against breakeven": beta is
  the logit shift from the price we pay. The intercept is unpenalised.
- **Penalty** lambda from {1, 10, 100, 1000, 10000, 100000} (on the summed log likelihood), chosen by 5-fold CV on FIT. The folds are
  events ordered by their first submit and cut into 5 contiguous blocks (event-grouped, time-ordered). The lowest
  out-of-fold log loss wins; ties go to the larger lambda. The standardisation uses all of FIT (no outcome enters it).
- **Score** = the predicted flat return, P(won) / breakeven - 1.
- The plan's label was "won minus fair". This uses won against breakeven, because the decision metric is flat ROI
  and ROI is paid against breakeven. The fair enters through `ev`, `n_books`, `disp` and `vmove`.

**Choosing the keep share (FIT only).**
- Out-of-fold scores come from the CV fits at the chosen lambda.
- For q in {0.5, 0.6, 0.7, 0.8, 0.9}: keep the FIT orders whose out-of-fold score is >= the (1 - q) quantile, and
  compute D_FIT(q) = flat ROI(kept) - flat ROI(all FIT).
- Choose the q with the largest D_FIT(q) > 0; ties go to the larger q. Every q keeps at least 50%.
- **The final model** is refit on all of FIT at the chosen lambda. **The cut** is the (1 - q) quantile of its FIT
  scores. On TEST and FORWARD the cut is FIXED (it is not re-quantiled), so the share kept there is measured, not set.

**Decision metric.** **D = flat ROI(kept) - flat ROI(all)** on the judged set, in pp, with S1's event-clustered 95%
interval (cluster = event_id; linearised influence for the overlapping sets; +-1.96 SE). A seeded event-cluster
bootstrap is printed as a check; it is not the registered interval.

**Rules, in order.**
1. **FIT stop:** if no q has D_FIT(q) > 0, there is no filter to test. Verdict **NO CHALLENGER**; S6 ends with no
   forward test. TEST is then reported at the q with the largest D_FIT, descriptively.
2. **Early KILL:** on TEST (11-08..11-18), if D's 95% upper bound < 0. No forward test.
3. **Otherwise FORWARD TEST.** The model and the cut are frozen as committed with the result (the `S6_MODEL_JSON`
   block below; `s6_adverse_selection.py forward --model-from` this file).
   - Set: orders in the same population submitted from 2026-11-20T00:00Z on, settled.
   - Read at the first reading where at least 150 distinct events have settled orders. The decision set is the
     orders on the first 150 events by their first submit.
   - **GO iff D's 95% lower bound > 0. Otherwise NO-GO.**
4. A positive D on the historical TEST decides nothing by itself (the window is contaminated, above).
5. A GO only names a challenger for a betting-change window (12-08 at the earliest; paper first if the user
   prefers). It changes nothing live, and the user decides.

**Reported beside, deciding nothing:** the CV table, the D_FIT(q) table, the fitted coefficients, kept / dropped / all
on TEST, kept minus dropped, the share kept on TEST, and D in 6 slices (live; paper twin + ladder; paper twin; ladder;
Kalshi; Polymarket). Under a true null about 0.3 of those 6 intervals would exclude 0 by chance. No slice is a finding
on its own, and none is a sport or market switch.

**Known limits, stated before the run.**
- `vmove` covers only part of the book (S1: 34%): the venue's own quote reaches `book_quotes` for few sports (I2).
- The ladder dominates the count and every order weighs the same in flat ROI. The ladder places many orders per
  event, so the event count, not the order count, sets the interval widths.
- With a negative intercept, a predicted-return score drops low-priced orders first even at beta = 0. That is a
  property of the price (a line property), and S5 showed price bands do not carry over, so the out-of-sample D is
  what judges it.
- Only settled orders count; TEST orders on games not yet final are absent.

## Coverage, measured before this pre-registration was pushed (counts only, no outcome)

**Per-family date coverage and the intersection.**

| family | dates | first | last | gaps |
|---|---|---|---|---|
| orders (population, submit UTC date) | 49 | 2026-10-02 | 2026-11-19 | none |
| `book_quotes` shards read | 49 | 2026-10-02 | 2026-11-19 | none |
| orders with a consensus capture age | 26 | 2026-10-25 | 2026-11-19 | none |
| orders with n_books >= 1 | 49 | 2026-10-02 | 2026-11-19 | none |
| orders with a venue move | 26 | 2026-10-25 | 2026-11-19 | none |

- **Intersection: 26 dates, 10-25..11-19.** The study rests on FIT 10-25..11-07 (14 dates) and TEST 11-08..11-18
  (11 dates). The 3,142 orders before the first heartbeat (509 events) are outside both windows; 11-19 (124 orders)
  is the gap.

**Feature availability by window and book (orders).**

| window / book | orders | events | won/lost | pin_age | cons_age | n_books | n_books >= 1 | disp | t_start | price | vmove | ev |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **FIT** | **8,684** | **723** | 8,659 | 7,239 | 8,654 | 8,345 | 7,885 | 7,729 | 8,684 | 8,684 | 3,108 | 8,684 |
| FIT, ladder | 8,033 | | 8,008 | 6,665 | 8,005 | 7,735 | 7,313 | 7,176 | 8,033 | 8,033 | 2,782 | 8,033 |
| FIT, live | 406 | | 406 | 339 | 404 | 377 | 345 | 341 | 406 | 406 | 181 | 406 |
| FIT, paper twin | 245 | | 245 | 235 | 245 | 233 | 227 | 212 | 245 | 245 | 145 | 245 |
| **TEST** | **9,445** | **802** | 9,388 | 6,869 | 9,444 | 9,419 | 9,132 | 8,965 | 9,445 | 9,445 | 3,981 | 9,445 |
| TEST, ladder | 8,602 | | 8,548 | 6,204 | 8,601 | 8,580 | 8,336 | 8,186 | 8,602 | 8,602 | 3,563 | 8,602 |
| TEST, live | 629 | | 628 | 478 | 629 | 625 | 586 | 573 | 629 | 629 | 288 | 629 |
| TEST, paper twin | 214 | | 212 | 187 | 214 | 214 | 210 | 206 | 214 | 214 | 130 | 214 |

- In percent: FIT pin_age 83%, cons_age 100%, n_books 96%, disp 89%, vmove 36%; TEST pin_age 73%, cons_age 100%,
  n_books 99.7%, disp 95%, vmove 42%. t_start, price and ev are 100% everywhere.
- **Venue-move classes (feature values, not outcomes)**, by reference: FIT toward 480 / flat 1,898 / away 184 on the
  Pinnacle reference and 114 / 329 / 103 on the consensus reference; TEST 278 / 1,702 / 80 (Pinnacle) and
  337 / 1,149 / 435 (consensus).
- **Per submit date** (orders; pin_age / vmove known): 10-25 285 (253 / 83), 10-26 912 (786 / 277), 10-27 517
  (481 / 177), 10-28 771 (682 / 171), 10-29 454 (435 / 178), 10-30 622 (491 / 124), 10-31 464 (433 / 170), 11-01
  571 (495 / 248), 11-02 729 (669 / 213), 11-03 459 (365 / 227), 11-04 700 (560 / 170), 11-05 730 (511 / 414),
  11-06 685 (482 / 282), 11-07 785 (596 / 374) | TEST 11-08 768 (637 / 363), 11-09 1,079 (854 / 389), 11-10 985
  (643 / 459), 11-11 952 (745 / 341), 11-12 809 (583 / 434), 11-13 870 (612 / 320), 11-14 1,078 (744 / 540), 11-15
  794 (623 / 285), 11-16 648 (542 / 185), 11-17 605 (329 / 329), 11-18 857 (557 / 336). No date is missing.
- **Drops** (all windows): ladder in game 4,830, duplicate position 4,380, unsettled 2,310; paper twin in game 523,
  duplicate 427, unsettled 65; live no event_id 552, in game 422, not filled 118, unsettled 57, no times 30, no
  stake 2.
- The FIT population matches S1's exactly (8,684 orders), as it should: same population, same window.
