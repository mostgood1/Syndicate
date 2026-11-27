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
- 2026-11-20 8:12 AM CST: collector `6e8c94369` started (run copy `C:\tmp\pfmon\s8\s8_lip_shadow.py`, sha256 prefix
  a7967dd833c3579b, the same as the commit), Idle priority, `collect --hours 124`.
  - The first select found **8,148 active liquidity programs with at least 6 h left** (7,260 on 11-19).
  - It reads every order book before choosing the book, about 35 min at its request spacing.
- 2026-11-20 8:35 AM CST: select done: 7,323 payable markets.
  - **Book: 43 markets, $2,499 of capital, static ceiling $277/day** (`universe_20261120T141218Z.json`).
  - Collection began 8:37 AM.
- **2026-11-20 8:37-9:24 AM CST: the first run (pid 11068) died silently after cycle 3.**
  - There was no reboot (last boot 11-17), and stderr and the log were empty.
  - It was most likely killed with this session's app process tree when the session restarted.
  - **14:37-15:26Z, 49 min, is UNOBSERVED.** Under the pre-registered rule, a gap over 120 s earns 0, which is
    conservative.
- **2026-11-20 9:26 AM CST: moved to the Windows scheduled task `SyndicateS8Collector`.**
  - It runs as the user with an Interactive logon, using `pyw.exe`, so no window. It restarts every 10 min with
    IgnoreNew, and the trigger ends 2026-11-25 13:30 local.
  - Collector commit c8844c70a adds:
    - `--until 2026-11-25T18:12:00Z`, so restarts cannot extend the study;
    - a restart reuses the current slot's book.
  - It resumed at 15:26:47Z with the same book, pid 19300 at **Idle** (verified). Cycle 4 at 15:32Z: 43 of 43 books,
    0 errors.
  - **Delete the task after 11-25.**
- **2026-11-20 9:45 AM CST: credit-to-cash check, a gate for any pilot. Leaning yes, not confirmed.**
  - Kalshi's help pages: rewards post as credits (Rewards; Account → Activity → Credits). The minimum is $1.00, and a
    verified SSN is required above the IRS reporting threshold, so they are taxable like income.
  - A CFTC filing names them "Promotional Bonus Credits" and forbids manipulation aimed at withdrawing their value,
    which implies the value can be withdrawn.
  - The exact rule (withdraw directly, or only after trading?) is not public in what was found. **The user's account
    Rewards page or Kalshi support settles it.**
- 2026-11-20 ~10:20 AM CST: **the scorer was pushed (c7dbc576e) BEFORE any collected data was read**
  (`s8_lip_shadow.py score [--final]`, 16 tests). It implements the table above. M2 and the 1 h / 24 h markouts are
  named in its output as not computed. Look 1 and look 2 are run by the daily task `portfolio-learning-review`.
- **2026-11-24 1:52 AM CST (07:52:29Z): LOOK 1 READ, verdict PASS.** Run by the daily learning review, on its first
  run after 11-23 9:00 AM CST.
  - **Command:** `py -3 scripts/s8_lip_shadow.py score --out C:\tmp\pfmon\s8`; output in
    `C:\tmp\pfmon\s8\look1_score.txt`.
  - **The first attempt crashed before scoring anything.**
    - The error: `TypeError: '<' not supported between instances of 'dict' and 'dict'` in `score_stream`. Two public
      trades in one market shared a `created_time`, so `sorted()` fell through to comparing the trade dicts.
    - **The fix is to the tie-break only:** sort on the timestamp key, and ties keep their input order
      (`key=lambda x: x[0]`). The reward, fill and markout rules are unchanged. 16 of 16 tests pass.
    - The fix came after the data existed, but it changes no statistic; it only lets the sort finish. The verdict
      below comes from the one run that completed.
  - **Result:** 3.719 days collected; 169 markets / 71 events; 189,725 snapshots; 9,272 trades; 484 M1 fills, 196
    settled and 22 unpriced. Reward $127.6/day, fill P&L $48.4/day, **net $176.0/day, 95% [$81.8, $288.2]**
    (event-clustered bootstrap).
  - **Verdict as registered: PASS** (point >= $25/day and lower bound > 0).
  - **Caveats, read with it:**
    - Fill P&L is POSITIVE under M1, the deliberately pessimistic front-of-queue model. But only 196 of 484 fills are
      settled; the rest are marked at the last mid.
    - M2 (FIFO) and the 1 h / 24 h markouts were not computed.
    - Competitor reaction and the queue effects of a real order cannot be measured here.
  - **Nothing changes live.** Per the pre-registration, a PASS leads only to the user's decisions:
    1. whether Kalshi reward credits can be withdrawn as cash (still unconfirmed);
    2. the program's term past 2027-01-01;
    3. then a capped $500 pilot in a betting-change window, only on the user's explicit yes.
  - The collector keeps running. The scheduled task still runs look 2 after 11-25 18:12Z, then disables
    `SyndicateS8Collector`. Look 1 is already a terminal PASS under the two-look rule, so look 2 is a confirmation
    read.
- **2026-11-25 12:12 PM CST (18:12:29Z): collection ended at its hour limit,** as registered (`s8.log`: "collect: stopped at the hour limit"). The last heartbeat was 18:11:35Z, cycle 7,329: 40 markets, 40 books ok, 0 errors.
- **Look 2 was late.** The daily learning review should have run it on its first run after 18:12Z. That was 11-26 at 1:57 AM CST, during the 12:14-11:11 AM CST network outage (`findings_2026-11-26_portfolio_monitor.md`), and all four attempts (07:57, 08:06, 08:26, 09:03Z) failed with `ENOTFOUND`. The data was complete before the outage began, so the outage cost no collection.
- **2026-11-26 10:09 PM CST (04:09:31Z 11-27): LOOK 2 (FINAL) READ, verdict PASS.** Run by the portfolio-monitor session at the user's request ("Run it now", answering "Should I run S8's final read now instead of waiting for 1:57 AM?").
  - **Command:** `py -3 scripts/s8_lip_shadow.py score --final --out C:\tmp\pfmon\s8`, run once at Idle priority, rc 0, 60 s. The output is in `C:\tmp\pfmon\s8\look2_score.txt` and `score_20261127T040931Z.json`. The scorer is unchanged since look 1 (`f41762fd4`).
  - **Result:** 5.15 days collected; 235 markets / 89 events; 234,941 snapshots; 13,255 trades; 713 M1 fills, 368 settled and 0 unpriced. Reward $123.7/day, fill P&L $38.1/day, **net $161.8/day, 95% [$46.0, $317.3]** (event-clustered bootstrap).
  - **Verdict as registered: PASS** (point >= $25/day and lower bound > 0). It agrees with look 1 ($176.0/day [$81.8, $288.2] at 3.72 days).
  - **What moved from look 1:** the point fell 8% and the lower bound fell from $81.8 to $46.0 as 66 markets / 18 events were added. The reward per day held (127.6 -> 123.7). Fill P&L fell (48.4 -> 38.1). Half of the fills (368 of 713) are now settled, against 196 of 484 at look 1.
  - **Caveats, unchanged:**
    - M1 is the pessimistic front-of-queue fill model, and its fill P&L is still positive.
    - The other 345 fills are marked at the last mid.
    - M2 (FIFO) and the 1 h / 24 h markouts were not computed.
    - Competitor reaction and the queue effects of a real order cannot be measured from a shadow.
  - **`SyndicateS8Collector` was disabled at 10:10 PM CST** (`Disable-ScheduledTask`; State Disabled). No collector process was running (pid 19300 gone).
  - **`portfolio-learning-review` prompt updated** so tonight's 1:57 AM run marks looks 1 and 2 done and does not score again.
  - **Nothing changes live.** The study is finished. The next steps are the user's decisions, in this order:
    1. whether Kalshi reward credits can be withdrawn as cash. Leaning yes, not confirmed; the user's account Rewards page or Kalshi support settles it.
    2. whether the incentive program runs past 2027-01-01.
    3. then a capped $500 pilot (the quietest markets) in a betting-change window, only on the user's explicit yes. That pilot would be a betting change, and its own lane.
