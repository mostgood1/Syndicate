"""Unit tests for scripts/backtest_nfl_lines_props.py -- the scoring and as-of rules, no data/ needed."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backtest_nfl_lines_props.py"
_spec = importlib.util.spec_from_file_location("bt_nfl_lines_props", _PATH)
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)  # type: ignore[union-attr]


def _game(gid, season, week, hs, as_, spread="3", total="45", hml="-150", aml="130"):
    return {"game_id": gid, "season_i": season, "week_i": week, "home_score": str(hs), "away_score": str(as_),
            "completed": True, "spread_line": spread, "total_line": total, "home_moneyline": hml,
            "away_moneyline": aml, "home_spread_odds": "-110", "away_spread_odds": "-110", "over_odds": "-110",
            "under_odds": "-110", "home_team": "KC", "away_team": "DET", "gameday": "2025-10-12"}


def test_devig_is_proportional_and_sums_to_one():
    p_home = bt.devig(bt.implied(-150), bt.implied(130))
    p_away = bt.devig(bt.implied(130), bt.implied(-150))
    assert abs(p_home + p_away - 1.0) < 1e-12
    assert 0.5 < p_home < bt.implied(-150)  # vig removed from the favourite


def test_league_baseline_never_reads_the_current_or_a_later_week():
    sched = {
        "a": _game("a", 2024, 1, 30, 0),     # prior season: in
        "b": _game("b", 2025, 3, 20, 10),    # earlier week: in
        "c": _game("c", 2025, 5, 0, 99),     # SAME week: must be out
        "d": _game("d", 2025, 9, 0, 99),     # later: must be out
    }
    r = bt.LeagueAsOf(sched).rates(2025, 5)
    assert r["n_games"] == 2
    assert r["margin"] == pytest.approx((30 + 10) / 2)


def test_boot_ci_is_game_clustered():
    # two games, many rows in one: the CI must reflect 2 clusters, not 101 rows
    rows = [("g1", 1.0)] * 100 + [("g2", 0.0)]
    point, lo, hi = bt.boot_ci(rows, n_boot=400)
    assert point == pytest.approx(100 / 101)
    assert lo == 0.0 and hi == 1.0  # resampling clusters can draw g2 twice or g1 twice


def test_prob_block_verdicts_follow_the_paired_ci():
    good = [{"gid": f"g{i}", "y": i % 2, "p_model": 0.9 if i % 2 else 0.1, "p_book": 0.5, "p_base": 0.5}
            for i in range(200)]
    v = bt.prob_block(good, ("p_model", "p_book", "p_base"), min_n=30)
    assert v["verdict_vs_book"] == "MODEL_BETTER" and v["verdict_vs_base"] == "MODEL_BETTER"
    bad = [dict(r, p_model=1 - r["p_model"]) for r in good]
    assert bt.prob_block(bad, ("p_model", "p_book", "p_base"), min_n=30)["verdict_vs_book"] == "MODEL_WORSE"
    assert bt.prob_block(good[:10], ("p_model", "p_book", "p_base"), min_n=30)["verdict_vs_book"] == "INSUFFICIENT_N"


def test_point_block_dmae_sign_and_verdict():
    rows = [{"gid": f"g{i}", "y": float(i), "model": float(i) + 1, "base": float(i) + 5} for i in range(100)]
    v = bt.point_block(rows, ("model", "base"), min_n=30)
    assert v["dmae_model_vs_base"]["point"] == pytest.approx(-4.0)
    assert v["verdict_vs_base"] == "MODEL_BETTER"


def test_spread_cover_uses_home_margin_positive_line():
    # nflverse spread_line=+3 means home favoured by 3: home covers iff margin > 3
    sched = {"p": _game("p", 2024, 1, 0, 0), "g": _game("g", 2025, 2, 27, 20, spread="3")}
    sims = {"g": {"margin_mean": 10.0, "total_mean": 45.0, "margin_stdev": 13.0, "total_stdev": 12.0,
                  "home_win_rate": 0.7}}
    rep = bt.score_lines(sched, sims, {"x": [2025]}, min_n=1)
    G = rep["groups"]["x"]
    assert G["spread"]["n"] == 1 and G["spread"]["base_rate"] == 1.0  # 7 > 3: covered
    assert G["spread"]["p_model"]["mean_p"] > 0.5  # mean 10 vs line 3


def test_configure_env_refuses_a_knob_production_does_not_set(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_NFL_TOTAL_LEVEL_SHRINK", "0.5")
    with pytest.raises(SystemExit):
        bt.configure_env(tmp_path)


def test_configure_env_sets_exactly_the_production_flags(monkeypatch, tmp_path):
    for k in bt.MUST_BE_ABSENT:
        monkeypatch.delenv(k, raising=False)
    for k in ("SYNDICATE_NFL_SOURCE_ROOT", "SYNDICATE_DATA_ROOT", *bt.PRODUCTION_ENV):
        monkeypatch.setenv(k, os.environ.get(k, ""))  # let monkeypatch restore them
    bt.configure_env(tmp_path / "nfl_source")
    assert os.environ["SYNDICATE_NFL_PPG_RATINGS"] == "1"
    assert os.environ["SYNDICATE_NFL_SOURCE_ROOT"].endswith("nfl_source")
