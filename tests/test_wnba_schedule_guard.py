"""WNBA's "the schedule is authoritative" guard must actually fire on Render.

Measured 2026-09-10, lane `wnba-chip-frozen-trace`:
  * `has_games_for_date` asked `site.api.espn.com`, which answers Render with
    HTTP 403, so the verdict for TODAY was None, never False;
  * the guard refused a stored-date substitution only on False;
  * on every no-game day a worker therefore saved the last real slate
    (2026-08-30) under today's live_state key, and the board's WNBA chips
    showed four finished games for eleven days.

Every test here is pinned both ways: the pre-fix code fails it.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.wnba import cards
from syndicate.features.wnba import sources

TODAY = "2026-09-10"
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


@pytest.fixture
def espn(monkeypatch):
    calls = []

    def _urlopen(request, timeout=None):
        calls.append(request)
        return _Response({"events": []})

    monkeypatch.setattr(sources.urllib_request, "urlopen", _urlopen)
    monkeypatch.setattr(sources, "central_today_iso", lambda: TODAY)
    monkeypatch.delenv("SYNDICATE_WNBA_SCOREBOARD_URL", raising=False)
    sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.discard(TODAY)
    return calls


# ------------------------------------------------------------------ (a) the host
def test_the_schedule_is_asked_on_the_host_that_answers_render(espn):
    assert sources.has_games_for_date(TODAY) is False
    request = espn[-1]
    assert request.full_url.startswith("https://site.web.api.espn.com/"), request.full_url
    assert "dates=20260910" in request.full_url
    # The pair verified from Render by scripts/build_wnba_boxscores.py.
    assert request.get_header("User-agent") == "Mozilla/5.0"
    assert request.get_header("Accept") == "application/json"


def test_the_scoreboard_override_is_honoured(espn, monkeypatch):
    monkeypatch.setenv("SYNDICATE_WNBA_SCOREBOARD_URL", "https://example.test/wnba/scoreboard")
    sources.has_games_for_date(TODAY)
    assert espn[-1].full_url.startswith("https://example.test/wnba/scoreboard?dates=")


def test_a_refused_fetch_is_still_unknown(monkeypatch):
    """None stays the honest answer to a failed fetch; (b) is what stops it
    being read as permission."""
    def _refuse(request, timeout=None):
        raise OSError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(sources.urllib_request, "urlopen", _refuse)
    monkeypatch.setattr(sources, "central_today_iso", lambda: TODAY)
    sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.discard(TODAY)
    assert sources.has_games_for_date(TODAY) is None


# --------------------------------------------------------------- (b) the resolver
@pytest.fixture
def no_cards_today(monkeypatch):
    monkeypatch.setattr(cards, "central_today_iso", lambda: TODAY)
    monkeypatch.setattr(cards, "available_dates", lambda: ["2026-08-28", "2026-08-29", LAST_SLATE])
    monkeypatch.setattr(cards, "_artifact_bundle", lambda _d, allow_fallback=True: {"rows": []})


@pytest.mark.parametrize("verdict, expected", [(None, TODAY), (False, TODAY), (True, LAST_SLATE)])
def test_today_is_substituted_only_when_the_schedule_confirms_games(no_cards_today, monkeypatch, verdict, expected):
    monkeypatch.setattr(cards, "has_games_for_date", lambda _d: verdict)
    assert cards._resolved_source_cards_date(TODAY, allow_stored_date_fallback=True) == expected


def test_a_past_date_keeps_the_stored_fallback(no_cards_today, monkeypatch):
    monkeypatch.setattr(cards, "has_games_for_date", lambda _d: None)
    assert cards._resolved_source_cards_date("2026-09-05", allow_stored_date_fallback=True) == LAST_SLATE


# ----------------------------------------------- (b) the page builder = the writer
def _stub_page_builder(monkeypatch, verdict):
    game = {"gamePk": "401857189", "event_id": "401857189", "away": {"abbr": "CON"},
            "home": {"abbr": "DAL"}, "detail": "Final"}
    monkeypatch.setattr(cards, "central_today_iso", lambda: TODAY)
    monkeypatch.setattr(cards, "has_games_for_date", lambda _d: verdict)
    monkeypatch.setattr(cards, "available_dates", lambda: [LAST_SLATE])
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


@pytest.mark.parametrize("verdict", [None, False])
def test_the_page_builder_keeps_an_unconfirmed_today_empty(monkeypatch, verdict):
    """The WRITER's own call: `build_live_state_payload(today, allow_stored_date_fallback=True)`
    builds this context and saves its games under TODAY's live_state key.

    Pre-fix this returned the 2026-08-30 game even for a correct `False` verdict,
    because the `_nearest_available_cards_date` branch never asked the schedule.
    """
    _stub_page_builder(monkeypatch, verdict)
    context = cards._build_cards_page_context_uncached(TODAY, allow_stored_date_fallback=True)
    assert context["date"] == TODAY
    assert context["games"] == []


def test_the_page_builder_still_recovers_a_confirmed_slate(monkeypatch):
    """The fallback's original purpose survives: games confirmed today, artifact not landed yet."""
    _stub_page_builder(monkeypatch, True)
    context = cards._build_cards_page_context_uncached(TODAY, allow_stored_date_fallback=True)
    assert context["date"] == LAST_SLATE
    assert len(context["games"]) == 1
