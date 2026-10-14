"""NHL matchup signals: names, game-log parsing, as-of features, rules, saves lines, forward family (signal-engine-nhl)."""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

from syndicate.features.shared import matchup_signals_nhl as nhl


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_name_key_joins_full_names_to_game_log_names() -> None:
    assert nhl.name_key("Brad Marchand") == nhl.name_key("{'default': 'B. Marchand'}") == "b marchand"
    assert nhl.name_key("James van Riemsdyk") == nhl.name_key("J. van Riemsdyk")
    assert nhl.name_key("Tim Stützle") == nhl.name_key("T. Stutzle")
    assert nhl.game_type("2026020015") == "02" and nhl.game_type("2026010006") == "01"


COLS = ["gamePk", "date", "team", "player_id", "player", "primary_position", "role", "shots", "goals", "assists", "blocked",
        "timeOnIce", "saves", "shotsAgainst", "decision"]


def _log(path: Path, games: list[tuple]) -> None:
    """games: (pk, day, [(team, pid, name, role, shots, toi, saves, goals, assists)])"""
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for pk, day, players in games:
            for team, pid, name, role, shots, toi, saves, goals, assists in players:
                w.writerow({"gamePk": pk, "date": f"{day}T16:00:00Z", "team": team, "player_id": pid,
                            "player": "{'default': '%s'}" % name, "role": role, "shots": shots, "goals": goals,
                            "assists": assists, "timeOnIce": toi, "saves": saves, "shotsAgainst": ""})


def _season(path: Path, n: int = 12) -> None:
    games = []
    for i in range(n):
        day = f"2026-11-{i + 1:02d}"
        toi = "15:00" if i < 9 else "19:00"          # a TOI jump over the last 3 games
        games.append((f"20260200{i + 10:02d}", day, [
            ("FLA", "1", "B. Marchand", "skater", 3, toi, "", 1, 0),
            ("FLA", "2", "S. Bobrovsky", "goalie", 0, "60:00", 25, 0, 0),
            ("CHI", "3", "C. Bedard", "skater", 30, "20:00", "", 0, 1),   # CHI shoots 30 a game
            ("CHI", "4", "S. Knight", "goalie", 0, "60:00", 2, 0, 0)]))
    games.append(("2026010001", "2026-09-20", [("FLA", "1", "B. Marchand", "skater", 9, "30:00", "", 3, 3)]))  # preseason
    _log(path, games)


def test_as_of_features_read_only_earlier_regular_season_games(tmp_path) -> None:
    path = tmp_path / "log.csv"
    _season(path)
    rows = nhl.load_game_log([path])
    asof = nhl.AsOf(rows)
    fla = asof.team("FLA", "2026", "2026-11-13")
    assert fla["games"] == 12 and fla["sa_pg"] == 30.0 and fla["sf_pg"] == 3.0 and fla["rest_days"] == 1
    assert asof.team("FLA", "2026", "2026-11-04")["games"] == 3 and "sa_pg" not in asof.team("FLA", "2026", "2026-11-04")
    sk = asof.skater("1", "2026", "2026-11-13")
    assert sk["games"] == 12 and sk["toi_l3"] == 19.0 and sk["toi_base"] == 15.0 and sk["toi_trend"] == 4.0
    assert asof.skater("1", "2026", "2026-11-12")["toi_trend"] == round(((15 + 19 + 19) / 3) - 15, 3)  # day 12 unseen


def test_rules_follow_thresholds_and_never_fire_on_unknowns() -> None:
    t = nhl.THRESHOLDS
    assert nhl.saves_fires({"opp_sf_pg": 31.0, "team_sa_trend": 4.0, "team_rest_days": 1}, t) == [
        "nhl.saves_opp_volume_high", "nhl.saves_team_leaky", "nhl.saves_team_b2b"]
    assert nhl.saves_fires({"opp_sf_pg": 23.0}, t) == ["nhl.saves_opp_volume_low"]
    assert nhl.saves_fires({}, t) == []
    assert nhl.skater_fires({"toi_trend": 2.5, "opp_sa_pg": 29.0}, t) == ["nhl.toi_up", "nhl.opp_allows_shots"]
    assert nhl.skater_fires({"toi_trend": -2.3, "opp_sa_pg": 23.9}, t) == ["nhl.toi_down", "nhl.opp_suppresses_shots"]
    assert nhl.skater_fires({"toi_trend": 9.0}, {**t, "toi_up": 0.0}) == []
    assert nhl.skater_eligible("nhl.toi_up", {"toi_trend": 0.1}) and not nhl.skater_eligible("nhl.toi_up", {})


def test_saves_main_line_is_the_most_two_sided_point() -> None:
    lift = _load("nhl_saves_lift")
    def book(key, point, over, under):
        return {"key": key, "markets": [{"key": "player_total_saves", "outcomes": [
            {"name": "Over", "description": "Arvid Soderblom", "price": over, "point": point},
            {"name": "Under", "description": "Arvid Soderblom", "price": under, "point": point}]}]}
    snap = {"snap": {"data": {"bookmakers": [book("dk", 26.5, -110, -110), book("fd", 26.5, -115, -105),
                                             book("mgm", 25.5, -130, 100)]}}}
    lines = lift.saves_main_lines(snap)
    assert len(lines) == 1 and lines[0]["point"] == 26.5 and lines[0]["books"] == 2
    assert lines[0]["under_dec_best"] == 1 + 100 / 105


def test_forward_family_rows_fire_per_signal_and_unders_take_every_line() -> None:
    fwd = _load("grade_nhl_forward")
    recs = [{"game": "g1", "day": "2026-11-01", "stat": "shots", "y_over": 0.0, "p_over": 0.5, "best_under": -110,
             "feats": {"toi_trend": 3.0, "opp_sa_pg": 26.0}},
            {"game": "g2", "day": "2026-11-01", "stat": "assists", "y_over": 1.0, "p_over": 0.4, "best_under": 120,
             "feats": {"toi_trend": None, "opp_sa_pg": None}}]
    rows = fwd.hypothesis_rows(recs)
    assert len(rows["K1"]) == 1 and rows["K1"][0]["y"] == 0.0 and "pnl" not in rows["K1"][0]   # an over: no under pnl
    assert rows["K2"] == [] and rows["K3"] == [] and rows["K4"] == []
    assert len(rows["K5"]) == 2 and rows["K5"][0]["pnl"] == pytest.approx(100 / 110) and rows["K5"][1]["pnl"] == -1.0
    rep = fwd.report(recs, final=False, counts={})
    assert rep["hypotheses"]["K5"]["verdict"].startswith("INTERIM") and "holm" not in rep


def test_registry_covers_every_rule() -> None:
    names = {"nhl.saves_opp_volume_high", "nhl.saves_opp_volume_low", "nhl.saves_team_leaky", "nhl.saves_team_b2b",
             "nhl.saves_under_bias", "nhl.toi_up", "nhl.toi_down", "nhl.opp_allows_shots", "nhl.opp_suppresses_shots",
             "nhl.skater_under_bias"}
    assert set(nhl.NHL_REGISTRY) == names


def test_saves_and_skater_history_results_are_recorded() -> None:
    for name in ("nhl.saves_opp_volume_high", "nhl.saves_opp_volume_low", "nhl.saves_team_leaky", "nhl.saves_team_b2b",
                 "nhl.saves_under_bias"):
        assert nhl.NHL_REGISTRY[name].status == "null" and nhl.NHL_REGISTRY[name].evidence["confirm_n"] > 0
    for name in ("nhl.toi_up", "nhl.toi_down", "nhl.opp_allows_shots", "nhl.opp_suppresses_shots", "nhl.skater_under_bias"):
        spec = nhl.NHL_REGISTRY[name]
        assert spec.status == "null" and spec.evidence["confirm_n"] > 0 and "forward" in spec.evidence


def _snap(*books):
    return {"snap": {"data": {"bookmakers": [{"key": k, "markets": ms} for k, ms in books]}}}


def _mk(key, player, point, over, under=None):
    outs = [{"name": "Over", "description": player, "price": over, "point": point}]
    if under is not None:
        outs.append({"name": "Under", "description": player, "price": under, "point": point})
    return {"key": key, "outcomes": outs}


def test_history_main_lines_per_player_market_two_sided_only() -> None:
    h = _load("nhl_skater_history_lift")
    snap = _snap(("draftkings", [_mk("player_shots_on_goal", "Brad Marchand", 2.5, -110, -110),
                                 _mk("player_goals", "Brad Marchand", 0.5, 150)]),          # one-sided: never a line
                 ("fanduel", [_mk("player_shots_on_goal", "Brad Marchand", 2.5, -120, 100),
                              _mk("player_shots_on_goal", "Brad Marchand", 3.5, 140, -180)]))
    lines = h.snapshot_main_lines(snap)
    assert len(lines) == 1 and lines[0]["stat"] == "shots" and lines[0]["point"] == 2.5 and lines[0]["books"] == 2
    assert lines[0]["under_dec_best"] == 2.0


def test_history_evaluate_splits_windows_and_k5_takes_every_line() -> None:
    h = _load("nhl_skater_history_lift")
    recs = []
    for i in range(12):
        w = "discover" if i < 6 else "confirm"
        recs.append({"window": w, "game": f"a{i}", "stat": "shots", "y_over": 1.0, "p_over": 0.5,
                     "under_dec_best": 1.9, "under_dec_median": 1.9, "feats": {"toi_trend": 3.0, "opp_sa_pg": 26.0}})
        recs.append({"window": w, "game": f"b{i}", "stat": "assists", "y_over": 0.0, "p_over": 0.5,
                     "under_dec_best": 1.9, "under_dec_median": 1.9, "feats": {"toi_trend": 0.0, "opp_sa_pg": None}})
    rep = h.evaluate(recs)
    k1 = rep["signals"]["K1"]
    assert k1["confirm"]["fired"]["n"] == 6 and k1["confirm"]["fired"]["residual"] == 0.5 and k1["verdict"] == "SUPPORTED"
    assert k1["confirm"]["baseline"]["n"] == 0   # the 0.0-trend lines are assists, not a K1 market
    assert rep["K5_unders"]["all"]["confirm"]["residual"]["n"] == 12
    assert rep["K5_unders"]["assists"]["confirm"]["residual"]["residual"] == 0.5


def test_pull_summarizes_a_snapshot_without_secrets() -> None:
    p = _load("nhl_skater_props_pull")
    s = p.summarize({"timestamp": "t", "data": {"bookmakers": [{"key": "dk", "markets": [_mk("player_points", "A", 0.5, -110, -110)]}]}})
    assert s == {"timestamp": "t", "books": ["dk"], "outcomes_by_market": {"player_points": 2}}
    assert p.CREDITS_PER_GAME == 40


def test_saves_v3_tests_only_new_games_and_holms_the_two_leads() -> None:
    lift = _load("nhl_saves_lift")
    graded = []
    for i in range(20):
        for source, y in (("odds_saves_rest", 1.0), ("odds_saves", 0.0)):
            graded.append({"source": source, "game": f"{source}{i}", "y_over": y, "p_over": 0.5, "under_dec_best": 1.9,
                           "under_dec_median": 1.9, "feats": {"opp_sf_pg": 31.0, "team_sa_trend": 4.0, "team_rest_days": 2}})
    rep = lift.lift_new(graded)
    assert rep["graded"] == {"new": 20, "full_season": 40}
    leaky = rep["new_games"]["nhl.saves_team_leaky"]["fired"]
    assert leaky["n"] == 20 and leaky["residual"] == 0.5          # the v1 games (all lost) are not in the test
    assert rep["full_season"]["nhl.saves_team_leaky"]["fired"]["residual"] == 0.0
    assert rep["verdicts"] == {"nhl.saves_team_leaky": "SUPPORTED", "nhl.saves_opp_volume_high": "SUPPORTED"}
