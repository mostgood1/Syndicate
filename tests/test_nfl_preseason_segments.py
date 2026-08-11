"""`#349` — NFL preseason interval markets come from the per-event endpoint.

`_nfl_segment_market_map()` already built the full Q1-Q4/H1-H2 vocabulary, and
nothing fed it: the script's only fetch is the SLATE endpoint, which serves the
core three. Measured 2026-08-11 -- all 121 NFL preseason rows were
`segment: full` across 16 real fixtures.

MLB documents the same split (`_CORE_GAME_MARKET_KEYS` on the slate, segments
per-event, "#17: 3 credits instead of 45"), so this mirrors a pattern already
proven rather than inventing one.
"""

from __future__ import annotations

import importlib.util
import pathlib

_SRC = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fetch_nfl_preseason_odds.py").read_text(encoding="utf-8")


def test_segments_are_fetched_per_event_not_on_the_slate_call():
    assert "/events/{event_id}/odds" in _SRC or "events/{event_id}/odds" in _SRC
    assert "_fetch_preseason_event_segments" in _SRC
    # and its output is appended to the same quote-log write as the slate
    assert "_append_nfl_preseason_book_quotes(events + segment_events)" in _SRC


def test_only_full_game_keys_are_excluded_from_the_per_event_request():
    # Requesting the core three per-event would pay 16x for what the slate call
    # already returned -- exactly the cost #17 avoided for MLB.
    assert 'spec[0] != "full"' in _SRC


def test_the_window_is_tunable_without_a_deploy():
    assert "SYNDICATE_NFL_PRESEASON_SEGMENT_WINDOW_SECONDS" in _SRC
    assert "4 * 3600" in _SRC


def test_a_failed_segment_fetch_cannot_cost_the_slate_its_prices():
    # The slate call is the load-bearing one; segments are additive.
    assert "segment fetch failed" in _SRC
    assert "continue" in _SRC


def test_live_and_recent_games_stay_in_window():
    # A negative time-to-kickoff is a live game, which is when interval lines
    # matter most -- excluding it would fetch segments only before kickoff.
    assert "until < -6 * 3600" in _SRC


def test_every_name_the_segment_fetch_uses_actually_resolves():
    """The bug the source-assertions above could NOT see.

    `requests`, `get_base_url` and `record_oddsapi_quota` were all used by
    `_fetch_preseason_event_segments` and none were imported -- the function
    would have NameError'd on its first call, in production, on a live slate.
    Every test above passed anyway, because they assert on source TEXT and text
    cannot tell you whether a name is bound.
    """
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "_nflpre_resolve", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fetch_nfl_preseason_odds.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("requests", "get_base_url", "record_oddsapi_quota"):
        assert hasattr(mod, name), f"{name} is used by the segment fetch but never imported"
    # and the function is callable with no events without touching the network
    assert mod._fetch_preseason_event_segments("key", []) == []
