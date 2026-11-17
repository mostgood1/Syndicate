"""`commit_portfolio` refuses an in-play row on a game a key player has left (lane live-player-exit-gate, #814).

The refusal reads the same snapshot as the board's gamelines and the in-play entry hold
(`live_player_exit_hold.ExitHold`): a game line on a failed game is refused `key_player_out`; a prop only when
its own player is the one out. Pregame rows, and `off` / `pass` / `unknown` verdicts, never refuse.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import live_player_exit_hold as H
from syndicate.features.shared import live_player_status as lps
from syndicate.features.shared import portfolio_commit as PC

HOME, AWAY = "Detroit Lions", "New England Patriots"
OUT = {"team": "NE", "player": "Drake Maye", "reason": "injury", "key": True, "modelled": False}


def _snap(players_out):
    return {"games": [{"home_name": HOME, "away_name": AWAY, "playersOut": players_out}]}


@pytest.fixture
def hold(monkeypatch):
    def use(snapshot):
        monkeypatch.setattr(PC, "_EXIT_HOLD", H.ExitHold(read_fn=lambda s: snapshot, env={}))
    return use


def _row(**kw):
    row = {"sport": "nfl", "home_team": HOME, "away_team": AWAY, "kind": "game", "market": "h2h",
           "market_state": "live", "selection": HOME, "price": -150}
    row.update(kw)
    return row


def test_a_game_line_on_a_refused_game_is_refused(hold):
    hold(_snap([OUT]))
    assert PC._refuses_key_player_out(_row()) is True


def test_only_the_out_players_props_are_refused(hold):
    hold(_snap([OUT]))
    assert PC._refuses_key_player_out(_row(kind="prop", market="player_pass_yds", player_name="Drake Maye")) is True
    assert PC._refuses_key_player_out(_row(kind="prop", market="player_rush_yds", player_name="Rhamondre Stevenson")) is False


@pytest.mark.parametrize("snapshot", [_snap([]), _snap([dict(OUT, modelled=True)]), {"games": []}, None])
def test_pass_unknown_and_a_modelled_exit_never_refuse(hold, snapshot):
    hold(snapshot)
    assert PC._refuses_key_player_out(_row()) is False


def test_a_pregame_row_is_never_read(monkeypatch):
    class Boom:
        def check(self, *a):
            raise AssertionError("pregame rows must not read the hold")
    monkeypatch.setattr(PC, "_EXIT_HOLD", Boom())
    assert PC._refuses_key_player_out(_row(market_state="pregame", game={"state": "pregame"})) is False


def test_off_ne_on(hold, monkeypatch):
    hold(_snap([OUT]))
    on = PC._refuses_key_player_out(_row())
    monkeypatch.setattr(PC, "_EXIT_HOLD", H.ExitHold(read_fn=lambda s: _snap([OUT]), env={lps.ENV_SWITCH: "off"}))
    assert on is True and PC._refuses_key_player_out(_row()) is False


def test_commit_portfolio_counts_the_refusal_by_name(hold, monkeypatch):
    """Reachability: the production call site in `commit_portfolio`'s row loop."""
    monkeypatch.setattr("syndicate.features.shared.request_path_guard.refuse_if_compute_in_request_path",
                        lambda *_: None)
    monkeypatch.setattr(PC, "refuse_if_compute_in_request_path", lambda *_: None)
    hold(_snap([OUT]))
    refused = PC.commit_portfolio([_row()], selected_date="2026-11-16")
    assert refused["refusals"].get("key_player_out") == 1
    assert refused["refusals_by_sport"]["key_player_out"] == {"nfl": 1}
    hold(_snap([]))
    priced = PC.commit_portfolio([_row()], selected_date="2026-11-16")
    assert "key_player_out" not in priced["refusals"]
