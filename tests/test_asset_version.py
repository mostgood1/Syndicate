from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import asset_version


class CardsSourceAssetVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.static_root = Path(self._tmp.name)
        self._root_patch = patch.object(asset_version, "_STATIC_ROOT", self.static_root)
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)

    def _touch(self, relative_path: str) -> None:
        path = self.static_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    def test_returns_max_mtime_across_existing_paths(self) -> None:
        self._touch("a.css")
        time.sleep(0.01)
        self._touch("b.js")
        result_a = int(asset_version.cards_source_asset_version("a.css").strip() or "0")
        result_both = int(asset_version.cards_source_asset_version("a.css", "b.js"))
        # b.js was written after a.css, so the combined result must reflect
        # b.js's later mtime, not a.css's earlier one.
        self.assertGreater(result_both, result_a)

    def test_returns_fallback_when_no_paths_exist(self) -> None:
        result = asset_version.cards_source_asset_version("does-not-exist.css")
        self.assertEqual(result, "1")

    def test_returns_fallback_for_empty_path_list(self) -> None:
        self.assertEqual(asset_version.cards_source_asset_version(), "1")

    def test_ignores_missing_paths_and_uses_the_real_one(self) -> None:
        self._touch("real.js")
        result = asset_version.cards_source_asset_version("missing.css", "real.js")
        self.assertNotEqual(result, "1")


if __name__ == "__main__":
    unittest.main()
