"""Confirmed lineups apply PER SIDE, not all-or-nothing per fixture.

Measured against the real ESPN feed 2026-08-21 18:11Z, today's slate:

    Marseille v Strasbourg      home 10  away  7   -> kept before and after
    Standard Liege v RAAL       home  9  away  5   -> WAS DISCARDED WHOLE
    Arsenal v Coventry          home  8  away  0   -> WAS DISCARDED WHOLE

Standard's nine confirmed starters and Arsenal's eight were thrown away for the
other club's name-matching gap: 1 of 4 fixtures got lineups where 3 could have.
"""
from __future__ import annotations

import pytest

from syndicate.features.soccer.features import lineups as L


def _rows(team, names, side):
    return [
        {"player_id": f"{team}-{i}", "player_name": n, "team": team, "side": side}
        for i, n in enumerate(names)
    ]


ELEVEN = [f"Player {i}" for i in range(11)]
FIVE = [f"Player {i}" for i in range(5)]


@pytest.fixture
def espn(monkeypatch):
    """ESPN posts a full XI for both sides; what varies is OUR roster."""
    def fake_summary(league, event_id):
        return {"_": event_id}

    def fake_rows(summary, *, event_id):
        out = []
        for side in ("home", "away"):
            for n in ELEVEN:
                out.append({"player_name": n, "side": side, "starter": True})
        return out

    monkeypatch.setattr(L, "fetch_match_summary", fake_summary)
    monkeypatch.setattr(L, "extract_match_player_rows", fake_rows)
    monkeypatch.setattr(
        L, "find_event_for_fixture",
        lambda events, *, home_team, away_team: {"event_id": "e1"},
    )


def _call(home_names, away_names):
    return L.fetch_confirmed_starter_ids(
        "epl",
        home_team="H", away_team="A",
        home_player_rows=_rows("H", home_names, "home"),
        away_player_rows=_rows("A", away_names, "away"),
        events=[{"event_id": "e1"}],
    )


def test_both_sides_resolve_is_unchanged(espn):
    """The Marseille case: nothing about a working fixture may change."""
    home, away = _call(ELEVEN, ELEVEN)
    assert len(home) == 11 and len(away) == 11


def test_weak_away_no_longer_discards_a_good_home(espn):
    """The Standard Liege case: home resolved 9, away 5. Home must survive."""
    home, away = _call(ELEVEN, FIVE)
    assert len(home) == 11, "a good home side was discarded for the away side"
    assert away == set(), "an under-evidenced side must contribute nothing"


def test_absent_away_roster_no_longer_discards_home(espn):
    """The Arsenal v Coventry case: the pipeline had ZERO Coventry players."""
    home, away = _call(ELEVEN, [])
    assert len(home) == 11
    assert away == set()


def test_both_sides_under_the_bar_still_refuses(espn):
    """The evidence bar per side is UNCHANGED -- this widens which sides
    qualify, not how little evidence qualifies one."""
    assert _call(FIVE, FIVE) is None


def test_an_unconfirmed_side_is_absent_not_an_empty_tuple(espn, monkeypatch):
    """`()` and a missing key are both falsy, but callers count confirmations by
    testing the HOME key -- writing `()` would make an away-only confirmation
    look like a home confirmation of nobody."""
    monkeypatch.setattr(L, "fetch_events", lambda league, **kw: [{"event_id": "e1"}])
    fixtures = [{"home_team": "H", "away_team": "A"}]
    out = L.attach_confirmed_starters(
        fixtures,
        league="epl",
        player_rows_by_team={"H": _rows("H", ELEVEN, "home"), "A": _rows("A", FIVE, "away")},
        date_windows=["20260821-20260821"],
    )
    assert "home_starter_ids" in out[0]
    assert "away_starter_ids" not in out[0], "an unconfirmed side must not be written"
