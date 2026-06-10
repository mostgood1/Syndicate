from __future__ import annotations

import unittest

from syndicate.features.intelligence_analysis_views import build_analysis_views


class IntelligenceAnalysisViewSortingTests(unittest.TestCase):
    def test_analysis_views_expose_ev_and_confidence_sort_options(self) -> None:
        candidates = [
            {
                "sport_slug": "nba",
                "candidate_type": "matchup",
                "name": "Lakers vs Celtics",
                "matchup": "Lakers @ Celtics",
                "market": "points",
                "pick": "Over 228.5",
                "line": 228.5,
                "projected": 232.1,
                "live_projection": None,
                "odds": -110,
                "expected_value": 0.072,
                "edge_pct": 7.2,
                "confidence": 0.68,
                "model_probability": 0.61,
                "market_probability": 0.54,
                "historical_context": {"roi_segment": 0.118, "sample_size": 42},
                "reasoning": ["Positive expected value", "Model probability clears market", "Strong historical ROI"],
                "score": 9.4,
                "market_fit_score": 6.7,
                "analysis_shape": "nba_usage_creation",
                "why": "Model edge and historical context support the play.",
            }
        ]

        view = build_analysis_views(
            candidates,
            {"analysis_focus": "market_board", "requested_sports": ["nba"], "limit": 5},
            build_mlb_home_run_analysis_views=lambda *_args, **_kwargs: None,
            mlb_statcast_market_text=lambda *_args, **_kwargs: "",
            safe_text=lambda value, default="": default if value is None else str(value),
            candidate_market_focuses=lambda candidate: {str(candidate.get("market") or "").lower()},
            advanced_signal_text=lambda *_args, **_kwargs: "",
        )

        self.assertIsNotNone(view)
        table = (view or {}).get("table") or {}
        sort_options = table.get("sort_options") or []
        sort_keys = {str(item.get("key") or "") for item in sort_options if isinstance(item, dict)}
        self.assertTrue({"expected_value", "confidence"}.issubset(sort_keys))
        self.assertEqual((table.get("default_sort") or {}).get("key"), "score")
        self.assertEqual((table.get("rows") or [])[0].get("historical_context"), {"roi_segment": 0.118, "sample_size": 42})
        self.assertEqual((table.get("rows") or [])[0].get("expected_value"), 0.072)
        self.assertEqual(str((table.get("rows") or [])[0].get("confidence")), "0.68")


if __name__ == "__main__":
    unittest.main()
