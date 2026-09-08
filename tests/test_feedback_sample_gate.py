"""WP3 "restore measurement" (2026-09-08): the evaluation-ledger feedback
terms cannot switch on ungated when settlement starts writing again, and a
missing probability is refused by name instead of defaulting to 0.5.

Covers, in order:
  - feedback_sample_gate itself (n=49 gated, n=50 live, env override, garbage)
  - _gated_reliability_profile: neutral AND labelled below the floor, measured
    above it; the raw measurement stays visible under `metrics` / `measured`
  - filter_candidates: the poor-market threshold bump is inert at n=49 and
    fires at n=50
  - rank_recommendations: ROI / calibration terms and the reliability
    multiplier are exactly neutral at n=49 (score identical to no history),
    and move at n=50; the gate is visible on `historical_profile`
  - _performance_multiplier_for_candidate: a summary block with no count, or
    a count below the floor, contributes 1.0; at the floor it contributes
  - the ranker refuses a candidate with no fair AND no model probability with
    reason `no_fair_probability` through the existing rejected_sink
  - bankroll_manager.compute_bet_size / compute_board_stake refuse an absent
    model or implied probability with a named reason and a zero stake
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from syndicate.features import bankroll_manager
from syndicate.features.shared import recommendation_engine as engine


def _loss(market: str, *, sport: str = "nba") -> dict:
    return {
        "result": "loss",
        "pnl": -1.0,
        "stake": 1.0,
        "implied_probability": 0.53,
        "recommendation": {"market": market, "selection": "Over 28.5", "line": 28.5, "odds": "+100"},
        "artifact_metadata": {"sport": sport},
    }


def _history(count: int, *, market: str = "points") -> list[dict]:
    # No recommendation_id on purpose: _latest_by_recommendation_id keeps
    # id-less records under distinct fallback keys, so `count` records really
    # is a sample of `count`.
    return [_loss(market) for _ in range(count)]


_UNRELATED_HISTORY = [
    {
        "result": "win",
        "pnl": 0.0,
        "stake": 1.0,
        "implied_probability": 0.5,
        "recommendation": {"market": "unrelated_placeholder_market", "selection": "n/a", "line": None, "odds": "+100"},
        "artifact_metadata": {"sport": "mlb"},
    }
]


def _points_candidate() -> dict:
    # model 0.53 at +100 -> edge 0.03: clears a 0.0 threshold, fails the
    # +0.06 bump a -1.0 market ROI produces once the gate opens.
    return {
        "name": "Jayson Tatum Over 28.5 Points",
        "event_id": "game-1",
        "market": "points",
        "selection": "Over 28.5",
        "odds": "+100",
        "score": 86.0,
        "confidence": 0.63,
        "model_probability": 0.53,
    }


class FeedbackSampleGateTests(unittest.TestCase):
    def test_default_floor_is_fifty_and_the_boundary_is_inclusive(self) -> None:
        self.assertEqual(engine.MIN_FEEDBACK_SAMPLE, 50)
        below = engine.feedback_sample_gate(49)
        at = engine.feedback_sample_gate(50)
        self.assertEqual(below, {"feedback_gated": True, "sample_size": 49, "min_sample": 50})
        self.assertEqual(at, {"feedback_gated": False, "sample_size": 50, "min_sample": 50})

    def test_env_override_moves_the_floor(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_FEEDBACK_MIN_SAMPLE": "3"}):
            self.assertEqual(engine.feedback_min_sample(), 3)
            self.assertFalse(engine.feedback_sample_gate(3)["feedback_gated"])
            self.assertTrue(engine.feedback_sample_gate(2)["feedback_gated"])

    def test_garbage_env_and_garbage_sample_stay_gated(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_FEEDBACK_MIN_SAMPLE": "lots"}):
            self.assertEqual(engine.feedback_min_sample(), 50)
        for junk in (None, "", "n/a", True, -4):
            gate = engine.feedback_sample_gate(junk)
            self.assertTrue(gate["feedback_gated"], junk)
            self.assertEqual(gate["sample_size"], 0, junk)


class GatedReliabilityProfileTests(unittest.TestCase):
    def test_below_the_floor_is_neutral_and_says_why(self) -> None:
        profile = engine._gated_reliability_profile(records=_history(49), sport="nba")
        self.assertTrue(profile["feedback_gated"])
        self.assertEqual(profile["sample_size"], 49)
        self.assertEqual(profile["min_sample"], 50)
        self.assertEqual(profile["reliability_multiplier"], 1.0)
        self.assertEqual(profile["calibration_error"], 0.0)
        self.assertEqual(profile["calibration_penalty"], 0.0)
        self.assertEqual(profile["win_rate_adjustment"], 0.0)
        self.assertEqual(profile["roi_adjustment"], 0.0)
        self.assertIsNone(profile["roi"])
        # The measurement is not hidden -- it is labelled as not applied.
        self.assertLess(profile["metrics"]["roi"], 0.0)
        self.assertLess(profile["measured"]["reliability_multiplier"], 1.0)
        self.assertLess(profile["measured"]["roi"], 0.0)

    def test_at_the_floor_the_measurement_applies(self) -> None:
        profile = engine._gated_reliability_profile(records=_history(50), sport="nba")
        self.assertFalse(profile["feedback_gated"])
        self.assertEqual(profile["sample_size"], 50)
        self.assertLess(profile["reliability_multiplier"], 1.0)
        self.assertGreater(profile["calibration_error"], 0.0)
        self.assertLess(profile["roi"], 0.0)
        self.assertNotIn("measured", profile)

    def test_empty_history_is_neutral_because_gated_not_because_measured(self) -> None:
        profile = engine._gated_reliability_profile(records=_UNRELATED_HISTORY, sport="nba")
        self.assertTrue(profile["feedback_gated"])
        self.assertEqual(profile["sample_size"], 0)
        self.assertEqual(profile["reliability_multiplier"], 1.0)


class FilterThresholdGateTests(unittest.TestCase):
    def test_threshold_bump_is_inert_at_49_and_fires_at_50(self) -> None:
        sink_49: list[dict] = []
        kept_49 = engine.filter_candidates([_points_candidate()], sport="nba", evaluation_records=_history(49), rejected_sink=sink_49)
        self.assertEqual(len(kept_49), 1)
        self.assertEqual(sink_49, [])
        self.assertTrue(kept_49[0]["market_profile"]["feedback_gated"])

        sink_50: list[dict] = []
        kept_50 = engine.filter_candidates([_points_candidate()], sport="nba", evaluation_records=_history(50), rejected_sink=sink_50)
        self.assertEqual(kept_50, [])
        self.assertEqual([row["_shadow_rejection_reason"] for row in sink_50], ["edge_below_threshold"])

    def test_a_profile_without_the_gate_field_gets_no_bump(self) -> None:
        # Unknown must not default permissive: a profile that never set
        # feedback_gated (a mock, an older producer) is treated as gated.
        bare = {"reliability_multiplier": 1.0, "calibration_error": 0.5, "sample_size": 500, "roi": -0.5, "metrics": {"roi": -0.5}}
        with patch.object(engine, "_gated_reliability_profile", return_value=bare):
            kept = engine.filter_candidates([_points_candidate()], sport="nba", evaluation_records=_UNRELATED_HISTORY)
        self.assertEqual(len(kept), 1)


class RankerGateTests(unittest.TestCase):
    def _score(self, records: list[dict]) -> dict:
        ranked = engine.rank_recommendations([_points_candidate()], sport="nba", evaluation_records=records)
        self.assertEqual(len(ranked), 1)
        return ranked[0]

    def test_gated_history_scores_identically_to_no_history(self) -> None:
        baseline = self._score(_UNRELATED_HISTORY)
        gated = self._score(_history(49))
        self.assertEqual(gated["core_adjusted_score"], baseline["core_adjusted_score"])
        self.assertEqual(gated["confidence"], baseline["confidence"])
        self.assertTrue(gated["historical_profile"]["market"]["feedback_gated"])
        self.assertEqual(gated["historical_profile"]["market"]["sample_size"], 49)
        self.assertEqual(gated["historical_profile"]["market"]["min_sample"], 50)
        self.assertTrue(gated["historical_profile"]["sport"]["feedback_gated"])

    def test_history_at_the_floor_moves_the_score(self) -> None:
        baseline = self._score(_UNRELATED_HISTORY)
        # +0.06 threshold bump would reject at 0.03 edge; raise the floor's
        # effect out of the way by giving the candidate more edge here.
        candidate = {**_points_candidate(), "model_probability": 0.70}
        ranked = engine.rank_recommendations([candidate], sport="nba", evaluation_records=_history(50))
        self.assertEqual(len(ranked), 1)
        live = ranked[0]
        self.assertFalse(live["historical_profile"]["market"]["feedback_gated"])
        self.assertEqual(live["historical_profile"]["market"]["sample_size"], 50)
        # A -1.0 ROI market and a >0 calibration error lower the score
        # relative to the same candidate with no usable history.
        ranked_baseline = engine.rank_recommendations([candidate], sport="nba", evaluation_records=_UNRELATED_HISTORY)
        self.assertLess(live["core_adjusted_score"], ranked_baseline[0]["core_adjusted_score"])
        self.assertLess(live["confidence"], ranked_baseline[0]["confidence"])
        del baseline

    def test_ranker_reports_the_gate_on_the_printed_line(self) -> None:
        with patch("builtins.print") as mocked_print:
            engine.rank_recommendations([_points_candidate()], sport="nba", evaluation_records=_history(49))
        lines = [str(call.args[0]) for call in mocked_print.call_args_list if call.args]
        rank_lines = [line for line in lines if "RANK_RECOMMENDATIONS" in line]
        self.assertEqual(len(rank_lines), 1)
        self.assertIn('feedback_gated={', rank_lines[0])
        self.assertIn('"sport": true', rank_lines[0])
        self.assertIn('"sample_size": 49', rank_lines[0])


class PerformanceMultiplierGateTests(unittest.TestCase):
    def _summary(self, count: int | None) -> dict:
        extra = {"settled_count": count} if count is not None else {}
        return {
            "by_sport": {"nba": {"roi": 0.18, **extra}},
            "by_market": {"points": {"roi": 0.12, **extra}},
            "by_probability_bucket": [
                {"bucket": "0.60-0.70", "predicted_probability": 0.62, "actual_win_rate": 0.70, **extra}
            ],
        }

    def _multiplier(self, summary: dict) -> dict:
        return engine._performance_multiplier_for_candidate(summary, sport="nba", market="points", probability=0.62)

    def test_blocks_without_a_count_are_gated(self) -> None:
        profile = self._multiplier(self._summary(None))
        self.assertEqual(profile["performance_multiplier"], 1.0)
        self.assertEqual(profile["performance_context"]["feedback_gated"], {"sport": True, "market": True, "confidence_bucket": True})
        self.assertIsNone(profile["performance_context"]["sport_roi"])

    def test_blocks_at_49_are_gated_and_at_50_apply(self) -> None:
        gated = self._multiplier(self._summary(49))
        self.assertEqual(gated["performance_multiplier"], 1.0)
        self.assertEqual(gated["performance_context"]["sample_size"]["sport"], 49)
        self.assertEqual(gated["performance_context"]["min_sample"], 50)
        live = self._multiplier(self._summary(50))
        self.assertGreater(live["performance_multiplier"], 1.0)
        self.assertEqual(live["performance_context"]["feedback_gated"], {"sport": False, "market": False, "confidence_bucket": False})

    def test_each_block_is_gated_on_its_own_count(self) -> None:
        summary = self._summary(50)
        summary["by_market"]["points"]["settled_count"] = 4
        profile = self._multiplier(summary)
        self.assertGreater(profile["performance_multiplier"], 1.0)
        self.assertIsNotNone(profile["performance_context"]["sport_roi"])
        self.assertIsNone(profile["performance_context"]["market_roi"])
        self.assertEqual(profile["performance_context"]["feedback_gated"]["market"], True)


class NoFairProbabilityRefusalTests(unittest.TestCase):
    def test_ranker_refuses_a_candidate_with_no_probability_of_any_kind(self) -> None:
        bare = {
            "name": "Mystery Over 1.5",
            "event_id": "game-9",
            "market": "points",
            "selection": "Over 1.5",
            "odds": "+100",
            "score": 90.0,
            "confidence": 0.9,
        }
        sink: list[dict] = []
        # filter_candidates already refuses this as no_model_probability;
        # bypass it so the ranker's own line is the one under test.
        with patch.object(engine, "filter_candidates", return_value=[dict(bare)]):
            ranked = engine.rank_recommendations([bare], sport="nba", evaluation_records=_UNRELATED_HISTORY, rejected_sink=sink)
        self.assertEqual(ranked, [])
        self.assertEqual(len(sink), 1)
        self.assertEqual(sink[0]["_shadow_rejection_reason"], "no_fair_probability")
        self.assertEqual(sink[0]["name"], "Mystery Over 1.5")

    def test_ranker_accepts_a_model_probability_without_a_fair_one(self) -> None:
        candidate = {**_points_candidate(), "model_probability": 0.6}
        candidate.pop("fair_probability", None)
        with patch.object(engine, "filter_candidates", return_value=[dict(candidate)]):
            ranked = engine.rank_recommendations([candidate], sport="nba", evaluation_records=_UNRELATED_HISTORY)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["fair_probability"], 0.6)


class BankrollRefusalTests(unittest.TestCase):
    _KEYS = {"model_probability", "implied_probability", "odds", "odds_adjustment", "edge", "kelly_fraction", "confidence", "cap_fraction", "recommended_bet_size"}

    def test_absent_model_probability_is_a_named_refusal(self) -> None:
        sizing = bankroll_manager.compute_bet_size({"odds": -110, "confidence": 70})
        self.assertEqual(sizing["reason"], "no_model_probability")
        self.assertEqual(sizing["recommended_bet_size"], 0.0)
        self.assertEqual(sizing["kelly_fraction"], 0.0)
        self.assertIsNone(sizing["model_probability"])
        self.assertTrue(self._KEYS <= set(sizing))

    def test_absent_implied_probability_and_odds_is_a_named_refusal(self) -> None:
        sizing = bankroll_manager.compute_bet_size({"model_probability": 0.6, "confidence": 70})
        self.assertEqual(sizing["reason"], "no_implied_probability")
        self.assertEqual(sizing["recommended_bet_size"], 0.0)
        self.assertIsNone(sizing["implied_probability"])

    def test_odds_still_supply_the_implied_probability(self) -> None:
        sizing = bankroll_manager.compute_bet_size({"model_probability": 0.62, "odds": -110, "confidence": 70})
        self.assertNotIn("reason", sizing)
        self.assertGreater(sizing["recommended_bet_size"], 0.0)

    def test_board_stake_carries_the_refusal_with_a_zero_stake(self) -> None:
        stake = bankroll_manager.compute_board_stake({"odds": -110}, settled_sample_size=200)
        self.assertEqual(stake["reason"], "no_model_probability")
        self.assertEqual(stake["stake_fraction"], 0.0)
        self.assertEqual(stake["stake_units"], 0.0)


if __name__ == "__main__":
    unittest.main()
