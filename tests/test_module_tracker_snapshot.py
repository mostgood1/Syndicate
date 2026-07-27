from __future__ import annotations

import unittest

from scripts.module_tracker_snapshot import module_snapshot
from scripts.module_tracker_snapshot import render_text_report


class ModuleTrackerSnapshotTests(unittest.TestCase):
    def test_snapshot_exposes_runtime_contract_and_ownership_scores(self) -> None:
        snapshot = module_snapshot()
        modules = {str(module["slug"]): module for module in snapshot["modules"]}

        self.assertIn("runtime_contract", modules["mlb"])
        self.assertEqual(modules["mlb"]["runtime_contract"]["dependency_tier"], "owned_local")
        self.assertEqual(modules["mlb"]["runtime_contract"]["ownership_score"], 100)

        self.assertEqual(modules["nba"]["runtime_contract"]["dependency_tier"], "artifact_backed")
        self.assertEqual(modules["ncaab"]["runtime_contract"]["dependency_tier"], "artifact_backed")
        self.assertEqual(modules["ncaab"]["runtime_contract"]["fallback_surfaces"], [])
        self.assertEqual(modules["nba"]["runtime_contract"]["ownership_score"], 90)
        self.assertEqual(modules["ncaab"]["runtime_contract"]["ownership_score"], 90)
        self.assertEqual(modules["nfl"]["runtime_contract"]["ownership_score"], 90)
        self.assertEqual(modules["ncaaf"]["runtime_contract"]["ownership_score"], 90)
        self.assertGreaterEqual(modules["ncaab"]["runtime_contract"]["ownership_score"], modules["nba"]["runtime_contract"]["ownership_score"])

    def test_gap_summary_ranks_low_ownership_modules(self) -> None:
        snapshot = module_snapshot()
        lowest = snapshot["gap_summary"]["lowest_ownership_modules"]

        self.assertGreaterEqual(len(lowest), 1)
        self.assertGreaterEqual(lowest[0]["ownership_score"], 90)
        self.assertEqual(lowest[0]["dependency_tier"], "artifact_backed")
        self.assertEqual({item["slug"] for item in lowest[:3]}, {"nba", "ncaab", "ncaaf"})

    def test_text_report_includes_ownership_section(self) -> None:
        snapshot = module_snapshot()
        report = render_text_report(snapshot)

        self.assertIn("Lowest ownership / source-independence modules:", report)
        self.assertIn("nba", report)
        self.assertIn("ncaab", report)
        self.assertIn("ncaaf", report)

    def test_text_report_ranks_real_gaps_and_suppresses_empty_rankings(self) -> None:
        # Soccer ships without a season betting-card surface (no settlement
        # pipeline yet), so the live snapshot now carries one real parity gap;
        # pin the "- None" suppression against an emptied gap summary instead.
        snapshot = module_snapshot()
        report = render_text_report(snapshot)

        self.assertIn("Highest leverage MLB parity gaps:\n- season betting-card: 1 modules (soccer)", report)
        self.assertIn("Modules ranked by remaining gap count:\n- soccer: gaps=1;", report)

        emptied = dict(snapshot)
        emptied["gap_summary"] = {
            "highest_leverage_gaps": [],
            "modules_ranked_by_gap_count": [],
            "lowest_ownership_modules": snapshot["gap_summary"].get("lowest_ownership_modules") or [],
        }
        emptied_report = render_text_report(emptied)
        self.assertIn("Highest leverage MLB parity gaps:\n- None", emptied_report)
        self.assertIn("Modules ranked by remaining gap count:\n- None", emptied_report)


if __name__ == "__main__":
    unittest.main()