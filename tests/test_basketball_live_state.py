"""Lane `basketball-native-live-state` (P2): the typed LiveGameState and its disk capture."""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import basketball_live_state as live
from tests.basketball_pbp_fixtures import Game


def _state(game: Game, league: str = "nba"):
    return live.build_live_game_state(game.summary(), league, date="2026-01-15", built_at="t")


def test_state_core_fields_mid_game():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").rebound(1, "10:40", "home", "h2").turnover(1, "10:20", "home", "h3")
    g.sub(1, "9:00", "away", "a6", "a5").shot(1, "8:30", "away", "a1", pts=3).timeout(1, "8:30", "home")
    st = _state(g)
    assert (st.period, st.clock_left, st.elapsed) == (1, 510.0, 210.0)
    assert (st.home.score, st.away.score) == (2, 3)
    assert st.status_state == "in" and not st.completed
    assert st.away.on_floor == tuple(sorted(["a1", "a2", "a3", "a4", "a6"]))
    assert st.home.timeouts_used == 1 and st.home.timeouts_remaining is None  # never guessed from a rule
    assert st.possession_side == "home" and st.possession_basis == "made_fg"  # away just scored
    assert st.home.fga == 1 and st.home.tov == 1 and st.away.fga == 1
    a6 = next(p for p in st.players if p.player_id == "a6")
    a5 = next(p for p in st.players if p.player_id == "a5")
    assert a6.on_floor and a6.current_stint_sec == pytest.approx(30.0)
    assert not a5.on_floor and a5.current_rest_sec == pytest.approx(30.0) and a5.seconds_played == pytest.approx(180.0)
    assert any(s.open for s in st.stints)


def test_nba_bonus_after_four_fouls_and_last_two_minute_rule():
    g = Game("nba", state="in")
    for i, clock in enumerate(("11:00", "10:00", "9:00", "8:00")):
        g.foul(1, clock, "away", f"a{i + 1}")
    st = _state(g)
    assert st.away.team_fouls_period == 4 and st.home.shooting_bonus == "bonus" and st.away.fouls_to_give == 0
    g2 = Game("nba", state="in")
    g2.foul(2, "5:00", "away", "a1").foul(2, "1:30", "away", "a2")
    st2 = _state(g2)
    assert st2.away.team_fouls_period == 2 and st2.home.shooting_bonus == "bonus"  # 2nd foul inside the last 2:00
    g3 = Game("nba", state="in")
    g3.foul(1, "11:00", "away", "a1").foul(1, "10:00", "away", "a1", "Offensive Foul")
    assert _state(g3).away.team_fouls_period == 1  # NBA: an offensive foul is not a team foul


def test_ncaab_half_fouls_one_and_one_then_double_bonus():
    g = Game("ncaab", state="in")
    for i in range(6):
        g.foul(1, f"{19 - i}:00", "away", "a1")
    st = _state(g, "ncaab")
    assert st.away.team_fouls_period == 6 and st.home.shooting_bonus == "bonus"
    for i in range(3):
        g.foul(1, f"{10 - i}:00", "away", "a2", "Offensive Foul")  # NCAAB counts offensive fouls
    st = _state(g, "ncaab")
    assert st.away.team_fouls_period == 9 and st.home.shooting_bonus == "double_bonus"
    g.foul(2, "19:00", "away", "a3")
    assert _state(g, "ncaab").away.team_fouls_period == 1  # reset at the half


def test_player_foul_out_by_league():
    g = Game("ncaab", state="in")
    for i in range(5):
        g.foul(1, f"{19 - i}:00", "home", "h1")
    st = _state(g, "ncaab")
    h1 = next(p for p in st.players if p.player_id == "h1")
    assert h1.pf == 5 and h1.fouled_out


def test_recent_window_run_drought_and_pace():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "away", "a1")
    g.shot(1, "10:00", "home", "h1", pts=3).shot(1, "9:30", "home", "h2").shot(1, "9:00", "home", "h3")
    st = _state(g)
    w180 = next(w for w in st.recent if w.window_sec == 180)
    assert w180.current_run == {"side": "home", "points": 7}
    assert w180.seconds_since_score["away"] == pytest.approx(120.0) and w180.seconds_since_score["home"] == 0.0
    assert w180.points == {"home": 7, "away": 2}
    assert w180.pace_per_game is not None and w180.pace_per_game > 0


def test_write_appends_a_tick_only_when_the_game_advanced(tmp_path):
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1")
    first = live.write_live_state(_state(g), out_dir=tmp_path)
    again = live.write_live_state(_state(g), out_dir=tmp_path)
    g.shot(1, "10:30", "away", "a1")
    third = live.write_live_state(_state(g), out_dir=tmp_path)
    assert (first["advanced"], again["advanced"], third["advanced"]) == (True, False, True)
    ticks = (tmp_path / "999.ticks.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(t)["score"] for t in ticks] == [[2, 0], [2, 2]]
    saved = json.loads((tmp_path / "999.json").read_text(encoding="utf-8"))
    assert saved["home"]["score"] == 2 and saved["schema_version"] == live.SCHEMA_VERSION


def test_write_refuses_an_oversize_state(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "MAX_STATE_BYTES", 100)
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1")
    with pytest.raises(ValueError, match="refusing"):
        live.write_live_state(_state(g), out_dir=tmp_path)
    assert not (tmp_path / "999.json").exists()


def test_capture_skips_pregame_and_already_final_games(tmp_path):
    g_live = Game("nba", state="in")
    g_live.shot(1, "11:00", "home", "h1")
    board = {"events": [
        {"id": "999", "season": {"year": 2027, "type": 1}, "competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]},
        {"id": "555", "season": {"year": 2027, "type": 1}, "competitions": [{"status": {"type": {"state": "pre"}}, "competitors": []}]},
    ]}
    fetched = []

    def summary(league, event_id):
        fetched.append(event_id)
        return g_live.summary()

    out = live.capture_live_states("nba", "2026-10-09", fetch_scoreboard=lambda *_: board, fetch_summary=summary, out_dir=tmp_path)
    assert fetched == ["999"] and out[0]["advanced"] and out[0]["score"] == [2, 0]


def test_score_prefers_espn_header_and_keeps_the_play_sum():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1")
    st = live.build_live_game_state(g.summary(official=(4, 0)), "nba", date="2026-01-15", built_at="t")
    assert (st.home.score, st.score_source, st.pbp_score["home"]) == (4, "official", 2)
