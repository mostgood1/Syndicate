from __future__ import annotations

import pytest


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
    from syndicate.features.wnba.cards import build_cards_page_context
    from syndicate.features.wnba.cards import build_live_player_lens_payload
    from syndicate.features.wnba.cards import build_live_state_payload
    from syndicate.features.wnba.cards import build_source_cards_payload

    caches = [
        build_live_state_payload,
        build_source_cards_payload,
        build_cards_page_context,
        build_live_player_lens_payload,
    ]
    # build_soccer_market_board's cache has the same hazard for the same
    # reason: it is keyed on (league, selected_date) + a 60s wall-clock
    # bucket + artifact signatures, and those signatures are all 0 in tests
    # because the real CSVs don't exist in a checkout. Two tests building
    # the same league/date with different patched rows would otherwise
    # collide -- which the existing BuildSoccerMarketBoardTests do, both on
    # ("mls", "2026-07-22").
    from syndicate.features.soccer.market_board import clear_soccer_market_board_cache

    for cache_owner in caches:
        cache_owner.cache_clear()
    clear_soccer_market_board_cache()
    yield
    for cache_owner in caches:
        cache_owner.cache_clear()
    clear_soccer_market_board_cache()


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
