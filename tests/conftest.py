from __future__ import annotations

import pytest


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
