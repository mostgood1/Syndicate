# Basketball Sim Engine (NBA + WNBA smart-sim) — reference, input state, and operating procedure

> 2026-08-18, lane `basketball-model-owner`. Basketball's copy of what
> `mlb_sim_engine_reference.md` is for MLB and `football_sim_engine_reference.md`
> is for football/NCAAF: the worked example `docs/ai_context/model_engine_standard.md`
> requires per engine.
>
> **Read `model_engine_standard.md` first.** Every number below is `[measured on
> this checkout]` unless marked `[production, dated]`. Per that standard's Sec3b,
> claims about production must name Render as the substrate; this session could
> not reach it live (see Sec 0b) so most numbers here are checkout-only and say so.

---

## 0. The headline

**Basketball's engine is a fourth SHAPE of sim engine in this repo, and the
shape itself is the finding worth documenting before any input number.**

- MLB: flat per-entity dataclass (`BatterProfile`/`PitcherProfile`).
- Football (smartsim2): typed dataclass + one untyped payload dict, five
  independent construction sites.
- Soccer: dict-shaped fields inside a dataclass, one `_first_float(container,
  [keys])` read pattern.
- **Basketball: no flat per-entity dataclass at all.** The only dataclass in
  `vendor/{wnba,nba}_betting_repo/src/*/sim/smart_sim.py` is `SmartSimConfig`
  (`n_sims`, `seed`, `roster_mode`, `use_pbp`) — run-level knobs, not model
  signal. The real per-player signal is a `PlayerPriors.rates` dict keyed by
  `(TEAM, PLAYER_KEY) -> {"pts_pm": ..., "reb_pm": ..., ...}`; the real
  per-team signal is a plain DataFrame loaded straight from a CSV.

**And the fact that actually matters for auditing this engine: importing the
"real" vendor module does NOT mean vendor logic computes the inputs.**
`basketball_props_smart_sim._call_source_simulate_smart_game_local`
(`syndicate/features/shared/basketball_props_smart_sim.py:3842-3995`)
monkeypatches ~20 of the vendor module's own named helper functions —
`_apply_player_priors`, `_team_adj_from_advanced_stats`,
`_compute_player_priors_cached`, `_load_smartsim_total_calibration`,
`_load_intervals_band_calibration`, `_load_intervals_time_profile`,
`_load_player_stat_calibration`, `_rotation_sim_minutes_from_history`,
`_player_split_rate_context`, `_player_career_opponent_rate_context`,
`_opponent_position_rate_context`, `simulate_pbp_game_boxscore`,
`simulate_event_level_boxscore`, `_team_players_from_props`, `_infer_game_id`,
and more — for Syndicate-local ports (`*_local` functions in
`basketball_props_smart_sim.py` and `basketball_props_onnx.py`), for the
duration of one `simulate_smart_game()` call, then restores the originals in a
`finally` block. **Only `simulate_smart_game`'s own possession/quarter
orchestration loop is genuinely vendor code that runs in production; the DATA
computation is Syndicate's own reimplementation, verified independently.**

This is why `scripts/basketball_sim_input_checklist.py` audits the LOCAL PORTS
(`_apply_player_priors_local`, `compute_player_priors_local`,
`_team_adj_from_advanced_stats_local`/`_team_adv_row_local`) rather than the
vendor originals — auditing the vendor functions would answer a question about
code that does not execute. **Verified no drift between the two copies**: the
local ports' literal key lists (`stat_pm_keys`, the 8-key advanced-stats list)
are byte-identical to the vendor originals', checked by AST, not by eye.

---

## 0b. RENDER IS THE SUBSTRATE OF RECORD. Read `model_engine_standard.md` Sec3b first.

**Attempted and could not complete.** `curl https://syndicate-an21.onrender.com/`
returned **HTTP 502** at the time this lane ran (2026-08-18), and
`/api/ops/artifacts/export` on the same host 502'd identically — the web
service was down for reasons outside this lane's scope (not diagnosed here;
not a basketball-model-owner file). Every population number in Secs 3-5 below
is therefore read from the **local git-tracked mirror**
(`data/{wnba,nba}_source/`), which CLAUDE.md is explicit is a lossy,
per-family-desynced cold-start copy, not a production snapshot. The script
prints this caveat on every run rather than silently reporting a checkout
number as if it were live.

**One prior, dated production reading exists and is cited here, not
re-asserted as this session's own measurement** (per the "re-derive
cross-lane numbers" rule — I did not re-verify it, I verified something
different but consistent: see Sec 2 below):

- Lane `sim-engine-phase0-census`, `.syndicate/plan_2026-08-16_sim_scheduling.md`
  lines 397-437, dated 2026-08-15: three real WNBA `smart_sim_2026-08-15_*.json`
  artifacts pulled via `/api/ops/artifacts/stream` all carried the real engine's
  signature (`score`/`intervals`/`rotation_minutes` present) and NONE carried
  the flat stub's fingerprint key (`home_team_total_pts_mean`, present ONLY in
  `_simulate_smart_game_local`'s return dict, `basketball_props_smart_sim.py:720-721`).
  Same document also read `n_sims = 100` directly off those three production
  artifacts, and showed the served `p_home_win`/`p_home_cover`/`p_total_over`
  values were exact multiples of 0.01 (9 of 9) — the quantization signature of
  a 100-draw count, not an inferred config value.

---

## 1. The pipeline, file:line at each hop

```
scripts/refresh_wnba_oddsapi_props.py / refresh_nba_oddsapi_props.py   (daily props refresh)
  smart_sim_n_sims = max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS", 500))
      REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS = "100" in render.yaml:1017-1018
      (comment there: cut from a higher value under live-odds-worker OOM
      pressure -- 2048MB container observed at 100%)
  -> basketball_props_smart_sim.export_props_predictions_with_smart_sim_local()   (:5157)
    -> _smart_sim_worker_init_local / _smart_sim_worker_run_local              (:4282)
      -> _build_local_smart_sim_module(processed_root, league_code)            (:765)
           _import_real_smart_sim_module_local(package_name)                   (:739)
             sys.path.insert(vendor/{pkg}_repo/src); importlib.import_module
             bare `except Exception: module = None`  <-- the #440 fallback trigger
           IF real_module is not None: pins `real_module.paths`, returns REAL module
           ELSE: returns SimpleNamespace(simulate_smart_game=_simulate_smart_game_local, ...)
      -> _call_source_simulate_smart_game_local(smart_sim_module, processed_root, kwargs)  (:3842)
           monkeypatches ~20 helper names onto smart_sim_module (see Sec0)
           calls smart_sim_module.simulate_smart_game(**kwargs)                (:4009)
             REAL PATH: vendor/{pkg}_repo/src/*/sim/smart_sim.py:simulate_smart_game (:3557)
               -> events.py:simulate_pbp_game_boxscore / simulate_event_level_boxscore  [MONKEYPATCHED]
               -> _apply_player_priors  [MONKEYPATCHED to _apply_player_priors_local, :3090]
                    priors from _compute_player_priors_cached [-> compute_player_priors_local,
                        basketball_props_onnx.py:218]
               -> _team_adj_from_advanced_stats  [MONKEYPATCHED to *_local, :3578]
                    -> _load_team_advanced_stats_asof_local (:3461) reads
                       <processed_root>/team_advanced_stats_<season>[_asof_<date>].csv
               -> _load_smartsim_total_calibration / _load_intervals_band_calibration /
                  _load_intervals_time_profile / _load_player_stat_calibration  [MONKEYPATCHED]
                    each reads <processed_root>/<name>.json, optional, None if absent
             FALLBACK PATH (real_module is None):
               _simulate_smart_game_local (:704) -- sums per-player means, NO score/
               intervals/probabilities block, cached identically to a real result
   writes: <processed_root>/smart_sim_<date>_<HOME>_<AWAY>.json
           (allowlisted: `HOT_ARTIFACT_PATTERNS` has `*_source/data/processed/smart_sim_*.json`
            and the `source_artifacts` variant -- artifact_publisher.py:95,173)
   read by: syndicate/features/{nba,wnba}/cards.py's cards_sim_detail_<date>.json build
            (NBA: cards.py:2625 build_cards_sim_detail_payload;
             WNBA: cards.py:2243 build_source_cards_sim_detail_payload, PLUS a raw
             smart_sim_<date>_*.json glob fallback WNBA has and NBA does not,
             cards.py:540-564)
```

**Neither `syndicate/features/nba/*.py` nor `syndicate/features/wnba/*.py`
imports `basketball_props_smart_sim` directly.** The bridge is consumed only
by the offline refresh scripts above, `basketball_props_predictions.py:14`,
and `live_refresh_loop.py:676`. The feature modules read the bridge's OUTPUT
artifact (`cards_sim_detail_<date>.json` / raw `smart_sim_*.json`), never the
bridge itself — the same "workers write, web reads" split CLAUDE.md's
architecture section describes for every other sport.

---

## 2. Level 0 — bridge reachability, the #440 hypothesis made runnable

`todo.md` #440 recorded the shape but not whether it fires. `scripts/
basketball_sim_input_checklist.py`'s Level 0 calls the ACTUAL bridge function
(`basketball_props_smart_sim._import_real_smart_sim_module_local`) for both
packages, in this process, and reports whether it returns the real module or
`None`.

**Measured on this checkout, 2026-08-18:**

```
wnba  package=wnba_betting   REAL ENGINE
nba   package=nba_betting    REAL ENGINE
```

Both packages import cleanly. This corroborates (does not merely repeat) the
2026-08-15 production artifact reading in Sec0b: that was inference from
OUTPUT shape on Render; this is a direct call of the IMPORT MECHANISM on a
different machine. Two independent methods, two dates, same conclusion: **the
fallback is not currently firing.**

**Why it could still fire and why this checklist should keep gating on it:**

- `vendor/{wnba,nba}_betting_repo/src/**` is git-tracked (`git ls-files`
  confirms both `sim/smart_sim.py` paths are tracked, not gitignored) — this
  is NOT the MLB DiskCache trap (gitignored + ephemeral checkout). It ships
  with every deploy.
- The import has no exotic dependency: `smart_sim.py`'s own imports are
  `numpy`, `pandas`, and sibling `wnba_betting`/`nba_betting` modules
  (`smart_sim.py:1-19`); `config.py`'s module-level code is entirely wrapped
  in try/except or path-existence checks (`config.py:20-48`) — nothing raises
  at import time by inspection.
- **But this session's Level 0 result proves the import succeeds on THIS
  machine with THIS `sys.path`/venv, not that it succeeds on the live
  worker's.** A worker-specific path issue (a stale `sys.path` entry, a
  version mismatch between the worker's installed `numpy`/`pandas` and what
  the vendored code expects) would not be caught by a local reachability
  test — only a fresh production artifact read (Sec0b's method) can rule
  that out, and that read is now 3 days old.
- **There is a second, structurally identical fallback** for the possession
  engine: `_import_real_events_module_local` (`basketball_props_smart_sim.py
  :3012-3052`) has the same bare `except: module = None` shape, feeding
  `_simulate_pbp_game_boxscore_local`/`_simulate_event_level_boxscore_local`.
  Its own code comment (`:3070-3076`) says the flat stand-in "produced
  identical score_q p10/p50/p90 across every simulation" — i.e. a
  *distributionally degenerate* fallback, a different and arguably worse
  failure mode than the game-level stub's missing keys, because it would NOT
  be caught by the `home_team_total_pts_mean` fingerprint check. **Not
  independently checked for reachability in this pass** — same import
  mechanism, same packages, so Level 0's result is suggestive but not proof
  for this second fallback; flagged as a follow-up in Sec6.

---

## 3. Level 1 — PlayerPriors per-minute rate keys

**CONSUMED** (AST over `_apply_player_priors_local`'s own literal
`stat_pm_keys` list, `basketball_props_smart_sim.py:3171-3185`) and
**PRODUCED** (AST over `compute_player_priors_local`'s own literal
`stat_cols` dict, `basketball_props_onnx.py:255-256`) are **identical, 13
keys**: `pts_pm reb_pm ast_pm stl_pm blk_pm tov_pm threes_pm threes_att_pm
fga_pm fgm_pm fta_pm ftm_pm pf_pm`. No drift.

**Population, measured on this checkout** — `compute_player_priors_local` run
for real against `boxscores_history.csv` (the `player_logs.csv` fallback path;
neither mirror has a `player_logs.csv`), `days_back=21`, as-of the last date
each mirror's history actually covers:

| league | as-of | rated (team, player) rows | all 13 keys populated |
|---|---|---|---|
| WNBA | 2026-07-08 (history: 2026-04-25..2026-07-07) | 321 | **56.1%** |
| NBA | 2026-05-25 (history: up to 2026-05-24) | 611 | **82.7%** |

**A methodology note earned mid-build, worth keeping**: the first version of
this measurement tested `value > 0.0` per key and reported `blk_pm`/`stl_pm`/
`threes_pm` as thinly populated (39.9%/49.2%/43.9% for WNBA) — because a
rostered, rated player who genuinely blocked/stole/hit zero threes in the
window has e.g. `blk_pm: 0.0`, a REAL present value, and `> 0.0` cannot tell
that apart from the key never being set. That is the model_engine_standard
Sec4.2 trap (`.get(key, 1.0)`) recurring at 0.0 instead of 1.0. Fixed to test
dict membership (`key in rr`) instead, which is the correct test given
`compute_player_priors_local` sets all 13 keys together in one loop only when
`games_played >= min_games and min_mu >= min_minutes_avg`
(`basketball_props_onnx.py:308-312`) — below that threshold a player carries
`{"min_mu": ...}` alone. **All 13 keys read identically per league** after the
fix (56.1% / 82.7% flat across all keys), which is the expected shape once
population is measured correctly: it is one binary gate (cleared threshold or
not), not 13 independent ones.

**The WNBA/NBA gap (56.1% vs 82.7%) is real and unexplained here** — could be
season-length/roster-churn differences (WNBA's shorter season and smaller
per-team rosters plausibly produce more below-threshold two-way/injury-
replacement entries per capita), could be a mirror-completeness difference.
**Not investigated further in this pass; flagged in Sec6.**

Below-threshold players are the correct, by-design analogue of MLB's
`EXPECTED_SPARSE` fields (`availability_mult`, `vs_pitcher_*`): a real
population floor exists (`min_games=2, min_minutes_avg=4.0`,
`basketball_props_onnx.py:120-...`) and clearing it is meaningful, not a
defect in the ones that don't.

---

## 4. Level 2 — team advanced-stats keys, and a confirmed WNBA gap

**CONSUMED** (AST over `_team_adv_row_local`'s own literal 8-key `for key in
[...]:` loop, `basketball_props_smart_sim.py:3535`): `pace off_rtg def_rtg
efg_pct tov_pct orb_pct ft_rate games`.

**Population, measured on this checkout:**

| league | season/as-of | teams | pace/off_rtg/def_rtg/efg_pct/tov_pct/orb_pct/ft_rate | games |
|---|---|---|---|---|
| WNBA | 2026, as-of 2026-07-08 | 15 | **100%** | **0%** |
| NBA | 2026, as-of 2026-05-30 | 30 | **100%** | **100%** |

**Confirmed by direct column inspection, not inference**: WNBA's
`team_advanced_stats_2026_asof_*.csv` producer emits 12 columns (`team pace
off_rtg def_rtg efg_pct tov_pct orb_pct ft_rate fg3a_rate fg3_pct ts_pct
ast_per_100`) — **no `games`, no `source` column at all.** NBA's producer
emits the same 12 plus `games` and `source` (`player_logs` observed).
`_team_adv_row_local` reads `games` unconditionally into its output dict
(`float(row.get("games"))` -> `NaN` when the column is absent) alongside the
seven real multiplier inputs, with no per-key guard. **Not currently observed
to cause a wrong number**: grepped `basketball_props_smart_sim.py` for any
downstream read of the resulting `games` value (`.get("games")`, `["games"]`)
after `_team_adv_row_local` returns it — zero matches. Nothing branches on it
today. **But it is a genuinely CONSUMED, genuinely UNPOPULATED (for WNBA)
field by the standard's own definition**, and the moment anything adds
sample-size-weighting on `games` (a plausible next step — 15 teams' small-N
advanced stats are exactly where a confidence weight would help), it goes
silently inert for one league and not the other with no log line, the
`.get(key, 1.0)`-shaped failure this whole standard exists to catch before it
ships. **New todo.md item filed for this — see Sec6.**

**2026-08-18, same day, root-caused and code-fixed — the paragraph above
describes the symptom correctly but attributes it to the wrong layer.** Read
`compute_team_advanced_stats_from_boxscores`/`_from_player_logs` in full for
BOTH leagues (`vendor/{nba,wnba}_betting_repo/src/.../advanced_stats_{boxscores,
player_logs}.py`): they are logically identical between NBA and WNBA and both
emit `games`/`source` unconditionally. **The producer is not the bug.** The bug
is in the caller: `_ensure_team_advanced_stats_asof`
(`vendor/{nba,wnba}_betting_repo/src/.../cli.py`, invoked automatically before
every `smart-sim`/`smart-sim-date` run at both leagues' call sites) treated any
non-zero-size file already sitting at the exact `team_advanced_stats_<season>
_asof_<date>.csv` path as "done" and returned it unrebuilt — including a file
written under the pre-`games`-column schema. WNBA's mirror as-of files predate
that schema change and have been cached-as-stale ever since; NBA's sampled
file simply didn't collide with a pre-existing stale path at the date checked,
which is why the population table above reads 100%/0% rather than exposing
this as a shared latent bug.

**Fix**: added `_team_adv_stats_cache_is_fresh()` (header-only `games`+`source`
column check) to both vendor `cli.py` files; `_ensure_team_advanced_stats_asof`
now rebuilds on a stale-schema hit, not just on missing/0-byte. **Measured
against real data, not simulated**: invoked the fixed function directly
against this checkout's real cached WNBA boxscores
(`vendor/wnba_betting_repo/data/processed/`, the actual path
`paths.data_processed` resolves to with no env override) for
`season=2026, as_of=2026-07-15` — output has all 14 columns, `games` populated
6-8 per team, `source=boxscores`, where the pre-fix file at the legacy filename
had 12. Re-invoking immediately after leaves the file's mtime unchanged,
confirming the cache-hit path still short-circuits correctly and this isn't a
rebuild-every-call regression. `tests/test_basketball_props_smart_sim_advanced_stats.py`
(5/5) unaffected.

**Not yet true in production**: this fix is code-only in this checkout. Until
it's committed and `refresh-worker` is deployed (behind the two-lock deploy
protocol), Render's mounted disk keeps building/serving the pre-fix stale
files, and the git-tracked mirror under `data/wnba_source/source_artifacts/
data/processed/` — deliberately left untouched rather than hand-edited to
"look" fixed, per CLAUDE.md's Render-is-truth rule — will keep showing the old
12-column schema, and `scripts/basketball_sim_input_checklist.py` will keep
reading its Level 2 WNBA alarm, until the fix deploys, a smart-sim run rebuilds
a cached path for real, and the mirror-refresh script pulls the corrected file
down. That chain completing is the actual close condition for this item — the
code fix alone is not the close condition.

**A second, independent finding surfaced getting here, also worth recording**:
this checkout has TWO git-tracked copies of WNBA's `team_advanced_stats`
family — `data/wnba_source/data/processed/` (both its `team_advanced_stats_
2026.csv` and its one as-of file are **0-byte**, matching the "partial/failed
write" case the loader's own code comment already anticipates,
`basketball_props_smart_sim.py:3471-3478`) and `data/wnba_source/
source_artifacts/data/processed/` (real, non-empty as-of snapshots
2026-07-03..2026-07-15, byte-identical `boxscores_history.csv` to the other
copy). The checklist targets the latter for WNBA and says so in-line — this is
CLAUDE.md's per-family mirror-desync trap, hit directly: which of two
git-tracked local copies is "the" mirror is not a fixed answer even within one
sport's own artifact family.

---

## 5. Level 3 — optional per-game calibration artifacts: absent, and unwired

Four JSON calibration layers exist as **optional** reads in the monkeypatched
local ports (`_load_smartsim_total_calibration_local`,
`_load_intervals_band_calibration_local`, `_load_intervals_time_profile_local`,
`_load_player_stat_calibration_local`, all in `basketball_props_smart_sim.py`)
— each returns `None`/`{}` and the caller skips the adjustment when the file is
absent. Genuinely optional by design, unlike a neutral-default multiplier.

**Measured on this checkout: all four are ABSENT for both leagues:**

```
smart_sim_total_calibration.json   ABSENT (wnba, nba)
intervals_band_calibration.json    ABSENT (wnba, nba)
intervals_time_profile.json        ABSENT (wnba, nba)
player_stat_calibration.json       ABSENT (wnba, nba)
```

**Each has a real builder tool**, present for both leagues:
`vendor/{wnba,nba}_betting_repo/tools/build_intervals_band_calibration.py`,
`build_intervals_time_profile.py`, `build_player_stat_calibration.py`
(confirmed present by file listing; `smart_sim_total_calibration.json` has no
matching `build_*` tool found by name — its only other reference besides the
reader is the reader itself, so either its builder is named differently or it
has never had one).

**None of the three found builders is referenced anywhere under `scripts/`**
(grepped `scripts/` for all three tool names — zero matches) **or in
`live_refresh_loop.py`** (grepped — zero matches). This is football's
"unwired payload" shape in a different register: not a missing argument at a
call site, but a builder that exists, is checked out, and — as far as this
session's read of the orchestration layer shows — has no scheduled caller
anywhere in the daily pipeline. Whether it was ever run manually and whether
its output should be scheduled is a product decision this lane does not make;
recorded as an open item (Sec6) rather than fixed, per the lane's scope.

---

## 6. Open items / follow-ups from this pass

1. **`#440` (existing)** — bridge fallback reachability. Status upgraded from
   "hypothesis" to "measured negative twice, from two different methods and
   machines, 3 days apart" — see Sec2. Recommend keeping OPEN with a lower
   urgency tag rather than closing outright, because Sec2 also names a real
   gap in the proof: no worker-specific (as opposed to this-checkout)
   reachability check exists, and the sibling `events` fallback (Sec2, last
   bullet) has never been checked at all.
2. **`#461` — WNBA `team_advanced_stats.games` gap, root-caused and code-fixed
   same day** (Sec4). Not a producer omission after all — a stale-schema
   cache-guard in `_ensure_team_advanced_stats_asof` (both leagues, same vendor
   `cli.py` shape). Fix verified against real cached data in this checkout;
   NOT yet live on Render and NOT yet reflected in the git-tracked mirror —
   closing this item for real requires a deploy + a fresh smart-sim run +
   a mirror refresh, in that order. See todo.md `#461`'s addendum.
3. **New: three calibration-artifact builder tools exist and appear
   unscheduled** (Sec5). Lower severity (graceful degradation, not a silent
   wrong number) but recorded because "builder exists, never runs" is exactly
   football's `#457` shape and worth a deliberate decision rather than
   quietly staying that way.
4. **Not investigated in this pass**: why WNBA's player-priors population
   rate (56.1%) is meaningfully lower than NBA's (82.7%) — Sec3.
5. **Not investigated in this pass**: `_simulate_pbp_game_boxscore_local`'s
   fallback reachability independent of the game-level fallback (Sec2, last
   bullet) — same import mechanism is likely but not confirmed to behave
   identically.
6. **Cross-checked per the lane brief, does NOT affect this checklist's
   scope**: the 2026-08-16 `learnings.md` entry on WNBA publishing
   `run_margin_dist`/`total_runs_dist` under MLB's key names with a 3-point
   quantile shape MLB's reader cannot parse. That is a CONSUMER-side
   (cross-sport market-board) defect in how another engine's reader
   interprets WNBA's OUTPUT artifact — it is downstream of everything this
   engine-input checklist audits (which stops at what feeds the simulation,
   not what reads its output), and it is not owned by this lane's file set
   (`basketball_market_board.py` reads/writes are in scope to READ but the
   MLB-side reader is not a basketball file). No new finding added here;
   confirmed via the citation in the lane brief and left alone.
7. **Not measured**: production's actual live env-var value for
   `REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS` at the time of this session — the
   `render.yaml` value (`"100"`, `render.yaml:1017-1018`, with a comment
   dating it to a live-odds-worker OOM fix) and the 2026-08-15 production
   artifact reading (Sec0b) agree, but per CLAUDE.md `render.yaml` is
   declared config, not a live read, and this session could not reach the
   live `/v1/services/<id>/env-vars` API (502). Two independent sources
   agreeing is treated here as strong, not certain, evidence.

---

## 7. Standard compliance — where this engine stands

| Sec5 requirement | status |
|---|---|
| Input inventory (`consumed?` / `populated%`) | **DONE** — Secs 3-5 |
| Gating checklist script, exits 1 | **DONE** — `scripts/basketball_sim_input_checklist.py` |
| Pipeline trace, file:line, incl. what it writes | **DONE** — Sec1 |
| Every input disk-backed via `SYNDICATE_DATA_ROOT` | **PARTIALLY AUDITED** — `refresh_{wnba,nba}_oddsapi_props.py` overrides `WNBA_BETTING_DATA_ROOT`/`NBA_BETTING_DATA_ROOT` to a `--source-root`-derived path per invocation (not the vendor-repo-relative default), which is the right shape; the CLI arg's own upstream resolution back to `SYNDICATE_DATA_ROOT` was not traced end-to-end in this pass |
| Every input allowlisted in `HOT_ARTIFACT_PATTERNS` | **NOT SATISFIED, confirmed** — grepped `syndicate/features/shared/artifact_publisher.py` for `team_advanced_stats`, `player_logs`, `player_priors`, and all four calibration filenames: **zero matches for all of them.** Only the final `smart_sim_*.json` OUTPUT is allowlisted (`:95,173`); every INPUT this checklist audits is unauditable through `/api/ops/artifacts/*`. New todo item filed. |
| Reuse/caching flags documented + rebuild procedure | **NOT AUDITED** — no MLB-style `--use-roster-artifacts` analogue found; `PlayerPriors`/team-advanced-stats are recomputed per call in the local ports (`_compute_player_priors_cached_local` has a cache but keyed per (date, days_back), not a persistent artifact-reuse flag) |
| Reachability test per flagged feature (`off != on`) | **DONE for Level0** (Sec2); not done for the `events` sibling fallback or for the four Level3 calibration flags |
| Mechanisms vs estimators, with the re-fit obligation | **NOT APPLICABLE THIS PASS** — no mechanism was added or proposed; nothing to re-fit |
| A market-relative scoreboard | **NOT DONE** — out of this lane's scope; see `vendor/{wnba,nba}_betting_repo/tools/audit_slate_prob_backtest.py` for the closest existing instrument (Brier/calibration against a ledger, not gated) |
| Known-sparse fields documented with reasons | **DONE** — Sec3 (below-threshold players), Sec5 (optional calibration layers) |

**Not audited is not "fine."** The `HOT_ARTIFACT_PATTERNS` gap in particular
means every number in Secs 3-5 could ONLY be read from this local, stale,
per-family-desynced checkout — there is no way to ask Render the same question
today even when it is reachable.
