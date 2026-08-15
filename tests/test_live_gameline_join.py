"""Drop 3 — the live game-line join prices, or refuses by name.

Lane `live-game-line-projection`. Built to the recorded user decision on spec
§8.1: PUBLISH, REFUSE TO PRICE at 120 sims.

The load-bearing tests here are the REFUSALS. A join that prices everything at
120 sims would publish a 2-point edge off a 4.56-point interval, which is the
specific harm the decision exists to prevent.
"""

from __future__ import annotations

import math

import pytest

from syndicate.features.shared.live_gameline_join import (
    PRICEABLE_SIGMA,
    REASON_NOT_PRICEABLE,
    REASON_NO_LIVE_PROJECTION,
    REASON_NO_MARKET_PRICE,
    REASON_TOTALS_MEAN,
    REASON_UNUSABLE_SIMS,
    attach_live_gamelines,
    build_live_gameline_index,
    live_gameline_from_lens,
    new_coverage,
    price_moneyline,
    prob_std_err,
    record,
    withhold_totals,
)


class TestProbStdErr:
    def test_matches_the_spec_table_at_120_sims(self):
        """The number the whole decision rests on: ±4.56 pp at p=0.5, n=120."""
        assert prob_std_err(0.5, 120) == pytest.approx(0.04564, abs=1e-5)
        assert prob_std_err(0.75, 120) == pytest.approx(0.03953, abs=1e-5)
        assert prob_std_err(0.90, 120) == pytest.approx(0.02739, abs=1e-5)

    def test_scales_as_one_over_sqrt_n(self):
        assert prob_std_err(0.5, 2500) == pytest.approx(0.01, abs=1e-4)

    @pytest.mark.parametrize("p,n", [(None, 120), (0.5, None), (0.5, 0), (0.5, -1),
                                     (-0.1, 120), (1.1, 120), ("x", 120), (0.5, "x")])
    def test_bad_input_is_none_never_zero(self, p, n):
        """A 0.0 would read as 'perfectly precise' and make everything
        priceable -- the worst substitution available in this module."""
        assert prob_std_err(p, n) is None


class TestLiveGamelineFromLens:
    def _lens(self, source, prob, key="live"):
        return [{"key": key, "source": source, "modelHomeWinProb": prob,
                 "simsRun": 120, "projection": {"total": 8.5, "homeMargin": 0.7}}]

    def test_reads_a_live_mc_lane(self):
        got = live_gameline_from_lens(self._lens("live_mc", 0.6842))
        assert got is not None
        assert got["home_win_prob"] == pytest.approx(0.6842)
        assert got["sims_run"] == 120

    def test_ignores_a_segment_lane_that_carries_a_probability(self):
        """THE TRAP. `_build_game_lens` stamps modelHomeWinProb on first1/3/5
        from a segment interpolation. Keying on the probability's presence would
        accept a lens the re-sim never touched."""
        assert live_gameline_from_lens(self._lens("segment_projection", 0.51, key="first3")) is None

    @pytest.mark.parametrize("rows", [None, [], "live_mc", [None], [{}],
                                      [{"source": "live_mc"}],
                                      [{"source": "live_mc", "modelHomeWinProb": None}],
                                      [{"source": "live_mc", "modelHomeWinProb": 1.4}],
                                      [{"source": "live_mc", "modelHomeWinProb": "x"}]])
    def test_malformed_is_none_not_an_exception(self, rows):
        assert live_gameline_from_lens(rows) is None


class TestPriceMoneyline:
    def test_a_big_edge_clears_the_gate(self):
        """0.68 vs 0.50 is 18 points against a 2-sigma bar of ~9.1."""
        v = price_moneyline(model_prob=0.68, market_prob=0.50, sims=120)
        assert v["priceable"] is True
        assert v["withheld_reason"] is None
        assert v["edge_pp"] == pytest.approx(18.0)

    def test_a_two_point_edge_is_REFUSED_at_120_sims(self):
        """The decision in one assertion. 2 points against a ~9.1-point bar."""
        v = price_moneyline(model_prob=0.52, market_prob=0.50, sims=120)
        assert v["priceable"] is False
        assert v["withheld_reason"] == REASON_NOT_PRICEABLE
        assert v["edge_pp"] == pytest.approx(2.0)
        # The edge is still REPORTED -- withheld is not the same as hidden.
        # NB the SE is evaluated at the MODEL's p (0.52), not at 0.5, so it is
        # 0.045613 and not the table's 0.045644. See the class docstring below.
        assert v["prob_std_err"] == pytest.approx(prob_std_err(0.52, 120))

    def test_the_same_two_point_edge_PRICES_at_2500_sims(self):
        """Raising sims is the honest lever, and it needs no change here:
        at n=2500 the bar is 2.0 points and a 2.0-point edge clears it."""
        v = price_moneyline(model_prob=0.52, market_prob=0.50, sims=2500)
        assert v["priceable"] is True

    def test_the_gate_is_symmetric_for_negative_edges(self):
        v = price_moneyline(model_prob=0.32, market_prob=0.50, sims=120)
        assert v["priceable"] is True
        assert v["edge_pp"] == pytest.approx(-18.0)

    def test_units_are_points_on_both_sides_of_the_gate(self):
        """A unit mismatch here would decide what gets published.

        THE MODEL PROBABILITY IS HELD FIXED AND THE MARKET IS MOVED. An earlier
        version of this test varied the model instead and failed: the SE is
        evaluated at the model's OWN p, so moving p moves the bar underneath the
        assertion. That is correct behaviour -- the interval belongs to the
        estimate being published -- but it makes 'the bar' meaningless unless p
        is pinned.
        """
        p = 0.5
        se = prob_std_err(p, 120)
        bar = PRICEABLE_SIGMA * se * 100.0
        just_over = price_moneyline(model_prob=p, sims=120,
                                    market_prob=p - (bar + 0.01) / 100.0)
        just_under = price_moneyline(model_prob=p, sims=120,
                                     market_prob=p - (bar - 0.01) / 100.0)
        assert just_over["priceable"] is True
        assert just_under["priceable"] is False
        assert just_under["withheld_reason"] == REASON_NOT_PRICEABLE

    def test_the_bar_moves_with_the_model_probability(self):
        """Pinned because it caused a wrong test and could cause a wrong
        reading: a lopsided game has a tighter interval, so a given edge clears
        more easily at p=0.9 than at p=0.5."""
        assert prob_std_err(0.9, 120) < prob_std_err(0.5, 120)
        edge_pp = 7.0
        at_half = price_moneyline(model_prob=0.5, market_prob=0.5 - edge_pp / 100.0, sims=120)
        at_high = price_moneyline(model_prob=0.9, market_prob=0.9 - edge_pp / 100.0, sims=120)
        assert at_half["priceable"] is False   # bar ~9.13
        assert at_high["priceable"] is True    # bar ~5.48

    @pytest.mark.parametrize("market", [None, "x", 0.0, 1.0, -0.2, 1.5])
    def test_no_usable_market_price_refuses_by_name(self, market):
        v = price_moneyline(model_prob=0.6, market_prob=market, sims=120)
        assert v["priceable"] is False
        assert v["withheld_reason"] == REASON_NO_MARKET_PRICE

    def test_absent_model_probability_refuses_by_name(self):
        v = price_moneyline(model_prob=None, market_prob=0.5, sims=120)
        assert v["withheld_reason"] == REASON_NO_LIVE_PROJECTION

    @pytest.mark.parametrize("sims", [0, 5, 19, None, "x"])
    def test_too_few_sims_refuses_by_name(self, sims):
        v = price_moneyline(model_prob=0.9, market_prob=0.5, sims=sims)
        assert v["priceable"] is False
        assert v["withheld_reason"] == REASON_UNUSABLE_SIMS

    def test_a_verdict_is_never_none(self):
        """An absent verdict is how 'withheld' silently becomes
        'not considered', which is how the prop counter's zero went undiagnosed."""
        for kwargs in ({"model_prob": None, "market_prob": None, "sims": None},
                       {"model_prob": 0.5, "market_prob": 0.5, "sims": 120}):
            v = price_moneyline(**kwargs)
            assert isinstance(v, dict)
            assert "priceable" in v and "prob_std_err" in v


def test_totals_always_refuse_because_a_mean_is_not_a_distribution():
    v = withhold_totals()
    assert v["priceable"] is False
    assert v["withheld_reason"] == REASON_TOTALS_MEAN


class TestCoverageCounters:
    def test_considered_is_the_denominator_for_everything(self):
        cov = new_coverage()
        record(cov, price_moneyline(model_prob=0.68, market_prob=0.50, sims=120), projected=True)
        record(cov, price_moneyline(model_prob=0.52, market_prob=0.50, sims=120), projected=True)
        record(cov, withhold_totals(), projected=True)
        record(cov, price_moneyline(model_prob=None, market_prob=0.5, sims=120), projected=False)

        assert cov["rows_live_gameline_considered"] == 4
        assert cov["rows_live_gameline_projected"] == 3
        assert cov["rows_live_gameline_edged"] == 1
        assert cov["rows_live_gameline_priceable"] == 1
        assert cov["rows_live_gameline_withheld"] == 3

    def test_every_withheld_row_names_its_reason(self):
        """Success is 'edged > 0 with every withheld row naming its reason' --
        a zero must be diagnosable, not mysterious."""
        cov = new_coverage()
        record(cov, price_moneyline(model_prob=0.52, market_prob=0.50, sims=120), projected=True)
        record(cov, withhold_totals(), projected=True)
        record(cov, price_moneyline(model_prob=0.6, market_prob=None, sims=120), projected=True)

        assert cov["withheld_by_reason"] == {
            REASON_NOT_PRICEABLE: 1,
            REASON_TOTALS_MEAN: 1,
            REASON_NO_MARKET_PRICE: 1,
        }
        assert sum(cov["withheld_by_reason"].values()) == cov["rows_live_gameline_withheld"]

    def test_counters_reconcile(self):
        cov = new_coverage()
        for p in (0.9, 0.52, 0.51, 0.2):
            record(cov, price_moneyline(model_prob=p, market_prob=0.5, sims=120), projected=True)
        assert (cov["rows_live_gameline_edged"] + cov["rows_live_gameline_withheld"]
                == cov["rows_live_gameline_considered"])


class TestIndexAndAttach:
    """The join itself, against the shapes measured in production 2026-08-15."""

    def _snapshot(self, prob=0.6842, source="live_mc", sims=120):
        return {"games": [{
            "gamePk": 823184,
            "status": {"abstract": "Live"},
            "matchup": {"away": {"name": "Colorado Rockies", "abbr": "COL"},
                        "home": {"name": "San Francisco Giants", "abbr": "SF"}},
            "gameLens": [{"key": "live", "source": source, "modelHomeWinProb": prob,
                          "simsRun": sims, "projection": {"total": 8.5, "homeMargin": 0.7}}],
        }]}

    def _row(self, state="live", market="h2h", kind="game", market_prob=0.50):
        return {"kind": kind, "market": market,
                "away_team": "Colorado Rockies", "home_team": "San Francisco Giants",
                "game": {"state": state},
                "projection": {"market_fair_prob_over": market_prob,
                               "edge_unavailable_reason": "game is live: a pregame projection cannot be priced against a live market",
                               "edge_vs_market_pct": None}}

    def test_index_keys_on_full_team_names(self):
        idx = build_live_gameline_index(self._snapshot())
        assert ("colorado rockies", "san francisco giants") in idx
        assert idx[("colorado rockies", "san francisco giants")]["game_pk"] == 823184

    def test_a_segment_only_game_is_not_indexed(self):
        assert build_live_gameline_index(self._snapshot(source="segment_projection")) == {}

    def test_attach_prices_a_big_live_edge_and_clears_the_pregame_reason(self):
        grid = [self._row(market_prob=0.50)]
        cov = attach_live_gamelines(grid, build_live_gameline_index(self._snapshot(prob=0.6842)))
        assert cov["rows_live_gameline_edged"] == 1
        row = grid[0]
        assert row["projection"]["live_aware"] is True
        assert row["projection"]["edge_unavailable_reason"] is None
        assert row["projection"]["edge_vs_market_pct"] == pytest.approx(18.42, abs=0.01)
        assert row["live_gameline"]["game_pk"] == 823184

    def test_attach_withholds_a_small_edge_but_still_marks_live_aware(self):
        """live_aware is about the MODEL knowing the score; priceable is about
        precision. Conflating them would either refuse everything or price noise."""
        grid = [self._row(market_prob=0.67)]
        cov = attach_live_gamelines(grid, build_live_gameline_index(self._snapshot(prob=0.6842)))
        assert cov["rows_live_gameline_edged"] == 0
        assert cov["withheld_by_reason"] == {REASON_NOT_PRICEABLE: 1}
        row = grid[0]
        assert row["projection"]["live_aware"] is True
        assert row["projection"]["edge_vs_market_pct"] is None
        assert row["projection"]["edge_unavailable_reason"] == REASON_NOT_PRICEABLE

    @pytest.mark.parametrize("kw", [{"state": "pregame"}, {"state": "final"},
                                    {"kind": "prop"}, {"market": "totals"}])
    def test_rows_outside_scope_are_untouched(self, kw):
        """A pregame, final, prop or totals row must not be considered at all --
        final in particular is live_edge_policy's call, not this module's."""
        grid = [self._row(**kw)]
        before = dict(grid[0]["projection"])
        cov = attach_live_gamelines(grid, build_live_gameline_index(self._snapshot()))
        assert cov["rows_live_gameline_considered"] == 0
        assert grid[0]["projection"] == before
        assert "live_gameline" not in grid[0]

    def test_an_unmatched_row_keeps_its_existing_suppression(self):
        """The miss must not silently grant an edge, and must be countable."""
        grid = [self._row()]
        grid[0]["home_team"] = "Some Other Team"
        cov = attach_live_gamelines(grid, build_live_gameline_index(self._snapshot()))
        assert cov["rows_live_gameline_considered"] == 1
        assert cov["rows_live_gameline_projected"] == 0
        assert cov["withheld_by_reason"] == {REASON_NO_LIVE_PROJECTION: 1}
        assert "live_aware" not in grid[0]["projection"]
        assert grid[0]["projection"]["edge_unavailable_reason"].startswith("game is live")

    def test_empty_grid_and_empty_index_are_safe(self):
        assert attach_live_gamelines([], {})["rows_live_gameline_considered"] == 0
        assert attach_live_gamelines(None, {})["rows_live_gameline_considered"] == 0
        cov = attach_live_gamelines([self._row()], {})
        assert cov["index_size"] == 0
        assert cov["withheld_by_reason"] == {REASON_NO_LIVE_PROJECTION: 1}
