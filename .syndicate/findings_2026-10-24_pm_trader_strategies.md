# How traders make money on Kalshi and Polymarket, mapped onto Syndicate: 2026-10-24

Lane `pm-trader-strategies`, session dbda2142, a side session of the portfolio endpoint (a21617bf).
This is research and design only. No fleet, env, order, cap or deploy change was made.

The user asked: "there has to be data out there in terms of how traders make money using kalshi and poly that we can apply here."

## Method and what this does NOT redo

- **Sources.** Three read-only research passes (venue documents and CFTC filings; academic papers; practitioner and on-chain evidence) plus two live public-API reads:
  - Kalshi `GET /incentive_programs`, all 7,454 active programs, read 2026-10-24 ~22:30Z;
  - Kalshi `/markets?status=settled` and `/markets/trades`, a probe confirming that public history carries `taker_side` and `result`.
- **Builds on, and does not redo:**
  - `findings_2026-10-23_prediction_market_strategy_research.md` (044e2634): makers beat takers, longshot and late-game bias, dip-buying loses on our data, the pregame price-band audit.
  - `findings_2026-10-24_live_cell_scorecard.md` (30b5daba, profit-program): no cell has a proven edge.
  - `findings_2026-10-24_maker_vs_taker_shadow.md` (maker-orders-study, pre-registered, not yet run): a resting bid in place of each of our own live fills.
  - The `kalshi-maker-shadow` job (pre-reg 023f3978): consensus-fair resting bids in 3 cells.
  - `findings_2026-10-20_in_game_trading.md`: Kalshi leads the books in play; take-profit loses vs hold.
- **Source grades.**
  - **A** = full trade data, on-chain data or a primary venue document.
  - **B** = a working paper with real data, or a named trader with checkable P&L.
  - **C** = a blog, vendor post or anecdote.
  - **D** = marketing or an unverifiable post.

## 0. The one-paragraph answer

The people who make money on these venues mostly do one thing we do not: **they are paid to be on the other side of takers.**

- On Kalshi sports, every trade 2021-06..2025-11 (43.6M trades): takers **-1.11%** mean excess return, makers **+1.12%** (A).
- On Polymarket, bots placed 80.8% of orders and finished **+$246.8M**; retail finished **-$338.9M**. Sports specialists had the worst win rate of any topic, **25.1%** (A, via press).
- The top public sports wallets earn about **1% of volume** at very high turnover: swisstony +$18.5M on $1.85B (A for the P&L; method unknown).

**We lose about 12-18% of stake, roughly ten times the average taker's loss.** Being a taker explains about 1-2 points of that. The rest is **selection**: what we choose to buy, and when. That matches our own data:
- before fees we are still -12.8% (Kalshi) and -28.6% (Polymarket);
- the price-band audit loses at both ends (044e2634 §5).

**What the evidence says does work for a small automated trader:**
1. Not buying where takers are worst: longshots, late-game trailing teams, parlays.
2. Requiring an edge over a fresh sharp price that clears the ALL-IN cost, not just CLV > 0.
3. Earning the spread, but only where fills are not adversely selected. Ours so far are.

**Two things that do NOT reach us, measured today:**
- **Kalshi's liquidity rewards do not reach any market we trade.** 7,454 active programs; **0** on a game, spread or total series. Sports rewards sit only on futures and novelty markets (`KXMLBSERIESHR`, `KXNHLSEASONGOALS`, `KXMLBWSMVP`, ...).
- **Polymarket's international rewards and 15% maker rebate are on a venue we do not use.** Polymarket US's maker rebate is 0 below $10M of monthly maker notional.

## 1. The methods, graded

Edge sizes are per dollar staked unless stated. Capacity means for us: about $5-$10 a bet, a few hundred bets a week.

| # | Method | Evidence | Typical edge | Capacity | What it takes |
|---|---|---|---|---|---|
| 1 | Passive market making (earn the spread) | **Strong on the sign** (A: Becker 72M Kalshi trades; Bürgi-Deng-Whelan 314k contract-prices; Betfair 902k bets) | Makers about +1% per trade on Kalshi sports. 0 to +2% pregame on Betfair. **Negative on longshots and late in play.** SD about 200%: Kelly would stake about 0.5% | Bounded by fills and by adverse selection. The named winners are SIG, Jump, DraftKings, Flutter | A fair that beats the mid, fast cancels on news, inventory limits. **Ours: fills won 5.37pp below the close (10-19 study)** |
| 1b | Liquidity-reward farming | Weak (C). No study measures returns. The only open-source bot (poly-maker) says it "can lose money" | Pools: Polymarket about $300k/month platform-wide (C). Kalshi LIP pays $10-$10k per market per day (filing) | **0 for us on Kalshi** (no game, spread or total market has a program); Polymarket international is not our venue; Polymarket US eligibility unverified | Two-sided quoting at Target Size (100-10,000 contracts) near the touch |
| 2 | Cross-venue arbitrage | Within Polymarket: $39.6M over 2024-25, before fees, sports-heavy (B: Saguillo et al.). Kalshi vs Polymarket vs books: **no rigorous study** | NBA in play: single-market arbs 7 episodes, median 3.6 s. Combinatorial 290 episodes, median 101 bps, 77% capped at about 15 shares (B) | Small, contested by bots, fees now on both venues | Simultaneous quotes, capital at both venues, identical settlement rules. **Ours (08-30): 12 Kalshi-Polymarket pairs, 0 positive; best -0.87c even with a free Polymarket** |
| 3 | Sharp-book anchoring / CLV | Medium. Consensus-deviation betting: +3.5% (56k-bet sim), +8.5% real money on 265 bets (B: Kaunitz 2017, sportsbooks). **Whelan (3,670 NBA games): only the TOP CLV decile pays (+11.4%); the 9th decile had +5% CLV and +0.2% profit** | 1-5% where an exchange price is stale against a sharp price | Top-of-book depth about $220-$500 a line (C, vendor snapshot). No account limits on exchanges | A FRESH sharp quote, a threshold above all-in cost, and depth. **This is what our live book already does, and it loses. See §2.** |
| 4 | Latency on news, injuries, lineups, in-play events | Weak for profit (C; one esports bot, about $208k in 3 months). Betfair absorbs goals in seconds (A: Croxson-Reade); Polymarket NBA mispricings close in a median 3.6 s | Large per event, rare | Venue design works against it: Polymarket delays sports takers 1-3 s and cancels resting orders at kickoff | Official data feeds and sub-second execution. **Ours: Kalshi's ask moves about 34 s before ESPN; our fleet polls every 2-5 min. We are the slow side, not the fast one** |
| 5 | Favourite-longshot bias | **Strong** (A/B: Bürgi-Deng-Whelan; Becker; Whelan Betfair; Le 2026) | Contracts at 10c or less lose over 60% after fees. Contracts at 70c or more earn small positive returns (about +1-3%). Makers buying at 50c+ about +2.6% | High: it is a filter, not a flow | A price filter. **Ours: our 75c+ PICKS lose (-17% to -58%), because our model selects favourites it overrates** |
| 5b | Late-game bias ("Yogi Berra") | **Strong, 3 independent sources** (Page 2012 InTrade; Whelan Betfair, bottom-decile late takers about -70%; Moshrefi 2026, 23M Kalshi trades, final-5-min Platt slope NBA 1.62, MLB 2.05, **NHL 4.56**) | Late longshots badly overpriced. Late favourites a small taker-POSITIVE cell (Betfair 2nd half) | Medium: in-play depth, a few games a night | In-play quotes and a clock. **Ours: final-period under-25c -5.0c per game [-7.5, -2.5]; 90-99c +1.4c [-1.0, +3.8], 23/29 games positive (044e2634 §2b)** |
| 6 | Event-resolution edge cases ("resolution arb", buying 97-99c) | Mixed (A/C). A small positive return on high-priced contracts exists (Becker, Whelan); the tail is documented | Small, with fat tails | Low | Rule reading. **Counter-cases:** Giants-Angels 2026-07-24 score correction (Kalshi totals and spreads settled on different scores; "sure" 97-99c bots reportedly lost seven figures, C). Western Michigan-Michigan 2026-09-05 (paid, then clawed back). Eagles-Jaguars 2026-10-11: 97c+ with 8 s left, settled 1c (A) |
| 7 | Holding vs trading around volatility | Medium. Moskowitz 2021 (JF): momentum is real, reversed by the outcome, smaller than costs | Usually negative after fees | n/a | **Ours: fixed take-profit loses vs hold at every margin (hold -6.4%, 10 s cadence -12.2%); dip-buying loses more than random entry** |
| 8 | Bankroll and position sizing | Strong in theory (B: Baker-McHale 2013, shrunk Kelly beats Kelly out of sample) | Creates no edge. Controls ruin and drawdown | n/a | Fractional Kelly at 0.25 or less on SHRUNK probabilities. Per-market caps at the depth. **With no proven edge, the Kelly stake is 0** |
| 9 | Parlays / combos (as the buyer) | Strong (B: Moshrefi, 12,639 combos, about 3% per leg rich; retail lost $117M to Kalshi combo makers Jan-Apr 2026, B/C) | Buyer about -3% per leg | n/a | Never buy them. Selling needs MM status |

**Venue facts that changed since 044e2634** (primary sources in §6):
- **Kalshi Volume Incentive Program: terminated**, effective no earlier than 2026-10-13.
- **Kalshi LIP amended terms from 2026-10-28:** discount 0.5 per tick, Target Size 100-10,000, $10-$10,000 per day per market, to 2027-01-01. Retail is eligible.
- **Kalshi DLP program from 2026-10-30:** Market Maker Agreement holders only, chosen by bid. Not reachable for us.
- **Polymarket US taker rebates, paid weekly:** 3% of taker fees at $250k of prior-month taker volume, 5% at $1M. We are far below.
- **Polymarket US Liquidity Incentive Program** (early pregame, day-of pregame and live pools): listed "Open, no signup" but under "Institutional". **Retail API eligibility is UNVERIFIED.** That is a one-email question for the user.
- **Polymarket international's sports taker fee is 0.05·p(1-p), and makers get 15% of it.** That is not our venue; the US fee 0.0695 stands.
- **No documented Kalshi pause on scoring events.** Resting orders survive a pause unless `cancel_order_on_pause` is set.

## 2. Against what Syndicate has: test data and what is missing

**The fact that reorders everything: our live book IS a sharp-anchoring strategy already.**
- Live stakes use market mode: `model_probability = fair` (`portfolio_commit.py:800-806`, todo #704). The model's view is discarded and we buy wherever the venue price sits below the consensus fair by more than the fee.
- The fair is Pinnacle-first when Pinnacle is present (`SYNDICATE_FAIR_ANCHOR=sharp_only`, deploy 4, 2026-09-09; `layer2_board.py:1140-1160`), otherwise the Shin-devigged median.
- That book is the one losing -11.8% on Kalshi pregame [-20, -4]. So "trade toward Pinnacle" is not a new idea for us; it is the thing to FIX.
- **The literature says how it fails:**
  - a small edge over consensus is not profit (Whelan's 9th decile: +5% CLV, +0.2% profit);
  - the sharp quote must be fresh, and ours often is not. The book grid flips every sportsbook stale whenever one feed lands 15 minutes after the others: 23% of NFL sides on 10-16 (`findings_2026-10-16_one_book_staleness.md`). Props are fetched about hourly;
  - **Kalshi leads the books in play** (in_game_trading §1), and an exchange price that "disagrees" with a lagging book is usually right. Pregame lead-lag is unmeasured.

| Method | Data we have | Missing |
|---|---|---|
| 1 Market making | `kalshi-maker-shadow` (3 cells, outcome-graded); maker-orders-study (a resting bid in place of each live fill); Kalshi public trade prints with `taker_side`, for any market and back to the venue's history cutoff; the in-play recorder (Kalshi quotes every 10 s) | Order-book DEPTH and queue position (recorder and `venue_odds` keep top-of-book only, 48 points per ticker). Polymarket US public trade history does not exist. Any live maker fill on our own account |
| 1b Reward farming | The live LIP list (read today, §0) | A Kalshi LIP program on a market we trade (there are none). Polymarket US eligibility (ask the venue) |
| 2 Cross-venue arb | The board joins Kalshi and Polymarket US to sportsbooks on one identity; both venues captured every few minutes | Same-instant quotes: our venue polls are 2-5 min apart, too slow to see a gap that lasts seconds. A settlement-rule diff table per market type (postponement, OT, ties). Measured 0/12 already; low priority |
| 3 Sharp anchoring | OddsAPI us,eu (Pinnacle is in eu); the execution ledger with `fair_source` and price per order; `order_clv` (closing marks from the quote log); paper books, ladders, live-cell-scorecard | **The Pinnacle quote AGE at the decision instant is not recorded on the order.** The live `closing_mark.clv_pct` defect (about -35pt, venue_native_selection 10-20) does NOT show in today's ledger: profit-program read 70 live Kalshi same-book marks at 22:02Z 10-24, mean +0.28, and 15 carry `clv_correction` (a re-stamp ran). Spot-check rows against the quote log before relying on it. Pinnacle prop coverage is thin |
| 4 Latency / news | The ESPN injury collector and `news_price_follow.py` (27 h read: no stale-price edge); the in-play recorder with ESPN state | A sub-minute feed. Usage weighting for injury events. We cannot be fast at a 2-5 min cadence, by design |
| 5 Favourite-longshot | The 044e2634 price-band audit (11,713 paper orders); the live ledger by price bucket; **Kalshi's public settled-market and trade history, market-wide, for the series we trade** | Nothing. This is the cheapest test available |
| 5b Late-game | The in-play recorder: 5+ nights, about 70 NBA/NHL/NCAAF/NFL games, Kalshi every 10 s plus ESPN clock; `inplay_price_buckets.py` | More games (the cell needs about 60 per sport); Polymarket in play (we do not trade it) |
| 6 Resolution | Kalshi `rules_primary` / `rules_secondary` per market (public); the ledger's settled outcomes | A rule-diff catalogue. Capacity is too small to be worth building |
| 7 Hold vs trade | `inplay_exit_replay.py`; kalshi-exit-path's 10-26 exit-vs-hold reading (todo #703) | Nothing new needed |
| 8 Sizing | The stake path (compounding, the $5 floor, cap C) | A proven edge to size. Sizing is downstream of the scorecard's gate |
| 9 Parlays | KXMVE combos are already excluded from analysis | Nothing; we do not buy them |

## 3. The top 3 to test first

Chosen for: evidence strength × whether our data can resolve it in weeks × money at stake. All three are shadow or paper only, place no order, and send only unauthenticated GETs to public endpoints or read the fleet ledger. None changes live behaviour; each produces a recommendation for the user.

**Ownership, to avoid overlap:**
- maker-orders-study owns "should OUR picks be makers".
- kalshi-maker-shadow owns its 3 consensus-bid cells.
- profit-program owns the per-cell scorecard and its live-gate policy.
- in-play-program owns in-game entries and exits.

Test A is new. Test B is a new axis for the scorecard. Test C pre-registers a cell 044e2634 proposed but nobody built.

### Test A: market-wide structural edge on Kalshi sports (favourite-longshot × maker/taker), on public history

**Question.** In the exact series we trade (NFL, NCAAF, NBA, NHL, MLB, soccer; game, spread and total), under TODAY's fee regime, does any (price bucket × side × phase) cell earn a positive return net of fees, for takers or makers? Becker and Bürgi-Deng-Whelan answered this for Kalshi as a whole, pre-2025 and mostly non-sports. Nobody has answered it for our series under the 2025-07 maker fee. If no cell is positive even market-wide, no selection rule on top of it is likely to be.

**Data.**
- Kalshi public `/markets?series_ticker=…&status=settled` gives `result`.
- `/markets/trades` gives every print with `yes_price`, `count` and `taker_side`, plus `/historical/trades` before the cutoff.
- `/series/<s>` gives `fee_type` and `fee_multiplier`.
- Probed today: works without credentials, but rate-limited (HTTP 429 at about 1 request/s), so run it as a nice-19 batch.

**Method.**
- Each print yields one TAKER position (the taker's side, at the print price) and one MAKER position (the opposite side, same price).
- Per-contract return = `result - price - fee`:
  - taker fee `ceil4(0.07·mult·P(1-P))`;
  - maker fee `0.0175·mult·P(1-P)` on `quadratic_with_maker_fees` series, else 0.
- **Cells:** sport × family × price bucket (1-10, 10-25, 25-40, 40-55, 55-70, 70-85, 85-95, 95-99c) × side (taker/maker) × phase.
  - Phase: pregame, or in play by the market's `occurrence_datetime - 3h` rule.
  - In play is split further into final-period and other where ESPN times exist.
- **Weighting:** contract-weighted and dollar-weighted, both reported.
- **Statistics:** game-clustered bootstrap (event ticker = game), 2,000 draws, 95% CI.
- **Split:**
  - DISCOVER: games before 2026-09-01.
  - CONFIRM: 2026-09-01 onward.
  - Fixed before any return is computed.

**Sample.**
- Every settled game in those series since 2025-07-01, the maker-fee change.
- That is several thousand games and millions of prints. Becker's sports sample was 43.6M trades.
- A cell is read only at **≥ 300 games**. That resolves about ±1c per contract at the game level, given the per-game SD we saw in play.

**Decision rule.**
- **STRUCTURAL EDGE in a cell:**
  - CONFIRM mean net return has a CI lower bound > 0;
  - DISCOVER has the same sign;
  - **≥ 300 games in each half.**
- **Kill:** no cell passes. Then pregame structural edges in our series are closed. Our only remaining lever is a model that beats the close, and Test B is that question.
- **If a TAKER cell passes:** it becomes a candidate price band for the live gate (scorecard owner).
- **If only MAKER cells pass:** hand them to maker-orders-study / kalshi-maker-shadow as the prior for their cells. Do not build anything new.

**Cost and owner.**
- About one session-day for the script; the run is hours at about 1 request/s.
- No fleet change; it runs on any host.
- New lane, research only.

### Test B: does a FRESH, LARGE edge over Pinnacle predict profit? (sharp anchoring, done the way it works)

**Question.** Our live book buys any positive net edge over a consensus that is often stale. Whelan's CLV deciles and Kaunitz's α-threshold both say only large edges over a fresh sharp price pay. **Is our -11.8% concentrated in small-edge and stale-anchor bets, with a profitable top slice?**

**Step 1, retrospective (read-only, the ledger as it stands).**
- **Population:** every settled live and paper order since 10-01.
- For each, recompute **at the decision instant** from the quote log (the same machinery `order_clv` uses):
  - (a) the Pinnacle two-sided no-vig fair;
  - (b) Pinnacle's quote age;
  - (c) `edge_pinn = fair_pinn - price - fee`;
  - (d) the number of fresh books.
- **Bucket by:**
  - decile of `edge_pinn`;
  - Pinnacle age: ≤ 2 min, 2-15 min, > 15 min, absent;
  - anchor tier actually used (`fair_source`).
- **Read:** settled net ROI (game-clustered 95% CI) and CLV against the Pinnacle CLOSE per bucket.
- **The question this answers:** is the ROI gradient monotone in `edge_pinn`, and does the loss sit in the stale and absent rows?

**Step 2, forward paper cell (pre-registered on step 1's DISCOVER half only).**
- **Rule:**
  - Pinnacle quoted both sides ≤ 120 s before the decision;
  - `edge_pinn ≥ fee + H`, where H is fixed from step 1. Default H = 3c if step 1 is flat;
  - the venue's top-of-book size ≥ the stake;
  - not in-play;
  - price 25-85c (Test A may tighten this).
- **Paper-alongside-live stamps:** it changes no live order.
- It needs one addition: the Pinnacle age and fair recorded on each paper row. That is a paper-book code change, owner paper-books / profit-program.

**Metric.** Net ROI on settlement (the primary metric); CLV against the Pinnacle close (secondary). CLV is secondary because CLV alone has misled us before (the 10-19 maker study).

**Sample and gate.** The scorecard's option-A bar: ≥ 150 bets, ≥ 40 games, ≥ 14 days, game-clustered 95% CI lower bound on net ROI > 0, and CLV > 0. So the scorecard can grade it with no new gate logic.

**Kill.**
- Step 1: ROI is not increasing in `edge_pinn` (the top-decile CI upper bound ≤ the pooled point estimate), and fresh-anchor rows lose as much as stale ones. Then sharp anchoring is not our fix; stop.
- Step 2: at 150 bets the ROI CI upper bound < 0.

**Fixes that step 1 also measures:**
- live same-book `clv_pct` looks usable after the re-stamp (profit-program, 10-24; see §2). If the decile split leans on CLV, recompute it from the quote log anyway;
- the baseline the top decile has to beat: live Kalshi pregame since 10-20 is -17.6% per bet [-29, -7], 129 bets (profit-program). A forward cell graduates through the per-cell live gate (4584fbe9);
- the per-feed staleness rule (one_book_staleness, fix option 1).

### Test C: late-game structural cells in play (pre-registration of 044e2634 §4(b), extended)

**Question.** Is the most-replicated in-play anomaly tradable on Kalshi after the fee?
- Final-period longshots are overpriced; Moshrefi measured NHL's final-5-minute slope at 4.56.
- Late favourites are slightly underpriced.

**Data.** The nightly in-play recorder (`C:/tmp/inplay_<date>/`): Kalshi quotes every 10 s and the ESPN period and clock, every game night to 2026-12-31. No new collection is needed.

**Cells (fixed now):**
- **C1, avoid/sell:** sell (or never hold) any leg priced under 25c with ≤ 10 game-minutes left (NHL: 3rd period ≤ 10:00; NBA: 4th ≤ 6:00; NFL/NCAAF: 4th ≤ 8:00).
  - P&L = bid minus fee, against hold to settlement, per position held in our recorded books;
  - and, as a population check, per-contract `result - ask - fee` on under-25c asks.
- **C2, buy:** take the favourite at the ask, priced 85-97c, in the same window, once per market per game, held to settlement. Return = `result - ask - fee`.
- Both cells are graded **per game** (one mean per game), because entries inside a game are correlated.

**Sample.** ≥ 60 games per sport-cell, plus a game-clustered 95% CI.

**GO and kill.**
- **GO** = CI lower bound > 0 at ≥ 60 games, AND positive in at least 2 of the 3 sports with ≥ 20 games.
- **Kill:**
  - CI upper bound < 0 at 60 games;
  - or for C2, any single loss larger than 10× the cell's mean gain inside the first 60 games (the Eagles-Jaguars tail). That is reported, not decided on.
- **Calendar stop:** 2026-12-31, when the recorder task ends.

**Why it is third, not first.** The cell is small: a few positions a night, a few cents each. The tail risk is real (late score corrections, settlement clawbacks). And in-play execution at our 2-5 min fleet cadence is not the recorder's 10 s. A GO here means about $1-$5 a night, not passive income. **C1 is worth more as an EXIT rule on what we already hold than as an entry.**

**Owner.** The in-play program; its scoreboard already computes per-game markouts. This is a pre-registration plus about 50 lines in `inplay_price_buckets.py`.

### Ranked out, and why

- **Liquidity-reward farming:** 0 programs on any market we trade (measured today). Revisit if Kalshi lists game, spread or total markets, or if Polymarket US confirms retail eligibility.
- **Cross-venue arbitrage:** 0/12 positive already, gaps last seconds, and we poll in minutes.
- **Latency:** we are structurally the slow side.
- **Resolution edge cases:** small capacity, documented fat tails.
- **Hold-vs-trade:** already measured (take-profit loses vs hold).
- **Sizing:** downstream of a proven edge.

## 4. Decisions owed to the user

1. **Build Test A?** It is a new research lane: one script and public data. It is the cheapest way to learn whether ANY structural edge exists in our markets under today's fees.
2. **Build Test B?** Step 1 is read-only on the fleet ledger. Step 2 adds two fields to paper rows: a paper-book code change, no live effect.
3. **Pre-register Test C on the in-play scoreboard?** In-play program owner.
4. **Optional, one email:** ask Polymarket US whether a retail API account is eligible for its Liquidity Incentive Program. If yes, its LIVE and pre-game pools are the only reward mechanism we could reach.

What none of these does: make money now. The evidence is consistent that our current book's loss is selection. Until a test passes, the scorecard's option A (live entries paper-only until a cell earns it back) is what this research supports.

## 5. Not measured here / open

- **Pregame lead-lag between Kalshi and Pinnacle:** no study exists, and we have not measured it. Test B step 1 partly covers it.
- **The unit of Kalshi `period_reward`:** the median is 1,000,000 per 168-hour program, and the API does not document the unit. It does not matter for us (0 programs on our markets).
- **Polymarket wallet studies count wallets, not people.** The leaderboard shows survivors only.
- **Practitioner method claims** (swisstony "sportsbook as oracle", broadcast lag) are unverified (D).

## 6. Sources

**Venue primary documents**
- Kalshi LIP terms, filing 2026-10-14, effective ≥ 2026-10-28: https://www.cftc.gov/filings/orgrules/rules10142633813.pdf
- Kalshi LIP help page: https://help.kalshi.com/en/articles/13823851
- Kalshi Volume Incentive termination, filed 2026-09-28: https://www.cftc.gov/filings/orgrules/rules09282630083.pdf
- Kalshi DLP program, filed 2026-10-19: https://www.cftc.gov/filings/orgrules/rules10182634499.pdf
- Kalshi Market Maker program: https://help.kalshi.com/markets/market-maker-program
- Kalshi incentives API: https://docs.kalshi.com/api-reference/incentive-programs/get-incentives.md
- Kalshi rate limits: https://docs.kalshi.com/getting_started/rate_limits
- Kalshi order types: https://docs.kalshi.com/api-reference/orders/create-order-v2.md
- Kalshi pauses: https://docs.kalshi.com/getting_started/maintenance_and_pauses.md
- Kalshi MLB settlement terms, filed 2026-08-04: https://www.cftc.gov/filings/orgrules/rules08042613673.pdf
- Polymarket international fees: https://docs.polymarket.com/trading/fees.md
- Polymarket maker rebates: https://docs.polymarket.com/programs/maker-rebates.md
- Polymarket liquidity rewards: https://docs.polymarket.com/market-makers/liquidity-rewards
- Polymarket holding rewards: https://docs.polymarket.com/polymarket-learn/trading/holding-rewards
- Polymarket order lifecycle (sports delay): https://docs.polymarket.com/concepts/order-lifecycle
- Polymarket US fees and rebate tiers: https://docs.polymarket.us/fees.md
- Polymarket US incentives: https://docs.polymarket.us/incentives/overview.md
- Polymarket US liquidity incentives: https://docs.polymarket.us/incentives/liquidity.md
- Polymarket US volume incentives: https://docs.polymarket.us/incentives/volume.md
- Polymarket US market maker program, filed 2026-09-30: https://www.cftc.gov/filings/orgrules/rules09302630736.pdf
- Polymarket US rate limits: https://docs.polymarket.us/trader-guide/rate-limits.md
- Polymarket US sports FAQ: https://docs.polymarket.us/faqs/sports-faqs.md

**Academic and working papers**
- Bürgi, Deng & Whelan, "Makers and Takers" (Kalshi): https://www.karlwhelan.com/Papers/Kalshi.pdf
- Whelan, "Agreeing to Disagree" (Betfair, 200k matches): https://www.karlwhelan.com/Papers/Betfair.pdf, also https://mpra.ub.uni-muenchen.de/126351
- Whelan, "The Truth about Closing Line Value" (2026-08-12): https://finemarginskarlwhelan.substack.com/p/the-truth-about-closing-line-value
- Whelan, "Prediction markets vs sportsbooks": https://finemarginskarlwhelan.substack.com/p/prediction-markets-vs-sportsbooks
- Becker, "Microstructure of Wealth Transfer" (72.1M Kalshi trades): https://jbecker.dev/research/prediction-market-microstructure
- Moshrefi 2026, late-game calibration on 23M Kalshi trades: https://arxiv.org/html/2607.14430
- Le 2026, 353M trades on Kalshi and Polymarket: https://arxiv.org/abs/2602.19520
- Saguillo et al. 2025, Polymarket arbitrage $39.6M: https://arxiv.org/html/2508.03474
- Polymarket NBA in-game arbitrage (173 games): https://econpapers.repec.org/paper/arxpapers/2605.00864.htm
- Akey, Grégoire, Harvie & Martineau, CEPR DP21615: https://econpapers.repec.org/RePEc:cpr:ceprdp:21615
- Ng, Peng, Tao & Zhou, Kalshi vs Polymarket lead-lag: https://papers.ssrn.com/abstract=5331995
- Kaunitz, Zhong & Kreiner 2017, consensus-deviation betting: https://arxiv.org/pdf/1710.02824
- Clegg, Song & Cartlidge 2026: https://arxiv.org/abs/2605.16066
- Page 2012, *Applied Economics* 44(1): https://ideas.repec.org/a/taf/applec/44y2012i1p81-92.html
- Brown 2012, *Applied Economics* 44(9): https://ueaeprints.uea.ac.uk/id/eprint/45783/1/00036846_2010.pdf
- Baker & McHale 2013, *Decision Analysis*: https://ideas.repec.org/a/inm/ordeca/v10y2013i3p189-199.html
- Moskowitz 2021, *Journal of Finance* 76 (summary): https://alphaarchitect.com/value-momentum-sports-betting/
- Croxson & Reade 2014, *Economic Journal* 124, DOI 10.1111/ecoj.12033

**On-chain, leaderboards, press**
- Polymarket sports leaderboard (read 2026-10-24): https://polymarket.com/leaderboard/sports/all/profit
- Wallet profiles: https://polymarket.com/@swisstony, https://polymarket.com/@kch123
- Galaxy Research 2026-10-01 (press): https://cryptobriefing.com/galaxy-research-polymarket-retail-losses/, https://www.playusa.com/news/report-finds-most-polymarket-retail-traders-lost-money-in-2-9m-account-analysis/
- Bloomberg wallet analysis (press): https://www.financemagnates.com/fintech/100000-polymarket-wallets-lost-at-least-1000-bloomberg-analysis-shows/
- The Defiant, wallet profitability April 2026: https://thedefiant.io/news/research-and-opinion/polymarket-profitability-report-april-2026
- Kalshi combos, retail losses: https://prospect.org/2026/08/26/house-always-wins-kalshi-prediction-markets/
- Ex-Kalshi Trading on combos: https://ufoholdings.substack.com/p/the-fish-are-the-product
- Ex-Kalshi Trading on Kalshi's liquidity incentives: https://ufoholdings.substack.com/p/kalshis-new-liquidity-incentives
- poly-maker README: https://github.com/warproxxx/poly-maker
- Kalshi in-house desk "not profitable": https://www.ingame.com/kalshi-in-house-trading-arm-not-profitable/
- Eagles-Jaguars 2026-10-11 loss: https://news.bitcoin.com/polymarket-whale-loses-147k-eagles-bet-after-a-last-second-57-yard-kick/
- Giants-Angels settlement split (single secondary source): https://pmpulse.substack.com/p/the-pm-pulse-009
- Western Michigan-Michigan clawback: https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/western-michigan-michigan-outcome-created-chaos-for-kalshi
- Polymarket UMA governance attack: https://www.theblock.co/post/348171/polymarket-says-governance-attack-by-uma-whale-to-hijack-a-bets-resolution-is-unprecedented
- French whale (politics): https://www.theblock.co/post/324996/french-polymarket-whale-us-election-profit-france-ban
- Kalshi trader interview (Kalshi promotional): https://news.kalshi.com/p/interview-kalshi-trader-iabvek-new-york-mayor-race
- Esports latency bot: https://www.esports.net/news/polymarket-bot-makes-over-200k-in-3-months-with-lol-dota-2-esports/
- Whale copy-trading backtest (vendor): https://orcalayer.com/blog/polymarket-copy-trading-whales-backtest
- Book margins vs Kalshi/Polymarket (vendor snapshot): https://oddspapi.io/blog/polymarket-api-kalshi-api-vs-sportsbooks-the-developers-guide/

**Internal**
- `findings_2026-10-23_prediction_market_strategy_research.md`
- `findings_2026-10-24_live_cell_scorecard.md`
- `findings_2026-10-24_maker_vs_taker_shadow.md`
- `findings_2026-10-19_kalshi_maker_entry_paper.md`
- `findings_2026-10-20_kalshi_maker_shadow_preregistration.md`
- `findings_2026-10-20_in_game_trading.md`
- `findings_2026-10-16_one_book_staleness.md`
- `findings_2026-10-14_news_price_follow.md`
- `findings_2026-10-20_venue_native_selection.md`
- `findings_2026-10-23_polymarket_fee_model.md`
- state `[venue-fee-economics]`, `[kalshi-in-play-efficiency]`, `[kalshi-maker-shadow]`
