# Layer 2 Games Rail — standing monitor AND improvement hunt, 2026-11-17 (lane `layer2-rail-monitor`)

Day 3 of the monitor.
- **User 11-17 ~10:04 AM CST: "Yes, from noon"**, answering "Monitor Tuesday 11-17 with the same
  method?".
- Then, ~10:10 AM CST: **"ensure not only are we monitoring but we should ALSO be looking for any and
  all optimizations or improvements that we can make"**.

So from today every reading also hunts for improvements:
- Each candidate gets evidence with a denominator and an owner.
- An unowned candidate gets its own lane (hypothesis first, an off != on test, landed on main).
- Any fleet load stays the user's call.

Method as on 11-15 / 11-16:
- Probe `scripts/layer2_rail_monitor_probe.py`; runner `scripts/layer2_rail_monitor_run.mjs`; grader
  `scripts/layer2_rail_flag_grade.py`.
- Wrappers `C:\tmp\railmon\grade1116.py` (pre-registered splits) and `C:\tmp\railmon\grade_window.py`
  (bands).
- Times are Central (CST) unless marked Z.

## Two-day evidence base (11-15 + 11-16), read before any 11-17 game

Source: `C:\tmp\railmon\grade_window.py` (read-only).
- Flags graded at first sighting against final chips; game-clustered bootstrap, 90% interval on
  (hit − book fair).
- 11-15: 491 flags / 63 games, using chips from the 11-15 10:24 PM reading (17 flags not final).
  11-16: 256 flags / 35 games.
- Output `C:\tmp\railmon\gw_1115.json` and `gw_1116.json`.

| bucket | 11-15 W-L (hit vs fair) | 11-16 W-L (hit vs fair) | two days |
|---|---|---|---|
| ALL | 256-233 (52.4% vs 47.5%), CI [+0.4, +9.1] | 128-128 (50.0% vs 47.6%) | 384-361 |
| book fair < 0.20 | 3-17 (15.0% vs 11.9%), Brier model 0.137 / book 0.115 | **0-9** (0% vs 11.2%), Brier 0.079 / 0.014 | **3-26** |
| book fair 0.20-0.40 | 11-25 (30.6% vs 29.9%) | 7-17 (29.2% vs 28.8%) | 18-42: hit ≈ fair, no edge |
| book fair 0.40-0.60 | **233-188 (55.3% vs 50.0%), CI [+0.6, +10.4]** | 108-100 (51.9% vs 49.9%) | 341-288 |
| book fair 0.60-0.80 | 6-2 | **12-2** (85.7% vs 65.7%) | 18-4 |
| NBA full-game spreads | **3-19** (13.6% vs 30.3%), CI [−28.1, −0.1] | 10-17 (37.0% vs 40.2%) | **13-36** |
| NBA segment spreads | 22-17 | 17-8 | 39-25 |
| NBA segment totals | 31-27 | 16-8 | 47-35 |
| NCAAB full-game spreads | 30-19 (61.2% vs 49.8%) | 20-9 (69.0% vs 49.7%), CI [+3.5, +34.0] | **50-28** |
| NCAAB full-game totals | 54-59 | 26-42 | 80-101 |
| NCAAB totals UNDER side | 59-40 | **24-53** | 83-93 |
| NCAAB totals OVER side | **35-56** | 12-4 | 47-60 |

**Reading:**
1. **A favourite-longshot pattern in the flags.** Where the book prices the flagged side under 40%,
   the flags hit at or below the book's own number (21-68 combined). The model claims far more (e.g.
   27% vs the book's 3.8% on POR @ MIN u199.5), and its Brier is worse than the book's on both days.
   The flags' value sits in fair 0.40-0.80.
2. **NCAAB totals direction flips by night.** Unders won 11-15 and lost 11-16 (24-53). A fixed level
   (#816's "Spread + level") bets one direction every night.
3. **NBA full-game spread flags lose** (13-36), most on alternate spreads, while NBA segment flags win.
4. **NCAAB full-game spreads** are the steadiest family (50-28).

**In-sample caveat:** these are the same two days that suggested the cuts. Every cut below is
**pre-registered for 11-17 out of sample** and changes nothing until it holds.

## PRE-REGISTERED for 11-17 (written ~10:25 AM CST, before any 11-17 game)

Graded tonight at first sighting, game-clustered, same method:

- **T1 (fair band):**
  - Flags with book fair < 0.40 hit at most their mean fair + 2 pp, and their Brier is worse than the
    book's.
  - Flags with fair >= 0.40 hit above their mean fair.
  - A "flag only when book fair >= 0.40" rule raises the day's hit-minus-fair.
  - Falsified if the < 0.40 flags beat their fair by more than 2 pp on >= 10 games.
- **T2:** NBA full-game spread flags hit below their mean fair. Falsified if they hit >= fair on
  >= 5 games.
- **T3:** NCAAB full-game spread flags hit above their mean fair. Falsified if they hit <= fair on
  >= 8 games.
- **T4:** NCAAB full-game total flags (calibrated) have no edge: |hit − fair| < 5 pp, OR their sign
  matches the night's scoring (all-totals over share). Reported, not a gate.

**CORRECTION ~10:50 AM CST, before any 11-17 game (raised by peer 0f519972 / local_208683f1):**
- T1's clause "a 'flag only when book fair >= 0.40' rule raises the day's hit-minus-fair" is
  **WITHDRAWN as a candidate.**
  - It is a band exclusion: it withholds every line in a fair band.
  - The user's standing rule forbids that: every line is its own decision; fix the model, then score
    each line. It is on record 5 times, 09-22 to 10-03
    (memory `feedback-every-line-its-own-decision`).
- T1's measurements stand unchanged: hit vs fair and Brier by book-fair band. Their result is
  evidence for a per-line TAIL CALIBRATION (shrink the model's probability toward the book's where the
  book's fair is far from 0.5), never a gate.
- The same applies to T2 (NBA full-game spreads): evidence for fixing the NBA alternate-spread
  distribution, not for withholding a market.

## Improvement backlog (ranked by expected value × confidence)

Evidence from 11-15 / 11-16 unless noted.

| # | improvement | evidence | owner | next step |
|---|---|---|---|---|
| I-1 | **Tail calibration, per line:** shrink the model's probability toward the book's where the book's fair is far from 0.5 (the longshot overconfidence). A per-line fix, never a band gate (corrected 10:50 AM, see T1). | 21-68 at hit ≈ fair below 0.40; Brier worse than the book both days; tail lines 3-26 | **No open lane.** The flag rule `liveRowFreshEdge` came from #781 (`3c38ef4c4`); lane `rail-callouts-sim-vs-book` closed 11-14. The calibration likely belongs to the engines' live probability. | New lane + user decision; T1 tonight is the out-of-sample evidence |
| I-2 | **De-duplicate the board query.** `ranked_all` (6,295 rows) is sent again as `board_contract.cards` (the same 6,295), and `top_opportunities` (4,500) and `top_live_opportunities` (2,176) are subsets. ~26 MB unique in an 80 MB response. | 7:48 PM 11-16 `query.json`: 23.9 + 23.1 + 21.4 + 11.9 MB. Query 3-78 s, 45-83 MB; web workers recycled every 5-15 requests | unowned: `blueprints/intelligence.py` is claimed by `nba-live-props-midnight`, the page by `dh-state-aware-pairing` (09-25) | Proposed as its own session (needs loans from both lanes) |
| I-3 | **NBA slow-sport cadence** | 70 dark NBA rows at 7:48 PM 11-16; NBA builds p50 58 s; 4 `deferred_slow` | No open lane (local_208683f1 raised the decision) | Decision owed by the user |
| I-4 | **NBA alternate lines stale between alt pulls** | NBA `_alt` priced <= 120 s in 2 of 23 readings 11-16 (#811 refreshes main lines only) | local_1f10ce63 (#811) | Sent; OddsAPI credit cost to be measured by the owner |
| I-5 | **NFL quarter/half lines go stale.** Fetched every 10 min; the overlay keeps lines <= 5 min | 52% of MNF with no fresh NFL segment line | local_78b841a1 (diagnosis on main `6ff29d9c4`) | Owner's; next NFL is TNF 11-19 |
| I-6 | **NFL live totals/spreads never price** (the #780 width gate); the uninformative band refuses whole games | MNF: 0 priced lines until Q3; first flag at 9:46 PM | NFL live-engine lanes (#780) | Known; the backlog records the cost |
| I-7 | **#816 level vs a night that flips** | Calibrated NCAAB full totals 23-40 on 11-16 | local_1f10ce63 | Sent; its 7-day grade |
| I-8 | **Under flag beside an "ours" above the line** | 8 of 13 at 7:21 PM 11-16 | local_1f10ce63 | Told; its call |
| I-9 | **A priced live line missing from the rail:** the MNF moneyline | Per local_208683f1 from `refresh-worker.log`: `LIVE_GAMELINE_BUILD nfl` priceable 1 only from 03:19:44Z to 03:27:20Z (0 before and after), so at the 03:23:01Z read the line was priceable but the rail had no NFL moneyline. The overlay's `refused=` counts are aggregates and cannot name it. | **No open lane** | A one-build `select_shortlist` replay at ~03:23Z (grid snapshot likely gone). Going forward, each reading compares join-priceable lines with rail rows carrying a model probability, per sport. |
| I-10 | **WNCAAB in-play coverage is thin** | 10 in-play grid rows for 7 live games at 5:41 PM 11-16 | local_1f10ce63 (#810 college pulls) | Measure books per game today |
| I-11 | **The monitor's own footprint** | A full page plus query = 117 MB a reading | this lane | Full page only every 4th reading (done 11-16) |
