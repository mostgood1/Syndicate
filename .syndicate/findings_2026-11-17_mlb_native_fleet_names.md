# MLB native tools: the Render names became fleet names

`[2026-11-17 ~7:20-8:10 PM CST, lane mlb-native-fleet-names, session fea5cdfa; todo #766 follow-up]`

Started from the parent session (`local_8aba9e1c`) after lane `render-name-cleanup` closed and
left this family on purpose (its findings, "Left on purpose (names)"). **Names only.** The base
URLs have pointed at the fleet (`http://127.0.0.1:10000`) since render-retirement `193df776e`.
Nothing touched the fleet, nothing was loaded, no Render call. **Betting change: no** (when an ff
carries it: the ops-report key names and two CLI spellings change; no bet is placed, sized, held
or exited differently).

## The mapping, and the rule behind it

`render` -> `fleet` wherever the name meant "production", so an old name predicts its new one.
Two exceptions: the base-URL normaliser became `_normalize_base_url` (the name
render-name-cleanup already gave its twin in `scripts/refresh_mlb_oddsapi.py`), and the
page-artifact check became `page_...` (it validates local artifacts the pages need; nothing in
it talks to a platform).

**Every old CLI flag is still accepted** (argparse alias, same `dest`), and so is the old
`--source render-sync` value (an extra choice, normalised to `fleet-sync`). **Both renamed
scripts are shims** at the old path: they run the same CLI, and `from <old module> import
<old name>` resolves to the renamed object (module `__getattr__`, old->new name map).

### Rename table, with every consumer checked

Consumers were searched with `git grep` over the whole repo (code, tests, templates, `static/`,
scripts, `.claude/`, `.syndicate/`, `docs/`, `reports/`) and `~/.claude/scheduled-tasks/*/SKILL.md`
(case-sensitive, every old name: **0 hits**). "In-repo readers" excludes the defining file.

| old | new | where | in-repo readers / callers | compat kept |
|---|---|---|---|---|
| `eval/sync_render_live_lens_history.py` | `eval/sync_fleet_live_lens_history.py` (`git mv`) | native tools | `tune/export_live_pitcher_projection_dataset.py` (import, moved) | **shim** at the old path (runs the CLI; old names import) |
| `sync_render_live_lens_history()` | `sync_fleet_live_lens_history()` | sync module | export script (moved) | via the shim |
| `_infer_render_base_url()` (3 copies) | `_infer_fleet_base_url()` | `daily_update.py`, sync module, smoke tool | export script (moved); each file's own calls | via both shims |
| `_normalize_render_base_url()` | `_normalize_base_url()` | `daily_update.py` | own calls only | none needed (private) |
| `smoke/smoke_render_frontend.py` | `smoke/smoke_fleet_frontend.py` (`git mv`) | native tools | `daily_update.py` launches it by path (moved) | **shim** at the old path |
| smoke User-Agent `mlb-betting-v2-render-smoke/1.0` | `mlb-betting-v2-fleet-smoke/1.0` | smoke tool | none (no code filters on it) | none |
| `--validate-render-frontend` | `--validate-fleet-frontend` | `daily_update.py` | `scripts/run_mlb_daily_sim_job.py:310` and `scripts/unified_daily_update.ps1:4108` (moved); the next-day relaunch (moved) | **alias** |
| `--render-validation-base-url` / `-cron-token` / `-timeout-seconds` | `--fleet-validation-*` | `daily_update.py` | none outside the file | **alias** |
| next-day relaunch strip list | strips BOTH spellings of all four | `daily_update.py` `_build_next_day_ui_daily_command` | — | — |
| `--render-base-url` / `--render-cron-token` / `--render-timeout-seconds` | `--fleet-base-url` / `--fleet-cron-token` / `--fleet-timeout-seconds` | the 3 tune scripts | `daily_update.py` `_refresh_live_pitcher_corrections_stage` (moved) | **alias** |
| `--sync-render` | `--sync-fleet` | the 3 tune scripts | none | **alias** |
| `--source render-sync` | `--source fleet-sync` | the 3 tune scripts | `daily_update.py` (moved) | **old value still a choice**, normalised |
| `_maybe_sync_render_history(sync_render=, render_base_url=, render_cron_token=, render_timeout_seconds=)` | `_maybe_sync_fleet_history(sync_fleet=, fleet_base_url=, fleet_cron_token=, fleet_timeout_seconds=)` | export script | the 2 fit scripts (moved) | none (private, no other caller) |
| `_iter_render_sync_projection_rows()` | `_iter_fleet_sync_projection_rows()` | export script | own call | none |
| `_run_render_frontend_validation_stage()` | `_run_fleet_frontend_validation_stage()` | `daily_update.py` | own call | none |
| `_validate_render_page_artifacts()` | `_validate_page_artifacts()` | `daily_update.py` | own call | none |
| args dests `validate_render_frontend`, `render_validation_*` | `validate_fleet_frontend`, `fleet_validation_*` | `daily_update.py` | only `daily_update.py` reads them (`getattr`) | via the flag aliases |

### Report keys and served values — readers listed before renaming

| old | new | written to | readers | twin? |
|---|---|---|---|---|
| ops-report stage `render_frontend_validation` | `fleet_frontend_validation` | `daily/ops/daily_ops_<date>.json` | **none.** The ops report's only readers are the two `_workflow_summary`s (`mlb/cards.py`, `live_lens_port/app_slice.py`: read `errors`, `warnings`, `status`, and any stage's `command` for `--sims`) and `app_slice._prior_day_settlement_from_ops_report` (reads `prior_day_card_settlement`). `.syndicate/state_mlb.md:822/:827` names it in a 2026-08 stage audit (prose). | **no** |
| stage field `render_base_url` (`prior_day_live_lens`, `live_pitcher_corrections`) | `base_url` | same report | none | **no** |
| stage `source` value `render_api` | `fleet_api` | same report | only `daily_update.py`'s own two comparisons in the same call (moved) | **no** |
| stage field `render_artifact_validation_error` | `page_artifact_validation_error` | same report | none | **no** |
| error text `render artifact validation failed: ...` | `page artifact validation failed: ...` | report `errors` | none parses it | **no** |
| validation text `render frontend validation failed` | `fleet frontend validation failed` | report `validation_errors` | **the two `_workflow_summary`s filter `errors` by this prefix** | **readers accept BOTH prefixes** (reports written before today keep the old text) |
| fitter artifact key `renderSync`, export summary key `renderSync` | `fleetSync` | `data/eval/live_pitcher_{outs,strikeouts}_correction.json`, stdout | **none**: `app_slice` reads only `model` and `feature_names` from the strikeouts artifact; `daily_update.py` reads `rows`, `date_window`, `*_metrics` from the fitter's stdout | **no** |
| fitter artifact `source: "render-sync"` | `"fleet-sync"` | same artifacts | none | **no** |
| dataset row `source: "render_sync_archive"` | `"fleet_sync_archive"` | export dataset rows | only the export's own `by_source` summary | **no** |

**Why no twins.** The rule is a twin where something outside the repo may read the key. Nothing
does: 0 hits in the ledger (beyond prose), 0 in scheduled tasks, and the ops report is not served
by any route as a whole (cards serve only the `_workflow_summary` digest). The 50 git-tracked
mirror ops reports (`data/mlb_source/data/daily/ops/`) carry the old keys (47
`render_frontend_validation`, 100 `render_base_url`) and nothing reads those keys from them
either, so old files need no migration. A twin would also have kept the very name this lane
removes. If a reader appears later, the old keys are in every report written before
2026-11-17 and in no report after.

## `live_lens/render_sync/` on disk — KEPT, not migrated, not aliased

Decision: **keep the directory name.** It is data on the fleet's data root
(`~/syndicate-prod/data/.../live_lens/render_sync/`), and it is named by
`syndicate/features/shared/artifact_publisher.py:154` and `:702` (allowlists; that file is held,
section-scoped, by OPEN lane `syndicate-decision-engine`), `scripts/refresh_mlb_oddsapi.py:52`,
`:258`, `:416`, `scripts/refresh_mlb_source_mirror.ps1:312`, and
`scripts/unified_daily_update.ps1:1241`, `:1263`, `:3343`. A new name would either split the
history in two (every reader globbing both forever) or need a migration on the fleet, which this
lane may not touch. In code the name now lives in one named constant per tool tree,
`LIVE_LENS_SYNC_DIRNAME` (sync module, imported by the export script) and
`_LIVE_LENS_SYNC_DIRNAME` (`daily_update.py`), each with the reason beside it. **A rename is a
task of its own:** a drained window, `mv` on the fleet's data root, both names in the allowlists
for one cycle, then the readers above. Not proposed: nothing gains from it but the name.

## Rollout safety (when an ff carries this)

The aliases are what make a mixed state safe. An already-running `run_mlb_daily_sim_job.py`
launches `daily_update.py` from disk: new disk + old caller passes `--validate-render-frontend`
(alias, accepted). `daily_update_multi_profile.py` forwards unknown flags back into
`daily_update.py --workflow core`, so either spelling round-trips. The next-day relaunch strips
both spellings. Nothing in this lane changes which bets are placed.

## Tests

`[2026-11-17 ~7:55 PM CST, this worktree, Idle priority]` `tests/test_mlb_native_fleet_names.py`
(NEW, 18 cases) + `tests/test_mlb_native_tools.py` + `tests/test_run_mlb_daily_sim_job.py`:
**52 passed, 2 subtests passed** in 136 s. The new file checks, per name: old and new flags parse
to the same dest (by running each `main()` to its `parse_args`); `daily_update.py` passes only new
names to the fitters AND each fitter's parser accepts exactly those; the next-day relaunch strips
both spellings; the validation stage launches `smoke_fleet_frontend.py` (exists); the prior-day
sync still writes `live_lens/render_sync/`; `fleet-sync` and `render-sync` read the same rows;
the sync failure text still contains `no archived observation rows were found` (the substring
`daily_update.py` downgrades to a skip); both shims import the old names and run the same
`--help`; both `_workflow_summary`s count both prefixes. `test_mlb_native_tools.py`'s
`test_every_launched_script_is_a_native_file` covers the new smoke path.

## Left in place

- The old spellings themselves (aliases, the `render-sync` choice, the two shims).
- Dated incident comments in `daily_update.py` (`:1064`, `:1094`, `:1982`, `:4760`),
  `eval/reconcile_daily_sim_artifacts.py:841`, `scripts/refresh_mlb_oddsapi.py` (6) and
  `scripts/run_mlb_daily_sim_job.py` (4): history, same policy as render-name-cleanup.
- `_render_recap_markdown` (`eval/build_season_*_manifest.py`): the verb, not the platform.
- `reports/ops_jobs.json`, `reports/intelligence/status_response_cache.json`,
  `reports/daily_update/2026-06-05/...`: recorded commands carrying the old flag (generated output).

## Noticed, not changed

- `_refresh_live_pitcher_corrections_stage` records each fitter command in the ops report, and
  that command carries the cron token (`--fleet-cron-token <token>`, `--render-cron-token` before
  today) whenever one is set; the frontend-validation stage records `--cron-token` the same way.
  Pre-existing. The 50 git-tracked mirror copies carry no token (checked: 0 `cron-token` hits);
  the fleet's own copies were not read (fleet not touched). Worth a redaction pass of its own.
