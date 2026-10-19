"""What an UNFITTED staked-probability cell stakes (lane `sim-stake-unfitted-market-only`, todo #704).

`findings_2026-10-19_ev_overstatement_decomp.md`: the fleet has no staked-probability profile, so
every cell is unfitted and the sizer stakes the raw sim (`fair + model_edge_pct/100`, weight ~1).
On 4,876 settled paper orders the sim's fitted weight is -0.27 [-0.78, +0.18].

`SYNDICATE_STAKED_PROBABILITY_UNFITTED`:
    raw (default; absent and unparseable)  today, bit for bit
    market_only_cells                      a cell the harness WROTE market_only stakes the market fair
    market                                 that, and every unfitted cell too

The first block is the bit-identity block; the second is reachability (off != on) through the
REAL sizer, not the profile helper alone.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared.portfolio_commit import (
    commit_portfolio,
    sizing_inputs_with_provenance,
    stake_attribution,
)
from syndicate.features.shared.portfolio_settings import PortfolioSettings
from syndicate.features.shared.staked_probability_profile import (
    MARKET_BASIS_VERSION_PREFIX,
    PROFILE_PATH_ENV,
    STAKED_BASIS_BLEND,
    STAKED_BASIS_MARKET,
    STAKED_BASIS_RAW,
    UNFITTED_MODE_ENV,
    UNFITTED_VERSION,
    BlendCell,
    StakedProbabilityProfile,
    cell_key,
    clear_profile_cache,
    unfitted_mode,
)

CELL = cell_key("mlb", "h2h", "full_game")


@pytest.fixture(autouse=True)
def _inert(monkeypatch, tmp_path):
    """Flag absent and the profile pointed at a file that does not exist."""
    monkeypatch.delenv(UNFITTED_MODE_ENV, raising=False)
    monkeypatch.delenv("SYNDICATE_KELLY_ON_FAIR", raising=False)
    monkeypatch.delenv("SYNDICATE_PREGAME_INTERVAL_GATE", raising=False)
    monkeypatch.setenv(PROFILE_PATH_ENV, str(tmp_path / "absent_profile.json"))
    clear_profile_cache()
    yield
    clear_profile_cache()


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


def _settings() -> PortfolioSettings:
    return PortfolioSettings(
        bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0, max_positions=50, min_stake_units=0.0
    )


def _write_profile(path, cells, version="sp-test"):
    path.write_text(
        json.dumps({"version": version, "generated_at": "2026-10-19T00:00:00Z", "fit_from": {}, "fields": {"cells": cells}}),
        encoding="utf-8",
    )
    clear_profile_cache()


# ---------------------------------------------------------------------------
# the flag's own parsing: absent and unparseable are OFF
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "  ", "MARKETS", "on", "1", "true", "market only"])
def test_absent_or_unrecognised_mode_is_raw(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(UNFITTED_MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(UNFITTED_MODE_ENV, value)
    assert unfitted_mode() == "raw"


@pytest.mark.parametrize("value,expected", [("market", "market"), (" Market ", "market"), ("market_only_cells", "market_only_cells")])
def test_recognised_modes(monkeypatch, value, expected):
    monkeypatch.setenv(UNFITTED_MODE_ENV, value)
    assert unfitted_mode() == expected


# ---------------------------------------------------------------------------
# the basis table, on the profile
# ---------------------------------------------------------------------------


def test_basis_table_for_every_cell_kind_and_mode():
    profile = StakedProbabilityProfile(
        cells={
            cell_key("mlb", "h2h", "full_game"): {"beta": 0.3},
            cell_key("mlb", "totals", "full_game"): {"beta": 0.0, "market_only": True},
            cell_key("mlb", "spreads", "full_game"): {"beta": 0.0},
        }
    )
    table = {
        (market, mode): profile.staked_basis("mlb", market, "full_game", mode=mode)
        for market in ("h2h", "totals", "spreads", "absent")
        for mode in ("raw", "market_only_cells", "market")
    }
    # fitted: blend under every mode
    assert {table[("h2h", m)] for m in ("raw", "market_only_cells", "market")} == {STAKED_BASIS_BLEND}
    # market_only cell: raw only when the flag is off
    assert table[("totals", "raw")] == STAKED_BASIS_RAW
    assert table[("totals", "market_only_cells")] == STAKED_BASIS_MARKET
    assert table[("totals", "market")] == STAKED_BASIS_MARKET
    # beta-0 cell without the flag, and an absent cell: unfitted
    for market in ("spreads", "absent"):
        assert table[(market, "raw")] == STAKED_BASIS_RAW
        assert table[(market, "market_only_cells")] == STAKED_BASIS_RAW
        assert table[(market, "market")] == STAKED_BASIS_MARKET


def test_a_contradictory_market_only_cell_with_a_beta_is_not_honoured():
    assert BlendCell.from_mapping({"beta": 0.4, "market_only": True}) is None
    profile = StakedProbabilityProfile(cells={CELL: {"beta": 0.4, "market_only": True}})
    assert profile.beta_for("mlb", "h2h", "full_game") == 0.0
    assert profile.staked_basis("mlb", "h2h", "full_game", mode="market_only_cells") == STAKED_BASIS_RAW


def test_market_only_round_trips_and_a_truthy_non_bool_is_not_market_only():
    cell = BlendCell.from_mapping({"beta": 0.0, "market_only": True})
    assert cell is not None and cell.market_only and not cell.fitted
    assert BlendCell.from_mapping(cell.to_dict()).market_only is True
    assert BlendCell.from_mapping({"beta": 0.0, "market_only": "yes"}).market_only is False


# ---------------------------------------------------------------------------
# bit identity with the flag absent, THROUGH THE SIZER
# ---------------------------------------------------------------------------


def test_flag_absent_a_market_only_cell_still_stakes_the_raw_model(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setenv(PROFILE_PATH_ENV, str(path))
    _write_profile(path, {CELL: {"beta": 0.0, "market_only": True}})
    inputs, reason, prov = sizing_inputs_with_provenance(_row())
    assert reason is None
    assert inputs.model_probability == prov["model_probability_raw"]
    assert prov["staked_probability_version"] == UNFITTED_VERSION
    assert prov["blend_beta"] == 0.0


def test_flag_absent_no_profile_is_the_raw_additive_model_bit_for_bit():
    row = _row()
    inputs, _, prov = sizing_inputs_with_provenance(row)
    profit = 100.0 / 110.0
    fair = (row["ev_pct"] / 100.0 + 1.0) / (profit + 1.0)
    assert inputs.model_probability == fair + row["model_edge_pct"] / 100.0
    assert prov["staked_probability_version"] == UNFITTED_VERSION


# ---------------------------------------------------------------------------
# REACHABILITY: off != on through the real sizer and the real commit
# ---------------------------------------------------------------------------


def test_mode_market_stakes_the_fair_on_an_unfitted_cell_and_stamps_it(monkeypatch):
    off_inputs, _, off_prov = sizing_inputs_with_provenance(_row())
    monkeypatch.setenv(UNFITTED_MODE_ENV, "market")
    on_inputs, reason, on_prov = sizing_inputs_with_provenance(_row())
    assert reason is None
    assert on_inputs.model_probability != off_inputs.model_probability  # off != on
    assert on_inputs.model_probability == on_inputs.market_fair_probability  # beta 0, exactly
    assert on_prov["staked_probability_version"] == MARKET_BASIS_VERSION_PREFIX + UNFITTED_VERSION
    assert on_prov["blend_beta"] == 0.0
    assert on_prov["model_probability_raw"] == off_prov["model_probability_raw"]  # the sim's claim is still recorded


def test_mode_market_only_cells_honours_a_written_cell_and_leaves_an_absent_one_raw(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setenv(PROFILE_PATH_ENV, str(path))
    _write_profile(path, {CELL: {"beta": 0.0, "market_only": True}}, version="sp-mo")
    monkeypatch.setenv(UNFITTED_MODE_ENV, "market_only_cells")
    inputs, _, prov = sizing_inputs_with_provenance(_row())
    assert inputs.model_probability == inputs.market_fair_probability
    assert prov["staked_probability_version"] == MARKET_BASIS_VERSION_PREFIX + "sp-mo"
    other, _, other_prov = sizing_inputs_with_provenance(_row(market="totals"))
    assert other.model_probability == other_prov["model_probability_raw"]


def test_a_fitted_cell_blends_the_same_under_every_mode(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setenv(PROFILE_PATH_ENV, str(path))
    _write_profile(path, {CELL: {"beta": 0.3}}, version="sp-fit")
    seen = set()
    for mode in ("raw", "market_only_cells", "market"):
        monkeypatch.setenv(UNFITTED_MODE_ENV, mode)
        inputs, _, prov = sizing_inputs_with_provenance(_row())
        assert prov["blend_beta"] == 0.3 and prov["staked_probability_version"] == "sp-fit"
        seen.add(inputs.model_probability)
    assert len(seen) == 1


def test_mode_market_takes_the_sim_out_of_the_committed_stake(monkeypatch):
    """The position the sizer commits: smaller stake, sim share 0.0, the row still staked."""
    off = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings())["positions"][0]
    monkeypatch.setenv(UNFITTED_MODE_ENV, "market")
    on = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings())["positions"][0]
    assert off["attribution"]["sim_share_of_stake"] > 0.0
    assert on["attribution"]["sim_share_of_stake"] == 0.0
    assert on["stake_fraction"] < off["stake_fraction"]
    assert on["stake_fraction"] == pytest.approx(off["attribution"]["stake_fraction_ev_only"], abs=1e-5)
    assert on["sizing"]["staked_probability_version"].startswith(MARKET_BASIS_VERSION_PREFIX)


def test_mode_market_refuses_nothing_the_default_admits_and_lifts_the_sims_veto(monkeypatch):
    """A negative sim edge on a positive-EV row: the raw model vetoes it (zero Kelly); on the
    market fair it is staked as price shopping. The flag never ADDS a refusal -- it removes the
    unmeasured sim's veto, which is the other half of the same change and must stay visible."""
    rows = [_row(event_id=f"e{i}", model_edge_pct=edge) for i, edge in enumerate((-6.0, -1.0, 0.0, 2.0, 9.0))]
    off_plan = commit_portfolio(rows, selected_date="2026-08-22", settings=_settings())
    off = {p["event_id"] for p in off_plan["positions"]}
    monkeypatch.setenv(UNFITTED_MODE_ENV, "market")
    on = {p["event_id"] for p in commit_portfolio(rows, selected_date="2026-08-22", settings=_settings())["positions"]}
    assert off <= on
    assert "e0" not in off and "e0" in on  # the -6 pp sim edge was a veto, and is lifted


def test_stake_attribution_agrees_the_market_basis_is_all_price(monkeypatch):
    monkeypatch.setenv(UNFITTED_MODE_ENV, "market")
    row = _row()
    inputs, _, _ = sizing_inputs_with_provenance(row)
    attribution = stake_attribution(row, inputs)
    assert attribution["side_picked_by"] == "price_shopping"
