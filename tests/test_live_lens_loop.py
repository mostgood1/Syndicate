from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import live_lens_loop


class LiveLensLoopTests(unittest.TestCase):
    def tearDown(self) -> None:
        live_lens_loop._LIVE_LENS_LOOP_STOP.set()
        live_lens_loop._LIVE_LENS_LOOP_THREAD = None
        live_lens_loop._release_process_lock()

    def test_loop_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(live_lens_loop._is_live_lens_loop_enabled())

    def test_interval_defaults_to_sixty_seconds(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(live_lens_loop._live_lens_loop_interval_seconds(), 60)

    def test_interval_honors_env_override(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_LIVE_LENS_INTERVAL_SECONDS": "90"}, clear=False):
            self.assertEqual(live_lens_loop._live_lens_loop_interval_seconds(), 90)

    def test_run_tick_for_sport_writes_valid_snapshot(self) -> None:
        snapshot = {"date": "2026-07-13", "rank_cards": [], "cards": [], "games": []}
        with TemporaryDirectory() as tmp_dir:
            snapshot_path = Path(tmp_dir) / "live" / "nba_live_lens.json"
            with patch.dict(live_lens_loop._LIVE_LENS_BUILDERS, {"nba": lambda date_str: dict(snapshot)}), patch.dict(
                live_lens_loop._LIVE_LENS_VALIDATORS, {"nba": lambda payload: True}
            ), patch.dict(live_lens_loop._LIVE_LENS_SNAPSHOT_PATHS, {"nba": lambda: snapshot_path}), patch.object(
                live_lens_loop, "write_json_file"
            ) as mocked_write:
                result = live_lens_loop._run_live_lens_tick_for_sport("nba", "2026-07-13")

        self.assertTrue(result["ok"])
        mocked_write.assert_called_once_with(snapshot_path, snapshot)

    def test_run_tick_for_sport_skips_write_on_invalid_snapshot(self) -> None:
        with patch.dict(live_lens_loop._LIVE_LENS_BUILDERS, {"wnba": lambda date_str: {"date": date_str}}), patch.dict(
            live_lens_loop._LIVE_LENS_VALIDATORS, {"wnba": lambda payload: False}
        ), patch.object(live_lens_loop, "write_json_file") as mocked_write:
            result = live_lens_loop._run_live_lens_tick_for_sport("wnba", "2026-07-13")

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "invalid_snapshot")
        mocked_write.assert_not_called()

    def test_run_tick_for_sport_catches_builder_exception(self) -> None:
        def _raise(date_str: str) -> dict[str, object]:
            raise RuntimeError("boom")

        with patch.dict(live_lens_loop._LIVE_LENS_BUILDERS, {"mlb": _raise}), patch.object(live_lens_loop, "write_json_file") as mocked_write:
            result = live_lens_loop._run_live_lens_tick_for_sport("mlb", "2026-07-13")

        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])
        mocked_write.assert_not_called()

    def test_one_sport_failure_does_not_block_others(self) -> None:
        def _raise(date_str: str) -> dict[str, object]:
            raise RuntimeError("mlb down")

        with patch.object(live_lens_loop, "central_today_iso", return_value="2026-07-13"), patch.dict(
            live_lens_loop._LIVE_LENS_BUILDERS,
            {
                "mlb": _raise,
                "nba": lambda date_str: {"date": date_str},
                "wnba": lambda date_str: {"date": date_str},
            },
        ), patch.dict(
            live_lens_loop._LIVE_LENS_VALIDATORS,
            {"nba": lambda payload: True, "wnba": lambda payload: True},
        ), patch.object(live_lens_loop, "write_json_file") as mocked_write:
            meta = live_lens_loop._run_live_lens_tick()

        self.assertFalse(meta["results"]["mlb"]["ok"])
        self.assertTrue(meta["results"]["nba"]["ok"])
        self.assertTrue(meta["results"]["wnba"]["ok"])
        self.assertFalse(meta["ok"])
        # nba, wnba snapshot writes + the tick-summary write itself.
        self.assertEqual(mocked_write.call_count, 3)

    def test_start_live_lens_loop_noop_when_disabled(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_LIVE_LENS_LOOP": "false"}, clear=False):
            started = live_lens_loop.start_live_lens_loop()

        self.assertFalse(started)
        self.assertIsNone(live_lens_loop._LIVE_LENS_LOOP_THREAD)


if __name__ == "__main__":
    unittest.main()
