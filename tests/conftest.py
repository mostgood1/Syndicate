from __future__ import annotations

import pytest


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
