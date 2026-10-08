"""NBA / WNBA multi-season player game log + the box reader that uses it (lane intelligence-evidence-coverage)."""

from __future__ import annotations

import csv
import datetime as dt
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_basketball_player_game_log", Path(__file__).resolve().parents[1] / "scripts" / "build_basketball_player_game_log.py"
)
log = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(log)

NAMES = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]


def _event(gid="9", season_type=2, home="CONN", away="LV"):
    return {"id": gid, "season": {"year": 2025, "type": season_type}, "status": {"type": {"state": "post"}},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"abbreviation": home}},
                                              {"homeAway": "away", "team": {"abbreviation": away}}]}]}


def _summary():
    athlete = lambda pid, name, stats, **kw: {"athlete": {"id": pid, "displayName": name, "position": {"abbreviation": "G"}},
                                             "stats": stats, "starter": kw.get("starter", True), "didNotPlay": kw.get("dnp", False)}
    line = lambda mins, pts: [mins, pts, "5-9", "2-4", "1-1", "4", "6", "2", "1", "0", "1", "3", "2", "+5"]
    return {"boxscore": {"players": [
        {"team": {"abbreviation": "LV"}, "statistics": [{"names": NAMES, "athletes": [
            athlete("1", "Jackie Young", line("34", "21")), athlete("2", "Bench DNP", [], dnp=True),
            athlete("3", "Zero Minutes", line("0", "0"), starter=False)]}]},
        {"team": {"abbreviation": "CONN"}, "statistics": [{"names": NAMES, "athletes": [athlete("4", "Home Guard", line("30", "12"))]}]},
    ]}}


def test_game_rows_fold_codes_skip_dnp_and_read_threes():
    rows = log.game_rows("wnba", 2025, dt.date(2025, 7, 15), _event(), _summary())
    assert [(r["PLAYER_NAME"], r["TEAM_ABBREVIATION"], r["opponent"], r["home_away"]) for r in rows] == [
        ("Jackie Young", "LVA", "CON", "away"), ("Home Guard", "CON", "LVA", "home")]
    assert rows[0]["FG3M"] == 2.0 and rows[0]["PTS"] == 21.0 and rows[0]["season_type"] == "regular"
    assert log.game_rows("wnba", 2025, dt.date(2025, 7, 15), _event(season_type=1), _summary()) == []  # preseason


def test_run_is_incremental(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_WNBA_SOURCE_ROOT", str(tmp_path / "wnba_source"))
    calls = []

    def fetch(url):
        calls.append(url)
        if "scoreboard" in url:
            return {"events": [_event()]} if url.endswith("20250715") else {"events": []}
        return _summary()

    first = log.run("wnba", 2025, today=dt.date(2025, 7, 17), fetch=fetch, pause=0)
    assert first["new_games"] == 1 and sum("summary" in c for c in calls) == 1
    calls.clear()
    again = log.run("wnba", 2025, today=dt.date(2025, 7, 17), fetch=fetch, pause=0)
    assert again["new_games"] == 0 and not any("summary" in c for c in calls)  # the known game is never re-fetched
    assert again["days_scanned"] == 5  # 07-12..07-16: three days before the newest game, through yesterday


def test_box_reader_dedupes_by_date_and_derives_the_opponent(tmp_path, monkeypatch):
    from syndicate.features.shared.prop_evidence import basketball as B
    from syndicate.features.shared.prop_evidence.contract import PropSubject

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    proc = tmp_path / "wnba_source" / "data" / "processed"
    proc.mkdir(parents=True)
    (proc / "boxscores_history.csv").write_text(
        "game_id,date,TEAM_ABBREVIATION,PLAYER_NAME,MIN,PTS,REB,AST,FG3M,STL,BLK,TOV\n"
        "g1,2026-06-01,LV,Jackie Young,30,25,3,4,2,1,0,2\n"
        "g1,2026-06-01,CON,Home Guard,30,10,3,4,2,1,0,2\n", encoding="utf-8")
    with (proc / "player_game_log_2025.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=log.FIELDS)
        writer.writeheader()
        for gid, day, pts in (("e1", "2025-07-15", 21), ("e2", "2025-08-01", 9)):
            for team, opp, name in (("LVA", "CON", "Jackie Young"), ("CON", "LVA", "Home Guard")):
                writer.writerow({"game_id": gid, "date": day, "TEAM_ABBREVIATION": team, "opponent": opp, "PLAYER_NAME": name,
                                 "MIN": 30, "PTS": pts if name == "Jackie Young" else 5})
    with (proc / "player_game_log_2026.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=log.FIELDS)
        writer.writeheader()
        for team, opp, name in (("LVA", "CON", "Jackie Young"), ("CON", "LVA", "Home Guard")):  # same game as g1, ESPN id
            writer.writerow({"game_id": "e9", "date": "2026-06-01", "TEAM_ABBREVIATION": team, "opponent": opp,
                             "PLAYER_NAME": name, "MIN": 30, "PTS": 99})
    games, _ = B._box_games("wnba", "Jackie Young", "2026-10-01")
    assert [(g["date"], g["team"], g["opponent"], g["PTS"]) for g in games] == [
        ("2026-06-01", "LVA", "CON", 25.0), ("2025-08-01", "LVA", "CON", 9.0), ("2025-07-15", "LVA", "CON", 21.0)]

    subject = PropSubject.from_board_row({"sport": "wnba", "kind": "prop", "player_name": "Jackie Young", "market": "player_points",
                                          "line": 15.5, "side": "over", "home_team": "Connecticut Sun", "away_team": "Las Vegas Aces"},
                                         selected_date="2026-10-01")
    layer = B._matchup(subject, None, games, ("PTS",), "PTS", {})
    assert layer.facts["opponent"] == "CON"
    assert layer.facts["vs_opponent"]["games"] == 3 and layer.facts["vs_opponent"]["hit_rate"]["hits"] == 2
    assert layer.facts["vs_opponent"]["since"] == "2025-07-15"
