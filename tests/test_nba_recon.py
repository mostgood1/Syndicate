"""NBA recon: the league-parameterised builder (WNBA default unchanged), the id-space-aware pred<->recon join, the
throttled refresh, and the props gate reaching it."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from scripts import build_wnba_recon as recon
from syndicate.features.shared import basketball_props_calibration as cal
from syndicate.features.shared import nba_history_refresh as hr


def _payload(home="GS", away="NY"):
    def team(abbr, ha, score, lines):
        return {"homeAway": ha, "score": str(score), "team": {"abbreviation": abbr},
                "linescores": [{"displayValue": str(v)} for v in lines]}
    keys = ["minutes", "points", "rebounds", "assists", "steals", "blocks", "turnovers",
            "threePointFieldGoalsMade-threePointFieldGoalsAttempted"]
    return {
        "header": {"competitions": [{"competitors": [team(home, "home", 110, [30, 25, 30, 25]),
                                                     team(away, "away", 100, [20, 30, 25, 25])]}]},
        "boxscore": {"players": [{"team": {"abbreviation": home}, "statistics": [{"keys": keys, "athletes": [
            {"athlete": {"id": "3934719", "displayName": "Jonas Valančiūnas"}, "stats": ["30", "12", "8", "2", "1", "0", "3", "0-1"]},
            {"athlete": {"id": "1", "displayName": "Bench Guy"}, "didNotPlay": True, "stats": []},
        ]}]}]},
    }


def test_nba_rows_use_nba_codes_and_endpoints_wnba_default_unchanged(monkeypatch):
    urls = []
    monkeypatch.setattr(recon, "_get", lambda url, timeout=30: urls.append(url) or _payload())
    nba = recon.rows_for_event("401", "2026-10-25", league="nba")
    assert nba["games"][0]["home_tri"] == "GSW" and nba["games"][0]["away_tri"] == "NYK"
    assert nba["props"][0]["team_abbr"] == "GSW" and len(nba["props"]) == 1        # DNP omitted, not zero
    assert "/basketball/nba/summary" in urls[-1]
    wnba = recon.rows_for_event("402", "2026-07-01")
    assert wnba["games"][0]["home_tri"] == "GS" and "/basketball/wnba/summary" in urls[-1]
    assert recon.artifact_relative_paths("2026-10-25", "nba")["props"] == "nba_source/data/processed/recon_props_2026-10-25.csv"
    assert recon.artifact_relative_paths("2026-07-01")["props"].startswith("wnba_source/")


def _write_day(root, pred_rows, recon_rows, d="2026-10-25"):
    pd.DataFrame(pred_rows).to_csv(root / f"props_predictions_{d}.csv", index=False)
    pd.DataFrame(recon_rows).to_csv(root / f"recon_props_{d}.csv", index=False)


def test_join_falls_back_to_name_and_team_when_id_spaces_differ(tmp_path):
    """Current NBA predictions carry stats.nba ids and accented names; recon carries ESPN ids and plain names."""
    _write_day(tmp_path,
               [{"player_id": 202685, "player_name": "Jonas Valančiūnas", "team": "DEN", "pred_pts": 9.0},
                {"player_id": 203501, "player_name": "Tim Hardaway Jr.", "team": "DEN", "pred_pts": 8.0}],
               [{"player_id": 3934719, "player_name": "Jonas Valanciunas", "team_abbr": "DEN", "pts": 12},
                {"player_id": 2528426, "player_name": "Tim Hardaway Jr.", "team_abbr": "UTA", "pts": 5}])  # other team
    m = cal._merge_pred_recon_for_date(processed_root=tmp_path, date_str="2026-10-25")
    assert m is not None and len(m) == 1 and int(m.iloc[0]["pts"]) == 12


def test_join_keeps_the_id_when_the_spaces_overlap(tmp_path):
    _write_day(tmp_path,
               [{"player_id": 11, "player_name": "A", "team": "NYK", "pred_pts": 9.0}],
               [{"player_id": 11, "player_name": "Different Spelling", "team_abbr": "NYK", "pts": 12}])
    m = cal._merge_pred_recon_for_date(processed_root=tmp_path, date_str="2026-10-25")
    assert m is not None and len(m) == 1


def test_compute_biases_now_uses_the_shared_join(tmp_path):
    rows_p = [{"player_id": 200000 + i, "player_name": f"P{i}", "team": "NYK", "pred_pts": 10.0} for i in range(60)]
    rows_r = [{"player_id": 3900000 + i, "player_name": f"P{i}", "team_abbr": "NYK", "pts": 12} for i in range(60)]
    _write_day(tmp_path, rows_p, rows_r, d="2026-10-24")
    b = cal.compute_biases(processed_root=tmp_path, anchor_date="2026-10-25", window_days=1, min_pairs=50)
    assert b and abs(float(b.get("pts", 0.0))) > 0                     # disjoint ids, still 60 pairs


NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def test_refresh_recon_builds_the_last_three_dates_for_nba_and_throttles(tmp_path):
    proc = tmp_path / "nba_source" / "data" / "processed"
    proc.mkdir(parents=True)
    calls = []

    def build(d, data_root=None, league=None):
        calls.append((d, Path(data_root), league))
        if d == "2026-10-23":
            raise RuntimeError("espn down")
        return {"status": "ok", "games": 3, "props": 60}

    out = hr.refresh_recon(proc, "2026-10-25", build=build, now=NOW)
    assert [c[0] for c in calls] == ["2026-10-24", "2026-10-23", "2026-10-22"]
    assert all(c[1] == tmp_path and c[2] == "nba" for c in calls)
    assert out["dates"]["2026-10-23"]["status"].startswith("failed") and out["dates"]["2026-10-22"]["status"] == "ok"
    assert hr.refresh_recon(proc, "2026-10-25", build=build, now=NOW + timedelta(hours=1)).get("skipped")
    assert len(calls) == 3


def test_props_gate_reaches_the_recon_refresh_and_off_switch(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "refresh_nba_oddsapi_props.py"
    spec = importlib.util.spec_from_file_location("refresh_nba_props_recon_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    src = tmp_path / "nba_source"
    (src / "data" / "processed").mkdir(parents=True)
    (src / "data" / "processed" / "player_logs.csv").write_text("PLAYER_NAME,GAME_DATE\nA,2026-04-01\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(hr, "refresh_player_logs", lambda *a, **k: {"skipped": "test"})
    monkeypatch.setattr(hr, "refresh_recon", lambda root, d, **k: seen.append((Path(root), d)) or {"dates": {}})
    log = tmp_path / "r.log"
    mod._ensure_player_logs_for_props_refresh(source_root=src, date_str="2026-10-25", log_file=log, heartbeat_cb=lambda: None)
    assert seen == [(src / "data" / "processed", "2026-10-25")]
    monkeypatch.setenv("SYNDICATE_NBA_RECON_REFRESH", "0")
    mod._ensure_player_logs_for_props_refresh(source_root=src, date_str="2026-10-25", log_file=log, heartbeat_cb=lambda: None)
    assert len(seen) == 1
