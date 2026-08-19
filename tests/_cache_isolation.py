"""Cache resets shared by the pytest conftest AND the unittest entrypoints.

**Why this file exists rather than living only in `conftest.py`.** The WNBA and
NBA cards caches are keyed on `(selected_date, ...)` plus a wall-clock TTL
bucket -- not on any content fingerprint -- so two tests that use the same date
literal within one TTL window silently share a result. `conftest.py` already
handled that with autouse fixtures, and under `pytest tests/` it works.

But **CI does not run pytest.** `.github/workflows/ci.yml` runs
`python -m unittest tests.test_archives`, and `daily-update.yml` runs a list of
thirteen modules the same way. `conftest.py` is a pytest plugin file: `unittest`
never imports it, so under those two workflows the isolation simply is not
there. Measured 2026-08-19: `tests/test_wnba_cards_merge_aliases.py` passed
under pytest and failed two tests under `python -m unittest`, because
`test_source_cards_payload_hydrates_betting_from_live_lines_artifact` runs first
alphabetically and leaves its `("2026-07-02", True)` payload in
`build_source_cards_payload`'s cache for the two tests after it -- which then
assert against a fixture they never got (`1 != 4`, and a `startTime` of
`2026-07-02T23:00:00Z` that belongs to the *earlier* test's `commence_time`).
That is not a flake and it did not need a race: it is deterministic and it had
been failing the Daily Update workflow every morning.

Putting the reset here and calling it from BOTH places means there is one
definition to keep correct. A test module that runs under `unittest` should
mix in `WallClockCacheIsolationMixin` below; `conftest.py` calls the same
functions from its autouse fixtures.
"""

from __future__ import annotations


def clear_wnba_wall_clock_caches() -> None:
    """Reset the WNBA cards + soccer market board wall-clock-TTL caches."""
    from syndicate.features.wnba.cards import build_cards_page_context
    from syndicate.features.wnba.cards import build_live_player_lens_payload
    from syndicate.features.wnba.cards import build_live_state_payload
    from syndicate.features.wnba.cards import build_source_cards_payload
    from syndicate.features.soccer.market_board import clear_soccer_market_board_cache

    for cache_owner in (
        build_live_state_payload,
        build_source_cards_payload,
        build_cards_page_context,
        build_live_player_lens_payload,
    ):
        cache_owner.cache_clear()
    clear_soccer_market_board_cache()


def clear_nba_cards_caches() -> None:
    """Reset the NBA cards caches -- same hazard, same shape as WNBA's."""
    from syndicate.features.nba.cards import _NBA_CARDS_CONTEXT_CACHE
    from syndicate.features.nba.cards import _live_projection_calibration_index
    from syndicate.features.nba.cards import _local_live_snapshot_payload_cached
    from syndicate.features.nba.cards import _local_live_state_payload_cached
    from syndicate.features.nba.cards import _nba_team_branding_index

    for cache_owner in (
        _nba_team_branding_index,
        _local_live_state_payload_cached,
        _local_live_snapshot_payload_cached,
        _live_projection_calibration_index,
    ):
        cache_owner.cache_clear()
    _NBA_CARDS_CONTEXT_CACHE.clear()


class WallClockCacheIsolationMixin:
    """Mix into a `unittest.TestCase` that builds WNBA/NBA cards payloads.

    Clears before the test and again after it, mirroring the autouse fixtures'
    yield-both-sides behaviour, so the module is safe to run under `unittest`,
    under `pytest`, and in either order relative to other modules.
    """

    def setUp(self) -> None:  # noqa: D102 - unittest hook
        super().setUp()
        clear_wnba_wall_clock_caches()
        clear_nba_cards_caches()
        self.addCleanup(clear_nba_cards_caches)
        self.addCleanup(clear_wnba_wall_clock_caches)
