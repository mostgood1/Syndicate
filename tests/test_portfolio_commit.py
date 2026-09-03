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


# --------------------------------------------------------------------------
# Sim/EV stake attribution -- the S6 input
# --------------------------------------------------------------------------


def _plan(rows, **settings_overrides):
    return commit_portfolio(
        rows, selected_date="2026-08-22", settings=_settings(**settings_overrides)
    )


def test_the_two_components_sum_to_the_committed_stake():
    """If they do not sum, the decomposition is not a decomposition."""
    position = _plan([_row()])["positions"][0]
    attribution = position["attribution"]
    assert attribution["stake_dollars_ev_only"] + attribution["stake_dollars_sim_delta"] == pytest.approx(
        position["stake_dollars"], abs=0.02
    )


def test_a_row_with_no_sim_disagreement_attributes_nothing_to_the_sim():
    attribution = _plan([_row(model_edge_pct=0.0)])["positions"][0]["attribution"]
    assert attribution["stake_dollars_sim_delta"] == pytest.approx(0.0, abs=0.01)
    assert attribution["sim_share_of_stake"] == pytest.approx(0.0, abs=1e-3)
    assert attribution["side_picked_by"] == "price_shopping"


def test_a_position_that_exists_only_because_of_the_sim_says_so():
    """Negative EV alone, positive with the model. The whole stake is the sim's,
    and the side was chosen by the model rather than by price shopping."""
    attribution = _plan([_row(ev_pct=-1.0, model_edge_pct=6.0)])["positions"][0]["attribution"]
    assert attribution["stake_dollars_ev_only"] == pytest.approx(0.0, abs=0.01)
    assert attribution["sim_share_of_stake"] == pytest.approx(1.0, abs=1e-3)
    assert attribution["side_picked_by"] == "simulation"


def test_a_stronger_sim_edge_attributes_more_of_the_stake_to_the_sim():
    weak = _plan([_row(model_edge_pct=1.0)])["positions"][0]["attribution"]
    strong = _plan([_row(model_edge_pct=6.0)])["positions"][0]["attribution"]
    assert strong["sim_share_of_stake"] > weak["sim_share_of_stake"]


def test_plan_totals_aggregate_the_attribution():
    rows = [
        _row(event_id="e1", ev_pct=4.5, model_edge_pct=3.2),
        _row(event_id="e2", ev_pct=-1.0, model_edge_pct=6.0),
        _row(event_id="e3", ev_pct=6.0, model_edge_pct=0.5),
    ]
    totals = _plan(rows)["totals"]
    assert totals["positions"] == 3
    assert 0.0 < totals["sim_share_of_staked"] <= 1.0
    assert totals["staked_dollars_sim_attributed"] <= totals["staked_dollars"]
    # e2 is the only one the model alone put on the board.
    assert totals["positions_where_sim_picked_the_side"] == 1


def test_attribution_is_scaled_with_the_stake_not_left_at_pre_budget_size():
    """The slate ceiling shrinks the committed stake; a counterfactual left at
    its pre-budget size would exceed it and the split would stop summing."""
    rows = [_row(event_id=f"e{index}") for index in range(8)]
    plan = _plan(rows, max_slate_exposure_fraction=0.01)
    assert plan["totals"]["slate_scale_factor"] < 1.0
    for position in plan["positions"]:
        attribution = position["attribution"]
        assert attribution["stake_dollars_ev_only"] <= position["stake_dollars"] + 0.02
        assert attribution["stake_dollars_ev_only"] + attribution["stake_dollars_sim_delta"] == pytest.approx(
            position["stake_dollars"], abs=0.02
        )


def test_a_sim_edge_that_shrinks_a_position_is_recorded_as_negative_not_clamped():
    """A small negative sim edge still clears Kelly on a good enough price, so
    the sim SHRANK this bet without vetoing it. Clamping that to zero would
    credit the sim only when it helps, which is how a component gets an edge it
    has not earned."""
    attribution = _plan([_row(ev_pct=8.0, model_edge_pct=-1.0)])["positions"][0]["attribution"]
    assert attribution["stake_dollars_sim_delta"] < 0
    assert attribution["sim_share_of_stake"] < 0


def test_a_zero_sim_edge_attributes_exactly_zero_not_a_rounding_artifact():
    """Regression: differencing a 5dp committed fraction against a 6dp
    counterfactual reported 2e-06 as a 0.15% sim contribution on a row whose sim
    edge was exactly zero."""
    attribution = _plan([_row(model_edge_pct=0.0)])["positions"][0]["attribution"]
    assert attribution["stake_fraction_sim_delta"] == 0.0
    assert attribution["sim_share_of_stake"] == 0.0


def test_sim_coverage_counts_rows_that_carried_a_probability_edge():
    """The board's own `sim_component` cannot answer this: at weight 0.0 it is
    structurally 0.0 for rows that HAVE a sim view and None for rows that do
    not, so it can never distinguish "the sim said nothing" from "the sim said
    something and the ranker discarded it"."""
    rows = [
        _row(event_id="e1", model_edge_pct=3.2),
        _row(event_id="e2", model_edge_pct=1.0),
        _row(event_id="e3", model_edge_pct=None),
        _row(event_id="e4", model_edge_pct=None),
    ]
    coverage = _plan(rows)["sim_coverage"]
    assert coverage["rows_in"] == 4
    assert coverage["rows_with_sim_edge"] == 2
    assert coverage["rows_without_sim_edge"] == 2
    assert coverage["share_with_sim_edge"] == 0.5


# ==========================================================================
# The Polymarket price resolver -- paper:polymarket stops being a label on
# the aggregator's prices
# ==========================================================================


def test_polymarket_now_gets_a_resolver_where_it_used_to_get_None(monkeypatch):
    """`_venue_price_resolver` returned `(None, None)` for every venue but
    Kalshi, so the paper:polymarket book was priced from the AGGREGATOR -- a
    venue label on someone else's prices."""
    from pipeline import portfolio_commit as mod

    # `event_id` is part of the resolver key and of every published board row
    # (`layer2_board.py:1825`). Without it the row is not an identity: a key of
    # (market, player, line, side) is shared by every h2h home row on the slate,
    # which is how a BAL@STL slug reached a CIN@SF position on 2026-08-25.
    board = [{"market": "h2h", "side": "Padres", "line": None, "sport": "mlb",
              "event_id": "evt-pit-sd",
              "home": "San Diego Padres", "away": "Pittsburgh Pirates",
              "selected_date": "2026-08-24"}]
    market = {"slug": "aec-mlb-pit-sd-2026-08-24",
              "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
              "outcomes": '["Pirates","Padres"]', "outcomePrices": '["0.45","0.55"]',
              "orderPriceMinTickSize": 0.01, "minimumTradeQty": 1}

    from syndicate.features.shared import polymarket_board_join as join_mod

    monkeypatch.setattr(join_mod, "load_polymarket_markets", lambda: ([market], 1787600000.0))
    monkeypatch.setattr(mod, "_board_rows_for_join", lambda _d: board)

    price, ticker = mod._venue_price_resolver("polymarket", "2026-08-24")
    assert price is not None and ticker is not None
    assert price(board[0]) == -122
    assert ticker(board[0])["slug"] == "aec-mlb-pit-sd-2026-08-24"


def test_an_absent_slate_falls_back_rather_than_half_pricing(monkeypatch):
    """`(None, None)` on every failure path, never a partial resolver. Falling
    back to the aggregator is documented and understood; a resolver built from
    half a slate would price some rows at the venue and some at the aggregator
    with no way to tell which from the outside."""
    from pipeline import portfolio_commit as mod
    from syndicate.features.shared import polymarket_board_join as join_mod

    monkeypatch.setattr(join_mod, "load_polymarket_markets", lambda: ([], None))
    assert mod._venue_price_resolver("polymarket", "2026-08-24") == (None, None)


def test_no_matches_falls_back_rather_than_returning_an_empty_resolver(monkeypatch):
    from pipeline import portfolio_commit as mod
    from syndicate.features.shared import polymarket_board_join as join_mod

    market = {"slug": "aec-nfl-lac-ten-2026-08-24",
              "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
              "outcomes": '["Chargers","Titans"]', "outcomePrices": '["0.5","0.5"]'}
    monkeypatch.setattr(join_mod, "load_polymarket_markets", lambda: ([market], 1.0))
    monkeypatch.setattr(mod, "_board_rows_for_join", lambda _d: [
        {"market": "h2h", "side": "Padres", "sport": "mlb", "home": "San Diego Padres",
         "away": "Pittsburgh Pirates", "selected_date": "2026-08-24"}])
    assert mod._venue_price_resolver("polymarket", "2026-08-24") == (None, None)


def test_kalshi_and_the_other_venues_are_unchanged(monkeypatch):
    """The Kalshi path and the quiet fallback for venues with no direct feed
    must behave exactly as before."""
    from pipeline import portfolio_commit as mod

    assert mod._venue_price_resolver("novig", "2026-08-24") == (None, None)
    assert mod._venue_price_resolver("prophetx", "2026-08-24") == (None, None)


# --------------------------------------------------------------------------
# The Kalshi resolver has to go through the board join, or it indexes nothing
# --------------------------------------------------------------------------


def _kalshi_prop_market(ticker="KXMLBHIT-26AUG251840BOSMIA-MIAARAMREZ50-1"):
    return {
        "ticker": ticker,
        "series": "KXMLBHIT",
        "title": "Agustin Ramirez: 1+ hits?",
        "yes_american": -120,
        "no_american": 105,
        "yes_ask_dollars": 0.55,
        "no_ask_dollars": 0.49,
    }


def _board_row(event_id="evt-1"):
    return {
        "event_id": event_id,
        "sport": "mlb",
        "market": "batter_hits",
        "player_name": "Agustin Ramirez",
        "line": 0.5,
        "side": "over",
        "home_team": "Miami Marlins",
        "away_team": "Boston Red Sox",
        "game_date": "2026-08-25",
    }


def test_a_match_with_no_board_event_id_can_never_be_indexed():
    """THE WHOLE DEFECT, in one assertion.

    `_match_key` indexes on `board_event_id` and returns None without one -- by
    design, because `("totals", "", 8.5, "over")` is otherwise one key for every
    8.5 total on the slate. `_resolvers_from_markets` built its match dicts by
    hand from `classify_market` alone, and a Kalshi market does not know which
    board row it belongs to. Every key was None; the index was empty; the
    resolver returned None for every row it was ever asked about.
    """
    from syndicate.features.shared.kalshi_board_join import _match_key, _row_key

    hand_built = {
        "market": "batter_hits", "player_name": "Agustin Ramirez",
        "line": 0.5, "board_side": "over", "kalshi_american": -120,
    }
    assert _match_key(hand_built) is None

    # The join stamps the one fact the market cannot know, and then the two
    # sides agree exactly.
    joined_like = dict(hand_built, board_event_id="evt-1")
    assert _match_key(joined_like) == _row_key(_board_row("evt-1"))


def test_the_kalshi_resolver_prices_a_row_it_was_silently_missing(monkeypatch):
    """END TO END, against the numbers this was found by.

    Measured 2026-08-25 4:40:11 PM Central, three artifact-reader fixes later:

        PAPER2_PLAN_WRITTEN venue=kalshi     rows_in=86 venue_priced=0
        PAPER2_PLAN_WRITTEN venue=polymarket rows_in=89 venue_priced=30

    ...while the fan-in priced 2,344 Kalshi quotes off the same artifact on the
    same service. Two matchers, one venue. Kalshi took the AGGREGATOR's price
    on all 86 rows and `venue_not_quoting` never fired, because a price was
    always found -- just not Kalshi's.
    """
    from pipeline import portfolio_commit as mod

    rows = [_board_row()]
    monkeypatch.setattr(mod, "_board_rows_for_join", lambda _d: rows)
    price_resolver, ticker_resolver = mod._resolvers_from_markets(
        [_kalshi_prop_market()], "2026-08-25"
    )

    assert price_resolver is not None, "the resolver must exist"
    assert price_resolver(rows[0]) is not None, (
        "the resolver exists but indexes nothing -- the exact silent failure"
    )
    # Price and contract id come from ONE match list, which is what stops a
    # bet being placed on a ticker at a price never quoted for it.
    assert ticker_resolver(rows[0])


def test_the_kalshi_resolver_reverts_to_the_aggregator_and_SAYS_SO(monkeypatch, capsys):
    """`(None, None)` is the documented fallback and must stay. What it must
    never do again is happen silently: the whole failure above was a venue
    quietly pricing off someone else's book with nothing in any log to say
    which."""
    from pipeline import portfolio_commit as mod

    monkeypatch.setattr(mod, "_board_rows_for_join", lambda _d: [])
    price_resolver, ticker_resolver = mod._resolvers_from_markets(
        [_kalshi_prop_market()], "2026-08-25"
    )

    assert (price_resolver, ticker_resolver) == (None, None)
    printed = capsys.readouterr().out
    assert "KALSHI_BOARD_JOIN" in printed, printed
    assert "matched=0" in printed, printed


# --------------------------------------------------------------------------
# The position cap must not spend a venue's slots on bets it cannot place
# --------------------------------------------------------------------------


def _cuttable_row(key, score, price_source, ev_pct=8.0, model_edge_pct=6.0):
    return {
        "position_key": key,
        "event_id": key,
        "sport": "mlb",
        "market": "totals",
        "side": "over",
        "line": 8.5,
        "quote": {"price": -110},
        "ev_pct": ev_pct,
        "model_edge_pct": model_edge_pct,
        "score": {"price_reliability": 0.8, "score": score},
        "price_source": price_source,
    }


def test_the_position_cap_prefers_rows_the_venue_can_actually_place():
    """AN UNPLACEABLE ROW MUST NOT HOLD A SLOT.

    A venue-scoped row priced from the AGGREGATOR carries no venue contract id
    and can never be bought at that venue. Ranking it against placeable rows
    lets a bet we cannot make consume one of `max_positions` (12) slots.

    Measured 2026-08-25 5:17:58 PM Central, the first Kalshi plan that ever
    priced off Kalshi's own book: 161 of 233 rows venue-priced, 40 cut here,
    and the ONE position that survived was `price_source=aggregator` --
    unplaceable, holding the only slot that mattered. `ORDER_PATH venue=kalshi`
    refused it `no_venue_ticker`.

    Placeability is PRIMARY, not a tiebreak: an unplaceable row's score is a
    statement about a bet we cannot hold, so ranking it above one we can
    optimises a book nobody can own.
    """
    from syndicate.features.shared.portfolio_commit import commit_portfolio
    from syndicate.features.shared.portfolio_settings import PortfolioSettings, resolve_settings

    settings = resolve_settings()
    settings = PortfolioSettings(**{**settings.__dict__, "max_positions": 2})

    rows = [
        _cuttable_row("agg-hi", 9.9, "aggregator"),
        _cuttable_row("agg-hi2", 9.8, "aggregator"),
        _cuttable_row("venue-lo", 1.0, "venue_feed"),
    ]
    plan = commit_portfolio(
        rows, selected_date="2026-08-25", settings=settings, prefer_placeable=True
    )
    # Identified by `event_id`: `position_key` is REGENERATED by hashing the
    # row's identity, not carried from the fixture.
    kept = {p.get("event_id") for p in plan["positions"]}
    assert "venue-lo" in kept, kept
    assert len(plan["positions"]) == 2


def test_the_main_plan_is_UNCHANGED_because_it_never_opts_in():
    """`prefer_placeable` is off by default and the main plan's rows carry no
    `price_source` at all.

    Explicit rather than inferred from the field's presence: a guarantee that
    depends on nobody ever setting a field is not a guarantee. With the flag
    off the order is pure score, highest first, exactly as before.
    """
    from syndicate.features.shared.portfolio_commit import commit_portfolio
    from syndicate.features.shared.portfolio_settings import PortfolioSettings, resolve_settings

    settings = resolve_settings()
    settings = PortfolioSettings(**{**settings.__dict__, "max_positions": 2})

    rows = [
        _cuttable_row("agg-hi", 9.9, "aggregator"),
        _cuttable_row("agg-hi2", 9.8, "aggregator"),
        _cuttable_row("venue-lo", 1.0, "venue_feed"),
    ]
    plan = commit_portfolio(rows, selected_date="2026-08-25", settings=settings)
    kept = [p.get("event_id") for p in plan["positions"]]
    assert kept == ["agg-hi", "agg-hi2"], kept


def test_nothing_is_dropped_by_the_preference_only_reordered():
    """The restricted-vs-unrestricted comparison keeps its full population.
    Preference decides WHO gets cut when the cap binds; it never removes a row
    from consideration, and every row is still accounted for by name."""
    from syndicate.features.shared.portfolio_commit import commit_portfolio
    from syndicate.features.shared.portfolio_settings import PortfolioSettings, resolve_settings

    settings = resolve_settings()
    settings = PortfolioSettings(**{**settings.__dict__, "max_positions": 2})

    rows = [
        _cuttable_row("agg-hi", 9.9, "aggregator"),
        _cuttable_row("venue-a", 5.0, "venue_feed"),
        _cuttable_row("venue-b", 4.0, "venue_feed"),
    ]
    plan = commit_portfolio(
        rows, selected_date="2026-08-25", settings=settings, prefer_placeable=True
    )
    # `rows_in` is top-level, and the invariant the module's own docstring
    # states: every row is accounted for by name.
    assert plan["totals"]["positions"] + sum(plan["refusals"].values()) == plan["rows_in"]
    assert plan["refusals"].get("beyond_max_positions") == 1
    # The aggregator row was the one cut, and it is still COUNTED.
    assert {p["event_id"] for p in plan["positions"]} == {"venue-a", "venue-b"}


def test_the_plan_log_names_where_the_bankroll_came_from(capsys, monkeypatch, tmp_path):
    """A bankroll printed without its provenance sends a reader to the wrong
    knob. `resolve_settings` is stored > env > default and the three are fixed
    in three different places -- the settings form, the Render dashboard, and
    this repo -- and they do not override symmetrically: setting the env var
    while a stored value exists changes nothing and looks like it worked."""
    from syndicate.features.shared import portfolio_settings as ps

    monkeypatch.delenv("SYNDICATE_BANKROLL_UNITS", raising=False)
    monkeypatch.setattr(ps, "_read_stored", lambda: ({}, None))
    assert ps.resolve_settings().sources["bankroll_units"] == "default"

    monkeypatch.setenv("SYNDICATE_BANKROLL_UNITS", "250")
    resolved = ps.resolve_settings()
    assert resolved.bankroll_units == 250.0
    assert resolved.sources["bankroll_units"] == "env"

    # STORED WINS. This is the asymmetry the log line exists to expose.
    monkeypatch.setattr(ps, "_read_stored", lambda: ({"bankroll_units": 1000.0}, None))
    resolved = ps.resolve_settings()
    assert resolved.bankroll_units == 1000.0
    assert resolved.sources["bankroll_units"] == "stored"


# ---------------------------------------------------------------------------
# WHICH MARKETS DIE WHERE. "98 rows had no model edge" cannot answer "why are
# no PROP positions being taken", and that is the question the counts get
# asked -- Kalshi's inventory is prop-heavy (batter_home_runs, strikeouts,
# player_threes) while every position taken has been a total or a moneyline.
# ---------------------------------------------------------------------------


def test_refusals_are_attributed_to_the_market_that_was_refused(monkeypatch):
    # POLICY-INDEPENDENT ON PURPOSE. These fixtures are MLB prop rows and this
    # test is about the ATTRIBUTION machinery, not about which families are
    # staked. `#615` added a sport-scoped family exclusion whose default is
    # `mlb:player_prop`, which made these rows land under
    # `market_family_excluded` and this test read as a regression in a counter
    # it does not test. Pinning the knob keeps the subject fixed.
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", "")
    from syndicate.features.shared.portfolio_commit import commit_portfolio
    from syndicate.features.shared.portfolio_settings import PortfolioSettings

    settings = PortfolioSettings(bankroll_units=1000.0, min_ev_pct=2.0, max_positions=25)

    def row(market, **over):
        base = {
            "sport": "mlb", "market": market, "side": "over", "line": 1.5,
            "quote": {"price": -110}, "ev_pct": 5.0, "model_edge_pct": 3.0,
            # `sizing_inputs_from_row` gates on this BEFORE the EV floor, so a
            # row without it never reaches `below_min_ev_pct` at all -- which is
            # what the first version of this test got wrong.
            "score": {"price_reliability": 1.0},
        }
        base.update(over)
        return base

    plan = commit_portfolio(
        [
            # No model edge -- a prop the sim does not cover.
            row("batter_home_runs", model_edge_pct=None),
            row("batter_home_runs", model_edge_pct=None),
            row("strikeouts", model_edge_pct=None),
            # Below the EV floor -- a game line the sim DOES cover.
            row("totals", ev_pct=0.5),
        ],
        selected_date="2026-08-25",
        settings=settings,
    )

    by_market = plan["refusals_by_market"]
    assert by_market["no_model_edge_pct"] == {"batter_home_runs": 2, "strikeouts": 1}
    assert by_market["below_min_ev_pct"] == {"totals": 1}

    # The per-market totals must reconcile with the flat counter, or one of the
    # two is lying about the same rows.
    for reason, count in plan["refusals"].items():
        assert sum(by_market[reason].values()) == count, reason


def test_markets_are_ordered_by_count_so_the_leader_is_first(monkeypatch):
    """The log line prints only the leader per reason; if ordering were
    arbitrary it would print an arbitrary market and read as the cause."""
    # POLICY-INDEPENDENT ON PURPOSE. These fixtures are MLB prop rows and this
    # test is about the ATTRIBUTION machinery, not about which families are
    # staked. `#615` added a sport-scoped family exclusion whose default is
    # `mlb:player_prop`, which made these rows land under
    # `market_family_excluded` and this test read as a regression in a counter
    # it does not test. Pinning the knob keeps the subject fixed.
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", "")
    from syndicate.features.shared.portfolio_commit import commit_portfolio
    from syndicate.features.shared.portfolio_settings import PortfolioSettings

    rows = [
        {"sport": "mlb", "market": "strikeouts", "side": "over", "line": 1.5,
         "quote": {"price": -110}, "ev_pct": 5.0}
    ] * 1 + [
        {"sport": "mlb", "market": "batter_home_runs", "side": "over", "line": 1.5,
         "quote": {"price": -110}, "ev_pct": 5.0}
    ] * 3
    plan = commit_portfolio(rows, selected_date="2026-08-25",
                            settings=PortfolioSettings(bankroll_units=1000.0))
    markets = plan["refusals_by_market"]["no_model_edge_pct"]
    assert list(markets) == ["batter_home_runs", "strikeouts"]


def test_a_refusal_with_no_market_is_counted_not_dropped():
    """Silently omitting it would make the per-market totals disagree with
    `refusals` for no visible reason."""
    from syndicate.features.shared.portfolio_commit import commit_portfolio
    from syndicate.features.shared.portfolio_settings import PortfolioSettings

    plan = commit_portfolio(["not a mapping"], selected_date="2026-08-25",
                            settings=PortfolioSettings())
    assert plan["refusals"]["row_not_a_mapping"] == 1
    assert plan["refusals_by_market"]["row_not_a_mapping"] == {"unkeyed": 1}


def test_no_model_edge_refusals_are_attributed_BY_SPORT(monkeypatch) -> None:
    """The market cut cannot answer WHICH SPORT is unsized, and that is the
    question the number gets asked.

    Measured 2026-09-03 across 4 days and 4 venues: 6,312 of 6,722 in-scope rows
    (93.9%) refused `no_model_edge_pct`, while the board's own projection join
    reported MLB at 1,472/1,645 (89%) and NFL at 6,643/8,736 (76%) coverage the
    same day. Those readings cannot both describe the same sport, and with no
    sport on the refusal there was no way to tell which one was wrong -- board
    coverage does not transfer, because a venue plan only holds rows that venue
    quotes.
    """
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", "")
    from syndicate.features.shared.portfolio_commit import commit_portfolio
    from syndicate.features.shared.portfolio_settings import PortfolioSettings

    rows = [
        {"sport": "mlb", "market": "strikeouts", "side": "over", "line": 1.5,
         "quote": {"price": -110}, "ev_pct": 5.0},
        {"sport": "soccer", "market": "player_shots", "side": "over", "line": 1.5,
         "quote": {"price": -110}, "ev_pct": 5.0},
        {"sport": "soccer", "market": "player_shots", "side": "over", "line": 2.5,
         "quote": {"price": -110}, "ev_pct": 5.0},
    ]
    plan = commit_portfolio(rows, selected_date="2026-08-25",
                            settings=PortfolioSettings(bankroll_units=1000.0))

    by_sport = plan["refusals_by_sport"]["no_model_edge_pct"]
    assert by_sport == {"soccer": 2, "mlb": 1}
    # Sorted by count desc, like the market cut, so the leader reads first.
    assert list(by_sport) == ["soccer", "mlb"]


def test_the_sport_split_RECONCILES_with_the_refusal_total(monkeypatch) -> None:
    """A split that does not sum to its parent is two numbers, not one fact."""
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", "")
    from syndicate.features.shared.portfolio_commit import commit_portfolio
    from syndicate.features.shared.portfolio_settings import PortfolioSettings

    rows = [
        {"sport": "mlb", "market": "strikeouts", "side": "over", "line": 1.5,
         "quote": {"price": -110}, "ev_pct": 5.0},
        {"sport": "", "market": "totals", "side": "over", "line": 2.5,
         "quote": {"price": -110}, "ev_pct": 5.0},
    ]
    plan = commit_portfolio(rows, selected_date="2026-08-25",
                            settings=PortfolioSettings(bankroll_units=1000.0))

    for reason, total in plan["refusals"].items():
        split = plan["refusals_by_sport"].get(reason, {})
        assert sum(split.values()) == total, reason
    # A row with no sport is counted as `unkeyed`, never dropped -- dropping it
    # is exactly how a split stops reconciling without anything looking wrong.
    assert plan["refusals_by_sport"]["no_model_edge_pct"].get("unkeyed") == 1
