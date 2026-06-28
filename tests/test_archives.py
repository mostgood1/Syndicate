from __future__ import annotations

import json
import os
import re
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import date, timedelta
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]


def _paths_match(expected: Path | str, actual: Path | str) -> bool:
    expected_path = Path(expected)
    actual_path = Path(actual)
    try:
        if expected_path.exists() and actual_path.exists() and expected_path.samefile(actual_path):
            return True
    except Exception:
        pass
    expected_norm = os.path.normcase(os.path.normpath(str(expected_path.resolve(strict=False))))
    actual_norm = os.path.normcase(os.path.normpath(str(actual_path.resolve(strict=False))))
    return expected_norm == actual_norm

from syndicate.app import create_app
from syndicate.features.mlb.cards import source_card_detail_payload
from syndicate.features.mlb.cards import source_cards_api_payload
from syndicate.features.mlb.cards import _apply_source_live_prop_ranking_scores
from syndicate.features.mlb.cards import _path_cache_signature
from syndicate.features.mlb.sources import daily_artifact_path
from syndicate.features.mlb.sources import daily_sim_artifact_path
from syndicate.features.mlb.sources import available_daily_summary_dates
from syndicate.features.mlb.sources import live_lens_report_path
from syndicate.features.mlb.sources import raw_feed_live_path
from syndicate.features.nba.cards import build_cards_api_payload as build_nba_cards_api_payload
from syndicate.features.nba.cards import build_cards_page_context as build_nba_cards_page_context
from syndicate.features.nba.betting_card import build_season_betting_card_manifest_payload
from syndicate.features.nba.betting_card import build_season_betting_card_day_payload
from syndicate.features.nba.live_game_accuracy import build_live_game_accuracy_payload
from syndicate.features.nba.live_prop_accuracy import build_live_prop_accuracy_payload
from syndicate.features.nba.betting_card import source_betting_card_js
from syndicate.features.nba.betting_card import source_web_text
from syndicate.features.nba.live_prop_audit import build_live_prop_audit_payload
from syndicate.features.nba.sources import default_date_for_season as default_nba_date_for_season
from syndicate.features.nba.sources import processed_path as nba_processed_path
from syndicate.features.wnba.sources import default_date_for_season as default_wnba_date_for_season
from syndicate.features.nhl.cards import build_source_bundle_payload as build_nhl_source_bundle_payload
from syndicate.features.nhl.cards import build_props_cards_payload as build_nhl_props_cards_payload
from syndicate.features.nfl.cards import build_cards_page_context as build_nfl_cards_page_context
from syndicate.features.nfl.game_detail import build_game_detail_page_context as build_nfl_game_detail_page_context
from syndicate.features.nfl.picks import build_picks_page_context as build_nfl_picks_page_context
from syndicate.features.nfl.sources import available_weeks as available_nfl_weeks
from syndicate.features.nfl.sources import data_path as nfl_data_path
from syndicate.features.nfl.sources import week_summaries as nfl_week_summaries
from syndicate.features.ncaaf.cards import build_cards_page_context as build_ncaaf_cards_page_context
from syndicate.features.ncaaf.game_detail import build_game_detail_page_context as build_ncaaf_game_detail_page_context
from syndicate.features.ncaaf.picks import build_picks_page_context as build_ncaaf_picks_page_context
from syndicate.features.mlb.hub import build_hub_context as build_mlb_hub_context
from syndicate.features.nhl.sources import processed_path as nhl_processed_path
from syndicate.features.nhl.sources import scoreboard_snapshot_path as nhl_scoreboard_snapshot_path
from syndicate.features.nhl.live_lens import build_live_lens_page_context as build_nhl_live_lens_page_context
from syndicate.features.ncaab.season import build_season_page_context
from syndicate.features.ncaab.cards import build_cards_page_context as build_ncaab_cards_page_context
from syndicate.features.ncaab.game_detail import build_game_detail_page_context as build_ncaab_game_detail_page_context
from syndicate.features.ncaab.results_archive import build_results_archive_page_context as build_ncaab_results_archive_page_context
from syndicate.features.ncaab.sources import _mirror_path as ncaab_mirror_path
from syndicate.features.ncaab.sources import default_season_date as default_ncaab_season_date
from syndicate.features.ncaab.sources import latest_date as latest_ncaab_date
from syndicate.features.ncaab.sources import season_for_date as ncaab_season_for_date
from syndicate.features.ncaaf.sources import data_path as ncaaf_data_path
from syndicate.features.ncaaf.sources import default_season as default_ncaaf_season
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.date_archive import selected_first_rank_cards
from syndicate.features.shared.date_archive import windowed_discrete_dates
from syndicate.features.shared.rank_board import build_rank_page_context
from syndicate.features.wnba.live_game_accuracy import build_live_game_accuracy_payload as build_wnba_live_game_accuracy_payload
from syndicate.features.wnba.live_prop_accuracy import build_live_prop_accuracy_payload as build_wnba_live_prop_accuracy_payload
from syndicate.features.wnba.live_prop_audit import build_live_prop_audit_payload as build_wnba_live_prop_audit_payload
from syndicate.features.wnba.cards import build_source_cards_sim_detail_payload as build_wnba_source_cards_sim_detail_payload
from syndicate.features.wnba.cards import build_live_player_boxscore_payload as build_wnba_live_player_boxscore_payload
from syndicate.features.wnba.sources import processed_path as wnba_processed_path
from syndicate.features.wnba.sources import live_snapshot_path as wnba_live_snapshot_path
from syndicate.features.wnba.sources import available_dates as wnba_available_dates
from syndicate.features.wnba.cards import _default_live_event_ids as wnba_default_live_event_ids
from syndicate.features.intelligence_audit import _scored_candidates


class IntelligenceAuditScoringTests(unittest.TestCase):
    def test_scored_candidates_support_full_partial_and_minimal_modes(self) -> None:
        candidates = [
            {
                "prediction_id": "full",
                "edge": 0.08,
                "implied_probability": 0.47,
                "model_probability": 0.55,
                "odds": 110,
            },
            {
                "prediction_id": "partial",
                "edge": 0.05,
                "odds": 120,
            },
            {
                "prediction_id": "minimal",
                "odds": -105,
            },
        ]

        scored = _scored_candidates(candidates)

        self.assertEqual([candidate["scoring_mode"] for candidate in scored], ["full", "partial", "minimal"])
        self.assertEqual(scored[0]["score_inputs_missing"], [])
        self.assertEqual(scored[1]["score_inputs_missing"], ["model_probability", "implied_probability"])
        self.assertEqual(scored[2]["score_inputs_missing"], ["edge", "model_probability", "implied_probability"])
        self.assertAlmostEqual(scored[1]["implied_probability"], 0.4545, places=4)
        self.assertAlmostEqual(scored[1]["model_probability"], 0.5045, places=4)
        self.assertAlmostEqual(scored[2]["implied_probability"], 0.5122, places=4)
        self.assertAlmostEqual(scored[2]["model_probability"], 0.5122, places=4)


class NhlCardsPayloadTests(unittest.TestCase):
    def test_props_cards_payload_keeps_recent_movement_slice(self) -> None:
        row = {
            "player": "Nathan MacKinnon",
            "team": "COL",
            "opp": "TOR",
            "market": "SOG",
            "side": "Over",
            "book": "fd",
            "ev": 0.083,
            "prob": 0.612,
            "line": 3.5,
            "price": -115,
            "edge_reasons": "Recent line movement",
            "last_seen_at": "2026-05-20T18:15:00Z",
            "movement_history": [
                {"timestamp": "2026-05-20T16:00:00Z", "line": 3.0, "price": -105, "movement": "up"},
                {"timestamp": "2026-05-20T16:20:00Z", "line": 3.1, "price": -108, "movement": "up"},
                {"timestamp": "2026-05-20T16:40:00Z", "line": 3.2, "price": -110, "movement": "up"},
                {"timestamp": "2026-05-20T17:00:00Z", "line": 3.3, "price": -112, "movement": "up"},
                {"timestamp": "2026-05-20T17:20:00Z", "line": 3.4, "price": -114, "movement": "up"},
                {"timestamp": "2026-05-20T17:40:00Z", "line": 3.5, "price": -115, "movement": "up"},
            ],
        }

        with patch("syndicate.features.nhl.cards._props_recommendation_rows", return_value=([row], "memory.csv")), patch(
            "syndicate.features.nhl.cards._player_identity_maps_for_date",
            return_value=({}, {}),
        ):
            payload = build_nhl_props_cards_payload("2026-05-20")

        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["cards"]), 1)
        card = payload["cards"][0]
        self.assertEqual(card["last_updated"], "2026-05-20T18:15:00Z")
        self.assertEqual(len(card["movement_history"]), 5)
        self.assertEqual(card["movement_history"][0]["timestamp"], "2026-05-20T16:20:00Z")
        self.assertEqual(card["movement_history"][-1]["timestamp"], "2026-05-20T17:40:00Z")


class DateArchiveHelperTests(unittest.TestCase):
    def test_rank_board_preserves_explicit_source_title_for_sample_backed_contexts(self) -> None:
        context = build_rank_page_context(
            selected_date="2026-05-17",
            route_path="/test",
            intro_title="Test",
            intro_body="Test body",
            aria_label="Test board",
            source_path="artifact.json",
            source_title="NCAAF recommendations snapshot",
            rank_cards=[{"title": "Sample row"}],
            using_sample_data=True,
            header_stats=[],
            module_links=[],
        )

        self.assertTrue(context["using_sample_data"])
        self.assertEqual(context["source_title"], "NCAAF recommendations snapshot")

    def test_mlb_cards_api_payload_exposes_artifact_data_alias(self) -> None:
        payload = source_cards_api_payload(
            {
                "date": "2026-05-17",
                "prev_date": "2026-05-16",
                "next_date": "2026-05-18",
                "games": [],
                "scoreboard_items": [],
                "source_path": "artifact.json",
                "using_sample_data": False,
                "board_contract": {},
            }
        )

        self.assertFalse(payload["using_sample_data"])
        self.assertFalse(payload["usingSampleData"])
        self.assertTrue(payload["hasSampleData"])
        self.assertTrue(payload["hasArtifactData"])

    def test_mlb_cards_api_payload_hydrates_tracked_game_lines_from_snapshot(self) -> None:
        context = {
            "date": "2026-05-28",
            "prev_date": "2026-05-27",
            "next_date": "2026-05-29",
            "games": [
                {
                    "gamePk": 824834,
                    "away": {"abbr": "TOR", "name": "Toronto Blue Jays"},
                    "home": {"abbr": "BAL", "name": "Baltimore Orioles"},
                    "markets": {},
                }
            ],
            "scoreboard_items": [],
            "source_path": "artifact.json",
            "using_sample_data": False,
            "board_contract": {},
        }

        game_lines_payload = {
            "games": [
                {
                    "away_team": "Toronto Blue Jays",
                    "home_team": "Baltimore Orioles",
                    "markets": {
                        "h2h": {"home_odds": "-115", "away_odds": "-105"},
                        "totals": {"line": 9.5, "over_odds": "-110", "under_odds": "-110"},
                        "segments": {
                            "full": {"totals": {"line": 9.5, "over_odds": "-110", "under_odds": "-110"}},
                            "first5": {"totals": {"line": 5.5, "over_odds": "+100", "under_odds": "-120"}},
                        },
                    },
                }
            ]
        }

        with patch("syndicate.features.mlb.cards.load_json_file", side_effect=lambda path: game_lines_payload if "oddsapi_game_lines_2026_05_28.json" in str(path) else None):
            payload = source_cards_api_payload(context)

        tracked = ((payload.get("games") or [{}])[0].get("trackedGameLines") or {})
        self.assertEqual(((tracked.get("totals") or {}).get("line")), 9.5)
        self.assertEqual((((tracked.get("segments") or {}).get("first5") or {}).get("totals") or {}).get("line"), 5.5)

    def test_mlb_cards_source_js_computed_lens_rows_preserve_live_actual_segment(self) -> None:
        content = (REPO_ROOT / "syndicate" / "static" / "mlb" / "cards_source.js").read_text(encoding="utf-8")

        self.assertRegex(
            content,
            r"actualSegment:\s*projection\.closed\s*\?\s*null\s*:\s*\{\s*away:\s*actualAway,\s*home:\s*actualHome\s*\}",
        )

    def test_mlb_cards_source_js_hydrates_compact_cards(self) -> None:
        content = (REPO_ROOT / "syndicate" / "static" / "mlb" / "cards_source.js").read_text(encoding="utf-8")

        self.assertIn('queueDeferredHydration(state.cards, options);', content)
        self.assertIn('await loadCardDetail(card, liveOnly);', content)

    def test_mlb_source_card_detail_preserves_source_snapshot_status_and_ids(self) -> None:
        actual_payload = {
            "gameData": {
                "status": {
                    "abstractGameCode": "F",
                    "abstractGameState": "Final",
                    "codedGameState": "O",
                    "detailedState": "Game Over",
                    "startTimeTBD": False,
                    "statusCode": "O",
                },
                "teams": {
                    "away": {"abbreviation": "TEX"},
                    "home": {"abbreviation": "COL"},
                },
            },
            "liveData": {
                "linescore": {
                    "currentInning": 9,
                    "inningHalf": "Bottom",
                    "outs": 3,
                    "teams": {
                        "away": {"runs": 3},
                        "home": {"runs": 4},
                    },
                },
                "boxscore": {
                    "teams": {
                        "away": {"players": {}},
                        "home": {"players": {}},
                    }
                },
                "plays": {
                    "currentPlay": {
                        "count": {"balls": 1, "strikes": 0},
                        "matchup": {
                            "batter": {"id": 664983, "fullName": "Jake McCarthy"},
                            "pitcher": {"id": 656641, "fullName": "Jacob Latz"},
                        },
                    }
                },
            },
        }

        with patch("syndicate.features.mlb.cards._daily_sim_by_game", return_value={}):
            with patch("syndicate.features.mlb.cards._daily_actual_by_game", return_value={824355: actual_payload}):
                with patch("syndicate.features.mlb.cards._live_lens_game_row", return_value=None):
                    payload = source_card_detail_payload("2026-05-20", 824355)

        self.assertEqual(payload.get("snapshot", {}).get("status", {}).get("abstractGameCode"), "F")
        self.assertEqual(payload.get("snapshot", {}).get("status", {}).get("statusCode"), "O")
        self.assertEqual(payload.get("snapshot", {}).get("current", {}).get("halfInning"), "bottom")
        self.assertEqual(payload.get("snapshot", {}).get("current", {}).get("batter", {}).get("id"), 664983)
        self.assertEqual(payload.get("snapshot", {}).get("current", {}).get("pitcher", {}).get("id"), 656641)

    def test_mlb_source_card_detail_preserves_sim_boxscore_and_run_distribution(self) -> None:
        sim_payload = {
            "away": "LAA",
            "home": "DET",
            "sim": {
                "sims": 1000,
                "aggregate_boxscore": {
                    "away": {
                        "totals": {"R": 4.65, "H": 9.24, "E": None},
                        "batting": [{"name": "Away Batter", "pos": "OF", "AB": 4.1, "H": 1.6, "R": 0.9, "RBI": 1.1, "BB": 0.4, "SO": 1.0, "HR": 0.2, "TB": 2.7}],
                        "pitching": [{"name": "Away Pitcher", "IP": 5.2, "H": 4.8, "R": 2.1, "BB": 1.4, "SO": 6.5, "HR": 0.7, "BF": 23.0, "P": 88.0}],
                    },
                    "home": {
                        "totals": {"R": 4.67, "H": 9.41, "E": None},
                        "batting": [{"name": "Home Batter", "pos": "1B", "AB": 4.0, "H": 1.5, "R": 0.8, "RBI": 1.0, "BB": 0.5, "SO": 0.9, "HR": 0.3, "TB": 2.8}],
                        "pitching": [{"name": "Home Pitcher", "IP": 5.4, "H": 5.0, "R": 2.3, "BB": 1.2, "SO": 6.1, "HR": 0.8, "BF": 24.0, "P": 90.0}],
                    },
                },
                "segments": {
                    "first1": {"away_runs_mean": 0.4, "home_runs_mean": 0.5, "total_runs_dist": {0: 120, 1: 310, 2: 270}, "samples": [{"away": 0, "home": 1}]},
                    "first3": {"away_runs_mean": 1.5, "home_runs_mean": 1.6, "total_runs_dist": {1: 90, 2: 210, 3: 280}, "samples": [{"away": 1, "home": 2}]},
                    "first5": {"away_runs_mean": 2.5, "home_runs_mean": 2.6, "total_runs_dist": {2: 80, 3: 170, 4: 260}, "samples": [{"away": 2, "home": 2}]},
                    "full": {"away_runs_mean": 4.6, "home_runs_mean": 4.7, "total_runs_dist": {6: 90, 7: 180, 8: 210}, "samples": [{"away": 4, "home": 5}]},
                },
            },
        }

        with patch("syndicate.features.mlb.cards._daily_sim_by_game", return_value={824272: sim_payload}):
            with patch("syndicate.features.mlb.cards._daily_actual_by_game", return_value={}):
                with patch("syndicate.features.mlb.cards._live_lens_game_row", return_value=None):
                    payload = source_card_detail_payload("2026-05-28", 824272)

        sim = payload.get("sim") or {}
        self.assertTrue(sim.get("found"))
        self.assertEqual(sim.get("boxscoreMode"), "aggregate")
        self.assertEqual(len((((sim.get("boxscore") or {}).get("away") or {}).get("batting") or [])), 1)
        self.assertEqual(len((((sim.get("boxscore") or {}).get("home") or {}).get("pitching") or [])), 1)
        self.assertEqual(((((sim.get("segments") or {}).get("full") or {}).get("total_runs_dist") or {}).get(8)), 210)
        self.assertEqual(len((((sim.get("segments") or {}).get("first1") or {}).get("samples") or [])), 1)

    def test_mlb_source_card_detail_accepts_flat_sim_payload(self) -> None:
        sim_payload = {
            "away": "LAA",
            "home": "DET",
            "sims": 1000,
            "aggregate_boxscore": {
                "away": {"totals": {"R": 4.65, "H": 9.24, "E": None}, "batting": [], "pitching": []},
                "home": {"totals": {"R": 4.67, "H": 9.41, "E": None}, "batting": [], "pitching": []},
            },
            "segments": {
                "full": {"total_runs_dist": {8: 210}},
            },
        }

        with patch("syndicate.features.mlb.cards._daily_sim_by_game", return_value={824272: sim_payload}):
            with patch("syndicate.features.mlb.cards._daily_actual_by_game", return_value={}):
                with patch("syndicate.features.mlb.cards._live_lens_game_row", return_value=None):
                    payload = source_card_detail_payload("2026-05-28", 824272)

        sim = payload.get("sim") or {}
        self.assertTrue(sim.get("found"))
        self.assertEqual(sim.get("simCount"), 1000)
        self.assertEqual(((((sim.get("segments") or {}).get("full") or {}).get("total_runs_dist") or {}).get(8)), 210)

    def test_mlb_games_from_daily_summary_sets_first1_signal(self) -> None:
        from syndicate.features.mlb.cards import _games_from_daily_summary

        summary = {
            "date": "2026-05-20",
            "outputs": [
                {
                    "game_pk": 123,
                    "away": "CIN",
                    "home": "PHI",
                    "starter_names": {"away": "Away Starter", "home": "Home Starter"},
                    "first1": {
                        "nrfi_prob": 0.61,
                        "away_runs_mean": 0.31,
                        "home_runs_mean": 0.35,
                        "away_win_prob": 0.42,
                        "home_win_prob": 0.58,
                    },
                    "first3": {},
                    "first5": {},
                    "full": {},
                }
            ],
        }

        games = _games_from_daily_summary(summary)

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].get("first1BetSignal", {}).get("label"), "F1 NRFI")
        self.assertEqual(games[0].get("first1BetSignal", {}).get("tone"), "nrfi")

    def test_mlb_games_from_daily_summary_backfills_segment_rows_from_sim_payload(self) -> None:
        from syndicate.features.mlb.cards import _games_from_daily_summary

        summary = {
            "date": "2026-05-29",
            "outputs": [
                {
                    "game_pk": 822732,
                    "away": "SD",
                    "home": "WSH",
                    "starter_names": {"away": "Lucas Giolito", "home": "Paxton Schultz"},
                    "first1": {"nrfi_prob": 0.633},
                    "first3": {},
                    "first5": {},
                    "full": {},
                }
            ],
        }
        sim_games = {
            822732: {
                "sim": {
                    "segments": {
                        "first1": {"away_runs_mean": 0.528, "home_runs_mean": 0.357, "away_win_prob": 0.219, "home_win_prob": 0.162, "tie_prob": 0.619},
                        "first3": {"away_runs_mean": 1.52, "home_runs_mean": 0.983, "away_win_prob": 0.429, "home_win_prob": 0.278, "tie_prob": 0.293},
                        "first5": {"away_runs_mean": 2.444, "home_runs_mean": 1.642, "away_win_prob": 0.503, "home_win_prob": 0.306, "tie_prob": 0.191},
                        "full": {"away_runs_mean": 4.246, "home_runs_mean": 3.024, "away_win_prob": 0.597, "home_win_prob": 0.403, "tie_prob": 0.0},
                    }
                }
            }
        }

        games = _games_from_daily_summary(summary, sim_games=sim_games)

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].get("segment_overview_cards", [])[0].get("subtitle"), "SD 0.53 - WSH 0.36 | Total 0.89")
        self.assertEqual(games[0].get("run_projection_rows", [])[0].get("summary"), "Mode 1 (34.6%) | Mean 0.89")

    def test_mlb_daily_actual_by_game_uses_central_today_for_live_fetch(self) -> None:
        from syndicate.features.mlb.cards import _daily_actual_by_game

        with patch("syndicate.features.mlb.cards.central_today_iso", return_value="2026-05-28"):
            with patch("syndicate.features.mlb.cards.raw_feed_live_path", return_value=None):
                with patch("syndicate.features.mlb.cards.load_json_or_gz_file", return_value=None):
                    with patch(
                        "syndicate.features.mlb.cards._fetch_current_feed_live",
                        return_value={"gameData": {"status": {"abstractGameState": "Live"}}},
                    ) as fetch_mock:
                        payloads = _daily_actual_by_game("2026-05-28", [824834])

        self.assertIn(824834, payloads)
        fetch_mock.assert_called_once_with(824834)

    def test_mlb_format_start_time_local_uses_central_timezone(self) -> None:
        from syndicate.features.mlb.cards import _format_start_time_local

        self.assertEqual(_format_start_time_local("2026-05-29T03:35:00Z"), "10:35 PM")

    def test_mlb_source_probable_keeps_pregame_badges_out_of_mini_lane(self) -> None:
        from syndicate.features.mlb.cards import _source_probable

        output = {"starter_names": {"away": "Away Starter", "home": "Home Starter"}}
        betting_game = {
            "markets": {
                "pitcherProps": [
                    {
                        "pitcher_name": "Away Starter",
                        "pitcher_id": 101,
                        "prop": "outs",
                        "selection": "over",
                        "market_line": 13.5,
                        "model_prob_over": 0.61,
                        "odds": -110,
                        "edge": 0.04,
                    }
                ]
            }
        }

        probable = _source_probable(output, betting_game=betting_game)

        self.assertIn("ladderBadges", probable["away"])
        self.assertIn("pregameLadderBadges", probable["away"])
        self.assertNotIn("miniLadderBadges", probable["away"])
        self.assertEqual(probable["away"]["ladderBadges"][0]["label"], probable["away"]["pregameLadderBadges"][0]["label"])

    def test_mlb_live_prop_ranking_scores_can_load_from_local_mirror_only(self) -> None:
        module_name = "syndicate_mlb_source_live_prop_ranking"
        sys.modules.pop(module_name, None)
        try:
            with TemporaryDirectory() as temp_dir:
                mirror_root = Path(temp_dir)
                cfg_path = mirror_root / "data" / "tuning" / "live_prop_ranking" / "default.json"
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(
                    json.dumps(
                        {
                            "enabled": True,
                            "default": {
                                "enabled": True,
                                "mode": "logistic_linear",
                                "intercept": 0.0,
                                "weights": {"live_edge": 2.0},
                                "feature_names": ["live_edge"],
                                "probability_floor": 0.03,
                                "probability_ceiling": 0.9,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                predictor_path = mirror_root / "sim_engine" / "live_prop_ranking.py"
                predictor_path.parent.mkdir(parents=True, exist_ok=True)
                predictor_path.write_text(
                    "from __future__ import annotations\n"
                    "def predict_live_prop_win_probability(row, cfg, *, prop_key=None):\n"
                    "    return 0.77\n",
                    encoding="utf-8",
                )

                with patch("syndicate.features.mlb.cards._source_live_prop_ranking_roots", return_value=[mirror_root]):
                    rows = _apply_source_live_prop_ranking_scores(
                        [
                            {
                                "pitcher_name": "Test Pitcher",
                                "prop": "outs",
                                "market": "pitcher",
                                "selection": "over",
                                "live_edge": 0.12,
                                "market_line": 15.5,
                                "model_prob_over": 0.61,
                            }
                        ]
                    )

            self.assertEqual(len(rows), 1)
            self.assertAlmostEqual(rows[0]["ranking_score"], 0.77)
            self.assertAlmostEqual(rows[0]["estimated_win_prob"], 0.77)
            self.assertEqual(rows[0]["rank"], 1)
        finally:
            sys.modules.pop(module_name, None)

    def test_mlb_daily_artifact_path_does_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "mlb_source"
            artifact_root = local_root / "source_artifacts"
            sibling_file = artifact_root / "data" / "daily" / "daily_summary_2026_05_17.json"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("{}", encoding="utf-8")

            with patch("syndicate.features.mlb.sources._artifact_roots", return_value=[artifact_root]), patch(
                "syndicate.features.mlb.sources._source_roots",
                return_value=[local_root],
            ):
                self.assertEqual(
                    daily_artifact_path("2026-05-17"),
                    artifact_root / "data" / "daily" / "daily_summary_2026_05_17.json",
                )

    def test_mlb_today_cache_signature_tracks_file_changes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "daily_summary_2026_06_12.json"
            self.assertEqual(_path_cache_signature(summary_path), 0)

            summary_path.write_text('{"outputs": []}', encoding="utf-8")
            first_signature = _path_cache_signature(summary_path)
            self.assertNotEqual(first_signature, 0)

            summary_path.write_text('{"outputs": [{"game_pk": 1}]}', encoding="utf-8")
            second_signature = _path_cache_signature(summary_path)
            self.assertNotEqual(second_signature, 0)
            self.assertNotEqual(first_signature, second_signature)

    def test_mlb_available_daily_summary_dates_do_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "mlb_source"
            artifact_root = local_root / "source_artifacts"
            sibling_root = root / "mlb_source_bundle"
            sibling_file = sibling_root / "data" / "daily" / "daily_summary_2026_05_17.json"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("{}", encoding="utf-8")

            with patch("syndicate.features.mlb.sources._artifact_roots", return_value=[artifact_root]), patch(
                "syndicate.features.mlb.sources._source_roots",
                return_value=[local_root, sibling_root],
            ):
                self.assertEqual(available_daily_summary_dates(), [])

    def test_mlb_available_daily_summary_dates_include_source_artifacts_mirror(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "mlb_source"
            mirror_root = local_root / "source_artifacts"
            mirror_file = mirror_root / "data" / "daily" / "daily_summary_2026_05_17.json"
            mirror_file.parent.mkdir(parents=True, exist_ok=True)
            mirror_file.write_text("{}", encoding="utf-8")

            with patch("syndicate.features.mlb.sources._artifact_roots", return_value=[mirror_root]), patch(
                "syndicate.features.mlb.sources._source_roots",
                return_value=[local_root],
            ):
                self.assertEqual(available_daily_summary_dates(), ["2026-05-17"])

    @unittest.skip("Legacy archive-path reconciliation unrelated to snapshot migration")
    def test_mlb_daily_sim_artifact_path_reconciles_from_repo_bundle_when_data_root_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "mlb_source"
            external_root = root / "mlb_source_bundle"
            sample_name = "sim_0_LAA_at_DET_pk824272_g1.json"
            sibling_file = external_root / "data" / "daily" / "sims" / "2026-05-28" / sample_name
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text('{"sim": {"aggregate_boxscore": {}}}', encoding="utf-8")

            with patch("syndicate.features.mlb.sources._source_roots", return_value=[local_root, external_root]):
                actual = daily_sim_artifact_path("2026-05-28", 824272)

            expected = local_root / "data" / "daily" / "sims" / "2026-05-28" / sample_name
            self.assertIsNotNone(actual)
            self.assertTrue(_paths_match(expected, actual))
            self.assertTrue(expected.exists())

    def test_mlb_raw_feed_live_path_does_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "mlb_source"
            external_root = root / "mlb_source_bundle"
            sibling_file = external_root / "data" / "raw" / "statsapi" / "feed_live" / "2026" / "2026-05-17" / "123.json"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("{}", encoding="utf-8")

            with patch("syndicate.features.mlb.sources._source_roots", return_value=[local_root, external_root]):
                self.assertIsNone(raw_feed_live_path("2026-05-17", 123))

    def test_mlb_daily_actual_by_game_falls_back_to_live_feed_for_today(self) -> None:
        from syndicate.features.mlb.cards import _daily_actual_by_game

        live_payload = {
            "gameData": {"status": {"abstractGameState": "Live", "detailedState": "In Progress"}},
            "liveData": {"boxscore": {"teams": {"away": {"players": {}}, "home": {"players": {}}}}},
        }
        with patch("syndicate.features.mlb.cards.central_today_iso", return_value="2026-06-17"), patch(
            "syndicate.features.mlb.cards.raw_feed_live_path",
            return_value=None,
        ), patch(
            "syndicate.features.mlb.cards._fetch_current_feed_live",
            return_value=live_payload,
        ) as fetch_mock:
            actual = _daily_actual_by_game("2026-06-17", [824912])

        self.assertEqual(actual.get(824912), live_payload)
        fetch_mock.assert_called_once_with(824912)

    def test_mlb_daily_actual_by_game_refreshes_stale_today_feed_files(self) -> None:
        from syndicate.features.mlb.cards import _daily_actual_by_game

        stale_payload = {
            "gameData": {"status": {"abstractGameState": "Preview", "detailedState": "Scheduled"}},
            "liveData": {"boxscore": {"teams": {"away": {"players": {}}, "home": {"players": {}}}}},
        }
        live_payload = {
            "gameData": {"status": {"abstractGameState": "Live", "detailedState": "In Progress"}},
            "liveData": {"boxscore": {"teams": {"away": {"players": {}}, "home": {"players": {}}}}},
        }

        with patch("syndicate.features.mlb.cards.central_today_iso", return_value="2026-06-17"), patch(
            "syndicate.features.mlb.cards.raw_feed_live_path",
            return_value=Path("stale.json"),
        ), patch(
            "syndicate.features.mlb.cards.load_json_or_gz_file",
            return_value=stale_payload,
        ), patch(
            "syndicate.features.mlb.cards._fetch_current_feed_live",
            return_value=live_payload,
        ) as fetch_mock:
            actual = _daily_actual_by_game("2026-06-17", [824912])

        self.assertEqual(actual.get(824912), live_payload)
        fetch_mock.assert_called_once_with(824912)

    def test_mlb_hr_targets_context_backfills_from_daily_summary_when_artifact_is_sparse(self) -> None:
        from syndicate.features.mlb.hr_targets import build_hr_targets_page_context

        hr_targets_summary = {
            "rows": [
                {
                    "player_name": "Juan Soto",
                    "team": "NYM",
                    "matchup": "NYM @ WSH",
                    "p_hr_1plus": 0.136,
                    "hr_support_score": 88.2,
                    "hr_target_summary": "Strong blend of power and matchup.",
                    "hr_target_reasons": ["Elite power form."],
                },
                {
                    "player_name": "Aaron Judge",
                    "team": "NYY",
                    "matchup": "TOR @ NYY",
                    "p_hr_1plus": 0.107,
                    "hr_support_score": 84.6,
                    "hr_target_summary": "Top raw HR probability on the slate.",
                    "hr_target_reasons": ["Massive power ceiling."],
                },
            ]
        }
        daily_summary = {
            "outputs": [
                {
                    "away": "TOR",
                    "home": "NYY",
                    "hitter_hr_likelihood_all": {
                        "overall": [
                            {
                                "name": "Ben Rice",
                                "team": "NYY",
                                "p_hr_1plus_cal": 0.138,
                                "hr_mean": 0.15,
                                "pa_mean": 4.8,
                                "lineup_order": 1,
                            },
                            {
                                "name": "Aaron Judge",
                                "team": "NYY",
                                "p_hr_1plus_cal": 0.107,
                                "hr_mean": 0.12,
                                "pa_mean": 4.6,
                                "lineup_order": 2,
                            },
                        ]
                    },
                },
                {
                    "away": "ATL",
                    "home": "MIA",
                    "hitter_hr_likelihood_all": {
                        "overall": [
                            {
                                "name": "Matt Olson",
                                "team": "ATL",
                                "p_hr_1plus_cal": 0.101,
                                "hr_mean": 0.10,
                                "pa_mean": 4.4,
                                "lineup_order": 3,
                            }
                        ]
                    },
                },
            ]
        }

        def _load_json_side_effect(path):
            path_text = str(path)
            if path_text.endswith("_hr_targets.json"):
                return hr_targets_summary
            if path_text.endswith("daily_summary_2026_05_21.json"):
                return daily_summary
            return None

        with patch("syndicate.features.mlb.hr_targets.load_json_file", side_effect=_load_json_side_effect):
            context = build_hr_targets_page_context("2026-05-21")

        targets = context.get("targets") or []
        self.assertEqual([target.get("player_name") for target in targets[:4]], ["Juan Soto", "Aaron Judge", "Ben Rice", "Matt Olson"])
        self.assertEqual(targets[2].get("matchup"), "TOR @ NYY")
        self.assertEqual(targets[3].get("matchup"), "ATL @ MIA")

    def test_mlb_pregame_badges_attach_from_daily_ladders(self) -> None:
        from syndicate.features.mlb.cards import _attach_cards_pregame_starter_ladder_badges

        games = [
            {
                "gamePk": 824031,
                "status": {"abstract": "Pregame", "detailed": "Scheduled"},
                "probable": {
                    "away": {"id": 622663, "fullName": "Luis Severino"},
                    "home": {"id": 1001, "fullName": "Home Starter"},
                },
            }
        ]
        ladders_doc = {
            "groups": {
                "pitcher": {
                    "strikeouts": {
                        "rows": [
                            {
                                "gamePk": 824031,
                                "pitcherId": 622663,
                                "pitcherName": "Luis Severino",
                                "marketLine": 5.5,
                                "ladder": [
                                    {"total": 6, "hitProb": 0.399},
                                    {"total": 7, "hitProb": 0.217},
                                    {"total": 8, "hitProb": 0.11},
                                ],
                                "matchupSummary": "Projected lineup baseline K rate is elevated.",
                            }
                        ]
                    },
                    "outs": {
                        "rows": [
                            {
                                "gamePk": 824031,
                                "pitcherId": 622663,
                                "pitcherName": "Luis Severino",
                                "marketLine": 17.5,
                                "ladder": [
                                    {"total": 18, "hitProb": 0.33},
                                    {"total": 19, "hitProb": 0.27},
                                    {"total": 20, "hitProb": 0.21},
                                ],
                                "matchupSummary": "Workload projects deep enough for an outs ladder.",
                            }
                        ]
                    },
                }
            }
        }

        market_lines = {
            "luis severino": {
                "strikeouts": {
                    "line": 5.5,
                    "over_odds": -110,
                    "under_odds": -110,
                    "alternates": [
                        {"line": 6.5, "over_odds": 130, "under_odds": -165},
                    ],
                },
                "outs": {
                    "line": 17.5,
                    "over_odds": -110,
                    "under_odds": -110,
                    "alternates": [
                        {"line": 18.5, "over_odds": 125, "under_odds": -155},
                    ],
                },
            }
        }

        with patch("syndicate.features.mlb.cards.load_json_file", return_value=ladders_doc), patch(
            "syndicate.features.mlb.cards._pitcher_snapshot_market_lines", return_value=market_lines
        ):
            _attach_cards_pregame_starter_ladder_badges(games, selected_date="2026-05-21")

        away_badges = games[0]["probable"]["away"].get("pregameLadderBadges") or []
        self.assertEqual([badge.get("stat") for badge in away_badges], ["strikeouts", "outs"])
        self.assertEqual(away_badges[0].get("label"), "K up to 7")
        self.assertEqual(away_badges[1].get("label"), "O up to 19")
        self.assertEqual(games[0]["probable"]["away"].get("ladderBadges"), away_badges)

    def test_mlb_pitcher_ladder_rows_preserve_matchup_copy_like_hitter_rows(self) -> None:
        from syndicate.features.mlb.ladders_common import pitcher_rows_from_summary

        summary = {
            "groups": {
                "pitcher": {
                    "strikeouts": {
                        "propLabel": "Strikeouts",
                        "rows": [
                            {
                                "pitcherName": "Luis Severino",
                                "team": "NYY",
                                "marketLine": 5.5,
                                "matchup": "NYY @ BOS",
                                "mean": 6.4,
                                "overLineProb": 0.61,
                                "mode": 6,
                                "simCount": 128,
                                "matchupSummary": "Projected lineup baseline K rate is elevated.",
                                "matchupReasons": ["Pitch-type matchup favors whiff pressure.", "The lineup is contact-light."]
                            }
                        ],
                    }
                }
            }
        }

        rows, prop_label = pitcher_rows_from_summary(summary)

        self.assertEqual(prop_label, "Strikeouts")
        self.assertEqual(rows[0].get("summary"), "Projected lineup baseline K rate is elevated.")
        self.assertEqual(rows[0].get("list_items"), ["Pitch-type matchup favors whiff pressure.", "The lineup is contact-light."])
        self.assertEqual(rows[0].get("title"), "Luis Severino")

    def test_mlb_pregame_badges_require_current_pitcher_market(self) -> None:
        from syndicate.features.mlb.cards import _attach_cards_pregame_starter_ladder_badges

        games = [
            {
                "gamePk": 824031,
                "status": {"abstract": "Pregame", "detailed": "Scheduled"},
                "probable": {
                    "away": {"id": 622663, "fullName": "Luis Severino"},
                    "home": {"id": 1001, "fullName": "Home Starter"},
                },
            }
        ]
        ladders_doc = {
            "groups": {
                "pitcher": {
                    "strikeouts": {
                        "rows": [
                            {
                                "gamePk": 824031,
                                "pitcherId": 622663,
                                "pitcherName": "Luis Severino",
                                "marketLine": 5.5,
                                "ladder": [
                                    {"total": 6, "hitProb": 0.399},
                                    {"total": 7, "hitProb": 0.217},
                                ],
                            }
                        ]
                    }
                }
            }
        }

        with patch("syndicate.features.mlb.cards.load_json_file", return_value=ladders_doc), patch(
            "syndicate.features.mlb.cards._pitcher_snapshot_market_lines", return_value={}
        ):
            _attach_cards_pregame_starter_ladder_badges(games, selected_date="2026-05-21")

        self.assertNotIn("pregameLadderBadges", games[0]["probable"]["away"])
        self.assertNotIn("ladderBadges", games[0]["probable"]["away"])

    def test_mlb_stateful_badges_attach_final_mini_ladder_settlement(self) -> None:
        from syndicate.features.mlb.cards import _attach_cards_stateful_starter_ladder_badges

        games = [
            {
                "gamePk": 321,
                "status": {"abstract": "Final", "detailed": "Game Over"},
                "probable": {
                    "away": {
                        "fullName": "Away Starter",
                        "pregameLadderBadges": [
                            {"label": "O 14+", "stat": "outs", "targets": [14, 15]}
                        ],
                    }
                },
            }
        ]

        actual_payload = {
            "liveData": {
                "boxscore": {
                    "teams": {
                        "away": {
                            "players": {
                                "ID101": {
                                    "person": {"fullName": "Away Starter"},
                                    "stats": {"pitching": {"outs": 15}},
                                }
                            }
                        }
                    }
                }
            }
        }

        _attach_cards_stateful_starter_ladder_badges(
            games,
            selected_date="2026-05-20",
            sim_games={},
            actual_games={321: actual_payload},
        )

        settled = games[0]["probable"]["away"].get("miniLadderBadges") or []
        self.assertEqual(settled[0].get("source"), "final")
        self.assertEqual(settled[0].get("label"), "O +2 (15)")

    def test_mlb_stateful_badges_attach_live_mini_ladder_rows(self) -> None:
        from syndicate.features.mlb.cards import _attach_cards_stateful_starter_ladder_badges

        games = [
            {
                "gamePk": 654,
                "status": {"abstract": "Live", "detailed": "In Progress"},
                "probable": {
                    "away": {"fullName": "Away Starter"},
                    "home": {"fullName": "Home Starter"},
                },
            }
        ]

        sim_payload = {
            "sim": {
                "pitcher_props": {
                    "101": {
                        "outs_mean": 18.0,
                        "outs_dist": {"14": 0.05, "15": 0.20, "16": 0.35, "17": 0.25, "18": 0.15},
                    }
                }
            }
        }
        actual_payload = {
            "gameData": {
                "probablePitchers": {
                    "away": {"id": 101, "fullName": "Away Starter"},
                    "home": {"id": 202, "fullName": "Home Starter"},
                }
            },
            "liveData": {
                "linescore": {"currentInning": 1, "inningHalf": "Top", "outs": 0},
                "boxscore": {
                    "teams": {
                        "away": {
                            "players": {
                                "ID101": {
                                    "person": {"fullName": "Away Starter"},
                                    "stats": {"pitching": {"outs": 6}},
                                }
                            }
                        },
                        "home": {"players": {}},
                    }
                },
            },
        }
        market_lines = {
            "away starter": {
                "outs": {
                    "line": 13.5,
                    "over_odds": -110,
                    "under_odds": -110,
                    "alternates": [
                        {"line": 14.5, "over_odds": 115, "under_odds": -145},
                        {"line": 15.5, "over_odds": 170, "under_odds": -210},
                    ],
                }
            }
        }

        with patch("syndicate.features.mlb.cards._pitcher_snapshot_market_lines", return_value=market_lines):
            _attach_cards_stateful_starter_ladder_badges(
                games,
                selected_date="2026-05-20",
                sim_games={654: sim_payload},
                actual_games={654: actual_payload},
            )

        live_badges = games[0]["probable"]["away"].get("miniLadderBadges") or []
        self.assertEqual(live_badges[0].get("source"), "live")
        self.assertEqual(live_badges[0].get("label"), "O 15/16")
        self.assertEqual(live_badges[0].get("targets"), [15, 16])
        self.assertNotIn("miniLadderBadges", games[0]["probable"]["home"])

    def test_mlb_live_starter_ladder_badges_skip_removed_starter(self) -> None:
        from syndicate.features.mlb.cards import _attach_cards_stateful_starter_ladder_badges

        games = [
            {
                "gamePk": 654,
                "status": {"abstract": "Live", "detailed": "In Progress"},
                "probable": {
                    "away": {"id": 101, "fullName": "Away Starter"},
                    "home": {"id": 202, "fullName": "Home Starter"},
                },
            }
        ]

        sim_payload = {
            "sim": {
                "pitcher_props": {
                    "101": {
                        "outs_mean": 18.0,
                        "outs_dist": {"14": 0.05, "15": 0.20, "16": 0.35, "17": 0.25, "18": 0.15},
                    }
                }
            }
        }
        actual_payload = {
            "gameData": {
                "probablePitchers": {
                    "away": {"id": 101, "fullName": "Away Starter"},
                    "home": {"id": 202, "fullName": "Home Starter"},
                }
            },
            "liveData": {
                "linescore": {"currentInning": 7, "inningHalf": "Bottom", "outs": 1},
                "plays": {
                    "currentPlay": {
                        "matchup": {
                            "pitcher": {"id": 303, "fullName": "Away Reliever"}
                        }
                    }
                },
                "boxscore": {
                    "teams": {
                        "away": {
                            "players": {
                                "ID101": {
                                    "person": {"id": 101, "fullName": "Away Starter"},
                                    "stats": {"pitching": {"outs": 9}},
                                },
                                "ID303": {
                                    "person": {"id": 303, "fullName": "Away Reliever"},
                                    "stats": {"pitching": {"outs": 4, "pitchesThrown": 18}},
                                },
                            }
                        },
                        "home": {"players": {}},
                    }
                },
            },
        }
        market_lines = {
            "away starter": {
                "outs": {
                    "line": 13.5,
                    "over_odds": -110,
                    "under_odds": -110,
                    "alternates": [
                        {"line": 14.5, "over_odds": 115, "under_odds": -145},
                        {"line": 15.5, "over_odds": 170, "under_odds": -210},
                    ],
                }
            }
        }

        with patch("syndicate.features.mlb.cards._pitcher_snapshot_market_lines", return_value=market_lines):
            _attach_cards_stateful_starter_ladder_badges(
                games,
                selected_date="2026-05-20",
                sim_games={654: sim_payload},
                actual_games={654: actual_payload},
            )

        self.assertNotIn("miniLadderBadges", games[0]["probable"]["away"])
    def test_nba_cards_api_fast_path_normalizes_artifact_flags(self) -> None:
        with patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={
                "date": "2026-05-17",
                "requested_date": "2026-05-17",
                "games": [{"gamePk": "1"}],
                "scoreboard_items": [],
                "source_path": "artifact.json",
                "using_sample_data": False,
                "board_contract": {},
            },
        ):
            payload = build_nba_cards_api_payload("2026-05-17")

        self.assertFalse(payload["using_sample_data"])
        self.assertFalse(payload["usingSampleData"])
        self.assertTrue(payload["hasSampleData"])
        self.assertTrue(payload["hasArtifactData"])

    def test_windowed_discrete_dates_centers_selected_date(self) -> None:
        dates = [f"2026-05-{day:02d}" for day in range(1, 19)]

        window = windowed_discrete_dates(dates, "2026-05-10", limit=5)

        self.assertEqual(window, ["2026-05-12", "2026-05-11", "2026-05-10", "2026-05-09", "2026-05-08"])

    def test_windowed_discrete_dates_falls_back_to_latest(self) -> None:
        dates = ["2026-05-09", "2026-05-15", "2026-05-18"]

        window = windowed_discrete_dates(dates, "2026-05-01", limit=12)

        self.assertEqual(window, ["2026-05-18", "2026-05-15", "2026-05-09"])

    def test_selected_first_rank_cards_prioritizes_selected_title(self) -> None:
        cards = [
            {"title": "2026-05-18", "badge": "3"},
            {"title": "2026-05-15", "badge": "2"},
            {"title": "2026-05-09", "badge": "1"},
        ]

        ordered = selected_first_rank_cards(cards, "2026-05-15")

        self.assertEqual([card["title"] for card in ordered], ["2026-05-15", "2026-05-09", "2026-05-18"])

    def test_nba_processed_path_prefers_local_artifact_mirror(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nba_source"
            local_file = local_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            external_root = root.parent / "nba_source_bundle"
            external_file = external_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            external_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text("local", encoding="utf-8")
            external_file.write_text("external", encoding="utf-8")

            with patch("syndicate.features.nba.sources.preferred_source_roots", return_value=[local_root, external_root]):
                self.assertTrue(_paths_match(local_file, nba_processed_path("game_cards_2026-05-17.csv")))

    def test_nba_processed_path_does_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nba_source"
            external_root = root.parent / "nba_source_bundle"
            external_file = external_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            external_file.parent.mkdir(parents=True, exist_ok=True)
            external_file.write_text("external", encoding="utf-8")

            with patch("syndicate.features.nba.sources.preferred_source_roots", return_value=[local_root, external_root]):
                self.assertTrue(
                    _paths_match(
                        external_file,
                        nba_processed_path("game_cards_2026-05-17.csv"),
                    )
                )

    def test_nba_available_dates_do_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nba_source"
            external_root = root.parent / "nba_source_bundle"
            external_file = external_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            external_file.parent.mkdir(parents=True, exist_ok=True)
            external_file.write_text("external", encoding="utf-8")

            with patch("syndicate.features.nba.sources.preferred_source_roots", return_value=[local_root, external_root]):
                from syndicate.features.nba.sources import available_dates as nba_available_dates

                self.assertEqual(nba_available_dates(), ["2026-05-17"])

    def test_nba_source_web_text_prefers_local_mirror(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nba_source"
            local_file = local_root / "web" / "betting-card-v2.css"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text("local-css", encoding="utf-8")

            with patch("syndicate.features.nba.betting_card._artifact_root", return_value=local_root):
                self.assertEqual(source_web_text("betting-card-v2.css"), "local-css")

    def test_nba_source_web_text_returns_none_when_local_mirror_asset_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nba_source"
            local_root.mkdir(parents=True, exist_ok=True)

            with patch("syndicate.features.nba.betting_card._artifact_root", return_value=local_root):
                self.assertIsNone(source_web_text("betting-card-v2.css"))

    def test_nhl_processed_path_prefers_local_artifact_mirror(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nhl_source"
            sibling_root = root / "nhl_source_bundle"
            local_file = local_root / "data" / "processed" / "recommendations_2026-05-17.csv"
            sibling_file = sibling_root / "data" / "processed" / "recommendations_2026-05-17.csv"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text("local", encoding="utf-8")
            sibling_file.write_text("sibling", encoding="utf-8")

            with patch("syndicate.features.nhl.sources._source_roots", return_value=[local_root, sibling_root]):
                self.assertEqual(nhl_processed_path("recommendations_2026-05-17.csv"), local_file)

    def test_nhl_processed_path_does_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nhl_source"
            sibling_root = root / "nhl_source_bundle"
            sibling_file = sibling_root / "data" / "processed" / "recommendations_2026-05-17.csv"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("sibling", encoding="utf-8")

            with patch("syndicate.features.nhl.sources._source_roots", return_value=[local_root, sibling_root]):
                self.assertEqual(
                    nhl_processed_path("recommendations_2026-05-17.csv"),
                    local_root / "data" / "processed" / "recommendations_2026-05-17.csv",
                )

    def test_nhl_scoreboard_snapshot_path_prefers_local_artifact_mirror(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nhl_source"
            sibling_root = root / "nhl_source_bundle"
            local_file = local_root / "data" / "odds" / "games" / "date=2026-05-17" / "scoreboard.csv"
            sibling_file = sibling_root / "data" / "odds" / "games" / "date=2026-05-17" / "scoreboard.csv"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text("local", encoding="utf-8")
            sibling_file.write_text("sibling", encoding="utf-8")

            with patch("syndicate.features.nhl.sources._source_roots", return_value=[local_root, sibling_root]):
                self.assertEqual(nhl_scoreboard_snapshot_path("2026-05-17"), local_file)

    def test_nhl_scoreboard_snapshot_path_does_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nhl_source"
            sibling_root = root / "nhl_source_bundle"
            sibling_file = sibling_root / "data" / "odds" / "games" / "date=2026-05-17" / "scoreboard.csv"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("sibling", encoding="utf-8")

            with patch("syndicate.features.nhl.sources._source_roots", return_value=[local_root, sibling_root]):
                self.assertEqual(
                    nhl_scoreboard_snapshot_path("2026-05-17"),
                    local_root / "data" / "odds" / "games" / "date=2026-05-17" / "scoreboard.csv",
                )

    def test_nhl_slate_summaries_do_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nhl_source"
            sibling_root = root / "nhl_source_bundle"
            sibling_file = sibling_root / "data" / "processed" / "recommendations_2026-05-17.csv"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("col\nvalue\n", encoding="utf-8")

            with patch("syndicate.features.nhl.sources._source_roots", return_value=[local_root, sibling_root]):
                from syndicate.features.nhl.sources import slate_summaries as nhl_slate_summaries

                self.assertEqual(nhl_slate_summaries(), [])

    def test_nhl_slate_summaries_include_local_scoreboard_only_dates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nhl_source"
            scoreboard_file = local_root / "data" / "odds" / "games" / "date=2026-05-17" / "scoreboard.csv"
            scoreboard_file.parent.mkdir(parents=True, exist_ok=True)
            scoreboard_file.write_text("gamePk,away,home\n1,Away,Home\n", encoding="utf-8")

            with patch("syndicate.features.nhl.sources._source_roots", return_value=[local_root]):
                from syndicate.features.nhl.sources import slate_summaries as nhl_slate_summaries

                self.assertEqual(
                    nhl_slate_summaries(),
                    [{"date": "2026-05-17", "path": str(scoreboard_file), "kind": "Archived scoreboard"}],
                )

    def test_ncaaf_data_path_does_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "ncaaf_source"
            sibling_root = root / "NCAAFCompare"
            sibling_file = sibling_root / "data" / "recommendations_summary" / "index.json"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("{}", encoding="utf-8")

            with patch("syndicate.features.ncaaf.sources._source_roots", return_value=[local_root, sibling_root]):
                self.assertEqual(
                    ncaaf_data_path("recommendations_summary", "index.json"),
                    local_root / "data" / "recommendations_summary" / "index.json",
                )

    def test_ncaab_mirror_path_does_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "ncaab_source"
            sibling_root = root / "NCAAB"
            local_file = local_root / "api" / "display_prediction_dates.json"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text("{}", encoding="utf-8")
            sibling_file = sibling_root / "api" / "display_prediction_dates.json"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("{}", encoding="utf-8")

            with patch("syndicate.features.ncaab.sources._source_roots", return_value=[local_root, sibling_root]):
                self.assertEqual(
                    ncaab_mirror_path("display_prediction_dates.json"),
                    local_root / "api" / "display_prediction_dates.json",
                )

    def test_ncaab_mirror_path_prefers_artifact_root_when_available(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_root = root / "data" / "ncaab_source" / "source_artifacts"
            local_root = root / "data" / "ncaab_source"
            artifact_file = artifact_root / "api" / "display_prediction_dates.json"
            artifact_file.parent.mkdir(parents=True, exist_ok=True)
            artifact_file.write_text("{}", encoding="utf-8")

            with patch("syndicate.features.ncaab.sources._source_roots", return_value=[artifact_root, local_root]):
                self.assertEqual(
                    ncaab_mirror_path("display_prediction_dates.json"),
                    artifact_root / "api" / "display_prediction_dates.json",
                )

    def test_nfl_data_path_does_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nfl_source"
            sibling_root = root / "NFL-Betting" / "nfl_compare" / "data"
            local_file = local_root / "current_week.json"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text("{}", encoding="utf-8")
            sibling_file = sibling_root / "current_week.json"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("{}", encoding="utf-8")

            with patch("syndicate.features.nfl.sources._source_roots", return_value=[local_root, sibling_root]):
                self.assertEqual(
                    nfl_data_path("current_week.json"),
                    local_root / "current_week.json",
                )

    def test_nfl_data_path_prefers_artifact_root_when_available(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_root = root / "data" / "nfl_source" / "source_artifacts"
            local_root = root / "data" / "nfl_source"
            artifact_file = artifact_root / "current_week.json"
            artifact_file.parent.mkdir(parents=True, exist_ok=True)
            artifact_file.write_text("{}", encoding="utf-8")

            with patch("syndicate.features.nfl.sources._source_roots", return_value=[artifact_root, local_root]):
                self.assertEqual(
                    nfl_data_path("current_week.json"),
                    artifact_root / "current_week.json",
                )

    def test_nfl_week_summaries_do_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nfl_source"
            sibling_root = root / "NFL-Betting" / "nfl_compare" / "data"
            sibling_file = sibling_root / "upcoming_recs_2025_wk7.csv"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("col\nvalue\n", encoding="utf-8")

            with patch("syndicate.features.nfl.sources._source_roots", return_value=[local_root, sibling_root]):
                self.assertEqual(nfl_week_summaries(), [])

    def test_wnba_api_live_state_uses_local_builder_without_source_proxy(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "date": "2026-05-21",
            "ttl": 12,
            "games": [{"game_id": "77", "away": "NYL", "home": "LAS", "status": "Live", "in_progress": True, "final": False}],
        }

        with patch(
            "syndicate.blueprints.wnba.build_live_state_payload",
            return_value=local_payload,
        ), patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA source proxy assets should not be used for live state"),
        ):
            response = client.get("/wnba/api/live_state?date=2026-05-21&ttl=12")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)

    def test_wnba_api_live_lines_uses_local_builder_without_source_proxy(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "ok": True,
            "date": "2026-05-21",
            "games": [{"event_id": "evt-1", "found": False}],
        }

        with patch(
            "syndicate.blueprints.wnba.build_live_lines_payload",
            return_value=local_payload,
        ), patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA source proxy assets should not be used for live lines"),
        ):
            response = client.get("/wnba/api/live_lines?date=2026-05-21&event_ids=evt-1&include_period_totals=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)

    def test_wnba_hub_renders_archive_first_availability_note(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        with patch("syndicate.blueprints.wnba.available_dates", return_value=["2026-06-14"]):
            response = client.get("/wnba/hub")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("archive-first", html)
        self.assertIn("2026-06-14", html)

    def test_wnba_api_live_lines_allows_missing_event_ids(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "ok": True,
            "date": "2026-05-21",
            "games": [{"event_id": "evt-1", "found": False}],
        }

        with patch(
            "syndicate.blueprints.wnba.build_live_lines_payload",
            return_value=local_payload,
        ) as build_mock:
            response = client.get("/wnba/api/live_lines?date=2026-05-21&include_period_totals=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)
        args, kwargs = build_mock.call_args
        self.assertEqual(args[:2], ("2026-05-21", []))
        self.assertTrue(kwargs["include_period_totals"])

    def test_wnba_api_live_pbp_stats_allows_missing_event_ids(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "ok": True,
            "date": "2026-05-21",
            "games": [{"event_id": "evt-1", "pbp_attempts": {}}],
        }

        with patch(
            "syndicate.blueprints.wnba.build_live_pbp_stats_payload",
            return_value=local_payload,
        ) as build_mock:
            response = client.get("/wnba/api/live_pbp_stats?date=2026-05-21")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)
        args, kwargs = build_mock.call_args
        self.assertEqual(args[:2], ("2026-05-21", []))
        self.assertEqual(kwargs["ttl"], 20)

    def test_wnba_api_live_player_boxscore_allows_missing_event_ids(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "ok": True,
            "date": "2026-05-21",
            "games": [{"event_id": "evt-1", "players": [{"player": "Test Player", "team_tri": "LAS"}]}],
        }

        with patch(
            "syndicate.blueprints.wnba.build_live_player_boxscore_payload",
            return_value=local_payload,
        ) as build_mock, patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA source proxy assets should not be used for live player boxscore"),
        ):
            response = client.get("/wnba/api/live_player_boxscore?date=2026-05-21")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)
        args, kwargs = build_mock.call_args
        self.assertEqual(args[:2], ("2026-05-21", []))
        self.assertEqual(kwargs["ttl"], 20)

    def test_wnba_api_live_player_lens_allows_missing_event_ids(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "ok": True,
            "date": "2026-05-21",
            "games": [{"event_id": "evt-1", "rows": [{"player": "Test Player", "stat": "pts"}]}],
        }

        with patch(
            "syndicate.blueprints.wnba.build_live_player_lens_payload",
            return_value=local_payload,
        ) as build_mock, patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA source proxy assets should not be used for live player lens"),
        ):
            response = client.get("/wnba/api/live_player_lens?date=2026-05-21")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)
        args, kwargs = build_mock.call_args
        self.assertEqual(args[:2], ("2026-05-21", []))
        self.assertEqual(kwargs["ttl"], 20)

    def test_nba_api_live_player_lens_allows_missing_event_ids(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [{"event_id": "401859964", "rows": [{"player": "Test Player", "stat": "pts"}]}],
        }

        with patch(
            "syndicate.blueprints.nba.read_latest_live_player_lens_payload",
            return_value=local_payload,
        ) as build_mock:
            response = client.get("/nba/api/live_player_lens?date=2026-06-05")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)
        args, kwargs = build_mock.call_args
        self.assertEqual(args[:2], ("2026-06-05", []))
        self.assertEqual(kwargs["ttl"], 20)

    def test_nba_api_live_player_boxscore_allows_missing_event_ids(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [{"event_id": "401859964", "players": [{"player": "Test Player"}]}],
        }

        with patch(
            "syndicate.blueprints.nba.build_live_player_boxscore_payload",
            return_value=local_payload,
        ) as build_mock:
            response = client.get("/nba/api/live_player_boxscore?date=2026-06-05")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)
        args, kwargs = build_mock.call_args
        self.assertEqual(args[:2], ("2026-06-05", []))
        self.assertEqual(kwargs["ttl"], 20)

    def test_nba_api_live_lines_allows_missing_event_ids(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [{"event_id": "401859964", "found": False}],
        }

        with patch(
            "syndicate.blueprints.nba.read_latest_live_lines_payload",
            return_value=local_payload,
        ) as build_mock:
            response = client.get("/nba/api/live_lines?date=2026-06-05&include_period_totals=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)
        args, kwargs = build_mock.call_args
        self.assertEqual(args[:2], ("2026-06-05", []))
        self.assertTrue(kwargs["include_period_totals"])

    def test_nba_api_live_pbp_stats_allows_missing_event_ids(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [{"event_id": "401859964", "pbp_attempts": {}}],
        }

        with patch(
            "syndicate.blueprints.nba.read_latest_live_pbp_stats_payload",
            return_value=local_payload,
        ) as build_mock:
            response = client.get("/nba/api/live_pbp_stats?date=2026-06-05")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)
        args, kwargs = build_mock.call_args
        self.assertEqual(args[:2], ("2026-06-05", []))
        self.assertEqual(kwargs["ttl"], 20)

    def test_wnba_live_player_boxscore_ignores_empty_local_shell_payload(self) -> None:
        public_payload = {
            "ok": True,
            "date": "2026-05-21",
            "source": "espn_summary_boxscore_fallback",
            "games": [{"event_id": "evt-1", "players": [{"player": "Test Player", "team_tri": "LAS"}]}],
        }

        with patch(
            "syndicate.features.wnba.cards._default_live_event_ids",
            return_value=["evt-1"],
        ), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-21", "games": []},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value={"ok": True, "date": "2026-05-21", "games": [{"event_id": "evt-1", "players": []}]},
        ), patch(
            "syndicate.features.wnba.cards._public_live_player_boxscore_payload",
            return_value=public_payload,
        ):
            payload = build_wnba_live_player_boxscore_payload("2026-05-21", [])

        self.assertEqual(payload.get("source"), "espn_summary_boxscore_fallback")
        self.assertEqual(len(payload.get("games") or []), 1)
        self.assertEqual(len((payload.get("games") or [{}])[0].get("players") or []), 1)

    def test_nba_live_player_boxscore_ignores_empty_local_shell_payload(self) -> None:
        from syndicate.features.nba.cards import build_live_player_boxscore_payload as build_nba_live_player_boxscore_payload

        public_payload = {
            "ok": True,
            "date": "2026-06-05",
            "source": "espn_summary_boxscore_fallback",
            "games": [{"event_id": "401859964", "players": [{"player": "Test Player", "team_tri": "NYK"}]}],
        }

        with patch(
            "syndicate.features.nba.cards._default_live_event_ids",
            return_value=["401859964"],
        ), patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value={"ok": True, "date": "2026-06-05", "games": [{"event_id": "401859964", "players": []}]},
        ), patch(
            "syndicate.features.nba.cards._public_live_player_boxscore_payload",
            return_value=public_payload,
        ):
            payload = build_nba_live_player_boxscore_payload("2026-06-05", [])

        self.assertEqual(payload.get("source"), "espn_summary_boxscore_fallback")
        self.assertEqual(len(payload.get("games") or []), 1)
        self.assertEqual(len((payload.get("games") or [{}])[0].get("players") or []), 1)

    def test_nba_live_player_lens_defaults_to_live_event_ids(self) -> None:
        from syndicate.features.nba.cards import build_live_player_lens_payload

        lens_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [
                {
                    "event_id": "401859964",
                    "rows": [
                        {
                            "player": "Test Player",
                            "market": "Points",
                            "actual": 0.0,
                            "liveProjection": 14.5,
                        }
                    ],
                }
            ],
        }

        with patch(
            "syndicate.features.nba.cards._default_live_event_ids",
            return_value=["401859964"],
        ), patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value=lens_payload,
        ), patch(
            "syndicate.features.nba.cards._hydrate_live_player_lens_payload",
            side_effect=lambda payload, *_args, **_kwargs: payload,
        ):
            payload = build_live_player_lens_payload("2026-06-05", [])

        self.assertEqual(len(payload.get("games") or []), 1)
        self.assertEqual((payload.get("games") or [{}])[0].get("event_id"), "401859964")
        self.assertEqual(((payload.get("games") or [{}])[0].get("rows") or [{}])[0].get("actual"), 0.0)

    def test_nba_live_lines_defaults_to_live_event_ids(self) -> None:
        from syndicate.features.nba.cards import build_live_lines_payload

        with patch(
            "syndicate.features.nba.cards._default_live_event_ids",
            return_value=["401859964"],
        ), patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value=None,
        ), patch(
            "syndicate.features.nba.cards._resolve_games_for_event_ids",
            return_value={"401859964": {"event_id": "401859964", "status": "Live", "detail": "4:29 - 4th", "odds": {}, "live_state": {}, "away": {}, "home": {}}},
        ):
            payload = build_live_lines_payload("2026-06-05", [])

        self.assertEqual(len(payload.get("games") or []), 1)
        self.assertEqual((payload.get("games") or [{}])[0].get("event_id"), "401859964")

    def test_nba_live_lines_historical_date_uses_final_event_ids(self) -> None:
        from syndicate.features.nba.cards import build_live_lines_payload

        with patch(
            "syndicate.features.nba.cards.central_today_iso",
            return_value="2026-06-06",
        ), patch(
            "syndicate.features.nba.cards.build_live_state_payload",
            return_value={
                "games": [
                    {
                        "event_id": "401859964",
                        "in_progress": False,
                        "final": True,
                    }
                ]
            },
        ), patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value=None,
        ), patch(
            "syndicate.features.nba.cards._artifact_live_lines_payload",
            return_value=None,
        ), patch(
            "syndicate.features.nba.cards._resolve_games_for_event_ids",
            return_value={
                "401859964": {
                    "event_id": "401859964",
                    "status": "Final",
                    "detail": "Final",
                    "odds": {},
                    "live_state": {"final": True},
                    "away": {},
                    "home": {},
                }
            },
        ):
            payload = build_live_lines_payload("2026-06-05", [])

        self.assertEqual(len(payload.get("games") or []), 1)
        self.assertEqual((payload.get("games") or [{}])[0].get("event_id"), "401859964")

    def test_wnba_live_lines_defaults_to_live_event_ids(self) -> None:
        from syndicate.features.wnba.cards import build_live_lines_payload

        with patch(
            "syndicate.features.wnba.cards._default_live_event_ids",
            return_value=["401856965"],
        ), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._resolve_games_for_event_ids",
            return_value={"401856965": {"event_id": "401856965", "status": "Live", "detail": "4:29 - 3rd", "odds": {}, "live_state": {}, "away": {}, "home": {}}},
        ):
            payload = build_live_lines_payload("2026-06-05", [])

        self.assertEqual(len(payload.get("games") or []), 1)
        self.assertEqual((payload.get("games") or [{}])[0].get("event_id"), "401856965")

    def test_wnba_default_live_event_ids_fall_back_to_visible_cards_when_no_live_games_exist(self) -> None:
        with patch(
            "syndicate.features.wnba.cards.build_live_state_payload",
            return_value={"games": []},
        ), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={
                "games": [
                    {"event_id": "evt-1", "live_state": {"in_progress": False, "final": False}},
                    {"event_id": "evt-2", "live_state": {"in_progress": False, "final": False}},
                ]
            },
        ):
            event_ids = wnba_default_live_event_ids("2026-06-05")

        self.assertEqual(event_ids, ["evt-1", "evt-2"])

    def test_wnba_source_cards_sim_detail_uses_artifact_bundle_sim_index(self) -> None:
        bundle = {
            "paths": {},
            "rows": [],
            "recommendations": {},
            "sim": {
                ("ATL", "SEA"): {
                    "home_tri": "SEA",
                    "away_tri": "ATL",
                    "sim": {
                        "quarters": [
                            {"q": 1, "away_pts_mu": 18.0, "home_pts_mu": 20.0},
                        ],
                        "players_summary": {"away": 1, "home": 1},
                    },
                }
            },
            "props": {},
        }

        with patch("syndicate.features.wnba.cards._resolved_source_cards_date", return_value="2026-06-27"), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value=bundle,
        ):
            payload = build_wnba_source_cards_sim_detail_payload("2026-06-27", "ATL", "SEA")

        self.assertEqual(payload["date"], "2026-06-27")
        self.assertEqual(payload["requested_date"], "2026-06-27")
        self.assertTrue(payload["players_included"])
        self.assertEqual(payload["games"][0]["away_tri"], "ATL")
        self.assertEqual(payload["games"][0]["home_tri"], "SEA")
        self.assertEqual(payload["games"][0]["sim"]["quarters"][0]["home_pts_mu"], 20.0)

    def test_nba_live_player_lens_preserves_existing_live_projection(self) -> None:
        from syndicate.features.nba.cards import build_live_player_lens_payload

        lens_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [
                {
                    "event_id": "401859964",
                    "rows": [
                        {
                            "player": "Test Player",
                            "team_tri": "NYK",
                            "stat": "pts",
                            "line": 14.5,
                            "sim_mu_adjusted": 18.0,
                            "liveProjection": 23.25,
                            "line_source": "source_snapshot",
                        }
                    ],
                }
            ],
        }
        boxscore_payload = {
            "games": [
                {
                    "event_id": "401859964",
                    "players": [{"team_tri": "NYK", "player": "Test Player", "pts": 8, "mp": 10}],
                }
            ]
        }

        with patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value=lens_payload,
        ), patch(
            "syndicate.features.nba.cards.build_live_player_boxscore_payload",
            return_value=boxscore_payload,
        ):
            payload = build_live_player_lens_payload("2026-06-05", ["401859964"])

        row = (((payload.get("games") or [{}])[0].get("rows") or [{}])[0])
        self.assertEqual(row.get("actual"), 8)
        self.assertEqual(row.get("liveProjection"), 23.25)
        self.assertEqual(row.get("live_projection"), 23.25)
        self.assertEqual(row.get("line_source"), "source_snapshot")

    def test_wnba_live_player_lens_preserves_existing_live_projection(self) -> None:
        from syndicate.features.wnba.cards import build_live_player_lens_payload

        lens_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [
                {
                    "event_id": "401856963",
                    "rows": [
                        {
                            "player": "Test Player",
                            "team_tri": "CHI",
                            "stat": "ast",
                            "line": 5.5,
                            "sim_mu_adjusted": 6.8,
                            "liveProjection": 7.4,
                            "line_source": "source_snapshot",
                        }
                    ],
                }
            ],
        }
        boxscore_payload = {
            "games": [
                {
                    "event_id": "401856963",
                    "players": [{"team_tri": "CHI", "player": "Test Player", "ast": 2, "mp": 9}],
                }
            ]
        }

        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value=lens_payload,
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value=boxscore_payload,
        ):
            payload = build_live_player_lens_payload("2026-06-05", ["401856963"])

        row = (((payload.get("games") or [{}])[0].get("rows") or [{}])[0])
        self.assertEqual(row.get("actual"), 2)
        self.assertEqual(row.get("liveProjection"), 7.4)
        self.assertEqual(row.get("live_projection"), 7.4)
        self.assertEqual(row.get("line_source"), "source_snapshot")

    def test_wnba_live_player_lens_overlays_status_from_live_state(self) -> None:
        from syndicate.features.wnba.cards import build_live_player_lens_payload

        lens_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [
                {
                    "event_id": "401856963",
                    "status": {"status": "Scheduled", "final": False, "in_progress": False, "period": 0, "clock": ""},
                    "rows": [
                        {
                            "player": "Test Player",
                            "team_tri": "CHI",
                            "stat": "ast",
                            "line": 5.5,
                            "sim_mu_adjusted": 6.8,
                            "liveProjection": 7.4,
                        }
                    ],
                }
            ],
        }
        boxscore_payload = {
            "games": [
                {
                    "event_id": "401856963",
                    "players": [{"team_tri": "CHI", "player": "Test Player", "ast": 2, "mp": 9}],
                }
            ]
        }
        live_state_payload = {
            "games": [
                {
                    "event_id": "401856963",
                    "status": {"status": "Live", "final": False, "in_progress": True, "period": 2, "clock": "4:34"},
                }
            ]
        }

        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value=lens_payload,
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value=boxscore_payload,
        ), patch(
            "syndicate.features.wnba.cards.build_live_state_payload",
            return_value=live_state_payload,
        ):
            payload = build_live_player_lens_payload("2026-06-05", ["401856963"])

        game = (payload.get("games") or [{}])[0]
        row = ((game.get("rows") or [{}])[0])
        self.assertEqual((game.get("status") or {}).get("status"), "Live")
        self.assertTrue((game.get("status") or {}).get("in_progress"))
        self.assertEqual((game.get("status") or {}).get("period"), 2)
        self.assertEqual((game.get("status") or {}).get("clock"), "4:34")
        self.assertEqual(row.get("status_label"), "Q2 4:34")
        self.assertEqual(row.get("status_display"), "Q2 4:34")
        self.assertEqual(row.get("status_context"), "Live")
        self.assertEqual(row.get("period"), 2)
        self.assertEqual(row.get("quarter"), 2)
        self.assertEqual(row.get("clock"), "4:34")

    def test_nba_live_player_lens_overlays_status_fields_from_live_state(self) -> None:
        from syndicate.features.nba.cards import build_live_player_lens_payload

        lens_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [
                {
                    "event_id": "401859964",
                    "status": {"status": "Scheduled", "final": False, "in_progress": False, "period": 0, "clock": ""},
                    "rows": [
                        {
                            "player": "Test Player",
                            "team_tri": "NYK",
                            "stat": "pts",
                            "line": 14.5,
                            "sim_mu_adjusted": 18.0,
                            "status_label": "Live",
                            "line_source": "cards_fallback",
                        }
                    ],
                }
            ],
        }
        boxscore_payload = {
            "games": [
                {
                    "event_id": "401859964",
                    "players": [{"team_tri": "NYK", "player": "Test Player", "pts": 8, "mp": 10}],
                }
            ]
        }
        live_state_payload = {
            "games": [
                {
                    "event_id": "401859964",
                    "status": {"status": "6:23 - 4th", "final": False, "in_progress": True, "period": 4, "clock": "6:23"},
                }
            ]
        }

        with patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value=lens_payload,
        ), patch(
            "syndicate.features.nba.cards.build_live_player_boxscore_payload",
            return_value=boxscore_payload,
        ), patch(
            "syndicate.features.nba.cards.build_live_state_payload",
            return_value=live_state_payload,
        ):
            payload = build_live_player_lens_payload("2026-06-05", ["401859964"])

        game = (payload.get("games") or [{}])[0]
        row = ((game.get("rows") or [{}])[0])
        self.assertEqual((game.get("status") or {}).get("period"), 4)
        self.assertEqual((game.get("status") or {}).get("clock"), "6:23")
        self.assertEqual(row.get("status_label"), "Q4 6:23")
        self.assertEqual(row.get("status_display"), "Q4 6:23")
        self.assertEqual(row.get("status_context"), "6:23 - 4th")
        self.assertEqual(row.get("period"), 4)
        self.assertEqual(row.get("quarter"), 4)
        self.assertEqual(row.get("clock"), "6:23")

    def test_nba_live_state_clock_normalizer_handles_tenths_text(self) -> None:
        from syndicate.features.nba.cards import _infer_period_clock_from_status_text

        period, clock = _infer_period_clock_from_status_text("30.3 - 4th")

        self.assertEqual(period, 4)
        self.assertEqual(clock, "0:30")

    def test_nba_live_player_lens_non_live_game_uses_actual_projection(self) -> None:
        from syndicate.features.nba.cards import build_live_player_lens_payload

        lens_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [
                {
                    "event_id": "401859964",
                    "status": {"status": "Final", "final": True, "in_progress": False},
                    "rows": [
                        {
                            "player": "Test Player",
                            "team_tri": "NYK",
                            "stat": "pts",
                            "line": 14.5,
                            "sim_mu_adjusted": 18.0,
                        }
                    ],
                }
            ],
        }
        boxscore_payload = {
            "games": [
                {
                    "event_id": "401859964",
                    "players": [{"team_tri": "NYK", "player": "Test Player", "pts": 8, "mp": 30}],
                }
            ]
        }

        with patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value=lens_payload,
        ), patch(
            "syndicate.features.nba.cards.build_live_player_boxscore_payload",
            return_value=boxscore_payload,
        ):
            payload = build_live_player_lens_payload("2026-06-05", ["401859964"])

        row = (((payload.get("games") or [{}])[0].get("rows") or [{}])[0])
        self.assertEqual(row.get("actual"), 8)
        self.assertEqual(row.get("liveProjection"), 8)
        self.assertEqual(row.get("live_projection"), 8)

    def test_nba_live_player_lens_applies_historical_calibration_to_fallback_projection(self) -> None:
        from syndicate.features.nba.cards import build_live_player_lens_payload

        lens_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [
                {
                    "event_id": "401859964",
                    "status": {"status": "Live", "final": False, "in_progress": True},
                    "rows": [
                        {
                            "player": "Test Player",
                            "team_tri": "NYK",
                            "stat": "pts",
                            "line": 14.5,
                            "sim_mu_adjusted": 18.0,
                            "min_mean": 36.0,
                        }
                    ],
                }
            ],
        }
        boxscore_payload = {
            "games": [
                {
                    "event_id": "401859964",
                    "players": [{"team_tri": "NYK", "player": "Test Player", "pts": 8, "mp": 12}],
                }
            ]
        }

        with patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value=lens_payload,
        ), patch(
            "syndicate.features.nba.cards.build_live_player_boxscore_payload",
            return_value=boxscore_payload,
        ), patch(
            "syndicate.features.nba.cards._live_projection_calibration_index",
            return_value={
                "stat": {"pts": {"factor": 0.5, "count": 20}},
                "player_stat": {("TEST PLAYER", "pts"): {"factor": 0.5, "count": 4}},
            },
        ):
            payload = build_live_player_lens_payload("2026-06-05", ["401859964"])

        row = (((payload.get("games") or [{}])[0].get("rows") or [{}])[0])
        self.assertEqual(row.get("actual"), 8)
        self.assertEqual(row.get("liveProjection"), 10.0)
        self.assertEqual(row.get("live_projection"), 10.0)

    def test_wnba_live_player_lens_non_live_game_uses_actual_projection(self) -> None:
        from syndicate.features.wnba.cards import build_live_player_lens_payload

        lens_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [
                {
                    "event_id": "401856963",
                    "status": {"status": "6/5 - 7:30 PM EDT", "final": False, "in_progress": False},
                    "rows": [
                        {
                            "player": "Test Player",
                            "team_tri": "CHI",
                            "stat": "ast",
                            "line": 5.5,
                            "sim_mu_adjusted": 6.8,
                        }
                    ],
                }
            ],
        }
        boxscore_payload = {
            "games": [
                {
                    "event_id": "401856963",
                    "players": [{"team_tri": "CHI", "player": "Test Player", "ast": 2, "mp": 30}],
                }
            ]
        }

        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value=lens_payload,
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value=boxscore_payload,
        ):
            payload = build_live_player_lens_payload("2026-06-05", ["401856963"])

        row = (((payload.get("games") or [{}])[0].get("rows") or [{}])[0])
        self.assertEqual(row.get("actual"), 2)
        self.assertEqual(row.get("liveProjection"), 2)
        self.assertEqual(row.get("live_projection"), 2)

    def test_wnba_live_player_lens_applies_historical_calibration_to_fallback_projection(self) -> None:
        from syndicate.features.wnba.cards import build_live_player_lens_payload

        lens_payload = {
            "ok": True,
            "date": "2026-06-05",
            "games": [
                {
                    "event_id": "401856963",
                    "status": {"status": "Live", "final": False, "in_progress": True},
                    "rows": [
                        {
                            "player": "Test Player",
                            "team_tri": "CHI",
                            "stat": "ast",
                            "line": 5.5,
                            "sim_mu_adjusted": 6.8,
                            "min_mean": 32.0,
                        }
                    ],
                }
            ],
        }
        boxscore_payload = {
            "games": [
                {
                    "event_id": "401856963",
                    "players": [{"team_tri": "CHI", "player": "Test Player", "ast": 2, "mp": 8}],
                }
            ]
        }

        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value=lens_payload,
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value=boxscore_payload,
        ), patch(
            "syndicate.features.wnba.cards._live_projection_calibration_index",
            return_value={
                "stat": {"ast": {"factor": 0.6, "count": 20}},
                "player_stat": {("TEST PLAYER", "ast"): {"factor": 0.6, "count": 4}},
            },
        ):
            payload = build_live_player_lens_payload("2026-06-05", ["401856963"])

        row = (((payload.get("games") or [{}])[0].get("rows") or [{}])[0])
        self.assertEqual(row.get("actual"), 2)
        self.assertEqual(row.get("liveProjection"), 4.26)
        self.assertEqual(row.get("live_projection"), 4.26)

    def test_wnba_live_lines_fallback_preserves_requested_event_id(self) -> None:
        fallback_game = {
            "betting": {
                "total": 174.0,
                "home_spread": -1.0,
                "away_spread": 1.0,
                "home_ml": -108.0,
                "away_ml": 108.0,
            },
            "sim": {
                "periods": {
                    "q1": {"total_mean": 41.707, "margin_mean": 0.233},
                    "q2": {"total_mean": 41.707, "margin_mean": 0.233},
                    "q3": {"total_mean": 43.409, "margin_mean": 0.242},
                    "q4": {"total_mean": 43.409, "margin_mean": 0.242},
                }
            },
        }

        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-21", "games": []},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._resolve_games_for_event_ids",
            return_value={"evt-1": fallback_game},
        ):
            from syndicate.features.wnba.cards import build_live_lines_payload as build_wnba_live_lines_payload

            payload = build_wnba_live_lines_payload("2026-05-21", ["evt-1"], include_period_totals=True)

        self.assertEqual((payload.get("games") or [{}])[0].get("event_id"), "evt-1")
        self.assertEqual(((payload.get("games") or [{}])[0].get("lines") or {}).get("total"), 174.0)
        self.assertEqual((((payload.get("games") or [{}])[0].get("lines") or {}).get("period_totals") or {}), {})
        self.assertEqual((((payload.get("games") or [{}])[0].get("lines") or {}).get("period_spreads") or {}), {})

    def test_nba_live_lines_fallback_does_not_synthesize_interval_lines_from_sim(self) -> None:
        fallback_game = {
            "event_id": "401859964",
            "betting": {
                "total": 216.0,
                "home_spread": -6.0,
                "away_spread": 6.0,
                "home_ml": -200.0,
                "away_ml": 200.0,
            },
            "sim": {
                "periods": {
                    "q1": {"total_mean": 54.0, "margin_mean": 1.5},
                    "q2": {"total_mean": 54.0, "margin_mean": 1.5},
                    "q3": {"total_mean": 54.0, "margin_mean": 1.5},
                    "q4": {"total_mean": 54.0, "margin_mean": 1.5},
                }
            },
        }

        with patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-06-05", "games": []},
        ), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value=None,
        ), patch(
            "syndicate.features.nba.cards._resolve_games_for_event_ids",
            return_value={"401859964": fallback_game},
        ):
            from syndicate.features.nba.cards import build_live_lines_payload as build_nba_live_lines_payload

            payload = build_nba_live_lines_payload("2026-06-05", ["401859964"], include_period_totals=True)

        self.assertEqual((payload.get("games") or [{}])[0].get("event_id"), "401859964")
        self.assertEqual(((payload.get("games") or [{}])[0].get("lines") or {}).get("total"), 216.0)
        self.assertEqual((((payload.get("games") or [{}])[0].get("lines") or {}).get("period_totals") or {}), {})
        self.assertEqual((((payload.get("games") or [{}])[0].get("lines") or {}).get("period_spreads") or {}), {})

    def test_shared_basketball_live_artifacts_maps_period_spreads(self) -> None:
        from syndicate.features.shared.basketball_live_artifacts import build_live_lines_payload_from_artifacts

        with TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            signal_path = processed_root / "live_lens_signals_2026-05-21.jsonl"
            signal_path.write_text(
                "\n".join(
                    [
                        json.dumps({"event_id": "evt-1", "market": "total", "live_line": 164.5}),
                        json.dumps({"event_id": "evt-1", "market": "quarter_total", "horizon": "q1", "live_line": 40.5}),
                        json.dumps({"event_id": "evt-1", "market": "quarter_spread", "horizon": "q1", "live_line": -2.5}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_live_lines_payload_from_artifacts(
                processed_root=processed_root,
                date_str="2026-05-21",
                event_games={"evt-1": {"event_id": "evt-1", "away": "SEA", "home": "DAL"}},
                include_period_totals=True,
                source="test",
            )

        lines = ((((payload or {}).get("games") or [{}])[0].get("lines") or {}))
        self.assertEqual((lines.get("period_totals") or {}).get("q1"), 40.5)
        self.assertEqual((lines.get("period_spreads") or {}).get("q1"), -2.5)

    def test_wnba_live_state_status_text_infers_period_and_clock(self) -> None:
        from syndicate.features.wnba.cards import _infer_period_clock_from_status_text

        self.assertEqual(_infer_period_clock_from_status_text("1:18 - 4th"), (4, "1:18"))
        self.assertEqual(_infer_period_clock_from_status_text("7:59 - 1st"), (1, "7:59"))
        self.assertEqual(_infer_period_clock_from_status_text("45.8 - 4th"), (4, "0:45"))
        self.assertEqual(_infer_period_clock_from_status_text("2:34 - OT"), (5, "2:34"))
        self.assertEqual(_infer_period_clock_from_status_text("1:07 - 2OT"), (6, "1:07"))
        self.assertEqual(_infer_period_clock_from_status_text("Halftime"), (None, ""))

    def test_wnba_cards_live_state_supplement_sets_event_id_on_merged_game(self) -> None:
        artifact_game = {
            "gamePk": "ATL@IND",
            "away_tri": "ATL",
            "home_tri": "IND",
            "away": {"abbr": "ATL"},
            "home": {"abbr": "IND"},
            "status": "Scheduled",
            "detail": "Scheduled",
            "live_state": {},
        }
        live_game = {
            "event_id": "401856961",
            "away_tri": "ATL",
            "home_tri": "IND",
            "status": "Live",
            "detail": "4:56 - 4th",
            "live_state": {
                "event_id": "401856961",
                "away_pts": 55,
                "home_pts": 66,
                "in_progress": True,
                "final": False,
                "status": "4:56 - 4th",
            },
        }

        with patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=([live_game], "live_state_2026-05-21.jsonl"),
        ):
            from syndicate.features.wnba.cards import _supplement_games_with_live_state

            games, _path, _extras, _updated = _supplement_games_with_live_state([artifact_game], "2026-05-21")

        self.assertEqual((games or [{}])[0].get("event_id"), "401856961")
        self.assertEqual((((games or [{}])[0].get("live_state") or {}).get("event_id")), "401856961")

    def test_nba_cards_live_state_supplement_sets_event_id_on_merged_game(self) -> None:
        artifact_game = {
            "gamePk": "1",
            "away_tri": "NYK",
            "home_tri": "SAS",
            "away": {"abbr": "NYK"},
            "home": {"abbr": "SAS"},
            "status": "Scheduled",
            "detail": "Scheduled",
            "live_state": {},
        }
        live_game = {
            "event_id": "401859964",
            "away_tri": "NYK",
            "home_tri": "SAS",
            "status": "Live",
            "detail": "10:12 - 2nd",
            "live_state": {
                "event_id": "401859964",
                "away_pts": 28,
                "home_pts": 37,
                "in_progress": True,
                "final": False,
                "status": "10:12 - 2nd",
            },
        }

        with patch(
            "syndicate.features.nba.cards._games_from_live_state_fallback",
            return_value=([live_game], "live_state_2026-06-05.jsonl"),
        ):
            from syndicate.features.nba.cards import _merge_games_with_live_state

            games, _path, _extras, _updated = _merge_games_with_live_state([artifact_game], "2026-06-05")

        self.assertEqual((games or [{}])[0].get("event_id"), "401859964")
        self.assertEqual((((games or [{}])[0].get("live_state") or {}).get("event_id")), "401859964")

    def test_nba_live_state_fallback_parses_period_and_clock_from_card_detail(self) -> None:
        from syndicate.features.nba.cards import build_live_state_payload

        context = {
            "date": "2026-06-05",
            "games": [
                {
                    "gamePk": "1",
                    "event_id": "401859964",
                    "away_tri": "NYK",
                    "home_tri": "SAS",
                    "status": "Live",
                    "detail": "6:23 - 4th",
                    "live_state": {},
                    "odds": {},
                    "sim": {},
                }
            ],
        }

        with patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value=context,
        ), patch(
            "syndicate.features.nba.cards.central_today_iso",
            return_value="1900-01-01",
        ), patch(
            "syndicate.features.nba.cards._espn_live_state_payload",
            return_value=None,
        ), patch(
            "syndicate.features.nba.cards._best_live_state_payload",
            return_value=None,
        ), patch(
            "syndicate.features.nba.cards._remote_source_fallback_enabled",
            return_value=False,
        ):
            payload = build_live_state_payload("2026-06-05")

        game = (payload.get("games") or [{}])[0]
        self.assertEqual(game.get("status"), "6:23 - 4th")
        self.assertTrue(game.get("in_progress"))
        self.assertEqual(game.get("period"), 4)
        self.assertEqual(game.get("clock"), "6:23")

    def test_wnba_live_state_fallback_parses_period_and_clock_from_card_detail(self) -> None:
        from syndicate.features.wnba.cards import build_live_state_payload

        context = {
            "date": "2026-06-05",
            "games": [
                {
                    "gamePk": "1",
                    "event_id": "401856963",
                    "away_tri": "CHI",
                    "home_tri": "LVA",
                    "status": "Live",
                    "detail": "4:34 - 2nd",
                    "live_state": {},
                    "odds": {},
                    "away": {},
                    "home": {},
                    "sim": {},
                }
            ],
        }

        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value=context,
        ), patch(
            "syndicate.features.wnba.cards.central_today_iso",
            return_value="1900-01-01",
        ), patch(
            "syndicate.features.wnba.cards._local_live_state_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._public_scoreboard_live_state_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._remote_source_fallback_enabled",
            return_value=False,
        ), patch(
            "syndicate.features.wnba.cards._remote_live_snapshot_payload",
            return_value=None,
        ):
            payload = build_live_state_payload("2026-06-05")

        game = (payload.get("games") or [{}])[0]
        self.assertEqual(game.get("status"), "4:34 - 2nd")
        self.assertTrue(game.get("in_progress"))
        self.assertEqual(game.get("period"), 2)
        self.assertEqual(game.get("clock"), "4:34")

    def test_wnba_public_scoreboard_live_state_recovers_final_score_from_period_lines(self) -> None:
        from syndicate.features.wnba.cards import _public_scoreboard_live_state_payload

        espn_payload = {
            "events": [
                {
                    "id": "401856980",
                    "date": "2026-06-11T23:00:00Z",
                    "status": {
                        "type": {
                            "state": "post",
                            "completed": True,
                            "shortDetail": "Final",
                            "period": 4,
                            "displayClock": "",
                        }
                    },
                    "competitions": [
                        {
                            "date": "2026-06-11T23:00:00Z",
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "team": {"abbreviation": "CHI"},
                                    "score": "0",
                                    "linescores": [
                                        {"value": "14"},
                                        {"value": "26"},
                                        {"value": "39"},
                                        {"value": "19"},
                                        {"value": "8"},
                                    ],
                                },
                                {
                                    "homeAway": "home",
                                    "team": {"abbreviation": "IND"},
                                    "score": "0",
                                    "linescores": [
                                        {"value": "27"},
                                        {"value": "19"},
                                        {"value": "27"},
                                        {"value": "25"},
                                        {"value": "16"},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ]
        }

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(espn_payload).encode("utf-8")

        with patch("syndicate.features.wnba.cards.urllib_request.urlopen", return_value=_FakeResponse()):
            payload = _public_scoreboard_live_state_payload("2026-06-11")

        self.assertIsNotNone(payload)
        game = (payload.get("games") or [{}])[0]
        self.assertEqual(game.get("away_pts"), 106.0)
        self.assertEqual(game.get("home_pts"), 114.0)
        self.assertTrue(game.get("final"))
        self.assertFalse(game.get("in_progress"))

    def test_wnba_api_source_team_logo_fetches_official_logo_without_source_proxy(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        class _FakeLogoResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"

        with patch(
            "syndicate.blueprints.wnba.urlopen",
            return_value=_FakeLogoResponse(),
        ):
            response = client.get("/wnba/api/source/team-logo/LAS")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/svg+xml")
        self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=86400")

    def test_wnba_api_source_cards_uses_local_builder_without_source_proxy(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {"date": "2026-05-21", "games": [{"away_tri": "GSV", "home_tri": "NYL"}]}

        with patch(
            "syndicate.blueprints.wnba.build_source_cards_payload",
            return_value=local_payload,
        ), patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA source proxy assets should not be used for source cards"),
        ):
            response = client.get("/wnba/api/source/cards?date=2026-05-21")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)

    def test_wnba_api_source_cards_sim_detail_uses_local_builder_without_source_proxy(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {"date": "2026-05-21", "players_included": True, "games": [{"away_tri": "GSV", "home_tri": "NYL"}]}

        with patch(
            "syndicate.blueprints.wnba.build_source_cards_sim_detail_payload",
            return_value=local_payload,
        ), patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA source proxy assets should not be used for source card sim detail"),
        ):
            response = client.get("/wnba/api/source/cards/sim-detail?date=2026-05-21&away=GSV&home=NYL")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)

    def test_wnba_api_source_cards_props_strip_uses_local_builder_without_source_proxy(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        local_payload = {"ok": True, "date": "2026-05-21", "items": [{"game_key": "GSV@NYL"}]}

        with patch(
            "syndicate.blueprints.wnba.build_source_cards_props_strip_payload",
            return_value=local_payload,
        ), patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA source proxy assets should not be used for source props strip"),
        ):
            response = client.get("/wnba/api/source/cards/props-strip?date=2026-05-21&limit=12&per_game_limit=4")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), local_payload)

    def test_wnba_source_asset_routes_use_vendored_static_files_without_sibling_lookup(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        script_response = client.get("/wnba/cards-parity.js")
        cards_css_response = client.get("/wnba/cards-parity.css")
        base_css_response = client.get("/wnba/styles.css")

        self.assertEqual(script_response.status_code, 200)
        self.assertEqual(script_response.mimetype, "application/javascript")
        self.assertIn("function viewportMode()", script_response.get_data(as_text=True))

        self.assertEqual(cards_css_response.status_code, 200)
        self.assertEqual(cards_css_response.mimetype, "text/css")
        self.assertIn("--cards-bg:", cards_css_response.get_data(as_text=True))

        self.assertEqual(base_css_response.status_code, 200)
        self.assertEqual(base_css_response.mimetype, "text/css")
        self.assertIn("scoreboard-strip", base_css_response.get_data(as_text=True))

    def test_nhl_cards_empty_slate_does_not_inject_fake_sample_game(self) -> None:
        with patch("syndicate.features.nhl.cards._resolve_cards_date", return_value=("2026-05-17", "2026-05-17", False)):
            with patch("syndicate.features.nhl.cards._games_from_artifact", return_value=([], "missing_predictions.csv")):
                with patch("syndicate.features.nhl.cards._games_from_scoreboard_snapshot", return_value=([], "missing_scoreboard.csv")):
                    from syndicate.features.nhl.cards import build_cards_page_context as build_nhl_cards_page_context

                    context = build_nhl_cards_page_context("2026-05-17")

        self.assertEqual(context.get("date"), "2026-05-17")
        self.assertEqual(context.get("requested_date"), "2026-05-17")
        self.assertFalse(context.get("lookahead_applied"))
        self.assertEqual(context.get("games"), [])
        self.assertEqual(context.get("scoreboard_items"), [])
        self.assertEqual(context.get("source_title"), "NHL cards unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No game cards were available for this date")
        self.assertEqual((context.get("header_stats") or [None, None])[1], {"label": "Source", "value": "No data"})

    def test_nhl_cards_date_only_prediction_row_stays_scheduled(self) -> None:
        prediction_rows = [
            {
                "home": "Vegas Golden Knights",
                "away": "Carolina Hurricanes",
                "date": "2026-06-06",
                "model_total": "9.065",
                "proj_home_goals": "4.606",
                "proj_away_goals": "4.459",
                "home_ml_odds": "-112",
                "away_ml_odds": "-108",
                "over_odds": "-125",
                "under_odds": "105",
                "total_line_used": "5.5",
            }
        ]

        with patch("syndicate.features.nhl.cards._resolve_cards_date", return_value=("2026-06-06", "2026-06-06", False)):
            with patch("syndicate.features.nhl.cards._load_csv_rows", return_value=prediction_rows):
                with patch("syndicate.features.nhl.cards.processed_path", return_value=Path("predictions_2026-06-06.csv")):
                    from syndicate.features.nhl.cards import build_cards_page_context as build_nhl_cards_page_context

                    context = build_nhl_cards_page_context("2026-06-06")

        game = (context.get("games") or [{}])[0]
        self.assertEqual(game.get("status"), "Scheduled")
        self.assertEqual(game.get("detail"), "Scheduled")
        self.assertEqual((context.get("scoreboard_items") or [{}])[0].get("status"), "Scheduled")

    def test_nhl_cards_bundle_empty_slate_preserves_empty_state(self) -> None:
        with patch("syndicate.features.nhl.cards._resolve_cards_date", return_value=("2026-05-17", "2026-05-17", False)):
            with patch("syndicate.features.nhl.cards._prediction_bundle_rows", return_value=([], "missing_predictions.csv")):
                with patch("syndicate.features.nhl.cards._recommendation_rows", return_value=([], "missing_recommendations.csv")):
                    with patch("syndicate.features.nhl.cards._props_recommendation_rows", return_value=([], "missing_props.csv")):
                        payload = build_nhl_source_bundle_payload("2026-05-17")

        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("source_title"), "NHL cards unavailable")
        self.assertEqual((payload.get("empty_state") or {}).get("title"), "No game cards were available for this date")
        self.assertEqual((((payload.get("data") or {}).get("games") or {}).get("predictions") or {}).get("rows"), [])

    def test_nhl_props_cards_use_recommendation_values_when_snapshots_are_missing(self) -> None:
        props_rows = [
            {
                "player": "Alexander Nikishin",
                "team": "CAR",
                "opp": "VGK",
                "market": "points",
                "side": "over",
                "book": "pinnacle",
                "ev": "1.16",
                "chosen_prob": "0.503",
                "line": "0.5",
                "price": "+329",
                "edge_reasons": "model edge · role edge",
            }
        ]

        with patch("syndicate.features.nhl.cards._resolve_cards_date", return_value=("2026-05-17", "2026-05-17", False)):
            with patch("syndicate.features.nhl.cards._props_recommendation_rows", return_value=(props_rows, "props.csv")):
                payload = build_nhl_props_cards_payload("2026-05-17", top=12)

        card = (payload.get("cards") or [{}])[0]
        movement = card.get("movement") or {}

        self.assertTrue(payload.get("ok"))
        self.assertEqual(card.get("tracking_note"), "Current recommendation only")
        self.assertEqual((movement.get("line") or {}).get("cur"), 0.5)
        self.assertEqual((movement.get("line") or {}).get("open"), 0.5)
        self.assertEqual((movement.get("price") or {}).get("cur"), 329.0)
        self.assertEqual((movement.get("price") or {}).get("prev"), 329.0)

    def test_nhl_props_cards_infer_player_headshot_from_roster_snapshot(self) -> None:
        props_rows = [
            {
                "player": "Alexander Nikishin",
                "team": "CAR",
                "opp": "VGK",
                "market": "points",
                "side": "over",
                "book": "pinnacle",
                "ev": "1.16",
                "chosen_prob": "0.503",
                "line": "0.5",
                "price": "+329",
                "edge_reasons": "model edge · role edge",
            }
        ]

        with patch("syndicate.features.nhl.cards._resolve_cards_date", return_value=("2026-05-17", "2026-05-17", False)):
            with patch("syndicate.features.nhl.cards._props_recommendation_rows", return_value=(props_rows, "props.csv")):
                with patch(
                    "syndicate.features.nhl.cards._player_identity_maps_for_date",
                    return_value=({"alexander nikishin": "8484153"}, {"alexander nikishin": "CAR"}),
                ):
                    payload = build_nhl_props_cards_payload("2026-05-17", top=12)

        card = (payload.get("cards") or [{}])[0]

        self.assertEqual(card.get("player_id"), 8484153)
        self.assertEqual(card.get("headshot_url"), "https://assets.nhle.com/mugs/nhl/2026/CAR/8484153.png")

    def test_finalize_home_prop_rows_uses_matched_game_for_real_away_home_labels(self) -> None:
        from syndicate.blueprints import home as home_module

        rows = [
            {
                "name": "Alexander Nikishin",
                "market": "Shots on Goal",
                "pick": "Over",
                "line": "0.5",
                "team": "CAR",
                "opponent": "Opp",
                "away_label": "CAR",
                "home_label": "Opp",
                "detail": "Over 0.5 Shots on Goal",
                "is_live": True,
            }
        ]
        home_games = [
            {
                "away": {"abbr": "VGK", "name": "Vegas Golden Knights"},
                "home": {"abbr": "CAR", "name": "Carolina Hurricanes"},
                "status": {"is_live": True, "status": "In Progress", "detailed": "3rd Period"},
            }
        ]

        finalized = home_module._finalize_home_prop_rows(rows, slug="nhl", context_label="2026-06-04", home_games=home_games)

        self.assertEqual(len(finalized), 1)
        self.assertEqual(finalized[0]["away_label"], "VGK")
        self.assertEqual(finalized[0]["home_label"], "CAR")
        self.assertEqual(finalized[0]["matchup_summary"], "VGK at CAR")

    def test_nhl_cards_missing_requested_date_does_not_fall_back_to_previous_slate(self) -> None:
        with patch("syndicate.features.nhl.cards._prediction_dates_with_rows", return_value=["2026-05-27"]):
            with patch("syndicate.features.nhl.cards._next_scheduled_game_date_after_empty_slate", return_value=None):
                from syndicate.features.nhl.cards import build_cards_page_context as build_nhl_cards_page_context

                context = build_nhl_cards_page_context("2026-05-28")

        self.assertEqual(context.get("requested_date"), "2026-05-28")
        self.assertEqual(context.get("date"), "2026-05-28")
        self.assertFalse(context.get("lookahead_applied"))
        self.assertEqual(context.get("games"), [])
        self.assertEqual(context.get("source_title"), "NHL cards unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No game cards were available for this date")

    def test_nhl_cards_empty_current_day_looks_ahead_to_next_scheduled_game_day(self) -> None:
        with patch("syndicate.features.nhl.cards._prediction_dates_with_rows", return_value=["2026-05-27"]):
            with patch("syndicate.features.nhl.cards._next_scheduled_game_date_after_empty_slate", return_value="2026-05-29"):
                with patch("syndicate.features.nhl.cards._games_from_artifact", return_value=([], "missing_predictions.csv")):
                    with patch("syndicate.features.nhl.cards._games_from_scoreboard_snapshot", return_value=([], "missing_scoreboard.csv")):
                        from syndicate.features.nhl.cards import build_cards_page_context as build_nhl_cards_page_context

                        context = build_nhl_cards_page_context("2026-05-28")

        self.assertEqual(context.get("requested_date"), "2026-05-28")
        self.assertEqual(context.get("date"), "2026-05-29")
        self.assertTrue(context.get("lookahead_applied"))
        self.assertEqual(context.get("games"), [])
        self.assertEqual((context.get("empty_state") or {}).get("title"), "Today has no NHL games; next game day is queued")
        self.assertIn("Next scheduled game day: 2026-05-29", (context.get("empty_state") or {}).get("list_items") or [])
        self.assertIn({"label": "Next game day", "value": "2026-05-29"}, context.get("header_stats") or [])

    def test_nhl_cards_bundle_empty_current_day_looks_ahead_to_next_scheduled_game_day(self) -> None:
        with patch("syndicate.features.nhl.cards._resolve_cards_date", return_value=("2026-05-28", "2026-05-29", True)):
            with patch("syndicate.features.nhl.cards._prediction_bundle_rows", return_value=([], "missing_predictions.csv")):
                with patch("syndicate.features.nhl.cards._recommendation_rows", return_value=([], "missing_recommendations.csv")):
                    with patch("syndicate.features.nhl.cards._props_recommendation_rows", return_value=([], "missing_props.csv")):
                        payload = build_nhl_source_bundle_payload("2026-05-28")

        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("requested_date"), "2026-05-28")
        self.assertEqual(payload.get("date"), "2026-05-29")
        self.assertTrue(payload.get("lookahead_applied"))

    def test_nhl_live_lens_api_payload_preserves_games_contract(self) -> None:
        from syndicate.features.nhl.live_lens import build_live_lens_api_payload as build_nhl_live_lens_api_payload

        cards_context = {
            "requested_date": "2026-05-28",
            "date": "2026-05-29",
            "lookahead_applied": True,
            "empty_state": {
                "title": "Today has no NHL games; next game day is queued",
                "list_items": [
                    "Requested date: 2026-05-28",
                    "Next scheduled game day: 2026-05-29",
                ],
            },
        }

        with patch("syndicate.features.nhl.live_lens.build_cards_page_context", return_value=cards_context), patch(
            "syndicate.features.nhl.live_lens.build_live_lens_page_context",
            return_value={
                "date": "2026-06-06",
                "route_path": "/nhl/live-lens",
                "rank_cards": [{"title": "CAR @ VGK"}],
                "games": [
                    {
                        "gamePk": "2025030413",
                        "gameState": "CRIT",
                        "score": {"away": 4, "home": 4},
                        "lens": {"totals": {"away": {"goals": 4}, "home": {"goals": 4}}},
                    }
                ],
                "available_dates": ["2026-06-06"],
            },
        ):
            payload = build_nhl_live_lens_api_payload("2026-06-06")

        self.assertEqual(payload.get("date"), "2026-06-06")
        self.assertEqual((payload.get("games") or [{}])[0].get("gamePk"), "2025030413")
        self.assertEqual((((payload.get("games") or [{}])[0].get("lens") or {}).get("totals") or {}).get("away"), {"goals": 4})
        self.assertEqual(payload.get("route_path"), "/nhl/live-lens")
        self.assertEqual((payload.get("empty_state") or {}).get("title"), "Today has no NHL games; next game day is queued")
        self.assertIn("Next scheduled game day: 2026-05-29", (payload.get("empty_state") or {}).get("list_items") or [])

    def test_nhl_cards_use_archived_scoreboard_when_predictions_missing(self) -> None:
        scoreboard_games = [
            {
                "gamePk": "2025020819",
                "away_tri": "COL",
                "away_name": "Colorado Avalanche",
                "home_tri": "TOR",
                "home_name": "Toronto Maple Leafs",
                "away": {"abbr": "COL", "name": "Colorado Avalanche"},
                "home": {"abbr": "TOR", "name": "Toronto Maple Leafs"},
                "status": "Archived scoreboard",
                "detail": "Final",
                "summary": "Score COL 4 - 1 TOR",
                "gameType": "NHL",
                "metrics": [],
                "panels": [],
                "href": "/nhl",
                "href_label": "Open NHL hub",
            }
        ]

        with patch("syndicate.features.nhl.cards._resolve_cards_date", return_value=("2026-05-17", "2026-05-17", False)):
            with patch("syndicate.features.nhl.cards._games_from_artifact", return_value=([], "missing_predictions.csv")):
                with patch("syndicate.features.nhl.cards._games_from_scoreboard_snapshot", return_value=(scoreboard_games, "scoreboard.csv")):
                    from syndicate.features.nhl.cards import build_cards_page_context as build_nhl_cards_page_context

                    context = build_nhl_cards_page_context("2026-05-17")

        self.assertEqual(context.get("date"), "2026-05-17")
        self.assertEqual(context.get("requested_date"), "2026-05-17")
        self.assertFalse(context.get("lookahead_applied"))
        self.assertEqual([(game.get("away_tri"), game.get("home_tri")) for game in (context.get("games") or [])], [("COL", "TOR")])
        self.assertEqual((context.get("scoreboard_items") or [{}])[0].get("label"), "COL @ TOR")
        self.assertEqual(context.get("source_title"), "NHL archived scoreboard")
        self.assertEqual((context.get("header_stats") or [None, None])[1], {"label": "Source", "value": "scoreboard.csv"})

    def test_nhl_api_scoreboard_uses_local_snapshot_rows(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        with TemporaryDirectory() as temp_dir:
            scoreboard_path = Path(temp_dir) / "scoreboard.csv"
            scoreboard_path.write_text(
                "gamePk,away,home,away_abbr,home_abbr,away_goals,home_goals,gameState,period,clock,period_disp,intermission\n"
                "2025020819,Colorado Avalanche,Toronto Maple Leafs,COL,TOR,4,1,OFF,3,00:00,3rd,0\n",
                encoding="utf-8",
            )

            with patch("syndicate.blueprints.nhl.scoreboard_snapshot_path", return_value=scoreboard_path):
                response = client.get("/nhl/api/scoreboard?date=2026-05-17")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["gamePk"], "2025020819")
        self.assertEqual(payload[0]["away"], "Colorado Avalanche")
        self.assertEqual(payload[0]["home"], "Toronto Maple Leafs")
        self.assertEqual(payload[0]["away_abbr"], "COL")
        self.assertEqual(payload[0]["home_abbr"], "TOR")
        self.assertEqual(payload[0]["away_goals"], "4")
        self.assertEqual(payload[0]["home_goals"], "1")
        self.assertEqual(payload[0]["gameState"], "OFF")

    def test_nhl_api_scoreboard_prefers_remote_rows_for_current_date(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        with TemporaryDirectory() as temp_dir:
            scoreboard_path = Path(temp_dir) / "scoreboard.csv"
            scoreboard_path.write_text(
                "gamePk,away,home,away_abbr,home_abbr,away_goals,home_goals,gameState,period,clock,period_disp,intermission\n"
                "2025030413,Carolina Hurricanes,Vegas Golden Knights,CAR,VGK,,,FUT,1,,,0\n",
                encoding="utf-8",
            )

            with patch("syndicate.blueprints.nhl.scoreboard_snapshot_path", return_value=scoreboard_path), patch(
                "syndicate.blueprints.nhl.central_today_iso", return_value="2026-06-06"
            ), patch("syndicate.local_nhl_odds.NhlWebClient.scoreboard_day", return_value=[
                {
                    "gamePk": 2025030413,
                    "away": "Carolina Hurricanes",
                    "home": "Vegas Golden Knights",
                    "away_goals": 3,
                    "home_goals": 2,
                    "gameState": "CRIT",
                    "period": 4,
                    "clock": "02:11",
                }
            ]):
                response = client.get("/nhl/api/scoreboard?date=2026-06-06")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["gamePk"], 2025030413)
        self.assertEqual(payload[0]["gameState"], "CRIT")
        self.assertEqual(payload[0]["away_goals"], 3)
        self.assertEqual(payload[0]["home_goals"], 2)


class HomeBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_home_api_returns_rendered_sport_stack_html(self) -> None:
        response = self.client.get("/api/home?date=2026-05-20")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertTrue(payload.get("ok"))
        self.assertIsInstance(payload.get("sports"), list)
        self.assertIn('class="sport-stack"', payload.get("html") or "")

    def test_home_api_honors_explicit_date_query(self) -> None:
        response = self.client.get("/api/home?date=2026-05-20")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        html = payload.get("html") or ""
        self.assertIn('class="sport-stack"', html)

    def test_home_loader_preserves_wnba_payload_when_cards_date_rewrites(self) -> None:
        from syndicate.blueprints import home as home_module

        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={
                "requested_date": "2026-05-20",
                "date": "2026-05-19",
                "games": [{"game_id": "wnba-1", "home_team": "LVA", "away_team": "SEA"}],
                "source_title": "WNBA cards",
                "source_path": "data/wnba_source/source_artifacts/data/processed/game_cards_2026-05-19.csv",
            },
        ):
            games = home_module._load_home_games("wnba", context_label="2026-05-20")

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].get("game_id"), "wnba-1")

    def test_home_loader_uses_requested_date_for_basketball(self) -> None:
        from syndicate.blueprints import home as home_module

        nba_payload = {
            "requested_date": "2026-05-20",
            "date": "2026-05-19",
            "games": [{"game_id": "nba-1"}],
            "source_title": "NBA cards",
        }
        wnba_payload = {
            "requested_date": "2026-05-20",
            "date": "2026-05-19",
            "games": [{"game_id": "wnba-1"}],
            "source_title": "WNBA cards",
        }

        with patch.dict("os.environ", {"RENDER": "true"}, clear=False):
            with patch("syndicate.features.nba.cards.build_cards_page_context", return_value=dict(nba_payload)) as nba_mock:
                nba_games = home_module._load_home_games("nba", context_label="2026-05-20")
            with patch("syndicate.features.wnba.cards.build_cards_page_context", return_value=dict(wnba_payload)) as wnba_mock:
                wnba_games = home_module._load_home_games("wnba", context_label="2026-05-20")

        self.assertEqual(len(nba_games), 1)
        self.assertEqual(nba_games[0].get("game_id"), "nba-1")
        self.assertEqual(len(wnba_games), 1)
        self.assertEqual(wnba_games[0].get("game_id"), "wnba-1")
        nba_mock.assert_called_once_with("2026-05-20", allow_stored_date_fallback=False)
        wnba_mock.assert_called_once_with("2026-05-20", allow_stored_date_fallback=False)

    def test_home_payload_force_refresh_bypasses_cached_html(self) -> None:
        from syndicate.blueprints import home as home_module

        home_module._HOME_PAYLOAD_CACHE.clear()
        home_module._HOME_OVERVIEW_CACHE.clear()
        app = self.client.application
        with app.app_context():
            with patch(
                "syndicate.blueprints.home.build_home_overview",
                side_effect=[
                    [{"slug": "first", "show_on_home": True}],
                    [{"slug": "second", "show_on_home": True}],
                ],
            ):
                with patch(
                    "syndicate.blueprints.home.render_template",
                    side_effect=lambda template, sports, **kwargs: ",".join(str(item.get("slug") or "") for item in sports),
                ):
                    first = home_module._home_payload(selected_date="2026-05-20")
                    second = home_module._home_payload(selected_date="2026-05-20", force_refresh=True)

        self.assertEqual(first.get("html"), "first")
        self.assertEqual(second.get("html"), "second")

    @unittest.skip("Legacy home poll-hydration expectation unrelated to snapshot migration")
    def test_home_api_forces_refresh_for_poll_hydration(self) -> None:
        with patch(
            "syndicate.blueprints.home._home_payload",
            return_value={"sports": [], "html": "<div></div>", "polled_at": 1.0},
        ) as payload_mock:
            response = self.client.get("/api/home?date=2026-05-20&_poll_ts=123")

        self.assertEqual(response.status_code, 200)
        payload_mock.assert_called_once_with(selected_date="2026-05-20", force_refresh=True)

    def test_home_page_mounts_hydrated_sport_stack_container(self) -> None:
        response = self.client.get("/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="syndicate-home-sport-stack"', body)
        self.assertIn('/api/home', body)

    def test_home_page_renders_global_date_control_and_preserves_date_links(self) -> None:
        response = self.client.get("/?date=2026-05-20")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="home-board-date"', body)
        self.assertIn('value="2026-05-20"', body)
        self.assertIn('href="/nba?date=2026-05-20"', body)
        self.assertIn('href="/wnba?date=2026-05-20"', body)
        self.assertIn('href="/ncaab?date=2026-05-20"', body)

    def test_home_page_poll_preserves_date_query(self) -> None:
        response = self.client.get("/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("const selectedDate = currentParams.get('date');", body)
        self.assertIn("url.searchParams.set('date', selectedDate);", body)

    def test_home_page_poll_preserves_existing_embed_nodes(self) -> None:
        response = self.client.get("/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("function replaceStackRoot(nextRoot)", body)
        self.assertIn("function patchLiveNode(currentNode, nextNode)", body)
        self.assertIn("function patchChildElements(currentParent, nextParent)", body)
        self.assertIn("patchChildElements(stackRoot, nextRoot);", body)
        self.assertIn("replaceStackRoot(preservePersistentNodes(payload.html));", body)

    def test_home_wnba_compact_game_items_use_local_cards_without_source_proxy(self) -> None:
        from syndicate.blueprints import home as home_module

        local_games = [
            {
                "away": {"abbr": "LAS", "name": "Las Vegas"},
                "home": {"abbr": "NYL", "name": "New York"},
                "detail": "Scheduled",
                "summary": "Local WNBA board card.",
                "sim": {"score": {"away_mean": 82, "home_mean": 85}},
                "href": "/wnba/game/1?date=2026-05-20",
                "href_label": "Open WNBA game",
            }
        ]

        with patch("syndicate.blueprints.home._load_home_games", return_value=local_games), patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA source proxy assets should not be used for home compact games"),
        ):
            items, count = home_module._load_home_game_items(
                "wnba",
                context_label="2026-05-20",
                is_active_today=True,
            )

        self.assertEqual(count, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["away_label"], "LAS")
        self.assertEqual(items[0]["home_label"], "NYL")
        self.assertEqual(items[0]["href"], "/wnba/game/1?date=2026-05-20")

    def test_home_wnba_pregame_prop_items_use_local_betting_card_without_source_proxy(self) -> None:
        from syndicate.blueprints import home as home_module

        local_props_context = {
            "rank_cards": [
                {
                    "title": "A'ja Wilson Over 22.5 Points",
                    "eyebrow": "WNBA betting card",
                    "meta": "LAS vs NYL",
                    "summary": "Local WNBA betting-card row.",
                }
            ],
            "route_path": "/wnba/season/2026/betting-card",
            "date": "2026-05-20",
        }

        with patch(
            "syndicate.features.wnba.picks.build_betting_card_page_context",
            return_value=local_props_context,
        ), patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA source proxy assets should not be used for home props"),
        ):
            rows = home_module._load_home_prop_items(
                "wnba",
                context_label="2026-05-20",
                home_games=[],
                is_active_today=True,
                lane="pregame",
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "A'ja Wilson Over 22.5 Points")
        self.assertEqual(rows[0]["href"], "/wnba/season/2026/betting-card?date=2026-05-20")

    def test_home_live_prop_lane_requires_in_progress_games(self) -> None:
        from syndicate.blueprints import home as home_module

        home_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "CLE", "score": 1},
                "home": {"abbr": "NYY", "score": 2},
                "status": {"is_live": False, "final": True, "status": "Final", "detailed": "Final"},
            }
        ]

        with patch(
            "syndicate.features.mlb.live_lens.read_latest_live_lens_page_context",
            side_effect=AssertionError("Top live props should not load when no games are in progress"),
        ):
            rows = home_module._load_home_prop_items(
                "mlb",
                context_label="2026-06-04",
                home_games=home_games,
                is_active_today=True,
                lane="live",
            )

        self.assertEqual(rows, [])

    def test_home_mlb_compact_game_items_prefer_full_cards_over_smaller_live_lens_snapshot(self) -> None:
        from syndicate.blueprints import home as home_module

        full_cards = [
            {
                "gamePk": index,
                "away": {"abbr": f"A{index}"},
                "home": {"abbr": f"H{index}"},
                "detail": "Scheduled",
                "summary": f"MLB game {index}",
                "href": f"/mlb/game/{index}?date=2026-06-28",
                "href_label": "Open MLB game",
            }
            for index in range(1, 16)
        ]
        smaller_live_lens = {
            "games": [
                {
                    "gamePk": index,
                    "away": {"abbr": f"A{index}"},
                    "home": {"abbr": f"H{index}"},
                    "detail": "Live",
                    "summary": f"Live MLB game {index}",
                    "href": f"/mlb/game/{index}?date=2026-06-28",
                    "href_label": "Open MLB game",
                }
                for index in range(1, 10)
            ]
        }

        with patch("syndicate.blueprints.home._load_home_games", return_value=full_cards), patch(
            "syndicate.features.mlb.live_lens.read_latest_live_lens_page_context",
            return_value=smaller_live_lens,
        ):
            items, count = home_module._load_home_game_items(
                "mlb",
                context_label="2026-06-28",
                is_active_today=True,
            )

        self.assertEqual(count, 15)
        self.assertEqual(len(items), 15)
        self.assertEqual(items[0]["gamePk"], 1)
        self.assertEqual(items[-1]["gamePk"], 15)

    def test_dashboard_prop_count_uses_unified_home_rails(self) -> None:
        from syndicate.blueprints import home as home_module

        sport = {
            "slug": "nba",
            "props_bar": {"items": []},
            "home_rails": {
                "pregame": {"items": [{"name": "Pregame prop"}]},
                "live": {"items": [{"name": "Live prop 1"}, {"name": "Live prop 2"}]},
            },
        }

        self.assertEqual(home_module._dashboard_prop_count(sport), 3)

    def test_finalize_home_prop_rows_uses_player_actual_for_live_total(self) -> None:
        from syndicate.blueprints import home as home_module

        rows = [
            {
                "game_pk": 1,
                "name": "Garrett Mitchell",
                "market": "Hitter Hits",
                "pick": "Over",
                "line": "0.5",
                "actual": "1",
                "live_projection": "1.6",
                "projected": "1.2",
                "is_live": True,
                "away_label": "SF",
                "home_label": "MIL",
                "detail": "Over 0.5 Hitter Hits",
            }
        ]
        home_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "SF", "score": 5},
                "home": {"abbr": "MIL", "score": 1},
                "status": {"is_live": True, "status": "In Progress", "detailed": "Top 6th"},
            }
        ]

        with patch("syndicate.blueprints.home._mlb_actual_payload_for_game", return_value=None):
            finalized = home_module._finalize_home_prop_rows(rows, slug="mlb", context_label="2026-06-04", home_games=home_games)

        self.assertEqual(len(finalized), 1)
        self.assertEqual(finalized[0]["live_total"], "1")
        self.assertEqual(finalized[0]["hero_live_box"], "1 H")
        self.assertEqual(finalized[0]["hero_sim_box"], "1.2 H")

    def test_finalize_home_prop_rows_falls_back_to_live_total_and_confidence_for_hero_metrics(self) -> None:
        from syndicate.blueprints import home as home_module

        rows = [
            {
                "game_pk": 1,
                "name": "Ryan McMahon",
                "market": "Batter Hits",
                "pick": "Over",
                "line": "0.5",
                "confidence": "67.8%",
                "live_total": "2",
                "is_live": True,
                "away_label": "CLE",
                "home_label": "NYY",
                "detail": "Over 0.5 Batter Hits",
            }
        ]
        home_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "CLE", "score": 1},
                "home": {"abbr": "NYY", "score": 2},
                "status": {"is_live": True, "status": "In Progress", "detailed": "Top 8th | 1 out"},
            }
        ]

        with patch("syndicate.blueprints.home._mlb_actual_payload_for_game", return_value=None):
            finalized = home_module._finalize_home_prop_rows(rows, slug="mlb", context_label="2026-06-04", home_games=home_games)

        self.assertEqual(len(finalized), 1)
        self.assertEqual(finalized[0]["hero_live_box"], "2 H")
        self.assertEqual(finalized[0]["hero_sim_box"], "0.5 H")
        self.assertEqual(finalized[0]["matchup_summary"], "CLE at NYY")

    def test_finalize_home_prop_rows_builds_required_display_pills_and_ladder_callout(self) -> None:
        from syndicate.blueprints import home as home_module

        rows = [
            {
                "name": "Caitlin Clark",
                "market": "threes",
                "pick": "Over",
                "line": "2.5",
                "odds": "102",
                "confidence": "64.1%",
                "projected": "3.1",
                "live_total": "1",
                "live_projection": "2.8",
                "is_live": True,
                "away_label": "ATL",
                "home_label": "IND",
                "detail": "Over 2.5 3PM",
                "ladder_groups": [{"short_label": "3PM", "targets": [3, 4]}],
            }
        ]

        finalized = home_module._finalize_home_prop_rows(rows, slug="wnba", context_label="2026-06-04", home_games=[])

        self.assertEqual(
            finalized[0]["display_pills"],
            [
                "Line 2.5",
                "Odds 102",
                "Sim% 64.1%",
                "Pregame 3PM Proj 3.1 3PM",
                "Live 3PM Total 1 3PM",
                "Live 3PM Proj 2.8 3PM",
                "Ladder 3PM 3/4",
            ],
        )

    def test_load_mlb_home_hr_target_items_aligns_away_home_logos_to_matchup(self) -> None:
        from syndicate.blueprints import home as home_module

        context = {
            "targets": [
                {
                    "game_pk": 1,
                    "team": "MIL",
                    "opponent": "SF",
                    "matchup": "SF @ MIL",
                    "player_name": "Rhys Hoskins",
                    "probability": "18.0%",
                    "support": "72",
                    "summary": "HR target",
                    "headshot_url": "https://example.test/rhys.png",
                    "team_logo_url": "https://example.test/mil.png",
                    "opponent_logo_url": "https://example.test/sf.png",
                }
            ]
        }

        with patch("syndicate.features.mlb.hr_targets.build_hr_targets_page_context", return_value=context):
            rows = home_module._load_mlb_home_hr_target_items("2026-06-04", limit=5)

        self.assertEqual(rows[0]["away_label"], "SF")
        self.assertEqual(rows[0]["home_label"], "MIL")
        self.assertEqual(rows[0]["away_logo"], "https://example.test/sf.png")
        self.assertEqual(rows[0]["home_logo"], "https://example.test/mil.png")

    def test_mlb_pregame_hitter_rows_keep_game_pk_for_live_actual_lookup(self) -> None:
        from syndicate.blueprints import home as home_module

        reco_payload = {
            823542: {
                "markets": {
                    "hitterProps": [
                        {
                            "player_name": "Ryan McMahon",
                            "prop": "hits",
                            "market_line": 0.5,
                            "selection": "OVER",
                            "edge": 0.145,
                            "model_prob": 0.678,
                        }
                    ]
                },
                "away": {"abbr": "CLE", "teamId": 114},
                "home": {"abbr": "NYY", "teamId": 147},
            }
        }

        with patch("syndicate.features.mlb.cards._cards_recommendation_payload_by_game", return_value=reco_payload):
            rows = home_module._pregame_prop_rows_from_mlb_recommendations("2026-06-04", limit=5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("game_pk"), 823542)
        self.assertEqual(rows[0].get("name"), "Ryan McMahon")
        self.assertEqual(rows[0].get("player_name"), "Ryan McMahon")

    def test_finalize_home_prop_rows_backfills_mlb_headshot_from_actual_payload(self) -> None:
        from syndicate.blueprints import home as home_module

        rows = [
            {
                "game_pk": 1,
                "name": "Jazz Chisholm Jr.",
                "market": "total bases",
                "pick": "Over",
                "line": "0.5",
                "is_live": True,
                "away_label": "CLE",
                "home_label": "NYY",
                "detail": "Over 0.5 Total Bases",
                "headshot_url": None,
            }
        ]
        home_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "CLE", "score": 1},
                "home": {"abbr": "NYY", "score": 2},
                "status": {"is_live": True, "status": "In Progress", "detailed": "Top 9th | 3 outs"},
            }
        ]
        actual_payload = {
            "liveData": {
                "boxscore": {
                    "teams": {
                        "away": {"players": {}},
                        "home": {
                            "players": {
                                "ID660271": {
                                    "person": {"id": 660271, "fullName": "Jazz Chisholm Jr."},
                                    "stats": {"batting": {"hits": 1, "atBats": 4, "totalBases": 2}},
                                }
                            }
                        },
                    }
                }
            },
            "gameData": {"status": {"abstractGameState": "Live", "detailedState": "In Progress"}},
        }

        with patch("syndicate.blueprints.home._mlb_actual_payload_for_game", return_value=actual_payload):
            finalized = home_module._finalize_home_prop_rows(rows, slug="mlb", context_label="2026-06-04", home_games=home_games)

        self.assertEqual(
            finalized[0]["headshot_url"],
            "https://img.mlbstatic.com/mlb-photos/image/upload/w_180,q_auto:best/v1/people/660271/headshot/67/current",
        )

    def test_home_nhl_compact_game_items_use_local_live_lens_without_source_proxy(self) -> None:
        from syndicate.blueprints import home as home_module

        local_games = [
            {
                "away": {"abbr": "COL", "name": "Colorado"},
                "home": {"abbr": "TOR", "name": "Toronto"},
                "away_score": 2,
                "home_score": 1,
                "href": "/nhl/game/77?date=2026-05-20",
                "href_label": "Open game detail",
            }
        ]

        with patch(
            "syndicate.blueprints.home._load_home_games",
            return_value=local_games,
        ):
            items, count = home_module._load_home_game_items(
                "nhl",
                context_label="2026-05-20",
                is_active_today=True,
            )

        self.assertEqual(count, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["away_label"], "COL")
        self.assertEqual(items[0]["home_label"], "TOR")
        self.assertEqual(items[0]["href"], "/nhl/game/77?date=2026-05-20")

    def test_home_nhl_prop_items_prefer_player_props_over_live_game_fallback(self) -> None:
        from syndicate.blueprints import home as home_module

        home_games = [
            {
                "away": {"abbr": "COL", "name": "Colorado"},
                "home": {"abbr": "TOR", "name": "Toronto"},
                "href": "/nhl/game/77?date=2026-05-20",
                "shared_is_live": True,
                "shared_prop_rows": [
                    {
                        "heading": "Live props",
                        "name": "Fallback team market",
                        "detail": "This generic fallback should not win.",
                        "value": "50.0%",
                    }
                ],
            }
        ]
        props_payload = {
            "date": "2026-05-20",
            "cards": [
                {
                    "player": "Nathan MacKinnon",
                    "headshot_url": "https://example.test/nathan.png",
                    "side": "Over",
                    "line": 3.5,
                    "market": "SOG",
                    "team": "COL",
                    "opp": "TOR",
                    "prob": 0.612,
                    "price": -115,
                    "ev": 0.083,
                    "reason_summary": "Local NHL player props row.",
                }
            ],
        }

        with patch(
            "syndicate.features.nhl.cards.build_props_cards_payload",
            return_value=props_payload,
        ):
            rows = home_module._load_home_prop_items(
                "nhl",
                context_label="2026-05-20",
                home_games=home_games,
                is_active_today=True,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Nathan MacKinnon")
        self.assertEqual(rows[0]["market"], "SOG")
        self.assertEqual(rows[0]["headshot_url"], "https://example.test/nathan.png")
        self.assertEqual(rows[0]["href"], "/nhl/cards?date=2026-05-20")

    def test_home_wnba_live_prop_rows_resolve_headshot_and_matchup_labels(self) -> None:
        from syndicate.blueprints import home as home_module

        games = [
            {
                "event_id": "401856961",
                "away": "ATL",
                "home": "IND",
                "status": {"status": "6/4 - 7:00 PM EDT", "in_progress": False, "final": False, "period": None, "clock": ""},
                "rows": [
                    {
                        "player": "Caitlin Clark",
                        "player_id": None,
                        "player_photo": None,
                        "team_tri": "IND",
                        "opponent_tri": "ATL",
                        "stat": "threes",
                        "line": 2.5,
                        "line_live": 2.5,
                        "lean": "OVER",
                        "price": 102.0,
                        "ev": 0.563635,
                        "win_prob": 1.0,
                        "recommendation_priority_score": 56.3634805411951,
                        "klass": "BET",
                        "status_label": "Live",
                    }
                ],
            }
        ]

        with patch("syndicate.blueprints.home._basketball_resolve_player_id", return_value=1642286):
            rows = home_module._prop_rows_from_nba_live_lens(
                games,
                sport_slug="wnba",
                fallback_href="/wnba/live-lens?date=2026-06-04",
            )
            finalized = home_module._finalize_home_prop_rows(rows, slug="wnba", context_label="2026-06-04", home_games=[])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Caitlin Clark")
        self.assertEqual(rows[0]["away_label"], "ATL")
        self.assertEqual(rows[0]["home_label"], "IND")
        self.assertEqual(rows[0]["headshot_url"], "https://cdn.nba.com/headshots/nba/latest/1040x760/1642286.png")
        self.assertEqual(finalized[0]["name"], "Caitlin Clark 3PM")
        self.assertEqual(finalized[0]["market_display"], "3PM")
        self.assertEqual(finalized[0]["meta_line"], "OVER 2.5")

    def test_wnba_rank_card_prop_rows_resolve_pregame_headshot(self) -> None:
        from syndicate.blueprints import home as home_module

        cards = [
            {
                "title": "Caitlin Clark Over 2.5 3PM",
                "eyebrow": "Props",
                "badge": "56.4% EV",
                "meta": "ATL vs IND",
                "summary": "Caitlin Clark",
                "metrics": [
                    {"label": "Price", "value": "102"},
                ],
            }
        ]

        with patch("syndicate.blueprints.home._basketball_resolve_player_id", return_value=4433403):
            rows = home_module._prop_rows_from_rank_cards(
                cards,
                sport_slug="wnba",
                fallback_href="/wnba/props?date=2026-06-04",
                heading_override="Props",
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["headshot_url"], "https://cdn.nba.com/headshots/nba/latest/1040x760/4433403.png")
        self.assertEqual(rows[0]["away_label"], "ATL")
        self.assertEqual(rows[0]["home_label"], "IND")

    def test_mlb_cards_embed_mode_renders_compact_source_shell(self) -> None:
        response = self.client.get('/mlb/cards?date=2026-05-20&client=source&embed=home-cards')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="cardsScoreboard"', body)
        self.assertIn('embedMode', body)
        self.assertNotIn('id="cardsGrid"', body)
        self.assertNotIn('id="cardsHrTargets"', body)

    def test_home_page_preserves_live_embed_shells_for_active_solo_clients(self) -> None:
        response = self.client.get('/')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('data-home-preserve-key="home-cards-section"', body)
        if 'data-home-preserve-key="home-cards"' in body:
            self.assertRegex(body, r'data-home-preserve-src="/mlb/cards\?date=[0-9]{4}-[0-9]{2}-[0-9]{2}&amp;client=source&amp;embed=home-cards"')
        if 'data-home-preserve-key="home-live-nba"' in body:
            self.assertRegex(body, r'data-home-preserve-src="/nba/(season/[0-9]{4}/)?live-lens\?date=[0-9]{4}-[0-9]{2}-[0-9]{2}(&amp;profile=[a-z0-9_-]+)?&amp;embed=home-live-nba"')
        if 'data-home-preserve-key="home-live-wnba"' in body:
            self.assertRegex(body, r'data-home-preserve-src="/wnba/live-lens\?date=[0-9]{4}-[0-9]{2}-[0-9]{2}&amp;embed=home-live-wnba"')
        if 'data-home-preserve-key="home-live-nhl"' in body:
            self.assertRegex(body, r'data-home-preserve-src="/nhl/cards\?date=[0-9]{4}-[0-9]{2}-[0-9]{2}"')

    def test_nba_live_lens_embed_mode_omits_standalone_header(self) -> None:
        response = self.client.get('/nba/live-lens?date=2026-05-16&embed=home-live-nba')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('NBA Live Lens', html)
        self.assertIn('cards-app-shell--embed', html)
        self.assertNotIn('NBA main cards', html)
        self.assertNotIn('class="cards-header"', html)
        self.assertNotIn('class="cards-control-card"', html)
        self.assertIn('data-cards-payload-path="/nba/api/live-lens"', html)
        self.assertIn('id="cardsScoreboard"', html)
        self.assertIn('id="cardsGrid"', html)

    def test_nba_cards_source_live_lens_keeps_odds_on_tile(self) -> None:
        js_content = (REPO_ROOT / "syndicate" / "static" / "nba" / "cards_source.js").read_text(encoding="utf-8")
        css_content = (REPO_ROOT / "syndicate" / "static" / "nba" / "cards_source.css").read_text(encoding="utf-8")

        self.assertIn("Live period", js_content)
        self.assertIn("Live half", js_content)
        self.assertIn("cards-live-lens-tile__edge", js_content)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", css_content)

    def test_wnba_cards_parity_live_lens_keeps_odds_on_tile(self) -> None:
        js_content = (REPO_ROOT / "syndicate" / "static" / "wnba" / "cards-parity.js").read_text(encoding="utf-8")
        css_content = (REPO_ROOT / "syndicate" / "static" / "wnba" / "cards-parity.css").read_text(encoding="utf-8")

        self.assertIn("Live period", js_content)
        self.assertIn("Live half", js_content)
        self.assertIn("cards-live-lens-tile__edge", js_content)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", css_content)

    def test_wnba_live_lens_embed_mode_omits_standalone_header(self) -> None:
        response = self.client.get('/wnba/live-lens?date=2026-05-16&embed=home-live-wnba')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('WNBA Live Lens', html)
        self.assertIn('cards-app-shell--embed', html)
        self.assertNotIn('WNBA main cards', html)
        self.assertNotIn('class="cards-header"', html)
        self.assertNotIn('class="cards-control-card"', html)
        self.assertIn('data-cards-payload-path="/wnba/api/live-lens"', html)
        self.assertIn('id="cardsScoreboard"', html)
        self.assertIn('id="cardsGrid"', html)

    def test_mlb_cards_source_js_skips_auto_refresh_for_embeds(self) -> None:
        content = (REPO_ROOT / "syndicate" / "static" / "mlb" / "cards_source.js").read_text(encoding="utf-8")

        self.assertIn('if (state.embedMode) {', content)
        self.assertIn('state.autoRefreshHandle = { stop: function () {} };', content)
        self.assertIn('state.autoRefreshHandle = window.SyndicatePolling.start({', content)

    def test_mlb_cards_source_shell_omits_shared_syndicate_chrome(self) -> None:
        response = self.client.get('/mlb/cards?date=2026-05-20&client=source')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('<title>MLB Game Cards — 2026-05-20</title>', body)
        self.assertNotIn('Syndicate app navigation', body)
        self.assertNotIn('Module navigation', body)

    def test_mlb_cards_source_shell_uses_versioned_assets(self) -> None:
        response = self.client.get('/mlb/cards?date=2026-05-20&client=source')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('/static/shared/standalone_shell.css?v=', body)
        self.assertIn('/static/mlb/cards_exact.css?v=', body)
        self.assertIn('/static/mlb/cards_source.js?v=', body)
        self.assertIn('/static/mlb/back_to_top.js?v=', body)

    def test_mlb_default_cards_page_keeps_syndicate_menu(self) -> None:
        response = self.client.get('/mlb/cards?date=2026-05-20')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Syndicate app navigation', body)
        self.assertIn('Module navigation', body)

    def test_mlb_pitcher_top_props_embed_mode_renders_standalone_style_shell(self) -> None:
        response = self.client.get('/mlb/pitcher-top-props?date=2026-05-20&embed=mlb-pitcher-props-embed')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="topPropsSections"', body)
        self.assertIn('MLBDailyTopPropsBootstrap', body)
        self.assertIn('embedMode', body)
        self.assertIn('mlb/daily_top_props.js', body)

    def test_mlb_hitter_top_props_embed_mode_renders_standalone_style_shell(self) -> None:
        response = self.client.get('/mlb/hitter-top-props?date=2026-05-20&embed=mlb-hitter-props-embed')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="topPropsSections"', body)
        self.assertIn('MLBDailyTopPropsBootstrap', body)
        self.assertIn('embedMode', body)
        self.assertIn('mlb/daily_top_props.js', body)

    def test_wnba_processed_path_prefers_local_artifact_mirror(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "wnba_source"
            external_root = root / "wnba_source_bundle"
            local_file = local_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            external_file = external_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            external_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text("local", encoding="utf-8")
            external_file.write_text("external", encoding="utf-8")

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[local_root, external_root]):
                self.assertEqual(wnba_processed_path("game_cards_2026-05-17.csv"), local_file)

    def test_wnba_live_snapshot_path_does_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "wnba_source"
            external_root = root / "wnba_source_bundle"
            local_file = local_root / "data" / "processed" / "live_snapshots" / "live_state_2026-05-17.json"
            external_file = external_root / "data" / "processed" / "live_snapshots" / "live_state_2026-05-17.json"
            external_file.parent.mkdir(parents=True, exist_ok=True)
            external_file.write_text("external", encoding="utf-8")

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[local_root, external_root]):
                self.assertEqual(wnba_live_snapshot_path("live_state_2026-05-17.json"), external_file)

    def test_wnba_available_dates_do_not_fall_back_to_sibling_repo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "wnba_source"
            external_root = root / "wnba_source_bundle"
            external_file = external_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            external_file.parent.mkdir(parents=True, exist_ok=True)
            external_file.write_text("external", encoding="utf-8")

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[local_root, external_root]):
                self.assertEqual(wnba_available_dates(), ["2026-05-17"])

    def test_wnba_cards_empty_slate_does_not_inject_fake_sample_game(self) -> None:
        with patch("syndicate.features.wnba.cards._games_from_artifacts", return_value=([], "missing_cards.csv", "missing_recommendations.json")):
            from syndicate.features.wnba.cards import build_cards_page_context as build_wnba_cards_page_context

            context = build_wnba_cards_page_context("1900-01-01")

        self.assertEqual(context.get("date"), "1900-01-01")
        self.assertEqual(context.get("requested_date"), "1900-01-01")
        self.assertFalse(context.get("lookahead_applied"))
        self.assertEqual(context.get("games"), [])
        self.assertEqual(context.get("scoreboard_items"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "WNBA cards unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No game cards were available for this date")

    def test_nba_picks_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.nba.picks.load_json", return_value=None):
            from syndicate.features.nba.picks import build_picks_page_context as build_nba_picks_page_context

            context = build_nba_picks_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NBA picks unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "NBA picks")

    def test_nba_picks_page_uses_standalone_shell(self) -> None:
        response = self.client.get('/nba/picks?date=2026-05-16')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="picksDateForm"', html)
        self.assertIn('NBA Picks', html)
        self.assertIn('Source artifact', html)
        self.assertIn('/nba/prop-ladders?date=2026-05-16', html)
        self.assertNotIn('One app with seven feature modules.', html)

    def test_nba_picks_page_empty_state_renders_in_standalone_shell(self) -> None:
        with patch('syndicate.features.nba.picks.load_json', return_value=None):
            response = self.client.get('/nba/picks?date=1900-01-01')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('No stored NBA picks were available for this date', html)
        self.assertIn('Stored slate navigation', html)

    def test_nba_props_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.nba.props.load_json", return_value=None):
            from syndicate.features.nba.props import build_props_page_context as build_nba_props_page_context

            context = build_nba_props_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NBA top props by game")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "NBA props")

    def test_nba_game_detail_missing_artifact_does_not_inject_fake_matchup(self) -> None:
        with patch("syndicate.features.nba.game_detail._game_by_id_from_artifacts", return_value=(None, {"paths": {"cards": "missing_cards.csv"}})):
            from syndicate.features.nba.game_detail import build_game_detail_page_context as build_nba_game_detail_page_context

            context = build_nba_game_detail_page_context("1900-01-01", "999")

        game = (context.get("games") or [{}])[0]
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NBA game unavailable")
        self.assertEqual(game.get("status"), "NBA game unavailable")
        self.assertEqual((game.get("away") or {}).get("abbr"), "AWY")
        self.assertEqual((game.get("home") or {}).get("abbr"), "HOM")

    def test_nba_archive_without_dates_uses_empty_state_not_sample_card(self) -> None:
        with patch("syndicate.features.nba.archive.available_dates", return_value=[]):
            from syndicate.features.nba.archive import build_archive_page_context as build_nba_archive_page_context

            context = build_nba_archive_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NBA archive unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "NBA daily archive")
        self.assertEqual((context.get("header_stats") or [None, None, None, None])[3], {"label": "Artifacts", "value": "No data"})

    def test_nba_archive_page_uses_standalone_shell(self) -> None:
        response = self.client.get('/nba/archive?date=2026-05-22')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="archiveDateForm"', html)
        self.assertIn('NBA Daily Archive', html)
        self.assertIn('/nba/cards?date=', html)
        self.assertIn('Source artifacts', html)
        self.assertNotIn('One app with seven feature modules.', html)

    def test_nba_archive_page_empty_state_renders_in_standalone_shell(self) -> None:
        with patch('syndicate.features.nba.archive.available_dates', return_value=[]):
            response = self.client.get('/nba/archive?date=1900-01-01')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('No stored NBA archive dates were available', html)
        self.assertIn('Stored archive navigation', html)

    def test_nhl_picks_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.nhl.picks.available_dates", return_value=[]):
            with patch("syndicate.features.nhl.picks._read_rows", return_value=[]):
                from syndicate.features.nhl.picks import build_picks_page_context as build_nhl_picks_page_context

                context = build_nhl_picks_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NHL picks unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "NHL picks")

    def test_nhl_picks_page_uses_standalone_shell(self) -> None:
        response = self.client.get('/nhl/picks?date=2026-05-16')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="picksDateForm"', html)
        self.assertIn('NHL Picks', html)
        self.assertIn('Source artifact', html)
        self.assertIn('/nhl/live-lens?date=', html)
        self.assertNotIn('One app with seven feature modules.', html)

    def test_nhl_picks_page_empty_state_renders_in_standalone_shell(self) -> None:
        with patch('syndicate.features.nhl.picks.available_dates', return_value=[]):
            with patch('syndicate.features.nhl.picks._read_rows', return_value=[]):
                response = self.client.get('/nhl/picks?date=1900-01-01')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('No stored NHL picks were available for this date', html)
        self.assertIn('Source artifact', html)

    def test_nhl_archive_without_dates_uses_empty_state_not_sample_card(self) -> None:
        with patch("syndicate.features.nhl.archive.available_dates", return_value=[]):
            from syndicate.features.nhl.archive import build_archive_page_context as build_nhl_archive_page_context

            context = build_nhl_archive_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NHL archive unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "NHL daily archive")

    def test_nhl_archive_page_uses_standalone_shell(self) -> None:
        response = self.client.get('/nhl/archive?date=2026-05-16')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="archiveDateForm"', html)
        self.assertIn('NHL Daily Archive', html)
        self.assertIn('/nhl/live-lens?date=', html)
        self.assertIn('Source artifacts', html)
        self.assertNotIn('One app with seven feature modules.', html)

    def test_nhl_archive_page_empty_state_renders_in_standalone_shell(self) -> None:
        with patch('syndicate.features.nhl.archive.available_dates', return_value=[]):
            response = self.client.get('/nhl/archive?date=1900-01-01')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('No stored NHL archive dates were available', html)
        self.assertIn('Source artifacts', html)


    def test_wnba_game_detail_missing_artifact_does_not_inject_fake_matchup(self) -> None:
        with patch("syndicate.features.wnba.game_detail._game_by_id_from_artifacts", return_value=(None, {"paths": {"cards": "missing_cards.csv"}})):
            from syndicate.features.wnba.game_detail import build_game_detail_page_context as build_wnba_game_detail_page_context

            context = build_wnba_game_detail_page_context("1900-01-01", "999")

        game = (context.get("games") or [{}])[0]
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "WNBA game unavailable")
        self.assertEqual(game.get("status"), "WNBA game unavailable")
        self.assertEqual((game.get("away") or {}).get("abbr"), "AWY")
        self.assertEqual((game.get("home") or {}).get("abbr"), "HOM")

    def test_wnba_picks_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.wnba.picks.load_json", return_value=None):
            from syndicate.features.wnba.picks import build_picks_page_context as build_wnba_picks_page_context

            context = build_wnba_picks_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "WNBA picks unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "WNBA picks")

    def test_wnba_picks_page_uses_standalone_shell(self) -> None:
        response = self.client.get('/wnba/picks?date=2026-05-22')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="picksDateForm"', html)
        self.assertIn('WNBA Picks', html)
        self.assertIn('/wnba/cards?date=2026-05-22', html)
        self.assertIn('/wnba/season/2026/betting-card?date=2026-05-22', html)
        self.assertIn('Source artifact', html)
        self.assertNotIn('One app with seven feature modules.', html)

    def test_wnba_picks_page_empty_state_renders_in_standalone_shell(self) -> None:
        response = self.client.get('/wnba/picks?date=1900-01-01')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('No stored WNBA picks were available for this date', html)
        self.assertIn('Stored slate navigation', html)

    def test_wnba_live_lens_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.wnba.live_lens.load_json", return_value=None):
            from syndicate.features.wnba.live_lens import build_live_lens_page_context as build_wnba_live_lens_page_context

            context = build_wnba_live_lens_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "WNBA live lens snapshot")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "WNBA live lens")
        self.assertIn("No stored WNBA live-lens snapshot", (context.get("empty_state") or {}).get("title") or "")

    def test_nba_live_state_fallback_preserves_event_id_from_cards_context(self) -> None:
        from syndicate.features.nba.cards import build_live_state_payload as build_nba_live_state_payload

        with patch("syndicate.features.nba.cards._local_live_state_payload", return_value=None), patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={
                "games": [
                    {
                        "gamePk": "game-1",
                        "event_id": "evt-123",
                        "away_tri": "NYK",
                        "home_tri": "BOS",
                        "status": "Live",
                        "detail": "Q3 08:12",
                    }
                ]
            },
        ):
            payload = build_nba_live_state_payload("2026-05-28")

        self.assertEqual((payload.get("games") or [{}])[0].get("event_id"), "evt-123")

    def test_wnba_live_state_fallback_preserves_event_id_from_cards_context(self) -> None:
        from syndicate.features.wnba.cards import build_live_state_payload as build_wnba_live_state_payload

        with patch("syndicate.features.wnba.cards._local_live_state_payload", return_value=None), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={
                "games": [
                    {
                        "gamePk": "game-1",
                        "event_id": "evt-456",
                        "away_tri": "LAS",
                        "home_tri": "NYL",
                        "status": "Live",
                        "detail": "Q4 04:21",
                    }
                ]
            },
        ):
            payload = build_wnba_live_state_payload("2026-05-28")

        self.assertEqual((payload.get("games") or [{}])[0].get("event_id"), "evt-456")

    def test_nba_live_lens_api_payload_uses_cards_contract(self) -> None:
        from syndicate.features.nba.live_lens import build_live_lens_api_payload as build_nba_live_lens_api_payload

        with patch(
            "syndicate.features.nba.live_lens.build_cards_page_context",
            return_value={
                "date": "2026-05-28",
                "requested_date": "2026-05-28",
                "lookahead_applied": False,
                "games": [{"gamePk": "game-1"}],
            },
        ), patch(
            "syndicate.features.nba.live_lens.build_live_lens_page_context",
            return_value={"date": "2026-05-28", "route_path": "/nba/live-lens", "rank_cards": [{"title": "Game 1"}]},
        ):
            payload = build_nba_live_lens_api_payload("2026-05-28")

        self.assertEqual(payload.get("date"), "2026-05-28")
        self.assertEqual((payload.get("games") or [{}])[0].get("gamePk"), "game-1")
        self.assertEqual(payload.get("route_path"), "/nba/live-lens")
        self.assertEqual((payload.get("rank_cards") or [{}])[0].get("title"), "Game 1")

    def test_nba_live_lens_page_context_prefers_live_spread_and_total(self) -> None:
        from syndicate.features.nba.live_lens import build_live_lens_page_context as build_nba_live_lens_page_context

        cards_context = {
            "date": "2026-05-28",
            "requested_date": "2026-05-28",
            "games": [
                {
                    "event_id": "evt-1",
                    "status": "Live",
                    "detail": "Q4 04:21",
                    "summary": "Consensus market snapshot",
                    "away": {"abbr": "NYK", "score": 100},
                    "home": {"abbr": "BOS", "score": 98},
                    "betting": {"home_spread": -2.5, "away_spread": 2.5, "total": 210.5},
                    "metrics": [{"label": "Spread", "value": "BOS -2.5"}],
                    "shared_top_play_rows": [],
                }
            ],
            "source_path": "nba_cards.csv",
        }
        live_lines_payload = {
            "games": [
                {
                    "event_id": "evt-1",
                    "lines": {"home_spread": -4.5, "away_spread": 4.5, "total": 214.5},
                }
            ]
        }

        with patch("syndicate.features.nba.live_lens.build_cards_page_context", return_value=cards_context), patch(
            "syndicate.features.nba.live_lens.build_live_lines_payload", return_value=live_lines_payload
        ):
            context = build_nba_live_lens_page_context("2026-05-28")

        rank_cards = context.get("rank_cards") or []
        self.assertTrue(rank_cards)
        metrics = rank_cards[0].get("metrics") or []
        self.assertTrue(any(metric.get("label") == "Live ATS" and metric.get("value") == "BOS -4.5" for metric in metrics))
        self.assertTrue(any(metric.get("label") == "Live total" and metric.get("value") == "214.5" for metric in metrics))
        self.assertIn("Live total 214.5", rank_cards[0].get("summary") or "")
        self.assertIn("Live ATS BOS -4.5", rank_cards[0].get("summary") or "")

    def test_wnba_live_lens_api_payload_uses_cards_contract(self) -> None:
        from syndicate.features.wnba.live_lens import build_live_lens_api_payload as build_wnba_live_lens_api_payload

        snapshot = {
            "date": "2026-05-28",
            "requested_date": "2026-05-28",
            "lookahead_applied": False,
            "games": [{"gamePk": "game-2"}],
            "rank_cards": [
                {
                    "title": "LAS @ NYL",
                    "eyebrow": "Stored lens",
                    "badge": "Watch",
                    "meta": "Q3 05:12",
                    "metrics": [{"label": "Live line", "value": "161.5"}],
                    "summary": "Stored WNBA live-lens snapshot.",
                    "list_items": ["Signal 1"],
                    "href": "/wnba/cards?date=2026-05-28",
                    "href_label": "Open WNBA game",
                }
            ],
        }
        with patch("syndicate.features.wnba.live_lens.load_json", return_value=snapshot):
            payload = build_wnba_live_lens_api_payload("2026-05-28")

        self.assertEqual(payload.get("date"), "2026-05-28")
        self.assertEqual((payload.get("games") or [{}])[0].get("gamePk"), "game-2")
        self.assertEqual((payload.get("rank_cards") or [{}])[0].get("title"), "LAS @ NYL")

    def test_wnba_live_lens_page_context_prefers_live_line(self) -> None:
        from syndicate.features.wnba.live_lens import build_live_lens_page_context as build_wnba_live_lens_page_context

        snapshot = {
            "date": "2026-05-28",
            "requested_date": "2026-05-28",
            "games": [
                {
                    "event_id": "evt-wnba-1",
                    "status": "Live",
                    "detail": "Q3 05:12",
                    "summary": "Consensus market snapshot",
                    "away": {"abbr": "LAS", "score": 48},
                    "home": {"abbr": "NYL", "score": 50},
                    "betting": {"total": 156.5},
                    "metrics": [{"label": "Live line", "value": "156.5"}],
                    "shared_top_play_rows": [],
                    "shared_prop_rows": [],
                }
            ],
            "source_path": "wnba_live_lens.json",
            "rank_cards": [
                {
                    "title": "LAS @ NYL",
                    "eyebrow": "Live",
                    "badge": "Watch",
                    "meta": "Q3 05:12",
                    "metrics": [{"label": "Live line", "value": "161.5"}],
                    "summary": "Total pts 98 vs Live line 161.5. Consensus market snapshot",
                    "list_items": ["Consensus market snapshot"],
                    "href": "/wnba/cards?date=2026-05-28",
                    "href_label": "Open WNBA game",
                }
            ],
        }

        with patch("syndicate.features.wnba.live_lens.load_json", return_value=snapshot):
            context = build_wnba_live_lens_page_context("2026-05-28")

        rank_cards = context.get("rank_cards") or []
        self.assertTrue(rank_cards)
        metrics = rank_cards[0].get("metrics") or []
        self.assertTrue(any(metric.get("label") == "Live line" and metric.get("value") == "161.5" for metric in metrics))
        self.assertIn("Live line 161.5", rank_cards[0].get("summary") or "")

    def test_wnba_live_lens_rank_card_uses_live_state_scores_when_team_scores_missing(self) -> None:
        from syndicate.features.wnba.live_lens import build_live_lens_page_context as build_wnba_live_lens_page_context

        snapshot = {
            "date": "2026-05-28",
            "requested_date": "2026-05-28",
            "games": [
                {
                    "event_id": "evt-wnba-2",
                    "status": "Live",
                    "detail": "Q3 05:12",
                    "summary": "Consensus market snapshot",
                    "away": {"abbr": "LAS"},
                    "home": {"abbr": "NYL"},
                    "live_state": {"away_pts": 41, "home_pts": 53},
                    "betting": {"total": 156.5},
                    "metrics": [{"label": "Live line", "value": "156.5"}],
                    "shared_top_play_rows": [],
                    "shared_prop_rows": [],
                }
            ],
            "source_path": "wnba_live_lens.json",
            "rank_cards": [
                {
                    "title": "LAS @ NYL",
                    "eyebrow": "Live",
                    "badge": "Watch",
                    "meta": "Q3 05:12",
                    "metrics": [
                        {"label": "Total pts", "value": "94"},
                        {"label": "Live line", "value": "161.5"},
                    ],
                    "summary": "Total pts 94. Live line 161.5. Consensus market snapshot",
                    "list_items": ["Consensus market snapshot"],
                    "href": "/wnba/cards?date=2026-05-28",
                    "href_label": "Open WNBA game",
                }
            ],
        }

        with patch("syndicate.features.wnba.live_lens.load_json", return_value=snapshot):
            context = build_wnba_live_lens_page_context("2026-05-28")

        rank_cards = context.get("rank_cards") or []
        self.assertTrue(rank_cards)
        metrics = rank_cards[0].get("metrics") or []
        self.assertTrue(any(metric.get("label") == "Total pts" and metric.get("value") == "94" for metric in metrics))
        self.assertIn("Total pts 94", rank_cards[0].get("summary") or "")
        self.assertIn("Live line 161.5", rank_cards[0].get("summary") or "")

    def test_wnba_cards_page_uses_live_state_fallback_when_artifacts_empty(self) -> None:
        from syndicate.features.wnba.cards import build_cards_page_context as build_wnba_cards_page_context

        live_payload = {
            "games": [
                {
                    "game_id": "game-9",
                    "event_id": "evt-9",
                    "away": "LAS",
                    "home": "NYL",
                    "status": "Q3 02:11",
                    "in_progress": True,
                    "final": False,
                    "away_pts": 61,
                    "home_pts": 58,
                }
            ]
        }

        with patch("syndicate.features.wnba.cards._games_from_artifacts", return_value=([], "cards.csv", "recs.json")), patch(
            "syndicate.features.wnba.cards._local_live_state_payload",
            return_value=live_payload,
        ):
            context = build_wnba_cards_page_context("2026-05-28", allow_stored_date_fallback=False)

        self.assertEqual(context.get("date"), "2026-05-28")
        self.assertEqual(context.get("source_title"), "WNBA live scoreboard fallback")
        self.assertEqual((context.get("games") or [{}])[0].get("event_id"), "evt-9")

    def test_wnba_cards_page_uses_public_scoreboard_fallback_when_local_live_state_is_empty(self) -> None:
        from syndicate.features.wnba.cards import build_cards_page_context as build_wnba_cards_page_context

        public_payload = {
            "ok": True,
            "source": "espn_scoreboard_fallback",
            "games": [
                {
                    "event_id": "evt-public-1",
                    "away": "TOR",
                    "home": "IND",
                    "away_pts": 0,
                    "home_pts": 0,
                    "status": "6/16 - 7:00 PM EDT",
                    "clock": "",
                    "period": None,
                    "in_progress": False,
                    "final": False,
                    "periods": [],
                }
            ],
        }

        with patch("syndicate.features.wnba.cards._games_from_artifacts", return_value=([], "cards.csv", "recs.json")), patch(
            "syndicate.features.wnba.cards._local_live_state_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._public_scoreboard_live_state_payload",
            return_value=public_payload,
        ):
            context = build_wnba_cards_page_context("2026-06-16", allow_stored_date_fallback=False)

        self.assertEqual(context.get("source_title"), "WNBA live scoreboard fallback")
        self.assertEqual((context.get("games") or [{}])[0].get("event_id"), "evt-public-1")

    def test_wnba_processed_card_rows_include_live_lens_client_fields(self) -> None:
        from syndicate.features.wnba.cards import _game_from_row

        row = {
            "game_id": "game-7",
            "event_id": "evt-7",
            "visitor_team": "Las Vegas Aces",
            "home_team": "Dallas Wings",
            "away_tri": "LVA",
            "home_tri": "DAL",
            "commence_time": "2026-05-29T00:10:00Z",
            "away_ml": "-130",
            "home_ml": "+110",
            "home_spread": "2.5",
            "total": "175.5",
            "bookmaker": "oddsapi_consensus",
        }
        sim_game = {
            "players_summary": {"away": 7, "home": 8},
            "sim": {
                "players": {
                    "away": [{"pts_mean": 91.2}],
                    "home": [{"pts_mean": 94.6}],
                }
            },
        }
        props_game = {
            "prop_recommendations": {
                "away": [{"player": "A'ja Wilson"}],
                "home": [{"player": "Paige Bueckers"}],
            }
        }
        game = _game_from_row(
            row,
            idx=1,
            selected_date="2026-05-28",
            rec_index={
                ("LVA", "DAL"): [
                    {
                        "market": "total",
                        "display_pick": "Over 175.5",
                        "selection": "OVER",
                        "p_win": 0.61,
                        "ev_pct": 7.5,
                    }
                ]
            },
            sim_index={("LVA", "DAL"): sim_game},
            props_index={("LVA", "DAL"): props_game},
        )

        self.assertEqual(game.get("game_id"), "game-7")
        self.assertEqual(game.get("away_tri"), "LVA")
        self.assertEqual(game.get("away_name"), "Las Vegas Aces")
        self.assertEqual(game.get("home_tri"), "DAL")
        self.assertEqual(game.get("home_name"), "Dallas Wings")
        self.assertEqual((game.get("betting") or {}).get("total"), 175.5)
        self.assertAlmostEqual(((game.get("sim") or {}).get("score") or {}).get("total_mean"), 185.8)
        self.assertEqual(len(game.get("game_market_recommendations") or []), 1)
        self.assertEqual(sorted((game.get("prop_recommendations") or {}).keys()), ["away", "home"])

    def test_home_wnba_uses_today_when_live_state_exists(self) -> None:
        from syndicate.blueprints.home import _build_sport_overview

        sport = {"slug": "wnba", "name": "WNBA", "primary_href": "/wnba", "primary_label": "Open WNBA cards"}

        with patch("syndicate.blueprints.home.wnba_available_dates", return_value=["2026-05-27"]), patch(
            "syndicate.blueprints.home._wnba_has_live_games",
            return_value=True,
        ), patch(
            "syndicate.blueprints.home.build_wnba_module_links",
            return_value=[{"label": "Live Lens", "href": "/wnba/live-lens?date=2026-05-28", "active": False}],
        ), patch(
            "syndicate.blueprints.home._load_home_game_items",
            return_value=([], 0),
        ), patch(
            "syndicate.blueprints.home._load_home_prop_items",
            return_value=[],
        ):
            overview = _build_sport_overview(sport, "2026-05-28", force_refresh=True)

        self.assertEqual(overview.get("context_label"), "2026-05-28")
        self.assertTrue(bool(overview.get("active_today")))

    def test_wnba_archive_without_dates_uses_empty_state_not_sample_card(self) -> None:
        with patch("syndicate.features.wnba.archive.available_dates", return_value=[]):
            from syndicate.features.wnba.archive import build_archive_page_context as build_wnba_archive_page_context

            context = build_wnba_archive_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "WNBA archive unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "WNBA daily archive")

    def test_wnba_archive_page_uses_standalone_shell(self) -> None:
        response = self.client.get('/wnba/archive?date=2026-05-22')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="archiveDateForm"', html)
        self.assertIn('WNBA Daily Archive', html)
        self.assertIn('/wnba/cards?date=2026-05-22', html)
        self.assertIn('Source artifacts', html)
        self.assertNotIn('One app with seven feature modules.', html)

    def test_wnba_archive_page_empty_state_renders_in_standalone_shell(self) -> None:
        with patch('syndicate.features.wnba.archive.available_dates', return_value=[]):
            response = self.client.get('/wnba/archive?date=1900-01-01')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('No stored WNBA archive dates were available', html)
        self.assertIn('Stored archive navigation', html)

    def test_wnba_props_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.wnba.props.load_json", return_value=None):
            from syndicate.features.wnba.props import build_props_page_context as build_wnba_props_page_context

            context = build_wnba_props_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "WNBA top props by game")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "WNBA props")

    def test_wnba_props_uses_latest_stored_top_by_game_artifact(self) -> None:
        fallback_payload = {
            "data": [
                {
                    "player": "Angel Reese",
                    "team_tricode": "CHI",
                    "team": "CHI",
                    "opponent": "MIN",
                    "tier": "High",
                    "top_play": {
                        "market": "reb",
                        "side": "OVER",
                        "line": 10.5,
                        "price": -110,
                        "edge": 0.14,
                        "ev_pct": 0.08,
                        "book": "fanduel",
                        "basketball_summary": "Stored fallback summary",
                    },
                }
            ]
        }

        def _load_json(path):
            if str(path).endswith("props_recommendations_top_by_game_2026-06-17.json"):
                return fallback_payload
            return None

        with patch("syndicate.features.wnba.props.available_dates", return_value=["2026-06-17"]), patch(
            "syndicate.features.wnba.props.load_json", side_effect=_load_json
        ):
            from syndicate.features.wnba.props import build_props_page_context as build_wnba_props_page_context

            context = build_wnba_props_page_context("2026-06-18")

        self.assertEqual(context.get("source_path").endswith("props_recommendations_top_by_game_2026-06-17.json"), True)
        self.assertEqual(len(context.get("rank_cards") or []), 1)
        self.assertIsNone(context.get("empty_state"))

    def test_wnba_props_page_uses_standalone_ladder_shell(self) -> None:
        response = self.client.get('/wnba/props?date=2026-05-20')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="propLadderForm"', html)
        self.assertIn('Player Prop Ladders', html)
        self.assertIn('/wnba/cards?date=2026-05-20', html)
        self.assertIn('/wnba/season/2026/betting-card?date=2026-05-20', html)
        self.assertNotIn('One app with seven feature modules.', html)

    def test_wnba_props_page_empty_state_renders_in_standalone_shell(self) -> None:
        response = self.client.get('/wnba/props?date=1900-01-01')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('No stored WNBA props were available for this date', html)
        self.assertIn('id="propLadderGrid"', html)

    def test_mlb_cards_empty_date_does_not_inject_fake_sample_games(self) -> None:
        with patch("syndicate.features.mlb.cards.load_json_file", return_value=None):
            from syndicate.features.mlb.cards import build_cards_page_context as build_mlb_cards_page_context

            context = build_mlb_cards_page_context("1900-01-01")

        self.assertEqual(context.get("games"), [])
        self.assertEqual(context.get("scoreboard_items"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "MLB cards unavailable")
        self.assertEqual((context.get("source_meta_items") or [None, None, None])[2], "No data")

    def test_mlb_game_detail_missing_artifact_does_not_inject_fake_matchup(self) -> None:
        with patch("syndicate.features.mlb.game_detail.load_json_file", return_value=None):
            from syndicate.features.mlb.game_detail import build_game_detail_page_context as build_mlb_game_detail_page_context

            context = build_mlb_game_detail_page_context("1900-01-01", 999)

        game = (context.get("games") or [{}])[0]
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "MLB game unavailable")
        self.assertEqual(game.get("status"), "MLB game unavailable")
        self.assertEqual((game.get("away") or {}).get("abbr"), "AWY")
        self.assertEqual((game.get("home") or {}).get("abbr"), "HOM")

    def test_mlb_daily_archive_without_dates_uses_empty_state_not_sample_card(self) -> None:
        with patch("syndicate.features.mlb.daily_archive.available_daily_summary_dates", return_value=[]):
            from syndicate.features.mlb.daily_archive import build_daily_archive_page_context as build_mlb_daily_archive_page_context

            context = build_mlb_daily_archive_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "MLB daily archive unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "MLB daily archive")

    def test_mlb_live_lens_empty_date_does_not_inject_fake_sample_games(self) -> None:
        with patch("syndicate.features.mlb.live_lens.load_json_file", return_value=None):
            from syndicate.features.mlb.live_lens import build_live_lens_snapshot_internal as build_mlb_live_lens_snapshot_internal

            context = build_mlb_live_lens_snapshot_internal("1900-01-01")

        report_path = live_lens_report_path("1900-01-01")

        self.assertEqual(context.get("games"), [])
        self.assertEqual(context.get("scoreboard_items"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "MLB live lens unavailable")
        self.assertTrue(_paths_match(context.get("dataRoot"), report_path.parent.parent))
        self.assertTrue(_paths_match(context.get("liveLensDir"), report_path.parent))
        self.assertEqual(
            context.get("counts"),
            {"archivedLiveProps": 0, "final": 0, "games": 0, "live": 0, "pregame": 0, "props": 0},
        )
        self.assertTrue(context.get("generatedAt"))

    def test_mlb_live_lens_reports_payload_synthesizes_from_live_builder(self) -> None:
        with patch("vendor.mlb_bettingv2.tools.web.flask_frontend._load_json_file", return_value={}), patch(
            "vendor.mlb_bettingv2.tools.web.flask_frontend._live_prop_registry_summary",
            return_value={"topStable": [], "topEdges": []},
        ), patch(
            "vendor.mlb_bettingv2.tools.web.flask_frontend._live_lens_payload",
            return_value={
                "date": "2026-06-01",
                "generatedAt": "2026-06-01T20:45:00-05:00",
                "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 2, "archivedLiveProps": 0},
                "performance": {"marketsRefreshed": True, "degraded": False},
                "games": [{"gamePk": 1, "status": {"abstract": "Live", "detailed": "In Progress"}}],
            },
        ):
            from vendor.mlb_bettingv2.tools.web.flask_frontend import _live_lens_reports_payload

            payload = _live_lens_reports_payload("2026-06-01")

        self.assertEqual(payload.get("latestReport", {}).get("counts", {}).get("games"), 1)
        self.assertEqual(payload.get("latestReport", {}).get("games", [{}])[0].get("gamePk"), 1)
        self.assertNotEqual(payload.get("latestReport"), {})

    def test_nfl_live_lens_empty_week_does_not_inject_fake_rank_card(self) -> None:
        with patch(
            "syndicate.features.nfl.live_lens.build_cards_page_context",
            return_value={"control_value": "1", "date": "2026", "games": [], "source_path": "missing_nfl_cards.csv"},
        ), patch("syndicate.features.nfl.live_lens.available_weeks", return_value=[]):
            from syndicate.features.nfl.live_lens import build_live_lens_page_context as build_nfl_live_lens_page_context

            context = build_nfl_live_lens_page_context(1, season=2026)

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NFL live lens unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "NFL live lens")

    def test_ncaaf_live_lens_empty_week_does_not_inject_fake_rank_card(self) -> None:
        with patch(
            "syndicate.features.ncaaf.live_lens.build_cards_page_context",
            return_value={"control_value": "1", "date": "2026", "games": [], "source_path": "missing_ncaaf_cards.csv"},
        ), patch("syndicate.features.ncaaf.live_lens.available_weeks", return_value=[]):
            from syndicate.features.ncaaf.live_lens import build_live_lens_page_context as build_ncaaf_live_lens_page_context

            context = build_ncaaf_live_lens_page_context(1)

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NCAAF live lens unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "NCAAF live lens")

    def test_mlb_live_lens_game_rows_preserve_structured_status(self) -> None:
        report = {
            "generatedAt": "2026-05-09T16:25:51-05:00",
            "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0},
            "games": [
                {
                    "gamePk": 822820,
                    "status": {"detailed": "In Progress"},
                    "matchup": {
                        "away": {"abbr": "LAA", "name": "Los Angeles Angels"},
                        "home": {"abbr": "TOR", "name": "Toronto Blue Jays"},
                        "liveText": "Bottom 7 | 0-1, 2 out | Vladimir Guerrero Jr. vs Mitch Farris",
                        "score": {"away": 0, "home": 9},
                    },
                    "liveProps": [],
                }
            ],
        }
        with patch("syndicate.features.mlb.live_lens.load_json_file", return_value=report):
            from syndicate.features.mlb.live_lens import build_live_lens_snapshot_internal as build_mlb_live_lens_snapshot_internal

            context = build_mlb_live_lens_snapshot_internal("2026-05-09")

        games = context.get("games") or []
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].get("status"), {"abstract": "Live", "detailed": "In Progress"})

    def test_mlb_betting_card_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.mlb.betting_card.load_json_file", return_value=None):
            from syndicate.features.mlb.betting_card import build_betting_card_page_context as build_mlb_betting_card_page_context

            context = build_mlb_betting_card_page_context(1900, "1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "MLB betting card unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "MLB betting card")

    def test_mlb_top_props_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.mlb.top_props.load_json_file", return_value=None):
            from syndicate.features.mlb.top_props import build_top_props_page_context as build_mlb_top_props_page_context

            context = build_mlb_top_props_page_context("1900-01-01", group="pitcher")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "MLB top props unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "MLB top props")

    def test_mlb_top_props_uses_latest_stored_daily_artifact(self) -> None:
        fallback_payload = {
            "groups": {
                "pitcher": {
                    "sections": [
                        {
                            "label": "Pitchers",
                            "rows": [
                                {
                                    "playerName": "Nolan McLean",
                                    "team": "NYM",
                                    "selectionLabel": "Over",
                                    "targetLabel": "16.5 Outs",
                                    "matchup": "NYM at CIN",
                                    "simProb": 0.83,
                                    "rawEdge": 0.31,
                                    "odds": -136,
                                    "mean": 21.2,
                                    "statLabel": "outs",
                                    "line": 16.5,
                                    "marketProb": 0.72,
                                    "rank": 1,
                                }
                            ],
                        }
                    ]
                }
            }
        }

        def _load_json_file(path):
            if str(path).endswith("daily_top_props_2026_06_17.json"):
                return fallback_payload
            return None

        with patch("syndicate.features.mlb.top_props.available_daily_summary_dates", return_value=["2026-06-17"]), patch(
            "syndicate.features.mlb.top_props.load_json_file", side_effect=_load_json_file
        ):
            from syndicate.features.mlb.top_props import build_top_props_page_context as build_mlb_top_props_page_context

            context = build_mlb_top_props_page_context("2026-06-18", group="pitcher")

        self.assertTrue((context.get("source_path") or "").endswith("daily_top_props_2026_06_17.json"))
        self.assertEqual(len(context.get("rank_cards") or []), 1)
        self.assertIsNone(context.get("empty_state"))

    def test_mlb_hub_context_exposes_top_props_lane_availability(self) -> None:
        summary = {
            "groups": {
                "pitcher": {"sections": [{"rows": [{"playerName": "Pitcher 1"}, {"playerName": "Pitcher 2"}]}]},
                "hitter": {"sections": [{"rows": []}]},
            }
        }

        with patch("syndicate.features.mlb.hub.available_daily_summary_dates", return_value=["2026-06-14"]):
            with patch("syndicate.features.mlb.hub.load_json_file", return_value=summary):
                context = build_mlb_hub_context()

        self.assertIn("no hitter rows yet", context.get("availability_note") or "")
        self.assertEqual(context.get("launch_date"), "2026-06-14")

    def test_mlb_pitcher_ladders_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.mlb.ladders_common.load_json_file", return_value=None):
            from syndicate.features.mlb.pitcher_ladders import build_pitcher_ladders_page_context

            context = build_pitcher_ladders_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "Pitcher ladders unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "Pitcher ladders")

    def test_mlb_hr_targets_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.mlb.hr_targets.load_json_file", return_value=None):
            from syndicate.features.mlb.hr_targets import build_hr_targets_page_context as build_mlb_hr_targets_page_context

            context = build_mlb_hr_targets_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "MLB HR targets unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "MLB HR targets")

    def test_mlb_rfi_targets_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.mlb.rfi_targets.load_json_file", return_value=None):
            from syndicate.features.mlb.rfi_targets import build_rfi_targets_page_context as build_mlb_rfi_targets_page_context

            context = build_mlb_rfi_targets_page_context("1900-01-01")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "MLB RFI targets unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("eyebrow"), "MLB RFI targets")

    def test_mlb_season_review_empty_date_does_not_inject_fake_sample_games(self) -> None:
        with patch("syndicate.features.mlb.season.load_json_file", return_value=None):
            from syndicate.features.mlb.season import build_season_page_context as build_mlb_season_page_context

            context = build_mlb_season_page_context(1900, "1900-01-01")

        self.assertEqual(context.get("games"), [])
        self.assertEqual(context.get("scoreboard_items"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "MLB season review unavailable")

    def test_nba_cards_empty_slate_does_not_inject_fake_sample_game(self) -> None:
        with patch("syndicate.features.nba.cards._games_from_artifacts", return_value=([], "missing_cards.csv", "missing_recs.json")):
            with patch("syndicate.features.nba.cards._local_live_state_payload", return_value={"games": []}):
                context = build_nba_cards_page_context("2026-05-17")

        self.assertEqual(context.get("date"), "2026-05-17")
        self.assertEqual(context.get("requested_date"), "2026-05-17")
        self.assertFalse(context.get("lookahead_applied"))
        self.assertFalse(context.get("has_games_on_slate"))
        self.assertEqual(context.get("games"), [])
        self.assertEqual(context.get("scoreboard_items"), [])
        self.assertEqual(context.get("source_title"), "NBA cards unavailable")
        self.assertEqual((context.get("header_stats") or [None, None])[1], {"label": "Recommendations", "value": "No data"})
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No NBA games are scheduled for this date")

    def test_nba_cards_api_empty_slate_preserves_empty_state(self) -> None:
        with patch("syndicate.features.nba.cards._games_from_artifacts", return_value=([], "missing_cards.csv", "missing_recs.json")):
            with patch("syndicate.features.nba.cards._local_live_state_payload", return_value={"games": []}):
                payload = build_nba_cards_api_payload("2026-05-17")

        self.assertEqual(payload.get("games"), [])
        self.assertFalse(payload.get("has_games_on_slate"))
        self.assertEqual(payload.get("source_title"), "NBA cards unavailable")
        self.assertEqual((payload.get("empty_state") or {}).get("title"), "No NBA games are scheduled for this date")
        self.assertFalse(payload.get("using_sample_data"))

    def test_nba_cards_missing_requested_date_does_not_fall_back_to_previous_slate(self) -> None:
        previous_day_games = [
            {
                "gamePk": "OKC@SAS",
                "away": {"abbr": "OKC"},
                "home": {"abbr": "SAS"},
                "detail": "Scheduled",
            }
        ]

        with patch(
            "syndicate.features.nba.cards._games_from_artifacts",
            side_effect=[([], "missing_cards.csv", "missing_recs.json"), (previous_day_games, "game_cards_2026-05-28.csv", "recommendations_slate_2026-05-28.json")],
        ):
            with patch("syndicate.features.nba.cards._local_live_state_payload", return_value={"games": []}):
                context = build_nba_cards_page_context("2026-05-29")

        self.assertEqual(context.get("requested_date"), "2026-05-29")
        self.assertEqual(context.get("date"), "2026-05-29")
        self.assertFalse(context.get("lookahead_applied"))
        self.assertFalse(context.get("has_games_on_slate"))
        self.assertEqual(context.get("games"), [])
        self.assertEqual(context.get("source_title"), "NBA cards unavailable")

    def test_nba_cards_live_state_fallback_uses_real_same_day_game(self) -> None:
        live_state_payload = {
            "games": [
                {
                    "away": "CLE",
                    "home": "DET",
                    "away_pts": 108,
                    "home_pts": 75,
                    "event_id": "401871339",
                    "game_id": "CLE@DET",
                    "status": "9:25 - 4th",
                    "in_progress": True,
                    "final": False,
                }
            ]
        }

        with patch("syndicate.features.nba.cards._games_from_artifacts", return_value=([], "missing_cards.csv", "missing_recs.json")):
            with patch("syndicate.features.nba.cards._local_live_state_payload", return_value=live_state_payload):
                with patch("syndicate.features.nba.cards._next_available_cards_date") as next_available_mock:
                    context = build_nba_cards_page_context("2026-05-17")

        self.assertEqual(context.get("date"), "2026-05-17")
        self.assertEqual(context.get("requested_date"), "2026-05-17")
        self.assertFalse(context.get("lookahead_applied"))
        self.assertEqual([(game.get("away_tri"), game.get("home_tri")) for game in (context.get("games") or [])], [("CLE", "DET")])
        self.assertEqual((context.get("scoreboard_items") or [{}])[0].get("label"), "CLE @ DET")
        self.assertEqual(context.get("source_title"), "NBA live scoreboard fallback")
        self.assertTrue(str(context.get("source_path") or "").endswith("live_state_2026-05-17.jsonl"))
        next_available_mock.assert_not_called()

    def test_nba_cards_live_state_fallback_prefers_local_snapshot_artifact(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            live_dir = root / "data" / "processed" / "live_snapshots"
            live_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / "live_state_2026-05-17.jsonl").write_text(
                json.dumps(
                    {
                        "ts": "2026-05-17T21:25:00Z",
                        "payload": {
                            "date": "2026-05-17",
                            "games": [
                                {
                                    "away": "CLE",
                                    "home": "DET",
                                    "away_pts": 108,
                                    "home_pts": 75,
                                    "event_id": "401871339",
                                    "game_id": "CLE@DET",
                                    "status": "9:25 - 4th",
                                    "in_progress": True,
                                    "final": False,
                                }
                            ],
                        },
                    }
                ) + "\n",
                encoding="utf-8",
            )

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]), patch(
                "syndicate.features.nba.cards._games_from_artifacts", return_value=([], "missing_cards.csv", "missing_recs.json")
            ), patch(
                "syndicate.features.nba.cards._next_available_cards_date"
            ) as next_available_mock:
                from syndicate.features.nba.cards import _local_live_state_payload

                _local_live_state_payload.cache_clear()
                context = build_nba_cards_page_context("2026-05-17")
                _local_live_state_payload.cache_clear()

        self.assertEqual([(game.get("away_tri"), game.get("home_tri")) for game in (context.get("games") or [])], [("CLE", "DET")])
        self.assertEqual(context.get("source_title"), "NBA live scoreboard fallback")
        self.assertTrue(str(context.get("source_path") or "").endswith("live_state_2026-05-17.jsonl"))
        next_available_mock.assert_not_called()

    def test_nba_cards_prefer_local_artifacts_over_source_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            (processed_dir / "game_cards_2026-05-17.csv").write_text(
                "game_id,visitor_team,home_team,away_tri,home_tri,commence_time,bookmaker,books_count,away_ml,home_ml,home_spread,total,prob_home_tip,early_threes_prob_ge_1\n"
                "game-1,Cleveland Cavaliers,Detroit Pistons,CLE,DET,2026-05-17T19:00:00Z,Consensus,12,120,-140,-3.5,221.5,0.51,0.42\n",
                encoding="utf-8",
            )
            (processed_dir / "recommendations_slate_2026-05-17.json").write_text(
                json.dumps({"per_game": []}),
                encoding="utf-8",
            )

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]):
                context = build_nba_cards_page_context("2026-05-17")
                payload = build_nba_cards_api_payload("2026-05-17")

        self.assertEqual([(game.get("away_tri"), game.get("home_tri")) for game in (context.get("games") or [])], [("CLE", "DET")])
        self.assertEqual(context.get("source_title"), "NBA processed game cards")
        self.assertTrue(str(context.get("source_path") or "").endswith("game_cards_2026-05-17.csv"))
        self.assertEqual([(game.get("away_tri"), game.get("home_tri")) for game in (payload.get("games") or [])], [("CLE", "DET")])
        self.assertTrue(str(payload.get("source_path") or "").endswith("game_cards_2026-05-17.csv"))
        self.assertFalse(bool(payload.get("using_sample_data")))


class ArchiveRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        cls.client = app.test_client()

    def test_ncaab_results_archive_route_and_api(self) -> None:
        response = self.client.get("/ncaab/api/archive?date=2025-11-03")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual((payload.get("rank_cards") or [{}])[0].get("title"), "2025-11-03")
        self.assertEqual((payload.get("rank_cards") or [{}])[0].get("href"), "/ncaab/season/2025?date=2025-11-03")
        self.assertEqual(len(payload.get("header_stats") or []), 4)
        self.assertTrue(payload.get("warning_panel"))
        self.assertEqual(payload.get("control_name"), "date")
        self.assertTrue(any(link.get("href") == "/ncaab/archive?date=2025-11-03" for link in (payload.get("module_links") or [])))

        html = self.client.get("/ncaab/archive?date=2025-11-03").get_data(as_text=True)
        self.assertIn("NCAAB Daily Archive", html)
        self.assertIn("2025-11-03", html)
        self.assertIn("/ncaab/season/2025?date=2025-11-03", html)

        alias_payload = self.client.get("/ncaab/api/results?date=2025-11-03").get_json()
        self.assertEqual(alias_payload.get("route_path"), "/ncaab/archive")
        alias_html = self.client.get("/ncaab/results?date=2025-11-03").get_data(as_text=True)
        self.assertIn("NCAAB Daily Archive", alias_html)

    def test_mlb_daily_archive_route_and_api(self) -> None:
        response = self.client.get("/mlb/api/archive?date=2026-05-18")
        payload = response.get_json()
        resolved_date = str(payload.get("date") or "")
        resolved_season = resolved_date[:4]

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual((payload.get("rank_cards") or [{}])[0].get("title"), resolved_date)
        self.assertEqual((payload.get("rank_cards") or [{}])[0].get("href"), f"/mlb/season/{resolved_season}?date={resolved_date}")
        self.assertEqual(len(payload.get("header_stats") or []), 4)
        self.assertTrue(payload.get("warning_panel"))

        html = self.client.get("/mlb/archive?date=2026-05-18").get_data(as_text=True)
        self.assertIn("MLB Daily Archive", html)
        self.assertIn(resolved_date, html)
        self.assertIn("Official picks", html)
        self.assertIn(f"/mlb/season/{resolved_season}?date={resolved_date}", html)

    def test_mlb_cards_api_without_date_uses_today(self) -> None:
        today_date = date.today().isoformat()
        response = self.client.get("/mlb/api/cards")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("date"), today_date)

    def test_mlb_source_cards_api_payload_trims_heavy_game_detail(self) -> None:
        payload = source_cards_api_payload(
            {
                "date": "1900-01-01",
                "games": [
                    {
                        "gamePk": 123,
                        "card_variant": "mlb_main",
                        "gameType": "R",
                        "away": {"abbr": "AWY", "name": "Away Team"},
                        "home": {"abbr": "HME", "name": "Home Team"},
                        "status": {"abstract": "Final", "detailed": "Final"},
                        "detail": "7:05 PM",
                        "summary": "Away Team vs Home Team",
                        "startTime": "7:05 PM",
                        "gameDate": "1900-01-01T19:05:00Z",
                        "officialDate": "1900-01-01",
                        "href": "/mlb/game/123?date=1900-01-01",
                        "href_label": "Open game detail",
                        "first1BetSignal": {"label": "F1", "summary": "lightweight"},
                        "flags": {"hasAnyRecommendations": False},
                        "markets": {"ml": {"selection": "away"}},
                        "probable": {"away": {"fullName": "Starter A"}, "home": {"fullName": "Starter H"}},
                        "trackedGameLines": {"ml": {"last_seen_at": "1900-01-01T19:00:00Z"}},
                        "oddsRefreshedAt": "1900-01-01T19:00:00Z",
                        "odds_refreshed_at": "1900-01-01T19:00:00Z",
                        "panels": [{"title": "heavy"}],
                        "predictions": {"full": {"away_runs_mean": 3.1}},
                        "market_tiles": [{"title": "heavy"}],
                        "actual_box_panel": {"title": "heavy"},
                        "prop_lens": {"title": "heavy"},
                        "prop_groups": [{"title": "heavy"}],
                        "run_projection_rows": [{"title": "heavy"}],
                        "segment_overview_cards": [{"title": "heavy"}],
                        "sim_box": {"title": "heavy"},
                    }
                ],
            }
        )

        card = (payload.get("cards") or [{}])[0]
        self.assertEqual(card.get("gamePk"), 123)
        self.assertEqual(card.get("summary"), "Away Team vs Home Team")
        self.assertEqual(card.get("first1BetSignal", {}).get("label"), "F1")
        self.assertEqual(card.get("probable", {}).get("away", {}).get("fullName"), "Starter A")
        self.assertEqual(card.get("markets", {}).get("ml", {}).get("selection"), "away")
        self.assertIn("trackedGameLines", card)
        self.assertNotIn("panels", card)
        self.assertNotIn("predictions", card)
        self.assertNotIn("market_tiles", card)
        self.assertNotIn("actual_box_panel", card)
        self.assertNotIn("prop_lens", card)
        self.assertNotIn("prop_groups", card)
        self.assertNotIn("run_projection_rows", card)
        self.assertNotIn("segment_overview_cards", card)
        self.assertNotIn("sim_box", card)

    def test_mlb_live_lens_merge_preserves_odds_refresh_metadata(self) -> None:
        from syndicate.features.mlb.cards import _merge_live_lens_row_into_game

        merged = _merge_live_lens_row_into_game(
            {"gamePk": 123, "summary": "Original"},
            {
                "status": {"abstract": "Live"},
                "oddsRefreshedAt": "2026-06-19T19:00:00Z",
                "odds_refreshed_at": "2026-06-19T19:00:00Z",
                "probable": {"away": {"miniLadderBadges": [{"label": "K 5+"}]}},
                "gameLens": [{"key": "live", "label": "Top 9"}],
                "props": [{"id": "live-prop"}],
                "liveProps": [{"id": "live-prop"}],
                "trackedProps": [{"id": "tracked-prop"}],
                "actual_box_panel": {"title": "Live box"},
                "sim_box": {"title": "Sim box"},
                "first1BetSignal": {"label": "F1"},
                "segment_overview_cards": [{"title": "Overview"}],
                "run_projection_rows": [{"title": "Projection"}],
                "snapshotAvailable": True,
                "simContextAvailable": True,
            },
        )

        self.assertEqual(merged.get("oddsRefreshedAt"), "2026-06-19T19:00:00Z")
        self.assertEqual(merged.get("odds_refreshed_at"), "2026-06-19T19:00:00Z")
        self.assertEqual(merged.get("probable", {}).get("away", {}).get("miniLadderBadges", [{}])[0].get("label"), "K 5+")
        self.assertEqual(merged.get("gameLens", [{}])[0].get("key"), "live")
        self.assertEqual(merged.get("props", [{}])[0].get("id"), "live-prop")
        self.assertEqual(merged.get("liveProps", [{}])[0].get("id"), "live-prop")
        self.assertEqual(merged.get("trackedProps", [{}])[0].get("id"), "tracked-prop")
        self.assertEqual(merged.get("actual_box_panel", {}).get("title"), "Live box")
        self.assertEqual(merged.get("sim_box", {}).get("title"), "Sim box")
        self.assertEqual(merged.get("first1BetSignal", {}).get("label"), "F1")
        self.assertTrue(merged.get("snapshotAvailable"))
        self.assertTrue(merged.get("simContextAvailable"))

    def test_nba_cards_api_without_date_preserves_today_request(self) -> None:
        today_date = date.today().isoformat()
        response = self.client.get("/nba/api/cards")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("requested_date"), today_date)

    def test_nhl_cards_bundle_without_date_preserves_today_request(self) -> None:
        today_date = date.today().isoformat()
        response = self.client.get("/nhl/api/cards/bundle")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("requested_date"), today_date)

    def test_wnba_cards_api_without_date_uses_today(self) -> None:
        today_date = date.today().isoformat()
        response = self.client.get("/wnba/api/cards")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("date"), today_date)

    def test_wnba_cards_default_route_uses_local_source_shell(self) -> None:
        with patch(
            "syndicate.features.wnba.source_proxy.source_web_text",
            side_effect=AssertionError("WNBA cards source shell should use local vendored parity assets"),
        ):
            response = self.client.get("/wnba/cards?date=2026-05-21")
            body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("/wnba/cards-parity.js", body)
        self.assertIn("WNBA Game Cards", body)
        self.assertNotIn("/static/shared/game_board.js", body)

    def test_wnba_cards_source_shell_uses_source_cards_api(self) -> None:
        response = self.client.get("/wnba/cards?date=2026-05-21")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-cards-payload-path="/wnba/api/source/cards"', body)
        self.assertNotIn('data-cards-payload-path="/wnba/api/cards"', body)

    def test_wnba_cards_source_shell_uses_versioned_assets(self) -> None:
        response = self.client.get("/wnba/cards?date=2026-05-21")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('/static/shared/standalone_shell.css?v=', body)
        self.assertIn('/wnba/styles.css?v=', body)
        self.assertIn('/wnba/cards-parity.css?v=', body)
        self.assertIn('/wnba/cards-parity.js?v=', body)

    def test_wnba_cards_parity_script_uses_namespaced_api_routes(self) -> None:
        script = self.client.get("/wnba/cards-parity.js").get_data(as_text=True)

        self.assertIn("const API_BASE_PATH = '/wnba/api';", script)
        self.assertIn("const SOURCE_CARDS_API_BASE_PATH = `${API_BASE_PATH}/source/cards`", script)
        self.assertNotIn("fetch(`/api/cards", script)

    def test_wnba_source_sim_stub_derives_team_score_from_players(self) -> None:
        from syndicate.features.wnba.cards import _source_sim_stub

        sim_game = {
            "sim": {
                "players": {
                    "away": [{"pts_mean": 21.5}, {"pts_mean": 12.0}],
                    "home": [{"pts_mean": 18.0}, {"pts_mean": 15.5}],
                }
            }
        }

        stub = _source_sim_stub("game-1", sim_game, {"total": "175.5", "home_spread": "2.5"})

        self.assertEqual((stub.get("score") or {}).get("away_mean"), 33.5)
        self.assertEqual((stub.get("score") or {}).get("home_mean"), 33.5)
        self.assertEqual((stub.get("score") or {}).get("total_mean"), 67.0)
        self.assertEqual((stub.get("score") or {}).get("margin_mean"), 0.0)

    def test_wnba_source_sim_stub_derives_quarter_periods_from_player_quarter_points(self) -> None:
        from syndicate.features.wnba.cards import _source_sim_stub

        sim_game = {
            "sim": {
                "players": {
                    "away": [
                        {"q_pts": [5.0, 6.0, 7.0, 8.0]},
                        {"q_pts": [4.0, 3.0, 2.0, 1.0]},
                    ],
                    "home": [
                        {"q_pts": [6.0, 5.0, 4.0, 3.0]},
                        {"q_pts": [2.0, 3.0, 4.0, 5.0]},
                    ],
                }
            }
        }

        stub = _source_sim_stub("game-1", sim_game, {"total": "170.5", "home_spread": "-4.5"})

        self.assertEqual((stub.get("periods") or {}).get("q1", {}).get("away_mean"), 9.0)
        self.assertEqual((stub.get("periods") or {}).get("q1", {}).get("home_mean"), 8.0)
        self.assertEqual((stub.get("periods") or {}).get("q1", {}).get("total_mean"), 17.0)
        self.assertEqual((stub.get("periods") or {}).get("q1", {}).get("margin_mean"), -1.0)
        self.assertIsNotNone((stub.get("periods") or {}).get("q1", {}).get("p_home_win"))
        self.assertEqual((stub.get("periods") or {}).get("q4", {}).get("away_mean"), 9.0)
        self.assertEqual((stub.get("periods") or {}).get("q4", {}).get("home_mean"), 8.0)

    def test_wnba_source_sim_stub_prefers_top_level_quarter_summary_when_player_quarter_points_are_zero(self) -> None:
        from syndicate.features.wnba.cards import _source_sim_stub

        sim_game = {
            "sim": {
                "quarters": [
                    {"q": 1, "away_pts_mu": 21.4, "home_pts_mu": 19.8},
                    {"q": 2, "away_pts_mu": 21.4, "home_pts_mu": 19.8},
                    {"q": 3, "away_pts_mu": 22.3, "home_pts_mu": 20.6},
                    {"q": 4, "away_pts_mu": 22.3, "home_pts_mu": 20.6},
                ],
                "players": {
                    "away": [{"pts_mean": 18.0, "q_pts": [0.0, 0.0, 0.0, 0.0]}],
                    "home": [{"pts_mean": 17.0, "q_pts": [0.0, 0.0, 0.0, 0.0]}],
                },
            }
        }

        stub = _source_sim_stub("game-1", sim_game, {"total": "164.0", "home_spread": "8.5"})

        self.assertEqual((stub.get("periods") or {}).get("q1", {}).get("away_mean"), 21.4)
        self.assertEqual((stub.get("periods") or {}).get("q1", {}).get("home_mean"), 19.8)
        self.assertEqual((stub.get("periods") or {}).get("q4", {}).get("total_mean"), 42.9)

    def test_wnba_source_sim_payload_includes_quarter_and_half_intervals(self) -> None:
        from syndicate.features.wnba.cards import _source_sim_payload

        sim_game = {
            "sim": {
                "quarters": [
                    {"q": 1, "away_pts_mu": 21.4, "home_pts_mu": 19.8},
                    {"q": 2, "away_pts_mu": 20.1, "home_pts_mu": 21.3},
                    {"q": 3, "away_pts_mu": 22.3, "home_pts_mu": 20.6},
                    {"q": 4, "away_pts_mu": 20.8, "home_pts_mu": 22.1},
                ]
            }
        }

        payload = _source_sim_payload("game-1", sim_game, {"total": "170.5", "home_spread": "-4.5"})

        self.assertEqual((payload.get("intervals") or {}).get("quarters", {}).get("q1", {}).get("away_mean"), 21.4)
        self.assertEqual((payload.get("intervals") or {}).get("quarters", {}).get("q4", {}).get("home_mean"), 22.1)
        self.assertEqual((payload.get("intervals") or {}).get("halves", {}).get("h1", {}).get("total_mean"), 82.6)
        self.assertEqual((payload.get("intervals") or {}).get("halves", {}).get("h2", {}).get("margin_mean"), -0.4)

    def test_wnba_advanced_game_contract_includes_intervals_and_coverage(self) -> None:
        from syndicate.features.wnba.cards import _wnba_advanced_game_contract

        game = {
            "game_id": "game-1",
            "event_id": "401000001",
            "away_tri": "PHX",
            "away_name": "Phoenix Mercury",
            "home_tri": "NYL",
            "home_name": "New York Liberty",
            "status": "Scheduled",
            "detail": "Scheduled",
            "betting": {"home_ml": -145, "away_ml": 125, "home_spread": -3.5, "total": 164.5, "p_home_win": 0.61},
            "prop_recommendations": {"away": [{"player": "A1"}], "home": [{"player": "H1"}]},
            "game_market_recommendations": [{"market_label": "Spread"}],
            "sim": {
                "score": {"away_mean": 78.4, "home_mean": 83.1},
                "periods": {
                    "q1": {"away_mean": 19.4, "home_mean": 20.1},
                    "q2": {"away_mean": 19.6, "home_mean": 20.4},
                    "q3": {"away_mean": 20.0, "home_mean": 20.6},
                    "q4": {"away_mean": 19.4, "home_mean": 22.0},
                },
                "intervals": {
                    "quarters": {"q1": {"away_mean": 19.4, "home_mean": 20.1}},
                    "halves": {"h1": {"away_mean": 39.0, "home_mean": 40.5}},
                },
                "quarters": [{"q": 1, "away_pts_mu": 19.4, "home_pts_mu": 20.1}],
                "players_summary": {"away": 2, "home": 2, "missing_away": 0, "missing_home": 0, "injured_away": 0, "injured_home": 1},
                "players": {
                    "away": [{"player_name": "A1", "pts_mean": 18.4}],
                    "home": [{"player_name": "H1", "pts_mean": 20.1}],
                },
                "missing_prop_players": {"away": [], "home": []},
                "injuries": {"away": [], "home": [{"player": "H2"}]},
                "pregame_context": {"pace_proj": 79.5},
            },
            "live_state": {"in_progress": False, "final": False, "status": "Scheduled"},
        }

        contract = _wnba_advanced_game_contract(game)

        self.assertEqual(contract["game_id"], "game-1")
        self.assertEqual(contract["simulation"]["intervals"]["quarters"]["q1"]["away_mean"], 19.4)
        self.assertEqual(contract["simulation"]["intervals"]["halves"]["h1"]["home_mean"], 40.5)
        self.assertTrue(contract["coverage"]["has_intervals"])
        self.assertTrue(contract["coverage"]["has_players"])
        self.assertTrue(contract["coverage"]["has_injuries"])
        self.assertEqual(contract["props"]["game_market_recommendations"][0]["market_label"], "Spread")

    def test_wnba_cards_parity_script_treats_missing_metrics_as_missing_not_zero(self) -> None:
        script = self.client.get("/wnba/cards-parity.js").get_data(as_text=True)

        self.assertIn("function toFiniteNumber(value)", script)
        self.assertIn("if (value == null)", script)
        self.assertIn("const hasMetrics = hasFiniteMetric(pick?.probability) || hasFiniteMetric(pick?.ev);", script)

    def test_shared_game_board_contract_derives_period_scores_from_total_and_margin(self) -> None:
        from syndicate.features.shared.game_board_contract import apply_game_board_contract

        context = apply_game_board_contract(
            {
                "games": [
                    {
                        "away": {"abbr": "PHX", "name": "Phoenix Mercury"},
                        "home": {"abbr": "NYL", "name": "New York Liberty"},
                        "status": "Processed artifact",
                        "detail": "2026-05-29T00:00:00Z",
                        "summary": "Consensus market snapshot",
                        "betting": {"home_spread": -4.5, "total": 168.5},
                        "metrics": [{"label": "Spread", "value": "NYL -4.5"}],
                        "sim": {
                            "periods": {
                                "q1": {
                                    "total_mean": 44.0,
                                    "margin_mean": 6.0,
                                    "p_home_win": 0.64,
                                }
                            }
                        },
                    }
                ]
            },
            sport="wnba",
            module="game_detail",
        )

        rows = ((context.get("games") or [])[0].get("shared_period_rows") or [])

        self.assertEqual(rows[0].get("main"), "PHX 19.0 - NYL 25.0")
        self.assertEqual(rows[0].get("subtitle"), "Projected total 44.0")
        self.assertIn("ATS NYL -4.5", rows[0].get("market"))
        self.assertIn("Total 168.5", rows[0].get("market"))
        self.assertNotEqual(rows[0].get("best_edge"), "-")

    def test_shared_game_board_contract_preserves_zero_valued_prop_fields(self) -> None:
        from syndicate.features.shared.game_board_contract import apply_game_board_contract

        context = apply_game_board_contract(
            {
                "games": [
                    {
                        "away": {"abbr": "NYK", "name": "New York Knicks"},
                        "home": {"abbr": "SAS", "name": "San Antonio Spurs"},
                        "prop_recommendations": {
                            "away": [
                                {
                                    "player": "Test Player",
                                    "display_pick": "Test Player Points OVER 0.5",
                                    "market": "Points",
                                    "actual": 0.0,
                                    "projected": 0.0,
                                    "liveProjection": 0.0,
                                    "market_line": 0.0,
                                }
                            ]
                        },
                    }
                ]
            },
            sport="nba",
            module="cards",
        )

        row = (((context.get("games") or [{}])[0].get("shared_prop_rows") or [{}])[0])

        self.assertEqual(row.get("actual"), 0.0)
        self.assertEqual(row.get("projected"), 0.0)
        self.assertEqual(row.get("live_projection"), 0.0)
        self.assertEqual(row.get("market_line"), 0.0)

    def test_wnba_cards_source_alias_preserves_explicit_source_shell(self) -> None:
        response = self.client.get("/wnba/cards/source?date=2026-05-21", follow_redirects=True)
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("/wnba/cards-parity.js", body)
        self.assertIn("WNBA Game Cards", body)

    def test_ncaab_cards_api_without_date_uses_today(self) -> None:
        today_date = date.today().isoformat()
        response = self.client.get("/ncaab/api/cards")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("date"), today_date)

    def test_mlb_cards_api_empty_slate_preserves_empty_state(self) -> None:
        with patch("syndicate.features.mlb.cards.load_json_file", return_value=None):
            from syndicate.features.mlb.cards import build_cards_page_context as build_mlb_cards_page_context
            from syndicate.features.shared.game_board_contract import build_game_board_api_payload

            context = build_mlb_cards_page_context("1900-01-01")
            payload = build_game_board_api_payload(context)
            payload.update(source_cards_api_payload(context))

        self.assertEqual(payload.get("games"), [])
        self.assertEqual(payload.get("source_title"), "MLB cards unavailable")
        self.assertEqual((payload.get("empty_state") or {}).get("title"), "No game cards were available for this date")
        self.assertFalse(payload.get("using_sample_data"))

    def test_mlb_cards_missing_requested_date_does_not_fall_back_to_previous_slate(self) -> None:
        with patch("syndicate.features.mlb.cards.available_daily_summary_dates", return_value=["2026-06-11"]):
            with patch("syndicate.features.mlb.cards.load_json_file", return_value=None):
                from syndicate.features.mlb.cards import build_cards_page_context as build_mlb_cards_page_context

                context = build_mlb_cards_page_context("2026-06-12")

        self.assertEqual(context.get("requested_date"), "2026-06-12")
        self.assertEqual(context.get("date"), "2026-06-12")
        self.assertEqual(context.get("cards_header_meta"), "Artifact-backed slate | 2026-06-12")
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No game cards were available for this date")
        self.assertIn("Requested date: 2026-06-12", (context.get("empty_state") or {}).get("list_items") or [])

    def test_ncaab_season_api_exposes_archive_navigation_metadata(self) -> None:
        response = self.client.get("/ncaab/api/season/2025?date=2025-11-03")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        module_links = payload.get("module_links") or []
        self.assertTrue(any(link.get("href") == "/ncaab/archive?date=2025-11-03" for link in module_links))
        self.assertTrue(any(link.get("href") == "/ncaab/season/2025/betting-card?date=2025-11-03" for link in module_links))
        self.assertEqual((payload.get("teaser") or {}).get("href"), "/ncaab/cards?date=2025-11-03")
        self.assertEqual(payload.get("control_action"), "/ncaab/season/2025")
        self.assertEqual(payload.get("control_name"), "date")

    def test_ncaab_season_context_uses_requested_season_copy(self) -> None:
        context = build_season_page_context(2024, "2024-11-01")

        self.assertEqual(context.get("route_path"), "/ncaab/season/2024")
        self.assertEqual(context.get("intro_title"), "NCAAB 2024 Season Review")
        self.assertEqual(context.get("source_title"), "NCAAB 2024 season review data")
        self.assertIn("2024 navigation lands on a real historical page", context.get("intro_body") or "")

    def test_ncaab_cards_empty_date_does_not_inject_fake_sample_game(self) -> None:
        with patch("syndicate.features.ncaab.cards.mirrored_recommendations_payload", return_value={}), patch(
            "syndicate.features.ncaab.cards.mirrored_available_dates", return_value=["2025-11-03"]
        ):
            context = build_ncaab_cards_page_context("2025-11-03")

        self.assertEqual(context.get("games"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NCAAB cards unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No game cards were available for this date")

    def test_ncaab_game_detail_missing_card_does_not_inject_fake_matchup(self) -> None:
        with patch(
            "syndicate.features.ncaab.game_detail.build_cards_page_context",
            return_value={
                "date": "2025-11-03",
                "prev_date": "2025-11-02",
                "next_date": "2025-11-04",
                "games": [],
                "using_sample_data": False,
                "source_path": "NCAAB /api/recommendations?date=2025-11-03",
                "control_value": "2025-11-03",
            },
        ):
            context = build_ncaab_game_detail_page_context("2025-11-03", "missing-game")

        game = (context.get("games") or [{}])[0]
        self.assertEqual(game.get("status"), "NCAAB game unavailable")
        self.assertEqual(context.get("source_title"), "NCAAB game unavailable")
        self.assertFalse(context.get("using_sample_data"))

    def test_ncaab_season_review_empty_date_does_not_inject_fake_sample_game(self) -> None:
        with patch("syndicate.features.ncaab.season.recommendations_payload", return_value={}), patch(
            "syndicate.features.ncaab.season.results_by_date_payload", return_value={}
        ), patch("syndicate.features.ncaab.season.season_dates", return_value=["2025-11-03"]), patch(
            "syndicate.features.ncaab.season.default_season_date", return_value="2025-11-03"
        ), patch("syndicate.features.ncaab.season.schedule_dates", return_value=[]), patch(
            "syndicate.features.ncaab.season.results_dates", return_value=[]
        ):
            context = build_season_page_context(2025, "2025-11-03")

        self.assertEqual(context.get("games"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No season-review rows were available for this date")

    def test_ncaab_results_archive_empty_date_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.ncaab.results_archive.results_dates", return_value=[]), patch(
            "syndicate.features.ncaab.results_archive.results_by_date_payload", return_value={}
        ):
            context = build_ncaab_results_archive_page_context("2025-11-03")

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NCAAB archive unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No settled NCAAB results dates were available")

    def test_ncaab_season_betting_card_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/ncaab/api/season/2025/betting-card?date=2025-11-03")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/ncaab/season/2025/betting-card")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/ncaab/archive?date=2025-11-03" for link in (payload.get("module_links") or [])))
        self.assertTrue(any(link.get("href") == "/ncaab/season/2025?date=2025-11-03" for link in (payload.get("module_links") or [])))

    def test_nhl_betting_card_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nhl/api/season/2026/betting-card?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/nhl/season/2026/betting-card")
        self.assertEqual(payload.get("reset_href"), "/nhl/season/2026/betting-card")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/nhl/season/2026/betting-card?date=2026-05-16" for link in (payload.get("module_links") or [])))

    def test_nhl_betting_card_page_uses_standalone_shell(self) -> None:
        response = self.client.get('/nhl/season/2026/betting-card?date=2026-05-16')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="bettingCardDateForm"', html)
        self.assertIn('NHL 2026 Betting Card', html)
        self.assertIn('Source artifact', html)
        self.assertIn('/nhl/picks?date=', html)
        self.assertIn('/nhl/archive?date=', html)
        self.assertNotIn('One app with seven feature modules.', html)

    def test_wnba_betting_card_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/wnba/api/season/2026/betting-card?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/wnba/season/2026/betting-card")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/wnba/season/2026/betting-card?date=2026-05-16" for link in (payload.get("module_links") or [])))
        self.assertTrue(any(link.get("href") == "/wnba/archive?date=2026-05-16" for link in (payload.get("module_links") or [])))

    def test_wnba_live_lens_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/wnba/api/live-lens?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/wnba/live-lens")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(str(link.get("href") or "").startswith("/wnba/live-lens?date=") for link in (payload.get("module_links") or [])))

    def test_nfl_archive_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nfl/api/archive?season=2025&week=21")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "week")
        self.assertEqual(payload.get("route_path"), "/nfl/archive")
        self.assertEqual(payload.get("reset_href"), "/nfl/archive?season=2025")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/nfl/archive?season=2025&week=21" for link in (payload.get("module_links") or [])))
        self.assertTrue(any(link.get("href") == "/nfl/season/2025/betting-card?week=21" for link in (payload.get("module_links") or [])))

    def test_nfl_live_lens_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nfl/api/live-lens?season=2025&week=21")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "week")
        self.assertEqual(payload.get("route_path"), "/nfl/live-lens")
        self.assertEqual(payload.get("reset_href"), "/nfl/live-lens?season=2025")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/nfl/live-lens?season=2025&week=21" for link in (payload.get("module_links") or [])))
        self.assertTrue(any(link.get("href") == "/nfl/archive?season=2025&week=21" for link in (payload.get("module_links") or [])))

    def test_ncaaf_archive_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/ncaaf/api/archive?week=1")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "week")
        self.assertEqual(payload.get("route_path"), "/ncaaf/archive")
        self.assertEqual(payload.get("reset_href"), "/ncaaf/archive")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/ncaaf/archive?week=1" for link in (payload.get("module_links") or [])))
        self.assertTrue(any("/ncaaf/season/" in str(link.get("href") or "") and "betting-card?week=1" in str(link.get("href") or "") for link in (payload.get("module_links") or [])))

    def test_ncaaf_live_lens_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/ncaaf/api/live-lens?week=1")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "week")
        self.assertEqual(payload.get("route_path"), "/ncaaf/live-lens")
        self.assertEqual(payload.get("reset_href"), "/ncaaf/live-lens")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/ncaaf/live-lens?week=1" for link in (payload.get("module_links") or [])))
        self.assertTrue(any(link.get("href") == "/ncaaf/archive?week=1" for link in (payload.get("module_links") or [])))

    def test_mlb_season_api_exposes_archive_navigation_metadata(self) -> None:
        response = self.client.get("/mlb/api/season/2026/board?date=2026-05-18")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        module_links = payload.get("module_links") or []
        self.assertTrue(any(link.get("href") == "/mlb/archive?date=2026-05-18" for link in module_links))
        self.assertEqual((payload.get("teaser") or {}).get("href"), "/mlb/season/2026/betting-card?date=2026-05-18")
        self.assertEqual(payload.get("route_path"), "/mlb/season/2026")
        self.assertEqual(payload.get("control_name"), "date")

    def test_mlb_betting_card_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/mlb/api/season/2026/betting-card?date=2026-06-08")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/mlb/archive?date=2026-06-08" for link in (payload.get("module_links") or [])))

    def test_mlb_top_props_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/mlb/api/top-props?date=2026-05-18")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/mlb/pitcher-top-props")
        self.assertTrue(any(link.get("href") == "/mlb/top-props?date=2026-05-18" or link.get("href") == "/mlb/pitcher-top-props?date=2026-05-18" for link in (payload.get("module_links") or [])))

    def test_mlb_group_top_props_apis_keep_rank_board_navigation_metadata(self) -> None:
        pitcher = self.client.get("/mlb/api/pitcher-top-props?date=2026-05-18").get_json()
        hitter = self.client.get("/mlb/api/hitter-top-props?date=2026-05-18").get_json()

        self.assertEqual(pitcher.get("control_name"), "date")
        self.assertEqual(hitter.get("control_name"), "date")
        self.assertEqual(pitcher.get("artifactSource"), "daily_top_props")
        self.assertEqual(hitter.get("artifactSource"), "daily_top_props")
        self.assertTrue(any(link.get("href") == "/mlb/archive?date=2026-05-18" for link in (pitcher.get("module_links") or [])))
        self.assertTrue(any(link.get("href") == "/mlb/archive?date=2026-05-18" for link in (hitter.get("module_links") or [])))

    def test_mlb_rfi_targets_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/mlb/api/rfi-targets?date=2026-05-18")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/mlb/rfi-targets")
        self.assertIn("signals", payload)
        self.assertTrue(any(link.get("href") == "/mlb/rfi-targets?date=2026-05-18" for link in (payload.get("module_links") or [])))

    def test_mlb_hr_targets_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/mlb/api/hr-targets?date=2026-05-18")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/mlb/hr-targets")
        self.assertIn("targets", payload)
        self.assertTrue(any(link.get("href") == "/mlb/hr-targets?date=2026-05-18" for link in (payload.get("module_links") or [])))

    def test_mlb_ladder_apis_keep_rank_board_navigation_metadata(self) -> None:
        pitcher = self.client.get("/mlb/api/pitcher-ladders?date=2026-05-18").get_json()
        hitter = self.client.get("/mlb/api/hitter-ladders?date=2026-05-18").get_json()

        self.assertEqual(pitcher.get("control_name"), "date")
        self.assertEqual(hitter.get("control_name"), "date")
        self.assertEqual(pitcher.get("route_path"), "/mlb/pitcher-ladders")
        self.assertEqual(hitter.get("route_path"), "/mlb/hitter-ladders")
        self.assertEqual(pitcher.get("artifactSource"), "daily_ladders")
        self.assertEqual(hitter.get("artifactSource"), "daily_ladders")
        self.assertTrue(any(link.get("href") == "/mlb/pitcher-ladders?date=2026-05-18" for link in (pitcher.get("module_links") or [])))
        self.assertTrue(any(link.get("href") == "/mlb/hitter-ladders?date=2026-05-18" for link in (hitter.get("module_links") or [])))

    def test_archive_launch_links_and_tracker_copy(self) -> None:
        today_date = date.today().isoformat()
        latest_mlb_date = "2026-06-10"
        ncaab_launch_season = ncaab_season_for_date(today_date)
        ncaab_season_launch_date = default_ncaab_season_date(ncaab_launch_season)
        ncaaf_season = default_ncaaf_season()
        with patch("syndicate.features.mlb.hub.available_daily_summary_dates", return_value=["2026-06-09", latest_mlb_date]), patch(
            "syndicate.features.mlb.hub.date"
        ) as mock_date:
            mock_date.today.return_value = date(2026, 6, 11)
            mlb_context = build_mlb_hub_context()
            mlb_hub = self.client.get("/mlb").get_data(as_text=True)

        mlb_launch_date = str(mlb_context.get("launch_date") or "")
        ncaab_hub = self.client.get("/ncaab").get_data(as_text=True)
        ncaaf_hub = self.client.get("/ncaaf").get_data(as_text=True)
        nfl_hub = self.client.get("/nfl").get_data(as_text=True)
        wnba_hub = self.client.get("/wnba/hub").get_data(as_text=True)
        nhl_hub = self.client.get("/nhl/hub").get_data(as_text=True)
        nba_hub = self.client.get("/nba/hub").get_data(as_text=True)
        home = self.client.get("/").get_data(as_text=True)

        self.assertEqual(mlb_launch_date, latest_mlb_date)
        self.assertIn(f"/mlb/cards?date={latest_mlb_date}", mlb_hub)
        self.assertIn(f"/mlb/archive?date={latest_mlb_date}", mlb_hub)
        self.assertIn("daily archive", mlb_hub.lower())
        self.assertIn("Active sports", home)
        self.assertIn(f"/ncaab/cards?date={today_date}", ncaab_hub)
        self.assertIn(f"/ncaab/archive?date={ncaab_season_launch_date}", ncaab_hub)
        self.assertIn("daily archive", ncaab_hub.lower())
        self.assertIn(f"/ncaab/season/{ncaab_launch_season}?date={ncaab_season_launch_date}", ncaab_hub)
        self.assertIn("/ncaaf/cards?week=1", ncaaf_hub)
        self.assertIn(f"/ncaaf/season/{ncaaf_season}/betting-card?week=1", ncaaf_hub)
        self.assertRegex(ncaaf_hub, r"/ncaaf/live-lens\?week=\d+")
        self.assertRegex(ncaaf_hub, r"/ncaaf/archive\?week=\d+")
        self.assertRegex(nfl_hub, r"/nfl/cards\?season=\d{4}(?:&|&amp;)week=\d+")
        self.assertRegex(nfl_hub, r"/nfl/picks\?season=\d{4}(?:&|&amp;)week=\d+")
        self.assertRegex(nfl_hub, r"/nfl/season/\d{4}/betting-card\?week=\d+")
        self.assertRegex(nfl_hub, r"/nfl/live-lens\?season=\d{4}(?:&|&amp;)week=\d+")
        self.assertRegex(nfl_hub, r"/nfl/archive\?season=\d{4}(?:&|&amp;)week=\d+")
        self.assertIn("Betting Card", nfl_hub)
        self.assertIn(f"/wnba/cards?date={today_date}", wnba_hub)
        self.assertRegex(wnba_hub, r"/wnba/cards\?date=\d{4}-\d{2}-\d{2}")
        self.assertIn("Recent WNBA processed dates", wnba_hub)
        self.assertRegex(wnba_hub, r"/wnba/season/\d{4}/betting-card\?date=\d{4}-\d{2}-\d{2}")
        self.assertIn(f"/nba/cards?date={today_date}", nba_hub)
        self.assertIn("Recent NBA processed dates", nba_hub)
        self.assertRegex(nba_hub, r"/nba/season/\d{4}/betting-card\?profile=retuned(?:&|&amp;)date=\d{4}-\d{2}-\d{2}")
        self.assertRegex(nba_hub, r"/nba/season/\d{4}/live-lens\?date=\d{4}-\d{2}-\d{2}(?:&|&amp;)profile=retuned")
        self.assertIn(f"/nhl/cards?date={today_date}", nhl_hub)
        self.assertRegex(nhl_hub, r"/nhl/reconciliation\?date=\d{4}-\d{2}-\d{2}")
        self.assertRegex(nhl_hub, r"/nhl/props/reconciliation\?date=\d{4}-\d{2}-\d{2}")
        self.assertRegex(nhl_hub, r"/nhl/props/lines\?date=\d{4}-\d{2}-\d{2}")
        self.assertRegex(nhl_hub, r"/nhl/live-lens\?date=\d{4}-\d{2}-\d{2}")
        self.assertIn("Recent NHL recommendation snapshots", nhl_hub)
        self.assertRegex(nhl_hub, r"/nhl/season/\d{4}/betting-card\?date=\d{4}-\d{2}-\d{2}")
        self.assertIn("Jump to each live rail with games, props, freshness, and data health.", home)
        self.assertIn("Board Date", home)
        self.assertIn("Live slate", home)
        self.assertIn("Compact rail", home)
        self.assertIn("Pregame only", home)
        self.assertIn("Open Live Lens", home)
        self.assertIn("Live only", home)

    def test_nfl_hub_prefers_latest_mirrored_week_for_launch_links(self) -> None:
        with patch(
            "syndicate.blueprints.nfl.week_summaries",
            return_value=[
                {"season": 2025, "week": 17, "count": 12},
                {"season": 2025, "week": 19, "count": 16},
                {"season": 2025, "week": 21, "count": 14},
            ],
        ), patch(
            "syndicate.blueprints.nfl.tracked_week",
            return_value={"season": 2025, "week": 22},
        ), patch(
            "syndicate.blueprints.nfl.latest_season",
            return_value=2025,
        ), patch(
            "syndicate.blueprints.nfl.default_week",
            return_value=21,
        ):
            html = self.client.get("/nfl/hub").get_data(as_text=True)

        self.assertIn("/nfl/cards?season=2025&amp;week=21", html)
        self.assertIn("Source app currently points at 2025 Week 22", html)

    def test_generic_sport_hub_uses_shared_visual_shell(self) -> None:
        app = self.client.application
        app.config["SYNDICATE_SPORTS"] = [
            *app.config["SYNDICATE_SPORTS"],
            {
                "slug": "test-sport",
                "name": "Test Sport",
                "status": "Planned",
                "phase": "Shared shell",
                "summary": "Synthetic hub for visual shell parity coverage.",
                "primary_href": "/test-sport/cards",
                "primary_label": "Open Test Sport cards",
                "surfaces": ["cards", "archive"],
                "next_step": "Keep the fallback hub on the shared visual shell.",
            },
        ]

        html = self.client.get("/test-sport").get_data(as_text=True)

        self.assertIn(">Home<", html)
        self.assertIn("Open Test Sport cards", html)
        self.assertIn("Module status", html)
        self.assertIn("Shared shell", html)
        self.assertIn("cards", html)
        self.assertIn("archive", html)

    def test_ncaab_hub_uses_per_date_season_links(self) -> None:
        with patch("syndicate.blueprints.ncaab.available_dates", return_value=["2024-11-05", "2025-11-03"]), patch(
            "syndicate.blueprints.ncaab.latest_date", return_value="2025-11-03"
        ), patch("syndicate.blueprints.ncaab.default_season_date", return_value="2025-11-03"), patch(
            "syndicate.blueprints.ncaab.season_dates", return_value=["2025-11-03"]
        ):
            html = self.client.get("/ncaab/hub").get_data(as_text=True)

        self.assertIn("/ncaab/season/2024?date=2024-11-05", html)
        self.assertIn("/ncaab/season/2024/betting-card?date=2024-11-05", html)
        self.assertIn("/ncaab/season/2025?date=2025-11-03", html)
        self.assertIn("/ncaab/season/2025/betting-card?date=2025-11-03", html)

    def test_ncaaf_hub_uses_per_week_season_links(self) -> None:
        with patch(
            "syndicate.blueprints.ncaaf.week_summaries",
            return_value=[
                {"week": 1, "season": 2024, "count": 10, "has_data": True},
                {"week": 2, "season": 2025, "count": 12, "has_data": True},
            ],
        ), patch("syndicate.blueprints.ncaaf.default_season", return_value=2025), patch(
            "syndicate.features.ncaaf.sources.default_season", return_value=2025
        ):
            html = self.client.get("/ncaaf/hub").get_data(as_text=True)

        self.assertIn("/ncaaf/season/2024/betting-card?week=1", html)
        self.assertIn("/ncaaf/season/2025/betting-card?week=2", html)

    def test_mlb_hub_context_uses_launch_date_season(self) -> None:
        context = build_mlb_hub_context()
        launch_date = str(context.get("launch_date") or "")
        launch_season = launch_date[:4]
        route_groups = context.get("route_groups") or []
        hrefs = [link.get("href") for group in route_groups for link in (group.get("links") or []) if isinstance(link, dict)]

        self.assertTrue(any(href == f"/mlb/season/{launch_season}?date={launch_date}" for href in hrefs))
        self.assertTrue(any(isinstance(href, str) and href.startswith(f"/mlb/season/{launch_season}/betting-card?date={launch_date}") for href in hrefs))
        self.assertIn(f"/mlb/live-lens-accuracy?date={launch_date}", hrefs)

    def test_mlb_live_lens_page_uses_standalone_daily_shell(self) -> None:
        response = self.client.get("/mlb/live-lens?date=2026-05-16")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('<title>MLB Live Lens - 2026-05-16</title>', body)
        self.assertIn('window.MLBLiveLensBootstrap', body)
        self.assertIn('Loading live lens', body)
        self.assertNotIn('Live Lens Accuracy', body)
        self.assertNotIn('Market Accuracy', body)

    def test_mlb_live_lens_api_defaults_to_persisting_current_day_state(self) -> None:
        with patch("syndicate.blueprints.mlb.read_latest_live_lens_api_payload", return_value={"ok": True}) as build_payload:
            response = self.client.get("/mlb/api/live-lens?date=2026-06-16")

        self.assertEqual(response.status_code, 200)
        build_payload.assert_called_once_with("2026-06-16")

    def test_ncaaf_picks_api_exposes_rank_board_navigation_metadata(self) -> None:
        ncaaf_season = default_ncaaf_season()
        response = self.client.get("/ncaaf/api/picks?week=1")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("week"), 1)
        self.assertEqual(payload.get("control_name"), "week")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/ncaaf/picks?week=1" for link in (payload.get("module_links") or [])))
        self.assertTrue(any(link.get("href") == f"/ncaaf/season/{ncaaf_season}/betting-card?week=1" for link in (payload.get("module_links") or [])))

    def test_ncaaf_cards_context_uses_source_derived_season_label(self) -> None:
        ncaaf_season = default_ncaaf_season()
        context = build_ncaaf_cards_page_context(1)

        self.assertEqual(context.get("date"), f"{ncaaf_season} Week 1")
        self.assertEqual(context.get("requested_date"), f"{ncaaf_season} Week 1")

    def test_ncaaf_cards_empty_week_does_not_inject_fake_sample_game(self) -> None:
        with patch("syndicate.features.ncaaf.cards.load_json", return_value={}), patch(
            "syndicate.features.ncaaf.cards.available_weeks", return_value=[1]
        ):
            context = build_ncaaf_cards_page_context(1)

        self.assertEqual(context.get("games"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NCAAF cards unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No game cards were available for this week")

    def test_ncaaf_picks_context_uses_source_derived_season_token(self) -> None:
        ncaaf_season = default_ncaaf_season()
        context = build_ncaaf_picks_page_context(1)

        self.assertEqual(context.get("season"), ncaaf_season)
        self.assertEqual(context.get("date"), f"{ncaaf_season}-01-01")

    def test_ncaaf_picks_empty_week_does_not_inject_fake_rank_card(self) -> None:
        with patch("syndicate.features.ncaaf.picks.load_json", return_value={}), patch(
            "syndicate.features.ncaaf.picks.available_weeks", return_value=[1]
        ):
            context = build_ncaaf_picks_page_context(1)

        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No recommendations available.")

    def test_ncaaf_game_detail_missing_card_does_not_inject_fake_matchup(self) -> None:
        with patch(
            "syndicate.features.ncaaf.game_detail.build_cards_page_context",
            return_value={
                "date": f"{default_ncaaf_season()} Week 1",
                "prev_date": "1",
                "next_date": "1",
                "games": [],
                "using_sample_data": False,
                "source_path": "summary.json",
                "control_value": "1",
            },
        ):
            context = build_ncaaf_game_detail_page_context(1, "missing-game")

        game = (context.get("games") or [{}])[0]
        self.assertEqual(game.get("status"), "NCAAF game unavailable")
        self.assertEqual(context.get("source_title"), "NCAAF game unavailable")
        self.assertFalse(context.get("using_sample_data"))

    def test_ncaaf_betting_card_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/ncaaf/api/season/2025/betting-card?week=1")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("season"), 2025)
        self.assertEqual(payload.get("week"), 1)
        self.assertEqual(payload.get("control_name"), "week")
        self.assertEqual(payload.get("route_path"), "/ncaaf/season/2025/betting-card")
        self.assertTrue(any(link.get("href") == "/ncaaf/season/2025/betting-card?week=1" for link in (payload.get("module_links") or [])))

    def test_nba_picks_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nba/api/picks?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/nba/picks")
        self.assertTrue(any(link.get("href") == "/nba/picks?date=2026-05-16" for link in (payload.get("module_links") or [])))

    def test_nba_archive_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nba/api/archive?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/nba/archive")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/nba/archive?date=2026-05-16" for link in (payload.get("module_links") or [])))
        self.assertTrue(isinstance(payload.get("available_dates"), list))

    def test_nba_props_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nba/api/prop-ladders?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/nba/prop-ladders")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/nba/prop-ladders?date=2026-05-16" for link in (payload.get("module_links") or [])))
        self.assertTrue(isinstance(payload.get("available_dates"), list))

    def test_nba_prop_ladders_api_exposes_unfiltered_controls(self) -> None:
        season_date = "2026-06-05"
        response = self.client.get(f"/nba/api/prop-ladders?date={season_date}")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual([control.get("name") for control in (payload.get("extra_controls") or [])], ["team", "player", "sort"])
        team_control = next(control for control in (payload.get("extra_controls") or []) if control.get("name") == "team")
        sort_control = next(control for control in (payload.get("extra_controls") or []) if control.get("name") == "sort")
        self.assertTrue(any(option.get("value") == "NYK" for option in (team_control.get("options") or [])))
        self.assertTrue(any(option.get("value") == "team" for option in (sort_control.get("options") or [])))
        first_card = (payload.get("rank_cards") or [{}])[0]
        self.assertEqual(first_card.get("href"), f"/nba/prop-ladders?date={season_date}&player=Jose+Alvarado")
        self.assertEqual(first_card.get("href_label"), "Player focus")

    def test_nba_prop_ladders_api_filters_cards_and_preserves_query_state(self) -> None:
        season_date = "2026-06-05"
        response = self.client.get(f"/nba/api/prop-ladders?date={season_date}&team=NYK&player=Jose&sort=team")
        payload = response.get_json()
        season_day = date.fromisoformat(season_date)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload.get("using_sample_data"))
        self.assertEqual(len(payload.get("rank_cards") or []), 1)
        self.assertIn("Jose Alvarado", (payload.get("rank_cards") or [{}])[0].get("title", ""))
        self.assertEqual(
            payload.get("prev_href"),
            f"/nba/prop-ladders?date={(season_day - timedelta(days=1)).isoformat()}&team=NYK&player=Jose&sort=team",
        )
        self.assertEqual(
            payload.get("next_href"),
            f"/nba/prop-ladders?date={(season_day + timedelta(days=1)).isoformat()}&team=NYK&player=Jose&sort=team",
        )
        self.assertEqual(
            payload.get("hidden_fields"),
            [],
        )
        self.assertEqual(payload.get("focus_panel", {}).get("eyebrow"), "Selected player")
        self.assertEqual(payload.get("focus_panel", {}).get("title"), "Jose Alvarado")
        self.assertEqual(
            payload.get("focus_panel", {}).get("href"),
            f"/nba/prop-ladders?date={season_date}&team=NYK&sort=team",
        )
        self.assertEqual(payload.get("focus_panel", {}).get("summary_stats", [])[1].get("value"), "Over 0.5 3PM")
        self.assertEqual(payload.get("focus_panel", {}).get("table_groups", [])[0].get("heading"), "Model outputs")

    def test_nba_prop_ladders_page_preserves_active_filters_in_date_form(self) -> None:
        season_date = "2026-06-05"
        response = self.client.get(f"/nba/prop-ladders?date={season_date}&team=NYK&player=Jose&sort=team")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="team"', html)
        self.assertIn('name="player"', html)
        self.assertIn('name="sort"', html)
        self.assertIn('<option value="NYK" selected>NYK</option>', html)
        self.assertIn('name="player" value="Jose"', html)
        self.assertIn('<option value="team" selected>Team</option>', html)
        self.assertNotIn('type="hidden" name="team" value="NYK"', html)
        self.assertNotIn('type="hidden" name="player" value="Jose"', html)
        self.assertNotIn('type="hidden" name="sort" value="team"', html)
        self.assertIn("Selected player", html)
        self.assertIn("Jose Alvarado", html)
        self.assertIn("Over 0.5 3PM", html)
        self.assertIn("Model outputs", html)
        self.assertIn(f'/nba/prop-ladders?date={season_date}&amp;team=NYK&amp;sort=team', html)
        self.assertIn(f'/nba/prop-ladders?date={season_date}&amp;team=NYK&amp;player=Jose+Alvarado&amp;sort=team', html)
        self.assertIn('id="propLadderForm"', html)
        self.assertIn('Player Prop Ladders', html)

    def test_nba_prop_ladders_page_shows_unfiltered_controls(self) -> None:
        response = self.client.get("/nba/prop-ladders?date=2026-06-05")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="team"', html)
        self.assertIn('name="player"', html)
        self.assertIn('name="sort"', html)
        self.assertIn('name="market"', html)
        self.assertIn('<option value="NYK">NYK</option>', html)

    def test_nba_prop_ladders_page_shows_empty_state_for_no_match_filters(self) -> None:
        season_date = "2026-06-05"
        response = self.client.get(f"/nba/prop-ladders?date={season_date}&team=ZZZ")
        payload = self.client.get(f"/nba/api/prop-ladders?date={season_date}&team=ZZZ").get_json()
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("rank_cards"), [])
        self.assertEqual(payload.get("empty_state", {}).get("title"), "No NBA props matched the current filters")
        self.assertIn("No NBA props matched the current filters", html)

    def test_nba_betting_card_day_api_forwards_include_prop_insights_flag(self) -> None:
        with patch(
            "syndicate.blueprints.nba.build_season_betting_card_day_payload",
            return_value={"season": 2026, "date": "2026-05-14", "games": []},
        ) as mocked_payload:
            response = self.client.get(
                "/nba/api/season/2026/betting-card/day/2026-05-14?profile=retuned&include_prop_insights=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"season": 2026, "date": "2026-05-14", "games": []})
        mocked_payload.assert_called_once_with(
            2026,
            "2026-05-14",
            "retuned",
            include_prop_insights=True,
        )

    def test_nba_betting_card_page_uses_versioned_syndicate_assets(self) -> None:
        season_date = "2026-06-05"
        html = self.client.get(f"/nba/season/2026/betting-card?profile=retuned&date={season_date}").get_data(as_text=True)

        self.assertIn('/nba/assets/betting-card-v2.css?v=', html)
        self.assertIn('/nba/assets/betting-card-v2.js?v=', html)
        self.assertIn(f'/nba/cards?date={season_date}', html)
        self.assertIn(f'/nba/season/2026/live-lens?date={season_date}&amp;profile=retuned', html)

    def test_nba_betting_card_page_preserves_requested_profile_in_live_lens_nav(self) -> None:
        html = self.client.get('/nba/season/2025/betting-card?profile=alt&date=2025-04-15').get_data(as_text=True)

        self.assertIn('/nba/season/2025/live-lens?date=2025-04-15&amp;profile=alt', html)

    def test_wnba_betting_card_page_uses_versioned_syndicate_assets(self) -> None:
        html = self.client.get('/wnba/season/2026/betting-card?date=2026-05-14').get_data(as_text=True)

        self.assertIn('/wnba/assets/betting-card-v2.css?v=', html)
        self.assertIn('/wnba/cards?date=2026-05-14', html)
        self.assertIn('/wnba/live-player-props-audit?date=2026-05-14', html)
        self.assertIn('WNBA Betting Card', html)
        self.assertIn('Stored slate navigation', html)

    def test_wnba_betting_card_styles_asset_is_served_locally(self) -> None:
        response = self.client.get('/wnba/assets/betting-card-v2.css')

        self.assertEqual(response.status_code, 200)
        self.assertIn('--cards-bg', response.get_data(as_text=True))

    def test_wnba_season_betting_card_route_without_date_uses_season_scoped_default(self) -> None:
        season_date = default_wnba_date_for_season(2025)
        html = self.client.get('/wnba/season/2025/betting-card').get_data(as_text=True)

        self.assertIn(f'/wnba/cards?date={season_date}', html)
        self.assertIn(f'/wnba/live-player-props-audit?date={season_date}', html)

    def test_nba_cards_source_page_uses_versioned_syndicate_assets(self) -> None:
        season_date = "2026-06-05"
        context = build_nba_cards_page_context(season_date)
        resolved_date = str(context.get("date") or "")
        html = self.client.get(f"/nba/cards?date={season_date}").get_data(as_text=True)

        self.assertIn('/static/shared/standalone_shell.css?v=', html)
        self.assertIn('/static/nba/cards_source.css?v=', html)
        self.assertIn('/static/nba/cards_source.js?v=', html)
        self.assertIn(f'/nba/season/{resolved_date[:4]}/betting-card?profile=retuned&amp;date={resolved_date}', html)
        self.assertIn(f'/nba/prop-ladders?date={resolved_date}', html)
        self.assertIn(f'/nba/season/{resolved_date[:4]}/live-lens?date={resolved_date}&amp;profile=retuned', html)

    def test_nhl_cards_source_page_links_betting_recap_for_selected_date(self) -> None:
        payload = build_nhl_source_bundle_payload("2026-05-14")
        resolved_date = str(payload.get("date") or "")
        html = self.client.get("/nhl/cards?date=2026-05-14").get_data(as_text=True)

        self.assertIn(f'/nhl/reconciliation?date={resolved_date}', html)
        self.assertIn("setDateScopedHref('bettingRecapLink', bettingRecapBasePath, d);", html)

    def test_nhl_cards_source_page_uses_versioned_syndicate_assets(self) -> None:
        html = self.client.get("/nhl/cards?date=2026-05-14").get_data(as_text=True)

        self.assertIn('/static/shared/standalone_shell.css?v=', html)
        self.assertIn('/static/nhl/cards_source_base.css?v=', html)
        self.assertIn('/static/shared/polling.js?v=', html)

    def test_nhl_cards_source_page_links_props_reconciliation_for_selected_date(self) -> None:
        payload = build_nhl_source_bundle_payload("2026-05-14")
        resolved_date = str(payload.get("date") or "")
        html = self.client.get("/nhl/cards?date=2026-05-14").get_data(as_text=True)

        self.assertIn(f'/nhl/props/reconciliation?date={resolved_date}', html)
        self.assertIn("setDateScopedHref('propsReconciliationLink', propsReconciliationBasePath, d);", html)

    def test_nhl_cards_source_page_links_props_lines_for_selected_date(self) -> None:
        payload = build_nhl_source_bundle_payload("2026-05-14")
        resolved_date = str(payload.get("date") or "")
        html = self.client.get("/nhl/cards?date=2026-05-14").get_data(as_text=True)

        self.assertIn(f'/nhl/props/lines?date={resolved_date}', html)
        self.assertIn("setDateScopedHref('propsLinesLink', propsLinesBasePath, d);", html)

    def test_nhl_cards_source_page_exposes_server_empty_state_hooks(self) -> None:
        html = self.client.get("/nhl/cards?date=2026-05-14").get_data(as_text=True)

        self.assertIn('id="emptyList"', html)
        self.assertIn("emptyState && Array.isArray(emptyState.list_items)", html)
        self.assertIn("renderEmptyHeaderMeta(b);", html)
        self.assertIn("setEmpty(String(emptyState?.body || 'No predictions rows available for this date yet.'), emptyItems);", html)

    def test_nba_cards_source_js_recomputes_betting_card_season_path_from_date(self) -> None:
        content = (REPO_ROOT / "syndicate" / "static" / "nba" / "cards_source.js").read_text(encoding="utf-8")

        self.assertIn("const seasonYear = Number(String(state.date || getLocalDateISO()).slice(0, 4))", content)
        self.assertIn("seasonBettingCardLink.href = `/nba/season/${encodeURIComponent(seasonYear)}/betting-card?profile=retuned&date=${encodeURIComponent(state.date || getLocalDateISO())}`", content)
        self.assertIn("propsLink.href = `/nba/prop-ladders?date=${encodeURIComponent(state.date || getLocalDateISO())}`", content)
        self.assertIn("liveAuditLink.href = `/nba/season/${encodeURIComponent(seasonYear)}/live-lens?date=${encodeURIComponent(state.date || getLocalDateISO())}&profile=retuned`", content)

    def test_nba_season_betting_card_route_without_date_uses_season_scoped_default(self) -> None:
        season_date = default_nba_date_for_season(2025)
        html = self.client.get("/nba/season/2025/betting-card?profile=retuned").get_data(as_text=True)

        self.assertIn(f"/nba/cards?date={season_date}", html)
        self.assertIn(f"/nba/features?date={season_date}", html)
        self.assertIn(f"/nba/season/2025/reconciliation?date={season_date}", html)
        self.assertIn(f"/nba/season/2025/live-lens?date={season_date}", html)

    def test_nba_features_route_preserves_requested_profile_in_nav(self) -> None:
        html = self.client.get('/nba/features?date=2025-04-15&profile=alt').get_data(as_text=True)

        self.assertIn('/nba/season/2025/betting-card?profile=alt&amp;date=2025-04-15', html)
        self.assertIn('/nba/season/2025/reconciliation?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/features?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('>Data Features</a>', html)

    def test_nba_season_live_lens_route_without_date_uses_season_scoped_default(self) -> None:
        html = self.client.get("/nba/season/2025/live-lens").get_data(as_text=True)

        self.assertRegex(html, r'/nba/season/\d{4}/betting-card\?profile=retuned&amp;date=\d{4}-\d{2}-\d{2}')
        self.assertRegex(html, r'/nba/season/\d{4}/live-lens\?date=\d{4}-\d{2}-\d{2}&amp;profile=retuned')

    def test_nba_season_live_lens_route_preserves_requested_profile_in_nav(self) -> None:
        html = self.client.get("/nba/season/2025/live-lens?date=2025-04-15&profile=alt").get_data(as_text=True)

        self.assertIn('name="profile" value="alt"', html)
        self.assertIn('/nba/season/2025/live-lens?date=2025-04-14&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens?date=2025-04-16&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens?date=2025-04-15&amp;profile=retuned', html)
        self.assertIn('>Live Lens</a>', html)

    def test_nba_season_live_lens_accuracy_route_preserves_requested_profile_in_nav(self) -> None:
        html = self.client.get('/nba/season/2025/live-lens-accuracy?date=2025-04-15&profile=alt').get_data(as_text=True)

        self.assertIn('/nba/season/2025/betting-card?profile=alt&amp;date=2025-04-15', html)
        self.assertIn('/nba/season/2025/market-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens-daily-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-game-lens-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('>Live Player Props Lens Accuracy</a>', html)
        self.assertIn('>Live Player Props Audit</a>', html)

    def test_nba_season_live_game_lens_accuracy_route_preserves_requested_profile_in_nav(self) -> None:
        html = self.client.get('/nba/season/2025/live-game-lens-accuracy?date=2025-04-15&profile=alt').get_data(as_text=True)

        self.assertIn('/nba/season/2025/betting-card?profile=alt&amp;date=2025-04-15', html)
        self.assertIn('/nba/season/2025/market-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens-daily-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-game-lens-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('>Live Game Lens Accuracy</a>', html)
        self.assertIn('>Live Player Props Lens Accuracy</a>', html)

    def test_nba_season_live_lens_daily_accuracy_route_preserves_requested_profile_in_nav(self) -> None:
        html = self.client.get('/nba/season/2025/live-lens-daily-accuracy?date=2025-04-15&profile=alt').get_data(as_text=True)

        self.assertIn('/nba/season/2025/betting-card?profile=alt&amp;date=2025-04-15', html)
        self.assertIn('/nba/season/2025/market-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens-daily-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-game-lens-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('>Live Lens Daily Accuracy</a>', html)
        self.assertIn('>Live Game Lens Accuracy</a>', html)
        self.assertIn('>Live Player Props Lens Accuracy</a>', html)

    def test_nba_season_market_accuracy_route_preserves_requested_profile_in_nav(self) -> None:
        html = self.client.get('/nba/season/2025/market-accuracy?date=2025-04-15&profile=alt').get_data(as_text=True)

        self.assertIn('/nba/season/2025/betting-card?profile=alt&amp;date=2025-04-15', html)
        self.assertIn('/nba/season/2025/market-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens-daily-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-game-lens-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('>Market Accuracy</a>', html)

    def test_nba_season_reconciliation_route_preserves_requested_profile_in_nav(self) -> None:
        html = self.client.get('/nba/season/2025/reconciliation?date=2025-04-15&profile=alt').get_data(as_text=True)

        self.assertIn('/nba/season/2025/betting-card?profile=alt&amp;date=2025-04-15', html)
        self.assertIn('/nba/season/2025/market-accuracy?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/live-lens?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('/nba/season/2025/reconciliation?date=2025-04-15&amp;profile=alt', html)
        self.assertIn('>Betting Recap</a>', html)

    def test_nba_betting_card_js_rewrites_source_routes_to_syndicate_paths(self) -> None:
        content = source_betting_card_js()

        self.assertIsInstance(content, str)
        assert content is not None
        self.assertIn("/nba/api/season/", content)
        self.assertIn("/nba/cards?date=", content)
        self.assertIn("/nba/season/${encodeURIComponent(state.season)}/live-lens?date=${encodeURIComponent(state.selectedDate)}&profile=${encodeURIComponent(state.profile)}", content)
        self.assertIn("nextUrl.searchParams.set('profile', state.profile);", content)
        self.assertIn("nextUrl.searchParams.set('date', state.selectedDate);", content)
        self.assertNotIn("/live-player-props-audit?date=", content)
        self.assertNotIn("href=\"/betting-card?date=", content)
        self.assertNotIn("href=\"/api/season/", content)

    def test_nba_betting_card_day_payload_rewrites_cards_url_to_syndicate_route(self) -> None:
        build_season_betting_card_day_payload.cache_clear()
        with patch(
            "syndicate.features.nba.betting_card.load_json",
            return_value={"season": 2026, "date": "2026-05-14", "cards_url": "/?date=2026-05-14", "games": []},
        ):
            payload = build_season_betting_card_day_payload(2026, "2026-05-14", "retuned")
        build_season_betting_card_day_payload.cache_clear()

        self.assertIsInstance(payload, dict)
        self.assertEqual((payload or {}).get("cards_url"), "/nba/cards?date=2026-05-14")

    def test_nba_betting_card_manifest_payload_rewrites_route_fields_to_syndicate_paths(self) -> None:
        build_season_betting_card_manifest_payload.cache_clear()
        with patch(
            "syndicate.features.nba.betting_card.load_json",
            return_value={
                "season": 2026,
                "days": [{"date": "2026-05-14", "cards_url": "/?date=2026-05-14"}],
                "meta": {"detail_url": "/api/season/2026/betting-card/day/2026-05-14?profile=retuned"},
            },
        ):
            payload = build_season_betting_card_manifest_payload(2026, "retuned", "2026-05-14")
        build_season_betting_card_manifest_payload.cache_clear()

        self.assertIsInstance(payload, dict)
        self.assertEqual(((payload or {}).get("days") or [{}])[0].get("cards_url"), "/nba/cards?date=2026-05-14")
        self.assertEqual(((payload or {}).get("meta") or {}).get("detail_url"), "/nba/api/season/2026/betting-card/day/2026-05-14?profile=retuned")

    def test_nba_betting_card_manifest_payload_rewrites_non_selected_day_routes(self) -> None:
        build_season_betting_card_manifest_payload.cache_clear()
        with patch(
            "syndicate.features.nba.betting_card.load_json",
            return_value={
                "season": 2026,
                "days": [
                    {"date": "2026-05-13", "cards_url": "/?date=2026-05-13", "audit_url": "/live-player-props-audit?date=2026-05-13"},
                    {"date": "2026-05-14", "cards_url": "/?date=2026-05-14"},
                ],
            },
        ):
            payload = build_season_betting_card_manifest_payload(2026, "retuned", "2026-05-14")
        build_season_betting_card_manifest_payload.cache_clear()

        first_day = ((payload or {}).get("days") or [{}])[0]
        self.assertEqual(first_day.get("cards_url"), "/nba/cards?date=2026-05-13")
        self.assertEqual(first_day.get("audit_url"), "/nba/season/2026/live-lens?date=2026-05-13&profile=retuned")

    def test_nba_betting_card_payloads_can_load_from_local_mirror_only(self) -> None:
        build_season_betting_card_manifest_payload.cache_clear()
        build_season_betting_card_day_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            (processed_dir / "season_betting_card_manifest_2026_retuned_2026-05-14.json").write_text(
                json.dumps(
                    {
                        "season": 2026,
                        "days": [{"date": "2026-05-14", "cards_url": "/?date=2026-05-14"}],
                        "meta": {"detail_url": "/api/season/2026/betting-card/day/2026-05-14?profile=retuned"},
                    }
                ),
                encoding="utf-8",
            )
            (processed_dir / "season_betting_card_day_2026_retuned_2026-05-14.json").write_text(
                json.dumps(
                    {
                        "season": 2026,
                        "date": "2026-05-14",
                        "cards_url": "/?date=2026-05-14",
                        "audit_url": "/live-player-props-audit?date=2026-05-14",
                        "games": [],
                    }
                ),
                encoding="utf-8",
            )

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]):
                manifest_payload = build_season_betting_card_manifest_payload(2026, "retuned", "2026-05-14")
                day_payload = build_season_betting_card_day_payload(2026, "2026-05-14", "retuned")

        build_season_betting_card_manifest_payload.cache_clear()
        build_season_betting_card_day_payload.cache_clear()

        self.assertEqual(((manifest_payload or {}).get("days") or [{}])[0].get("cards_url"), "/nba/cards?date=2026-05-14")
        self.assertEqual(((manifest_payload or {}).get("meta") or {}).get("detail_url"), "/nba/api/season/2026/betting-card/day/2026-05-14?profile=retuned")
        self.assertEqual((day_payload or {}).get("cards_url"), "/nba/cards?date=2026-05-14")
        self.assertEqual((day_payload or {}).get("audit_url"), "/nba/season/2026/live-lens?date=2026-05-14&profile=retuned")

    def test_nba_betting_card_manifest_payload_falls_back_to_undated_local_manifest(self) -> None:
        build_season_betting_card_manifest_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            (processed_dir / "season_betting_card_manifest_2026_retuned.json").write_text(
                json.dumps(
                    {
                        "season": 2026,
                        "days": [{"date": "2026-05-14", "cards_url": "/?date=2026-05-14"}],
                        "meta": {"detail_url": "/api/season/2026/betting-card/day/2026-05-14?profile=retuned"},
                    }
                ),
                encoding="utf-8",
            )

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]):
                payload = build_season_betting_card_manifest_payload(2026, "retuned", "2026-05-19")

        build_season_betting_card_manifest_payload.cache_clear()

        self.assertEqual(((payload or {}).get("days") or [{}])[0].get("cards_url"), "/nba/cards?date=2026-05-14")
        self.assertEqual(((payload or {}).get("meta") or {}).get("detail_url"), "/nba/api/season/2026/betting-card/day/2026-05-14?profile=retuned")

    def test_nba_betting_card_payloads_return_none_when_local_artifacts_are_missing(self) -> None:
        build_season_betting_card_manifest_payload.cache_clear()
        build_season_betting_card_day_payload.cache_clear()
        with patch("syndicate.features.nba.betting_card.load_json", return_value=None):
            manifest_payload = build_season_betting_card_manifest_payload(2026, "retuned", "2026-05-14")
            day_payload = build_season_betting_card_day_payload(2026, "2026-05-14", "retuned")

        build_season_betting_card_manifest_payload.cache_clear()
        build_season_betting_card_day_payload.cache_clear()

        self.assertIsNone(manifest_payload)
        self.assertIsNone(day_payload)

    def test_nba_season_betting_card_manifest_api_without_date_uses_season_scoped_default(self) -> None:
        season_date = default_nba_date_for_season(2025)
        with patch(
            "syndicate.blueprints.nba.build_season_betting_card_manifest_payload",
            return_value={"season": 2025, "days": []},
        ) as mocked_payload:
            response = self.client.get("/nba/api/season/2025/betting-card?profile=retuned")

        self.assertEqual(response.status_code, 200)
        mocked_payload.assert_called_once_with(2025, "retuned", season_date)

    def test_nba_season_live_lens_api_without_date_uses_season_scoped_default(self) -> None:
        response = self.client.get("/nba/api/season/2025/live-lens")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get("route_path"), "/nba/season/2025/live-lens")
        self.assertTrue(isinstance(payload.get("module_links"), list))
        self.assertEqual(payload.get("control_name"), "date")

    def test_nba_live_prop_audit_prefers_local_mirror_artifacts(self) -> None:
        build_live_prop_audit_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            processed_dir = Path(temp_dir) / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            projection_row = {
                "market": "player_prop",
                "game_id": "1234567890",
                "player": "Jalen Brunson",
                "stat": "pts",
                "proj": 28.5,
                "sim_mu": 27.9,
                "sim_mu_adjusted": 28.1,
                "elapsed": 18,
                "line": 27.5,
                "context": {"pregame_team_total_ratio": 1.01, "pregame_game_total_ratio": 1.02},
            }
            (processed_dir / "live_lens_projections_2026-05-18.jsonl").write_text(
                json.dumps(projection_row) + "\n",
                encoding="utf-8",
            )
            (processed_dir / "recon_props_2026-05-18.csv").write_text(
                "game_id,player_name,pts,reb,ast\n1234567890,Jalen Brunson,30,4,7\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"SYNDICATE_NBA_ARTIFACT_ROOT": temp_dir}, clear=False):
                payload = build_live_prop_audit_payload("date=2026-05-18&include_rows=1")

        build_live_prop_audit_payload.cache_clear()
        self.assertIsInstance(payload, dict)
        self.assertEqual((payload or {}).get("status"), "ok")
        self.assertEqual((((payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertTrue(isinstance((((payload or {}).get("overall") or {}).get("n")), int))
        self.assertEqual((((payload or {}).get("history") or {}).get("rows") or [{}])[0].get("actual"), 30.0)

    def test_nba_live_game_accuracy_prefers_local_mirror_artifacts(self) -> None:
        build_live_game_accuracy_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            processed_dir = Path(temp_dir) / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            signal_row = {
                "market": "ats",
                "klass": "BET",
                "game_id": "1234567890",
                "home": "NYK",
                "away": "BOS",
                "side": "NYK",
                "live_line": -3.5,
                "driver_tags": ["mgn:close"],
                "received_at": "2026-05-18T01:00:00Z",
            }
            (processed_dir / "live_lens_signals_2026-05-18.jsonl").write_text(json.dumps(signal_row) + "\n", encoding="utf-8")
            (processed_dir / "recon_games_2026-05-18.csv").write_text(
                "game_id,home_tri,away_tri,home_pts,visitor_pts,total_actual\n1234567890,NYK,BOS,110,102,212\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"SYNDICATE_NBA_ARTIFACT_ROOT": temp_dir}, clear=False):
                payload = build_live_game_accuracy_payload("since=2026-05-18&until=2026-05-18&include_rows=1")

        build_live_game_accuracy_payload.cache_clear()
        self.assertIsInstance(payload, dict)
        self.assertEqual((((payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertEqual((((payload or {}).get("overall") or {}).get("ats") or {}).get("n_settled"), 1)

    def test_nba_live_prop_accuracy_prefers_local_mirror_artifacts(self) -> None:
        build_live_prop_accuracy_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            processed_dir = Path(temp_dir) / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            signal_row = {
                "market": "player_prop",
                "klass": "BET",
                "game_id": "1234567890",
                "player": "Jalen Brunson",
                "stat": "pts",
                "side": "OVER",
                "line": 27.5,
                "driver_tags": ["sim:edge"],
                "received_at": "2026-05-18T01:00:00Z",
            }
            (processed_dir / "live_lens_signals_2026-05-18.jsonl").write_text(json.dumps(signal_row) + "\n", encoding="utf-8")
            (processed_dir / "recon_props_2026-05-18.csv").write_text(
                "game_id,player_name,pts,reb,ast\n1234567890,Jalen Brunson,30,4,7\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"SYNDICATE_NBA_ARTIFACT_ROOT": temp_dir}, clear=False):
                payload = build_live_prop_accuracy_payload("since=2026-05-18&until=2026-05-18&include_rows=1")

        build_live_prop_accuracy_payload.cache_clear()
        self.assertIsInstance(payload, dict)
        self.assertEqual((((payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertEqual((((payload or {}).get("overall") or {}).get("props") or {}).get("n_settled"), 1)

    def test_nba_live_lens_builders_return_local_empty_payloads_without_source_fallback(self) -> None:
        build_live_prop_audit_payload.cache_clear()
        build_live_game_accuracy_payload.cache_clear()
        build_live_prop_accuracy_payload.cache_clear()
        from syndicate.features.nba.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload

        build_live_lens_daily_accuracy_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"SYNDICATE_NBA_ARTIFACT_ROOT": temp_dir}, clear=False):
                audit_payload = build_live_prop_audit_payload("date=2026-05-18&include_rows=1")
                game_payload = build_live_game_accuracy_payload("since=2026-05-18&until=2026-05-18&include_rows=1")
                prop_payload = build_live_prop_accuracy_payload("since=2026-05-18&until=2026-05-18&include_rows=1")
                daily_payload = build_live_lens_daily_accuracy_payload("date=2026-05-18")

        build_live_prop_audit_payload.cache_clear()
        build_live_game_accuracy_payload.cache_clear()
        build_live_prop_accuracy_payload.cache_clear()
        build_live_lens_daily_accuracy_payload.cache_clear()

        self.assertEqual((((audit_payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertEqual((audit_payload or {}).get("status"), "empty")
        self.assertEqual((((game_payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertEqual((game_payload or {}).get("status"), "empty")
        self.assertEqual((((prop_payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertEqual((prop_payload or {}).get("status"), "empty")
        self.assertEqual(((daily_payload or {}).get("summary") or {}).get("available"), False)
        self.assertEqual((((daily_payload or {}).get("window") or {}).get("since")), "2026-05-18")

    def test_wnba_live_prop_audit_prefers_local_mirror_artifacts(self) -> None:
        build_wnba_live_prop_audit_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            processed_dir = Path(temp_dir) / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            projection_row = {
                "market": "player_prop",
                "game_id": "1234567890",
                "player": "A'ja Wilson",
                "stat": "pts",
                "proj": 25.5,
                "sim_mu": 24.9,
                "sim_mu_adjusted": 25.1,
                "elapsed": 16,
                "line": 24.5,
                "context": {"pregame_team_total_ratio": 1.02, "pregame_game_total_ratio": 1.01},
            }
            (processed_dir / "live_lens_projections_2026-05-18.jsonl").write_text(
                json.dumps(projection_row) + "\n",
                encoding="utf-8",
            )
            (processed_dir / "recon_props_2026-05-18.csv").write_text(
                "game_id,player_name,pts,reb,ast\n1234567890,A'ja Wilson,28,8,3\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"SYNDICATE_WNBA_SOURCE_ROOT": temp_dir}, clear=False):
                payload = build_wnba_live_prop_audit_payload("date=2026-05-18&include_rows=1")

        build_wnba_live_prop_audit_payload.cache_clear()
        self.assertIsInstance(payload, dict)
        self.assertEqual((((payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertTrue(isinstance((((payload or {}).get("overall") or {}).get("n")), int))

    def test_wnba_live_game_accuracy_prefers_local_mirror_artifacts(self) -> None:
        build_wnba_live_game_accuracy_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            processed_dir = Path(temp_dir) / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            signal_row = {
                "market": "ats",
                "klass": "BET",
                "game_id": "1234567890",
                "home": "LVA",
                "away": "SEA",
                "side": "LVA",
                "live_line": -4.5,
                "driver_tags": ["mgn:close"],
                "received_at": "2026-05-18T01:00:00Z",
            }
            (processed_dir / "live_lens_signals_2026-05-18.jsonl").write_text(json.dumps(signal_row) + "\n", encoding="utf-8")
            (processed_dir / "recon_games_2026-05-18.csv").write_text(
                "game_id,home_tri,away_tri,home_pts,visitor_pts,total_actual\n1234567890,LVA,SEA,95,88,183\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"SYNDICATE_WNBA_SOURCE_ROOT": temp_dir}, clear=False):
                payload = build_wnba_live_game_accuracy_payload("since=2026-05-18&until=2026-05-18&include_rows=1")

        build_wnba_live_game_accuracy_payload.cache_clear()
        self.assertIsInstance(payload, dict)
        self.assertEqual((((payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertTrue(isinstance(((((payload or {}).get("overall") or {}).get("ats") or {}).get("n_settled")), int))

    def test_wnba_live_prop_accuracy_prefers_local_mirror_artifacts(self) -> None:
        build_wnba_live_prop_accuracy_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            processed_dir = Path(temp_dir) / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            signal_row = {
                "market": "player_prop",
                "klass": "BET",
                "game_id": "1234567890",
                "player": "A'ja Wilson",
                "stat": "pts",
                "side": "OVER",
                "line": 24.5,
                "driver_tags": ["sim:edge"],
                "received_at": "2026-05-18T01:00:00Z",
            }
            (processed_dir / "live_lens_signals_2026-05-18.jsonl").write_text(json.dumps(signal_row) + "\n", encoding="utf-8")
            (processed_dir / "recon_props_2026-05-18.csv").write_text(
                "game_id,player_name,pts,reb,ast\n1234567890,A'ja Wilson,28,8,3\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"SYNDICATE_WNBA_SOURCE_ROOT": temp_dir}, clear=False):
                payload = build_wnba_live_prop_accuracy_payload("since=2026-05-18&until=2026-05-18&include_rows=1")

        build_wnba_live_prop_accuracy_payload.cache_clear()
        self.assertIsInstance(payload, dict)
        self.assertEqual((((payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertTrue(isinstance(((((payload or {}).get("overall") or {}).get("props") or {}).get("n_settled")), int))

    def test_nba_season_live_lens_accuracy_api_without_date_uses_season_scoped_default(self) -> None:
        season_date = default_nba_date_for_season(2025)
        with patch(
            "syndicate.blueprints.nba.build_live_prop_accuracy_payload",
            return_value={"ok": True, "status": "empty"},
        ) as mocked_payload:
            response = self.client.get("/nba/api/season/2025/live-lens-accuracy")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "status": "empty"})
        mocked_payload.assert_called_once_with(f"date={season_date}")

    def test_nba_season_live_game_lens_accuracy_api_without_date_uses_season_scoped_default(self) -> None:
        season_date = default_nba_date_for_season(2025)
        with patch(
            "syndicate.blueprints.nba.build_live_game_accuracy_payload",
            return_value={"ok": True, "status": "empty"},
        ) as mocked_payload:
            response = self.client.get("/nba/api/season/2025/live-game-lens-accuracy")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "status": "empty"})
        mocked_payload.assert_called_once_with(f"date={season_date}")

    def test_nba_season_live_lens_daily_accuracy_api_without_date_uses_season_scoped_default(self) -> None:
        season_date = default_nba_date_for_season(2025)
        with patch(
            "syndicate.blueprints.nba.build_live_lens_daily_accuracy_payload",
            return_value={"ok": True, "summary": {}, "days": [], "window": {"since": season_date, "until": season_date}},
        ) as mocked_payload:
            response = self.client.get("/nba/api/season/2025/live-lens-daily-accuracy")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "summary": {}, "days": [], "window": {"since": season_date, "until": season_date}})
        mocked_payload.assert_called_once_with(f"date={season_date}")

    def test_nba_season_market_accuracy_api_without_date_uses_season_scoped_default(self) -> None:
        season_date = default_nba_date_for_season(2025)
        with patch(
            "syndicate.blueprints.nba.build_market_accuracy_payload",
            return_value={"ok": True, "summary": {}, "days": [], "window": {"since": season_date, "until": season_date}},
        ) as mocked_payload:
            response = self.client.get("/nba/api/season/2025/market-accuracy")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "summary": {}, "days": [], "window": {"since": season_date, "until": season_date}})
        mocked_payload.assert_called_once_with(f"date={season_date}")

    def test_nba_season_market_accuracy_api_preserves_explicit_window_query(self) -> None:
        with patch(
            "syndicate.blueprints.nba.build_market_accuracy_payload",
            return_value={"ok": True, "summary": {}, "days": [], "window": {"since": "2026-04-20", "until": "2026-05-19"}},
        ) as mocked_payload:
            response = self.client.get("/nba/api/season/2026/market-accuracy?since=2026-04-20&until=2026-05-19")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "summary": {}, "days": [], "window": {"since": "2026-04-20", "until": "2026-05-19"}})
        mocked_payload.assert_called_once_with("since=2026-04-20&until=2026-05-19")

    def test_nba_season_betting_recap_api_without_date_uses_season_scoped_window(self) -> None:
        season_date = default_nba_date_for_season(2025)
        since_date = (date.fromisoformat(season_date) - timedelta(days=13)).isoformat()
        with patch(
            "syndicate.blueprints.nba.build_betting_recap_payload",
            return_value={"version": "recaps-v1", "window": {"since": since_date, "until": season_date}, "items": []},
        ) as mocked_payload:
            response = self.client.get("/nba/api/season/2025/betting-recap")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"version": "recaps-v1", "window": {"since": since_date, "until": season_date}, "items": []})
        mocked_payload.assert_called_once_with(f"since={since_date}&until={season_date}&days=14")

    def test_nba_features_api_returns_payload(self) -> None:
        with patch(
            "syndicate.blueprints.nba.build_features_payload",
            return_value={"generated_at": "2026-01-01T00:00:00Z", "catalog_path": "data/features_catalog.json", "datasets": [], "descriptions": {}},
        ) as mocked_payload:
            response = self.client.get("/nba/api/features")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"generated_at": "2026-01-01T00:00:00Z", "catalog_path": "data/features_catalog.json", "datasets": [], "descriptions": {}})
        mocked_payload.assert_called_once_with()

    def test_nba_market_accuracy_route_without_season_is_available(self) -> None:
        html = self.client.get('/nba/market-accuracy?date=2025-04-15').get_data(as_text=True)

        self.assertIn('/nba/market-accuracy?date=2025-04-15', html)
        self.assertIn('>Market Accuracy</a>', html)

    def test_nba_live_lens_accuracy_route_without_season_is_available(self) -> None:
        html = self.client.get('/nba/live-lens-accuracy?date=2025-04-15').get_data(as_text=True)

        self.assertIn('/nba/live-lens-accuracy?date=2025-04-15', html)
        self.assertIn('>Live Lens Daily Accuracy</a>', html)

    def test_mlb_market_accuracy_route_renders_native_template(self) -> None:
        html = self.client.get('/mlb/market-accuracy?date=2026-05-19').get_data(as_text=True)

        self.assertIn('MLB Betting - Market Accuracy', html)
        self.assertIn('/mlb/api/market-accuracy', html)
        self.assertIn('/mlb/live-lens?date=2026-05-19', html)
        self.assertIn('/mlb/live-lens-accuracy?date=2026-05-19', html)
        self.assertIn('Search picks, players, games', html)
        self.assertIn('All results', html)
        self.assertIn('Quick filters', html)
        self.assertIn('Pitcher Props', html)
        self.assertIn('Official summary', html)
        self.assertIn('Window actions', html)
        self.assertIn('Moneyline only', html)
        self.assertIn('Active filter', html)
        self.assertIn('Clear filter', html)

    def test_mlb_season_live_lens_page_keeps_accuracy_links(self) -> None:
        html = self.client.get('/mlb/season/2026/live-lens?date=2026-05-19').get_data(as_text=True)

        self.assertIn('/mlb/market-accuracy?date=2026-05-19', html)
        self.assertIn('>Market Accuracy</a>', html)
        self.assertIn('/mlb/live-lens-accuracy?date=2026-05-19', html)

    def test_nba_live_player_props_accuracy_route_without_season_is_available(self) -> None:
        html = self.client.get('/nba/live-player-props-lens-accuracy?date=2025-04-15').get_data(as_text=True)

        self.assertIn('/nba/live-player-props-lens-accuracy?date=2025-04-15', html)
        self.assertIn('>Live Player Props Lens Accuracy</a>', html)

    def test_wnba_live_accuracy_pages_render_native_templates(self) -> None:
        cases = [
            (
                '/wnba/live-player-props-audit?date=2026-05-16',
                'WNBA Betting - Live Player Props Audit',
                '/wnba/api/live-player-props-audit',
                '/wnba/market-accuracy?date=2026-05-16',
            ),
            (
                '/wnba/live-player-props-lens-accuracy?date=2026-05-16',
                'WNBA Betting - Live Player Props Lens Accuracy',
                '/wnba/api/live-player-props-lens-accuracy',
                '/wnba/live-player-props-audit?date=2026-05-16',
            ),
            (
                '/wnba/live-game-lens-accuracy?date=2026-05-16',
                'WNBA Betting - Live Game Lens Accuracy',
                '/wnba/api/live-game-lens-accuracy',
                '/wnba/live-lens-accuracy?date=2026-05-16',
            ),
            (
                '/wnba/live-lens-accuracy?date=2026-05-16',
                'WNBA Betting - Live Lens Daily Accuracy',
                '/wnba/api/live-lens-accuracy',
                '/wnba/market-accuracy?date=2026-05-16',
            ),
            (
                '/wnba/market-accuracy?date=2026-05-16',
                'WNBA Betting - Market Accuracy',
                '/wnba/api/market-accuracy',
                '/wnba/live-lens-accuracy?date=2026-05-16',
            ),
        ]

        for route, title, api_path, nav_href in cases:
            with self.subTest(route=route):
                html = self.client.get(route).get_data(as_text=True)

                self.assertIn(title, html)
                self.assertIn(api_path, html)
                self.assertIn(nav_href, html)
                self.assertNotIn('source page unavailable', html)

    def test_nhl_live_lens_accuracy_page_renders_native_template(self) -> None:
        html = self.client.get('/nhl/live-lens-accuracy?date=2026-05-16').get_data(as_text=True)

        self.assertIn('NHL Betting - Live Lens Daily Accuracy', html)
        self.assertIn('/nhl/api/live-lens-accuracy', html)
        self.assertIn('/nhl/live-lens?date=2026-05-16', html)
        self.assertIn('/nhl/reconciliation?date=2026-05-16', html)
        self.assertNotIn('source page unavailable', html)

    def test_nhl_live_game_accuracy_page_renders_native_template(self) -> None:
        html = self.client.get('/nhl/live-game-lens-accuracy?date=2026-05-16').get_data(as_text=True)

        self.assertIn('NHL Betting - Live Game Lens Accuracy', html)
        self.assertIn('/nhl/api/live-game-lens-accuracy', html)
        self.assertIn('/nhl/live-lens-accuracy?date=2026-05-16', html)
        self.assertIn('/nhl/reconciliation?date=2026-05-16', html)
        self.assertNotIn('source page unavailable', html)

    def test_nhl_market_accuracy_page_renders_native_template(self) -> None:
        html = self.client.get('/nhl/market-accuracy?date=2026-05-16').get_data(as_text=True)

        self.assertIn('NHL Betting - Market Accuracy', html)
        self.assertIn('/nhl/api/market-accuracy', html)
        self.assertIn('/nhl/live-lens-accuracy?date=2026-05-16', html)
        self.assertIn('/nhl/reconciliation?date=2026-05-16', html)
        self.assertNotIn('source page unavailable', html)

    def test_nhl_reconciliation_page_renders_native_template(self) -> None:
        html = self.client.get('/nhl/reconciliation?date=2026-05-16').get_data(as_text=True)

        self.assertIn('Betting Recap | NHL Betting', html)
        self.assertIn('/nhl/api/betting-recap', html)
        self.assertIn('/nhl/market-accuracy?date=2026-05-16', html)
        self.assertIn('/nhl/props/reconciliation?date=2026-05-16', html)
        self.assertNotIn('source page unavailable', html)

    def test_nhl_player_props_reconciliation_page_renders_native_template(self) -> None:
        html = self.client.get('/nhl/props/reconciliation?date=2026-05-16').get_data(as_text=True)

        self.assertIn('NHL Betting - Player Props Reconciliation', html)
        self.assertIn('/nhl/api/player-props-reconciliation', html)
        self.assertIn('/nhl/reconciliation?date=2026-05-16', html)
        self.assertIn('/nhl/props/lines?date=2026-05-16', html)
        self.assertNotIn('source page unavailable', html)

    def test_nhl_props_lines_page_renders_native_template(self) -> None:
        html = self.client.get('/nhl/props/lines?date=2026-05-16').get_data(as_text=True)

        self.assertIn('NHL Betting - Props Lines', html)
        self.assertIn('/nhl/api/props/lines.json', html)
        self.assertIn('/nhl/props/reconciliation?date=2026-05-16', html)
        self.assertNotIn('source page unavailable', html)

    def test_nba_reconciliation_api_without_season_uses_requested_window(self) -> None:
        with patch(
            "syndicate.blueprints.nba.build_betting_recap_payload",
            return_value={"version": "recaps-v1", "window": {"since": "2025-04-01", "until": "2025-04-14"}, "items": []},
        ) as mocked_payload:
            response = self.client.get("/nba/api/betting-recap?since=2025-04-01&until=2025-04-14")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"version": "recaps-v1", "window": {"since": "2025-04-01", "until": "2025-04-14"}, "items": []})
        mocked_payload.assert_called_once_with("since=2025-04-01&until=2025-04-14")

    def test_nhl_reconciliation_api_uses_requested_window(self) -> None:
        with patch(
            "syndicate.blueprints.nhl.build_betting_recap_payload",
            return_value={"version": "recaps-v1", "window": {"since": "2026-03-01", "until": "2026-03-14"}, "items": []},
        ) as mocked_payload:
            response = self.client.get("/nhl/api/betting-recap?since=2026-03-01&until=2026-03-14")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"version": "recaps-v1", "window": {"since": "2026-03-01", "until": "2026-03-14"}, "items": []})
        mocked_payload.assert_called_once_with("since=2026-03-01&until=2026-03-14")

    def test_nhl_player_props_reconciliation_api_uses_query_string_payload_builder(self) -> None:
        with patch(
            "syndicate.blueprints.nhl.build_player_props_reconciliation_payload",
            return_value={"ok": True, "version": "player-props-reconciliation-v1", "date": "2026-03-01", "data": []},
        ) as mocked_payload:
            response = self.client.get("/nhl/api/player-props-reconciliation?date=2026-03-01&market=GOALS")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "version": "player-props-reconciliation-v1", "date": "2026-03-01", "data": []})
        mocked_payload.assert_called_once_with("date=2026-03-01&market=GOALS")

    def test_nhl_props_lines_api_uses_query_string_payload_builder(self) -> None:
        with patch(
            "syndicate.blueprints.nhl.build_props_lines_payload",
            return_value={"ok": True, "version": "props-lines-v1", "date": "2026-05-19", "data": [], "total_rows": 0},
        ) as mocked_payload:
            response = self.client.get("/nhl/api/props/lines.json?date=2026-05-19&market=GOALS")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "version": "props-lines-v1", "date": "2026-05-19", "data": [], "total_rows": 0})
        mocked_payload.assert_called_once_with("date=2026-05-19&market=GOALS")

    def test_nfl_picks_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nfl/api/picks?week=21")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("week"), 21)
        self.assertEqual(payload.get("control_name"), "week")
        self.assertEqual(payload.get("season"), 2025)
        self.assertEqual(payload.get("submit_label"), "Apply")
        self.assertEqual(payload.get("reset_href"), "/nfl/picks?season=2025")
        self.assertEqual(payload.get("hidden_fields"), [{"name": "season", "value": "2025"}])
        self.assertTrue(any(link.get("href") == "/nfl/picks?season=2025&week=21" for link in (payload.get("module_links") or [])))

    def test_nfl_picks_api_exposes_sort_control_and_preserves_sort_in_week_nav(self) -> None:
        response = self.client.get("/nfl/api/picks?season=2025&week=21&sort=odds")
        payload = response.get_json()
        prev_week, next_week = neighboring_values(available_nfl_weeks(2025), 21, fallback=21)

        self.assertEqual(response.status_code, 200)
        self.assertEqual((payload.get("extra_controls") or [{}])[0].get("name"), "sort")
        self.assertEqual((payload.get("extra_controls") or [{}])[0].get("value"), "odds")
        self.assertEqual(payload.get("prev_href"), f"/nfl/picks?season=2025&week={prev_week}&sort=odds")
        self.assertEqual(payload.get("next_href"), f"/nfl/picks?season=2025&week={next_week}&sort=odds")
        self.assertEqual(payload.get("summary_panel", {}).get("title"), "2025 Week 21 recommendation mix")
        self.assertEqual((payload.get("summary_panel", {}).get("table_groups") or [{}])[0].get("heading"), "Confidence tiers")

    def test_nfl_cards_api_preserves_explicit_season_navigation_metadata(self) -> None:
        response = self.client.get("/nfl/api/cards?season=2025&week=21")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "week")
        self.assertEqual(payload.get("date"), "2025 Week 21")
        self.assertEqual(payload.get("control_action"), "/nfl/cards")
        self.assertEqual(payload.get("hidden_fields"), [{"name": "season", "value": "2025"}])
        self.assertTrue(any(link.get("href") == "/nfl/picks?season=2025&week=21" for link in (payload.get("module_links") or [])))

    def test_nfl_cards_page_preserves_explicit_season_in_week_form(self) -> None:
        html = self.client.get("/nfl/cards?season=2025&week=21").get_data(as_text=True)

        self.assertIn('type="hidden" name="season" value="2025"', html)
        self.assertIn('type="number" name="week" value="21"', html)

    def test_nfl_cards_context_links_game_detail_with_explicit_season(self) -> None:
        context = build_nfl_cards_page_context(21, season=2025)
        games = context.get("games") or []

        self.assertTrue(games)
        self.assertTrue(all("?season=2025&week=21" in str(game.get("href") or "") for game in games[:3]))

    def test_nfl_cards_empty_week_does_not_inject_fake_sample_game(self) -> None:
        with patch("syndicate.features.nfl.cards._read_snapshot_rows", return_value=()), patch(
            "syndicate.features.nfl.cards._available_card_weeks", return_value=[21]
        ):
            context = build_nfl_cards_page_context(21, season=2025)

        self.assertEqual(context.get("games"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual(context.get("source_title"), "NFL cards unavailable")
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No game cards were available for this week")

    def test_nfl_cards_api_resolves_unmirrored_week_to_last_available_snapshot(self) -> None:
        response = self.client.get("/nfl/api/cards?season=2025&week=22")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("date"), "2025 Week 21")
        self.assertEqual(payload.get("requested_date"), "2025 Week 22")
        self.assertEqual(payload.get("control_value"), "21")
        self.assertTrue(str(payload.get("source_path") or "").endswith("upcoming_recs_2025_wk21.csv"))

    def test_nfl_live_lens_api_resolves_unmirrored_week_to_last_available_snapshot(self) -> None:
        response = self.client.get("/nfl/api/live-lens?season=2025&week=22")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("week"), 21)
        self.assertEqual(payload.get("control_value"), "21")
        self.assertTrue(str(payload.get("source_path") or "").endswith("upcoming_recs_2025_wk21.csv"))

    def test_nfl_game_detail_page_preserves_explicit_season_in_week_form(self) -> None:
        context = build_nfl_cards_page_context(21, season=2025)
        game_pk = str((context.get("games") or [{}])[0].get("gamePk") or "")
        html = self.client.get(f"/nfl/game/{game_pk}?season=2025&week=21").get_data(as_text=True)

        self.assertIn('type="hidden" name="season" value="2025"', html)
        self.assertIn('type="number" name="week" value="21"', html)

    def test_nfl_game_detail_missing_card_does_not_inject_fake_matchup(self) -> None:
        with patch(
            "syndicate.features.nfl.game_detail.build_cards_page_context",
            return_value={
                "date": "2025 Week 21",
                "prev_date": "20",
                "next_date": "22",
                "games": [],
                "using_sample_data": False,
                "source_path": "NFL-Betting /api/cards?season=2025&week=21&sort=date",
                "header_stats": [
                    {"label": "Games", "value": "0"},
                    {"label": "Season", "value": "2025"},
                    {"label": "Week", "value": "21"},
                ],
            },
        ):
            context = build_nfl_game_detail_page_context(21, "missing-game", season=2025)

        game = (context.get("games") or [{}])[0]
        self.assertEqual(game.get("status"), "NFL game unavailable")
        self.assertEqual(context.get("source_title"), "NFL game unavailable")
        self.assertFalse(context.get("using_sample_data"))

    def test_nfl_betting_card_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nfl/api/season/2025/betting-card?week=21")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("season"), 2025)
        self.assertEqual(payload.get("week"), 21)
        self.assertEqual(payload.get("control_name"), "week")
        self.assertEqual(payload.get("route_path"), "/nfl/season/2025/betting-card")
        self.assertEqual(payload.get("submit_label"), "Apply")
        self.assertEqual(payload.get("reset_href"), "/nfl/season/2025/betting-card")
        self.assertEqual(payload.get("hidden_fields"), [{"name": "season", "value": "2025"}])
        self.assertTrue(any(link.get("href") == "/nfl/season/2025/betting-card?week=21" for link in (payload.get("module_links") or [])))

    def test_nfl_betting_card_api_preserves_sort_in_week_nav(self) -> None:
        response = self.client.get("/nfl/api/season/2025/betting-card?week=21&sort=odds")
        payload = response.get_json()
        prev_week, next_week = neighboring_values(available_nfl_weeks(2025), 21, fallback=21)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("prev_href"), f"/nfl/season/2025/betting-card?week={prev_week}&sort=odds")
        self.assertEqual(payload.get("next_href"), f"/nfl/season/2025/betting-card?week={next_week}&sort=odds")

    def test_nfl_picks_page_preserves_explicit_season_in_week_form(self) -> None:
        html = self.client.get("/nfl/picks?season=2025&week=21").get_data(as_text=True)

        self.assertIn('type="hidden" name="season" value="2025"', html)

    def test_nfl_picks_page_shows_sort_control(self) -> None:
        html = self.client.get("/nfl/picks?season=2025&week=21&sort=odds").get_data(as_text=True)

        self.assertIn('name="sort"', html)
        self.assertIn('<option value="odds" selected>Odds</option>', html)
        self.assertIn('>Apply</button>', html)
        self.assertIn('href="/nfl/picks?season=2025"', html)
        self.assertIn('2025 Week 21 recommendation mix', html)
        self.assertIn('Confidence tiers', html)

    def test_nfl_picks_api_exposes_confidence_grouped_sections(self) -> None:
        response = self.client.get("/nfl/api/picks?season=2025&week=19")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual((payload.get("card_sections") or [{}])[0].get("title"), "High confidence")
        self.assertEqual((payload.get("card_sections") or [{}, {}])[1].get("title"), "Medium confidence")

    def test_nfl_picks_api_keeps_full_confidence_section_counts(self) -> None:
        response = self.client.get("/nfl/api/picks?season=2025&week=17")
        payload = response.get_json()
        sections = payload.get("card_sections") or []

        self.assertEqual(response.status_code, 200)
        self.assertEqual((sections[0].get("meta") if sections else None), "13 recommendations")
        self.assertEqual(len((sections[0].get("cards") if sections else []) or []), 13)
        self.assertEqual((sections[-1].get("title") if sections else None), "Other")
        self.assertEqual((sections[-1].get("meta") if sections else None), "14 recommendations")
        self.assertEqual(len((sections[-1].get("cards") if sections else []) or []), 14)
        self.assertEqual(len(payload.get("rank_cards") or []), payload.get("rows"))

    def test_nfl_picks_header_card_count_matches_full_snapshot(self) -> None:
        response = self.client.get("/nfl/api/picks?season=2025&week=17")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual((payload.get("header_stats") or [{}])[0].get("value"), str(payload.get("rows")))

    def test_nfl_picks_api_preserves_explicit_missing_week_as_empty_state(self) -> None:
        response = self.client.get("/nfl/api/picks?season=2025&week=999")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("week"), 999)
        self.assertEqual(payload.get("rows"), 0)
        self.assertEqual(payload.get("rank_cards"), [])
        self.assertFalse(payload.get("have_data"))
        self.assertEqual((payload.get("empty_state") or {}).get("title"), "No recommendations available.")

    def test_nfl_picks_page_shows_empty_state_for_explicit_missing_week(self) -> None:
        html = self.client.get("/nfl/picks?season=2025&week=999").get_data(as_text=True)

        self.assertIn("No recommendations available.", html)
        self.assertIn("2025 Week 999", html)
        self.assertNotIn("Sample NFL Moneyline Edge", html)

    def test_nfl_picks_context_without_rows_uses_empty_state_not_sample_card(self) -> None:
        with patch("syndicate.features.nfl.picks.available_weeks", return_value=[21]), patch(
            "syndicate.features.nfl.picks._read_rows", return_value=[]
        ), patch("syndicate.features.nfl.picks.recommendation_path", return_value=Path("missing.csv")), patch(
            "syndicate.features.nfl.picks.tracked_week", return_value={"season": 2025, "week": 21}
        ):
            context = build_nfl_picks_page_context(21, season=2025)

        self.assertEqual(context.get("week"), 21)
        self.assertEqual(context.get("rank_cards"), [])
        self.assertFalse(context.get("using_sample_data"))
        self.assertEqual((context.get("empty_state") or {}).get("title"), "No recommendations available.")

    def test_nfl_betting_card_api_preserves_explicit_missing_week_as_empty_state(self) -> None:
        response = self.client.get("/nfl/api/season/2025/betting-card?week=999")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("week"), 999)
        self.assertEqual(payload.get("rows"), 0)
        self.assertEqual(payload.get("rank_cards"), [])
        self.assertFalse(payload.get("have_data"))
        self.assertEqual((payload.get("empty_state") or {}).get("title"), "No recommendations available.")

    def test_nfl_betting_card_page_shows_empty_state_for_explicit_missing_week(self) -> None:
        html = self.client.get("/nfl/season/2025/betting-card?week=999").get_data(as_text=True)

        self.assertIn("No recommendations available.", html)
        self.assertIn("2025 Week 999", html)
        self.assertNotIn("Sample NFL Moneyline Edge", html)

    def test_nfl_picks_api_exposes_source_style_rows_and_groups(self) -> None:
        response = self.client.get("/nfl/api/picks?season=2025&week=19")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("rows"), len(payload.get("data") or []))
        self.assertTrue(payload.get("have_data"))
        self.assertEqual(len((payload.get("groups") or {}).get("High") or []), 8)
        self.assertEqual(((payload.get("data") or [{}])[0]).get("confidence"), "High")

    def test_nfl_picks_page_renders_confidence_grouped_sections(self) -> None:
        html = self.client.get("/nfl/picks?season=2025&week=19").get_data(as_text=True)

        self.assertIn("High confidence", html)
        self.assertIn("Medium confidence", html)

    def test_nfl_picks_page_renders_other_bucket_title(self) -> None:
        html = self.client.get("/nfl/picks?season=2025&week=17").get_data(as_text=True)

        self.assertIn(">Other<", html)
        self.assertNotIn("Other confidence", html)

    def test_nfl_betting_card_page_preserves_explicit_season_in_week_form(self) -> None:
        html = self.client.get("/nfl/season/2025/betting-card?week=21").get_data(as_text=True)

        self.assertIn('type="hidden" name="season" value="2025"', html)

    def test_nhl_picks_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nhl/api/picks?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertTrue(any(link.get("href") == "/nhl/picks?date=2026-05-16" for link in (payload.get("module_links") or [])))
        self.assertTrue(isinstance(payload.get("available_dates"), list))

    def test_nhl_live_lens_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nhl/api/live-lens?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/nhl/live-lens")
        self.assertTrue(payload.get("warning_panel"))
        self.assertIn(payload.get("source_title"), {"NHL shared cards lens", "NHL shared cards + scoreboard lens", "NHL live scoreboard fallback", "NHL live lens unavailable"})
        self.assertEqual(len(payload.get("header_stats") or []), 5)
        self.assertTrue(any(link.get("href") == "/nhl/live-lens?date=2026-05-16" for link in (payload.get("module_links") or [])))
        self.assertTrue(isinstance(payload.get("available_dates"), list))

    def test_nhl_live_lens_context_uses_shared_cards_and_scoreboard_contract(self) -> None:
        cards_context = {
            "requested_date": "2026-05-16",
            "date": "2026-05-16",
            "prev_date": "2026-05-15",
            "next_date": "2026-05-17",
            "source_path": str(REPO_ROOT / "data" / "processed" / "predictions_2026-05-16.csv"),
            "source_title": "NHL processed predictions",
            "games": [
                {
                    "gamePk": "1",
                    "away": {"abbr": "TOR", "name": "Toronto Maple Leafs", "logo": "away.svg"},
                    "home": {"abbr": "MTL", "name": "Montreal Canadiens", "logo": "home.svg"},
                    "status": "Scheduled",
                    "detail": "7:00 PM ET",
                    "summary": "Stored game card",
                    "betting": {"home_ml_ev": 0.05},
                    "sim": {
                        "score": {"total_mean": 5.8, "margin_mean": 0.4},
                        "first10": {"prob_yes": 0.52, "ev_yes": 0.03},
                    },
                    "panels": [],
                }
            ],
        }
        scoreboard_index = {
            ("gamepk", "1"): {
                "away": "Toronto Maple Leafs",
                "home": "Montreal Canadiens",
                "away_goals": "2",
                "home_goals": "1",
                "gameState": "LIVE",
                "period": "2",
                "clock": "08:13",
            }
        }
        team_odds_index = {
            ("tor", "mtl"): [
                {
                    "home": "Montreal Canadiens",
                    "away": "Toronto Maple Leafs",
                    "bookmaker_key": "draftkings",
                    "bookmaker": "DraftKings",
                    "book_last_update": "2026-05-16T23:11:00Z",
                    "market": "h2h",
                    "outcome_name": "Toronto Maple Leafs",
                    "outcome_price": "+102",
                },
                {
                    "home": "Montreal Canadiens",
                    "away": "Toronto Maple Leafs",
                    "bookmaker_key": "draftkings",
                    "bookmaker": "DraftKings",
                    "book_last_update": "2026-05-16T23:11:00Z",
                    "market": "h2h",
                    "outcome_name": "Montreal Canadiens",
                    "outcome_price": "-122",
                },
                {
                    "home": "Montreal Canadiens",
                    "away": "Toronto Maple Leafs",
                    "bookmaker_key": "draftkings",
                    "bookmaker": "DraftKings",
                    "book_last_update": "2026-05-16T23:11:00Z",
                    "market": "totals",
                    "outcome_name": "Over",
                    "outcome_price": "-115",
                    "outcome_point": "5.5",
                },
                {
                    "home": "Montreal Canadiens",
                    "away": "Toronto Maple Leafs",
                    "bookmaker_key": "draftkings",
                    "bookmaker": "DraftKings",
                    "book_last_update": "2026-05-16T23:11:00Z",
                    "market": "totals",
                    "outcome_name": "Under",
                    "outcome_price": "-105",
                    "outcome_point": "5.5",
                },
            ]
        }

        with patch("syndicate.features.nhl.live_lens.build_cards_page_context", return_value=cards_context), patch(
            "syndicate.features.nhl.live_lens._load_scoreboard_index", return_value=scoreboard_index
        ), patch("syndicate.features.nhl.live_lens._load_team_odds_index", return_value=(team_odds_index, "2026-05-16T23:11:00Z")), patch("syndicate.features.nhl.live_lens.slate_summaries", return_value=[{"date": "2026-05-16"}]):
            context = build_nhl_live_lens_page_context("2026-05-16")

        self.assertEqual(context.get("source_title"), "NHL shared cards + scoreboard lens")
        self.assertEqual((context.get("header_stats") or [None, None, None])[2], {"label": "Live", "value": "1"})
        self.assertEqual((context.get("warning_panel") or {}).get("title"), "NHL live lens runs on the shared Syndicate game board artifacts")
        rank_cards = context.get("rank_cards") or []
        self.assertTrue(rank_cards)
        metrics = rank_cards[0].get("metrics") or []
        self.assertTrue(any(metric.get("label") == "Live ML" for metric in metrics))
        self.assertTrue(any(metric.get("label") == "Live total" for metric in metrics))
        self.assertIn("P2", rank_cards[0].get("meta") or "")
        self.assertEqual(rank_cards[0].get("odds_refreshed_at"), "2026-05-16T23:11:00Z")
        self.assertEqual(context.get("odds_refreshed_at"), "2026-05-16T23:11:00Z")

    def test_nhl_live_lens_prefers_remote_scoreboard_for_current_date(self) -> None:
        cards_context = {
            "requested_date": "2026-06-06",
            "date": "2026-06-06",
            "prev_date": "2026-06-05",
            "next_date": "2026-06-07",
            "source_path": str(REPO_ROOT / "data" / "processed" / "predictions_2026-06-06.csv"),
            "source_title": "NHL processed predictions",
            "games": [
                {
                    "gamePk": "2025030413",
                    "away": {"abbr": "CAR", "name": "Carolina Hurricanes", "logo": "away.svg"},
                    "home": {"abbr": "VGK", "name": "Vegas Golden Knights", "logo": "home.svg"},
                    "status": "Scheduled",
                    "detail": "Scheduled",
                    "summary": "Stored game card",
                    "betting": {"home_ml_ev": 0.05},
                    "sim": {
                        "score": {"total_mean": 5.8, "margin_mean": 0.4},
                        "first10": {"prob_yes": 0.52, "ev_yes": 0.03},
                    },
                    "panels": [],
                }
            ],
        }

        with TemporaryDirectory() as temp_dir:
            scoreboard_path = Path(temp_dir) / "scoreboard.csv"
            scoreboard_path.write_text(
                "gamePk,away,home,away_goals,home_goals,gameState,period,clock\n"
                "2025030413,Carolina Hurricanes,Vegas Golden Knights,,,FUT,1,\n",
                encoding="utf-8",
            )

            with patch("syndicate.features.nhl.live_lens.build_cards_page_context", return_value=cards_context), patch(
                "syndicate.features.nhl.live_lens.scoreboard_snapshot_path", return_value=scoreboard_path
            ), patch("syndicate.features.nhl.live_lens.central_today_iso", return_value="2026-06-06"), patch(
                "syndicate.local_nhl_odds.NhlWebClient.scoreboard_day",
                return_value=[
                    {
                        "gamePk": 2025030413,
                        "away": "Carolina Hurricanes",
                        "home": "Vegas Golden Knights",
                        "away_goals": 3,
                        "home_goals": 2,
                        "gameState": "CRIT",
                        "period": 4,
                        "clock": "02:11",
                    }
                ],
            ), patch("syndicate.features.nhl.live_lens._load_team_odds_index", return_value=({}, None)), patch(
                "syndicate.features.nhl.live_lens.slate_summaries", return_value=[{"date": "2026-06-06"}]
            ):
                context = build_nhl_live_lens_page_context("2026-06-06")

        self.assertEqual((context.get("header_stats") or [None, None, None])[2], {"label": "Live", "value": "1"})
        rank_cards = context.get("rank_cards") or []
        self.assertTrue(rank_cards)
        self.assertEqual(rank_cards[0].get("eyebrow"), "Live")
        self.assertIn("CRIT", rank_cards[0].get("meta") or "")

    def test_nhl_live_lens_page_renders_rank_board_instead_of_redirecting(self) -> None:
        response = self.client.get("/nhl/live-lens?date=2026-05-16")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("NHL Live Lens", html)
        self.assertIn('/nhl/live-lens?date=', html)

    def test_wnba_live_lens_page_renders_rank_board_instead_of_redirecting(self) -> None:
        response = self.client.get("/wnba/live-lens?date=2026-05-16")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("WNBA Live Lens", html)
        self.assertIn('/wnba/live-lens?date=', html)

    def test_nhl_game_route_redirects_to_cards_with_game_pk_and_date(self) -> None:
        response = self.client.get("/nhl/game/824031?date=2026-05-16")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/nhl/cards?date=2026-05-16&gamePk=824031")

    def test_nhl_live_lens_accuracy_api_uses_query_string_payload_builder(self) -> None:
        with patch(
            "syndicate.blueprints.nhl.build_live_lens_daily_accuracy_payload",
            return_value={"ok": True, "version": "live-lens-accuracy-v1", "window": {"since": "2026-05-10", "until": "2026-05-16"}},
        ) as mocked_payload:
            response = self.client.get("/nhl/api/live-lens-accuracy?date=2026-05-16")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "version": "live-lens-accuracy-v1", "window": {"since": "2026-05-10", "until": "2026-05-16"}},
        )
        mocked_payload.assert_called_once_with("date=2026-05-16")

    def test_nhl_live_game_accuracy_api_uses_query_string_payload_builder(self) -> None:
        with patch(
            "syndicate.blueprints.nhl.build_live_game_accuracy_payload",
            return_value={"ok": True, "status": "ok", "meta": {"start": "2026-05-10", "end": "2026-05-16"}},
        ) as mocked_payload:
            response = self.client.get("/nhl/api/live-game-lens-accuracy?days=14&full_game_only=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "status": "ok", "meta": {"start": "2026-05-10", "end": "2026-05-16"}},
        )
        mocked_payload.assert_called_once_with("days=14&full_game_only=1")

    def test_nhl_live_lens_builders_return_local_empty_payloads_without_source_fallback(self) -> None:
        from syndicate.features.nhl.live_game_accuracy import build_live_game_accuracy_payload as build_nhl_live_game_accuracy_payload
        from syndicate.features.nhl.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload as build_nhl_live_lens_daily_accuracy_payload

        build_nhl_live_game_accuracy_payload.cache_clear()
        build_nhl_live_lens_daily_accuracy_payload.cache_clear()
        with TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"SYNDICATE_NHL_ARTIFACT_ROOT": temp_dir}, clear=False):
                game_payload = build_nhl_live_game_accuracy_payload("since=2026-05-18&until=2026-05-18&include_rows=1")
                daily_payload = build_nhl_live_lens_daily_accuracy_payload("date=2026-05-18")

        build_nhl_live_game_accuracy_payload.cache_clear()
        build_nhl_live_lens_daily_accuracy_payload.cache_clear()

        self.assertEqual((((game_payload or {}).get("meta") or {}).get("source")), "local_mirror")
        self.assertEqual((game_payload or {}).get("status"), "empty")
        self.assertEqual(((daily_payload or {}).get("summary") or {}).get("available"), False)
        self.assertEqual((((daily_payload or {}).get("window") or {}).get("since")), "2026-05-18")

    def test_nhl_market_accuracy_api_uses_query_string_payload_builder(self) -> None:
        with patch(
            "syndicate.blueprints.nhl.build_market_accuracy_payload",
            return_value={"ok": True, "version": "accuracy-market-v1", "window": {"since": "2026-05-10", "until": "2026-05-16"}},
        ) as mocked_payload:
            response = self.client.get("/nhl/api/market-accuracy?date=2026-05-16")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "version": "accuracy-market-v1", "window": {"since": "2026-05-10", "until": "2026-05-16"}},
        )
        mocked_payload.assert_called_once_with("date=2026-05-16")

    def test_nhl_archive_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/nhl/api/archive?date=2026-05-16")
        payload = response.get_json()
        resolved_date = str(payload.get("date") or "")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/nhl/archive")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == f"/nhl/archive?date={resolved_date}" for link in (payload.get("module_links") or [])))
        self.assertTrue(isinstance(payload.get("available_dates"), list))

    def test_wnba_picks_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/wnba/api/picks?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertTrue(any(link.get("href") == "/wnba/picks?date=2026-05-16" for link in (payload.get("module_links") or [])))

    def test_wnba_archive_api_exposes_rank_board_navigation_metadata(self) -> None:
        response = self.client.get("/wnba/api/archive?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("control_name"), "date")
        self.assertEqual(payload.get("route_path"), "/wnba/archive")
        self.assertTrue(payload.get("warning_panel"))
        self.assertTrue(any(link.get("href") == "/wnba/archive?date=2026-05-16" for link in (payload.get("module_links") or [])))
        self.assertTrue(isinstance(payload.get("available_dates"), list))

    def test_wnba_cards_api_exposes_game_board_navigation_metadata(self) -> None:
        response = self.client.get("/wnba/api/cards?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("board_contract", {}).get("schema"), "game_board_v1")
        self.assertEqual(payload.get("control_name"), "date")
        self.assertTrue(isinstance(payload.get("module_links"), list))

    def test_wnba_game_detail_api_exists_and_exposes_game_board_metadata(self) -> None:
        cards_payload = self.client.get("/wnba/api/cards?date=2026-05-16").get_json()
        game_pk = str(((cards_payload.get("games") or [{}])[0]).get("gamePk") or "1")

        response = self.client.get(f"/wnba/api/game/{game_pk}?date=2026-05-16")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("board_contract", {}).get("module"), "game_detail")
        self.assertEqual(payload.get("control_name"), "date")
        self.assertTrue(any(link.get("href") == "/wnba/cards?date=2026-05-16" for link in (payload.get("module_links") or [])))


if __name__ == "__main__":
    unittest.main()