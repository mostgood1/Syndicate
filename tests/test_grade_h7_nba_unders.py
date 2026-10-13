"""H7 forward grader: the registered bet, read exactly (lane signal-engine-nba)."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

from syndicate.features.shared import matchup_signals as ms


def _load():
    spec = importlib.util.spec_from_file_location(
        "grade_h7_nba_unders", Path(__file__).resolve().parents[1] / "scripts" / "grade_h7_nba_unders.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CSV_HEADER = ["snapshot_ts", "event_id", "commence_time", "bookmaker", "bookmaker_title", "market", "outcome_name",
              "player_name", "point", "price", "last_update", "home_team", "away_team"]
LOG_HEADER = ["game_id", "date", "season", "season_type", "TEAM_ABBREVIATION", "opponent", "home_away", "PLAYER_ID",
              "PLAYER_NAME", "position", "starter", "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV", "source"]
TIP = "2026-11-03T00:00:00Z"  # 7 pm Central on 2026-11-02; cutoff 23:15Z


def _quote(snap, book, market, player, point, over, under, event="e1", commence=TIP):
    base = {"snapshot_ts": snap, "event_id": event, "commence_time": commence, "bookmaker": book, "market": market,
            "player_name": player, "point": point}
    return [dict(base, side="over", price=over), dict(base, side="under", price=under)]


def test_main_line_reads_each_books_last_snapshot_before_the_scheduled_tip() -> None:
    g = _load()
    rows = []
    rows += _quote("2026-11-02T20:00:00Z", "draftkings", "player_rebounds", "Big Man", 10.5, -110, -110)
    rows += _quote("2026-11-02T22:00:00Z", "draftkings", "player_rebounds", "Big Man", 11.5, -110, -110)  # dk moved
    rows += _quote("2026-11-02T22:00:00Z", "fanduel", "player_rebounds", "Big Man", 11.5, -105, -115)
    rows += _quote("2026-11-02T22:00:00Z", "pinnacle", "player_rebounds", "Big Man", 11.5, -120, 110)  # not a US book
    rows += _quote("2026-11-02T22:00:00Z", "betmgm", "player_rebounds", "Big Man", 10.5, -110, -110)
    # with dk's stale 10.5 kept, 10.5 would tie 11.5 at 3 books and win the tie (p_over exactly 0.5)
    rows += _quote("2026-11-02T22:00:00Z", "betrivers", "player_rebounds", "Big Man", 10.5, -110, -110)
    # in-play row: OddsAPI rewrote commence to the actual start; a per-row cutoff (23:25Z) would admit this 23:20Z quote
    rows += _quote("2026-11-02T23:20:00Z", "draftkings", "player_rebounds", "Big Man", 14.5, -110, -110,
                   commence="2026-11-03T00:10:00Z")
    rows += _quote("2026-11-02T23:59:00Z", "fanduel", "player_rebounds", "Big Man", 12.5, -110, -110)  # after cutoff
    lines = g.main_lines(rows)
    assert len(lines) == 1
    line = lines[0]
    assert line["point"] == 11.5 and line["books"] == 3      # dk's dropped 10.5 does not count for 10.5
    assert line["best_us_under"] == -110                     # best of dk -110 / fd -115; Pinnacle +110 excluded
    assert line["date"] == "2026-11-02"


def test_change_log_carries_an_unchanged_side_forward_and_snapshots_do_not() -> None:
    g = _load()
    rows = _quote("2026-11-02T20:00:00Z", "draftkings", "player_threes", "Big Man", 1.5, -110, -110)
    rows.append({"snapshot_ts": "2026-11-02T22:00:00Z", "event_id": "e1", "commence_time": TIP, "bookmaker": "draftkings",
                 "market": "player_threes", "player_name": "Big Man", "point": 1.5, "side": "under", "price": -125})
    logged = g.main_lines(rows, change_log=True)
    assert len(logged) == 1 and logged[0]["best_us_under"] == -125
    assert g.main_lines(rows, change_log=False) == []  # a snapshot without the over side is not two-sided


def test_change_log_drops_a_point_the_book_moved_off() -> None:
    g = _load()
    t1, t2 = "2026-11-02T20:00:00Z", "2026-11-02T22:00:00Z"
    rows = _quote(t1, "fanduel", "player_rebounds", "Big Man", 10.5, -110, -110)
    rows += _quote(t2, "fanduel", "player_rebounds", "Big Man", 11.5, -110, -110)  # the log never records 10.5 leaving
    rows += _quote(t2, "betrivers", "player_rebounds", "Big Man", 11.5, -105, -115)
    rows += _quote(t2, "pinnacle", "player_rebounds", "Big Man", 11.5, -105, -115)
    rows += _quote(t2, "betmgm", "player_rebounds", "Big Man", 10.5, -110, -110)
    rows += _quote(t2, "draftkings", "player_rebounds", "Big Man", 10.5, -110, -110)
    # fd's stale 10.5 would make 10.5 tie 11.5 at 3 books and win the tie (p_over 0.5 exactly)
    lines = g.main_lines(rows, change_log=True)
    assert len(lines) == 1 and lines[0]["point"] == 11.5 and lines[0]["books"] == 3


def _write_csv(path: Path, header, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _props(rows):
    out = []
    for r in rows:
        out.append({"snapshot_ts": r["snapshot_ts"], "event_id": r["event_id"], "commence_time": r["commence_time"],
                    "bookmaker": r["bookmaker"], "bookmaker_title": r["bookmaker"], "market": r["market"],
                    "outcome_name": r["side"].title(), "player_name": r["player_name"], "point": r["point"],
                    "price": r["price"], "last_update": r["snapshot_ts"], "home_team": "H", "away_team": "A"})
    return out


def _log(day, name, minutes, reb=0, ast=0, fg3=0, game="g1"):
    return {"game_id": game, "date": day, "season": "2026", "season_type": "regular", "TEAM_ABBREVIATION": "HOU",
            "opponent": "OKC", "home_away": "home", "PLAYER_ID": name, "PLAYER_NAME": name, "position": "F",
            "starter": "1", "MIN": minutes, "PTS": 10, "REB": reb, "AST": ast, "FG3M": fg3, "STL": 0, "BLK": 0, "TOV": 0,
            "source": "espn"}


def _fixture(root: Path) -> None:
    raw = root / "nba_source" / "data" / "raw"
    snap = "2026-11-02T22:00:00Z"
    quotes = []
    for book in ("draftkings", "fanduel"):
        quotes += _quote(snap, book, "player_rebounds", "Big Man", 10.5, -115, -105 if book == "fanduel" else -110)
        quotes += _quote(snap, book, "player_points", "Big Man", 20.5, -110, -110)  # not an H7 market
        quotes += _quote(snap, book, "player_rebounds", "Bench Guy", 4.5, -110, -110)
        quotes += _quote(snap, book, "player_threes", "Push Guy", 2.0, -110, -110)
        quotes += _quote(snap, book, "player_assists", "Dnp Guy", 5.5, -110, -110)
        quotes += _quote(snap, book, "player_rebounds_assists", "Combo Guy", 12.5, -110, -110, event="e2")
    _write_csv(raw / "odds_nba_player_props_history_2026-11-02.csv", CSV_HEADER, _props(quotes))
    later = _quote("2026-11-04T22:00:00Z", "draftkings", "player_rebounds", "Big Man", 10.5, -110, -110, event="e3",
                   commence="2026-11-05T00:00:00Z")
    later += _quote("2026-11-04T22:00:00Z", "fanduel", "player_rebounds", "Big Man", 10.5, -110, -110, event="e3",
                    commence="2026-11-05T00:00:00Z")
    _write_csv(raw / "odds_nba_player_props_2026-11-04.csv", CSV_HEADER, _props(later))  # fallback source
    ms.write_signal_table(root, "nba", "2026-27", "2026-11-02", [
        {"player_key": "big man", "min_prior10": 36.0}, {"player_key": "bench guy", "min_prior10": 22.0},
        {"player_key": "push guy", "min_prior10": 34.0}, {"player_key": "dnp guy", "min_prior10": 33.0},
        {"player_key": "combo guy", "min_prior10": 31.0}])
    # no table for 2026-11-04: the grader rebuilds it from games strictly before that date
    _write_csv(root / "nba_source" / "data" / "processed" / "player_game_log_2026.csv", LOG_HEADER, [
        _log("2026-11-02", "Big Man", 36, reb=8),                     # under 10.5 wins at -105
        _log("2026-11-02", "Bench Guy", 22, reb=2),
        _log("2026-11-02", "Push Guy", 34, fg3=2),                    # push -> void
        _log("2026-11-02", "Combo Guy", 31, reb=7, ast=6, game="g2"),  # 13 > 12.5 -> under loses
        _log("2026-11-04", "Big Man", 38, reb=12, game="g3"),         # over 10.5 -> under loses
    ])


def test_grade_applies_every_registered_gate_and_voids(tmp_path) -> None:
    g = _load()
    _fixture(tmp_path)
    rep = g.grade(tmp_path, "2026-11-04")
    c = rep["counts"]
    assert c["graded"] == 3 and c["below_min30"] == 1 and c["void_push"] == 1 and c["void_dnp_or_missing"] == 1
    assert c["signal_tables_rebuilt"] == 1
    assert rep["price_sources_by_date"] == {"props_history": 1, "props_snapshot": 1}
    p = rep["primary_roi_best_us_price"]
    assert p["n"] == 3 and p["games"] == 3
    assert abs(p["roi_pct"] - round(100 * ((100 / 105) - 1 - 1) / 3, 2)) < 1e-9
    assert rep["verdict"].startswith("INTERIM") and rep["final_read"] is False
    assert rep["by_market"]["player_rebounds"]["n"] == 2 and rep["by_market"]["player_threes"]["n"] == 0
    assert rep["secondary_residual_vs_shin"]["n"] == 3


def test_final_read_needs_a_ci_above_zero_and_through_is_capped(tmp_path) -> None:
    g = _load()
    _fixture(tmp_path)
    rep = g.grade(tmp_path, "2027-06-30")
    assert rep["through"] == "2027-04-11" and rep["final_read"] is True
    assert rep["verdict"] == "NOT SUPPORTED"  # 3 games: no CI, so the bar cannot be met


def test_cli_writes_the_report(tmp_path) -> None:
    g = _load()
    _fixture(tmp_path)
    out = tmp_path / "h7.json"
    assert g.main(["--data-root", str(tmp_path), "--through", "2026-11-04", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["counts"]["graded"] == 3
    assert g.main(["--data-root", "", "--out", str(out)]) == 2


def test_holm_family_rule_is_step_down_and_missing_p_never_passes() -> None:
    g = _load()
    assert g.holm({"H7": 0.010, "H7_late": 0.020}) == {"H7": True, "H7_late": True}
    assert g.holm({"H7": 0.020, "H7_late": 0.010}) == {"H7": True, "H7_late": True}
    assert g.holm({"H7": 0.900, "H7_late": 0.012}) == {"H7": False, "H7_late": True}
    assert g.holm({"H7": 0.900, "H7_late": 0.013}) == {"H7": False, "H7_late": False}  # alone, 0.013 < 0.025 would pass
    assert g.holm({"H7": 0.001, "H7_late": None}) == {"H7": True, "H7_late": False}


def test_roi_p_value_is_the_bootstrap_share_at_or_below_zero() -> None:
    g = _load()
    wins = [{"game": f"g{i}", "pnl": 1.0} for i in range(10)]
    assert g.roi(wins, B=200)["p_one_sided"] == round(1 / 201, 5)   # no resample can reach ROI <= 0
    losses = [{"game": f"g{i}", "pnl": -1.0} for i in range(10)]
    assert g.roi(losses, B=200)["p_one_sided"] == 1.0
    assert g.roi(wins[:4], B=200)["p_one_sided"] is None            # < 5 games: no bootstrap, no p


def test_h7_late_grades_only_games_on_or_after_its_start(tmp_path, monkeypatch) -> None:
    g = _load()
    _fixture(tmp_path)
    monkeypatch.setattr(g, "LATE_START", "2026-11-03")
    rep = g.grade(tmp_path, "2026-11-04")
    late = rep["h7_late"]
    assert late["primary_roi_best_us_price"]["n"] == 1 and late["primary_roi_best_us_price"]["roi_pct"] == -100.0
    assert rep["primary_roi_best_us_price"]["n"] == 3                 # H7 keeps the whole season
    assert late["verdict"].startswith("INTERIM") and "supported" not in rep["family"]
    final = g.grade(tmp_path, "2027-06-30")
    assert final["family"]["supported"] == {"H7": False, "H7_late": False}
    assert final["h7_late"]["verdict"] == "NOT SUPPORTED"
