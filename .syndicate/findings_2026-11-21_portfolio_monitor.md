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
