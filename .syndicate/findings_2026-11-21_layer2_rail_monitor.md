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
- Instrument: `p2_boardpub.py` lost a leftover debug print, a hard-coded 11-21 01:1x Z line dump. It printed after the numbers and did not change them. The backup in `scripts/rail_monitor/` is updated.
