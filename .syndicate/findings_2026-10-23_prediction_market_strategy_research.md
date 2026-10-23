# Prediction-market trading strategy research, applied to Syndicate — 2026-10-23

Lane `in-game-trading`, session 15ceeb14. The user asked: research Kalshi and Polymarket as trading markets (internet and elsewhere), find the best methods for automated trading for profit, and apply them to Syndicate's sports markets, pregame and live, including "buying on dips".

**Method.** Two research agents read the web and the literature (read-only; sources are below). Their claims were then tested on our own recorded in-play data, 2 nights, 31 games, 706 Kalshi markets:
- `scripts/inplay_dip_study.py` (7ce27cb3)
- `scripts/inplay_price_buckets.py`

They were also checked against the ledger's earlier measurements:
- pregame maker study, `findings_2026-10-19_kalshi_maker_entry_paper.md`
- in-play findings, `findings_2026-10-20_in_game_trading.md` §1-9

## 1. What the outside evidence says (ranked by strength)

1. **Makers beat takers, but most of both lose.**
   - Kalshi, Bürgi, Deng & Whelan, "Makers and Takers" (2025/26, ~314k contract-prices): makers −9.6% vs takers −31.5% average return after fees. Makers buying at 50c or above earned +2.6%. Mostly non-sports data.
   - Polymarket, Akey et al., CEPR DP21615, and Galaxy Research 2026-10-01: 69% of accounts lose, and winners provide liquidity. *Sports specialists had the lowest win rate (25%).*
   - Betfair, Whelan 2025 (200k matches): makers +0.6 to +2.0%, takers −2.2 to −2.5%.
2. **Favourite-longshot bias.**
   - Kalshi contracts at 10c or below lose over 60% after fees; contracts above 70c earn small positive returns (Whelan).
   - Polymarket is underconfident (calibration slope 1.11).
   - Cross-game parlays/combos are overpriced vs their legs (Moshrefi 2026, 23M Kalshi sports trades).
3. **The late-game "Yogi Berra" bias** is the most replicated in-play anomaly. In the final minutes the trailing team's contracts are overpriced (Page 2012; Whelan 2025; Moshrefi 2026, final ~10 min).
4. **In-play news is absorbed within seconds to about 2 minutes** (Croxson & Reade 2014; Clegg et al. 2026: 99% within 2 min; Polymarket NBA: mispricings close in a median 3.6 s).
   - Residual effects are context-specific (cricket wickets, extreme surprises).
   - **There is no peer-reviewed support for a generic "buy the dip" rule.** Resting bids in play are a documented adverse-selection trap (Brown 2012: courtsiding/TV delay pick off quotes).
5. **CLV is necessary, not sufficient.**
   - Positive average CLV can still lose money; only the top CLV decile was clearly profitable (Whelan, 3,670 NBA games).
   - Line-move momentum is real but smaller than costs (Moskowitz 2021).
6. **Weak or anecdotal evidence:** cross-venue arbitrage (rare after a ~2.75% cost threshold), copying sharp books, harvesting near-certain 95-99c contracts (oracle/settlement wipeouts), liquidity-reward farming, in-play latency trading (venue delays of 1-3 s exist to neutralise it).

**Venue facts that matter to us** (agent report; unverified items are flagged in the agent text):
- **Kalshi taker fee** = 0.07·C·P(1−P). **Maker fee** = 0.0175·C·P(1−P) on NFL/NBA/NHL since 2025-07-01 (not 0).
- Kalshi Liquidity Incentive Program listed to 2026-09-01; extension unverified. The Volume Incentive Program is ending.
- **Polymarket US (QCX) taker fee** = 0.0695·C·p(1−p) per its CFTC filing 2026-09-29 (0.06 from July). Our `venue_fees.py` models it as a flat 1.5% of notional, which is **the wrong shape**:
  - The quadratic with 0.06 reproduces our own six recorded commissions: 0.06·0.235·0.765 = 1.08c vs the measured 1.066c (C65VD0R72KDG), and ≈1.48c at 0.43-0.47 vs the 1.5c fit.
  - Since 09-29 the mid-price fee is ≈1.74c, above our 1.5c assumption. The tails are far cheaper than we assume.
  - **Owner: whoever holds venue_fees / Polymarket pricing. A one-fill check against a post-09-29 Polymarket commission settles it.**
- Polymarket cancels open limit orders at scheduled game start and delays marketable sports orders 1-3 s.

## 2. What our own data says (tested here)

### 2a. Buying the dip in play: it LOSES, worse than random entry
`scripts/inplay_dip_study.py`. Values are per contract after fee; the CI is per entry, and entries within a game are correlated, so the intervals are optimistic. Read the signs.

| strategy | markout +5 min | settled | n (31 games) |
|---|---|---|---|
| random entry at the ask (cost baseline) | −2.6c | −2.6c | 28k |
| taker, after a >=10c drop in 60 s | −3.5c | **−5.4c** | 2.5k |
| taker, after a >=15c drop | −4.2c | −5.3c | 1.0k |
| maker, resting bid mid−5c, fills only if the market comes down (no fee) | −2.5c | **−5.1c** | 6.1k |
| maker, resting bid mid−10c | −2.6c | −5.8c | 2.3k |

- After a drop, the price continues about 1c further on average. That is momentum, not overreaction.
- Resting bids fill when the price is right to fall (adverse selection). They lose more than random taking despite paying no fee or spread.
- "Noise" dips (no score within ±90 s) lose too. Every sport is negative except NFL, which has one game.
- This replicates the pregame maker study: its filled orders won **5.37pp less** than the close implied.

### 2b. Price bucket × game phase (favourite-longshot, late game)
`scripts/inplay_price_buckets.py`, buying at the ask after fee, settled. Per-GAME means (29 games):

| cell | per-game mean | games positive |
|---|---|---|
| final period, favourites at 90-99c | +1.4c [−1.0, +3.8] | 23/29 |
| final period, longshots under 25c | **−5.0c [−7.5, −2.5]** | 7/29 |
| mid game, 10-25c | −0.4c (noise; one comeback drives the per-sample table) | 12/29 |

- The late-longshot loss is solid at the game level. The late-favourite edge is only a lean, consistent with the literature.

### 2c. Already in the ledger
- Book-consensus in-play edges mark out at −1.26c (CI −1.80..−0.72, n=1,613). Kalshi moves before the books.
- The fixed take-profit loses vs hold.
- The entry-rule sweep (2,160 configs) finds nothing positive out of sample (§9).
- The paper entry rule settled −8c/contract (n=24).

## 3. Applied to Syndicate

### Pregame (where our edge exists: the model vs the close)
1. **Keep making money where it is measured: model edge entered early and held.**
   - Require edge > fee + spread, gated on the measured CLV decile, not just on CLV > 0 (Whelan).
   - The min-EV floor tuner and the scorecard optimizer are the right owners.
2. **Avoid buying longshots.** Add or verify a floor that refuses long-shot buys (around 15c and below) unless the model edge is large. *Measure first:* the share of our live and paper stake below 15c and its settled ROI.
3. **Maker entry is NOT a general win for us.** The pregame maker shadow measured adverse selection. It stays paper in its two clean cells (soccer totals/spreads, NCAAF segment totals; kalshi-maker-shadow lane).
   - Note: Kalshi now charges makers 0.0175·P(1−P) on NFL/NBA/NHL. The shadow assumed 0 for "quadratic" series; check that this series list excludes those sports.
4. **Never buy combos/parlays.** If Kalshi RFQ/combos are ever offered to us, the evidence favours being the seller or responder, not the buyer.
5. **Fix the Polymarket fee model** (§1). Mid-price Polymarket edges are about 0.2-0.25c thinner than we compute. Owner lane decision.

### Live (in-game)
1. **Do not build dip-buying.** Both taker and maker forms lose more than random entry on our data, and the literature agrees.
2. **Do not enter on book consensus.** It lags Kalshi. The live entry switch stays OFF (findings §9).
3. **Late-game longshots: never buy them, and SELL ours.**
   - The robust in-play signal we found: under-25c contracts in the final period are overpriced by about 5c per game.
   - An exit rule "in the final period, sell a held leg priced under 25c at the bid" would capture part of that, if it beats the exit fee. *Testable now on recorded data* with the same per-game check before anything ships.
4. **Late-game favourites at 90-99c:** +1.4c per game, 23/29 positive, CI includes 0. A **paper cell to pre-register**, not a strategy. Tail risk is real (comebacks, settlement disputes, outages; Kalshi has gone down mid-game).
5. **In-play market making:** not on Kalshi in play. Our maker fills are adversely selected, and the venue gives makers no delay protection there. Polymarket's 1-3 s taker delay is maker protection, but our Polymarket book is pregame-only and a live Polymarket sale is unbuilt. Revisit only with a fair that beats the mid.
6. **Exits:** keep the hold guard at a bid of 0.90 or more (coordinator, 4eafd1d5). It points the same way: do not sell favourites cheaply late.

## 4. Proposed next steps (each needs its own user decision)
- (a) **Late-longshot SELL exit:** test on recorded nights per game (`inplay_price_buckets.py` + exit replay), then paper on the fast loop. Read-only test first.
- (b) **Pre-register the late-favourite paper cell** (90-99c, final period). GO only at >= 60 games with a per-game CI > 0.
- (c) **Polymarket fee model:** verify against a post-09-29 Polymarket commission, then refit `venue_fees.polymarket_fee_dollars` to 0.0695·p(1−p). Owner: venue-fees/Polymarket lane.
- (d) **Longshot exposure audit, pregame:** stake share and settled ROI by price bucket on the live and paper books.

## Sources (from the two agent reports; full lists in the session transcript)
Bürgi, Deng & Whelan, *Makers and Takers* (karlwhelan.com/Papers/Kalshi.pdf); Whelan, *Agreeing to Disagree* (MPRA 126351); Whelan, *The Truth about CLV* (karlwhelan.com/?p=2595); Moskowitz (2021) JF 76; Croxson & Reade (2014) EJ 124; Choi & Hui (2014) JEBO 107B; Angelini, De Angelis & Singleton (2022) IJF 38; Norton, Gray & Faff (2015) JBF 61; Page (2012) Applied Econ 44; Brown (2012) Applied Econ 44; Moshrefi (2026) arXiv 2607.14430; Clegg et al. (2026) arXiv 2605.16066; Akey et al. CEPR DP21615; Galaxy Research 2026-10-01; Saguillo et al. AFT 2025 (arXiv 2508.03474); QCX CFTC filing 2026-09-29 (cftc.gov/filings/orgrules/rules09292630356.pdf); docs.kalshi.com; docs.polymarket.com; help.kalshi.com Liquidity Incentive Program.


## 5. Pregame longshot audit, by entry price (user ask 2026-10-23)

`scripts/price_bucket_audit.py` over the execution-ledger ARCHIVE `orders_2026-10.jsonl` (fleet, read-only copy). 11,713 graded paper orders, 10-02..10-22, every paper book (paper, paper:kalshi, paper:polymarket, paper:novig, paper:prophetx, ladders). PREGAME only. ROI = pnl/stake with a GAME-clustered 95% CI.

**Below 15c is a non-issue:** 24 orders / 17 games, **0.1% of stake**, ROI −88%. A 15c floor is harmless but saves ~$55 of paper stake in 3 weeks.

**The real losses are wider, at BOTH ends** (all books):

| entry price | stake share | ROI [game-clustered CI] |
|---|---|---|
| 15-25c | 0.6% | −22.8% [−64, +18] |
| **25-40c** | 3.1% | **−37.3% [−55, −19]** |
| 40-60c | 69.4% | −2.4% [−9.5, +4.8] |
| 60-75c | 11.2% | +9.7% [−4.9, +24] |
| **75-90c** | 14.4% | **−17.1% [−33, −1]** |
| **90c+** | 1.2% | **−58.0% [−93, −23]** |

**Every week, three bands:**

| band | wk1 | wk2 | wk3 |
|---|---|---|---|
| under 40c | −36.6% [−58, −15] | −35.7% [−64, −7] | −35.7% [−71, −1] |
| 40-75c | −2.7% | −1.6% | +6.1% |
| 75c+ | −37.1% [−64, −10] | −13.1% [−33, +7] | −14.9% [−55, +25] |

- **Reading:** the model is overconfident at extreme prices. Its "edges" on longshots and on heavy favourites are not real, while the 40-75c core is roughly break-even to slightly positive. This is a calibration problem, not only a longshot one.
- It agrees with the market evidence on longshots (§1). It contradicts the market-level "favourites earn small positive returns": OUR favourite picks lose, because our model selects favourites it overrates.
- **LIVE exposure** (LIVE_LEDGER_ROW lines 10-20..10-23, filled, latest row per order): 75c+ = **36.8% of live stake** ($151 / 32 fills), 40-75c = 61%, under 40c = 2%. Only 25 graded live rows, too few to judge live alone.

**Options (user decision):**
- (A) **Entry price band** for pregame buys, e.g. refuse < 0.40 and >= 0.75 (or start with < 0.40 only: strong in every week, ~4% of stake).
- (B) **Fix the cause:** shrink model probabilities toward the market at the extremes (the daily optimizer already fits a calibration shrink w*; check whether it is applied to the live sizing path).
- (C) **Shadow first:** count what the band would have refused on the live book for 1-2 weeks.

Owners: live sizing and gates sit with the coordinator lane (332cb014); the model calibration sits with the optimizer/scorecard lanes.
