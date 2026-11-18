# Findings — lane `trader-following-pregame-study` (2026-11-18, session e9b4d640)

The user asked "Pre-register and run a pregame-only version of the study?" and answered "Yes, run it". This is the
rerun of lane `trader-following-study` (`findings_2026-11-18_trader_following_study.md`). That study's registered test
passed, but the 3 selected wallets were late-game certainty buyers, and its follow price had a look-ahead.

This run is paper-only and read-only: Polymarket's public Data API, gamma and CLOB, cached at
`C:\tmp\pfmon\trader_study\cache`. Nothing on the fleet was touched.

- **Pre-registration:** hypothesis, falsification and follow-price rule in `lanes.md`, commit `788e08fa2` (committed 7:50 AM CST),
  before any outcome or price data for this design was pulled.
- **Code:** `scripts/trader_follow_pregame.py` + 9 tests, commit `cc7a965f0`. The run used that commit. Output:
  `C:\tmp\pfmon\trader_study\pregame\summary.json` and `run.log`.

## Source check, done before registering

CLOB `prices-history?market=<token>&fidelity=1` returns about one point a minute. Its `p` is the **book midpoint**.
On `mls-sea-aus-2026-08-19-total-2pt5`, just before kickoff, `p` = 0.625 while the trade tape showed BUYs of Over at
0.63 and Under at 0.38: bid 0.62, ask 0.63, mid 0.625. So "price the copy from the book" was feasible, and the
next-trade fallback was not needed.

## Design (as registered)

- **Same as the first study:**
  - universe: Polymarket sports leaderboard, PNL and VOLUME boards, month and all-time, top 300 each, de-duplicated;
  - windows: in-sample 2026-08-01..10-16, out-of-sample 10-17..11-16 UTC;
  - exclusions: wallets that bought both outcomes of a market, judged on all sports buys; page-capped
    (high-frequency) wallets;
  - selection: at least 100 resolved in-sample bets, own-price ROI event-clustered lower 95% bound > 0;
  - delays 0 / 60 / 300 s.
- **New:**
  - A qualifying BUY has entry price 0.10-0.90 and comes **before** the market's `gameStartTime`. A bet folds a
    wallet's qualifying buys of one market outcome.
  - The copy price is the midpoint at or before t+delay (at most 300 s old) **+ 1 cent** taker cost. It is
    unfollowable if t+delay is at or after kickoff, and nothing after t+delay is read. A test proves later points
    change nothing.
  - Baseline: a seeded random 3,000 of all out-of-sample qualifying bets, priced with the same rule.
- **Verdict rule:**
  - NO-GO if 0 wallets are selected;
  - NO-GO if the selected 60 s lower 95% bound is <= 0, or the selected 60 s ROI is not above the baseline's;
  - otherwise GO for a paper shadow only.

## Population (one full run, finished 2026-11-18 8:12 AM CST; 2,995 new API calls, the rest cached)

| step | count |
|---|---|
| universe wallets | 859 |
| page-capped (high-frequency), excluded | 88 |
| two-sided wallets, excluded | 290 |
| in-band sports BUYs (0.10-0.90) | 459,672 |
| resolved markets / with a start time | 58,285 / 58,274 |
| pregame bets (qualifying buys folded) | 65,049 |
| resolved in-sample / out-of-sample bets | 22,887 / 42,107 |
| wallets with >= 100 resolved in-sample bets | 53 |
| **selected wallets** | **0** |
| baseline bets priced (CLOB histories) | 3,000 |

## Registered result: **NO-GO (0 wallets selected)**

No wallet among Polymarket's 859 leaderboard sports traders met the pre-registered rule for a copyable pregame edge.

**Baseline, for context** (not a verdict input once nobody is selected). These are random leaderboard wallets'
pregame bets, out-of-sample:

| copy | bets | events | ROI | lower 95% |
|---|---|---|---|---|
| at their own price (all 42,107) | 42,107 | 2,492 | +1.09% | -0.55% |
| own price, the 3,000 sample | 3,000 | 1,123 | +1.36% | -2.68% |
| book mid + 1c, 0 s | 2,990 | 1,122 | +1.17% | -2.87% |
| book mid + 1c, 60 s | 2,944 | 1,110 | -0.24% | -4.24% |
| book mid + 1c, 300 s | 2,835 | 1,079 | -0.95% | -5.03% |

- **Followable coverage:** 99.7% / 98.1% / 94.5% at 0 / 60 / 300 s. The misses are mostly copies that would land
  after kickoff.
- **Delay cost (exploratory):** on the bets followable at 60 s, the wallets' own price earned +0.86%; the 60 s copy
  earned -0.24%. Waiting a minute plus the 1-cent cost took about 1.1 points. The subset is 98% of the sample, so no
  selection artifact like the first study's.
- **Baseline entries:** price p10 / p50 / p90 0.33 / 0.50 / 0.67; placed 12 / 292 / 1,243 min before kickoff.

## How close anyone came (exploratory, NOT pre-registered; cache only, 0 new calls)

Of the 53 wallets with at least 100 in-sample pregame bets:
- **11 page-capped and 45 two-sided** (overlapping). **8 eligible** for selection.
- **Only 2 of the 53 had an in-sample lower bound above 0, and both are two-sided.**
  - One is also capped: +27.4% on 127 bets, out-of-sample +4.5% on 458.
  - The other: +6.3% on 1,234 bets, out-of-sample +3.4% on 647.
  - Buying both outcomes is market making or hedging. A follower who sees only the buys cannot copy it, which is why
    the rule excludes it.
- The 8 eligible wallets' in-sample ROI ran p10 / p50 / p90 -9.7% / +4.1% / +16.7%. None was significant.

## Verdict and recommendation

- **Registered: NO-GO.** No selectable wallet, so there is nothing to shadow.
- **In plain words:** nobody on Polymarket's sports leaderboard showed a pregame edge we could copy. Copying the
  leaderboard at large is flat at best, and a minute of delay plus a 1-cent spread turns it slightly negative,
  which is the decay OddsJam's own chart shows. **Do not build trader-following.**
- With the first study (late-game certainty buyers, flat at their own price), both versions of the idea are now NO-GO
  on public Polymarket data.

## Coverage this rests on

- In-sample: 77 days (08-01..10-16), 22,887 resolved bets. Out-of-sample: 31 days (10-17..11-16), 42,107 resolved
  bets, 2,492 events.
- Volume is skewed to the fall seasons (most of the 20-wallet check in the first study was November). The in-sample
  window is thinner for wallets that started with them, and a longer history could select wallets this one could
  not. That would be a new pre-registration, not a re-cut.
- Gross of venue fees. The 1-cent cost stands in for half the spread and is generous for liquid markets.
