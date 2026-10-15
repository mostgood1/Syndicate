"""Confirmed starters filed under another club, or under a comma-joined label (lane soccer-starter-club-move, 2026-10-15).

Measured 10-09..10-12 under the production env, 2,222 confirmed starters: production's exact-team grouping resolved
2,132; filing comma-joined rows under every club they name 2,156; plus within-league club moves 2,164 (8 moves, all
hand-checked: Galarza Atlanta -> Inter Miami, Padelford Minnesota -> Red Bulls, ...).
"""
from __future__ import annotations

from syndicate.features.soccer.features import lineups as L


def _row(pid, name, team):
    return {"player_id": pid, "player_name": name, "team": team}


def test_a_starter_under_another_club_moves_to_the_club_that_started_them():
    galarza = _row("asa_1", "Matías Galarza", "Atlanta United FC")
    pool = [galarza, _row("asa_2", "Somebody Else", "Atlanta United FC")]
    side = [_row("asa_3", "Lionel Messi", "Inter Miami CF")]
    moved = L._move_starters_from_other_clubs("mls", {"matias galarza"}, {}, "Inter Miami CF", side, pool)
    assert moved == {"asa_1"}
    assert galarza["team"] == "Inter Miami CF" and galarza in side and galarza not in pool


def test_two_candidates_elsewhere_move_nobody():
    pool = [_row("asa_1", "Matías Galarza", "Atlanta United FC"), _row("asa_9", "Matias Galarza", "Austin FC")]
    side = []
    assert L._move_starters_from_other_clubs("mls", {"matias galarza"}, {}, "Inter Miami CF", side, pool) == set()
    assert {r["team"] for r in pool} == {"Atlanta United FC", "Austin FC"}


def test_a_one_word_name_never_moves():
    """FC Dallas' goalkeeper 'Daniel' must not pull San Jose's 'Daniel' row."""
    pool = [_row("asa_1", "Daniel", "San Jose Earthquakes")]
    assert L._move_starters_from_other_clubs("mls", {"daniel"}, {}, "FC Dallas", [], pool) == set()


def test_a_comma_joined_row_is_never_moved():
    pool = [_row("u_1", "Achraf Hakimi", "Paris Saint Germain,Rennes")]
    assert L._move_starters_from_other_clubs("ligue_1", {"achraf hakimi"}, {}, "Lens", [], pool) == set()


def test_off_is_not_on_without_the_pool_nothing_moves(monkeypatch):
    """Reachability: the pass only runs when the caller hands it the other clubs' rows."""
    calls = []
    monkeypatch.setattr(L, "_move_starters_from_other_clubs", lambda *a, **k: calls.append(a) or set())
    monkeypatch.setattr(L, "find_event_for_fixture", lambda *a, **k: {"event_id": "e1"})
    monkeypatch.setattr(L, "fetch_match_summary", lambda *a, **k: {})
    starters = [{"side": side, "starter": True, "player_name": f"{side} {i} x", "player_id": f"{side}{i}"}
                for side in ("home", "away") for i in range(11)]
    monkeypatch.setattr(L, "extract_match_player_rows", lambda *a, **k: starters)
    L.fetch_confirmed_starter_ids("mls", home_team="A", away_team="B", home_player_rows=[], away_player_rows=[],
                                  events=[{}])
    assert calls == []
    L.fetch_confirmed_starter_ids("mls", home_team="A", away_team="B", home_player_rows=[], away_player_rows=[],
                                  events=[{}], other_club_rows=[_row("x", "y z", "C")])
    assert len(calls) == 2


def test_comma_joined_labels_are_filed_under_every_club_they_name(monkeypatch):
    seen = {}
    monkeypatch.setattr(L, "fetch_events", lambda *a, **k: [])

    def capture(league, **kw):
        seen["home"] = [r["player_name"] for r in kw["home_player_rows"]]
        return None

    monkeypatch.setattr(L, "fetch_confirmed_starter_ids", capture)
    rows_by_team = {"Paris Saint Germain": [_row("u_2", "Ousmane Dembele", "Paris Saint Germain")],
                    "Paris Saint Germain,Rennes": [_row("u_1", "Achraf Hakimi", "Paris Saint Germain,Rennes")],
                    "Lens": [_row("u_3", "Lens Player", "Lens")]}
    L.attach_confirmed_starters([{"home_team": "Paris Saint Germain", "away_team": "Lens"}], league="ligue_1",
                                player_rows_by_team=rows_by_team, date_windows=["20261012"])
    assert set(seen["home"]) == {"Ousmane Dembele", "Achraf Hakimi"}
