"""MLB matchup splits producer + the board sentence it feeds (lane intelligence-evidence-coverage, phase 2)."""

from __future__ import annotations

import csv
import gzip
import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_mlb_matchup_splits", Path(__file__).resolve().parents[1] / "scripts" / "build_mlb_matchup_splits.py"
)
splits = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(splits)


def _pa(event, *, batter="1", pitcher="9", stand="L", throws="R", top="Top", date="2026-06-01", pk="100", game_type="R"):
    return {"events": event, "batter": batter, "pitcher": pitcher, "stand": stand, "p_throws": throws,
            "inning_topbot": top, "home_team": "NYY", "away_team": "BOS", "game_date": date, "game_pk": pk,
            "game_type": game_type}


def test_outcome_counts_ab_hits_and_total_bases():
    assert splits.outcome("double") == {"pa": 1, "ab": 1, "h": 1, "tb": 2, "hr": 0, "so": 0, "bb": 0, "hbp": 0}
    assert splits.outcome("walk")["ab"] == 0 and splits.outcome("sac_fly")["ab"] == 0
    assert splits.outcome("strikeout_double_play")["so"] == 1


def test_aggregate_splits_by_hand_team_and_game_and_skips_spring_and_non_pa_pitches():
    rows = [
        _pa("home_run"), _pa("strikeout", throws="L", pitcher="7"), _pa(""),  # "" = a pitch that ended no PA
        _pa("single", top="Bot", batter="2", stand="R"),
        _pa("single", game_type="S"),
    ]
    batters, pitchers, log, newest = splits.aggregate(rows)
    assert batters["1"]["vs_R"]["hr"] == 1 and batters["1"]["vs_L"]["so"] == 1
    assert batters["1"]["vs_team"]["NYY"]["pa"] == 2  # Top = the away batter faces the home team
    assert batters["2"]["vs_team"]["BOS"]["h"] == 1
    assert pitchers["9"]["throws"] == "R" and pitchers["9"]["vs_L"]["pa"] == 1 and pitchers["9"]["vs_R"]["pa"] == 1 and pitchers["7"]["throws"] == "L"
    assert log[("100", "1")]["team"] == "BOS" and log[("100", "1")]["tb"] == 4
    assert newest == "2026-06-01"


def test_run_writes_dated_splits_and_the_sentence_reads_them(tmp_path, monkeypatch):
    root = tmp_path / "data"
    raw = root / "statcast" / "raw_pitches" / "2026"
    raw.mkdir(parents=True)
    rows = []
    for day in range(1, 13):  # batter 1 (BOS) vs NYY's righty 9: a hit on even days
        rows.append(_pa("single" if day % 2 == 0 else "field_out", date=f"2026-06-{day:02d}", pk=str(day)))
    with gzip.open(raw / "statcast_2026_06.csv.gz", "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setenv("SYNDICATE_MLB_DATA_ROOT", str(root))
    summary = splits.run()
    assert summary["through"] == "2026-06-12" and summary["batter_games"] == 12
    payload = json.loads((root / "derived" / "mlb_matchup_splits_2026_asof_20260612.json").read_text())
    assert payload["batters"]["1"]["vs_R"]["pa"] == 12

    snap = root / "daily" / "snapshots" / "2026-06-13"
    snap.mkdir(parents=True)
    (snap / "probables.json").write_text(json.dumps({"games": [
        {"home": {"abbr": "NYY"}, "away": {"abbr": "BOS"}, "home_probable_id": 9, "away_probable_id": 8,
         "home_validation": {"selected_name": "Righty Nine"}}]}), encoding="utf-8")

    from syndicate.features import intelligence_recent_matchup as rm

    row = {"market": "batter_hits", "line": 0.5, "side": "over", "player_id": "1", "home_team": "NYY", "away_team": "BOS"}
    text = rm.mlb_prop_recent_matchup_text(row, selected_date="2026-06-13")
    assert "over 0.5 in 5 of the last 10 logged games" in text  # days 3..12 from the full-season log
    assert "Splits (2026 regular season): vs RHP .500 AVG, 0 HR in 12 PA; vs NYY .500 AVG, 0 HR in 12 PA." in text


def test_feed_live_games_after_the_statcast_cutoff_are_appended(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "derived").mkdir(parents=True)
    (root / "processed").mkdir(parents=True)
    fields = ",".join(splits.LOG_FIELDS)
    season = [f"2026-09-{d:02d},{d},1,BOS,NYY,4,4,0,0,0,1,0,0" for d in range(10, 28)]
    (root / "derived" / "mlb_batter_game_log_statcast_2026.csv").write_text(fields + "\n" + "\n".join(season) + "\n", encoding="utf-8")
    # feed_live: one game inside the Statcast window (ignored) and two postseason games
    (root / "processed" / "mlb_batter_game_log.csv").write_text(
        "date,player_id,team,h\n2026-09-20,1,BOS,3\n2026-10-01,1,BOS,2\n2026-10-02,1,BOS,1\n", encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_MLB_DATA_ROOT", str(root))
    from syndicate.features import intelligence_recent_matchup as rm

    text = rm.mlb_prop_recent_matchup_text({"market": "batter_hits", "line": 0.5, "side": "over", "player_id": "1"}, selected_date="2026-10-03")
    assert text.startswith("Recent form: over 0.5 in 2 of the last 10 logged games (avg 0.3; log since 2026-09-20).")
