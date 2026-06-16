from __future__ import annotations

import unittest
from pathlib import Path


class RenderYamlEnvTests(unittest.TestCase):
    def test_render_yaml_points_sport_roots_at_render_data_disk(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        content = (repo_root / "render.yaml").read_text(encoding="utf-8")

        for expected in (
            "SYNDICATE_MLB_SOURCE_ROOT",
            "SYNDICATE_NBA_SOURCE_ROOT",
            "SYNDICATE_NBA_ARTIFACT_ROOT",
            "SYNDICATE_NHL_SOURCE_ROOT",
            "SYNDICATE_NFL_SOURCE_ROOT",
            "SYNDICATE_NCAAF_SOURCE_ROOT",
            "SYNDICATE_NCAAB_SOURCE_ROOT",
            "SYNDICATE_WNBA_SOURCE_ROOT",
            "MLB_BETTING_DATA_ROOT",
            "NBA_BETTING_DATA_ROOT",
            "WNBA_BETTING_DATA_ROOT",
            "NHL_DATA_DIR",
            "NHL_LIVE_LENS_DIR",
        ):
            self.assertIn(expected, content)

        self.assertNotIn("/opt/render/project/src/data/mlb_source/source_artifacts/data", content)
        self.assertNotIn("/opt/render/project/src/data/nba_source/source_artifacts/data", content)
        self.assertNotIn("/opt/render/project/src/data/nhl_source/source_artifacts/data", content)
        self.assertNotIn("/opt/render/project/src/data/", content)


if __name__ == "__main__":
    unittest.main()
