# Profit learning program — how Syndicate learns its way to a positive, scalable live book (2026-11-18)

**Asked for by the user** (2026-11-18):
- "I need YOUR ideas on learning and how we make this achieve our passive income goals";
- "make sure not to waste the breadth and depth of the historical data available from not only this endpoint, but all
  areas of Syndicate".

**Written by** the portfolio session (lane `portfolio-monitor`). It is a measurement program, not financial advice.
No result guarantees future returns.

## Where the book stands (fleet, measured 2026-11-18; details in `findings_2026-11-18_portfolio_monitor.md`)

- **Results:** the live book is **-7.35% ROI over 30 days [-12.8, -1.9]** (1,605 bets / 673 games) and **-11.0% all
  time.** No slice wins beyond noise.
- **Every live pick comes from price shopping:** the venue's ask sits below the de-vigged sportsbook consensus, and
  the sim has 0 weight.
- **Ruled out today, pre-registered:**
  - a higher EV floor (paper ladder: returns do not rise with net EV);
  - the closing-price gap (mostly the venue's spread);
  - the spread paid at entry (tight-spread bets lose as much);
  - a better fair-price source (both the consensus and the venue's own price overstate our sides).
- **What is left: the trigger is adversely selected.** Our picks win 7.8 pp less than the consensus and 5.9 pp less
  than the venue's own fair price (388 bets / 272 games).
- **Test B's forward looks agree** (`findings_2026-10-24_live_cell_scorecard.md` s13). Sharp-book edge >= 0.4 is
  -7.2% overall, but **bets whose Pinnacle quote was more than 2 min old lose -11.3% [-22.2, -0.8], against -1.0%
  [-15.2, +12.2] when fresh.** The "edge" is mostly a stale price elsewhere.

## Principles

1. **Champion and challengers.**
   - The live book is the champion. Every idea is a challenger, judged on history first, then paper, then live.
   - A challenger is promoted only in a betting-change window (`betting_change_windows.md`, every second Tuesday),
     and only on its pre-registered evidence.
   - A window may promote nothing.
2. **Every test is pre-registered:**
   - the hypothesis and its falsifier are written to main before any number is computed;
   - time-split (fit before a date, judge after it);
   - fee-net;
   - event-clustered, because 1,600 bets are about 670 games.
   - Each test prints per-family date coverage and their intersection first (CLAUDE.md, the lossy-mirror rule).
3. **Pay the minimum tuition.** While no challenger has passed, the champion's live stakes should sit at the smallest
   size that still measures fills and slippage. The user decides; it is a pure risk reduction, so it may load outside
   a window.
   - **Measured 11-18:** the cut is worth about $1.30 a day of expected loss at the last week's volume. Its env keys
     load only through a drained full down/up, which also loads every unloaded commit on main into the roles.
   - **Decided 11-18 ~1:20 PM CST, user: "Yes, drop the cut".** Sizing stays as it is: stakes compound off the venue
     capital (fraction 1.0, its maximum), so volume follows the balances and falls as the book loses. Lane
     `live-stake-minimum` closed; nothing loaded.
4. **Slices are evidence for per-line rules, never a sport or market switch** (learnings line 1056).
5. **Nothing is thrown away.** Every family below is kept, joined and reused.

## The data, all of Syndicate (inventory by the systems engineer, 2026-11-18)

| family | depth | labels |
|---|---|---|
| live execution ledger + archive | 2,159 graded live bets, 66 slates, 08-06..11-17 | outcomes, closes, sizing |
| paper ladder + paper venue books | 27,347 settled, 10-20..11-17, by net-EV band | outcomes |
| Test B forward ledger | 23,480 settled since REG; 19,455 with the quote's capture age | outcomes, Pinnacle close |
| priced-population ledger | every priced candidate since 09-14, ~5-20 MB/sport/day | graded by the scorecard |
| Layer 2 / evaluation ledger | first-sighting picks since ~10-07 | outcomes |
| model scorecard / optimizer / sim-gap | daily since 09-17 | outcomes |
| `book_quotes` (all books) | 120-day retention | closes |
| in-play recorder (Kalshi 10 s, books, ESPN) | **27 nights (10-20, 10-22..11-17; 10-21 was not recorded), 319 files, 14.1 GB; copied and compressed 11-18 to 1.4 GB in `~/syndicate-prod/data/research/inplay_recorder/` (319 of 319 verified; originals untouched on C:\tmp); new nights copied daily by the Windows task `SyndicateInplayPreserve`** | scores + settlement |
| Kalshi public trade prints | 3,566 games, 3.51M prints, 2025-07..2026-10-24 | results |
| maker shadow, combos, cheat sheets / SGP paper, momentum-lag study | various | various |

## The studies, ranked (each is pre-registered when it starts)

1. **S1: freshness and adverse selection (start now).** Do picks lose because the price they beat was stale?
   - Data: Test B's 19,455 orders with capture age, plus `book_quotes` for whether the venue moved after the sharp
     quote, plus the paper ladder.
   - Challenger rule: fire only when the sharp or consensus quote is fresh (<= N min, N fit before the split) **and**
     the venue has not moved toward the consensus since it.
   - Win condition: out-of-sample fee-net ROI lower bound > the champion's on the same dates.
   - **Result 11-18: FALSIFIED as registered** (`findings_2026-11-18_s1_freshness_study.md`; pre-registration
     `5ee9e18c1` pushed before the run, result `5affebf41`).
     - N = 10 min, chosen on FIT.
     - On TEST (6,300 orders / 274 games), fresh-only minus all is **+0.21 pp [-2.82, +3.24]**.
     - The consensus-age arm fails the same way.
     - No challenger goes to the 11-24 window.
   - **Lead for S6 (exploratory, not a result):** picks did 12.6 pp worse when the venue's own price had moved
     toward the reference before submit [-28.2, +2.9]. That is 747 vs 301 orders, and only 34% of orders have the
     venue quote, which is the I2 gap.
2. **S2: in-play 95-99c favourites**, the one structural cell that survived fees: +1.1..+1.6c per contract in 5 of 6
   sports (`findings_2026-10-24_kalshi_market_price_map.md`). Forward-confirm on the recorder nights with the ESPN
   clock. Its tails (late flips, score corrections) are sized before it goes live.
   - **Result 11-18: KILL**, under the cell's own pre-registration (R3, `in-game-trading`, locked 10-25)
     (`findings_2026-11-18_s2_inplay_favourites.md`).
     - Over 27 nights, the first qualifying ask was **+0.26c per game [-1.59, +1.95]**.
     - **19 of 476 games lost (3.99%)**, above the registered 3% line.
     - After the lock alone: about +0.8c and a 3.4% loss rate.
     - No challenger. What is left of the cell is the maker side, which is S3's question.
3. **S3: maker entry.** Earn the spread instead of paying it, in zero- and low-fee cells (maker shadow, counted looks
   at 200 / 400 / 600). Today's tests say our picks are not worse than the venue's fair, so capturing the spread is a
   direct lever.
   - **Started 11-18, read at the existing registrations** (`findings_2026-11-18_s3_maker_entry.md`). Neither test is
     due yet:
     - **Paper maker shadow:**
       - no cell has a look;
       - soccer totals reaches its 200 look about 11-26/27 (171 now, -11.9% [-28.1, +4.9]);
       - soccer spreads will be INSUFFICIENT at the 01-31 stop.
     - **Live maker pilot:**
       - about 22 of 30 timed fills, so the re-judge falls about 11-24;
       - that holds only if fill times are saved: the ledger row has no fill time, and the log rotates in ~3.5 days;
       - 844 pilot log lines were saved 11-18 to `research/maker_pilot/`.
     - No maker challenger before the 12-08 window.
4. **S4: Kalshi as the in-play prior, the sim as the challenger.** Kalshi's in-play log loss beats the books by
   0.02-0.09 nats, and the sim earns weight only where it beats Kalshi out of sample.
5. **S5: a calibration map by side and price band** (live + ladder + closes). The live book's 0.30-0.45 band is -12.6%,
   and longshots lose in every phase. It feeds S1's features.
6. **S6: an adverse-selection model.**
   - Features at entry: quote age, book count, dispersion, time to start, price band, the venue's recent move.
   - Label: won minus fair. Trained on the ladder and live history, time-split.
   - It is a filter in front of any trigger.
7. **S7: correlation products** (Kalshi combos, SGP paper) and **props** (population ledger + forward quote mirror),
   later.

## Infrastructure that makes learning compound

1. **I1: preserve history.** Copy the in-play recorder nightly into the fleet research store. **Done 11-18 (user: "Yes, set it up"):**
   - Backfill complete: 27 nights, 319 files, 1.4 GB compressed.
   - Windows task `SyndicateInplayPreserve` runs daily at 7:15 AM local:
     - it runs `C:\SyndicateProd\inplay_preserve\preserve_inplay_recordings.sh` (source:
       `scripts/preserve_inplay_recordings.sh`);
     - copy only, every file verified;
     - it skips tonight and any night written in the last 90 min;
     - it exits 1 if a file is still missing;
     - log: `~/syndicate-prod/logs/inplay_preserve.log`.
   - First run 11-18 19:40Z: 27 nights, 319 already copied, 0 failed, result 0.
   - Later: the recorder's owner, `in-game-trading`, could write there directly.
   - Still open: review retention for the research families (`book_quotes` 120 d, `odds_history` 60 d, `venue_odds`
     14 d).
2. **I2: log the venue book at every fill:** both sides' asks and depth, at the moment of the order. Today 48% of
   fills have no logged own-side quote before the fill, which blinds every spread and CLV test on half the book.
3. **I3: one decision table:** every candidate, bet or passed, with its features at decision time, its outcome and its
   close. `decision_records` (#709, shadow) is the start; passes are what make the adverse-selection model possible.
4. **I4: a learning scoreboard in each portfolio reading:** the champion against each challenger on the same dates,
   with the window calendar.

## Cadence

- **Every reading (30-60 min):** the champion's ROI with its 95% range, the signals beyond noise, and the challenger
  scoreboard.
- **Weekly:** Test B looks (Mondays, existing) and study progress.
- **Every window (second Tuesday, 2-7 AM CST):** promote at most one challenger, with its evidence on main; otherwise
  load nothing and let the gate count.

## The income arithmetic, plainly

- **Volume (corrected 11-18 from the full live ledger; an earlier version said "about $100 a day today"):**
  - The 30-day average is about $100 a day staked live (graded 10-19..11-17: $3,065).
  - The current rate is lower: **about $49 a day over the last 7 graded dates** ($41 pregame, $8 in-play), and
    about $28 a day on 11-16 and 11-17. Pregame orders are mostly one contract already (226 of 380 in 7 days).
  - At the current -7.35%, $49 a day is about -$3.60 a day in expectation.
  - One contract per order would have staked about $31 a day over the same 7 dates ($29 pregame, $2 in-play), about
    -$2.30 a day. The stake cut is worth about $1.30 a day at this volume.
  - At a proven +2% net, $49 a day would be about +$1 a day.
- **Passive income comes from three things in order:**
  1. a selection that is positive after fees and proven by the gate (800 graded games, ROI lower bound > 0, CLV
     agreeing);
  2. scale within the venues' depth, raising caps step by step behind the gate;
  3. automation, which already exists (the fleet places, prices, settles and reconciles unattended).
- Today the program is at step 1. **The fastest route is to stop paying tuition on a trigger shown to be adversely
  selected, and to let S1-S3 run on history and paper until one passes.**
