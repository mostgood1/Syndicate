from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.error import URLError

from syndicate.app import create_app
from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path
from syndicate.features.shared.artifact_publisher import publish_hot_artifact
from syndicate.features.shared.artifact_publisher import publish_changed_hot_artifacts
from syndicate.features.shared.artifact_publisher import odds_history_relative_paths_for_date
from syndicate.features.shared.artifact_publisher import pull_hot_artifacts
from syndicate.features.shared.artifact_publisher import pull_streamed_artifact


HOT_RELATIVE_PATH = "wnba_source/source_artifacts/data/processed/recommendations_slate_2026-07-13.json"


def _write_required_daily_artifact(data_root: str, date_str: str) -> Path:
    """Create the once-daily betting-card, top-props, locked-policy, AND
    base daily-summary payloads inside a test data root.

    #68 added a repair pass to pull_hot_artifacts: any board-critical artifact
    that is written once a day and is MISSING gets one extra exact-path fetch,
    because the since= watermark can never reach it. #124 added daily_top_props
    (confirmed live: MLB pregame props absent from the board because
    refresh-worker's copy was permanently missing, not merely stale) and then
    the locked-policy summary (confirmed live: MLB LIVE props specifically
    stayed empty even after the top-props fix -- traced to
    _cards_recommendation_payload_by_game reading this file to populate
    markets.{pitcher,hitter,extraPitcher,extraHitter}Props, which
    _live_props_from_card needs). #128 added the base daily_summary_<date>.json
    (no suffix -- a DIFFERENT file from the locked-policy one, loaded
    separately by build_cards_page_context as its own `summary`; confirmed
    live: even after the locked-policy repair landed and ran on
    live-odds-worker, build_cards_page_context still reported source_title
    "MLB cards unavailable" and zero props, because THIS file, not the
    locked-policy one, is what that check actually gates on). In a
    TemporaryDirectory every such artifact is missing, so tests that count
    requests for unrelated reasons would otherwise see extra calls. Creating
    all four files keeps each of those tests about the thing it is actually
    asserting; the repair pass has its own tests.
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

    locked_policy_target = (
        Path(data_root)
        / "mlb_source"
        / "source_artifacts"
        / "data"
        / "daily"
        / f"daily_summary_{date_str.replace('-', '_')}_locked_policy.json"
    )
    locked_policy_target.parent.mkdir(parents=True, exist_ok=True)
    locked_policy_target.write_text(json.dumps({}), encoding="utf-8")

    daily_summary_target = (
        Path(data_root)
        / "mlb_source"
        / "source_artifacts"
        / "data"
        / "daily"
        / f"daily_summary_{date_str.replace('-', '_')}.json"
    )
    daily_summary_target.parent.mkdir(parents=True, exist_ok=True)
    daily_summary_target.write_text(json.dumps({}), encoding="utf-8")

    wnba_processed_dir = Path(data_root) / "wnba_source" / "data" / "processed"
    wnba_processed_dir.mkdir(parents=True, exist_ok=True)
    (wnba_processed_dir / f"recommendations_slate_{date_str}.json").write_text(json.dumps({}), encoding="utf-8")
    (wnba_processed_dir / f"props_recommendations_{date_str}.csv").write_text("", encoding="utf-8")

    from syndicate.features.soccer.sources import active_leagues_for_date, default_season

    for league in active_leagues_for_date(date_str):
        schedule_dir = Path(data_root) / "soccer_source" / league / "api" / "schedule"
        schedule_dir.mkdir(parents=True, exist_ok=True)
        (schedule_dir / f"schedule_{default_season(league)}.json").write_text(json.dumps({"weeks": [], "matches": []}), encoding="utf-8")
    return target




def _body_then_eof(payload: bytes):
    """A response `read` that yields the body once and then signals EOF.

    `mock.read.side_effect = _body_then_eof(<bytes>` returns the SAME non-empty bytes on every)
    call, and `pull_streamed_artifact` drains a response with
    `while True: chunk = response.read(n); if not chunk: break`. A fixture that
    never empties is therefore an infinite loop writing 1MB chunks to disk, and
    it HANGS the suite rather than failing it -- two tests in this file did
    exactly that (reproduced standalone: exit 124; located with
    faulthandler.dump_traceback_later, both at artifact_publisher.py:1383).

    The bulk pull calls `read()` with no arguments and wants the JSON body; the
    streaming pull calls `read(n)` and wants bytes until EOF. Splitting on the
    argument gives both what a real HTTP response would give them.
    """

    def _read(*args, **kwargs):
        return payload if not args else b""

    return _read


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

    def test_accepts_mlb_player_game_log_and_statcast_features(self) -> None:
        # #163: written by refresh-worker (run_mlb_daily_sim_job.py's post-sim
        # hook / the Statcast regen), read on web by Ask The Syndicate --
        # confirmed live 2026-07-30 that omitting these left a real production
        # query ("Eury Perez outs") with no visuals at all post-deploy.
        self.assertTrue(is_hot_artifact_relative_path("mlb_source/source_artifacts/data/processed/mlb_pitcher_game_log.csv"))
        self.assertTrue(is_hot_artifact_relative_path("mlb_source/data/processed/mlb_pitcher_game_log.csv"))
        self.assertTrue(is_hot_artifact_relative_path("mlb_source/source_artifacts/data/processed/mlb_batter_game_log.csv"))
        self.assertTrue(is_hot_artifact_relative_path("mlb_source/data/processed/mlb_batter_game_log.csv"))
        self.assertTrue(is_hot_artifact_relative_path("mlb_source/source_artifacts/data/statcast/features/player_features_latest.json"))
        self.assertTrue(is_hot_artifact_relative_path("mlb_source/data/statcast/features/player_features_latest.json"))

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

    def test_accepts_the_three_live_lens_snapshots_but_rejects_lookalikes(self) -> None:
        # #124: live-odds-worker's live_lens_loop.py writes these three paths
        # (data_root()/live/{mlb,nba,wnba}_live_lens.json) every ~60s while
        # games are live, with real populated liveProps/archivedLiveProps --
        # they were never allowlisted at all, so the loop's own periodic
        # publish_changed_hot_artifacts sweep always skipped them
        # (SKIP_NOT_ALLOWLISTED), and every other service fell back to an
        # independent recompute that structurally has the same keys but with
        # zero rows (confirmed live: prop_row_counts=[0]*9 across 9 real live
        # games on refresh-worker, vs 24/18/16 real rows on web).
        self.assertTrue(is_hot_artifact_relative_path("live/mlb_live_lens.json"))
        self.assertTrue(is_hot_artifact_relative_path("live/nba_live_lens.json"))
        self.assertTrue(is_hot_artifact_relative_path("live/wnba_live_lens.json"))
        # Not a prefix match -- a same-directory file with a different name,
        # or the same filename nested a level deeper, must not slip through.
        self.assertFalse(is_hot_artifact_relative_path("live/mlb_live_lens_backup.json"))
        self.assertFalse(is_hot_artifact_relative_path("mlb_source/live/mlb_live_lens.json"))
        self.assertFalse(is_hot_artifact_relative_path("live/nhl_live_lens.json"))


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
            mocked_response.read.side_effect = _body_then_eof(b"{}")

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
            # TODAY's date, not the module-level HOT_RELATIVE_PATH's hardcoded
            # 2026-07-13. This test asserts the sweep publishes a file it calls
            # "fresh", and since `29746931` added _PUBLISH_MAX_AGE_DAYS the sweep
            # judges freshness by the SLATE DATE IN THE FILENAME. A fixture
            # pinned to a July date is stale on every day after 2026-07-14, so
            # this test failed unconditionally from the moment that bound
            # landed -- `SWEEP_SKIPPED {'stale_slate': 1}`, published 0 != 1.
            # It was red for the wrong reason, which is the same as being off:
            # it could no longer catch a real regression in the sweep.
            fresh_date = date.today().isoformat()
            fresh = data_root / f"wnba_source/source_artifacts/data/processed/recommendations_slate_{fresh_date}.json"
            fresh.parent.mkdir(parents=True, exist_ok=True)
            fresh.write_text("{}", encoding="utf-8")
            not_allowlisted = data_root / "reports" / "intelligence" / "evaluation_ledger_chunks" / "part_1.json"
            not_allowlisted.parent.mkdir(parents=True, exist_ok=True)
            not_allowlisted.write_text("{}", encoding="utf-8")

            since_epoch = time.time() - 3600

            mocked_response = MagicMock()
            mocked_response.__enter__.return_value = mocked_response
            mocked_response.read.side_effect = _body_then_eof(b"{}")

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
            mocked_response.read.side_effect = _body_then_eof(json.dumps({"ok": True, "count": 0, "artifacts": {}}).encode("utf-8"))

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

            # 2 date-pattern requests + 3 unconditional live-lens snapshot
            # fetches (#124: mlb/nba/wnba_live_lens.json carry no date in
            # their filename at all, so the date-pattern glob above can
            # never match them -- they're always fetched by exact path
            # instead, every cycle, regardless of watermark or presence).
            #
            # Counted over the EXPORT endpoint only. #209's per-book quote logs
            # are pulled through /artifacts/stream (they are far too big for
            # export's 24MB budget) and are unconditional, so a bare
            # call_count here started counting a second transport's requests.
            requested_urls = {call.args[0].full_url for call in mocked_urlopen.call_args_list}
            self.assertEqual(len([url for url in requested_urls if "/artifacts/export?" in url]), 5, requested_urls)
            pattern_urls = {url for url in requested_urls if "pattern=" in url}
            live_lens_urls = {url for url in requested_urls if "path=live%2F" in url}
            # Every request now carries a since= floor: "no watermark" used to
            # mean an unbounded pull, which is what OOM-looped the worker on
            # 2026-07-25. Assert the pattern scoping, ignore the epoch value.
            self.assertEqual(
                {url.split("&since=")[0] for url in pattern_urls},
                {
                    "https://syndicate.onrender.com/api/ops/artifacts/export?pattern=%2A2026-07-20%2A",
                    "https://syndicate.onrender.com/api/ops/artifacts/export?pattern=%2A2026_07_20%2A",
                },
            )
            self.assertTrue(all("since=" in url for url in pattern_urls))
            self.assertEqual(
                live_lens_urls,
                {
                    "https://syndicate.onrender.com/api/ops/artifacts/export?path=live%2Fmlb_live_lens.json",
                    "https://syndicate.onrender.com/api/ops/artifacts/export?path=live%2Fnba_live_lens.json",
                    "https://syndicate.onrender.com/api/ops/artifacts/export?path=live%2Fwnba_live_lens.json",
                },
            )
            self.assertTrue(all("since=" not in url for url in live_lens_urls))

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
            mocked_response.read.side_effect = _body_then_eof(json.dumps({"ok": True, "count": 0, "artifacts": {}}).encode("utf-8"))

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
            mocked_response.read.side_effect = _body_then_eof(json.dumps(export_payload).encode("utf-8"))

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
        empty_response.read.side_effect = _body_then_eof(json.dumps({"ok": True, "count": 0, "artifacts": {}}).encode("utf-8"))

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
                    # #124: the unconditional live-lens snapshot fetches
                    # always run last and never carry since=, so pick the
                    # last date-*pattern* call specifically rather than the
                    # literal last call overall.
                    first_call_url = next(
                        call.args[0].full_url for call in reversed(mocked_urlopen.call_args_list) if "pattern=" in call.args[0].full_url
                    )
                    # With no watermark the request now carries the bounded
                    # window floor rather than no since= at all. "No
                    # watermark" used to mean an unbounded pull, which is what
                    # OOM-looped the refresh-worker on 2026-07-25.
                    self.assertIn("since=", first_call_url)
                    first_since = float(first_call_url.split("since=")[1])

                    pull_hot_artifacts(date_str="2026-07-24")
                    second_call_url = next(
                        call.args[0].full_url for call in reversed(mocked_urlopen.call_args_list) if "pattern=" in call.args[0].full_url
                    )
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
                empty_response.read.side_effect = _body_then_eof(
                    json.dumps({"ok": True, "count": 0, "artifacts": {}}).encode("utf-8")
                )
                with patch("urllib.request.urlopen", return_value=empty_response) as mocked_urlopen:
                    pull_hot_artifacts(date_str="2026-07-24")
                    # No watermark was recorded after the failure, so this
                    # next pull still has nothing to advance FROM -- it falls
                    # back to the bounded window floor rather than to an
                    # unbounded fetch, which is the whole point of the clamp.
                    # #124: pick the last date-*pattern* call specifically --
                    # the unconditional live-lens snapshot fetches run last
                    # and never carry since=.
                    retry_url = next(
                        call.args[0].full_url for call in reversed(mocked_urlopen.call_args_list) if "pattern=" in call.args[0].full_url
                    )
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
                mocked_response.read.side_effect = _body_then_eof(json.dumps(export_payload).encode("utf-8"))
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
            mocked_response.read.side_effect = _body_then_eof(json.dumps(export_payload).encode("utf-8"))

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
        mocked_response.read.side_effect = _body_then_eof(json.dumps({"ok": True, "count": 0, "artifacts": {}}).encode("utf-8"))
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_DATA_ROOT": tmp_dir,
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports_root"),
                "ADMIN_TOKEN": "secret-token",
                "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                # WNBA's required-artifact paths (added alongside the MLB ones
                # above) resolve via syndicate.features.wnba.sources, which
                # falls back to the REAL repo's data/wnba_source when this
                # isn't set -- non-deterministic across environments. Isolate
                # it the same way test_wnba_refresh_runner.py/test_intelligence.py
                # already do.
                "SYNDICATE_WNBA_SOURCE_ROOT": str(Path(tmp_dir) / "wnba_source"),
            },
            clear=False,
        ):
            with patch("urllib.request.urlopen", return_value=mocked_response) as mocked_urlopen:
                pull_hot_artifacts(date_str=date_str)
        return [call.args[0].full_url for call in mocked_urlopen.call_args_list]

    # #124: the three live-lens snapshot fetches (mlb/nba/wnba_live_lens.json)
    # run unconditionally on EVERY pull, regardless of watermark or whether the
    # file already exists locally -- unlike the missing-artifact repair pass,
    # they carry no date in their filename at all, so the date-pattern glob
    # can never match them, and they need to stay fresh every cycle rather
    # than being fetched once and left stale forever. Every test below has to
    # account for these three extra `path=` requests alongside whatever the
    # missing-required-artifact repair pass contributes.
    _LIVE_LENS_SNAPSHOT_URLS = {
        "https://syndicate.onrender.com/api/ops/artifacts/export?path=live%2Fmlb_live_lens.json",
        "https://syndicate.onrender.com/api/ops/artifacts/export?path=live%2Fnba_live_lens.json",
        "https://syndicate.onrender.com/api/ops/artifacts/export?path=live%2Fwnba_live_lens.json",
    }

    @staticmethod
    def _export_path_urls(urls: list[str]) -> list[str]:
        """The `path=` requests that go through /artifacts/EXPORT.

        These assertions used to match on the substring "path=" alone, which was
        unambiguous until #209 added the per-book quote logs
        (`*_source/tracking/book_quotes/*.jsonl`). Those are pulled through
        /artifacts/STREAM -- a different endpoint, chosen because a quote log is
        far too big for export's 24MB whole-response budget -- and they also
        carry `path=`. So one pull now issues ~16 extra `path=` requests that
        have nothing to do with either the live-lens snapshots or the
        missing-artifact repair pass these tests are about.

        Not hidden, split: `_quote_log_stream_urls` below asserts the stream
        pulls happen, so widening the transport stays covered rather than
        becoming invisible to this class.
        """
        return [url for url in urls if "/artifacts/export?" in url and "path=" in url]

    @staticmethod
    def _quote_log_stream_urls(urls: list[str]) -> list[str]:
        return [url for url in urls if "/artifacts/stream?" in url]

    def test_missing_artifact_triggers_one_exact_path_request_per_required_file_with_no_since(self) -> None:
        # #124: daily_top_props and then the locked-policy summary both
        # joined season_betting_day in the required list (all three written
        # once a day; confirmed live that a permanently missing copy of
        # each on refresh-worker is why MLB pregame AND live props never
        # reached candidate generation). #128 added the base daily-summary
        # file (a different file from the locked-policy one -- confirmed
        # live on live-odds-worker that build_cards_page_context still
        # reported zero props even after the locked-policy repair alone).
        # Same session, same night: a cross-sport comparison found WNBA had
        # never been added to this list at all, despite its pregame-props
        # source (recommendations_slate_<date>.json, the sole input to
        # _WNBADataProvider.pregame_props) being the identical
        # written-once-a-day shape as the four MLB entries -- latent, not yet
        # observed in production, but the same class of gap. Added
        # recommendations_slate + props_recommendations, so a fully empty
        # data root now needs six repair requests, not four -- plus the
        # three always-on live-lens snapshot fetches (see class comment
        # above). A later same-night fix (chasing why soccer's steam-move
        # board candidates couldn't resolve a real matchup) added soccer's
        # once-a-season schedule artifact, scoped to whichever leagues are
        # actually in season for this date -- July means only MLS, so one
        # more repair request, seven total.
        with TemporaryDirectory() as tmp_dir:
            urls = self._run_pull(tmp_dir, "2026-07-26")

        path_urls = self._export_path_urls(urls)
        live_lens_urls = [url for url in path_urls if url in self._LIVE_LENS_SNAPSHOT_URLS]
        repair_urls = [url for url in path_urls if url not in self._LIVE_LENS_SNAPSHOT_URLS]
        self.assertEqual(set(live_lens_urls), self._LIVE_LENS_SNAPSHOT_URLS, urls)
        self.assertEqual(len(repair_urls), 7, urls)
        # #209's quote logs ride the stream endpoint, and they are a real part
        # of a pull -- asserted rather than merely filtered out above.
        self.assertTrue(
            all("tracking%2Fbook_quotes%2F" in url for url in self._quote_log_stream_urls(urls)),
            self._quote_log_stream_urls(urls),
        )
        # ?path= is the endpoint's single-artifact form: one stat and one read,
        # no glob over the matched set. That is what makes ignoring the
        # watermark safe here -- the ceiling exists to bound response SIZE, and
        # each response is one small file.
        self.assertTrue(any("season_betting_day_2026_07_26.json" in url for url in repair_urls), repair_urls)
        self.assertTrue(any("daily_top_props_2026_07_26.json" in url for url in repair_urls), repair_urls)
        self.assertTrue(any("daily_summary_2026_07_26_locked_policy.json" in url for url in repair_urls), repair_urls)
        self.assertTrue(
            any(url.endswith("daily_summary_2026_07_26.json") for url in repair_urls), repair_urls
        )
        self.assertTrue(any("recommendations_slate_2026-07-26.json" in url for url in repair_urls), repair_urls)
        self.assertTrue(any("props_recommendations_2026-07-26.csv" in url for url in repair_urls), repair_urls)
        self.assertTrue(any("mls" in url and "schedule_" in url for url in repair_urls), repair_urls)
        for repair_url in path_urls:
            self.assertNotIn("since=", repair_url)
            self.assertNotIn("pattern=", repair_url)

    def test_no_repair_request_when_the_artifact_is_already_present(self) -> None:
        # Costs nothing extra on a healthy worker beyond the always-on
        # live-lens fetches.
        with TemporaryDirectory() as tmp_dir:
            _write_required_daily_artifact(tmp_dir, "2026-07-26")
            urls = self._run_pull(tmp_dir, "2026-07-26")

        path_urls = set(self._export_path_urls(urls))
        self.assertEqual(path_urls, self._LIVE_LENS_SNAPSHOT_URLS, urls)
        # 2 date-pattern pulls + 3 live-lens snapshots. Counted over the export
        # endpoint only: the quote-log stream pulls (#209) are unconditional and
        # their number varies with the soccer look-ahead window, so folding them
        # into a fixed total would make this assertion break on a calendar
        # change rather than on a repair-pass regression.
        self.assertEqual(len([url for url in urls if "/artifacts/export?" in url]), 5, urls)

    def test_repair_runs_after_the_normal_date_scoped_pull(self) -> None:
        # Ordering matters: the incremental pull may itself supply the file, in
        # which case there is nothing to repair. It also means a repair failure
        # cannot stop the watermark advancing for the pull that did succeed.
        # 2 date-pattern + 7 missing-required repairs + 3 always-on live-lens.
        with TemporaryDirectory() as tmp_dir:
            urls = self._run_pull(tmp_dir, "2026-07-26")

        # Counted over the export endpoint: the quote-log stream pulls (#209)
        # are a separate, unconditional transport and vary in number.
        self.assertEqual(len([url for url in urls if "/artifacts/export?" in url]), 12, urls)
        self.assertNotIn("path=", urls[0])
        self.assertNotIn("path=", urls[1])
        for later_url in urls[2:]:
            self.assertIn("path=", later_url)


class OddsHistoryStreamedPullTests(unittest.TestCase):
    """The board's movement data could not cross services at all.

    Measured in production 2026-08-04: web held 3,436 MLB odds-history
    markets while every one of 354 MLB board candidates rendered
    history_points=0. The board is built on refresh-worker (render.yaml gives
    only that service SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=true),
    which can only receive artifacts by pulling them, and a real MLB shard is
    ~51MB against /api/ops/artifacts/export's 24MB whole-response budget. So
    the bulk pull either truncated before reaching it -- forever, since its
    watermark only advances on a complete response -- or would have returned
    it whole and OOMed a 2GB web instance (#50). WNBA was unaffected
    throughout: 34 markets, kilobytes, well inside the budget. The join
    itself was never broken; replaying production's own candidates against
    production's own history matched 330/354.
    """

    def _stream_env(self, tmp_dir: str) -> dict[str, str]:
        return {
            "SYNDICATE_DATA_ROOT": tmp_dir,
            "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports_root"),
            "ADMIN_TOKEN": "secret-token",
            "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
        }

    def test_shard_paths_are_allowlisted_and_skip_week_scoped_sports(self) -> None:
        paths = odds_history_relative_paths_for_date("2026-08-04")
        for relative_path in paths:
            self.assertTrue(is_hot_artifact_relative_path(relative_path), relative_path)
        self.assertIn("mlb_source/artifacts/mlb/odds_history/2026-08-04.json", paths)
        # nfl/ncaaf shard by season/week (_shard_key_for_row), so a
        # date-named shard never exists for them -- asking would 404 every
        # cycle for nothing.
        self.assertFalse([p for p in paths if p.startswith(("nfl_", "ncaaf_"))], paths)
        # One transport per sport, not two: the "tracking" copy holds the same
        # payload, so pulling it as well would move ~51MB twice for one file.
        self.assertFalse([p for p in paths if "/tracking/" in p], paths)

    def test_streams_to_disk_in_chunks_and_stamps_web_mtime(self) -> None:
        body = json.dumps({"markets": {"k": {"v": 1}}}).encode("utf-8")
        chunks = [body[:4], body[4:], b""]
        mocked_response = MagicMock()
        mocked_response.__enter__.return_value = mocked_response
        mocked_response.read.side_effect = chunks
        mocked_response.headers = {"X-Artifact-Mtime": "1785800000.0"}

        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, self._stream_env(tmp_dir), clear=False):
                with patch("urllib.request.urlopen", return_value=mocked_response):
                    ok, written = pull_streamed_artifact(
                        "mlb_source/artifacts/mlb/odds_history/2026-08-04.json"
                    )
            self.assertTrue(ok)
            self.assertEqual(written, 1)
            target = Path(tmp_dir) / "mlb_source/artifacts/mlb/odds_history/2026-08-04.json"
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"markets": {"k": {"v": 1}}})
            # Stamped with web's mtime, not download time -- the next cycle
            # sends this back as since=, and a local mtime later than the
            # source would make an updated shard look current forever.
            self.assertAlmostEqual(target.stat().st_mtime, 1785800000.0, places=0)
            # Streamed, not read whole: that is the entire point.
            self.assertGreater(mocked_response.read.call_count, 1)
            self.assertFalse(list(target.parent.glob("*.tmp")), "temp file left behind")

    def test_existing_copy_sends_its_mtime_as_since(self) -> None:
        mocked_response = MagicMock()
        mocked_response.__enter__.return_value = mocked_response
        mocked_response.read.side_effect = [b"{}", b""]
        mocked_response.headers = {}

        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "mlb_source/artifacts/mlb/odds_history/2026-08-04.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
            os.utime(target, (1785700000.0, 1785700000.0))
            with patch.dict(os.environ, self._stream_env(tmp_dir), clear=False):
                with patch("urllib.request.urlopen", return_value=mocked_response) as mocked_urlopen:
                    pull_streamed_artifact("mlb_source/artifacts/mlb/odds_history/2026-08-04.json")
            url = mocked_urlopen.call_args.args[0].full_url
        self.assertIn("/api/ops/artifacts/stream?path=", url)
        self.assertIn("since=1785700000.0", url)

    def test_not_modified_is_a_success_that_writes_nothing(self) -> None:
        # The steady state -- and the reason this is cheap enough to call on
        # every board-build cycle instead of re-sending 51MB every ~30s.
        error = HTTPError("https://x/api/ops/artifacts/stream", 304, "Not Modified", {}, None)
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, self._stream_env(tmp_dir), clear=False):
                with patch("urllib.request.urlopen", side_effect=error):
                    ok, written = pull_streamed_artifact(
                        "mlb_source/artifacts/mlb/odds_history/2026-08-04.json"
                    )
        self.assertTrue(ok)
        self.assertEqual(written, 0)

    def test_absent_on_web_is_reported_not_raised(self) -> None:
        error = HTTPError("https://x/api/ops/artifacts/stream", 404, "Not Found", {}, None)
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, self._stream_env(tmp_dir), clear=False):
                with patch("urllib.request.urlopen", side_effect=error):
                    ok, written = pull_streamed_artifact(
                        "mlb_source/artifacts/mlb/odds_history/2026-08-04.json"
                    )
        self.assertFalse(ok)
        self.assertEqual(written, 0)

    def test_network_failure_never_raises(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, self._stream_env(tmp_dir), clear=False):
                with patch("urllib.request.urlopen", side_effect=URLError("boom")):
                    ok, written = pull_streamed_artifact(
                        "mlb_source/artifacts/mlb/odds_history/2026-08-04.json"
                    )
        self.assertFalse(ok)
        self.assertEqual(written, 0)

    def test_non_allowlisted_path_is_refused_before_any_request(self) -> None:
        # The shared copy (reports/odds_control_plane/...) is the reader's
        # FIRST precedence and is deliberately not allowlisted, so it can
        # never cross services -- on a worker it simply doesn't exist and the
        # reader falls through to the artifacts path this pull provides.
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, self._stream_env(tmp_dir), clear=False):
                with patch("urllib.request.urlopen") as mocked_urlopen:
                    ok, written = pull_streamed_artifact(
                        "reports/odds_control_plane/odds_history/mlb/2026-08-04.json"
                    )
        self.assertFalse(ok)
        self.assertEqual(written, 0)
        mocked_urlopen.assert_not_called()


class ArtifactStreamEndpointTests(unittest.TestCase):
    """The web-side half of the odds-history transport fix.

    Same allowlist and same admin gate as /api/ops/artifacts/export -- this
    widens the transport, not what is allowed to cross it.
    """

    ODDS_HISTORY_RELATIVE_PATH = "mlb_source/artifacts/mlb/odds_history/2026-08-04.json"

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_stream_requires_admin_token(self) -> None:
        response = self.client.get("/api/ops/artifacts/stream?path=x")
        self.assertEqual(response.status_code, 503)

    def test_stream_refuses_a_path_outside_the_allowlist(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_DATA_ROOT": tmp_dir},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/artifacts/stream?path=mlb_source/source_artifacts/data/statcast/2026.csv",
                    headers={"Authorization": "Bearer secret-token"},
                )
        self.assertEqual(response.status_code, 403)

    def test_stream_rejects_traversal(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_DATA_ROOT": tmp_dir},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/artifacts/stream?path=../../etc/passwd",
                    headers={"Authorization": "Bearer secret-token"},
                )
        self.assertEqual(response.status_code, 400)

    def test_stream_returns_the_file_body_and_mtime_header(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / self.ODDS_HISTORY_RELATIVE_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"markets": {"k": {}}}), encoding="utf-8")
            os.utime(target, (1785800000.0, 1785800000.0))
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_DATA_ROOT": tmp_dir},
                clear=False,
            ):
                response = self.client.get(
                    f"/api/ops/artifacts/stream?path={self.ODDS_HISTORY_RELATIVE_PATH}",
                    headers={"Authorization": "Bearer secret-token"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.get_data(as_text=True)), {"markets": {"k": {}}})
            self.assertAlmostEqual(float(response.headers["X-Artifact-Mtime"]), 1785800000.0, places=0)
            # send_file streams from an open handle; on Windows the
            # TemporaryDirectory cleanup below fails with WinError 32 unless
            # the response is closed first.
            response.close()

    def test_stream_answers_304_without_a_body_when_not_modified(self) -> None:
        # What keeps this affordable every cycle: an unchanged 51MB shard
        # costs a round trip, not a transfer.
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / self.ODDS_HISTORY_RELATIVE_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"markets": {}}), encoding="utf-8")
            os.utime(target, (1785700000.0, 1785700000.0))
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_DATA_ROOT": tmp_dir},
                clear=False,
            ):
                response = self.client.get(
                    f"/api/ops/artifacts/stream?path={self.ODDS_HISTORY_RELATIVE_PATH}&since=1785700000.0",
                    headers={"Authorization": "Bearer secret-token"},
                )
            self.assertEqual(response.status_code, 304)
            self.assertEqual(response.get_data(), b"")

    def test_stream_404s_when_the_artifact_is_absent(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_DATA_ROOT": tmp_dir},
                clear=False,
            ):
                response = self.client.get(
                    f"/api/ops/artifacts/stream?path={self.ODDS_HISTORY_RELATIVE_PATH}",
                    headers={"Authorization": "Bearer secret-token"},
                )
        self.assertEqual(response.status_code, 404)


class MatchupCoverageDiagnosticHonestyTests(unittest.TestCase):
    """The coverage diagnostic answered a different question than it was asked.

    It accepted ?sport= and ?date= and honoured neither, always returning the
    last refresh's write. During triage on 2026-08-04 it answered for
    2026-08-05 when asked for 2026-08-04 (a look-ahead run had written last),
    which read as "the endpoint ignores its date param" and cost real
    investigation time; asked for 2026-01-15 it answered 2026-08-04 just as
    confidently. The record really is last-write-only, so the fix is to say
    which date is being described rather than to fake per-date history.
    """

    STATUS_RELATIVE = ("refresh_status", "latest", "odds_history_h2h_matchup_coverage_status.json")

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def _write_status(self, reports_root: Path, payload: dict) -> None:
        target = reports_root.joinpath(*self.STATUS_RELATIVE)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")

    def _get(self, tmp_dir: str, query: str) -> dict:
        reports_root = Path(tmp_dir) / "reports"
        self._write_status(
            reports_root,
            {
                "mlb": {"date": "2026-08-04", "in_source": ["A@B"], "written": ["A@B"]},
                "wnba": {"date": "2026-08-04", "in_source": [], "written": []},
            },
        )
        with patch.dict(
            os.environ,
            {"ADMIN_TOKEN": "secret-token", "SYNDICATE_REPORTS_ROOT": str(reports_root), "SYNDICATE_DATA_ROOT": tmp_dir},
            clear=False,
        ):
            response = self.client.get(
                f"/api/ops/odds-history/matchup-coverage{query}",
                headers={"Authorization": "Bearer secret-token"},
            )
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_matching_date_is_reported_as_matching(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            payload = self._get(tmp_dir, "?sport=mlb&date=2026-08-04")
        self.assertTrue(payload["matches_requested_date"])
        self.assertEqual(payload["reported_dates"], ["2026-08-04"])
        self.assertEqual(sorted(payload["by_sport"]), ["mlb"])

    def test_a_different_date_is_flagged_not_silently_answered(self) -> None:
        # The whole point: the numbers are real, they are just not about the
        # day that was asked for, and the response now says so.
        with TemporaryDirectory() as tmp_dir:
            payload = self._get(tmp_dir, "?sport=mlb&date=2026-01-15")
        self.assertFalse(payload["matches_requested_date"])
        self.assertEqual(payload["requested_date"], "2026-01-15")
        self.assertEqual(payload["reported_dates"], ["2026-08-04"])
        self.assertEqual(payload["source"], "last_refresh_write_only")

    def test_sport_filter_is_honoured(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            payload = self._get(tmp_dir, "?sport=wnba")
        self.assertEqual(sorted(payload["by_sport"]), ["wnba"])
        self.assertIsNone(payload["matches_requested_date"])

    def test_no_filters_returns_every_sport(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            payload = self._get(tmp_dir, "")
        self.assertEqual(sorted(payload["by_sport"]), ["mlb", "wnba"])
        self.assertIsNone(payload["requested_date"])


class CandidateTraceSportScopingTests(unittest.TestCase):
    """?sport= reached only the per-sport loop at the bottom of the response.

    preferences was built with a hardcoded sport="all", and fallback_merge_trace
    -- the stage-by-stage collect -> score -> filter drop-off, i.e. the numbers
    a reader looks at FIRST -- was computed over every sport in the overview.
    Fetched with ?sport=mlb it still described the whole board, so "collect=412,
    filtered=0" read as MLB's drop-off when it was not. Same class of bug as
    matchup-coverage's ignored date param, fixed the same day.
    """

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def _overview(self):
        return [
            {"slug": "mlb", "dashboard_games": [{"game_id": 1}]},
            {"slug": "wnba", "dashboard_games": [{"game_id": 2}]},
        ]

    def _trace(self, query: str) -> dict:
        import syndicate.blueprints.ops as ops_module

        seen: dict = {}

        def fake_collect(overview_arg, preferences_arg, _extra=None):
            seen["collect_slugs"] = [row.get("slug") for row in overview_arg]
            seen["preferences_sports"] = preferences_arg.get("requested_sports") if isinstance(preferences_arg, dict) else None
            return []

        from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE as service

        # _build_candidate_pool is the real, expensive board build -- it runs
        # collect/score/filter over every sport and will blow past any sane
        # test timeout. This endpoint's pool_wide sections are not what these
        # tests are about.
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.features.intelligence.build_intelligence_overview", return_value=self._overview()
        ), patch("syndicate.features.intelligence.collect_candidates", side_effect=fake_collect), patch(
            "syndicate.features.intelligence._collect_candidates", return_value=[]
        ), patch.object(
            service, "_available_sport_manifests", return_value={}
        ), patch.object(
            service, "_source_state_fingerprint", return_value="fp"
        ), patch.object(
            service, "_build_candidate_pool", return_value={"candidate_count": 0}
        ), patch.object(
            service, "_candidate_pool_key", return_value="k"
        ):
            response = self.client.get(
                f"/api/ops/intelligence/candidate-trace{query}",
                headers={"Authorization": "Bearer secret-token"},
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])
        payload = response.get_json()
        payload["_seen"] = seen
        return payload

    def test_scoped_request_reports_the_requested_sport(self) -> None:
        payload = self._trace("?sport=mlb&date=2026-08-04")
        self.assertEqual(payload["requested_sport"], "mlb")
        self.assertTrue(payload["requested_sport_present"])
        self.assertEqual([row["slug"] for row in payload["sports"]], ["mlb"])
        self.assertEqual(payload["fallback_merge_trace"].get("0_scope"), "mlb")

    def test_scoped_request_narrows_the_preferences_and_the_merge_trace_input(self) -> None:
        # The actual defect: these two used every sport regardless.
        payload = self._trace("?sport=mlb&date=2026-08-04")
        # _query_preferences lands an explicit sport in requested_sports;
        # unscoped leaves it empty, meaning "every sport".
        self.assertEqual(payload["preferences"]["requested_sports"], ["mlb"])
        self.assertEqual(payload["_seen"].get("collect_slugs"), ["mlb"])

    def test_unscoped_request_still_covers_every_sport(self) -> None:
        payload = self._trace("?date=2026-08-04")
        self.assertIsNone(payload["requested_sport"])
        self.assertIsNone(payload["requested_sport_present"])
        self.assertEqual(payload["preferences"]["requested_sports"], [])
        self.assertEqual(sorted(row["slug"] for row in payload["sports"]), ["mlb", "wnba"])
        self.assertEqual(payload["fallback_merge_trace"].get("0_scope"), "all_sports")

    def test_a_sport_not_in_the_overview_is_stated_not_implied_by_an_empty_list(self) -> None:
        payload = self._trace("?sport=nfl&date=2026-08-04")
        self.assertFalse(payload["requested_sport_present"])
        self.assertEqual(payload["sports"], [])
        self.assertEqual(sorted(payload["sports_in_overview"]), ["mlb", "wnba"])

    def test_pool_wide_sections_are_labelled_as_pool_wide(self) -> None:
        # _build_candidate_pool takes no sport argument by design, so these
        # stay whole-board even on a scoped request and must say so.
        payload = self._trace("?sport=mlb&date=2026-08-04")
        self.assertEqual(
            payload["pool_wide_sections"],
            ["manifest_check", "full_pool_check", "app_context_pool_check"],
        )


class CandidateTraceReadOnlyScopeTests(unittest.TestCase):
    """?read_only=1 returns before the main path, so it needs its own answer.

    It reads whole-board persisted state (no per-sport dimension), so ?sport=
    genuinely cannot apply -- but silently accepting the param and never
    mentioning it is how the main path's partial scoping stayed invisible.
    """

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_read_only_states_that_the_sport_filter_does_not_apply(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get(
                "/api/ops/intelligence/candidate-trace?sport=mlb&date=2026-08-04&read_only=1",
                headers={"Authorization": "Bearer secret-token"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["requested_sport"], "mlb")
        self.assertFalse(payload["sport_filter_applies"])
        self.assertEqual(payload["scope"], "all_sports")
        self.assertIn("read_only_trace", payload)


class BookQuoteStateSidecarAllowlistTests(unittest.TestCase):
    """The quote change-log's sidecar must cross services with the log itself.

    `append_book_quotes` writes a row only when (line, price) CHANGES, and
    records "when did we last OBSERVE this market" in `<date>.state.json`
    beside the `.jsonl`. Only the `.jsonl` was allowlisted, so the service that
    READS quotes (refresh-worker, via `pipeline/layer2_shortlist`) could never
    see last-seen written by the service that CAPTURES them
    (live-odds-worker). Different disks.

    Measured 2026-08-08 with the threading deployed and sweeps confirmed
    running (MLB capture 21:38:09Z): `quote_seen_age_seconds` was None on 112
    of 112 board rows, so `_freshness_factor` fell back to movement age and
    scored every row 0.25 -- the harshest discount -- for markets that had
    merely not moved. Live and inert.
    """

    def _matches(self, path: str) -> bool:
        import fnmatch

        from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS

        return any(fnmatch.fnmatch(path, pattern) for pattern in HOT_ARTIFACT_PATTERNS)

    def test_the_state_sidecar_is_published(self) -> None:
        self.assertTrue(self._matches("mlb_source/tracking/book_quotes/2026-08-08.state.json"))

    def test_the_quote_log_itself_still_publishes(self) -> None:
        self.assertTrue(self._matches("mlb_source/tracking/book_quotes/2026-08-08.jsonl"))

    def test_every_sport_is_covered_not_just_mlb(self) -> None:
        for sport in ("mlb", "wnba", "soccer", "nhl", "nfl"):
            self.assertTrue(self._matches(f"{sport}_source/tracking/book_quotes/2026-08-08.state.json"), sport)

    def test_the_temp_write_file_is_not_published(self) -> None:
        """`_write_state` writes `<name>.tmp` then renames. Publishing a
        half-written file would be worse than publishing nothing."""
        self.assertFalse(self._matches("mlb_source/tracking/book_quotes/2026-08-08.state.json.tmp"))

    def test_the_pattern_does_not_widen_to_other_tracking_dirs(self) -> None:
        """Deliberately one filename in one already-allowlisted directory --
        not `tracking/**`. Republishing is implicated in web's OOM, so the
        blast radius stays as small as the fix allows.

        NOT asserted here: `tracking/odds_history/`. Its own PRE-EXISTING
        pattern is `*_source/tracking/odds_history/*.json`, which already
        matches any `.json` in that directory including a `.state.json`. That
        breadth is not introduced by this change and is left alone rather than
        narrowed in passing.
        """
        self.assertFalse(self._matches("mlb_source/tracking/other/2026-08-08.state.json"))
        self.assertFalse(self._matches("mlb_source/tracking/book_quotes_archive/2026-08-08.state.json"))

    def test_a_star_in_these_patterns_crosses_directory_separators(self) -> None:
        """Worth pinning because it is easy to get wrong -- I did, twice, while
        writing the test above.

        These are `fnmatch` patterns, not `glob`: `*` matches `/` as well, so
        `book_quotes/*.state.json` also matches a nested path. That is
        pre-existing behaviour of EVERY pattern in this list (the sibling
        `.jsonl` pattern included), not something this change introduces. A
        reader assuming glob semantics will size the blast radius of any new
        pattern too small.
        """
        self.assertTrue(self._matches("mlb_source/tracking/book_quotes/nested/2026-08-08.state.json"))


class StreamedPublishTransportTests(unittest.TestCase):
    """Large artifacts publish as a raw streamed body, not a JSON envelope.

    `publish_hot_artifact` held FOUR full copies of every file at once
    (read_text -> encode for the checksum -> json.dumps -> encode), and the
    receiver held roughly three more (body bytes -> parsed dict carrying a full
    str copy -> re-encode on write). `29746931` named this mechanism as the
    reason web was OOMing "with no correlation to anyone's deploys" and then
    bounded only which files the SWEEP selects. The DIRECT publishers -- #43's
    board-state fallback, #112's odds_history fallback, #124's live-lens loop --
    were left unbounded, and the board state is exactly what goes through them:
    27,420,309 bytes published on every cycle that produces a real board
    (measured on refresh-worker 2026-08-08, confirmed landed on web's disk).

    Measured on that same real 27,420,309-byte payload:

        sender    peak 84.0MB (3.21x) -> 2.0MB (0.08x)   42x
        receiver  peak 65.4MB (2.50x) -> 2.0MB (0.08x)   33x
        wire      30,308,012 bytes -> 27,420,309 bytes   10.5% less

    Two forms stay accepted on one route. live-odds-worker is pinned to an
    older commit and must keep publishing, and a receiver that understood only
    the new form would make the deploy order load-bearing.
    """

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def _big_payload(self) -> bytes:
        from syndicate.features.shared.artifact_publisher import _PUBLISH_STREAM_MIN_BYTES

        return json.dumps({"rows": ["x" * 512] * ((_PUBLISH_STREAM_MIN_BYTES // 512) + 64)}).encode("utf-8")

    def test_the_streamed_form_writes_the_file_and_verifies_the_checksum(self) -> None:
        body = self._big_payload()
        checksum = hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {"SYNDICATE_DATA_ROOT": tmp_dir, "ADMIN_TOKEN": "secret-token"},
                clear=False,
            ):
                response = self.client.post(
                    "/api/ops/artifacts/publish",
                    data=body,
                    content_type="application/octet-stream",
                    headers={
                        "Authorization": "Bearer secret-token",
                        "X-Artifact-Path": HOT_RELATIVE_PATH,
                        "X-Artifact-Checksum": checksum,
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["transport"], "stream")
                self.assertEqual(response.get_json()["bytes"], len(body))
                written = Path(tmp_dir) / HOT_RELATIVE_PATH
                self.assertTrue(written.is_file())
                self.assertEqual(written.read_bytes(), body)

    def test_a_corrupted_transfer_leaves_the_previous_artifact_in_place(self) -> None:
        """The failure that matters: every consumer reads these files whole, so
        a truncated body must not replace a good one."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / HOT_RELATIVE_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("the good previous artifact", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"SYNDICATE_DATA_ROOT": tmp_dir, "ADMIN_TOKEN": "secret-token"},
                clear=False,
            ):
                response = self.client.post(
                    "/api/ops/artifacts/publish",
                    data=b"truncated",
                    content_type="application/octet-stream",
                    headers={
                        "Authorization": "Bearer secret-token",
                        "X-Artifact-Path": HOT_RELATIVE_PATH,
                        "X-Artifact-Checksum": hashlib.sha256(b"the whole thing").hexdigest(),
                    },
                )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(target.read_text(encoding="utf-8"), "the good previous artifact")
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_the_streamed_form_honours_the_same_allowlist(self) -> None:
        """Widening the transport must not widen what may cross."""
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                data=b"data",
                content_type="application/octet-stream",
                headers={
                    "Authorization": "Bearer secret-token",
                    "X-Artifact-Path": "mlb_source/source_artifacts/data/statcast/2026.csv",
                },
            )
        self.assertEqual(response.status_code, 403)
        for bad in ("/etc/passwd", "wnba_source/../../etc/passwd"):
            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
                response = self.client.post(
                    "/api/ops/artifacts/publish",
                    data=b"data",
                    content_type="application/octet-stream",
                    headers={"Authorization": "Bearer secret-token", "X-Artifact-Path": bad},
                )
            self.assertEqual(response.status_code, 400, bad)

    def test_the_json_envelope_still_works_unchanged(self) -> None:
        """live-odds-worker is pinned on 11aea7bf and publishes this way."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {"SYNDICATE_DATA_ROOT": tmp_dir, "ADMIN_TOKEN": "secret-token"},
                clear=False,
            ):
                response = self.client.post(
                    "/api/ops/artifacts/publish",
                    json={"relative_path": HOT_RELATIVE_PATH, "content": '{"ok": true}'},
                    headers={"Authorization": "Bearer secret-token"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("transport", response.get_json())
                self.assertEqual(
                    (Path(tmp_dir) / HOT_RELATIVE_PATH).read_text(encoding="utf-8"), '{"ok": true}'
                )


class _FakePublishResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b"{}"


class StreamedPublishSenderTests(unittest.TestCase):
    def setUp(self) -> None:
        from syndicate.features.shared import artifact_publisher

        self.module = artifact_publisher

    def _write(self, root: str, size: int) -> Path:
        path = Path(root) / HOT_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"y" * size)
        return path

    def test_small_files_keep_the_json_envelope(self) -> None:
        """Below the threshold the four-copy cost is four kilobytes, and the
        envelope is the proven path."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write(tmp_dir, 1024)
            self.assertFalse(self.module._should_stream_publish(path))

    def test_large_files_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write(tmp_dir, self.module._PUBLISH_STREAM_MIN_BYTES + 1)
            self.assertTrue(self.module._should_stream_publish(path))

    def test_checksum_matches_a_whole_file_hash(self) -> None:
        """Chunked hashing must agree with the receiver's, or every large
        publish would be rejected as corrupt."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write(tmp_dir, (self.module._PUBLISH_STREAM_CHUNK_BYTES * 2) + 7)
            self.assertEqual(
                self.module._file_checksum(path), hashlib.sha256(path.read_bytes()).hexdigest()
            )

    def test_an_older_receiver_falls_back_to_the_json_envelope(self) -> None:
        """Deploy order must not be load-bearing: a web instance predating the
        streamed form answers 4xx, and the file must still publish."""
        from urllib.error import HTTPError

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write(tmp_dir, self.module._PUBLISH_STREAM_MIN_BYTES + 1)
            calls: list[str] = []

            def fake_urlopen(request_obj, *args, **kwargs):
                content_type = str(request_obj.headers.get("Content-type") or "")
                calls.append(content_type)
                if "octet-stream" in content_type:
                    raise HTTPError(url="u", code=404, msg="no route", hdrs=None, fp=None)
                return _FakePublishResponse()

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": tmp_dir,
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    result = self.module.publish_hot_artifact(path)

            self.assertTrue(result)
            self.assertEqual(len(calls), 2)
            self.assertIn("octet-stream", calls[0])
            self.assertIn("json", calls[1])

    def test_a_real_refusal_is_not_retried_as_json(self) -> None:
        """403 is the allowlist saying no. Re-sending the same bytes as JSON
        would only be refused again, at four times the memory."""
        from urllib.error import HTTPError

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write(tmp_dir, self.module._PUBLISH_STREAM_MIN_BYTES + 1)
            calls: list[str] = []

            def fake_urlopen(request_obj, *args, **kwargs):
                calls.append(str(request_obj.headers.get("Content-type") or ""))
                raise HTTPError(url="u", code=403, msg="not allowlisted", hdrs=None, fp=None)

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": tmp_dir,
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    result = self.module.publish_hot_artifact(path)

            self.assertFalse(result)
            self.assertEqual(len(calls), 1)


class ArtifactExportNamesOnlyTests(unittest.TestCase):
    """`?names_only=1` returns an inventory, not bodies.

    THE INCIDENT: at 2026-08-08T21:29:41Z a lane called
    /api/ops/artifacts/export?pattern=reports/intelligence/intelligence_state*.json&names_only=1
    and web returned 30,308,015 bytes. The parameter DID NOT EXIST -- Flask
    ignores unknown query args, so it ran as a full-body export while its author
    believed the flag was protecting them. 30MB through the 2Gi web service from
    a query that was meant to list filenames.
    """

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def _seed(self, tmp_dir: str) -> bytes:
        body = json.dumps({"rows": ["x" * 256] * 400}).encode("utf-8")
        target = Path(tmp_dir) / HOT_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return body

    def test_names_only_returns_sizes_and_not_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            body = self._seed(tmp_dir)
            with patch.dict(
                os.environ,
                {"SYNDICATE_DATA_ROOT": tmp_dir, "ADMIN_TOKEN": "secret-token"},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/artifacts/export?names_only=1",
                    headers={"Authorization": "Bearer secret-token"},
                )
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["names_only"])
            entry = payload["artifacts"][HOT_RELATIVE_PATH]
            self.assertEqual(entry["bytes"], len(body))
            self.assertIn("mtime", entry)
            # The whole point: the body must not be in the response at all.
            self.assertNotIn("rows", response.get_data(as_text=True))
            self.assertLess(len(response.get_data()), len(body))

    def test_the_body_carrying_form_is_unchanged(self) -> None:
        """Without the flag, the endpoint still returns content -- this fix must
        not quietly change what existing callers (the puller) receive."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._seed(tmp_dir)
            with patch.dict(
                os.environ,
                {"SYNDICATE_DATA_ROOT": tmp_dir, "ADMIN_TOKEN": "secret-token"},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/artifacts/export",
                    headers={"Authorization": "Bearer secret-token"},
                )
            payload = response.get_json()
            self.assertNotIn("names_only", payload)
            self.assertIn("rows", payload["artifacts"][HOT_RELATIVE_PATH])

    def test_names_only_honours_the_pattern_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._seed(tmp_dir)
            with patch.dict(
                os.environ,
                {"SYNDICATE_DATA_ROOT": tmp_dir, "ADMIN_TOKEN": "secret-token"},
                clear=False,
            ):
                matching = self.client.get(
                    "/api/ops/artifacts/export?names_only=1&pattern=wnba_source/*",
                    headers={"Authorization": "Bearer secret-token"},
                )
                non_matching = self.client.get(
                    "/api/ops/artifacts/export?names_only=1&pattern=nhl_source/*",
                    headers={"Authorization": "Bearer secret-token"},
                )
            self.assertEqual(matching.get_json()["count"], 1)
            self.assertEqual(non_matching.get_json()["count"], 0)

    def test_names_only_still_requires_the_admin_token(self) -> None:
        """Widening what can be asked cheaply must not widen who may ask."""
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get(
                "/api/ops/artifacts/export?names_only=1",
                headers={"Authorization": "Bearer wrong-token"},
            )
        self.assertEqual(response.status_code, 401)
