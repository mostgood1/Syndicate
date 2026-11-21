# 2026-11-21: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

Slate day 11-21 (the slate day rolls at 5 AM CST). Lean mode: the Claude-free Windows task `SyndicateRailWatch` takes the readings into `C:\tmp\railmon\dash\rows_2026-11-21.jsonl` and the Rail Watch page. This file holds the owned readings and the nightly close's summary.

## R-F #850 exploratory: the refresh-worker parent's morning floor, 9:04 AM CST 11-21 (read-only)

Asked by §3 of `findings_2026-11-18_board_split_memory_guard.md`: if the 11-21 ~9 AM floor is at least 0.5 GB above 11-20's 1,610 MB, the parent ratchet is a multi-day trend.

- **Parent:** pid 1011283 (`/home/amyn/.venvs/syndicate/bin/python scripts/run_refresh_worker.py`, ppid 1011198), read 15:04:25Z.
  - etimes 165,839 s (46.1 h). This is the same parent since the #850 load (11-19 17:00:09Z); it has not restarted.
- **RSS 2,263,028 KiB = 2,210 MiB** on one `ps` sample.
  - The owner's reading 3 minutes earlier (local_438df6f6, `e25b3bade`, §10) was p50 2,166 MB over n 40.
- **+600 MB on 11-20's 1,610 MB (+556 on the owner's p50): the trend IS multi-day.**
  - The floor went 785 MB (11-19 11:23 AM), then 1,610 (11-20 9:28 AM), then 2,166-2,210 (11-21 9 AM).
- **Not restarted.** The owner's 9 AM task had its condition met (≥ 2,110 MB), but its gate stopped the restart: a TERM would load 71 runtime files from 268 commits since `38c3a6905`. That is the user's decision, and it is tracked in the owner's §10. This reading changed nothing on the fleet.
- **`p7count.py 2026-11-19T17:00:09`** (the whole span since the load):
  - `MEMORY_GUARD_ABORT` 93 in all:
    - **88 at #850 P1's stage `pre_source_state_fingerprint`**;
    - post_build_overview 3, build_candidate_pool_start 1, post_pull_hot_artifacts 1.
  - `BOARD_PROCESS_EXITED` 13, every one rc 75. `RECYCLE_EXIT` 12, all `heavy_build_refused`; 7 of them were since 05Z today (05:47, 06:46, 10:09, 11:10, 13:06, 13:52, 14:36Z). `Fatal Python error` 0.
  - `POST_BUILD_CHECK`: `held=transient_jobs` 51, `min_uptime` 1. `BOARD_PROCESS_RECYCLE` reason `post_build_headroom` fired once (time not read).
  - `BOARD_BUILD_TIMING` builds 517; the longest gaps were 1,526 s (15:55Z 11-20), 1,079 s and 1,062 s; 5 were over 900 s.
- **New: the refusals now run all night**, as §3 predicted for the second or third evening.
  - P1-stage refusals on 11-21, 06-15Z (12-9 AM CST): 5, 2, 8, 5, 3, 5, 8, 8, 3 an hour, **47 in all**.
  - The same hours on 11-20 had **1** (13Z).
- **What it costs the board in quiet hours** (`p2_boardpub.py`, 05-15Z, 11 PM-9 AM CST):

  | | publications | median gap | max gap | gaps > 600 s | gaps > 1,800 s |
  |---|---|---|---|---|---|
  | 11-21 | 103 | 302 s | 1,079 s | 8 | 0 |
  | 11-20 | 136 | 244 s | 798 s | 1 | 0 |

  - That is 24% fewer publications overnight, and no gap reached 30 min. Few games are live in those hours, so the evening is where this costs money.
- **Expectation for the 11-21 evening** (written before it; not a pass/fail): the third evening starts with the parent ~0.55-0.6 GB higher than 11-20's did. Expect more P1-stage refusals in 5-10 PM than 11-20's 13.
- **VOID, 12:19 PM CST: the expectation above no longer holds, because the parent was reset.**
  - The kalshi lane restarted refresh-worker at 18:14:49Z (12:14 PM CST). Its new parent is pid 2397127: etimes 255 s and 1,109,804 KiB (1,084 MiB) at 18:19:12Z. The fleet checkout is at `b07e80882`.
  - The owner's 4 AM CST resets for Sunday and Monday are re-pinned to that SHA (`cd849619d`).
  - So the 11-21 evening starts from a fresh parent, as 11-19's did, not a third-day one. Compare its 9 PM RSS with 11-19's 1.55-1.60 GB, not with the ratchet.
- Instrument: `p2_boardpub.py` lost a leftover debug print, a hard-coded 11-21 01:1x Z line dump. It printed after the numbers and did not change them. The backup in `scripts/rail_monitor/` is updated.

## Fleet-watcher flag: NCAAF games with no live model, R7-R9 (12:03-12:43 PM CST)

local_379fd729 flagged three games. Wisconsin @ Purdue was dark at R7, R8 and R9, Wofford @ Ole Miss at R8 and R9, East Carolina @ Army at R8 only. **Verdict: all three were NCAAF re-sim refusals for `key_player_out`** (#814's deliberate gate, the same kind as 11-20's BKN Nolan Traore). It was not a join gap, and not the 12:14 PM refresh-worker TERM.

- **Per game, from the `ncaaf_live_lens.json` keyvalue** (`generatedAt` 12:58:22 PM):
  - **Wisconsin @ Purdue:** `liveResimRefusal key_player_out`, detail `PUR:Evans Chuba:replaced`, source pbp, since 17:40:55Z (11:40 AM). That is before R7 and before the TERM.
  - **Wofford @ Ole Miss:** `playersOut` holds WOF Ethan Drumm, `replaced`, key, since 18:08:34Z (12:08 PM).
  - **East Carolina @ Army:** `playersOut` is now empty.
- **Refresh-worker's `NCAAF_LIVE_RESIM` summary:** `key_player_out` was 1 from 17:43Z and 2 from 18:12Z. It was 3 at 18:21Z and back to 2 at 18:27Z: Army's 6-minute flap, which is why only R8 caught it.
  - At 18:58Z: 16 games live, 14 re-simmed, refusals `key_player_out` 2, `no_live_state` 12 (12 all day, games with no ESPN live state), `game_not_in_progress` 42.
- **LEAD (not a defect):** the pbp `replaced` detection can be transient. Army's cleared in about 6 minutes, and while it held the game had no model. Count the flaps at the nightly close before calling it noise or cost.
- **Second flag, 1:58 PM.** Syracuse @ Boston College is `key_player_out` (`SYR:Steve Angeli:replaced`, since 19:09:13Z). Mercyhurst @ Western Illinois is **I-29**: the NCAAB snapshot has the teams REVERSED (home Mercyhurst), at every reading from R9 to R12. The fix is change G on 11-24.
- **Ticker change (the fleet-watcher's ask; Claude-free dashboard files only, no fleet change).** From R13 (2:03 PM) each row carries `live_games_no_model_reasons` {game: reason} and `live_games_no_model_detail`.
  - `p29_orient.py` now reads every per-game snapshot: ncaab, wncaab, nba, ncaaf and nhl lens, nfl, soccer lens. It adds `reason`/`detail` and `priced`/`priced_with_model`. The page's dark list now uses the row's rule, priced full-game rows only.
  - The first row: 13 no-model games. 5 NCAAF `key_player_out`, 1 `orientation_reversed`, 7 soccer.
  - **The soccer live lens was 21 min old at 2:06 PM** (generated 1:45 PM; MLS and Eredivisie only), while 7 European games were live. The 2:23 reading tells whether it refreshes.
- How to read this next time: NCAAF prints no `_LIVE_RESIM_TICK`. Use `ncaaf_events.py` (event names per role log) and `ncaaf_resim_peek.py <team> ...` (the per-game lens), both in `scripts/rail_monitor/`. The runbook says so.
