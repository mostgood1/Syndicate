"""WNBA signals v1: the purchase's game/event selection and the registered tests (lane signal-engine-wnba)."""
from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from pathlib import Path


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


COLS = ["game_id", "date", "season", "season_type", "TEAM_ABBREVIATION", "opponent", "home_away", "PLAYER_ID",
        "PLAYER_NAME", "position", "starter", "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV", "source"]


def _log(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, 0) for c in COLS})


def _row(game, day, team, name, minutes, pts=10, reb=5, ast=3, fg3=1, stype="regular", starter=1):
    return {"game_id": game, "date": day, "season": 2026, "season_type": stype, "TEAM_ABBREVIATION": team,
            "PLAYER_NAME": name, "starter": starter, "MIN": minutes, "PTS": pts, "REB": reb, "AST": ast, "FG3M": fg3}


def test_purchase_takes_regular_season_games_between_real_clubs_only(tmp_path) -> None:
    p = _load("wnba_props_pull")
    path = tmp_path / "log.csv"
    _log(path, [_row("1", "2026-07-08", "LVA", "A", 30), _row("1", "2026-07-08", "NYL", "B", 30),
                _row("2", "2026-07-25", "COOP", "C", 20), _row("2", "2026-07-25", "SPO", "D", 20),        # All-Star
                _row("3", "2026-10-09", "LVA", "A", 30, stype="playoffs"), _row("3", "2026-10-09", "NYL", "B", 30)])
    games = p.regular_season_games(path)
    assert list(games) == ["1"] and games["1"]["teams"] == frozenset({"las vegas aces", "new york liberty"})
    ev = {"id": "e1", "home_team": "New York Liberty", "away_team": "Las Vegas Aces", "commence_time": "2026-07-08T23:00:00Z"}
    late = dict(ev, id="e2", commence_time="2026-07-10T23:00:00Z")
    assert p.match_event(games["1"], [late, ev])["id"] == "e1" and p.match_event(games["1"], [late]) is None
    assert p.CREDITS_PER_GAME == 80


def test_minute_thresholds_are_the_nba_rules_scaled_to_40_minutes() -> None:
    w = _load("wnba_signal_tests")
    assert (w.TREND, w.B2B_MIN, w.HEAVY_MIN) == (3.3, 23.3, 25.0)
    assert w.wnba_fires({"min_trend": 3.4, "min_prior10": 30}) == ["wnba.minutes_trend_up"]
    assert w.wnba_fires({"min_trend": -3.3, "rest_days": 1, "min_prior10": 24.0}) == ["wnba.minutes_trend_down", "wnba.b2b"]
    assert w.wnba_fires({"rest_days": 1, "min_prior10": 23.0}) == []
    assert w.wnba_fires({}) == []


def test_main_line_is_per_player_market_two_sided() -> None:
    w = _load("wnba_signal_tests")
    def mk(key, player, point, over, under):
        return {"key": key, "outcomes": [{"name": "Over", "description": player, "price": over, "point": point},
                                         {"name": "Under", "description": player, "price": under, "point": point}]}
    snap = {"snap": {"data": {"bookmakers": [
        {"key": "dk", "markets": [mk("player_points", "A'ja Wilson", 24.5, -110, -110)]},
        {"key": "fd", "markets": [mk("player_points", "A'ja Wilson", 24.5, -115, -105),
                                  mk("player_steals", "A'ja Wilson", 1.5, -110, -110)]}]}}}
    lines = w.main_lines(snap)
    assert len(lines) == 1 and lines[0]["player_key"] == "aja wilson" and lines[0]["books"] == 2
    assert lines[0]["under_dec_best"] == 1 + 100 / 105


def test_collect_joins_outcomes_voids_dnp_and_drops_the_all_star_game(tmp_path) -> None:
    w = _load("wnba_signal_tests")
    path = tmp_path / "log.csv"
    rows = []
    for i in range(14):
        day = f"2026-07-{i + 1:02d}"
        rows += [_row(f"g{i}", day, "LVA", "A'ja Wilson", 30 if i < 13 else 34, pts=20 + i),
                 _row(f"g{i}", day, "NYL", "Bench Player", 10 if i < 13 else 0, pts=2)]
    rows += [_row("as", "2026-07-25", "COOP", "A'ja Wilson", 99), _row("as", "2026-07-25", "SPO", "Other", 99)]
    _log(path, rows)
    odds = tmp_path / "odds"
    odds.mkdir()
    def snap(player, point):
        mk = {"key": "player_points", "outcomes": [{"name": "Over", "description": player, "price": -110, "point": point},
                                                   {"name": "Under", "description": player, "price": -110, "point": point}]}
        return {"key": "dk", "markets": [mk]}
    (odds / "g13.json").write_text(json.dumps({"game": "g13", "date": "2026-07-14", "snap": {"data": {"bookmakers": [
        snap("A'ja Wilson", 30.5), snap("Bench Player", 1.5)]}}}), encoding="utf-8")
    counts: dict = defaultdict(int)
    recs = w.collect(path, odds, counts)
    assert counts["void_no_outcome_or_dnp"] == 1                     # the bench player logged 0 minutes
    assert len(recs) == 1 and recs[0]["y_over"] == 1.0 and recs[0]["window"] == "confirm"
    assert recs[0]["feats"]["games_prior"] == 13                     # the All-Star game is not a prior game
    assert recs[0]["feats"]["min_prior10"] == 30.0


def test_evaluate_reports_signals_and_the_unders_tests() -> None:
    w = _load("wnba_signal_tests")
    recs = []
    for i in range(12):
        window = "discover" if i < 6 else "confirm"
        recs.append({"window": window, "game": f"g{i}", "market": "player_points", "y_over": 0.0, "p_over": 0.5,
                     "under_dec_best": 1.9, "under_dec_median": 1.9, "feats": {"min_trend": -4.0, "min_prior10": 26.0}})
    rep = w.evaluate(recs)
    assert rep["signals"]["wnba.minutes_trend_down"]["confirm"]["fired"]["n"] == 6
    assert rep["signals"]["wnba.minutes_trend_down"]["verdict"] == "SUPPORTED"
    assert rep["unders"]["W6a"]["confirm"]["residual"]["n"] == 6 and rep["unders"]["W6b"]["confirm"]["residual"]["n"] == 6
