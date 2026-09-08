"""Pricing plane v1, P4 -- NHL pre-sim market anchoring is explicit, flagged and recorded.

Covers, without needing the data/ mirror (the slate + market readers are monkeypatched in the
producer's namespace):
- `SYNDICATE_NHL_MARKET_ANCHOR_WEIGHT` absent => the served columns are bit-identical to what the
  pre-flag producer wrote (anchor at 0.35, computed here by hand through the same seams), plus the
  four new provenance columns;
- `0` => served == raw, `anchor_state == disabled`, and off != on (reachability);
- the weight the env carries is the weight `market_anchoring.anchor_game_features` receives;
- `no_market` when no usable moneyline exists;
- the refresh entrypoint threads ONE resolved weight into the producer;
- the market grader scores `_raw` as the model on a P4 row and REFUSES moneyline/puck-line on a
  legacy row (`anchored_probability_not_separable`) while totals still score.
"""
from __future__ import annotations

import csv
import importlib.util
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

import scripts.build_nhl_artifacts as producer
from syndicate.features.nhl.sim_engine.hockeysim import market_anchoring
from syndicate.features.nhl.sim_engine.hockeysim.adapters import build_game_prediction
from syndicate.features.nhl.sim_engine.hockeysim.artifacts import PREDICTIONS_COLUMNS, prediction_to_row
from syndicate.features.nhl.sim_engine.hockeysim.contracts import (
    HockeyGameFeatures,
    HockeyMarketLines,
    HockeyTeamFeatures,
)
from syndicate.features.nhl.sim_engine.hockeysim.market_anchoring import (
    ENV_ANCHOR_WEIGHT,
    anchor_game_features,
    resolve_anchor_weight,
)

_REPO = Path(__file__).resolve().parents[1]
_DATE = "2026-01-15"
_LEGACY_COLUMNS = [c for c in PREDICTIONS_COLUMNS
                   if c not in ("anchor_weight", "anchor_state", "p_home_ml_raw", "p_home_pl_-1.5_raw")]


def _game(pk: str, home: str, away: str, home_periods=(1.05, 1.1, 1.15), away_periods=(0.9, 0.95, 1.0)):
    return HockeyGameFeatures(
        game_pk=pk, date=_DATE,
        home=HockeyTeamFeatures(name=home, period_goal_lambdas=tuple(home_periods)),
        away=HockeyTeamFeatures(name=away, period_goal_lambdas=tuple(away_periods)),
    )


_MARKET = HockeyMarketLines(
    total_line=6.5, home_ml_odds=-220, away_ml_odds=185, over_odds=-105, under_odds=-115,
    home_pl_odds=135, away_pl_odds=-160,
)


@pytest.fixture
def synthetic_slate(monkeypatch):
    """Two games: one with a full market (anchorable), one with no odds at all."""
    games = [_game("1", "Boston Bruins", "Chicago Blackhawks"),
             _game("2", "Toronto Maple Leafs", "Ottawa Senators")]
    markets = {("Boston Bruins", "Chicago Blackhawks"): _MARKET}
    monkeypatch.setattr(producer, "build_slate_features", lambda date, root=None: list(games))
    monkeypatch.setattr(producer, "load_market_lines", lambda date, root=None: markets)
    monkeypatch.setattr(producer, "market_for_game", lambda lines, home, away: lines.get((home, away)))
    return games


def _rows(path: Path):
    with Path(path).open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, list(reader)


def _legacy_served_row(game, market, weight=0.35):
    """What the pre-flag producer wrote for a game: anchor at `weight`, then sim, then map."""
    g = replace(game, market=market)
    g = anchor_game_features(g, weight=weight)
    return prediction_to_row(build_game_prediction(g), g.market)


# --------------------------------------------------------------------------- resolve_anchor_weight

def test_resolve_anchor_weight_precedence_and_parsing():
    assert resolve_anchor_weight(env={}) == (0.35, "default")
    assert resolve_anchor_weight(env={ENV_ANCHOR_WEIGHT: "0"}) == (0.0, "env")
    assert resolve_anchor_weight(env={ENV_ANCHOR_WEIGHT: "0.2"}) == (0.2, "env")
    assert resolve_anchor_weight(env={ENV_ANCHOR_WEIGHT: "1.5"}) == (1.0, "env")      # clamped
    assert resolve_anchor_weight(env={ENV_ANCHOR_WEIGHT: "junk"}) == (0.35, "default_invalid_env")
    assert resolve_anchor_weight(0.6, env={ENV_ANCHOR_WEIGHT: "0.1"}) == (0.6, "explicit")


# --------------------------------------------------------------------------- producer behaviour

def test_flag_absent_is_bit_identical_to_legacy_plus_new_columns(synthetic_slate, tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_ANCHOR_WEIGHT, raising=False)
    path, n = producer.build_predictions_for_date(_DATE, out_dir=tmp_path)
    assert n == 2
    header, rows = _rows(path)
    assert header == PREDICTIONS_COLUMNS
    assert header[:len(_LEGACY_COLUMNS)] == _LEGACY_COLUMNS

    # Game 1 (market): every pre-existing column equals the pre-flag producer's output.
    legacy = _legacy_served_row(synthetic_slate[0], _MARKET)
    for col in _LEGACY_COLUMNS:
        expected = "" if legacy[col] is None else str(legacy[col])
        assert rows[0][col] == expected, col
    assert rows[0]["anchor_state"] == "anchored"
    assert float(rows[0]["anchor_weight"]) == pytest.approx(0.35)
    # The raw twin is the pure model on the un-anchored lambdas -- and it differs from the served blend.
    raw = build_game_prediction(replace(synthetic_slate[0], market=_MARKET))
    assert float(rows[0]["p_home_ml_raw"]) == pytest.approx(raw.p_home_ml)
    assert float(rows[0]["p_home_pl_-1.5_raw"]) == pytest.approx(raw.p_home_pl_minus_1_5)
    assert float(rows[0]["p_home_ml"]) != pytest.approx(float(rows[0]["p_home_ml_raw"]))

    # Game 2 (no odds): pass-through, served == raw, state recorded as no_market at the same weight.
    assert rows[1]["anchor_state"] == "no_market"
    assert float(rows[1]["anchor_weight"]) == pytest.approx(0.35)
    assert rows[1]["p_home_ml"] == rows[1]["p_home_ml_raw"]
    assert rows[1]["p_home_pl_-1.5"] == rows[1]["p_home_pl_-1.5_raw"]


def test_flag_zero_disables_anchoring_and_off_differs_from_on(synthetic_slate, tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_ANCHOR_WEIGHT, raising=False)
    _, on_rows = _rows(producer.build_predictions_for_date(_DATE, out_dir=tmp_path / "on")[0])
    monkeypatch.setenv(ENV_ANCHOR_WEIGHT, "0")
    _, off_rows = _rows(producer.build_predictions_for_date(_DATE, out_dir=tmp_path / "off")[0])

    assert off_rows[0]["anchor_state"] == "disabled"
    assert float(off_rows[0]["anchor_weight"]) == 0.0
    assert off_rows[0]["p_home_ml"] == off_rows[0]["p_home_ml_raw"]
    assert off_rows[0]["p_home_pl_-1.5"] == off_rows[0]["p_home_pl_-1.5_raw"]
    # Reachability: off != on on the served column, and the raw model is the same either way.
    assert off_rows[0]["p_home_ml"] != on_rows[0]["p_home_ml"]
    assert off_rows[0]["p_home_ml_raw"] == on_rows[0]["p_home_ml_raw"]
    # `--no-anchor` (anchor=False) is the same state regardless of the env.
    monkeypatch.setenv(ENV_ANCHOR_WEIGHT, "0.5")
    _, na_rows = _rows(producer.build_predictions_for_date(_DATE, anchor=False, out_dir=tmp_path / "na")[0])
    assert na_rows[0]["anchor_state"] == "disabled"
    assert na_rows[0]["p_home_ml"] == off_rows[0]["p_home_ml"]


def test_env_weight_reaches_market_anchoring(synthetic_slate, tmp_path, monkeypatch):
    seen = []

    def _spy(game, *, weight, **kw):
        seen.append(weight)
        return anchor_game_features(game, weight=weight, **kw)

    monkeypatch.setattr(producer, "anchor_game_features", _spy)

    monkeypatch.delenv(ENV_ANCHOR_WEIGHT, raising=False)
    producer.build_predictions_for_date(_DATE, out_dir=tmp_path / "a")
    assert seen == [0.35]            # one anchorable game, default weight

    seen.clear()
    monkeypatch.setenv(ENV_ANCHOR_WEIGHT, "0.2")
    _, rows = _rows(producer.build_predictions_for_date(_DATE, out_dir=tmp_path / "b")[0])
    assert seen == [0.2]
    assert float(rows[0]["anchor_weight"]) == pytest.approx(0.2)

    seen.clear()
    monkeypatch.setenv(ENV_ANCHOR_WEIGHT, "0")
    producer.build_predictions_for_date(_DATE, out_dir=tmp_path / "c")
    assert seen == []                # disabled => the anchor is never even called

    seen.clear()
    monkeypatch.setenv(ENV_ANCHOR_WEIGHT, "0.9")
    producer.build_predictions_for_date(_DATE, anchor_weight=0.1, out_dir=tmp_path / "d")
    assert seen == [0.1]             # an explicit kwarg (the refresh entrypoint) beats the env


def test_recommendations_share_the_resolved_weight(synthetic_slate, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_ANCHOR_WEIGHT, "0")
    off_path, _ = producer.build_recommendations_for_date(_DATE, out_dir=tmp_path / "off")
    monkeypatch.delenv(ENV_ANCHOR_WEIGHT, raising=False)
    on_path, _ = producer.build_recommendations_for_date(_DATE, out_dir=tmp_path / "on")
    _, off_rows = _rows(off_path)
    _, on_rows = _rows(on_path)
    ml_off = [r for r in off_rows if r["market"] == "ML" and r["side"] == "Boston Bruins"][0]
    ml_on = [r for r in on_rows if r["market"] == "ML" and r["side"] == "Boston Bruins"][0]
    assert ml_off["conf"] != ml_on["conf"]


# --------------------------------------------------------------------------- refresh entrypoint

def _load_refresh_module():
    spec = importlib.util.spec_from_file_location("test_p4_refresh_nhl_oddsapi", _REPO / "scripts" / "refresh_nhl_oddsapi.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_refresh_entrypoint_threads_one_resolved_weight(tmp_path, monkeypatch):
    module = _load_refresh_module()
    calls = []
    fake_producer = types.ModuleType("build_nhl_artifacts")
    fake_producer.build_predictions_for_date = lambda date, **kw: calls.append(("pred", date, kw)) or (tmp_path, 1)
    fake_producer.build_recommendations_for_date = lambda date, **kw: calls.append(("rec", date, kw)) or (tmp_path, 1)
    fake_producer.build_props_for_date = lambda date, **kw: calls.append(("props", date, kw)) or (tmp_path, 1)
    monkeypatch.setitem(sys.modules, "build_nhl_artifacts", fake_producer)
    import syndicate.features.nhl.sim_engine.hockeysim.ingestion as ingestion
    monkeypatch.setattr(ingestion, "collect_slate_inputs", lambda date, root=None: None)

    monkeypatch.setenv(ENV_ANCHOR_WEIGHT, "0.2")
    warnings: list = []
    module._run_owned_generation(artifact_root=tmp_path, target_dates=["2026-01-15", "2026-01-16"], props_n_sims=5, warnings=warnings)
    assert warnings == []
    pred_calls = [c for c in calls if c[0] == "pred"]
    rec_calls = [c for c in calls if c[0] == "rec"]
    assert len(pred_calls) == 2 and len(rec_calls) == 2
    assert all(c[2]["anchor_weight"] == 0.2 for c in pred_calls + rec_calls)
    # props are NOT anchored and receive no weight
    assert all("anchor_weight" not in c[2] for c in calls if c[0] == "props")

    calls.clear()
    monkeypatch.delenv(ENV_ANCHOR_WEIGHT, raising=False)
    module._run_owned_generation(artifact_root=tmp_path, target_dates=["2026-01-15"], props_n_sims=5, warnings=warnings)
    assert [c[2]["anchor_weight"] for c in calls if c[0] in ("pred", "rec")] == [0.35, 0.35]


# --------------------------------------------------------------------------- grader

def _grader():
    spec = importlib.util.spec_from_file_location("test_p4_grade_nhl", _REPO / "scripts" / "grade_nhl_predictions_vs_market.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_BASE_ROW = {
    "date": _DATE, "home": "Boston Bruins", "away": "Chicago Blackhawks",
    "p_home_ml": "0.62", "p_over": "0.51", "totals_line_used": "6.5", "p_home_pl_-1.5": "0.33",
    "home_ml_odds": "-220", "away_ml_odds": "185", "over_odds": "-105", "under_odds": "-115",
    "home_pl_-1.5_odds": "135", "away_pl_+1.5_odds": "-160",
}
_OUTCOMES = {(_DATE, "BOS", "CHI"): (4, 2)}


def test_grader_refuses_legacy_anchored_columns_but_scores_totals():
    g = _grader()
    pairs, counters, _, _ = g.score([dict(_BASE_ROW)], _OUTCOMES)
    assert counters["home_ml:anchored_probability_not_separable"] == 1
    assert counters["home_puck_line_-1.5:anchored_probability_not_separable"] == 1
    assert counters.get("home_ml:scored", 0) == 0
    assert pairs["home_ml"]["model"] == [] and pairs["home_puck_line_-1.5"]["model"] == []
    assert counters["total_over:scored"] == 1
    assert pairs["total_over"]["model"] == [(0.51, 0.0)]      # 6 goals, line 6.5 -> under
    assert counters["anchor_state:legacy_unknown"] == 1


def test_grader_scores_raw_as_model_and_served_as_anchored():
    g = _grader()
    row = dict(_BASE_ROW, anchor_weight="0.35", anchor_state="anchored",
               **{"p_home_ml_raw": "0.55", "p_home_pl_-1.5_raw": "0.29"})
    pairs, counters, _, _ = g.score([row], _OUTCOMES)
    assert counters["home_ml:scored"] == 1 and counters["home_puck_line_-1.5:scored"] == 1
    assert pairs["home_ml"]["model"] == [(0.55, 1.0)]
    assert pairs["home_ml"]["anchored"] == [(0.62, 1.0)]
    assert pairs["home_puck_line_-1.5"]["model"] == [(0.29, 1.0)]
    assert pairs["home_puck_line_-1.5"]["anchored"] == [(0.33, 1.0)]
    assert pairs["total_over"]["anchored"] == []                # totals are never anchored
    assert counters["anchor_state:anchored"] == 1 and counters["anchor_weight:0.35"] == 1
    assert "home_ml:anchored_probability_not_separable" not in counters


def test_grader_accepts_p4_row_that_says_it_was_not_anchored():
    g = _grader()
    row = dict(_BASE_ROW, anchor_weight="0", anchor_state="disabled")  # no raw column, but served == raw by contract
    pairs, counters, _, _ = g.score([row], _OUTCOMES)
    assert counters["home_ml:scored"] == 1
    assert pairs["home_ml"]["model"] == [(0.62, 1.0)]


def test_grader_end_to_end_on_producer_output(synthetic_slate, tmp_path, monkeypatch):
    """The real producer's CSV, read back by the real grader's loader, scores the raw column."""
    monkeypatch.delenv(ENV_ANCHOR_WEIGHT, raising=False)
    root = tmp_path / "root"
    proc = root / "data" / "processed"
    producer.build_predictions_for_date(_DATE, out_dir=proc)
    g = _grader()
    rows = g.load_predictions(root)
    assert len(rows) == 2
    pairs, counters, _, _ = g.score(rows, _OUTCOMES)
    assert counters["home_ml:scored"] == 1
    (p_model, _), = pairs["home_ml"]["model"]
    (p_served, _), = pairs["home_ml"]["anchored"]
    assert p_model == pytest.approx(float(rows[0]["p_home_ml_raw"]))
    assert p_served == pytest.approx(float(rows[0]["p_home_ml"]))
    assert p_model != p_served
