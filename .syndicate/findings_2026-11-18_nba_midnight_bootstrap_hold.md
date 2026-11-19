# Findings 2026-11-18: the 1,800 s ~12:01 AM CST NBA/college holds of the live odds lane

Lane `nba-midnight-bootstrap-hold` (session 11c3b7a0). Requested by session local_68526c0a on the user's "start a
session for the 1,800 s midnight NBA runs"; lead from lane `soccer-pregame-odds-lane` (todo `#840`).
Substrate: **fleet** (`~/syndicate-prod/data`, `~/syndicate-prod/logs`), read-only at `nice 19`, 2026-11-18
12:30-1:30 PM CST. The fix was replayed on a copy of the fleet's history file with the network stubbed.

## 1. Answer

The hung call is the **NBA props job's games-history fetch**. On a new date, the first NBA props run that sees that
date's OddsAPI events finds no `predictions_<D>.csv`, so it runs the source bootstrap. The bootstrap sees yesterday's
finals missing from `raw/games_nba_api.csv` (`GAMES_HISTORY_BEHIND_SCHEDULE`) and runs `cli fetch --years 1` with a
**2,700 s** subprocess timeout. That is longer than the live odds lane's **1,800 s** step timeout.

The fetch is slow because of a **game-id format mismatch**:
- The history is read back with pandas' default dtypes, so `0022600001` returns as `22600001`.
- LeagueGameLog returns `0022600001`. The two never compare equal.
- So the quarter merge matched no game. Every fetch walked BoxScoreSummaryV2 for **every game of the season**, 196 by
  11-15. Each call is 30 s × up to 4 attempts when stats.nba.com stalls.

The same mismatch kept the save from replacing the season, so **every completed fetch appended another copy of it**.

## 2. The launcher (H2: CONFIRMED)

`[live_refresh_loop] ODDS_SWEEP_LAUNCHED date=<D> sports=nba,ncaab,wncaab` fires right after the 00:00 CST roll.
This is the live loop's pregame sweep for the new date, run with `--force-refresh --force-refresh-sports nba,wnba`.
Observed 11-15 06:00:44Z, 11-16 06:02:37Z, 11-17 06:01:33Z and 11-18 06:01:15Z. Older log files have rotated away;
the manifests carry the same command for every night.

## 3. Every night, 11-09..11-18 (H1, H3: CONFIRMED)

These are the live-odds-worker's ~00:01 CST pregame `nba,ncaab,wncaab` runs. Each fetch row comes from that night's
NBA props log.

| night (CST) | run stamp (Z) | run length | bootstrap fetch at midnight | outcome |
|---|---|---|---|---|
| 11-09 | 060125 | 62 s | no | ok |
| 11-10 | 060208 | 178 s | no | ok |
| 11-11 | 060120 | 160 s | no (fetch completed 11-10 22:07Z) | ok |
| **11-12** | 060200 | **1,801 s** | yes (behind 11-10, 11-11; 15 finals) | killed in the fetch |
| 11-13 | 060232 | 197 s | no (predictions built 11-12 23:49Z) | ok |
| **11-14** | 060144 | **1,801 s** | yes (behind 11-12, 11-13; 13 finals) | killed in the fetch |
| **11-15** | 060044 | **1,800 s** | yes (behind 11-12..11-14; 18 finals) | killed in the fetch |
| 11-16 | 060237 | 42 s | no (predictions built by refresh-worker 05:24Z) | ok |
| 11-17 | 060133 | 125 s | no (cooldown: refresh-worker's 05:24Z fetch) | ok |
| **11-18** | 060115 | **1,765 s** | yes (behind 11-16, 11-17; 11 finals) | killed in the fetch |
| 11-19 (fix ON) | 060116 | **760 s** | yes (behind 11-16..11-18; 25 finals) | ok: the bounded fetch took 630 s; see §10 |

- **4 of 10 nights** ran into the timeout, not 3: the soccer lane's list missed 11-12. All 4 fetched at midnight, and
  none of the 6 other nights did.
- Every night's run has rc 1 anyway, because `wncaab_odds_snapshot` reports ok false on every run (a lead, §8).
- On 11-18 the NBA child sat in the fetch from 06:01:31Z to its kill at 06:30:40Z: 81 BoxScoreSummaryV2 attempts,
  54 gaps over 25 s (timeouts). On the first launch after a kill the 6 h cooldown skips the fetch, so predictions
  are built from the stale history (11-18: 06:33Z; history to 11-15).

**All 18 fetches 10-29..11-18, every lane:**
- 11 completed, in 237-1,743 s. The fast ones had 0-11 timeouts; the 1,487-1,743 s ones had 34-42.
- 7 were killed, after 1,775 s or more.
  - Five were the live lane's midnight run: 11-05 (`odds_refresh_20261105_060146`, live-odds-worker,
    `nba,ncaab,wncaab`, `TimeoutExpired`, a fifth instance before the table's window), 11-12, 11-14, 11-15 and 11-18.
  - Two started at 04:41Z 11-09 and 05:24Z 11-17. Their run's lane was not read.
- Fetch time scales with the season's game count and with stats.nba.com's stall rate.

## 4. The cost

- **Live odds lane:** 4 holds, ~2.0 h in total, at 00:01-00:31 CST.
  - Refused sweeps with these holders: 2 (11-15 06:26:44Z and 11-18 06:26:09Z, the 5-sport pregame cadence sweep);
    0 on 11-12 and 11-14 (from the soccer lane's extract, since those logs rotated).
  - The low count is because the pregame cadence is 1,500-1,800 s, and live games ran on their own lanes. On 11-18,
    23 `NBA_LIVE_AUTORUN_LAUNCHED` (1 NBA game live) and 23 `NCAAB_LIVE_AUTORUN_LAUNCHED` (1-2 live) went out on
    `live-odds-worker-nba-live` / `-ncaab-live` during the hold.
- **The run itself:** before `2ae0c646a`, the `TimeoutExpired` escaped, so NCAAB and WNCAAB pregame for the new date
  never ran in it, and NBA's result was dropped.
- **The NBA history never caught up on those nights.** 11-18's predictions were built on a history ending 11-15
  (11 finals missing). It still ends 11-15 as of 1 PM CST.
- **The history is duplicated** (the larger harm). The fleet's `raw/games_nba_api.csv` holds 1,563 rows for 196
  current-season games, with up to 16 copies of a game: 212 ids appear once, the rest 2-16 times.
  - `build_features` and `predict-date` replay each copy as a game: Elo updates, rest days, form.
  - Pre-game Elo at each team's latest game, duplicated minus de-duplicated: **mean |Δ| 119, max 293** (Golden
    State +293, Charlotte −226), over all 30 teams.
  - `predict-date` builds `elo_diff` from that replay. This lane did NOT trace which live bets read NBA
    `predictions_<D>.csv`.

## 5. H4 (the `2ae0c646a` deadline alone): NOT acceptable

With `SYNDICATE_ODDS_LANE_STEP_DEADLINE` on, a timeout is a failed step and NCAAB/WNCAAB then run. But:
- the bootstrap fetch still outlives the 1,800 s step, so the lane is still held ~30 min;
- NBA's run is still lost, and the history still does not catch up.

The deadline also does nothing for the duplication. **Tonight (11-19 00:01 CST) was not yet readable**; §7 gives its
prediction.

## 6. The fix

On main, behind `SYNDICATE_NBA_HISTORY_FETCH_BOUNDED`. **Absent = OFF**, because it is a betting change outside a
window.

In `syndicate/features/nba/source_cli/scrape_nba_api.py` `fetch_games_nba_api`, with the switch on:
- game ids are compared as 10-digit strings (`normalize_game_ids`), and the stored history is reduced to one row per
  game before the quarter merge. The row with quarters is preferred;
- the quarter walk asks only for games with no quarters in any copy, newest first. It stops at
  `SYNDICATE_NBA_LINESCORE_DEADLINE_SECONDS` (default 600) and leaves the rest for the next fetch;
- the save keeps one row per game id. Rows without a numeric id are never merged;
- `[fetch] LINESCORE_WALK bounded=1 ...` and `[fetch] HISTORY_SAVE bounded=1 ...` go to the props log on every fetch.

In `scripts/refresh_nba_oddsapi_props.py`, `_games_history_fetch_timeout_seconds`:
- the bootstrap's fetch timeout is 900 s (`SYNDICATE_NBA_HISTORY_FETCH_TIMEOUT_SECONDS`) instead of 2,700 s,
  logged as `GAMES_HISTORY_FETCH_BOUNDED`;
- a stalled stats.nba.com fails this one call, and the bootstrap carries on with the history it has.

**Why one switch, not two.** Bounding the walk without the id fix makes every fetch complete. Each completed fetch
appends one more copy of the season, so the duplication would grow faster. The id fix is also what de-duplicates.

**Tests:** `tests/test_nba_history_fetch_deadline.py`, 10 cases:
- off != on through the real `fetch_games_nba_api` (calls and rows) and through `_ensure_source_game_inputs` (the
  fetch call's timeout);
- the deadline cuts the walk and the new final is still written;
- id normalization and switch parsing.

Related suites: 84 passed, 1 skipped (`test_nba_history_refresh`, `test_nba_history_seed_native`,
`test_nba_source_cli_reachability`, `test_nba_refresh_runner`, `test_basketball_games_history_freshness`, and
others).

**Replay** on a copy of the fleet's history (11-18), with LeagueGameLog stubbed as the copy's 196 distinct games and
BoxScoreSummaryV2 counting calls:

| | BoxScoreSummaryV2 calls | season rows written | ids | games with quarters |
|---|---|---|---|---|
| off | 196 (every game) | 1,759 (+196, one more copy) | 196 | 502 rows |
| on | 31 (games with no quarters) | 196 | 196 | 165 games |

## 7. Pre-registered predictions

**Tonight, 11-19 ~00:01 CST, on `2ae0c646a` only (switch off).** If the run fetches (`predictions_2026-11-19.csv`
absent at that time and no fetch since 12:01Z 11-18):
- the NBA step ends `status=timeout` at about 1,800 s as a FAILED step, not an escape;
- `ncaab_odds_history_snapshot` and `wncaab_odds_snapshot` then run, and the run ends at about 1,800-1,900 s;
- the history's newest game stays 2026-11-15.

If refresh-worker's evening look-ahead fetched first, the midnight run does not fetch and finishes in under 300 s.

**After the switch is on** (first 7 nights, fleet logs and manifests):
- **P1:** each bootstrap fetch logs `GAMES_HISTORY_FETCH_BOUNDED timeout_s=900` and `LINESCORE_WALK bounded=1` with
  `to_fetch <= 60` (baseline: the whole season, 196-210).
- **P2:** every fetch ends within 900 s (baseline 7 of 18 ran past 1,775 s).
- **P3:** 0 midnight `nba,ncaab,wncaab` runs over 1,100 s, and 0 NBA step timeouts (baseline 4 of 10 at 1,765 s or
  more).
- **P4:** after the first completed fetch, the season's rows equal its unique game ids (0 duplicates; baseline
  1,563 / 196), and the newest date is the last night with finals. At least 90% of fetches complete (baseline 11 of
  18 = 61%).
- **P5:** the next `build-features` moves each team's latest pre-game Elo by a mean |Δ| of about 119 (the size of
  the correction, not a harm).
- **P6:** 0 added OddsAPI calls (the fetch reads stats.nba.com only).

## 8. Leads (not followed)

- `wncaab_odds_snapshot` reports ok false on every live-odds-worker run 11-09..11-18, so every run's rc is 1.
- The WNBA twin (`scripts/refresh_wnba_oddsapi_props.py` and its source CLI) has the same bootstrap shape. Its id
  handling was not checked; WNBA is off-season.
- The money impact of the duplicated history: **sized** by session 9383ef18 in
  `.syndicate/findings_2026-11-18_nba_elo_money_impact.md` (main `20c9f9f45`).

## 9. Load

- **Classification: `betting change: yes`.** The NBA game model's Elo, rest and form inputs change materially once
  the history is de-duplicated, and the live lane is freed at midnight.
- Under the window rule (effective 18:00Z 11-18) it lands default-off.
- **The load is a fleet ff to the SHA plus a turn-on.** Either:
  - a default flip on main inside the window (absent = on) and an ff (child scripts, no restart); or
  - the env key in `local_production.env` with a drained `down`/`up`.
- The next window opens 2026-11-24 08:00Z (2:00 AM CST). Whether to load there, or outside it as an exception, is
  the user's call.

**LOADED 2026-11-18 21:02:51Z (3:02 PM CST), on the user's "Load it now".** I had recommended the 11-24 window.
- The default was flipped to absent = ON in `a3104a5b6`, and the fleet was ff'd `db6a395ed` -> `a3104a5b6`, with no
  restart.
- BC-052 is a betting change OUTSIDE a window, by user override. It is not a revert, a risk reduction or a money-path
  fix.
- A fleet child reads `history_fetch_bounded()` = True, and no env layer names the key.
- The §7 switch-off prediction for tonight can no longer be read. 11-19 is the first night ON the fix, read against
  P1-P4.
- Entry: `.syndicate/deploys.md` "2026-11-18 21:02:51Z".

## 10. First night on the fix (2026-11-19): P1-P4 MET

Read at 12:45 AM CST (06:45:42Z) by the scheduled task `nba-history-fix-first-night-1119`, which ran
`C:\tmp\mn1800\mn1800_reading_1119.py` (fleet, read-only, nice 19). This session re-read the output
(`C:\tmp\mn1800\reading_1119.txt`) at 06:56Z.

Before the run, the script was dry-run on the 11-18 night. It reproduced that night's §3/§4 numbers: 1,765 s, the NBA
step timeout, 1,563 / 196, and 1 refusal behind the run.

**Code and switch:** fleet head `d78a448c4` (contains `a3104a5b6`). `history_fetch_bounded()` = True, and 0 of 5 env
layers name the key.

**The fetch** was the first after the load. It came from the 00:01 CST live-lane run; nothing fetched earlier that
evening. From the props log:
- 06:01:36Z: `GAMES_HISTORY_BEHIND_SCHEDULE` (11-16..11-18, 25 finals), then `GAMES_HISTORY_FETCH_BOUNDED timeout_s=900`.
- 06:12:05Z: `LINESCORE_WALK bounded=1 to_fetch=56 attempted=33 success=33 failures=0 skipped_deadline=23
  deadline_hit=1 elapsed_s=627.6`.
- 06:12:05Z: `HISTORY_SAVE bounded=1 history_rows_read=13532 rows_written=12190 fetched_games=221`.
- The fetch took **630 s**. `build-features` followed, and `predictions_2026-11-19.csv` was written at 06:12:26Z.

| prediction | reading | baseline | verdict |
|---|---|---|---|
| P1 | `timeout_s=900`; `to_fetch` 56 (<= 60) | 2,700 s; the whole season, 196-210 games | MET |
| P2 | 630 s; 0 of 1 fetches timed out | 7 of 18 past 1,775 s | MET |
| P3, night 1 of 7 | `odds_refresh_20261119_060116` (live-odds-worker): **760 s**; NBA step 755 s, rc 0, no timeout; 0 sweeps refused behind it | 1,765-1,801 s on fetch nights | MET |
| P4 | 221 season rows / 221 ids (0 duplicates); newest 2026-11-18; 1 of 1 fetches completed | 1,563 / 196, newest 2026-11-15; 61% complete | MET |

- **The walk hit its 600 s deadline.** It left 23 of 56 quarter-less games for the next fetch. That is the designed
  bound, and those games come back newest-first on the next walk.
  - `to_fetch` = 56 sat near P1's bar of 60, because this fetch covered three nights of finals (25), not the usual
    one or two.
- **A fetching night still costs the lane about 760 s,** against under 300 s on nights with no fetch. The ceiling is
  the 900 s cap plus `build-features` and `predict-date`, which stays under the live lane's 1,800 s step timeout.
- **Owed:**
  - P3, and P4's completion rate, over nights 11-20..11-25;
  - P5 (the Elo shift at this `build-features`; the pre-run features file was overwritten, so it needs a recompute
    from the old history, not a before/after read);
  - P6 (0 added OddsAPI calls).
  - Todo `#843` carries them.
