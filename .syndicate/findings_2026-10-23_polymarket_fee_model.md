# Polymarket US fee model: verified against the filings and our own fills — 2026-10-23

Lane `polymarket-fee-quadratic`, session 9333b297. This follows up §1 / §4(c) of
`findings_2026-10-23_prediction_market_strategy_research.md`. Read-only: no code changed, nothing deployed.

**Verdict.** The straight-trade taker fee on Polymarket US is `0.0695 × C × p × (1−p)`, rounded to the cent per fill.
`venue_fees.polymarket_fee_dollars` charges a flat `0.015 × C`, which is the wrong shape.
- 17 of our 18 live fills since go-live match the quadratic to the cent. The 18th is 1¢ BELOW it, which the venue's rounding rule allows.
- On the current board the refit thins 47 of 49 Polymarket rows by about 0.5 pp of stake.
- **It takes all 7 rows that pass today's 0.5% live floor below the floor.**

## 1. The fee schedule (primary sources: QCX CFTC filings, extracted from the PDFs)

| effective | change | source |
|---|---|---|
| 2026-04-03 (secondary sources) | Θ_taker = 0.05; maker rebate Θ = −0.0125 (25% of the taker fee, paid at the time of trade) | the 10-02 filing dates the rebate to the 2026-03-27 submission |
| **2026-07-01 00:00 ET** | Θ_taker 0.05 → **0.06**. Formula `Fee = Θ·C·p·(1−p)`; maximum $1.50 per 100 contracts at p = 0.50. Maker rebate unchanged. | `rules0707269057.pdf` (filed 07-07) |
| **by 2026-09-25; exact date unconfirmed** | Θ_taker 0.06 → **0.0695** (maximum $1.74 per 100) | The 09-29 filing says straight trades "remain" `0.0695·C·p·(1−p)`. A third-party fee-watcher PR dates the docs change to 2026-10-01 10:00 ET, and its own filing was not found. **Our first post-change fill is 10-20, so the date does not affect anything we traded.** |
| 2026-09-25 00:00 ET | combos only: `C·p·[0.0695(1−p) + 0.04(1−p)^4]` (the docs page now shows 0.06 for the quartic term) | `rules09292630356.pdf` (filed 09-29) |
| 2026-10-07 | table tennis taker Θ = 0.10; combos get no maker rebate (combo maker fee = 0) | `rules10142633348.pdf`, `rules10132632911.pdf` |
| **2026-10-19 13:00 ET** | maker rebate becomes TIERED by prior-month maker notional: below $10M none; $10M+ −0.0035; $50M+ −0.0070; $200M+ −0.0104 | `rules10022631178.pdf` (filed 10-02, certified 10-19); docs.polymarket.us/fees |

- **Rounding** (docs): fees are rounded to the cent with banker's rounding (half to even), per fill. An order that fills against several resting orders is never charged more than the rounded cumulative exact fee; that adjustment can only LOWER a charge.
- **Taker rebate tiers** start at $250k of monthly taker volume (3%). We are far below that.
- **The Θ = −0.0125 maker rebate was real until 10-19 13:00 ET. From then on our maker rebate is ZERO** (Tier 1: under $10M of maker volume).
- `commissionsBasisPoints` reads `'0'` on all 18 fills, so the `COMMISSION_RATE_APPEARED` alarm cannot fire for this change. That field has no way to express a quadratic.

## 2. Fit against our real commissions

Population: **every live Polymarket fill with a recorded commission.**
- Source: the fleet's Redis `execution_ledger.json`, 3,000 rows (`mode=live`, `fees_dollars` set). It agrees with the `[polymarket_us_orders] COMMISSION` log lines in `~/syndicate-prod/logs` on order id, count and fee.
- That gives 18 orders, 2026-10-20 23:09Z → 2026-10-23 04:29Z.
- There are no live Polymarket fills between 09-28 and 10-19: Render was suspended and the fleet went live on 10-19.
- The 132 earlier live fills (08-26..09-27) have `fees_dollars = null` because fee capture had not been wired yet. They cannot test the 0.06 → 0.0695 date.
- C = `fill_stake_dollars / fill_price`. The models are rounded half-even to the cent.

| model | exact on all 18 | exact on the 8 fills where the models disagree after rounding | total modelled vs $1.51 paid | Σ\|err\| |
|---|---|---|---|---|
| flat $0.015/contract (current code) | 11 | 1 | $1.36 | $0.19 |
| 0.06·C·p(1−p) | 10 | **0** | $1.31 | $0.20 |
| **0.0695·C·p(1−p)** | **17** | **7** | **$1.52** | **$0.01** |

By price:
- **p = 0.47-0.49, about 11.3 contracts (6 fills): 5 × $0.20, all exact for 0.0695 (flat and 0.06 both give $0.17).**
  - `D816C6F010JF` (11.51 @ 0.47) was charged $0.19 against an exact fee of $0.1993. That is 1¢ below, consistent with per-fill rounding across several resting orders, which can only lower a charge.
- **p = 0.755, 10.03 contracts (`D7X0DKEG10JE`): charged $0.13.** The quadratic at 0.0695 gives $0.13; flat gives $0.15 and 0.06 gives $0.11. This is the one off-mid fill that separates all three models, and the quadratic wins.
- p = 0.35, 1.09 contracts: charged $0.02. 0.0695 and flat both give 0.02; 0.06 gives 0.01.
- 10 small fills (0.44-1.08 contracts) at 0.47-0.53 round identically under every model.
- **Implied Θ over the 7 fills above 5 contracts: 0.0700.**
- **Pre-change cross-check:** the six 08-30 commissions recorded in `venue_fees.py`'s docstring fit Θ = 0.06, the rate in force then. One example is `C65VD0R72KDG`: 13.13 @ 0.235 → $0.14, against 0.06 → $0.1416. So both regimes fit the same formula.

**Not covered by our data:** tails below 0.35 or above 0.755. That shape rests on the filing, not on a fill of ours.

## 3. Who reads the Polymarket fee (callers on origin/main 9260ea0b)

- `venue_fees.taker_fee_per_contract("polymarket", …)` returns `POLYMARKET_MEASURED_NOTIONAL_RATE` flat, with basis `polymarket_measured_notional`. Its consumers:
  - **`layer2_board.venue_fee_per_contract` → `score_v2` → `ev_net_pct`.** That is what the 0.5% live Polymarket floor reads (`SYNDICATE_LIVE_NET_FLOOR_POLYMARKET=0.5` on refresh-worker), so this path selects live bets.
  - `execution_ledger` (around line 2495): the paper-fill fee.
  - `venue_capital`, `venue_scope`, `cheat_sheets`, and the study scripts `paper_bet_optimization.py` and `venue_native_selection_study.py`.
- `polymarket_fee_dollars`:
  - `execution_exits.estimate_fee` (Polymarket exit fee)
  - `venue_basis_edge` (around line 459)
  - `kalshi_polymarket_arb` (unbounded branch)
- `polymarket_worst_case_fee_dollars` / `POLYMARKET_ASSUMED_WORST_CASE_RATE` (0.02 flat): the arb bound. `kalshi_polymarket_arb` line 489 applies the 0.02 rate as a QUADRATIC in its bounded branch, which contradicts its own comment. Under the new schedule that is 0.5¢ at the mid, below the real 1.74¢. **That bound currently undercuts the truth.**
- `POLYMARKET_MEASURED_NOTIONAL_RATE`: `kalshi_polymarket_arb` line 492.
- Tests that pin the flat shape:
  - `tests/test_venue_fees.py` (13 references)
  - `test_arb_net_edge.py` (6)
  - `test_paper_fees_and_closing_marks.py` (2)
  - `test_venue_order_fee_ceiling.py` (2)

## 4. EV impact on the current board

The board read was the fleet Redis Layer 2 shortlists for 10-23, 10-24 and 10-25: 44 keys, **49 unique rows priced at Polymarket** (`fee_basis = polymarket_measured_notional`).
- New fee minus old fee per contract is `0.0695·p(1−p) − 0.015`.
- The EV shift is about `−delta / p` of stake. This is an approximation, not a re-run of `score_v2`.

- The new fee crosses the old one at p = 0.315 and p = 0.685. **Between those prices the new fee is dearer, by up to +0.24¢ at the mid. Outside them it is cheaper**: −0.10¢ at 0.72, and −1.2¢ at 0.95, where the new fee is 0.33¢ against 1.5¢.
- **On this board, 47 of 49 rows get thinner** (mean +0.21¢ per contract, −0.44 to −0.49 pp of stake at 0.44-0.51). Only 2 get cheaper (both at 0.72, +0.14 pp). The board's Polymarket rows sit almost entirely at 0.39-0.67, because they are totals, spreads and BTTS.
- **The floor flips.** All 7 rows at or above the 0.5% Polymarket floor fall below it:
  - 6 NCAAF totals, `ev_net` 0.853 → ≈0.36
  - 1 NCAAF spread, 0.861 → ≈0.37
  - That is 7 → 0 live-eligible Polymarket rows on this board. 9 → 7 rows stay above zero.
- **Realised P&L is already correct.** `fees_dollars` records what the venue charged. The error is in SELECTION and SIZING: we pick and size mid-price Polymarket bets as if they cost 1.50¢ when they cost 1.73¢.
- The 10-19 rebate change matters only if we ever rest maker orders on Polymarket. We now earn no rebate (Tier 1), where before we earned about 0.31¢ at the mid.

## 5. Proposed refit (lane `polymarket-fee-quadratic`, NOT built; it waits for the user)

1. `venue_fees.py`:
   - Add `POLYMARKET_TAKER_THETA = 0.0695` and `POLYMARKET_TAKER_THETA_EFFECTIVE`, with the filing citations.
   - Make `polymarket_fee_dollars` return `round_half_even_cent(Θ·C·p·(1−p))`. It currently ceils to 4 decimal places. Use half-even to the cent, per fill, as the docs specify. For per-contract EV, keep the unrounded rate.
   - `taker_fee_per_contract("polymarket")` returns `Θ·p·(1−p)` with basis `polymarket_filed_quadratic`.
   - Keep `POLYMARKET_MEASURED_NOTIONAL_RATE` only as a named, retracted constant, the way the module already keeps its retractions. Remove it from the active path.
   - Worst-case bound: a quadratic with Θ_bound = 0.10 (the highest filed straight-trade Θ, table tennis). The `bound >= measured at every p` test stays.
   - Leave the combo formula out of scope. We never buy combos (research §3.4), so a combo row should be refused rather than priced.
2. `kalshi_polymarket_arb` lines 482-492: delete the flat branch and its now-false comment ("Polymarket's is a flat proportion"). Bounded and unbounded both become the quadratic at their respective Θ.
3. Tests:
   - A fixture of the 18 real fills, asserting 17 exact and none above.
   - The p = 0.755 discriminator.
   - Parity with the 08-30 regime at Θ = 0.06 (`C65VD0R72KDG` → $0.14).
   - Bound ≥ fee at p ∈ {0.01, 0.05, 0.5, 0.95, 0.99}.
   - Update the four test files listed in §3.
4. **Before the live floor is touched:** state in the deploy's `--expect` that the Polymarket live candidate count falls on a mid-price-heavy board. 7 → 0 on today's board is a real behaviour change, not a regression. Whether to lower `LIVE_NET_FLOOR_POLYMARKET` is a separate user decision, and this note does not recommend it.
5. Docstring: the "150 BPS OF NOTIONAL, FLAT" section becomes a retraction. Its own crossover analysis predicted this break, and the 0.755 fill confirms it.

## Decision requested from the user
- **(A) Build the refit** in this lane, ship to main, and deploy behind the claims and preflight. Effect: Polymarket picks get priced at the real fee, and today's 7 live-eligible rows drop out.
- **(B) Build but do not deploy.**
- **(C) Leave the flat 1.5¢.** It understates mid-price fees by about 0.23¢, about 0.5 pp of stake.

Recommendation: **(A)**. The fee is filed, and 17 of 18 of our own fills confirm it.

Raw extracts are in `C:\tmp\pmfee\`: filing PDFs and text, `comm.json`, `ledger_live.json`, `board_pm_v3.json`.
