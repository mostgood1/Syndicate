# MLB engine, tools and live-lens code: frozen from vendor, maintained here

Since 2026-10-19 (lane `mlb-vendor-deletion-prep`, user decision "freeze them"), three trees in this directory are
Syndicate's own **source**: edit them directly. They began as copies of `vendor/mlb_bettingv2`
(mostgood1/MLB-BettingV2), **frozen at Syndicate commit `988fa33d` (2026-10-09)**, the last commit to touch the
vendored tree. Before then they were generated and `--check`'d against it.

| tree | what it is | origin |
|---|---|---|
| `sim_engine/` | the MLB Monte Carlo engine, every module | whole files, verbatim |
| `native/tools/` | the 20 tools scripts the daily sim, the season-manifest launcher, the engine-input producers and the live lens reach | whole files, verbatim |
| `live_lens_port/app_slice.py` | the slice of the vendored Flask app (`tools/web/flask_frontend.py`) the live lens and the daily sim's web helpers use | a `symtable` closure, statements verbatim, behind the app's own imports |

The generators (`scripts/port_mlb_sim_engine.py`, `scripts/port_mlb_live_lens.py`), the parity harnesses
(`scripts/mlb_live_lens_parity.py`, `scripts/mlb_daily_sim_parity.py`) and the one-shot data migration
(`scripts/migrate_mlb_engine_data.py`, run in production 2026-10-16 18:42Z) are retired. They live in git history,
with their results in `.syndicate/deploys.md` (lanes `mlb-live-lens-native-p1`, `mlb-sim-engine-native-p2`,
`mlb-daily-sim-native-p3`, `mlb-engine-data-native-p4`). Nothing is pulled from upstream any more:
`scripts/sync_vendor_upstream.py` is retired (2026-10-20, vendor/ is empty), and the upstream repo is BEHIND this copy
(`.syndicate/findings_2026-10-19_mlb_vendor_deletion_scope.md`).

## Conventions the copies carry (keep them when editing)

- **DATA root: `engines/mlb/`** (repo-relative, the same depth as the old `vendor/mlb_bettingv2`). A module that
  locates data off its own path does it through `_ENGINE_FILE`: the module's path *as if* its tree sat at
  `engines/mlb/`, so `Path(_ENGINE_FILE).resolve().parents[k]` means what `parents[k]` meant in the vendored tree.
  Concretely, `parents[1]`/`[2]` reach `engines/mlb` (its `data/`, `.env`) and `parents[4]` reaches the Syndicate
  repo root (its `data/`). Do not "simplify" it to `Path(__file__)`: the files sit at a different depth, and every
  data root would silently move.
- **CODE root: `_NATIVE_ROOT`** (`syndicate/features/mlb/native`). Scripts launch other scripts as
  `_NATIVE_ROOT / "tools" / ...`, never off the data root.
- **sys.path: `_SYNDICATE_ROOT`.** Scripts put the Syndicate repo root on `sys.path`, never a vendored one, so a
  stray `from sim_engine ...` fails loudly instead of loading another copy.
- **Imports are absolute Syndicate paths:** `syndicate.features.mlb.sim_engine...`,
  `syndicate.features.mlb.native.tools...`, and `...live_lens_port.app_slice` for the old `tools.web.flask_frontend`.
- Runtime state the engine writes under `engines/mlb/data/` (roster registry, statcast caches) is gitignored. Only
  the 12 engine inputs there are tracked (added with `--force`).
- `"tool": "tools/<x>.py"` provenance labels in outputs are DATA and kept as they were.

## The engine standard still applies

`docs/ai_context/model_engine_standard.md`: the input checklist (`scripts/sim_input_checklist.py`, which audits THIS
engine) and the file:line trace in `docs/ai_context/mlb_sim_engine_reference.md` (re-derived on these files
2026-10-19) must follow every change here.

## Edits made here that the vendored tree does not have

These are behaviour, not plumbing. Before the freeze they were TOOLS_EDITS in the generator; now they are just code.

- `native/tools/eval/settle_locked_policy_cards.py` (lane `mlb-postponed-grading`, user decision 2026-10-19,
  commit `a6c32498`): StatsAPI files a postponed / cancelled / suspended game under `abstractGameState` "Final"
  at 0-0. `_feed_is_final` refuses a game that was not played (`syndicate.features.mlb.game_status.not_played_reason`);
  `_load_feed` never returns an off-date final nor caches an off-date fetch under the slate's path; `_settle_card`
  raises "game rescheduled off slate date". Tests: `tests/test_mlb_game_status.py`.
