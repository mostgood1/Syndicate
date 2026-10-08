"""Inside a web request the Layer 2 live restate reads PUBLISHED chips only.

Lane `web-restart-healthz` 2026-10-08. A cold `/api/syndicate/query` took 47.9 s live
(ask_bar.js aborts at 45 s). Profiled in a fresh process on the fleet, ~65-80% of it was
`_refresh_layer2_live_state` calling `build_game_chips`: a fan-out over every sport, with
live ESPN / StatsAPI fetches, for every requested date, even though the worker publishes
today's chips every few minutes and the published ones were ranked first anyway.

In a request: published chips (fresh or stale) restate, and the inline build never runs.
Outside one (the worker loop): unchanged. The env switch restores the inline build on web.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask import Flask

from pipeline import intelligence_state as S

CHIPS = "syndicate.features.shared.game_chip_scoreboard.build_game_chips"
DATE = "2026-09-14"
AWAY, HOME = "Denver Broncos", "Kansas City Chiefs"


def _card():
    return {
        "sport": "nfl", "away_team": AWAY, "home_team": HOME,
        "away_key": "denver broncos", "home_key": "kansas city chiefs",
        "commence_time": "2026-09-15T00:15:00Z", "game_date": DATE,
        "lane": "pregame", "market_state": "pregame",
    }


def _chip(state="live"):
    return {
        "sport": "nfl", "state": state,
        "away": {"name": AWAY, "abbr": "DEN", "key": "denver broncos", "score": "7"},
        "home": {"name": HOME, "abbr": "KC", "key": "kansas city chiefs", "score": "14"},
    }


def _stamp(age_s):
    return (datetime.now(timezone.utc) - timedelta(seconds=age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def published(monkeypatch):
    box = {"payload": None}
    monkeypatch.setattr(S, "read_game_chips", lambda d: box["payload"] if d == DATE else None)
    monkeypatch.delenv("SYNDICATE_LAYER2_RESTATE_INLINE_ON_WEB", raising=False)
    return box


def _in_request(fn):
    with Flask("probe").test_request_context("/api/syndicate/query", method="POST"):
        return fn()


def test_in_a_request_the_inline_build_never_runs_and_published_chips_restate(published):
    published["payload"] = {"written_at": _stamp(30), "chips": [_chip()]}
    card = _card()
    with patch(CHIPS, side_effect=AssertionError("inline build in a web request")) as build:
        restated = _in_request(lambda: S._refresh_layer2_live_state([card], [DATE]))
    assert build.call_count == 0
    assert restated == 1 and card.get("is_live") is True


def test_in_a_request_a_stale_published_chip_still_restates(published):
    """Stale, not empty: the only chips web has are the worker's."""
    published["payload"] = {"written_at": _stamp(7200), "chips": [_chip()]}
    card = _card()
    with patch(CHIPS, side_effect=AssertionError("inline build in a web request")):
        restated = _in_request(lambda: S._refresh_layer2_live_state([card], [DATE]))
    assert restated == 1 and card.get("is_live") is True


def test_in_a_request_with_no_published_chips_the_card_is_left_as_written(published):
    card = _card()
    with patch(CHIPS, side_effect=AssertionError("inline build in a web request")):
        restated = _in_request(lambda: S._refresh_layer2_live_state([card], [DATE]))
    assert restated == 0 and card["lane"] == "pregame" and "is_live" not in card


def test_outside_a_request_the_worker_still_builds_inline(published):
    """Reachability, off != on: the same call outside a request DOES build."""
    card = _card()
    with patch(CHIPS, return_value=[_chip()]) as build:
        restated = S._refresh_layer2_live_state([card], [DATE])
    assert build.call_count == 1
    assert restated == 1 and card.get("is_live") is True


def test_the_env_switch_restores_the_inline_build_on_web(published, monkeypatch):
    monkeypatch.setenv("SYNDICATE_LAYER2_RESTATE_INLINE_ON_WEB", "1")
    card = _card()
    with patch(CHIPS, return_value=[_chip()]) as build:
        restated = _in_request(lambda: S._refresh_layer2_live_state([card], [DATE]))
    assert build.call_count == 1 and restated == 1
