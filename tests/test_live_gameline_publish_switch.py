"""The sport-scoped publish switch: publication stops, measurement does not.

WHY THIS EXISTS. The MLB live game-line model loses to the market over 252
games / 19 dates (pooled +0.00905, bootstrap-over-games CI [+0.00154,
+0.01686], excludes zero), the deficit is RESOLUTION not calibration, and all
three cheap fixes are closed by measurement -- recalibration capped at 6.5%, no
subpopulation surviving leave-one-date-out, and a model/market blend that is
significantly worse out of sample. So MLB stops publishing edges.

THE TWO THINGS THAT MUST NOT BREAK, and neither is about MLB:

  1. SCOPE. The pre-existing floor `SYNDICATE_LIVE_GAMELINE_MIN_EDGE_PP` is
     GLOBAL and sport-blind. Using it would have silenced WNBA -- whose model
     BEATS the market on the record (-0.12504) -- on MLB-only evidence. Every
     test here that names wnba is guarding that, not padding the count.

  2. MEASUREMENT. A disabled row must still carry `edge_pp` and
     `prob_std_err` and still reach the ledger as non-priceable. Turning
     publication off must not destroy the evidence needed to ever turn it back
     on, including the `pregame_home_win_prob` shrink-toward-prior test that
     only just became possible.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.live_gameline_join import (
    REASON_NOT_PRICEABLE,
    REASON_PUBLISH_DISABLED,
    price_moneyline,
    publishing_disabled_for_sport,
)

ENV = "SYNDICATE_LIVE_GAMELINE_PUBLISH_DISABLED_SPORTS"

# A big, precise edge: comfortably clears the 2-sigma bar at 120 sims, so
# anything that refuses it is refusing on purpose rather than on precision.
CLEARS_THE_BAR = dict(model_prob=0.75, market_prob=0.50, sims=120)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


class TestOffIsNotOn:
    """Reachability before correctness: prove the flag does something."""

    def test_off_prices_mlb_exactly_as_before(self):
        v = price_moneyline(**CLEARS_THE_BAR, sport="mlb")
        assert v["priceable"] is True
        assert v["withheld_reason"] is None

    def test_on_refuses_mlb_by_its_own_name(self, monkeypatch):
        monkeypatch.setenv(ENV, "mlb")
        v = price_moneyline(**CLEARS_THE_BAR, sport="mlb")
        assert v["priceable"] is False
        assert v["withheld_reason"] == REASON_PUBLISH_DISABLED

    def test_the_refusal_is_NOT_the_precision_refusal(self, monkeypatch):
        """A 999pp `min_edge_pp` would produce the same silence under the WRONG
        name. `not_priceable` means "too small to trust"; this means "we do not
        believe this model". A reader must be able to tell them apart forever."""
        monkeypatch.setenv(ENV, "mlb")
        v = price_moneyline(**CLEARS_THE_BAR, sport="mlb")
        assert v["withheld_reason"] != REASON_NOT_PRICEABLE


class TestScopeIsPerSport:
    """The whole reason this is not the existing global knob."""

    def test_disabling_mlb_leaves_wnba_publishing(self, monkeypatch):
        monkeypatch.setenv(ENV, "mlb")
        assert price_moneyline(**CLEARS_THE_BAR, sport="wnba")["priceable"] is True

    def test_disabling_mlb_leaves_soccer_and_ncaaf_publishing(self, monkeypatch):
        monkeypatch.setenv(ENV, "mlb")
        for sport in ("soccer", "ncaaf"):
            assert price_moneyline(**CLEARS_THE_BAR, sport=sport)["priceable"] is True, sport

    def test_several_sports_can_be_disabled_together(self, monkeypatch):
        monkeypatch.setenv(ENV, "mlb, soccer")
        assert price_moneyline(**CLEARS_THE_BAR, sport="mlb")["priceable"] is False
        assert price_moneyline(**CLEARS_THE_BAR, sport="soccer")["priceable"] is False
        assert price_moneyline(**CLEARS_THE_BAR, sport="wnba")["priceable"] is True

    @pytest.mark.parametrize("raw", ["MLB", "  mlb  ", "wnba,mlb", "mlb,,"])
    def test_the_list_is_parsed_forgivingly(self, monkeypatch, raw):
        monkeypatch.setenv(ENV, raw)
        assert publishing_disabled_for_sport("mlb") is True

    def test_an_absent_sport_is_never_silenced(self, monkeypatch):
        """UNKNOWN MUST NOT TAKE THE PERMISSIVE BRANCH IN EITHER DIRECTION. A row
        with no sport cannot be shown to be disabled -- and must not be disabled
        by accident, which would suppress a sport nobody named."""
        monkeypatch.setenv(ENV, "mlb")
        for missing in (None, "", "   "):
            assert publishing_disabled_for_sport(missing) is False
            assert price_moneyline(**CLEARS_THE_BAR, sport=missing)["priceable"] is True


class TestMeasurementSurvives:
    """Publication stops; the denominator does not."""

    def test_disabling_changes_ONLY_the_publication_decision(self, monkeypatch):
        """The invariant, stated directly rather than as magic numbers: every
        field the ledger scores the model on is byte-identical with the switch
        off and on. Only `priceable` and `withheld_reason` may differ.

        (The raw 0.75 becomes 0.7419 via Agresti-Coull add-two smoothing at
        n=120, so `edge_pp` is 24.19 and not 25.0 -- deliberate, and equally
        true on both sides of this comparison, which is the point.)
        """
        off = price_moneyline(**CLEARS_THE_BAR, sport="mlb")
        monkeypatch.setenv(ENV, "mlb")
        on = price_moneyline(**CLEARS_THE_BAR, sport="mlb")

        assert off["priceable"] is True and on["priceable"] is False
        for field in set(off) | set(on):
            if field in {"priceable", "withheld_reason"}:
                continue
            assert off.get(field) == on.get(field), f"{field} changed when publication was disabled"

        # and the fields must actually be POPULATED -- an all-None row would
        # satisfy the equality above while carrying no measurement at all.
        assert on["edge_pp"] is not None
        assert on["prob_std_err"] is not None
        assert on["model_prob"] is not None
        assert on["market_prob"] == pytest.approx(0.50)
        assert on["model_prob_raw"] == pytest.approx(0.75)

    def test_the_switch_is_applied_AFTER_the_precision_gate(self, monkeypatch):
        """Ordering matters and is not cosmetic. A row that fails the precision
        bar must still say so, otherwise disabling a sport would rewrite the
        history of WHY rows were refused and make the two causes
        indistinguishable in the ledger."""
        monkeypatch.setenv(ENV, "mlb")
        tiny = price_moneyline(model_prob=0.501, market_prob=0.500, sims=120, sport="mlb")
        assert tiny["withheld_reason"] == REASON_NOT_PRICEABLE

    def test_default_is_off_so_no_sport_changes_without_being_named(self):
        for sport in ("mlb", "wnba", "soccer", "ncaaf", None):
            assert publishing_disabled_for_sport(sport) is False
