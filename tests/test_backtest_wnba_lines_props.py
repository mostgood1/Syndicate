"""Tests for scripts/backtest_wnba_lines_props.py (lane `wnba-lines-props-backtest`).

The decisions these pin are the ones a wrong answer would hide inside a plausible number: the ESPN tri-code join
(the reason the weekly WNBA backtest joins 0 games), the de-vig at the modal line, the board's ladder threshold
(floor(line) + 1, gaps in the ladder), the as-of truncation (no row dated >= D survives), and the
comparison label (diagnostic only -- every line is its own decision, user 2026-10-02).
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bt_wnba", ROOT / "scripts" / "backtest_wnba_lines_props.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)  # type: ignore[union-attr]


def _event(eid, date, home, away, hs, as_, ls_h, ls_a, slug="regular-season", ctype="STD", completed=True):
    def comp(tri, name, score, ls, ha):
        return {"homeAway": ha, "score": str(score), "team": {"abbreviation": tri, "displayName": name},
                "linescores": [{"value": v} for v in ls]}
    return {"id": eid, "date": date, "season": {"slug": slug},
            "status": {"type": {"completed": completed}},
            "competitions": [{"type": {"abbreviation": ctype},
                              "competitors": [comp(home[0], home[1], hs, ls_h, "home"), comp(away[0], away[1], as_, ls_a, "away")]}]}


def _write_sb(d: Path, date: str, events):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"sb_{date}.json").write_text(json.dumps({"events": events}), encoding="utf-8")


def test_espn_tricodes_map_to_syndicate_codes_and_exhibitions_are_dropped(tmp_path):
    # Production 2026-10-01: ESPN says LV/IND, Syndicate's cards say LVA/IND. GS/LA/NY/CONN differ the same way.
    _write_sb(tmp_path, "2026-10-01", [
        _event("401", "2026-10-02T01:08Z", ("LV", "Las Vegas Aces"), ("IND", "Indiana Fever"), 94, 83,
               [20, 25, 24, 25], [22, 20, 21, 20], slug="post-season", ctype="RD16"),
        _event("402", "2026-10-02T01:08Z", ("COOP", "Team Coop"), ("SPO", "Team Spo"), 100, 99,
               [25, 25, 25, 25], [25, 25, 25, 24], ctype="ALLSTAR"),
        _event("403", "2026-10-02T23:00Z", ("GS", "Golden State Valkyries"), ("NY", "New York Liberty"), 0, 0,
               [], [], completed=False),
    ])
    g = B.load_games(tmp_path)
    assert list(g) == ["401"]
    assert (g["401"]["home"], g["401"]["away"], g["401"]["phase"]) == ("LVA", "IND", "playoff")
    assert g["401"]["seg"]["full"] == (11, 177)
    assert g["401"]["seg"]["h1"] == (3.0, 87.0)
    assert g["401"]["seg"]["q4"] == (5.0, 45.0)


def test_h2_includes_overtime(tmp_path):
    _write_sb(tmp_path, "2026-07-01", [
        _event("9", "2026-07-01T23:00Z", ("SEA", "Seattle Storm"), ("MIN", "Minnesota Lynx"), 90, 86,
               [20, 20, 20, 20, 10], [20, 20, 20, 20, 6])])
    g = B.load_games(tmp_path)["9"]
    assert g["ot"] is True
    assert g["seg"]["h2"] == (4.0, 96.0)          # q3 + q4 + OT: 50 - 46, 50 + 46
    assert g["seg"]["full"] == (4, 176)


def test_devig_takes_the_modal_line_and_drops_one_sided(tmp_path):
    g = {"1": {"home_name": "H", "away_name": "A"}}
    books = []
    for key, line in (("b1", 160.5), ("b2", 160.5), ("b3", 158.5)):
        books.append({"key": key, "markets": [{"key": "totals", "outcomes": [
            {"name": "Over", "point": line, "price": -120}, {"name": "Under", "point": line, "price": 100}]}]})
    props = [{"key": "b1", "markets": [
        {"key": "player_points", "outcomes": [
            {"name": "Over", "description": "A'ja Wilson", "point": 24.5, "price": -110},
            {"name": "Under", "description": "A'ja Wilson", "point": 24.5, "price": -110}]},
        {"key": "player_double_double", "outcomes": [{"name": "Yes", "description": "A'ja Wilson", "price": 150}]}]}]
    (tmp_path / "1.json").write_text(json.dumps({"game": {"timestamp": "t", "data": {"bookmakers": books}},
                                                 "props": {"data": {"bookmakers": props}}}), encoding="utf-8")
    out, cnt = B.load_book(tmp_path, g)
    tot = out["1"]["game"][("totals", "full")]
    assert tot["line"] == 160.5 and tot["books"] == 2
    assert tot["p"] == pytest.approx((120 / 220) / (120 / 220 + 0.5))
    assert out["1"]["props"][("aja wilson", "player_points")]["p"] == pytest.approx(0.5)
    assert ("aja wilson", "player_double_double") not in out["1"]["props"]
    assert cnt["prop_one_sided:player_double_double"] == 1


def test_ladder_threshold_is_floor_plus_one_and_respects_gaps():
    f = B.ladder_over([{"total": 10, "hitProb": 0.9}, {"total": 13, "hitProb": 0.4}, {"total": 15, "hitProb": 0.1}])
    assert f(12.5) == 0.4      # over 12.5 -> >= 13
    assert f(11.5) == 0.4      # >= 12 is in a gap: zero mass at 12, so P(>=12) = P(>=13)
    assert f(12.0) == 0.4      # over 12 (whole) -> >= 13
    assert f(20.5) == 0.0      # beyond the highest simulated total: an honest 0, not None


def test_histogram_over_is_strict():
    f = B.hist_over({150.0: 1, 160.0: 2, 170.0: 1})
    assert f(160.0) == pytest.approx(0.25)
    assert f(159.5) == pytest.approx(0.75)


def test_comparison_label_names_which_reference_the_model_beats():
    below = {"point": -0.1, "ci95": [-0.2, -0.01]}
    straddle = {"point": -0.1, "ci95": [-0.2, 0.05]}
    above = {"point": 0.1, "ci95": [0.02, 0.2]}
    assert B._gate(below, below, 100, 30) == "beats baseline AND book"
    assert B._gate(below, straddle, 100, 30).startswith("beats baseline, not book")
    assert B._gate(straddle, below, 100, 30) == "beats book, not baseline"
    assert B._gate(above, above, 100, 30) == "no skill (worse than baseline); worse than book"
    assert B._gate(below, below, 10, 30) == "insufficient"


def test_boot_ci_clusters_by_game():
    rows = [("g1", 1.0)] * 50 + [("g2", -1.0)]
    r = B.boot_ci(rows, n_boot=400)
    assert r["point"] == pytest.approx(49 / 51, abs=1e-4)
    # one game of 50 identical rows must not look like 50 independent observations
    assert r["ci95"][0] < 0


def test_prepare_scratch_leaves_nothing_dated_on_or_after_the_slate(tmp_path):
    pristine, scratch = tmp_path / "p", tmp_path / "s"
    pd_ = pristine / "wnba_source" / "data"
    (pristine / "wnba_source" / "src" / "wnba_betting").mkdir(parents=True)
    for sub in ("raw", "processed"):
        (pd_ / sub).mkdir(parents=True)
    rows = [("2026-07-18", 1), ("2026-07-19", 2), ("2026-07-20", 3), ("2026-07-21", 4)]
    for rel, col in B.HISTORY_FILES.items():
        with (pd_ / rel).open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([col, "x"])
            w.writerows(rows)
    for name in ("boxscores_2026-07-19.csv", "boxscores_2026-07-20.csv", "recon_props_2026-07-19.csv",
                 "recon_props_2026-07-20.csv", "team_advanced_stats_2026_asof_20261001.csv",
                 "team_advanced_stats_2026.csv", "home_court_advantage.json", "predictions_2026-07-25.csv"):
        (pd_ / "processed" / name).write_text("a\n1\n")
    info = B.prepare_scratch(pristine, scratch, "2026-07-20", None, False)
    sp = scratch / "wnba_source" / "data" / "processed"
    names = sorted(p.name for p in sp.iterdir())
    assert "boxscores_2026-07-20.csv" not in names and "boxscores_2026-07-19.csv" in names
    assert "recon_props_2026-07-20.csv" not in names and "recon_props_2026-07-19.csv" in names
    assert not [n for n in names if n.startswith(("team_advanced_stats", "home_court", "predictions_"))]
    for rel, col in B.HISTORY_FILES.items():
        with (scratch / "wnba_source" / "data" / rel).open() as fh:
            dates = [r[col] for r in csv.DictReader(fh)]
        assert dates == ["2026-07-18", "2026-07-19"], rel
        assert info[rel] == 2


def test_team_naive_baseline_uses_only_earlier_games(tmp_path):
    events = []
    for i in range(25):
        day = f"2026-06-{i + 1:02d}"
        events.append((day, _event(str(i), f"{day}T23:00Z", ("SEA", "Seattle Storm"), ("MIN", "Minnesota Lynx"),
                                    90, 80, [20, 25, 20, 25], [20, 20, 20, 20])))
    late = "2026-06-30"
    events.append((late, _event("late", f"{late}T23:00Z", ("SEA", "Seattle Storm"), ("MIN", "Minnesota Lynx"),
                                50, 120, [10, 10, 15, 15], [30, 30, 30, 30])))
    for day, ev in events:
        _write_sb(tmp_path, day, [ev])
    g = B.load_games(tmp_path)
    h = B.History(g, {})
    naive = h.team_naive(g["late"])
    assert naive["full"]["margin"] == pytest.approx(10 + (10 - (-10)) / 2)   # HCA 10 + net diff / 2
    assert naive["full"]["total"] == pytest.approx(170)                     # the 120-50 blowout is NOT visible


def test_old_layout_quarter_normals_give_a_probability(tmp_path):
    p = tmp_path / "smart_sim_2026-06-01_SEA_MIN.json"
    p.write_text(json.dumps({"date": "2026-06-01", "home": "SEA", "away": "MIN", "market_total": 166.5,
                             "market_home_spread": -4.5, "home_team_total_pts_mean": 88.0,
                             "away_team_total_pts_mean": 82.0,
                             "quarters": [{"q": q, "home_pts_mu": 22.0, "away_pts_mu": 20.5, "home_pts_sigma": 6.0,
                                           "away_pts_sigma": 6.0, "corr": 0.25} for q in (1, 2, 3, 4)],
                             "players": {"home": [], "away": []}}), encoding="utf-8")
    games = {"1": {"date": "2026-06-01", "home": "SEA", "away": "MIN", "tip": "x"}}
    gout, _, cnt = B.load_sim_json_games([p], games)
    full = gout["1"]["full"]
    assert full["margin"] == 6.0 and full["total"] == 170.0
    sd = math.sqrt(4 * 2 * 36 * 0.75)
    assert full["cover"](-4.5) == pytest.approx(1 - B.phi((4.5 - 6.0) / sd), abs=1e-3)
    assert cnt["old_layout_quarter_normals"] == 1
