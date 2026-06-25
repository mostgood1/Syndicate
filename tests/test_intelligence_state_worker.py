from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.run_intelligence_state_worker as intelligence_state_worker


class IntelligenceStateWorkerTests(unittest.TestCase):
    def test_run_tick_computes_and_writes_board_state(self) -> None:
        computed_state = {
            "ok": True,
            "top_opportunities": [{"name": "Play 1"}],
            "candidate_count": 1,
        }

        with patch("scripts.run_intelligence_state_worker.central_today_iso", return_value="2026-06-25"):
            with patch(
                "scripts.run_intelligence_state_worker.compute_intelligence_state_response",
                return_value=dict(computed_state),
            ) as mocked_compute:
                with patch("scripts.run_intelligence_state_worker.write_latest_intelligence_state") as mocked_write:
                    intelligence_state_worker._run_tick()

        mocked_compute.assert_called_once_with(
            {
                "question": "top edges today",
                "mode": "recommendation",
                "date": "2026-06-25",
                "timing": "all",
                "sport": "all",
                "game_state": "all",
                "limit": 5,
                "include_props": True,
                "include_games": True,
            }
        )
        mocked_write.assert_called_once_with(computed_state)


if __name__ == "__main__":
    unittest.main()