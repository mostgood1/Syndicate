"""The MLB lens lane must carry the PREGAME baseline probability, not None.

WHY THIS FILE EXISTS SEPARATELY FROM `test_live_gameline_quote_age.py`.
That file already asserts a VALUE for `pregame_home_win_prob`
(`rec["pregame_home_win_prob"] == 0.5571`, :262-273) and it passed every day
that the field was null in 100% of production rows. It hand-writes
`"baselineHomeWinProb": 0.5571` into its own lens dict and never executes
`_build_game_lens`, so it pins the PROPAGATION (join -> block -> ledger) and is
structurally blind to the PRODUCER. That is `presence != reachability`: every
unit test agreed with every other unit test, and none of them built the real
lens.

WHAT WAS ACTUALLY BROKEN, measured before the fix. `_build_game_lens` read
`baseline_probs.get("homeWin")` / `.get("awayWin")`, while the only producers of
that dict -- `_merge_prediction_row` and `_normalized_full_game_probs` -- write
`home_win_prob` / `away_win_prob`. Across the whole vendor tree those two
camelCase strings occurred at exactly three sites and all three were reads:
there was no writer, so the value could never be non-None. In the exported MLB
ledger for 2026-08-20..09-07 the field was populated on **0 of 2872 v4 rows and
0 of 531 v5 rows**, while `progress_fraction` / `inning` / `outs` -- added in the
SAME commit and carried over the SAME hops -- were 2872/2872.

So these tests call the vendored builder for real, and one of them
(`test_the_camelcase_shape_yields_no_baseline`) exists solely to prove the suite
can TELL THE TWO KEY NAMES APART -- without it, the assertions below could pass
for a reason unrelated to the fix.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.live_gameline_join import live_gameline_from_lens


class TestBuildGameLensCarriesThePregameBaseline:
    # The shape `_merge_prediction_row` ACTUALLY produces. Deliberately written
    # out rather than imported, so that if the producer's field names change
    # this fixture stops matching production and the test starts lying -- which
    # is the failure this whole file is about. If you change these keys, change
    # them because you read the producer, not because a test went red.
    _PRED_FULL = {"home_win_prob": 0.5571, "away_win_prob": 0.4429, "tie_prob": 0.0}

    _MC = {"away": 3.4, "home": 4.1, "total": 7.5, "homeMargin": 0.7,
           "homeWinProb": 0.775, "awayWinProb": 0.225, "closed": False,
           "source": "live_mc", "simsRun": 120}

    def _call(self, predictions, *, mc=None):
        from vendor.mlb_bettingv2.tools.web.flask_frontend import _build_game_lens

        card = {"status": {"abstract": "Live", "detailed": "In Progress"},
                "predictions": predictions, "markets": {}}
        snapshot = {"status": {"abstractGameState": "Live", "detailedState": "In Progress"},
                    "teams": {"away": {"totals": {"R": 1}}, "home": {"totals": {"R": 2}}}}
        sim_context = {"found": True, "predicted": {"away": 4.1, "home": 4.6}}
        return {r["key"]: r for r in _build_game_lens(
            card, snapshot, sim_context, None,
            date_str="2026-08-15",
            live_mc_projection=dict(mc if mc is not None else self._MC))}

    def test_full_lane_carries_the_pregame_home_win_prob(self):
        """The headline: the real builder, the real key shape, a real value."""
        rows = self._call({"full": dict(self._PRED_FULL)})
        assert rows["full"]["baselineHomeWinProb"] == pytest.approx(0.5571)

    def test_the_camelcase_shape_yields_no_baseline(self):
        """THE MUTATION DETECTOR, and the reason this file is not redundant.

        Feed the builder the shape the OLD read expected. If this ever starts
        returning 0.5571, the reads have drifted back to camelCase (a re-vendor
        from upstream would do exactly that, silently) -- or the test above is
        passing for a reason that has nothing to do with the key name.
        """
        rows = self._call({"full": {"homeWin": 0.5571, "awayWin": 0.4429}})
        assert rows["full"]["baselineHomeWinProb"] is None

    def test_segment_lane_renormalises_a_two_way_baseline(self):
        """Only the `full` lane is normalised at build time
        (`normalize_full=True`), so a segment lane must renormalise its own pair
        rather than publish a raw probability that does not sum to 1."""
        rows = self._call({"first5": {"home_win_prob": 0.6, "away_win_prob": 0.2}})
        assert rows["first5"]["baselineHomeWinProb"] == pytest.approx(0.75)

    def test_absent_predictions_still_yield_none_rather_than_a_number(self):
        """A missing baseline must stay missing. `None` is the honest answer and
        the ledger records it as such; a default would be indistinguishable from
        a real pregame probability at every level except the data."""
        rows = self._call({})
        assert rows["full"]["baselineHomeWinProb"] is None

    def test_the_baseline_survives_the_join_into_the_ledger_field(self):
        """End to end, producer through reader: the value the builder computes is
        the value the ledger's `pregame_home_win_prob` will hold.

        This is the assertion `test_live_gameline_quote_age.py` believed it was
        making. The difference is that the lens here was BUILT, not written by
        hand.
        """
        rows = self._call({"full": dict(self._PRED_FULL)})
        got = live_gameline_from_lens(list(rows.values()))
        assert got is not None
        assert got["pregame_home_win_prob"] == pytest.approx(0.5571)
