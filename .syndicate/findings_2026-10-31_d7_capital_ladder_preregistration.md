# D7 capital ladder: pre-registration DRAFT `[2026-10-31, lane syndicate-decision-engine, plan #736 decision D7]`

**Status: DRAFT. The user has not adopted it yet.** The user asked for it, verbatim: "Yes, draft D7". Edits made
before the first canary order of a strategy that passed the gate are edits to this draft. After that order, any
change is a new registration and must be named as one.

**Plan D7, verbatim:** "Capital ladder: pre-register how stake bands grow once a strategy passes the edge gate.
Example: double the band after each further 400 bets with the CLV and ROI CIs still above 0, with a drawdown stop
that drops back one rung." The recommendation was "Yes, write it before Phase 2 ends". It was adopted on 10-26 with
D1–D8.

**Written before any data it judges exists.** No strategy has passed the Phase 2 edge gate, and no laddered bet
exists. Before writing this I read:
- the plan;
- the Phase 2 pre-registration (`findings_2026-10-26_decision_policy_v1_preregistration.md`, `8d16ab07`);
- `live_stake_band.py`;
- the live sizing chain in `state_portfolio.md`;
- the edge-gate clock reading (log 2026-10-30 23:15Z, counts only).

The calibration (§6) uses two published aggregates and nothing else. I opened no live order, paper bet, grade or
ledger.

## 0. Scope

- **Who it applies to.** It covers only a strategy that has done all three of these:
  - passed the Phase 2 edge gate (prereg §7);
  - shown no CLV/ROI CONTRADICTION at its pass;
  - been given the user's yes to canary live (D2 and D6).
  P1 `ev_lb` and P2 `net_floor_719` are the strategies today. A later strategy, such as the E2 maker, enters only
  through its own registered gate, and these rules then apply to it unchanged.
- **Nothing changes now.** Rung R0 is today's live band.
- **No cap is raised.** These all still run after the band:
  - the executor caps ($100/order ceiling, the per-venue and all-venue day ceilings);
  - the balance caps (25% a day and 5% an order of venue capital);
  - the per-event and axis caps.
- **The ladder sizes. It never selects.** Every line is still its own decision. No market, family or sport is
  switched off.
- **In-play is out of scope.** It belongs to E7 and the in-play program.

## 1. The rungs

| Rung | Band (min–max) | Favourite max loss | Funding capital needed per venue |
|---|---|---|---|
| **R0** (canary) | $5–$10 | $5 | none: the user's measurement band (10-20) |
| **R1** | $10–$20 | $10 | $2,000 |
| **R2** | $20–$40 | $20 | $4,000 |
| **R3** (top of this registration) | $40–$80 | $40 | $8,000 |

- **Doubling:** each rung doubles the band, and the favourite cap's maximum loss is the rung's minimum.
- **Unchanged on every rung:**
  - the band formula: `min + (max − min) · full_kelly / 0.05`, capped at max;
  - the refusal shorter than −1000 and the favourite line at −200;
  - the small-edge line;
  - every executor cap.
- **The top:** going past R3, or past the $100/order ceiling, needs a new registration and the user's decision.
- **Funding capital** is the venue capital that the compounding step stamps (`compounding.capital`), which is the
  number the balance caps already use. A rung above R0 needs **max ≤ 1% of it** at every venue the strategy trades.
- **Why 1%.** Across the live price band (0.40–0.75), with the sizer believing a 2% edge, the band's average stake
  is 0.80 × max, so about 0.8% of capital.
  - At a 55c price, full Kelly is 2.44% at a 2% edge and 1.22% at a 1% edge.
  - So the average stake is a third of Kelly if the edge is as believed, and two-thirds if it is half that.
  - This is the plan's "fractional Kelly shrunk for estimation error" (§10).
- **Today's capital funds no rung above R0.** At the 10-19 reading, Kalshi held about $465 and Polymarket about
  $586. I did not re-read either. So the ladder says when the evidence supports a bigger stake, and whether to fund
  it is the user's decision.

## 2. Three rung values per strategy: earned, funded, live

- **earned.**
  - It moves up one rung only after a rung read PASSES (§4) and the user says yes.
  - It moves down one rung on the edge stop (§5).
- **funded** is the highest rung the funding capital meets at the day's first read. R0 is always funded. A drop in
  funding loses no evidence.
- **live** = `min(earned, funded, breaker)`.
  - `breaker` is R0 for 14 days after a loss stop (§5).
  - Otherwise `breaker` places no limit.
  - The live rung sets the four band keys: `SYNDICATE_LIVE_STAKE_BAND_MIN_DOLLARS`, `_MAX_DOLLARS`,
    `SYNDICATE_LIVE_BAND_FAVOURITE_MAX_LOSS`, and `SYNDICATE_LIVE_STAKE_BAND=on`.
- **Which bets count.** A bet counts toward the read of its rung only when it was placed with live == earned, so
  that the stake under test is the one used. Bets placed while the strategy was held below its earned rung are
  reported but count toward no read.
- **Re-entry.** A rung re-entered after an edge-stop demotion starts a fresh read. Bets from before the demotion do
  not count.

## 3. Population and grading (inherits Phase 2 §6)

- **Population.** The strategy's live pregame fills, each tagged with the strategy id and its DecisionRecord.
- **CLV.** `CLV_net` per bet is `100 · (p_close / c − 1)`.
  - `c` is the **fill** price plus the fee actually charged. Slippage is therefore inside it, which is what a
    bigger rung has to survive.
  - `p_close` is Pinnacle's last pregame two-sided pair at the bet's own line, power de-vigged, using Phase 2's
    rule exactly.
  - A bet with no Pinnacle close is outside the CLV population. It is counted and reported by sport and market
    family.
- **ROI.** Return per dollar staked, fee-net, settled by the venue, flat per bet, over **all** of the strategy's
  settled live bets, props included. The venue settles props, unlike the paper track, which has no prop grader.
- **Statistics.** These are Phase 2 §7's:
  - game-clustered SE: `SE² = G/(G−1) · Σ_g (Σ_{i∈g} (x_i − x̄))² / n²`, with `Z = x̄ / SE`;
  - a game-clustered bootstrap 95% CI (2,000 resamples, seed 20261031) is reported and is never decisive.

## 4. Promotion: one rung up

A rung read uses the counted bets at that rung (§2).

| Look | Sharp-graded bets | Games | CLV Z must be ≥ |
|---|---|---|---|
| L1 | ≥ 400 | ≥ 100 | **3.471** |
| L2 | ≥ 800 | ≥ 200 | **2.454** |
| L3 (last) | ≥ 1,200 | ≥ 300 | **2.004** |

- **Boundaries.** O'Brien–Fleming, one-sided α = 0.025: the textbook values that the Phase 2 prereg reproduces.
  Under the null, simulated α is 0.025. Each strategy's ladder is its own test, so there is no Bonferroni split.
- **Realization check, at every rung.** The upper bound of the cumulative live ROI's 95% CI (all settled live bets
  since canary) must be **at or above** the cumulative mean `CLV_net`.
  - If it falls short, that is a **REALIZATION SHORTFALL**: the money is significantly below what the close
    implied. There is no promotion, and the user is told.
  - The two sides cover different populations: CLV covers sharp-graded bets, ROI covers all bets. So a shortfall
    can also mean the bets we cannot grade are the ones losing. Either reading is worth knowing.
- **R2 → R3 only: ROI above 0.** At each of R2's looks, the cumulative ROI Z must also clear that look's boundary.
  This is the plan's "ROI CI above 0", applied at the rung where the stakes are largest.
- **A pass ends the rung read.**
  - The evaluator reports PASS.
  - The move up needs the user's yes, and the next rung must be funded. If it is not funded, the read reports
    **EARNED, NOT FUNDED**.
- **No pass by L3 means HELD.** The strategy stays at that rung, and this registration allows it no further
  promotion. A new registration may.

## 5. Demotion

**If the user adopts this section, it is pre-authorised:** each stop is applied at the read that finds it, without
waiting for an answer, and the user is told. Promotions always wait for the user.

- **Edge stop: earned drops one rung.**
  - **Trigger:** at a weekly read with ≥ 200 sharp-graded counted bets at the current rung, CLV Z ≤ −2.0.
  - **At R0:** the strategy goes back to paper.
  - **Calibration** (weekly reads from 200 to 1,200 bets):

    | True CLV | Chance the stop fires |
    |---|---|
    | +1pp | 0.05% |
    | +0.5pp | 0.7% |
    | 0 | 9.6% |
    | −0.5pp | 57% |
    | −1pp | 96% |

- **Funding stop: funded is recomputed daily.**
  - When capital sits near a threshold, a loss moves the strategy down a rung by itself. That is D7's "drawdown
    stop that drops back one rung".
  - It comes back up when the capital does.
- **Loss stop: breaker = R0 for 14 days.**
  - **Trigger:** the strategy's realised loss over the trailing 7 days is ≥ 20% of its funding capital at the
    start of that window.
  - **After 14 days:** live returns to `min(earned, funded)`, unless the edge stop fired in the meantime.
  - **Calibration**, over 14 weeks at 1% funding:

    | True ROI | At 10 bets/day | At 20 bets/day |
    |---|---|---|
    | +2% (false triggers) | 0.6% | 14% |
    | −8% (detections) | 16% | 94% |

  - It is a circuit breaker for breakages, such as a sizing bug or a venue mispricing at size. It is not an edge
    detector; the edge stop is.
- **Incidents.** A venue kill switch or an identity-guard incident on one of the strategy's live orders sets live
  to R0 until the user clears it.

## 6. Calibration (`scripts/capital_ladder_calibration.py`, seed 20261031, `--fund 0.01`)

**The two per-bet spreads come from published aggregates:**
- **CLV, 9.88pp per bet:** the Suggested grade's EV at the Shin close was +1.51% [+0.63, +2.44] (95% by game) on
  457 bets (`findings_2026-10-26_suggested_grade.md`).
- **ROI, 113.8pp per bet:** the live Kalshi pregame book was −11.8% [−20, −4], **CI90** by game, on 548 bets
  (`findings_2026-10-24_live_cell_scorecard.md`).

The clustering is inside both spreads. The loss-stop simulation draws independent bets in the 0.40–0.75 price band.

**The CLV rung read: chance it has passed by L1 / L2 / L3**

| True CLV | 0 | +0.5pp | +0.75pp | +1pp | +1.5pp | +2pp |
|---|---|---|---|---|---|---|
| L1 | 0% | 0.7% | 2.5% | 7% | 33% | 72% |
| L2 | 0.7% | 16% | 38% | 66% | 97% | 100% |
| L3 | 2.4% | 41% | 74% | 94% | 100% | 100% |

**Why ROI above 0 is required only for R3.** The chance a cumulative ROI test has passed by L1 / L2 / L3, with 28%
of bets sharp-graded (today's paper share):

| True ROI | Recommended (R2 → R3, cumulative) | Literal reading (every rung, from R0 → R1) |
|---|---|---|
| +2% | 1 / 13 / 31% | 0.2 / 7 / 20% |
| +3% | 4 / 32 / 59% | 1 / 15 / 40% |
| +4% | 12 / 58 / 84% | 2 / 28 / 62% |

Read literally, the plan's example would hold a true 2–3% edge at R0 most of the time. With half the bets
sharp-graded, ROI power is lower still (+3%: 25% by L3 at R0 → R1), because there are fewer ROI bets for each
sharp-graded one.

## 7. Pace

- **Paper P2:** about 11 sharp-graded bets a day out of about 40 booked (10-27..10-29, log 10-30 23:15Z), a 28%
  sharp share.
- **If live matches paper:** a rung's L1 is about 5 weeks and its L3 about 16 weeks. The day caps and missed fills
  can only make that slower.
- **The lever** on the sharp share is D5 (lane `pinnacle-coverage-d5`).
- **Earliest R1:** P2's first edge-gate look could come in early December (the 10-30 clock reading). That puts R1
  no earlier than mid-January.

## 8. Prerequisites

None of these exists today. All must exist before the first canary order of a laddered strategy, or R0's bets
cannot be read.

1. **Tagging.** Every live order carries the strategy id, its DecisionRecord build id and its order instant
   (Phase 0's join).
2. **A live grader:** CLV at the fill price plus the fee charged against the Pinnacle close (Phase 2 §6), and
   venue-settled ROI.
3. **A ladder evaluator.**
   - It reads looks, stops, and the earned, funded and live rungs, and writes a dated read.
   - It needs hermetic tests, including a reachability test (`off != on`), a held-rung test and a test for each
     stop.
4. **Band scope.** The band must reach only the laddered strategy's orders: either a per-strategy band
   configuration, or a live book that holds only that strategy. Today the band is one global setting, so a rung
   above R0 would also resize every other live order.
5. **Funding log.** The funding capital per venue is read and logged daily.

The owner is whoever takes the canary step (D2's live step). Until a lane holds it, the umbrella lane carries it.

## 9. Known biases, stated before the data

- **Depth.** A bigger stake walks the book. Fill CLV captures that, which is why every rung is re-read live
  instead of carried over from paper.
- **Uneven sharp coverage.** 72% of graded paper bets had no Pinnacle close from 10-27 to 10-30. The read rests on
  whatever mix is sharp-graded, and is reported by sport and market family.
- **Season phase.** A read can span preseason, regular season and playoffs. Results are reported by sport and phase
  but are never decisive.
- **Calibration inputs** come from other books (the Suggested set, the live Kalshi book) and from independent bets.
  The real spreads of a passing strategy will differ. The boundaries do not depend on them; the power figures do.

## 10. Reads and moves

- **Read cadence.** Weekly rung reads (Mondays) and daily funding and loss checks. They go into `#717`'s register at
  the canary step, so that no read rests on a one-time task.
- **Every rung move is one fleet environment change** to the four band keys:
  - made behind the deploy locks;
  - with `--expect` naming the keys;
  - with its measurement (the first `STAKE_BAND` line at the new band) recorded in `deploys.md`.

## 11. Decisions owed by the user

1. **Adopt this draft as written.**
2. **ROI rule.** Recommended: ROI above 0 is required only for R2 → R3, with the realization check at every rung.
   The literal alternative requires it at every rung; see §6 for what that costs.
3. **Funding at 1% of venue capital.** Recommended. At 1.5%, R1 needs $1,333, but the loss stop gets noisier. Even
   with the stop raised to 25%, a true +2% edge trips it 5% of the time at 10 bets a day and 34% at 20 a day.
4. **Pre-authorised demotions** (§5). Recommended. The alternative is to ask each time, which leaves a losing
   strategy at size while the question waits.
