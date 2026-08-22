"""Stage A commit: sizing a Layer 2 row, and refusing to size one we cannot."""

from __future__ import annotations

import pytest

from syndicate.features.bankroll_manager import compute_bet_size
from syndicate.features.shared.portfolio_commit import (
    SizingInputs,
    commit_portfolio,
    position_key,
    sizing_input_field_names,
    sizing_inputs_from_row,
)
from syndicate.features.shared.portfolio_settings import PortfolioSettings


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


# --------------------------------------------------------------------------
# The regression this module exists to prevent.
# --------------------------------------------------------------------------


def test_sizing_a_raw_layer2_row_would_have_produced_a_zero_stake():
    """FAILS ON THE NAIVE IMPLEMENTATION, which is the point of writing it.

    A Layer 2 shortlist row carries no `model_probability` and no `odds`, so
    handing one straight to `compute_bet_size` -- the obvious implementation --
    returns edge 0 and a $0 stake for EVERY row, with no exception and no log
    line. This pins that fact so nobody 'simplifies' the adapter away.
    """
    naive = compute_bet_size(_row())
    assert naive["kelly_fraction"] == 0.0
    assert naive["recommended_bet_size"] == 0.0

    plan = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings())
    assert plan["totals"]["positions"] == 1
    assert plan["positions"][0]["stake_dollars"] > 0


# --------------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------------


def test_the_market_probability_is_recovered_exactly_from_ev_and_price():
    from syndicate.features.shared.opportunity_signals import expected_value_pct

    fair = 0.5473
    price = -110
    ev = expected_value_pct(price, fair)
    inputs, reason = sizing_inputs_from_row(_row(ev_pct=ev))
    assert reason is None
    assert inputs.market_fair_probability == pytest.approx(fair, abs=1e-4)


def test_the_model_probability_is_the_market_plus_the_edge_in_points():
    inputs, _ = sizing_inputs_from_row(_row(ev_pct=4.5, model_edge_pct=3.2))
    assert inputs.model_probability == pytest.approx(inputs.market_fair_probability + 0.032, abs=1e-9)


def test_implied_probability_is_not_passed_so_kelly_stays_textbook():
    """`compute_bet_size`'s `edge / (decimal - 1)` equals textbook Kelly only
    when the subtracted probability is the price's OWN implied probability.
    Passing the de-vigged fair there computes a different, larger number."""
    from syndicate.features.shared.portfolio_commit import sizing_candidate

    inputs, _ = sizing_inputs_from_row(_row())
    candidate = sizing_candidate(_row(), inputs)
    assert "implied_probability" not in candidate
    assert candidate["odds"] == -110


# --------------------------------------------------------------------------
# Refusals -- every one by name, none by neutral default
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ({"quote": None}, "no_quote_price"),
        ({"quote": {"bookmaker": "dk"}}, "no_quote_price"),
        # Present but unusable is a DIFFERENT fact from absent -- a book
        # quoting 0 is a feed bug, a missing quote is a thin market.
        ({"quote": {"price": 0}}, "unusable_price"),
        ({"ev_pct": None}, "no_ev_pct"),
        ({"model_edge_pct": None}, "no_model_edge_pct"),
        ({"score": None}, "no_price_reliability"),
        ({"score": {"score": 1.0}}, "no_price_reliability"),
    ],
)
def test_a_missing_input_is_refused_by_name(mutation, expected):
    inputs, reason = sizing_inputs_from_row(_row(**mutation))
    assert inputs is None
    assert reason == expected


def test_every_row_is_accounted_for_by_a_named_reason():
    rows = [
        _row(),
        _row(event_id="evt-2", ev_pct=None),
        _row(event_id="evt-3", model_edge_pct=None),
        _row(event_id="evt-4", quote=None),
    ]
    plan = commit_portfolio(rows, selected_date="2026-08-22", settings=_settings())
    assert plan["rows_in"] == 4
    assert len(plan["positions"]) + sum(plan["refusals"].values()) == 4
    assert plan["refusals"]["no_ev_pct"] == 1
    assert plan["refusals"]["no_model_edge_pct"] == 1
    assert plan["refusals"]["no_quote_price"] == 1


def test_a_negative_model_edge_does_not_produce_a_negative_stake():
    plan = commit_portfolio(
        [_row(model_edge_pct=-8.0)], selected_date="2026-08-22", settings=_settings()
    )
    assert plan["positions"] == []
    assert plan["refusals"]["zero_kelly_stake"] == 1


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------


def test_the_ev_cut_line_drops_rows_below_it():
    plan = commit_portfolio(
        [_row(), _row(event_id="evt-2", ev_pct=0.5)],
        selected_date="2026-08-22",
        settings=_settings(min_ev_pct=2.0),
    )
    assert plan["totals"]["positions"] == 1
    assert plan["refusals"]["below_min_ev_pct"] == 1


def test_the_position_cap_truncates_and_says_how_many_it_dropped():
    rows = [_row(event_id=f"evt-{index}") for index in range(10)]
    plan = commit_portfolio(rows, selected_date="2026-08-22", settings=_settings(max_positions=3))
    assert plan["totals"]["positions"] == 3
    assert plan["refusals"]["beyond_max_positions"] == 7


def test_the_slate_ceiling_scales_the_whole_book_rather_than_cutting_its_tail():
    rows = [_row(event_id=f"evt-{index}") for index in range(8)]
    generous = commit_portfolio(rows, selected_date="2026-08-22", settings=_settings())
    capped = commit_portfolio(
        rows, selected_date="2026-08-22", settings=_settings(max_slate_exposure_fraction=0.01)
    )
    # Same positions, all of them smaller -- composition preserved, scale cut.
    assert len(capped["positions"]) == len(generous["positions"])
    assert capped["totals"]["slate_scale_factor"] < 1.0
    assert capped["totals"]["staked_fraction"] == pytest.approx(0.01, abs=1e-4)


def test_total_staked_never_exceeds_the_slate_ceiling():
    rows = [_row(event_id=f"evt-{index}", model_edge_pct=14.0) for index in range(20)]
    plan = commit_portfolio(
        rows,
        selected_date="2026-08-22",
        settings=_settings(bankroll_units=1000.0, max_slate_exposure_fraction=0.2),
    )
    assert plan["totals"]["staked_dollars"] <= 200.0 + 1e-6


def test_a_stake_too_small_to_place_is_dropped_not_rounded_up():
    plan = commit_portfolio(
        [_row()], selected_date="2026-08-22", settings=_settings(min_stake_units=50.0)
    )
    assert plan["positions"] == []
    assert plan["refusals"]["below_min_stake"] == 1


def test_bankroll_scales_dollars_but_not_fractions():
    small = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings(bankroll_units=1000.0))
    large = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings(bankroll_units=10000.0))
    assert small["positions"][0]["stake_fraction"] == large["positions"][0]["stake_fraction"]
    assert large["positions"][0]["stake_dollars"] == pytest.approx(
        small["positions"][0]["stake_dollars"] * 10, rel=1e-6
    )


def test_correlated_legs_on_one_game_are_budgeted_together():
    """Three legs on ONE event must not be sized as three independent bets."""
    same_game = [_row(market=market) for market in ("h2h", "totals", "spreads")]
    spread_out = [_row(event_id=f"evt-{index}", market=market)
                  for index, market in enumerate(("h2h", "totals", "spreads"))]
    together = commit_portfolio(same_game, selected_date="2026-08-22", settings=_settings())
    apart = commit_portfolio(spread_out, selected_date="2026-08-22", settings=_settings())
    assert together["totals"]["staked_dollars"] < apart["totals"]["staked_dollars"]


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def test_position_key_is_stable_across_rebuilds():
    assert position_key(_row()) == position_key(_row())


@pytest.mark.parametrize(
    "mutation",
    [
        {"side": "away"},
        {"line": -1.5},
        {"quote": {"price": -110, "bookmaker": "fanduel"}},
        {"market": "totals"},
        {"event_id": "evt-2"},
    ],
)
def test_a_different_bet_gets_a_different_key(mutation):
    """Side, line and book each make it a DIFFERENT BET, not a different view of
    the same one. Stage B's idempotency hangs off this key."""
    assert position_key(_row(**mutation)) != position_key(_row())


def test_price_alone_does_not_change_the_identity():
    """The same bet at a moved price is still the same bet -- otherwise every
    quote refresh would look like a new position to the ledger."""
    assert position_key(_row(quote={"price": -104, "bookmaker": "draftkings"})) == position_key(_row())


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------


def test_the_sizing_inputs_are_exactly_the_four_the_checklist_gates():
    assert set(sizing_input_field_names()) == {
        "american_price",
        "market_fair_probability",
        "model_probability",
        "price_reliability",
    }


def test_stakes_are_published_in_dollars_under_a_name_that_says_so():
    """`bankroll_manager`'s `stake_units` is percent-of-bankroll x 100 -- a
    different quantity. Publishing dollars under that name is the 2026-08-21
    FORBIDDEN rule."""
    plan = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings())
    position = plan["positions"][0]
    assert "stake_dollars" in position
    assert "stake_units" not in position


def test_the_sizing_breadcrumb_records_every_shrinkage():
    plan = commit_portfolio([_row()], selected_date="2026-08-22", settings=_settings())
    sizing = plan["positions"][0]["sizing"]
    for key in (
        "kelly_fraction",
        "kelly_multiplier",
        "sample_credibility",
        "settled_sample_size",
        "price_reliability_factor",
        "stake_fraction_pre_reliability",
        "slate_scale_factor",
    ):
        assert sizing[key] is not None, key


def test_an_empty_shortlist_produces_an_empty_plan_not_an_error():
    plan = commit_portfolio([], selected_date="2026-08-22", settings=_settings())
    assert plan["positions"] == []
    assert plan["rows_in"] == 0
    assert plan["totals"]["staked_dollars"] == 0.0


# --------------------------------------------------------------------------
# Runner reachability -- `off != on`, before any correctness claim
# --------------------------------------------------------------------------


def test_the_commit_job_is_dark_by_default_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", raising=False)
    from pipeline import portfolio_commit as runner

    result = runner.run_portfolio_commit("2026-08-22")
    assert result["status"] == "skipped"
    assert result["reason"] == "disabled"
    assert not runner.portfolio_plan_path("2026-08-22").exists()


def test_enabling_the_job_makes_the_plan_appear_for_the_same_date(tmp_path, monkeypatch):
    """The other half of `off != on`. A feature that writes either way cannot be
    shown to be reachable, so both directions are asserted on one date."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    from pipeline import portfolio_commit as runner

    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist",
        lambda date: {"rows": [_row()]},
    )
    result = runner.run_portfolio_commit("2026-08-22")
    assert result["status"] == "ok"
    assert result["plan"]["totals"]["positions"] == 1
    assert runner.read_portfolio_plan("2026-08-22")["totals"]["positions"] == 1


def test_an_absent_shortlist_is_reported_rather_than_written_as_an_empty_plan(tmp_path, monkeypatch):
    """"No shortlist" and "a shortlist that committed nothing" need different
    fixes, so they must not collapse into the same artifact."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    from pipeline import portfolio_commit as runner

    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: None)
    result = runner.run_portfolio_commit("2026-08-22")
    assert result["status"] == "skipped"
    assert result["reason"] == "no_shortlist"
    assert not runner.portfolio_plan_path("2026-08-22").exists()


def test_a_failing_input_checklist_blocks_the_plan_write(tmp_path, monkeypatch):
    """The gate must REFUSE, not warn.

    An unfed sizer writes a plan full of $0 positions that reads identically to
    a slate with no edges. Refusing leaves an absence to explain, which is the
    recoverable direction -- so this asserts no artifact appears.
    """
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    from pipeline import portfolio_commit as runner

    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist",
        lambda date: {"rows": [_row()]},
    )
    import portfolio_commit_input_checklist as checklist

    monkeypatch.setattr(
        checklist, "run_checklist", lambda: (False, ["FAIL  model_probability CONSUMED=False"])
    )
    result = runner.run_portfolio_commit("2026-08-22")
    assert result["status"] == "error"
    assert result["reason"] == "input_checklist_failed"
    # The evidence rides along, not just the verdict.
    assert any("model_probability" in line for line in result["failures"])
    assert not runner.portfolio_plan_path("2026-08-22").exists()
