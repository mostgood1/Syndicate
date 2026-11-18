# Findings — lane `trader-following-study` (2026-11-17/18, session 69d80317)

Asked by the user: "https://oddsjam.com/prediction/traders, figure out how to integrate this into our app", then "we
may need to build our own version of this", then "start the study". The scope is in
`scope_2026-11-17_trader_following.md`.

This is a read-only, paper-only backtest on Polymarket's public data (Data API v2, gamma). No fleet data, code path,
env or deploy was touched. The hypothesis and falsification test were written to the lane (`934d27b82`) before any
trade was pulled.

## Method (`scripts/trader_follow_study.py`, run on `cc71822e1`)

- **Universe.** The Polymarket v2 leaderboard, sports category: PNL and VOLUME, month and all-time, top 300 of each,
  de-duplicated.
- **Bets.** Each wallet's BUY trades on our sports' slugs (NFL, NBA, WNBA, NHL, MLB, NCAAF, NCAAB, soccer leagues).
  Repeat buys of one outcome fold into one bet at the size-weighted price.
- **Settlement.** From the resolved market's `outcomePrices`. Voided and 50/50 markets are dropped.
- **In-sample** 2026-08-01..10-16, **out-of-sample** 10-17..11-16 (UTC).
- **Selection, as pre-registered:**
  - at least 100 resolved in-sample bets;
  - in-sample ROI with an event-clustered 95% lower bound above 0;
  - never bought both outcomes of one market;
  - not page-capped (high-frequency).
- **Follow.** The follow price is the first taker BUY of the same outcome on the market's own tape at least 0 / 60 /
  300 s after the wallet's fill (within 30 min). Return is per dollar at that price. The 95% bound is clustered on
  events.
- **Baseline.** A seeded random 3,000 of all out-of-sample bets, every wallet in the universe.

## Population (one full run, 2026-11-18 ~03:15Z; 5,979 API calls)

| step | count |
|---|---|
| universe wallets | 859 |
| capped (high-frequency), excluded | 88 |
| two-sided wallets, excluded | 290 |
| sports bets | 202,871 |
| resolved markets | 58,285 |
| resolved in-sample / out-of-sample bets | 71,732 / 130,598 |
| **selected wallets** | **3** |
| tapes read / not reaching the bet | 2,912 / 0 |

## Pre-registered result (60 s is the registered cell)

| group | delay | bets | events | ROI | lower 95% |
|---|---|---|---|---|---|
| selected | own price | 289 | 206 | +0.29% | -0.60% |
| selected | 0 s | 289 | 206 | +0.33% | -0.57% |
| **selected** | **60 s** | **69** | **62** | **+2.52%** | **+0.62%** |
| selected | 300 s | 55 | 51 | +2.52% | +0.55% |
| baseline | own price | 130,598 | 3,310 | +1.46% | -2.35% |
| baseline | 60 s | 2,188 | 882 | +0.18% | -5.38% |
| baseline | 300 s | 1,963 | 817 | -3.01% | -7.87% |

Unfollowable at 60 s / 300 s: selected 220 / 234 of 289, baseline 812 / 1,037 of 3,000.

**The registered falsification test is NOT met.** At 60 s the selected lower bound is +0.62% > 0 and the ROI is above
the baseline's +0.18%. By the letter, that is a "go" for a paper shadow.

## Why the "go" is not trader skill (exploratory, NOT pre-registered; `C:\tmp\pfmon\trader_study\subset_check.py`, cache only, 0 new calls)

A copier beating the trader (+2.52% at 60 s vs +0.29% at their own price) is the wrong sign for a follow edge, so the
cell was taken apart:

- **The 3 wallets buy outcomes that are already decided.** Entry price p10 / p50 / p90 is 0.995 / 0.999 / 0.999
  in-sample and 0.988 / 0.999 / 0.999 out-of-sample. **613 of 624** in-sample and **282 of 289** out-of-sample buys
  came after the game's start time. Win rate: 99.5% on the unfollowable bets (220), 100% on the followable ones (69).
- **The 60 s cell is a subset, not a follow effect.**
  - The same 69 bets earned +2.13% at the wallets' own price (lower 95% -0.24%).
  - The 220 bets nobody re-bought within 30 min earned -0.28%.
  - The price moved own -> follow by a median of 0.000 (mean -0.005).
  - The cell holds no losing bet. At a ~0.99 price, one loss costs ~100% of that bet against ~1% per win, so a
    clustered bound over a sample with no loss events does not measure the tail.
- **Baseline split, same shape:** followable +0.70% at own price, against -11.80% on the unfollowable remainder.
  Whether anyone re-buys an outcome later is itself correlated with how it turns out. The registered follow price
  conditions on a later trade existing, which is a look-ahead the design did not see.

## Verdict

- **Registered:** NOT falsified (60 s lower 95% +0.62% > 0, above baseline). The study ran as designed.
- **Recommendation: NO-GO on following traders.**
  - The rule selected late-game "certainty buyers": entries at 0.99+ after kickoff, a high-win-rate carry trade with
    tail risk. It found no wallet with a pregame sports read we could follow.
  - Out-of-sample at their own price that strategy is flat: +0.29%, lower 95% -0.60%.
  - It needs no one to follow, and it is outside this system's model edge.
  - Of 859 leaderboard wallets, none other passed the in-sample rule.
- **What the rule missed, for any rerun** (a new pre-registration, not a re-cut of this one):
  - a price band (for example 0.10-0.90);
  - pregame-only buys (before gameStartTime);
  - a follow price taken from the book at t+delay (CLOB `prices-history`), not from the next taker trade.

## Coverage this rests on

- Out-of-sample: 31 days (10-17..11-16), 206 events for the selected group and 3,310 for the baseline.
- In-sample: 77 days (08-01..10-16).
- Bets are skewed to recent months: in a 20-wallet check, 73% of bets were in November and ~925 in Aug-Sep. The
  in-sample window is thin for wallets that started with the fall seasons.
