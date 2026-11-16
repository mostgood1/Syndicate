"""WNBA live lens refuses a game a starter has left, and refuses an out player's live props (lane live-player-exit-gate).

The in-season WNBA path is the linear lens (`wnba/cards.py _build_wnba_game_lens`) published through
`wnba/live_lens.build_live_lens_snapshot`; it models NO exit, so every key exit (ejection, foul-out, in-game
injury) re-stamps the game's lanes off `live_projection`, which is the only stamp the board's WNBA gameline
index accepts. Exits are read from one ESPN summary per live game (`live_player_exit_tick.collect_exit_statuses`).
Synthetic ESPN summaries: `tests/basketball_pbp_fixtures.Game("wnba")`.
"""

from __future__ import annotations

from unittest.mock import patch

from syndicate.features.shared import live_player_exit_hold as H
from syndicate.features.shared import live_player_exit_tick as exit_tick
from syndicate.features.shared import live_player_status as lps
from syndicate.features.wnba import live_lens as wl
from tests.basketball_pbp_fixtures import Game

EVENT = "401900001"
HOME, AWAY = "Las Vegas Aces", "Seattle Storm"


def _summary(ejected: str | None = None, starter: bool = True):
    g = Game("wnba", state="in")
    g.shot(1, "9:00", "home", "h1").shot(1, "8:30", "away", "a1", pts=3).foul(1, "7:00", "home", "h2")
    g.end_period(1)
    g.shot(2, "9:40", "home", "h1")
    s = g.summary()
    if ejected:
        for team in s["boxscore"]["players"]:
            for cat in team["statistics"]:
                for entry in cat["athletes"]:
                    if entry["athlete"]["displayName"] == ejected:
                        entry["ejected"] = True
                        entry["starter"] = starter
    return s


def _game(in_progress: bool = True):
    lane = {"lane": "full", "source": "live_projection", "modelHomeWinProb": 0.61,
            "projection": {"total": 160.5, "homeMargin": 4.0}}
    return {"event_id": EVENT, "home": HOME, "away": AWAY, "home_name": HOME, "away_name": AWAY,
            "status": {"period": 2, "clock": "5:00", "in_progress": in_progress},
            "live_state": {"in_progress": in_progress}, "gameLens": [lane]}


def _collect(summary):
    calls: list[str] = []

    def collect(sport, rows, log_tag=None):
        def fetch(event_id):
            calls.append(event_id)
            return summary
        return exit_tick.collect_exit_statuses(sport, rows, fetch=fetch, log_tag=log_tag)
    return collect, calls


def test_a_starter_ejected_re_stamps_the_lanes_and_publishes_who_is_out():
    games = [_game()]
    original_lane = games[0]["gameLens"][0]
    collect, calls = _collect(_summary(ejected="H1"))
    tally = wl._apply_player_exits(games, collect=collect)
    lane = games[0]["gameLens"][0]
    assert calls == [EVENT]
    assert lane["source"] == wl.EXIT_REFUSED_LENS_SOURCE and lane["refusedSource"] == "live_projection"
    assert lane["liveRefusal"] == "key_player_out" and "H1:ejection" in lane["liveRefusalDetail"]
    assert original_lane["source"] == "live_projection"  # the cards context's own lane is not mutated
    assert [(p["player"], p["reason"], p["key"]) for p in games[0]["playersOut"]] == [("H1", "ejection", True)]
    assert tally["read"] == 1 and tally["key_players_out"] == 1 and tally["refused_games"] == 1


def test_off_ne_on(monkeypatch):
    collect, _ = _collect(_summary(ejected="H1"))
    on = [_game()]
    wl._apply_player_exits(on, collect=collect)
    monkeypatch.setenv(lps.ENV_SWITCH, "off")
    off = [_game()]
    tally = wl._apply_player_exits(off, collect=collect)
    assert on[0]["gameLens"][0]["source"] == wl.EXIT_REFUSED_LENS_SOURCE
    assert off[0]["gameLens"][0]["source"] == "live_projection" and "playersOut" not in off[0]
    assert tally.get("enabled") is False


def test_a_clean_game_keeps_its_lane_and_publishes_an_empty_exit_list():
    games = [_game()]
    collect, _ = _collect(_summary())
    tally = wl._apply_player_exits(games, collect=collect)
    assert games[0]["gameLens"][0]["source"] == "live_projection"
    assert games[0]["playersOut"] == [] and tally["refused_games"] == 0


def test_a_game_not_in_progress_is_not_fetched():
    games = [_game(in_progress=False)]
    collect, calls = _collect(_summary(ejected="H1"))
    tally = wl._apply_player_exits(games, collect=collect)
    assert calls == [] and "playersOut" not in games[0] and tally["live_games"] == 0


def test_an_unreadable_summary_gives_no_exit_list_and_is_counted():
    games = [_game()]
    collect, _ = _collect(None)
    tally = wl._apply_player_exits(games, collect=collect)
    assert "playersOut" not in games[0] and tally["unreadable"] == 1
    assert games[0]["gameLens"][0]["source"] == "live_projection"  # unknown is not refused (pre-gate behaviour)


def test_a_bench_player_out_keeps_the_game_but_refuses_his_props():
    games = [_game()]
    collect, _ = _collect(_summary(ejected="H1", starter=False))
    wl._apply_player_exits(games, collect=collect)
    assert games[0]["gameLens"][0]["source"] == "live_projection"
    assert [(p["player"], p["key"]) for p in games[0]["playersOut"]] == [("H1", False)]
    rows = [{"playerName": "H1", "prop": "player_points", "line": 10.5, "liveModelProbOver": 0.55},
            {"playerName": "H2", "prop": "player_points", "line": 8.5, "liveModelProbOver": 0.48}]
    assert wl._refuse_out_player_props(games[0], rows) == 1
    assert rows[0]["liveModelProbOver"] is None and rows[0]["notPricedReason"] == "player_out"
    assert rows[1]["liveModelProbOver"] == 0.48


def test_attach_live_props_refuses_the_out_player_and_counts_it():
    game = {"event_id": EVENT, "status": {"period": 2, "clock": "5:00"},
            "sim": {"players": {"home": [{"player_name": "Paige Bueckers", "min_mean": 30.0, "pts_mean": 18.0}],
                                "away": []}},
            "shared_prop_rows": [{"name": "Paige Bueckers", "market": "pts", "line": 17.5}],
            "playersOut": [{"player": "Paige Bueckers", "reason": "ejection", "key": True}]}
    record = {"payload": {"games": [{"event_id": EVENT, "players": [
        {"player": "Paige Bueckers", "team_tri": "DAL", "mp": "9", "pts": 6.0, "reb": 2.0, "ast": 1.0,
         "threes_made": 1.0}]}]}}
    with patch("syndicate.features.shared.refresh_state_store.read_json_file", return_value=record):
        wl._attach_live_props([game], "2026-08-20")
    rows = game["liveProps"]
    assert rows and all(r["liveModelProbOver"] is None and r["notPricedReason"] == "player_out" for r in rows)
    assert game["livePropsCoverage"]["player_out_refused"] == len(rows)


def test_the_LIVE_GAMELINE_index_drops_the_game_and_the_entry_hold_fails():
    from syndicate.features.shared.live_gameline_join import build_live_gameline_index, lens_sources_for_sport

    def index(games):
        return build_live_gameline_index({"games": games}, sources=lens_sources_for_sport("wnba"), sport="wnba")

    clean = [_game()]
    collect, _ = _collect(_summary())
    wl._apply_player_exits(clean, collect=collect)
    refused = [_game()]
    collect, _ = _collect(_summary(ejected="H1"))
    wl._apply_player_exits(refused, collect=collect)
    assert len(index(clean)) >= 1 and len(index(refused)) == 0
    out = H.ExitHold(read_fn=lambda sport: {"games": refused}, env={}).check("wnba", HOME, AWAY)
    # The synthetic box carries no team abbreviation (a real ESPN box does), hence the empty team.
    assert out["verdict"] == "fail" and out["players"] == [":H1:ejection"]
    assert H.ExitHold(read_fn=lambda sport: {"games": clean}, env={}).check("wnba", AWAY, HOME)["verdict"] == "pass"


def test_wnba_publishes_to_the_hold():
    assert H.PUBLISHING_SPORTS["wnba"] == wl.live_lens_snapshot_path().name
