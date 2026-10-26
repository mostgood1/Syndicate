# Decision policy v1, PAPER track — pre-registration `[2026-10-26, lane decision-policy-paper, Decision Engine Phase 2, #736]`

**Written and committed BEFORE** (a) the z / σ fit below was computed, and (b) any forward paper bet
existed. Before writing it I had read code only (`decision_record.py`, `syndicate_fair_runtime.py`,
`syndicate_fair.py`, `scripts/syndicate_fair_fit.py`, `event_concentration.axis_key`), plus the field
NAMES and array SHAPES of the stage-1 diag files in `C:\tmp\sfv1\diag\` (no values). I opened no
DecisionRecord file, no paper or live ledger and no outcome. Changing anything below after this commit is
a new registration, named as one, and bets already booked keep the σ and z stamped on their own row.

Plan: `docs/ai_context/plan_syndicate_decision_engine.md` §3 L3 (the formulas), §4 E1, §7, §8 Phase 2,
§9. User decisions (`state.md` `[user-decisions]` 2026-10-26): **D2** select and size on venue-native net
EV, paper2 first, canary live only after the gate; **D6** live capital stays at canary until the gate.

## 0. What this is, and what it is not

- **A PAPER-ONLY track.** A job reads the latest DecisionRecord file for a date
  (`<data root>/reports/intelligence/decision_records/<date>.json.gz`, rewritten by every heavy build)
  and writes its OWN book under `<data root>/reports/intelligence/decision_policy_paper/`. It imports no
  order module (a test pins that). Nothing reads its book for placement, sizing or the board.
- **No market-level gate.** Every line is its own decision. Uncertainty shrinks a line's edge through
  `EV_lb`; it never switches a market, family or sport off. The gates in §1 are per-line data quality
  and timing.
- **No staked probability changes** (`#704`'s 11-02 read), no live order path, no plan, no board change.
- **In play is out of scope** (E7, the in-play program).
- `p_fair_v1` is **never** used (user, 10-26). Only `sigma_fair_v1` is read.

## 1. The population: one candidate per (record, venue), every heavy build

A **candidate** is one DecisionRecord (one side of one board line) at one venue
`v ∈ {kalshi, polymarket}` for which the record carries a venue `PriceQuote` with `price_prob` and
`fee_per_contract`. The **decision instant** `t_d` is the record header's `written_at`. A candidate is
eligible only if every per-line gate passes:

| gate | rule |
|---|---|
| G1 pregame | `commence_time` parses, `t_d < commence_time`, and `identity.game_state` is not live / in_progress / final |
| G2 decision window | `commence_time − t_d ≤ 36 h` — the window σ is fitted on. A line further out is decided when it enters the window: a timing rule, not an exclusion |
| G3 market fair | `market.p_market` present and `market.two_sided` true |
| G4 quote | `market.suspect_stale` is not true |
| G5 plausible venue price | the record's own `plausible_price` gate for `live:<v>` passed |
| G6 contract identity | the record's `live:<v>` contract identity is not `wrong_date` |
| G7 cost | `0 < c < 1`, with `c = price_prob + fee_per_contract` |

The venue price is what the board's venue feed recorded for that side (Kalshi `*_ask_dollars` via
`kalshi_client`; Polymarket US likewise). Its fee is the record's `venue_fees.taker_fee_per_contract`
(Kalshi 0.07·q(1−q) with series multipliers, Polymarket US 0.0695·q(1−q)).

## 2. The policy (plan §3 L3)

```
p        = market.p_market                      # the Shin consensus; = p_decision wherever w_model = 0 (D3)
sigma    = sigma source S1 / S2 / S3 below      # one-vs-rest LOGIT scale, this side
p_lb     = sigmoid(logit p − z_s · sigma)        # z_s fitted per sigma source (section 3)
c        = price_prob + fee_per_contract         # per $1 payout, the venue's own ask
EV_net   = p / c − 1
EV_lb    = p_lb / c − 1
```

**σ sources, in order** (the plan's "σ inflating at each step"):

- **S1** `fair_v1.sigma_fair_v1` from the record, where recorded (the four stage-1 PASS families — NCAAF
  game, NHL game, NHL props, soccer game — within 36 h, once a refresh-worker restart loads `636ba4ff`).
- **S2** otherwise, the **book-dispersion σ**, computed by the paper job from the same book grid the
  record's fair_v1 reads (`<sport>_source/data/book_grid/book_grid_<date>.json`, the selected date and the
  next). Per book: Shin de-vig of its two-sided price (`opportunity_signals.devig`, `"shin"`), quotes older
  than 12 h dropped, at least 2 books. With equal weights `π_b = 1/n`: the log pool `p_eq`,
  `D² = Σ_b π_b (logit p_b − logit p_eq)²` on this side, and

  `σ_S2² = D²·Σπ_b² + r²_S2(kind, mfam, tts)`

  — `syndicate_fair.sigma_fair`'s form with equal weights. `mfam` = `syndicate_fair.market_family`, `tts` =
  `syndicate_fair_runtime.tts_bucket` of `commence − t_d`.
- **S3** when S2 cannot be computed (no grid line, fewer than 2 books, a one-sided grid line):
  `σ_S3 = 2 · sqrt(max over cells of r²_S2)`, flagged `sigma_source = "S3_inflated"`. It uses `z_S2`.

## 3. Fitting z (and r²_S2) — once, before the forward test, then frozen

**Target level: a one-sided 84.13% lower bound (Φ(1)).** `z_s` is the value with
`P( logit T − logit p < −z_s·σ_s ) = 0.1587` on held-out rows, where `T` is the close. Why this level:
stage 1 found ±1σ calibrated (0.70–0.74) and ±2σ short (0.90–0.94), so the tail is heavier than normal;
the 1σ quantile is the one these data estimate stably, and the fitted z replaces the normal 1.0 there.

- **z_S1**: the stage-1 walk-forward held-out arrays of the REGISTERED arm
  (`C:\tmp\sfv1\diag\<family>_registered.npz`) for the four S1 families. Every outcome of every row with a
  close target (`has_t`), finite `sigma > 0`: `u = (logit T_j − logit base_j) / sigma_j`, `base` = the Shin
  median at the snapshot (the board's `p_market`, parity 0/3,125 in stage 1), `T` = Pinnacle (power) close
  else the Shin-median close. Both outcomes of a two-way line count (a bet can be on either side).
  `z_S1 = −quantile(u, 0.1587)`.
  - **Input check, before the quantile is taken:** the arrays' ±1σ coverage around `p_v1` (scored
    outcomes as `syndicate_fair.scored_outcomes` defines them) must reproduce the published stage-1 values
    (`findings_2026-10-26_syndicate_fair_v1.md` §4: NCAAF game 0.717, NHL game 0.735, NHL props 0.772,
    soccer game 0.700) within 0.01 per family. If it does not, the arrays are not what I think they are:
    z_S1 is not fitted and S1 lines use z_S2.
- **r²_S2 and z_S2**: rows assembled by `scripts/syndicate_fair_fit.assemble_sport` from the stage-1
  extract in `C:\tmp\sfv1` (kickoffs 2026-09-30 .. 10-26 08:00Z, all seven sports, the same snapshots
  t24h / t6h / t2h / t30m, the same close). **Time split by UTC commence date:** the first two thirds of the
  dates (date order) fit `r²_S2` per (kind, mfam, tts) `= max(0, mean(resid²) − mean(D²·Σπ²))` pooled over
  sports (`syndicate_fair.fit_residual_var`'s estimator, equal weights); a cell with fewer than 200
  training outcomes takes its (kind, mfam) value, then its kind value. The last third of the dates is held
  out: `z_S2 = −quantile(u_S2, 0.1587)` with `u_S2` computed under that σ_S2.
- **Reported, never used:** z by sport family, z against the sharp-only target, and each source's
  two-sided ±1σ / ±2σ coverage.
- **Degenerate-fit guard:** a fitted z outside [0.5, 2.0] is not used; that source takes z = 1.0, and the
  anomaly is reported.
- The fit (`scripts/fit_decision_policy_z.py`) writes `syndicate/features/shared/decision_policy_v1_params.json`:
  z_S1, z_S2, the r²_S2 cells with their n, the data window and the code SHA. It is committed after this
  file.

## 4. Sizing (stamped on every bet; the gate does NOT read it)

- Paper bankroll **B = 1,000 units, fixed** (no compounding) for the whole test.
- `f_kelly_lb = max(0, (p_lb − c) / (1 − c))`.
- **Baker–McHale shrink** `λ = Δ² / (Δ² + s_p²)`, `Δ = p − c`, `s_p = σ·p·(1 − p)` (delta method);
  `λ = 0` when `Δ ≤ 0`.
- `f = min(0.02, f_kelly_lb · λ)`; `stake_units = round(f · B, 2)`.
- **Per game:** a strategy's stakes on one event sum to at most 0.05·B; a later bet on that event is cut to
  the room left (possibly 0). It is still booked and graded flat.
- **Ladders and game axes count once (`#711` R1):** at most ONE bet per (strategy, `event_id`,
  `event_concentration.axis_key`) for the whole test, across both venues. The axis is the executor's own:
  `margin|seg` holds the moneyline, the spread and every alt-spread rung; `total|seg`; `teamtotal|…|seg`;
  `prop|market|player|seg`.

## 5. Strategies

| id | role | qualifies when | within a build, per (event, axis), the one booked |
|---|---|---|---|
| **P1 `ev_lb`** | candidate (primary) | `EV_lb > 0` | largest `EV_lb` |
| **P2 `net_floor_719`** | candidate | `EV_net ≥ 1.0%` at Kalshi / `≥ 0.5%` at Polymarket (`#719`) | largest `EV_net` |
| **C0 `suggested_2pct`** | comparator, never a candidate | `board_suggested` is true (today's Suggested: 2% at the best book, two-sided, plausible, fresh, one side per line) and the venue quotes that side; booked at the venue's ask | largest `board_ev_pct`, then lower `c` |

All three use the same §1 gates on the same lines. **Decide once:** a (strategy, event, axis) is booked at
the FIRST build at which it qualifies and is held to settlement (plan §3 L3 "Exits": hold by default).

## 6. Grading

- **The sharp close (the gate's truth):** Pinnacle's last pregame two-sided pair on the bet's own line
  (`captured_at ≤ commence`; both sides; the later side within 12 h of commence), from the sport's
  `book_quotes` shards for the commence US-Central date and the day before, **power** de-vig — exactly the
  close `syndicate_fair_fit.assemble_sport` takes. `p_close` is the bet's side.
- **CLV_net** per bet (%) `= 100 · (p_close / c − 1)`, `c` the booked cost (ask + fee): fee-net CLV against
  the sharp close in EV-at-close form (the same form as the Suggested grade's "EV at the Shin close").
- A bet with no Pinnacle close at its own line is **outside the gate population**. It is counted and
  reported by sport and market family, with its CLV against the Shin-median consensus close (≥ 2 books) at
  the same line, so a selection effect from moved lines is visible.
- **Outcome (the ROI judge):** full-game h2h / spreads / totals, settled from the final score
  (`layer2_live_scorecard.grade` on the fleet's game chips): win `+(1 − c)/c` per unit staked at cost `c`,
  loss `−1`, push `0`. Props and segments have no outcome grader in v1: ROI-ungraded, reported as coverage.

## 7. The edge gate (decisive)

Per candidate `k ∈ {P1, P2}`, over its bets WITH a sharp close:

- `x_i = CLV_net_i`, flat (one per bet). `x̄` their mean. Game-clustered SE with `G` events:
  `SE² = G/(G−1) · Σ_g (Σ_{i∈g} (x_i − x̄))² / n²`. `Z = x̄ / SE`.
- **Looks** (each strategy's own): **L1** the first daily read with `n ≥ 400` and `games ≥ 100`;
  **L2** `n ≥ 800` and `games ≥ 200`; **L3 (final)** `n ≥ 1,200` and `games ≥ 300`, **or** the read on
  **2027-01-31** (the end of plan Phase 3), whichever comes first.
- **Boundaries:** O'Brien–Fleming, K = 3, equal information spacing, one-sided α = 0.0125 per candidate
  (Bonferroni over the two candidates, family-wise one-sided 0.025). Computed before this file from the
  joint normal of the three looks, Monte Carlo-checked (2M paths: 0.01242):

  | look | Z must be ≥ | nominal one-sided p |
  |---|---|---|
  | L1 | **3.935** | 0.00004 |
  | L2 | **2.783** | 0.0027 |
  | L3 | **2.272** | 0.0115 |

  (The same code reproduces the textbook α = 0.025 values 3.471 / 2.454 / 2.004.)
- **PASS** = a candidate's Z clears its look's boundary. The first pass ends that candidate's test; later
  looks are reported, not re-decided.
- **Then ROI.** At a pass, the strategy's outcome-graded bets give a flat ROI with a game-clustered
  bootstrap 95% CI. A pass whose ROI CI lies **wholly below 0** is reported as a **CLV/ROI CONTRADICTION**
  and does not clear the strategy for canary live: the user decides.
- A pass does not change live. Canary live is D2/D6's next step and the user's decision.
- **Reported at every read, never decisive:** a game-clustered bootstrap 95% CI (2,000 resamples, seed
  20261026); C0 on the same statistic; per venue, sport and market family; the 0.40–0.75 price-band subset
  (the live band, user 10-23 — the canary step reads it before promotion); the σ-source mix; stake-weighted
  CLV and ROI under §4; and P1 − C0 on the axes both booked.

## 8. Kill rule (plan §9, unchanged)

If no candidate passes by its final look (no later than the 2027-01-31 read): live capital stays at
canary; the board stays a research surface while the engine keeps learning; the next lever is a better
fair (E1/E3), not more capital. A candidate that never reaches L1 by 2027-01-31 has not passed.

## 9. Known biases, stated before the data

- **Paper fill:** a full fill at the recorded ask at the build instant. No depth, no slippage, and no
  venue-quote age (the record does not carry one per venue). This biases paper CLV UP against live; canary
  live is where it is measured.
- **Moved lines** drop out of the gate population (section 6); the dropped share and its consensus CLV are
  reported.
- **Sharp coverage** is uneven (`state_venues.md` `[sharp-reference-price]`): Pinnacle game lines all
  window for NCAAF (and MLB, now out of season), from 10-25 for NFL / NBA / soccer, none for NHL game lines;
  NHL props all window, NBA props from 10-25. The gate is read on whatever mix that produces, reported by
  sport.
- **Decide once on the first qualifying build** selects for transient venue prices. That is the edge
  hypothesis itself (E1), and the sharp close is what grades it.

## 10. Reads

- The job books after every heavy build it sees and grades once a day; the evaluator writes the day's read.
- Dated reads are in `#717`'s register (`docs/ai_context/todo.md`), so the gate never rests on a one-time
  scheduled task: weekly on Mondays from the first Monday after the job is enabled, until L1; the final read
  2027-01-31.
