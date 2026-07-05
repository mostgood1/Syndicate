from __future__ import annotations

import unittest
from pathlib import Path


class RenderYamlEnvTests(unittest.TestCase):
    def test_render_yaml_keeps_web_stateless_and_worker_disk_backed(self) -> None:
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
            "SYNDICATE_BOOTSTRAP_ON_START",
            "SYNDICATE_BOOTSTRAP_WNBA_TODAY",
            "MLB_BETTING_DATA_ROOT",
            "NBA_BETTING_DATA_ROOT",
            "WNBA_BETTING_DATA_ROOT",
            "NHL_DATA_DIR",
            "NHL_LIVE_LENS_DIR",
        ):
            self.assertIn(expected, content)

        lines = content.splitlines()
        worker_index = lines.index("  - type: worker")
        web_section = "\n".join(lines[:worker_index])
        worker_section = "\n".join(lines[worker_index:])

        self.assertIn("SYNDICATE_BOOTSTRAP_ON_START", web_section)
        self.assertIn("SYNDICATE_BOOTSTRAP_WNBA_TODAY", web_section)
        self.assertIn("SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP", web_section)
        self.assertIn("/opt/render/project/data/wnba_source", web_section)
        self.assertIn("SYNDICATE_REPORTS_ROOT", web_section)
        self.assertIn("/opt/render/project/data/reports", web_section)

        self.assertIn("disk:", worker_section)
        self.assertIn("/opt/render/project/data/", worker_section)


if __name__ == "__main__":
    unittest.main()
