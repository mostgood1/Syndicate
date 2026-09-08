"""The `first5` lens lane stops being an interpolation when the MC can answer.

WHAT IT REPLACES, measured on production 2026-09-07 via
`/api/ops/live-lens/snapshot-index`: gamePk 823902 published `first5 0.3242`
from `_live_margin_win_prob` over `_segment_projection` -- a LINEAR SCALING OF
PREGAME MEANS (`mean * innings/9`, less expected-to-date, plus actual runs) that
reads no bases, no outs, no inning and no pitcher.

That number is not merely weak, it is UNPRICEABLE: the lane carries no
`simsRun`, so `sqrt(p(1-p)/n)` has no `n` and the publish-refuse-to-price gate
has no interval to clear. The fix is a readout of the same Bernoulli trials the
full-game number comes from, which brings its own trial count.

TWO INVARIANTS THIS FILE EXISTS TO PROTECT, both of which are ways the change
could be silently wrong rather than loudly broken:

1. **No full-game quantity may reach a segment lane.** The comment guarding the
   original `{"live","full"}` restriction is correct -- those histograms
   describe the full remaining game, and putting them on a first5 lane prices a
   full-game distribution against a segment market (+42.43 pp of pure artifact,
   measured). The new branch reads SEPARATE first5-scoped fields.

2. **A first5 lane must not answer "did the full-game re-sim run".**
   `_lens_rows_have_live_state_signal` tests `source == "live_mc"` and a merge
   decision hangs off it, so the segment lane is stamped `live_mc_first5`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vendor.mlb_bettingv2.tools.web.flask_frontend import (  # noqa: E402
    _build_game_lens,
    _lane_has_live_mc_first5,
)
from syndicate.features.mlb.live_lens import (  # noqa: E402
    _lens_rows_have_live_state_signal,
)

SNAPSHOT = {
    "status": {"abstractGameState": "Live", "detailedState": "In Progress"},
    "teams": {"away": {"totals": {"R": 1}}, "home": {"totals": {"R": 2}}},
    "linescore": {"currentInning": 3, "isTopInning": False},
}
CARD = {"status": {"abstract": "Live", "detailed": "In Progress"}, "markets": {}}
SIM = {"found": True, "predicted": {"away": 4.2, "home": 4.6}}


def _mc(**over):
    """A `_live_mc_projection` payload with the first-five block populated."""
    base = {
        "away": 4.1, "home": 4.9, "total": 9.0, "homeMargin": 0.8,
        "homeWinProb": 0.61, "awayWinProb": 0.39, "closed": False,
        "source": "live_mc", "simsRun": 120,
        "totalRunsDist": {9: 120}, "marginDist": {1: 120},
        "first5Available": True,
        "first5HomeWinProb": 0.44, "first5AwayWinProb": 0.36,
        "first5TieProb": 0.20, "first5Total": 4.3, "first5HomeMargin": -0.2,
        "first5TotalRunsDist": {4: 120}, "first5MarginDist": {0: 120},
    }
    base.update(over)
    return base


def _lane(rows, key):
    for r in rows:
        if r.get("key") == key:
            return r
    raise AssertionError(f"no {key} lane in {[r.get('key') for r in rows]}")


class TestThePredicate:
    def test_both_clauses_are_required(self):
        assert _lane_has_live_mc_first5(_mc()) is True
        assert _lane_has_live_mc_first5(_mc(first5Available=False)) is False
        assert _lane_has_live_mc_first5(_mc(first5HomeWinProb=None)) is False, (
            "an available window with no probability must not take the "
            "permissive branch")
        assert _lane_has_live_mc_first5(None) is False
        assert _lane_has_live_mc_first5({}) is False


class TestTheFirst5LaneCarriesTheMC:
    def test_it_publishes_the_MC_probability_not_the_interpolation(self):
        rows = _build_game_lens(CARD, SNAPSHOT, SIM, None, live_mc_projection=_mc())
        lane = _lane(rows, "first5")
        assert lane["modelHomeWinProb"] == pytest.approx(0.44)

    def test_it_carries_simsRun_so_the_precision_gate_HAS_an_n(self):
        """The whole reason the interpolation could not price."""
        rows = _build_game_lens(CARD, SNAPSHOT, SIM, None, live_mc_projection=_mc())
        assert _lane(rows, "first5")["simsRun"] == 120

    def test_its_source_is_its_OWN_label(self):
        rows = _build_game_lens(CARD, SNAPSHOT, SIM, None, live_mc_projection=_mc())
        assert _lane(rows, "first5")["source"] == "live_mc_first5"

    def test_the_distributions_are_the_FIRST5_ones_not_the_full_game_ones(self):
        """Invariant 1. If this ever reads `{9: 120}`/`{1: 120}` the full-game
        histogram has reached a segment lane and the +42.43pp defect is back."""
        rows = _build_game_lens(CARD, SNAPSHOT, SIM, None, live_mc_projection=_mc())
        proj = _lane(rows, "first5")["projection"]
        assert proj["totalRunsDist"] == {4: 120}
        assert proj["marginDist"] == {0: 120}
        assert proj["total"] == pytest.approx(4.3)


class TestItDoesNotContaminateTheFullGameQuestion:
    def test_a_first5_lane_does_NOT_satisfy_the_live_mc_signal_test(self):
        """Invariant 2. `_lens_rows_have_live_state_signal` decides whether a
        rebuild may replace a lens; if a first5 lane made it read True, a lens
        the FULL-GAME re-sim never touched would win that merge."""
        first5_only = [{"key": "first5", "source": "live_mc_first5",
                        "modelHomeWinProb": 0.44}]
        assert _lens_rows_have_live_state_signal(first5_only) is False
        with_full = first5_only + [{"key": "full", "source": "live_mc"}]
        assert _lens_rows_have_live_state_signal(with_full) is True

    def test_the_live_and_full_lanes_are_UNCHANGED(self):
        rows = _build_game_lens(CARD, SNAPSHOT, SIM, None, live_mc_projection=_mc())
        for key in ("live", "full"):
            lane = _lane(rows, key)
            assert lane["source"] == "live_mc"
            assert lane["simsRun"] == 120
            assert lane["modelHomeWinProb"] == pytest.approx(0.61)
            assert lane["projection"]["totalRunsDist"] == {9: 120}


class TestItFallsBackExactlyWhereItShould:
    def test_without_the_first5_block_the_lane_is_the_OLD_interpolation(self):
        """`off != on`: strip the new fields and the lane must look exactly as
        it did in production -- `segment_projection`, no `simsRun`."""
        rows = _build_game_lens(CARD, SNAPSHOT, SIM, None,
                                live_mc_projection=_mc(first5Available=False))
        lane = _lane(rows, "first5")
        assert lane["source"] == "segment_projection"
        assert lane["simsRun"] is None

    def test_first3_and_first1_stay_interpolated(self):
        """The readout exists for five innings only. Deriving the other two from
        it would reintroduce exactly the segment mismatch this avoids."""
        rows = _build_game_lens(CARD, SNAPSHOT, SIM, None, live_mc_projection=_mc())
        for key in ("first1", "first3"):
            lane = _lane(rows, key)
            assert lane["source"] == "segment_projection"
            assert lane["simsRun"] is None
