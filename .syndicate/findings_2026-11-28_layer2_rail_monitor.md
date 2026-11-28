# Layer 2 Games Rail monitor — Sat 11-28 (day 14)

Lane `layer2-rail-monitor`, session d58574cb. Lean mode: the Windows task SyndicateRailWatch reads every 20 min; the
nightly close writes the DAILY SUMMARY here.

## User decisions, 10:00 AM CST 11-28

Answering the three open decisions from the 11-27 close, typed in session d58574cb:

- **(a2) the carried card's rows and flags:** "1: Yes".
- **(b) NCAAB quotes filed by the Central tip day:** "2: filed by central tip time".
- **Close lane `nhl-live-join-stl-alias` and todo #860:** "3: yes if completed". Completed (tests, the 11-24 window
  load BC-069, the 11-25 live reading 2 of 2). **CLOSED 10:10 AM CST**; #860 archived to `todo_closed.md`.

## (b) measured before building: tip-day filing alone would starve the late games after midnight

Read-only, nice 19 (`C:\tmp\railmon\ncaab_shard_1128.sh`, `ncaab_shard_replay_1128.py`, output
`ncaab_shard_replay_1128.txt`). The two NCAAB games live across the 11-27 -> 11-28 roll were Creighton @ Gonzaga
and Texas Tech @ San Diego State.

**Where their quotes landed after midnight** (rows captured per 10 min, by shard file):

| UTC | 11-27 file (tip day) | 11-28 file | 11-29 file |
|---|---|---|---|
| 05:50Z | 382 | 0 | 0 |
| 06:00Z | 424 | 98 | 0 |
| 06:10Z | 430 | 0 | 96 |
| 06:20Z | 414 | 76 | 0 |
| 06:30Z | 403 | 0 | 0 |
| 06:40Z | 257 | 0 | 0 |
| 06:50Z | 139 | 74 | 0 |

**Which files were priced** (`LIVE_GAMELINE_BUILD sport=ncaab`, refresh-worker):

- 11-27: 15 builds in 05:50Z, then **1 build at 06:00Z and none after**.
- 11-28: 7-8 builds every 10 min from 06:00Z, index 2 (the two late games). Written 0-29 rows per 10 min (05:50Z on
  11-27: 101).

**Why.** The book-grid tick builds today, rebuilds yesterday ONCE after the roll, and builds forward dates
(`scripts/run_refresh_worker.py` ~7382-7389; a price-on-pull pass is today only). So after midnight:

- the tip-day file, which gets the #792 in-play pull's 60 s quotes (403-430 rows per 10 min), is never priced;
- the only priced file is today's, which gets just the shared sweep's copies (74-98 rows every 10-20 min). Its quotes
  age past the pricing ceiling between sweeps, so written falls to 0-29.

**So filing by the tip day alone is the wrong fix.** It would move those 74-98 rows into the tip-day file too, and
today's builds would have no quotes at all for the late games. The capture half already files by the tip day (the
#792 lane, `college-quote-capture-midnight`, found the same: quotes flowing, the prior date's join priced 0).

**What the files hold** (rows whose Central tip day is not the file's date):

| file | rows | off-day pregame | off-day in-play |
|---|---|---|---|
| 11-27 | 151,601 | 12,830 (62 games of 11-28) | 981 (11-25 / 11-26 games) |
| 11-28 | 24,209 | 8,561 | 604 (50 games of 11-27, 2 of 11-26) |
| 11-29 | 8,372 | 8,264 | 108 (the 2 late 11-27 games) |

Before midnight, in-play rows filed off their day are 0.5-0.8% of in-play rows. The cost is after midnight.

**The fix that would price them** has two parts. First, keep building the previous date's grid and in-play overlay
while one of its games is still live. Then file the sweep copies by the tip day. Both are betting changes (the
carryover board prices rows it does not price today), so 12-08 at the earliest, default-off on main. The cost is
unmeasured: the 11-27 file is 72 MB / 151,601 rows, and the worker rebuilds yesterday only once because a pivot that
size is expensive. Put to the user 11-28 ~10:15 AM CST.

## (a2) design: rows come from the live-rail read, not the combined board

- After midnight the late games' rows are in TODAY's in-play overlay (the 11-28 builds above, index 2).
- `/api/board/live-rail` already returns every live game row of a date's overlay, and the page polls it every ~15 s.
  The page then drops the late games' rows, because the board shows no row for them (#779's lower date bound, on
  purpose).
- So the carried card can take its rows from that poll, plus `/api/board/live-rail?date=<the chip's own date>` if the
  previous date's overlay is ever built after midnight. It runs them through the rail's own row and flag code.
- No change to `pipeline/intelligence_state.py` or the combined board read. Display only, not a betting change: the
  rows never enter the shortlist or the plan.
- Files: `syndicate/templates/intelligence.html` (claimed by `surface-consistency-oversight` and
  `ncaab-total-overprojection`) and a JS test. Loan put to the user 11-28 ~10:15 AM CST.
