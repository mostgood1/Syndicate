# PRE-REGISTRATION -- is the SGP builders' `p_joint` miscalibrated on settled tickets? (lane `sgp-pjoint-calibration`, 2026-10-27)

Written and committed **before any outcome join**. Before this commit I read only the ledger's schema: field names,
date ranges, and ticket counts by family, tier and size (`C:\tmp\sgpcal\schema.py`, 14:18Z). I did not read any
ticket or leg result, and I computed no hit rate. OFFLINE and read-only on production. No deploy, restart or env edit.

## Why, and what is already known (disclosure)

E4's `c-ledger` table (`findings_2026-10-26_e4_combo_correlation.md`) was **descriptive and not pre-registered**. It
showed `p_joint` 3-6 points above the realised all-legs-won rate:

| Sport | Tickets / games | Realised | Mean `p_joint` |
|---|---|---|---|
| NHL | 601 / 63 | 19.5% | 22.8% |
| NBA | 226 / 31 | 42.0% | 45.0% |
| NFL | 149 / 23 | 26.2% | 32.0% |

The cheat-sheets lane's nightly `SGP_PAPER` lines also print the same aggregate.

- **That lead read the same tickets this test reads**, through ticket dates of 10-25. So the primary test below is a
  pre-specified **confirmatory re-analysis of data that already suggested the effect**. It is NOT an independent
  replication.
- Tickets dated **2026-10-26** were graded after E4 ran. They are reported separately as the unseen slice.
- **The independent test is the registered forward read (§8).**

## 1. Data

- **Source:** fleet `~/syndicate-prod/data/cheatsheets/<sport>/sgp_ledger.jsonl` and `sgp_graded.jsonl`, for
  `<sport>` in nhl, nba, nfl, wnba and mlb. No other sport has a ledger.
- **Snapshot:** copied once to `C:\tmp\sgpcal\snap\`, with each file's sha256 and mtime recorded. All analysis runs on
  the snapshot.
- **The ledger** (`nfl/sgp.py:787` `ledger_records`) holds each ticket as first suggested:
  - `p_joint` and `p_independent`;
  - per leg: `p_market` (side-relative de-vigged market), `p_over` (the consistency posterior's P(over)), `side`,
    `line`, `hits`, `games`, `role`, `market`, `alt`.
- **The graded file** (`scripts/grade_sgp_paper.py`, the rule in `cheat_sheets.sgp_results`) holds each ticket's
  `status` and each leg's `result`.
- **Join:** `sgp_id`, ledger first occurrence. A graded `p_joint` that differs from the ledger's is counted and reported.
- **Freeze:** ticket `date` <= **2026-10-26**. The graded file is the 2026-10-27 ~04:56Z nightly.
- **Who sees what:** the page serves `family == "hit_rate"` only (`build_cheat_sheets.py:1048`). The correlation
  family goes to the ledger only. So the "shown to users" subset is the hit-rate family.

## 2. Population -- primary is CLEAN, not as-graded

The grader's rule is: LOST if any leg lost, else VOID if any leg void (a DNP or a push), else WON if every leg won.
A ticket with a void or pending leg can therefore be LOST but never WON. **Counting the grader's "settled" tickets
censors asymmetrically, toward a lower hit rate.** That is a candidate source of the lead's gap that has nothing to do
with the model.

- **PRIMARY population ("clean"):** status won or lost, AND every leg's result is won or lost. `p_joint` is the
  probability that every leg wins given every leg is played, which is also how books void an SGP leg.
- **SECONDARY ("as-graded"):** status won or lost, as the lead and the nightly print count them.
- `G_censor` = CITL(as-graded) - CITL(clean) is reported as the grading-censoring component.

## 3. Primary test (gated)

`y` = 1 if the ticket won, `p` = its `p_joint`.

- **CITL** (calibration-in-the-large) = mean(`p`) - mean(`y`). **Positive means over-prediction.**
- **Game-clustered SE:** cluster = (sport, `event_id`).
  `SE = sqrt(G/(G-1) * sum_g (sum_{i in g} (p_i - y_i))^2) / n`. This is `grade_sgp_paper.summarize`'s own estimator,
  so this test and the nightly print agree on method. Two-sided normal p-value.
- **Robustness:** a game-cluster bootstrap percentile CI (2,000 resamples, seed 20261027) is printed beside it. If the
  two disagree about excluding 0, that is stated.
- **Family:**
  - **P1** pooled over all 5 sports;
  - **P2** NHL, **P3** NBA, **P4** NFL (each has >= 20 settled games);
  - WNBA (~4 games) and MLB (~5 games) are reported and not gated.
- **Holm at alpha 0.05 over P1-P4.**
- **Verdicts:**
  - **MISCALIBRATED (OVER or UNDER)** when the Holm-adjusted test rejects.
  - **NOT SHOWN** otherwise. It is then reported with the 80%-power minimum detectable gap, `MDE = 2.80 x SE`, so a
    null is never read as "calibrated".
  - **"The gap is real"** iff at least one of P1-P4 rejects.

## 4. Slope (registered, secondary -- not in the verdict family)

- Logistic recalibration `logit P(y) = a + b * logit(p)`, per sport and pooled. Estimated by IRLS, with a
  game-clustered sandwich SE on `b`. Tested against `b = 1`.
- Also the logit-scale CITL: `a0` in `logit P(y) = a0 + offset(logit p)`.
- Why it is secondary: `p_joint` spans a narrow range in each family (the hit-rate tiers sit at 0.28-0.6), so `b` is
  weakly identified at these n.

## 5. Breakdowns (descriptive, game-clustered CIs, no multiplicity claim)

Per sport and pooled, by:
- leg count (2-6);
- family (`hit_rate` = served, `correlation` = ledger-only, none = NHL's pre-family tickets);
- tier (safer / payout);
- relation (same_player / teammate / opponent / mixed);
- `p_joint` decile (a reliability table);
- date slice (<= 10-25, seen by the lead, vs 10-26, unseen).

## 6. Decomposition (computed for every sport; read as ATTRIBUTION only where §3 rejects)

### 6a. Ticket arms

- **A** = product over legs of `m_i`, where `m_i` = the leg's recorded side-relative `p_market`. This is the market
  with independent legs.
- **B** = product over legs of `q_i`, where `q_i` = side-adjusted `p_over` (`p_over` for over/yes, `1 - p_over` for
  under). This is the consistency posterior with independent legs. It must reproduce the ledger's `p_independent`
  within 0.002 on >= 99% of tickets; failures are reported.
- **C** = `p_joint`.
- **Identity:** `G_C = G_A + D_nudge + D_copula`, where `G_X` = mean(`X`) - mean(`y`), `D_nudge` = mean(`B - A`) and
  `D_copula` = mean(`C - B`). Each term gets a game-clustered CI.
- **Paired log loss**, game-clustered: `LL(B) - LL(A)`, `LL(C) - LL(B)`, `LL(C) - LL(A)`.
- Tickets with any leg missing `p_market` are excluded from 6a only (counted).

### 6b. Legs -- the marginals and the de-vig

- **Unique legs:** dedup on (sport, date, `event_id`, player, market, side, line). Result must be won or lost. The
  first occurrence's fields are kept.
- **Measures, game-clustered:**
  - `g_m` = mean(`m`) - mean(`y_leg`);
  - `g_q` = mean(`q`) - mean(`y_leg`);
  - paired `LL(q) - LL(m)`.
- **By:** sport; pool legs (`alt` true: gate-selected alt rungs de-vigged by the main-line margin,
  `sgp_hit_rate.market_prob`) vs sheet-row legs; `p_market` band (<.55, .55-.65, .65-.75, .75-.80, .80-.85, .85-.90,
  .90-.95, >.95); record hits (<=7, 8, 9, 10 of 10); market.
- **Leg logistic recalibration** `logit P(y_leg) = alpha + beta * logit(m)`, per sport.

### 6c. Pairs -- the copula

- **Unique within-ticket leg pairs** where both legs are won or lost.
- **Correlation:** reconstructed with `syndicate.features.nfl.sgp.rho_for` on the sport's correlations file and the
  sport's own type labels (`market|role`; basketball `code|role`), signed by side.
- **Reconstruction gate:** re-pricing every ticket with `nfl.sgp.ticket_joints` from the ledger's legs must reproduce
  the ledger's `p_joint`:
  - within 0.002 for size 2 (exact);
  - within 0.01 for size >= 3 (quasi-Monte Carlo);
  - on >= 95% of that sport's tickets.

  A sport that fails is reported as **NOT RECONSTRUCTED**, and its copula attribution rests on `D_copula` alone.
- **Marginals = `m`** (market-anchored, as in E4); repeated with `q`.
- **Measures, game-clustered, by relation:**
  - `P_c` = the copula's P(both win), `P_i` = `m_a * m_b`;
  - excess `mean(y_a y_b) - mean(P_c)` and `mean(y_a y_b) - mean(P_i)`;
  - 4-cell log loss `D_K = LL(copula) - LL(independence)`. Negative means the copula is better.

### 6d. The 18.5% haircut -- a code reading, registered as such

`ASSUMED_BOOK_DISCOUNT` enters `est_dec` / `est_ev_pct` only (`nfl/sgp.py:447,460,568,577`). `p_joint` is computed
before it and without it (`sgp.py:433`, `559-560`; `sgp_hit_rate.tickets`).

- **Its only route to calibration is selection:** correlation-family pairs are ranked by `est_ev_pct`
  (`sgp.py:466,477`).
- **That ranking does not depend on the discount:** `est_ev_pct = (p_joint * product * 0.815 - 1) * 100` is monotone
  in `p_joint * product`. The discount changes the order only where the flat +5-point same-player term meets the
  rescaled spread.
- **Predicted contribution: 0.** Reported with the correlation-family size-2 CITL. If the code reading is wrong, the
  findings say so.

### 6e. Attribution rule (for a rejecting sport with OVER-prediction; mirrored for UNDER)

1. **Grading censoring** is a source iff `G_censor > 0` with its CI excluding 0.
2. **Marginals (market price / de-vig)** are a source iff `G_A > 0` with its CI excluding 0 (tickets), or `g_m > 0`
   with its CI excluding 0 (legs).
3. **The consistency nudge** is a source iff `D_nudge > 0` AND the paired leg `LL(q) - LL(m) > 0` with its CI excluding
   0. If `D_nudge > 0` but the leg test is null, it is reported as "adds `D_nudge` mechanically; not shown wrong".
4. **The copula** is a source iff `D_copula > 0` AND either:
   - `D_K > 0` with its CI excluding 0; or
   - the pair excess `mean(y_a y_b) - mean(P_c)` is below 0 with its CI excluding 0, while the independence excess's
     CI covers 0.
5. **The haircut:** 0 unless §6d's reading is falsified.
6. **Residual** = `G_C` minus the flagged terms, reported as unattributed (selection, multi-leg structure).
7. **Shares:** each term is reported as a fraction of `G_C`, with a game-bootstrap CI, only where `G_C`'s CI excludes 0.

## 7. Correction (registered procedure; per line ONLY)

A correction is proposed only for a component flagged in §6e. Each candidate changes **one leg's or one pair's own
probability**. Under no outcome is a market-, family- or sport-level pause, switch or exclusion proposed (user
standing rule: every line is its own decision).

- **De-vig:** a per-leg recalibration of the market probability, `logit m' = alpha + beta * logit m`. Fitted per sport,
  or pooled with sport intercepts where a sport has fewer than 300 settled unique legs.
- **Nudge:** the prior strength `k` refitted by leg log-likelihood on the grid {10, 20, 40, 80, 160, 320, infinity}.
  Infinity means the market alone.
- **Copula:** each pair's rho scaled by `lambda` on the grid {0, 0.1, ..., 1}, fitted on the settled pairs.
- **Validation:** leave-one-date-out (fit on every other date, score the held-out date), game-clustered. A candidate
  is **RECOMMENDED** only if both hold:
  - (i) its out-of-fold leg (or pair) log loss improves, with a CI below 0;
  - (ii) the out-of-fold ticket-level CITL CI contains 0 **on the subset it will be applied to**, the served
    `hit_rate` family. This is required by learnings 2026-09-21: never adopt a whole-population fit without checking
    the acted-on subset.

  Otherwise it is "fitted, not validated".
- **Implementation belongs to the owning lane**, not this one. The leg and ticket code is in
  `syndicate/features/{nfl,nhl}/sgp*.py`, `shared/sgp_hit_rate.py`, `shared/*_sgp_pool.py` and `shared/cheat_sheets.py`
  (`consistency_posterior`). Those came from the closed `*-sgp-builder` lanes and live on under `cheat-sheets`
  (session 9e18a0e7). This lane proposes; it edits none of them.

## 8. Forward read (the independent test)

Re-run the same script, with these constants unchanged, on tickets dated >= **2026-10-27**. The trigger is NHL, NBA and
NFL each reaching >= 30 new clean settled games, or 2026-11-24, whichever comes first. That read gets the same §3 rule
and the same Holm family.

## 9. Coverage print (required in the findings)

Per sport:
- ledger dates (first .. last, n);
- tickets ledgered, graded, won / lost / void / pending;
- clean settled tickets and games;
- unique legs with a result;
- legs with `p_market`;
- pairs reconstructed;
- the 10-26 unseen slice's n.

The n behind every number is printed beside it.

## 10. Implementation choices registered here

- Probabilities are clipped to [1e-6, 1 - 1e-6] for log loss.
- A leg's side probability: `p_over` for over or yes, `1 - p_over` for under.
- NHL's 28 tickets with no `family` are in the primary. A robustness run without them is printed.
- `relation` for re-pricing is `nfl.sgp.relation_of` (same player / same team / opponent), which every builder uses.
- Code: `scripts/sgp_pjoint_calibration.py`, with hermetic tests, including a reachability test that the clean filter
  changes the population on a fixture with a void leg. Committed before the run. Any change to a choice above after
  this commit is an amendment, committed before the join.
