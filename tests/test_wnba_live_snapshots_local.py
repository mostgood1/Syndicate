from __future__ import annotations

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
        self.assertEqual(((payload.get("games") or [{}])[0]).get("rows"), [{"player": "Two"}])

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
        ), patch("syndicate.features.wnba.cards._public_scoreboard_live_state_payload", return_value=None):
            _local_live_state_payload.cache_clear()
            payload = build_live_state_payload("2026-05-21", ttl=12)
            _local_live_state_payload.cache_clear()

        self.assertEqual(payload.get("source"), "syndicate_cards_fallback")
        self.assertEqual([game.get("game_id") for game in payload.get("games") or []], ["42"])
        self.assertTrue(((payload.get("games") or [{}])[0]).get("in_progress"))

    def test_live_lens_card_surface_shows_total_points_and_live_line(self) -> None:
        with patch(
            "syndicate.features.wnba.live_lens.build_cards_page_context",
            return_value={
                "date": "2026-05-21",
                "source_path": "wnba_cards.json",
                "games": [
                    {
                        "away": {"abbr": "SEA", "score": 46},
                        "home": {"abbr": "DAL", "score": 70},
                        "status": "Live",
                        "detail": "3:27 - 4th",
                        "summary": "Live scoring pace is tracking toward the under.",
                        "betting": {"total": 166.5},
                        "shared_prop_rows": [],
                        "shared_top_play_rows": [],
                    }
                ],
            },
        ):
            from syndicate.features.wnba.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context("2026-05-21")

        card = (context.get("rank_cards") or [{}])[0]
        metrics = card.get("metrics") or []
        metric_text = " ".join(f"{row.get('label')} {row.get('value')}" for row in metrics if isinstance(row, dict))

        self.assertIn("Total pts 116", card.get("summary"))
        self.assertIn("Live line 166.5", card.get("summary"))
        self.assertIn("Total pts 116", metric_text)
        self.assertIn("Live line 166.5", metric_text)

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


if __name__ == "__main__":
    unittest.main()