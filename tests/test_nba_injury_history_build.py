"""Historical NBA injury feed (scripts/nba_injury_history_build.py; lane basketball-player-distribution step 1d)."""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

import pandas as pd

from scripts.nba_injury_history_build import PdfStore, build, games, pick_report, report_names


def _summary(path, eid, date, home, away, stype=2):
    hdr = {"season": {"type": stype}, "competitions": [{"date": date, "competitors": [
        {"homeAway": "home", "team": {"abbreviation": home}}, {"homeAway": "away", "team": {"abbreviation": away}}]}]}
    with gzip.open(path / f"summary_{eid}.json.gz", "wt") as f:
        json.dump({"header": hdr}, f)


def test_games_regular_season_nba_only(tmp_path):
    _summary(tmp_path, 1, "2025-11-06T00:30Z", "BOS", "WSH")  # 7:30 PM ET on 11-05
    _summary(tmp_path, 2, "2026-02-16T01:00Z", "WORLD", "STRIPES")  # All-Star, filed as type 2
    _summary(tmp_path, 3, "2025-10-10T23:00Z", "BOS", "NY", stype=1)  # preseason
    g = games(tmp_path)
    assert [(x["date"], x["home"], x["away"]) for x in g] == [("2025-11-05", "BOS", "WAS")]


def test_report_names_both_formats():
    assert report_names(datetime(2025, 11, 15, 17, 0)) == ["Injury-Report_2025-11-15_05_00PM.pdf",
                                                           "Injury-Report_2025-11-15_05PM.pdf"]
    assert report_names(datetime(2026, 1, 15, 0, 45)) == ["Injury-Report_2026-01-15_12_45AM.pdf"]


def test_pick_report_never_reads_after_tip_minus_30():
    tip = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)  # 7:00 PM ET on 01-15
    have = {"Injury-Report_2026-01-15_06_45PM.pdf", "Injury-Report_2026-01-15_06_30PM.pdf",
            "Injury-Report_2026-01-15_05_00PM.pdf"}
    assert pick_report(tip, have.__contains__)[0] == "Injury-Report_2026-01-15_06_30PM.pdf"
    old = {"Injury-Report_2025-11-15_06PM.pdf", "Injury-Report_2025-11-15_07PM.pdf"}
    tip_old = datetime(2025, 11, 16, 0, 30, tzinfo=timezone.utc)  # 7:30 PM ET
    assert pick_report(tip_old, old.__contains__)[0] == "Injury-Report_2025-11-15_07PM.pdf"
    assert pick_report(tip, set().__contains__) is None


def test_build_keeps_only_the_games_teams(tmp_path):
    name = "Injury-Report_2026-01-15_06_30PM.pdf"
    (tmp_path / name).write_bytes(b"%PDF fake")
    store = PdfStore(tmp_path)
    report = pd.DataFrame([
        {"team": "BOS", "player": "Hurt Guy", "status": "OUT", "injury": "Knee"},
        {"team": "MIA", "player": "Other Game", "status": "OUT", "injury": "Ankle"},
        {"team": "WAS", "player": "Not Rostered", "status": "QUESTIONABLE", "injury": "Back"},
    ])
    g = [{"date": "2026-01-15", "home": "BOS", "away": "WAS", "tip": datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)}]
    out, s = build(g, store, lambda pdf, d: report, {"hurt guy", "other game"}, str.lower)
    assert sorted(out["player"]) == ["Hurt Guy", "Not Rostered"]
    assert set(out["source"]) == {"nba_official"} and set(out["date"]) == {"2026-01-15"}
    assert s["team_games_listed"] == 2 and s["rows_off_roster"] == 1 and s["games_no_report"] == 0
    assert s["report_age_min"][0.5] == 30.0
