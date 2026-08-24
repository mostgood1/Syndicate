"""Soccer chips must cover the board's HORIZON, not the current matchday. `#545`.

MEASURED IN PRODUCTION 2026-08-24T20:36:39Z:

    CHIP_JOIN_COVERAGE sport=soccer chips=96
      chip_dates=['2026-08-22','2026-08-23',...]
      cards=342 by_matchup=7 by_canonical=57 no_chip_available=251

65 of those 96 chips described fixtures that had ALREADY BEEN PLAYED, and 72 of
the 105 fixtures inside the board's seven-day window had no chip at all.

The cause is a phase offset, not a thin build. `default_week(reference_date=
today)` answers "which matchday are we in"; on a Monday that is the one that
finished over the weekend. The board asks a different question -- the next seven
days. `primeira_liga` was the control: its resolved week happened to align and
it was the only league with zero uncovered fixtures.

It also DECAYS through the day: `by_matchup` fell 94 -> 7 between 15:34Z and
20:36Z as the board rolled forward past the fixtures the chips described. So
coverage was thinnest exactly when the next slate is the one being bet.
"""

from __future__ import annotations

import syndicate.blueprints.home as home_module


class _Ctx:
    league = "mls"
    season = 2026
    week = 5
    requested_date = "2026-08-24"
    context_label = "test"


def _provider():
    return home_module._SoccerDataProvider()


def test_it_asks_for_the_current_week_and_the_next(monkeypatch):
    asked: list[tuple[str, int, int]] = []

    def _fake_cards(league, week, season):
        asked.append((league, week, season))
        return {"games": [{"event_id": f"{league}-{week}-1"}]}

    monkeypatch.setattr(home_module, "build_cards_page_context", _fake_cards, raising=False)
    monkeypatch.setattr(
        "syndicate.features.soccer.cards.build_cards_page_context", _fake_cards, raising=False
    )
    provider = _provider()
    monkeypatch.setattr(provider, "_active_leagues", lambda today: ["la_liga"])
    monkeypatch.setattr(provider, "_league_season_week", lambda lg, ctx, today: (2026, 5))

    games = provider.games(_Ctx(), is_active_today=True)

    assert [w for _, w, _ in asked] == [5, 6], "current matchday alone is the defect"
    assert len(games) == 2


def test_a_fixture_in_both_weeks_is_emitted_once(monkeypatch):
    """Two chips for one fixture is WORSE than one, not merely redundant.

    The browser's canonical index drops colliding keys rather than picking one,
    so a duplicated fixture loses its chip entirely -- the widening would have
    caused the very symptom it exists to fix.
    """

    def _fake_cards(league, week, season):
        return {"games": [{"event_id": "same-fixture"}]}

    monkeypatch.setattr(
        "syndicate.features.soccer.cards.build_cards_page_context", _fake_cards, raising=False
    )
    provider = _provider()
    monkeypatch.setattr(provider, "_active_leagues", lambda today: ["la_liga"])
    monkeypatch.setattr(provider, "_league_season_week", lambda lg, ctx, today: (2026, 5))

    games = provider.games(_Ctx(), is_active_today=True)

    assert len(games) == 1


def test_a_missing_next_week_does_not_cost_the_current_one(monkeypatch):
    """Normal at a season boundary, so the guard is PER WEEK, not per league."""

    def _fake_cards(league, week, season):
        if week == 6:
            raise RuntimeError("no such week")
        return {"games": [{"event_id": "wk5"}]}

    monkeypatch.setattr(
        "syndicate.features.soccer.cards.build_cards_page_context", _fake_cards, raising=False
    )
    provider = _provider()
    monkeypatch.setattr(provider, "_active_leagues", lambda today: ["la_liga"])
    monkeypatch.setattr(provider, "_league_season_week", lambda lg, ctx, today: (2026, 5))

    games = provider.games(_Ctx(), is_active_today=True)

    assert [g["event_id"] for g in games] == ["wk5"]


def test_one_broken_league_does_not_empty_the_sport(monkeypatch):
    def _fake_cards(league, week, season):
        if league == "broken":
            raise RuntimeError("bad schedule artifact")
        return {"games": [{"event_id": f"{league}-{week}"}]}

    monkeypatch.setattr(
        "syndicate.features.soccer.cards.build_cards_page_context", _fake_cards, raising=False
    )
    provider = _provider()
    monkeypatch.setattr(provider, "_active_leagues", lambda today: ["broken", "la_liga"])
    monkeypatch.setattr(provider, "_league_season_week", lambda lg, ctx, today: (2026, 5))

    games = provider.games(_Ctx(), is_active_today=True)

    assert {g["event_id"] for g in games} == {"la_liga-5", "la_liga-6"}


def test_a_fixture_with_no_id_is_still_emitted(monkeypatch):
    """De-duplication must not become a filter.

    Identity is used to drop repeats; a game the provider gives no id is still a
    real fixture and dropping it would trade one coverage gap for another.
    """

    def _fake_cards(league, week, season):
        return {"games": [{"away": {"name": "A"}, "home": {"name": "B"}}]}

    monkeypatch.setattr(
        "syndicate.features.soccer.cards.build_cards_page_context", _fake_cards, raising=False
    )
    provider = _provider()
    monkeypatch.setattr(provider, "_active_leagues", lambda today: ["la_liga"])
    monkeypatch.setattr(provider, "_league_season_week", lambda lg, ctx, today: (2026, 5))

    games = provider.games(_Ctx(), is_active_today=True)

    assert len(games) == 2
