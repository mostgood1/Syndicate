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
2. **rebuild rosters** — set **`SYNDICATE_MLB_ROSTER_REBUILD_DATE=<YYYY-MM-DD>`**
   on refresh-worker and let that date's sim run.

   **Until 2026-08-18 this step was IMPOSSIBLE in production**, and this document
   asserted it anyway. `run_mlb_daily_sim_job.py` built a hardcoded command of
   eleven flags and never passed `--use-roster-artifacts`, so
   `daily_update.py`'s default (`on` = reuse) always won. There was no env var,
   no CLI path and no ops endpoint, and the worker runs no HTTP server so its
   disk could not be cleared remotely either.

   The gate is **DATE-SCOPED, not on/off, deliberately**: a rebuild is the
   expensive path, and a plain flag left set silently pays that cost on every
   run forever. A date matches at most one day and is inert by the next morning
   whether or not anyone remembers it. `always` exists for a deliberate
   multi-day rebuild and says what it is.

   **Absent means today's behaviour, not `off`** — with the var unset the flag
   is not passed at all. Adding the key changes nothing until it is set.

   It **prints on both paths** (`ROSTER_REBUILD armed` / `ROSTER_REBUILD inert:
   gate=... does not match date=...`), because a silently mis-set gate is
   indistinguishable from a rebuild that ran — which is the failure the gate
   exists to make visible.

   Cheapest alternative, no env change: `roster_objs/` are per-date, so the
   **first sim on a NEW DATE rebuilds for free.**
3. run `sim_input_checklist.py --publish` and confirm the field left the FAIL list.

   **THIS IS THE ONLY VERIFICATION WITH A PATH OFF THE WORKER, and that is not a
   style preference.** The sim job is spawned with its stdout redirected to a
   FILE — `live_refresh_loop.py:2784-2790` sets
   `popen_kwargs["stdout"] = open(log_path, "wb")` — so **nothing the job prints
   reaches Render's log collector.** On 2026-08-19 I spent twenty minutes
   watching the logs API for a line the wrapper prints on every run; it can never
   appear there. Verifying an input by grepping Render logs for a sim-job print
   is checking a channel the line cannot reach, and it will always look like
   failure. The checklist REPORT is allowlisted and published, so it is readable
   remotely; the on-disk sim log is not, absent an ops endpoint that tails it.
   No such endpoint exists today;
4. only then measure effect.

Skipping (2) produces a confident "shipped" followed by a flat measurement.

---

## 2b. INPUT PROVENANCE — where each input is produced and applied

**This table exists because I made FOUR alternating wrong calls about BVP in one
session**, each from grepping the wrong file. Inputs are applied in THREE
different places, and knowing which one decides whether a fix is a config change,
a cache clear, or a build.

| input | produced by | applied in | gate |
|---|---|---|---|
| pitch-type splits | `tools/statcast/fetch_pitcher_pitch_splits_x64.py` -> artifact | **`build_roster.py`** :2141/:2154 | `--statcast-starter-splits` (default `starter`) |
| batted-ball (batter) | `scripts/build_mlb_batted_ball_artifact.py` | **`build_roster.py`** batter loop | `SYNDICATE_MLB_BATTED_BALL_WEIGHT` (default 0.0) |
| batted-ball (pitcher) | same artifact, `pitchers` block | **`build_roster.py`** starter + bullpen | unconditional |
| **BVP `vs_pitcher_*`** | **computed from `data/raw/statcast/pitches/<season>/`** | **`daily_update.py:7564`** — **NOT `build_roster`** | `--bvp-hr` (default `on`) |
| position substitution | hazard table in `simulate.py` | `simulate.py` half-inning hook | `GameConfig.position_substitutions` (default False) |

**The BVP row is the trap.** `build_roster.py` contains no BVP reference at all,
so grepping it returns nothing and suggests the feature is unwired. It is wired —
one level up, in `daily_update.py`, and **on by default.**

### The BVP failure, recorded in full so it is not repeated

Four claims, each wrong, each from a different shortcut:

1. *"BVP is fetched daily, 1,282 files, needs only a mapping"* — from a FILE
   COUNT. Every file had `by_batter: {}`.
2. *"BVP needs a real fetch job"* — from the empty files. Wrong: computing fresh
   returned **117-170 batter entries for 5 of 5 pitchers**.
3. *"BVP is cheap, just invalidate the cache"* — right conclusion, wrong
   reasoning; I had not checked that anything applies it.
4. *"Invalidation will not help, nothing writes `vs_pitcher_*`"* — from grepping
   **`build_roster.py`**, the wrong file. `daily_update.py:7564` applies it.

**Settled empirically instead:** cache moved aside, applier run directly ->
**0 -> 6 of 9 batters populated.**

**ROOT CAUSE: a stale-empty cache with a 30-day TTL.** An earlier run cached `{}`
when the raw corpus was unreachable, and the TTL served that emptiness as
authoritative. The corpus (39 files, 2026-03-11..07-30) was present the whole
time.

**Fix: delete `data/cache/statcast/bvp/`.** It recomputes.

## 3. INPUT STATE — **26 -> 5** after this session's wiring

`[measured 2026-08-18]` Progression, each step a simulated rebuild:

    26   as archived (nothing wired)
    20   + pitch splits, batter batted-ball blend
    15   + native batter bb_* population
    10   + pitcher bb_* population
     5   + BVP cache invalidation      <- current

**THE REMAINING 5, with causes:**

| field | why | fixable |
|---|---|---|
| `batter.vs_pitch_type`, `vs_pitch_type_hr` | the pitch-splits artifact is PITCHER-side only; no batter-vs-pitch-type source was built | yes |
| `batter.statcast_quality_mult`, `pitcher.statcast_quality_mult` | **no producer anywhere in the repo** — only `getattr` reads | needs a definition first |
| `pitcher.pitch_type_hr_mult` | `PitcherPitchSplits` carries `whiff_mult` + `inplay_mult` only | **not from this source** |

**BVP coverage after invalidation:** `vs_pitcher_history` 338/522,
the four multipliers 84/522 — real but partial, because a batter only has
history against starters he has actually faced.

### Superseded — the original 0% snapshot, kept for the record

### (original) INPUT STATE — 26 consumed fields at 0% population

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
- ~~batter-vs-pitcher history reaches nothing~~ **CORRECTED: it was a stale-empty cache, now fixed — see §2b.**

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

---

## 8. The JOINT outcome distribution (`#621` Phase 4)

`model_engine_standard` §2 requires a documented pipeline trace, file:line at
each hop, including what it writes. This is that trace for the joint.

### What it fixes

`_sim_many` runs 1,000 game simulations and reduces every one into MARGINAL
counters. The joint — which outcomes land TOGETHER — was computed on every run
and discarded. Only 50 per-segment score `samples` survived to the artifact:
**0.137% of the ~292,000 scalars a 1,000-sim game produces.**

Meanwhile the correlation the platform prices parlays with is a sum of
categorical flags plus a static table holding one constant for every player in
every game — `("mlb", ("home_runs", "total_bases")): 1.35`,
`syndicate/features/intelligence.py:617`. It reaches real money via parlay
pricing, the board correlation badges, and `bankroll_manager.build_portfolio`
bet SIZING.

### Trace

```
live_refresh_loop._run_mlb_sim_tick
  -> scripts/run_mlb_daily_sim_job.py                       (detached subprocess)
    -> vendor/mlb_bettingv2/tools/daily_update.py
       :336  from sim_engine.joint_outcomes import ...      (the math + accumulator)
       :344  _joint_accumulator_for(batter_ids, n_sims)     -> None when nothing to measure

       -- PATH A, the DEFAULT (`--workers` = 4) ------------------------------
       :645  _simw_chunk(start_i, n)                        (one of four processes)
       :720    joint_acc = _joint_accumulator_for(...)
       :833    joint_row[batter|<id>|<market>] = hitter_stat_values[<row_key>]
       :886    joint_acc.record(i - start_i, joint_row)     (+ 8 segment scores)
       :919    return {..., "joint": joint_acc.to_transport()}
       :4494   joint_total.extend(res["joint"])             THE MERGE THAT DID NOT EXIST

       -- PATH B, `--workers 1` ----------------------------------------------
       :4595   joint_row[...] = hitter_stat_values[...]     (second copy)
       :4632   joint_total.record(i, joint_row)

       :4705 out["joint"] = joint_total.to_payload(players=...)
       :8237 _write_json(sim_path, record)
  writes: data/daily/sims/<date>/sim_*.json  ->  record["sim"]["joint"]
```

Read back by `syndicate/features/mlb/sim_joint_correlation.py`, which builds the
`measured_lookup` that `correlation_engine.compute_correlation` has accepted
since `1bbcc246`. A measured coefficient REPLACES the heuristic and stamps
`correlation_basis="measured_joint"`.

**No allowlist change and no web deploy.** `data/daily/sims/*/sim_*.json` is
already in `HOT_ARTIFACT_PATTERNS` (`artifact_publisher.py:586,596`).

### Reuse flag (§3 corollary)

`--use-roster-artifacts` defaults to `on`, but it governs ROSTER INPUTS, not sim
OUTPUTS. The joint is computed inside `_sim_many` from live per-sim results, so
nothing short-circuits it — a reused roster still produces a fresh joint.
**What it does need is a SIM RUN**: shipping this code does not rewrite an
existing `sim_*.json`, so a date simmed before it landed has no `joint` and the
resolver counts that as `joint_field_absent` rather than reporting zero.

### Two-site invariant — and why reachability is NOT sufficient

The accumulation is duplicated at `_simw_chunk` and `_sim_many`. That
duplication has drifted three times (`#334` zeroed `hrr_mean`; `#429` added
warning comments at both sites; a third instance happened anyway WITH those
comments in place).

**Measured: with site 1 broken and site 2 intact, BOTH `off != on` reachability
tests still PASS**, because `workers=1` never enters `_simw_chunk` — and
`--workers` defaults to 4, so the tests take the path production does not.
`model_engine_standard` §4.3 is necessary and not sufficient for a duplicated
site.

`scripts/sim_input_checklist.py::joint_site_problems()` is the control. It parses
with `ast`, **never a regex**: measured on this file, a non-greedy
`hitter_stat_values = \{(.*?)\}` reads **6 keys where the dict has 10**, because
the `#621` fix's own comment contains a literal `{0: n_sims}` whose brace closes
the match early — a false reading shaped exactly like the bug.

### Measured, 2026-09-04

Substrate: input `render` (production roster
`snapshots/2026-09-04/roster_0_DET_at_CLE_pk824424_g1.json`), run local — so per
§3b this is evidence about the CODE, not the deployment.

| pair | mean rho | median | range | n |
|---|---|---|---|---|
| `home_runs x total_bases` | **+0.610** | +0.611 | +0.227 .. +0.805 | 18/18 |
| `hits x total_bases` | +0.922 | +0.918 | +0.877 .. +0.959 | 18/18 |
| `hits x home_runs` | +0.369 | +0.364 | +0.136 .. +0.546 | 18/18 |
| `hits x rbi` | +0.514 | +0.514 | +0.385 .. +0.625 | 18/18 |
| `rbi x total_bases` | +0.645 | +0.652 | +0.428 .. +0.786 | 18/18 |
| `home_runs x rbi` | +0.608 | +0.633 | +0.278 .. +0.767 | 18/18 |

Cross-batter `total_bases x total_bases`: **same team +0.097** (n=72),
**opposing +0.018** (n=81).

**THE SPREAD IS THE FINDING, NOT THE MEAN.** One constant serves all eighteen
batters today; the measured range on the headline pair is 3.5x end to end
(Steven Kwan +0.227, a contact hitter, against Dillon Dingler +0.805).

Cost: accumulator 160,000 B against a 36,950,016 B peak RSS (**0.433%**);
payload 16,634 B/game, ~0.3 MB across a 17-game slate; 3,160 pairs in 0.32 s.
