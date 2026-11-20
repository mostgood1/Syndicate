"""live_player_status: who has left a live game, from real ESPN summary payloads.

Fixtures (tests/fixtures/live_player_status/, trimmed ESPN summary payloads):
  nfl_401873053_halftime_2026-11-15  NE @ DET at halftime: Drake Maye hurt 14:41:43Z, DeVito in
  nba_401909981_final                DAL @ CLE final: no in-game exit (Allen DNP pregame)
  nhl_401892708_final_goaliechange   WPG @ CHI final: Skinner pulled after 20:00, Daws in
  soccer_401879244_final_redcard     BRE @ BHA final: Igor Thiago red card 23'
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from syndicate.features.shared import live_player_status as lps

FIX = Path(__file__).parent / "fixtures" / "live_player_status"


def _load(name: str) -> dict:
    with gzip.open(FIX / name, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _set_live(summary: dict) -> dict:
    s = copy.deepcopy(summary)
    s["header"]["competitions"][0]["status"]["type"]["state"] = "in"
    return s


@pytest.fixture
def nfl():
    return _load("nfl_401873053_halftime_2026-11-15.json.gz")


# --------------------------------------------------------------- reachability first


def test_gate_switch_absent_is_on_and_off_is_off():
    assert lps.gate_enabled({}) is True
    assert lps.gate_enabled({lps.ENV_SWITCH: "on"}) is True
    for off in ("off", "0", "false", "no", "OFF"):
        assert lps.gate_enabled({lps.ENV_SWITCH: off}) is False


def test_off_ne_on_the_real_exit_changes_the_gameline_verdict(nfl, monkeypatch):
    """The same game with and without the exit in its feed must differ."""
    on = lps.exits_from_espn_summary("nfl", nfl)
    stripped = copy.deepcopy(nfl)
    stripped["injuries"] = []
    for drive in stripped["drives"]["previous"]:
        for play in drive["plays"]:
            play["text"] = play["text"].replace("NE-D.Maye was injured during the play.", "")
    # With the injury text gone, the backup's snaps still give him away (the replacement rule) ...
    assert lps.gameline_refusal(lps.exits_from_espn_summary("nfl", stripped))["players"] == ["NE:Drake Maye:replaced"]
    # ... so a truly clean game also turns that rule off.
    monkeypatch.setattr(lps, "REPLACED_AFTER_SNAPS", 10**6)
    off = lps.exits_from_espn_summary("nfl", stripped)
    assert lps.gameline_refusal(on) is not None
    assert lps.gameline_refusal(off) is None


# --------------------------------------------------------------- football


def test_nfl_maye_exit_is_detected_from_the_play_not_the_late_injury_stamp(nfl):
    st = lps.exits_from_espn_summary("nfl", nfl)
    assert st.in_progress
    maye = st.player_is_out("Drake Maye")
    assert maye is not None
    assert maye.key is True  # a quarterback
    assert maye.reason == "injured_in_play"
    assert maye.source == "pbp"
    assert maye.since == "2026-11-15T14:41:43Z"  # ESPN's injuries list said Out only at 15:43Z
    assert st.player_is_out("Tommy DeVito") is None
    assert st.home_team == "Detroit Lions" and st.away_team == "New England Patriots"
    ref = lps.gameline_refusal(st)
    assert ref["reason"] == lps.REASON_KEY_PLAYER_OUT
    assert ref["players"] == ["NE:Drake Maye:injured_in_play"]


def test_nfl_player_who_returned_is_not_out(nfl):
    # M.Moses: injured 1Q 6:08, "has returned to the game" 2Q 9:44
    st = lps.exits_from_espn_summary("nfl", nfl)
    assert all("Moses" not in p.player for p in st.players_out)


def test_nfl_non_qb_exit_refuses_props_not_gamelines(nfl):
    st = lps.exits_from_espn_summary("nfl", nfl)
    spillane = st.player_is_out("Robert Spillane")
    assert spillane is not None and spillane.key is False
    assert lps.prop_refusal(st, "Robert Spillane")["reason"] == lps.REASON_PLAYER_OUT
    assert lps.prop_refusal(st, "Drake Maye")["reason"] == lps.REASON_KEY_PLAYER_OUT
    assert lps.prop_refusal(st, "Jared Goff") is None


def test_nfl_qb_who_reappears_lifts_the_gate(nfl):
    s = copy.deepcopy(nfl)
    last = s["drives"]["previous"][-1]["plays"][-1]
    s["drives"]["previous"][-1]["plays"].append(
        {**last, "id": "back1", "sequenceNumber": "999999", "wallclock": "2026-11-15T16:30:00Z",
         "text": "(Shotgun) D.Maye pass short right to H.Henry to NE 40 for 6 yards (B.Branch)."}
    )
    st = lps.exits_from_espn_summary("nfl", s)
    assert st.player_is_out("Drake Maye") is None
    assert lps.gameline_refusal(st) is None


def test_injury_stamped_before_kickoff_is_pregame_not_an_exit(nfl):
    st = lps.exits_from_espn_summary("nfl", nfl)
    # Ben Brown: Out 13:03Z, kickoff 14:30Z -> the pregame report, not this lane's
    assert st.player_is_out("Ben Brown") is None


def test_pregame_or_final_payload_never_refuses(nfl):
    for state in ("pre", "post"):
        s = copy.deepcopy(nfl)
        s["header"]["competitions"][0]["status"]["type"]["state"] = state
        st = lps.exits_from_espn_summary("nfl", s)
        assert st.players_out == ()
        assert lps.gameline_refusal(st) is None
        assert lps.prop_refusal(st, "Drake Maye") is None


# --------------------------------------------------------------- basketball


def test_nba_game_without_an_exit_refuses_nothing():
    st = lps.exits_from_espn_summary("nba", _set_live(_load("nba_401909981_final.json.gz")))
    assert st.players_out == ()  # Jarrett Allen was a pregame DNP, not an exit
    assert lps.gameline_refusal(st) is None


def _first_starter(summary):
    team = summary["boxscore"]["players"][0]
    cat = team["statistics"][0]
    entry = next(a for a in cat["athletes"] if a.get("starter"))
    return cat, entry


@pytest.mark.parametrize("sport,limit", [("nba", 6), ("wnba", 6), ("ncaab", 5), ("wncaab", 5)])
def test_basketball_foul_out_at_the_league_limit(sport, limit):
    s = _set_live(_load("nba_401909981_final.json.gz"))
    cat, entry = _first_starter(s)
    pf = cat["labels"].index("PF")
    for team in s["boxscore"]["players"]:  # the real final has a 5-foul player
        for a in team["statistics"][0]["athletes"]:
            if len(a.get("stats") or []) > pf:
                a["stats"][pf] = "0"
    entry["stats"][pf] = str(limit - 1)
    assert lps.exits_from_espn_summary(sport, s).players_out == ()
    entry["stats"][pf] = str(limit)
    st = lps.exits_from_espn_summary(sport, s)
    (p,) = st.players_out
    assert p.reason == "foul_out" and p.key is True
    assert lps.gameline_refusal(st)["reason"] == lps.REASON_KEY_PLAYER_OUT


def test_basketball_ejection_of_a_bench_player_refuses_his_props_only():
    s = _set_live(_load("nba_401909981_final.json.gz"))
    cat = s["boxscore"]["players"][0]["statistics"][0]
    bench = next(a for a in cat["athletes"] if not a.get("starter") and not a.get("didNotPlay"))
    bench["ejected"] = True
    st = lps.exits_from_espn_summary("nba", s)
    (p,) = st.players_out
    assert p.reason == "ejection" and p.key is False
    assert lps.gameline_refusal(st) is None
    assert lps.prop_refusal(st, bench["athlete"]["displayName"])["reason"] == lps.REASON_PLAYER_OUT


def test_basketball_in_game_out_ruling_after_tip():
    s = _set_live(_load("nba_401909981_final.json.gz"))
    _cat, starter = _first_starter(s)
    tip = s["header"]["competitions"][0]["date"]
    team_abbr = s["boxscore"]["players"][0]["team"]["abbreviation"]
    s["injuries"] = [{"team": {"abbreviation": team_abbr}, "injuries": [
        {"athlete": starter["athlete"], "status": "Out", "date": "2099-01-01T00:00Z"},
    ]}]
    st = lps.exits_from_espn_summary("nba", s)
    assert st.player_is_out(starter["athlete"]["displayName"]).reason == "injury"
    s["injuries"][0]["injuries"][0]["date"] = "2000-01-01T00:00Z"  # before tip: pregame
    assert lps.exits_from_espn_summary("nba", s).players_out == ()
    assert tip  # the fixture carries a start time


# --------------------------------------------------------------- hockey


def test_nhl_goalie_change_is_a_key_exit():
    st = lps.exits_from_espn_summary("nhl", _set_live(_load("nhl_401892708_final_goaliechange.json.gz")))
    names = {p.player for p in st.players_out}
    assert names == {"Stuart Skinner", "Nico Daws"}
    assert all(p.key and p.reason == "goalie_change" and p.team == "WPG" for p in st.players_out)
    assert lps.gameline_refusal(st)["reason"] == lps.REASON_KEY_PLAYER_OUT


def test_nhl_one_goalie_all_game_is_no_exit():
    s = _set_live(_load("nhl_401892708_final_goaliechange.json.gz"))
    for team in s["boxscore"]["players"]:
        for cat in team["statistics"]:
            if "goal" in cat["name"].lower():
                cat["athletes"] = cat["athletes"][:1]
    assert lps.exits_from_espn_summary("nhl", s).players_out == ()


# --------------------------------------------------------------- soccer


def test_soccer_red_card_is_a_key_exit():
    st = lps.exits_from_espn_summary("soccer", _set_live(_load("soccer_401879244_final_redcard.json.gz")))
    (p,) = st.players_out
    assert (p.player, p.reason, p.key, p.since) == ("Igor Thiago", "red_card", True, "23'")


def test_soccer_penalty_scored_is_not_a_red_card():
    """'Penalty - Scored' contains the substring 'red' -- the type must match exactly."""
    s = _set_live(_load("soccer_401879244_final_redcard.json.gz"))
    s["keyEvents"] = [e for e in s["keyEvents"] if e["type"]["text"] != "Red Card"]
    assert any("red" in e["type"]["text"].lower() for e in s["keyEvents"])  # the trap is present
    assert lps.exits_from_espn_summary("soccer", s).players_out == ()


def test_soccer_starting_keeper_subbed_off_is_a_key_exit():
    s = _set_live(_load("soccer_401879244_final_redcard.json.gz"))
    s["keyEvents"] = []
    keeper = next(e for e in s["rosters"][0]["roster"]
                  if (e.get("position") or {}).get("abbreviation") == "G" and e.get("starter"))
    keeper["subbedOut"] = True
    (p,) = lps.exits_from_espn_summary("soccer", s).players_out
    assert p.reason == "keeper_change" and p.key


# --------------------------------------------------------------- misc


def test_unknown_sport_and_empty_payload_refuse_nothing():
    assert lps.exits_from_espn_summary("cricket", {"header": {}}).players_out == ()
    assert lps.exits_from_espn_summary("nfl", None).players_out == ()
    assert lps.gameline_refusal(None) is None


def test_name_normalisation_matches_board_spellings():
    assert lps.normalize_name("Jaime Jaquez Jr.") == lps.normalize_name("jaime jaquez")
    assert lps.normalize_name("Óscar Mingueza") == "oscar mingueza"


def test_to_dict_round_trips_the_published_shape(nfl):
    d = lps.exits_from_espn_summary("nfl", nfl).to_dict()
    assert d["game_id"] == "401873053" and d["home_team"] == "Detroit Lions"
    assert {"player", "team", "reason", "key", "source", "since"} <= set(d["players_out"][0])
    json.dumps(d)


# --------------------------------------------------------------- feed-survey corrections


def test_wnba_ejection_is_read_from_the_play_because_the_box_flag_lies():
    s = _set_live(_load("wnba_401856991_final_ejection.json.gz"))
    flags = [a.get("ejected") for t in s["boxscore"]["players"] for a in t["statistics"][0]["athletes"]
             if a["athlete"]["displayName"] == "Isabelle Harrison"]
    assert flags == [False]  # the trap: the boxscore flag never flipped
    st = lps.exits_from_espn_summary("wnba", s)
    p = st.player_is_out("Isabelle Harrison")
    assert p is not None and p.reason == "ejection" and p.source == "pbp"
    s["plays"] = [pl for pl in s["plays"] if pl["type"]["text"].lower() != "ejection"]
    assert lps.exits_from_espn_summary("wnba", s).player_is_out("Isabelle Harrison") is None


def _nhlapi():
    return _load("nhlapi_2025021309_final_goaliechange.json.gz")


def test_nhl_api_starter_pulled_is_a_key_exit():
    box = _nhlapi()
    box["gameState"] = "LIVE"
    st = lps.exits_from_nhl_boxscore(box)
    assert (st.home_team, st.away_team) == ("Utah Mammoth", "St. Louis Blues")
    (p,) = st.players_out
    assert (p.team, p.player, p.reason, p.key) == ("UTA", "K. Vejmelka", "goalie_change", True)
    assert lps.gameline_refusal(st)["reason"] == lps.REASON_KEY_PLAYER_OUT


def test_nhl_api_relief_goalie_without_ice_time_is_no_exit():
    box = _nhlapi()
    box["gameState"] = "LIVE"
    for side in ("homeTeam", "awayTeam"):
        for g in box["playerByGameStats"][side]["goalies"]:
            if not g.get("starter"):
                g["toi"] = "00:00"
    assert lps.exits_from_nhl_boxscore(box).players_out == ()


def test_nhl_api_final_or_pregame_never_refuses():
    for state in ("OFF", "FINAL", "FUT", "PRE"):
        box = _nhlapi()
        box["gameState"] = state
        assert lps.gameline_refusal(lps.exits_from_nhl_boxscore(box)) is None


# --------------------------------------------------------------- basketball off-floor signal (ESPN has no injury cue)
#   nba_401910012_final_murray_boyles_exit   WSH @ TOR 11-19: Murray-Boyles subbed out P1 7:06, never back (5 min)
#   wncaab_401918531_final_card_exit         UTC @ APSU 11-19: Ava Card subbed out P1 5:54, never back (4 min)


def _cut(summary: dict, period: int, clock: str) -> dict:
    """The live payload as of the first play at (period, clock): plays up to it, state 'in'."""
    s = _set_live(summary)
    plays = s["plays"]
    idx = next(i for i, p in enumerate(plays) if p["period"]["number"] == period and p["clock"]["displayValue"] == clock)
    s["plays"] = plays[: idx + 1]
    return s


@pytest.fixture
def mb():
    return _load("nba_401910012_final_murray_boyles_exit.json.gz")


@pytest.fixture
def card():
    return _load("wncaab_401918531_final_card_exit.json.gz")


def _off(status, who):
    hit = status.player_is_out(who)
    return hit if hit is not None and hit.reason == "off_floor" else None


def test_off_floor_switch_absent_is_off():
    assert lps.off_floor_enabled({}) is False
    assert lps.off_floor_enabled({lps.OFF_FLOOR_SWITCH: "on"}) is True
    assert lps.off_floor_enabled({lps.OFF_FLOOR_SWITCH: "off"}) is False


def test_off_ne_on_the_nba_off_floor_exit_changes_the_gameline_verdict(mb, monkeypatch):
    live = _cut(mb, 2, "3:24")  # ~16 game-min after he left
    monkeypatch.delenv(lps.OFF_FLOOR_SWITCH, raising=False)
    off = lps.exits_from_espn_summary("nba", live)
    monkeypatch.setenv(lps.OFF_FLOOR_SWITCH, "on")
    on = lps.exits_from_espn_summary("nba", live)
    assert _off(off, "Collin Murray-Boyles") is None
    hit = _off(on, "Collin Murray-Boyles")
    assert hit is not None and hit.key and hit.team == "TOR" and hit.source == "pbp"
    assert lps.gameline_refusal(off) is None or "Murray-Boyles" not in str(lps.gameline_refusal(off))
    ref = lps.gameline_refusal(on)
    assert ref["reason"] == lps.REASON_KEY_PLAYER_OUT and "TOR:Collin Murray-Boyles:off_floor" in ref["players"]
    assert lps.prop_refusal(on, "Collin Murray-Boyles")["reason"] == lps.REASON_KEY_PLAYER_OUT


def test_nba_off_floor_waits_n_minutes(mb, monkeypatch):
    monkeypatch.setenv(lps.OFF_FLOOR_SWITCH, "on")
    early = lps.exits_from_espn_summary("nba", _cut(mb, 1, "3:53"))  # ~3 game-min off: a normal rest
    assert _off(early, "Collin Murray-Boyles") is None


def test_college_off_floor_fires_k_minutes_into_the_second_half(card, monkeypatch):
    monkeypatch.setenv(lps.OFF_FLOOR_SWITCH, "on")
    # WNCAAB has no N rule: still off at the end of the first half is not a flag
    assert _off(lps.exits_from_espn_summary("wncaab", _cut(card, 2, "6:21")), "Ava Card") is None
    hit = _off(lps.exits_from_espn_summary("wncaab", _cut(card, 3, "1:51")), "Ava Card")
    assert hit is not None and hit.key and hit.team == "UTC"


def _synthetic(plays, starters_home=("H1", "H2", "H3", "H4", "H5"), starters_away=("A1", "A2", "A3", "A4", "A5")):
    def team(ab, names):
        return {"team": {"abbreviation": ab}, "statistics": [{"labels": ["MIN", "PF"], "athletes": [
            {"athlete": {"displayName": n, "id": n}, "starter": True, "stats": ["10", "0"]} for n in names]}]}
    return {"header": {"id": "9", "competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]},
            "boxscore": {"players": [team("HOM", starters_home), team("AWY", starters_away)]},
            "plays": [{"period": {"number": per}, "clock": {"displayValue": clk}, "type": {"text": kind}, "text": text,
                       "homeScore": hs, "awayScore": as_} for per, clk, kind, text, hs, as_ in plays]}


def test_a_play_naming_the_player_lifts_the_flag(monkeypatch):
    monkeypatch.setenv(lps.OFF_FLOOR_SWITCH, "on")
    out = [(1, "10:00", "Substitution", "B1 enters the game for H1", 0, 0), (2, "7:00", "Jump Shot", "A2 misses jumper", 0, 0)]
    assert _off(lps.exits_from_espn_summary("nba", _synthetic(out)), "H1") is not None  # 17 game-min off
    back = out + [(2, "6:50", "Jump Shot", "H1 makes jumper", 2, 0)]
    assert _off(lps.exits_from_espn_summary("nba", _synthetic(back)), "H1") is None


def test_foul_trouble_blowout_and_end_window_never_flag(monkeypatch):
    monkeypatch.setenv(lps.OFF_FLOOR_SWITCH, "on")
    fouls = [(1, "11:00", "Personal Foul", "H1 personal foul", 0, 0), (1, "10:30", "Shooting Foul", "H1 shooting foul", 0, 0),
             (1, "10:00", "Substitution", "B1 enters the game for H1", 0, 0), (2, "7:00", "Jump Shot", "A2 misses jumper", 0, 0)]
    assert _off(lps.exits_from_espn_summary("nba", _synthetic(fouls)), "H1") is None  # 2 fouls in Q1 = foul trouble
    blowout = [(1, "10:00", "Substitution", "B1 enters the game for H1", 30, 5), (2, "7:00", "Jump Shot", "A2 misses", 30, 5)]
    assert _off(lps.exits_from_espn_summary("nba", _synthetic(blowout)), "H1") is None
    late = [(4, "11:00", "Substitution", "B1 enters the game for H1", 0, 0), (4, "0:30", "Jump Shot", "A2 misses", 0, 0)]
    assert _off(lps.exits_from_espn_summary("nba", _synthetic(late)), "H1") is None  # fires inside the last 5 min


def test_bench_players_are_never_off_floor_flagged(monkeypatch):
    monkeypatch.setenv(lps.OFF_FLOOR_SWITCH, "on")
    plays = [(1, "10:00", "Substitution", "H1 enters the game for B9", 0, 0), (2, "7:00", "Jump Shot", "A2 misses", 0, 0)]
    st = lps.exits_from_espn_summary("nba", _synthetic(plays))
    assert not [p for p in st.players_out if p.reason == "off_floor"]


def _without_starter_flags(box):
    for side in ("homeTeam", "awayTeam"):
        for g in box["playerByGameStats"][side]["goalies"]:
            g.pop("starter", None)
    return box


def test_nhl_api_goalie_change_is_caught_without_starter_flags():
    """2026-11-20: BUF @ WSH's goalie change was missed live (players_out=0 every tick) though its FINAL box is
    caught; the suspected cause is a live box with no `starter` flag. Two goalies with ice time is a change."""
    box = _without_starter_flags(_nhlapi())
    box["gameState"] = "LIVE"
    st = lps.exits_from_nhl_boxscore(box)
    assert sorted((p.team, p.player, p.reason, p.key) for p in st.players_out) == [
        ("UTA", "K. Vejmelka", "goalie_change", True), ("UTA", "V. Vanecek", "goalie_change", True)]
    assert lps.gameline_refusal(st)["reason"] == lps.REASON_KEY_PLAYER_OUT


def test_nhl_api_without_starter_flags_one_goalie_with_ice_time_is_no_exit():
    box = _without_starter_flags(_nhlapi())
    box["gameState"] = "LIVE"
    for side in ("homeTeam", "awayTeam"):
        goalies = box["playerByGameStats"][side]["goalies"]
        for g in goalies[1:]:
            g["toi"] = "00:00"
    assert lps.exits_from_nhl_boxscore(box).players_out == ()
