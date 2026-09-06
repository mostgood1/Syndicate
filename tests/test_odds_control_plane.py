from __future__ import annotations

import os
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
    def test_odds_history_takes_the_FRESHEST_copy_not_the_highest_precedence(self) -> None:
        """Renamed and re-pointed `[2026-09-05]`. It asserted the OLD contract.

        `load_odds_history_payload_for_sport` was FIRST-HIT over
        `odds_history_paths_for_sport`'s fixed precedence (shared -> artifacts ->
        tracking) and was deliberately changed to NEWEST MTIME WINS, with
        precedence demoted to a tie-break. Its docstring carries the incident:
        live on refresh-worker 2026-08-04, `STREAM_PULL_OK` wrote 19,798,176
        bytes of the 3,436-market MLB shard and the very next board build still
        read `entry_count=611` from the stale shared copy, leaving every MLB
        candidate at `history_points=0`.

        This test wrote the three files in precedence order, so `tracking` was
        newest and correctly won -- and the old assertion read that correct
        behaviour as a failure. Both halves of the real contract are pinned
        below, with mtimes SET rather than inherited from write order, because
        a tie-break cannot be tested by a fixture that never ties.
        """
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

                # (1) FRESHEST WINS, against precedence. `tracking` is last in
                # precedence and newest here, so a first-hit regression returns
                # "shared" and fails.
                os.utime(shared_path, (1_000_000, 1_000_000))
                os.utime(artifact_path, (1_000_100, 1_000_100))
                os.utime(tracking_path, (1_000_200, 1_000_200))
                self.assertEqual(
                    load_odds_history_payload_for_sport("nba", shard_key),
                    {"source": "tracking"},
                    "the freshest copy must win -- a stale higher-precedence copy "
                    "shadowing a newly pulled shard is the 2026-08-04 incident",
                )

                # (2) ...and the reverse, so (1) cannot pass by simply always
                # taking the LAST path: make `artifact` newest and it must win.
                os.utime(tracking_path, (1_000_050, 1_000_050))
                self.assertEqual(
                    load_odds_history_payload_for_sport("nba", shard_key),
                    {"source": "artifact"},
                )

                # (3) ON A TIE, precedence decides -- shared first. This is the
                # writing service's case, where _sync_odds_history_for_refresh
                # writes all three together.
                for path in (shared_path, artifact_path, tracking_path):
                    os.utime(path, (1_000_500, 1_000_500))
                self.assertEqual(
                    load_odds_history_payload_for_sport("nba", shard_key),
                    {"source": "shared"},
                    "equal mtimes must fall back to precedence order",
                )

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