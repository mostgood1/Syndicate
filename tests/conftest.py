from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _season_pull_already_done():
    """Keep the suite from performing `sweep_changed_hot_artifacts`'s boot pull.

    `_pull_season_artifacts_once_per_process` runs on the FIRST sweep of a
    process and makes one HTTP request per season pattern. Two problems in a
    test suite, and the second is the dangerous one:

      1. Any test that configures a publish URL suddenly issues network calls it
         did not before -- `test_publish_changed_hot_artifacts_only_publishes_
         recent_matching_files` asserts `urlopen` was called ONCE and started
         failing the moment the pull landed, correctly.
      2. The flag has PROCESS lifetime, so whichever test sweeps first pays the
         pull and every later test skips it. That makes the behaviour
         ORDER-DEPENDENT: the same test passes or fails depending on what ran
         before it, which is the failure mode `suite-order-pollution` exists for.

    Defaulting it to "already pulled" removes both. A test that actually wants
    the pull resets the flag itself -- `tests/test_season_pull_before_sweep.py`
    does exactly that, and its own fixture takes precedence.
    """
    from syndicate.features.shared import artifact_publisher

    previous = artifact_publisher._SEASON_ARTIFACTS_PULLED_THIS_PROCESS
    artifact_publisher._SEASON_ARTIFACTS_PULLED_THIS_PROCESS = True
    try:
        yield
    finally:
        artifact_publisher._SEASON_ARTIFACTS_PULLED_THIS_PROCESS = previous


@pytest.fixture(autouse=True)
def _isolate_intelligence_state(tmp_path_factory):
    """Keep the suite out of the repo's REAL intelligence-state files.

    Same failure as `_isolate_prediction_ledger` below, different file. A full
    `pytest tests/` run rewrites `reports/intelligence/intelligence_state.json`
    and appends to `intelligence_state_history.jsonl`, because
    `persist_intelligence_state` writes to module-level paths resolved through
    `reports_root()` at import.

    **Why that is worse here than an untracked scratch file.** Both are TRACKED
    and must stay tracked -- `intelligence_state.json` is the `#43`
    worker->web artifact-transport file, listed in `artifact_publisher`'s hot
    patterns. So they cannot be gitignored the way the `#503` byproducts were,
    and every full run left the tree dirty with locally-computed values sitting
    on top of production-shaped data. `335dca07` is what happens next: a
    `git add -A` swept exactly this class and rewrote all eight sport manifests'
    `artifact_paths` to a local checkout path. The tree being clean after a test
    run is what stops that, so it is worth a fixture rather than a habit.

    Suite-wide and autouse for the same reason as the ledger fixture: many test
    files reach `persist_intelligence_state` indirectly through the query API
    and the background loop, so a fix in any one of them leaves the rest open.

    Tests that care about these paths patch them explicitly, which takes
    precedence over this default.
    """
    from unittest.mock import patch as _patch

    from pipeline import intelligence_state

    state_dir = tmp_path_factory.mktemp("intelligence_state")
    with _patch.object(
        intelligence_state,
        "INTELLIGENCE_STATE_PATH",
        state_dir / "intelligence_state.json",
    ), _patch.object(
        intelligence_state,
        "INTELLIGENCE_HISTORY_PATH",
        state_dir / "intelligence_state_history.jsonl",
    ):
        yield


@pytest.fixture(autouse=True)
def _isolate_reports_root(tmp_path_factory, monkeypatch):
    """Point the WHOLE reports tree at a scratch dir, for every test.

    The two fixtures below this one, and the one above it, each patched a
    single artifact after it was caught dirtying the working tree. That is
    three rounds of the same fix, and the fourth was already queued: one run of
    `tests/test_kalshi_odds_cadence.py` and `tests/test_execute_portfolio.py`
    together left ELEVEN tracked files modified -- seven sport manifests, the
    refresh state, the OddsAPI quota, a live-lens capture and the Kalshi
    markets artifact. Patching each of those in turn would not have ended
    either, because the list depends on test ORDER: the cadence file alone
    dirties two of them, the pair dirties eleven, and pytest-randomly means the
    set changes between runs.

    Everything in that list resolves its path through ONE function --
    `refresh_state_store.reports_root()` -- which already honours
    `SYNDICATE_REPORTS_ROOT`. So the fix belongs at that seam rather than at
    each of its callers, and a new artifact added next month is covered without
    anyone remembering to add a fixture.

    **Why the tree being clean is worth a suite-wide fixture.** These files are
    TRACKED and must stay tracked -- the manifests and `intelligence_state`
    are the worker->web artifact transport (`#43`), and `kalshi_markets.json`
    is `execute_portfolio`'s price fallback. They cannot be gitignored. So the
    alternative to isolating them is a working tree that is dirty after every
    test run, in files that look machine-generated and plausible. `335dca07`
    is what happens next: one `git add -A` swept exactly this class and
    rewrote all eight sport manifests' `artifact_paths` to point at a local
    checkout. Committing locally-computed values on top of production-shaped
    data is not a cosmetic problem.

    A test that genuinely needs the repo's committed reports sets
    `SYNDICATE_REPORTS_ROOT` itself, or patches the path it cares about --
    both take precedence over this default, which is why the many tests that
    already do so are unaffected.
    """
    root = tmp_path_factory.mktemp("reports_root")
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(root))
    yield


@pytest.fixture(autouse=True)
def _isolate_kalshi_markets_artifact(tmp_path_factory):
    """THE THIRD INSTANCE OF THE SAME DEFECT. See the two fixtures around it.

    A full `pytest tests/` run rewrote the tracked
    `reports/intelligence/kalshi_markets.json`, because
    `run_kalshi_odds_refresh` resolves its path through `reports_root()` and
    several tests reach it indirectly through `intelligence_state`'s loop
    rather than calling it themselves. `tests/test_kalshi_odds_cadence.py`
    isolates it correctly and was never the problem, which is exactly why a
    per-file fix would not have worked.

    **What the churn actually was, and why committing it would be worse than
    noise.** This dev container cannot reach Kalshi -- every host 403s at the
    proxy -- so the file came back as a set of `all_hosts_failed` records with
    fresh timestamps. Committing that writes THIS SANDBOX's connectivity into
    an artifact whose whole job is to describe what the VENUE is quoting in
    production. It is not stale data; it is data about the wrong machine, in a
    file nobody would re-read closely because it looks machine-generated and
    correct.

    Tracked, and must stay tracked: `execute_portfolio` reads it as the price
    fallback when a live venue read fails, so it cannot be gitignored the way
    a scratch byproduct could. `335dca07` is what happens when this class of
    dirt meets a `git add -A` -- eight sport manifests rewritten to a local
    checkout path. A clean tree after a test run is the thing that prevents it.

    Tests that care about this path patch it themselves, which takes
    precedence over this default.
    """
    from unittest.mock import patch as _patch

    from pipeline import kalshi_odds_refresh

    markets_dir = tmp_path_factory.mktemp("kalshi_markets")
    with _patch.object(
        kalshi_odds_refresh,
        "markets_artifact_path",
        return_value=markets_dir / "kalshi_markets.json",
    ):
        yield


# PROCESS-WIDE, NOT AN AUTOUSE FIXTURE, and the difference is measured.
#
# `schedule_adapter._fetch_basketball_schedule_via_cli` spawns
# `python -m wnba_betting.cli fetch-schedule` as a CHILD process, which fetches
# the live schedule over the network and rewrites the git-tracked
# `vendor/wnba_betting_repo/data/processed/schedule_2026.{json,csv}`. A child
# process cannot be seen by an in-process interceptor, so the guard below is
# blind to it by construction -- it was found by the file coming back modified
# while the guard reported nothing.
#
# This started as an autouse fixture, which was not enough: session
# `data-mirror-write-guard-sweep` instrumented a full parallel run and recorded
# **143 mtime changes** on that file, of which **25 carried an EMPTY
# `PYTEST_CURRENT_TEST`** -- i.e. the write happened BETWEEN tests, from a thread
# that outlived the test which started it. A fixture's patch is in force only
# DURING a test, so those 25 were unprotected by construction. Entering the
# block once at import and never exiting closes that window; a single-file run
# cannot exercise it, which is why it was invisible here.
#
# Nothing legitimately wants the real CLI under test -- it is a live network
# fetch -- so there is no case for making this releasable.
#
# Reasoning and the block itself in `tests/_artifact_isolation.py`, shared with
# the unittest entrypoints.
_VENDORED_SCHEDULE_FETCH_BLOCK = None


def _install_vendored_schedule_fetch_block() -> None:
    global _VENDORED_SCHEDULE_FETCH_BLOCK
    if _VENDORED_SCHEDULE_FETCH_BLOCK is not None:
        return
    from tests._artifact_isolation import no_vendored_basketball_schedule_fetch

    _VENDORED_SCHEDULE_FETCH_BLOCK = no_vendored_basketball_schedule_fetch()
    _VENDORED_SCHEDULE_FETCH_BLOCK.__enter__()


_install_vendored_schedule_fetch_block()


@pytest.fixture(autouse=True)
def _isolate_wnba_cards_context_publish(tmp_path_factory):
    """THE FOURTH INSTANCE, and the first one under `data/` rather than `reports/`.

    `build_cards_page_context` ends in `publish_cards_page_context`, which writes
    `data/live/wnba_cards_context*.json` under `data_root()`. Two test files
    reach it through code they are actually asserting on --
    `test_archives.py` via its routes and `test_intelligence.py` via
    `build_intelligence_overview` -> `_wnba_has_live_games` -> ... -> the
    publish -- so a per-file fix would have to be repeated for the next caller.

    The write guard below is what found it. The redirect itself lives in
    `tests/_artifact_isolation.py` because CI runs `python -m unittest
    tests.test_archives` and never imports this file; one definition, both
    runners.
    """
    from tests._artifact_isolation import isolated_wnba_cards_context

    with isolated_wnba_cards_context(tmp_path_factory.mktemp("wnba_cards_context")):
        yield


@pytest.fixture(autouse=True)
def _isolate_prediction_ledger(tmp_path_factory):
    # The suite was writing this dev machine's REAL data/prediction_ledger.json.
    # intelligence.py:7706 calls record_prediction() on every query, and
    # prediction_ledger._default_ledger_path() resolves through data_root() to
    # the repo's data/ dir, so any test reaching that path appended to it.
    #
    # Measured 2026-07-26: ~14.5KB per test (29,023 bytes from two tests). The
    # cost is quadratic, not linear -- record_prediction rewrites the ENTIRE
    # file on each call, so as it grows every subsequent write gets more
    # expensive, and the file is never reset between runs. A 171-test file adds
    # ~2.5MB per pass and re-serialises an ever-larger document each time,
    # which is how tests/test_intelligence.py reached ~3 hours. The ledger had
    # already accumulated to 2.5MB this way.
    #
    # This is deliberately suite-wide rather than per-file: 15 test files reach
    # record_prediction or the query API, so a fix inside any one of them would
    # leave the leak open everywhere else.
    #
    # Safe for tests/test_prediction_ledger.py -- it passes explicit
    # ledger_path= arguments and patches _default_ledger_path itself where it
    # needs to, both of which take precedence over this default.
    from unittest.mock import patch as _patch

    from syndicate.features import prediction_ledger

    ledger_dir = tmp_path_factory.mktemp("prediction_ledger")
    with _patch.object(
        prediction_ledger,
        "_default_ledger_path",
        return_value=ledger_dir / "prediction_ledger.json",
    ), _patch.object(
        prediction_ledger,
        "_default_signal_weights_path",
        return_value=ledger_dir / "signal_weights.json",
    ):
        yield


@pytest.fixture(autouse=True)
def _clear_wall_clock_ttl_caches() -> None:
    # build_live_state_payload's and build_source_cards_payload's caches
    # (syndicate/features/wnba/cards.py) are keyed on (selected_date, ...) +
    # wall-clock TTL, not on any content fingerprint -- unlike the
    # file-mtime-keyed lru_cache helpers elsewhere in this codebase, they
    # can't tell "same date, different mocked/patched data" apart on their
    # own. Two tests using the same date literal within the same TTL window
    # would otherwise leak a stale result from one test into the next. Clear
    # before every test so each one starts cold regardless of real elapsed
    # wall-clock time.
    # The reset itself lives in tests/_cache_isolation.py because CI does NOT
    # run pytest -- ci.yml and daily-update.yml both use `python -m unittest`,
    # which never loads this file. Two WNBA tests were failing the Daily Update
    # workflow every morning for exactly that reason. One definition, called
    # from both runners.
    from tests._cache_isolation import clear_wnba_wall_clock_caches

    clear_wnba_wall_clock_caches()
    yield
    clear_wnba_wall_clock_caches()


@pytest.fixture(autouse=True)
def _clear_nba_cards_caches() -> None:
    # NBA's equivalent of the WNBA cache hazard above -- syndicate/features/nba/cards.py
    # has its own _NBA_CARDS_CONTEXT_CACHE (an OrderedDict keyed on a cache
    # tuple, not date-only) plus four lru_cache-decorated functions
    # (_nba_team_branding_index, _local_live_state_payload_cached,
    # _local_live_snapshot_payload_cached, _live_projection_calibration_index).
    # None of these were reset by any autouse fixture -- a documented gap
    # ("test order-pollution... no conftest reset") from an earlier session's
    # end-to-end assessment. Individual test files worked around it by
    # calling cache_clear() themselves, which only protects that one file's
    # own run order, not the full suite. Clearing here follows the exact
    # same pattern this file already uses for WNBA/soccer above.
    from tests._cache_isolation import clear_nba_cards_caches

    clear_nba_cards_caches()
    yield
    clear_nba_cards_caches()


@pytest.fixture(autouse=True)
def _clear_mlb_wall_clock_caches() -> None:
    # home._MLB_FEED_LIVE_STATE_CACHE is keyed on (selected_date, game_pks) plus
    # a 20s wall-clock TTL and no content fingerprint, so two tests sharing a
    # date literal inside one window would share a result -- and the second
    # would never reach the statsapi fan-out it exists to exercise. Same reason
    # the WNBA/NBA fixtures above exist; same shared definition, so the unittest
    # entrypoints get it too via WallClockCacheIsolationMixin.
    from tests._cache_isolation import clear_mlb_wall_clock_caches

    clear_mlb_wall_clock_caches()
    yield
    clear_mlb_wall_clock_caches()


@pytest.fixture(autouse=True)
def _no_background_loops_in_tests():
    # create_app wires _start_background_loops onto the app's first request
    # for non-Render runs, so ANY test that touches a test client spawns the
    # intelligence-state background loop thread. That thread contends the
    # process-wide intelligence execution guard: whichever request loses the
    # race is silently served get_latest_intelligence_cached_response's
    # snapshot instead of a fresh pipeline run, so dozens of
    # test_intelligence assertions pass solo and fail in a full run,
    # depending on where the loop happened to be. The loop also persists
    # state, bleeding one test's snapshots into the next.
    #
    # Tests that assert the loops DO start patch these same seams themselves;
    # a with-patch inside a test rebinds over this fixture's patch for its
    # scope, so those assertions still see their own mocks.
    from unittest.mock import patch as _patch

    import syndicate.app as app_module

    with _patch.object(app_module, "start_intelligence_state_background_loop", return_value=True), _patch.object(
        app_module, "start_live_refresh_background_loop", return_value=None
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_intelligence_state_snapshots():
    # _INTELLIGENCE_STATE_SERVICE is a module singleton whose snapshot cache
    # outlives any single test in the same process. A snapshot computed under
    # one test's patches is a perfectly valid cache hit for the next test's
    # identical payload (same question/date literals), so later tests read
    # the earlier test's fixture data. Start each test cold.
    from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE as _service

    with _service._condition:
        _service._snapshots.clear()
        _service._latest_key = None
    yield


@pytest.fixture(autouse=True)
def _isolate_intelligence_pipeline_busy_signal():
    # _mlb_daily_sim_decision now defers while the intelligence board build is
    # computing (#55), which it detects by reading the live service's
    # execution guard. That guard is real, process-wide, ambient state: any
    # test that calls create_app() starts the intelligence background loop,
    # and if that loop happens to be mid-compute when an unrelated sim-gate
    # test runs, the decision comes back "intelligence_pipeline_busy" instead
    # of the reason under test. The failure is order-dependent -- the sim-gate
    # tests pass in isolation and fail in a full run.
    #
    # Default the signal to "idle" so decision tests are deterministic. Tests
    # that exercise the deference itself patch it to True explicitly, which
    # overrides this.
    from unittest.mock import patch as _patch

    from syndicate.features.shared import live_refresh_loop

    with _patch.object(live_refresh_loop, "_intelligence_pipeline_busy", return_value=False):
        yield


@pytest.fixture(autouse=True)
def _no_live_espn_calls_in_tests():
    # NFL cards/market-board now stamp real game state from ESPN's scoreboard
    # (syndicate/features/nfl/live_game_state.py), so building an NFL board
    # makes a live HTTP call -- measured: exactly 1 fetch, ~1.5s, per
    # build_preseason_cards_page_context.
    #
    # That makes any test touching those builders network-dependent AND
    # non-deterministic against real game state: test_nfl_preseason_cards'
    # market-board test began failing the moment this landed, because it
    # builds 2026 preseason week 1 -- Hall of Fame weekend -- and ESPN
    # correctly reports those games as `final` rather than the `pregame` the
    # board used to hardcode. A true reading of the world, and a flaky test.
    #
    # Blocked at the fetch seam rather than at nfl_game_state_index, so the
    # index's own caching/keying logic still runs under test and only the
    # socket is removed. Returning None is the module's real
    # ESPN-unreachable path, which yields an empty index and leaves every
    # card exactly as it was pre-fix.
    #
    # Tests that want game state patch _fetch_scoreboard or
    # nfl_game_state_index themselves; a monkeypatch inside a test rebinds
    # over this for its scope, same contract as _no_background_loops_in_tests.
    from unittest.mock import patch as _patch

    from syndicate.features.nfl import live_game_state

    live_game_state._cache.clear()
    with _patch.object(live_game_state, "_fetch_scoreboard", return_value=None):
        yield
    live_game_state._cache.clear()


@pytest.fixture(autouse=True)
def _isolate_kalshi_discovered_series():
    """`kalshi_catalogue._DISCOVERED` is a module-global dict that NOTHING resets.

    `register_discovered()` adds to it and it lives for the life of the
    interpreter, so one test teaching the catalogue a real series changes what
    `classify_market` answers for every test after it -- across files, in one
    direction only, and never in a targeted run.

    MEASURED 2026-09-04: `test_kalshi_catalogue`'s two "unseen series" tests
    passed alone and failed in a full-suite run --
    `stat_not_in_market_vocabulary` where they assert `unmapped_series`, and an
    EMPTY work queue where they assert `{"KXNBAPTS"}`. Both say the same thing:
    by then the catalogue had LEARNED `KXNBAPTS`, so the series check passed and
    the stat check refused instead. Reproduced exactly, both failures, with a
    single `register_discovered({"KXNBAPTS": "nba"})`.

    Where it came from is worth recording, because it is the same defect twice:
    the suite REWRITES the tracked `reports/intelligence/kalshi_markets.json`
    (+255,828 lines in the run that found this), and the rewritten file carries
    `KXNBAPTS` twice while the committed one carries it ZERO times. Discovery
    then reads that artifact and registers what it finds. The
    `_isolate_kalshi_markets_artifact` fixture above exists to stop exactly that
    write and does not cover this path -- the artifact leak is NOT fixed here,
    only its effect on the in-process registry.

    Snapshot-and-restore rather than clear-on-entry: a test that registers a
    series on purpose still sees it for its own duration.
    """
    from syndicate.features.shared import kalshi_catalogue

    before = dict(kalshi_catalogue._DISCOVERED)
    try:
        yield
    finally:
        kalshi_catalogue._DISCOVERED.clear()
        kalshi_catalogue._DISCOVERED.update(before)


# ---------------------------------------------------------------------------
# THE TRACKED-DATA-MIRROR WRITE GUARD
# ---------------------------------------------------------------------------
# The fixtures above are five rounds of the same lesson about `reports/`: a test
# wrote a TRACKED artifact, the tree came back dirty, and `335dca07` is what a
# `git add -A` then does with that class of dirt. `data/` is the same defect
# with a bigger blast radius, because `CLAUDE.md` gives that tree a specific job
# -- a cold-start mirror that is explicitly NOT what production computed -- and
# the reason it is documented at that length is that a locally-written file
# there is indistinguishable from a mirrored one.
#
# MEASURED 2026-09-09: `pytest tests/ -k "venue or kalshi or polymarket"`
# created `data/mlb_source/tracking/book_quotes/.jsonl` -- note the EMPTY date
# prefix -- plus its `.state.json` sidecar. `reports/` had five fixtures by
# then and `data/` had none, so nothing said so.
#
# IT FOUND A SECOND ONE IMMEDIATELY, which is the argument for having it rather
# than only fixing the reported case: five `test_archives.py` tests reached
# `wnba/cards.py::publish_cards_page_context` through the routes they exercise
# and published board context into `data/live/`. Nothing under `data/live/` is
# tracked, and that makes it worse rather than better -- untracked and NOT
# ignored is precisely the state a `git add` sweep collects, and a later local
# run reads the file back as if the mirror had produced it. Isolated in that
# module's `setUpModule`; see the comment there for why not a fixture.
#
# WHY AN INTERCEPTOR RATHER THAN AN ENV OVERRIDE. `SYNDICATE_DATA_ROOT` is the
# `reports_root()`-shaped fix and it does NOT work here: 92 tests read
# `REPO_ROOT/data/...` on purpose and several ignore the variable entirely (see
# `scripts/session_worktree.py`'s `--with-test-data` note), so pointing the
# whole suite at a scratch dir would break the tests whose SUBJECT is the
# mirror. Reads must keep working; only WRITES are the defect. So this guard
# names the OPERATION instead of the path, which also covers a writer nobody
# has added yet.
#
# It fails TWICE on purpose. The raise puts the offending writer in the
# traceback, which is the only thing that makes the cause cheap to find. But
# several writers on this path are deliberately never-raise instrumentation
# (`append_book_quotes` catches `Exception`, prints `FAILED` and returns), so a
# raise alone can be swallowed and leave the run green with the file on disk --
# and that is exactly how `book_quotes/.jsonl` got written. The recorded list is
# what the teardown assertion reads, and that cannot be swallowed.
#
# TWO EXEMPTIONS, BOTH MEASURED RATHER THAN GUESSED. A guard that reports
# harmless operations gets switched off, so both of these were found by running
# the guard over the whole suite and reading what it caught:
#
#   * **A `mkdir` that creates nothing.** `mkdir(parents=True, exist_ok=True)`
#     against an existing directory is a no-op, and eleven `test_archives.py`
#     tests do it on `.../source_artifacts/data/live_lens`, a directory with 208
#     TRACKED files already in it. A mkdir that WOULD create is still reported,
#     because it is the earliest visible point of intent and gives the best
#     traceback -- it is how the `book_quotes` writer was found.
#   * **A path `.gitignore` already excludes.** The harm this guard exists to
#     prevent is a file nobody meant to commit -- reached by a `git add` sweep,
#     or read back later as if the mirror had produced it. Neither can happen
#     under an ignore rule, and `.gitignore` is the repo's own statement that a
#     subtree is regenerable local cache: `data/nfl_source/tracking/` is listed
#     there, and nine `test_football_sim_engine.py` tests populate the nflverse
#     release cache under it through the real code path on purpose. A TRACKED
#     file is never exempt, whatever rules match it -- `git check-ignore` says 1
#     for a tracked path -- and an ignore check that fails for any reason counts
#     as NOT ignored, because an unknown must not land on the permissive branch.
#
# NOT COVERED, stated so it is not mistaken for covered: `os.open` and anything
# below it (a C extension writing through its own file handle), and every
# `python -m unittest` entrypoint -- CI runs `tests.test_archives` that way and
# `unittest` never imports a conftest. `tests/_cache_isolation.py` exists for
# that same gap and explains it at length.
#
# The `os.open` gap is REAL and MEASURED: an append to a tracked mirror file
# through `Path.open("a")` is refused, while the same append through
# `os.open(..., O_WRONLY|O_APPEND)` passes and the bytes land (controls run by
# session `data-mirror-write-guard-sweep`). It is not theoretical --
# `scripts/refresh_*_oddsapi.py::_copy_file_with_fallback` already copies through
# `os.open` on EINVAL.
#
# BUT IT DOES NOT EXPLAIN `live_lens_2026_06_02.jsonl`, and that hypothesis is
# recorded as FALSIFIED so nobody re-runs it. It was the obvious candidate for
# the modification this lane saw twice with nothing attributable to it, and a
# one-variable A/B killed it: with the `os.open` wrapper PRESENT and with it
# REMOVED, `test_mlb_refresh_runner.py::test_build_live_lens_snapshot_internal_
# merges_cards_detail_into_vendor_report` is intercepted identically and the file
# stays at 20 lines and 0 dirty either way. The real writer was ordinary and
# in-process: the report/log path asymmetry in `_persist_live_lens_report`, fixed
# in that test. A guard's blind spot being real does not make it the cause of the
# nearest unexplained symptom.
#
# TWO ROOTS, NOT ONE `[widened after the first full-suite sweep]`. `data/` is
# the mirror `CLAUDE.md` names; `vendor/<repo>/data/` is the second, and a test
# run rewrites all 114 rows of the TRACKED
# `vendor/wnba_betting_repo/data/processed/schedule_2026.csv` -- a file
# `wnba_fixture_identity` calls "the git-tracked master", with the
# `data/wnba_source` copies as its mirrors. Watching only `data/` was blind to
# the more authoritative of the two. See `_guarded_mirror_roots`.
#
# THE SHAPE THIS KEEPS CATCHING, named because it has now appeared three times
# in three unrelated scripts and the next one will look the same: **A TEST PINS
# ONE PATH AND THE CODE RESOLVES TWO.** The test passes an explicit destination,
# asserts on the file it named, and passes -- while a SECOND path in the same
# call resolves from `data_root()` and lands in the mirror. The passing
# assertion is what hides it: it proves the file the test named is right and
# says nothing about the file it did not.
#
#   * `refresh_ncaab_odds_history` takes `--out-dir`, which covers the odds CSV
#     the test asserts on; `append_book_quotes` ignores the flag and writes
#     `data/ncaab_source/tracking/book_quotes/<date>.jsonl`.
#   * `_persist_live_lens_report` resolves `live_lens_log_path(date)` separately
#     from `live_lens_report_path(date)`; a test stubbing only the report still
#     appends to the tracked JSONL log.
#   * `emit_settlement_inputs` is `Path(out_dir) if out_dir is not None else
#     (data_root() / "settlement_inputs")`, and `run_refresh_worker` calls it
#     with no `out_dir` at all. (Traced by session
#     `data-mirror-write-guard-sweep`, who named the pattern; closed here as a
#     side effect of the module-scoped data root in `test_refresh_worker.py`,
#     verified with the guard MUTED so "fixed" is distinguishable from
#     "blocked".)
#
# The lesson for a fix, not just for finding it: redirect the ROOT, not the
# symbol or the flag. A flag covers one path by construction, and patching a
# path-returning symbol can miss -- measured on `live_lens_log_path`, where
# `patch.object` was in scope at the failing line and the write still landed.
#
# A test that genuinely means to write there says so with
# `@pytest.mark.writes_tracked_data`. To tell this guard's findings apart from
# failures that were already there, re-run with
# `SYNDICATE_TEST_DATA_MIRROR_GUARD=off`.
_REPO_ROOT_FOR_GUARD = Path(__file__).resolve().parents[1]
_TRACKED_DATA_MIRROR = os.path.normcase(str(_REPO_ROOT_FOR_GUARD / "data"))


def _guarded_mirror_roots() -> tuple[str, ...]:
    """Every tracked artifact mirror in this repo, not just the obvious one.

    `data/` is the mirror `CLAUDE.md` names. `vendor/<repo>/data/` is the second
    one, and it was found the way the rest of this guard was -- by measurement:
    a test run rewrites the TRACKED
    `vendor/wnba_betting_repo/data/processed/schedule_2026.csv`, all 114 rows of
    it, and `wnba_fixture_identity` calls that file "the git-tracked master"
    with the `data/wnba_source` copies as its mirrors. A guard that watched only
    `data/` was blind to the MORE authoritative of the two.

    Adding these roots is close to free in false positives, because the
    `.gitignore` exemption does the discriminating: `vendor/*/data/` is largely
    ignored, so only a tracked file (or an untracked, unignored one -- exactly
    what a `git add` sweep collects) can trip the guard there.
    """
    roots = [_TRACKED_DATA_MIRROR]
    vendor = _REPO_ROOT_FOR_GUARD / "vendor"
    if vendor.is_dir():
        for child in sorted(vendor.iterdir()):
            candidate = child / "data"
            if candidate.is_dir():
                roots.append(os.path.normcase(str(candidate)))
    return tuple(roots)


_GUARDED_MIRROR_ROOTS = _guarded_mirror_roots()
_DATA_MIRROR_WRITES: list[str] = []
_DATA_MIRROR_GUARD_MUTED = {"value": False}
_DATA_MIRROR_GUARD_DISABLED = str(os.environ.get("SYNDICATE_TEST_DATA_MIRROR_GUARD") or "").strip().lower() in {
    "off",
    "0",
    "false",
    "no",
}
_WRITE_MODE_CHARS = frozenset("wxa+")
_GIT_IGNORED_PATH_CACHE: dict[str, bool] = {}
_GIT_IGNORED_SUBTREE_CACHE: dict[str, bool] = {}


def _is_inside_tracked_data_mirror(path: object) -> bool:
    try:
        raw = os.fspath(path)  # type: ignore[arg-type]
    except TypeError:
        return False  # an int fd, a socket -- not a path we can attribute
    if isinstance(raw, bytes):
        try:
            raw = raw.decode()
        except Exception:
            return False
    normalized = os.path.normcase(os.path.abspath(raw))
    for root in _GUARDED_MIRROR_ROOTS:
        if normalized == root or normalized.startswith(root + os.sep):
            return True
    return False


def _git_ignores(path: object) -> bool:
    """Does `.gitignore` already exclude this path?

    Only ever called for a write that is already inside the mirror, so the
    subprocess cost lands on the rare path and never on a read.

    PROBE THE PATH ITSELF, NOT ITS PARENT. A rule written with a trailing slash
    (`data/nfl_source/tracking/`) matches a leading component of a longer path
    whether or not that component exists on disk, but matches the component
    ITSELF only if it is a directory that exists -- and an ignored subtree is
    exactly what a fresh worktree does not have. Probing the parent therefore
    answers "not ignored" for the whole tree the rule was written for.

    Two caches, and the difference matters. A directory rule applies to the
    whole subtree, so its verdict is safe to reuse for every sibling; any other
    pattern (`*.tmp`, say) is about the FILENAME, and reusing it per directory
    would exempt a real write that happens to sit beside an ignored one. So only
    a trailing-slash pattern populates the per-directory cache.

    Any failure -- git absent, a timeout, output in an unexpected shape --
    answers False. A guard whose join failed must not relax the rule.
    """
    try:
        target = Path(os.path.abspath(os.fspath(path)))  # type: ignore[arg-type]
    except Exception:
        return False
    exact_key = os.path.normcase(str(target))
    cached = _GIT_IGNORED_PATH_CACHE.get(exact_key)
    if cached is not None:
        return cached
    parent_key = os.path.normcase(str(target.parent))
    if _GIT_IGNORED_SUBTREE_CACHE.get(parent_key):
        return True
    import subprocess

    pattern = ""
    try:
        completed = subprocess.run(
            ["git", "check-ignore", "-v", "--", str(target)],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            timeout=20,
        )
        ignored = completed.returncode == 0
        if ignored:
            # `<source>:<line>:<pattern>	<path>` -- the pattern is the third
            # colon-separated field of the first line.
            first = (completed.stdout or "").splitlines()[0]
            pattern = first.split("	", 1)[0].split(":", 2)[-1].strip()
    except Exception:
        ignored = False
    _GIT_IGNORED_PATH_CACHE[exact_key] = ignored
    if ignored and pattern.endswith("/"):
        _GIT_IGNORED_SUBTREE_CACHE[parent_key] = True
    return ignored


def _record_data_mirror_write(operation: str, path: object) -> None:
    """Record, then raise. See the block comment above for why it is both."""
    if _DATA_MIRROR_GUARD_MUTED["value"] or _git_ignores(path):
        return
    import traceback

    detail = f"{operation} -> {path}"
    _DATA_MIRROR_WRITES.append(detail + "\n" + "".join(traceback.format_stack()[:-2][-12:]))
    raise RuntimeError(
        f"TEST WROTE INTO THE TRACKED data/ MIRROR: {detail}\n"
        "That tree is a git-tracked cold-start mirror, not scratch space -- see "
        "CLAUDE.md. Redirect the write (monkeypatch SYNDICATE_DATA_ROOT to a "
        "tmp_path, or patch the path the code under test resolves), or mark the "
        "test writes_tracked_data if it truly must write there."
    )


def _would_create(path: object) -> bool:
    """A `mkdir(exist_ok=True)` on an existing directory writes nothing."""
    try:
        return not Path(os.fspath(path)).exists()  # type: ignore[arg-type]
    except Exception:
        return True


def _install_data_mirror_write_guard() -> None:
    """Wrap the write seams once, at conftest import.

    `builtins.open` and `io.open` are the same function object under two names,
    and `Path.open` reaches `io.open` directly, so patching one of the three
    leaves the other two open. `Path.write_text`/`write_bytes` go through
    `Path.open` and need no wrapper of their own. `os.replace`/`os.rename` are
    here because an atomic write whose temp file sits OUTSIDE the mirror still
    lands inside it at the rename.
    """
    import builtins
    import io

    if getattr(builtins.open, "_syndicate_data_mirror_guard", False):
        return

    def _guard_open(original):
        def _open(file, mode="r", *args, **kwargs):
            if isinstance(mode, str) and (_WRITE_MODE_CHARS & set(mode)) and _is_inside_tracked_data_mirror(file):
                _record_data_mirror_write(f"open(mode={mode!r})", file)
            return original(file, mode, *args, **kwargs)

        _open._syndicate_data_mirror_guard = True  # type: ignore[attr-defined]
        return _open

    builtins.open = _guard_open(builtins.open)
    io.open = _guard_open(io.open)

    _path_open = Path.open

    def _guarded_path_open(self, mode="r", *args, **kwargs):
        if isinstance(mode, str) and (_WRITE_MODE_CHARS & set(mode)) and _is_inside_tracked_data_mirror(self):
            _record_data_mirror_write(f"Path.open(mode={mode!r})", self)
        return _path_open(self, mode, *args, **kwargs)

    Path.open = _guarded_path_open  # type: ignore[assignment]

    _path_mkdir = Path.mkdir

    def _guarded_path_mkdir(self, *args, **kwargs):
        if _is_inside_tracked_data_mirror(self) and _would_create(self):
            _record_data_mirror_write("Path.mkdir", self)
        return _path_mkdir(self, *args, **kwargs)

    Path.mkdir = _guarded_path_mkdir  # type: ignore[assignment]

    _path_unlink = Path.unlink

    def _guarded_path_unlink(self, *args, **kwargs):
        if _is_inside_tracked_data_mirror(self):
            _record_data_mirror_write("Path.unlink", self)
        return _path_unlink(self, *args, **kwargs)

    Path.unlink = _guarded_path_unlink  # type: ignore[assignment]

    for _name in ("makedirs", "mkdir"):
        def _guarded_os_mkdir(path, *args, _original=getattr(os, _name), _name=_name, **kwargs):
            if _is_inside_tracked_data_mirror(path) and _would_create(path):
                _record_data_mirror_write(f"os.{_name}", path)
            return _original(path, *args, **kwargs)

        setattr(os, _name, _guarded_os_mkdir)

    for _name in ("remove", "unlink", "rmdir"):
        def _guarded_os_delete(path, *args, _original=getattr(os, _name), _name=_name, **kwargs):
            if _is_inside_tracked_data_mirror(path):
                _record_data_mirror_write(f"os.{_name}", path)
            return _original(path, *args, **kwargs)

        setattr(os, _name, _guarded_os_delete)

    for _name in ("replace", "rename"):
        def _guarded_os_move(src, dst, *args, _original=getattr(os, _name), _name=_name, **kwargs):
            if _is_inside_tracked_data_mirror(dst) or _is_inside_tracked_data_mirror(src):
                _record_data_mirror_write(f"os.{_name}", dst)
            return _original(src, dst, *args, **kwargs)

        setattr(os, _name, _guarded_os_move)


_install_data_mirror_write_guard()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "writes_tracked_data: this test deliberately writes under the git-tracked "
        "data/ mirror; the conftest write guard is muted for it.",
    )


@pytest.fixture
def data_mirror_write_guard():
    """A handle on the write guard, for the guard's OWN self-check only.

    `tests/test_data_mirror_write_guard.py` has to make the guard fire on
    purpose, and a test cannot both trip it and pass: `pytest.raises` catches
    the raise, but the recorded entry still fails the autouse fixture in
    teardown -- which is the point of recording it. `consume()` takes the
    entries this test caused, so the teardown check sees an empty list and the
    self-check can assert on what was recorded.

    Nothing else should use this. A test that trips the guard by accident is the
    defect the guard exists to report.
    """

    class _Handle:
        def __init__(self) -> None:
            self._from = len(_DATA_MIRROR_WRITES)

        def consume(self) -> list[str]:
            taken = _DATA_MIRROR_WRITES[self._from:]
            del _DATA_MIRROR_WRITES[self._from:]
            return taken

        @staticmethod
        def classifies_as_mirror(path: object) -> bool:
            return _is_inside_tracked_data_mirror(path)

        @staticmethod
        def git_ignores(path: object) -> bool:
            return _git_ignores(path)

        @staticmethod
        def mirror_roots() -> tuple[str, ...]:
            return _GUARDED_MIRROR_ROOTS

    return _Handle()


@pytest.fixture(autouse=True)
def _no_writes_into_the_tracked_data_mirror(request):
    """Fail any test that writes under the repo's git-tracked `data/` tree."""
    muted = _DATA_MIRROR_GUARD_DISABLED or request.node.get_closest_marker("writes_tracked_data") is not None
    previous = _DATA_MIRROR_GUARD_MUTED["value"]
    _DATA_MIRROR_GUARD_MUTED["value"] = muted
    before = len(_DATA_MIRROR_WRITES)
    try:
        yield
    finally:
        _DATA_MIRROR_GUARD_MUTED["value"] = previous
        recorded = _DATA_MIRROR_WRITES[before:]
        del _DATA_MIRROR_WRITES[before:]
    if recorded:
        # Reached even when the writer swallowed the raise -- the normal case
        # for this repo's never-raise instrumentation paths.
        raise AssertionError(
            "this test wrote into the git-tracked data/ mirror "
            f"({len(recorded)} operation(s)); see the block comment in "
            "tests/conftest.py.\n\n" + "\n\n".join(recorded)
        )
