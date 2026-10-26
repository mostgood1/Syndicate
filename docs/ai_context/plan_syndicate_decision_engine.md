# Syndicate Decision Engine — the plan `[2026-10-26, ADOPTED with D1–D8 as recommended; see the decision log, section 12]`

**Status: ADOPTED 2026-10-26** (umbrella lane `syndicate-decision-engine`, todo `#736`). Progress lives in the lane
and the decision log at the end of section 12; this document is the design. It was first written as a proposal.
It is written for the user to decide on and for the sessions that would carry it out.
Every measured number below is cited with its window, n and source. Substrate is the
local fleet (production since Render was suspended 2026-09-30) unless marked.
Nothing was re-measured for this document; the figures are the ledger's, and four
load-bearing ones were spot-checked against their files.

**What the user asked for (2026-10-26):** make Syndicate *be* an AI engine that uses
everything it knows — sims, live and pregame models, advanced stats, history,
teammate/opponent interactions, all odds current and historical, game shapes, cheat
sheets, news, injuries, sentiment — to make profitable decisions. Those decisions are
the **Suggested** picks on the Layer 2 board and the trades the **Portfolio** makes on
Kalshi and Polymarket.

**Clarified the same day:** this is *not* a product to sell. The bar is to be as
successful as a market-grade product would have to be: a real, durable edge,
professional reliability and risk control, and capital that compounds. So the
resale-only concerns are out of scope: licensing for resale, CTA/CPO registration,
pricing, and competitors. Venue legal status stays in, because it decides whether
the Portfolio can keep trading.

---

## 0. Summary

1. **The integration problem is real, but it is not the main problem.** The main
   problem is that no measured source of edge exists *at the price we actually pay*.
   The live book loses −11.8% (Kalshi pregame) and −18.2% (Polymarket) net of fees.
   Fees are only 2.8% of stake, so the loss comes from selection.
   Feeding more inputs into today's machinery would automate a losing book faster.
2. **Most of the "everything" has already been tested and is in the price.**
   No sim beats a two-sided de-vigged close in any sport × market cell. The sim's
   fitted weight on 4,876 settled orders is −0.27 [−0.78, +0.18]. Matchup stacks,
   form, BvP, SP+/EPA/xG/GSAx, on/off and minutes redistribution all read null.
   That is normal for liquid markets and it tells us where *not* to look for edge.
3. **So the engine is designed around edges a participant on these venues can
   plausibly hold.** In order of evidence they are:
   - (E1) the gap between a *sharp* fair and the retail venue's executable price;
   - (E2) being the maker rather than the taker;
   - (E3/E4) pricing what the sharp market does not quote directly (ladders,
     segments, props, combos), where the sims' *shape and correlation* matter more
     than their mean;
   - (E5) reacting to official availability news before the venue does.
4. **The spine already exists: DecisionRecord (`#709`), in shadow since 10-23.**
   This plan extends it. It does not fork it. The engine is one per-line record:
   - one fair, the **Syndicate Fair**;
   - signals that each earn their own weight;
   - one decision policy at the executable venue price;
   - one learning loop.

   Board, Suggested, paper, live, Ask and cheat sheets all read that record.
5. **Every line stays its own decision.** Uncertainty shrinks a line's edge. Nothing
   switches a market off.
6. **"Market-grade" means operating like a professional desk, not selling
   anything.** That requires four things:
   - a tamper-evident record of every suggestion;
   - production that does not stop when one home PC sleeps;
   - kill switches by venue and by strategy;
   - a pre-registered ladder for growing capital as evidence accrues.

   Capital scales only after the edge gate is passed, and then step by step.

---

## 1. Where we actually are (the baseline the plan must beat)

| Fact | Number | Window / n | Source |
|---|---|---|---|
| Live book, Kalshi pregame | **−11.8%** flat ROI net of fees [−20, −4] | 548 bets / 300 games, 08-06..10-24 | `.syndicate/findings_2026-10-24_live_cell_scorecard.md` |
| Live book, Polymarket pregame | **−18.2%** [−34, −2] | 148 / 124 | same |
| Fees as share of stake | 2.8%; Kalshi pre-fee is still −12.8% | same | same |
| Suggested vs everything priced (recorder, flat, fees not netted) | Suggested −4.2% [−10.7, +1.8] per bet; **+0.8% [−4.0, +5.7] ladders once**; all priced −13.5% | 2,462 bets / 326 games, 10-17..10-25 | `.syndicate/findings_2026-10-26_suggested_grade.md` |
| Suggested EV at the Shin close | **+1.51% [+0.63, +2.44]** | 457 bets / 191 games | same |
| Model vs de-vigged close | **0** cells beat a two-sided close. The 7 soccer-prop "beats" are scored against the one-sided margin-model fair. | scorecard 10-26, 1,003 games, 425 cells | `/api/model-scorecard` (fleet) |
| Sim's fitted weight on staked orders | **−0.27 [−0.78, +0.18]** | 4,876 orders, 10-02..10-18 | `#704` findings |
| Suggested Kalshi sides that are negative at Kalshi's own price | **12 of 13** | fleet shortlist 10-20 18:10Z | `.syndicate/findings_2026-10-20_one_engine_audit.md` |
| Edge over Pinnacle at decision ≥0.4pp | +13.0% [−4.5, +30] (lead only: post-hoc cut, NCAAF-heavy) | 199 bets / 89 games | live-cell scorecard; forward test pre-registered 10-25 |
| Kalshi pregame structural price map | no pregame cell with edge under today's fees; only 95–99c in-play favourites at +1.1..+1.6c | 3,566 games, 3.51M prints | `state_kalshi.md` `[kalshi-structural-price-map]` |
| Same rule, our real-time prices | −3.2c/game [−10.5, +2.7]; 7.5% of entries lost (fail line 3%) | 67 games, 4 nights | in-play program R3 first read |
| Kalshi in-play vs books | Kalshi leads (corr +0.44); book-consensus in-play edges mark out −1.26c after fee | 11 games, 64,688 samples | `[kalshi-in-play-efficiency]` |
| Maker vs taker | pregame resting orders fill ~45% and save 4–5% of stake; in-play fills are adversely selected at −16.6c/contract | | `#735`, maker shadow |
| One-engine audit | 5 fair bases, 6 price bases, 21 EV implementations, 7 grading ledgers | code read 10-20 | one-engine audit |
| Ops | one local host since 09-30; host sleep paused collectors 390 min on 10-14; ≥4 scheduled reads failed to dispatch; 78 OPEN/BLOCKED lanes | | ledger |

**Reading it.** The board already finds prices that beat the close (+1.51%). That is a
real, small, *quote-quality* signal. It turns into negative money for three reasons:
- the bet is re-priced at a venue where the same side is worse (12/13);
- ladders multiply one opinion into many bets;
- the sim's added stake amplifies noise (`#704`).

None of those is fixed by adding data. All of them are fixed by deciding once, at the
price we pay, with honest uncertainty.

---

## 2. What "Syndicate as an AI engine" means — eight design principles

An AI engine here is a closed decision loop. The loop has six stages:
1. **perception:** a point-in-time evidence store and an event bus;
2. **belief:** a calibrated probability, with its own uncertainty, for every line;
3. **decision:** a policy at the executable price;
4. **action:** execution;
5. **learning:** grading on three clocks, then refitting;
6. **explanation:** why, in plain words, on the board.

The principles that make that loop trustworthy:

- **P1. The market is the prior.** Start every line from the sharpest available price.
  Everything else is a residual on the log-odds scale that must earn its weight.
  (Benter's two-stage model; Kaunitz et al.'s consensus-outlier result; our own fits,
  which return w≈0 for the sim everywhere.)
- **P2. Decide once.** The DecisionRecord is the only place a fair, an EV, a gate or a
  size is computed. Board, Suggested, paper, live, Ask, cheat sheets and play cards
  all read it. That retires 5 fair bases and 21 EV implementations.
- **P3. Decide at the price you pay.** Selection and sizing use the venue's
  *executable* price, read against the book depth for the stake and net of that
  venue's fee. The fee is `venue_fees.py`: Kalshi 0.07·q(1−q) with series
  multipliers, Polymarket US 0.0695·q(1−q). The latter is fitted to fills
  2026-10-23 and is newer than public write-ups that say 5%.
- **P4. Confidence, not exclusion.** Every line is its own decision (standing user
  rule, restated five times). An uncertain fair shrinks that line's edge through a
  lower-bound EV. No market, family or sport is switched off.
- **P5. Every signal earns its weight, per cell, automatically.** A weight is applied
  only when its lower confidence bound is above 0. The default weight is **0**. Today
  `decision_record.py:58` defaults the sim to 0.25 on unmeasured cells, which
  contradicts the measured w. Fixing that is decision D3.
- **P6. Three clocks of truth.**
  - **Sharp CLV** comes back in hours and has a large n. It is the steering signal.
  - **Calibration and log loss** against the fair and the outcome come back in days.
  - **Fee-net P&L** comes back in weeks. It is the judge.

  Promote on the fast clock, confirm on the slow ones. ROI needs about 2,300 bets for
  ±2pp; a paired CLV comparison resolves far sooner (09-01 finding). The 10-24 reading
  showed positive *same-book* CLV alongside negative ROI, so the CLV used must be
  against a **sharp** close, net of fees.
- **P7. Sims do the jobs the market cannot.** Those jobs are:
  - **shape and correlation:** ladders, segments, alt lines, combos;
  - **shock propagation:** who absorbs an absent player's role;
  - **engine diagnosis:** the graded disagreements the market won become the engine
    owners' work list.

  The sim is not a second opinion on a main line the sharp market already prices.
  This keeps the user's "secret sauce" loop (sims, advanced data and EV improving each
  other) and points it where it can pay.
- **P8. Pre-register, shadow, canary, promote.** One change per deploy. Kill criteria
  are written before the data is seen. The measurement goes in `deploys.md`.

---

## 3. Architecture

```
            ┌──────────────── L7 RISK & OPS ENVELOPE (kill switches, state gating, drawdown stop, identity, durability) ────────────────┐
            │                                                                                                                         │
 sources →  L0 EVIDENCE STORE ──► L1 SYNDICATE FAIR ──► L2 SIGNAL EXPERTS + ──► L3 DECISION POLICY ──► L4 EXECUTION ──► venues      │
 (odds,      point-in-time,         sharp-weighted         SKILL REGISTRY           venue-native EV,       taker / maker /             │
 venues,     as-of replay           fair + σ, price        Δlogit per expert,       lower-bound EV,        wait, exits                 │
 news,       + availability         surface for            earned per-cell          correlation-aware                                  │
 stats,      event bus              derived markets        weights (default 0)      shrunk Kelly                                       │
 sims)            ▲                                                                       │                                             │
            │     │                                       ┌──── DecisionRecord (#709) ────┘                                             │
            │     └──────── L5 LEARNING LOOP ◄── settle ◄─┤  one per line, per build                                                   │
            │               3 clocks, nightly refit,      └──► L6 SURFACES: Layer 2 board + Suggested, Portfolio, track record, Ask    │
            │               champion/challenger, strategy allocator, engine-read → sim owners                                          │
            └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### L0 — Evidence store (perception)

- **Exists:**
  - `book_quotes` change log: fleet history from 09-30, 120-day retention, about
    780 MB gz.
  - Venue quotes: `reports/intelligence/venue_odds`, 14-day retention.
  - `clv_openings`, `closing_lines`.
  - News snapshots every 10 min since 10-13 (`scripts/collect_news_snapshots.py`).
  - Rotation stints, pair minutes, lineup pools.
  - The replay-diff gate: a production day reproduces offline with 0 mismatches.
  - `preserve_forward_inputs.py`, which keeps props only.
- **New:**
  1. An **as-of contract.** Every feature carries `observed_at`, and training reads
     only `observed_at ≤ decision_at`. Replay already proves this is possible.
  2. **Preserve game lines and venue order books.** Today only prop forward inputs
     survive retention.
  3. **Store Kalshi trade prints.** The public history API reaches back to 2025-07. It
     was pulled once, 3.51M prints, for research, and is not stored.
  4. **Put the per-(date, sport) openings cap on the fleet.** 36,228+ openings were
     lost to the old cap.
  5. **Off-host backup.** The fleet data root is the only copy of everything since
     09-30, and `data-backup` writes to the same host.

### L1 — Syndicate Fair (belief, part 1)

- **Exists:**
  - `_consensus_fair` (`layer2_board.py:1480`): a median of per-book Shin de-vigs.
  - A sharp-anchor tier behind `SYNDICATE_FAIR_ANCHOR=sharp`; its fleet value is
    unread.
  - `book_margin_model` for one-sided markets. That fair is overstated by 8.5pp.
  - Pinnacle on NBA/NFL/soccer/WNBA game lines since 10-25.
- **New: a learned sharpness-weighted fair.**
  - `logit p_fair = Σ_b w_b·logit p_b / Σ_b w_b`. Weights are by book × sport ×
    market family × time-to-start bucket × quote age.
  - The weights are fitted to minimise log loss against (i) the sharp close where one
    exists, and (ii) the outcome.
  - The output is `p_fair` and `σ_fair`. `σ_fair` comes from dispersion across books
    plus the fitted residual variance.
  - This is the most *learnable* problem in the system: every line, every tick, with
    the close arriving within hours.
  - **Fallback order**, with σ inflating at each step and the basis always recorded:
    1. sharp book;
    2. weighted consensus;
    3. a two-sided venue mid, used only after an identity check;
    4. the margin model, flagged one-sided.
- **New: a price surface for derived markets.**
  - Fit the distribution of margin, total and player stat to the *sharp main quotes*,
    then price ladder rungs, alt lines, quarters/halves and props off that surface.
  - Where history is thin, the sim supplies the *shape* (variance, skew, tail, joint
    distribution), with its location pinned to the market.
  - This is the sim's most defensible job, and it is unmeasured today. The test is E3.
- **Gate:** held-out log loss below the Shin consensus with a CI below 0, per sport
  family, plus the pre-registered Pinnacle forward test. It lives in the
  `fair-price-v2` lane (Shin is live, H6 soccer margin fair scores from 10-30).

### L2 — Signal experts and the skill registry (belief, part 2)

Each expert outputs a shift on the log-odds scale (Δlogit) with its own σ.
`p_decision = sigmoid(logit p_fair + Σ_i w_i·Δ_i)`, and
`σ_decision² = σ_fair² + Σ_i w_i²·σ_i²`.

| Expert | Δ it proposes | Evidence today | Starting weight |
|---|---|---|---|
| Sim, mean | sim vs fair | loses or parity everywhere; w = −0.27 | 0 (earn per cell) |
| Sim, shape | rung/segment/combo price vs surface | unmeasured | 0 until E3 |
| Prop under-tilt (likelihood shadow) | +1.0..+2.4pp toward the under | NBA +1.0/+1.6, NCAAF +2.35/+2.42, MLB hits +0.99 [+0.21, +1.79]; blind unders lose after hold | prior shift only |
| Availability shock | status change → fair move | price-follow: books reprice game lines in ~15 min; venue lag unmeasured | 0 until E5 |
| Referee / umpire crew | total and foul-rate shift | collected (NBA, NHL), consumed by nothing | 0, test |
| Weather (NWS) | MLB/NFL totals | MLB weather is in the sim; NWS forecast has no reader | 0, test |
| Rest / travel | margin shift | NBA back-to-back only | 0, test |
| Movement / steam | sharp-book move direction | the single-book movement term is OFF since 10-02 (measured negative); a sharp-book move is untested | 0, test as a CLV feature |
| Venue flow | Kalshi taker imbalance as a public-money proxy | not stored | 0, test |
| Season phase | pre / regular / post priors | NBA guards live 10-20 | regime label, not a Δ |

- **The skill registry** replaces the hand-curated `measured_market_skill.py` and the
  0.25 default.
  - **Hierarchical partial pooling:** sport → market family → market → segment →
    phase. The prior is w ~ N(0, τ²).
  - **Fit on two residuals:** the CLV residual is fast, the outcome residual is slow.
  - A weight is applied only when its lower bound is above 0, and is shrunk toward 0.
  - It extends the daily optimizer's w* (`daily_optimizer.py`) and the bucket
    overlay. It is not a third system.
- **Engine read** (the user's 10-15 rule). Every nightly fit also writes, per sport:
  - bias;
  - calibration slope;
  - the fitted trust weight by gap size;
  - error by time-to-start;
  - the 25 biggest disagreements the market won.

  These go to the engine owners as concrete inputs and knobs.

### L3 — Decision policy (decision)

For every executable quote `q` (Kalshi ask, Polymarket ask, or a sportsbook price for
the board view):

```
cost c(q)      = q + fee_venue(q)                         # per $1 payout, venue_fees.py
EV_net(q)      = p_decision / c(q) − 1
p_lb           = p_decision − z·σ_decision                # z fitted so lower bounds are calibrated
EV_lb(q)       = p_lb / c(q) − 1
kelly(q)       = max(0, (p_lb − c) / (1 − c)) × λ × credibility     # λ: Baker–McHale shrink
```

- **Choose how to execute:**
  - **TAKE** when `EV_lb > 0` at the executable depth.
  - **REST** a maker order at a price `r` when
    `P(fill) × (EV_net(r) − adverse_selection) > 0`. The adverse-selection term is
    learned from the maker shadow and pilot.
  - **WAIT** when a timing model (Phase 3) predicts a better price before the start.
- **Correlation-aware sizing.** Positions group by game axis: margin, total, team
  total, and per player stat, each per segment. A ladder is **one** position. The
  existing caps then apply: per game, per slate, per venue, a daily loss stop, and
  the favourite cap. This is `#711`'s R1 axis rule folded in as `identity.axis` plus
  `size.concentration`.
- **Exits.** Hold by default: replay says take-profit loses to hold at every margin.
  Exit only on a news event or a fair move beyond a threshold. The in-play program
  owns the live exit rules.
- **Suggested (board)** is the policy's verdict at the best *executable* price across
  venues and books. **Portfolio** is the same verdict at the venue it can trade. The
  board and the portfolio therefore agree by construction. That is DecisionRecord
  step 3, the `#719` venue-native selection, and it is decision D2.

### L4 — Execution (action)

- **Exists:**
  - `kalshi_orders.py`, `polymarket_us_orders.py`;
  - exits and the fast-exit loop;
  - `kalshi_maker_pilot.py`, live at $5/order and $10/day;
  - the maker shadow, hourly;
  - order and fan-in identity guards (F2 fixed 10-20).
- **New:**
  - **A general maker engine.**
    - Quote at fair minus a margin.
    - **Cancel on a fair move, a news event, or a time cut-off before the start.**
      The availability bus is what protects resting orders.
    - Polymarket US makers pay no fee, and Kalshi maker fees are a quarter of taker.
  - **Depth-aware pricing**, so the stake walks the book.
  - **Per-order slippage and fill logging.** 551 of 704 settled live fills have no
    order instant today.

### L5 — Learning loop (learning)

1. **Close the loop's breaks first:**
   - `#722` (`staked_probability_version` cannot be joined to outcomes);
   - missing order instants;
   - 928 paper and ladder rows unsettled, mostly NBA;
   - soccer is 35% ungraded.
2. **Nightly:** refit book weights (L1), expert weights (L2) and calibration (z, λ).
3. **Weekly: champion/challenger on frozen replay.** The replay-diff gate makes a
   past day reproducible. A challenger is promoted by its pre-registered gate, never
   by eye.
4. **Strategy allocator.** Each strategy (E1–E7) is an arm.
   - Capital share follows the posterior of fee-net CLV, then ROI.
   - The floor is canary size and there is a hard cap.
   - This allocates capital between *strategies*. Every line is still judged on its
     own, and no market is excluded.
5. **Drift alarms.** Calibration slope, ECE and fill/adverse-selection drift per cell
   page a lane. They do not auto-switch anything.

### L6 — Surfaces (explanation)

- **Layer 2 board.** Every line shows:
  - the Syndicate Fair, with its basis and age;
  - the best executable EV, net of fee, with its lower bound;
  - a confidence grade;
  - which experts moved it and by how much;
  - the cell's track record;
  - the timing call (take, rest or wait).

  The "why" sentence is written from the record by template, with no LLM:

  > *"Sharp fair 56.2% (Pinnacle, 4 min old) vs Kalshi 52c + 1.7c fee → +4.3% edge,
  > +1.9% at the low end. Sim shape agrees on the −4.5 rung. No status change in the
  > last 30 min."*
- **Portfolio.** Positions, P&L and CLV per strategy, allocator shares, and the state
  of every kill switch.
- **Track record.** Before first pitch or tip each day, write a SHA-256 digest of
  the Suggested set to an append-only log. That makes the record tamper-evident, so
  "how are we really doing" can never be answered from a cherry-picked or rebuilt
  history.
- **Ask, cheat sheets and play cards** read the record. That is DecisionRecord step 6,
  and it ends cheat sheets learning nothing and governing nothing (10-20 audit).

### L7 — Risk and ops envelope

- **Kill switches** at four levels: venue, strategy, legal state (US state) and
  global.
- **Drawdown stop.** If the 7-day loss exceeds X% of capital, drop to canary size.
- **Identity gate.** No venue price becomes a feature or an order without the
  game/date identity check.
- **Stale and news gates.**
- **Durability:**
  - off-host backups;
  - a watchdog for host sleep and missed dispatches;
  - production moves off a single home host, or is kept from sleeping, before capital scales (D8).

---

## 4. Where profit can come from — edge hypotheses, each with a test and a kill rule

Ranked by evidence × structural plausibility × cost to test. "Owner" is the existing
lane the work belongs to, if one exists.

| # | Hypothesis | Why it might be true | First test (pre-registered) | Kill rule | Owner |
|---|---|---|---|---|---|
| **E1** | **Sharp–venue gap (taker).** Kalshi and Polymarket are retail-heavy, so their pregame prices sometimes trail the sharp books. Taking the gap fee-net at the venue's own ask pays. | Pinnacle-edge lead +13.0% vs −10.6% below 0 (post hoc). Kaunitz consensus-outlier result. When the consensus disagrees with Pinnacle the bet loses −35.6% (38 bets). | Pinnacle forward test (registered 10-25), plus venue-native paper2 (D2) ranked on EV_lb vs the sharp fair. | Forward fee-net CLV vs the sharp close not above 0 (game-clustered CI) at ≥400 bets / ≥100 games | `live-cell-scorecard`, `venue-native-selection` |
| **E2** | **Maker with news-cancel.** Rest at fair minus margin, earn the spread instead of paying it, and cancel on news. | Pregame fills ~45% and save 4–5% of stake. Polymarket US makers pay no fee and Kalshi maker fees are ¼ of taker. In-play is adversely selected (−16.6c), so stay pregame. | The maker shadow's pre-registered looks at 200/400/600 orders. Add a news-cancel arm once L4 exists. | The shadow's own rule; calendar stop 2027-01-31 | `kalshi-maker-shadow-paper` |
| **E3** | **Derived-market surface.** Ladder rungs, alt lines, segments and thin props priced off the sharp main line plus a distribution shape beat the venue's quotes. | The venues list many rungs. One-sided prop holds are 6–8%. The sim's *shape* is unmeasured, while its mean is measured useless. | Offline: price every Kalshi rung from a surface fitted to the sharp main line (parametric vs sim-shaped), then grade vs the venue price and the outcome over the stored quote log. | Surface log loss not below the venue mid on held-out rungs | new lane |
| **E4** | **Combos and correlation.** Combos are about ⅔ of Kalshi weekend notional, and Kalshi pays maker incentives on prop-combo legs. The sims' joint distributions can price correlation better than the independence-plus-haircut a venue or casual maker uses. | Sims are built for joint outcomes. The 18.5% SGP price haircut is unmeasured. | Grade the sim-implied correlation (anchored marginals) vs realised co-occurrence on settled games, then vs the combo prices captured. | Sim correlation no better than independence on realised outcomes | new lane |
| **E5** | **Availability timing.** Official status events reach us before some venue prices move, especially on props. | Official schedules are fixed: NBA reports every 15 min, NFL inactives at T−90, EPL XI at T−75, NHL scratches at T−24..29. Books reprice game lines in about 15 min. Venue lag is unmeasured. | Join the news collector to the Kalshi and Polymarket quote logs, and measure time-to-move after OUT/IN events by market type. | Median venue lag under 2 min, or the move is symmetric (timing, not edge) | **KILLED 2026-10-26** (lane `e5-venue-news-lag`, prereg `d9ce947f`, findings `6f0e90cc`, todo `#739`). Kalshi: move after our capture +0.04pp [−0.05, +0.13], 197 units / 93 games; fee-net EV at +1 min −4.32%. Polymarket survives only by the letter (+0.21pp, 39 units). Where books did move, Kalshi had moved BEFORE our 10-min collector saw the news. |
| **E6** | **Small residuals:** under-tilt, referee, weather, rest. They improve the fair; they are not bets on their own. | Under-tilt is measured. The rest are collected but untested. | Each one in the skill registry as a per-cell Δ with a CI | Weight lower bound ≤ 0 → it stays at 0 (it never gets "turned off" for a market) | registry |
| **E7** | **In-play fair beats the Kalshi mid.** | Hard: Kalshi leads the books in play. NBA re-sim Brier 0.189 vs Kalshi 0.163 (2 games). | Owned by the in-play program; NBA forward read after 12-15 | That program's rules | `in-game-trading`, `#700` |

**What not to chase** (already measured as in the price or negative): raw sim
probabilities on main lines; `model_edge_pct` as a rank; matchup and advanced-stat
score terms; cross-book consensus edge vs the venue price with no sharp anchor;
take-profit exits; book-consensus in-play edges.

---

## 5. Idea bank

The user asked for ideas. The priority column reflects §4's evidence and the cost of
the first test.

| Idea | What it is | Data we already have | Priority |
|---|---|---|---|
| **Sharpness-weighted fair** | Learn which books predict the sharp close, by sport, market and time-to-start | `book_quotes` since 09-30 | **P0** |
| **Venue-native selection** | Select and size at the venue's own ask, fee-net (DecisionRecord step 3) | DecisionRecord shadow | **P0 (decision D2)** |
| **Lower-bound EV instead of a fixed 2% floor** | The floor becomes per-line uncertainty, so thin cells get less money without being excluded | σ from book dispersion | **P0, as a challenger to 2%** |
| **Ladders count once** | Correlation-aware sizing on game axes | `#711` R1, alt-ladder cap (10-26) | **P0** |
| **Maker engine with news-cancel** | Earn the spread pregame; the event bus protects resting orders | maker pilot and shadow | **P1** |
| **Availability event bus** | Cancel-protection plumbing ONLY (E5 killed the timing use, 2026-10-26): cancel resting maker orders and stale-gate takers on official status changes | collector since 10-13 | **P3, gated** on the Phase 3 maker engine + an official-source event time |
| **Price surface for rungs and segments** | Price ladders and segments off the sharp main line; the sim gives shape | quote logs, sims | **P1** |
| **Bet-timing model** | Predict drift toward the close, to choose take now, rest, or wait | openings → closes | **P1** |
| **Hierarchical skill registry** | Automatic per-cell weights with CIs; replaces the hand-curated registry and the 0.25 default | optimizer w*, overlay | **P1** |
| **Combo correlation engine** | Sim joint distributions price combos and prop-combo legs | sims, settled outcomes | **P2** |
| **Venue-flow signal** | Kalshi taker imbalance as a free public-money proxy, in place of paid public-% splits | Kalshi trade API (not stored) | **P2** |
| **Strategy allocator** | A Bayesian bandit across strategies with a canary floor | needs E1–E5 arms | **P2** |
| **Engine-read queue** | The nightly list of "market won" disagreements goes to the sim owners | scorecard | **P1** (it is the secret-sauce loop) |
| **Verifiable track record** | A daily hash of the Suggested set, written before games | DecisionRecord | **P1** (cheap, and it keeps every later P&L claim honest) |
| **Regime priors** | Season-phase and early-season shrink toward the market | NBA phase guards | **P2** |
| **LLM news triage** (todo #86) | Extract structured status from free text, e.g. beat reporters; off the money path until it beats the close | none; needs D4 | **P3, decision** |
| **Weather, referees, travel as Δs** | Small residual experts | NBA/NHL crews collected; NWS free | **P2** |

---

## 6. News, injuries, lineups and sentiment

**DECIDED 2026-10-26, after E5 (user, verbatim): "Yes, adopt E5's recommendation: Phase 4 becomes cancel-protection plumbing only, gated on the Phase 3 maker engine and an earlier official-source event time; no paid news feed. Update the plan and #736 accordingly."**
- E5 found no timing edge at either venue (findings `6f0e90cc`). The bus below is therefore **cancel-protection
  plumbing only**, never a timing strategy.
- It is **built only once both exist**:
  1. the Phase 3 maker engine (no resting orders, nothing to protect);
  2. an official-source event time earlier than the 10-minute collector. Fed by today's collector, the bus would cancel a
     resting order after Kalshi had already moved.
- When an official event time exists, re-run E5 (`#739`) on it before building.
- E5's engine read is CORRECTNESS work for the sim owners, independent of the bus: NFL, NCAAF and soccer sims read no
  status, and NBA keeps day-to-day players at full minutes.

**Design (for when the gate opens): an availability event bus driven by official schedules.**
- **Schema:** `AvailabilityEvent{sport, game, team, player, status, p_play, source,
  source_tier, observed_at, supersedes}`.
- **Sources, by when they publish:**
  - NBA: official injury report every 15 min, with fixed deadlines (5 p.m. the day
    before; 11 a.m.–1 p.m. on game day).
  - NFL: Wednesday–Friday reports, game status Friday, inactives at T−90.
  - EPL: XI at T−75 (EFL at T−60).
  - NHL: scratches at T−24..29; confirmed goalies from Daily Faceoff.
  - MLB: posted lineups about T−2..3h.
  - Soccer: confirmed XI. Our soccer XI arrives about 1 minute before kickoff today.
- **What it triggers, in this order:**
  1. **cancel** resting maker orders on affected games;
  2. **stale-gate** taker orders on affected lines until the fair refreshes;
  3. **re-sim** the affected game (removal correctness: NBA DTD at full weight in 78 of
     88 cases on 10-16; NFL, NCAAF and soccer reach no sim);
  4. **re-score**;
  5. **record**, so E5's venue-lag test accrues data automatically.
- **What it must not do yet:** redistribute minutes or targets inside the sim. That
  was tested and came back null or negative for WNBA and NFL. It can be re-tested
  through the registry.

**Sentiment and public money.**
- No source exists today. Action Network and VSiN splits have no public API, and
  scraping them is a terms risk.
- The cheapest honest proxy is **venue flow**: Kalshi's own trade prints, which are
  public and free, give taker imbalance on the very venue we trade.
- The X API costs about $0.005 per post read (an estimated $675/month for 300 beat
  reporters). It is optional, P3, and only behind the LLM decision D4.
- Reddit: no.

**LLM.**
- The 2026-08-14 user decision stands: Ask's LLM is off, and the deterministic snapshot
  path is the product.
- If an LLM enters at all, the plan scopes it to three worker-side jobs, logged and
  off the money path until each one beats the close:
  1. news materiality and status extraction from free text (todo #86);
  2. a pre-trade "anything we missed?" check on the day's top Suggested lines;
  3. summarising the nightly engine read for the engine owners.
- That requires an explicit, logged override (D4).

**Data reliability (not resale).** For our own use the practical risk of free feeds
is breakage, not legality:
- the ESPN college-football feed already died;
- ESPN athlete-id churn created false new+cleared pairs in 37 of 82 NBA events on
  10-16;
- the terms of ESPN (Disney ToU §2(B)) and MLBAM both discourage automated pulls.

Prefer official sources (league injury PDFs, NFL inactives, EPL team sheets, NHL
scratches). **No paid news feed** (user, 2026-10-26, after E5: minutes of latency are not worth money at these venues).
Rejected options, for the record:
- SportsDataIO, median buyer about $16.5k/year;
- RotoWire via OpticOdds.

---

## 7. The Layer 2 "Syndicate Score" and what Suggested means

**Per line, shown on the board, all read from the DecisionRecord:**
- **Edge:** `EV_lb` at the best executable price, fee-net, with `EV_net` beside it.
- **Confidence:** a grade (A/B/C) from `σ_decision`, the fair's basis (sharp /
  weighted / one-sided), quote age, and the cell's graded sample. The thresholds are
  fitted, not chosen.
- **Drivers:** the experts with non-zero earned weight on this line, and their Δ.
- **Timing:** take now, rest at a price, or wait.
- **Flags:** pending news, correlated with a held position, a one-sided fair.

**Suggested.** `EV_lb > 0` at an executable price, the gates pass (identity,
freshness, two-sided fair, no pending status change), and the line is the best side
of its axis. It runs **as a challenger beside the current 2% floor**, which the user
decided on 10-26 to keep. The two are compared on the same lines through the 10-31/11-01
re-grade and after, on forward sharp CLV and then ROI. The challenger replaces the
floor only through its gate.

**Ranking.** Keep the current rank until a challenger wins on forward sharp CLV.
`score_v2` (Kelly-growth rank) was not promoted at −0.04 [−0.17, +0.09] over 62
slates, so a growth rank must win its own test.

---

## 8. Roadmap — phases with gates

Weeks are estimates from 2026-10-26. A phase starts when its gate input exists, not
when its date arrives.

| Phase | Deliverables | Gate to move on | Lanes |
|---|---|---|---|
| **0. Make the truth trustworthy** (now → ~11-09) | Fix the loop breaks: `#722` join, order instants, 928 unsettled rows, the openings cap on the fleet, the venue-prop close fix on the fleet. Off-host backup. Dispatch watchdog. D3 (default weight 0) in shadow. **Live capital stays at canary.** | Checklist exit 0. Every settled live fill joins to its record and order instant. | `decision-record-shadow`, `live-cell-scorecard`, ops |
| **1. Syndicate Fair v1** (→ ~11-30) | Learned sharpness weights and σ_fair, written into the DecisionRecord in shadow. Game-line forward preservation. Pinnacle coverage widened within the OddsAPI budget (about 0.3–0.7M credits of headroom). | Held-out log loss below Shin with a CI below 0 per sport family. Pinnacle forward-test read. | `fair-price-v2` |
| **2. Decision policy v1, paper2** (→ ~12-14) | Venue-native EV_lb selection (D2), correlation-aware shrunk Kelly, the challenger Suggested flag, per-order fill/slippage logs. | **The edge gate:** forward fee-net CLV vs the sharp close above 0 (game-clustered CI) at ≥400 bets / ≥100 games for at least one strategy. Then canary live. | `venue-native-selection`, `decision-record-shadow` |
| **3. Execution intelligence** (Dec → Jan) | General maker engine with news-cancel, timing model, depth-aware pricing. | Maker shadow looks pass. Adverse selection measured below the spread captured. | `kalshi-maker-shadow-paper`, new |
| **4. Availability event bus -- CANCEL-PROTECTION ONLY** (decided 2026-10-26 after E5; starts only when the Phase 3 maker engine exists AND an official-source event time earlier than the 10-min collector exists) | Event schema, official-source ingestion, cancel and stale-gate triggers. No timing strategy, no paid feed. | An E5 re-run (`#739`) on the official-source time; then reachability (`off != on`). | `news-availability-gate` |
| **5. Derived markets and combos** (Dec → Feb) | Price surface (E3), combo correlation (E4), sim-shape tests. | E3/E4 kill rules. | new lanes |
| **6. Autonomy** (Jan → Feb) | Nightly refits, champion/challenger on replay, strategy allocator, drift alarms, engine-read queue. | Allocator in shadow for 4 weeks, agreeing with the hand-run decisions. | new |
| **7. Professional-grade operations and capital scaling** (backup and watchdog now; the rest gated on the Phase 2 result) | Production that survives host sleep (or moves to a cloud host). Venue-status kill switch. Hash-chained record. A pre-registered capital ladder: stake bands widen only after N more bets keep the CLV and ROI CIs above 0. | Each rung of the ladder is its own pre-registered read. | new |

**Date-bound reads this plan must not disturb:**

| Date | Read |
|---|---|
| 10-28 | NBA lineup pools re-read (`#696`) |
| from 10-30 | H6 soccer margin fair scores offline |
| 10-31 / 11-01 | Suggested re-grade |
| ~11-01 | `#727` earned-profile refit |
| 11-02 | **`#704` keep/revert** (staked probability = market on unfitted cells) |
| 11-04 | News price-follow re-read |
| 200/400/600 orders | Maker shadow looks |
| after 12-15 | NBA live re-sim forward read (`#700`) |
| ongoing | Pinnacle forward test |

**Rule:** nothing in Phases 0–2 changes the staked probability before 11-02.

---

## 9. Scorecard and kill criteria

- **North star:** forward **fee-net CLV against the sharp close** on executed bets,
  per strategy, with a game-clustered CI.
- **Judge:** realised **fee-net ROI** with a CI, per strategy and pooled.
- **Model health:**
  - log loss and ECE of `p_decision` vs `p_fair` vs outcome;
  - the share of lines with a sharp-anchored fair;
  - the share of Suggested lines that are executable at a venue.
- **Execution:** fill rate, slippage vs the decision price, maker adverse selection.
- **Ops:** dispatch success, quote age at decision, host uptime, backup age.

**Kill criterion for automated trading.** If no strategy passes the Phase 2 edge gate
by the end of Phase 3:
- live capital stays at canary size;
- the board stays a research surface while the engine keeps learning;
- the next lever is a better fair (E1/E3), not more capital.

This is written before any data is seen, on purpose.

---

## 10. What "market-grade" means here (the bar, not a product)

The user's bar (2026-10-26) is "that level of successful" for our own capital. Read
as engineering requirements, it means:

| Area | Bar | Today | Closes in |
|---|---|---|---|
| **Edge** | Forward fee-net CLV vs the sharp close above 0 with a game-clustered CI, per strategy, then ROI confirming it | none proven (§1) | Phases 1–2 |
| **Honesty of the record** | Every Suggested set and every order hashed before the games; P&L reproducible from the ledger alone | 7 grading ledgers; 551/704 old fills without an order instant | Phase 0, L6 |
| **Reliability** | No single sleeping host. Off-host backup. A watchdog for missed dispatches. | One home host; 390-min pause 10-14; ≥4 missed reads | Phase 0 (backup, watchdog), Phase 7 (host) |
| **Risk control** | Kill switches by venue, strategy and legal state; a drawdown stop; per-game and axis caps; identity gate | Per-event cap, cell gate and identity guards exist; no drawdown stop or venue-status switch | L7, Phase 0–2 |
| **Capital growth** | A pre-registered ladder: stake bands widen only when more bets keep the CIs above 0; fractional Kelly shrunk for estimation error | $5–10 stake band scaled on full Kelly | Phase 7 |
| **Autonomy** | Nightly refits, champion/challenger and drift alarms run with no session in the loop | Many reads are manual or one-shot scheduled tasks | Phase 6 |

**Venue risk** is the one outside force that could stop the Portfolio regardless of
edge. Kalshi's sports contracts face a circuit split:
- the Third Circuit ruled **for** Kalshi;
- the Ninth and Sixth Circuits, and Massachusetts, ruled **against**;
- a Supreme Court cert petition (NJ, No. 26-299) is pending;
- the CFTC's proposed rule defining event contracts as swaps has comments due
  around 11-18;
- New York sued on 10-22 to enforce subpoenas.

So the engine must be **venue-agnostic**. A venue is a price source plus an executor.
Kalshi, Polymarket US and any newcomer (ProphetX and Novig are already visible
through OddsAPI `us_ex`) plug into the same policy. A venue can be switched off in
minutes without touching the decision logic.

---

## 11. Coordination with the sessions and lanes already running

| Workstream | Owner (lane / session) | What this plan asks of it | Do not touch |
|---|---|---|---|
| DecisionRecord (`#709`) | `decision-record-shadow` | Steps 3–8 become Phases 2 and 6; D3 default weight | `decision_record.py` is theirs |
| Fair price | `fair-price-v2` | Phase 1 (learned weights, σ_fair, surface) | `layer2_board.py` fair code is claimed |
| Profitability program / per-cell gate | `live-cell-scorecard` (live-trading coordinator 332cb014 per the ledger; sessions "Profitability program" and its parent "Kalshi/Polymarket portfolio endpoint") | E1 forward test; the Phase 2 edge gate uses its scorecard | `live_cell_gate.py`, the scorecard script, the gate hook in `pipeline/portfolio_commit.py` |
| In-play | `in-game-trading` ("In-play trading program") | E7 stays theirs | in-play entries and exits |
| Maker | `kalshi-maker-shadow-paper`; pilot | E2; the news-cancel arm after Phase 4 | the pilot's stop rule |
| min-EV tuner | `min-ev-tuner-shadow` | stays in shadow (user, 10-26) | — |
| `#704` staked probability | `sim-stake-unfitted-market-only` | nothing before 11-02 | staked-probability code |
| Concentration | `live-event-concentration` (coordinator holds readings) | folded into L3 as `size.concentration` | `pipeline/portfolio_commit.py`, `execute_portfolio.py` (loan chains) |
| News | `news-availability-gate` | Phase 4 bus (cancel-protection only, gated); E5 closed (`#739`) | — |
| Layer 2 grading | the "Layer 2 board assessment" session (closed `layer2-suggested-opps`) | challenger Suggested in the 10-31/11-01 re-grade | the 2% floor |

**Process.**
- One umbrella lane, `syndicate-decision-engine`, carries this plan and its gates.
- Each phase item goes to the owner above. New lanes are opened only for new
  components (fair v1 model, event bus, price surface, combo engine, allocator).
- With 78 OPEN/BLOCKED lanes against a cap of 3, the umbrella lane should *absorb*
  dormant ones rather than add to the count.

---

## 12. Decisions owed by the user

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Adopt this plan as the program, under one umbrella lane | Yes |
| **D2** | DecisionRecord step 3: select and size live and paper2 on venue-native net EV (`#719`; proposed floors Kalshi 1.0, Polymarket 0.5, or `EV_lb > 0`) | Yes, paper2 first, then canary |
| **D3** | DecisionRecord default model weight 0.25 → **0** on unmeasured cells (shadow-only effect today) | Yes |
| **D4** | An LLM in the worker for news triage only (Ask stays off), behind a CLV test | Defer to Phase 4. Build rules-based official-feed ingestion first. |
| **D5** | OddsAPI spend: widen sharp-book coverage (props, NHL game lines) within or above the 5M cap | Yes, within budget first |
| **D6** | Live capital posture until the Phase 2 gate | Canary only. Do not widen the bands. |
| **D7** | Capital ladder: pre-register how stake bands grow once a strategy passes the edge gate. Example: double the band after each further 400 bets with the CLV and ROI CIs still above 0, with a drawdown stop that drops back one rung. | Yes, write it before Phase 2 ends |
| **D8** | Reliability: off-host backup and a dispatch watchdog now; production off the single home host (or kept from sleeping) | Backup and watchdog now; the host decision at Phase 7 |

**Decision log** (each one is the user's own words in the session "Syndicate AI decision engine"; detail in lane `syndicate-decision-engine`):
- 2026-10-26: D1–D8 adopted as recommended.
- 2026-10-26: not a product to sell; the bar is market-grade success with our own capital.
- 2026-10-26: D3 landed on a loan (`46fba654`); the backup goes to OneDrive.
- 2026-10-26: Fair v1 shadow wiring (`636ba4ff`).
- 2026-10-26: Phase 2's paper reader may read the DecisionRecord (guard-test loan).
- 2026-10-26: "Widen tonight's window": the fleet ff goes to `0fca3f2b`, with the Phase 2 paper key and one full down/up.
- 2026-10-26: **E5 adopted**. Phase 4 becomes cancel-protection plumbing only, gated on the Phase 3 maker engine and an
  earlier official-source event time; no paid news feed.

---

## Sources (external)

- Benter (1994), computer-based horse race handicapping (model + public odds second-stage logit): https://www.gwern.net/doc/statistics/decision/1994-benter.pdf
- Kaunitz, Zhong, Kreiner (2017), beating bookmakers with their own numbers: https://www.technologyreview.com/2017/10/19/67760/the-secret-betting-strategy-that-beats-online-bookmakers/
- Hubáček, Šourek, Železný (2019), exploiting sports-betting market using machine learning (decorrelation from bookmaker): https://ideas.repec.org/a/eee/intfor/v35y2019i2p783-796.html
- Walsh & Joshi (2024), calibration vs accuracy for model selection: https://researchportal.bath.ac.uk/en/publications/machine-learning-for-sports-betting-should-model-selection-be-bas/
- Kull et al. (2017), beta calibration: https://proceedings.mlr.press/v54/kull17a.html
- Pinnacle / Buchdahl on closing odds and profit expectation: https://www.pinnacle.com/betting-resources/en/betting-strategy/what-can-closing-odds-tell-us-about-profit-expectation/xqp2jmbsbhbwep88
- Baker & McHale (2013), optimal betting under parameter uncertainty (Kelly shrinkage): https://ideas.repec.org/a/inm/ordeca/v10y2013i3p189-199.html
- Fractional Kelly with risk controls (2021): https://arxiv.org/abs/2107.08827v1
- NBA official injury report rules (2025-26): https://official.nba.com/nba-injury-report-2025-26-season/
- Disney (ESPN) terms of use: https://disneytermsofuse.com/english/
- MLBAM copyright notice: http://gdx.mlb.com/components/copyright.txt
- X API pricing: https://docs.x.com/x-api/getting-started/pricing
- Kalshi API rate limits: https://docs.kalshi.com/getting_started/rate_limits
- Kalshi fee schedule by market (secondary): https://www.oddsshopper.com/articles/prediction-markets/kalshi-fee-schedule-by-market
- Prediction-market weekend volume, Oct 2026: https://www.covers.com/industry/prediction-sites-produce-first-11-billion-weekend-oct-19-2026
- Third Circuit (Apr 2026): https://www.paulweiss.com/insights/client-memos/a-divided-third-circuit-holds-that-the-cftc-has-exclusive-jurisdiction-over-sports-related-event-contracts
- Ninth Circuit (Aug 2026): https://www.covers.com/industry/circuit-court-rules-against-prediction-market-sports-event-contracts-august-28-2026
- Sixth Circuit (Sep 2026): https://www.cnbc.com/2026/09/25/appeals-court-rules-states-can-regulate-sports-prediction-markets.html
- CFTC interim final + proposed rule (Oct 2026): https://www.freewritings.law/2026/10/cftc-draws-the-line-interim-final-rule-excludes-certain-gaming-products-from-and-proposed-rule-includes-event-contracts-in-the-swap-definition/

## Internal sources

`.syndicate/findings_2026-10-20_one_engine_audit.md`, `findings_2026-10-24_live_cell_scorecard.md`,
`findings_2026-10-26_suggested_grade.md`, `findings_2026-10-13_layer2_edge_deep_dive.md`,
`findings_2026-10-16_absence_handling_survey.md`, `findings_2026-10-19_ev_overstatement_decomp.md`,
`findings_2026-10-22_clv_openings_ceiling.md`, `state_layer2.md`, `state_kalshi.md`, `state_model.md`;
`docs/ai_context/decision_record.md`, `todo.md` (`#704`, `#709`, `#711`, `#719`, `#722`, `#727`, `#735`);
code: `syndicate/features/shared/{decision_record,layer2_board,opportunity_signals,portfolio_commit,venue_fees,daily_optimizer,optimizer_overlay}.py`,
`pipeline/{portfolio_commit,execute_portfolio}.py`.
