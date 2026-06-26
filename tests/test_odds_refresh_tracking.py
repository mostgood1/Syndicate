from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared.odds_refresh_tracking import sync_post_refresh_tracking_for_source_root
from syndicate.features.shared.odds_refresh_tracking import refresh_impacted_recommendations_for_tracking
from syndicate.features.shared.odds_lifecycle import load_odds_lifecycle_events


class OddsRefreshTrackingTests(unittest.TestCase):
    def test_sync_nhl_tracking_writes_tracking_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
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
            history_path = root / "tracking" / "odds_history.json"
            shared_history_path = Path(result["artifacts"]["odds_history"]["shared_history_path"])
            self.assertTrue(history_path.exists())
            self.assertTrue(shared_history_path.exists())

            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            shared_history_payload = json.loads(shared_history_path.read_text(encoding="utf-8"))
            self.assertEqual(shared_history_payload["markets"].keys(), history_payload["markets"].keys())
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

    def test_sync_nfl_tracking_reads_source_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
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
        with tempfile.TemporaryDirectory() as tmpdir:
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

    def test_sync_ncaab_tracking_writes_team_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
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
        with tempfile.TemporaryDirectory() as tmpdir:
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

            with patch.dict("os.environ", {"SYNDICATE_ODDS_EVENTS_ROOT": str(lifecycle_root)}, clear=False):
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


if __name__ == "__main__":
    unittest.main()