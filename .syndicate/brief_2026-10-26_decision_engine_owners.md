# Decision Engine — owner briefs `[2026-10-26, lane syndicate-decision-engine]`

**Why this file exists:** the briefs below were sent as cross-session messages on
2026-10-26 ~16:40Z. Five of six were **HELD, not delivered** (the recipient sessions
run in a different permission mode). This file is the durable copy. If you own one
of the lanes below, the section with your lane's name is addressed to you.

**User, verbatim (2026-10-26, session "Syndicate AI decision engine"):**
"Adopt the decision-engine plan with the recommended D1-D8. Open the umbrella lane,
brief the owner sessions, and start Phase 0."

- Plan: `docs/ai_context/plan_syndicate_decision_engine.md`.
- Decisions D1–D8: `.syndicate/state.md` `[user-decisions]` 2026-10-26.
- Umbrella lane: `syndicate-decision-engine`. It claims no code and holds none of
  your files.
- Route any USER decision this plan needs to the session "Syndicate AI decision
  engine", with the options and your recommendation.

Standing constraints on every item:
- Nothing changes the staked probability before `#704`'s 11-02 keep/revert read.
- One change per deploy, with the measurement in `deploys.md`.
- Every line stays its own decision; no market-level switches.

---

## `decision-record-shadow` (`#709`)

1. **D3, Phase 0.** In `decision_record.py`, change `DEFAULT_MODEL_WEIGHT` 0.25 → 0 on
   unmeasured cells, and use w\* only where its CI lower bound is above 0. `:693`
   currently takes the point estimate for `not_proven` cells; that should be 0 as well.
   The effect is shadow-only.
   - Reason: the measured sim weight is w = −0.27 [−0.78, +0.18] on 4,876 orders (`#704`).
2. **D2, Phase 2.** Build step 3 (`#719`): venue-native selection and sizing on fee-net
   EV at the venue's own ask.
   - Run it in a **paper2** track first.
   - Canary live only after the Phase-2 edge gate: fee-net CLV vs the sharp close > 0,
     game-clustered CI, at ≥400 bets / ≥100 games.
   - Use the `#719` floors (Kalshi 1.0 / Polymarket 0.5) until a lower-bound EV exists.
   - Phase 1 (`fair-price-v2`) adds `p_fair` and `σ_fair` to the record.
3. When D3 lands, put its SHA in lane `syndicate-decision-engine`.

## Portfolio coordinator (session "Kalshi/Polymarket portfolio endpoint")

- **D6.** Live capital stays at CANARY until a strategy passes the Phase-2 edge gate.
  Do not widen the stake bands before then.
- **D7.** A capital ladder is pre-registered before Phase 2 ends. It sets how bands
  grow as evidence accrues, plus a drawdown step-down. Proposed owner:
  `live-cell-scorecard` (profitability program). Confirm or reassign.
- **E1** (the Pinnacle forward test) is the main input to the Phase-2 gate. **E2**
  (maker shadow) and **E7** (in-play) stay with their owners, unchanged.

Phase 0 readings, fleet, read-only, 2026-10-26 16:31Z, via `full_history_orders()`
with the live-odds-worker store env:

- **Live in-play entries** (`position_key` `ingame:`), 10-23 23:38Z → 10-26 01:20Z:

  | day | orders | fills | staked | P&L |
  |---|---|---|---|---|
  | 10-23 | 23 | 21 | $8.76 | −$0.81 |
  | 10-24 | 33 | 28 | $11.59 | −$2.53 |
  | 10-25 | 61 | 46 | $20.81 | −$0.61 |
  | 10-26 | 7 | 7 | $3.21 | −$0.60 |
  | **total** | **124** | **102** | **$44.37** | **−$4.55** |

  Fees totalled $1.73. Fills by sport: NBA 53, NFL 24, NCAAF 18, NHL 5, MLB 2.
- **`#722` provenance** (`966e0b5f`) is loaded on every role: web and refresh-worker
  `6dd8a536`, live-odds-worker `1a841c91`.
  - Since 10-21 22:00Z, 117 of 241 live orders carry `staked_probability_version`. The
    other 124 are exactly the `ingame:` orders above, which bypass the plan sizer by
    design and are attributable by prefix.
  - Paper: 2,332 of 6,119 carry it. 3,787 paper orders since then carry none; their
    source path is unidentified.
  - The stamped prefixes confirm `#704` market mode is in effect:
    `market_fair@staked_probability_pooled_v1@2026-10-22T21` on 94 live and 1,631 paper
    orders.
- **Paper backlog:** 1,896 FILLED paper orders have no outcome more than 48h after
  submit: NCAAF 1,102, soccer 478, NFL 123, MLB 104, NBA 76, NHL 7. Live: 5 NBA
  `ingame:` and 1 soccer.
  - Some of these are forward bets on games not yet played, so the true backlog needs a
    count by GAME date.
  - **Which lane owns paper settlement?**
- **Missed dispatches at 16:3xZ:**
  - three one-time tasks are past their fire time and never ran:
    `layer2-suggested-grade-1026`, `clv-openings-ceiling-forward-reading` and
    `uefa-branding-autorefresh-reading-1022`;
  - `nba-standin-admission-watch` (twice daily) last ran 10-24 21:47Z.

## `live-cell-scorecard` (profitability program)

1. The Phase-2 edge gate is read from your scorecard. Can it report fee-net CLV against
   the SHARP (Pinnacle) close, per strategy? If not, what would it take?
2. E1 is your pre-registered Pinnacle forward test (10-25). Nothing changes; the plan
   depends on its read.
3. D7: pre-register the capital ladder before Phase 2 ends. Example: double the band
   after each further 400 bets with the CLV and ROI CIs still above 0, and step back one
   rung on a drawdown stop.
4. D6: canary only until the gate.
- Hands off `live_cell_gate.py`, the scorecard script and the gate hook: they stay yours.

## `in-game-trading` (in-play program)

In-play is entirely yours, as E7. D6 keeps live at canary, and the 1-contract entries
already sit inside that. The live `ingame:` table is in the coordinator section above.
The plan's later per-strategy allocator needs no field change, because the `ingame:`
prefix already identifies the strategy.

## Layer 2 grading (session "Layer 2 board assessment and optimization")

- The user's 10-26 keep-2% decision stands.
- The plan's **challenger** Suggested flag (lower-bound EV > 0 at the best executable
  price, plus the gates) only exists after Phase 1 (`σ_fair`) and Phase 2. It is **not**
  in the 10-31/11-01 re-grade, so grade that weekend as planned.
- `layer2-suggested-grade-1026` never dispatched. Put the 10-31/11-01 date in `#717`'s
  dated-reads register, so it never rests on a one-time task alone.

## `fair-price-v2` (Phase 1)

Phase 1 is a learned, sharpness-weighted fair (weights by book × sport × market family ×
time-to-start × quote age) carrying its own `σ_fair`. It is fitted to the sharp close and
to outcomes, and written into the DecisionRecord in shadow.

- Gate: held-out log loss below the Shin consensus with a CI below 0, per sport family.
- Fallback order, with σ widening at each step:
  1. sharp book;
  2. weighted consensus;
  3. an identity-checked two-sided venue mid;
  4. the margin model, flagged as one-sided.
- Also: a price surface for derived markets (E3).
- This does not disturb the H6 scoring from 10-30.

## `kalshi-maker-shadow-paper` (E2)

No change. A news-cancel arm will be proposed after Phase 4 builds the availability bus.

## `news-availability-gate` (Phase 4, E5)

Phase 4 is an availability event bus driven by official schedules. Each event triggers,
in order: cancel resting orders, stale-gate taker orders, re-sim, re-score, and record for
the E5 venue-lag test. The 11-04 price-follow re-read stands. Redistribution inside the
sim stays out until re-tested.

## Nightly outcome-feedback loop (session "Nightly outcome-feedback loop for edge floors")

- The plan's steering metric is fee-net CLV vs the SHARP close, with ROI as the judge.
  Any edge-floor move should be judged on those, pre-registered.
- Phase 6 adds nightly refits, champion/challenger and a strategy allocator; your loop
  feeds it. Nothing changes now.
