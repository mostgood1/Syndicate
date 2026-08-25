# SCOPE — parallelize CI's `pytest-baseline` job

Drafted 2026-08-25 by `exchange-markets-api-integration` (session 71a74bb7), in
response to: "we need to fix all the failures and find a way to shorten the
test." This is the "shorten the test" half, split out on the user's own
instruction ("fix #1 now, scope #2 separately") after the "fix all the
failures" half turned out to mostly not be about parallelization at all --
see §3, which corrects an over-cautious hypothesis from earlier the same
session.

## 0. What this is NOT

Not a claim on any file below. Nothing in this document has been edited.
Everything here is read-only investigation plus a proposed change to exactly
one file (`.github/workflows/ci.yml`) and one dependency
(`requirements-dev.txt`), both currently unclaimed by any OPEN lane (checked
against `.syndicate/lanes.md`, 2026-08-25). The actual test/source fixes this
scope recommends belong to whichever lane owns each file -- see §4's table.

## 1. The measurement

`.github/workflows/ci.yml`'s `pytest-baseline` job runs the full suite
(11,000+ tests) serially, gated on **no NEW failures vs. `tests/pytest_baseline.json`**
(not on full green -- see that file's own docstring for why). Measured twice
today on real CI runs (`main`, pushes at 14:52Z and earlier): **~45-46 minutes
wall clock** (`2026-08-25T14:52:39Z` -> `15:39:02Z`), against a 60-minute
job timeout -- i.e. within ~15 minutes of timing out outright on a slightly
slower day.

Installed `pytest-xdist` (3.8.0) locally and re-ran the identical suite:

    python -m pytest tests/ -q --tb=short -p no:cacheprovider \
      -n auto --dist=loadscope --junitxml=...

**725 seconds (~12 minutes) on 4 cores** -- a **3.7x speedup**, same sandbox,
same checkout. GitHub-hosted `ubuntu-latest` runners currently provision 4
vCPUs, matching this sandbox, so the multiplier should transfer directly
(worth confirming on the first real CI run rather than assumed -- see §5).

## 2. `--dist=loadscope`, not `--dist=load` (the default)

`loadscope` groups tests by **module/class** and assigns whole groups to one
worker, rather than interleaving individual tests from different files
across workers. Two reasons this matters here, not just style:

- Several test files in this suite share **module-level mutable state**
  within a single process (the exact class of bug `#515`'s watermark fix and
  this repo's WNBA `lru_cache`-clearing `conftest.py` fixture already
  document). `loadscope` keeps a file's tests together in one worker process,
  which is the safer default against that class -- `--dist=load` would let
  two DIFFERENT files' tests interleave inside the same worker in
  effectively random order, which is closer to today's serial-suite ordering
  problem than a fix for it.
- It does **not** eliminate cross-PROCESS collisions on a shared real
  resource (a fixed file path, a bound port) -- see §3.4 for the one
  candidate found.

## 3. What actually changed under `-n auto` — CORRECTED

The first pass through this investigation (same session, same day) reported
"~15 of 21 new failures look like parallelization races." **That was wrong,
and is corrected here after actually checking.** Every failure below was
re-run standalone, one test per process, with `-n auto` entirely absent, and
the results contradict the original hypothesis:

### 3.1 — 15 of 21 reproduce standalone, serially, with zero relation to `-n auto`

    OpsRefreshApiTests::test_build_refresh_plan_uses_nfl_syndicate_runner_in_source_mode
    WnbaRefreshRunnerTests::test_main_prefers_existing_refresh_outputs_before_source_job
    WnbaRefreshRunnerTests::test_main_refreshes_live_snapshots_even_when_reusing_existing_outputs
    NbaRefreshRunnerTests::test_main_materializes_core_artifacts_into_bundle_root
    RefreshWorkerTests::test_main_run_once_autolaunches_soccer_weekly_refresh_when_in_season_and_enabled
    IntelligenceStateTests::test_compute_response_recomputes_when_cached_snapshot_is_stale
    test_every_converter_is_registered_or_excused
    OddsControlPlaneTests::test_odds_history_prefers_artifact_history_over_tracking
    StaleArtifactStateTests::test_it_cannot_downgrade_a_started_match
    DispatchOrder::test_injuries_fetch_is_dispatched_directly_behind_pbp_fetch
    DispatchOrder::test_injuries_fetch_sits_high_in_the_chain
    DispatchOrder::test_both_sit_high_in_the_chain
    RealScheduleFallbackTests::test_main_falls_back_when_no_pbp_exists_yet
    WeekScheduleTests::test_includes_post_season_games
    MainTests::test_main_writes_artifact_for_real_schedule_rows

**12 of these 15 are already recorded in `tests/pytest_baseline.json`** (the
2026-08-23 baseline) -- confirmed by direct membership check, not
inference. They are pre-existing, already-tracked debt that CI's own gate
correctly does NOT flag as new, whether the suite runs serially or in
parallel. The 3 NFL projection tests fail on a missing local file
(`data/nfl_source/tracking/nflverse/pbp/pbp_2026.csv` / `pbp_2025.csv`,
gitignored, disk-only in production) -- an environment/data-availability
gap, not code, and also unrelated to `-n auto`.

**Conclusion: `-n auto` did not introduce these. They would appear in ANY
full run of this suite, serial or parallel, on this checkout.** The original
"parallelization race" read was a misattribution -- these tests simply
hadn't been checked standalone yet when that read was written.

### 3.2 — 1 of 21 is genuinely new and untracked, and is ALSO not about `-n auto`

`test_daily_update_smoke.py::test_home_dashboard_payload_exposes_live_lens_link`
-- NOT in `tests/pytest_baseline.json`. Diagnosed (not fixed): `/api/home`'s
"Open Live Lens" link is conditional on `is_active_today` with a real
`live_href`; this sandbox's local `data/` mirror has zero MLB games for
today and the odds APIs 403 through the agent proxy (visible in the test's
own captured log). Same "stale/lossy local mirror" class CLAUDE.md's own
first rule warns about. **Whether this reproduces on a real CI runner
depends on whether that runner's checkout has the same data gap -- unverified,
and out of scope for a parallelization decision either way.**

### 3.3 — 2 of 21 are environment-flaky memory/malloc introspection tests

`test_memory_watchdog.py::test_untracked_census_deduplicates_shared_strings`,
`test_memory_observability.py::test_malloc_arena_snapshot_degrades_quietly_off_glibc`.
Already established earlier the same session: re-running
`test_memory_observability.py` twice standalone failed a **different**
specific test each time (real glibc/malloc/container-memory state, not
mocked). These read live system memory, so of course parallel execution
(different ambient memory pressure than serial) picks a different specific
failure than a serial run would -- but the CLASS of flakiness is not created
by `-n auto`; it already exists in the serial baseline (`test_memory_observability.py`
and `test_memory_watchdog.py` both already carry entries in
`tests/pytest_baseline.json`).

### 3.4 — 1 of 21 is a real, standalone thread-leak, found via a different signal

Not a `FAILED` line at all -- a `PytestUnhandledThreadExceptionWarning` at
session end. A background thread started by
`pipeline/intelligence_state.py::_background_loop` (via some test that never
stops/joins it) keeps running into LATER tests' processes and hits a mock
(`_trim_ordered_dict`, configured by whichever test started it to raise
`RuntimeError("install stretch dies")` as a side effect) that has since been
torn down. This is a real test-isolation defect -- a leaked thread outliving
its own test -- and it is **not xdist-specific**: a leaked thread persists
for the rest of ONE process's lifetime whether that process is running the
whole suite serially or one `loadscope` group under a worker. Named here
because it surfaced during this investigation, owned by whichever lane holds
`pipeline/intelligence_state.py` / `tests/test_intelligence_state.py`, not by
this scope.

### 3.5 — net finding

**No genuine `-n auto`-caused failure was found in this pass.** Every one of
the 21 traces to something that already exists in the serial suite (tracked
debt, an environment gap, or inherent flakiness). This does not prove no such
hazard exists anywhere in 11,000+ tests -- it proves none turned up in THIS
run, on THIS checkout, once actually checked rather than assumed. Recommend
re-confirming on 2-3 real CI runs before trusting this as durable (see §5).

## 4. What actually needs owning, if anything

Given §3's correction, there is **no urgent isolation-fix backlog blocking
`-n auto`** the way the first pass implied. What remains, by owner:

| Item | File(s) | Status |
|---|---|---|
| Leaked background thread | `pipeline/intelligence_state.py`, `tests/test_intelligence_state.py` | Real defect, standalone-reproducible, NOT blocking -- a leaked thread in a torn-down test process does not survive to the NEXT `pytest` invocation (each CI job run is a fresh process). Worth a lane fixing on its own merits, not a `-n auto` prerequisite. |
| 12 pre-existing baseline tests | `test_ops.py`, `test_wnba_refresh_runner.py`, `test_nba_refresh_runner.py`, `test_refresh_worker.py`, `test_intelligence_state.py`, `test_probability_differential.py`, `test_odds_control_plane.py`, `test_soccer_board_mlb_parity.py`, `test_nfl_injuries_fetch_autorun.py`, `test_nfl_roster_depth_autorun.py` | Pre-existing tracked debt, unrelated to this scope. Already visible as a number in `tests/pytest_baseline.json` (23 known failures) -- fixing them is real work but a different, much larger effort spanning many lanes, not a `-n auto` blocker. |
| 3 NFL PBP-data tests | `test_generate_smartsim2_nfl_projections.py`, `test_generate_smartsim2_nfl_preseason_projections.py` | Environment data gap (missing gitignored disk-only file), not fixable by a code change. |
| `test_daily_update_smoke` | `tests/test_daily_update_smoke.py` | Diagnosed, needs either a data-mirror refresh or a test-mocking rewrite; separate decision (§3.2). |
| Memory-flake pair | `test_memory_watchdog.py`, `test_memory_observability.py` | Inherent to reading live system state; not safely patchable without redesigning what they assert against. |

**None of these block adopting `-n auto`.** They are pre-existing regardless
of it.

## 5. The actual `-n auto` adoption checklist

1. **Add `pytest-xdist` to `requirements-dev.txt`**, pinned the same way
   `pytest` already is.
2. **`.github/workflows/ci.yml`, `pytest-baseline` job only** (leave the fast
   `test` job untouched -- it is not the slow one and does not need this):
   add `-n auto --dist=loadscope` to the `Full pytest suite` step's pytest
   invocation. `scripts/pytest_baseline.py`'s `_run_pytest` builds that
   command; it takes `pytest_args` as a passthrough list already, so this is
   additive there too, not a rewrite.
3. **Regenerate `tests/pytest_baseline.json`** via `--update` run **under
   the new parallel invocation**, not the old serial one -- the gate must
   compare like-for-like. (§3's finding that the failing SET is the same
   either way means this should be close to a no-op diff against the current
   baseline file, but "should be" is not "measured": run it for real before
   trusting that.)
4. **Confirm on 2-3 real CI runs**, not just this sandbox: the wall-clock
   speedup, that no NEW failure appears beyond the regenerated baseline, and
   that GitHub's runner actually reports 4 cores (`nproc` in a debug step, or
   read it once from `Print runtime diagnostics`'s existing step).
5. **junit reporting under `loadscope`**: `pytest-xdist` merges worker
   results into one `--junitxml` output transparently -- `_failed_keys()` in
   `pytest_baseline.py` reads that same file and does not need to change.
   Worth one dry run confirming the merged report's test count matches the
   serial collection count (11,000+ -- both this session's runs matched, so
   this is a confirmation step, not an open risk).

## 6. What this scope explicitly does not include

- Fixing any of the pre-existing baseline debt in §4's table -- that is
  real, separate, multi-lane work.
- Extending `-n auto` to the fast `test` job (383 archive-suite tests +
  ledger/hook-guard checks already run in ~3 minutes; parallelizing a
  3-minute job is not worth the added complexity).
- Any change to `tests/pytest_baseline.json`'s CONTENT beyond what step 3
  above regenerates mechanically.
