from __future__ import annotations

import unittest
from pathlib import Path

from syndicate.features.shared.odds_control_plane import build_odds_control_plane_snapshot
from syndicate.features.shared.publish_parity import build_publish_parity_summary


class PublishParitySummaryTests(unittest.TestCase):
    def test_publish_parity_summary_groups_paths_by_sport(self) -> None:
        summary = build_publish_parity_summary(
            date="2026-06-14",
            forced_paths=[
                "C:/Users/tempadmin/OneDrive/Coding/Syndicate/data/mlb_source/data/daily/daily_summary_2026_06_14.json",
                "C:/Users/tempadmin/OneDrive/Coding/Syndicate/data/nba_source/data/processed/game_cards_2026-06-14.csv",
                "C:/Users/tempadmin/OneDrive/Coding/Syndicate/data/nba_source/data/processed/props_edges_2026-06-14.csv",
                "C:/Users/tempadmin/OneDrive/Coding/Syndicate/data/wnba_source/data/processed/recommendations_2026-06-14.csv",
            ],
            intelligence_paths=[
                "C:/Users/tempadmin/OneDrive/Coding/Syndicate/reports/intelligence/example.json",
            ],
        )

        self.assertEqual(summary["date"], "2026-06-14")
        self.assertEqual(summary["totalForcedPublishPaths"], 4)
        self.assertEqual(summary["totalIntelligencePublishPaths"], 1)
        sports = {item["sport"]: item for item in summary["sports"]}
        self.assertEqual(sports["mlb"]["forcedPublishPathCount"], 1)
        self.assertEqual(sports["nba"]["forcedPublishPathCount"], 2)
        self.assertEqual(sports["wnba"]["forcedPublishPathCount"], 1)
        self.assertEqual(sports["nhl"]["forcedPublishPathCount"], 0)
        self.assertEqual(sports["mlb"]["totalPublishPathCount"], 1)
        self.assertEqual(sports["nba"]["totalPublishPathCount"], 2)
        self.assertEqual(sports["wnba"]["totalPublishPathCount"], 1)
        self.assertEqual(sports["mlb"]["intelligencePublishPathCount"], 0)

    def test_odds_control_plane_snapshot_carries_publish_parity(self) -> None:
        summary = {
            "date": "2026-06-14",
            "phase": "all",
            "execution_mode": "source",
            "dry_run": False,
            "ok": True,
            "publish_parity": {
                "generatedAt": "2026-06-14T00:00:00Z",
                "date": "2026-06-14",
                "totalForcedPublishPaths": 2,
                "totalIntelligencePublishPaths": 0,
                "totalPublishPaths": 2,
                "sports": [],
            },
            "results": [
                {
                    "sport": "mlb",
                    "ok": True,
                    "generation_mode": "full",
                    "ingestion_mode": "mirror",
                    "source_repo": "mlb_source",
                    "source_root_env_var": "SYNDICATE_SOURCE_ROOT_MLB",
                    "artifact_paths": ["data/mlb_source/data/daily/daily_summary_2026_06_14.json"],
                    "sport_manifest": {
                        "payload": {
                            "metadata": {
                                "post_refresh_ok": True,
                                "mirror_ok": True,
                            }
                        }
                    },
                }
            ],
        }

        snapshot = build_odds_control_plane_snapshot(summary)

        self.assertEqual(snapshot["date"], "2026-06-14")
        self.assertEqual((snapshot.get("publish_parity") or {}).get("totalForcedPublishPaths"), 2)
        self.assertEqual(
            snapshot["sports"][0]["odds_history"]["source_precedence"],
            ["shared_history", "artifact_history", "tracking_history"],
        )


if __name__ == "__main__":
    unittest.main()
