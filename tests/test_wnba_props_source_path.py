from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.wnba import props as wnba_props


class WnbaPropsSourcePathTests(unittest.TestCase):
    def test_falls_back_to_candidate_root_when_processed_root_default_is_empty(self) -> None:
        # Regression: processed_root() unconditionally prefers a
        # "source_artifacts" candidate root even when nothing was ever
        # written there. The refresh pipeline writes
        # props_recommendations_top_by_game_{date}.json straight into the
        # WNBA source root's data/processed dir, so the props board must
        # search every candidate root instead of trusting the first one.
        with TemporaryDirectory() as tmp_dir:
            empty_default_root = Path(tmp_dir) / "wnba_source" / "source_artifacts" / "data" / "processed"
            real_root = Path(tmp_dir) / "wnba_source"
            real_processed = real_root / "data" / "processed"
            real_processed.mkdir(parents=True, exist_ok=True)
            file_name = "props_recommendations_top_by_game_2026-07-13.json"
            (real_processed / file_name).write_text('{"date": "2026-07-13", "data": []}', encoding="utf-8")

            with patch.object(wnba_props, "processed_root", return_value=empty_default_root), patch.object(
                wnba_props,
                "preferred_artifact_roots",
                return_value=[empty_default_root.parents[1], real_root],
            ):
                resolved = wnba_props._resolve_top_by_game_source_path("2026-07-13")

        self.assertEqual(resolved, real_processed / file_name)

    def test_uses_processed_root_default_when_it_has_the_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            default_root = Path(tmp_dir) / "processed"
            default_root.mkdir(parents=True, exist_ok=True)
            file_name = "props_recommendations_top_by_game_2026-07-13.json"
            (default_root / file_name).write_text('{"date": "2026-07-13", "data": []}', encoding="utf-8")

            with patch.object(wnba_props, "processed_root", return_value=default_root):
                resolved = wnba_props._resolve_top_by_game_source_path("2026-07-13")

        self.assertEqual(resolved, default_root / file_name)


if __name__ == "__main__":
    unittest.main()
