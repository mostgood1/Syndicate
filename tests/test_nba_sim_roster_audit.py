"""scripts/nba_sim_roster_audit.py (lane nba-current-rosters): the instrument that measured 179 stale players on the
2026-10-20/21 NBA sims. Its counts must be right before they are evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts import nba_sim_roster_audit as audit_mod

DATE = "2026-10-20"
FULL = {"Philadelphia 76ers": "PHI", "New York Knicks": "NYK"}


def _to_tri(value: object) -> str:
    v = str(value or "").strip()
    return FULL.get(v, v.upper())


def _seed(root: Path) -> Path:
    processed = root / "nba_source" / "data" / "processed"
    processed.mkdir(parents=True)
    sim = {
        "home": "NYK", "away": "PHI",
        "players": {
            "home": [{"player_name": "Jalen Brunson"}, {"player_name": "Ariel Hukporti"}],
            "away": [{"player_name": "Paul George"}, {"player_name": "Tyrese Maxey"}, {"player_name": "Joel Embiid"}],
        },
        "context": {"excluded_players": {"PHI": ["JOEL EMBIID"]}},
    }
    (processed / f"smart_sim_{DATE}_NYK_PHI.json").write_text(json.dumps(sim), encoding="utf-8")
    (processed / f"smart_sim_{DATE}_NYK_PHI.json.tmp").write_text("{}", encoding="utf-8")  # not a sim file
    with (processed / f"oddsapi_player_props_{DATE}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["market", "player_name", "home_team", "away_team"])
        w.writerow(["player_points", "LeBron James", "New York Knicks", "Philadelphia 76ers"])
        w.writerow(["h2h", "", "New York Knicks", "Philadelphia 76ers"])
    (processed / "rosters_2025-26.csv").write_text("PLAYER,TEAM_ABBREVIATION\nPaul George,PHI\nLeBron James,LAL\n", encoding="utf-8")
    (processed / "player_logs.csv").write_text(
        "PLAYER_NAME,TEAM_ABBREVIATION,GAME_DATE\nPaul George,PHI,2026-04-12\nLeBron James,LAL,2026-04-12\n", encoding="utf-8"
    )
    return processed


CURRENT = {
    "PHI": ["LeBron James", "Tyrese Maxey", "Joel Embiid", "Adem Bona", "Ariel Hukporti"],
    "NYK": ["Jalen Brunson"],
    "MIN": ["Paul George"],
}


def test_counts_stale_missing_and_priced(tmp_path):
    processed = _seed(tmp_path)
    report = audit_mod.audit(processed, [DATE], CURRENT, _to_tri)
    sides = {s["team"]: s for s in report["sides"]}
    phi, nyk = sides["PHI"], sides["NYK"]
    assert [(x["player"], x["now_on"], x["rosters_2025_26"], x["last_log_team"]) for x in phi["stale"]] == [("Paul George", "MIN", "PHI", "PHI")]
    missing = {m["player"]: m for m in phi["missing"]}
    assert set(missing) == {"LeBron James", "Adem Bona", "Ariel Hukporti"}
    assert missing["LeBron James"]["priced"] and missing["LeBron James"]["has_history"]
    assert not missing["Adem Bona"]["priced"] and not missing["Adem Bona"]["has_history"]
    assert phi["n_overlap"] == 2  # Maxey, Embiid (the sim's excluded stamp is reported, Embiid is simulated here)
    assert [x["player"] for x in nyk["stale"]] == ["Ariel Hukporti"] and nyk["n_missing"] == 0
    t = report["totals"]
    assert (t["sides"], t["stale_players"], t["missing_priced_players"], t["stale_matching_2025_26_team"]) == (2, 2, 1, 1)


def test_excluded_stamp_is_visible_on_a_missing_player(tmp_path):
    processed = _seed(tmp_path)
    sim = json.loads((processed / f"smart_sim_{DATE}_NYK_PHI.json").read_text(encoding="utf-8"))
    sim["players"]["away"] = [p for p in sim["players"]["away"] if p["player_name"] != "Joel Embiid"]
    (processed / f"smart_sim_{DATE}_NYK_PHI.json").write_text(json.dumps(sim), encoding="utf-8")
    phi = next(s for s in audit_mod.audit(processed, [DATE], CURRENT, _to_tri)["sides"] if s["team"] == "PHI")
    assert next(m for m in phi["missing"] if m["player"] == "Joel Embiid")["excluded_in_sim"] is True


def test_main_exit_codes(tmp_path, monkeypatch):
    processed = _seed(tmp_path)
    roster_csv = tmp_path / "roster.csv"
    with roster_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PLAYER", "TEAM_ABBREVIATION"])
        for tri, names in CURRENT.items():
            for n in names:
                w.writerow([n, tri])
    monkeypatch.setattr(audit_mod, "_default_to_tri", lambda: _to_tri)
    out_json = tmp_path / "r.json"
    rc = audit_mod.main(["--date", DATE, "--data-root", str(tmp_path), "--roster-csv", str(roster_csv), "--json", str(out_json), "--quiet"])
    assert rc == 1 and json.loads(out_json.read_text(encoding="utf-8"))["totals"]["stale_players"] == 2
    clean = {"PHI": ["Paul George", "Tyrese Maxey", "Joel Embiid"], "NYK": ["Jalen Brunson", "Ariel Hukporti"]}
    with roster_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PLAYER", "TEAM_ABBREVIATION"])
        for tri, names in clean.items():
            for n in names:
                w.writerow([n, tri])
    assert audit_mod.main(["--date", DATE, "--data-root", str(tmp_path), "--roster-csv", str(roster_csv), "--quiet"]) == 0
    assert audit_mod.main(["--date", "2026-01-01", "--data-root", str(tmp_path), "--roster-csv", str(roster_csv)]) == 2
