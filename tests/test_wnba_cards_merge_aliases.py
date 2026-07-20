from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.wnba.cards import build_cards_page_context
from syndicate.features.wnba.cards import _games_from_live_state_fallback
from syndicate.features.wnba.cards import _supplement_games_with_live_state
from syndicate.features.wnba.cards import _source_sim_score
from syndicate.features.wnba.cards import get_wnba_overview
from syndicate.features.wnba.cards import build_source_cards_sim_detail_payload
from syndicate.features.wnba.cards import build_source_cards_payload


class WnbaCardsMergeAliasTests(unittest.TestCase):
    def test_live_aliases_do_not_create_duplicate_cards(self) -> None:
        processed_games = [
            {
                "gamePk": "1",
                "event_id": "",
                "away_tri": "LA",
                "home_tri": "WSH",
                "status": "Scheduled",
                "detail": "2026-05-31T00:00:00+00:00",
            }
        ]
        live_games = [
            {
                "gamePk": "LAS@WSH",
                "event_id": "",
                "away_tri": "LAS",
                "home_tri": "WSH",
                "status": "Final",
                "detail": "Final",
                "live_state": {
                    "away": "LAS",
                    "home": "WSH",
                    "status": "Final",
                    "final": True,
                },
            }
        ]

        with patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_live_fetch"),
        ):
            merged_games, _, supplemented_count, _ = _supplement_games_with_live_state(processed_games, "2026-05-30")

        self.assertEqual(len(merged_games), 1)
        self.assertEqual(supplemented_count, 0)

    def test_live_event_id_variant_does_not_duplicate_matchup(self) -> None:
        processed_games = [
            {
                "gamePk": "3",
                "event_id": "",
                "away_tri": "IND",
                "home_tri": "POR",
                "status": "Scheduled",
                "detail": "2026-05-31T00:00:00+00:00",
            }
        ]
        live_games = [
            {
                "gamePk": "IND@POR",
                "event_id": "401772472",
                "away_tri": "IND",
                "home_tri": "POR",
                "status": "Live",
                "detail": "Q3",
                "live_state": {
                    "away": "IND",
                    "home": "POR",
                    "status": "Q3",
                    "event_id": "401772472",
                },
            }
        ]

        with patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_live_fetch"),
        ):
            merged_games, _, supplemented_count, _ = _supplement_games_with_live_state(processed_games, "2026-05-30")

        self.assertEqual(len(merged_games), 1)
        self.assertEqual(supplemented_count, 0)

    def test_live_state_mislabeled_team_code_does_not_add_phantom_card(self) -> None:
        # Regression: the live-state fallback source has been observed to
        # mislabel the Los Angeles Sparks as "LVA" (Las Vegas Aces' code)
        # instead of "LAS". Since that mismatched matchup key slips past the
        # identity/matchup dedup, it must still be dropped because Atlanta
        # already has a real game today -- a team can't play twice in one day.
        processed_games = [
            {
                "gamePk": "1",
                "event_id": "059e806dd41a1cdd33be91c732ab446be",
                "away_tri": "LAS",
                "home_tri": "ATL",
                "status": "Scheduled",
                "detail": "2026-07-13T23:08:15Z",
            }
        ]
        live_games = [
            {
                "gamePk": "LVA@ATL",
                "event_id": "",
                "away_tri": "LVA",
                "home_tri": "ATL",
                "status": "Live",
                "detail": "2026-07-13T23:08:15Z",
                "live_state": {
                    "away": "LVA",
                    "home": "ATL",
                    "status": "Live",
                    "in_progress": True,
                },
            }
        ]

        with patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "live_state_jsonl"),
        ):
            merged_games, _, supplemented_count, _ = _supplement_games_with_live_state(processed_games, "2026-07-13")

        self.assertEqual(len(merged_games), 1)
        self.assertEqual(merged_games[0]["away_tri"], "LAS")

    def test_live_state_fallback_keeps_old_zero_zero_rows_scheduled(self) -> None:
        live_games = [
            {
                "gamePk": "MIN@NYL",
                "event_id": "401857037",
                "away_tri": "MIN",
                "home_tri": "NYL",
                "away": "MIN",
                "home": "NYL",
                "status": "7/3 - 7:30 PM EDT",
                "in_progress": False,
                "final": False,
                "away_pts": 0,
                "home_pts": 0,
                "status_id": 1,
                "periods": [],
            }
        ]

        with patch("syndicate.features.wnba.cards._local_live_state_payload", return_value={"games": live_games}), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value={"sim": {}},
        ):
            games, source_path = _games_from_live_state_fallback("2026-07-03")

        self.assertTrue(str(source_path).endswith("live_state_2026-07-03.jsonl"))
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["status"], "Scheduled")
        self.assertFalse(games[0]["live_state"]["final"])
        self.assertEqual(games[0]["detail"], "7/3 - 7:30 PM EDT")

    def test_artifact_bundle_loads_rows_even_when_schedule_probe_says_no_games(self) -> None:
        from syndicate.features.wnba.cards import _artifact_bundle

        with TemporaryDirectory() as temp_dir:
            processed_dir = Path(temp_dir) / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            (processed_dir / "game_cards_2026-07-02.csv").write_text(
                "away_tri,home_tri,visitor_team,home_team,commence_time\n"
                "LAS,IND,Las Vegas Aces,Indiana Fever,2026-07-02T23:00:00Z\n",
                encoding="utf-8",
            )

            with patch("syndicate.features.wnba.cards._wnba_source_roots", return_value=[Path(temp_dir)]), patch(
                "syndicate.features.wnba.cards.has_games_for_date",
                return_value=False,
            ):
                bundle = _artifact_bundle("2026-07-02")

        self.assertEqual(len(bundle.get("rows") or []), 1)
        self.assertEqual((bundle.get("rows") or [{}])[0].get("away_tri"), "LAS")

    def test_artifact_bundle_prefers_root_with_complete_sim_and_props_bundle(self) -> None:
        from syndicate.features.wnba.cards import _artifact_bundle

        with TemporaryDirectory() as temp_dir_a, TemporaryDirectory() as temp_dir_b:
            root_a = Path(temp_dir_a)
            root_b = Path(temp_dir_b)
            processed_a = root_a / "data" / "processed"
            processed_b = root_b / "data" / "processed"
            processed_a.mkdir(parents=True, exist_ok=True)
            processed_b.mkdir(parents=True, exist_ok=True)

            (processed_a / "game_cards_2026-07-03.csv").write_text(
                "away_tri,home_tri,visitor_team,home_team,commence_time\n"
                "MIN,NYL,MIN,NYL,2026-07-03T23:00:00Z\n",
                encoding="utf-8",
            )
            (processed_b / "game_cards_2026-07-03.csv").write_text(
                "away_tri,home_tri,visitor_team,home_team,commence_time\n"
                "MIN,NYL,MIN,NYL,2026-07-03T23:00:00Z\n",
                encoding="utf-8",
            )
            (processed_b / "recommendations_slate_2026-07-03.json").write_text("{\"per_game\": []}", encoding="utf-8")
            (processed_b / "cards_sim_detail_2026-07-03.json").write_text(
                "{\"MIN\":{\"NYL\":{\"sim\":{\"players\":{\"away\":[],\"home\":[]}}}}}",
                encoding="utf-8",
            )
            (processed_b / "cards_props_snapshot_2026-07-03.json").write_text(
                "{\"MIN\":{\"NYL\":{\"prop_recommendations\":{\"away\":[],\"home\":[]}}}}",
                encoding="utf-8",
            )

            with patch("syndicate.features.wnba.cards._wnba_source_roots", return_value=[root_a, root_b]):
                bundle = _artifact_bundle("2026-07-03")

        self.assertEqual(bundle["paths"]["cards"], processed_b / "game_cards_2026-07-03.csv")
        self.assertEqual(bundle["paths"]["sim"], processed_b / "cards_sim_detail_2026-07-03.json")
        self.assertEqual(bundle["paths"]["props"], processed_b / "cards_props_snapshot_2026-07-03.json")

    def test_source_cards_payload_hydrates_betting_from_live_lines_artifact(self) -> None:
        artifact_bundle = {
            "rows": [
                {
                    "away_tri": "LAS",
                    "home_tri": "IND",
                    "visitor_team": "Las Vegas Aces",
                    "home_team": "Indiana Fever",
                    "gamePk": "401857500",
                    "event_id": "401857500",
                    "commence_time": "2026-07-02T23:00:00Z",
                }
            ],
            "recommendations": {},
            "sim": {},
            "props": {},
        }
        live_lines_payload = {
            "ok": True,
            "date": "2026-07-02",
            "odds_refreshed_at": "2026-07-02T09:09:00-05:00",
            "games": [
                {
                    "event_id": "401857500",
                    "found": True,
                    "total": 167.5,
                    "home_spread": -6.5,
                    "away_spread": 6.5,
                    "home_ml": -240,
                    "away_ml": 196,
                    "lines": {
                        "total": 167.5,
                        "home_spread": -6.5,
                        "away_spread": 6.5,
                        "home_ml": -240,
                        "away_ml": 196,
                    },
                }
            ],
        }

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-07-02"), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value=artifact_bundle,
        ), patch(
            "syndicate.features.wnba.cards._artifact_live_lines_payload",
            return_value=live_lines_payload,
        ), patch(
            "syndicate.features.wnba.cards._games_from_public_scoreboard",
            return_value=([], "espn_scoreboard_fallback"),
        ), patch(
            "syndicate.features.wnba.cards._supplement_games_with_live_state",
            return_value=([
                {
                    "gamePk": "401857500",
                    "event_id": "401857500",
                    "away_tri": "LAS",
                    "home_tri": "IND",
                    "away_name": "Las Vegas Aces",
                    "home_name": "Indiana Fever",
                    "away": {"abbr": "LAS", "name": "Las Vegas Aces"},
                    "home": {"abbr": "IND", "name": "Indiana Fever"},
                    "status": "Scheduled",
                    "detail": "Scheduled",
                    "odds": {"commence_time": "2026-07-02T23:00:00Z"},
                    "betting": {
                        "total": 167.5,
                        "home_spread": -6.5,
                        "away_spread": 6.5,
                        "home_ml": -240,
                        "away_ml": 196,
                    },
                    "sim": {
                        "score": {
                            "away_mean": 81.25,
                            "home_mean": 85.75,
                            "total_mean": 167.0,
                            "margin_mean": 4.5,
                        }
                    },
                }
            ], None, 0, 0),
        ):
            payload = build_source_cards_payload("2026-07-02", allow_stored_date_fallback=True)

        game = (payload.get("games") or [{}])[0]
        betting = game.get("betting") if isinstance(game, dict) else {}
        predictions = game.get("predictions") if isinstance(game, dict) else {}
        markets = game.get("markets") if isinstance(game, dict) else {}
        self.assertEqual((payload.get("board_contract") or {}).get("surface"), "mlb_dense_board_v1")
        self.assertEqual(betting.get("total"), 167.5)
        self.assertEqual(betting.get("home_spread"), -6.5)
        self.assertEqual(betting.get("home_ml"), -240)
        self.assertEqual(betting.get("away_ml"), 196)
        self.assertEqual(predictions.get("away_mean"), 81.25)
        self.assertEqual(predictions.get("home_mean"), 85.75)
        self.assertEqual(predictions.get("total_mean"), 167.0)
        self.assertEqual(predictions.get("margin_mean"), 4.5)
        self.assertIsNotNone((predictions.get("probabilities") or {}).get("home_win"))
        self.assertIsNotNone((predictions.get("probabilities") or {}).get("away_win"))
        self.assertEqual((markets.get("moneyline") or {}).get("home"), -240)
        self.assertEqual((markets.get("moneyline") or {}).get("away"), 196)
        self.assertEqual((markets.get("spread") or {}).get("home"), -6.5)
        self.assertEqual((markets.get("spread") or {}).get("away"), 6.5)
        self.assertEqual((markets.get("total") or {}).get("line"), 167.5)

    def test_source_cards_payload_uses_public_scoreboard_for_today_when_artifacts_are_missing(self) -> None:
        public_games = [
            {
                "gamePk": "401857500",
                "event_id": "401857500",
                "away_tri": "LAS",
                "home_tri": "IND",
                "status": "Scheduled",
                "detail": "Scheduled",
                "away": {"abbr": "LAS"},
                "home": {"abbr": "IND"},
                "live_state": {"event_id": "401857500", "away": "LAS", "home": "IND"},
            }
        ]

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-07-02"), patch(
            "syndicate.features.wnba.cards.has_games_for_date",
            return_value=False,
        ), patch(
            "syndicate.features.wnba.cards.available_dates",
            return_value=[],
        ), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value={"rows": [], "recommendations": {}, "sim": {}, "props": {}},
        ), patch(
            "syndicate.features.wnba.cards._games_from_public_scoreboard",
            return_value=(public_games, "espn_scoreboard_fallback"),
        ):
            payload = build_source_cards_payload("2026-07-02", allow_stored_date_fallback=True)

        self.assertEqual(payload["date"], "2026-07-02")
        self.assertEqual(payload["requested_date"], "2026-07-02")
        self.assertEqual(len(payload.get("games") or []), 1)
        first_game = (payload.get("games") or [{}])[0]
        self.assertEqual(first_game.get("event_id"), "401857500")
        self.assertIsInstance(first_game.get("status"), dict)
        self.assertEqual(first_game.get("status", {}).get("status"), "Scheduled")
        self.assertEqual(first_game.get("startTime"), "2026-07-02")
        self.assertEqual(first_game.get("detail"), "Scheduled")
        self.assertEqual(first_game.get("summary"), "Scheduled")

    def test_cards_page_context_keeps_today_pinned_for_public_scoreboard_fallback(self) -> None:
        public_games = [
            {
                "gamePk": "401857500",
                "event_id": "401857500",
                "away_tri": "LAS",
                "home_tri": "IND",
                "status": "Scheduled",
                "detail": "Scheduled",
                "away": {"abbr": "LAS"},
                "home": {"abbr": "IND"},
                "live_state": {"event_id": "401857500", "away": "LAS", "home": "IND"},
            }
        ]

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-07-02"), patch(
            "syndicate.features.wnba.cards.has_games_for_date",
            return_value=True,
        ), patch(
            "syndicate.features.wnba.cards.available_dates",
            return_value=["2026-06-30"],
        ), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value={"rows": [], "recommendations": {}, "sim": {}, "props": {}},
        ), patch(
            "syndicate.features.wnba.cards._render_web_dyno",
            return_value=True,
        ), patch(
            "syndicate.features.wnba.cards._games_from_public_scoreboard",
            return_value=(public_games, "espn_scoreboard_fallback"),
        ):
            context = build_cards_page_context("2026-07-02", allow_stored_date_fallback=True)

        self.assertEqual(context["date"], "2026-07-02")
        self.assertEqual(context["requested_date"], "2026-07-02")
        self.assertEqual(context["source_title"], "WNBA live scoreboard fallback")
        self.assertEqual(len(context.get("games") or []), 1)


    def test_cards_page_context_keeps_explicit_today_empty_without_live_fallback(self) -> None:
        live_games = [
            {
                "gamePk": "401857016",
                "event_id": "401857016",
                "away_tri": "LVA",
                "home_tri": "NYL",
                "status": "Live",
                "detail": "Q2",
                "live_state": {"event_id": "401857016", "away": "LVA", "home": "NYL"},
            }
        ]

        with TemporaryDirectory() as tempdir, patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-06-23"), patch(
            "syndicate.features.wnba.cards.available_dates",
            return_value=["2026-06-23"],
        ), patch(
            "syndicate.features.wnba.cards._artifact_paths",
            side_effect=lambda selected_date, **kwargs: {
                "cards": Path(tempdir) / f"game_cards_{selected_date}.csv",
                "recommendations": Path(tempdir) / f"recommendations_slate_{selected_date}.json",
                "sim": Path(tempdir) / f"cards_sim_detail_{selected_date}.json",
                "props": Path(tempdir) / f"cards_props_snapshot_{selected_date}.json",
            },
        ), patch(
            "syndicate.features.wnba.cards._path_cache_signature",
            return_value=0,
        ), patch(
            "syndicate.features.wnba.cards.live_snapshot_path",
            side_effect=lambda filename: Path(tempdir) / "live_snapshots" / filename,
        ), patch(
            "syndicate.features.wnba.sources.live_snapshot_path",
            side_effect=lambda filename: Path(tempdir) / "live_snapshots" / filename,
        ), patch(
            "syndicate.features.wnba.sources.processed_path",
            side_effect=lambda filename: Path(tempdir) / filename,
        ), patch(
            "syndicate.features.wnba.sources._strict_artifact_path",
            side_effect=lambda filename, subdir: Path(tempdir).joinpath(*subdir, filename),
        ), patch(
            "syndicate.features.wnba.cards._games_from_artifacts",
            return_value=([], "cards_path", "recs_path"),
        ), patch(
            "syndicate.features.wnba.cards._supplement_games_with_live_state",
            return_value=([], None, 0, 0),
        ), patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "live_source_path"),
        ) as mocked_live_fallback:
            context = build_cards_page_context("2026-06-23", allow_stored_date_fallback=False)

        self.assertEqual(context["date"], "2026-06-23")
        self.assertFalse(context["lookahead_applied"])
        self.assertEqual(context["games"], [])

    def test_wnba_overview_uses_stored_date_fallback(self) -> None:
        with patch("syndicate.features.wnba.cards.has_games_for_date", return_value=True), patch(
            "syndicate.features.wnba.cards.build_source_cards_payload"
        ) as mocked_build_payload:
            mocked_build_payload.side_effect = lambda selected_date, allow_stored_date_fallback=False: {
                "games": [{"event_id": "evt-1"}] if allow_stored_date_fallback else [],
                "date": selected_date,
                "requested_date": selected_date,
                "board_contract": {},
            }

            overview = get_wnba_overview("2026-06-30")

        self.assertEqual(overview["status"], "ok")
        self.assertEqual(len(overview["games"]), 1)
        mocked_build_payload.assert_called_once_with("2026-06-30", allow_stored_date_fallback=True)

    def test_source_cards_payload_keeps_explicit_today_date_without_stored_fallback(self) -> None:
        empty_bundle = {"rows": [], "recommendations": {}, "sim": {}, "props": {}}

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-06-23"), patch(
            "syndicate.features.wnba.cards.available_dates",
            return_value=["2026-06-22", "2026-06-23"],
        ), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value=empty_bundle,
        ):
            payload = build_source_cards_payload("2026-06-23", allow_stored_date_fallback=False)

        self.assertEqual(payload["date"], "2026-06-23")
        self.assertFalse(payload["lookahead_applied"])
        self.assertEqual(payload["requested_date"], "2026-06-23")

    def test_source_cards_payload_uses_live_supplement_for_today(self) -> None:
        artifact_bundle = {
            "rows": [
                {"away_tri": "CHI", "home_tri": "CON", "gamePk": "1", "commence_time": "2026-06-22T18:00:00Z"},
                {"away_tri": "TOR", "home_tri": "ATL", "gamePk": "2", "commence_time": "2026-06-22T20:00:00Z"},
            ],
            "recommendations": {},
            "sim": {},
            "props": {},
        }

        live_games = [
            {"gamePk": "401857012", "event_id": "401857012", "away_tri": "CHI", "home_tri": "CON", "status": "Scheduled", "detail": "Scheduled", "live_state": {"event_id": "401857012", "away": "CHI", "home": "CON"}},
            {"gamePk": "401857013", "event_id": "401857013", "away_tri": "TOR", "home_tri": "ATL", "status": "Scheduled", "detail": "Scheduled", "live_state": {"event_id": "401857013", "away": "TOR", "home": "ATL"}},
            {"gamePk": "401857014", "event_id": "401857014", "away_tri": "PHX", "home_tri": "IND", "status": "Scheduled", "detail": "Scheduled", "live_state": {"event_id": "401857014", "away": "PHX", "home": "IND"}},
            {"gamePk": "401857015", "event_id": "401857015", "away_tri": "DAL", "home_tri": "SEA", "status": "Scheduled", "detail": "Scheduled", "live_state": {"event_id": "401857015", "away": "DAL", "home": "SEA"}},
        ]

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-06-22"), patch(
            "syndicate.features.wnba.cards._resolved_source_cards_date",
            return_value="2026-06-22",
        ), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value=artifact_bundle,
        ), patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_scoreboard_fallback"),
        ), patch(
            # A fresh ESPN scoreboard fetch is now tried first and merged in
            # preference to the keyvalue-backed live_state fallback above;
            # returning nothing here keeps this test exercising that
            # keyvalue-fallback path specifically, without hitting the real
            # network.
            "syndicate.features.wnba.cards._games_from_public_scoreboard",
            return_value=([], "espn_scoreboard_fallback"),
        ):
            payload = build_source_cards_payload("2026-06-22")

        self.assertEqual(payload["date"], "2026-06-22")
        self.assertEqual(len(payload["games"]), 4)
        self.assertEqual([game.get("event_id") for game in payload["games"]], ["401857012", "401857013", "401857014", "401857015"])
        first_game = payload["games"][0]
        self.assertIsInstance(first_game.get("status"), dict)
        self.assertEqual(first_game.get("status", {}).get("status"), "Scheduled")
        self.assertEqual(first_game.get("startTime"), "2026-06-22T18:00:00Z")
        self.assertEqual(first_game.get("detail"), "Scheduled")
        self.assertEqual(first_game.get("summary"), "Consensus market snapshot")

    def test_cards_page_context_prefers_today_public_scoreboard_over_stored_artifact_fallback(self) -> None:
        fallback_bundle = {
            "paths": {
                "cards": Path("game_cards_2026-06-27.csv"),
                "recommendations": Path("recommendations_slate_2026-06-27.json"),
                "sim": Path("cards_sim_detail_2026-06-27.json"),
                "props": Path("cards_props_snapshot_2026-06-27.json"),
            },
            "rows": [
                {
                    "away_tri": "LAS",
                    "home_tri": "CON",
                    "visitor_team": "Las Vegas Aces",
                    "home_team": "Connecticut Sun",
                    "gamePk": "1",
                    "commence_time": "2026-06-27T18:00:00Z",
                }
            ],
            "recommendations": {},
            "sim": {
                ("LAS", "CON"): {
                    "sim": {
                        "players_summary": {"away": 4, "home": 5, "missing_away": 0, "missing_home": 0, "injured_away": 0, "injured_home": 0},
                        "players": {
                            "away": [{"player_name": "Away Player", "pts_mean": 10.5, "reb_mean": 4.2, "ast_mean": 2.1, "pra_mean": 16.8}],
                            "home": [{"player_name": "Home Player", "pts_mean": 11.3, "reb_mean": 5.1, "ast_mean": 3.0, "pra_mean": 19.4}],
                        },
                        "pregame_context": {"available": True, "source": "sim"},
                        "quarters": [{"quarter": 1, "away_mean": 20.0, "home_mean": 22.0}],
                    }
                }
            },
            "props": {
                ("LAS", "CON"): {
                    "prop_recommendations": {
                        "away": [{"player": "Away Player", "market": "pts", "side": "over"}],
                        "home": [{"player": "Home Player", "market": "reb", "side": "under"}],
                    }
                }
            },
        }

        def _artifact_bundle_side_effect(selected_date: str):
            if selected_date == "2026-07-02":
                return {"rows": [], "recommendations": {}, "sim": {}, "props": {}}
            if selected_date == "2026-06-27":
                return fallback_bundle
            return {"rows": [], "recommendations": {}, "sim": {}, "props": {}}

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-07-02"), patch(
            "syndicate.features.wnba.cards.available_dates",
            return_value=["2026-06-27", "2026-07-02"],
        ), patch(
            "syndicate.features.wnba.cards.has_games_for_date",
            return_value=True,
        ), patch(
            "syndicate.features.wnba.cards._render_web_dyno",
            return_value=True,
        ), patch(
            "syndicate.features.wnba.cards._path_cache_signature",
            return_value=0,
        ), patch(
            "syndicate.features.wnba.cards._games_from_public_scoreboard",
            return_value=(
                [
                    {
                        "gamePk": "401857500",
                        "event_id": "401857500",
                        "away_tri": "LAS",
                        "home_tri": "IND",
                        "status": "Scheduled",
                        "detail": "Scheduled",
                        "away": {"abbr": "LAS"},
                        "home": {"abbr": "IND"},
                        "live_state": {"event_id": "401857500", "away": "LAS", "home": "IND"},
                    }
                ],
                "espn_scoreboard_fallback",
            ),
        ), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            side_effect=_artifact_bundle_side_effect,
        ):
            context = build_cards_page_context("2026-07-02", allow_stored_date_fallback=True)

        self.assertEqual(context["date"], "2026-07-02")
        self.assertEqual(context["source_title"], "WNBA live scoreboard fallback")
        self.assertIn("espn_scoreboard_fallback", context["source_path"])
        game = (context.get("games") or [{}])[0]
        self.assertEqual(game.get("event_id"), "401857500")

    def test_source_cards_payload_keeps_full_sim_player_rows(self) -> None:
        artifact_bundle = {
            "rows": [
                {
                    "away_tri": "LAS",
                    "home_tri": "CON",
                    "visitor_team": "Las Vegas Aces",
                    "home_team": "Connecticut Sun",
                    "game_id": "1",
                    "commence_time": "2026-06-22T18:00:00Z",
                }
            ],
            "recommendations": {},
            "sim": {
                ("LAS", "CON"): {
                    "sim": {
                        "players_summary": {
                            "away": 4,
                            "home": 5,
                            "missing_away": 0,
                            "missing_home": 0,
                            "injured_away": 0,
                            "injured_home": 0,
                        },
                        "players": {
                            "away": [
                                {"player_name": "Away Player", "pts_mean": 10.5, "reb_mean": 4.2, "ast_mean": 2.1, "pra_mean": 16.8}
                            ],
                            "home": [
                                {"player_name": "Home Player", "pts_mean": 11.3, "reb_mean": 5.1, "ast_mean": 3.0, "pra_mean": 19.4}
                            ],
                        },
                        "pregame_context": {"available": True, "source": "sim"},
                        "quarters": [{"quarter": 1, "away_mean": 20.0, "home_mean": 22.0}],
                    }
                }
            },
            "props": {
                ("LAS", "CON"): {
                    "prop_recommendations": {
                        "away": [{"player": "Away Player", "market": "pts", "side": "over"}],
                        "home": [{"player": "Home Player", "market": "reb", "side": "under"}],
                    }
                }
            },
        }

        with patch("syndicate.features.wnba.cards._artifact_bundle", return_value=artifact_bundle):
            payload = build_source_cards_payload("2026-06-22", allow_stored_date_fallback=False)

        games = payload.get("games") or []
        self.assertGreaterEqual(len(games), 1)

        first_game = games[0]
        sim = first_game.get("sim") if isinstance(first_game, dict) else {}
        self.assertTrue(sim.get("players_loaded"))
        self.assertGreater(len((sim.get("players") or {}).get("away") or []), 0)
        self.assertGreater(len((sim.get("players") or {}).get("home") or []), 0)
        self.assertIn("pregame_context", sim)
        self.assertGreater(len(sim.get("pregame_context") or {}), 0)
        self.assertIn("quarters", sim)
        self.assertGreaterEqual(int((sim.get("players_summary") or {}).get("away") or 0), 0)
        self.assertGreaterEqual(int((sim.get("players_summary") or {}).get("home") or 0), 0)

    def test_source_cards_sim_detail_payload_accepts_flat_sim_payload(self) -> None:
        artifact_bundle = {
            "rows": [],
            "recommendations": {},
            "sim": {
                ("LAS", "CON"): {
                    "players_summary": {"away": 4, "home": 5},
                    "players": {"away": [{"player_name": "Away Player"}], "home": [{"player_name": "Home Player"}]},
                    "pregame_context": {"available": True, "source": "sim"},
                    "quarters": [{"quarter": 1, "away_mean": 20.0, "home_mean": 22.0}],
                }
            },
            "props": {},
        }

        with patch("syndicate.features.wnba.cards._artifact_bundle", return_value=artifact_bundle):
            payload = build_source_cards_sim_detail_payload("2026-06-22", "LAS", "CON")

        games = payload.get("games") or []
        self.assertEqual(len(games), 1)
        sim = games[0].get("sim") if isinstance(games[0], dict) else {}
        self.assertTrue(sim.get("players_loaded"))
        self.assertGreater(len((sim.get("players") or {}).get("away") or []), 0)
        self.assertGreater(len((sim.get("players") or {}).get("home") or []), 0)
        self.assertIn("pregame_context", sim)
        self.assertIn("quarters", sim)

    def test_source_cards_sim_detail_payload_uses_latest_artifact_when_today_bundle_is_empty(self) -> None:
        fallback_bundle = {
            "rows": [],
            "recommendations": {},
            "sim": {
                ("LAS", "CON"): {
                    "sim": {
                        "players_summary": {"away": 4, "home": 5, "missing_away": 0, "missing_home": 0, "injured_away": 0, "injured_home": 0},
                        "players": {
                            "away": [{"player_name": "Away Player", "pts_mean": 10.5, "reb_mean": 4.2, "ast_mean": 2.1, "pra_mean": 16.8}],
                            "home": [{"player_name": "Home Player", "pts_mean": 11.3, "reb_mean": 5.1, "ast_mean": 3.0, "pra_mean": 19.4}],
                        },
                        "pregame_context": {"available": True, "source": "sim"},
                        "quarters": [{"quarter": 1, "away_mean": 20.0, "home_mean": 22.0}],
                    }
                }
            },
            "props": {},
        }

        def _artifact_bundle_side_effect(selected_date: str):
            if selected_date == "2026-07-02":
                return {"rows": [], "recommendations": {}, "sim": {}, "props": {}}
            if selected_date == "2026-06-27":
                return fallback_bundle
            return {"rows": [], "recommendations": {}, "sim": {}, "props": {}}

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-07-02"), patch(
            "syndicate.features.wnba.cards.available_dates",
            return_value=["2026-06-27", "2026-07-02"],
        ), patch(
            "syndicate.features.wnba.cards.has_games_for_date",
            return_value=True,
        ), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            side_effect=_artifact_bundle_side_effect,
        ):
            payload = build_source_cards_sim_detail_payload("2026-07-02", "LAS", "CON")

        self.assertEqual(payload["date"], "2026-06-27")
        self.assertEqual(payload["requested_date"], "2026-07-02")
        games = payload.get("games") or []
        self.assertEqual(len(games), 1)
        sim = games[0].get("sim") if isinstance(games[0], dict) else {}
        self.assertTrue(sim.get("players_loaded"))
        self.assertGreater(len((sim.get("players") or {}).get("away") or []), 0)
        self.assertGreater(len((sim.get("players") or {}).get("home") or []), 0)
        self.assertIn("pregame_context", sim)
        self.assertIn("quarters", sim)

    def test_source_sim_score_uses_row_projection_when_players_are_missing(self) -> None:
        score = _source_sim_score(
            None,
            {
                "pred_total": "161.5",
                "pred_margin": "5.5",
            },
        )

        self.assertEqual(score["away_mean"], 78.0)
        self.assertEqual(score["home_mean"], 83.5)
        self.assertEqual(score["total_mean"], 161.5)
        self.assertEqual(score["margin_mean"], 5.5)


if __name__ == "__main__":
    unittest.main()
