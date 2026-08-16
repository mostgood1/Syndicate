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
    def test_agresti_coull_near_the_spec_table_at_120_sims(self):
        """Add-two smoothing, so these sit just inside the Wald figures the spec
        quotes (0.04564 / 0.03953 / 0.02739). The decision's ~4.5 pp headline
        survives; the boundary behaviour is what changed."""
        assert prob_std_err(0.5, 120) == pytest.approx(0.0449, abs=1e-4)
        assert prob_std_err(0.75, 120) == pytest.approx(0.0392, abs=1e-4)
        assert prob_std_err(0.90, 120) == pytest.approx(0.02842, abs=1e-4)

    @pytest.mark.parametrize("p", [0.0, 1.0])
    def test_the_boundary_is_never_zero_width(self, p):
        """THE DEFECT THIS FIX EXISTS FOR. Wald gives 0.0 at p in {0,1}, so the
        2-sigma bar became 0 and EVERY edge cleared it. 0/120 and 120/120 are
        ordinary Monte Carlo outcomes, so this fired on a live slate."""
        se = prob_std_err(p, 120)
        assert se is not None and se > 0.0
        assert se == pytest.approx(0.01131, abs=1e-4)

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

    def _row(self, state="live", market="h2h", kind="game", market_prob=0.50, segment="full"):
        return {"kind": kind, "market": market, "segment": segment,
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
                                    {"kind": "prop"}, {"market": "player_points"}])
    def test_rows_outside_scope_are_untouched(self, kw):
        """A pregame, final, prop or non-game-line row must not be considered at
        all -- final in particular is live_edge_policy's call, not this module's.

        `{"market": "totals"}` USED TO BE IN THIS LIST and was removed on
        2026-08-16, deliberately: totals are now priced off the re-sim's own
        `totalRunsDist`, so a live totals row IS in scope. It was excluded
        before because the lens carried only `avg_total_runs` and a mean cannot
        price a line -- see `REASON_TOTALS_MEAN`, now a legacy path for old
        snapshots. Replaced with a genuinely out-of-scope market rather than
        dropped, so the "not every market is ours" guarantee still has a case.
        """
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


class TestSimsRunReachesTheGate:
    """`simsRun` and `source` must be stamped by the SAME predicate.

    The Drop 3 deploy measured `sim_count_unusable: 12` -- every projected row
    refused a step BEFORE the precision gate, because `_build_game_lens` never
    copied `simsRun` onto the lens row. The key was ABSENT, not null. These pin
    the contract from the join's side: a lens claiming `live_mc` must carry a
    usable sim count, and a segment lens must never be indexed regardless.
    """

    def _lens(self, source, sims):
        row = {"key": "live", "source": source, "modelHomeWinProb": 0.775,
               "projection": {"total": 8.5, "homeMargin": 0.7}}
        if sims is not None:
            row["simsRun"] = sims
        return [row]

    def test_a_live_mc_lens_without_simsRun_is_refused_by_name(self):
        """The production defect, reproduced: not priceable, and it SAYS why."""
        got = live_gameline_from_lens(self._lens("live_mc", None))
        assert got is not None and got["sims_run"] is None
        v = price_moneyline(model_prob=got["home_win_prob"], market_prob=0.50, sims=got["sims_run"])
        assert v["priceable"] is False
        assert v["withheld_reason"] == REASON_UNUSABLE_SIMS

    def test_the_same_lens_WITH_simsRun_reaches_the_precision_gate(self):
        """The fix's payload: the refusal stops being a plumbing gap and becomes
        the actual product decision, which is the whole reason to fix it."""
        got = live_gameline_from_lens(self._lens("live_mc", 120))
        assert got["sims_run"] == 120
        v = price_moneyline(model_prob=got["home_win_prob"], market_prob=0.50, sims=got["sims_run"])
        assert v["withheld_reason"] != REASON_UNUSABLE_SIMS
        assert v["prob_std_err"] == pytest.approx(prob_std_err(0.775, 120))
        # 0.775 vs 0.50 is 27.5 pp against a ~8.4 pp bar, so it prices.
        assert v["priceable"] is True

    def test_a_segment_lens_is_never_indexed_even_carrying_simsRun(self):
        """If a later change stamps simsRun on segment lanes too, `source` must
        still be the thing that keeps them out of the index."""
        assert live_gameline_from_lens(self._lens("segment_projection", 120)) is None


class TestBuildGameLensStampsSimsRun:
    """Pins the PRODUCER side of the contract, in the vendored builder itself.

    The tests above pin what the join does GIVEN a lens. They would all still
    pass with the vendor fix reverted, because they construct their own lens
    rows -- which is exactly how the original defect survived: every unit test
    agreed with every other unit test, and none of them built the real lens.
    This one calls `_build_game_lens` for real.
    """

    def _call(self, mc):
        from vendor.mlb_bettingv2.tools.web.flask_frontend import _build_game_lens

        card = {"status": {"abstract": "Live", "detailed": "In Progress"},
                "predictions": {}, "markets": {}}
        snapshot = {"status": {"abstractGameState": "Live", "detailedState": "In Progress"},
                    "teams": {"away": {"totals": {"R": 1}}, "home": {"totals": {"R": 2}}}}
        sim_context = {"found": True, "predicted": {"away": 4.1, "home": 4.6}}
        return _build_game_lens(card, snapshot, sim_context, None,
                                date_str="2026-08-15", live_mc_projection=mc)

    _MC = {"away": 3.4, "home": 4.1, "total": 7.5, "homeMargin": 0.7,
           "homeWinProb": 0.775, "awayWinProb": 0.225, "closed": False,
           "source": "live_mc", "simsRun": 120}

    def test_live_mc_lanes_carry_both_source_and_simsRun(self):
        rows = {r["key"]: r for r in self._call(dict(self._MC))}
        for lane in ("live", "full"):
            assert rows[lane]["source"] == "live_mc"
            assert rows[lane]["simsRun"] == 120, f"{lane} lost its sim count"

    def test_segment_lanes_get_no_sim_count(self):
        """A default here would make an interpolation look exactly as precise as
        a real re-sim, which is the one substitution that would defeat the gate."""
        rows = {r["key"]: r for r in self._call(dict(self._MC))}
        for lane in ("first1", "first3", "first5", "first7"):
            assert rows[lane]["source"] == "segment_projection"
            assert rows[lane]["simsRun"] is None

    def test_the_two_fields_never_disagree(self):
        """The invariant the hoisted predicate exists to guarantee: a lane is
        live_mc if and only if it carries a sim count."""
        for mc in (dict(self._MC), None):
            for row in self._call(mc):
                assert (row["source"] == "live_mc") == (row["simsRun"] is not None)

    def test_end_to_end_a_real_lens_now_reaches_the_precision_gate(self):
        """The whole point, in one assertion: build a REAL lens, run it through
        the join's reader and pricer, and confirm it is no longer refused for a
        missing sim count."""
        rows = self._call(dict(self._MC))
        got = live_gameline_from_lens(rows)
        assert got is not None and got["sims_run"] == 120
        v = price_moneyline(model_prob=got["home_win_prob"], market_prob=0.50, sims=got["sims_run"])
        assert v["withheld_reason"] != REASON_UNUSABLE_SIMS


class TestSegmentFilter:
    """A full-game projection may only be priced against a full-game market.

    Measured 2026-08-16, SD @ CLE: the same h2h market appears once per segment,
    and the live re-sim's home win probability (0.9667, full game) was priced
    against every one of them -- including `first1` at mkt 0.5424, producing a
    **+42.43 pp** edge that is purely the mismatched segment. The full-game row
    for the same game and tick was +9.17 pp.
    """

    def _snapshot(self):
        return {"games": [{
            "gamePk": 824400, "status": {"abstract": "Live"},
            "matchup": {"away": {"name": "San Diego Padres"},
                        "home": {"name": "Cleveland Guardians"}},
            "gameLens": [{"key": "live", "source": "live_mc", "modelHomeWinProb": 0.9667,
                          "simsRun": 120, "projection": {"total": 7.5, "homeMargin": 0.7}}]}]}

    def _row(self, segment, market_prob):
        return {"kind": "game", "market": "h2h", "segment": segment,
                "away_team": "San Diego Padres", "home_team": "Cleveland Guardians",
                "game": {"state": "live"},
                "projection": {"market_fair_prob_over": market_prob}}

    def test_the_first_inning_row_is_refused_by_name(self):
        grid = [self._row("first1", 0.5424)]
        cov = attach_live_gamelines(grid, build_live_gameline_index(self._snapshot()))
        assert cov["rows_live_gameline_edged"] == 0
        assert cov["withheld_by_reason"] == {"segment_is_not_full_game": 1}
        assert "live_gameline" not in grid[0]

    def test_the_full_game_row_still_prices(self):
        grid = [self._row("full", 0.8750)]
        cov = attach_live_gamelines(grid, build_live_gameline_index(self._snapshot()))
        assert cov["rows_live_gameline_edged"] == 1
        assert grid[0]["live_gameline"]["edge_pp"] == pytest.approx(9.17, abs=0.01)

    @pytest.mark.parametrize("segment", ["first1", "first3", "first5", "", None, "unknown"])
    def test_every_non_full_segment_including_ABSENT_is_refused(self, segment):
        """An absent segment refuses too: unknown must not default permissive."""
        grid = [self._row(segment, 0.8750)]
        cov = attach_live_gamelines(grid, build_live_gameline_index(self._snapshot()))
        assert cov["rows_live_gameline_edged"] == 0
        assert cov["withheld_by_reason"] == {"segment_is_not_full_game": 1}

    def test_the_production_case_end_to_end(self):
        """All four SD @ CLE rows: exactly one prices, and it is the full game."""
        grid = [self._row("full", 0.8750), self._row("first5", 0.8856),
                self._row("first3", 0.8993), self._row("first1", 0.5424)]
        cov = attach_live_gamelines(grid, build_live_gameline_index(self._snapshot()))
        assert cov["rows_live_gameline_considered"] == 4
        assert cov["rows_live_gameline_edged"] == 1
        assert cov["withheld_by_reason"] == {"segment_is_not_full_game": 3}
        assert grid[3].get("live_gameline") is None   # the +42pp row is gone


class TestLiveDistributionPricing:
    """Live TOTALS and SPREADS priced off the re-sim's own histograms.

    THE DEFECT, measured on the served board 2026-08-16 19:13Z across 8 live
    MLB games: `h2h|full` had 7 of 8 joined and 2 priceable, while
    `totals|full` (41 rows), `spreads|full` (36), `totals_alt|first5` (98) and
    `spreads_alt|first5` (79) were **0 live_aware and 0 edge** -- 470+ rows
    rendering a PREGAME projection against a live market.

    It was a discard, not a gap. `LiveMcResult.total_runs_dist` has always
    existed; `flask_frontend`'s live-MC return kept `batterStatDist` and
    `pitcherStatDist` for the props and dropped the game histograms on the
    floor, so `live_gameline_join` had a mean and nothing else.
    """

    # 100 sims: totals 5..10, margin -3..+3. Deliberately hand-countable so a
    # failure names the arithmetic rather than the fixture.
    TOTAL_DIST = {5: 10, 6: 20, 7: 30, 8: 20, 9: 15, 10: 5}
    MARGIN_DIST = {-3: 10, -2: 15, -1: 20, 0: 10, 1: 20, 2: 15, 3: 10}

    def _price(self, **kw):
        from syndicate.features.shared.live_gameline_join import price_distribution_market
        base = dict(dist=self.TOTAL_DIST, line=7.5, side="over", market="totals",
                    market_prob=0.40, sims=100)
        base.update(kw)
        return price_distribution_market(**base)

    def test_over_probability_comes_off_the_histogram(self):
        """P(total > 7.5) = (15+5)/100 = 0.40 exactly, not a normal fit."""
        out = self._price(line=7.5, side="over", market_prob=0.20)
        assert out["model_prob"] == 0.40

    def test_under_is_the_complement_side_not_one_minus_over(self):
        """P(total < 7.5) = (10+20+30)/100 = 0.60. Push mass is excluded from
        BOTH sides, so at a whole-number line these do not sum to 1."""
        assert self._price(line=7.5, side="under", market_prob=0.20)["model_prob"] == 0.60
        out = self._price(line=7.0, side="over", market_prob=0.20)
        under = self._price(line=7.0, side="under", market_prob=0.20)
        assert out["model_prob"] + under["model_prob"] < 1.0, "the push on 7 must not be split"

    def test_the_spread_home_branch_does_not_negate(self):
        """The sign convention that cost 19-28 point phantom edges in 2026-08.

        With `L` the away-frame line, home covers when `margin > L`. Negating
        computes P(margin > -L) -- the home +L probability reported against the
        home -L market. At L=1.5 on this histogram:
            correct  P(margin >  1.5) = (15+10)/100         = 0.25
            negated  P(margin > -1.5) = (20+10+20+15+10)/100 = 0.75
        Three times the true value, in the bettor's favour -- the direction
        that gets money on the table.
        """
        out = self._price(dist=self.MARGIN_DIST, line=1.5, side="home",
                          market="spreads", market_prob=0.50)
        assert out["model_prob"] == 0.25, "home branch negated the line"

    def test_the_spread_away_branch_reads_the_frame_it_is_given(self):
        """away wants P(margin < L). At L=1.5: (10+15+20+10+20)/100 = 0.75."""
        out = self._price(dist=self.MARGIN_DIST, line=1.5, side="away",
                          market="spreads", market_prob=0.50)
        assert out["model_prob"] == 0.75

    def test_alt_lines_are_priced_by_the_same_distribution(self):
        """The whole point of a histogram over a mean: any line is answerable.

        Leaving the alt families out would repeat `prop_projections:615` --
        53 of 107 live game-line rows unprojected, every one `spreads_alt` or
        `totals_alt`, because neither key was in the set.
        """
        for market in ("totals_alt", "alternate_totals"):
            assert self._price(market=market, line=9.5, market_prob=0.10)["model_prob"] == 0.05
        for market in ("spreads_alt", "alternate_spreads"):
            out = self._price(dist=self.MARGIN_DIST, line=2.5, side="home",
                              market=market, market_prob=0.50)
            assert out["model_prob"] == 0.10

    def test_the_precision_gate_is_the_same_bar_as_the_moneyline(self):
        """A histogram answers WHICH probability, not how precise it is.

        std_err at p=0.40, n=100 is 0.049, so 2 sigma is ~9.8 points. A 5-point
        edge must be withheld and a 20-point one released -- otherwise a shape
        would launder noise that the moneyline gate refuses.
        """
        from syndicate.features.shared.live_gameline_join import REASON_NOT_PRICEABLE
        tight = self._price(line=7.5, side="over", market_prob=0.45)
        assert tight["priceable"] is False
        assert tight["withheld_reason"] == REASON_NOT_PRICEABLE
        wide = self._price(line=7.5, side="over", market_prob=0.15)
        assert wide["priceable"] is True
        assert wide["edge_pp"] == 25.0

    def test_an_absent_distribution_refuses_by_name(self):
        """An old snapshot degrades to a NAMED refusal, never to a guess."""
        from syndicate.features.shared.live_gameline_join import REASON_NO_LIVE_DISTRIBUTION
        out = self._price(dist={})
        assert out["priceable"] is False
        assert out["withheld_reason"] == REASON_NO_LIVE_DISTRIBUTION
        assert out["model_prob"] is None

    def test_a_missing_line_and_an_unknown_side_each_refuse_by_name(self):
        from syndicate.features.shared.live_gameline_join import (
            REASON_NO_LINE, REASON_UNKNOWN_SIDE,
        )
        assert self._price(line=None)["withheld_reason"] == REASON_NO_LINE
        assert self._price(side="draw")["withheld_reason"] == REASON_UNKNOWN_SIDE

    def test_no_market_price_refuses_rather_than_assuming_one(self):
        from syndicate.features.shared.live_gameline_join import REASON_NO_MARKET_PRICE
        assert self._price(market_prob=None)["withheld_reason"] == REASON_NO_MARKET_PRICE
        assert self._price(market_prob=0.0)["withheld_reason"] == REASON_NO_MARKET_PRICE
        assert self._price(market_prob=1.0)["withheld_reason"] == REASON_NO_MARKET_PRICE

    def test_the_verdict_is_always_a_dict_carrying_its_own_refusal(self):
        """Never a bare None -- an absent verdict is how "withheld" silently
        becomes "not considered"."""
        for kw in ({"dist": {}}, {"line": None}, {"side": "x"},
                   {"market": "h2h_3_way"}, {"market_prob": None}):
            out = self._price(**kw)
            assert isinstance(out, dict)
            assert out["priceable"] is False
            assert out["withheld_reason"]
            assert out["sigma"] == 2.0
