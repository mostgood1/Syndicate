"""`wnba/cards.py::_american_from_prob` must refuse, not clamp.

Lane `probability-clamp-removal`, following the Tier 3a differential
(`d448a100`). The old body clamped to `[0.02, 0.98]`, which is why the sibling
copies published `fair_price` -4900 for a `fair_probability` of 0.992056 where
the correct price is -12488.

The distinction these tests protect is narrow and worth naming: a **clamp**
answers an out-of-range question with a confident in-range number, while a
**guard** declines to answer. On a betting surface the second is correct --
"absent renders as absent" (web `932a1f71` / `a86eb4ed`) -- because a fabricated
price is indistinguishable from a real one once it is on the card.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared.opportunity_signals import american_price
from syndicate.features.shared.opportunity_signals import implied_probability
from syndicate.features.wnba.cards import _american_from_prob
from syndicate.features.wnba.cards import _source_betting


class TestRefusesRatherThanClamps:
    @pytest.mark.parametrize("probability", [0.0, 1.0, -0.5, 1.5])
    def test_out_of_domain_is_refused(self, probability):
        """The old body returned +/-4900 for every one of these."""
        assert _american_from_prob(probability) is None

    def test_percent_scale_is_refused(self):
        """50.0 is a unit error, not a 50-to-1 favourite.

        `confidence` is stored 0-100 and probability 0-1 in the same rows, so
        this is the substitution most likely to happen silently. The clamp
        answered it with -4900, which looks like a real price.
        """
        assert _american_from_prob(50.0) is None

    @pytest.mark.parametrize("probability", [None, "", "abc"])
    def test_missing_or_unparseable_is_refused_without_raising(self, probability):
        assert _american_from_prob(probability) is None

    def test_extremes_inside_the_domain_are_priced_correctly_not_clamped(self):
        """The regression the differential actually caught.

        Under the clamp both of these returned +/-4900 -- the same price for two
        materially different probabilities.
        """
        assert _american_from_prob(0.99) == -9900
        assert _american_from_prob(0.992056) == -12488
        assert _american_from_prob(0.01) == 9900

    def test_round_trips_through_the_inverse(self):
        """A clamp cannot round-trip a probability outside its clamp; this is
        what separated `american_price` from the other four implementations
        without anyone having to prefer one."""
        for probability in (0.01, 0.25, 0.5238, 0.75, 0.98, 0.99):
            priced = _american_from_prob(probability)
            assert priced is not None
            assert implied_probability(priced) == pytest.approx(probability, abs=5e-3)

    def test_delegates_rather_than_carrying_a_fifth_copy(self):
        for probability in (0.02, 0.4, 0.5, 0.5238, 0.98, 0.0, 1.0, None, 50.0):
            assert _american_from_prob(probability) == american_price(probability)


class TestCallSitesStillProduceAPrice:
    """The lane's falsification test: a moneyline that renders today must not go
    blank for a probability strictly inside 0..1."""

    def test_normal_model_probability_still_yields_a_moneyline(self):
        betting = _source_betting({"p_home_win": "0.61", "pred_margin": "8.0"})
        assert betting.get("home_ml") is not None
        assert betting.get("away_ml") is not None

    def test_derived_moneyline_matches_the_canonical_price(self):
        betting = _source_betting({"p_home_win": "0.61", "pred_margin": "8.0"})
        assert betting["home_ml"] == american_price(0.61)

    def test_a_degenerate_certainty_now_renders_absent(self):
        """p=1.0 is not a price, it is a broken sim output.

        Blank is the correct rendering. Asserted explicitly because it IS a
        user-visible change from the clamped -4900, and a future reader should
        find it recorded as intended rather than as a regression.
        """
        betting = _source_betting({"p_home_win": "1.0", "pred_margin": "40.0"})
        assert betting.get("home_ml") is None

    def test_a_book_supplied_moneyline_is_untouched(self):
        """The converter only fills a MISSING price; a real book line wins."""
        betting = _source_betting({"home_ml": "-200", "away_ml": "170", "pred_margin": "1.0"})
        # Compared numerically: `_source_betting` float-coerces a supplied price
        # to -200.0, which predates this change and is not what is under test.
        assert float(betting["home_ml"]) == -200.0
