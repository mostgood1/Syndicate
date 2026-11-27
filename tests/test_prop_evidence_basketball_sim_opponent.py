"""The MATCHUP layer resolves the opponent from the sim GAME when the sim's player row carries none (todo #862).

The NBA engine's `cards_sim_detail` player rows have no `team` / `opponent` (every NBA file 10-03..11-27, read on the
fleet 2026-11-27); the WNBA engine's rows do, and so does the production-sliced WNBA fixture the rest of the basketball
evidence tests read. So those tests stayed green while every NBA player the sim found lost the whole layer: no opponent,
no meetings, no opposing-defence table. Once the 11-10..11-14 name join found most NBA players in the sim, NBA sheet rows
with 3+ meetings fell 348 -> 14, starving NBA Matchups (+20.6% [+4.0, +37.7] on 142 bets before) and NBA defender
matchups (the sheet row's opponent fell back to a full team name `defender_matchups.team_code` cannot read).

These tests strip `team` / `opponent` from the real fixture's sim rows, which is the NBA shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.shared import prop_evidence
from syndicate.features.shared.prop_evidence import basketball
from syndicate.features.shared.prop_evidence.contract import Layer

ROOT = Path(__file__).parent / "fixtures" / "prop_evidence" / "root"

RIVERS_POINTS = {  # the same served row tests/test_prop_evidence_basketball.py uses (Rivers plays for CON, at ATL)
    "sport": "wnba", "event_id": "0fd1d4ee6d6e720e030e8cefb6a5a591", "market": "player_points",
    "player_name": "Saniya Rivers", "line": 9.5, "side": "over", "segment": "full",
    "home_team": "Atlanta Dream", "away_team": "Connecticut Sun", "commence_time": "2026-09-17T23:30:00Z",
    "kind": "prop", "projection": None,
}
AUSTIN_POINTS_UNDER = {  # Austin plays for CHI's opponent WAS, away at CHI
    "sport": "wnba", "event_id": "e1345bc3242e9236f8524205bb759ad3", "market": "player_points",
    "player_name": "Shakira Austin", "line": 17.5, "side": "under", "segment": "full",
    "home_team": "Chicago Sky", "away_team": "Washington Mystics", "commence_time": "2026-09-18T00:00:00Z",
    "kind": "prop", "projection": None,
}


@pytest.fixture(autouse=True)
def _data_root(monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(ROOT))


@pytest.fixture
def nba_shaped_sim(monkeypatch):
    """`_find_player` as production NBA returns it: the player row without `team` / `opponent`."""
    real = basketball._find_player
    seen: list[tuple] = []

    def stripped(sport, subject):
        found = real(sport, subject)
        if found is None:
            return None
        player = {k: v for k, v in found[0].items() if k not in ("team", "opponent")}
        seen.append((found[1], found[2]))
        return (player, *found[1:])

    monkeypatch.setattr(basketball, "_find_player", stripped)
    return seen


def _matchup(row):
    evidence = prop_evidence.build_prop_evidence(row, selected_date="2026-09-17")
    return evidence.layers.get(Layer.MATCHUP)


@pytest.mark.parametrize("row", [RIVERS_POINTS, AUSTIN_POINTS_UNDER], ids=["away-player", "home-player"])
def test_a_sim_row_without_an_opponent_takes_the_games_other_tricode(nba_shaped_sim, row):
    layer = _matchup(row)
    assert nba_shaped_sim, "the sim path must run: the fixture's player is in cards_sim_detail"
    game, side = nba_shaped_sim[-1]
    other = game["away_tri"] if side == "home" else game["home_tri"]
    assert layer is not None and layer.filled, layer
    assert layer.facts["opponent"] == other


@pytest.mark.parametrize("row", [RIVERS_POINTS, AUSTIN_POINTS_UNDER], ids=["away-player", "home-player"])
def test_the_meetings_and_the_opposing_defence_come_back(nba_shaped_sim, row):
    facts = _matchup(row).facts
    vs = facts.get("vs_opponent") or {}
    assert vs.get("games", 0) >= 1 and vs.get("values"), facts
    assert facts.get("opponent_advanced"), "the opposing-defence table needs the opponent too"


def test_same_answer_as_a_sim_row_that_names_its_opponent(nba_shaped_sim, monkeypatch):
    """The WNBA shape (opponent on the row) and the NBA shape (opponent only on the game) give the same facts."""
    nba_shape = _matchup(RIVERS_POINTS).facts
    monkeypatch.undo()
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(ROOT))
    wnba_shape = _matchup(RIVERS_POINTS).facts
    assert nba_shape == wnba_shape


def test_the_row_own_opponent_still_wins_over_the_game(monkeypatch):
    """A row that names its opponent keeps it: the game is only the fallback (the WNBA engine's rows)."""
    real = basketball._find_player

    def renamed(sport, subject):
        found = real(sport, subject)
        game = {**found[1], "home_tri": "XXX", "away_tri": "YYY"}
        return (found[0], game, *found[2:])

    monkeypatch.setattr(basketball, "_find_player", renamed)
    assert _matchup(RIVERS_POINTS).facts["opponent"] == "ATL"


def test_a_sim_row_from_another_game_does_not_lend_its_opponent(monkeypatch):
    """`_find_player` also reads the tip's UTC-date file, which can hold the team's NEXT game: measured on the fleet
    replay 2026-11-27, 11-10 Josh Hart (MIL @ NYK) was found in the 11-11 file vs CLE, and the game's tricodes would
    have shown "vs CLE". A sim game that is not this prop's two teams is ignored, and the box path decides."""
    real = basketball._find_player

    def next_game(sport, subject):
        found = real(sport, subject)
        player = {k: v for k, v in found[0].items() if k not in ("team", "opponent")}
        game = {**found[1], "home_tri": "CHI", "away_tri": "WAS"}      # a real WNBA pair, but not ATL vs CON
        return (player, game, *found[2:])

    monkeypatch.setattr(basketball, "_find_player", next_game)
    facts = _matchup(RIVERS_POINTS).facts
    assert facts["opponent"] == "ATL", facts                        # the box path's answer, as with no sim row at all


def test_unknown_game_is_not_this_game():
    class S:  # the three fields the check reads
        sport, home_team, away_team = "nba", "Milwaukee Bucks", "New York Knicks"
    assert basketball._sim_game_is_this_game(S, {"home_tri": "NYK", "away_tri": "MIL"}) is True
    assert basketball._sim_game_is_this_game(S, {"home_tri": "NYK", "away_tri": "CLE"}) is False
    assert basketball._sim_game_is_this_game(S, {"home_tri": "NYK"}) is False
    assert basketball._sim_game_is_this_game(S, None) is False
