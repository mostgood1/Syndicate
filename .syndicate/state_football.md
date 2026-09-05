# state — football

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [nfl-board-projection-coverage] NFL BOARD PROJECTION COVERAGE IS 100% `[measured 2026-09-04T23:19:34Z on the served payload, lanes nfl-projection-et-datekey + nfl-la-rams-alias]`

`/api/board/book-grid?sport=nfl` reads **`unmatched_game_rows` 0** of 1,251 game rows;
all 78 Los Angeles Rams rows carry a projection. Two defects, two commits:

    299  baseline
     78  `52870f57`  the projection join compared a UTC day against an ET day
      0  `fb7a1f96`  nflverse writes the Rams `LA`; `_NFL_ALIAS_TO_NAME` knew only `LAR`

**CONFIRMED TWICE, on two different deployed commits and two different rebuilt
artifacts** — so this is not a one-artifact fluke:

    2026-09-04T23:19:34Z  refresh-worker `ea1e3ac0`   unmatched 0 / 1,251, Rams 78/78
    2026-09-05T02:18:14Z  refresh-worker `3a9153f4`   unmatched 0 / 1,251, Rams 78/78

web is ALSO on `3a9153f4` (live 2026-09-04T23:02:47Z). Verified by CONTENT, not only
ancestry: `git show 3a9153f4:.../team_aliases.py` carries the `"la"` entry, and both
`fb7a1f96` and `52870f57` are ancestors. Several sessions have deployed both services
since, and the fix has survived each — it is on `main`, so it rides along.

**THIS ENDPOINT SERVES `source: "precomputed_artifact"` — refresh-worker's output,
NOT web's request path.** A web deploy of the same commit moved the number by ZERO;
it moved only once refresh-worker had the commit AND rebuilt. Anyone changing
`attach_nfl_game_projections` or `team_aliases` must deploy **refresh-worker** and wait
for a rebuild before reading. Tells that the request path did not run: no
`projection_coverage` key in the response, and `projection` ABSENT (not null) on rows.

**nflverse vocabulary, enumerated over all of `data/nfl_source/schedule_2026.csv`:**
32 distinct codes, `LA` (Rams) and `LAC` (Chargers) present, **`LAR` absent entirely**,
`WAS` not `WSH`. `_NFL_ALIAS_TO_NAME` now resolves all 32.

## [ncaaf-zero-orders-is-two-gates] NCAAF SERVES ZERO ORDERS BY DESIGN, and it is TWO gates, not one `[verified 2026-09-01, lane game-market-entry-roi-curve]`

The board is alive: `/api/board/layer2-shortlist?sport=ncaaf` serves **480 rows**,
`per_sport.ncaaf.selected=480`. The first zero is the SIZING input.

    model_edge_pct numeric     0 / 480      <- what the sizing path reads
    ev_pct         numeric   480 / 480
    ev_basis       market_fair on 480 / 480

1. `football/pick_gate.py` denies the MODEL claim on a measured out-of-sample
   loss: 2023 SP+ → 2024, n=2,233 clean, model margin MAE **15.775 vs market
   12.212, +3.563 at t=+17.20**, losing to the OPEN line by nearly as much and at
   every scale 6..24. Default deny; serving requires a recorded WIN.
2. `portfolio_commit.py:267` refuses any row with no `model_edge_pct`, by design
   ("a legitimate way to RANK and not a basis on which to SIZE"). **This is the
   gate that actually kills NCAAF**, since every served row is `market_fair`.

**`pick_gate`'s 2026-08-29 `(sport, market, BASIS)` re-key cannot produce orders
on its own** — it un-blocked RANKING; sizing still needs a model edge the gate
denies. Changing this is a PRODUCT DECISION, the position `#624` step 6 holds for
MLB props. **NCAAF settlement is shipped and NEVER verified end-to-end**; tripwire
at `#627`'s LIFT_CONDITION.

## [ncaaf-team-registry-two-files] THE RESOLVER READS THE *SNAPSHOT*, AND THE FILE BESIDE IT IS OLDER AND DIFFERENT `[measured 2026-09-03]`

Two registries live in
`data/ncaaf_source/source_artifacts/data/processed/team_registry/`:

| | `..._snapshot.csv` **(READ)** | `ncaaf_team_registry.csv` (not read) |
|---|---|---|
| `St. Anselm` | 0 | 1 |
| `Albany State GA` | 0 | 1 |
| St./Saint schools | 12 | 11 |

Same row count, different contents. **`resolve_team` / `_alias_map` read the
SNAPSHOT** (`oddsapi_lines.py:190` via `team_registry_snapshot_path()`), and
`feature_payload.py:136` reads snapshot first with the plain registry only as a
fallback. The snapshot is newer and authoritative: written by `d195be63`
(2026-08-26, "build the 2026 team data") from a live CFBD
`fetch_team_catalog(season=...)`; the other was last touched `4c5583fa`
(2026-08-01).

**The 2026 catalog RENAMED schools rather than dropping them:**
`St. Anselm` -> `Saint Anselm`, `St. Francis (PA)` -> `Saint Francis`,
`Albany State GA` -> `Albany State`. Three tests asserting the pre-2026
spellings failed while the resolver was correct throughout — `fold()` produced
the right keys and `_alias_map` was not dropping them as ambiguous; nothing
claimed those keys because the rows are not in the file that is read.

**How to avoid re-deriving this:** before concluding `resolve_team` is broken,
print `team_registry_snapshot_path()` and grep THAT file. Grepping the
sibling `ncaaf_team_registry.csv` will show the team and prove nothing.

## [football-smartsim2] FOOTBALL (NFL + NCAAF) — smartsim2 runs on FOUR SCALARS `[measured 2026-08-18, lane football-model-owner]`

**Owner: `football-model-owner`.** Strategy, every measurement and the exit
criterion: `docs/ai_context/ncaaf_beat_the_close_strategy.md` (§0–§13).
Pre-08-20 detail archived VERBATIM in `state_archive_2026-08-20.md`.

### THE DIAGNOSIS — dominated, not broken `[measured 2026-08-20, 751 clean OOS games]`

`actual = a + b*market + w*(model−market)` → **b=+0.990** CI [0.909,1.076] (the
closing line is UNBIASED) and **w=−0.028** CI [−0.130,+0.069] (the model's
deviation carries ZERO information). r(market,actual)=+0.645 → R² **41.6%**;
r(model,actual)=+0.421 → R² **17.8%**. **Gap = 23.8 points of R².**

The model has REAL signal and is strictly dominated: everything it knows the
market knows, and where they differ it is noise. **This one fact explains every
failed remedy** — no threshold, weight or subset helps a dominated model, so
STOP re-testing them. `scripts/grade_football_model_weight.py`.

### IT LOSES TO A MINDLESS SIDE BET `[2026-08-20]`

always-bet-the-underdog **51.2%** vs model **46.8%** (NCAAF, 735 bets);
**58.9%** vs **54.7%** (NFL preseason, 95 bets) — **−4.4 / −4.2 points, two
independent sports**. NCAAF ATS gets WORSE as the edge filter tightens
(46.8% → 45.2% at 10+ pts). `scripts/grade_football_playability.py`.

### EVERY LEVER MEASURED, ALL DEAD — do not retry `[2026-08-20]`

| lever | verdict |
|---|---|
| situational (8 factors) | PRICED. 1,746 games, no \|t\|≥2. Positive control t=+2.70 |
| injuries | **PRICED — RESOLVED on 4,431 games / 17 seasons (2009-25)**. All 4 measures null (best −1.74). Power stated: detects ~0.18 pts, observed −0.146. A 4-season run read t=−2.10/−2.23 and that was a FALSE POSITIVE — per-season slopes swing +0.73/+0.71/−0.95/−0.80 with 3 seasons crossing \|t\|=2 in BOTH directions. ATS 51.3/51.1/52.1/59.5%, none clearing 52.4% |
| returning production | pooled ΔMAE −0.062, t=−0.89. **Code REMOVED** |
| `SP_RATING_SCALE` | every scale 6..24 loses |
| blending | w≈0 → optimal blend is 100% market |
| three scalar totals fixes | measured dead |

**A WORKTREE COMMIT DOES NOT UPDATE THE PRIMARY TREE, AND THE GAP IS A REVERT
HAZARD** `[measured 2026-08-20]`. Today's `lanes.md` trims were committed from
worktrees; the SHARED tree's copy stayed at **127,558 B against origin's
106,084** — 21 KB stale. Any session editing `lanes.md` there and pushing would
have silently REVERTED the 34 KB trim and every lane edit landed since. After
working from a worktree, **sync the shared tree's copy back**, and verify by
HASH not by size. Note `git reset --keep origin/main` correctly ABORTS while
another session holds an uncommitted file (it hit `deploys.md`), so the safe
move is a single-file `git checkout origin/main -- <path>` followed by a commit —
`checkout <rev> -- <path>` writes the index EVERY session shares, and a stray
staged file is what gets swept into someone else's commit.

**THE `smartsim2_projections_*.csv` ALLOWLIST IS ORPHANED — THREE HANDOFFS HAVE
NOW FAILED** `[verified on origin 2026-08-20, after the NFL allowlist landed]`.
`basketball-model-owner` was asked twice and archived without acting;
`soccer-odds-capture-cadence-gap` closed; and `nfl-artifact-allowlist-add`
CLOSED-VERIFIED having added the NFL **injuries / roster / depth** patterns —
**not this one**. Checked `origin/main:artifact_publisher.py` directly: no
`smartsim2_projections` entry. `tests/test_football_projection_publish.py` still
reports **1 xfailed**, which is the designed signal.
**Consequence:** both football generators' `publish_hot_artifact` calls remain
INERT, and NCAAF projections still reach web ONLY via git + a web deploy — a
production deploy per model change. Whoever wants this fixed should add the one
line themselves rather than hand it off a fourth time.

**THE SOCCER SUITE IS SLOW BECAUSE OF ONE FILE. Both of my earlier diagnoses
were measurement bugs** `[bisected 2026-08-20]`.

    tests/test_soccer_market_anchoring.py  ALONE  13 passed in 1,064s (17m44s)
    the other 41 soccer files                     ~136s combined
    collect-only, all 8,900 tests                    6.06s

Eight tests in that ONE file: 241s, 163s, 124s, 122s, 120s, 118s, 116s, 55s.
They call `simulated_home_win_probability(simulations=300)` and
`solve_market_rating_shift(simulations=100)` — **Monte Carlo inside a solver
loop**, so every solver iteration runs hundreds of match simulations. Real
compute; not a fixture, not collection, not accumulated state.

**RETRACTED — THREE claims, all mine, all from measurement bugs:**
1. *"The cost is COLLECTION."* No: collection is 6.06s for all 8,900 tests.
2. *"Use explicit file lists, not `-k`."* No: explicit was SLOWER (875.8 vs 822.4).
3. *"Superlinear TEST INTERACTION, 4.76x."* **No — and this is the instructive
   one.** My per-file timing loop used `timeout 300`, which KILLED this file and
   wrote `none`. It never entered the "sum of individual runs", so the baseline
   was missing the single most expensive file. Files 1-25 showed 1.0x only
   because this file is #31. **There is no interaction effect.**

**What is actually true:** one pathologically slow file dominates. **CONFIRMED by removing it:**

    all 67 soccer files                    875.8s
    the same minus that ONE file (13 tests) 149.6s   633 passed, 0 failed
    -> 5.9x faster; that file was 83% of the suite's runtime

So `--deselect tests/test_soccer_market_anchoring.py` makes the soccer suite
usable as a pre-deploy gate (under 3 minutes) instead of ~15. **The proper fix
is that file's own `simulations=` counts, and it is NOT mine to make:** lowering
a simulation count to make a test fast is how a test stops testing anything, and
the precision each assertion needs has not been analysed.

**Note on precision:** the same file measured 511s inside a 42-file run and
1,064s alone, because several runs overlapped on this machine. Treat the
magnitude as "8-17 minutes, dominant either way", not a precise constant.

**CONSOLIDATED DEPLOYS ARE THE WORKING PATTERN FOR A BUSY DAY** `[2026-08-20]`.
114 files / 5+ lanes / **3 deploys**: refresh-worker `db469003` (9 files,
19:09:55Z), live-odds-worker `a381d652` (38, 20:04:14Z), web `454f3caa` (67,
20:20:34Z). Each verified BY CONTENT per file; web also on the served payload.
Tool: `scripts/build_consolidated_graft.py`. **It prevented two reverts,
measured**: web's parent moved TWICE mid-build so the file list was RECOMPUTED
(67→68→67, dropping `soccer/cards.py` once another deploy carried it), and the
builder REFUSED a graft when web read `d9a23a38` as live while `00541a8d` was
`update_in_progress`. **Reading the parent live is NOT enough — an in-flight
deploy leaves the OLD sha reading live.**

**THE SESSION DIGEST DOES NOT READ state.md, AND READS ONLY HEADINGS FROM
learnings.md** `[measured 2026-08-20 from .claude/hooks/session-start.sh]`.
state.md's own size costs nothing at session start — the hook's header records
that v1 cat-ed it, spent the whole ~2KB budget, and that was the bug being
fixed. learnings.md is grepped for FORBIDDEN/EXONERATED **headings only**, and
`lanes.md`'s OPEN LANES section truncates on **lane COUNT** (`LANE_CAP=600` vs
~6,489 B raw), not on file size — trimming lanes.md 134,022 → 98,118 B did NOT
stop it truncating. **So "LEDGER OVER BUDGET" is a byte warning about the cost
to whoever OPENS a file; it does not describe the digest.** Do not trim these
files expecting the digest to change.

**35 of 44 STANDING RULES REACHED NO SESSION until 2026-08-20.** The digest
grepped `^###` while learnings.md entries are written at `##` — 8 matched, 35
invisible, including "never point a worker publish URL at a public hostname".
Fixed in `362c505d`: matches `^#{2,3}`, clips each entry to 64 chars, takes the
TAIL so the newest rules show, and prints "showing 6 most recent of 43".
**Relaxing the grep alone would have been worse** — 43 headings ≈ 4,800 B against
a 450 B cap taken in append order would have shown only the OLDEST. That edit is
a CROSS-LANE take of `.claude/hooks/` (claimed by `repo-coordination`, OPEN)
made under explicit user instruction and messaged to them.

**NFL CLOSING LINES ARE FREE AND LOCAL — do not buy them.** nflverse
`schedules/games.csv` (2.2 MB) carries `spread_line` and `total_line` back to
**1999** alongside final scores; fetch via
`ingestion/nflverse_ingestion.py`-style release URLs, cached under
`tracking/nflverse/schedules_games.csv`. **`spread_line` IS the home-margin
prediction** (positive = home favoured), verified empirically: r=+0.431 with
realised home margin, MAE **10.264 as-is vs 14.645 negated**. Using it negated
inverts every conclusion while producing plausible numbers.
**OddsAPI historical NFL starts in 2020** — 2018/2019 return zero events (billed
0 credits), so a pre-2020 backfill buys nothing.

**NO USABLE NCAAF INJURY FEED.** CFBD's OpenAPI spec: **74 endpoints, none**.
ESPN core — NFL control **597 fresh injuries / 8 teams** vs CFB **1 record
across 60, dated 2020-11-21**. Cause: the NCAA has no mandatory injury report.
Re-check in-season with `scripts/probe_ncaaf_injury_feed.py`.

### SERVING STATE

- **Picks SUPPRESSED**, `syndicate/features/football/pick_gate.py`, default-DENY.
  `LIFT_CONDITION` (web `ea6f431f`, 8/8 probes) requires: ATS above the better
  naive baseline, 95% CI LOWER bound above **52.4%**, out-of-sample with subsets
  pre-specified, denominators in **BETS not rows** (per-book rows overstated
  significance **3.4×**). Pinned by `LiftConditionTests`.
- **Board serves SP+, WEEK 1 ONLY** (pregame window). 51 games, \|margin\| max
  50.60, SD 12.93. **A SINGLE READ IS NOT A MEASUREMENT** — 12 probes once read
  9 PPA / 3 SP+ because gunicorn workers cache independently. Probe repeatedly.

### ENGINE FACTS THAT REMAIN TRUE

- **9 feature blocks / 65 keys consumed, 0 of 3 production entrypoints pass a
  payload.** Every NFL/NCAAF game runs on four rating scalars plus a hardcoded
  `pace_seconds_per_play=24.0`. Reachability: 21 of 21 drive-prior fields move
  when fed. **Wiring it is NOT indicated** — §10's domination result means the
  payload path cannot supply what is missing. Gate:
  `scripts/football_sim_input_checklist.py`.
- Of the unfed blocks: `defensive_metrics` is **MISROUTED** (all 7 keys sit in
  `team_metrics`), `pace` is **NULL AT SOURCE** (all 4 keys `None`).
- **TWO unrelated football models exist.** `FootballSimulationAdapter` is not
  smartsim2; do not conflate them.
- `smartsim2/calibration_profile.py` showing as `M` in `git status` is a CRLF
  artifact, not an edit.

### OPERATIONAL — cost hours to learn

- **The artifact reaches web via GIT → WEB DEPLOY → BOOTSTRAP → MOUNTED DISK,
  NOT via the worker.** `smartsim2_projections_*.csv` matches none of the 127
  `HOT_ARTIFACT_PATTERNS`; web reads `SYNDICATE_NCAAF_SOURCE_ROOT`;
  `bootstrap_data_root` copies and **never prunes**. So the refresh-worker
  season-projection autorun regenerates a file **nothing reads**, and deleting a
  stale artifact from git does NOT remove it from the served disk.
  **CHANGED 2026-08-20 (`32148cac`, live on web `15a0be64`) — this path is now
  SEED-ONLY.** The boot sync copies an artifact root file only when the
  destination is ABSENT. A NEW week's `smartsim2_projections_*.csv` is a new
  path and still arrives; a REGENERATED file for a week already on the disk no
  longer overwrites it. Pruning is unchanged (still none). This makes the
  allowlist + `publish_hot_artifact` path the only way to UPDATE an NCAAF
  artifact already on web, so the owed allowlist entry is now load-bearing
  rather than tidy. Both
  generators now call `publish_hot_artifact`, INERT until
  `*_source/data/smartsim2_projections_*.csv` is allowlisted (handed to
  `soccer-odds-capture-cadence-gap`; asserted as `expectedFailure`).
- **`deploy_preflight --service web` can NEVER return CLEAR** — web emits no
  process telemetry. Use `--allow-off-main` and read the live SHA directly.
- **Do NOT diagnose NCAAF from a local checkout** — `data/**` is a lossy mirror.
- Stage 0 ledger: `syndicate/features/football/pick_ledger.py` +
  `build_ncaaf_pick_ledger.py` / `build_nfl_preseason_pick_ledger.py`.

## [ncaaf-calibration-profile-live] THE PROMOTED NCAAF PROFILE IS LIVE, AND PROMOTING ONE IS A **CODE DEPLOY** `[verified 2026-09-05, render]`

The production read `ncaaf-pace-block` left owed is DISCHARGED. refresh-worker
(`eb7951fe`) emits `[calibration] ncaaf profile source=artifact
version=ncaaf-goal-line-refit-1 goal_line_touchdown=True
drive_yardage_multiplier=0.95` — `source=artifact`, and BOTH discriminating
fields disagree with the in-source defaults (`False` / `1.15`), so this
distinguishes the promoted fit from the default rather than merely reporting a
healthy-looking string. All **51/51** rows of
`smartsim2_projections_2026_wk1.csv` carry `profile_source=artifact` +
`profile_version=ncaaf-goal-line-refit-1`, and all **51/51** served
`/ncaaf/api/cards` join back to that CSV by team pair with projected
total/spread equal to 1dp. Every NCAAF number on the board came from the
promoted fit. **Nothing is owed and there is no env var to set.**

**THE OPERATIONAL FACT, and it is the reusable one: a calibration profile is
selected by the CODE DEPLOY, not by configuration.**
`SYNDICATE_CALIBRATION_PROFILE_DIR` and
`SYNDICATE_CALIBRATION_PROFILE_PATH_NCAAF`/`_NFL` are **absent from all three
services** (enumerated live, paginated: web 77 keys, refresh-worker 154,
live-odds-worker 129). `calibration_profile_dir()` therefore falls through to
`repo_root_from(__file__)/data/calibration` — path arithmetic on the module's
own location, **with no `SYNDICATE_DATA_ROOT` term**. So the artifact publisher
CANNOT deliver a profile: it is not in `HOT_ARTIFACT_PATTERNS`, and
`export?pattern=ncaaf_source/historical_truth/*&names_only=1` returns
`count=0`. Promoting a re-fit means deploying every service that runs that sim.

**Only refresh-worker runs an NCAAF sim** (as a subprocess). web and
live-odds-worker never import the module, so `[calibration] ncaaf` matching
nothing in their logs is NOT evidence about them — they have no emitter to be
silent. (`learnings.md`: absent signal is a fact about the emitter.)

### Three corrections to the headline this lane promoted on

The `15.00% -> 7.24%, impossible drives 159 -> 0` framing is wrong in shape,
though the decision it justified stands.

- **`15.00% -> 7.24%` is the MEAN NORMALIZED ERROR over 7 scored metrics — NOT
  an impossible-drive rate.** The two were conflated.
- **`159 -> 0` is a COUNT at 120 games, and a count is not a rate.** State it as
  **~6.5–7.3% of all drives -> 0.00%**; the engine docstring independently says
  6.60%.
- **`-7.76 pts` is the TOP of the range, not the centre.** Out-of-sample
  replication over three seed blocks (200 games, neutral ratings): promoted
  **7.24 / 7.33 / 7.00** — stable, so the fit is NOT in-sample-only — but the
  DEFAULT arm ranges **15.00 / 13.94 / 12.72**, and the fit's own block is the
  default's WORST. Block mean is **13.89 -> 7.19, −6.70 pts.**

### On a REAL slate the composite gain mostly evaporates — the impossible-drive rate is the metric that survives

30 games kicking off 2026-09-05, 300 seeds, real SP+ ratings. The local run
reproduced production's served per-game score means **exactly (60/60 values,
max |diff| 0.0000)**, so these are production's own drives, not an analogue.

| | promoted (what ran) | shipped default (counterfactual) |
|---|---|---|
| impossible drives (>100 yd) | **1 / 221,557 = 0.0005%** | 18,647 / 190,850 = **9.77%** |
| longest drive | 103 yd | **528 yd** |
| scored mean abs err | 9.78% | 10.55% |

The composite improves only **0.77 pts** here, not 7.76. The default's
`yards_per_drive` (44.37 vs truth 42.49) even looks BETTER than the promoted
profile's 32.50 — bought by 9.77% of drives being physically impossible. **The
default's estimator is right for the wrong reason.** A single-slate composite is
confounded by slate composition; the impossible-drive rate is the
slate-independent, interpretable number. Judge future football re-fits on it.

### Two traps left standing

- **`smartsim2_projections_2026_wk2.csv` on production is a PRE-REFIT July
  artifact** — 49 rows, `generated_at` 2026-07-21, PPA-rated, and **no
  `profile_source`/`profile_version` columns at all**. Nothing serves it because
  the resolver pins week 1. **If the week resolver is ever fixed without
  regenerating wk2, the board silently moves onto a pre-refit artifact** — and
  the absent stamp columns mean it would not announce itself.
- **NFL's resolution is UNOBSERVABLE from production.** No `[calibration] nfl`
  print, and `nfl/smartsim2_projection.py` carries `profile_name` but not
  `profile_source`/`profile_version`. NFL running its in-source default (the
  deliberate decision) rests on inference-from-absence: file absent at the
  deployed SHA, no env override. NCAAF has an emitter AND an output stamp; NFL
  has neither. One line + two columns closes it.
- `calibration_profile_store.py`'s docstring — *"Nothing calls this yet from a
  live sim path"* — **is FALSE** for NCAAF since `600a753a` (2026-08-27) and for
  NFL since `#440` Phase 5. It is the first thing a future session reads here.

**Method note that cost a wrong first read:** `render_logs.py` returns the
NEWEST `limit` matches in a window, so a wide `--text calibration` window
returns 40 lines of `INTEL_TRACE {"calibration_error": ...}` and **hides** the
one line that matters. Narrow the window and quote the bracket: `--text
"[calibration]"`.

## [nfl-archived] NFL — earlier closed work, archived — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [football-model-leaks] FOOTBALL — TWO MODEL LEAKS, BOTH FIXED `[verified 2026-08-19, lane football-model-owner]`

**The football feature payload was LEAKED.** `build_nflverse_game_metrics`
computes EPA/success-rate/pass-rate from **the game being predicted** —
`_match_game_rows` filters pbp to that one matchup+week. Measured over 285 games
of 2023: **r = 0.988** against the final margin. Replacement
`syndicate/features/football/features/asof_team_form.py` certifies at **r = 0.235**
via an in-module assertion, not just a test.

**NCAAF ratings were LEAKED for backtests.** `/ppa/teams?year=S` is
season-aggregate. Measured over 558 games of 2024: full-season **r = 0.663** vs
as-of **0.509** — 30% inflation. Fixed to aggregate `/ppa/games` over weeks < N.
**`/ppa/teams` ACCEPTS `week=N` AND IGNORES IT** (identical rows and values), so
the obvious fix is a silent no-op. **`seasonType=regular` is load-bearing**: without
it `/ppa/games?week=1` returns the College Football Playoff, importing January
games into a week-8 rating — worse than the leak it replaced. **The 2026 opener is
UNAFFECTED** (no in-season history → 2025 prior-season fallback, verified).

**A population checklist CANNOT detect leakage.** A leaked field is 100%
populated by construction and passes every check this repo has — the input
checklist marked these FED, reachability passed, unit tests passed.

## [football-board-defects] FOOTBALL BOARDS — THREE DEFECTS SHIPPED AND MEASURED `[2026-08-18/19]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [football-engine-levers] FOOTBALL ENGINE — THE PAYLOAD IS THE WEAK LEVER `[measured 2026-08-19]`

**`feature_generation_payload` moves margin 0.553 pts; the RATINGS path moves it
2.322 — 4.2x, or 17.2% vs 4.1% of the 13.5-pt margin SD.** `build_drive_priors`
builds ONE game-level profile (never reads `away_*_rating`); per-team
differentiation is in `play_simulator.py:258-259`, on the ratings path.
**All three generate scripts ALREADY pass ratings, and NFL's are already as-of**
(`_mean_epa(..., before_week=week)`). The unwired payload was real and is the
wrong lever.

**AND THE PAYLOAD IS A MEASURED NULL** `[Phase 3, n=269, 2023, 300 seeds]`:
`dCRPS +0.0226 (0.97 SE)`, `dMAE +0.0256 (0.88 SE)` — nominally worse, under 1 SE
both ways. **It does not ship, and Phase 4 is moot.** An intervention worth 4.1%
of the outcome's spread cannot produce a detectable accuracy change even if
directionally perfect. **Anyone revisiting this should test the RATINGS path, not
the payload** — `asof_team_form.py` is built and certified for exactly that.

**Engine baselines do not match real NFL distributions** — `success_rate` assumed
0.500 vs a league mean of 0.422, `explosive_play_rate` 0.100 vs 0.066. Raw values
put league-mean `offense_index` at 0.405 vs a neutral 0.500 and suppressed every
game's total by ~2.6 pts. Re-centring on the **as-of** league mean restores 0.500.

### CONFIRMED — the emitter trace, and `psutil` was never the cause `[2026-08-19]`

**Upgrades the PROVISIONAL trace above to CONFIRMED, on direct evidence rather
than inference.** Two lines from the SAME tick of the SAME process on
refresh-worker, read from the Render logs API 2026-08-19T01:50:41:

    PROCESS_ENUM_DEBUG {"error_count": 1, "errors": ["psutil_unavailable:ImportError"], ...}
    ALL_PROCESS_MEMORY {"accounted_rss_mb": 1312.168, "container_memory_headroom_mb": 1811.645, ...}

**The worker emits `ALL_PROCESS_MEMORY` WHILE psutil is unavailable.** It falls
back to procfs and enumerates fine. So:

- **`psutil` is DEFINITIVELY not the cause** of web's dead preflight. The
  retraction filed earlier was right, and this is now measured rather than
  argued. **Installing it would have changed nothing.**
- **The caller trace is CONFIRMED.** The emitting line arrives from
  `live_lens_loop` — `start_live_lens_loop` is imported by
  `run_live_odds_refresh_worker.py` and by nothing else, and `app.py` starts the
  live-refresh and intelligence-state loops but NOT live-lens. **Web has no
  caller. It is not broken; it was never wired.**
- Therefore **`deploy_preflight.py` gates every service on a WORKER-ONLY
  signal**, and web's preflight has never been satisfiable. Tonight's
  break-glass was not an exception to a working gate — it was the only path web
  has ever had.
- **The fix is to make preflight service-aware**, NOT to add periodic work to a
  web process. A web deploy has no long job to land on: measured tonight, 4
  processes, all infrastructure, zero jobs.

**FOUR causes were proposed for this symptom and three were refuted** (broken
sampler / missing psutil / deleted emitter). This is the fourth and the only one
with direct evidence. **Instrument check that made it trustworthy:** the Render
logs `text=` filter was verified to work first — four strings visible in the
unfiltered feed each returned rows — so a null result from it is now evidence of
absence rather than of a broken query. **Earlier tonight I reported nulls from a
query I had never proven could return non-null.**

## [ncaaf-chip-grid-join] THE CHIP->GRID JOIN CALLED `teams_match` WITH ITS ARGUMENTS INVERTED `[measured 2026-08-29T18:43-18:59Z, web+worker 95c4fb12]`

**`board_enrichment._side_matches` called `teams_match(sport, row_team, token)`.**
The signature is `teams_match(sport, token, row_team)`, and the final heuristic
(`team_aliases.py:660`) splits **`row_team`** into words asking whether any
`word.startswith(token_norm)` — so it only answers when `token` is the SHORT
side. Over 8 real pairs from the 2026-08-29 slate: **0/8 as called, 8/8
reversed.** Not even `USC` against `USC Trojans`.

**Why it survived:** with an alias map BOTH sides resolve canonically and
`teams_match` returns at `team_aliases.py:644`, which is order-INDEPENDENT.
`_alias_map` is **EMPTY for ncaaf, nhl and ncaab** — only those three reach the
order-sensitive branch, and NCAAF was the one with a live slate.

**VERIFIED on `book-grid`:** ncaaf `game_state` went
`{"chips": 8, "rows_matched": 0, "unmatched_teams": [14 teams]}` ->
**`{"chips": 8, "rows_matched": 44}`**, `unmatched_teams` gone.

**Blast radius measured BEFORE shipping**, on production payloads, because this
touches every sport:

    sport   rows chips | as-called amb | reversed amb | delta
    mlb      300    17 |       300  35 |      300  35 | +0
    wnba     300     2 |       300   0 |      300   0 | +0
    nfl      300    16 |       115   0 |      115   0 | +0
    soccer   300   231 |       285   0 |      290   0 | +5
    ncaaf     43     8 |         0   0 |       43   0 | +43

No sport loses a match, none gains an ambiguous row, no pair flips True->False.
MLB's 35 ambiguous rows are identical in both orders and pre-existing.

**PROVEN ON BOTH SURFACES, and the distinction between them is load-bearing.**
`book-grid` re-runs `attach_game_state` at READ time on web; `layer2-shortlist`
is a PURE READ (`source: layer2_shortlist_artifact`) of a pool built on the
worker inside `_build_candidate_pool`, so it changes only when that pool is
REBUILT.

    layer2-shortlist  written_at 2026-08-29T19:03:08Z (post-fix)
    ncaaf  0/96  ->  49/92        mlb 400/400  wnba 374/374  soccer 400/400  nfl 18/18

    by kickoff date:  08-29  28/28 ALL     09-03   2/20 partial
                      08-30   6/6  ALL     09-04  13/38 partial

**Every row for a game today or tomorrow carries state**, against zero on every
date before. Coverage is strictly better everywhere; nothing regressed.

**Residual, NOW MEASURED — TWO causes, and only ONE is a defect.** Over the 10
unmatched matchups on 09-03/09-04:

- **9 are CORRECT.** They are FBS-vs-**FCS** (Albany, Bethune-Cookman,
  Merrimack, West Georgia, Arkansas Pine Bluff, Eastern Illinois, Idaho,
  Indiana State, North Carolina A&T). The board cards FBS-vs-FBS only, so no
  chip is built and no join is possible. This is the curated-subset property,
  working as designed — the earlier "hypothesis" is confirmed for these.
- **1 IS A REAL ALIAS GAP.** `Massachusetts @ Rutgers`, 09-03, **fbs vs fbs**,
  chip correctly built as `MAS @ RUT`. The Rutgers side matches on BOTH name
  and abbr; the UMass side fails on both:

      row "UMass Minutemen"  vs  chip name "Massachusetts" -> False
      row "UMass Minutemen"  vs  chip abbr "MAS"           -> False

  No heuristic can bridge `Massachusetts` <-> `UMass`; it is a vocabulary fact,
  the same class as `UNC` <-> `North Carolina` measured on NCAAB. Costs **4 rows
  on a future date**; no game in play is affected.

  **AND POPULATING `_alias_map("ncaaf")` DOES NOT FIX IT — built, measured,
  REVERTED 2026-08-29.** A map derived from
  `ncaaf_team_registry.unambiguous_team_index()` (2,232 keys) still returned
  `None` for `UMass Minutemen`, because team 113 carries no `umass` key — a
  derived map cannot invent vocabulary its source lacks. Worse, it made
  `canonical_team("ncaaf", "MAS")` resolve to **`UMass Dartmouth`** (team 379's
  real abbreviation), and once a map exists `teams_match` is MAP-AUTHORITATIVE
  (`team_aliases.py:640-644` skips the heuristics), turning a harmless miss into
  a confident wrong answer. Control after reverting: map back to 0 keys, the 8
  slate pairs still 8/8. **The gap is REGISTRY DATA, upstream of both** — CFBD
  does not ship the alias and `cfbd.py:475` is faithful to it. Handed to lane
  `ncaaf-settlement-resolver`:
  `.syndicate/handoff_2026-08-29_ncaaf_umass_alias_gap.md`.

## [ncaaf-live-lens-state] THE NCAAF LIVE LENS'S STATE BRANCH WAS UNREACHABLE, NOT EMPTY — **FIXED AND VERIFIED IN PRODUCTION** `[measured 2026-08-29T16:30:28Z, web 061d5b2b, lane ncaaf-live-lens-state]`

> **`Final` DISCHARGED 2026-08-29T19:32:02Z.** ESPN `post=1`; lens `Final=1`, eyebrow `'Final'`, `Score: NC 15 - 10 TCU`; strip head `'Final'`, rows `NC 15 / TCU 10`. The 'Final is unit-tested only' caveat below is superseded.

**The reading that matters, one script run, production and ESPN together:**

```
ESPN        events=8  in=1  post=0   UNC VS TCU  "4:00 - 1st Quarter"
PRODUCTION  games=51  Live=1  Final=0  Pregame=50
            card "NC @ TCU"  eyebrow 'Q1 - 4:00'
VERDICT     MATCH
```

25 minutes earlier, same endpoint, same game already in progress:
`Games 51 | Live 0 | Final 0 | Pregame 51`.

**`ncaaf/cards.py` contained ZERO occurrences of `live_state`.**
`publication_adapter._shared_game_state` derives `live`, `final`, `period` and
`clock` from exactly that key, so every NCAAF card carried
`{live:false, final:false, period:null, clock:"", startTime:null,
status:"Week 1"}` — `status` a constant, not a state. `_game_state_label`'s
live branch could not be taken by any input.

**This is the entry directly below this one coming due.**
`[ncaaf-board-surfaces]` shipped the state PATH on 2026-08-27 and said so
honestly: *"The live lens's state PATH is tested; its DATA cannot be until a
game is in progress."* That was accurate and it was a **deferred
falsification** — the first NCAAF game of the season was the test, and the
test failed. A caveat written down is not a defect prevented; it is a defect
scheduled.

### The join key was in the payload all along

`logo_url` carries ESPN's own team id (`.../i/teamlogos/ncaa/500/153.png`),
stamped by `_resolve_branding`. Measured over the 51-game week-1 board:

| key | result |
|---|---|
| **ESPN team id pair** | **51/51 carry both, 51 distinct pairs, exact** |
| abbreviation pair | **0 of 10** comparable games matched |
| display name | unsafe — no alias map, degrades to a prefix heuristic |

Board abbreviations are CFBD's, not ESPN's: `NC`/`UNC`, `SJS`/`SJSU`,
`NS`/`NCSU`, `VIR`/`UVA`, `JS`/`JVST`, `NDS`/`NDSU`, `SS`/`SAC`, `EM`/`EMU`,
`NMS`/`NMSU`, `FS`/`FSU`. **A board joined on abbreviations reports every game
pregame forever and is indistinguishable from the bug being fixed.** Names are
worse — `ncaaf-settlement-resolver` measured that NCAAF has no alias map, so
"Michigan" matches "Michigan State".

### What changed

- NEW `syndicate/features/ncaaf/live_game_state.py`. State semantics are
  IMPORTED from `scripts/poll_ncaaf_live_state._game_from_event` (owned by
  OPEN lane `ncaaf-settlement-resolver`, untouched) rather than
  reimplemented — that module warns against exactly this drift, and it already
  measured that `final` needs BOTH `completed` and `state == "post"`. This
  adds only the join key and `period`/`displayClock`, off the same event.
- Request-path fetch behind a 45s TTL cache and
  `warn_if_compute_in_request_path` — the shape `nfl/live_game_state.py`
  already runs in production. Fails soft to an EMPTY index; `matched` is
  logged separately from `live`/`final` so a dead join and a quiet slate are
  distinguishable (`NCAAF_LIVE_STATE ...`).
- Only dates that have STARTED are fetched — one call on opening Saturday, not
  ten for a week spanning 08-29..09-07.
- The lens now shows the REAL score (`Score: NC 3 - 3 TCU`) above
  `Predicted final:`. The old "NO LIVE SCORE, deliberately" rule was correct
  and its premise is now false: it refused because the only `score` in the
  contract was the PROJECTED one.
- `startTime` **8/51 -> 51/51**, from `scoreboard.kickoff` already on the
  card. Findings 2026-08-26 §1 flagged the null; no fetch was needed to fix it.

### Two things this did NOT fix, stated so nobody reads a match as completeness

- **NCAAF is still absent from `_LIVE_LENS_SPORTS`** in
  `shared/live_lens_loop.py` (`mlb, nba, wnba, soccer, nfl`). The cross-sport
  live-lens SNAPSHOT carries no NCAAF. This lane fixed the NCAAF board and
  lens, which are a different subsystem.
- **`Final` has not been observed in production.** At the time of the reading
  no game had finished. The final path is unit-tested only — the same class of
  claim that `[ncaaf-board-surfaces]` made about the live path, and it is
  named here rather than left implicit.

### A lane guard was silently claiming every sport's cards builder

The UNOWNED lane `soccer-board-mlb-parity` had a bare `cards.py` in the prose
of its `- Files:` block, inside a note that *said the claim had been removed*.
`lane-guard` matches on path SUFFIX (`rel.endswith("/" + f)`), and a bare
filename has no directory to disambiguate it — so that token claimed **mlb,
nba, nfl, ncaaf and wnba** cards builders at once, and blocked an NCAAF edit
during the first game of the season. `check_lane_invariants` passed the whole
time: it verifies each claim has exactly ONE holder, and this one did. Same
basename-collision class this file already records for `live_lens` across
eight sports. **A disclaimer beside a path does not unclaim it — only deleting
the path text does.**

## [ncaaf-market-basis-edge] NCAAF SERVES PICKS AGAIN — on a MARKET basis; the model gate is UNCHANGED and still denies `[verified 2026-08-30 03:0x-05:5xZ, web+refresh-worker+live-odds-worker `d7cda903`, lane ncaaf-market-basis-picks]`

**`pick_gate` was keyed `(sport, market)`, so a verdict about the MODEL also
denied a claim it never measured**: *this book's price beats the market's own
consensus*. Measured production 2026-08-29: **90 of 90 sides carried
`best[side].edge_vs_consensus_pct` while 45 of 45 rows rendered no edge.** The
number was computed (`book_grid.py:496`) and discarded at render. Registry is
now `(sport, market, BASIS)`; every model verdict is byte-identical and
`("ncaaf","spread",model)` still denies at n=2233, t=17.20.

**IT IS A PRICE-SHOPPING DELTA, NOT EXPECTED VALUE.** Anchor is
`consensus_vigged_price`; nothing de-vigs it. Adding Pinnacle improved the
ANCHOR, not the claim. Upgrading this to +EV owes a de-vig and a measurement.

**Served, verified:** sharps restored (book set **11 -> 25**, `pinnacle` 70 rows,
`novig` 158) — the env var `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` was **already
`eu,us_ex` on both workers all along**; its only READER was the MLB fetcher
until this lane, so it sat inert. Displayed sides **143 -> 418**, servable
**5 -> 125**, edge **p50 0.75 pts** — the gain is COVERAGE, not size (414 of 552
sides previously had one quoting book). `/ncaaf/picks` serves its 12-card cap;
"Picks suppressed" is gone from the served HTML.

**Guards fire on real data and that is why the big numbers are absent:** of 90
sides on the 08-29 slate, 58 refused "game has started" and 32 "1 book quoting",
including a 16.04pp outlier that was ten quotes on ONE line 115s apart (over
+1200 vs +175) on a live game.

**UNVERIFIED, and must not be cited as measured:** that this edge is
profitable; the two serving constants (3 books, 1.0 pt) are unfitted; no NCAAF
2026 outcome exists to grade the 125 picks against.

## [ncaaf-board-surfaces] NCAAF BOARD SURFACES — projections published, compact strip rebuilt, live lens state-aware `[measured 2026-08-27T15:47Z, web 87c36d05]`

**Projections reach the SHARED contract: 0/51 -> 51/51** on `home_mean`,
`away_mean`, `margin_mean`, `total_mean`, `home_cover`, `total_over`. They were
on the card all along in `metrics` — a DISPLAY list of label/value pairs — while
`shared_predictions`, which Layer 1, Layer 2, the compact cards and the market
board read, was null on every field but `home_win`.

**This was never the pick gate.** The gate governs PICKS and is correctly
denying them (margins lose to the close by 3.56 MAE at t=17.2). Projections are
a different surface that was never published.

**Compact strip, measured in a browser (desktop + 375px mobile):**

    generic fallback  435px   no crests, two PROSE blocks repeating the card below
    soccer's shape    181px   uniform across ALL 51, crest <img> 22x22

Uniform height is the load-bearing number — direct evidence nothing wraps.
`logo_url` was on every game and never rendered.

**Live lens is state-aware:** eyebrow is "Q2 · 7:31" / "Final" / kickoff instead
of one constant string x51, plus a Live/Final/Pregame header split. NO LIVE
SCORE — the contract carries none, and the only `score` in it is the PROJECTED
one.

**UNVERIFIABLE IN PRODUCTION, and say so rather than let a green read imply
otherwise:** `_EngineRowProjection` is unit-level only.
`build_smartsim_cards_page_context(selected_week)` takes a WEEK ONLY; 2026 has
no engine rows, so the board always falls through to standalone and the engine
path is UNREACHABLE while 2026 is active. The live lens's state PATH is tested;
its DATA cannot be until a game is in progress.

## [ncaaf-props-live] NCAAF PLAYER PROPS ARE ON THE BOARD — first capture in this platform's history `[measured 2026-08-27T03:07:03Z, lane ncaaf-opener-regions-props]`

    prop_rows=38  status_rows=38  games_with_props=6  with_model_prob=33
    NC props   Jordan Shipp  Anytime TD - 4 books  +195  model 0.3602
    NC props   Demon June    Over 35.5 Rush Yds    -114  model None

**The proof is a 17-sample series, not a spot read.** 0 for 50 minutes straight
(02:17:33Z..03:00:56Z) with the artifact ALREADY on disk, `-1` through a deploy,
then 38 — which is what separates "web lacked the READER code" from "the data
was missing". `fetch_ncaaf_oddsapi_props_local.py` had existed with NO CALLER;
it now runs from `refresh_odds_sources.py` and publishes to an allowlisted path.
Multi-book: the parser kept 1 of N books before, now aggregates all (60 → 329
rows on capture).

`model None` on the yardage line is CORRECT — the model covers **Anytime TD
only**, because the 2025 backtest (Brier 0.18168) showed the player's own mean
beats it on continuous markets. **No 2026 outcomes exist yet, so production
calibration is UNVERIFIED.**

Region policy is **`us` ONLY** (user, 2026-08-27) — narrowed from `us`+`us2`.

## [ncaaf-payload-vs-market] THE ADVANCED-DATA PAYLOAD DOES NOT CLOSE THE GAP TO MARKET — a VALID null `[measured 2026-08-27, 693 paired games]`

    model MAE payload OFF   15.184
    model MAE payload ON    15.144
    market MAE, same games  11.854
    gap_to_market_ON        +3.290    BAR WAS <= 0

Closes **1.2%** of the 3.33-point gap; would need to be ~80x larger to ship.
**This is a null, not an unfed pipeline** — priors-moving block coverage 98.6%
(coach_continuity 714/714, returning_production 704/714). An earlier version of
the same harness reported "100% coverage" while both of those were absent for
every game. **Do not read the -0.040 as directional**: the harness emits no
paired SE or t-stat, so significance is unstated in both directions.

The WIRING is fine and stays (16/22 fields move, disk-backed, allowlisted).
Three blocks were never in this test and are the only route to a different
answer: `defensive_metrics` misrouted, `pace` null at source, `player_usage`
wrong grain. Full entry in `learnings.md`; do not re-litigate without new data.

## [ncaaf-readiness-2026] NCAAF SEASON READINESS — the model is ready, the MARKET is not connected to it `[measured 2026-08-25, four days before kickoff]`

Full assessment with every reading:
`docs/ai_context/ncaaf_readiness_assessment_2026_08_25.md`.

> **SUPERSEDED IN PART `[2026-08-27T03:18Z]`.** The prices ARRIVED. Same
> service, same endpoints: `candidate_generation sport=ncaaf generated=293
> markets={game: 255, prop: 38}`, 38 prop rows served on the board across 6
> games (33 carrying a model probability), and
> `PREGAME_PROJECTION_JOIN sport=ncaaf considered=94 projected=47`. What
> remains TRUE from this block: `odds_history_input entry_count=0
> present=false` — **there is still no NCAAF odds history, so no CLV is
> measurable for opening weekend.** ALSO SUPERSEDED `[2026-08-27T15:47Z]`: the
> projections this block reports as absent now reach the shared contract on
> 51/51 cards — see `[ncaaf-board-surfaces]`. The readings below are the 08-25 state,
> kept because the diagnosis chain in them is still the right one.

**51 games render with a projection on every one, in production and locally.
Every surface that needs a PRICE is at exactly zero.**

    [prod 2026-08-25T14:21:27Z]
    overview_counts        dashboard_games_count=51 data_health=partial
    game_candidate_inputs  gameMarkets=0 game_market_recommendations=0 markets=5
    GAME_CANDIDATES_EXIT   sport=ncaaf rows=0
    candidate_generation   generated=0 markets={}
    SPORT_PROPS_DONE       sport=ncaaf pregame=0 live=0
    odds_history_input     entry_count=0 present=false shard_key=2026_wk1

`markets: 5` is a KEY count, not a value count. Measured on the same board
`[local]`: **markets non-null 0 of 51, predictions non-null 0 of 51,
shared_game_state.startTime 0 of 51** — the last two while the NCAAF card's own
`metrics`/`panels` carry the numbers and the kickoff correctly. A cross-sport
consumer reading the shared contract sees a sport with no model and no clock.

**THIS WEEKEND IS COVERED. 8 games 08-28..08-30, all FBS-vs-FBS, all 8 simmed.**
But "Week 1" as the board serves it spans **08-29 → 09-07**: 8 games this
weekend, **43 on 09-03..09-07**, all under one undated `WEEK 1` badge. And the
FBS-only filter drops **48 of 99** week-1 games (every FBS-vs-FCS matchup) —
free this weekend, half the slate from 09-05.

### THE BLOCKER IS ONE ARTIFACT FAMILY WITH NO PRODUCER `[the part that does not self-clear]`

`_smartsim2_standalone_market_lines` (cards.py:237) reads exactly
`data/ncaaf_source/data/cfbd_lines_{season}_wk{week}.json`.

- Written ONLY by `fetch_ncaaf_market_lines.py` / `fetch_cfbd_lines.py`.
  **Both have ZERO callers** — not `refresh_odds_sources.py`, not either
  worker, not any `.ps1`. Manual scripts.
- **Zero `cfbd_lines_*.json` in git at any SHA**, none on this checkout.
- **Not allowlisted** — `cfbd_lines_*` and `smartsim2_projections_*.csv` match
  nothing in `HOT_ARTIFACT_PATTERNS`. **CORRECTED 2026-08-25 (same day):** the
  earlier wording here, "0 NCAAF patterns of 155", was literally true and
  materially misleading. The patterns are SPORT-AGNOSTIC GLOBS, and two of them
  already match NCAAF — `*_source/tracking/book_quotes/*.jsonl` and
  `*_source/data/book_grid/book_grid_*.json` (fnmatch, verified). So NCAAF is
  covered for the shared quote/grid transport and is NOT covered for those two
  named files. `#552` routes the new OddsAPI capture through the covered path
  precisely so no allowlist edit is needed.

What the sweep DOES run for NCAAF is `refresh_ncaaf_oddsapi.py`, writing
`recommendations_summary/` off the legacy 2025 predicted-totals CSVs — which
production already reports absent for 2026 (`artifact_status data_health=missing
artifact_exists=false`).

**PREDICTION, to be READ on 08-28/29 and not believed:** the sweep arms,
`book_quotes`/`book_grid` fill, Layer 1 may populate — and the cards' `markets`
block STAYS NULL, so Layer 2 candidates stay at 0. Tokens: `markets.total.line`
on `/ncaaf/api/cards?week=1`, and `GAME_CANDIDATES_EXIT sport=ncaaf rows=`.

### TODAY'S SWEEP EXCLUSION IS THE GATE WORKING, NOT A DEFECT — VERIFIED, NOT ASSUMED

    [prod 2026-08-25T14:23:45Z] SWEEP_OWNERSHIP_EXCLUDED date=2026-08-25
      kept=mlb,wnba,soccer dropped=nfl:… ncaaf:not_in_SYNDICATE_ACTIVE_SPORTS

`SYNDICATE_ACTIVE_SPORTS` is **not in `render.yaml`** (0 matches) — a service
env var, so editing it would NOT fire `blueprint_sync`. But it should not need
editing: `#520`'s weekly carve-out keeps nfl/ncaaf/ncaab on the fast tick on
game days regardless of that var, at `horizon_days=1` (today+tomorrow). No
NCAAF game within 08-25..08-26 → correctly dropped; 7 games on 08-29 → should
claim on **08-28**.

**Confirmed the carve-out actually fires in production**, same file, same live
SHA (`620734fb`, byte-identical to this checkout), on NFL:

    [prod 2026-08-24T03:55:01Z..04:56:14Z, repeating]
    SWEEP_OWNERSHIP_WEEKLY_CLAIM sport=nfl kept=true
      reason=claimed_by_fast_tick_despite_SYNDICATE_ACTIVE_SPORTS

**Caveat: horizon 1 means no line history before Friday** — no opening-line
capture, no CLV baseline across the week, on a market trading for months.

### WEB SERVES AN 08-19 ARTIFACT AND THE WORKER'S DAILY REBUILD NEVER REACHES IT

Live web `0e0017d7` carries `smartsim2_projections_2026_wk1.csv`, 51 rows,
`generated_at 2026-08-19T22:11:51Z`, committed `46ca8445` on 08-24. The worker
regenerates daily (`SEASON_PROJECTION_LAUNCHING sport=ncaaf … age_seconds=86552`,
08-24T20:43:54Z) into a file web never reads. `CFBD_API_KEY` is present on
refresh-worker as a service env var (it is in no `render.yaml`), so `#458` is
resolved there.

**CORRECTED 2026-08-27: the inference that the generator SUCCEEDS was wrong.**
An age sitting at one interval rather than growing shows the job FIRES on
schedule; it says nothing about whether it completes. Measured from the Render
logs API this evening, four runs 21:21:37–21:23:31Z each printed their
calibration line at module import and then died ~1s later:
`HTTP Error 429: Too Many Requests` in `load_ppa_ratings_asof`. A crashing job
and a succeeding job produce the SAME age signal, because the age is stamped by
the launcher.

**Only week 1 exists** anywhere. Week 2 needs a manual commit + web deploy.

### THE BACKTESTS CANNOT BE REPRODUCED FROM THIS REPO, AND FAIL SILENTLY

    scripts/grade_football_playability.py:42   REPO = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")
    scripts/grade_football_model_weight.py:36  REPO = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")

Run here with `PYTHONPATH` set: **`0 gradable games` for both sports, exit 0, no
error.** Proximate cause is that the pick-ledger CSVs they grade
(`{sport}_source/data/pick_ledger/pick_ledger_*.csv`) are **untracked and
absent** — `git ls-files | grep pick_ledger` returns only the builder, the
module and its test. The hardcoded path is a second, independent barrier.

The conclusions are almost certainly right (stated with n and CIs). The problem
is that **the entire evidence base for suppressing NCAAF picks lives on one
laptop**, and re-running it anywhere else returns a clean, plausible zero rather
than failing. That is `model_engine_standard.md`'s unfed-input signature applied
to the EVIDENCE layer instead of the input layer.

### UI — the compact card is inherited, not designed

NCAAF falls to `_scoreboard_strip_generic.html`; only `mlb_main` and
`soccer_main` have their own. Against MLB's strip, NCAAF's has **no kickoff
time** (badge reads `WEEK 1`, identical on all 51), no score, **no logo `<img>`
though `logo_url` IS in the payload**, no market chips, no odds-freshness stamp
— and the `PROJECTED TOTAL` tile is **clipped at the card edge on every card**.
Two of ~4 text blocks per card say a legacy engine has no prediction, the second
repeating the first verbatim.

**Two fields named for quantities they do not hold** (the 2026-08-21 rule,
recurring): the header stat **`Candidates 51`** counts GAMES — production
generated **0** candidates from this board; and the main card's **Section 2 is
titled `Enhanced Totals Engine`** while holding SmartSim 2.0's numbers, beside a
panel saying the Enhanced Totals Engine has no prediction.

Props parity: MLB carries 10 props/ladder surfaces, NCAAF **zero**.

### PROPS ARE UNWIRED BY DESIGN AND THE DESIGN'S OWN DEADLINE HAS PASSED

`fetch_ncaaf_oddsapi_props_local.py`'s docstring says the join should be built
"once real market coverage is confirmed closer to the season
(**~2026-08-23 to 2026-08-30**)". That window opened two days ago; nobody built
it. No caller anywhere, no `oddsapi_player_props_*.csv` on disk. And the planned
rate basis — `player_stats.py` over the `player_game_stats` snapshot — has
**never produced a file**, correctly, since no 2026 games have been played. So
**week 1 has no rate basis for a props ladder regardless**; props are a week-3+
surface, not an opening-weekend one.

### SIM ENGINE — checklist FAILs, and that is a truth, not a work order

`scripts/football_sim_input_checklist.py`: **FAIL, 9 alarms.** 9 blocks / 65
keys consumed, **0 of 3 production entrypoints pass a payload**; every NCAAF
game runs on four rating scalars plus a hardcoded `pace_seconds_per_play=24.0`.
**Do NOT read this as "wire the payload"** — the domination result (b=+0.990,
w=−0.028, 751 clean OOS games) says the payload path cannot supply what is
missing, measured at 4.1% of margin SD against the ratings path's 17.2%.

One loose end worth a look: the checklist's NCAAF arm reports
**`UNMEASURED: loader returned 0 games`** from a checkout where the board
builder returns **51**. Different loaders; the checklist is measuring something
the board does not use.

## [nfl-autorun-chain-order] THE NFL AUTORUN CHAIN RAN THE FANTASY ARTIFACT ABOVE ITS OWN INPUTS — FIXED IN CODE, NOT DEPLOYED `[measured 2026-08-25, lane ncaaf-oddsapi-game-lines]`

Detail: `todo.md` `#554`. Two `learnings.md` rules filed the same day.

**THE DEFECT.** `build_nfl_fantasy_projection_artifact.py` reads injury
availability (`use_injury_availability`) and the news layer.
`_launch_autorun_nfl_fantasy_artifact` sat ABOVE both
`_launch_autorun_nfl_injuries_fetch` and `_launch_autorun_nfl_news_capture` in
the autorun `elif` chain. **Only one branch fires per tick** (`#341`), so on a
busy slate the artifact was built from yesterday's injuries and news. Order now:

    reconciliation -> evaluation_settlement -> pbp -> injuries -> roster
      -> depth -> news -> fantasy artifact -> mlb -> ...

Starvation is NOT reopened: everything now above the artifact is daily or
six-hourly gated, so the NFL block needs ~6 winning ticks/day out of ~2,880.
`#341`'s starvation came from sitting below HIGH-FREQUENCY branches, still
forbidden by the window assertion in `test_nfl_fantasy_artifact_autorun.py`.

**FOUR POSITION COMMENTS WERE STALE AND TWO CLAIMED THE SAME SLOT** — the
fantasy artifact and the injuries fetch both read "THIRD, directly behind the pbp
fetch"; the pbp branch said "SECOND" while sitting third. All rewritten as
RELATIONSHIPS. **Ordinals in an ordered chain are wrong the moment anyone inserts
above them, and nothing reports it.**

**THE TESTS WERE FIGHTING EACH OTHER, WHICH IS WHY THIS SURVIVED.**
`test_nfl_injuries_fetch_autorun`'s `index <= 2` had been UNSATISFIABLE alongside
the same file's `injuries == pbp + 1` ever since `evaluation_settlement` was
inserted above the pbp fetch. Two assertions that cannot both pass are not an
alarm; the pair read as pre-existing noise and the real inversion hid behind it.
Absolute indices replaced with relative bounds throughout.

**SEVEN TESTS WERE RED ON `origin/main`**, six reported plus one found while
verifying. Three unrelated causes: this one, plus three tests still steering the
pbp read with `DATA_ROOT` after `#441` deliberately moved `_pbp_path` off it, plus
a platform-dependent `mocked_popen.assert_not_called()` (on Linux
`ctypes.util.find_library` shells out to `/sbin/ldconfig -p`; green on the Windows
dev box, red here — and `find_library` caches, so 4 of 5 identical sites were
passing on test ORDER alone).

**CROSS-LANE AND UNMEASURED.** `scripts/run_refresh_worker.py` is claimed by TWO
OPEN lanes and was already this repo's one contested file. The edit reorders
existing `elif` blocks and corrects comments — no branch logic, gating or body
touched; reverting is re-ordering the same blocks back. The priority call
(which NFL job wins a tick first) was made on PRODUCER-BEFORE-CONSUMER grounds,
not measured, because the effect cannot be measured from a checkout. **The
owners should confirm it.** Nothing is deployed; `autoDeploy` is off.

## [ncaaf-capture-live] NCAAF captures from real OddsAPI: 184/184 teams, 432 rows on the 08-29 slate `[measured 2026-08-25T23:07:25Z, lane ncaaf-oddsapi-game-lines]`

**Only VERIFIED facts here.** Narrative in `log/2026-08-25.md`; deploy readings in
`deploys.md`.

```
live-odds-worker 23:07:25Z
  EVENTS events=111 teams=184 resolved=184 unresolved=0
  QUOTES date=2026-08-29 events=7 rows=432 appended=18
  DONE   events=111 dates=14 rows_appended=74
```

- **`appended` is the reading, never `rows`.** 432/18 — the mirror already held NCAAF
  quotes, so a row count reads as success whether or not anything was captured. The
  190KB `book_grid` at 22:14 was refused as evidence for exactly this reason.
- Grid moved after the capture: `book_grid_2026-08-29.json` 190,954 → **198,278 B**,
  checksum changed; new `book_grid_2026-08-30.json` (28,892 B).
- **`HOT_ARTIFACT_PATTERNS` gates BOTH ENDS.** The registry pull failed with **403, not
  404** — the file was on web and web refused it, because web ran an older SHA with the
  old 155-pattern tuple. Deploying only the puller is not deploying the fix.
- **live-odds-worker never runs `bootstrap_data_root`** (zero lines in 7 days), so a
  git-tracked file is present on web and absent on that worker. That asymmetry is
  invisible from a checkout and is why every local test passed at `resolved=0`.
- `FIXTURE_CADENCE sport=ncaaf interval=86400 reason=far:88h_out` — in the loop, on a
  DISTANCE-based cadence that tightens as kickoff nears. Being claimed by the fast tick
  does not mean a fast cadence.
- ~~**Layer 2 does not cover NCAAF until 2026-08-26**, and that is correct:
  `_SLATE_WINDOW_DAYS["ncaaf"] = 3` and the slate is 4 days out.~~
  **WRONG, AND THIS LINE CERTIFIED THE BUG AS CORRECT BEHAVIOUR `[2026-08-27,
  `#588`]`.** 3 never reached the openers from ANY anchor in the preceding week
  — the window ended 08-28 and the quote shards start 08-29, ONE DAY short — so
  `quote_rows` was empty, `layer2_shortlist` hit `if not quote_rows: continue`,
  and the sport was skipped BEFORE its enrichment loop on every build. Now
  **`_SLATE_WINDOW_DAYS["ncaaf"] = 7`**, matching nfl and soccer.
- `SWEEP_OWNERSHIP_EXCLUDED` prints only `if dropped:` — **its silence is not evidence
  of success.**

## [ncaaf-sweep-env-gate] RESOLVED — `SYNDICATE_ACTIVE_SPORTS` now carries `ncaaf,nfl`; the capture runs `[measured 2026-08-25T23:07:25Z, lane ncaaf-oddsapi-game-lines]`

PR #61 is DEPLOYED and live on all three services (`.syndicate/deploys.md`,
2026-08-25T20:31Z). It still captures nothing, and this is why:

```
[live_refresh_loop] SWEEP_OWNERSHIP_EXCLUDED date=2026-08-25
  kept=mlb,wnba,soccer
  dropped=nfl:not_in_SYNDICATE_ACTIVE_SPORTS ncaaf:not_in_SYNDICATE_ACTIVE_SPORTS
```

**Two gates, and reading the wrong one gives the wrong answer with total
confidence.** `ops_refresh._active_sports_for_date` (line 1150) is a CALENDAR
window and has NCAAF active since **Aug 15** — I read it first and would have
concluded the sweep covers NCAAF today. It does not. The live services carry
`SYNDICATE_ACTIVE_SPORTS=mlb,wnba,soccer`, which is checked FIRST, so
`ncaaf_game_lines_oddsapi` is unreachable in production no matter what SHA is
deployed. NFL is excluded the same way, four days from its own season.

`SYNDICATE_ACTIVE_SPORTS` is **not in `render.yaml`** — grep returns nothing —
so it is set per-service in the Render dashboard/API. That means changing it
does NOT need a `render.yaml` push and does NOT fire `blueprint_sync`; it is
`update_environment_variables` on each worker. Cheaper and far narrower than
`#284`'s blast radius, but still a production change: adding `ncaaf` starts
spending OddsAPI credits on a sport that has never been fetched.

**NOT DONE — needs a user decision.** Detail and the exact change: `todo.md`
`#558`.

## [ncaaf-oddsapi-lines] NCAAF GAME LINES — LIVE IN PRODUCTION, 432 rows captured on the 08-29 slate `[measured 2026-08-25T23:07:25Z, lane ncaaf-oddsapi-game-lines]`

**Read `[ncaaf-readiness-2026]` first — this closes its stated blocker in CODE
and changes nothing that is running.** Detail: `todo.md` `#552`, `#553`.

**NO LIVE FETCH HAS HAPPENED.** This session had no egress to
`api.the-odds-api.com` (agent proxy answers 403 to CONNECT) and no
`ODDS_API_KEY`. Every number below comes from a REPLAYED FIXTURE built over the
real 8-game 08-29/08-30 slate. The fetch itself is unproven and must be proven
on the worker.

    markets non-null           0 of 51  ->  51 of 51   (8 with a real book line)
    Layer 1 market-board rows  0        ->  32         (ML/ML/spread/total x 8)
    team-name join             94 of 94 on the real week-1 slate, both directions
    tests                      354 ncaaf + 411 shared-contract green; CI archive 383 OK

**THE DESIGN DECISION WORTH KEEPING.** Lines go into the SHARED QUOTE LOG, not a
new file. `HOT_ARTIFACT_PATTERNS`' globs are sport-agnostic and already match
`ncaaf_source/tracking/book_quotes/*.jsonl`, and `run_refresh_worker.py`'s
book-grid pass already loops over `ncaaf` — so one capture feeds BOTH the cards
board and Layer 1, crosses worker→web with **no allowlist edit**, and avoids the
`artifact_publisher.py` collision with `basketball-live-momentum`. A bespoke
`ncaaf_*_lines.json` would have needed a new allowlist entry and given the board
a second line source free to disagree with Layer 1's.

**TWO SILENT BUGS THE REACHABILITY TEST CAUGHT** — neither would have failed a
correctness test that only checked "the number is right when present":
1. The quote log normalises `selection` to `home`/`away`. Matching it against the
   TEAM NAME dropped every spread and moneyline while TOTALS — whose outcome name
   really is "Over" — kept working. That reads as thin book coverage, not a bug.
2. With a correct index, `markets` STILL stayed null on all 51: the card never
   emitted the `betting` block `publication_adapter._shared_markets` reads. The
   line existed and the board could not see it.

**AND ONE CAUGHT BY READING THE OUTPUT, NOT BY A TEST:** `p_home_cover` came out
**0.97** for a game the model has the home side LOSING to the spread by 4.6
points — the cover line was passed negated. Plausible-looking and exactly
inverted, the same shape as the nflverse `spread_line` trap already in this file.
Now pinned by a test asserting DIRECTION (`< 0.5` when the model trails the line)
rather than a value.

**TEAM NAMES ARE THE STANDING RISK.** OddsAPI sends "<School> <Mascot>"; the
board joins on CFBD's canonical name; ~680 schools share mascots. The resolver is
exact (school+mascot from the team registry, plus a validated supplement),
REFUSES ambiguity rather than guessing, and never keys on a bare mascot.
`fold()` transliterates diacritics before stripping punctuation — without that,
CFBD "San José State" and OddsAPI "San Jose State" never meet, because the
board's own `_normalize_text` DELETES non-ASCII instead of folding it.
**OddsAPI's exact spellings remain unverified**; `--report` prints every
unresolved name and `_ODDSAPI_NAME_SUPPLEMENT` is where they go.

**WIRED INTO THE SWEEP 2026-08-25** — `ncaaf_game_lines_oddsapi`, first of the
two NCAAF steps in `_build_ncaaf_steps`, phases `(pregame, live)`. A CROSS-LANE
take of `scripts/refresh_odds_sources.py` (held by OPEN lane
`layer2-sim-view-and-live-projection`) made under explicit user instruction,
scoped to one appended `RefreshStep` and nothing else, recorded in `lanes.md`.

**VERIFIED BY RUNNING THE SWEEP, not by reading the builder**: against a local
fake OddsAPI, `refresh_odds_sources.py --date 2026-08-29 --phase pregame
--sports ncaaf` wrote **192 quote rows** across the two kickoff shards and the
board then read `priced=8 of 51`, `layer1_rows=32`. `return_code=0` was
deliberately not taken as the acceptance reading — the step exits 0 whether or
not it captured anything.

**NO --season/--week, on purpose.** The capture shards each event by its OWN
commence date, because NCAAF weeks are not calendar windows (2026 week 1 spans
08-29→09-07) and the board reads quotes per kickoff date. Pinned by a test.

**NOT separately season-gated, also on purpose.**
`live_refresh_loop._weekly_sport_claimed_by_fast_tick` already decides whether
NCAAF is on the sweep at all, and `#520` records that re-applying an upstream
gate at the launch site is how NFL lost 24 hours of capture. Out of season the
call costs one credit and appends nothing.

**TWO STALE `test_ops.py` ASSERTIONS FIXED, one of them NOT MINE.** Both pinned a
sport at exactly one refresh step and read it as `refresh_steps[0]`.
`test_build_refresh_plan_uses_nfl_syndicate_runner_in_source_mode` had been **RED
ON `origin/main`** (verified in a clean worktree) since `nfl_schedule_refresh`
was added — that step is deliberate and load-bearing (`schedule_{season}.csv` is
a MODEL INPUT, +1.18 ROI points paired on 16,906 held-out 2025 bets) so the TEST
was stale, not the code. Both now assert the step NAMES IN ORDER and look each
command up BY NAME, which is strictly stronger than the count they replaced and
cannot be repointed by a third step appearing. `test_ops.py` is now **124 passed,
0 failed** (baseline 1 failed / 123 passed).

**A PRE-EXISTING NFL RED BAND EXISTS AND IS NOT MINE** `[surfaced 2026-08-25]`.
Widening a `-k` filter to include `nfl` revealed **6 failures that reproduce
identically on `origin/main`**: `test_generate_smartsim2_nfl_projections` (2),
`test_generate_smartsim2_nfl_preseason_projections` (1),
`test_nfl_injuries_fetch_autorun::DispatchOrder` (2),
`test_nfl_roster_depth_autorun::DispatchOrder` (1). Untouched by this lane and
left alone; recorded so the next session does not mistake them for new breakage.

**STILL OWED: a LIVE run.** Nothing here has touched real OddsAPI.

## [ncaaf-margin-calibration] NCAAF MARGINS ARE CALIBRATED; TOTALS ARE NOT `[verified 2026-08-19]`

**Margins fixed and measured** on the 2026 wk1 slate (51 games, 300 seeds):

| metric | before | after | market | ratio |
|---|---|---|---|---|
| margin SD | 1.74 | **15.37** | 14.46 | **1.06** |
| margin max | 7.80 | **50.64** | 49.50 | |
| total SD | 2.56 | 5.77 | 3.46 | **1.67** |

**The cause was the RATING SOURCE, not the engine.** CFBD PPA `overall` is a
per-play rate (SD 0.089); its differential rendered as margin SD ~2.3 through the
engine's ~17-pts-per-unit transfer. **SP+ replaces it** — points-per-game, and it
beat PPA on realised margins in two independent prior-season->next-season pairs
(r 0.506 vs 0.372; residual SD 17.63 vs 18.97, ~740 games each). `SP_RATING_SCALE
= 10.0`, calibrated on the real slate.

**TOTALS: the carrier is SCORING RATE, identified by decomposition.**
`total = drives x score% x pts/score` is exhaustive; across the slate's extremes
score% runs **20.8% -> 53.9% (2.6x)** while drives move only 24.4 -> 19.8 and
points-per-score is near flat. Real CFB converts ~35-45%. **TD share also runs
60.7% -> 83.8% against a real ~55-60%** — field goals are under-used at the top
end, which will distort FG props and alternate totals.

**THREE SCALAR FIXES FOR TOTALS ARE DEAD — do not retry:** the index clamp
(made margins AND totals worse, reverted), the yardage weight asymmetry (parity
was worse), and the `scoring_environment` weight asymmetry (a 3x reduction moved
total SD 0.07 pts, reverted). **They all damp INPUTS to a loop whose outputs
compound** across four-down sequences. The fix is in how `drive_simulator`
converts drives, and it is shared with NFL.

## [ncaaf-ratings-leak] NCAAF RATINGS WERE LEAKED FOR BACKTESTS — FIXED `[verified 2026-08-19]`

`/ppa/teams?year=S` is season-aggregate and contains the game being predicted:
**r 0.663 vs 0.509 as-of** over 558 games of 2024, a 30% inflation of apparent
skill. Fixed to aggregate `/ppa/games` over weeks < N.

**Two traps recorded because each produced a wrong result during the fix:**
`/ppa/teams` **accepts `week=N` and silently ignores it** (identical rows and
values), so the obvious fix is a no-op; and `/ppa/games` without
`seasonType=regular` returns the **College Football Playoff** under "week 1",
importing January games into a week-8 rating — strictly worse than the leak it
replaced. The tell was an impossible count (10 prior games through week 7), not
a failing test.

**The 2026 opener is unaffected either way** — no in-season history means the
2025 prior-season fallback, verified.

## [ncaaf-2026-data] NCAAF 2026 DATA IS BUILT AND SLATE-COMPLETE `[verified 2026-08-19]`

Coverage checked against the **94 FBS teams the wk1 slate needs**, not against
last year's totals: roster 15,442 rows / 138 teams / **0 missing**; coach
continuity 138 / **0**; returning production 136 / 2 (North Dakota State and
Sacramento State are FCS->FBS transitions with no prior FBS production —
legitimate); transfers 3,288 touching 137 teams / **0**.

**Five of seven builders could not run at all** — only `roster` and
`player_game_stats` loaded `.env`; the rest died on "Missing CFBD API key" from a
normal shell. Fixed at the shared choke point (`CfbdClient.from_env`). That is
likely why several snapshots had never been produced.

**None of it reaches the sim.** The generator is team-rating only. See
`docs/ai_context/ncaaf_data_pipeline.md` for the builders, their dependency
order, and the team_id-vs-name traps.

## [nfl-fantasy-engine] NFL FANTASY FOOTBALL ENGINE — **PASSES ITS FALSIFICATION TEST ON ALL FOUR CRITERIA, AND IS LIVE ON PRODUCTION `[web 003a5866, refresh-worker 6855fe96, read 2026-08-21T23:2xZ]`** — `/nfl/api/fantasy/draft-board` returns `available: true`, `mode: artifact`, and a real ordered board (Bijan Robinson RB1 VOR 167.9); the Fantasy pill is on the shared NFL nav — `render.yaml` was not touched, so no `blueprint_sync`; with `autoDeploy = no` this push ships nothing until someone deploys it. Depth chart current to 2026-08-21. `[measured 2026-08-21, lane nfl-fantasy-projections]`

ESPN-scoring season + weekly projections for QB/RB/WR/TE/K/DST at
`/nfl/fantasy`, with `/nfl/api/fantasy/{projections,draft-board}`. On `main` as
`45632889..c1c811c3`. **Every number below is from a local checkout, not from
production.** Pre-merge gate: the rebased branch, run in a tree WITH `data/`
present, produced exactly the four failures clean `main` already had -- zero
new. (Run in the sparse session worktree it showed four EXTRA failures, all
from `nfl_team_branding.csv` being absent under an excluded `data/`, not from
the code. A test failure in a sparse worktree is a fact about the worktree.) Reference:
`docs/ai_context/nfl_fantasy_engine_reference.md`.

**NEWS LAYER — two halves, and only one of them moves a number.**
The INJURY half is fitted and gated on: game designation → availability, graded
on 2,226 held-out player-weeks, MAE 6.894 → 4.399 (**+36.2%**). Measured
negative: adding the practice report made it WORSE (+25.8% / +30.9% vs +36.2%),
because the practice week is already priced into the designation.
The TEXT half (coach quotes, camp/role/workload talk) is CAPTURED and DISPLAYED
but **NOT SCORED** — `use_news_adjustments=False`. `scripts/capture_nfl_news.py`
builds an append-only dated archive (worker autorun, `interval_s=3600`,
CONFIRMED from the worker's own skip line) precisely because the text
was never ungradeable — it had merely never been STORED. Links use ESPN's own
athlete tags: measured 92 of 95 player-links via `espn_tag`, 3 via name match.
**The Buzz column is a DIALOG, not a tooltip** (`003a5866`): click the badge for the headline, the full description, when it ran and whether ESPN tagged it. Quiet rows are inert dashes, not empty buttons; article text is emitted ONCE per page as JSON keyed by player, because both tables render.
**NO CUSTOM HEADERS on any ESPN call** — see `learnings.md` 2026-08-21; a custom
UA 403s from Render AND from a dev machine, and `live_game_state.py:50` is where
that rule lives.
**MEASURED TWICE, AND THE ARCHIVE ACCUMULATES.** 22:28:32Z `fetched=50 new=50 total_today=50`; 23:29:29Z `fetched=50 new=2 total_today=52 linked=36` — 48 of 50 recognised as repeats by article id and the file GREW, which is the append-only merge doing the one job it exists for. Detail: `status=ok fetched=50 linked=35`, published, and `/nfl/fantasy` went from 0 live Buzz badges to 101 (58 players with coverage). Whole chain proven: worker fetch -> archive -> publish -> web disk -> request path -> rendered row.

**MEASURED, held out.** 2025 projected from 2022-2024 only, graded on ONE common
266-player set for every method:

| | baseline "last year" | engine | |
|---|---|---|---|
| season MAE | 49.41 | **47.67** | engine better |
| season spearman | 0.7058 | **0.7392** | engine better |
| per-game MAE | 3.68 | **3.56** | engine better |
| per-game spearman | 0.6138 | **0.6337** | engine better |

Rank correlation better at EVERY position. **The test ran four times: it passed,
then FAILED after a legitimate re-calibration, and the fail was reported rather
than tuned away.** Fixing the defect that fail exposed produced this result.

**THE AVAILABILITY COMPRESSION WAS THE DEFECT.** `_expected_games` scaled a role
curve by a health RATIO shrunk to the position mean and clamped to [0.5, 1.35]:
dispersion ratio 0.65 against the real spread, costing every genuine starter ~2
games (fit-season bias `0-4: +6.81 | 5-9: +3.34 | 10-14: +0.58 | 15-17: -2.00`).
Replaced with a DIRECT blend of a player's own games record and his projected
role's average. Dispersion **0.65 → 0.79** (2024), **0.71 → 0.81** (2025); bias
+12.03 → +6.91.

**THE TENSION THAT ALMOST HID IT: the blend is a WORSE predictor of GAMES (fit
MAE 3.55 → 3.65) and a BETTER predictor of SEASON POINTS (48.08 → 47.55).**
Compressing games toward the mean is exactly what minimises games error --
correct regression to the mean -- but season points are a PRODUCT of games and
rate, and a compressed factor biases the product. **A games-MAE sweep alone
would have REJECTED this fix.** Do not optimise the sub-quantity.

**TWO DEAD HYPOTHESES, measured, do not re-run:** the games curve IS
survivor-conditioned but fixing it is a NO-OP (teams already field 11 players
with carries and 15 with targets against a curve depth of 8, so zeros never
reach the modelled ordinals); and in-season callups take only **0.1-1.8%** of
team opportunity across 2023-25.

**RESIDUAL BIAS IS NOT A CONSTANT OFFSET** — it flips SIGN between seasons
(2024 -12.3 at >=8 games, 2025 +2.6). No level term removes it.

**CALIBRATION.** Constants selected on 2024 ONLY; 2025 never used to select
anything. Re-swept THREE times, most recently after the availability rebuild,
and **the third pass changed NOTHING** — every material constant was already at
the selected value, so the held-out result reproduces byte for byte. That is
stability across a structural change, which is stronger evidence than the
original selection. Confirmed with grid shape: `role_curve_strength` 0.0
(monotone, span 6.52 MAE, natural bound — pulling teams toward the league-average
split was the single largest accuracy loss in the engine);
`availability_history_half_games` 2.0 (clean interior peak, span 1.90);
`share_history_half_games` 18.0 (monotone to 18, turns at 26);
`rz_weight_receiving` 1.0. Seven others span 0.05-0.18 MAE and ship UNFITTED.

**A GRID'S WIDTH IS NOT ITS EFFECT SIZE.** The mechanical adoption rule flagged
`season_recency_weights` as material on a 1.43 MAE span; ~1.35 of that is the gap
between ONE prior season and more than one, which the default already clears.
Every multi-season option is within 0.08 MAE of every other and the "winner" beat
the incumbent by 0.0003 on a non-monotone ridge. REJECTED. The same rule
mislabelled `role_curve_strength` an edge selection when 0.0 is a natural bound.
Read the grid, not its width.

**A TEAM CODE THAT DOES NOT JOIN IS A SILENT WHOLE-TEAM DEFECT.** Refetching
`roster_2026.csv` changed Arizona from `ARI` to `AZ` while the schedule and pbp
kept `ARI`. Nothing raised: every Arizona player stopped joining to a team volume
or schedule, fell through to the no-market fallback, and STILL PRODUCED A
PLAUSIBLE NUMBER — Trey McBride held TE1 and his projection went UP. Fixed with
`fantasy_players.canonical_team()`; a test now asserts every roster team joins to
BOTH the schedule and usage. **Re-verify after any roster or schedule refetch.**

**THE ROLE PRIOR IS FITTED CONTEMPORANEOUSLY AND SPLIT BY EXPERIENCE.** Pairing
the CURRENT chart with the PREVIOUS season's usage priced "rank-2 QB" off a
population of displaced starters: Stetson Bennett, who has never taken an NFL
snap, drew a 0.374 pass share and pulled Stafford to 0.815. Now fitted
season-S-chart against season-S-usage over 2022-2025 (strictly before target),
keyed `(position, rank, rookie|no_prior_role|prior_role)`.

**HISTORICAL ROSTERS AND DEPTH CHARTS ARE NOW LOCAL** (`roster_{2022..2024}`,
`depth_charts_{2022..2025}`, via `scripts/fetch_nfl_rosters_depth_charts.py`).
Their absence was invisible — it surfaced as a calibration run scoring `inf` on
every parameter because `load_fantasy_players(2024)` returned an empty roster.
**nflverse publishes TWO depth-chart schemas** (dated snapshots for 2026,
week-indexed `club_code`/`depth_team` for 2022-2025); reading only the first
leaves every past season silently chart-less.

**GATE:** `scripts/nfl_fantasy_input_checklist.py --season 2026` exits 0 — 49
consumed fields populated, 15 documented sparse, 3 populated-but-unread surfaced
as dead weight. Emits UNMEASURED, never 0%, from a local checkout.

**NEWS/INJURY LAYER SHIPS OFF AND UNFITTED** — a MECHANISM added to an engine
calibrated without it (`model_engine_standard.md` s4.4), and no archived
historical news exists locally to grade its keyword weights. `?news=1` per
request; reachability-tested. **A share promotion and an availability cut of
reciprocal size leave the season total EXACTLY unchanged** (the pool normalises
on `share x games`) — correct, and it reads as "inert"; test the two separately.

**OWED BEFORE ANY DEPLOY** (nothing has been): build usage/news/input-report
artifacts ON THE WORKER; set `SYNDICATE_NFL_FANTASY_USAGE_STRICT=1` on web so a
request-path pbp parse fails loudly. A new usage FIELD needs
`build_nfl_fantasy_usage.py --force`, not just a deploy.

**BUZZ DUPLICATE-ACROSS-DAYS FIXED AND LIVE `[web 60ca2486, verified by Render
deploy record 2026-08-23T23:53:42Z]`.** The `[measured 22:28.../23:29...]`
line above proves the CAPTURE-time merge (`capture_nfl_news.py`, one day's
file) deduped correctly by article id. It does NOT cover the separate READ-time
aggregation `recent_news_by_player()` does across its 21-day window — that had
NO dedup at all, so a story surviving several days on ESPN's feed was counted
and DISPLAYED once per day it was captured, not once per distinct story,
crowding out real coverage under the `[:6]` cap. Fixed: dedupe by article id
(headline fallback) across the whole window, not just within one day's file.
Also fixed `date.today()` → `datetime.now(timezone.utc).date()` in the same
walk-back (`#518` timezone guard) and stale "Hover the badge" copy → "Click"
(the badge has been a click-to-open dialog since `003a5866`, not a tooltip;
the popup already rendered `description`, contrary to how the leftover copy
read). PR #24 (fix) + PR #26/#27 (ledger). Full detail and the deploy's actual
composition (73 commits rode along, unrelated to this fix) in
`.syndicate/deploys.md`, 2026-08-23 23:42-23:53Z entry + correction.

## [nfl-player-props-model] NFL PLAYER-PROP MODEL: `#471` FULLY CLOSED, ALL 6 TUNED CONSTANTS STABILITY-VERIFIED, ALLOWLIST GAP FIXED+LIVE — WEB DEPLOY OF THE FIX SET IN FLIGHT, NOT YET CONFIRMED `[verified 2026-08-19]`

`syndicate/features/nfl/player_stats.player_rate` (rolling season-to-date
rate) + `props._nfl_prop_model_probability` (Normal-CDF cover probability) —
the live NFL player-prop model — had never been backtested before this.
`scripts/backtest_nfl_props.py` (new) measured it over 152,919 real
(player, week, stat) rows, 2022-2025, complete local nflverse pbp (no
"Render is truth" caveat — historical/static data). **8 of 9 markets beat a
constant baseline both in-sample and out-of-sample** (fit 2022-2023, scored
2024-2025); `interceptions` genuinely shows no skill (corr 0.045). Full
table: `docs/ai_context/todo.md` `#471`, `.syndicate/deploys.md` 2026-08-19.

**Defect 2 FIXED, TUNED, MEASURED out-of-sample `[2026-08-19, lane
nfl-player-props-calibration-fix, 30caf008]`**: `anytime_td` at a rolling
rate of exactly 0.0 used to predict 0% (real hit rate ~13-14%, a
small-sample MLE problem). `player_stats.anytime_td_rate` now applies a
Gamma-Poisson shrinkage toward a no-lookahead league-wide prior, `k=12`
selected on 2022-2023 and only ever reported on 2024-2025 (never
re-selected there). OOS Brier 0.1973 → 0.1680 (8,464 held-out rows); the
raw_mean==0.0 bucket moved 0.0% → 18.0% predicted against a real 14.1% —
closes most of the gap, a ~4pp residual stays, stated not hidden. Real
trade-off: `anytime_td`'s point MAE got WORSE (0.358→0.386), correct for
a probability market (Brier is the graded metric) but a real cost.

**Defect 1 FIXED, TUNED, MEASURED out-of-sample `[2026-08-19, lane
nfl-player-props-skew-fix, 5def74df]`**: every count/yardage market's
Normal-CDF cover probability was overconfident near its own mean (~50%
predicted, ~37-44% actual) — real box-score stats are right-skewed,
`Normal(mean, stdev)` can't represent that. **First attempt (pure
log-normal, method-of-moments) was a NULL RESULT** — improved 4 of 8
markets, WORSENED the other 4 by overcorrecting; recorded (`reports/nfl_
cover_probability_model_comparison.json`), not shipped. **Real fix: a
per-market Normal/log-normal BLEND weight, closed-form Brier-minimizing**
(Brier is convex in a linear blend of two fixed probabilities — no grid
search), selected on 2022-2023, reported on 2024-2025:
`passing_attempts` w=1.0 (Brier 0.2062→0.1998), `rushing_yards` w=0.573
(0.2157→0.2111), smaller real gains on 3 more markets; `passing_tds`/
`interceptions` showed no real OOS benefit and ship UNCHANGED (w=0) —
not forced through. Full-scale re-run confirms the same shape
(`passing_attempts` Brier 0.1919→0.1836). Section 1 point-accuracy MAE
confirmed byte-identical before/after — no regression to any beats-
baseline verdict. Deliberately stdlib-only, no `scipy` (a declared-but-
never-imported dependency).

**`#471` is now FULLY CLOSED** — both calibration defects it found are
fixed and measured out-of-sample.

**Production artifact-allowlist gap — FIXED, DEPLOYED, VERIFIED LIVE
`[2026-08-19]`**. `basketball-model-owner` added `nfl_source/oddsapi_
player_props_*.csv` to `HOT_ARTIFACT_PATTERNS` (deliberately scoped to
`nfl_source/` specifically rather than a broader `*_source/` glob, to
avoid matching an unrelated shallow-depth file in another sport's tree).
Deployed to web (scoped commit, parented on web's live SHA — a straight
`main` deploy would have carried unrelated concurrent work).
`/api/ops/artifacts/export?pattern=nfl_source/oddsapi_player_props_*.csv`
now returns `count: 14` on production (was 0). **Content checked, not
just presence**: production's real coverage EXACTLY MATCHES the local
git mirror — 13 header-only stubs (5 bytes each) plus the single real
populated week, `2025_wk22.csv` (10,208 bytes, matching the local copy).
**Resolves the earlier "believed but unverified" uncertainty**: the
mirror was NOT lossy for this artifact; production genuinely has no
richer real-odds coverage. No `#471` Section 3 re-run is owed — there is
nothing new to re-run against.

**All 6 tuned `#471` constants individually stability-checked against
genuinely independent data `[2026-08-19]`**, one lane per constant,
fit-half (2022-2023) vs an INDEPENDENTLY computed estimate on the
2024-2025 half (never used to select, only to compare — closed form for
the 5 blend weights, grid search for `anytime_td`'s shrinkage k since the
`(n+k)` denominator makes Brier rational not quadratic there):

| constant | half A | half B | ratio | verdict |
|---|---|---|---|---|
| `rushing_yards` w | 0.5731 | 0.5717 | 1.00x | STABLE |
| `anytime_td` shrinkage k | 12.0 | 12.0 | 1.00x (exact) | STABLE |
| `receptions` w | 0.1367 | 0.0771 | 1.77x | STABLE |
| `receiving_yards` w | 0.2158 | 0.1242 | 1.74x | STABLE |
| `passing_attempts` w | 1.1409 | 0.8842 | opp. sides of 1.0 | UNSTABLE — left capped |
| `passing_tds` w | 0.3155 | 0.0217 | 14.55x | UNSTABLE — left at w=0 |
| `interceptions` w | 0.1329 | 0.0287 | 4.62x | UNSTABLE — left at w=0 |

No code change resulted from any of the 6 checks — every constant was
either confirmed well-supported or was already at its correct
conservative/safe value. Reports: `reports/nfl_*_stability_check.json`
(one per constant/group).

**WEB DEPLOY OF THE FULL FIX SET IS IN FLIGHT, NOT YET CONFIRMED LIVE**
`[fired 2026-08-19T21:59:15Z]`. Scoped commit `f149f5e2`
(`syndicate/features/nfl/{props.py,player_stats.py}` only, parented on
web's live SHA `450e0d6e`), deploy `dep-da32ecou01pc73fojijg`. Last read:
`build_in_progress`. **Do not cite this fix as live in production until a
later state.md edit confirms `status=live` by content** — the code has
been on `origin/main` since earlier today, but `origin/main` is not
production.

**NFL has no distribution/PMF at all** for player props — confirmed
independently by `convergence-phase7-crps`'s 165-file/160-date check. This
backtest measures the ceiling of a mean+stdev approximation, not a real
simulated ladder like MLB's pitcher props.

## [nfl-data-ingestion-autoruns] NFL ROSTER/DEPTH-CHART/INJURIES INGESTION — ALL 3 AUTORUNS ARMED, DEPLOYED, CONFIRMED FIRING — ONE PUBLISH SUCCESS STILL PENDING `[2026-08-21]`

`roster_snapshot_builder.py` and `depth_chart_snapshot_builder.py` are real
(both already consumed by `ask_the_syndicate_data.py`'s team-profile
evidence) but had NO automated production trigger before this session
(CLI-only) and both wrote via the probing-based `default_nfl_source_root()`
instead of `nfl_artifact_output_root()` -- the same `#389`-class write-side
bug already measured for SmartSim2 projections. Fixed (both switched to the
non-probing resolver; `injury_adjustment.py`'s depth-chart READ path also
had the sibling `#441`-class bug, fixed via a shared resolver mirroring
`nfl_pbp_path`/`nfl_injuries_path`), and wired into refresh-worker as two
new default-OFF autoruns
(`NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN`,
`NFL_DEPTH_CHART_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN`).

**Armed and deployed in production** (refresh-worker, `df04c294` live
2026-08-20T17:32:54Z). Depth-chart: `LAUNCHING` clean on its first real
run, no crash. Roster-snapshot: crashed on its FIRST real run --
`ValueError: Roster snapshot validation failed: row 91 has invalid team
AZ; ...` (~90 rows, every Arizona Cardinals player) -- nflverse's own
team code for Arizona is `AZ`, not `ARI`, and `canonical_team_abbr` (the
shared `team_identity.py`) had no alias entry for it. **Fixed and
CONFIRMED WORKING against real production data**: the autorun's real
retry fired 2026-08-20T19:41:42Z, zero traceback in the full launch
window, `rows_written=2930` (the real 2026 nflverse roster, Arizona
included).

**`NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN` -- ARMED
2026-08-21.** Deliberately deferred initially ("both autoruns" meant
roster/depth-chart specifically), offered as a ridealong to
`football-model-owner`; that session ended without acting (env var
confirmed absent across all 112 vars, no lane update mentioning it).
Armed directly on explicit user instruction: env var set, then a
user-triggered manual Render-dashboard redeploy (`deploy_preflight.py`
correctly refused a same-SHA redeploy as "ALREADY LIVE -- redundant",
no override exists for the env-var-only-refresh case). That manual
redeploy picked up `origin/main`'s tip (`916593f6`, 94 commits/48 files
past refresh-worker's prior SHA) rather than a scoped same-commit
refresh -- flagged immediately, confirmed clean (no traceback, memory
stabilized ~50% of container). `NFL_INJURIES_FETCH_LAUNCHING` fired
2026-08-21T02:10:40Z, result `"status": "unavailable"` (a real HTTP
404 from nflverse -- the fetcher's own documented NORMAL case for a
season with no injury reports published yet, not a crash). Autorun
confirmed correctly wired and firing.

**HOT_ARTIFACT_PATTERNS allowlisting: DONE, DEPLOYED, but a SECOND gap
found behind it (`nfl-artifact-allowlist-add` / `nfl-artifact-publish-
wiring`).** `basketball-model-owner` (the original handoff target)
archived without acting; taken directly since its lane was no longer
OPEN. Added the 3 patterns, deployed to BOTH web (`c5c1b0b5`, live
2026-08-20T20:59:56Z) and refresh-worker (`08bd601f`, live
2026-08-20T21:18:35Z). A real `/api/ops/artifacts/export` call against
production then returned `count: 0` for both checked patterns --
**allowlisting alone was not sufficient.** Traced (not assumed): NOTHING
called `publish_hot_artifact()` for any of the 3 artifacts --
`fetch_nfl_injuries.py` had no publish call site at all;
`roster_snapshot_builder.py`/`depth_chart_snapshot_builder.py`'s own
`publish=` flag only renamed the local file, never pushed cross-service.
Exactly `#208`'s lesson ("allowlisting PERMITS a transfer, it does not
MAKE one happen"), measured as real rather than hypothetical. Fixed --
all 3 scripts now call `publish_hot_artifact()` best-effort after a
successful write, mirroring `generate_smartsim2_nfl_projections.py`'s
existing pattern -- and deployed to refresh-worker (`d1a897b2`, live
2026-08-20T21:57:44Z).

**Roster/depth-chart's real retry (2026-08-21T01:42Z) hit a
TRANSIENT, UNRELATED web-restart DNS blip on the publish call** --
both wrote cleanly (`rows_written=2930` for roster, identical to the
earlier confirmed run) but `artifact_published=False` for both, traced
to `PUBLISH_FAILED ... Name or service not known` coincident with an
unrelated web deploy finishing at 01:43:40Z. Confirmed the transport
recovered fully (105 `PUBLISH_OK` lines for other artifacts within
minutes). **This is the one remaining unverified link**: all 3 autoruns
are armed, deployed, and confirmed firing correctly, but no clean
end-to-end publish success (a real `PUBLISH_OK` for one of the 3 NFL
paths, or a nonzero `/api/ops/artifacts/export` count) has happened
yet. Next roster/depth-chart retry ~21600s from 2026-08-21T01:42Z;
injuries fetch will retry on its own schedule too, and would also
confirm the publish path once nflverse actually has data to return.

## [nfl-player-props] NFL player props: capture fixed, model priced and BEATEN by the market

`[verified 2026-08-21, lane nfl-props-odds-allowlist]`

- **NFL/NCAAF prop capture returned ZERO rows for its entire existence.** Bulk
  `/sports/{key}/odds` does not serve player props (`422 INVALID_MARKET`,
  verified live); they are per-event only. Two market keys were also invalid.
  Fixed; refresh-worker live on `59afbbb6`. 0 -> 80 rows on a live run.
- **PRODUCTION BEHAVIOUR VERIFIED 2026-08-21T14:08:06Z.**
  `oddsapi_player_props_2026_wk1.csv` went **5 bytes -> 12,142 bytes** with a
  FRACTIONAL mtime (runtime write, not a boot copy). Content read, not inferred:
  **84 rows, 84 distinct players, real DraftKings Anytime TD prices**. Ran
  unattended on refresh-worker. First real NFL player-prop capture this platform
  has ever made.
- **NFL runs on `refresh-worker`, and ONLY there. CORRECTED 2026-08-21** —
  an earlier line here said live-odds-worker owned NFL in season. That was
  wrong. It was reasoned from `_weekly_sport_claimed_by_fast_tick` in the CODE
  and never checked against the env. Measured from live env-vars:

      refresh-worker    SYNDICATE_ACTIVE_SPORTS = nfl
      live-odds-worker  SYNDICATE_ACTIVE_SPORTS = mlb,wnba,soccer
      web               SYNDICATE_ACTIVE_SPORTS = mlb,wnba,soccer,nfl

  `SYNDICATE_ACTIVE_SPORTS` gates EARLIER than the ownership predicate, so
  live-odds-worker can never run NFL whatever the horizon says. Confirmed in
  its own logs, every tick:

      [live_refresh_loop] SWEEP_OWNERSHIP_EXCLUDED kept=mlb,wnba,soccer
        dropped=nfl:not_in_SYNDICATE_ACTIVE_SPORTS

  The horizon predicate is real but unreachable for NFL on that service.
- **The prop model does not beat the market**: -7.35% (best price, n=48,024) /
  -7.23% (DraftKings, n=13,368) over 64,007 graded bets, 2023-2025 REG closing
  lines. Fading it loses 16.93%, so the picks are correctly signed.
- **Price shopping is worth +2.95 ROI points**, controlled on 12,986 identical
  bets. Largest single lever measured.
- **Backfilled odds now exist on disk**: 109,750 rows / 513,235 quotes / 579 of
  816 REG games, 2023-2025. `data/nfl_source/` (untracked mirror).

## [nfl-game-context] Game context is built and measured, and INERT in production

`[verified 2026-08-21, lane nfl-props-odds-allowlist]`

- Implied team total + spread, self-normalised against the player's own history,
  fitted per market on 2023-2024. **Paired on 16,906 held-out 2025 bets:
  -7.44% -> -6.26% (+1.18 pts)**, brier and hit rate moving with it.
- **DEPLOYED INERT on web `7c2e92c0`.** It read
  `tracking/nflverse/schedules_games.csv`, which is gitignored and has no writer
  in this repo -- `count: 0` on web with the pattern confirmed deployed.
  Multiplier collapses to 1.0 for every player. Harmless, but doing nothing.
- Fix landed on `8fe78662` (reads `schedule_{season}.csv`, allowlisted, publish
  call added to `fetch_nfl_schedule.py`) and is **NOT DEPLOYED**.

## [cfbd-monthly-quota-exhausted] 2026-08-30 — LIVE: NCAAF projections are FAILING in production, on opener weekend

**MEASURED 2026-08-30T22:03:34Z**, one direct call to
`api.collegefootballdata.com/ppa/teams`:

    HTTP 429   {"message":"Monthly call quota exceeded."}

Not a rate limit. Not transient. The MONTHLY quota is gone and does not clear
until the month rolls (2026-09-01, ~2 days).

**Production is already failing on it.** refresh-worker, 21:07:50-21:08:01Z:
`generate_smartsim2_ncaaf_projections.py` -> `cfbd_backoff.call_with_retry`
exhausted 5 attempts on `GET /ppa/teams` and raised. The backoff (`bf184804`)
works correctly; there is nothing left to back off to.

**This is a SECOND cause of NCAAF's 0% model coverage, and it was previously
attributed entirely to the pick_gate suppression.** Of 373 NCAAF board rows:
~193 carry the gate's own named refusals (139 totals over-dispersion, 54
margin-loses-to-close), but ~180 carry **"no projection object at all"** — no
edge_unavailable_reason, no projection dict. That is the shape of a projection
that was never generated, which is what a quota failure produces.

**Blocked by this until the quota rolls:** any NCAAF backtest, the totals
accuracy measurement `pick_gate` demands, and live NCAAF projections. The
schedule loads from cache (`[games] source=cache`); PPA does not.

**WHAT IS LOCALLY AVAILABLE, and why it is only a PARTIAL unblock** (inventoried
2026-08-30):

    historical_truth/plays_2025_wk00..16.json.gz   17 files, per-week
    historical_truth/drives_2023..2025.json.gz
    historical_truth/games_2023..2026.json.gz      actuals
    data/cfbd_lines_*.json                          market lines
    data/smartsim2_projections_2025_wk*.csv         17, stale+leaked (evidence)

**PPA is fully derivable locally and leak-free BY CONSTRUCTION.** The play rows
carry a per-play `ppa` field: 40,904 of 55,079 non-null across 2025 wk1-4
(**74.3%**), 224 teams on both offense and defense. Aggregating weeks STRICTLY
BEFORE N is exactly `load_ppa_ratings_asof`'s definition, and reading only prior
weeks cannot leak. No CFBD call needed for PPA.

**BUT PPA-ONLY IS THE KNOWN-BAD PATH, so that unblock does not buy a
production-representative backtest.** `generate_smartsim2_ncaaf_projections`
prefers SP+ and falls back to PPA per team, and its own comment records why:
SP+ margin r 0.506 vs PPA 0.372, residual SD 17.63 vs 18.97 over 740 games, and
"PPA is a per-play rate whose differential SD of 0.136 produced **margin SD 1.74
against a market 14.46**".

**THIS RESOLVES THE DISPERSION CONTRADICTION recorded above.** The 752-record log
stamps `rating_source=cfbd_ppa_season_2025` -- the PPA path -- which is why it
measures **0.463x UNDER-dispersed**, while `pick_gate`'s 1.67x OVER was measured
on the SP+ production path. Different RATING SOURCES, not only different
populations or engines. The gate's figure is the production-relevant one; the
log's is not comparable to it and must not be averaged with it.

**SP+ is the missing input.** No `sp_ratings_*.json` on this disk. Its status on
Render is UNKNOWN, not absent: the generator dies on `/ppa/teams` before it ever
reaches SP+ loading, and there are ZERO `[sp_ratings]` log lines on either worker
in 6 days. The web disk export returns 0, but that is the wrong service.

**NET: the production-representative totals backtest stays blocked until the
quota rolls (~2026-09-01).** What local data DOES buy: the market benchmark
(`cfbd_lines_*`) and the actuals (`games_*`) are free, so once ratings exist the
join is cheap.

**PPA IS NOT CACHED and SP+ IS.** `436686a3` cached SP+ as "the one CFBD call
with no local substitute" — the same argument applies to `/ppa/games`, which
`load_ppa_ratings_asof` calls once per prior week (~15 per season). Caching it
would make backtests repeatable and quota-independent after one fetch. It does
not help before the roll: the cache is empty and cannot be filled.

## [ncaaf-live-resim] SMARTSIM2 CAN BE RESUMED FROM MID-GAME; ITS ENTRYPOINT COULD NOT `[measured 2026-09-05, lane ncaaf-live-resim]`

**THE DEFECT, measured on production mid-slate.** `/ncaaf/api/live-lens` served
**51 games, 8 live, 26 final** while every live card's win probability, predicted
final, spread and total was the PREGAME number. Boise State led Oregon **17-7 in
Q2** beside a published **"Oregon 97.7%"**. The board suppressing an edge on
those rows is CORRECT (`#340`); what was missing was a probability that knows
the score.

**THE ENGINE ALWAYS COULD.** `possession_state.build_initial_possession_state`
has always taken `quarter`, `clock_remaining`, `score_home`, `score_away`, and
`drive_simulator` already branches on `state.quarter` / `state.clock_remaining`
for the two-minute drill and end-of-half. `game_simulator.simulate_game`
hard-coded `quarter=1`, `clock_remaining=quarter_seconds`, no score, and looped
`range(1, quarters + 1)`. Four defaulted fields and a loop bound — landed
`ca5be54b`.

**PREGAME OUTPUT IS BIT-IDENTICAL.** 40 shared seeds, the two edited files
stashed and restored in ONE worktree: sha256 `3281e358...` both ways. A first
attempt compared two working trees and reported a DIFFERENCE — it was wrong, and
the reason is worth keeping: the trees loaded different NCAAF calibration
profiles (`source=default` in a `--no-data` worktree vs the promoted
`ncaaf-goal-line-refit-1` artifact in the primary tree). A cross-tree A/B of a
sim engine measures the profile, not the diff.

**WHAT THE RE-SIM SAYS ON REAL LIVE STATE**, ratings held NEUTRAL so the number
is the state's contribution alone (n=120/game):

| game | state | board pregame | live re-sim |
|---|---|---|---|
| Boise State @ Oregon | Q2 2:48, 17-7 away | **97.7%** | **0.2500** |
| Oklahoma State @ Tulsa | Q2 2:43, 0-3 home | 18.3% | 0.6458 |
| Texas State @ Texas | Q2 0:27, 7-28 home | 93.0% | 1.0000 |
| Northern Illinois @ Iowa | Q1 2:35, 0-20 home | 100.0% | 0.9667 |

**COVERAGE, with denominators `[2026-09-05, production cards + ESPN, same
minute]`:** 51 board games; 30 matched to today's ESPN slate (the other 21 kick
off on other dates — the ESPN-id key and an ESPN-`location`-name key matched the
SAME 30, so the producer needs no id map); 8 live on both sides; **7 of 8
(87.5%) carry a resumable state** and would publish a live-aware probability.
The 8th refuses `no_period` (kickoff not taken). Over all 30 matched:
`game_final 9, game_not_in_progress 13, no_period 1`.

**COST FALLS AS THE GAME RUNS** — 154 ms/sim pregame, 85 ms at Q2, 7.9 ms at
Q4 2:00, 0.7 ms at Q4 0:15. The 7 live games above took ~4-7 s each at 120 sims,
~35 s for the slate, inside the 90 s tick budget. **A live re-sim is always
cheaper than the pregame sim it updates.** The 2-sigma edge bar at n=120 came
out 2.26 / 6.98 / 8.62 pp (min/median/max).

**THE INTERLOCK.** Every unpriceable path returns a named `NcaafResimRefusal`
and publishes a lane stamped `pregame` carrying **no `modelHomeWinProb` key at
all** — not the pregame value, not zero, not a null an `or` could rescue.
`LIVE_LENS_SOURCES_BY_SPORT["ncaaf"] = ("live_resim",)` accepts only the priced
stamp, so the join withholds while `sources_seen` still shows the reason. That
is `#414`'s rule enforced by the stamp instead of by convention.

**ONE MARKET FAMILY, DELIBERATELY.** The lane carries `modelHomeWinProb` and
`simsRun` and NO `marginDist` / `totalRunsDist`, because `live_gameline_join`
would price totals and spreads off those the moment they appeared and no NCAAF
live totals estimator has ever been graded (`#499` is the precedent in the other
direction: WNBA totals only priced after a 249-game backtest gave a measured
0.150 interval).

**THE PRODUCER MUST RUN ON refresh-worker, NOT ON THE LIVE-LENS LOOP.** Read
from `render.yaml`: `SYNDICATE_ENABLE_LIVE_LENS_LOOP=true` appears ONLY in the
live-odds-worker block. The re-sim's two inputs are on refresh-worker's disk —
`ncaaf_source/data/smartsim2_projections_*_wk*.csv` (allowlisted, but carrying
`wk1` and no DATE token, so `pull_hot_artifacts`' `*<date>*` glob would never
carry it) and `ncaaf_source/historical_truth/sp_ratings_<season>.json` (**not in
`HOT_ARTIFACT_PATTERNS` at all**). Wiring this into `live_lens_loop` would put
the compute on the one service that cannot read its inputs. The OUTPUT has no
such problem: `data/live/ncaaf_live_lens.json` is keyvalue-backed by
`refresh_state_store`, which is how `mlb_live_lens.json` already reaches web.

**OWED, none of it taken this session (no deploy, no env change, by
instruction):** (1) call `build_live_lens_snapshot` from refresh-worker's tick
and write it through `write_json_file`; (2) add `sp_ratings_*.json` to
`HOT_ARTIFACT_PATTERNS` (`artifact_publisher.py` is held by
`evaluation-ledger-projected-mirror`); (3) a deploy of web + refresh-worker.
The reading that closes it: `/api/ops/live-lens/snapshot-index?sport=ncaaf`
showing `sources_seen {live_resim: N}` with N equal to the live-and-resumable
count, and a live NCAAF row on the board carrying an edge whose
`projection.live_aware` is true.

**FOUND ON THE WAY, AND IT IS NOT NCAAF'S: A LIVE MONEYLINE EDGE IS LABELLED
`edge_basis: "pregame"` `[measured 2026-09-05, affects mlb and wnba equally]`.**
`live_gameline_join._apply_verdict` sets
`edge_basis = "live" if live_projected is not None else "pregame"`; the
DISTRIBUTION branch passes `live_projected`, the MONEYLINE branch does not — yet
`price_moneyline` is called with `model_prob=hit["home_win_prob"]`, the live
number. Measured with the real functions: a live probability of **1.0** against
`market_fair_prob_over` **0.310** produced `edge_vs_market_pct` **69.0**, which
is `(1.0 - 0.310) * 100`; the pregame pairing `(0.977 - 0.310)` gives 66.7 and is
NOT what came out. The row was labelled `pregame`. That label exists precisely
because "a reader cannot recover" the pairing (its own comment, measured 7/7 on
the served shortlist 2026-08-16), so being wrong on the moneyline path defeats
what it was added for. **PINNED, NOT FIXED** — `tests/test_ncaaf_live_gameline_
registration.py` asserts the current value with the reason stated, because
correcting it changes the label on every live moneyline row on three sports'
boards and belongs to a change that can measure that.

**THE JOIN HOP IS PROVEN END TO END** `[commit 7d9ec94e]`, not just the
producer: `build_game_lens -> build_live_gameline_index -> attach_live_gamelines
-> live_edge_policy`, with the OPPOSITE outcome asserted for a refused game (the
index is empty, `live_aware` is never set, the pregame `model_prob_over` is
untouched, the suppression reason stands). Two things the first draft of that
test got wrong are kept as comments: the grid row had no `age_seconds`, so the
staleness gate — which sits ABOVE the market branch, so a newly registered sport
cannot route around it — refused every case before any model reached it, and the
refusal tests "passed" for a reason unrelated to the re-sim.
