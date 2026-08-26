"""The chip strip asks for the board's horizon; the home rail asks for today. `#575`.

TWO DEFECTS, ONE ROOT. `provider.games()` served two callers that need
different answers, and overloading it produced both:

  * SOCCER: `#542` widened the span to two matchdays unconditionally. That fixed
    the board (`no_chip_available` 251 -> 0) and, unnoticed, DOUBLED the home
    rail from 98 games to 210 -- `_load_home_game_items` falls through to
    `_compact_game_cards(home_games)` for soccer and renders every one, with a
    count badge then claiming 210 games today.
  * NFL: measured 2026-08-26T17:16:23Z, `CHIP_JOIN_COVERAGE sport=nfl chips=0
    cards=106 no_chip_available=106`. Every NFL card printed full club names.
    On that date `preseason_week_for_date` is None and
    `regular_season_game_ids_for_date` is None, so it falls to
    `preseason_target_week`=4 and then filters week 4 down to games played ON
    08-26 -- none. Right for a rail meaning "today", fatal for a strip serving a
    board whose cards run weeks ahead.

The horizon is now the CALLER's to ask for.
"""

from __future__ import annotations

import syndicate.blueprints.home as home_module
from syndicate.features.shared.game_chip_scoreboard import (
    _games_accepts_include_upcoming,
)


class _Ctx:
    league = "la_liga"
    season = 2026
    week = 5
    requested_date = "2026-08-26"
    context_label = "2026-08-26"


def _soccer_provider(monkeypatch, fake_cards):
    monkeypatch.setattr(
        "syndicate.features.soccer.cards.build_cards_page_context", fake_cards, raising=False
    )
    provider = home_module._SoccerDataProvider()
    monkeypatch.setattr(provider, "_active_leagues", lambda today: ["la_liga"])
    monkeypatch.setattr(provider, "_league_season_week", lambda lg, ctx, today: (2026, 5))
    return provider


def test_the_home_rail_gets_one_matchday(monkeypatch):
    asked: list[int] = []

    def _fake(league, week, season):
        asked.append(week)
        return {"games": [{"event_id": f"{league}-{week}"}]}

    provider = _soccer_provider(monkeypatch, _fake)
    games = provider.games(_Ctx(), is_active_today=True)

    assert asked == [5], "the rail means TODAY; a second matchday is the #542 regression"
    assert len(games) == 1


def test_the_chip_strip_gets_two(monkeypatch):
    asked: list[int] = []

    def _fake(league, week, season):
        asked.append(week)
        return {"games": [{"event_id": f"{league}-{week}"}]}

    provider = _soccer_provider(monkeypatch, _fake)
    games = provider.games(_Ctx(), is_active_today=True, include_upcoming=True)

    assert asked == [5, 6]
    assert len(games) == 2


def test_the_default_is_the_narrow_one():
    """Default False, so an un-updated caller keeps its old behaviour.

    Asserted on the SIGNATURE, because the whole failure mode here is a caller
    silently getting a horizon it did not ask for.
    """
    import inspect

    for provider_type in (home_module._SoccerDataProvider, home_module._NFLDataProvider):
        param = inspect.signature(provider_type.games).parameters["include_upcoming"]
        assert param.default is False


def test_the_probe_detects_an_old_provider():
    """`home.py` and the chip builder are separate blobs; either can lag a deploy.

    An unguarded kwarg would raise TypeError against an older provider and blank
    EVERY sport's strip -- strictly worse than the narrow chips it replaces.
    """

    class _Old:
        def games(self, context, *, is_active_today):
            return []

    class _New:
        def games(self, context, *, is_active_today, include_upcoming=False):
            return []

    assert _games_accepts_include_upcoming(_New()) is True
    assert _games_accepts_include_upcoming(_Old()) is False


def test_an_unintrospectable_provider_assumes_the_old_signature():
    """False costs the wider horizon; True would raise and blank the strip."""

    class _Weird:
        games = "not a function"

    assert _games_accepts_include_upcoming(_Weird()) is False


def test_nfl_keeps_the_exact_date_filter_for_the_rail(monkeypatch):
    """The filter is CORRECT for the rail -- this pins that it survives."""
    calls: list[object] = []

    def _fake_filter(games, requested_date):
        calls.append(requested_date)
        return []

    monkeypatch.setattr(home_module, "_nfl_games_on_requested_date", _fake_filter)
    monkeypatch.setattr(
        "syndicate.features.nfl.preseason_cards.build_preseason_cards_page_context",
        lambda week, season=None: {"games": [{"gamePk": "1"}]},
        raising=False,
    )
    monkeypatch.setattr(
        "syndicate.features.nfl.preseason_cards.build_nfl_preseason_market_board",
        lambda season, week: {"games": []},
        raising=False,
    )
    monkeypatch.setattr(
        "syndicate.features.nfl.sources.preseason_week_for_date",
        lambda season, date_text: None,
        raising=False,
    )
    monkeypatch.setattr(
        "syndicate.features.nfl.sources.regular_season_game_ids_for_date",
        lambda season, date_text: None,
        raising=False,
    )
    monkeypatch.setattr(
        "syndicate.features.nfl.sources.preseason_target_week",
        lambda season: 4,
        raising=False,
    )

    class _NflCtx:
        season = 2026
        week = None
        context_label = "2026-08-26"
        requested_date = "2026-08-26"

    provider = home_module._NFLDataProvider()

    assert provider.games(_NflCtx(), is_active_today=True) == []
    assert calls == ["2026-08-26"], "the rail must still filter to the requested date"

    # And the strip must NOT be filtered -- this is the 106-card defect.
    calls.clear()
    strip = provider.games(_NflCtx(), is_active_today=True, include_upcoming=True)
    assert strip == [{"gamePk": "1"}]
    assert calls == [], "the strip must not be narrowed to one date"
