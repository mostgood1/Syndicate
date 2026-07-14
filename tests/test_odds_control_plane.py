from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared.odds_control_plane import build_odds_control_plane_snapshot
from syndicate.features.shared.odds_control_plane import list_available_shard_keys
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_lookback_shard_keys
from syndicate.features.shared.odds_control_plane import odds_history_paths_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_roots_for_sport
from syndicate.features.shared.odds_control_plane import resolve_current_shard_key
from syndicate.features.shared.odds_control_plane import write_odds_control_plane_snapshot


class OddsControlPlaneTests(unittest.TestCase):
    def test_odds_history_prefers_artifact_history_over_tracking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir) / "data"
            report_root = Path(tmp_dir) / "reports"
            shard_key = "2026-06-12"
            shared_path = report_root / "odds_control_plane" / "odds_history" / "nba" / f"{shard_key}.json"
            artifact_path = data_root / "nba_source" / "artifacts" / "nba" / "odds_history" / f"{shard_key}.json"
            tracking_path = data_root / "nba_source" / "tracking" / "odds_history" / f"{shard_key}.json"
            shared_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            tracking_path.parent.mkdir(parents=True, exist_ok=True)
            shared_path.write_text('{"source":"shared"}', encoding="utf-8")
            artifact_path.write_text('{"source":"artifact"}', encoding="utf-8")
            tracking_path.write_text('{"source":"tracking"}', encoding="utf-8")

            with patch("syndicate.features.shared.odds_control_plane.data_root", return_value=data_root), patch(
                "syndicate.features.shared.odds_control_plane.reports_root",
                return_value=report_root,
            ):
                actual_paths = [path.resolve() for path in odds_history_paths_for_sport("nba", shard_key)]
                self.assertEqual(actual_paths, [shared_path.resolve(), artifact_path.resolve(), tracking_path.resolve()])
                self.assertEqual(load_odds_history_payload_for_sport("nba", shard_key), {"source": "shared"})

    def test_control_plane_snapshot_writes_central_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir) / "data"
            report_root = Path(tmp_dir) / "reports"
            control_plane_path = report_root / "odds_control_plane" / "latest.json"
            with patch("syndicate.features.shared.odds_control_plane.data_root", return_value=data_root), patch(
                "syndicate.features.shared.odds_control_plane.reports_root",
                return_value=report_root,
            ):
                snapshot = build_odds_control_plane_snapshot(
                    {
                        "date": "2026-06-12",
                        "phase": "all",
                        "execution_mode": "source",
                        "dry_run": False,
                        "ok": True,
                        "results": [
                            {
                                "sport": "nba",
                                "ok": True,
                                "generation_mode": "local_artifact_bundle",
                                "ingestion_mode": "mirror_script",
                                "source_repo": str(Path(tmp_dir) / "nba_betting_repo"),
                                "source_root_env_var": "SYNDICATE_SOURCE_ROOT_NBA",
                                "artifact_paths": ["one", "two"],
                                "sport_manifest": {"payload": {"metadata": {"post_refresh_ok": True, "mirror_ok": True}}},
                            }
                        ],
                    }
                )
                written = write_odds_control_plane_snapshot(
                    {
                        "date": "2026-06-12",
                        "phase": "all",
                        "execution_mode": "source",
                        "dry_run": False,
                        "ok": True,
                        "results": snapshot["sports"],
                    }
                )

            self.assertEqual(Path(written["path"]), control_plane_path)
            self.assertTrue(control_plane_path.exists())
            self.assertEqual(snapshot["source_precedence"], ["shared_history", "artifact_history", "tracking_history"])
            self.assertEqual(snapshot["sports"][0]["sport"], "nba")
            self.assertEqual(snapshot["sports"][0]["odds_history"]["source_precedence"], ["shared_history", "artifact_history", "tracking_history"])

    def test_odds_history_roots_stay_on_data_root_and_shared_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir) / "data"
            report_root = Path(tmp_dir) / "reports"
            with patch("syndicate.features.shared.odds_control_plane.data_root", return_value=data_root), patch(
                "syndicate.features.shared.odds_control_plane.reports_root",
                return_value=report_root,
            ):
                roots = odds_history_roots_for_sport("wnba")

            self.assertEqual([root.resolve() for root in roots], [
                (report_root / "odds_control_plane" / "odds_history" / "wnba").resolve(),
                (data_root / "wnba_source").resolve(),
            ])

    def test_resolve_current_shard_key_daily_sport_returns_date(self) -> None:
        self.assertEqual(resolve_current_shard_key("mlb", "2026-06-12"), "2026-06-12")

    def test_resolve_current_shard_key_weekly_sport_uses_current_week_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir) / "data"
            report_root = Path(tmp_dir) / "reports"
            nfl_root = data_root / "nfl_source"
            nfl_root.mkdir(parents=True)
            (nfl_root / "current_week.json").write_text('{"season": 2025, "week": 3}', encoding="utf-8")

            with patch("syndicate.features.shared.odds_control_plane.data_root", return_value=data_root), patch(
                "syndicate.features.shared.odds_control_plane.reports_root",
                return_value=report_root,
            ):
                # No schedule data on disk to derive a date->week window, so
                # this falls back to the current_week.json tracked week.
                shard_key = resolve_current_shard_key("nfl", "2026-06-12")

            self.assertEqual(shard_key, "2025_wk3")

    def test_list_available_shard_keys_across_mirrors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir) / "data"
            report_root = Path(tmp_dir) / "reports"
            shared_dir = report_root / "odds_control_plane" / "odds_history" / "mlb"
            tracking_dir = data_root / "mlb_source" / "tracking" / "odds_history"
            shared_dir.mkdir(parents=True)
            tracking_dir.mkdir(parents=True)
            (shared_dir / "2026-06-01.json").write_text("{}", encoding="utf-8")
            (tracking_dir / "2026-06-02.json").write_text("{}", encoding="utf-8")

            with patch("syndicate.features.shared.odds_control_plane.data_root", return_value=data_root), patch(
                "syndicate.features.shared.odds_control_plane.reports_root",
                return_value=report_root,
            ):
                keys = list_available_shard_keys("mlb")

            self.assertEqual(keys, ["2026-06-01", "2026-06-02"])

    def test_odds_history_lookback_shard_keys_daily(self) -> None:
        self.assertEqual(
            odds_history_lookback_shard_keys("mlb", "2026-06-08", 2),
            ["2026-06-07", "2026-06-06"],
        )
        self.assertEqual(odds_history_lookback_shard_keys("mlb", "2026-06-08", 0), [])

    def test_odds_history_lookback_shard_keys_weekly(self) -> None:
        self.assertEqual(
            odds_history_lookback_shard_keys("nfl", "2025_wk3", 2),
            ["2025_wk2", "2025_wk1"],
        )


if __name__ == "__main__":
    unittest.main()