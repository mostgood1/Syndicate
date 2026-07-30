from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
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

    def test_min_headroom_defaults_to_300mb(self) -> None:
        # #124 root cause (2026-07-30): the old 1800MB default was
        # copy-pasted from live_refresh_loop.py's odds-refresh gate, which is
        # calibrated to a much heavier operation (~1528MB worst-case WNBA
        # odds-refresh spike). That left only 248MB of a 2048MB container
        # "allowed" to be in use, which live-odds-worker's steady-state
        # baseline (~700-900MB) never satisfied -- production logs showed
        # 33/33 sampled tick failures over 40h were reason=low_headroom, zero
        # exceptions. Paired before/after-build memory snapshots showed
        # estimate_live's real per-tick cost is 0-13MB. A silent regression
        # back toward 1800 would reintroduce the near-permanent failure rate.
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(live_lens_loop._mlb_live_lens_min_headroom_bytes(), 300 * 1024 * 1024)

    def test_pull_enabled_by_default(self) -> None:
        # #128: live-odds-worker had no mechanism to pull hot artifacts from
        # web at all (that only ran inside the intelligence-state loop,
        # which this service deliberately doesn't own) -- confirmed live via
        # MLB's build_cards_page_context reporting source_title "MLB cards
        # unavailable" on this service despite the identical call succeeding
        # on web. Default must stay True; a silent env-driven regression to
        # False would reintroduce this gap.
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(live_lens_loop._live_lens_pull_enabled())

    def test_pull_honors_env_override(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_LIVE_LENS_LOOP_PULL_ARTIFACTS": "false"}, clear=False):
            self.assertFalse(live_lens_loop._live_lens_pull_enabled())

    def test_background_loop_pulls_hot_artifacts_before_each_tick(self) -> None:
        with patch.object(live_lens_loop, "_live_lens_pull_enabled", return_value=True), patch.object(
            live_lens_loop, "pull_hot_artifacts", return_value=0
        ) as mock_pull, patch.object(live_lens_loop, "_run_live_lens_tick", return_value={"ok": True, "results": {}}), patch.object(
            live_lens_loop, "_live_lens_publish_enabled", return_value=False
        ), patch.object(live_lens_loop, "write_json_file"), patch.object(
            live_lens_loop, "_live_lens_loop_interval_seconds", return_value=60
        ):
            live_lens_loop._LIVE_LENS_LOOP_STOP.clear()

            def stop_after_first_wait(_seconds: float) -> bool:
                live_lens_loop._LIVE_LENS_LOOP_STOP.set()
                return True

            with patch.object(live_lens_loop._LIVE_LENS_LOOP_STOP, "wait", side_effect=stop_after_first_wait):
                live_lens_loop._live_lens_background_loop()

        mock_pull.assert_called_once()
        self.assertEqual(mock_pull.call_args.kwargs.get("date_str"), live_lens_loop.central_today_iso())

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

    def test_mlb_tick_skips_build_when_headroom_insufficient(self) -> None:
        builder = Mock(return_value={"date": "2026-07-20", "games": []})
        with patch.dict(
            live_lens_loop._LIVE_LENS_BUILDERS, {"mlb": builder}
        ), patch.object(
            live_lens_loop,
            "_mlb_live_lens_headroom_snapshot",
            return_value={"current_mb": 1900.0, "max_mb": 2048.0, "headroom_mb": 148.0, "min_required_mb": 1800.0, "sufficient": False},
        ), patch.object(live_lens_loop, "write_json_file") as mocked_write:
            result = live_lens_loop._run_live_lens_tick_for_sport("mlb", "2026-07-20")

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "low_headroom")
        self.assertFalse(result["memoryHeadroom"]["sufficient"])
        builder.assert_not_called()
        mocked_write.assert_not_called()

    def test_mlb_tick_proceeds_when_headroom_sufficient(self) -> None:
        snapshot = {"date": "2026-07-20", "games": []}
        with patch.dict(
            live_lens_loop._LIVE_LENS_BUILDERS, {"mlb": lambda date_str: dict(snapshot)}
        ), patch.object(
            live_lens_loop,
            "_mlb_live_lens_headroom_snapshot",
            return_value={"current_mb": 100.0, "max_mb": 2048.0, "headroom_mb": 1948.0, "min_required_mb": 1800.0, "sufficient": True},
        ), patch.object(live_lens_loop, "write_json_file") as mocked_write:
            result = live_lens_loop._run_live_lens_tick_for_sport("mlb", "2026-07-20")

        self.assertTrue(result["ok"])
        mocked_write.assert_called_once()

    def test_mlb_tick_proceeds_when_headroom_unmeasurable(self) -> None:
        # Local dev/tests have no cgroups, so headroom is unmeasurable (None)
        # on essentially every run -- that must NOT block the MLB build, or
        # this gate would silently disable MLB live-lens everywhere except
        # production.
        snapshot = {"date": "2026-07-20", "games": []}
        with patch.dict(
            live_lens_loop._LIVE_LENS_BUILDERS, {"mlb": lambda date_str: dict(snapshot)}
        ), patch.object(
            live_lens_loop, "_mlb_live_lens_headroom_snapshot", return_value=None
        ), patch.object(live_lens_loop, "write_json_file") as mocked_write:
            result = live_lens_loop._run_live_lens_tick_for_sport("mlb", "2026-07-20")

        self.assertTrue(result["ok"])
        mocked_write.assert_called_once()

    def test_mlb_tick_records_live_mc_source_tally(self) -> None:
        snapshot = {
            "date": "2026-07-20",
            "games": [
                {
                    "gameLens": [
                        {"source": "live_mc"},
                        {"source": "live_mc"},
                        {"source": "live_projection"},
                    ]
                },
                {"gameLens": [{"source": "segment_projection"}]},
            ],
        }
        with patch.dict(
            live_lens_loop._LIVE_LENS_BUILDERS, {"mlb": lambda date_str: snapshot}
        ), patch.object(
            live_lens_loop, "_mlb_live_lens_headroom_snapshot", return_value=None
        ), patch.object(live_lens_loop, "write_json_file"):
            result = live_lens_loop._run_live_lens_tick_for_sport("mlb", "2026-07-20")

        self.assertEqual(result["liveMcSources"], {"live_mc": 2, "live_projection": 1, "segment_projection": 1})

    def test_non_mlb_ticks_are_not_headroom_gated(self) -> None:
        with patch.object(live_lens_loop, "_mlb_live_lens_headroom_snapshot") as mocked_gate, patch.object(
            live_lens_loop, "write_json_file"
        ):
            live_lens_loop._run_live_lens_tick_for_sport("nba", "2026-07-20")
            live_lens_loop._run_live_lens_tick_for_sport("wnba", "2026-07-20")

        mocked_gate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
