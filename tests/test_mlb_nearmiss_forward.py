"""M1 / M2 MLB forward grader: as-of firing, the registered close and price, voids, the per-test bar (mlb-nearmiss-forward)."""
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
from collections import defaultdict
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "grade_mlb_nearmiss_forward", Path(__file__).resolve().parents[1] / "scripts" / "grade_mlb_nearmiss_forward.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HIT = ["date", "season", "game_type", "game_pk", "player_id", "player_name", "team", "opponent", "is_home", "pa", "ab", "h",
       "tb", "hr", "rbi", "r", "so", "bb", "hbp"]
PIT = ["date", "season", "game_type", "game_pk", "player_id", "player_name", "team", "opponent", "is_home", "is_starter",
       "outs", "k", "bb", "er", "h", "hr", "pitches", "batters_faced"]
NYY, SF = "New York Yankees", "San Francisco Giants"


def _csv(path: Path, cols, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, 0) for c in cols})


def _fixture(root: Path, last_day: str = "2027-06-20") -> None:
    base = root / "mlb_source" / "source_artifacts" / "data"
    hit, pit = [], []
    for i in range(20):  # 20 earlier games: SF hits rarely strike out (SO/PA 0.10); the graded game is on `last_day`
        day, g = f"2027-06-{i:02d}" if i else "2027-05-31", str(500 + i)
        hit.append({"date": day, "game_type": "R", "game_pk": g, "player_id": 7, "player_name": "Aaron Judge", "team": NYY,
                    "opponent": SF, "pa": 30, "h": 1, "tb": 1, "so": 3})
        hit.append({"date": day, "game_type": "R", "game_pk": g, "player_id": 8, "player_name": "Matt Chapman", "team": SF,
                    "opponent": NYY, "pa": 30, "h": 1, "tb": 1, "so": 3})
        pit.append({"date": day, "game_type": "R", "game_pk": g, "player_id": 9, "player_name": "Gerrit Cole", "team": NYY,
                    "opponent": SF, "is_starter": 1, "k": 5, "batters_faced": 25})
    g = "999"
    hit.append({"date": last_day, "game_type": "R", "game_pk": g, "player_id": 8, "player_name": "Matt Chapman", "team": SF,
                "opponent": NYY, "pa": 4, "h": 0, "tb": 0, "so": 0})
    pit.append({"date": last_day, "game_type": "R", "game_pk": g, "player_id": 9, "player_name": "Gerrit Cole", "team": NYY,
                "opponent": SF, "is_starter": 1, "k": 3, "batters_faced": 26})
    _csv(base / "derived" / "mlb_player_game_log_2027_hitting.csv", HIT, hit)
    _csv(base / "derived" / "mlb_player_game_log_2027_pitching.csv", PIT, pit)
    raw = base / "statcast" / "raw_pitches" / "2027"
    raw.mkdir(parents=True)
    with gzip.open(raw / "statcast_2027-05-31_2027-06-19.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["game_date", "game_type", "batter", "pitcher", "pitch_type", "events", "woba_value"])
        w.writeheader()
        for i in range(60):  # Chapman: poor vs FF, Cole throws only FF -> a bad arsenal edge
            day = f"2027-06-{(i % 19) + 1:02d}"
            w.writerow({"game_date": day, "game_type": "R", "batter": 8, "pitcher": 1, "pitch_type": "SL" if i % 2 else "FF",
                        "events": "single" if i % 2 else "field_out", "woba_value": 0.9 if i % 2 else 0.0})
        for i in range(320):
            w.writerow({"game_date": "2027-06-01", "game_type": "R", "batter": 2, "pitcher": 9, "pitch_type": "FF",
                        "events": "", "woba_value": ""})
    bq = root / "mlb_source" / "tracking" / "book_quotes"
    bq.mkdir(parents=True)
    rows = []
    for market, player, point in (("batter_hits", "Matt Chapman", 0.5), ("strikeouts", "Gerrit Cole", 5.5)):
        for book, over, under in (("draftkings", -110, -110), ("fanduel", -115, -105), ("pinnacle", 120, 150)):
            for sel, price in (("over", over), ("under", under)):
                rows.append({"kind": "prop", "event_id": "ev", "commence_time": f"{last_day}T23:05:00Z",
                             "captured_at": f"{last_day}T20:00:00Z", "bookmaker": book, "market": market, "selection": sel,
                             "player_name": player, "line": point, "price": price, "home_team": NYY, "away_team": SF})
    (bq / f"{last_day}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_m1_and_m2_fire_as_of_and_grade_at_the_us_price(tmp_path) -> None:
    g = _load()
    _fixture(tmp_path)
    counts: dict = defaultdict(int)
    recs = g.collect(tmp_path, "2027-06-20", False, counts)
    by = {r["h"]: r for r in recs}
    assert set(by) == {"M1", "M2"}
    assert by["M1"]["stat"] == "h" and by["M1"]["y"] == 1.0 and by["M1"]["price"] == -105   # 0 hits < 0.5; best US under
    assert by["M2"]["stat"] == "k" and by["M2"]["y"] == 1.0                                 # 3 K < 5.5; SF SO/PA 0.10
    rep = g.report(recs, "2027-06-20", counts)
    assert rep["hypotheses"]["M1"]["verdict"].startswith("INTERIM") and rep["hypotheses"]["M1"]["alpha"] == 0.0125


def test_doubleheaders_and_pre_registration_games_are_never_graded(tmp_path, monkeypatch) -> None:
    g = _load()
    _fixture(tmp_path)
    counts: dict = defaultdict(int)
    monkeypatch.setattr(g, "REGISTERED_AT", g.REGISTERED_AT.replace(year=2027, month=7))
    assert g.collect(tmp_path, "2027-06-20", False, counts) == [] and counts["pre_registration"] >= 2
    log = tmp_path / "mlb_source" / "source_artifacts" / "data" / "derived" / "mlb_player_game_log_2027_hitting.csv"
    with log.open("a", encoding="utf-8", newline="") as fh:   # a second NYY-SF game on the graded day
        csv.DictWriter(fh, fieldnames=HIT).writerow({c: 0 for c in HIT} | {"date": "2027-06-20", "game_type": "R",
                                                     "game_pk": "1000", "player_id": 5, "player_name": "X", "team": NYY,
                                                     "opponent": SF})
    monkeypatch.setattr(g, "REGISTERED_AT", g.REGISTERED_AT.replace(year=2026, month=10))
    counts = defaultdict(int)
    assert g.collect(tmp_path, "2027-06-20", False, counts) == [] and counts["void_doubleheader"] >= 1
