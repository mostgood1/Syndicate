"""MLB signals v1: purchase selection, as-of features (no look-ahead), rules, lines, end to end (signal-engine-mlb)."""
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
from collections import defaultdict
from pathlib import Path


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HIT_COLS = ["date", "season", "game_type", "game_pk", "player_id", "player_name", "team", "opponent", "is_home", "pa", "ab",
            "h", "tb", "hr", "rbi", "r", "so", "bb", "hbp"]
PIT_COLS = ["date", "season", "game_type", "game_pk", "player_id", "player_name", "team", "opponent", "is_home", "is_starter",
            "outs", "k", "bb", "er", "h", "hr", "pitches", "batters_faced"]
NYY, SF = "New York Yankees", "San Francisco Giants"


def _csv(path: Path, cols, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, 0) for c in cols})


def test_purchase_excludes_doubleheaders_and_non_regular_games(tmp_path) -> None:
    p = _load("mlb_props_pull")
    rows = [{"date": "2026-06-01", "game_type": "R", "game_pk": "1", "team": NYY, "opponent": SF},
            {"date": "2026-06-02", "game_type": "R", "game_pk": "2", "team": NYY, "opponent": SF},   # doubleheader
            {"date": "2026-06-02", "game_type": "R", "game_pk": "3", "team": NYY, "opponent": SF},
            {"date": "2026-10-05", "game_type": "D", "game_pk": "4", "team": NYY, "opponent": SF}]
    _csv(tmp_path / "h.csv", HIT_COLS, rows)
    games, dh = p.regular_season_games(tmp_path / "h.csv")
    assert list(games) == ["1"] and dh == 2 and p.CREDITS_PER_GAME == 30
    ev = {"id": "e", "home_team": NYY, "away_team": SF, "commence_time": "2026-06-01T23:05:00Z"}
    assert p.match_event(games["1"], [ev])["id"] == "e"
    assert p.match_event(games["1"], [ev, dict(ev, id="e2", commence_time="2026-06-02T03:05:00Z")]) is None


def test_features_read_only_earlier_days() -> None:
    m = _load("mlb_signal_tests")
    st = m.State({(9, 7): [12, 6]})                       # pre-2026: batter 7 is 6-for-12 against pitcher 9
    for i in range(30):
        st.add_day({"pa": [(9, 7, "FF", 0.9, True)] if i == 0 else [], "pitches": [(9, "FF")] * 20 + [(9, "SL")] * 10},
                   [{"pid": 7, "team": NYY, "pa": 4.0, "h": 2.0 if i >= 23 else 1.0, "so": 1.0}], [])
    for _ in range(60):
        st.add_day({"pa": [(1, 7, "SL", 0.1, False), (1, 7, "FF", 0.5, True)], "pitches": []}, [], [])
    f = st.batter_features(7, 9)
    assert f["bvp_pa"] == 13 and f["bvp_edge"] == round(7 / 13 - (7 * 2 + 23 * 1) / 120, 4)
    assert f["recency"] == round(14 / 28 - 23 / 92, 4)
    assert f["arsenal"] is not None and f["arsenal"] > 0     # the pitcher throws mostly FF, the batter's best type
    assert st.batter_features(7, 999)["arsenal"] is None      # no pitch-mix history -> unknown, not zero


def test_rules_need_registered_thresholds() -> None:
    m = _load("mlb_signal_tests")
    t = {**m.THRESHOLDS, "bvp_edge": 0.1, "arsenal_hi": 0.02, "arsenal_lo": -0.02, "recency": 0.08, "stack_bvp": 0.05,
         "stack_arsenal": 0.01, "stack_recency": 0.04, "k_trend": 0.05, "opp_k_hi": 0.25, "opp_k_lo": 0.20}
    f = {"bvp_edge": 0.12, "arsenal": 0.03, "recency": 0.09}
    assert set(m.fires(f, t)) == {"mlb.bvp_edge", "mlb.arsenal_edge", "mlb.hot_streak", "mlb.matchup_stack"}
    assert m.fires({"arsenal": -0.03, "opp_k": 0.19}, t) == ["mlb.arsenal_bad", "mlb.opp_k_low"]
    assert m.fires(f) == []                                  # unregistered thresholds never fire
    assert m.eligible("mlb.matchup_stack", f) and not m.eligible("mlb.matchup_stack", {"bvp_edge": 0.1})


def test_main_line_per_player_market() -> None:
    m = _load("mlb_signal_tests")
    def mk(key, player, point, over, under):
        return {"key": key, "outcomes": [{"name": "Over", "description": player, "price": over, "point": point},
                                         {"name": "Under", "description": player, "price": under, "point": point}]}
    snap = {"snap": {"data": {"bookmakers": [
        {"key": "dk", "markets": [mk("batter_hits", "Aaron Judge", 0.5, -250, 190), mk("batter_hits", "Aaron Judge", 1.5, 220, -300)]},
        {"key": "fd", "markets": [mk("batter_hits", "Aaron Judge", 0.5, -240, 185)]}]}}}
    lines = m.main_lines(snap)
    assert len(lines) == 1 and lines[0]["point"] == 0.5 and lines[0]["books"] == 2 and lines[0]["over_dec_best"] == 1 + 100 / 240


def test_collect_end_to_end_is_as_of_and_voids_absent_players(tmp_path) -> None:
    m = _load("mlb_signal_tests")
    hit, pit = [], []
    for i in range(3):
        day, g = f"2026-06-0{i + 1}", str(100 + i)
        hit.append({"date": day, "game_type": "R", "game_pk": g, "player_id": 7, "player_name": "Aaron Judge", "team": NYY,
                    "opponent": SF, "pa": 4, "h": i, "tb": i, "so": 1})
        pit.append({"date": day, "game_type": "R", "game_pk": g, "player_id": 9, "player_name": "Logan Webb", "team": SF,
                    "opponent": NYY, "is_starter": 1, "k": 5 + i, "batters_faced": 25})
    _csv(tmp_path / "hit.csv", HIT_COLS, hit)
    _csv(tmp_path / "pit.csv", PIT_COLS, pit)
    raw = tmp_path / "raw" / "2026"
    raw.mkdir(parents=True)
    with gzip.open(raw / "statcast_2026-06-01_2026-06-03.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["game_date", "game_type", "batter", "pitcher", "pitch_type", "events", "woba_value"])
        w.writeheader()
        for i in range(3):
            w.writerow({"game_date": f"2026-06-0{i + 1}", "game_type": "R", "batter": 7, "pitcher": 9, "pitch_type": "FF",
                        "events": "single", "woba_value": 0.9})
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "a.json").write_text(json.dumps({"by_date": {"2025-07-01": {"9": {"7": {"pa": 10, "hits": 5}}},
                                                            "2026-06-02": {"9": {"7": {"pa": 99, "hits": 99}}}}}), encoding="utf-8")
    odds = tmp_path / "odds"
    odds.mkdir()
    def mk(key, player, point):
        return {"key": key, "outcomes": [{"name": "Over", "description": player, "price": -110, "point": point},
                                         {"name": "Under", "description": player, "price": -110, "point": point}]}
    (odds / "102.json").write_text(json.dumps({"game": "102", "date": "2026-06-03", "snap": {"data": {"bookmakers": [
        {"key": "dk", "markets": [mk("batter_hits", "Aaron Judge", 1.5), mk("pitcher_strikeouts", "Logan Webb", 6.5),
                                  mk("batter_hits", "Bench Guy", 0.5)]}]}}}), encoding="utf-8")
    counts: dict = defaultdict(int)
    recs = m.collect(odds, tmp_path / "hit.csv", tmp_path / "pit.csv", tmp_path / "raw", legacy, counts, with_outcomes=True)
    by = {r["market"]: r for r in recs}
    assert counts["void_no_box_row"] == 1                     # Bench Guy has no box row
    assert by["batter_hits"]["y_over"] == 1.0                 # 2 hits > 1.5
    assert by["batter_hits"]["feats"]["bvp_pa"] == 12         # 10 pre-2026 + the 2 earlier 2026 days; 2026 legacy ignored
    assert by["pitcher_strikeouts"]["y_over"] == 1.0          # 7 K > 6.5
    assert by["batter_hits"]["window"] == "discover"
