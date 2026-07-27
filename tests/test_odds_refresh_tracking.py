from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared.odds_refresh_tracking import sync_post_refresh_tracking_for_source_root
from syndicate.features.shared.odds_refresh_tracking import refresh_impacted_recommendations_for_tracking
from syndicate.features.shared.odds_lifecycle import load_odds_lifecycle_events
from tests.test_refresh_state_store import _FakeKeyValueClient


class OddsRefreshTrackingTests(unittest.TestCase):
    def test_sync_nhl_tracking_writes_tracking_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            props_root = root / "data" / "props" / "player_props_lines" / "date=2026-06-07"
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            props_root.mkdir(parents=True)
            team_root.mkdir(parents=True)
            (props_root / "oddsapi.csv").write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-110,2026-06-07T12:00:00Z\n",
                encoding="utf-8",
            )
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\n"
                "Home,Away,draftkings,total,over,6.5,-110\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertFalse(result.get("skipped", False))
            self.assertTrue((root / "tracking" / "odds_nhl_player_props_opening_2026-06-07.csv").exists())
            history_path = root / "tracking" / "odds_history" / "2026-06-07.json"
            shared_history_path = Path(result["artifacts"]["odds_history"]["shared_history_path"])
            self.assertTrue(history_path.exists())
            self.assertTrue(shared_history_path.exists())

            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            shared_history_payload = json.loads(shared_history_path.read_text(encoding="utf-8"))
            self.assertEqual(shared_history_payload["markets"].keys(), history_payload["markets"].keys())
            # Every market used to also be flattened onto the payload's own
            # top level (an exact duplicate of "markets", roughly doubling
            # this payload's size) -- confirmed no reader needs that shape
            # once "markets" is populated, so it should no longer appear.
            non_metadata_top_level_keys = set(history_payload) - {"schema_version", "sport", "shard_key", "date", "updated_at", "history_limit", "markets"}
            self.assertEqual(non_metadata_top_level_keys, set())
            market_key = next(key for key in history_payload["markets"] if "selection=over" in key)
            self.assertEqual(len(history_payload["markets"][market_key]["history"]), 1)
            first_state = history_payload["markets"][market_key]
            first_entry = first_state["history"][0]
            self.assertEqual(first_entry["market_id"], market_key)
            self.assertEqual(first_entry["sport"], "nhl")
            self.assertEqual(first_entry["event_id"], "Away@Home")
            self.assertEqual(first_entry["market_type"], "total")
            self.assertEqual(first_entry["entity"], "over")
            self.assertEqual(first_entry["line"], 6.5)
            self.assertEqual(first_entry["odds"], -110)
            self.assertEqual(first_entry["timestamp"], first_entry["captured_at"])
            self.assertEqual(first_state["last_line"], 6.5)
            self.assertEqual(first_state["movement"], "flat")
            self.assertIsNone(first_state["delta"])
            self.assertIsNone(first_state["percent_change"])

            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\n"
                "Home,Away,draftkings,total,over,7.0,-110\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertEqual(result["artifacts"]["odds_history"]["entries_appended"], 1)
            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            market_state = history_payload["markets"][market_key]
            self.assertEqual(len(market_state["history"]), 2)
            latest_entry = market_state["history"][-1]
            self.assertEqual(latest_entry["market_id"], market_key)
            self.assertEqual(latest_entry["sport"], "nhl")
            self.assertEqual(latest_entry["event_id"], "Away@Home")
            self.assertEqual(latest_entry["market_type"], "total")
            self.assertEqual(latest_entry["entity"], "over")
            self.assertEqual(latest_entry["line"], 7.0)
            self.assertEqual(latest_entry["odds"], -110)
            self.assertEqual(latest_entry["timestamp"], latest_entry["captured_at"])
            self.assertEqual(market_state["last_line"], 7.0)
            self.assertEqual(market_state["movement"], "up")
            self.assertAlmostEqual(market_state["delta"], 0.5)
            self.assertAlmostEqual(market_state["percent_change"], 7.6923076923, places=6)
            self.assertNotEqual(market_state["history"][0]["current_line"], market_state["history"][1]["current_line"])
            self.assertEqual(market_state["history"][1]["movement"], "up")

    def test_sync_nhl_tracking_appends_when_odds_change_without_line_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            props_root = root / "data" / "props" / "player_props_lines" / "date=2026-06-07"
            props_root.mkdir(parents=True)
            (props_root / "oddsapi.csv").write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-110,2026-06-07T12:00:00Z\n",
                encoding="utf-8",
            )

            first_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(first_result["ok"])

            (props_root / "oddsapi.csv").write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-105,2026-06-07T12:05:00Z\n",
                encoding="utf-8",
            )

            second_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(second_result["ok"])
            self.assertEqual(second_result["artifacts"]["odds_history"]["entries_appended"], 1)
            history_payload = json.loads((root / "tracking" / "odds_history" / "2026-06-07.json").read_text(encoding="utf-8"))
            market_key = next(key for key in history_payload["markets"] if "selection=" in key)
            market_state = history_payload["markets"][market_key]
            self.assertEqual(len(market_state["history"]), 2)
            self.assertEqual(market_state["history"][0]["current_line"], market_state["history"][1]["current_line"])
            self.assertNotEqual(market_state["history"][0]["last_odds"], market_state["history"][1]["last_odds"])

    def test_sync_nhl_tracking_appends_when_refresh_timestamp_changes_without_market_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            props_root = root / "data" / "props" / "player_props_lines" / "date=2026-06-07"
            props_root.mkdir(parents=True)
            csv_path = props_root / "oddsapi.csv"
            csv_path.write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-110,2026-06-07T12:00:00Z\n",
                encoding="utf-8",
            )

            first_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(first_result["ok"])

            csv_path.write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-110,2026-06-07T12:05:00Z\n",
                encoding="utf-8",
            )

            second_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(second_result["ok"])
            self.assertEqual(second_result["artifacts"]["odds_history"]["entries_appended"], 1)
            history_payload = json.loads((root / "tracking" / "odds_history" / "2026-06-07.json").read_text(encoding="utf-8"))
            market_key = next(key for key in history_payload["markets"] if "selection=" in key)
            market_state = history_payload["markets"][market_key]
            self.assertEqual(len(market_state["history"]), 2)
            self.assertEqual(market_state["history"][0]["current_line"], market_state["history"][1]["current_line"])
            self.assertEqual(market_state["history"][0]["last_odds"], market_state["history"][1]["last_odds"])
            self.assertNotEqual(market_state["history"][0]["snapshot_ts"], market_state["history"][1]["snapshot_ts"])

    def test_sync_nfl_tracking_reads_source_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            artifact_root = root / "source_artifacts"
            artifact_root.mkdir(parents=True)
            (artifact_root / "current_week.json").write_text(json.dumps({"season": 2026, "week": 1}), encoding="utf-8")
            (artifact_root / "oddsapi_player_props_2026_wk1.csv").write_text(
                "player,market,book,line,over_price\n"
                "Player Two,Passing Yards,draftkings,250.5,-115\n",
                encoding="utf-8",
            )
            (artifact_root / "real_betting_lines_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "fetched_at": "2026-06-07T12:00:00Z",
                        "lines": {
                            "Away @ Home": {
                                "moneyline": {"home": -150, "away": 130},
                                "total_runs": {"line": 44.5, "over": -110, "under": -110},
                                "run_line": {"home": -3.5},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="nfl", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertIn("player_props", result["artifacts"])
            self.assertTrue((root / "tracking" / "odds_nfl_player_props_opening_2026_wk1.csv").exists())
            team_opening_path = Path(result["artifacts"]["team_odds"]["opening_path"])
            self.assertTrue(team_opening_path.exists())

    def test_sync_mlb_tracking_writes_snapshot_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            snapshot_root = root / "source_artifacts" / "data" / "daily" / "snapshots" / "2026-06-07"
            snapshot_root.mkdir(parents=True)
            (snapshot_root / "oddsapi_game_lines_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "retrieved_at": "2026-06-07T12:00:00Z",
                        "games": [
                            {
                                "away_team": "Away",
                                "home_team": "Home",
                                "bookmaker": "draftkings",
                                "markets": {
                                    "h2h": {"home_odds": "-140", "away_odds": "+120"},
                                    "spreads": {"home_line": -1.5, "home_odds": "+120"},
                                    "totals": {"line": 8.5, "over_odds": "-110"},
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (snapshot_root / "oddsapi_hitter_props_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "retrieved_at": "2026-06-07T12:00:00Z",
                        "hitter_props": {"Player Three": {"batter_hits": {"line": 0.5, "over_odds": "+120", "under_odds": "-140"}}},
                    }
                ),
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="mlb", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertIn("game_lines", result["artifacts"])
            self.assertIn("hitter_props", result["artifacts"])
            self.assertTrue((root / "tracking" / "odds_mlb_game_lines_opening_2026-06-07.csv").exists())

    def test_sync_mlb_tracking_writes_prop_odds_history_entries(self) -> None:
        # 2026-07-24 fix: oddsapi_hitter_props/oddsapi_pitcher_props are
        # nested two levels deep (player_name -> market_name -> {line,
        # over_odds, under_odds}) -- the generic odds-history row reader
        # only understands one level of dynamic nesting, so these files were
        # being scanned but silently produced zero rows, leaving MLB player
        # props with no odds-history/movement tracking at all despite the
        # CSV-based props tracking (asserted below, already worked) reading
        # the exact same file correctly via _flatten_mlb_props.
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            snapshot_root = root / "source_artifacts" / "data" / "daily" / "snapshots" / "2026-06-07"
            snapshot_root.mkdir(parents=True)
            (snapshot_root / "oddsapi_game_lines_2026_06_07.json").write_text(
                json.dumps({"retrieved_at": "2026-06-07T12:00:00Z", "games": []}), encoding="utf-8"
            )
            (snapshot_root / "oddsapi_pitcher_props_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "retrieved_at": "2026-06-07T12:00:00Z",
                        "pitcher_props": {
                            "shane drohan": {
                                "strikeouts": {"line": 5.5, "over_odds": "-125", "under_odds": "-102"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="mlb", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertEqual(result["artifacts"]["odds_history"]["markets_tracked"], 2)

            history_path = root / "tracking" / "odds_history" / "2026-06-07.json"
            payload = json.loads(history_path.read_text(encoding="utf-8"))
            markets = payload["markets"]
            prop_key = next(
                (key for key in markets if "player_name=shane drohan" in key and "market=strikeouts" in key and "selection=over" in key),
                None,
            )
            self.assertIsNotNone(prop_key, f"no prop market key found among {list(markets)}")
            self.assertEqual(markets[prop_key]["last_line"], 5.5)

    def test_sync_mlb_tracking_shards_by_commence_time_not_invocation_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            snapshot_root = root / "source_artifacts" / "data" / "daily" / "snapshots" / "2026-06-07"
            snapshot_root.mkdir(parents=True)
            (snapshot_root / "oddsapi_game_lines_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "retrieved_at": "2026-06-07T12:00:00Z",
                        "games": [
                            {
                                "away_team": "Away",
                                "home_team": "Home",
                                "bookmaker": "draftkings",
                                "commence_time": "2026-06-07T23:00:00Z",
                                "markets": {
                                    "h2h": {"home_odds": "-140", "away_odds": "+120"},
                                },
                            },
                            {
                                "away_team": "Away2",
                                "home_team": "Home2",
                                "bookmaker": "draftkings",
                                "commence_time": "2026-06-08T00:30:00Z",
                                "markets": {
                                    "h2h": {"home_odds": "-130", "away_odds": "+110"},
                                },
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="mlb", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            shards = result["artifacts"]["odds_history"]["shards"]
            self.assertEqual(sorted(shards.keys()), ["2026-06-07", "2026-06-08"])

            today_path = root / "tracking" / "odds_history" / "2026-06-07.json"
            tomorrow_path = root / "tracking" / "odds_history" / "2026-06-08.json"
            self.assertTrue(today_path.exists())
            self.assertTrue(tomorrow_path.exists())

            today_payload = json.loads(today_path.read_text(encoding="utf-8"))
            tomorrow_payload = json.loads(tomorrow_path.read_text(encoding="utf-8"))
            today_key = next(key for key in today_payload["markets"] if "home_team=Home|" in key)
            tomorrow_key = next(key for key in tomorrow_payload["markets"] if "home_team=Home2|" in key)
            self.assertNotIn(tomorrow_key, today_payload["markets"])
            self.assertNotIn(today_key, tomorrow_payload["markets"])

    def test_sync_ncaab_tracking_writes_team_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            odds_root = root / "raw_outputs" / "by_date" / "2026-06-07"
            odds_root.mkdir(parents=True)
            (odds_root / "odds_2026-06-07.csv").write_text(
                "home_team,away_team,bookmaker,market,point,price\n"
                "Home,Away,draftkings,h2h,,-140\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="ncaab", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            opening_path = Path(result["artifacts"]["team_odds"]["opening_path"])
            self.assertTrue(opening_path.exists())

    def test_sync_ncaaf_tracking_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            artifact_root = root / "source_artifacts"
            artifact_root.mkdir(parents=True)
            (artifact_root / "college_football_schedule_2025_predicted_totals_enhanced_20251123T161637Z.csv").write_text(
                "season,week,home_team,away_team\n2025,1,Home,Away\n",
                encoding="utf-8",
            )
            summary_root = artifact_root / "recommendations_summary"
            summary_root.mkdir(parents=True)
            (summary_root / "summary.json").write_text("{}", encoding="utf-8")

            result = sync_post_refresh_tracking_for_source_root(sport="ncaaf", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            manifest_path = Path(result["artifacts"]["source_manifest"]["manifest_path"])
            self.assertTrue(manifest_path.exists())

    def test_sync_soccer_tracking_writes_odds_history_across_leagues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            mls_odds_root = root / "mls" / "api" / "odds"
            mls_odds_root.mkdir(parents=True)
            (mls_odds_root / "game_odds_current.csv").write_text(
                "league,event_id,home_team,away_team,commence_time,market,side,line,price,book\n"
                "mls,1,Columbus Crew,New York City FC,2026-06-07T23:30:00Z,h2h,home,,210,fanduel\n"
                "mls,1,Columbus Crew,New York City FC,2026-06-07T23:30:00Z,h2h,draw,,260,fanduel\n",
                encoding="utf-8",
            )
            mls_props_root = root / "mls" / "props"
            mls_props_root.mkdir(parents=True)
            (mls_props_root / "2026-06-07.csv").write_text(
                "league,player,market,market_key,line,over_price,under_price,book,event,event_id,game_time,home_team,away_team\n"
                "mls,Diego Rossi,Anytime Goalscorer,player_goal_scorer_anytime,,250,,betmgm,x,1,2026-06-07T23:30:00Z,Columbus Crew,New York City FC\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="soccer", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertFalse(result["artifacts"]["game_odds"].get("skipped", True))
            self.assertFalse(result["artifacts"]["player_props"].get("skipped", True))
            shared_history_path = Path(result["artifacts"]["odds_history"]["shared_history_path"])
            self.assertTrue(shared_history_path.exists())
            history_payload = json.loads(shared_history_path.read_text(encoding="utf-8"))
            market_key = "event_id=1|home_team=Columbus Crew|away_team=New York City FC|market=h2h|side=home|book=fanduel"
            self.assertIn(market_key, history_payload["markets"])
            self.assertEqual(history_payload["markets"][market_key]["last_line"], 210.0)

    def test_sync_soccer_tracking_with_no_files_is_a_graceful_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            result = sync_post_refresh_tracking_for_source_root(sport="soccer", source_root=root, date_str="2026-06-07")
            self.assertTrue(result["ok"])
            self.assertTrue(result["artifacts"]["game_odds"].get("skipped"))
            self.assertTrue(result["artifacts"]["player_props"].get("skipped"))

    def test_refresh_impacted_recommendations_updates_only_matching_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            processed_root = root / "data" / "processed"
            tracking_root = root / "tracking"
            processed_root.mkdir(parents=True)
            tracking_root.mkdir(parents=True)

            signals_path = tracking_root / "odds_nba_player_props_movement_signals_2026-06-07.csv"
            signals_path.write_text(
                "event_id,player_name,market,selection,line_move,implied_move\n"
                "game-1,Player One,points,Over 28.5,0.8,0.03\n",
                encoding="utf-8",
            )
            recommendation_path = processed_root / "recommendations_slate_2026-06-07.json"
            recommendation_path.write_text(
                json.dumps(
                    {
                        "data": [
                            {
                                "event_id": "game-1",
                                "sport": "nba",
                                "market": "points",
                                "selection": "Over 28.5",
                                "score": 86.0,
                                "simulation": {"probability_distributions": {"win": 0.64, "loss": 0.36}},
                            },
                            {
                                "event_id": "game-2",
                                "sport": "nba",
                                "market": "moneyline",
                                "selection": "Home",
                                "score": 81.0,
                                "model_probability": 0.52,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = refresh_impacted_recommendations_for_tracking(
                sport="nba",
                source_root=root,
                date_str="2026-06-07",
                tracking_meta={"signals_path": str(signals_path)},
            )

            payload = json.loads(recommendation_path.read_text(encoding="utf-8"))
            rows = payload["data"]

            self.assertTrue(result["ok"])
            self.assertEqual(result["files_updated"], 1)
            self.assertEqual(result["rows_updated"], 1)
            self.assertEqual(rows[0]["model_probability"], 0.64)
            self.assertEqual(rows[1]["model_probability"], 0.52)
            self.assertIn("lightweight_refresh", payload)

    def test_sync_tracking_appends_lifecycle_events_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            lifecycle_root = root / "odds_events"
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            team_root.mkdir(parents=True)
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\n"
                "Home,Away,draftkings,total,over,6.5,-110\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"SYNDICATE_ODDS_EVENTS_ROOT": str(lifecycle_root), "SYNDICATE_REPORTS_ROOT": str(root / "reports")}, clear=False):
                first = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

                (team_root / "oddsapi.csv").write_text(
                    "home_team,away_team,bookmaker,market,selection,line,price\n"
                    "Home,Away,draftkings,total,over,7.0,-110\n",
                    encoding="utf-8",
                )

                second = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
                events = load_odds_lifecycle_events("2026-06-07")

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertGreaterEqual(len(events), 2)
            self.assertEqual(events[0]["event_type"], "open")
            self.assertEqual(events[-1]["event_type"], "update")
            self.assertEqual(events[-1]["line"], 7.0)
            self.assertEqual(events[-1]["sport"], "nhl")

    def test_odds_history_sync_is_readable_cross_service_via_keyvalue_backend(self) -> None:
        # Real bug found in production: the odds-history shard write here
        # used _write_json (plain local-disk _atomic_write_text), but the
        # board reads these same paths through
        # odds_control_plane.load_odds_history_payload_for_sport, which
        # calls refresh_state_store.read_json_file -- keyvalue-store-only
        # when SYNDICATE_REFRESH_STATE_BACKEND=keyvalue (the production
        # config on both `syndicate` and `refresh-worker`). A write that
        # only ever touched local disk was invisible to that read no
        # matter how many refresh runs completed -- the actual root cause
        # of the Betting Board's "Move" column staying blank board-wide.
        # This confirms the write now goes through the same keyvalue-aware
        # path the board's own reader uses, so a fake keyvalue client
        # actually receives the write.
        fake_client = _FakeKeyValueClient()
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ",
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"),
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            root = Path(tmpdir)
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            team_root.mkdir(parents=True)
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\n"
                "Home,Away,draftkings,total,over,6.5,-110\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            shared_history_path = Path(result["artifacts"]["odds_history"]["shared_history_path"])

            # The write must have actually gone into the fake keyvalue
            # store, not just local disk -- proving cross-service reads
            # (via refresh_state_store.read_json_file) will see it.
            self.assertTrue(fake_client.store, "expected the odds-history write to reach the keyvalue store")
            from syndicate.features.shared.refresh_state_store import read_json_file

            payload = read_json_file(shared_history_path)
            self.assertIsInstance(payload, dict)
            self.assertEqual(payload.get("sport"), "nhl")
            self.assertIn("markets", payload)

    def test_write_json_writes_atomically(self) -> None:
        # This writes the odds-history artifacts that feed the Betting
        # Board's line-movement/CLV display. Overlapping refresh runs (see
        # docs/fix_notes_log.md) calling this concurrently for the same path
        # with a plain write_text could leave a truncated/corrupt file --
        # the likely cause of the board's "Move" column going blank.
        # Confirms this now routes through the atomic write helper.
        from syndicate.features.shared.odds_refresh_tracking import _write_json

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "odds_history" / "2026-05-22.json"
            captured: dict[str, object] = {}

            def _capture(path: Path, payload: str) -> None:
                captured["path"] = path
                captured["payload"] = payload

            with patch(
                "syndicate.features.shared.odds_refresh_tracking._atomic_write_text",
                side_effect=_capture,
            ):
                _write_json(out_path, {"markets": ["h2h"]})

            self.assertEqual(captured["path"], out_path)
            self.assertIn("h2h", str(captured["payload"]))
            self.assertFalse(out_path.exists())


if __name__ == "__main__":
    unittest.main()

class CapturePhaseTests(unittest.TestCase):
    """#82 Phase 3. Opening/closing lines become lookups, not timestamp
    inference: every lifecycle observation is tagged with the pregame phase it
    was captured in. event_type="open" already marks the opener; CLV's closing
    line is the last observation tagged "closing".
    """

    def _phase(self, *, minutes_to_start, is_live=False):
        from syndicate.features.shared.odds_refresh_tracking import _capture_phase

        observed = "2026-07-27T18:00:00+00:00"
        commence = f"2026-07-27T{18 + (minutes_to_start // 60):02d}:{minutes_to_start % 60:02d}:00+00:00"
        return _capture_phase(commence_time=commence, observed_at=observed, is_live=is_live)

    def test_boundaries_bracket_the_t_window_sweeps(self) -> None:
        # The T-75m sweep must land in "ramp", the T-10m sweep in "closing" --
        # the windows are 80/12 min so scheduler jitter cannot push a sweep's
        # observations into the wrong phase.
        self.assertEqual(self._phase(minutes_to_start=180), "drift")
        self.assertEqual(self._phase(minutes_to_start=75), "ramp")
        self.assertEqual(self._phase(minutes_to_start=10), "closing")

    def test_live_wins_regardless_of_clock(self) -> None:
        self.assertEqual(self._phase(minutes_to_start=75, is_live=True), "live")

    def test_started_games_are_live_even_without_the_flag(self) -> None:
        from syndicate.features.shared.odds_refresh_tracking import _capture_phase

        self.assertEqual(
            _capture_phase(
                commence_time="2026-07-27T17:00:00+00:00",
                observed_at="2026-07-27T18:00:00+00:00",
                is_live=False,
            ),
            "live",
        )

    def test_unknowable_fails_open_to_none_not_a_guess(self) -> None:
        from syndicate.features.shared.odds_refresh_tracking import _capture_phase

        for commence in (None, "", "not-a-date", "2026-07-27T18:00:00"):
            self.assertIsNone(
                _capture_phase(commence_time=commence, observed_at="2026-07-27T18:00:00+00:00", is_live=False),
                commence,
            )

    def test_lifecycle_events_carry_the_tag(self) -> None:
        from syndicate.features.shared.odds_refresh_tracking import _market_lifecycle_event

        event = _market_lifecycle_event(
            row={"commence_time": "2026-07-27T18:05:00+00:00", "event_id": "abc"},
            normalized_entry={},
            event_type="open",
            sport="mlb",
            timestamp="2026-07-27T18:00:00+00:00",
            market_key="mlb:abc:h2h",
            current_line=None,
            current_odds=-110.0,
            is_live=False,
        )
        self.assertEqual(event["capture_phase"], "closing")


class SteamDetectorTests(unittest.TestCase):
    """#83. The market is the best-aggregated news feed available: sharp money
    moves lines before news is actionable, and this pipeline already observes
    every move. Steam = a big move across a SMALL time gap. The actuator is
    deliberately just a flag + bounded record until #62's cheap re-price
    exists -- a false trigger that forced a re-sim would block the board.
    """

    def _signal(self, **overrides):
        from syndicate.features.shared.odds_refresh_tracking import _steam_signal

        kwargs = dict(
            previous_line=8.5,
            current_line=8.5,
            previous_odds=-110.0,
            current_odds=-110.0,
            previous_ts="2026-07-27T18:00:00+00:00",
            observed_ts="2026-07-27T18:10:00+00:00",
            capture_phase="drift",
        )
        kwargs.update(overrides)
        return _steam_signal(**kwargs)

    def test_a_half_point_line_move_in_ten_minutes_is_steam(self) -> None:
        steam = self._signal(current_line=9.0)
        self.assertIsNotNone(steam)
        self.assertEqual(steam["line_delta"], 0.5)
        self.assertEqual(steam["window_seconds"], 600.0)

    def test_the_same_move_across_four_hours_is_drift_not_steam(self) -> None:
        self.assertIsNone(self._signal(current_line=9.0, observed_ts="2026-07-27T22:00:00+00:00"))

    def test_a_fifteen_cent_price_move_is_steam_even_with_the_line_pinned(self) -> None:
        steam = self._signal(current_odds=-125.0)
        self.assertIsNotNone(steam)
        self.assertEqual(steam["odds_delta"], -15.0)

    def test_late_phases_lower_the_price_bar(self) -> None:
        # 12 cents: under the 15-cent drift bar, over the 10-cent late bar.
        # Late money is the most informed money.
        self.assertIsNone(self._signal(current_odds=-122.0, capture_phase="drift"))
        self.assertIsNotNone(self._signal(current_odds=-122.0, capture_phase="closing"))

    def test_small_moves_are_not_steam(self) -> None:
        self.assertIsNone(self._signal(current_line=8.0 + 0.5, previous_line=8.25))
        self.assertIsNone(self._signal(current_odds=-115.0))

    def test_no_prior_observation_fails_open_to_none(self) -> None:
        self.assertIsNone(self._signal(previous_ts=None, current_line=12.0))
        self.assertIsNone(self._signal(previous_ts="garbage", current_line=12.0))

    def test_record_is_bounded_and_never_raises(self) -> None:
        import json as _json
        from tempfile import TemporaryDirectory
        from unittest.mock import patch as _patch

        from syndicate.features.shared import odds_refresh_tracking as tracking

        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "steam_events_2026-07-27.json"
            with _patch.object(tracking, "_steam_events_path", return_value=path):
                events = [{"market_id": f"m{i}", "steam": {"line_delta": 1.0}} for i in range(250)]
                tracking._record_steam_events("2026-07-27", events)
                payload = _json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["events"]), tracking._STEAM_EVENTS_KEEP)
        self.assertEqual(payload["events"][-1]["market_id"], "m249")
