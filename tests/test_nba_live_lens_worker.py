from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.run_nba_live_lens_worker import _run_tick
from syndicate.features.nba.live_lens import LIVE_LENS_SNAPSHOT_PATH


class NbaLiveLensWorkerTests(unittest.TestCase):
    def test_worker_writes_valid_snapshot(self) -> None:
        snapshot = {
            "ok": True,
            "date": "2026-06-05",
            "rank_cards": [{"title": "BOS @ NYK"}],
            "page_context": {"route_path": "/nba/live-lens", "rank_cards": [{"title": "BOS @ NYK"}]},
            "api_payload": {"ok": True, "rank_cards": [{"title": "BOS @ NYK"}]},
            "live_player_lens_payload": {"ok": True, "games": []},
            "live_lines_payload": {"ok": True, "games": []},
            "live_pbp_stats_payload": {"ok": True, "games": []},
        }

        with patch("scripts.run_nba_live_lens_worker.build_live_lens_snapshot", return_value=dict(snapshot)) as mocked_build, patch(
            "scripts.run_nba_live_lens_worker.validate_live_lens_snapshot",
            return_value=True,
        ) as mocked_validate, patch("scripts.run_nba_live_lens_worker.write_json_file") as mocked_write:
            result = _run_tick()

        self.assertEqual(result, snapshot)
        mocked_build.assert_called_once()
        mocked_validate.assert_called_once_with(snapshot)
        mocked_write.assert_called_once_with(LIVE_LENS_SNAPSHOT_PATH, snapshot)

    def test_worker_skips_invalid_snapshot_write(self) -> None:
        snapshot = {"ok": True, "date": "2026-06-05", "rank_cards": []}

        with patch("scripts.run_nba_live_lens_worker.build_live_lens_snapshot", return_value=dict(snapshot)) as mocked_build, patch(
            "scripts.run_nba_live_lens_worker.validate_live_lens_snapshot",
            return_value=False,
        ) as mocked_validate, patch("scripts.run_nba_live_lens_worker.write_json_file") as mocked_write:
            result = _run_tick()

        self.assertEqual(result, snapshot)
        mocked_build.assert_called_once()
        mocked_validate.assert_called_once_with(snapshot)
        mocked_write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
