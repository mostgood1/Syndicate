# Full-suite baseline on Windows — what a single pass can and cannot establish

Lane `suite-baseline-flakiness`, session 4ab694ed. Runs on 2026-10-07/08/09.

## 1. Collection: one bad file takes the whole suite to zero

MEASURED 2026-10-07, sparse worktree, with 42 of 43 `--ignore` args in place:

    22003 tests collected, 1 error in 150.34s
    !!!!! Interrupted: 1 error during collection !!!!!

22,003 tests collect and **none execute**. pytest treats a collection error as
fatal, so a single uncollectable file is not "one red test" — it is a total
outage of the suite. Worth knowing before reading any "N errors" headline.

The 43 uncollectable files in a SPARSE worktree split as:

| cause | n | what it is |
|---|---|---|
| `No module named 'vendor'` | 30 | sparse tree has no `vendor/` |
| `No module named 'sim_engine'` | 8 | same (vendor module) |
| `No module named 'wnba_betting'` | 4 | same (vendor module) |
| `No module named 'fcntl'` | 1 | a real Windows defect |

42 of 43 are sparseness, and all 42 are present and collectable in the primary
tree. The primary tree collected **22,477 tests with 0 errors**.

### The fcntl one was real (now fixed upstream, by its own lane)

`tests/test_web_worker_fast_healthz.py:28` imported `syndicate.web_worker`,
which at `:55` did `from gunicorn.workers.gthread import ThreadWorker` at module
scope -> `gunicorn/util.py:8  import fcntl`. The file ALREADY had the right idea
— its docstring says the classifier tests "run everywhere" and lines 32-37 are a
`try: import fcntl` guard — but the guard sat four lines BELOW the import that
killed collection. Fixed by lane `web-restart-healthz` (not me): pure helpers
moved to `syndicate/web_healthz.py` (imports only `os`), test imports from there.
VERIFIED STRUCTURALLY on origin/main. Their runtime numbers (20 passed /
7 POSIX-skipped) are THEIRS — I did not reproduce them.

## 2. The sparse-worktree run (the one that completed)

    331 failed, 21257 passed, 314 skipped, 1 xfailed, 11 warnings, 191 errors,
    528 subtests passed in 37755.48s (10:29:15)

Tree `b1d9ce0f` (44 behind by the end), 22,003 of 22,477 tests, one process,
serial. **Do not quote the 331/191 as a defect count.** See section 3.

## 3. A large share of failures are RUN-DEPENDENT, not real and not data gaps

Per-file isolated re-runs (whole file, fresh process, sequential, parametrize ids
normalised) of the 23 files failing as of a 31.3% snapshot:

    REPRODUCED      92   failed in the long run AND alone
    NOT REPRODUCED  56   failed in the long run, passed alone
    ONLY ISOLATED   41   passed in the long run, failed alone

Two populations, split by FILE:

- **STABLE (13 files)** — identical sets both times. `test_archives.py` 32/32,
  `test_bet_status_ncaaf.py` 10/10, `test_ask_sport_coverage.py` 4/4, ...
- **UNSTABLE (8 files)** — the set CHANGES between runs.
  `test_inplay_board_cadence.py`: **7 one run, 9 the other, ZERO overlap**.
  `test_execution_multi_venue.py`: exactly 1 each time — **a different test**.
  Also `test_intelligence.py` (40 vs 38, only 14 shared),
  `test_football_sim_engine.py`, `test_http_compression.py`,
  `test_fotmob_match_id.py`, `test_formatter.py`,
  `test_football_calibration_artifacts.py`.

Zero overlap refutes "pollution masked it" as a story; the mechanism is
nondeterminism, and these are thread / lock / launcher / socket / HTTP tests on a
host that was at 100% CPU.

The completed run's 514 named FAILED/ERROR lines across 91 files classify as:

| group | failures | files | worth |
|---|---|---|---|
| stable | 77 | 13 | real signal; names say data-dependent |
| unstable | 70 | 6 | a single pass says nothing |
| **never isolated** | **367** | **72** | **unknown** |

The isolation study was built from a 31.3% snapshot, so it only ever covered 23
files. The run went on to fail in 72 files nobody examined — `ncaaf_lines_autorun`
(25), `odds_refresh_tracking` (24), `wnba_live_refresh_autorun` (22),
`venue_poll_loop` (19) — autorun/refresh/poll-loop families, the same shape as
the files that PROVED unstable. BELIEVED, NOT ESTABLISHED.

## 4. Priority is the throughput lever, and the fleet owns the host

A/B with two simultaneous Idle controls, 30 s window, 2026-10-07:

| process | priority | CPU |
|---|---|---|
| 46348 | Normal | **94% of one core** |
| 48636 | Idle | 30% |
| 13992 | Idle | **1%** |

Later, with the fleet holding ~11 of 12 cores: the Idle run took **0.0 s of CPU
over 30 s** — total starvation. `learnings.md` already recorded the other side:
host at 100% starved the VM to 2-3.6 of 12 cores and blew the board's shortlist
step from ~120-230 s to 1,924 s. Windows sees the whole fleet as ONE Normal
process, so an Idle run yields to it completely and a Normal run competes with it
directly. USER DECISION 2026-10-07: stay at Idle, accept it may not finish.

## 5. Dead ends, so nobody repeats them

- **`xdist -n 3 --dist loadfile` "deadlocks" this suite — WRONG.** Controller and
  3 workers at 0.00 s CPU for 8.5 min looked like an execnet hang. It was CPU
  starvation at Idle on a saturated host. I asserted the mechanism, then built an
  entire args-file sharding scheme on it, which crawled identically.
- **Args-file sharding / `shard_plugin` / bin-packing to 1.0001 imbalance** —
  correct work, irrelevant: there was no spare CPU to parallelise into.
- **BelowNormal fixes I/O priority — refuted.** 0.09 s vs Idle controls at
  0.13-0.20 s. (That test was also too weak to prove anything: one 20 s window,
  no matched controls.)
- **Counting progress characters to get live pass/fail totals — unreliable here.**
  160 progress lines are interrupted mid-line by test debug dumps
  (`PROCESS_ENUM_DEBUG`, `ALL_PROCESS_MEMORY`), so a char count UNDERCOUNTS and
  silently. Use pytest's own summary line.

## 6. Open: the primary-tree run

Started 2026-10-08 08:27:49 in the primary tree at `4d9f4ade` (60 behind), one
process at Idle, no ignores. At **99%** as of 2026-10-09 11:33 — ~27 h wall,
69,503 s CPU, repeatedly starved to 0% while the fleet held the host. NOT
FINISHED; no summary line yet. It is the run that can settle section 3, because a
complete checkout removes the data-dependent class outright.

Output lives at `C:/tmp/a1-draft/final_pr.txt` (worktree run: `final_wt.txt`,
117 MB; per-file isolation results: `C:/tmp/a1-draft/rerun/*.txt`).

## 7. RESOLVED — the primary-tree baseline and its classification

The run finished **2026-10-09 12:30:35**, 1 day 3h59m25s, primary tree
`4d9f4ade`, one process at Idle, no `--ignore` list:

    49 failed, 22701 passed, 33 skipped, 1 xfailed, 16 warnings, 6 errors,
    602 subtests passed in 100765.20s (1 day, 3:59:25)

All 26 failing files were then re-run per file, alone, in the same tree. Node
names come from pytest's own `-rfE` summary in BOTH runs, so this is a direct
comparison and not a position-mapping; parametrize ids are normalised.

```
  files re-run: 26 of 26   (complete)

  REPRODUCED       37   real candidate defects
  NOT REPRODUCED   15   run-dependent in the full suite
  ONLY ISOLATED     0   the full run was masking these

    file                                                 run  iso  repro  rundep  new
    tests/test_board_freshness_derived.py                  2    0      0       2    0
    tests/test_duplicate_module_names.py                   1    1      1       0    0
    tests/test_fetch_ncaaf_oddsapi_props_local.py          1    0      0       1    0
    tests/test_intelligence_state_persist_budget.py        1    1      1       0    0
    tests/test_layer2_fast_refresh.py                      1    0      0       1    0
    tests/test_layer2_out_player_gate.py                   5    5      5       0    0
    tests/test_layer2_prior_date_carryover.py              1    0      0       1    0
    tests/test_layer2_row_context.py                       1    1      1       0    0
    tests/test_layer2_row_parity.py                        1    1      1       0    0
    tests/test_market_gone_drop.py                         2    0      0       2    0
    tests/test_nba_cards_keyvalue_backend.py               1    0      0       1    0
    tests/test_ncaaf_live_resim.py                         1    1      1       0    0
    tests/test_ncaaf_props_board.py                        2    2      2       0    0
    tests/test_nfl_injury_adjustment.py                    1    0      0       1    0
    tests/test_nfl_market_board.py                         1    1      1       0    0
    tests/test_nfl_player_stats.py                        14   14     14       0    0
    tests/test_nfl_props.py                                4    3      3       1    0
    tests/test_nfl_props_board.py                          2    2      2       0    0
    tests/test_nhl_confirmed_goalies.py                    1    1      1       0    0
    tests/test_probability_differential.py                 1    1      1       0    0
    tests/test_publisher_identity_header.py                2    0      0       2    0
    tests/test_refresh_worker.py                           2    0      0       2    0
    tests/test_slate_date_timezone_discipline.py           1    1      1       0    0
    tests/test_slate_phase_wiring.py                       1    1      1       0    0
    tests/test_soccer_team_ratings_as_of.py                1    0      0       1    0
    tests/test_worker_shutdown.py                          1    1      1       0    0

  REPRODUCED -- these are the ones worth looking at:
    [FAILED] tests/test_duplicate_module_names.py::test_no_module_level_name_is_defined_twice_anywhere
    [FAILED] tests/test_intelligence_state_persist_budget.py::GuardReleaseTests::test_guard_releases_when_the_install_stretch_raises
    [FAILED] tests/test_layer2_out_player_gate.py::test_end_to_end_an_out_player_is_not_seated
    [FAILED] tests/test_layer2_out_player_gate.py::test_end_to_end_off_is_not_on
    [FAILED] tests/test_layer2_out_player_gate.py::test_the_flag_survives_build_layer2_rows
    [FAILED] tests/test_layer2_out_player_gate.py::test_the_sample_is_capped_per_sport
    [FAILED] tests/test_layer2_out_player_gate.py::test_the_sample_names_the_gated_players
    [FAILED] tests/test_layer2_row_context.py::test_the_write_up_context_follows_but_its_price_sentence_does_not
    [FAILED] tests/test_layer2_row_parity.py::test_the_row_context_brings_the_write_up
    [FAILED] tests/test_ncaaf_live_resim.py::test_the_probability_moves_with_the_score_which_is_the_entire_point
    [FAILED] tests/test_ncaaf_props_board.py::test_best_price_across_books_wins_and_names_the_book
    [FAILED] tests/test_ncaaf_props_board.py::test_unbettable_books_are_excluded_by_default
    [FAILED] tests/test_nfl_market_board.py::NflMarketBoardBuilderTests::test_build_nfl_market_board_shapes_games
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_anytime_td_attributed_to_scorer_only
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_anytime_td_league_prior_excludes_current_and_later_weeks
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_anytime_td_rate_requires_two_games_same_as_player_rate
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_anytime_td_rate_shrinks_a_zero_history_toward_the_league
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_final_stat_value_returns_real_settled_value
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_interceptions_attributed_to_passer_only
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_player_game_log_extracts_all_stats
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_player_rate_excludes_current_and_later_weeks
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_player_rate_requires_at_least_two_games
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_player_rate_returns_the_SAMPLE_sd_not_the_population_sd
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_receiving_yards_attributed_to_receiver_only
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_resolve_player_id_matches_full_name_to_short_name
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_shrinkage_is_REACHABLE_off_differs_from_on
    [FAILED] tests/test_nfl_player_stats.py::NflPlayerStatsTests::test_the_spread_is_SHRUNK_toward_a_usage_scaled_league_prior
    [FAILED] tests/test_nfl_props.py::NflPropsTests::test_available_weeks_excludes_header_only_stubs
    [FAILED] tests/test_nfl_props.py::NflPropsTests::test_header_only_stub_returns_empty
    [FAILED] tests/test_nfl_props.py::NflPropsTests::test_missing_file_returns_empty
    [FAILED] tests/test_nfl_props_board.py::test_a_genuinely_empty_week_still_resolves_to_a_concrete_path
    [FAILED] tests/test_nfl_props_board.py::test_week_enumeration_unions_every_root
    [FAILED] tests/test_nhl_confirmed_goalies.py::test_refresh_never_raises_and_has_an_off_switch
    [FAILED] tests/test_probability_differential.py::test_every_converter_is_registered_or_excused
    [FAILED] tests/test_slate_date_timezone_discipline.py::SlateDateTimezoneDisciplineTests::test_no_new_timezone_ambiguous_date_calls
    [FAILED] tests/test_slate_phase_wiring.py::test_tick_publishes_for_the_board_only_while_observing
    [FAILED] tests/test_worker_shutdown.py::test_the_record_survives_a_signal_that_lands_MID_PRINT

  NOT REPRODUCED -- run-dependent:
    tests/test_board_freshness_derived.py::CombinedBoardStateMetaTests::test_age_is_the_OLDEST_input_and_newest_is_reported_beside_it
    tests/test_board_freshness_derived.py::CombinedBoardStateMetaTests::test_fresh_shortlist_is_reported_fresh_with_a_real_age
    tests/test_fetch_ncaaf_oddsapi_props_local.py::FetchNcaafOddsApiPropsLocalTests::test_main_requires_api_key
    tests/test_layer2_fast_refresh.py::Layer2FastRefreshTests::test_shortlist_rebuilds_while_the_layer1_floor_is_refusing
    tests/test_layer2_prior_date_carryover.py::PriorDateCarryoverTests::test_it_yields_to_a_board_build_holding_the_guard_and_releases_its_own
    tests/test_market_gone_drop.py::test_market_gone_rows_are_dropped
    tests/test_market_gone_drop.py::test_one_sports_dead_market_does_not_touch_another
    tests/test_nba_cards_keyvalue_backend.py::NbaCardsKeyvalueBackendTests::test_live_snapshot_payload_cache_invalidates_on_new_keyvalue_write
    tests/test_nfl_injury_adjustment.py::OffenseAdjustmentIntegrationTests::test_questionable_status_is_not_adjusted
    tests/test_nfl_props.py::NflPropsTests::test_anytime_td_sim_row_uses_the_shrunk_rate_not_the_raw_zero
    tests/test_publisher_identity_header.py::test_an_UNSET_lane_sends_empty_rather_than_a_guess
    tests/test_publisher_identity_header.py::test_the_JSON_path_sends_the_publisher
    tests/test_refresh_worker.py::RefreshWorkerTests::test_main_run_once_executes_runner_when_pending
    tests/test_refresh_worker.py::RefreshWorkerTests::test_main_run_once_recovers_stuck_claim_before_launch
    tests/test_soccer_team_ratings_as_of.py::test_every_caller_passes_as_of
```

### What this settles

- **The sparse worktree overstated the suite by ~10x** (331 failed / 191 errors
  over 22,003). All 13 files whose failure sets were stable across two sparse runs
  are GREEN here — data dependence, confirmed by DISAPPEARANCE, not by names.
- **A sparse run does not identify the right FILES.** Zero overlap: the 26 files
  failing here include none of the 23 the sparse run pointed at.
- **A complete checkout is far more deterministic.** 37/15/0 here against 92/56/41
  from the sparse runs, where 41 failures appeared only in isolation. The earlier
  instability was substantially the sparse tree plus a host at 100% CPU.
- **15 failures are run-dependent** (pass alone): NOT defects on this evidence.

### Leads handed on — NOT taken by this lane

- **`test_nfl_player_stats.py` 14/14 reproduce.** One is
  `test_shrinkage_is_REACHABLE_off_differs_from_on`; by
  `docs/ai_context/model_engine_standard.md` a failing reachability test means the
  feature may be INERT, which is the standard's primary failure mode.
- **`test_layer2_out_player_gate.py` 5/5 reproduce**, including
  `test_end_to_end_an_out_player_is_not_seated` and `test_end_to_end_off_is_not_on`
  — an OUT-player gate that may not be gating.
- Smaller stable clusters: `test_ncaaf_props_board.py` 2/2,
  `test_nfl_props_board.py` 2/2, `test_nfl_props.py` 3/4,
  `test_duplicate_module_names.py` 1/1.
