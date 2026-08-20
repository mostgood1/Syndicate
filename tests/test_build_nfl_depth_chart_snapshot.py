"""`nfl-artifact-publish-wiring`: THE FALSIFICATION CASE for
`scripts/build_nfl_depth_chart_snapshot.py`. Same shape as the roster-
snapshot sibling -- before this lane, no publish call site existed here
either.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.build_nfl_depth_chart_snapshot as build_script


def _fake_result(output_path: Path) -> MagicMock:
    result = MagicMock()
    result.rows = [{"player_id": "00-1"}]
    result.output_path = output_path
    return result


class PublishesToWebOnSuccess(unittest.TestCase):
    def test_main_calls_publish_hot_artifact_with_the_real_output_path(self) -> None:
        output_path = Path("/fake/depth_2026_snapshot.csv")
        with patch.object(build_script, "load_nflverse_roster", return_value=()), \
             patch.object(build_script, "load_nflverse_depth_chart", return_value=()), \
             patch.object(build_script, "write_depth_snapshot_csv", return_value=_fake_result(output_path)), \
             patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=True) as mock_publish, \
             patch.object(sys, "argv", ["build_nfl_depth_chart_snapshot.py", "--season", "2026"]):
            exit_code = build_script.main()
        mock_publish.assert_called_once_with(output_path)
        self.assertEqual(exit_code, 0)

    def test_publish_failure_does_not_fail_the_build(self) -> None:
        output_path = Path("/fake/depth_2026_snapshot.csv")
        with patch.object(build_script, "load_nflverse_roster", return_value=()), \
             patch.object(build_script, "load_nflverse_depth_chart", return_value=()), \
             patch.object(build_script, "write_depth_snapshot_csv", return_value=_fake_result(output_path)), \
             patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", side_effect=RuntimeError("network down")), \
             patch.object(sys, "argv", ["build_nfl_depth_chart_snapshot.py", "--season", "2026"]):
            exit_code = build_script.main()
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
