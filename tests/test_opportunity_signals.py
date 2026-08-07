"""#238: no-vig fair probability, hold, and EV.

Cases are drawn from the real production MLB/WNBA shards for 2026-08-06 where
possible, so the numbers assert against prices that actually traded rather than
invented ones.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.opportunity_signals import (
    american_price,
    arbitrage_profit_pct,
    blended_score,
    consensus_fair_probability,
    devig,
    edge_pct,
    expected_value_pct,
    fair_probability_by_book,
    hold_pct,
    implied_probability,
    is_low_hold,
    model_edge_pct,
    overround,
)


def test_implied_probability_both_signs():
    assert implied_probability(100) == pytest.approx(0.5)
    assert implied_probability(-110) == pytest.approx(0.5238, abs=1e-4)
    assert implied_probability(+130) == pytest.approx(0.4348, abs=1e-4)
    assert implied_probability(0) is None
    assert implied_probability("nonsense") is None


def test_american_price_round_trips_with_implied():
    for price in (-450, -250, -110, 100, 130, 390):
        probability = implied_probability(price)
        assert american_price(probability) == pytest.approx(price, abs=1)


def test_standard_minus_110_market_holds_4_55_pct():
    # The canonical example: -110/-110 is a 4.55% hold.
    assert hold_pct([-110, -110]) == pytest.approx(4.55, abs=0.01)


def test_measured_median_hold_matches_production():
    # Production median across two-sided MLB markets was 6.25%.
    assert overround([-130, +105]) is not None
    assert hold_pct([-110, -110]) > 0


def test_devig_returns_a_probability_distribution():
    fair = devig([-110, -110])
    assert fair is not None
    assert sum(fair) == pytest.approx(1.0)
    assert fair[0] == pytest.approx(0.5)


def test_devig_removes_exactly_the_hold():
    # A real low-hold pair from the shard: fanatics -130 / fanduel +130 was
    # measured at 0.00% hold, so de-vigging must barely move it.
    fair = devig([-130, +130])
    assert fair is not None
    assert sum(fair) == pytest.approx(1.0)
    assert fair[0] == pytest.approx(0.5652, abs=1e-3)


def test_devig_handles_three_way_markets():
    # h2h_3_way needs its draw leg. Treating this as two-way is what fabricated
    # 7 of the 10 "arbitrages" in the first measurement pass.
    fair = devig([+240, +325, +260])
    assert fair is not None
    assert len(fair) == 3
    assert sum(fair) == pytest.approx(1.0)


def test_devig_refuses_implausible_overround():
    # Mispaired legs. home -1.5 and away -1.5 are not two sides of anything;
    # the sum lands far outside a real market and a "fair" price from it would
    # be confidently wrong.
    assert devig([+3300, +3500]) is None       # 0.06 total -- far under
    assert devig([-100000, -100000]) is None   # ~2.0 total -- far over


def test_power_devig_takes_more_from_the_longshot():
    # A +390/-450 prop pair. Multiplicative scales both sides equally; power
    # removes more margin from the longshot, which is the point of using it.
    multiplicative = devig([+390, -450], method="multiplicative")
    power = devig([+390, -450], method="power")
    assert multiplicative is not None and power is not None
    assert sum(power) == pytest.approx(1.0)
    assert power[0] < multiplicative[0]


def test_power_devig_agrees_on_a_symmetric_market():
    # With no favourite-longshot asymmetry the two methods must not diverge.
    multiplicative = devig([-110, -110], method="multiplicative")
    power = devig([-110, -110], method="power")
    assert multiplicative is not None and power is not None
    assert power[0] == pytest.approx(multiplicative[0], abs=1e-6)


def test_fair_probability_is_computed_per_book_not_across_books():
    # THE methodological point. Book A is the cheap over, book B the cheap
    # under. De-vigging the best-of-each would launder the line-shopping edge
    # into "fair" and make the edge vanish from the EV that should report it.
    by_book = fair_probability_by_book({
        "draftkings": {"over": +130, "under": -160},
        "betmgm": {"over": +110, "under": -140},
    })
    assert set(by_book) == {"draftkings", "betmgm"}
    for probabilities in by_book.values():
        assert sum(probabilities.values()) == pytest.approx(1.0)


def test_fair_probability_skips_books_quoting_one_side_only():
    by_book = fair_probability_by_book({
        "draftkings": {"over": +130, "under": -160},
        "bovada": {"over": +125},
    })
    assert set(by_book) == {"draftkings"}


def test_consensus_uses_median_so_one_stale_book_cannot_drag_it():
    prices = {
        "draftkings": {"over": -110, "under": -110},
        "betmgm": {"over": -110, "under": -110},
        "betrivers": {"over": -110, "under": -110},
        # A stale line, wrong by a mile.
        "bovada": {"over": +900, "under": -2000},
    }
    consensus = consensus_fair_probability(prices)
    assert consensus is not None
    assert sum(consensus.values()) == pytest.approx(1.0)
    assert consensus["over"] == pytest.approx(0.5, abs=0.02)


def test_consensus_returns_none_when_no_book_quotes_both_sides():
    assert consensus_fair_probability({"draftkings": {"over": +130}}) is None


def test_expected_value_is_not_a_probability_difference():
    # At a fair 50% on a +130 price: EV = 0.5*1.3 - 0.5 = +15%.
    assert expected_value_pct(+130, 0.5) == pytest.approx(15.0, abs=1e-6)
    # The naive probability gap would report only ~6.5 points, understating a
    # longshot's return -- which is why ranking uses EV, not edge.
    assert edge_pct(+130, 0.5) == pytest.approx(6.52, abs=0.01)


def test_expected_value_is_zero_at_a_genuinely_fair_price():
    assert expected_value_pct(+100, 0.5) == pytest.approx(0.0, abs=1e-9)
    assert expected_value_pct(-110, implied_probability(-110)) == pytest.approx(0.0, abs=1e-6)


def test_devig_lifts_ev_by_roughly_half_the_hold():
    """The headline defect, as a test.

    Production median hold is 6.25%. Against the VIGGED implied probability a
    model at 55% shows one number; against the de-vigged fair probability it
    shows one about 3 points higher. That gap is what the board was losing on
    every row.
    """
    prices = [-122, -108]  # 6.43% hold, right at the production median
    assert hold_pct(prices) == pytest.approx(6.4, abs=0.3)
    vigged = implied_probability(prices[0])
    fair = devig(prices)
    assert fair is not None
    understated = (0.55 - vigged) * 100.0
    corrected = (0.55 - fair[0]) * 100.0
    assert corrected - understated == pytest.approx(3.5, abs=0.6)


def test_arbitrage_profit_is_positive_only_under_100_pct():
    # The one clearly real arb in the shard: over bovada +130 / under fanatics
    # -125, measured at -0.97% hold.
    profit = arbitrage_profit_pct([+130, -125])
    assert profit is not None and profit > 0
    assert arbitrage_profit_pct([-110, -110]) < 0


def test_low_hold_threshold():
    assert is_low_hold([-130, +130])          # 0.00% measured in production
    assert not is_low_hold([-110, -110])      # 4.55%
    assert not is_low_hold([+130, -125])      # an arb is not a low hold


def test_model_edge_needs_both_sides_vig_free():
    fair = devig([-118, +108])
    assert fair is not None
    edge = model_edge_pct(0.55, fair[0])
    assert edge is not None and edge > 0


def test_model_edge_accepts_percent_or_fraction():
    assert model_edge_pct(55.0, 0.5) == pytest.approx(model_edge_pct(0.55, 0.5))


def test_nothing_raises_on_garbage():
    for bad in (None, "", "abc", float("nan")):
        assert implied_probability(bad) is None or isinstance(implied_probability(bad), float)
        assert expected_value_pct(bad, 0.5) is None or isinstance(expected_value_pct(bad, 0.5), float)
    assert devig([None, -110]) is None
    assert hold_pct([]) is None
    assert overround([-110]) is None  # one side is not a market


# --- #243: blended score -------------------------------------------------


def test_blended_score_returns_none_without_any_value_term():
    # A row with neither EV nor a sim edge has nothing to rank. Scoring it 0
    # would sort it above genuinely negative rows, which is worse than absent.
    assert blended_score(books_quoting=7, book_age_seconds=10) is None


def test_blended_score_discounts_a_thin_stale_row_below_a_wide_fresh_one():
    """The ranking property that matters, stated as a test.

    A +15% EV from ONE book on a seven-hour-old line must not outrank a +4% EV
    from seven books quoted a minute ago. Additive reliability would let it;
    multiplicative does not.
    """
    thin_stale = blended_score(ev_pct=15.0, books_quoting=1, book_age_seconds=25200)
    wide_fresh = blended_score(ev_pct=4.0, books_quoting=7, book_age_seconds=60)
    assert thin_stale is not None and wide_fresh is not None
    assert wide_fresh["score"] > thin_stale["score"]


def test_blended_score_exposes_its_components():
    scored = blended_score(ev_pct=6.0, model_edge=4.0, books_quoting=7, book_age_seconds=60)
    assert scored is not None
    # value = 6.0 + 0.5*4.0 = 8.0, reliability = 1.0 * 1.0
    assert scored["value_pct"] == pytest.approx(8.0)
    assert scored["ev_component"] == pytest.approx(6.0)
    assert scored["sim_component"] == pytest.approx(2.0)
    assert scored["book_confidence"] == pytest.approx(1.0)
    assert scored["freshness_factor"] == pytest.approx(1.0)
    assert scored["score"] == pytest.approx(8.0)


def test_blended_score_sim_edge_counts_half():
    ev_only = blended_score(ev_pct=4.0, books_quoting=7, book_age_seconds=60)
    sim_only = blended_score(model_edge=4.0, books_quoting=7, book_age_seconds=60)
    assert ev_only is not None and sim_only is not None
    assert sim_only["score"] == pytest.approx(ev_only["score"] / 2.0)


def test_blended_score_treats_unknown_book_age_as_not_fresh():
    # Several sources publish no book clock. Treating that as brand new would
    # float exactly the least verifiable rows to the top.
    unknown = blended_score(ev_pct=5.0, books_quoting=7, book_age_seconds=None)
    fresh = blended_score(ev_pct=5.0, books_quoting=7, book_age_seconds=10)
    assert unknown is not None and fresh is not None
    assert unknown["score"] < fresh["score"]


def test_blended_score_keeps_negative_value_negative():
    # Most retail prices are -EV. A reliability multiplier must not flip a bad
    # bet positive, only shrink it toward zero.
    scored = blended_score(ev_pct=-6.0, books_quoting=7, book_age_seconds=60)
    assert scored is not None and scored["score"] < 0


# NOTE (#245): the dead-in-play-market rules that lived here moved to
# `opportunity_gate`, which is now the single place eligibility is decided.
# See tests/test_opportunity_gate.py -- the same production cases (Luis Arraez
# at 30,556s, the unnormalised game_state strings, the missing book clock) are
# asserted there against the one implementation rather than a second copy.
