# MLB Sim Engine — reference, input state, and operating procedure

> 2026-08-18, lane `convergence-phase7-crps`. The worked example behind
> `docs/ai_context/model_engine_standard.md`. Every number is `[measured]` unless
> marked otherwise.
>
> **Read `model_engine_standard.md` first** — this document is that standard
> applied to one engine, not a substitute for it.

---

## 1. The pipeline, file:line at each hop

```
live_refresh_loop._run_mlb_sim_tick
  -> scripts/run_mlb_daily_sim_job.py                    (detached subprocess)
    -> vendor/mlb_bettingv2/tools/daily_update.py            (:236)
      -> sim_engine/data/build_roster.py
           statcast_cache created at daily_update.py:5859
           when --statcast-starter-splits != "off"   (DEFAULT "starter")
        -> _apply_cached_statcast_pitch_splits            (build_roster.py:75)
             starter :2141   AND bullpen_all :2154
          -> fetch_pitcher_pitch_splits    artifact-first, DiskCache fallback
        -> apply_batted_ball_to_batter     (gated SYNDICATE_MLB_BATTED_BALL_WEIGHT)
      -> sim_engine/simulate.py            simulate_game
```

**Writes, in flight:**

| path | content |
|---|---|
| `snapshot_dir/roster_objs/roster_obj_*.json` | the profiles the sim actually consumes |
| `snapshot_dir/schedule_raw.json` | slate |
| `snapshot_dir/team_rosters_raw.json`, `injuries_raw.json`, `roster_events.json` | inputs |
| `data/daily/daily_summary_<date>.json` | the projections |

`roster_objs/` is what `scripts/sim_input_checklist.py` audits — i.e. exactly
what the sim consumed.

---

## 2. THE OPERATING TRAP — a new input needs a REBUILD, not a publish

```
--use-roster-artifacts    default "on"    reuse roster_objs when present
--write-roster-artifacts  default "on"
```

`run_mlb_daily_sim_job.py` **overrides neither.**

**The worker reuses roster artifacts serialised BEFORE a new input existed.**
Publishing a new artifact changes nothing on any date whose `roster_objs/`
already exist — the build that would read it never runs.

**Procedure for landing any new input:**
1. publish the input artifact to the mounted disk;
2. **rebuild rosters** — `--use-roster-artifacts=off`, or clear `roster_objs/`
   for the target date;
3. run `sim_input_checklist.py --publish` and confirm the field left the FAIL list;
4. only then measure effect.

Skipping (2) produces a confident "shipped" followed by a flat measurement.

---

## 3. INPUT STATE — 26 consumed fields at 0% population

`[measured 2026-08-18, 40 rosters, 720 batters, 717 pitchers]`

**Batter (13):** `bb_gb_rate` `bb_fb_rate` `bb_ld_rate` `bb_pu_rate`
`bb_inplay_n` `statcast_quality_mult` `vs_pitch_type` `vs_pitch_type_hr`
`vs_pitcher_k_mult` `vs_pitcher_hr_mult` `vs_pitcher_bb_mult`
`vs_pitcher_inplay_mult` `vs_pitcher_history`

**Pitcher (13):** `bb_gb_rate` `bb_fb_rate` `bb_ld_rate` `bb_pu_rate`
`bb_inplay_n` `pitch_type_whiff_mult` `pitch_type_inplay_mult`
`pitch_type_hr_mult` `statcast_quality_mult` `statcast_splits_source`
`statcast_splits_n_pitches` `statcast_splits_start_date` `statcast_splits_end_date`

**Consequences today:**
- **every pitch type is interchangeable** — a slider and a fastball have identical effect;
- **every hitter has the same batted-ball profile** — league defaults 0.44/0.25/0.20/0.11;
- **batter-vs-pitcher history is fetched daily (1,282 cached files) and reaches nothing.**

**Healthy by contrast:** `arsenal` 100%, `inplay_hit_rate` 100%, platoon ~99%,
venue ~97%, `k_rate`/`bb_rate`/`hr_rate` ~99%.

---

## 4. What has been built (all OFF, none deployed)

| thing | state | gate |
|---|---|---|
| pitch-splits artifact + artifact-first loader | built, 73 pitchers | needs artifact on worker disk |
| batted-ball artifact + estimator blend | built, 450 players | `SYNDICATE_MLB_BATTED_BALL_WEIGHT` = 0.0 |
| position-player substitution | built, closes 34.3% of the opportunity gap | `GameConfig.position_substitutions` = False |
| input checklist | built, gates at exit 1 | — |

All three artifacts are allowlisted in `HOT_ARTIFACT_PATTERNS`. **Roster objects
are deliberately NOT** — hundreds of large files per date, and the allowlist
drives publishing as well as reading.

---

## 5. Measured results — what these features are actually worth

| change | effect | verdict |
|---|---|---|
| substitution alone | hits +0.00209, RBI +0.00573, runs +0.00146, **TB −0.00154** | 3 of 4 better, market still wins all |
| pitch splits alone | ~+0.001 | real but small |
| **both together** | interaction **−0.00331, negative in 4 of 4** | **they interfere** |
| opportunity haircut | 3 of 3 markets closer, out-of-sample | superseded by real substitution |

**Why the small numbers:** the engine's rates were fitted with these mechanisms
ABSENT, so they already absorb the average effect. Re-adding double-counts, and
adding two compounds it. **A re-fit is a precondition, not a follow-up** — see
the standard §4.4.

**Model vs market, hitter props:** the market wins every clean family
(hits +0.0100, runs +0.0015, TB +0.0067 Brier). **No demonstrated edge anywhere.**

---

## 6. Genuinely absent (not merely unfed)

- **Defensive quality** — no OAA/DRS/UZR; BABIP has nothing fielding behind it.
- **Catcher framing** — the umpire IS modelled, the catcher is not.
- **Batter fatigue** — `availability_mult` is pitcher-only.

---

## 7. Standing caveat on production

`/api/ops/artifacts/stream` **403s on `roster_objs/`** — the endpoint gates on
`HOT_ARTIFACT_PATTERNS` and roster objects are excluded by design. **All
population numbers here come from mirrored artifacts, not a live read.**

The intended route is `sim_input_checklist.py --publish` **run on the worker**,
which emits a small allowlisted report. Until that runs, production population is
**inferred, not measured.**
