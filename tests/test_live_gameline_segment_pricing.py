"""A first5 row prices against the first5 lane, and against nothing else.

THREE THINGS THIS PINS, in descending order of how much money a mistake costs.

1. **THE LEG FRAME.** Over five innings ties are common (~20% of sims) and an F5
   moneyline is quoted BOTH three-way and two-way-with-a-push.
   `market_fair_prob_over` is de-vigged from whatever legs the book quoted, so
   the MODEL probability has to describe the same leg set. A model reading
   home 0.44 / tie 0.20 / away 0.36 against a two-way book implying 0.55 shows
   **-11 pp** on home; conditioned properly, 0.44/(0.44+0.36) = 0.55, the true
   edge is **zero**. Eleven points of pure frame mismatch -- the same defect as
   the +42.43 pp full-vs-first1 pairing, on the leg axis.

2. **INDEX ISOLATION.** A `full` row may only see the full-game index and a
   `first5` row only the first5 one. One shared lookup reopens exactly the
   mismatch `REASON_SEGMENT_NOT_FULL_GAME` exists to prevent.

3. **OFF MEANS OFF.** The flag defaults off, and with it off the behaviour is
   byte-for-byte what shipped in `16b7ad1f` -- counted, refused, recorded.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.live_gameline_join import (  # noqa: E402
    REASON_SEGMENT_LEG_SET_UNKNOWN,
    REASON_SEGMENT_NOT_FULL_GAME,
    REASON_SEGMENT_PRICING_DISABLED,
    REFUSAL_KEY,
    _two_way_home_prob,
    attach_live_gamelines,
    first5_pricing_enabled,
    segment_home_win_prob,
)

# home 44 / tie 20 / away 36 out of 100 sims -- the worked example above.
MARGIN_DIST = {2: 30, 1: 14, 0: 20, -1: 20, -2: 16}


def _hit(**over):
    base = {
        "game_pk": 824966, "home_win_prob": 0.44, "sims_run": 100,
        "total_mean": 4.3, "home_margin": -0.2,
        "total_runs_dist": {4: 100}, "margin_dist": dict(MARGIN_DIST),
        "as_of": None, "carried_forward": False, "analytic_markets": {},
        "progress": {"fraction": 0.3}, "pregame_home_win_prob": 0.5,
    }
    base.update(over)
    return base


def _row(segment="first5", market="h2h", sides=("home", "away"), fair=0.55):
    return {
        "kind": "game", "market": market, "segment": segment, "line": None,
        "event_id": "e1", "home_team": "Athletics", "away_team": "Texas Rangers",
        "books": ["pinnacle"], "age_seconds": 5.0, "sides": list(sides),
        "game": {"state": "live"},
        "projection": {"market_fair_prob_over": fair},
    }


KEY = ("texas rangers", "athletics")


class TestTheLegFrame:
    def test_two_way_conditional_is_the_tie_removed_probability(self):
        assert _two_way_home_prob(MARGIN_DIST) == pytest.approx(44 / 80)

    def test_a_two_way_row_uses_the_CONDITIONAL_not_the_raw_probability(self):
        """The eleven points. Raw 0.44 against a 0.55 two-way de-vig would read
        as an 11pp away edge that does not exist."""
        prob, n, reason = segment_home_win_prob(_hit(), _row(sides=("home", "away")))
        assert reason is None
        assert prob == pytest.approx(0.55, abs=1e-9)
        assert n == 80, "the conditional is a proportion of the DECISIVE sims"
        assert prob != pytest.approx(0.44), "raw probability leaked into a two-way frame"

    def test_a_three_way_row_uses_the_RAW_probability(self):
        """With the draw quoted, the de-vig carries the tie and the raw home
        probability is the matching quantity."""
        prob, n, reason = segment_home_win_prob(_hit(), _row(sides=("home", "draw", "away")))
        assert reason is None
        assert prob == pytest.approx(0.44)
        assert n == 100, "every sim resolves to one of the three legs"

    @pytest.mark.parametrize("sides", [(), ("home",), ()])
    def test_an_unreadable_leg_set_REFUSES_rather_than_guessing(self, sides):
        """Guessing is not neutral: the raw probability manufactures an AWAY
        edge on a two-way book and the conditional manufactures a HOME edge on a
        three-way one. Both invent money, so unknown takes neither branch."""
        prob, n, reason = segment_home_win_prob(_hit(), _row(sides=sides))
        assert prob is None and n is None
        assert reason == REASON_SEGMENT_LEG_SET_UNKNOWN

    def test_an_empty_margin_histogram_refuses(self):
        prob, n, reason = segment_home_win_prob(_hit(margin_dist={}), _row())
        assert prob is None and n is None and reason == REASON_SEGMENT_LEG_SET_UNKNOWN

    def test_an_all_tie_histogram_refuses_rather_than_dividing_by_zero(self):
        prob, n, reason = segment_home_win_prob(_hit(margin_dist={0: 100}), _row())
        assert prob is None and n is None and reason == REASON_SEGMENT_LEG_SET_UNKNOWN


class TestOffMeansOff:
    def test_the_flag_defaults_to_OFF(self, monkeypatch):
        monkeypatch.delenv("SYNDICATE_MLB_FIRST5_PRICING", raising=False)
        assert first5_pricing_enabled() is False

    def test_with_the_flag_off_a_first5_row_is_still_refused_and_recorded(self, monkeypatch):
        monkeypatch.delenv("SYNDICATE_MLB_FIRST5_PRICING", raising=False)
        grid = [_row()]
        cov = attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        assert cov["rows_live_gameline_priceable"] == 0
        assert "live_gameline" not in grid[0]
        # named as the FLAG, not as the standing rule -- the lane exists
        assert grid[0][REFUSAL_KEY]["withheld_reason"] == REASON_SEGMENT_PRICING_DISABLED

    def test_with_no_segment_index_it_is_the_standing_rule(self, monkeypatch):
        monkeypatch.delenv("SYNDICATE_MLB_FIRST5_PRICING", raising=False)
        grid = [_row()]
        attach_live_gamelines(grid, {})
        assert grid[0][REFUSAL_KEY]["withheld_reason"] == REASON_SEGMENT_NOT_FULL_GAME

    def test_ON_actually_prices_it(self, monkeypatch):
        """`off != on`. Without this the whole feature could be inert and every
        test above would still pass."""
        monkeypatch.setenv("SYNDICATE_MLB_FIRST5_PRICING", "1")
        grid = [_row()]
        cov = attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        assert cov["rows_live_gameline_projected"] == 1
        assert "live_gameline" in grid[0], "the first5 row never got a projection"
        assert REFUSAL_KEY not in grid[0]

    def test_ON_with_a_matched_frame_produces_ZERO_edge_not_eleven_points(self, monkeypatch):
        """The end-to-end form of the worked example.

        The published point estimate is Agresti-Coull, not the raw ratio, and
        the smoothing uses the DECISIVE sim count: `(44+2)/(80+4) = 0.5476`
        against a market of 0.55, so the honest edge is **-0.24 pp** -- zero to
        within the estimator's own rounding.

        The number that matters is the counterfactual on the next line. Skipping
        the conditioning gives `(44+2)/(100+4) = 0.4423` against the same 0.55,
        which publishes **-10.8 pp** of edge that does not exist."""
        monkeypatch.setenv("SYNDICATE_MLB_FIRST5_PRICING", "1")
        grid = [_row(fair=0.55)]
        attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        block = grid[0]["live_gameline"]
        assert block["model_prob_raw"] == pytest.approx(0.55, abs=1e-9)
        assert block["model_prob"] == pytest.approx(46 / 84, abs=1e-9)
        assert abs(block["edge_pp"]) < 1.0, block["edge_pp"]
        naive = ((44 + 2) / (100 + 4) - 0.55) * 100
        assert naive < -10.0, "the counterfactual should be a big fake edge"

    def test_the_interval_uses_the_DECISIVE_sims_not_all_of_them(self, monkeypatch):
        """A two-way conditional is 44 of 80, not 44 of 100. Handing the pricer
        the full count would state an interval ~10% too tight and price rows
        that should be refused."""
        monkeypatch.setenv("SYNDICATE_MLB_FIRST5_PRICING", "1")
        grid = [_row(fair=0.55)]
        attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        block = grid[0]["live_gameline"]
        assert block["sims_run"] == 100, "the hit still reports every sim it ran"
        import math
        # Agresti-Coull throughout: the centre is `(k+2)/(n+4)` and the interval
        # uses that same `n+4`. What this pins is the `n` FED IN -- 80 decisive
        # sims, giving 84, not 100 giving 104.
        p_ac = 46 / 84
        assert block["prob_std_err"] == pytest.approx(
            math.sqrt(p_ac * (1 - p_ac) / 84), rel=1e-6), (
            "the interval was built on the wrong denominator")
        naive_p = 46 / 104
        naive_se = math.sqrt(naive_p * (1 - naive_p) / 104)
        assert block["prob_std_err"] > naive_se, (
            "feeding all 100 sims would have stated a TIGHTER interval than the "
            "conditional estimate earns -- the over-pricing this guards")


class TestIndexIsolation:
    def test_a_full_row_NEVER_reads_the_segment_index(self, monkeypatch):
        monkeypatch.setenv("SYNDICATE_MLB_FIRST5_PRICING", "1")
        grid = [_row(segment="full")]
        # only a SEGMENT hit exists; a full row must not find it
        cov = attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        assert "live_gameline" not in grid[0]
        assert cov["withheld_by_reason"].get("no_live_gameline_projection") == 1

    def test_a_first5_row_NEVER_reads_the_full_game_index(self, monkeypatch):
        monkeypatch.setenv("SYNDICATE_MLB_FIRST5_PRICING", "1")
        grid = [_row(segment="first5")]
        # only a FULL-GAME hit exists. Reading it would price a full-game
        # projection against a five-inning market -- the +42.43pp defect.
        cov = attach_live_gamelines(grid, {KEY: _hit(home_win_prob=0.97)},
                                    segment_index={})
        assert "live_gameline" not in grid[0]
        assert cov["rows_live_gameline_priceable"] == 0

    def test_first3_and_first1_are_NOT_priceable_even_with_the_flag_on(self, monkeypatch):
        """The readout covers five innings. first3/first1 keep the standing
        refusal rather than borrowing the first5 lane."""
        monkeypatch.setenv("SYNDICATE_MLB_FIRST5_PRICING", "1")
        grid = [_row(segment="first3"), _row(segment="first1")]
        attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        for row in grid:
            assert "live_gameline" not in row
            assert row[REFUSAL_KEY]["withheld_reason"] == REASON_SEGMENT_NOT_FULL_GAME


class TestTheFullGamePathIsUntouched:
    def test_a_full_game_h2h_row_still_uses_the_RAW_probability(self, monkeypatch):
        """MLB games do not end level, so there is no tie mass to condition on
        and the full-game frame must not change."""
        monkeypatch.setenv("SYNDICATE_MLB_FIRST5_PRICING", "1")
        grid = [_row(segment="full", fair=0.20)]
        attach_live_gamelines(grid, {KEY: _hit(home_win_prob=0.44)}, segment_index={})
        block = grid[0]["live_gameline"]
        # RAW is the sim's own number; `model_prob` is Agresti-Coull over ALL
        # 100 sims, because a full-game row has no tie mass to remove.
        assert block["model_prob_raw"] == pytest.approx(0.44)
        assert block["model_prob"] == pytest.approx(46 / 104, abs=1e-9)

    def test_the_default_call_signature_still_works(self):
        """`segment_index` is keyword-only with a default, so every existing
        caller is unaffected."""
        grid = [_row(segment="full", fair=0.20)]
        cov = attach_live_gamelines(grid, {KEY: _hit()})
        assert cov["rows_live_gameline_projected"] == 1
