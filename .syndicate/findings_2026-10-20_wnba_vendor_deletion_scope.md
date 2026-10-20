# Scope: deleting vendor/wnba_betting_repo (2026-10-20, lane wnba-vendor-deletion-scope)

User: "move the wnba vendor tree off next" (2026-10-20). Same method as the NBA scope
(`findings_2026-10-19_nba_vendor_deletion_scope.md`). Analysis only; nothing changed.

## Headline

**Production already runs no vendored WNBA code and reads no vendored WNBA data.** My lane hypothesis (that the
loop's commence times and `wnba_fixture_identity` still read the vendored `schedule_2026.*`) is FALSIFIED: both moved
earlier (`wnba_fixture_identity` 2026-10-14; the loop reads the data-root schedule the refresh rewrites). What is left
is bigger than NBA's but of the same kind: two generators that now have ONLY a WNBA arm (so both retire whole), their
harness arms, ~90 tests, two research scripts, the Windows runner, docs.

## Production, measured

- **Static (origin/main 4142b395):** AST scan, 116 non-vendor `.py` files mention `wnba_betting`; 50 have code-level
  references. On production paths every one is a `package_name="wnba_betting"` LABEL (refresh_wnba_oddsapi_props.py
  :1268/:3667/:3800/:4021/:4530/:5055 pin it and refuse anything else; `basketball_props_smart_sim` maps it to a fork)
  or `refresh_odds_sources._basketball_source_root`'s dev-only fallback (never taken with a data root set).
- **Fleet, 2026-10-20 14:23Z, HEAD e491c260:** tree 76 MB, 425 tracked, 181 ignored, **0 modified**. Files written under it
  since 10-10: **0** (newest 10-07 11:41). **Population:** the WNBA refresh wrote 207 files in the data root since 10-16
  (today's schedule 09:18 CDT). No process cwd/fd under the tree; no role env var or PYTHONPATH points at it (booleans).
- **Fleet import trace (fresh interpreter, env -i, nice 19):** 14 modules -- refresh_wnba_oddsapi_props, wnba.live_lens,
  wnba.live_tick.tick, wnba.source_cli.cli, wnba.cards, wnba.live_resim, wnba_fixture_identity, live_refresh_loop,
  schedule_adapter, blueprints.wnba, build_wnba_totals_calibration, refresh_odds_sources, run_refresh_worker,
  run_live_odds_refresh_worker -- load **0** vendored WNBA modules.

## Upstream (mostgood1/WNBA-Betting main, newest commit 2026-05-29)

252 rows: 172 IN_SYNC, 66 LOCAL_ONLY, 10 LOCAL_PATCH, 4 CONFLICT, **0 UPSTREAM_AHEAD**. The 4 CONFLICTs (cli.py, league.py,
league_status.py, sim/events.py): of the lines upstream added since the recorded baseline, 33/34, 3/4, 61/73, 262/265 are
in our copy; the missing ones are comments citing Syndicate's own measurements ("measured 2026-10-06", "the Syndicate
deployment", "PR #9") -- Syndicate work sent upstream -- plus league_status's WNBA `league_id` on ScoreboardV2, which the
port carries (`wnba/source_cli/league_status.py:44`, `LEAGUE.stats_league_id`). **Nothing found that exists only upstream.**

## Tests, measured by deletion (174 files, 2,649 tests, Idle)

Tree present vs moved aside (restored after, 0 status lines): **61 outcomes change and 4 files (54 tests) fail to collect.**

| group | count | what | at deletion |
|---|---|---|---|
| estimator test files (dispersion, shape, minutes redistribution, rate shrink) | 4 files / 54 tests, collection error | import vendored `wnba_betting.prop_ladders.build_exact_ladder_payload` as a FIXTURE builder | repoint to `basketball_engine/orchestrator/prop_ladders.py` (same source, sha 0e2594b8 for both forks) |
| vendored-module behaviour tests (bovada_league 5, league_status_roster 3, predict_date_league 4, fetch_rosters_season 1, scoreboard_league_id 1) | 14 fail | exercise `wnba_betting.{cli,odds_bovada,teams,league,config,league_status}` | repoint to the ports production runs (`wnba/source_cli`, `wnba/live_tick`); a module the ports lack (fetch-rosters) -> retire |
| `test_wnba_refresh_runner` offline signals | 1 fail | the vendored `tools/generate_offline_live_lens_signals.py` | retire: nothing in scripts/ or syndicate/ references that tool |
| injury filter [wnba], orchestrator hooks test | 2 fail | vendored smart_sim normaliser / hook names | repoint to the orchestrator (as NBA's was) |
| klass gate [vendor/wnba_betting_repo] | 3 fail | the #626(e) gate in the vendored app | drop the param: the gate is pinned on both PORTS already |
| live period lines native-vs-vendored | 31 skip | `wnba/live_period_lines.py` parity (shipped 10-12) | retire, keep the port's own tests |
| generator checks (live_tick, source_cli, live_tick_fixes x2) | 5 skip | `--check` / fixed-vs-verbatim | generators retire (below); keep a FIXED-side behaviour test for the registry fix on the port |
| vendored comparisons (league_rules, props_models, source_cli_parity) | 3 skip | | retire |
| mirror-guard x2, duplicate-names | 3 fail | stale only once the tree is gone | fix in the delete commit |

## Generators, harnesses, scripts

| item | after deleting the WNBA tree |
|---|---|
| `port_basketball_live_tick.py`, `port_basketball_source_cli.py` | **WNBA is their last arm (NBA retired 10-19): retire both**; FREEZE `wnba/live_tick/` (carries the generator's one FIX, the `current_last_updates` registry parameter) and `wnba/source_cli/` |
| `basketball_source_cli_parity.py` | retire (vendored arm only) |
| `basketball_live_tick_parity.py` | keep: its replay arm pins the ports against recorded vendored output without the tree |
| `basketball_orchestrator_parity.py` | keep (native arm, compare-outputs); its vendored arm dies |
| `basketball_engine_parity.py` | already refuses vendored mode without the tree; `--corpus` recorded is the gate |
| `sync_vendor_upstream.py`, `check_duplicate_module_names.py` baseline, `vendor/upstream_sync.json` | drop WNBA |
| `census_kickoff_hours.py` | reads the vendored `schedule_2026.json` (frozen 09-25): repoint to the data root's schedule |
| `backtest_wnba_lines_props.py` (lane wnba-lines-props-backtest, OPEN) | runs `python -m wnba_betting.cli predict-date` from the vendored repo: repoint to `syndicate.features.wnba.source_cli.cli` (what production runs) -- needs that lane's owner |
| `basketball_scenario_rates.py` etc. | sys.path lines only: inert |
| `unified_daily_update.ps1` WNBA step | throws without `vendor\wnba_betting_repo\app.py`; repoint `--source-root` to `data\wnba_source` as NBA's was |
| `wnba/recon_tools/` | already Syndicate copies (byte-identical); nothing to do |

Claims to clear at prep/delete time: `basketball-scenario-calibration` claims `vendor/wnba_betting_repo/src/wnba_betting/sim/events.py`
(its owner released the NBA twin on 10-20 on the same reasoning); `wnba-lines-props-backtest` owns the backtest script.

## Proposed sequence (as NBA)

1. **Decision (user):** freeze `wnba/live_tick/` and `wnba/source_cli/` as maintained source and retire both generators.
2. **Prep (one lane):** headers + FROZEN note; the test repoints / retirements above; census + Windows runner repoints;
   backtest repoint with its owner; docs. Before/after + tree-absent runs.
3. **Delete:** `git rm -r vendor/wnba_betting_repo` + the 3 delete-step tests + upstream_sync + CLAUDE.md.
4. **Fleet:** archive; the tree leaves with the next fleet ff.

Timing: the WNBA season is over, and P5's switch-on is at the 2027 opener (#694). After this, `vendor/` holds only
`nhl_betting_repo`.
