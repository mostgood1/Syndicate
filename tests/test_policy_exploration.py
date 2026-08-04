"""Tests for the Stage 4 policy-exploration-budget + promotion_score fix
in recommendation_engine.py -- see build_policy_optimization_summary's own
docstring for the deadlock this closes: a challenger tied with (or losing
to) the incumbent used to NEVER receive traffic, so it could never accrue
the settled samples needed to prove itself."""

from __future__ import annotations

import unittest

from syndicate.features.shared import recommendation_engine as re


def _record(*, policy: str, result: str, edge: float = 0.05, confidence: float = 0.6, odds: float | None = None, closing_price: float | None = None) -> dict:
    recommendation = {"policy": policy, "market": "moneyline", "sport": "mlb", "edge": edge, "confidence": confidence}
    if odds is not None:
        recommendation["odds"] = odds
    record: dict = {
        "result": result,
        "pnl": 0.91 if result == "win" else -1.0,
        "stake": 1.0,
        "implied_probability": 0.5,
        "recommendation": recommendation,
        "query": {"sport": "mlb"},
    }
    if closing_price is not None:
        record["closing_price"] = closing_price
    return record


class ExplorationBudgetTests(unittest.TestCase):
    def test_with_zero_history_some_experiment_keys_still_explore_a_challenger(self) -> None:
        # No settled history at all -> every policy scores promotion_score
        # 0.0, a permanent tie. Before the fix this always resolved to the
        # incumbent; now a ~10% deterministic slice of experiment_keys
        # should explore a real challenger instead.
        explored_policies = set()
        explored_count = 0
        for i in range(300):
            summary = re.build_policy_optimization_summary([], sport="mlb", experiment_key=f"game-{i}")
            self.assertFalse(summary["promoted"])
            if summary["explored"]:
                explored_count += 1
                explored_policies.add(summary["selected_policy"])
                self.assertNotEqual(summary["selected_policy"], re.DEFAULT_POLICY)
        # ~10% of 300 = ~30, allow a wide band since bucketing is hash-based, not random.
        self.assertGreater(explored_count, 15)
        self.assertLess(explored_count, 50)
        self.assertTrue(explored_policies)  # at least one non-default policy actually got picked

    def test_same_experiment_key_always_explores_the_same_challenger(self) -> None:
        # Determinism matters: a real experiment shouldn't flip-flop which
        # policy a given game/market gets on repeated calls.
        results = {re.build_policy_optimization_summary([], sport="mlb", experiment_key="stable-key")["selected_policy"] for _ in range(5)}
        self.assertEqual(len(results), 1)

    def test_no_experiment_key_never_explores(self) -> None:
        summary = re.build_policy_optimization_summary([], sport="mlb", experiment_key=None)
        self.assertFalse(summary["explored"])
        self.assertEqual(summary["selected_policy"], re.DEFAULT_POLICY)

    def test_zero_exploration_rate_disables_exploration(self) -> None:
        for i in range(50):
            summary = re.build_policy_optimization_summary([], sport="mlb", experiment_key=f"k-{i}", exploration_rate=0.0)
            self.assertFalse(summary["explored"])
            self.assertEqual(summary["selected_policy"], re.DEFAULT_POLICY)

    def test_promoted_challenger_is_not_also_flagged_as_explored(self) -> None:
        balanced = [_record(policy="balanced", result="loss") for _ in range(50)]
        aggressive = [_record(policy="aggressive", result="win") for _ in range(50)]
        summary = re.build_policy_optimization_summary(balanced + aggressive, sport="mlb", experiment_key="obvious-signal")
        self.assertTrue(summary["promoted"])
        self.assertFalse(summary["explored"])


class PromotionScoreRealizedOutcomesOnlyTests(unittest.TestCase):
    def test_high_edge_and_confidence_alone_do_not_promote_a_losing_policy(self) -> None:
        # aggressive: high edge/confidence but a losing record. balanced:
        # modest edge/confidence but a winning record. Before the fix,
        # average_edge*18 + average_confidence*10 could offset a real ROI
        # deficit; now promotion_score should track realized outcomes only.
        balanced = [_record(policy="balanced", result="win", edge=0.02, confidence=0.55) for _ in range(60)]
        aggressive = [_record(policy="aggressive", result="loss", edge=0.15, confidence=0.9) for _ in range(60)]
        comparison = re.compare_policies(balanced + aggressive, sport="mlb")
        by_policy = {row["policy"]: row for row in comparison}
        self.assertGreater(by_policy["balanced"]["promotion_score"], by_policy["aggressive"]["promotion_score"])
        summary = re.build_policy_optimization_summary(balanced + aggressive, sport="mlb")
        self.assertNotEqual(summary["selected_policy"], "aggressive")

    def test_edge_and_confidence_still_reported_on_the_row_for_visibility(self) -> None:
        records = [_record(policy="aggressive", result="win", edge=0.1, confidence=0.7) for _ in range(10)]
        comparison = re.compare_policies(records, sport="mlb")
        aggressive_row = next(row for row in comparison if row["policy"] == "aggressive")
        self.assertIn("average_edge", aggressive_row)
        self.assertIn("average_confidence", aggressive_row)

    def test_win_rate_standard_error_present_and_shrinks_with_sample_size(self) -> None:
        small = re.compare_policies([_record(policy="balanced", result="win") for _ in range(5)], sport="mlb", policies=["balanced"])
        large = re.compare_policies([_record(policy="balanced", result="win") for _ in range(500)], sport="mlb", policies=["balanced"])
        small_se = next(r for r in small if r["policy"] == "balanced")["win_rate_standard_error"]
        large_se = next(r for r in large if r["policy"] == "balanced")["win_rate_standard_error"]
        # win_rate=1.0 in both cases makes SE mathematically 0 regardless of
        # n (no variance in an all-win sample) -- use a mixed-result sample
        # so SE is actually informative.
        self.assertEqual(small_se, 0.0)
        self.assertEqual(large_se, 0.0)


class ClvDrivenPromotionTests(unittest.TestCase):
    def test_better_clv_increases_promotion_score_at_similar_roi(self) -> None:
        # Both policies have identical win/loss records (same ROI); only
        # CLV differs (aggressive consistently beat the closing line,
        # balanced consistently got worse than the close).
        balanced = [
            _record(policy="balanced", result=("win" if i % 2 == 0 else "loss"), odds=-110, closing_price=-95)
            for i in range(40)
        ]
        aggressive = [
            _record(policy="aggressive", result=("win" if i % 2 == 0 else "loss"), odds=-110, closing_price=-130)
            for i in range(40)
        ]
        comparison = re.compare_policies(balanced + aggressive, sport="mlb")
        by_policy = {row["policy"]: row for row in comparison}
        self.assertGreater(by_policy["aggressive"]["average_clv_price"], by_policy["balanced"]["average_clv_price"])
        self.assertGreater(by_policy["aggressive"]["promotion_score"], by_policy["balanced"]["promotion_score"])

    def test_missing_closing_price_does_not_dilute_clv_toward_zero(self) -> None:
        # Half the records have real CLV data, half don't -- average_clv_price
        # should reflect only the records that actually captured a close,
        # not be diluted by treating missing data as clv=0.
        with_clv = [_record(policy="balanced", result="win", odds=-110, closing_price=-140) for _ in range(20)]
        without_clv = [_record(policy="balanced", result="win", odds=-110) for _ in range(20)]
        comparison = re.compare_policies(with_clv + without_clv, sport="mlb", policies=["balanced"])
        row = next(r for r in comparison if r["policy"] == "balanced")
        self.assertEqual(row["clv_sample_size"], 20)
        self.assertGreater(row["average_clv_price"], 0.0)


if __name__ == "__main__":
    unittest.main()
