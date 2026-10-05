"""Pricing plane v1, P2 (`lane p2-sizer-blend`, 2026-09-08).

Three additions to the staking path, every one inert by default:

  1. Kelly on the de-vigged fair (`SYNDICATE_KELLY_ON_FAIR`), `kelly_basis` stamped.
  2. The pregame interval gate (`SYNDICATE_PREGAME_INTERVAL_GATE`), refusing
     under the live gate's own imported name.
  3. The fitted blend through `staked_probability`, weighted by a versioned
     per-(sport, market, segment) profile; absent profile == beta 0 == today.

The first test in each block is the bit-identity test: with nothing set, the
numbers are the numbers the sizer produced before this lane existed.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.bankroll_manager import (
    KELLY_BASIS_FAIR,
    KELLY_BASIS_IMPLIED,
    KELLY_ON_FAIR_ENV,
    compute_bet_size,
    compute_board_stake,
)
from syndicate.features.shared.live_gameline_join import PRICEABLE_SIGMA, REASON_NOT_PRICEABLE, prob_std_err
from syndicate.features.shared.portfolio_commit import (
    PREGAME_INTERVAL_GATE_ENV,
    commit_portfolio,
    sizing_candidate,
    sizing_inputs_from_row,
    sizing_inputs_with_provenance,
)
from syndicate.features.shared.portfolio_settings import PortfolioSettings
from syndicate.features.shared.staked_probability_profile import (
    PROFILE_PATH_ENV,
    UNFITTED_VERSION,
    StakedProbabilityProfile,
    cell_key,
    clear_profile_cache,
    load_staked_probability_profile,
)


@pytest.fixture(autouse=True)
def _inert(monkeypatch, tmp_path):
    """Every flag absent and the profile pointed at a file that does not exist,
    so a real artifact on the dev machine can never leak into a test."""
    monkeypatch.delenv(KELLY_ON_FAIR_ENV, raising=False)
    monkeypatch.delenv(PREGAME_INTERVAL_GATE_ENV, raising=False)
    monkeypatch.setenv(PROFILE_PATH_ENV, str(tmp_path / "absent_profile.json"))
    clear_profile_cache()
    yield
    clear_profile_cache()


def _settings(**overrides) -> PortfolioSettings:
    base = {
        "bankroll_units": 1000.0,
        "max_slate_exposure_fraction": 1.0,
        "min_ev_pct": -100.0,
        "max_positions": 50,
        "min_stake_units": 0.0,
    }
    base.update(overrides)
    return PortfolioSettings(**base)


def _row(**overrides):
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "kind": "game",
        "market": "h2h",
        "segment": "full_game",
        "line": None,
        "player_name": None,
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2026-08-22T23:05:00Z",
        "side": "home",
        "quote": {"price": -110, "bookmaker": "draftkings"},
        "ev_pct": 4.5,
        "model_edge_pct": 3.2,
        "score": {"score": 5.1, "price_reliability": 0.82},
    }
    row.update(overrides)
    return row


FIXTURE_ROWS = (
    _row(),
    _row(event_id="evt-2", quote={"price": 135, "bookmaker": "fanduel"}, ev_pct=6.1, model_edge_pct=-1.4),
    _row(event_id="evt-3", quote={"price": -240, "bookmaker": "betmgm"}, ev_pct=1.2, model_edge_pct=8.0),
    _row(event_id="evt-4", market="totals", segment="1st_5", line=4.5, ev_pct=-2.0, model_edge_pct=6.0),
)


def _write_profile(path, cells, version="sp1-test"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": version, "generated_at": "2026-09-08T00:00:00Z", "fit_from": {}, "fields": {"cells": cells}}),
        encoding="utf-8",
    )
    clear_profile_cache()


# ---------------------------------------------------------------------------
# BIT-IDENTITY with everything absent
# ---------------------------------------------------------------------------


def _pre_p2_inputs(row):
    """The derivation as it stood before this lane, written out by hand."""
    price = float(row["quote"]["price"])
    profit = 100.0 / abs(price) if price < 0 else price / 100.0
    fair = (row["ev_pct"] / 100.0 + 1.0) / (profit + 1.0)
    return price, fair, fair + row["model_edge_pct"] / 100.0, row["score"]["price_reliability"]


@pytest.mark.parametrize("row", FIXTURE_ROWS, ids=lambda r: r["event_id"])
def test_env_absent_sizing_inputs_are_the_pre_p2_derivation_bit_for_bit(row):
    inputs, reason = sizing_inputs_from_row(row)
    assert reason is None
    price, fair, model, reliability = _pre_p2_inputs(row)
    assert inputs.american_price == price
    assert inputs.market_fair_probability == fair
    assert inputs.model_probability == model  # exact, not approx: no logit round trip happened
    assert inputs.price_reliability == reliability


@pytest.mark.parametrize("row", FIXTURE_ROWS, ids=lambda r: r["event_id"])
def test_env_absent_compute_board_stake_is_byte_identical_with_or_without_the_fair(row):
    inputs, _ = sizing_inputs_from_row(row)
    with_fair = sizing_candidate(row, inputs)
    assert "fair_probability" in with_fair
    without_fair = {k: v for k, v in with_fair.items() if k != "fair_probability"}
    a = compute_board_stake(with_fair, settled_sample_size=7)
    b = compute_board_stake(without_fair, settled_sample_size=7)
    # Only the two provenance keys may differ, and only in the expected way.
    assert a["kelly_basis"] == KELLY_BASIS_IMPLIED and b["kelly_basis"] == KELLY_BASIS_IMPLIED
    assert b["fair_probability"] is None and a["fair_probability"] == round(inputs.market_fair_probability, 4)
    strip = lambda d: {k: v for k, v in d.items() if k != "fair_probability"}  # noqa: E731
    assert json.dumps(strip(a), sort_keys=True) == json.dumps(strip(b), sort_keys=True)


def test_env_absent_the_canonical_row_stakes_the_pinned_number():
    """The checklist's canonical row. Pinned so a future 'tidy-up' of either
    branch shows up as a number, not a vibe."""
    plan = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings())
    position = plan["positions"][0]
    assert position["stake_fraction"] == 0.00313  # 5dp, from `apply_exposure_budgets`
    sizing = position["sizing"]
    assert sizing["kelly_basis"] == KELLY_BASIS_IMPLIED
    assert sizing["staked_probability_version"] == UNFITTED_VERSION
    assert sizing["blend_beta"] == 0.0
    assert sizing["interval_gate"]["gate"] == "off"
    assert sizing["model_probability_raw"] == position["model_probability"] or abs(sizing["model_probability_raw"] - position["model_probability"]) < 1e-5


def test_the_refused_shape_carries_no_basis():
    assert compute_bet_size({"odds": -110})["kelly_basis"] is None


# ---------------------------------------------------------------------------
# 1. KELLY ON FAIR
# ---------------------------------------------------------------------------


def test_kelly_on_fair_stakes_less_on_a_positive_ev_row_and_says_so(monkeypatch):
    row = _row()  # ev +4.5 => fair 0.5395 > implied 0.5238
    inputs, _ = sizing_inputs_from_row(row)
    candidate = sizing_candidate(row, inputs)
    implied = compute_board_stake(candidate)
    monkeypatch.setenv(KELLY_ON_FAIR_ENV, "1")
    fair = compute_board_stake(candidate)
    assert implied["kelly_basis"] == KELLY_BASIS_IMPLIED
    assert fair["kelly_basis"] == KELLY_BASIS_FAIR
    # edge_fair - edge_implied == implied - fair, which is negative here.
    assert fair["edge"] == pytest.approx(inputs.model_probability - inputs.market_fair_probability, abs=1e-4)
    assert fair["edge"] < implied["edge"]
    assert 0.0 < fair["stake_fraction"] < implied["stake_fraction"]
    assert fair["odds_adjustment"] == implied["odds_adjustment"]  # payout still from the quoted price


def test_kelly_on_fair_stakes_more_on_a_negative_ev_row(monkeypatch):
    row = _row(ev_pct=-2.0, model_edge_pct=6.0)  # fair < implied
    inputs, _ = sizing_inputs_from_row(row)
    candidate = sizing_candidate(row, inputs)
    implied = compute_board_stake(candidate)
    monkeypatch.setenv(KELLY_ON_FAIR_ENV, "true")
    fair = compute_board_stake(candidate)
    assert fair["stake_fraction"] > implied["stake_fraction"]


def test_kelly_on_fair_without_a_fair_stays_on_implied(monkeypatch):
    monkeypatch.setenv(KELLY_ON_FAIR_ENV, "1")
    before = compute_bet_size({"model_probability": 0.62, "odds": -110, "confidence": 70})
    assert before["kelly_basis"] == KELLY_BASIS_IMPLIED
    monkeypatch.delenv(KELLY_ON_FAIR_ENV)
    after = compute_bet_size({"model_probability": 0.62, "odds": -110, "confidence": 70})
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)


def test_kelly_on_fair_reaches_the_committed_position(monkeypatch):
    monkeypatch.setenv(KELLY_ON_FAIR_ENV, "1")
    plan = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings())
    assert plan["positions"][0]["sizing"]["kelly_basis"] == KELLY_BASIS_FAIR
    assert plan["positions"][0]["stake_fraction"] < 0.00313


def test_the_fair_keyword_overrides_the_candidate_key(monkeypatch):
    monkeypatch.setenv(KELLY_ON_FAIR_ENV, "1")
    sized = compute_bet_size({"model_probability": 0.60, "odds": -110, "fair_probability": 0.50}, fair_probability=0.55)
    assert sized["fair_probability"] == 0.55
    assert sized["edge"] == pytest.approx(0.05, abs=1e-4)


# ---------------------------------------------------------------------------
# 2. PREGAME INTERVAL GATE
# ---------------------------------------------------------------------------


def _gated_row(edge_pts, **projection):
    return _row(model_edge_pct=edge_pts, projection=projection)


def test_gate_off_admits_a_row_the_gate_would_refuse():
    inputs, reason, prov = sizing_inputs_with_provenance(_gated_row(0.5, prob_std_err=0.01))
    assert reason is None and inputs is not None
    assert prov["interval_gate"]["gate"] == "off"


def test_gate_refuses_under_the_imported_live_name_and_admits_at_the_bar(monkeypatch):
    monkeypatch.setenv(PREGAME_INTERVAL_GATE_ENV, "1")
    se = 0.01
    bar_pts = PRICEABLE_SIGMA * se * 100.0  # 2.0 points
    assert REASON_NOT_PRICEABLE == "prob_interval_swamps_edge"

    inputs, reason, prov = sizing_inputs_with_provenance(_gated_row(bar_pts - 1e-4, prob_std_err=se))
    assert inputs is None and reason == REASON_NOT_PRICEABLE
    assert prov["interval_gate"]["gate"] == "refused"
    assert prov["interval_gate"]["std_err_basis"] == "row_std_err"
    assert prov["interval_gate"]["bar"] == pytest.approx(PRICEABLE_SIGMA * se)

    inputs, reason, prov = sizing_inputs_with_provenance(_gated_row(bar_pts + 1e-4, prob_std_err=se))
    assert reason is None and inputs is not None
    assert prov["interval_gate"]["gate"] == "admitted"


def test_gate_derives_the_interval_from_sims_run_through_the_imported_estimator(monkeypatch):
    monkeypatch.setenv(PREGAME_INTERVAL_GATE_ENV, "1")
    sims = 100
    _, fair, model, _ = _pre_p2_inputs(_row(model_edge_pct=3.0))
    se = prob_std_err(model, sims)
    assert se is not None and se > 0.04  # ~0.049 at n=100: a 3-point edge is noise
    inputs, reason, prov = sizing_inputs_with_provenance(_gated_row(3.0, sims_run=sims))
    assert reason == REASON_NOT_PRICEABLE
    assert prov["interval_gate"]["std_err_basis"] == "sim_count"
    assert prov["interval_gate"]["prob_std_err"] == pytest.approx(se)

    inputs, reason, _ = sizing_inputs_with_provenance(_gated_row(12.0, sims_run=sims))
    assert reason is None and inputs is not None


def test_a_row_with_no_uncertainty_is_admitted_and_labelled_not_refused(monkeypatch):
    """Absent uncertainty is not zero uncertainty -- and it is not a refusal
    either. The gap is named on the breadcrumb so it can be counted."""
    monkeypatch.setenv(PREGAME_INTERVAL_GATE_ENV, "1")
    inputs, reason, prov = sizing_inputs_with_provenance(_row(model_edge_pct=0.2))
    assert reason is None and inputs is not None
    assert prov["interval_gate"]["gate"] == "no_std_err"
    assert prov["interval_gate"]["prob_std_err"] is None


def test_a_zero_std_err_is_treated_as_absent_not_as_perfect_precision(monkeypatch):
    monkeypatch.setenv(PREGAME_INTERVAL_GATE_ENV, "1")
    _, _, prov = sizing_inputs_with_provenance(_gated_row(0.2, prob_std_err=0.0))
    assert prov["interval_gate"]["gate"] == "no_std_err"


def test_a_market_fair_row_is_not_gated(monkeypatch):
    monkeypatch.setenv(PREGAME_INTERVAL_GATE_ENV, "1")
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", "ncaaf")
    row = _row(sport="ncaaf", model_edge_pct=None, projection={"prob_std_err": 0.5})
    inputs, reason, prov = sizing_inputs_with_provenance(row)
    assert reason is None and inputs is not None
    assert prov["interval_gate"] is None


def test_the_refusal_is_counted_by_name_in_the_plan(monkeypatch):
    monkeypatch.setenv(PREGAME_INTERVAL_GATE_ENV, "1")
    plan = commit_portfolio([_gated_row(0.5, prob_std_err=0.01)], selected_date="2026-08-22", settings=_settings())
    assert plan["totals"]["positions"] == 0
    assert plan["refusals"][REASON_NOT_PRICEABLE] == 1


# ---------------------------------------------------------------------------
# 3. THE FITTED BLEND
# ---------------------------------------------------------------------------


def test_profile_absent_means_beta_zero_and_the_raw_model(tmp_path):
    profile, meta = load_staked_probability_profile()
    assert meta["source"] == "default"
    assert profile.version == UNFITTED_VERSION
    assert profile.beta_for("mlb", "h2h", "full_game") == 0.0
    inputs, _, prov = sizing_inputs_with_provenance(_row())
    assert prov["blend_beta"] == 0.0
    assert prov["staked_probability_version"] == UNFITTED_VERSION
    assert inputs.model_probability == prov["model_probability_raw"]


def test_a_fitted_cell_moves_the_probability_toward_the_market_and_is_stamped(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setenv(PROFILE_PATH_ENV, str(path))
    _write_profile(path, {cell_key("mlb", "h2h", "full_game"): {"beta": 0.3, "n_test": 400}}, version="sp1-2026-09-08")

    inputs, reason, prov = sizing_inputs_with_provenance(_row())
    assert reason is None
    raw = prov["model_probability_raw"]
    fair = inputs.market_fair_probability
    assert inputs.model_probability != raw
    assert fair < inputs.model_probability < raw  # convex: strictly between the two inputs
    assert prov["blend_beta"] == 0.3
    assert prov["staked_probability_version"] == "sp1-2026-09-08"

    plan = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings())
    sizing = plan["positions"][0]["sizing"]
    assert sizing["blend_beta"] == 0.3
    assert sizing["staked_probability_version"] == "sp1-2026-09-08"
    assert plan["positions"][0]["stake_fraction"] < 0.00313  # less model, less stake


def test_lookup_is_exact_so_a_fit_on_one_cell_does_not_leak_to_another(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setenv(PROFILE_PATH_ENV, str(path))
    _write_profile(path, {cell_key("mlb", "h2h", "full_game"): {"beta": 0.3}})
    _, _, prov = sizing_inputs_with_provenance(_row(market="totals", segment="1st_5"))
    assert prov["blend_beta"] == 0.0
    _, _, prov = sizing_inputs_with_provenance(_row(sport="nba"))
    assert prov["blend_beta"] == 0.0


def test_a_cell_with_beta_zero_is_unfitted_not_market_only(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setenv(PROFILE_PATH_ENV, str(path))
    _write_profile(path, {cell_key("mlb", "h2h", "full_game"): {"beta": 0.0}})
    inputs, _, prov = sizing_inputs_with_provenance(_row())
    assert prov["blend_beta"] == 0.0
    assert prov["staked_probability_version"] == UNFITTED_VERSION
    assert inputs.model_probability == prov["model_probability_raw"]


def test_a_malformed_profile_degrades_to_the_default(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setenv(PROFILE_PATH_ENV, str(path))
    path.write_text("{not json", encoding="utf-8")
    clear_profile_cache()
    profile, meta = load_staked_probability_profile()
    assert meta["source"] == "default"
    assert profile.beta_for("mlb", "h2h", "full_game") == 0.0


def test_the_profile_round_trips_through_the_shared_store(tmp_path):
    from syndicate.features.shared.calibration_profile_store import save_versioned_profile

    profile = StakedProbabilityProfile().with_cells({cell_key("mlb", "h2h", "full_game"): {"beta": 0.25}}, version="v")
    path = tmp_path / "rt.json"
    save_versioned_profile(profile, artifact_path=path, version="sp1-rt")
    loaded, meta = load_staked_probability_profile(path)
    assert meta["source"] == "artifact" and loaded.version == "sp1-rt"
    assert loaded.beta_for("MLB ", "h2h", "full_game") == 0.25


def test_the_gating_checklist_still_passes_with_everything_absent():
    from scripts.portfolio_commit_input_checklist import run_checklist

    ok, lines = run_checklist()
    assert ok, "\n".join(lines)
