from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from syndicate.features.wnba.cards import _local_live_snapshot_payload
from syndicate.features.wnba.cards import _local_live_state_payload
from syndicate.features.wnba.cards import build_live_lines_payload
from syndicate.features.wnba.cards import build_live_pbp_stats_payload
from syndicate.features.wnba.cards import build_live_player_boxscore_payload
from syndicate.features.wnba.cards import build_live_player_lens_payload
from syndicate.features.wnba.cards import build_live_state_payload


class WnbaLiveSnapshotLocalTests(unittest.TestCase):
    def _write_snapshot(self, root: Path, kind: str, payload: dict[str, object]) -> None:
        live_dir = root / "data" / "processed" / "live_snapshots"
        live_dir.mkdir(parents=True, exist_ok=True)
        (live_dir / f"{kind}_2026-05-21.jsonl").write_text(
            json.dumps({"ts": "2026-05-21T19:30:00Z", "payload": payload}) + "\n",
            encoding="utf-8",
        )

    def test_live_player_boxscore_payload_uses_local_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_snapshot(
                root,
                "live_player_boxscore",
                {
                    "ok": True,
                    "date": "2026-05-21",
                    "games": [
                        {"event_id": "evt-1", "players": [{"player": "One"}]},
                        {"event_id": "evt-2", "players": [{"player": "Two"}]},
                    ],
                },
            )

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_player_boxscore_payload("2026-05-21", ["evt-2"], ttl=20)
                _local_live_snapshot_payload.cache_clear()

        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["evt-2"])
        self.assertEqual(((payload.get("games") or [{}])[0]).get("players"), [{"player": "Two"}])

    def test_live_player_boxscore_payload_retries_resolved_event_ids(self) -> None:
        def _snapshot_payload(kind: str, selected_date: str, event_ids: list[str]) -> dict[str, object] | None:
            if kind != "live_player_boxscore":
                return None
            if event_ids == ["evt-hash"]:
                return {"ok": True, "date": selected_date, "games": [{"event_id": "evt-hash", "players": []}]}
            if event_ids == ["401857027"]:
                return {
                    "ok": True,
                    "date": selected_date,
                    "games": [{"event_id": "401857027", "players": [{"player": "Two"}]}],
                }
            return None

        with patch("syndicate.features.wnba.cards.build_cards_page_context", return_value={"date": "2026-06-28"}), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            side_effect=_snapshot_payload,
        ), patch(
            "syndicate.features.wnba.cards._public_live_player_boxscore_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._resolve_games_for_event_ids",
            return_value={"evt-hash": {"event_id": "401857027", "game_id": "401857027"}},
        ):
            payload = build_live_player_boxscore_payload("2026-06-28", ["evt-hash"], ttl=20)

        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["401857027"])
        self.assertEqual(((payload.get("games") or [{}])[0]).get("players"), [{"player": "Two"}])

    def test_live_player_lens_payload_uses_local_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_snapshot(
                root,
                "live_player_lens",
                {
                    "ok": True,
                    "date": "2026-05-21",
                    "games": [
                        {"event_id": "evt-1", "rows": [{"player": "One"}]},
                        {"event_id": "evt-2", "rows": [{"player": "Two"}]},
                    ],
                },
            )

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)
                _local_live_snapshot_payload.cache_clear()

        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["evt-2"])
        self.assertEqual((((payload.get("games") or [{}])[0]).get("rows") or [{}])[0].get("player"), "Two")

    def test_live_lines_payload_uses_local_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_snapshot(
                root,
                "live_lines",
                {
                    "ok": True,
                    "date": "2026-05-21",
                    "games": [
                        {"event_id": "evt-1", "found": True, "total": 164.5},
                        {"event_id": "evt-2", "found": True, "total": 159.5},
                    ],
                },
            )

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_lines_payload("2026-05-21", ["evt-2"], ttl=20, include_period_totals=True)
                _local_live_snapshot_payload.cache_clear()

        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["evt-2"])
        self.assertEqual(((payload.get("games") or [{}])[0]).get("total"), 159.5)

    def test_live_pbp_stats_payload_uses_local_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_snapshot(
                root,
                "live_pbp_stats",
                {
                    "ok": True,
                    "date": "2026-05-21",
                    "games": [
                        {"event_id": "evt-1", "pbp_recent": {"points_total": 9}},
                        {"event_id": "evt-2", "pbp_recent": {"points_total": 14}},
                    ],
                },
            )

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_pbp_stats_payload("2026-05-21", ["evt-2"], ttl=20)
                _local_live_snapshot_payload.cache_clear()

        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["evt-2"])
        self.assertEqual((((payload.get("games") or [{}])[0]).get("pbp_recent") or {}).get("points_total"), 14)

    def test_date_scoped_paths_prefer_current_day_over_larger_previous_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_root = root / "data" / "processed"
            live_root = processed_root / "live_snapshots"
            processed_root.mkdir(parents=True, exist_ok=True)
            live_root.mkdir(parents=True, exist_ok=True)

            older_processed = processed_root / "recommendations_slate_2026-06-20.json"
            newer_processed = processed_root / "recommendations_slate_2026-06-21.json"
            older_live = live_root / "live_pbp_stats_2026-06-20.jsonl"
            newer_live = live_root / "live_pbp_stats_2026-06-21.jsonl"

            older_processed.write_text("{\"ok\": true, \"date\": \"2026-06-20\", \"payload\": \"older\"}\n", encoding="utf-8")
            newer_processed.write_text("{\"ok\": true, \"date\": \"2026-06-21\", \"payload\": \"newer\"}\n", encoding="utf-8")
            older_live.write_text("{\"ok\": true, \"date\": \"2026-06-20\", \"games\": []}\n" * 3, encoding="utf-8")
            newer_live.write_text("{\"ok\": true, \"date\": \"2026-06-21\", \"games\": []}\n", encoding="utf-8")

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]):
                from syndicate.features.wnba.sources import live_snapshot_path
                from syndicate.features.wnba.sources import processed_path

                selected_processed = processed_path("recommendations_slate_2026-06-21.json")
                selected_live = live_snapshot_path("live_pbp_stats_2026-06-21.jsonl")

        self.assertEqual(selected_processed, newer_processed)
        self.assertEqual(selected_live, newer_live)

    def test_date_scoped_paths_fallback_to_latest_available_when_current_day_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_root = root / "data" / "processed"
            live_root = processed_root / "live_snapshots"
            processed_root.mkdir(parents=True, exist_ok=True)
            live_root.mkdir(parents=True, exist_ok=True)

            fallback_processed = processed_root / "recommendations_slate_2026-06-20.json"
            fallback_live = live_root / "live_pbp_stats_2026-06-20.jsonl"
            fallback_processed.write_text("{\"ok\": true, \"date\": \"2026-06-20\", \"payload\": \"fallback\"}\n", encoding="utf-8")
            fallback_live.write_text("{\"ok\": true, \"date\": \"2026-06-20\", \"games\": []}\n", encoding="utf-8")

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]):
                from syndicate.features.wnba.sources import live_snapshot_path
                from syndicate.features.wnba.sources import processed_path

                selected_processed = processed_path("recommendations_slate_2026-06-21.json")
                selected_live = live_snapshot_path("live_pbp_stats_2026-06-21.jsonl")

        self.assertEqual(selected_processed, fallback_processed)
        self.assertEqual(selected_live, fallback_live)

    def test_live_state_payload_falls_back_to_cards_context(self) -> None:
        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={
                "games": [
                    {
                        "gamePk": "42",
                        "away": {"abbr": "NYL", "name": "New York Liberty"},
                        "home": {"abbr": "LAS", "name": "Las Vegas Aces"},
                        "status": "Live",
                        "detail": "Q3 04:21",
                    }
                ]
            },
        ), patch("syndicate.features.wnba.cards._remote_live_snapshot_payload", return_value=None), patch(
            "syndicate.features.wnba.cards._public_scoreboard_live_state_payload",
            return_value=None,
        ):
            _local_live_state_payload.cache_clear()
            payload = build_live_state_payload("2026-05-21", ttl=12)
            _local_live_state_payload.cache_clear()

        self.assertEqual(payload.get("source"), "syndicate_cards_fallback")
        self.assertEqual([game.get("game_id") for game in payload.get("games") or []], ["42"])
        self.assertTrue(((payload.get("games") or [{}])[0]).get("in_progress"))

    def test_live_state_payload_render_skips_remote_and_public_fallbacks(self) -> None:
        with patch.dict("os.environ", {"RENDER": "1"}, clear=False), patch(
            "syndicate.features.wnba.cards.central_today_iso",
            return_value="2026-05-21",
        ), patch(
            "syndicate.features.wnba.cards._local_live_state_payload",
            return_value={
                "ok": True,
                "source": "local_snapshot",
                "games": [
                    {
                        "event_id": "evt-1",
                        "away": "NYL",
                        "home": "LAS",
                        "away_pts": 81,
                        "home_pts": 79,
                        "status": "Live",
                        "periods": [],
                    }
                ],
            },
        ) as local_payload, patch(
            "syndicate.features.wnba.cards._remote_live_snapshot_payload",
            side_effect=AssertionError("remote snapshot should not be used on Render"),
        ) as remote_payload, patch(
            "syndicate.features.wnba.cards._public_scoreboard_live_state_payload",
            side_effect=AssertionError("public scoreboard should not be used on Render"),
        ) as public_payload, patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={
                "games": [
                    {
                        "event_id": "evt-1",
                        "away_tri": "NYL",
                        "home_tri": "LAS",
                        "away": {"abbr": "NYL", "score": 81},
                        "home": {"abbr": "LAS", "score": 79},
                        "live_state": {"in_progress": True, "final": False},
                        "status": "Live",
                        "detail": "Q4 01:12",
                    }
                ]
            },
        ):
            payload = build_live_state_payload("2026-05-21", ttl=12)

        self.assertEqual(payload.get("source"), "local_snapshot")
        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["evt-1"])
        self.assertEqual(local_payload.call_count, 1)
        self.assertEqual(remote_payload.call_count, 0)
        self.assertEqual(public_payload.call_count, 0)

    def test_live_state_payload_repairs_stale_public_scoreboard_with_cards_context(self) -> None:
        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-05-21"), patch(
            "syndicate.features.wnba.cards._remote_live_snapshot_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._local_live_state_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._public_scoreboard_live_state_payload",
            return_value={
                "ok": True,
                "source": "espn_scoreboard_fallback",
                "games": [
                    {
                        "event_id": "evt-2",
                        "away": "NYL",
                        "home": "LAS",
                        "away_pts": 0,
                        "home_pts": 0,
                        "status": "5/21 - 7:00 PM EDT",
                        "clock": "",
                        "period": None,
                        "in_progress": False,
                        "final": False,
                        "periods": [],
                    }
                ],
            },
        ), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={
                "games": [
                    {
                        "event_id": "evt-2",
                        "away_tri": "NYL",
                        "home_tri": "LAS",
                        "away": {"abbr": "NYL", "score": 64},
                        "home": {"abbr": "LAS", "score": 66},
                        "status": "Live",
                        "detail": "3:27 - 4th",
                        "live_state": {"in_progress": True, "final": False},
                    }
                ]
            },
        ):
            payload = build_live_state_payload("2026-05-21", ttl=12)

        game = (payload.get("games") or [{}])[0]
        self.assertTrue(game.get("in_progress"))
        self.assertEqual(game.get("away_pts"), 64.0)
        self.assertEqual(game.get("home_pts"), 66.0)
        self.assertEqual(game.get("clock"), "3:27")
        self.assertEqual(game.get("period"), 4)

    def test_live_state_payload_preserves_public_rows_when_cards_context_is_incomplete(self) -> None:
        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-05-21"), patch(
            "syndicate.features.wnba.cards._remote_live_snapshot_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._local_live_state_payload",
            return_value=None,
        ), patch(
            "syndicate.features.wnba.cards._public_scoreboard_live_state_payload",
            return_value={
                "ok": True,
                "source": "espn_scoreboard_fallback",
                "games": [
                    {
                        "event_id": "evt-1",
                        "away": "NYL",
                        "home": "LAS",
                        "away_pts": 18,
                        "home_pts": 21,
                        "status": "Q1 09:31",
                        "clock": "9:31",
                        "period": 1,
                        "in_progress": True,
                        "final": False,
                        "periods": [],
                    },
                    {
                        "event_id": "evt-999",
                        "away": "CHI",
                        "home": "CON",
                        "away_pts": 0,
                        "home_pts": 0,
                        "status": "Scheduled",
                        "clock": "",
                        "period": None,
                        "in_progress": False,
                        "final": False,
                        "periods": [],
                    },
                ],
            },
        ), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={
                "games": [
                    {
                        "event_id": "evt-1",
                        "away_tri": "NYL",
                        "home_tri": "LAS",
                        "away": {"abbr": "NYL", "score": 18},
                        "home": {"abbr": "LAS", "score": 21},
                        "status": "Live",
                        "detail": "Q1 09:31",
                        "live_state": {"in_progress": True, "final": False},
                    }
                ]
            },
        ):
            payload = build_live_state_payload("2026-05-21", ttl=12)

        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["evt-1", "evt-999"])
        self.assertEqual(len(payload.get("games") or []), 2)

    def test_live_lines_payload_merges_partial_local_snapshot_with_artifact(self) -> None:
        with patch("syndicate.features.wnba.cards.build_cards_page_context", return_value={"date": "2026-05-21"}), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "games": [{"event_id": "evt-1", "found": True, "total": 164.5, "lines": {"total": 164.5}}],
            },
        ), patch(
            "syndicate.features.wnba.cards._artifact_live_lines_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "games": [
                    {
                        "event_id": "evt-2",
                        "found": True,
                        "total": 159.5,
                        "lines": {"total": 159.5, "period_totals": {"q1": 40.5}, "period_spreads": {}},
                    }
                ],
            },
        ):
            payload = build_live_lines_payload("2026-05-21", ["evt-1", "evt-2"], ttl=20, include_period_totals=True)

        games = {str(game.get("event_id")): game for game in payload.get("games") or [] if isinstance(game, dict)}
        self.assertEqual(set(games.keys()), {"evt-1", "evt-2"})
        self.assertEqual(games["evt-1"].get("total"), 164.5)
        self.assertEqual(games["evt-2"].get("total"), 159.5)
        self.assertEqual((((games["evt-2"].get("lines") or {}).get("period_totals") or {}).get("q1")), 40.5)

    def test_live_lines_payload_prefers_richer_artifact_when_local_snapshot_is_thin(self) -> None:
        with patch("syndicate.features.wnba.cards.build_cards_page_context", return_value={"date": "2026-05-21"}), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "include_period_totals": False,
                "games": [{"event_id": "evt-2", "found": True, "total": 159.5, "lines": {"total": 159.5}}],
            },
        ), patch(
            "syndicate.features.wnba.cards._artifact_live_lines_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "include_period_totals": True,
                "games": [
                    {
                        "event_id": "evt-2",
                        "found": True,
                        "total": 159.5,
                        "lines": {"total": 159.5, "period_totals": {"q1": 40.5}, "period_spreads": {"q1": -2.5}},
                    }
                ],
            },
        ):
            payload = build_live_lines_payload("2026-05-21", ["evt-2"], ttl=20, include_period_totals=True)

        lines = (((payload.get("games") or [{}])[0].get("lines") or {}))
        self.assertTrue(bool(payload.get("include_period_totals")))
        self.assertEqual((lines.get("period_totals") or {}).get("q1"), 40.5)
        self.assertEqual((lines.get("period_spreads") or {}).get("q1"), -2.5)

    def test_live_lens_card_surface_shows_total_points_and_live_line(self) -> None:
        with patch(
            "syndicate.features.wnba.live_lens.build_cards_page_context",
            return_value={
                "date": "2026-05-21",
                "source_path": "wnba_cards.json",
                "games": [
                    {
                        "event_id": "evt-2",
                        "away": {"abbr": "SEA", "score": 46},
                        "home": {"abbr": "DAL", "score": 70},
                        "status": "Live",
                        "detail": "3:27 - 4th",
                        "summary": "Live scoring pace is tracking toward the under.",
                        "betting": {"total": 166.5},
                        "panels": [
                            {
                                "eyebrow": "Market snapshot",
                                "title": "Consensus lines",
                                "body": "Spread DAL -4.5 | total 166.5.",
                                "summary_stats": [
                                    {"label": "Away ML", "value": "+180"},
                                    {"label": "Home ML", "value": "-220"},
                                ],
                            },
                            {
                                "eyebrow": "Top recommendations",
                                "title": "Per-game playable looks",
                                "body": "Top picks are pulled from the processed WNBA recommendation slate artifact.",
                                "items": ["Alysha Clark | Over 1.5 3PM", "Natisha Hiedeman | Under 10.5 PTS"],
                            },
                        ],
                        "shared_prop_rows": [],
                        "shared_top_play_rows": [],
                    }
                ],
            },
        ), patch(
            "syndicate.features.wnba.live_lens.build_live_lines_payload",
            return_value={"games": [{"event_id": "evt-2", "total": 169.5}]},
        ):
            from syndicate.features.wnba.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context("2026-05-21")

        card = (context.get("rank_cards") or [{}])[0]
        metrics = card.get("metrics") or []
        metric_text = " ".join(f"{row.get('label')} {row.get('value')}" for row in metrics if isinstance(row, dict))

        self.assertIn("Total pts 116", card.get("summary"))
        self.assertIn("Live line 169.5", card.get("summary"))
        self.assertIn("Total pts 116", metric_text)
        self.assertIn("Live line 169.5", metric_text)
        self.assertIn("Market snapshot: Consensus lines", card.get("list_items")[0])
        self.assertIn("Away ML +180", " ".join(card.get("list_items")))
        self.assertIn("Alysha Clark | Over 1.5 3PM", " ".join(card.get("list_items")))

    def test_live_lens_card_surface_does_not_fallback_to_cards_total(self) -> None:
        with patch(
            "syndicate.features.wnba.live_lens.build_cards_page_context",
            return_value={
                "date": "2026-05-21",
                "source_path": "wnba_cards.json",
                "games": [
                    {
                        "event_id": "evt-2",
                        "away": {"abbr": "SEA", "score": 46},
                        "home": {"abbr": "DAL", "score": 70},
                        "status": "Live",
                        "detail": "3:27 - 4th",
                        "summary": "Live scoring pace is tracking toward the under.",
                        "betting": {"total": 166.5},
                        "panels": [],
                        "shared_prop_rows": [],
                        "shared_top_play_rows": [],
                    }
                ],
            },
        ), patch(
            "syndicate.features.wnba.live_lens.build_live_lines_payload",
            return_value={"games": []},
        ):
            from syndicate.features.wnba.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context("2026-05-21")

        card = (context.get("rank_cards") or [{}])[0]
        metrics = card.get("metrics") or []
        metric_labels = " ".join(str(row.get("label")) for row in metrics if isinstance(row, dict))

        self.assertNotIn("Live line", card.get("summary"))
        self.assertNotIn("Live line", metric_labels)

    def test_live_player_lens_payload_hydrates_actuals_from_boxscore(self) -> None:
        with patch("syndicate.features.wnba.cards.build_cards_page_context", return_value={"date": "2026-05-21"}):
            with patch(
                "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
                return_value={
                    "ok": True,
                    "date": "2026-05-21",
                    "games": [
                        {
                            "event_id": "evt-2",
                            "rows": [
                                {
                                    "player": "Breanna Stewart",
                                    "team_tri": "NYL",
                                    "stat": "pts",
                                    "line_live": 17.5,
                                    "sim_mu": 21.0,
                                    "sim_mu_adjusted": 21.0,
                                    "price": -112,
                                    "win_prob": 0.64,
                                }
                            ],
                        }
                    ],
                },
            ):
                with patch(
                    "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
                    return_value={
                        "games": [
                            {
                                "event_id": "evt-2",
                                "players": [
                                    {"team_tri": "NYL", "player": "Breanna Stewart", "pts": 19, "reb": 6, "ast": 4, "mp": 23}
                                ],
                            }
                        ]
                    },
                ):
                    payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("actual"), 19)
        self.assertIsNotNone(row.get("live_projection"))
        self.assertIsNotNone(row.get("live_edge"))
        self.assertEqual(row.get("line_source"), "boxscore_sim_fallback")

    def test_live_player_lens_payload_fallback_hydrates_actuals_from_boxscore(self) -> None:
        with patch("syndicate.features.wnba.cards.build_cards_page_context", return_value={"date": "2026-05-21"}):
            with patch("syndicate.features.wnba.cards._filtered_local_live_snapshot_payload", return_value=None):
                with patch(
                    "syndicate.features.wnba.cards._resolve_games_for_event_ids",
                    return_value={
                        "evt-2": {
                            "event_id": "evt-2",
                            "away_tri": "NYL",
                            "home_tri": "LAS",
                            "sim": {
                                "players": {
                                    "away": [{"player_name": "Breanna Stewart", "pts_mean": 21, "reb_mean": 7, "ast_mean": 4}],
                                    "home": [],
                                }
                            },
                            "prop_recommendations": {
                                "away": [
                                    {
                                        "player": "Breanna Stewart",
                                        "market": "pts",
                                        "line": 17.5,
                                        "side": "OVER",
                                        "price": -112,
                                        "ev_pct": 12.0,
                                        "p_win": 0.64,
                                    }
                                ],
                                "home": [],
                            },
                        }
                    },
                ):
                    with patch(
                        "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
                        return_value={
                            "games": [
                                {
                                    "event_id": "evt-2",
                                    "players": [
                                        {"team_tri": "NYL", "player": "Breanna Stewart", "pts": 19, "reb": 6, "ast": 4, "mp": 23}
                                    ],
                                }
                            ]
                        },
                    ):
                        payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("actual"), 19)
        self.assertIsNotNone(row.get("live_projection"))
        self.assertIsNotNone(row.get("live_edge"))
        self.assertEqual(row.get("line_source"), "boxscore_sim_fallback")

    def test_live_player_lens_payload_uses_local_projection_artifact_when_snapshot_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            (processed_dir / "live_lens_projections_2026-05-21.jsonl").write_text(
                json.dumps(
                    {
                        "market": "player_prop",
                        "game_id": "0401",
                        "player": "Breanna Stewart",
                        "team": "NYL",
                        "opponent": "LAS",
                        "stat": "pts",
                        "line": 17.5,
                        "proj": 23.0,
                        "sim_mu": 21.0,
                        "klass": "BET",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]), patch(
                "syndicate.features.wnba.cards.build_cards_page_context",
                return_value={"date": "2026-05-21"},
            ), patch(
                "syndicate.features.wnba.cards._resolve_games_for_event_ids",
                return_value={"evt-2": {"event_id": "evt-2", "gamePk": "0401", "away_tri": "NYL", "home_tri": "LAS"}},
            ), patch(
                "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
                return_value={
                    "games": [
                        {
                            "event_id": "evt-2",
                            "players": [
                                {"team_tri": "NYL", "player": "Breanna Stewart", "pts": 19, "reb": 6, "ast": 4, "mp": 23}
                            ],
                        }
                    ]
                },
            ):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)
                _local_live_snapshot_payload.cache_clear()

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("player"), "Breanna Stewart")
        self.assertEqual(row.get("line_source"), "live_lens_projection_artifact")
        self.assertEqual(row.get("actual"), 19)
        self.assertEqual(row.get("live_projection"), 23.0)

    def test_live_lines_payload_uses_local_signals_artifact_when_snapshot_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "data" / "processed"
            live_snapshots_dir = processed_dir / "live_snapshots"
            live_snapshots_dir.mkdir(parents=True, exist_ok=True)
            (live_snapshots_dir / "live_lines_2026-05-21.jsonl").write_text(
                json.dumps(
                    {
                        "payload": {
                            "date": "2026-05-21",
                            "games": [
                                {
                                    "event_id": "evt-2",
                                    "game_id": "0401",
                                    "away": "NYL",
                                    "home": "LAS",
                                    "found": True,
                                    "lines": {"period_totals": None, "period_spreads": None},
                                }
                            ],
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (processed_dir / "live_lens_signals_2026-05-21.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "market": "total",
                                "game_id": "0401",
                                "home": "LAS",
                                "away": "NYL",
                                "live_line": 163.5,
                            }
                        ),
                        json.dumps(
                            {
                                "market": "quarter_total",
                                "game_id": "0401",
                                "home": "LAS",
                                "away": "NYL",
                                "horizon": "q1",
                                "live_line": 40.5,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]), patch(
                "syndicate.features.wnba.cards.build_cards_page_context",
                return_value={"date": "2026-05-21"},
            ), patch(
                "syndicate.features.wnba.cards._resolve_games_for_event_ids",
                return_value={"evt-2": {"event_id": "evt-2", "gamePk": "0401", "away_tri": "NYL", "home_tri": "LAS"}},
            ), patch(
                "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
                return_value=None,
            ):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_lines_payload("2026-05-21", ["evt-2"], ttl=20, include_period_totals=True)
                _local_live_snapshot_payload.cache_clear()

        game = (payload.get("games") or [{}])[0]
        self.assertEqual(game.get("total"), 163.5)
        self.assertEqual((((game.get("lines") or {}).get("period_totals") or {}).get("q1")), 40.5)
        self.assertEqual(payload.get("source"), "syndicate_live_lens_signals_artifact")

    def test_live_lines_payload_prefers_local_snapshot_artifact_over_signals(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "data" / "processed"
            live_snapshots_dir = processed_dir / "live_snapshots"
            live_snapshots_dir.mkdir(parents=True, exist_ok=True)
            (processed_dir / "live_lens_signals_2026-05-21.jsonl").write_text(
                json.dumps(
                    {
                        "market": "total",
                        "game_id": "0401",
                        "home": "LAS",
                        "away": "NYL",
                        "live_line": 163.5,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (live_snapshots_dir / "live_lines_2026-05-21.jsonl").write_text(
                json.dumps(
                    {
                        "payload": {
                            "date": "2026-05-21",
                            "games": [
                                {
                                    "event_id": "evt-2",
                                    "game_id": "0401",
                                    "away": "NYL",
                                    "home": "LAS",
                                    "found": True,
                                    "lines": {
                                        "total": 159.5,
                                        "period_totals": {"q1": 40.5},
                                        "period_spreads": {"q1": -2.5},
                                    },
                                }
                            ],
                            "generated_at": "2026-05-21T20:00:00Z",
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]), patch(
                "syndicate.features.wnba.cards.build_cards_page_context",
                return_value={"date": "2026-05-21"},
            ), patch(
                "syndicate.features.wnba.cards._resolve_games_for_event_ids",
                return_value={"evt-2": {"event_id": "evt-2", "gamePk": "0401", "away_tri": "NYL", "home_tri": "LAS"}},
            ), patch(
                "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
                return_value=None,
            ):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_lines_payload("2026-05-21", ["evt-2"], ttl=20, include_period_totals=True)
                _local_live_snapshot_payload.cache_clear()

        game = (payload.get("games") or [{}])[0]
        lines = game.get("lines") or {}
        self.assertEqual(lines.get("total"), 159.5)
        self.assertEqual((lines.get("period_totals") or {}).get("q1"), 40.5)
        self.assertEqual((lines.get("period_spreads") or {}).get("q1"), -2.5)
        self.assertEqual(payload.get("source"), "syndicate_live_snapshot_artifact")

    def test_live_player_lens_payload_skips_zero_line_projection_artifact_placeholders(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            (processed_dir / "live_lens_projections_2026-05-21.jsonl").write_text(
                json.dumps(
                    {
                        "player": "A'ja Wilson",
                        "team": "LVA",
                        "opponent": "GSV",
                        "stat": "pts",
                        "line": 0.0,
                        "proj": 27.1,
                        "sim_mu": 25.5,
                        "klass": "WATCH",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]), patch(
                "syndicate.features.wnba.cards.build_cards_page_context",
                return_value={"date": "2026-05-21"},
            ), patch(
                "syndicate.features.wnba.cards._resolve_games_for_event_ids",
                return_value={"evt-2": {"event_id": "evt-2", "gamePk": "0401", "away_tri": "GSV", "home_tri": "LVA"}},
            ):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)
                _local_live_snapshot_payload.cache_clear()

        rows = ((payload.get("games") or [{}])[0].get("rows") or [])
        self.assertEqual(rows, [])

    def test_live_player_lens_payload_hydrates_prices_from_processed_oddsapi_props(self) -> None:
        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-21"},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "games": [
                    {
                        "event_id": "evt-2",
                        "rows": [
                            {
                                "player": "Breanna Stewart",
                                "team_tri": "NYL",
                                "stat": "pts",
                                "line_live": 17.5,
                                "sim_mu": 21.0,
                                "sim_mu_adjusted": 21.0,
                                "live_projection": 15.0,
                                "live_edge": -2.5,
                                "price": None,
                                "line_source": "live_lens_projection_artifact",
                            }
                        ],
                    }
                ],
            },
        ), patch(
            "syndicate.features.wnba.cards._resolve_games_for_event_ids",
            return_value={
                "evt-2": {
                    "event_id": "evt-2",
                    "gamePk": "0401",
                    "away_tri": "NYL",
                    "home_tri": "LAS",
                    "prop_recommendations": {"away": [], "home": []},
                }
            },
        ), patch(
            "syndicate.features.wnba.cards._processed_live_player_odds_index",
            return_value={
                ("evt-2", "BREANNA STEWART", "pts"): [
                    {
                        "line": 17.5,
                        "price_over": -112,
                        "price_under": -108,
                        "book": "FanDuel",
                    }
                ]
            },
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value={"games": []},
        ), patch(
            "syndicate.features.wnba.cards.build_live_state_payload",
            return_value={"games": [{"event_id": "evt-2", "status": {"in_progress": True, "period": 2, "clock": "8:00", "status": "8:00 - 2nd"}}]},
        ):
            payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("price_over"), -112)
        self.assertEqual(row.get("price_under"), -108)
        self.assertEqual(row.get("price"), -108)
        self.assertEqual(row.get("ev_side"), "UNDER")
        self.assertEqual(row.get("book"), "FanDuel")
        self.assertEqual(row.get("line_source"), "oddsapi_player_props_fallback")

    def test_live_player_lens_payload_keeps_surpassed_live_line(self) -> None:
        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-21"},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "games": [
                    {
                        "event_id": "evt-2",
                        "rows": [
                            {
                                "player": "Arike Ogunbowale",
                                "team_tri": "DAL",
                                "stat": "threes",
                                "line_live": 1.5,
                                "line_source": "live_lens_projection_artifact",
                                "price": -129,
                                "price_over": -129,
                                "price_under": None,
                            }
                        ],
                    }
                ],
            },
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value={"games": [{"event_id": "evt-2", "players": [{"player": "Arike Ogunbowale", "team_tri": "DAL", "threes_made": 3}]}]},
        ), patch(
            "syndicate.features.wnba.cards.build_live_state_payload",
            return_value={"games": [{"event_id": "evt-2", "status": {"in_progress": True, "period": 3, "clock": "4:08", "status": "4:08 - 3rd"}}]},
        ):
            payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("actual"), 3)
        self.assertEqual(row.get("line_live"), 1.5)
        self.assertEqual(row.get("price"), -129)
        self.assertEqual(row.get("line_source"), "boxscore_sim_fallback")

    def test_attach_odds_refresh_timestamp_normalizes_to_central(self) -> None:
        from syndicate.features.wnba import cards as module

        with patch.object(module, "central_now", return_value=datetime(2026, 6, 15, 12, 21, 0, tzinfo=timezone(timedelta(hours=-5)))):
            out = module._attach_odds_refresh_timestamp({"generated_at": "2026-06-15T17:21:00Z"})

        self.assertEqual(out.get("odds_refreshed_at"), "2026-06-15T12:21:00-05:00")
        self.assertEqual(out.get("generated_at"), "2026-06-15T17:21:00Z")

    def test_live_player_lens_payload_reconciles_status_from_top_level_live_state_rows(self) -> None:
        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-21"},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "games": [
                    {
                        "event_id": "evt-2",
                        "rows": [
                            {
                                "player": "Breanna Stewart",
                                "team_tri": "NYL",
                                "stat": "pts",
                                "line_live": 17.5,
                                "price": -112,
                                "status_label": "Scheduled",
                                "status_display": "Scheduled",
                            }
                        ],
                    }
                ],
            },
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value={"games": []},
        ), patch(
            "syndicate.features.wnba.cards.build_live_state_payload",
            return_value={
                "games": [
                    {
                        "event_id": "evt-2",
                        "in_progress": True,
                        "final": False,
                        "period": 4,
                        "clock": "2:30",
                        "status": "2:30 - 4th",
                    }
                ]
            },
        ):
            payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("status_label"), "Q4 2:30")
        self.assertEqual(row.get("status_display"), "Q4 2:30")

    def test_live_player_lens_payload_skips_no_price_projection_artifact_rows_after_hydration(self) -> None:
        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-21"},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "games": [
                    {
                        "event_id": "evt-2",
                        "rows": [
                            {
                                "player": "Breanna Stewart",
                                "team_tri": "NYL",
                                "stat": "pts",
                                "line_live": None,
                                "line_source": "live_lens_projection_artifact",
                                "price": None,
                                "price_over": None,
                                "price_under": None,
                            }
                        ],
                    }
                ],
            },
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value={"games": []},
        ), patch(
            "syndicate.features.wnba.cards.build_live_state_payload",
            return_value={"games": []},
        ), patch(
            "syndicate.features.wnba.cards._resolve_games_for_event_ids",
            return_value={},
        ), patch(
            "syndicate.features.wnba.cards._processed_live_player_odds_index",
            return_value={},
        ):
            payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        rows = ((payload.get("games") or [{}])[0].get("rows") or [])
        self.assertEqual(rows, [])

    def test_live_player_lens_payload_prefers_priced_rows_over_artifact_duplicates(self) -> None:
        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-21"},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "games": [
                    {
                        "event_id": "evt-2",
                        "rows": [
                            {
                                "player": "Breanna Stewart",
                                "team_tri": "NYL",
                                "stat": "pts",
                                "line_live": 17.5,
                                "line_source": "live_lens_projection_artifact",
                                "price": None,
                                "price_over": None,
                                "price_under": None,
                            },
                            {
                                "player": "Breanna Stewart",
                                "team_tri": "NYL",
                                "stat": "pts",
                                "line_live": 17.5,
                                "line_source": "oddsapi_player_props_fallback",
                                "price": -108,
                                "price_over": -112,
                                "price_under": -108,
                                "book": "FanDuel",
                            },
                        ],
                    }
                ],
            },
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value={"games": []},
        ), patch(
            "syndicate.features.wnba.cards.build_live_state_payload",
            return_value={"games": []},
        ):
            payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        rows = ((payload.get("games") or [{}])[0].get("rows") or [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("price"), -108)
        self.assertEqual(rows[0].get("line_source"), "oddsapi_player_props_fallback")

    def test_live_player_lens_payload_matches_processed_odds_even_when_line_drift_is_large(self) -> None:
        with patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-21"},
        ), patch(
            "syndicate.features.wnba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "games": [
                    {
                        "event_id": "evt-2",
                        "rows": [
                            {
                                "player": "Breanna Stewart",
                                "team_tri": "NYL",
                                "stat": "pts",
                                "line_live": 26.5,
                                "line_source": "live_lens_projection_artifact",
                                "price": None,
                                "price_over": None,
                                "price_under": None,
                            }
                        ],
                    }
                ],
            },
        ), patch(
            "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
            return_value={"games": []},
        ), patch(
            "syndicate.features.wnba.cards.build_live_state_payload",
            return_value={"games": []},
        ), patch(
            "syndicate.features.wnba.cards._resolve_games_for_event_ids",
            return_value={"evt-2": {"event_id": "evt-2", "away_tri": "NYL", "home_tri": "LAS"}},
        ), patch(
            "syndicate.features.wnba.cards._processed_live_player_odds_index",
            return_value={
                ("evt-2", "BREANNA STEWART", "pts"): [
                    {
                        "line": 17.5,
                        "price_over": -112,
                        "price_under": -108,
                        "book": "FanDuel",
                    }
                ]
            },
        ):
            payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("price_over"), -112)
        self.assertEqual(row.get("price_under"), -108)
        self.assertEqual(row.get("price"), -108)
        self.assertEqual(row.get("book"), "FanDuel")
        self.assertEqual(row.get("line_source"), "oddsapi_player_props_fallback")


if __name__ == "__main__":
    unittest.main()