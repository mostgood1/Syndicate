from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from syndicate.features.ncaab.mirror_export import build_live_lines_payload_from_raw
from syndicate.features.ncaab.mirror_export import build_live_state_payload_from_raw
from syndicate.features.ncaab.mirror_export import build_recommendations_payload_from_raw
from syndicate.features.ncaab.mirror_export import build_results_payload_from_raw
from syndicate.features.ncaab.mirror_export import export_api_bundle_from_raw


class NcaabMirrorExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.raw_root = self.repo_root / "data" / "ncaab_source" / "raw_outputs"
        self.selected_date = "2026-04-06"

    def test_build_recommendations_payload_from_raw_generates_local_rows(self) -> None:
        payload = build_recommendations_payload_from_raw(self.raw_root, self.selected_date)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["date"], self.selected_date)
        self.assertGreaterEqual(int(payload["rows"]), 2)
        rows = payload.get("data") if isinstance(payload.get("data"), list) else []
        self.assertTrue(any(str(row.get("rec_code")) == "ATS" for row in rows))
        self.assertTrue(any(str(row.get("rec_code")) == "OU" for row in rows))
        self.assertTrue(any(str(row.get("game_id")) == "401856600" for row in rows))

    def test_export_api_bundle_from_raw_writes_dates_and_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            api_root = Path(tmp_dir) / "api"
            manifest = export_api_bundle_from_raw(api_root, self.raw_root, self.selected_date)

            self.assertEqual(manifest["date"], self.selected_date)
            self.assertIn(self.selected_date, manifest["display_dates"])
            self.assertTrue((api_root / "display_prediction_dates.json").exists())
            self.assertTrue((api_root / "dates.json").exists())
            self.assertTrue((api_root / "recommendations" / f"recommendations_{self.selected_date}.json").exists())

    def test_build_results_payload_from_raw_generates_settled_rows(self) -> None:
        payload = build_results_payload_from_raw(self.raw_root, self.selected_date)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["date"], self.selected_date)
        self.assertEqual(int(payload["count"]), 1)
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        self.assertEqual(rows[0]["game_id"], 401856600)
        self.assertEqual(rows[0]["home_score"], 69)
        self.assertEqual(rows[0]["away_score"], 63)
        self.assertEqual(rows[0]["actual_ats"], "Away Cover")
        self.assertEqual(rows[0]["actual_ou"], "Under")
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        self.assertEqual(summary.get("ats_correct"), 1)
        self.assertEqual(summary.get("totals_correct"), 0)

    def test_export_api_bundle_from_raw_writes_results_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            api_root = Path(tmp_dir) / "api"
            manifest = export_api_bundle_from_raw(api_root, self.raw_root, self.selected_date)

            self.assertIn(self.selected_date, manifest["results_dates"])
            self.assertTrue((api_root / "results_dates.json").exists())
            self.assertTrue((api_root / "results_by_date" / f"results_{self.selected_date}.json").exists())

    def test_build_live_state_payload_from_raw_generates_recent_final(self) -> None:
        payload = build_live_state_payload_from_raw(self.raw_root, self.selected_date)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["date"], self.selected_date)
        self.assertEqual(int(payload["count"]), 1)
        games = payload.get("games") if isinstance(payload.get("games"), dict) else {}
        game = games.get("401856600") if isinstance(games.get("401856600"), dict) else {}
        self.assertEqual(game.get("home_score"), 69)
        self.assertEqual(game.get("away_score"), 63)
        self.assertEqual(game.get("state"), "post")
        self.assertEqual(game.get("is_final"), True)

    def test_build_live_lines_payload_from_raw_generates_latest_line_snapshot(self) -> None:
        payload = build_live_lines_payload_from_raw(self.raw_root, self.selected_date)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["date"], self.selected_date)
        self.assertGreaterEqual(int(payload["count"]), 1)
        lines = payload.get("lines") if isinstance(payload.get("lines"), dict) else {}
        line = lines.get("401856600") if isinstance(lines.get("401856600"), dict) else {}
        self.assertEqual(line.get("book"), "DraftKings")
        self.assertEqual(line.get("total"), 132.5)

    def test_build_live_lines_payload_from_raw_does_not_require_snapshot_lines_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_root = Path(tmp_dir) / "raw_outputs"
            date_root = raw_root / "by_date" / self.selected_date
            date_root.mkdir(parents=True, exist_ok=True)
            for name in [
                f"live_features_{self.selected_date}.csv",
                f"predictions_unified_enriched_{self.selected_date}.csv",
            ]:
                shutil.copy2(self.raw_root / "by_date" / self.selected_date / name, date_root / name)

            payload = build_live_lines_payload_from_raw(raw_root, self.selected_date)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["date"], self.selected_date)
        self.assertGreaterEqual(int(payload["count"]), 1)
        lines = payload.get("lines") if isinstance(payload.get("lines"), dict) else {}
        line = lines.get("401856600") if isinstance(lines.get("401856600"), dict) else {}
        self.assertEqual(line.get("book"), "DraftKings")
        self.assertEqual(line.get("total"), 132.5)

    def test_export_api_bundle_from_raw_writes_live_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            api_root = Path(tmp_dir) / "api"
            export_api_bundle_from_raw(api_root, self.raw_root, self.selected_date)

            self.assertTrue((api_root / "live_state" / f"live_state_{self.selected_date}.json").exists())
            self.assertTrue((api_root / "live_lines" / f"live_lines_{self.selected_date}.json").exists())

    def test_refresh_ncaab_mirror_script_has_no_source_fallback_switch(self) -> None:
        script_path = self.repo_root / "scripts" / "refresh_ncaab_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertNotIn("[switch]$AllowSourceAppFallback", content)
        self.assertNotIn("--allow-source-app-fallback", content)

    def test_export_ncaab_source_mirror_script_has_no_source_app_fallback_flag(self) -> None:
        script_path = self.repo_root / "scripts" / "export_ncaab_source_mirror.py"
        content = script_path.read_text(encoding="utf-8")

        self.assertNotIn("--allow-source-app-fallback", content)
        self.assertNotIn("def _run_source_app_fallback", content)
        self.assertNotIn("live_snapshot_lines_", content)
        self.assertNotIn("predictions_display_", content)