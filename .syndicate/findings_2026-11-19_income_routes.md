# Income routes beyond selection: venue liquidity rewards (2026-11-19, lane portfolio-monitor)

The user asked to "get creative ... there MUST be ways for us to leverage all this work into something that can
generate income". This file records what was measured. Every figure is read-only and comes from public venue data
read 11-19, 17:30-19:10Z. No order was placed. Scripts and raw pulls are in `C:\tmp\pfmon\income\`.

## Why look outside selection

S1-S7 (`plan_2026-11-18_profit_learning_program.md`) found no challenger to the live book's selection. That book is
-7.15% over 30 d. Fees are 3.87% of stake, and the ROI before fees is -3.28%. The live stake is about $49 a day.

Two things follow:
- Even a proven +2% edge would earn about $1 a day.
- The measured losses are paying the taker fee and being picked off on a stale quote.

Both venues pay makers to rest orders, whether or not the orders fill. That reward does not depend on predicting
better than the market.

## 1. Kalshi Liquidity Incentive Program (LIP) — the lead

**Terms** (help.kalshi.com 13823851, read by a web agent 11-19):
- **Eligibility:** "Most regular U.S. Kalshi members". There is no application and no exclusion for API use.
- **Scoring:**
  - A snapshot is taken once a second, at a random moment within it.
  - The reference price on each side is the first level from the best where cumulative size reaches 1/5 of the
    target size.
  - Orders at or better than the reference score 1.0x. Worse orders score DF^ticks.
  - The yes and no sides are scored separately, each normalised to 1.
  - A snapshot pays nothing unless BOTH sides reach the target size.
- **Payment:** in **credits**, daily from about 6 AM ET, with a $1 minimum per market program.
- **End date:** January 1, 2027. "Kalshi can end or modify the program at any time".
- **Unverified:** whether the credits can be withdrawn as cash.

**Size:**
- `GET /incentive_programs`: 7,260 active liquidity programs.
- `period_reward` is in centi-cents (per the API doc), which makes **$647k in the current periods and $137,998 a
  day**.
- The median market pays $14.3 a day, the 90th percentile $29.3, the maximum $169.

**Where the money is:**
- 0 programs are on any sports game, spread or total. That is unchanged since the 10-24 read
  (`state_kalshi.md [kalshi-structural-price-map]`).
- By $/day the top series are: KXRT (Rotten Tomatoes, $14.5k), KXGBPUSD/USDJPY/USDMXN events ($13.3k together),
  KXDPRESPRIMARY ($4.4k), KXGAMEAWARDS ($3.6k), KXYTVIEWSW, KXGRAMMY, KXNVDACEO, KXART, KXFEATURE and AAA gas.

**Fees:**
- `GET /series/<s>` reports fee_type `quadratic` (taker-only) for KXRT, KXPANAMAWEEKLY, KXAPRPOTUS, KXYTVIEWSW,
  KXTRUMPPHOTO, KXGBPUSDEVENT and KXANTHSHARE. Resting orders there trade free.
- `quadratic_with_maker_fees` applies to KXAAAGASM and all sports game series.

**Capture ceiling** (`kalshi_lip_scan.py` + `kalshi_lip_size.py`, all 7,252 order books read 18:37-19:05Z):
- Method:
  - Add S contracts at the reference price on each side (full credit, resting behind the touch).
  - Share per side = S / (others' score + S). Each side is half the pool.
  - Pay only where both sides reach the target size.
  - Capital = S x (yes_ref + no_ref).
  - Greedy fill by $/day per $ of capital.
- This is an UPPER BOUND: the book is held still, competitors do not respond, and there are no fills and no adverse
  selection.

| capital | S=50 / side | S=100 / side | S=250 / side |
|---|---|---|---|
| $1,000 | $172/day (37 mkts) | $192/day (20) | $177/day (12) |
| $2,500 | $292/day (77) | $346/day (39) | $356/day (18) |
| $5,000 | $426/day (144) | $523/day (70) | $571/day (38) |
| $10,000 | $617/day (270) | $776/day (146) | $898/day (62) |

- Crowded books earn nothing: currency events and primaries hold 40k-500k contracts at the best price.
- The capture sits in thin books: KXRT strikes, KXGAMEAWARDS, KXTRUTHSOCIAL, KXART, KXANTHSHARE, KXTRUMPPHOTO,
  KXUSMEXTARIFFUP, KXTRUMPNOMNUM, KXEOWEEK, KXZAIVREQ, KXFDANOM, the weekly Hormuz/Suez/Panama markets, and others.

**Fill pressure** (`kalshi_lip_fills.py`, the 70 best markets by $/day per $ of capital at S=100):
- Method: public taker volume in the last 7 days that traded at or through our reference price on each side.
- **36 of 70 traded < 100 contracts/day through our level on BOTH sides.** Their ceiling is **$207/day on $2,092 of
  capital.** Fills there would be rare, so the reward would dominate the P&L.
- The other 34 are busy. KXRT-HUN-60/70 traded about 15k/day through our level on one side, and KXRT-IPL-87 and the
  KXTRUTHSOCIAL brackets traded 1-3k/day. That flow is the informed kind (reviews landing, post counts), so those are
  the markets where getting picked off decides the outcome.

**What is NOT known (and decides the real number):**
- How fast the book and competitors move. The ceiling comes from one snapshot.
- The markout on our fills.
- Whether credits convert to cash.
- Whether the program is extended past 01-01.
- Most rewarded markets close within days and new ones list, so a quoter must roll its market set daily.

## 2. Polymarket US Liquidity Incentive Program — second

**Terms** (docs.polymarket.us/incentives/liquidity.md and overview.md):
- "Open ... No signup or application needed". This settles the 10-24 question about retail eligibility
  (`findings_2026-10-24_pm_trader_strategies.md` §1, item 4).
- Scoring:
  - Score = DF^ticks x size, counted from the best price, within the walk to the target size.
  - A snapshot every second, with each side normalised.
  - An optional max spread.
- Makers pay no fee on Polymarket US. Maker rebates start only at $10M a month.

**Size:**
- `GET api.prod.polymarketexchange.com/v1/incentives`, public: 52,672 markets in 219 programs.
- **A pool is shared across a program's markets and is never summed per market** (polymarket.us/rewards). Counted
  once per program, the active pools total $54,274:
  - NFL live: $18,945. Its spreads program is $6,300 across 1,189 markets.
  - UFC live: $5,525.
  - College football live: $4,577.
  - Crypto daily: $2,881.
  - NBA live: $2,830.
  - Soccer leagues live: about $8.9k.
  - NHL live: $592.
- Pregame (early/day-of) pools run $20-$625 per program.

**Why second:**
- The money is on LIVE play, where pick-off risk is worst (S2/S4/maker shadow: in-play fills are adversely selected).
- A per-market pool of about $5 per game is split among every quoter.
- Testable offline later on the in-play recorder (27+ nights of Kalshi at 10 s). Not started.

## 3. Routes checked and ranked low

- **Analytics tools for prediction-market traders:**
  - TrustMRR self-reports: Alphascope $498 MRR / 40 subscriptions, Propheseer $64 / 30 d; PolyPick is being sold.
  - Kairos raised $2.5M (a16z, 02-2026).
  - Real but small, and it needs distribution we do not have.
- **Referrals:**
  - Kalshi: about $25 in credit per referral, about 40 referrals at most, about $1k total.
  - Polymarket US: needs approval and pays a published schedule.
  - Both need an audience.
- **Selling picks or projections:** consumer tiers run about $10-40 a month. Our selections lose beyond noise, so
  selling them would sell a losing product.
- **Polymarket international** ($5M/month in sports rewards, plus the builder program): not available to US
  persons. Out of scope.

## Proposed next step (not started; needs the user's go)

**S8, read-only shadow:**
- Every 60 s for 3-5 days, record the order books of the top ~150 Kalshi LIP markets by $/day per $ of capital.
- Score a hypothetical S at the reference price under the help-page rule, snapshot by snapshot.
- Count the public trades that would have filled it, and mark each fill to the market 1 h / 24 h later and to
  settlement.
- Decision rule, to be pre-registered before any data is read: reward - markout > 0, with an event-clustered lower
  bound > 0.

**A live pilot only after that:**
- capped (for example $500 of capital, about 10 quiet markets);
- in a betting-change window (next 11-24) and with the user's explicit yes, because it places live orders;
- it would reuse `kalshi_orders` (post-only, GTC, cancel), the execution ledger and reconcile.
