"""A date's "has games" verdict must not carry across midnight from artifact existence.

Measured 2026-09-15, lane `wnba-future-date-cache-carry`:
  * refresh-worker writes an EMPTY `recommendations_slate_<date>.json` (0 games,
    94 bytes) for TOMORROW before midnight CT -- 09-14's at 22:39 CDT 09-13,
    09-15's at 02:06 CDT 09-14;
  * `available_dates()` counts any slate file, so `has_games_for_date(tomorrow)`
    took the "not today and an artifact exists" shortcut and put the date into
    `_HAS_GAMES_CONFIRMED_TRUE_CACHE`;
  * that cache is checked BEFORE the "today always asks ESPN" rule, so after
    midnight the same process read today as confirmed, the stored-date guard
    allowed the substitution, and refresh-worker saved the 2026-08-30 games
    under today's live_state key (first phantom 00:04 CDT 09-14, 00:06 CDT 09-15).

Every test here is pinned both ways: the pre-fix code fails it.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.wnba import cards
from syndicate.features.wnba import sources

EVE = "2026-09-14"
TODAY = "2026-09-15"
LAST_SLATE = "2026-08-30"


class _Response:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


@pytest.fixture
def world(monkeypatch):
    """The eve of a no-game day: tomorrow's empty slate file already exists."""
    clock = _Clock(EVE)
    calls = []

    def _urlopen(request, timeout=None):
        calls.append(request.full_url)
        return _Response({"events": []})

    monkeypatch.setattr(sources.urllib_request, "urlopen", _urlopen)
    monkeypatch.setattr(sources, "central_today_iso", clock)
    monkeypatch.setattr(sources, "available_dates", lambda: [LAST_SLATE, EVE, TODAY])
    monkeypatch.delenv("SYNDICATE_WNBA_SCOREBOARD_URL", raising=False)
    sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.clear()
    yield clock, calls
    sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.clear()


def test_a_future_dates_artifact_verdict_does_not_survive_into_that_day(world):
    clock, calls = world
    # Unchanged: a non-today date with an artifact is still trusted without ESPN.
    assert sources.has_games_for_date(TODAY) is True
    assert calls == []

    clock.value = TODAY  # midnight CT, same process
    assert sources.has_games_for_date(TODAY) is False
    assert len(calls) == 1 and "dates=20260915" in calls[0]


def test_an_espn_confirmed_future_date_still_carries(world, monkeypatch):
    """The cache's real purpose survives: a SCHEDULE-confirmed True is stable."""
    clock, calls = world
    monkeypatch.setattr(sources, "available_dates", lambda: [])

    def _games(request, timeout=None):
        calls.append(request.full_url)
        return _Response({"events": [{"id": "401857190"}]})

    monkeypatch.setattr(sources.urllib_request, "urlopen", _games)
    assert sources.has_games_for_date(TODAY) is True
    clock.value = TODAY
    assert sources.has_games_for_date(TODAY) is True
    assert len(calls) == 1


def _stub_page_builder(monkeypatch, clock):
    game = {"gamePk": "401857189", "event_id": "401857189", "away": {"abbr": "CON"},
            "home": {"abbr": "DAL"}, "detail": "Final"}
    monkeypatch.setattr(cards, "central_today_iso", clock)
    monkeypatch.setattr(cards, "available_dates", lambda: [LAST_SLATE, EVE, TODAY])
    monkeypatch.setattr(cards, "_nearest_available_cards_date", lambda _d: LAST_SLATE)
    monkeypatch.setattr(cards, "_artifact_bundle", lambda _d, allow_fallback=True: {"rows": []})
    monkeypatch.setattr(cards, "_games_from_artifacts",
                        lambda d: ([dict(game)], "cards.csv", "recs.json") if d == LAST_SLATE else ([], "cards.csv", "recs.json"))
    monkeypatch.setattr(cards, "_games_from_public_scoreboard", lambda _d: ([], ""))
    monkeypatch.setattr(cards, "_supplement_games_with_live_state", lambda games, _d, **_k: (games, None, 0, 0))
    monkeypatch.setattr(cards, "_games_from_live_state_fallback", lambda _d, ttl=12: ([], ""))
    monkeypatch.setattr(cards, "_render_web_dyno", lambda: False)
    monkeypatch.setattr(cards, "_cache_get_context", lambda _k: None)
    monkeypatch.setattr(cards, "_cache_set_context", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(cards, "_build_wnba_game_lens", lambda _g: {})
    monkeypatch.setattr(cards, "_attach_wnba_momentum", lambda *_a, **_k: None)
    monkeypatch.setattr(cards, "apply_game_board_contract", lambda payload, **_k: dict(payload))
    monkeypatch.setattr(cards, "_wnba_advanced_contract", lambda **_k: {})


def test_the_writer_does_not_save_the_last_slate_after_midnight(world, monkeypatch):
    """The WRITER's own call, with the REAL `has_games_for_date` (not stubbed):
    `build_live_state_payload(today, allow_stored_date_fallback=True)` builds this
    context and saves its games under today's live_state key.

    Pre-fix: the eve's lookup of tomorrow cached True, and after midnight this
    returned the 2026-08-30 game under today's date.
    """
    clock, _calls = world
    _stub_page_builder(monkeypatch, clock)
    assert cards.has_games_for_date is sources.has_games_for_date

    sources.has_games_for_date(TODAY)  # the eve: any caller asking about tomorrow
    clock.value = TODAY
    context = cards._build_cards_page_context_uncached(TODAY, allow_stored_date_fallback=True)
    assert context["date"] == TODAY
    assert context["games"] == []
