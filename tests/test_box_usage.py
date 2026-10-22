"""Box-score usage for result cards (lane result-cards): the graded game's opportunity against the player's usual."""
from __future__ import annotations

from syndicate.features.shared import box_usage as bu


def _nhl_fetch(url):
    if "/game-log/20262027/" in url:
        return {"gameLog": [{"gameDate": "2026-10-15", "toi": "16:16"}, {"gameDate": "2026-10-13", "toi": "18:20"},
                            {"gameDate": "2026-10-10", "toi": "17:25"}]}
    if "/game-log/20252026/" in url:
        return {"gameLog": [{"gameDate": "2026-04-15", "toi": "15:45"}, {"gameDate": "2026-04-13", "toi": "16:56"}]}
    return None


def test_nhl_ice_time_against_the_usual_across_the_season_boundary(tmp_path):
    card = {"sport": "nhl", "date": "2026-10-15", "market": "SOG"}
    item = {"kind": "prop", "headshot_url": "https://assets.nhle.com/mugs/nhl/latest/8484471.png"}
    u = bu.usage_for(card, item, cache=tmp_path, fetch=_nhl_fetch)
    assert u["metric"] == "Ice time" and u["actual"] == 16.3 and u["games"] == 4                # 2 this season + 2 last
    assert u["usual"] == round((18 + 20 / 60 + 17 + 25 / 60 + 15 + 45 / 60 + 16 + 56 / 60) / 4, 1)
    assert bu.usage_for(dict(card, market="saves"), item, cache=tmp_path, fetch=_nhl_fetch) is None   # a goalie: not minutes
    assert bu.usage_for(dict(card, date="2026-10-14"), item, cache=tmp_path, fetch=_nhl_fetch) is None  # no game that day


def _mlb_fetch(url):
    if "group=pitching" in url and "gameType=P" in url:
        return {"stats": [{"splits": [{"date": "2026-10-15", "stat": {"battersFaced": 18, "gamesStarted": 1}},
                                      {"date": "2026-10-07", "stat": {"battersFaced": 20, "gamesStarted": 1}}]}]}
    if "group=pitching" in url:
        return {"stats": [{"splits": [{"date": "2026-09-25", "stat": {"battersFaced": 24, "gamesStarted": 1}},
                                      {"date": "2026-09-20", "stat": {"battersFaced": 4, "gamesStarted": 0}},
                                      {"date": "2026-09-14", "stat": {"battersFaced": 22, "gamesStarted": 1}}]}]}
    if "group=hitting" in url and "gameType=P" in url:
        return {"stats": [{"splits": [{"date": "2026-10-15", "stat": {"plateAppearances": 4}},
                                      {"date": "2026-10-15", "stat": {"plateAppearances": 3}}]}]}       # a doubleheader
    return {"stats": [{"splits": []}]}


def test_mlb_workload_counts_starts_only_for_a_starter_and_never_guesses_a_doubleheader(tmp_path):
    card = {"sport": "mlb", "date": "2026-10-15", "market": "hits_allowed"}
    item = {"kind": "prop", "headshot_url": "https://img.mlbstatic.com/mlb-photos/image/upload/w_360/v1/people/607192/headshot/67/current"}
    u = bu.usage_for(card, item, cache=tmp_path, fetch=_mlb_fetch)
    assert u["metric"] == "Batters faced" and u["actual"] == 18 and u["of"] == "starts" and u["games"] == 3
    assert u["usual"] == round((20 + 24 + 22) / 3, 1)                                  # the relief outing (4) left out
    batter = bu.usage_for(dict(card, market="batter_hits"), item, cache=tmp_path, fetch=_mlb_fetch)
    assert batter is None                                                               # two games that day: not guessed


def test_only_supported_props_get_usage(tmp_path):
    item = {"kind": "prop", "player_id": "1"}
    assert bu.usage_for({"sport": "nfl", "date": "2026-10-15", "market": "Receptions"}, item, cache=tmp_path) is None
    assert bu.usage_for({"sport": "mlb", "date": "2026-10-15", "market": "h2h"}, {"kind": "game"}, cache=tmp_path) is None
    assert bu.player_id("nhl", {"headshot_url": "https://assets.nhle.com/mugs/nhl/latest/8478402.png"}) == "8478402"
    assert bu.player_id("mlb", {"player_id": 607192}) == "607192"


def test_nfl_targets_carries_and_attempts_from_the_play_by_play(tmp_path):
    pbp = tmp_path / "nfl_source" / "tracking" / "nflverse" / "pbp"
    pbp.mkdir(parents=True)
    head = "game_id,game_date,pass_attempt,rush_attempt,sack,two_point_attempt,receiver_player_name,receiver_player_id," \
           "rusher_player_name,rusher_player_id,passer_player_name,passer_player_id\n"
    rows = []
    for date, targets in (("2026-10-15", 2), ("2026-10-05", 6), ("2026-09-28", 5), ("2026-09-21", 7)):
        rows += [f"g,{date},1,0,0,0,T.Horton,00-1,,,G.Smith,00-9" for _ in range(targets)]
    rows.append("g,2026-10-15,1,0,1,0,,,,,G.Smith,00-9")                        # a sack: not a pass attempt
    rows.append("g,2026-10-15,1,0,0,1,T.Horton,00-1,,,G.Smith,00-9")             # a two-point try: not counted
    rows += ["g,2026-10-15,0,1,0,0,,,K.Walker,00-2,," for _ in range(3)]
    (pbp / "pbp_2026.csv").write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    card = {"sport": "nfl", "date": "2026-10-15", "market": "Receiving Yards", "player": "Tory Horton"}
    u = bu.usage_for(card, {"kind": "prop"}, cache=tmp_path, data_root=tmp_path)
    assert u["metric"] == "Targets" and u["actual"] == 2.0 and u["usual"] == 6.0 and u["games"] == 3
    attempts = bu.usage_for(dict(card, market="Passing Yards", player="Geno Smith"), {"kind": "prop"}, cache=tmp_path, data_root=tmp_path)
    assert attempts["actual"] == 2.0                                               # the sack and the two-point try left out
    assert bu.usage_for(dict(card, market="Anytime TD"), {"kind": "prop"}, cache=tmp_path, data_root=tmp_path) is None
    assert bu.usage_for(dict(card, market="Rushing Yards", player="Kenneth Walker III"), {"kind": "prop"}, cache=tmp_path,
                        data_root=tmp_path) is None                                # 3 carries but no earlier games: no usual


def test_two_players_sharing_a_key_are_never_guessed(tmp_path):
    pbp = tmp_path / "nfl_source" / "tracking" / "nflverse" / "pbp"
    pbp.mkdir(parents=True)
    head = "game_id,game_date,pass_attempt,rush_attempt,sack,two_point_attempt,receiver_player_name,receiver_player_id\n"
    rows = ["g,2026-10-15,1,0,0,0,J.Smith,00-1", "g,2026-10-15,1,0,0,0,J.Smith,00-2"]
    rows += [f"g,{d},1,0,0,0,J.Smith,00-1" for d in ("2026-10-05", "2026-09-28", "2026-09-21")]
    (pbp / "pbp_2026.csv").write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    card = {"sport": "nfl", "date": "2026-10-15", "market": "Receptions", "player": "Jaxon Smith"}
    assert bu.usage_for(card, {"kind": "prop"}, cache=tmp_path, data_root=tmp_path) is None


def _hoops_log(tmp_path, league, season, rows):
    folder = tmp_path / f"{league}_source" / "data" / "processed"
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["game_id,date,season,season_type,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN"]
    lines += [f"g{i},{d},{season},{t},PHI,1,{name},{m}" for i, (d, t, name, m) in enumerate(rows)]
    (folder / f"player_game_log_{season}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_nba_minutes_against_the_same_phase_usual_across_the_season_boundary(tmp_path):
    """2026-10-22: NBA prop losses carried no usage (0 of 63). Minutes from the league's own game log; the usual from the
    SAME phase -- last season's playoff minutes never set a regular-season usual."""
    _hoops_log(tmp_path, "nba", 2025, [("2026-04-10", "regular", "Kelly Oubre Jr.", 30), ("2026-04-12", "regular", "Kelly Oubre Jr.", 32),
                                       ("2026-05-01", "playoffs", "Kelly Oubre Jr.", 44), ("2026-05-03", "playoffs", "Kelly Oubre Jr.", 46)])
    _hoops_log(tmp_path, "nba", 2026, [("2026-10-20", "regular", "Kelly Oubre Jr.", 28), ("2026-10-22", "regular", "Kelly Oubre Jr.", 18)])
    card = {"sport": "nba", "date": "2026-10-22", "market": "player_points", "player": "Kelly Oubre"}
    u = bu.usage_for(card, {"kind": "prop"}, cache=tmp_path, data_root=tmp_path)
    assert u["metric"] == "Minutes" and u["actual"] == 18.0 and u["games"] == 3 and u["usual"] == 30.0   # (28+32+30)/3
    assert bu.usage_for(dict(card, date="2026-10-21"), {"kind": "prop"}, cache=tmp_path, data_root=tmp_path) is None  # no game
    assert bu.usage_for(dict(card, player="Somebody Else"), {"kind": "prop"}, cache=tmp_path, data_root=tmp_path) is None


def test_a_playoff_game_with_few_playoff_games_falls_back_to_the_regular_season(tmp_path):
    _hoops_log(tmp_path, "wnba", 2026, [("2026-08-01", "regular", "A Wilson", 34), ("2026-08-03", "regular", "A Wilson", 36),
                                        ("2026-08-05", "regular", "A Wilson", 35), ("2026-09-20", "playoffs", "A Wilson", 40)])
    u = bu.hoops_usage(tmp_path, "wnba", "A. Wilson", "2026-09-20")
    assert u["games"] == 3 and u["usual"] == 35.0 and u["source"] == "Syndicate WNBA game log"
