# Scope: deleting vendor/nba_betting_repo (2026-10-19, lane nba-vendor-deletion-scope)

User: "move the nba vendor tree off next" (2026-10-19). Same method as the MLB scope
(`findings_2026-10-19_mlb_vendor_deletion_scope.md`). Analysis only; nothing changed.

## Headline

**Production already runs no vendored NBA code.** Every runtime NBA path was moved by earlier lanes (engine P1,
orchestrator P6, live tick, source CLI, recon tools, history, props models; `docs/ai_context/basketball_live_native_plan.md`).
What is left is the MLB pattern: generators, parity harnesses, research scripts, tests and docs. One structural
difference: **two generators build ONE shared basketball package from the NBA tree** (the engine from NBA
`sim/events.py` alone; the orchestrator from BOTH forks), so deleting the NBA tree means those two packages can never
be regenerated -- the freeze decision covers the WNBA side of them too.

## Production, measured

- **Static, origin/main cae68602:** an AST scan (code strings + imports, docstrings excluded) finds 165 non-vendor `.py`
  files mentioning `nba_betting`; 42 have code-level references, and on production paths every one is a
  `package_name="nba_betting"` LABEL (the refreshes pin it and refuse anything else; `basketball_props_smart_sim` maps
  it to `fork="nba"`), not an import. No `import nba_betting` on any production path; the only import is
  `scripts/replay_basketball_teammate_effects.py` (research, lineup teammate effects retired 2026-10-13). Dynamic
  imports of `<league>_betting` exist only in parity harnesses. The loop's `fetch-injuries` and `schedule_adapter`'s
  `fetch-schedule` already run `syndicate.features.nba.source_cli.cli` (the plan's 10-09 table still lists them).
- **Fleet, 2026-10-19 20:10Z, HEAD 94c97011:** tree 62 MB, 507 tracked, 53 ignored, **0 modified**. Files written under
  it since 10-10: **0** (newest: `sim/events.py` 10-08 16:15, its `.pyc` 10-08 18:21 -- before P6 shipped 10-10). No
  process has a cwd or open fd under it. web / refresh / live-odds env: no NBA var and no `PYTHONPATH` points under
  vendor/ (booleans only). **Limit:** a current `.pyc` means an import writes nothing, so "0 writes" is not "0 imports"
  -- hence the next reading.
- **Fleet import trace (fresh interpreter, env -i, nice 19):** 15 production modules -- `refresh_nba_oddsapi_props`,
  `nba.live_lens`, `nba.live_tick.tick`, `nba.source_cli.cli`, `basketball_props_smart_sim`,
  `basketball_props_predictions`, `basketball_engine.orchestrator`, `schedule_adapter`, `live_refresh_loop`,
  `nba_history_refresh`, `blueprints.nba`, `nba.cards`, `refresh_odds_sources`, `run_refresh_worker`,
  `run_live_odds_refresh_worker` -- load **0** vendored NBA modules. Import time only; lazy imports are covered by the
  static scan above.
- **Dev-only fallback:** `refresh_odds_sources._basketball_source_root` returns `vendor/nba_betting_repo` only when no
  data root is set AND `data/nba_source` is absent (a dev checkout). On the fleet it never does.
- **Local Windows runner:** `scripts/unified_daily_update.ps1` NBA step THROWS without `vendor\nba_betting_repo\app.py` and
  passes `--source-root vendor\nba_betting_repo`. Must be repointed (as MLB's was, 2f12e380).

## Tests, measured by deletion (146 files, 2,071 tests, Idle priority)

Run A tree present vs run B tree moved out of the worktree (restored after; 0 status lines): **24 outcomes change,
nothing else.** 10 FAIL and 14 SKIP without the tree.

| fails without the tree | what it does | at deletion |
|---|---|---|
| `test_basketball_engine_parity::test_synthetic_parity_is_exact[production,vendored_default]` | native engine vs the vendored engine | retire with the harness (parity proven 10-09) or keep a frozen-output invariant |
| `test_basketball_injury_exclusion_reinclusion::..._nba` | the source filter against the VENDORED smart_sim's name normaliser | repoint to `basketball_engine.orchestrator.smart_sim` |
| `test_live_lens_tick_klass_gate` x3 `[nba_betting_repo]` | pins the #626(e) "never BET on a model line" gate in the vendored `app.py` | repoint to the ports: the gate IS in `nba/live_tick/tick.py:9261` and called at :10559, and `test_basketball_live_tick_reachability` already pins it there |
| `test_nba_preseason_oddsapi.VendoredNbaTests` x2 | preseason sport keys + no-Bovada, run against vendored `nba_betting.odds_api` / `cli` | repoint to `nba/source_cli/odds_api.py` (has `NBA_GAME_SPORT_KEYS`) and `source_cli/cli.py` |
| `test_data_mirror_write_guard[vendor/nba_betting_repo/...]` | path used as test data | swap the param |
| `test_duplicate_module_names` | `check_duplicate_module_names.VENDOR_BASELINE` names the NBA cli | drop the entry |

The 14 that SKIP (green-by-skip after deletion, so they must not be left): `--check` / generator-match tests
(`test_basketball_live_tick_reachability`, `test_nba_schedule_current_season`, `test_nba_source_cli_reachability`),
vendor-comparison tests (`test_basketball_league_rules[nba]`, `test_basketball_orchestrator_parity` x3,
`test_basketball_props_models_native[nba]`, `test_basketball_source_cli_parity[nba]`, `test_nba_player_logs_fetch` x5).
Replace with post-deletion invariants (no vendored import, roots, served bytes) or retire, as MLB did.

## Generators and harnesses (vendor is their source by design)

| script | reads | after deleting the NBA tree |
|---|---|---|
| `port_basketball_engine.py` | NBA `sim/events.py` only | cannot run: **freeze** `basketball_engine/engine.py` (NBA + WNBA engine) |
| `port_basketball_orchestrator.py` | BOTH forks | cannot run: **freeze** `basketball_engine/orchestrator/` (both forks) |
| `port_basketball_live_tick.py` | per league | freeze `nba/live_tick/`; keep the WNBA arm |
| `port_basketball_source_cli.py` | per league | freeze `nba/source_cli/`; keep the WNBA arm |
| `basketball_{engine,orchestrator}_parity.py`, `basketball_{live_tick,source_cli}_parity.py`, `basketball_{orchestrator,sim}_input_checklist.py` | vendored arm | drop the NBA arm (engine/orchestrator: retire); the checklists keep their "imports no vendored module" checks |
| `sync_vendor_upstream.py` | NBA in TREES | drop NBA, plus its `upstream_sync.json` entry |
| research: `basketball_scenario_rates.py`, `record_nba_engine_inputs_asof.py`, `resim_nba_availability.py` | put vendored `src` on sys.path; import nothing from it | delete the path line. `basketball_scenario_rates.py` is RUNNING on the fleet now (lane basketball-scenario-calibration, PID 2571137): edit on main only, it is unaffected until an ff |
| `replay_basketball_teammate_effects.py` | imports vendored `lineup_context_features` | retire (feature retired 10-13) or freeze the one module |

Generated headers to rewrite (count of files saying "generated"/"do not edit"): engine 1, orchestrator 12,
nba/live_tick 7, nba/source_cli 18. WNBA's 8 + 25 stay generated.

## Upstream (sync_vendor_upstream report, mostgood1/NBA-Betting main, newest commit 2026-07-17)

328 rows: 179 IN_SYNC, 139 LOCAL_ONLY, 9 LOCAL_PATCH, 1 CONFLICT, **0 UPSTREAM_AHEAD**. The CONFLICT is
`src/nba_betting/cli.py`; upstream's last change there (8073ecc, 2026-05-15, `_build_slate_from_game_odds`
fallback) is already in BOTH the vendored copy (:13125) and Syndicate's port (`nba/source_cli/cli.py:1141`), so it is
a stale baseline, not lost content. **Nothing found that exists only upstream.**

## WNBA is independent

0 files under vendor/wnba_betting_repo import `nba_betting` or name the NBA tree. Deleting NBA does not touch WNBA's
vendored paths.

## Docs

CLAUDE.md vendor line; 11 docs name the tree (incl. `basketball_live_native_plan.md`, whose P6 table should get the
two stale loop rows struck, and `basketball_sim_engine_reference.md`, the engine-standard trace).

## Proposed sequence (mirrors MLB)

1. **Decision (user):** freeze the four NBA-derived generated trees as maintained source -- the basketball engine and
   orchestrator (shared with WNBA) plus `nba/live_tick` and `nba/source_cli` -- and retire the two shared generators
   and the NBA arms of the other two and of the harnesses.
2. **Prep (one lane, one landing):** headers + a FROZEN note; the 10 failing tests repointed; the 14 skipping tests
   replaced or retired; research path lines; `unified_daily_update.ps1`; the dev fallback; `check_duplicate_module_names`
   baseline; `sync_vendor_upstream`; docs. JUnit before/after + a vendor-absent run.
3. **Delete:** `git rm -r vendor/nba_betting_repo` + upstream_sync entry + CLAUDE.md; vendor-absent run + import trace.
4. **Fleet:** archive the dir; the deletion rides the next fleet ff (nothing reads it; 0 modified files already).
5. **Timing:** the NBA regular season opens 2026-10-20. None of steps 2-3 changes a runtime path, but they touch
   test and generator files other OPEN basketball lanes list -- check claims at prep time.
