# Scope: deleting vendor/nhl_betting_repo (2026-10-20, lane nhl-vendor-deletion-scope)

User: "move the nhl vendor tree off next" (2026-10-20). Same method as the NBA / WNBA scopes. Analysis only.

## Headline

**The smallest of the four.** Production runs and reads nothing from the tree. No generator, harness or research script
reads it (the hockey sim `syndicate/features/nhl/sim_engine/hockeysim` was absorbed by hand earlier, not generated), so
there is **nothing to freeze**. What is left: the Windows runner's NHL branch, `sync_vendor_upstream.py`'s last tree,
the two mirror-guard tests that name it, and docs.

## Production, measured

- **Static (origin/main 249ff48b):** 23 non-vendor `.py` files mention `nhl_betting`; 4 have code-level references --
  `sync_vendor_upstream.py` (TREES), and 3 tests, two of which ASSERT the refresh does not use the vendored CLI
  (`test_nhl_refresh_runner.py:292`, `test_ops.py:989`).
- **Fleet, 2026-10-20 19:52Z, HEAD 22c56001:** tree 3.5 MB, 89 tracked, 0 ignored, **0 modified**; **0 files written under it since
  2026-09-30** and **no `.pyc` anywhere in it** -- nothing on the fleet has ever imported it from this checkout. Population: the NHL
  pipeline wrote 304 files in the data root since 10-16 (book grid 14:44 CDT today). No process cwd/fd under it; no role env var
  or PYTHONPATH points at it (booleans).
- **Fleet import trace (fresh interpreter, env -i, nice 19):** 14 modules -- refresh_nhl_oddsapi, build_nhl_artifacts,
  update_nhl_boxscore_log, fetch_nhl_confirmed_goalies, nhl.live_lens, nhl.cards, nhl.sim_engine.hockeysim, nhl.boxscore_log,
  live_refresh_loop, schedule_adapter, blueprints.nhl, refresh_odds_sources, run_refresh_worker, run_live_odds_refresh_worker --
  load **0** vendored modules.

## Upstream (mostgood1/NHL-Betting, default branch `master`, newest 2026-05-25)

80 rows: 77 IN_SYNC, 3 LOCAL_PATCH, **0 CONFLICT, 0 UPSTREAM_AHEAD**. Nothing exists only upstream.

## Tests, measured by deletion (82 files, 1,993 tests, Idle)

Tree present vs moved aside (restored after, 0 status lines): **2 outcomes change** -- `test_data_mirror_write_guard::
test_the_guarded_roots_are_this_repos_tracked_mirrors` and its `[vendor/nhl_betting_repo/data/...-True]` param, which since
e633f12c name the NHL tree as the last vendor data root. With no vendor tree left they drop the vendor-root case (the
engines/mlb root and data/ stay guarded).

## The rest

| item | at deletion |
|---|---|
| `unified_daily_update.ps1` NHL step | it already branches: vendored CLI present -> "NHL vendored daily update" with `--source-root vendor\\nhl_betting_repo`; else the native "NHL local odds refresh". Collapse to the native step, keeping `--props-boxscore-n-sims` (only the vendored branch passes it; the script accepts it, default 1000) |
| `sync_vendor_upstream.py` | NHL is its LAST tree: with it gone the script has nothing to sync -> retire it and `vendor/upstream_sync.json` (and its test), or leave an empty TREES; retiring is cleaner |
| `check_duplicate_module_names.py` | no NHL baseline entry; nothing to do |
| tests asserting "no vendored CLI" | keep: they still pass and still guard against a regression |
| docs | CLAUDE.md vendor line (vendor/ becomes empty), end_to_end_context, nhl_model_inventory, the vendor-repos memory note |

## Proposed sequence

One step is enough (no freeze, no port work): the runner + sync retirement + the 2 tests + docs, the `git rm`, a
before/after run, fleet archive, and the tree leaves the fleet with the next fleet ff. After it `vendor/` is empty.
