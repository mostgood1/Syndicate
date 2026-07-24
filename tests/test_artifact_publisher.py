from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.error import URLError

from syndicate.app import create_app
from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path
from syndicate.features.shared.artifact_publisher import publish_hot_artifact
from syndicate.features.shared.artifact_publisher import publish_changed_hot_artifacts
from syndicate.features.shared.artifact_publisher import pull_hot_artifacts


HOT_RELATIVE_PATH = "wnba_source/source_artifacts/data/processed/recommendations_slate_2026-07-13.json"


class HotArtifactAllowlistTests(unittest.TestCase):
    def test_accepts_known_hot_artifact_shapes(self) -> None:
        self.assertTrue(
            is_hot_artifact_relative_path(
                "mlb_source/source_artifacts/data/live_lens/live_lens_report_2026_07_13.json"
            )
        )
        self.assertTrue(is_hot_artifact_relative_path(HOT_RELATIVE_PATH))

    def test_accepts_phase3_calibration_and_manifest_files_with_confirmed_live_reads(self) -> None:
        # Only files confirmed read by a blueprint/cards.py at request time
        # belong here -- see the allowlist's own comment for what was
        # deliberately excluded (calibration_active.json, prob_calibration.json,
        # manifests/*) because nothing in the web-serving path reads them.
        self.assertTrue(is_hot_artifact_relative_path("nfl_source/current_week.json"))
        self.assertTrue(is_hot_artifact_relative_path("nfl_source/source_artifacts/current_week.json"))
        self.assertTrue(
            is_hot_artifact_relative_path(
                "nba_source/data/processed/season_betting_card_manifest_2025_retuned.json"
            )
        )
        self.assertTrue(
            is_hot_artifact_relative_path(
                "nba_source/source_artifacts/data/processed/live_player_lens_tuning_2026-05-28.csv"
            )
        )
        self.assertTrue(
            is_hot_artifact_relative_path(
                "wnba_source/data/processed/live_player_lens_tuning_2026-05-29.csv"
            )
        )

    def test_accepts_daily_odds_and_lineup_snapshots(self) -> None:
        # Confirmed live reads: MLB cards.py loads snapshots/<date>/oddsapi_*
        # and lineups.json for market tiles; hr_targets.py walks the date dir.
        for name in ("oddsapi_game_lines_2026_07_16", "oddsapi_hitter_props_2026_07_16", "oddsapi_pitcher_props_2026_07_16", "lineups", "probables", "meta"):
            self.assertTrue(
                is_hot_artifact_relative_path(
                    f"mlb_source/source_artifacts/data/daily/snapshots/2026-07-16/{name}.json"
                ),
                name,
            )
        self.assertTrue(
            is_hot_artifact_relative_path("mlb_source/data/daily/snapshots/2026-07-16/lineups.json")
        )
        # Non-JSON or deeper nesting stays excluded.
        self.assertFalse(
            is_hot_artifact_relative_path("mlb_source/source_artifacts/data/daily/snapshots/2026-07-16/raw/feed.csv")
        )

    def test_accepts_nba_wnba_raw_player_props_csv(self) -> None:
        # Confirmed via direct research 2026-07-23: this raw OddsAPI feed
        # was written worker-side but never allowlisted, so it never
        # reached the web dyno -- the market board's Layer 1 join only ever
        # saw the recommendation engine's own curated picks.
        self.assertTrue(is_hot_artifact_relative_path("nba_source/source_artifacts/data/processed/oddsapi_player_props_2026-07-23.csv"))
        self.assertTrue(is_hot_artifact_relative_path("wnba_source/data/processed/oddsapi_player_props_2026-07-23.csv"))

    def test_accepts_soccer_raw_odds_props_and_picks(self) -> None:
        # 2026-07-24 fix: the fetch/picks scripts have been scheduled in
        # refresh_odds_sources.py for a while and run successfully (confirmed
        # live in production, return_code=0), but these three patterns were
        # never allowlisted, so the resulting files never reached the web
        # dyno -- the market board's Layer 1 join saw zero rows regardless
        # of league or date.
        self.assertTrue(is_hot_artifact_relative_path("soccer_source/mls/api/odds/game_odds_current.csv"))
        self.assertTrue(is_hot_artifact_relative_path("soccer_source/epl/api/odds/game_odds_current.csv"))
        self.assertTrue(is_hot_artifact_relative_path("soccer_source/mls/props/2026-07-23.csv"))
        self.assertTrue(is_hot_artifact_relative_path("soccer_source/mls/api/picks/picks_2026-07-23.csv"))

    def test_rejects_worker_only_calibration_and_manifest_files(self) -> None:
        self.assertFalse(is_hot_artifact_relative_path("nfl_source/calibration_active.json"))
        self.assertFalse(is_hot_artifact_relative_path("nfl_source/prob_calibration.json"))
        self.assertFalse(is_hot_artifact_relative_path("nfl_source/manifests/mirror_refresh_latest.json"))

    def test_rejects_paths_outside_allowlist(self) -> None:
        self.assertFalse(is_hot_artifact_relative_path("reports/intelligence/evaluation_ledger_chunks/part_1.json"))
        self.assertFalse(is_hot_artifact_relative_path("mlb_source/source_artifacts/data/statcast/2026.csv"))
        self.assertFalse(is_hot_artifact_relative_path(""))

    def test_rejects_intelligence_board_snapshot_and_state(self) -> None:
        # board_snapshot.json / intelligence_state.json are written through the
        # shared keyvalue (Redis) backend already, so they're intentionally
        # excluded from the HTTP-push allowlist. A file never exists on disk for
        # these on Render, so publishing would always fail anyway.
        self.assertFalse(is_hot_artifact_relative_path("reports/intelligence/board_snapshot.json"))
        self.assertFalse(is_hot_artifact_relative_path("reports/intelligence/intelligence_state.json"))

    def test_rejects_path_traversal_and_absolute_paths(self) -> None:
        self.assertFalse(is_hot_artifact_relative_path("../../etc/passwd"))
        self.assertFalse(is_hot_artifact_relative_path(f"/{HOT_RELATIVE_PATH}"))
        self.assertFalse(is_hot_artifact_relative_path(f"wnba_source/../../../{HOT_RELATIVE_PATH}"))


class PublishHotArtifactClientTests(unittest.TestCase):
    def test_noop_when_publish_url_not_configured(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            target = data_root / HOT_RELATIVE_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"SYNDICATE_DATA_ROOT": str(data_root), "ADMIN_TOKEN": "secret-token"},
                clear=False,
            ):
                os.environ.pop("SYNDICATE_WEB_PUBLISH_URL", None)
                with patch("urllib.request.urlopen") as mocked_urlopen:
                    result = publish_hot_artifact(target)
        self.assertFalse(result)
        mocked_urlopen.assert_not_called()

    def test_noop_when_path_not_in_allowlist(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            target = data_root / "mlb_source" / "source_artifacts" / "data" / "statcast" / "2026.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("data", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen") as mocked_urlopen:
                    result = publish_hot_artifact(target)
        self.assertFalse(result)
        mocked_urlopen.assert_not_called()

    def test_publishes_allowlisted_file_with_expected_request(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            target = data_root / HOT_RELATIVE_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"candidate_count": 3}), encoding="utf-8")

            mocked_response = MagicMock()
            mocked_response.__enter__.return_value = mocked_response
            mocked_response.read.return_value = b"{}"

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=mocked_response) as mocked_urlopen:
                    result = publish_hot_artifact(target)

        self.assertTrue(result)
        mocked_urlopen.assert_called_once()
        sent_request = mocked_urlopen.call_args.args[0]
        self.assertEqual(sent_request.full_url, "https://syndicate.onrender.com/api/ops/artifacts/publish")
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer secret-token")
        body = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(body["relative_path"], HOT_RELATIVE_PATH)
        self.assertIn("candidate_count", body["content"])

    def test_network_failure_is_swallowed(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            target = data_root / HOT_RELATIVE_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", side_effect=URLError("boom")):
                    result = publish_hot_artifact(target)
        self.assertFalse(result)

    def test_publish_changed_hot_artifacts_only_publishes_recent_matching_files(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            fresh = data_root / HOT_RELATIVE_PATH
            fresh.parent.mkdir(parents=True, exist_ok=True)
            fresh.write_text("{}", encoding="utf-8")
            not_allowlisted = data_root / "reports" / "intelligence" / "evaluation_ledger_chunks" / "part_1.json"
            not_allowlisted.parent.mkdir(parents=True, exist_ok=True)
            not_allowlisted.write_text("{}", encoding="utf-8")

            since_epoch = time.time() - 3600

            mocked_response = MagicMock()
            mocked_response.__enter__.return_value = mocked_response
            mocked_response.read.return_value = b"{}"

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=mocked_response) as mocked_urlopen:
                    published_count = publish_changed_hot_artifacts(since_epoch)

        self.assertEqual(published_count, 1)
        mocked_urlopen.assert_called_once()


class PullHotArtifactClientTests(unittest.TestCase):
    def test_noop_when_publish_url_not_configured(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {"SYNDICATE_DATA_ROOT": tmp_dir, "ADMIN_TOKEN": "secret-token"},
                clear=False,
            ):
                os.environ.pop("SYNDICATE_WEB_PUBLISH_URL", None)
                with patch("urllib.request.urlopen") as mocked_urlopen:
                    result = pull_hot_artifacts()
        self.assertEqual(result, 0)
        mocked_urlopen.assert_not_called()

    def test_scopes_request_to_date_pattern_when_provided(self) -> None:
        # Two separate requests, one per date-separator format -- WNBA's
        # artifacts are hyphen-dated (recommendations_slate_2026-07-20.json),
        # MLB's are underscore-dated (live_lens_report_2026_07_20.json). A
        # single combined bracket-expression pattern matching both at once
        # was tried first and reproducibly 502'd in production (roughly
        # doubles the combined result size); two smaller requests each stay
        # close to the original, already-safe per-request size.
        with TemporaryDirectory() as tmp_dir:
            mocked_response = MagicMock()
            mocked_response.__enter__.return_value = mocked_response
            mocked_response.read.return_value = json.dumps({"ok": True, "count": 0, "artifacts": {}}).encode("utf-8")

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": tmp_dir,
                    "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports_root"),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=mocked_response) as mocked_urlopen:
                    pull_hot_artifacts(date_str="2026-07-20")

            self.assertEqual(mocked_urlopen.call_count, 2)
            requested_urls = {call.args[0].full_url for call in mocked_urlopen.call_args_list}
            self.assertEqual(
                requested_urls,
                {
                    "https://syndicate.onrender.com/api/ops/artifacts/export?pattern=%2A2026-07-20%2A",
                    "https://syndicate.onrender.com/api/ops/artifacts/export?pattern=%2A2026_07_20%2A",
                },
            )

    def test_date_glob_patterns_cover_both_separator_styles(self) -> None:
        import fnmatch

        from syndicate.features.shared.artifact_publisher import _date_glob_patterns

        patterns = _date_glob_patterns("2026-07-20")
        self.assertTrue(any(fnmatch.fnmatch("recommendations_slate_2026-07-20.json", p) for p in patterns))
        self.assertTrue(any(fnmatch.fnmatch("live_lens_report_2026_07_20.json", p) for p in patterns))
        self.assertFalse(any(fnmatch.fnmatch("recommendations_slate_2026-07-21.json", p) for p in patterns))

    def test_unfiltered_request_omits_pattern_query_param(self) -> None:
        # A full, unfiltered export reproducibly hit Render's proxy timeout
        # in production once enough sports/days had accumulated hot
        # artifacts -- date_str scoping (tested above) is the path every
        # real caller should use. This just confirms omitting date_str still
        # hits the plain export URL for callers/tests that want that.
        with TemporaryDirectory() as tmp_dir:
            mocked_response = MagicMock()
            mocked_response.__enter__.return_value = mocked_response
            mocked_response.read.return_value = json.dumps({"ok": True, "count": 0, "artifacts": {}}).encode("utf-8")

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": tmp_dir,
                    "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports_root"),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=mocked_response) as mocked_urlopen:
                    pull_hot_artifacts()

            sent_request = mocked_urlopen.call_args.args[0]
            self.assertEqual(sent_request.full_url, "https://syndicate.onrender.com/api/ops/artifacts/export")

    def test_writes_allowlisted_artifacts_and_skips_the_rest(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir).resolve()
            export_payload = {
                "ok": True,
                "count": 2,
                "artifacts": {
                    HOT_RELATIVE_PATH: json.dumps({"candidate_count": 7}),
                    "reports/intelligence/evaluation_ledger_chunks/part_1.json": "{}",
                },
            }
            mocked_response = MagicMock()
            mocked_response.__enter__.return_value = mocked_response
            mocked_response.read.return_value = json.dumps(export_payload).encode("utf-8")

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "SYNDICATE_REPORTS_ROOT": str(data_root / "reports_root"),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=mocked_response) as mocked_urlopen:
                    written = pull_hot_artifacts()

            self.assertEqual(written, 1)
            mocked_urlopen.assert_called_once()
            sent_request = mocked_urlopen.call_args.args[0]
            self.assertEqual(sent_request.full_url, "https://syndicate.onrender.com/api/ops/artifacts/export")
            self.assertEqual(sent_request.get_header("Authorization"), "Bearer secret-token")

            written_path = data_root / HOT_RELATIVE_PATH
            self.assertTrue(written_path.exists())
            self.assertEqual(json.loads(written_path.read_text(encoding="utf-8"))["candidate_count"], 7)
            self.assertFalse((data_root / "reports" / "intelligence" / "evaluation_ledger_chunks" / "part_1.json").exists())
            leftovers = list(written_path.parent.glob(f"{written_path.name}.*.pull.tmp"))
            self.assertEqual(leftovers, [])

    def test_second_pull_sends_since_watermark_from_first_pulls_start(self) -> None:
        # The dominant fix for repeated 8.6-28.9MB export responses every
        # ~30s: a second pull should ask the server to skip anything
        # unchanged since the first pull's own start time, not re-request
        # everything again.
        empty_response = MagicMock()
        empty_response.__enter__.return_value = empty_response
        empty_response.read.return_value = json.dumps({"ok": True, "count": 0, "artifacts": {}}).encode("utf-8")

        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": tmp_dir,
                    "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports_root"),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=empty_response) as mocked_urlopen:
                    pull_hot_artifacts(date_str="2026-07-24")
                    first_call_url = mocked_urlopen.call_args.args[0].full_url
                    self.assertNotIn("since=", first_call_url)

                    pull_hot_artifacts(date_str="2026-07-24")
                    second_call_url = mocked_urlopen.call_args.args[0].full_url
                    self.assertIn("since=", second_call_url)

    def test_failed_pull_does_not_advance_watermark(self) -> None:
        # A transient network blip must not permanently skip files modified
        # during the failed window -- the next pull should still ask for
        # everything since the last SUCCESSFUL pull, not the failed one's
        # start time.
        with TemporaryDirectory() as tmp_dir:
            env = {
                "SYNDICATE_DATA_ROOT": tmp_dir,
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports_root"),
                "ADMIN_TOKEN": "secret-token",
                "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("urllib.request.urlopen", side_effect=URLError("boom")):
                    written = pull_hot_artifacts(date_str="2026-07-24")
                self.assertEqual(written, 0)

                empty_response = MagicMock()
                empty_response.__enter__.return_value = empty_response
                empty_response.read.return_value = json.dumps({"ok": True, "count": 0, "artifacts": {}}).encode("utf-8")
                with patch("urllib.request.urlopen", return_value=empty_response) as mocked_urlopen:
                    pull_hot_artifacts(date_str="2026-07-24")
                    # No watermark was recorded after the failure, so this
                    # next pull still has nothing to advance from.
                    self.assertNotIn("since=", mocked_urlopen.call_args.args[0].full_url)

    def test_concurrent_pulls_of_the_same_artifact_do_not_collide(self) -> None:
        # Confirmed live 2026-07-23: two overlapping pulls for the same
        # artifact in the same process (same pid) computed the identical
        # temp_path, so the first os.replace() consumed it and the second's
        # os.replace() failed with ENOENT ('src' -> 'dst', PULL_WRITE_FAILED
        # in production for soccer's MLS recommendations/live_state
        # artifacts). Runs real threads writing the same artifact
        # concurrently to prove the fix (a uuid-suffixed temp filename)
        # eliminates that specific collision.
        #
        # Not asserting every concurrent writer reports success: POSIX
        # os.replace() to the same destination is atomic and never errors
        # this way (production is Linux), but Windows' file-replace
        # semantics can still reject a same-destination write racing another
        # thread's replace with an unrelated (correctly unique) temp source
        # -- a real Windows-dev-sandbox quirk, not the bug this fix targets.
        # The meaningful assertions are: no leftover temp files (nothing
        # orphaned), the final artifact is valid, and no failure references
        # a *missing* temp file (the actual collision signature fixed here).
        import threading

        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir).resolve()
            export_payload = {
                "ok": True,
                "count": 1,
                "artifacts": {HOT_RELATIVE_PATH: json.dumps({"candidate_count": 7})},
            }

            def _fake_urlopen(*_args, **_kwargs):
                mocked_response = MagicMock()
                mocked_response.__enter__.return_value = mocked_response
                mocked_response.read.return_value = json.dumps(export_payload).encode("utf-8")
                return mocked_response

            results: list[int] = []
            errors: list[BaseException] = []

            def _run() -> None:
                try:
                    results.append(pull_hot_artifacts())
                except BaseException as exc:  # pragma: no cover - defensive
                    errors.append(exc)

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                    threads = [threading.Thread(target=_run) for _ in range(8)]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join(timeout=10)

            self.assertEqual(errors, [])
            self.assertGreaterEqual(sum(results), 1)
            written_path = data_root / HOT_RELATIVE_PATH
            self.assertTrue(written_path.exists())
            self.assertEqual(json.loads(written_path.read_text(encoding="utf-8"))["candidate_count"], 7)
            leftovers = list(written_path.parent.glob(f"{written_path.name}.*.pull.tmp"))
            self.assertEqual(leftovers, [])

    def test_rejects_path_traversal_in_response(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            export_payload = {
                "ok": True,
                "count": 1,
                "artifacts": {f"../../{HOT_RELATIVE_PATH}": "{}"},
            }
            mocked_response = MagicMock()
            mocked_response.__enter__.return_value = mocked_response
            mocked_response.read.return_value = json.dumps(export_payload).encode("utf-8")

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=mocked_response):
                    written = pull_hot_artifacts()

        self.assertEqual(written, 0)
        self.assertFalse(any(data_root.parent.glob(HOT_RELATIVE_PATH)))

    def test_network_failure_is_swallowed(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": tmp_dir,
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", side_effect=URLError("boom")):
                    result = pull_hot_artifacts()
        self.assertEqual(result, 0)


class ArtifactPublishEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_requires_admin_token(self) -> None:
        response = self.client.post(
            "/api/ops/artifacts/publish",
            json={"relative_path": HOT_RELATIVE_PATH, "content": "{}"},
        )
        self.assertEqual(response.status_code, 503)

    def test_rejects_unauthorized_request(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                json={"relative_path": HOT_RELATIVE_PATH, "content": "{}"},
                headers={"Authorization": "Bearer wrong-token"},
            )
        self.assertEqual(response.status_code, 401)

    def test_rejects_path_not_in_allowlist(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                json={"relative_path": "mlb_source/source_artifacts/data/statcast/2026.csv", "content": "data"},
                headers={"Authorization": "Bearer secret-token"},
            )
        self.assertEqual(response.status_code, 403)

    def test_rejects_intelligence_board_snapshot_path(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                json={"relative_path": "reports/intelligence/board_snapshot.json", "content": "{}"},
                headers={"Authorization": "Bearer secret-token"},
            )
        self.assertEqual(response.status_code, 403)

    def test_rejects_path_traversal(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                json={
                    "relative_path": f"../../{HOT_RELATIVE_PATH}",
                    "content": "{}",
                },
                headers={"Authorization": "Bearer secret-token"},
            )
        self.assertEqual(response.status_code, 400)

    def test_writes_allowlisted_artifact_atomically(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_DATA_ROOT": str(data_root)},
                clear=False,
            ):
                response = self.client.post(
                    "/api/ops/artifacts/publish",
                    json={
                        "relative_path": HOT_RELATIVE_PATH,
                        "content": json.dumps({"candidate_count": 5}),
                    },
                    headers={"Authorization": "Bearer secret-token"},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            written_path = data_root / HOT_RELATIVE_PATH
            self.assertTrue(written_path.exists())
            self.assertEqual(json.loads(written_path.read_text(encoding="utf-8"))["candidate_count"], 5)
            # No leftover temp files from the atomic write.
            leftovers = list(written_path.parent.glob(f"{written_path.name}.*.tmp"))
            self.assertEqual(leftovers, [])


class ArtifactExportEndpointTests(unittest.TestCase):
    # Phase 4 of migrating off the daily-update GHA cron: read-only
    # counterpart to /api/ops/artifacts/publish, letting the reduced
    # backup-only workflow pull the current hot-artifact set back down for a
    # git-committed cold-start safety net.
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_export_requires_admin_token(self) -> None:
        response = self.client.get("/api/ops/artifacts/export")
        self.assertEqual(response.status_code, 503)

    def test_export_rejects_unauthorized_request(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get(
                "/api/ops/artifacts/export",
                headers={"Authorization": "Bearer wrong-token"},
            )
        self.assertEqual(response.status_code, 401)

    def test_export_returns_only_allowlisted_artifacts_with_content(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            hot_path = data_root / HOT_RELATIVE_PATH
            hot_path.parent.mkdir(parents=True, exist_ok=True)
            hot_path.write_text(json.dumps({"candidate_count": 5}), encoding="utf-8")

            bulk_path = data_root / "mlb_source" / "source_artifacts" / "data" / "statcast" / "2026.csv"
            bulk_path.parent.mkdir(parents=True, exist_ok=True)
            bulk_path.write_text("bulk,data\n1,2\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_DATA_ROOT": str(data_root)},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/artifacts/export",
                    headers={"Authorization": "Bearer secret-token"},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertIn(HOT_RELATIVE_PATH, payload["artifacts"])
            self.assertEqual(
                json.loads(payload["artifacts"][HOT_RELATIVE_PATH])["candidate_count"], 5
            )
            self.assertNotIn(
                "mlb_source/source_artifacts/data/statcast/2026.csv", payload["artifacts"]
            )
            self.assertEqual(payload["count"], len(payload["artifacts"]))

    def test_export_since_param_excludes_files_unmodified_since_watermark(self) -> None:
        # Mirrors sweep_changed_hot_artifacts' own mtime check on the push
        # side (artifact_publisher.py) -- confirmed as the fix for this
        # endpoint serving 8.6-28.9MB responses every ~30s to a single
        # caller, almost all of it unchanged since that caller's own last
        # successful pull.
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            old_path = data_root / HOT_RELATIVE_PATH
            old_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.write_text(json.dumps({"candidate_count": 5}), encoding="utf-8")
            old_epoch = time.time() - 3600
            os.utime(old_path, (old_epoch, old_epoch))

            fresh_relative = "wnba_source/source_artifacts/data/processed/recommendations_slate_2026-07-24.json"
            fresh_path = data_root / fresh_relative
            fresh_path.parent.mkdir(parents=True, exist_ok=True)
            fresh_path.write_text(json.dumps({"candidate_count": 9}), encoding="utf-8")

            since_epoch = time.time() - 60

            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_DATA_ROOT": str(data_root)},
                clear=False,
            ):
                response = self.client.get(
                    f"/api/ops/artifacts/export?since={since_epoch}",
                    headers={"Authorization": "Bearer secret-token"},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertNotIn(HOT_RELATIVE_PATH, payload["artifacts"])
            self.assertIn(fresh_relative, payload["artifacts"])


if __name__ == "__main__":
    unittest.main()
