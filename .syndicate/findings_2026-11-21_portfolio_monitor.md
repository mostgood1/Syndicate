# Portfolio monitor — Sat 11-21 (Central)

Lane `portfolio-monitor`. Counts and percentages only (the repo is public). Times are CST.

## 2:00 AM — the fleet-watcher's question, the dead watch fixed, and the grade conflict read

**Asked** (fleet-watcher, via the NCAAF backtesting session): Portfolio Watch counted 5 anomalies on 11-20; what are they
and does any need action?

**The 5 (all from the 18 readings 12:28 AM - 11:04 AM):** all are `ENDPOINT ... slow`, inside 9:27 - 10:34 AM:
- 9:27 AM, three in one reading: live_today 5.39 s, settings 3.45 s, page 3.20 s. The settings figure was the probe's
  own Idle-priority starvation: 3.45 s client against 285 ms server. That was fixed at 9:32 AM by `8506b7202`.
- 9:58 AM: live_today 8.77 s.
- 10:34 AM: live_all 5.80 s.

All five come before the web decode fix (the 40 MB Layer 2 shortlist, `eeeb62a63`) loaded at 11:38 AM. Those are the
web stalls lane `web-silent-worker-kills` already owns. **No action from them.**

**The count covers only half the day.** 11-20 has no readings after 11:04 AM (F25 below), so it is a morning count. The
first hours after the decode fix were never read by this watch.

### F25 — Portfolio Watch dead for 14.5 h, RESOLVED 2:00 AM
- **What happened:** a bare Python 3.12.10 was reinstalled at 11:24 AM 11-20, and numpy, openpyxl and opencv followed at
  11:37. The `py` launcher picks the newest version, so the task's `py.exe -3` switched from 3.11 to 3.12.
- **Why it failed:** 3.12 has no `tzdata`, so the probe and the history step died on `ZoneInfo("America/Chicago")`.
  29 of 29 runs failed, 11:34 AM - 1:34 AM.
- **Why nothing flagged it:** LastTaskResult stayed 0, because `conhost --headless` hides the exit code.
- **Already known elsewhere:** lane engine-learner logged the reinstall at 12:29 PM (`1ab8a976e`), and the daily review
  recorded this outage at 1:50 AM (`07543e5ee`). The review took one reading by hand with 3.11 at 1:47 AM.
- **Fix:** the task action is now
  `conhost.exe --headless C:\Windows\py.exe -3.11 C:\SyndicateProd\portfolio_watch\run.py`. The 2:00:48 AM run was
  rc 0 on probe, page data, history and dashboard (113 readings; rollup 107 days through 11-20).
- **The other `py -3` tasks on this host:**
  - SyndicateS8Collector: unaffected. It has run on 3.11 since 9:26 AM 11-20 (heartbeat cycle 975, 0 errors), and it is
    stdlib-only, so a restart on 3.12 would still work. Left as is.
  - SyndicateEngineWatch: engine-learner gave it a time-zone fallback.
  - SyndicatePlayCards: engine-learner lists it as at risk. Not mine; not touched.

### F26 — the grade conflict is a false alarm; the cross-check is blind on in-game NO moneylines
**Hypothesis, written before the check:** the 1:47 AM `LEDGER grade_conflicts: 1` is either a wrong-side fill (what the
check exists to catch) or our resolver mis-reading the side. If Kalshi settled the market against the side we hold and
still paid us, it is a wrong-side fill. If Kalshi's settlement matches the side we hold, it is our resolver.

**The row:**
- Kalshi in-game NBA moneyline, New Orleans at Oklahoma City, 11-20.
- Position `ingame:KXNBAGAME-26NOV20NOPOKC-NOP:no`, i.e. NO on "New Orleans wins".
- Ledger `outcome won`, `settled_by venue`.
- `grade_check`: our_outcome lost, venue_outcome won, settled_value -6.0.

**Kalshi's public market:** `KXNBAGAME-26NOV20NOPOKC-NOP` is finalized with result **no**, and the `-OKC` market resolved
**yes**. Oklahoma City won, so NO on New Orleans won. **The venue and the ledger are right, and this is not a wrong-side
fill.** Our resolver's "lost" is the error. That is consistent with it grading NO as if we held New Orleans to win; I
believe this but have not traced it in the code path. Hypothesis 2 is confirmed and hypothesis 1 is ruled out.

**The class, from the 2:00 AM ledger (every Kalshi in-game h2h row carrying a grade_check):**

| held side | order `side` | agrees | reason | rows |
|---|---|---|---|---|
| yes | home / away | True | — | 39 |
| yes | yes | None | no_matchup_on_order | 2 |
| no | no | None | side_not_a_team_in_this_game | 36 |
| no | no | None | no_matchup_on_order | 1 |
| no | no | True | — | 1 |
| no | no | **False** | — | **1** (this row) |

In-game NO moneylines record `side "no"` instead of a team, so `_our_verdict` cannot place them. The venue-vs-game
check, which `paper_settlement._check_venue_grade` calls the only machine check for a wrong-side order, has therefore
graded 2 of 39 in-game NO moneylines, and one of those 2 came out inverted. A real wrong-side fill on that class would
go unseen.

**Owner:** no OPEN lane claims `paper_settlement.py`, `bet_status.py` or `game_line_bet.py`. This was checked against
origin/main `lanes.md` at 2:05 AM. kalshi-exit-path claims only `venue_settlement.py`'s partial-close functions. A fix
gets its own lane. It writes only `grade_check` and never `outcome` / `pnl_dollars`, so it is not a betting change. Clearing the
open conflict (`acknowledge_grade_conflict`) writes the live ledger and waits for the user's yes; it changes no money.
Until then the portfolio page shows "1 settled bet disagrees with the actual game result".

## 10:00 AM — "23 anomalies on 11-21": a counting artefact, plus two real items

**Asked** (fleet-watcher, via the NCAAF backtesting session): the rollup shows 23 anomalies on 11-21 with 2 bets graded,
while page data shows 5 and then 4. Is something wrong, or is the rollup miscounting?

**Breakdown.** The rollup summed every non-GATE anomaly line over every reading of the day:
- 16 readings, 1:47 - 8:34 AM: each one re-flagged the same `LEDGER grade_conflicts: 1` (F26, a false alarm).
- 9:04 AM: 4 lines. 9:34 AM: 3 lines.
- 16 + 4 + 3 = 23.

Page data counts the latest reading only, including its GATE line: 4 + 1 = 5, then 3 + 1 = 4. The two counts measure
different things and do not conflict. **Fixed:** `build_history.ops_by_day` now counts DISTINCT anomalies per day (the
text with numbers blanked). The old sum survives as `anomaly_lines`, and the dashboard column is renamed "Distinct
anomalies". After the 10:02 AM run: 11-21 = 4 distinct from 25 lines over 19 readings; 11-20 = 4 from 5; 11-19 = 1 from
3. 7 tests pass.

**The 4 distinct on 11-21:**
1. **The grade conflict (F26).** A false alarm; it waits on the user (fix the check, clear the conflict).
2. and 3. **Slow live and page reads:**
   - 9:04 AM: live_today 4.22 s, page 4.58 s.
   - 9:34 AM: live_today 3.27 s.
   - The SERVER log agrees, so this is not probe starvation: `/api/portfolio/live` max 4,134 ms, and p50 3,149 ms in the
     9:34 window.
   - This is after web's decode fix (11:38 AM 11-20), so it was passed to lane web-silent-worker-kills as a reading for
     its measurement.
4. **Resting Polymarket order `ac07e83e`:**
   - The order: NBA alternate spread, Spurs -15.5 against the Pelicans (tip-off 7:10 PM). Submitted 6:50 AM as a taker
     at 0.57 against a 0.56 slate quote 51 s old.
   - Its state: unfilled since (`ORDER_STATE_NEW`, cum 0). The reconciler reads it about every 5 min.
   - **It cannot rest into the game:** the worker log shows `TIME_IN_FORCE_GOOD_TILL_DATE`,
     `goodTillTime='2026-11-22T01:10:00Z'`, so the venue expires it at tip-off.
   - What it costs: `cancel_stale_resting_orders` is Kalshi-only. The worker's comment calls widening it to Polymarket "a
     different decision", and `polymarket_us_orders.cancel_order` exists but nothing calls it. So the order holds its
     idempotency key until kickoff, and the bet cannot be re-placed at a price that exists. That costs a possible fill,
     not money at risk.
   - **Lead, not a lane:** a Polymarket stale cancel (the same age + price-band rule as Kalshi). It changes which bets
     are held, so it is a betting change: window only, the user's call. First filed 09-11 in lanes_history (when there
     was no kickoff expiry either; that half was fixed).

**No action needed now** beyond what F26 already waits on.

## 3:08 PM — resting order `373a43d7` is a men's bet placed on Kalshi's WOMEN'S market (F27)

Flagged by the fleet-watcher from the 2:34 PM reading (`resting order 373a43d7 (taker): resting 174 min`). It is
**not** the `ac07e83e` class (Polymarket, good-till-date). It is a Kalshi order on the wrong game.

- **The row** (`/api/portfolio/live?on=all&show=all`, read 21:02Z): sport `ncaab`, OddsAPI event `089763b5`
  (`ncaab_source` odds), UC Irvine @ San Diego, tip **21:30Z (3:30 PM)**, h2h side away (UC Irvine), taker at 0.61,
  submitted 17:40:32Z, `venue_status=resting`.
- **The ticker:** `KXNCAAWBGAME-26NOV21UCIUSD-UCI`. `kalshi_catalogue` maps `KXNCAAWBGAME` to `wncaab`. The women's
  UC Irvine @ San Diego game tips **2026-11-22T03:00Z (9:00 PM)** (`wncaab_source` scoreboard). Today's live-odds-worker
  log carries no `KXNCAAMB*` ticker for `UCIUSD`, so Kalshi lists no men's market for this game.
- **How often:**
  - **Live endpoint:** 1 of 5 `KXNCAAWBGAME` rows is labelled `ncaab`; this is the one.
  - **Ledger archive:** 32,005 Kalshi rows. The only other family/sport mismatches are 2 PAPER rows (key `c0a80a61`)
    on the same game today. No live fill, ever.
- **Cause, reproduced locally against `kalshi_board_join._resolve_event`:**
  - It resolves a market's event by team codes against `_distinct_games(board_rows)`. That list carries **no sport**,
    and `portfolio_commit._resolvers_from_markets` passes the whole cross-sport board.
  - `sport_for_series` picks the club map only.
  - Results for `KXNCAAWBGAME-26NOV21UCIUSD-UCI`:
    - board with only the men's game: `ok` → men's event `089763b5`;
    - board with both games: `ambiguous` (refused);
    - the mirror case (a `KXNCAAMBGAME` market with only the women's game on the board) also resolves `ok`.
  - So a market whose own game is missing from the board lands on a same-named game in the sibling sport. The women's
    game had no OddsAPI women's odds row (`wncaab_source` odds 11-21: no UC Irvine row), so it was not on the board.
- **Exposure now:**
  - Unfilled. Kalshi orders are good-till-canceled.
  - `cancel_pregame_resting_at_kickoff` reads the row's own (men's) `commence_time`, so it should pull the order at
    21:30Z. Until then it can fill at 0.61 on the women's game.
  - The boot stale pass at 18:26:35Z skipped it (`CANCEL_SKIPPED_NO_PRICE`).
  - If it filled, the venue would settle it on the women's result, and our grade would read the men's.
- **Owner:** no OPEN lane claims `kalshi_board_join.py` or `kalshi_catalogue.py` (origin/main 21:05Z).
- **The fix:** `_distinct_games` carries each game's `sport`. `_resolve_event` matches only games whose sport equals
  the market's `sport_for_series`, and a game with no sport stays eligible. It changes which bets are placed, so it is
  a **betting change**: the 11-24 window, or a `broken money path` exception on the user's yes.
- **Taken:** no venue action. A watcher is on the log for this order's `CANCEL_AT_KICKOFF`, fill or terminal
  reconcile, until 22:15Z.
- **3:32 PM, retired unfilled:**
  - The log line: `RECONCILED key=373a43d7 ... submitted->rejected venue_status='canceled' contracts=0` (21:32:16Z).
  - **Our kickoff pass did not send it.** No `CANCEL_AT_KICKOFF`, `[kalshi_orders]` cancel or any other cancel request
    appears in the live-odds-worker, refresh-worker or web logs, 21:00-21:33Z. The cancel came from outside the role
    processes (by hand, another session's script, or Kalshi itself); which one is not known.
  - Exposure is now 0. F27's code defect stands: the next same-named game whose own Kalshi market is missing can land
    on the sibling sport again.

## 6:35 PM — F27 fix built (lane `kalshi-join-sport-scope`), not loaded

- User "Yes, build it". Sport-scoped event resolution landed on main at `b65707658`, default `report`. Today's
  matches are unchanged, and refresh-worker prints one `SPORT_SCOPE` count per build once the fleet carries the
  commit. `on` is a betting change (window only).
- Baseline: 21,349 archived Kalshi rows have the same sport on the row and its series; 3 differ (the F27 class),
  plus the 1 live row. `event_matches_two_games` read 13 to 23 markets per build (22:56Z to 00:18Z), which caps what
  `on` can newly resolve. Details and predictions: `findings_2026-11-21_kalshi_join_sport_scope.md`.

## DAILY SUMMARY — Sat 11-21 (Central), written Sun 11-22 2:10 AM CST by the daily learning review

Counts and percentages only (the repo is public). Sources: `daily_rollup.json` and `performance.json` built from the
2:04 AM CST 11-22 watch reading (ledger saved 08:04:06Z), and the 47 watch readings dated 11-21 CST. Every 11-21 game
is graded: 0 started and unsettled, 0 late.

**Performance.**
- **11-21: 62 graded bets / 47 games, ROI +5.33% [-12.8, +23.5].** Won 58.1% against a 62.2% breakeven (excess -2.5
  wins): as on 11-19 and 11-20, the gain came from where the stakes sat, not from winning more than the prices implied.
- **7 d: 367 bets / 197 games, +1.68% [-7.4, +10.8]** (11-20: -3.40%). First positive 7 d since 11-15 (+0.07%).
- **30 d: 1,709 bets / 773 games, -4.91% [-10.2, +0.34]** (11-20: -7.06%). **The 30 d range includes 0 for the first
  time in the rollup since at least 11-07** — the window dropped its oldest losing days and 11-21 was positive.
  All-time: 2,262 bets / 1,234 games, -10.41% [-17.4, -3.4].
- **Fee-net CLV:** 30 d -0.39 pp; 7 d -0.64 pp (clv_n-weighted over the last 7 rollup days, 179 priced closes);
  11-21 alone -1.73 pp on 35.
- **Fees: 2.87% of stake on 11-21, 4.0% over 30 d** — now about 81% of the 30 d loss (ROI before fees ~ -0.9%).
- **Gate: 83 of 800 events**, clock BC-053 since 11-19 17:00Z (11:00 AM CST); since then +4.53% (lower -9.0), excess
  wins -7.6; condition 3 fails (fee-net CLV -1.47 pp against ROI +4.53%, close calibration -8.44 pp, z -1.37).
  2 deploys.md loads still unclassified.
- **Revision:** the 11-20 rollup row now reads 30 bets / 23 games, +4.06% (yesterday's summary had 23 / 17, +13.47%);
  later grades landed on that date. Not re-derived further.

**30-day slices beyond noise (95% range excludes 0):**
- EV band 2-5 -7.47% [-14.8, -0.12] against a predicted +4.11% (1,036 bets / 573 games);
- price 0.30-0.45 -12.32% [-23.6, -1.0] (305 / 199).
- **Left beyond-noise today:** totals -11.13% [-22.4, +0.17] (412 / 325); largest-stake quartile (63.7% of dollars)
  -4.99% [-12.4, +2.4]; the `model_edge` path -4.99% [-11.6, +1.7]. Kalshi -3.38% [-9.0, +2.2], Polymarket -10.41%
  [-23.1, +2.3], both noise.

**Operations (47 readings).** Anomaly kinds, by readings flagged: GATE 47 (the 2 unclassified loads); LEDGER
grade_conflicts 1 in all 47 (the F26 false alarm, unchanged); ORDERS resting taker order 25 (22 for one order, 3 for
the F27 order 373a43d7); ORDERS failed/rejected 19 (at most 3 of 68 by day end); CAP Polymarket dollars over the day
cap 14 (5:04-11:34 PM, 424-1322% of cap — not investigated here); ENDPOINT slow 5. Endpoint reads over 2 s: 9, of which
6 over 3 s (live_today 4, page 1, plan 1), all but one inside 9:04-11:04 AM. Plan age: median 6.2 min, max 31.7 min.
Orders 11-21: 68, 65 filled, 3 not filled.

**Studies.** S8 heartbeat 08:06:05Z (cycle 2,407, 0 errors), fresh; LOOK 1 due after 11-23 9:00 AM CST. S6 forward:
73 distinct events with settled orders submitted from 11-20T00:00Z (need 150; counted from the newest `live_all.json`,
not the tool's fleet join) — not run. S5 forward: 94 events with selected_date >= 11-19 (need 150) — not run. 11-24
window check not yet due; baseline: `venue_quote_at_submit` is populated on 86 and `venue_filled_at` on 94 of 2,552
ledger rows already, so the 11-24 read must count rows submitted after the load, not presence. F27 readings not due
(11-25).

### What the data teaches (11-21)
- The 30 d trend turned: -7.39% (11-19) → -7.06% (11-20) → -4.91% (11-21, 773 games), and the upper bound crossed 0
  (+0.34). Most of the one-day move is the window roll, not new skill: 11-21 itself was +5.33% on 47 games.
- The recent upturn is not backed by prices: 7 d ROI +1.68% while 7 d fee-net CLV is -0.64 pp (179 closes) and the
  gate's close calibration is -8.44 pp. Results and the instrument disagree in sign, so treat the upturn as variance.
- Of the five persistent signals from 11-17..11-20, two hold: price 0.30-0.45 (-12.3%, unchanged point estimate) and
  EV 2-5 overstatement (realised -7.47% vs +4.11%, gap narrowed from 14.5 to 11.6 pp). Totals (-11.1%) and the
  largest-stake quartile (-5.0%, from -8.6%) fell into noise as the window rolled; totals' point estimate barely moved,
  the quartile's did — so yesterday's stake-cap lead lost most of its motivation.
- Fees are 4.0% of stake against a -4.91% ROI: before fees the 30 d book is about -0.9%. Fees are now the bulk of
  the loss, and 11-21's lower 2.87% fee share is one day.
- Winning frequency still trails the prices: 30 d excess wins -29.6 (55.2% won vs 56.9% breakeven); every one of the
  last three positive days also had negative excess wins.

**One optimization lead (pre-registrable, offline, changes nothing live).**
- *Hypothesis:* our fair price over-rates underdogs: on bets priced 0.30-0.45 the model's win probability exceeds the
  realised win rate, which is what drives that band's -12% and part of the EV 2-5 overstatement.
- *Data:* the 30 d graded book in `live_all.json`, bets with fill price 0.30-0.45 (305 / 199 games): per game, the
  stake-weighted mean model probability (fill price + model_edge) against the realised win rate, event-clustered; then
  a forward copy on bets selected from 11-23 once that band reaches 150 games.
- *Decision rule:* GO (name a longshot fair-price shrink toward the market, with w fitted on the 30 d set, as a
  challenger for the 12-08 window) iff realised-minus-predicted has a 95% upper bound < 0 on BOTH the 30 d set and the
  forward set, AND the same check on the 0.45-0.55 band is inside noise (so it is a longshot effect, not a global
  over-confidence). Otherwise KILL.
