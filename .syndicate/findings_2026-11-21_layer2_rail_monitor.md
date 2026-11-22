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
  - **The soccer live lens was 21 min old at 2:06 PM** (generated 1:45 PM; MLS and Eredivisie only), while 7 European games were live.
    - **LEAD:** `live_lens_loop TICK_COMPLETE` had soccer True every 1-3 min until 19:45:32Z, then **False on every tick to 20:07:47Z (22 min)**. The window spans the Serie A, Ligue 1, Belgian and Eredivisie kickoffs.
    - The lens it then wrote, generated 2:07:45 PM, holds all 11 live games, and their rows carry a model again.
    - So **7 games had no live model for about their first 20 minutes.** Earlier False runs today: 18:08-18:27Z (19 min), 15:56-16:31Z (35 min), 15:25-15:40Z (15 min).
    - Meanwhile `SOCCER_LIVE_AUTORUN_FAILED RefreshLaneBusy` fired 47 times since 15Z.
    - Not diagnosed. Count kickoff-window False runs at the close (`lens_loop_soccer.py <since>`).
  - The helper now also matches soccer-lens spellings ("AJ Auxerre" / "Auxerre") on a word subset. It still misses "PEC Zwolle" / "FC Zwolle", which is labelled `not_in_resim` with the snapshot time.
  - A new refusal reason seen, NCAAB `pbp_score_mismatch` (St. Thomas (MN) @ Milwaukee, "pbp 5-4 official 3-4"): fail-closed, and expected to be transient.
- **Third flag, 2:43 PM: dark rows** went 0 (R11-R13), then 7 (R14), then 5 (R15), with ~70 games live. **Verdict: board cadence, not the soccer lens stall.**
  - All 12 sampled rows carry a model (gap 4.4-44.5 pp) and span NCAAB, NCAAF and soccer.
  - **Every one has no `price_grid_generated_at`.** The probe therefore ages it from the board build: `grid_age_s` 238.7 at R14 and 303.9 at R15, both exactly `board_built_age_s`. Quote ages at pricing were 15-110 s.
  - Those rows are h2h, quarter-ball soccer lines (0.25), and some alt / half lines. The book grid does not re-price them; it ticks every 26 s median (p90 61 s, max 134 s, 230 ticks 19-21Z; `gridcad.py`).
  - So they go dark whenever the board is about 4 min old. This afternoon the board published every 457-890 s (R10-R12) with build walls of 265-548 s. That puts them dark for roughly the back half of each board cycle.
  - R11-R13's 0 were readings that landed early in a cycle. The flag is withheld by design (fail-closed). Its cost is the share of time these rows cannot flag, which is the board cadence lane's number.
  - `dark_rows_detail` (from the 3:03 PM tick) names each row, its grid age and a reason: `board_cadence`, `grid_stale` or `cadence_edge`.
- How to read this next time: NCAAF prints no `_LIVE_RESIM_TICK`. Use `ncaaf_events.py` (event names per role log) and `ncaaf_resim_peek.py <team> ...` (the per-game lens), both in `scripts/rail_monitor/`. The runbook says so.

## Why the soccer live lens stalls at kickoff (diagnosed 6:20-7:10 PM CST, read-only; user "find out why the soccer live lens stalled at kickoff")

Hypothesis written to the lane before the test (`8749da338`). **Verdict: CONFIRMED on all three falsifiers.** The soccer lens is not failing. Its own memory gate skips it, and the soccer live ODDS refresh fills the gate. That refresh runs only while leagues are in play, and at the European kickoffs its runs stack on each other.

- **(1) Every soccer `False` is the gate.**
  - Over 05:00Z to ~00:10Z 11-22 there were 799 soccer lens ticks, each joined to its `live_lens_tick_before_soccer` sample. 662 were True and 137 False.
  - **137 of 137 False ticks carry `LIVE_LENS_TICK_DIAG sport=soccer ok=False reason=low_headroom`. No True tick does, and no other reason appears.**
  - The gate is `live_lens_loop.py:701-731`: `_soccer_live_lens_min_headroom_bytes` defaults to 300 MB, and its own comment says that number is "NOT yet backed by a real production measurement".
- **What the gate reads on the fleet** (`memory_observability.py:115-157`, `353-440`).
  - With `SYNDICATE_LOCAL_MEMORY_LIMIT_MB` set and no cgroup limit, "current" is the RSS of the ROLE's whole process tree: the worker plus every child, summed. The ceiling is 3,072 MB, the role's old Render plan.
  - So the lens refuses whenever live-odds-worker's tree passes 2,772 MB. The log line's `basis: reclaimable_cache` means there is no memory.stat breakdown on this host, not that cache was counted.
- **(2) The worker alone never trips it.** In False ticks the worker's own RSS ran median 1,421 MB, max 1,688 MB. The whole tree ran median 3,122 MB (min 2,753, max 4,630). In True ticks the tree ran median 1,993 MB.
- **(3) The child that differs is the soccer live odds refresh.**
  - That is the `SOCCER_LIVE_AUTORUN` run on lane `live-odds-worker-soccer-live`: `refresh_odds_sources.py --sports soccer --phase live --mode fast`.
  - It was alive in **0.96 of False ticks against 0.28 of True ticks**, at a median 751 MB vs 323 MB when present.
  - The other children barely separate the two: soccer pregame/full 0.89 vs 0.53 (~290 MB either way); re-sim workers 0.80 vs 0.40 (~180 MB).
  - Each run spawns `poll_soccer_live_state.py --league <x>` per in-play league, at 113-511 MB each (epl, championship and la_liga 275-300 MB; serie_a up to 511 MB). That is the same per-league live-state poll the lens itself makes in-process every ~70 s, and it writes the same `live_state_<date>.json` files.
- **Why at kickoff: the runs outlast their own 120 s relaunch interval, then stack.** 206 runs today (204 finished, 2 failed), joined 206 of 206 to their `SOCCER_LIVE_AUTORUN_LAUNCHED in_play=...` line:

  | leagues in play | runs | seconds median / p90 / max | over 120 s | launched while a same-lane run was still alive |
  |---|---|---|---|---|
  | 1 | 31 | 43 / 76 / 142 | 0.03 | 0.00 |
  | 2 | 27 | 80 / 97 / 298 | 0.04 | 0.00 |
  | 3 | 42 | 85 / 125 / 153 | 0.17 | 0.00 |
  | 4 | 21 | 88 / 126 / 256 | 0.19 | 0.00 |
  | 5 | 17 | 226 / 291 / 325 | 0.82 | 0.41 |
  | 6 | 45 | 203 / 338 / 598 | 0.93 | 0.58 |
  | 7 | 23 | 267 / 320 / 470 | 1.00 | 0.87 |

  - **53 of 206 launches started while another run of the same lane was alive.** Up to 3 were alive at once (15:31:56Z), with 5,604 s (93 min) of 2+ alive.
  - The overlapping launches fell in UTC hours 15 (15), 16 (13), 18 (8), 19 (2), 20 (11) and 21 (4). Those are the hours of the lens stalls.
  - Seen in the tree: three runs alive at 16:10:39Z (tree 3,435 MB) and two at 20:21:08Z (2,985 MB).
- **The longer stalls** (consecutive False ticks; CST):
  - 9:26-9:38 AM (11 ticks);
  - 9:57-10:28 AM (24 ticks, the longest);
  - 12:09-12:23 PM (8);
  - 1:46-2:04 PM (14);
  - 2:14-2:25 PM (8).

  Most of the other 37 runs are 1-3 ticks. In all, 137 of 799 ticks (17%) of the day's soccer lens ticks were skipped. Every skipped tick leaves every live soccer game on the last lens, which is how the rail showed 7 games with no live model at 2:06 PM.
- **A contributing defect in the lane guard, found and not fully explained.**
  - The guard does refuse. `REFRESH_LAUNCH_REFUSED reason=lane_busy lane=live-odds-worker-soccer-live` fired at 15:22:05, 15:22:18, 15:22:35 and 15:23:06Z against run `20261121_152002`, and that run's manifest says it ended at 15:25:26Z. Yet the next run launched at 15:23:40Z.
  - `run_refresh_odds_job.py:153` (`_update_state`) writes a finishing run's terminal manifest over the lane's shared `latest` pointer unconditionally. So once two runs overlap, the older one finishing marks the lane free while the newer one is still running. That fits most of the chain at 15:23-15:42Z.
  - It does NOT explain the first overlap (15:23:40Z), nor `20261121_153156` (15:31:56Z), which launched with no same-lane run finishing since the previous launch. Not diagnosed.
- **What this is not:**
  - an exception in the poller: 0 non-gate False. The day's one `LEAGUE_POLL_FAILED` (mls, a 30 s `ReadTimeout` to americansocceranalysis at 4:14 PM CST) is swallowed per league and does not fail a tick;
  - the keyvalue write;
  - the 12:14 PM refresh-worker TERM, which is a different role;
  - the board build.

  MLB and WNBA are skipped by the same gate in the same ticks; out of season, that is harmless. NBA, NHL and NFL lenses are ungated, which is why soccer is the only in-season sport that stalls.
- **Shared pages, measured by the peer lane.** Lane `board-split-memory-guard` reached the same reading independently: `findings_2026-11-18_board_split_memory_guard.md` §14, `2ef5a433b`, pushed a minute before this block, with the verdict "belongs to lane `layer2-rail-monitor`".
  - Its gate count, soccer 135 from 14Z to 00Z, matches this block's 137 from 05Z: the 2 extra are this block's 05:06Z and 05:21Z.
  - It measured what this block had left unread: tree PSS 1,940 MB against RSS 2,379 MB (-18%) at 00:23Z, a quiet moment. So the 4.6 GB peaks are ~3.7-3.9 GB unique, still over the 2,772 MB line.
  - The median False tick may not be. At 3,122 MB RSS, an 18% discount gives ~2,560 MB, under the line. The 18% comes from one quiet reading with a different process mix, so how many of the 137 skips a PSS-based gate would have passed is not measured.
  - The host has 15,746 MB with 5,348 MB available at 00:23Z, so 3,072 is a declared budget that nothing else enforces.
- **Fix options** (none taken; all are outside this lane, and any that changes when the lens runs changes which live soccer bets are placed, so it is a betting change for a window):
  - (a) stop the soccer live odds runs from stacking: the guard defect above, plus the next run starting only after the last has finished;
  - (b) drop the duplicate per-league live-state poll from the odds run, since the lens already writes those files;
  - (c) re-measure the 300 MB soccer floor, which its comment says was never measured;
  - (d) the 3,072 MB ceiling, an env change.
- Instruments, read-only, in `C:\tmp\railmon\` and `scripts/rail_monitor/`:
  - `soccer_gate_test.py <since>` (the three falsifiers);
  - `soccer_run_vs_leagues.py <date>` (the table);
  - `run_manifests.py <date> soccer live <lane>` (overlaps, from the Redis manifests);
  - `tree_at.py <utc>` (the role tree at a tick);
  - `soccer_fast_runs.py`, `logwin.py`, `apm_peek.py`.

## Fleet-watcher flag 4: NHL New Jersey @ St. Louis with no live model, R26-R27 (6:23 and 6:43 PM CST); read-only

**Verdict: a real NHL join defect, specific to St. Louis.**
- The live lens names the team "St. Louis Blues" and the odds rows say "St Louis Blues".
- `live_gameline_join._norm_team` (`live_gameline_join.py:2190`) lowercases and collapses whitespace but keeps the period, and the join keys on the exact pair (`:2472`, `:2628`, `:2757`).
- The name-alias fallback is NCAAF-only (`_TEAM_ALIAS_JOIN_SPORTS`, `:2215`).
- So a Blues game, home or away, never reaches its live lane. The monitor's own helper matched it ("direct", "resimmed") only because `p29_orient.norm` strips periods.
- The same spelling split was fixed in `sgp_pool` before (todo around line 2304, "St. Louis Blues" vs "St Louis Blues"). `nhl/sources.py:190-191` already maps both spellings to STL. No other NHL club has punctuation; Montréal carries its accent on both sides and joins.

The rest of the flag was the monitor's own labelling:

- **R26 `no_snapshot_for_sport` was a monitor label, not a missing NHL snapshot.**
  - `dash_update` assigned it to every no-model game of a sport that the helper's OWN live-rail GET held no game of.
  - That GET (web access log 6:26:06 PM, 200, 353,678 bytes, 363 ms) held no NHL game. Yet the probe's read at 6:23:30 PM held 127 NHL rows, and the fleet's `INPLAY_OVERLAY_MERGED` 4 s later held 91 NHL cards (newest overlay 6:25:47 PM).
  - The NHL overlay itself published every 1-2 min: 6:23:28 PM 127 cards, 6:24:10 PM 116, 6:25:48 PM 91. The write is atomic (`os.replace`, `book_grid_artifact.py:1185-1187`) and the age limit is 360 s.
  - Why that one response held no NHL is **not determined** (one reading).
  - **Monitor fix:** the label is now `sport_absent_from_helper_read`, and `p29_orient.py` prints a `{"rail": {read_at, newest_written_at, rows, games_by_sport, sports}}` line, so the next one can be checked. Tested at 7:05 PM: 9 NHL games in the read.
- **R27 `resimmed_no_row_model` overstated NHL.**
  - NHL live totals are refused at the join by design: no total distribution is published (`findings_2026-11-13_nhl_live_total_calibration.md`). They were 0 of 16 rows modelled at R26 and 0 of 21 at R27.
  - At R27 every NHL game's moneyline and puck-line rows on the full rail carried a model, except St. Louis (0 of 1). New Jersey @ St. Louis's rows were 3 totals plus an alternate +2.5 puck line; alternates do price elsewhere, e.g. Buffalo @ Florida +3.5 at 0.98.
  - Pittsburgh @ Nashville (3 totals; its h2h at 0.49 is outside the priced set) and Vegas @ Winnipeg (2 totals) were false positives from counting NHL totals.
  - **Monitor fix:** `dash_update` and `p29_orient` now skip NHL totals in the priced rule, so NHL counts its puck lines only.
  - R26's four unmodelled games at 6 PM CT (Detroit, Ottawa, St. Louis, Winnipeg) were puck-drop lag. All but St. Louis carried models by 6:43 PM.
- **The fleet fix (not taken; outside this lane).** Either:
  - strip punctuation in `_norm_team`, which changes every sport's exact key; or
  - add NHL to the alias fallback with the STL map, which is narrower.

  Either changes which live NHL bets can be placed on Blues games, so it is a betting change for a window (next: Tue 11-24, 2-7 AM CST).
- Instruments: `nhl_lens_peek.py [team | resimmed]` (`C:\tmp\railmon\`, backed up to `scripts/rail_monitor/`).
- **BUILT 11-22 ~11:20 AM CST (todo `#860`, lane `nhl-live-join-stl-alias`): on main `cb98b201a`, DEFAULT OFF behind `SYNDICATE_LIVE_GAMELINE_NHL_TEAM_ALIASES`. The kit is `C:\tmp\w1124_stl\`. Queued for the 11-24 window by the fleet-watcher. Loading is the user's decision.**
- **PRE-REGISTERED before any load (written 11-22 11:27 AM CST).** Each reading is taken during a live NHL slate after the key is on, with `kit_after_up_stl.sh` plus the rail monitor's `p29_orient.py` lines:
  - **P1 (reachability):** on a live St. Louis Blues game, its full-game moneyline and puck-line rows carry `live_model_probability` at the same rate as the other live NHL games at the same reading: N of N once the game has been re-simmed. Today's baseline is 0 of N.
  - **P2 (no side effect):** no other live NHL game's moneyline/puck-line modelled share falls. 11-21 6:43 PM baseline: 8 of 8 games all modelled.
  - **P3 (no wrong join):** no NHL row joins a different game. There are no `team_pair_covers_more_than_one_game` refusals for NHL; the NHL slate has no doubleheaders.
  - **P4 (unchanged elsewhere):** NCAAF rows join exactly as before; its fallback switch is untouched.
  - **FALSIFIED IF:** P1 reads below N of N on a re-simmed Blues game with the key on; or P2's share falls on any non-Blues game; or any NHL row shows a different game's model.

## Fleet-watcher flag 5: board_wall_max_s 473-612 s at R28-R33 (7:03-8:43 PM CST 11-21) while live games fell 43 -> 28 (diagnosed 11-22 ~11:25 AM CST; read-only)

**Verdict: not #850. The wall is CPU work inside the board build, and on Saturday it ran ~1.7x the weekday evenings from about 10 AM CST, when the college slate went live.** It is the known evening board-cost problem (backlog I-20, lane `layer2-board-process-split`, GOAL NOT MET). #850's memory-guard refusals ran alongside it: they make the publication gaps, not the wall.

- **What the number is.** `d4metrics.py` takes the maximum `BOARD_BUILD_TIMING wall_s` in the reading window. That line also carries `cpu_s`: a 433 s build at 02:20Z 11-22 was `cpu_s` 392.6, off-CPU 9.4%; one at 18:03Z was 406.3 / 378.6, 6.8%. So the build is computing, not waiting on memory or locks.
- **The rise is the whole Saturday, not the evening.** Wall p50 by UTC hour, with builds per hour (`board_evening.py`):

  | span (CST) | wall p50 | wall max | builds/h |
  |---|---|---|---|
  | 11-21 8-10 AM | 225-250 | 293-311 | 9 |
  | 11-21 10 AM-noon | 376-434 | 536-552 | 3-6 |
  | 11-21 noon-6 PM | 307-479 | 403-548 | 5-7 |
  | 11-21 6-11 PM | 378-473 | 498-770 | 3-6 |
  | 11-20 6-11 PM (Fri) | 242-257 | 265-340 | 7-10 |
  | 11-19 6-11 PM (Thu) | 221-254 | 247-548 | 8-11 |
  | 11-22 8-11 AM (Sun) | 165-173 | 221-285 | 13-14 |

  The refresh-worker parent reset at 12:14 PM CST 11-21 did not bring it down, and neither did the code that loaded with it. The rise started before both, at 16Z.
- **Not the candidate pool's size.** `pool_json_bytes` ran 42-49 MB on every evening. Across 1,225 builds, r(pool MB, wall) = -0.01 (`pool_vs_wall.py`). What changed is CPU per pool MB:
  - 11-19 / 11-20 / Saturday morning: 4.5-4.8;
  - Saturday from 16Z: 7.4-9.2;
  - this morning: 3.4.
- **It tracks the day's accumulated quote rows, which is why it did not fall with the live count.** `BOOK_GRID_QUOTE_READ kept` grew monotonically all Saturday (`quote_read_growth.py`): NCAAB 11.5k -> 54k, NCAAF 48k -> 130k, NHL 11.8k -> 21k, soccer 54k -> 65k.
  - On Saturday, r(total kept rows, wall) = 0.62 over 176 builds; at 350-400k kept, wall p50 was 384 s, max 770 (`kept_vs_wall.py`).
  - On Friday r was only 0.20, and Saturday's 16Z jump is larger than the row growth alone. So the slate's live load also plays a part, and the split between the two is not measured.
- **#850 in the same hours:** `MEMORY_GUARD_ABORT` (stage `pre_source_state_fingerprint`) 1-4 an hour, plus 3 board-child exits / recycles in 01-04Z. Publication gaps peaked at 1,221-1,555 s. That is #850's part: its 11-24 fix is pending, and the 4 AM CST 11-22 parent reset (`deploys.md` 2026-11-22T10:37:58Z) is tonight's baseline.
- Instruments, read-only, in `C:\tmp\railmon\` and backed up to `scripts/rail_monitor/`:
  - `board_evening.py <from> <to> ...`;
  - `board_build_ctx.py <utc>`;
  - `pool_vs_wall.py`;
  - `quote_read_growth.py`;
  - `kept_vs_wall.py`.
