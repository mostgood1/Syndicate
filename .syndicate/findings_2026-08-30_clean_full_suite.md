# main was NOT green at `7cea63c5` — 46 real test failures `[2026-08-30, MEASURED]`

**This is the clean-control reading the session owed.** A first attempt gave 60
failures and was WORTHLESS: it ran 5h17m against the SHARED primary tree while
that tree was being fast-forwarded twice and written to by several sessions, so
it smeared across many states. At least 9 of its 60 were already explained.

## How this one was made trustworthy

| property | value |
|---|---|
| worktree | detached, `/c/tmp/cleanrun`, nobody else's path |
| sha at start | `7cea63c5d1cdd5ea93554aae0e0fc7eeea762555` |
| sha at end | **identical** — the code never moved under the run |
| `data/` present | yes (absent `data/` fabricates soccer failures — see learnings) |
| duration | 3:17:27, 06:23:48Z → 09:41:56Z |
| pytest exit | 1, captured from pytest itself, not from a trailing `tail` |

**RESULT: 46 failed, 13,056 passed, 51 skipped, 1 xfailed.**

**An integrity guard fired and was checked, not waved away.** `dirty@end` was 7,
and my own footer said that voids the result. It does not: **0 tracked `.py`
files were modified.** The dirt is test-generated — a live-lens fixture, a
kalshi_markets snapshot, two vendored WNBA schedules, plus two new output dirs.
Side finding worth someone's time: **tests write into `data/` and `vendor/`.**

## Two diagnoses CONFIRMED by absence

- **`test_deploy_preflight` — 0 failures here, 6 in the smeared run.** Those 6
  read the LIVE shared deploy claim; none was held during this run. Confirms the
  mechanism, and confirms that reverting my attempted fix (which took 6 → 8) was
  right. The defect is still open: the tests are not isolated from live state.
- **`test_artifact_publisher` / `test_home` — 0 failures.** The `beaf5533` fixes
  hold at this SHA, independently of the tree they were made in.

So 60 → 46 is fully accounted for: 3 fixed mid-run, 6 claim-dependent, 5 other
mid-run states.

## The 46, and NONE of them are this session's

They span 26 files this session never touched.

**45 named, 46 counted — and the gap is stated rather than rounded away.**
pytest's own tally says `46 failed`; its `-rf` short summary names 45 unique
ids, with no duplicates. The unnamed one is most likely a SUBTEST or teardown
failure (the run reports `434 subtests passed`), which counts toward the total
but is not emitted as a `FAILED <id>` line. So the breakdown below covers 45 of
46; one failure has no id here and would need `-rA` or a re-run to name.

```
   8  test_open_bet_live_status.py
   5  test_mlb_sim_run_reconcile.py
   4  test_ncaaf_picks_local.py
   2  test_kalshi_catalogue.py
   2  test_ncaaf_oddsapi_game_lines.py
   2  test_ops.py
   2  test_refresh_odds_sources.py
   2  test_wnba_refresh_runner.py
   1  test_lane_guard_files_forms.py
   1  test_layer2_movement_live_segment.py
   1  test_live_refresh_loop.py
   1  test_memory_watchdog.py
   1  test_nba_refresh_runner.py
   1  test_ncaaf_team_registry_reachability.py
   1  test_nfl_props.py
   1  test_nfl_props_board.py
   1  test_odds_control_plane.py
   1  test_probability_differential.py
   1  test_prop_player_keying.py
   1  test_quote_join_index_equivalence.py
   1  test_refresh_state_store.py
   1  test_smartsim2_calibration_profile.py
   1  test_soccer_board_mlb_parity.py
   1  test_soccer_fixture_pair_resolution.py
   1  test_soccer_read_scope.py
   1  test_wnba_grader_root_per_file.py
```

## Scope of the claim, stated as part of the claim

- This is **"was main green at `7cea63c5`"**, not "is main green now" — peers
  push steadily and the SHA was already behind when the run finished.
- The 46 are UNTRIAGED. Real defect vs environment-sensitive test is unknown per
  case; this session's own experience is that both exist in this repo.
- **51 skipped, against 6 in the smeared run.** Some is the roster-dependent
  gating another lane added 2026-08-30 (`needs_soccer_rosters`), but that was
  NOT verified for all 51 and a skip that should be a run is invisible.

## For whoever picks this up

Start with the clusters — `test_open_bet_live_status` (8),
`test_mlb_sim_run_reconcile` (5), `test_ncaaf_picks_local` (4) — and for each,
reproduce in a CLEAN detached worktree at `origin/main` with `data/` present
before attributing anything to a commit. Full output: the run wrote
`CLEAN_RUN_RESULT.txt` into `/c/tmp/cleanrun`, which is a throwaway worktree and
will not survive a prune; the per-file counts above are the durable record.

