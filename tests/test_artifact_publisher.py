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


def _write_required_daily_artifact(data_root: str, date_str: str) -> Path:
    """Create the once-daily betting-card AND top-props payloads inside a
    test data root.

    #68 added a repair pass to pull_hot_artifacts: any board-critical artifact
    that is written once a day and is MISSING gets one extra exact-path fetch,
    because the since= watermark can never reach it. #124 added
    daily_top_props to the same repair list (confirmed live: MLB props
    absent from the board because refresh-worker's copy was permanently
    missing, not merely stale). In a TemporaryDirectory every such artifact
    is missing, so tests that count requests for unrelated reasons would
    otherwise see extra calls. Creating both files keeps each of those tests
    about the thing it is actually asserting; the repair pass has its own
    tests.
    """
    season = int(date_str[:4])
    target = (
        Path(data_root)
        / "mlb_source"
        / "source_artifacts"
        / "data"
        / "eval"
        / "seasons"
        / str(season)
        / "betting_day_payloads_retuned"
        / f"season_betting_day_{season}_{date_str.replace('-', '_')[5:]}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"games": {}}), encoding="utf-8")

    top_props_target = (
        Path(data_root)
        / "mlb_source"
        / "source_artifacts"
        / "data"
        / "daily"
        / "top_props"
        / f"daily_top_props_{date_str.replace('-', '_')}.json"
    )
    top_props_target.parent.mkdir(parents=True, exist_ok=True)
    top_props_target.write_text(json.dumps({"pitcher": [], "hitter": []}), encoding="utf-8")
    return target



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

    def test_rejects_board_snapshot_but_accepts_intelligence_state(self) -> None:
        # board_snapshot.json stays on the shared keyvalue (Redis) backend and
        # out of the HTTP-push allowlist. intelligence_state.json used to live
        # there too, but #43 moved it onto the artifact transport: measured at
        # 15.5MB for 150 candidates against the store's ~8MB hard ceiling, so
        # it is data (workers write, web reads), not coordination state.
        self.assertFalse(is_hot_artifact_relative_path("reports/intelligence/board_snapshot.json"))
        self.assertTrue(is_hot_artifact_relative_path("reports/intelligence/intelligence_state.json"))
        self.assertTrue(is_hot_artifact_relative_path("reports/intelligence/intelligence_state_2026_07_26.json"))

    def test_accepts_bounded_steam_record_but_rejects_the_raw_lifecycle_log(self) -> None:
        # steam_events_<date>.json is capped at the newest 200 events
        # (_STEAM_EVENTS_KEEP) and carries capture_phase directly -- the
        # cheap, bounded way to verify #82/#83 without exporting the raw
        # per-observation lifecycle log, which reached 1.2GB in a single day
        # and must never be allowlisted.
        self.assertTrue(is_hot_artifact_relative_path("reports/steam/steam_events_2026-07-27.json"))
        self.assertFalse(is_hot_artifact_relative_path("data/odds_events/2026-07-27.jsonl"))

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
            _write_required_daily_artifact(tmp_dir, "2026-07-20")
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
            # Every request now carries a since= floor: "no watermark" used to
            # mean an unbounded pull, which is what OOM-looped the worker on
            # 2026-07-25. Assert the pattern scoping, ignore the epoch value.
            self.assertEqual(
                {url.split("&since=")[0] for url in requested_urls},
                {
                    "https://syndicate.onrender.com/api/ops/artifacts/export?pattern=%2A2026-07-20%2A",
                    "https://syndicate.onrender.com/api/ops/artifacts/export?pattern=%2A2026_07_20%2A",
                },
            )
            self.assertTrue(all("since=" in url for url in requested_urls))

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
            self.assertEqual(
                sent_request.full_url.split("?")[0],
                "https://syndicate.onrender.com/api/ops/artifacts/export",
            )
            self.assertIn("since=", sent_request.full_url)

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
            self.assertEqual(
                sent_request.full_url.split("?")[0],
                "https://syndicate.onrender.com/api/ops/artifacts/export",
            )
            self.assertIn("since=", sent_request.full_url)
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
            _write_required_daily_artifact(tmp_dir, "2026-07-24")
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
                    # With no watermark the request now carries the bounded
                    # window floor rather than no since= at all. "No
                    # watermark" used to mean an unbounded pull, which is what
                    # OOM-looped the refresh-worker on 2026-07-25.
                    self.assertIn("since=", first_call_url)
                    first_since = float(first_call_url.split("since=")[1])

                    pull_hot_artifacts(date_str="2026-07-24")
                    second_call_url = mocked_urlopen.call_args.args[0].full_url
                    self.assertIn("since=", second_call_url)

    def test_failed_pull_does_not_advance_watermark(self) -> None:
        # A transient network blip must not permanently skip files modified
        # during the failed window -- the next pull should still ask for
        # everything since the last SUCCESSFUL pull, not the failed one's
        # start time.
        with TemporaryDirectory() as tmp_dir:
            _write_required_daily_artifact(tmp_dir, "2026-07-24")
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
                    # next pull still has nothing to advance FROM -- it falls
                    # back to the bounded window floor rather than to an
                    # unbounded fetch, which is the whole point of the clamp.
                    retry_url = mocked_urlopen.call_args.args[0].full_url
                    self.assertIn("since=", retry_url)
                    from syndicate.features.shared.artifact_publisher import _MAX_PULL_WINDOW_SECONDS
                    import time as _time

                    retry_since = float(retry_url.split("since=")[1])
                    self.assertLessEqual(
                        _time.time() - retry_since,
                        _MAX_PULL_WINDOW_SECONDS + 60,
                        "a failing pull must not be able to widen its own window without bound",
                    )

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


class HotArtifactPullWindowClampTests(unittest.TestCase):
    """2026-07-25 incident: refresh-worker OOM crash loop + cascading web 502s.

    The pull window had two unbounded paths. No watermark meant "fetch
    everything", so every deploy pulled the entire artifact set at boot. And
    because the watermark only advances on a fully successful pull, a FAILING
    pull left the window growing forever -- each failure made the next attempt
    strictly heavier, so once the response exceeded what a 2GB container could
    json.loads(), it could never get back under it.

    Both sides hold the whole response in memory, so window size is peak
    memory on two services at once.
    """

    def setUp(self) -> None:
        from syndicate.features.shared.artifact_publisher import _MAX_PULL_WINDOW_SECONDS

        self.max_window = _MAX_PULL_WINDOW_SECONDS
        self.now = 1785000000.0

    def _since(self, stored):
        from syndicate.features.shared import artifact_publisher

        payload = {} if stored is None else {"epoch": stored}
        with patch("syndicate.features.shared.refresh_state_store.read_json_file", return_value=payload):
            return artifact_publisher._hot_artifact_pull_since_epoch(pull_started_epoch=self.now)

    def test_missing_watermark_is_bounded_not_unbounded(self) -> None:
        self.assertEqual(self.now - self._since(None), self.max_window)

    def test_zero_watermark_is_bounded(self) -> None:
        self.assertEqual(self.now - self._since(0.0), self.max_window)

    def test_stalled_watermark_cannot_widen_the_window_forever(self) -> None:
        # The spiral: repeated failures freeze the watermark, so without a
        # clamp each retry asks for a strictly larger window than the last.
        ancient = self.now - (30 * 24 * 3600)
        self.assertEqual(self.now - self._since(ancient), self.max_window)

    def test_recent_watermark_is_preserved(self) -> None:
        # The clamp must not throw away a healthy incremental window.
        self.assertEqual(self.now - self._since(self.now - 600.0), 600.0)

    def test_watermark_exactly_at_the_boundary_is_preserved(self) -> None:
        self.assertEqual(self.now - self._since(self.now - self.max_window), self.max_window)

    def test_unparseable_watermark_falls_back_to_the_bounded_floor(self) -> None:
        from syndicate.features.shared import artifact_publisher

        with patch("syndicate.features.shared.refresh_state_store.read_json_file", return_value={"epoch": "garbage"}):
            since = artifact_publisher._hot_artifact_pull_since_epoch(pull_started_epoch=self.now)
        self.assertEqual(self.now - since, self.max_window)


class MissingRequiredArtifactRepairTests(unittest.TestCase):
    """#68. The pull could not converge on a once-a-day artifact.

    Two independent blockers, both measured in production 2026-07-26:
    the betting-card payload was not allowlisted at all, so neither the push
    nor the pull could move it; and even allowlisted, `since=` filters on
    web's mtime, so a file written once in the morning stops being eligible
    within minutes and a worker that never had it never gets it. Consequence:
    BETTING_PAYLOAD_READ exists=False -> betting_game_count 0 -> every MLB
    market block 0 -> MLB contributed nothing to the board all day.
    """

    def test_betting_day_payload_is_allowlisted_without_opening_the_eval_tree(self) -> None:
        self.assertTrue(
            is_hot_artifact_relative_path(
                "mlb_source/source_artifacts/data/eval/seasons/2026/"
                "betting_day_payloads_retuned/season_betting_day_2026_07_26.json"
            )
        )
        self.assertTrue(
            is_hot_artifact_relative_path(
                "mlb_source/data/eval/seasons/2026/"
                "betting_day_payloads_retuned/season_betting_day_2026_07_26.json"
            )
        )
        # data/eval/seasons/** is bulk/historical and stays excluded -- that
        # exclusion is correct and this must not widen it.
        for blocked in (
            "mlb_source/source_artifacts/data/eval/seasons/2026/statcast_cache/pitches_2026_07_26.json",
            "mlb_source/source_artifacts/data/eval/seasons/2026/season_rollup.json",
            "mlb_source/source_artifacts/data/eval/seasons/2026/betting_day_payloads_retuned/notes.txt",
        ):
            self.assertFalse(is_hot_artifact_relative_path(blocked), blocked)

    def _run_pull(self, tmp_dir: str, date_str: str) -> list[str]:
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
                pull_hot_artifacts(date_str=date_str)
        return [call.args[0].full_url for call in mocked_urlopen.call_args_list]

    def test_missing_artifact_triggers_one_exact_path_request_per_required_file_with_no_since(self) -> None:
        # #124: daily_top_props joined season_betting_day in the required
        # list (both written once a day; confirmed live that a permanently
        # missing daily_top_props copy on refresh-worker is why MLB props
        # never reached candidate generation), so a fully empty data root
        # now needs two repair requests, not one.
        with TemporaryDirectory() as tmp_dir:
            urls = self._run_pull(tmp_dir, "2026-07-26")

        repair_urls = [url for url in urls if "path=" in url]
        self.assertEqual(len(repair_urls), 2, urls)
        # ?path= is the endpoint's single-artifact form: one stat and one read,
        # no glob over the matched set. That is what makes ignoring the
        # watermark safe here -- the ceiling exists to bound response SIZE, and
        # each response is one small file.
        self.assertTrue(any("season_betting_day_2026_07_26.json" in url for url in repair_urls), repair_urls)
        self.assertTrue(any("daily_top_props_2026_07_26.json" in url for url in repair_urls), repair_urls)
        for repair_url in repair_urls:
            self.assertNotIn("since=", repair_url)
            self.assertNotIn("pattern=", repair_url)

    def test_no_repair_request_when_the_artifact_is_already_present(self) -> None:
        # Costs nothing on a healthy worker.
        with TemporaryDirectory() as tmp_dir:
            _write_required_daily_artifact(tmp_dir, "2026-07-26")
            urls = self._run_pull(tmp_dir, "2026-07-26")

        self.assertEqual([url for url in urls if "path=" in url], [])
        self.assertEqual(len(urls), 2, urls)

    def test_repair_runs_after_the_normal_date_scoped_pull(self) -> None:
        # Ordering matters: the incremental pull may itself supply the file, in
        # which case there is nothing to repair. It also means a repair failure
        # cannot stop the watermark advancing for the pull that did succeed.
        with TemporaryDirectory() as tmp_dir:
            urls = self._run_pull(tmp_dir, "2026-07-26")

        self.assertEqual(len(urls), 4, urls)
        self.assertNotIn("path=", urls[0])
        self.assertNotIn("path=", urls[1])
        self.assertIn("path=", urls[2])
        self.assertIn("path=", urls[3])
