# S8 — Kalshi liquidity-reward shadow (lane `s8-lip-shadow`, opened 2026-11-20)

**User decision 2026-11-20 ~8:05 AM CST:** "go ahead with S8".

**Study.** S8 of the profit learning program (`plan_2026-11-18_profit_learning_program.md`). It is read-only: only
public GETs to `api.elections.kalshi.com`, with no orders, no account and no fleet change. It is not a betting
change.

**Why.** `findings_2026-11-19_income_routes.md` found that Kalshi pays about $138k a day for resting orders on 7,260
non-sports markets. From one snapshot, the capture ceiling is about $346 a day on $2,500, and about $207 a day on
$2,092 in 36 quiet markets. That ceiling ignores three things this study measures over time:
1. how the book moves;
2. fills;
3. what fills cost.

## PRE-REGISTRATION

Written and pushed before the collector started. No collected data is read before the first look below.

### Universe (chosen without look-ahead)

- **When:** at collector start, then daily at about 06:00 CST.
- **Inputs:**
  - every active Kalshi `liquidity` incentive program (`GET /incentive_programs`, start ≤ now < end, at least 6 h
    left);
  - each program's order book read at that moment.
- **Selection:** score each market with the static rule below at **S = 100 contracts per side**, then fill greedily
  by static $/day per $ of resting capital until **$2,500** of resting capital (S × (yes_ref + no_ref)) is used.
  Those markets are the day's book.
- **Recorded per market:** the program's `period_reward` (centi-cents, per the API doc), start and end, target size,
  discount factor, event and series ticker, and the series `fee_type`.

### The hypothetical quote

- **Where it rests:** S = 100 on each side, at that side's **reference price**. This is the help-page rule
  (help.kalshi.com 13823851): walking from the best price, the reference is the first level where cumulative
  resting size reaches **1/5 of the target size**.
- **Its score:** our order rests at the reference, so it scores 1.0x. Other orders at or better than the reference
  score 1.0x; orders worse than it score DF^ticks (1 tick = $0.01).
- **Repricing:** at each snapshot the quote moves to the current reference. Kalshi scores the live book, so a quoter
  that tracks the reference is the strategy measured.

### Reward accrual (approximates the help-page formula)

The help page's terms:
- one snapshot a second;
- each side normalised to 1;
- a snapshot is excluded unless **both** sides reach the target size;
- reward = period reward × Σ(our snapshot score / 2) / all snapshots.

**Our approximation:**
- Per observed snapshot t, on each side where our order is resting:
  - share = 100 / (others' score + 100);
  - the target test counts our 100.
- The snapshot earns `usd_per_day × w_t / 86400 × 0.5 × (share_yes + share_no)`. It earns 0 if either side misses
  the target size.
- `w_t` is the seconds since the previous snapshot of that market, capped at 120 s. A longer gap counts as
  unobserved and earns 0, which is conservative.
- `usd_per_day = period_reward / 10,000 / program days`.

### Fills (primary model M1, deliberately pessimistic)

- **When a side fills:** a yes bid at P fills in full when any public trade prints at yes price ≤ P with taker side
  `no`. A no bid at Q fills when any trade prints at yes price ≥ 1 - Q with taker side `yes`.
  - Fills come from `GET /markets/trades`, read every 5 min, deduplicated by trade id.
  - We are assumed to be at the front of the queue. That maximises fills, and with them the exposure to adverse
    selection.
- **After a fill:** the side earns no reward until it is re-posted at the next snapshot.
- **Cap:** at most **3 fills per side per market per CST day**. After that, the side stops quoting for the day.
- **Diagnostic only (M2):** FIFO, behind the resting size at our price at the last snapshot, with no credit for
  cancellations.

### Value of a fill (markout)

- **Bought YES at P:** settlement (1 or 0) − P. **Bought NO at Q:** settlement − Q.
  - If the market has not settled by the read, use the last observed mid instead. The settled share is reported.
- **Fees:** series whose `fee_type` is `quadratic` charge makers nothing. Series with `quadratic_with_maker_fees`
  are charged 0.0175 × p × (1 − p) per contract.
- Markouts at 1 h and 24 h after the fill are diagnostics only.

### Statistic and decision

- **Net per day** = (Σ rewards + Σ fill P&L) / collected days, over the day's books. The rewards are not converted
  for credit status.
- **Interval:** 95% percentile, from an event-clustered bootstrap (cluster = Kalshi `event_ticker`, 2,000
  resamples).
- **Looks:** two only.
  - **Look 1** at 72 h of collection: PASS only if both conditions in the PASS row hold. Anything else continues.
  - **Look 2** at 120 h is final.

| verdict | rule |
|---|---|
| **PASS** | point ≥ **$25/day** on the $2,500 book **and** 95% lower bound > 0 |
| **KILL** | 95% upper bound < 0, **or** point < **$10/day** |
| **INSUFFICIENT** | anything else; at look 2 it counts as KILL for now |

- **What a PASS leads to (still not a live order):**
  1. confirm whether Kalshi incentive credits can be withdrawn as cash;
  2. confirm the program's term past 2027-01-01;
  3. then propose a capped live pilot ($500 of capital, the quietest markets, in a betting-change window, only with
     the user's explicit yes).
- **What cannot be measured here:**
  - competitors reacting to our presence (we are not in the book);
  - queue effects of a real order;
  - any program change before 01-01.

## Collector

- **Script:** `scripts/s8_lip_shadow.py`.
  - `select` picks the universe.
  - `collect` loops: books every 60 s, trades every 5 min, and a daily reselect.
  - It runs at Idle priority on the host, not on the fleet.
- **Data:** `C:\tmp\pfmon\s8\` (outside the repo); hourly JSONL, gzipped when the hour closes.
- **Heartbeat:** `C:\tmp\pfmon\s8\heartbeat.json`. The portfolio-monitor readings check it and restart the collector
  if it is stale.
- **Tests:** `tests/test_s8_lip_shadow.py` covers the reference price, the shares and the target test.

## Log

- 2026-11-20 ~8:10 AM CST: lane opened; pre-registration written; collector not started.
