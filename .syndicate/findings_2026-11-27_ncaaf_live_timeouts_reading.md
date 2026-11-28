# Findings 2026-11-27: the live NCAAF timeouts reading (todo #859, item I of the 12-08 window batch)

Session 309b272a, started by session 91b0c989 (lane `window-1208-batch`) to take the reading that item I of
`.syndicate/window_2026-12-08_batch.md` needs. Read-only: ESPN's public site API plus the fleet's
`GET /ncaaf/api/cards` (no token). No fleet env edit, ff, restart or code push. Every job ran at Idle priority.
Times are CST unless marked Z.

## What was read

- **ESPN:** the college-football site scoreboard
  (`site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300`), the URL
  `scripts/poll_ncaaf_live_state.py` uses (it adds `dates=`). Every 30 s, 5:53 PM to 10:08 PM CST on Fri 11-27
  (Black Friday). One JSON line per in-progress game per read: `situation.homeTimeouts` / `awayTimeouts`, their
  types, period, clock, and (from 6:58 PM) `situation.lastPlay`.
- **The fleet:** `http://127.0.0.1:10000/ncaaf/api/cards` every 120 s, the `live_state.espn_situation` block of each
  in-progress card (`ncaaf/live_game_state.py` copies the poller's raw `situation` there).
- **Ground truth:** ESPN's own play-by-play (`.../college-football/summary?event=<id>`), fetched after the finals.
- **Scripts and raw reads:** `C:/tmp/ncaaf859to/` (`poll_sb2.py`, `poll_fleet.py`, `cfb_grade.py`,
  `second_half.py`, `lastplay_concord.py`, `final_tally.sh`; `sb_reads_1127.jsonl`, `sb2_reads_1127.jsonl`,
  `fleet_reads_1127.jsonl`; play-by-play in `pbp_final/`).

## Result 1: the keys are there (the batch's condition)

| check | reads |
|---|---|
| ESPN live reads, 7 games | **1227** |
| both keys present | **1227 of 1227** |
| ints in 0..3 | **1227 of 1227** |
| fleet live rows (`espn_situation`), 6 games | **296 of 296** carry both as ints 0..3 (2 fetches timed out, 6:48 / 6:51 PM) |

Games: FLA @ FSU, TEM @ MEM, NDSU @ SJSU, AFA @ UNM, MINN @ WIS, TEX @ TA&M, WVU @ UTAH (in Q3 at the cut).
The fleet's rows carry ESPN's numbers. 269 fleet rows have an ESPN read at the same period and game clock, and 268
of them carry the same pair; 1 differs. `endgame.timeouts_fed` does not exist yet: it appears only once item I
loads.

## Result 2: the SECOND-HALF values are wrong. ESPN's college counter does not reset at halftime

**The finding.** ESPN's college `situation` timeouts read **3 minus every timeout the team has used in
regulation, floored at 0**. The counter does NOT reset to 3 at halftime. College rules give each team 3 a half,
and unused first-half timeouts do not carry over. The NFL feed resets: the MNF read
(`findings_2026-11-16_nfl_live_timeouts.md`) showed (3, 3) at the half. In the first half the college values are
right.

**Halftime, seen directly (3 of 3 games watched across the break):**
- MINN @ WIS: (1, 0) at halftime, the whole of Q3, and into Q4. Wisconsin's first second-half timeout (Q4 4:23)
  took it 1 -> 0, not 3 -> 2.
- TEX @ TA&M: (0, 2) at halftime. Texas's first second-half timeout (Q3 9:09) took it 2 -> 1, not 3 -> 2. A&M
  read 0 for the whole second half, and it used 3 there.
- WVU @ UTAH: (3, 2) at halftime and at Q3 15:00, not (3, 3).

**Graded against the play-by-play.** Two models are scored on every read: `reset` (3 a half, the rule and what the
end game assumes) and `carry` (one regulation pool of 3, floored at 0).

| model | match | boundary (within 180 s of a timeout play) | halftime | mismatch |
|---|---|---|---|---|
| `carry`, the 6 games with a usable play-by-play (1164 reads) | 1026 | 9 | 129 | **0** |
| `reset`, same 1164 reads | 526 | 106 | 129 | **403** |

NDSU @ SJSU is left out: its play-by-play charges 21 team timeouts, which is impossible. On it, both models read
24 match / 20 mismatch.

**How wrong, in the second half** (true value = 3 minus that half's timeouts, from the play-by-play):
- 505 second-half reads, 6 games: **1** equals the true count. 0 read high.
- Q4: **541 of 606** team counts read LOW. **170** read 0 for a team that still had 1 to 3 left.

**The scoreboard is self-consistent.** Each timeout moves it once:
- 14 of 15 one-step drops came in the same read as a "Timeout <team>" `lastPlay`. The one exception: Minnesota,
  Q2 14:55, right after an extra point.
- No read ever went up inside a half, and none went below 0.

## The play-by-play needs two corrections before it can grade timeouts (college only)

1. **The two-minute timeout.** NCAA football has had an official timeout at 2:00 of each half since 2024. ESPN
   writes it as "Timeout <team>, clock 02:00" (or 1:58), and the scoreboard never charges it. Without skipping
   the first such play at 1:45-2:00 of Q2 and Q4, FLA @ FSU and AFA @ UNM look as if they reset. With the skip,
   all six games read `carry`.
2. **Team-labelled stoppages that are not charged.**
   - NDSU @ SJSU shows 21 team timeouts, and timeout `lastPlay` text at 1:59, 1:49 and 1:47 with no count change.
   - AFA @ UNM lists one Q4 timeout twice.
   - Dedupe the plays, and treat a half with more than 3 timeouts as an unusable play-by-play.

## What it means for item I (#859, the user's call)

- **`ncaaf/live_resim.py` feeds these values in every period.** `_timeouts_left` (line 423) maps them to
  `NcaafLiveGameState.home_timeouts` / `away_timeouts`, then to `initial_timeouts_*` (lines 1004-1007), with no
  halftime guard.
- **Loaded as built, the end game would see too few Q4 timeouts.** Often it would see 0 for a team that has 3. That
  is the input the real-timeouts hold-out (CFBD, true per-half counts) did NOT test. With the feed absent, the engine
  starts the half at 3 (`None`, "never a guess"), which is closer to the truth than a carried 0.
- **A fix is code, for a later window. It is the lane owner's design call:**
  - (a) feed `None` in periods 3-4, so the engine uses its default 3;
  - (b) keep each game's halftime value and pass `3 - (halftime value - current)` while the current value is
    above 0, else `None`.
  - A floored 0 loses the count, so (b) still needs (a)'s fallback.
- **The batch's presence condition is met regardless.** Item I still needs the user's own 12-07 yes. That yes
  should be asked with this caveat in front of the user.

Not checked: whether CFBD's own timeouts fields (the hold-out's input) carry the same artefact. The hold-out
reported real per-half timeouts, so it should not, but it was not re-read here.
