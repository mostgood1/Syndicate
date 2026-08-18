# The Football Sim Engine — smartsim2 (NFL + NCAAF) reference

> Written 2026-08-18, lane `football-model-owner`. This is football's copy of
> what `mlb_sim_engine_reference.md` is for MLB: the worked example that
> `docs/ai_context/model_engine_standard.md` §2 makes mandatory.
>
> **Read this before changing anything under `syndicate/features/football/`.**
> The single most important fact in it is in §3, and it is not visible from any
> test, log line, or UI surface.

---

## 0. The headline, measured

**The engine has a fully-built advanced-analytics intake. Every production
entrypoint passes it nothing.**

`scripts/football_sim_input_checklist.py` (this engine's gate, §6) reads the
engine's own call sites structurally and finds **9 feature blocks / 65 keys**
that `drive_priors.py` consumes. It then reads every construction site of
`SmartSim2SimulationInput`:

| entrypoint | kind | passes `feature_generation_payload`? |
|---|---|---|
| `scripts/generate_smartsim2_nfl_projections.py` | **production** | **NO** |
| `scripts/generate_smartsim2_nfl_preseason_projections.py` | **production** | **NO** |
| `scripts/generate_smartsim2_ncaaf_projections.py` | **production** | **NO** |
| `scripts/backtest_nfl_preseason_projection.py` | analysis | no |
| `scripts/analyze_nfl_injury_adjustment_sides.py` | analysis | no |
| `.../smartsim2/calibration/baseline_audit.py` | analysis | **passes one, and it is INERT** |

**0 of 3 production entrypoints.** So `build_drive_priors` receives `payload =
{}` on every NFL and NCAAF game the platform serves, every one of the 65 keys
falls to a neutral default, and the only signal reaching the Monte Carlo is the
four rating scalars (`home/away_offense_rating`, `home/away_defense_rating`) plus
`pace_seconds_per_play`'s hardcoded 24.0.

### It is not a small effect

Measured 2026-08-18 by running `build_drive_priors` with an empty payload (what
production does) against the same game with the payload the feature layer can
already supply — **21 of 21 drive-prior fields move**:

| prior | production (empty) | with payload | delta |
|---|---|---|---|
| `offense_index` | 0.560 | 0.785 | +0.225 |
| `defense_index` | 0.475 | 0.584 | +0.109 |
| `pace_index` | 0.400 | 0.150 | −0.250 |
| `returning_production_index` | **0.500** | 0.720 | +0.220 |
| `coach_continuity_index` | **0.500** | 0.900 | +0.400 |
| `player_usage_index` | **0.250** | 0.543 | +0.293 |
| `market_prior_index` | **0.500** | 0.368 | −0.133 |
| `transfer_volatility_index` | **0.200** | 0.300 | +0.100 |
| `drive_success_probability` | 0.349 | 0.410 | +0.060 |
| `touchdown_probability` | 0.183 | 0.223 | +0.040 |
| `expected_clock_seconds` | 150.96 | 175.47 | +24.51 |

The bolded values are the hardcoded neutral constants in `drive_priors.py`.
**Every NFL and NCAAF game in production carries those identical numbers.**

At the score level, 400 seeds per arm on one game through `simulate_game` with
`NFL_CALIBRATION_PROFILE`:

| | empty (production) | with payload | delta |
|---|---|---|---|
| margin | 1.667 | 0.542 | **−1.125** |
| total | 48.428 | 46.742 | **−1.685** |
| home win% | 54.25% | 47.75% | **−6.50 pts** |

A 6.5-point win-probability swing is far larger than any edge this platform
claims to find.

### The one payload that IS passed is inert — and it nearly fooled this gate

`calibration/baseline_audit.py:287` *does* pass a `feature_generation_payload`.
It contains `{game_id, season, week, market_total, market_spread_home}` — and
**not one of those is a key the engine reads.** `_extract_block` wants a nested
block named `market_features`/`market`/`betting`; a flat `market_total` is
invisible to it.

The first version of the checklist asked only *"is a payload passed"* and
reported this site as **wired**. It now checks the payload's literal keys against
the consumed block names and reports `INERT PAYLOAD`. **A gate that asks about
presence rather than reachability green-lights exactly the half-fix it exists to
catch** — and the half-fix here is the likely shape of a careless wiring pass.

### Read §5 before "fixing" this

The delta above is **not** the improvement available from wiring the payload in.
The NFL profile is a *frozen calibrated* profile fit with the payload empty, so
wiring it in is adding mechanisms to a calibrated engine. See §5.

---

## 0b. RENDER IS THE SOURCE OF TRUTH FOR THIS ENGINE. Read `model_engine_standard.md` §3b first.

**Every number in this document that describes production was read from Render** —
the served payload, the live env-vars API, or the deployed blob's content. Where a
number came from a local checkout it is labelled as such and is a statement about
the checkout only.

**This engine is where that rule was earned.** Twice in one session a local read
produced a confident, wrong, published claim:

- *"the NCAAF feature loader returns zero games"* — true locally, **false in
  production**, which serves 16. Retracted (§4).
- *"every input block is 0% populated"* — a **1-game** degenerate load. The real
  load is **272 games**, three blocks at **100%** (§3).

**Reading football facts, correctly:**

| question | command |
|---|---|
| what the board serves | `curl -s "https://syndicate-an21.onrender.com/ncaaf/api/cards?week=1"` |
| whether the model reached it | `.games[].predictions.home_mean` non-null on that payload |
| whether the board truncated | `.board_row_counts` on that payload (`truncated`, `dropped`) |
| whether an input artifact exists | `/api/ops/artifacts/export?path=...` with `ADMIN_TOKEN` |
| whether a key is set | live `/v1/services/<id>/env-vars`, paginated — **not `render.yaml`** |
| which code is live | the **content** of the deployed blob, never ancestry from `main` |

**Known gap:** NCAAF's `recommendations_summary/week_N.json` — the artifact the
board renders from — is **not in `HOT_ARTIFACT_PATTERNS`**, so it cannot be read
through `/api/ops/artifacts/*` and there is no local copy either. Its row count
was unanswerable from outside; that is why `board_row_counts` now ships in the
payload. **Allowlisting it is owed work**, not a nicety — an unauditable
artifact forces exactly the local guessing this rule forbids.

`scripts/football_sim_input_checklist.py` reads the local feature loader by
design (it is a code-and-population gate, not a production probe) and therefore
reports **UNMEASURED**, never 0%, below `MIN_GAMES_FOR_A_RATE`, naming the mirror
in its failure text.

---

## 1. There are TWO football models and they are unrelated

This is the fact that makes every other football question confusing until you
know it.

**Track A — `FootballSimulationAdapter`** (`syndicate/features/football/adapters.py`)
- `load_features` (`:245`, `:256`) → `build_football_simulation_input`
  (`features/loaders.py:526`) → `FootballGameFeatures` carrying the full advanced
  stack (nflverse EPA, rbsdm success/explosive/red-zone, market, pace, 19,400
  player-usage rows on a 2025 wk1 load).
- `simulate_games` (`:265`) → `_game_projection` (`:110`) is a **closed-form
  linear formula with hardcoded coefficients** (`epa_component * 4.5`,
  `success_component * 8.0`, …). **It never calls smartsim2.** No Monte Carlo, no
  drives.
- Callers: `feature_lift_analysis.py`, `player_prop_lift_analysis.py`,
  `season_validation.py`, and tests. **All offline analysis. Nothing user-facing.**
- `NflAdapter` / `NcaafAdapter` (`sim_engine/nfl_adapter.py`, `ncaaf_adapter.py`)
  have **zero non-self callers**.

**Track B — smartsim2** (`sim_engine/smartsim2/`)
- The real Monte Carlo drive engine. Produces every projection a user sees.
- Fed by the three `generate_smartsim2_*` scripts, which build
  `SmartSim2SimulationInput` **by hand from four scalars**.

**The two tracks never meet.** Track A owns the features; Track B owns the
users. `drive_priors._extract_block` accepts block names (`team_metrics`,
`advanced_metrics`, `market_features`, `pace_features`) that are *exactly* the
field names Track A produces — the seam was designed and never connected.

---

## 2. The pipeline trace (§2 of the standard — file:line at every hop)

### NFL regular season
```
scripts/run_refresh_worker.py
  _SEASON_PROJECTION_SPORTS = ("nfl", "ncaaf")                        (:2321)
  gated by SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN            (:2324)
      -- ABSENT env => DISABLED. Fires 21:00Z = 16:00 CDT.
  _season_projection_script_args -> generate_smartsim2_<sport>_projections.py (:2370-2372)
  _SEASON_PROJECTION_MAX_RUNTIME_SECONDS = 45*60                      (:2375)
    -> scripts/generate_smartsim2_nfl_projections.py
         team_rating() from data/nfl_source/pbp_<season>.csv  (nflverse EPA)
         adjust_team_rating_for_injuries()                            (:402-409)
         SmartSim2SimulationInput(...)   <-- NO feature_generation_payload (:414)
         simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE)    (:423)
           -> smartsim2/game_simulator.py:simulate_game               (:67)
             -> smartsim2/drive_simulator.py:simulate_drive           (:195)
               -> build_drive_priors(simulation_input, ...)           (:204)
                 -> smartsim2/drive_priors.py:build_drive_priors      (:230)
                      payload = _copy_mapping(source.feature_generation_payload)  (:232)
                      ^^^ {} in production. 9 blocks / 65 keys default. ^^^
         write_projection_artifact(...)                               (:515)
   writes: data/nfl_source/smartsim2_projections_<season>_wk<week>.csv
   read by: syndicate/features/nfl/cards.py:483, :777  (read_projection_artifact)
            syndicate/features/nfl/picks.py, archive.py,
            syndicate/blueprints/ask_the_syndicate_data.py, ops.py
```

### NFL preseason (separate script, separate artifact — live NOW)
```
scripts/run_refresh_worker.py:_launch_autorun_preseason_projections   (:2873)
  _preseason_projection_script_args -> generate_smartsim2_nfl_preseason_projections.py (:2868)
    -> shrunk_rating(...)  nudges ratings toward league-neutral by nonstarter share
       SmartSim2SimulationInput(...)  <-- NO payload                  (:165)
       simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE)          (:174)
   writes: data/nfl_source/smartsim2_preseason_projections_<season>_wk<week>.csv
            (via nfl_artifact_output_root(), :2860)
   read by: syndicate/features/nfl/preseason_cards.py, preseason_projection.py
```

### NCAAF
```
same autorun tuple (:2321) -> generate_smartsim2_ncaaf_projections.py
  week from syndicate/features/ncaaf/sources.py:ncaaf_target_week     (:2343-2346)
  offense_defense_rating(team, ppa_index)   <-- CFBD PPA, not EPA
  SmartSim2SimulationInput(...)  <-- NO payload                       (:199)
  simulate_game(sim_input, profile=NCAAF_CALIBRATION_PROFILE)         (:208)
  write_projection_artifact(...)                                      (:306)
   writes: <data_root>/ncaaf_source/data/smartsim2_projections_<season>_wk<week>.csv (:2367)
   read by: syndicate/features/ncaaf/cards.py:34
```

**Note the artifact-root asymmetry**: NFL resolves through
`nfl_artifact_output_root()`; NCAAF hardcodes `data_root / "ncaaf_source" /
"data"`. `run_refresh_worker.py:2360-2367` calls this out explicitly and refuses
to generalise one sport's layout from the other's.

---

## 3. The input inventory (§5's first box)

Measured by `scripts/football_sim_input_checklist.py --season 2025 --week 1`,
over **272 real NFL games** from the production feature loader (not fixtures).
NCAAF is **UNMEASURED** — its loader returns 0 games (see §4).

| block | engine accepts these names | keys read | NFL populated | verdict |
|---|---|---|---|---|
| `offensive_metrics` | `offensive_metrics`, `offense_metrics`, **`team_metrics`**, `offense`, `offensive` | 18 | **100%** | FED |
| `advanced_metrics` | `advanced_metrics`, `advanced`, `game_metrics` | 7 | **100%** | FED |
| `market_features` | `market_features`, `market`, `betting` | 6 | **100%** | FED |
| `defensive_metrics` | `defensive_metrics`, `defense_metrics`, `defense`, `defensive` | 7 | **0%** | **MISROUTED** |
| `pace` | `pace`, `pace_features`, `tempo`, `clock` | 4 | **0%** | **NULL AT SOURCE** |
| `player_usage` | `player_usage`, `usage`, `players` | 12 | **0%** | **WRONG GRAIN** |
| `returning_production` | `returning_production`, `returning`, … | 3 | 0% | EXPECTED_SPARSE (NCAAF-only) |
| `coach_continuity` | `coach_continuity`, `coach`, `continuity` | 2 | 0% | EXPECTED_SPARSE (NCAAF-only) |
| `transfer_impact` | `transfer_impact`, `transfer`, `portal` | 6 | 0% | EXPECTED_SPARSE (NCAAF-only) |

**The three 0% rows have three DIFFERENT remedies. This is §4.1 of the standard —
"absent" and "unfed" and "misnamed" look identical from the outside and are not
the same defect.** Each was localised by reading the actual loaded object:

**`defensive_metrics` — MISROUTED, the data exists.**
`FootballGameFeatures.defensive_metrics` is `{}`, but `team_metrics` carries all
seven keys `_defense_strength` reads: `defensive_epa`, `epa_allowed`,
`success_rate_allowed`, `home_defensive_epa`, `away_defensive_epa`,
`home_success_rate_allowed`, `away_success_rate_allowed` — at 100%.
`loaders.py:526+` `setdefault`s them onto `team_metrics` and never onto
`defensive_metrics`. The engine's defensive alias list does not include
`team_metrics` (its offensive one does). **Remedy: route, don't build.**
Partially masked today because `_defense_strength` also reads `advanced_metrics`
for `home/away_defensive_epa`, which *is* fed.

**`pace` — GENUINELY NULL, this one is a data pipeline job.**
`pace_features == {'pace': None}`, and `team_metrics['home_pace_secs_play']`,
`['away_pace_secs_play']`, `['pace_seconds_per_play']`, `['secs_per_play']` are
**all `None`**. The keys exist; the values were never produced. `rbsdm_metrics`
`setdefault`s `home_pace_secs_play` from a source returning `None`. **Remedy:
populate the source.** (I first guessed "name mismatch" from the key list and was
wrong — the field audit corrected it. §4.1 again.)

**`player_usage` — RIGHT DATA, WRONG GRAIN.**
19,400 `FootballPlayerFeatures` rows on a 2025 wk1 load, each carrying
`snap_share`, `target_share`, `route_participation`, `carry_share`. But
`FootballGameFeatures` has **no `player_usage` attribute at all**, and the engine
reads a *game-level* block. The aggregation already exists and works —
`adapters.py:_team_player_usage` returns real numbers (`target_share 0.0305`,
`route_participation 0.0657`). Nothing puts its output on the game.
**Remedy: attach the existing aggregate.** Note `snap_share` and `air_yard_share`
came back `0.0` in that aggregate — worth checking separately, not assumed broken.

---

## 4. NCAAF — the board is live, the model output is NULL, and one env var is why

**Season opens 2026-08-29.** Measured 2026-08-18 against production, not locally.

### RETRACTED: "the NCAAF feature loader returns zero games"

I wrote that earlier in this document. **It is true of a local checkout and false
of production.** `FootballSimulationAdapter(sport="ncaaf").load_features(...)`
returns 0 games here; `GET /ncaaf/api/cards?week=1` on production serves **16**,
and all 16 are real games on the CFBD 2026 wk1 slate.

That is the `data/**` lossy-mirror trap in CLAUDE.md, hit exactly as described. I
nearly filed it as a production defect. **Do not diagnose NCAAF data from this
checkout.** The checklist's level-2 message now says so in the failure text.

### What IS wrong, measured

**All 16 served NCAAF games carry an entirely null predictions block:**

```json
"predictions": {"home_mean": null, "away_mean": null, "margin_mean": null,
                "total_mean": null,
                "probabilities": {"home_win": null, "away_win": null,
                                  "home_cover": null, "away_cover": null,
                                  "total_over": null, "total_under": null}}
```

`smartsim_reasons` is `[]` on every one. **The NCAAF board renders and shows no
model output at all.**

**The cause is one absent env var.** `CFBD_API_KEY` is ABSENT on all three Render
services (enumerated from the live `/v1/services/<id>/env-vars`, not from
`render.yaml`). `generate_smartsim2_ncaaf_projections.py:57` raises on it, so the
autorun dies before fetching a single game and the projection artifact is never
written. Production logs, 06:00Z–15:34Z on 08-18: **21 of 21
`SEASON_PROJECTION_ARTIFACT_MISSING` lines are `sport=ncaaf`, 0 are `sport=nfl`**
— the same guard is silent for the football sport that works, which is the
positive control that it is not misfiring.

`interval_seconds=86400`, so this is a **once-daily** failure, **not** a relaunch
loop — it is not burning worker cycles.

**Two-arm test, run locally against the real CFBD API:**

| arm | result |
|---|---|
| A — no key (= production today) | `RuntimeError: Missing CFBD API key.` Dies immediately. |
| B — with the key | 99 CFBD games → **51 FBS-vs-FBS** rows via the `#445` fallback → **136** PPA teams (`cfbd_ppa_season_2025_fallback_for_2026`) → **50 of 51** home teams resolve to a non-zero rating. |

**Everything downstream of the key already works**, including `#445`'s guard,
confirmed present by content in the deployed blob (`00e9a49f`), not by ancestry.

Deploy request filed: `.syndicate/deploy/requests/20260818T154432Z-football-model-owner.md`.
Env-only, one key, one service. **`render.yaml` must not be touched** — that
fires `blueprint_sync`.

### FIXED: the board was capping the slate at 16 — an NFL-shaped number

**The board served 16 games because of a hardcoded cap, not because the data
held 16.** Production evidence: weeks **1, 2, 3, 5, 8 and 12 ALL served exactly
16** while CFBD lists **51** FBS-vs-FBS for week 1 alone. Six weeks landing on
the cap exactly is the cap binding.

16 is the NFL's natural weekly slate (32 teams / 2), where such a cap can never
bind. FBS plays 50–60. Worse, the truncation kept the top rows **by `edge`** —
and with no projection artifact the edges are absent, so the surviving 16 were an
**arbitrary** 16 presented as the board.

**There were THREE caps, on three branches of the same page**, and the one that
mattered most was not the one serving the board that day:

| site | branch | status |
|---|---|---|
| `_collapse_games(limit=16)` | legacy `recommendations_summary` — the **fallback**, active today | fixed |
| `runtime_rows[:16]` | legacy Enhanced Totals Engine rows | fixed |
| `runtime_rows[:16]` | **SmartSim2 standalone rows** | fixed — **this is the one that bites next** |

**The route calls `build_smartsim_cards_page_context`, not
`build_cards_page_context`** (`blueprints/ncaaf.py:85,91`). A fix applied only to
`_collapse_games` would have been inert on the served path — and the SmartSim2
branch returns zero rows today *only* because the projection artifact is missing.
**The moment `CFBD_API_KEY` lands, that branch returns ~51 rows and the old
`[:16]` would have cut them straight back to 16 — re-breaking the board at the
exact moment it started working.**

**Raised, not removed.** `_NCAAF_BOARD_GAME_LIMIT = 80`. An unbounded board is a
real memory and payload risk on a 2 GB display service (~9.8 KB/game measured, so
60 games ≈ 590 KB). The cap stays as a guard at a size the sport can actually
reach.

**And it now announces itself** — per the no-silent-caps rule. Every context
carries `board_row_counts` (`runtime_rows`/`distinct_matchups`, `limit`,
`truncated`, `dropped`, `source`), present **whether or not** it truncated, so
"not truncated" is a reading rather than an absent key. A bite also prints
`NCAAF_BOARD_TRUNCATED` to web's stdout, which Render does collect.

This doubles as the instrument for a question that could not be answered from
outside: with the summary artifact unallowlisted and no local copy, "does the
summary hold more than 16 rows?" was uninspectable. `board_row_counts` answers it
on the next request.

Regression cover: `tests/test_ncaaf_board_slate_coverage.py` (7 tests) — asserts
the limit clears a real FBS week, that the old cap *would* have dropped 35 of 51
(so the fix is not vacuous), that the guard still bites and reports above its
threshold, and — **via AST, not a text search** — that no board-sized hardcoded
slice returns. The text-search version of that last test failed against the
module's own docstrings, which quote the removed cap while explaining it.

### Still open, NOT to be waved through

After the key lands, the projection artifact should carry ~51 rows. **Confirm the
board then serves ~51 and not 16** — read `board_row_counts` and the game count,
not just `predictions.home_mean`. A populated `16 of 16` would mean the join, not
the cap, is now the constraint.

Also seen and NOT a Syndicate defect: USC, San José State and Eastern Michigan
each appear twice in the served week. Both of each pair are present in CFBD's own
week-1 response, so this is upstream schedule data for an unfinalised 2026
season, not a bug here. Recorded because it looks like one.

### Still genuinely unmeasured for NCAAF

The three NCAAF-only input blocks (`returning_production`, `coach_continuity`,
`transfer_impact`) have builders
(`build_ncaaf_{returning_production,coach_continuity,transfer_portal}_snapshot.py`)
whose output has **never been shown to reach the engine** — no NCAAF entrypoint
passes a payload at all (§0). Their population is unmeasured against a real
slate, and the checklist cannot measure it from this checkout.

---

## 5. Wiring the payload in is a TWO-PART change (§4.4 — the expensive rule)

**Do not simply pass the payload and call it an improvement.**

`NFL_CALIBRATION_PROFILE` is the *frozen NFL Production Candidate*
(`smartsim2/calibration_profile.py`). `NCAAF_CALIBRATION_PROFILE` is v2
(`627a99c2`, "close red-zone conversion gap"). **Both were fit against a payload carrying nothing the engine reads.**
`baseline_audit.py` — which *is* in the fit chain (`truth_audit.py:49` →
`build_baseline_audit_snapshot_and_inputs`) — passes a payload of
`{game_id, season, week, market_total, market_spread_home}`, none of which
`drive_priors` consumes. Functionally identical to empty. Every other entrypoint
in the calibration and backtest chain passes no payload at all.

Worth noting for whoever does the re-fit: `baseline_audit._build_simulation_input`
*does* feed the typed `pace_seconds_per_play` from the game row's
`home_pace_secs_play`/`away_pace_secs_play` — so **the calibration corpus has
pace that the production feature loader returns as `None`** (§3). The re-fit and
production do not currently see the same pace input.

So the fitted rates have already absorbed the average effect of the neutral
defaults. The standard's §4.4 is exact about what happens next:

> adding two mechanisms to a calibrated engine produced a **negative interaction
> in 4 of 4 markets**. The fitted rates already absorb the average effect of a
> missing mechanism, so re-adding it double-counts.

The −1.685 total and −6.50 win-point deltas in §0 are **what the wiring does to
an un-refitted engine**. They are a measurement of the *disturbance*, not of the
*improvement*. Shipping the wiring without a re-fit is shipping half a change,
and §4.4 says that is worse than shipping neither.

**The obligation, stated so it cannot be skipped:**
1. Wire the payload (mechanism).
2. **Re-fit** `CalibrationProfile` for NFL and NCAAF against historical truth
   with the payload live (`smartsim2/calibration/`, `historical_truth/`).
3. Score against the market, not against climatology (§5's ninth box).

Also relevant, and already earned elsewhere in this repo: a single-feature
measurement against un-refitted rates **understates** a suppressed feature
(§4.5). A small delta on one of these nine blocks is weak evidence that the block
does not matter.

Note `calibration_profile.py`'s own comment: NFL is currently **all 1.0
multipliers** — the profile seam is wired (`964c89a4`) but carries no fitted
content, so `load_versioned_profile` returns the frozen default. The re-fit in
step 2 has somewhere to land.

---

## 6. The gate

```bash
py -3 scripts/football_sim_input_checklist.py --season 2025 --week 1
```

Three levels, none of them a name grep:

- **Level 0 — entrypoint wiring.** AST census of every
  `SmartSim2SimulationInput(...)` site: does it pass a payload? *Football-specific
  and the one that matters here* — a key can be perfectly populated and still
  never reach the engine. MLB and soccer have no equivalent because they have one
  entrypoint each.
- **Level 1 — consumed surface.** AST over `drive_priors.py` for
  `_extract_block(sources, [names])`, `_first_float(block, [keys])`, and
  `block.get("key")`. Read from the literal argument lists, so a renamed key
  changes the report instead of silently passing.
- **Level 2 — population.** Over real games from the production feature loader.
  Below `MIN_GAMES_FOR_A_RATE = 8` it reports **UNMEASURED**, never 0%.

Exits non-zero on any alarm. Suitable for `/preflight` or `migration_gate.py`.

`--json <path>` writes the bounded report artifact so production can be audited
without streaming raw inputs (§3 of the standard).

### The instrument-blindness trap this gate already fell into

The **first** run of level 2 passed `season=None`. The loader fell back to a
degenerate single-game context and every block read **"0.0% populated on 1
game"** — which is indistinguishable from a total data outage, and was in fact a
broken instrument. The real load at `season=2025, week=1` returns **272 games**
with `team_metrics` carrying **28 keys**.

`MIN_GAMES_FOR_A_RATE` exists because of that. **A 0% is evidence only once the
instrument is known to be able to read non-zero.**

---

## 7. Standard compliance — where this engine stands

| §5 requirement | status |
|---|---|
| Input inventory (`consumed?` / `populated%`) | **DONE** — §3 |
| Gating checklist script, exits 1 | **DONE** — `scripts/football_sim_input_checklist.py` |
| Pipeline trace, file:line, incl. what it writes | **DONE** — §2 |
| Every input disk-backed via `SYNDICATE_DATA_ROOT` | **NOT AUDITED** |
| Every input allowlisted in `HOT_ARTIFACT_PATTERNS` | **NOT AUDITED** |
| Reuse/caching flags documented + rebuild procedure | **NOT AUDITED** — no `--use-*-artifacts` analogue found; MLB's reuse trap may not apply |
| Reachability test per flagged feature (`off != on`) | **DONE for the payload** (§0, 21/21 + score-level). Not done per-block. |
| Mechanisms vs estimators, with the re-fit obligation | **DONE** — §5 |
| A market-relative scoreboard | **NOT DONE** — see `docs/reports/nfl_validation_report.md`, `smartsim_betting_performance_report.md` for what exists |
| Known-sparse fields documented with reasons | **DONE** — `EXPECTED_SPARSE` in the checklist |

**Not audited is not "fine".** Those four rows are the next lane's work, not a
clean bill of health.
