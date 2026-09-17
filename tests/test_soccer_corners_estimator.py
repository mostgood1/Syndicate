"""The soccer corners estimator (lane `soccer-corners-model-rebuild`, H27).

Four groups:

  1. the estimator -- team rates move the number, shrinkage, recency, no future rows,
     the pressure term exactly as registered
  2. the production inputs -- history CSV, live_state box scores, the odds CSV de-vig
  3. REACHABILITY -- `build_artifacts` publishes the estimator's corners (on) and the
     sim's (off), and the goals fields are identical either way
  4. it can never cost the board
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from syndicate.features.soccer.features import corners_estimator as ce
from syndicate.features.soccer.features.corners_estimator import CornerRow

_REPO = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 9, 19)


def _league(n_rounds=6, *, strong="alpha", weak="omega", start=date(2026, 3, 1)):
    """A small league where `strong` wins many corners and `weak` concedes many."""
    teams = [strong, "beta", "gamma", "delta", weak, "eps"]
    rows, day = [], start
    for _ in range(n_rounds):
        for i, home in enumerate(teams):
            for away in teams[i + 1:]:
                hc = 5.0 + (3.0 if home == strong else 0.0) + (2.0 if away == weak else 0.0)
                ac = 4.0 + (3.0 if away == strong else 0.0) + (2.0 if home == weak else 0.0)
                rows.append(CornerRow(day, home, away, hc, ac))
                day += timedelta(days=1)
    return rows


# ---------------------------------------------------------------------------
# 1. THE ESTIMATOR
# ---------------------------------------------------------------------------


def test_team_rates_move_the_number(artifacts_free=None):
    rows = _league()
    strong_home = ce.estimate_corners(rows, "alpha", "omega", AS_OF)
    plain = ce.estimate_corners(rows, "beta", "gamma", AS_OF)
    assert strong_home["home_corners"] > plain["home_corners"] + 1.0
    assert strong_home["home_corners"] + strong_home["away_corners"] > plain["home_corners"] + plain["away_corners"]


def test_an_unknown_team_is_the_league_venue_mean(artifacts_free=None):
    rows = _league()
    known = ce.estimate_corners(rows, "beta", "gamma", AS_OF)
    unknown = ce.estimate_corners(rows, "promoted fc", "newcomers", AS_OF)
    # Shrinkage toward 1.0 with no data leaves exactly mu_H and mu_A.
    weights = [0.5 ** ((AS_OF - r.day).days / ce.HALF_LIFE_DAYS) for r in rows]
    mu_h = sum(w * r.home_corners for w, r in zip(weights, rows)) / sum(weights)
    assert unknown["home_corners"] == pytest.approx(round(mu_h, 4), abs=1e-4)
    assert unknown["home_team_weight"] == 0.0 and known["home_team_weight"] > 0


def test_rows_on_or_after_the_slate_date_are_never_used():
    rows = _league()
    before = ce.estimate_corners(rows, "alpha", "omega", AS_OF)
    future = rows + [CornerRow(AS_OF, "alpha", "omega", 30.0, 30.0), CornerRow(AS_OF + timedelta(days=3), "alpha", "omega", 30.0, 30.0)]
    assert ce.estimate_corners(future, "alpha", "omega", AS_OF) == before


def test_recent_matches_weigh_more_than_old_ones():
    old = [CornerRow(date(2025, 1, 1) + timedelta(days=i), "x", "y", 12.0, 3.0) for i in range(40)]
    recent = [CornerRow(date(2026, 9, 1) + timedelta(days=i % 15), "x", "y", 3.0, 12.0) for i in range(40)]
    est = ce.estimate_corners(old + recent, "x", "y", AS_OF)
    assert est["away_corners"] > est["home_corners"]


def test_too_little_history_declines():
    rows = _league(n_rounds=1)[:ce.MIN_LEAGUE_ROWS - 1]
    assert ce.estimate_corners(rows, "alpha", "omega", AS_OF) is None


def test_the_pressure_term_is_exactly_the_registered_one():
    rows = _league()
    base = ce.estimate_corners(rows, "beta", "gamma", AS_OF)
    ph, pa, po = 0.60, 0.20, 0.58
    pressed = ce.estimate_corners(rows, "beta", "gamma", AS_OF, {"p_home": ph, "p_away": pa, "p_over": po})
    total = base["home_corners"] + base["away_corners"] - 0.080 + 0.415 * abs(ph - pa) + 2.125 * (po - 0.5)
    margin = base["home_corners"] - base["away_corners"] - 0.350 + 2.866 * (ph - pa)
    assert pressed["pressure_applied"] is True
    assert pressed["home_corners"] == pytest.approx((total + margin) / 2, abs=2e-4)
    assert pressed["away_corners"] == pytest.approx((total - margin) / 2, abs=2e-4)


def test_an_unpriced_total_reads_as_even_and_no_1x2_means_no_adjustment():
    rows = _league()
    base = ce.estimate_corners(rows, "beta", "gamma", AS_OF)
    no_ou = ce.estimate_corners(rows, "beta", "gamma", AS_OF, {"p_home": 0.4, "p_away": 0.3, "p_over": None})
    even = ce.estimate_corners(rows, "beta", "gamma", AS_OF, {"p_home": 0.4, "p_away": 0.3, "p_over": 0.5})
    assert no_ou == even
    assert ce.estimate_corners(rows, "beta", "gamma", AS_OF, {"p_home": None, "p_away": 0.3, "p_over": 0.6}) == base


def test_each_side_is_floored():
    rows = [CornerRow(date(2026, 8, 1) + timedelta(days=i), "a", "b", 0.2, 0.2) for i in range(40)]
    est = ce.estimate_corners(rows, "a", "b", AS_OF, {"p_home": 0.05, "p_away": 0.9, "p_over": 0.1})
    assert est["home_corners"] >= ce.FLOOR and est["away_corners"] >= ce.FLOOR


# ---------------------------------------------------------------------------
# 2. PRODUCTION INPUTS
# ---------------------------------------------------------------------------


def _write_history(league_dir: Path, n=40):
    path = league_dir / "history" / "matches_2025.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        w = csv.writer(handle)
        w.writerow(["league", "season", "match_id", "date", "home_team", "away_team", "home_corners", "away_corners"])
        for i in range(n):
            d = date(2026, 1, 1) + timedelta(days=i)
            w.writerow(["epl", 2025, f"m{i}", d.strftime("%d/%m/%Y"), "Arsenal" if i % 2 else "Leeds United", "Leeds United" if i % 2 else "Arsenal", 6 if i % 2 else 4, 4 if i % 2 else 6])
        w.writerow(["epl", 2025, "blank", "02/03/2026", "Arsenal", "Leeds United", "", ""])


def _write_live_state(league_dir: Path, day: str, boxes: dict):
    path = league_dir / "api" / "live_state" / f"live_state_{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"match_box": boxes}), encoding="utf-8")


def _box(home, away, hc, ac):
    return {"teams": {"home": {"team": home, "stats": {"Corners": hc}}, "away": {"team": away, "stats": {"Corners": ac}}}}


def test_history_rows_parse_football_data_dates_and_skip_blank_corners(tmp_path):
    _write_history(tmp_path)
    rows = ce.history_corner_rows(tmp_path)
    assert len(rows) == 40 and rows[0].day == date(2026, 1, 1)


def test_live_state_rows_read_box_score_Corners_and_dedupe_events(tmp_path):
    _write_live_state(tmp_path, "2026-09-13", {"e1": _box("Arsenal", "Leeds United", "7", "3"), "e2": {"teams": {"home": {"stats": {}}}}})
    _write_live_state(tmp_path, "2026-09-14", {"e1": _box("Arsenal", "Leeds United", "7", "3")})
    rows = ce.live_state_corner_rows(tmp_path)
    assert [(r.day, r.home_corners, r.away_corners) for r in rows] == [(date(2026, 9, 13), 7.0, 3.0)]


def test_odds_pressure_devigs_three_way_and_the_2_5_total(tmp_path):
    path = tmp_path / "game_odds_current.csv"
    rows = [
        ("h2h", "Arsenal", "", "-150"), ("h2h", "Draw", "", "+280"), ("h2h", "Leeds United", "", "+400"),
        ("h2h", "Arsenal", "", "-160"),
        ("totals", "Over", "2.5", "-120"), ("totals", "Under", "2.5", "+100"),
        ("totals", "Over", "3.5", "+200"), ("h2h", "Arsenal", "", "50"),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        w = csv.writer(handle)
        w.writerow(["league", "event_id", "home_team", "away_team", "commence_time", "market", "side", "line", "price", "book"])
        for market, side, line, price in rows:
            w.writerow(["epl", "ev1", "Arsenal", "Leeds United", "2026-09-19T14:00:00Z", market, side, line, price, "dk"])
    got = ce.pressure_by_team_pair(path)[("arsenal", "leeds united")]
    home = (150 / 250 + 160 / 260) / 2
    draw, away = 100 / 380, 100 / 500
    norm = home + draw + away
    assert got["p_home"] == pytest.approx(home / norm) and got["p_away"] == pytest.approx(away / norm)
    assert got["p_over"] == pytest.approx((120 / 220) / (120 / 220 + 0.5))


# ---------------------------------------------------------------------------
# 3. REACHABILITY
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def artifacts():
    name = "build_soccer_artifacts_corners_under_test"
    spec = importlib.util.spec_from_file_location(name, _REPO / "scripts" / "build_soccer_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeOutput:
    def __init__(self, match_outputs, player_outputs):
        self.match_outputs = match_outputs
        self.player_outputs = player_outputs


class _FakeAdapter:
    def simulate_props(self, _input):
        return _FakeOutput(
            [{"match_id": "e1", "matchup": {"home_team": "Arsenal", "away_team": "Leeds United"},
              "team_projection": {"home_mean": 1.6, "away_mean": 0.9},
              "volume_projection": {"home_corners": 5.5, "away_corners": 4.9, "home_shots": 13.0}}],
            [],
        )


def _build(artifacts, tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "_fetch_fixtures", lambda league, iso_date: [
        {"event_id": "e1", "home_team": "Arsenal", "away_team": "Leeds United", "kickoff": "2099-09-19T14:00Z", "status_state": "pre"}])
    monkeypatch.setattr(artifacts, "_load_team_ratings", lambda league, root, iso_date: {"Arsenal": {}, "Leeds United": {}})
    monkeypatch.setattr(artifacts, "_load_player_rows", lambda league, root: [{"player_id": "a0", "team": "Arsenal"}])
    monkeypatch.setattr(artifacts, "_attach_confirmed_starters", lambda league, iso_date, fixtures, rows: fixtures)
    monkeypatch.setattr(artifacts, "_apply_market_anchor", lambda league, root, fixtures, ratings: (ratings, {"state": "disabled"}))
    monkeypatch.setattr(artifacts, "_squad_audit", lambda outputs, rows: {})
    monkeypatch.setattr(artifacts, "build_soccer_simulation_input", lambda **kwargs: object())
    monkeypatch.setattr(artifacts, "build_soccer_simulation_adapter", lambda league: _FakeAdapter())
    monkeypatch.setattr(artifacts, "freeze_prekickoff", lambda *a, **k: {})
    root = tmp_path / "soccer_source"
    _write_history(root / "epl")
    artifacts.build_artifacts("epl", "2099-09-19", source_root=root, out_root=root, simulations=10)
    written = next(root.rglob("recommendations_2099-09-19.json"))
    return json.loads(written.read_text(encoding="utf-8"))


def test_REACHABILITY_on_publishes_the_estimator_and_off_publishes_the_sim(artifacts, tmp_path, monkeypatch):
    """Read back from DISK, `off != on`, before any correctness claim."""
    monkeypatch.delenv("SYNDICATE_SOCCER_CORNERS_ESTIMATOR", raising=False)
    on = _build(artifacts, tmp_path / "on", monkeypatch)
    monkeypatch.setenv("SYNDICATE_SOCCER_CORNERS_ESTIMATOR", "off")
    off = _build(artifacts, tmp_path / "off", monkeypatch)

    von, voff = on["matches"][0]["volume_projection"], off["matches"][0]["volume_projection"]
    assert on["corners_estimator"]["state"] == "on" and on["corners_estimator"]["estimated"] == 1
    assert von["corners_basis"] == ce.CORNERS_BASIS
    assert (von["sim_home_corners"], von["sim_away_corners"]) == (5.5, 4.9)
    assert (von["home_corners"], von["away_corners"]) != (5.5, 4.9)
    assert off["corners_estimator"]["state"] == "disabled"
    assert (voff["home_corners"], voff["away_corners"]) == (5.5, 4.9) and "corners_basis" not in voff
    # Nothing else moves: goals and every other volume field are identical.
    assert on["matches"][0]["team_projection"] == off["matches"][0]["team_projection"]
    assert von["home_shots"] == voff["home_shots"]


def test_a_league_without_enough_history_keeps_the_sim_and_says_so(artifacts, tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_SOCCER_CORNERS_ESTIMATOR", raising=False)
    monkeypatch.setattr(ce, "MIN_LEAGUE_ROWS", 10_000)
    payload = _build(artifacts, tmp_path, monkeypatch)
    volume = payload["matches"][0]["volume_projection"]
    assert volume["corners_basis"] == "sim" and (volume["home_corners"], volume["away_corners"]) == (5.5, 4.9)
    assert payload["corners_estimator"]["declined"] == 1


# ---------------------------------------------------------------------------
# 4. NEVER COSTS THE BOARD
# ---------------------------------------------------------------------------


def test_an_estimator_failure_writes_the_artifact_with_the_sim_corners(artifacts, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("history unreadable")

    monkeypatch.setattr(artifacts, "apply_corners_estimator", boom)
    payload = _build(artifacts, tmp_path, monkeypatch)
    assert payload["corners_estimator"]["state"] == "failed:RuntimeError"
    assert (payload["matches"][0]["volume_projection"]["home_corners"], payload["matches"][0]["volume_projection"]["away_corners"]) == (5.5, 4.9)
