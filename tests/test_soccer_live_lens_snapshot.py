from __future__ import annotations

import unittest

from syndicate.features.soccer.live_lens import live_lens_snapshot_path
from syndicate.features.soccer.live_lens import validate_live_lens_snapshot


class SoccerLiveLensSnapshotTests(unittest.TestCase):
    def test_snapshot_path_matches_other_sports_convention(self) -> None:
        path = live_lens_snapshot_path()
        self.assertEqual(path.name, "soccer_live_lens.json")
        self.assertEqual(path.parent.name, "live")

    def test_validate_rejects_non_dict(self) -> None:
        self.assertFalse(validate_live_lens_snapshot(None))
        self.assertFalse(validate_live_lens_snapshot(["not", "a", "dict"]))

    def test_validate_rejects_missing_date(self) -> None:
        self.assertFalse(validate_live_lens_snapshot({"games": []}))
        self.assertFalse(validate_live_lens_snapshot({"date": "", "games": []}))

    def test_validate_rejects_non_list_games(self) -> None:
        self.assertFalse(validate_live_lens_snapshot({"date": "2026-07-31", "games": {}}))

    def test_validate_accepts_real_shape(self) -> None:
        self.assertTrue(validate_live_lens_snapshot({"date": "2026-07-31", "games": []}))
        self.assertTrue(
            validate_live_lens_snapshot(
                {"date": "2026-07-31", "games": [{"league": "mls", "event_id": "123"}], "leagues_checked": ["mls"]}
            )
        )


if __name__ == "__main__":
    unittest.main()
