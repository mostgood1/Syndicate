from __future__ import annotations

import os
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.mlb.cards import _daily_sim_updated_at_by_game
from syndicate.features.mlb.cards import _freshness_display
from syndicate.features.shared.timezone import CENTRAL_TIMEZONE


class FreshnessDisplayTests(unittest.TestCase):
    def test_formats_central_iso_to_short_display(self) -> None:
        self.assertEqual(_freshness_display("2026-07-24T13:25:41-05:00"), "7/24 1:25 PM")

    def test_converts_utc_to_central(self) -> None:
        # 18:25 UTC == 1:25 PM Central during daylight saving time.
        self.assertEqual(_freshness_display("2026-07-24T18:25:00Z"), "7/24 1:25 PM")

    def test_empty_and_garbage_inputs(self) -> None:
        self.assertIsNone(_freshness_display(None))
        self.assertIsNone(_freshness_display(""))
        self.assertEqual(_freshness_display("not-a-timestamp"), "not-a-timestamp")


class DailySimUpdatedAtTests(unittest.TestCase):
    def test_reads_artifact_mtime_per_game(self) -> None:
        # Single-game resims rewrite only that game's sim artifact, so the
        # per-game mtime is the "last simulated" signal -- two games whose
        # artifacts were written at different times must report different
        # timestamps.
        with TemporaryDirectory() as tmp:
            older = Path(tmp) / "sim_pk100.json"
            newer = Path(tmp) / "sim_pk200.json"
            older.write_text("{}", encoding="utf-8")
            newer.write_text("{}", encoding="utf-8")
            older_epoch = datetime(2026, 7, 24, 9, 0, 0, tzinfo=CENTRAL_TIMEZONE).timestamp()
            newer_epoch = datetime(2026, 7, 24, 12, 30, 0, tzinfo=CENTRAL_TIMEZONE).timestamp()
            os.utime(older, (older_epoch, older_epoch))
            os.utime(newer, (newer_epoch, newer_epoch))

            paths = {100: older, 200: newer, 300: None}
            with patch(
                "syndicate.features.mlb.cards.daily_sim_artifact_path",
                side_effect=lambda date_str, game_pk: paths.get(int(game_pk)),
            ):
                out = _daily_sim_updated_at_by_game("2026-07-24", [100, 200, 300])

        self.assertEqual(set(out), {100, 200})
        self.assertEqual(out[100], "2026-07-24T09:00:00-05:00")
        self.assertEqual(out[200], "2026-07-24T12:30:00-05:00")
        self.assertLess(out[100], out[200])

    def test_missing_artifact_file_is_skipped(self) -> None:
        with patch(
            "syndicate.features.mlb.cards.daily_sim_artifact_path",
            return_value=Path("C:/definitely/not/a/real/path/sim.json"),
        ):
            out = _daily_sim_updated_at_by_game("2026-07-24", [100])
        self.assertEqual(out, {})


if __name__ == "__main__":
    unittest.main()
