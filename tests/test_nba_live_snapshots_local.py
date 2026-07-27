from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from syndicate.features.nba.cards import _local_live_snapshot_payload
from syndicate.features.nba.cards import build_live_lines_payload
from syndicate.features.nba.cards import build_live_pbp_stats_payload
from syndicate.features.nba.cards import build_live_player_boxscore_payload
from syndicate.features.nba.cards import build_live_player_lens_payload


class NbaLiveSnapshotLocalTests(unittest.TestCase):
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

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]), patch(
                # snapshot/artifact reads now resolve via the odds-control-plane processed root
                "syndicate.features.nba.sources.artifact_processed_root",
                return_value=root / "data" / "processed",
            ):
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
            if event_ids == ["401859964"]:
                return {
                    "ok": True,
                    "date": selected_date,
                    "games": [{"event_id": "401859964", "players": [{"player": "Two"}]}],
                }
            return None

        with patch("syndicate.features.nba.cards.build_cards_page_context", return_value={"date": "2026-06-05"}), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            side_effect=_snapshot_payload,
        ), patch(
            "syndicate.features.nba.cards._public_live_player_boxscore_payload",
            return_value=None,
        ), patch(
            "syndicate.features.nba.cards._resolve_games_for_event_ids",
            return_value={"evt-hash": {"event_id": "401859964", "game_id": "401859964"}},
        ):
            payload = build_live_player_boxscore_payload("2026-06-05", ["evt-hash"], ttl=20)

        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["401859964"])
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

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]), patch(
                # snapshot/artifact reads now resolve via the odds-control-plane processed root
                "syndicate.features.nba.sources.artifact_processed_root",
                return_value=root / "data" / "processed",
            ):
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
                        {"event_id": "evt-1", "found": True, "total": 221.5},
                        {"event_id": "evt-2", "found": True, "total": 219.5},
                    ],
                },
            )

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]), patch(
                # snapshot/artifact reads now resolve via the odds-control-plane processed root
                "syndicate.features.nba.sources.artifact_processed_root",
                return_value=root / "data" / "processed",
            ):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_lines_payload("2026-05-21", ["evt-2"], ttl=20, include_period_totals=True)
                _local_live_snapshot_payload.cache_clear()

        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["evt-2"])
        self.assertEqual(((payload.get("games") or [{}])[0]).get("total"), 219.5)

    def test_live_lines_payload_prefers_richer_artifact_when_intervals_requested(self) -> None:
        with patch("syndicate.features.nba.cards.build_cards_page_context", return_value={"date": "2026-05-21"}), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "include_period_totals": False,
                "games": [{"event_id": "evt-2", "found": True, "total": 219.5, "lines": {"total": 219.5}}],
            },
        ), patch(
            "syndicate.features.nba.cards._artifact_live_lines_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "include_period_totals": True,
                "games": [
                    {
                        "event_id": "evt-2",
                        "found": True,
                        "total": 219.5,
                        "lines": {"total": 219.5, "period_totals": {"q1": 54.5}, "period_spreads": {"q1": -1.5}},
                    }
                ],
            },
        ):
            payload = build_live_lines_payload("2026-05-21", ["evt-2"], ttl=20, include_period_totals=True)

        lines = (((payload.get("games") or [{}])[0].get("lines") or {}))
        self.assertTrue(bool(payload.get("include_period_totals")))
        self.assertEqual((lines.get("period_totals") or {}).get("q1"), 54.5)
        self.assertEqual((lines.get("period_spreads") or {}).get("q1"), -1.5)

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

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]), patch(
                # snapshot/artifact reads now resolve via the odds-control-plane processed root
                "syndicate.features.nba.sources.artifact_processed_root",
                return_value=root / "data" / "processed",
            ):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_pbp_stats_payload("2026-05-21", ["evt-2"], ttl=20)
                _local_live_snapshot_payload.cache_clear()

        self.assertEqual([game.get("event_id") for game in payload.get("games") or []], ["evt-2"])
        self.assertEqual((((payload.get("games") or [{}])[0]).get("pbp_recent") or {}).get("points_total"), 14)

    def test_live_player_lens_payload_hydrates_actuals_from_boxscore(self) -> None:
        with patch("syndicate.features.nba.cards.build_cards_page_context", return_value={"date": "2026-05-21"}):
            with patch(
                "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
                return_value={
                    "ok": True,
                    "date": "2026-05-21",
                    "games": [
                        {
                            "event_id": "evt-2",
                            "rows": [
                                {
                                    "player": "Jayson Tatum",
                                    "team_tri": "BOS",
                                    "stat": "pts",
                                    "line_live": 18.5,
                                    "sim_mu": 22.0,
                                    "sim_mu_adjusted": 22.0,
                                    "price": -115,
                                    "win_prob": 0.61,
                                }
                            ],
                        }
                    ],
                },
            ):
                with patch(
                    "syndicate.features.nba.cards.build_live_player_boxscore_payload",
                    return_value={
                        "games": [
                            {
                                "event_id": "evt-2",
                                "players": [
                                    {"team_tri": "BOS", "player": "Jayson Tatum", "pts": 20, "reb": 5, "ast": 3, "mp": 24}
                                ],
                            }
                        ]
                    },
                ):
                    payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("actual"), 20)
        self.assertIsNotNone(row.get("live_projection"))
        self.assertIsNotNone(row.get("live_edge"))
        self.assertEqual(row.get("line_source"), "boxscore_sim_fallback")

    def test_live_player_lens_payload_keeps_surpassed_live_line(self) -> None:
        with patch("syndicate.features.nba.cards.build_cards_page_context", return_value={"date": "2026-05-21"}), patch(
            "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
            return_value={
                "ok": True,
                "date": "2026-05-21",
                "games": [
                    {
                        "event_id": "evt-2",
                        "rows": [
                            {
                                "player": "Jayson Tatum",
                                "team_tri": "BOS",
                                "stat": "pts",
                                "line_live": 18.5,
                                "price": -115,
                            }
                        ],
                    }
                ],
            },
        ), patch(
            "syndicate.features.nba.cards.build_live_player_boxscore_payload",
            return_value={
                "games": [
                    {
                        "event_id": "evt-2",
                        "players": [
                            {"team_tri": "BOS", "player": "Jayson Tatum", "pts": 20, "reb": 5, "ast": 3, "mp": 24}
                        ],
                    }
                ]
            },
        ), patch(
            "syndicate.features.nba.cards.build_live_state_payload",
            return_value={"games": [{"event_id": "evt-2", "status": {"in_progress": True, "period": 2, "clock": "8:00", "status": "8:00 - 2nd"}}]},
        ):
            payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("actual"), 20)
        self.assertEqual(row.get("line_live"), 18.5)
        self.assertEqual(row.get("line_source"), "boxscore_sim_fallback")

    def test_attach_odds_refresh_timestamp_normalizes_to_central(self) -> None:
        from syndicate.features.nba import cards as module

        with patch.object(module, "central_now", return_value=datetime(2026, 6, 15, 12, 21, 0, tzinfo=timezone(timedelta(hours=-5)))):
            out = module._attach_odds_refresh_timestamp({"generated_at": "2026-06-15T17:21:00Z"})

        self.assertEqual(out.get("odds_refreshed_at"), "2026-06-15T12:21:00-05:00")
        self.assertEqual(out.get("generated_at"), "2026-06-15T17:21:00Z")

    def test_live_lens_card_surface_shows_total_points_and_live_line(self) -> None:
        with patch(
            "syndicate.features.nba.live_lens.build_cards_page_context",
            return_value={
                "date": "2026-05-21",
                "source_path": "nba_cards.json",
                "games": [
                    {
                        "event_id": "evt-2",
                        "away": {"abbr": "BOS", "score": 104},
                        "home": {"abbr": "NYK", "score": 102},
                        "status": "Live",
                        "detail": "Q4 02:11",
                        "summary": "Live scoring pace is tracking toward the over.",
                        "betting": {"total": 221.5},
                        "panels": [
                            {
                                "eyebrow": "Market snapshot",
                                "title": "Consensus lines",
                                "body": "Spread NYK -2.5 | total 221.5.",
                                "summary_stats": [
                                    {"label": "Away ML", "value": "+105"},
                                    {"label": "Home ML", "value": "-125"},
                                ],
                            },
                            {
                                "eyebrow": "Top recommendations",
                                "title": "Per-game playable looks",
                                "body": "Top picks are pulled from the processed NBA recommendation slate artifact.",
                                "items": ["Jayson Tatum | Over 28.5 PTS", "Jalen Brunson | Under 6.5 AST"],
                            },
                        ],
                        "shared_prop_rows": [],
                        "shared_top_play_rows": [],
                    }
                ],
            },
        ), patch(
            "syndicate.features.nba.live_lens.build_live_lines_payload",
            return_value={"games": [{"event_id": "evt-2", "total": 224.5}]},
        ):
            from syndicate.features.nba.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context("2026-05-21")

        card = (context.get("rank_cards") or [{}])[0]
        metrics = card.get("metrics") or []
        metric_text = " ".join(f"{row.get('label')} {row.get('value')}" for row in metrics if isinstance(row, dict))

        self.assertIn("Total pts 206", card.get("summary"))
        self.assertIn("Live total 224.5", card.get("summary"))
        self.assertIn("Total pts 206", metric_text)
        self.assertIn("Live total 224.5", metric_text)
        self.assertIn("Market snapshot: Consensus lines", card.get("list_items")[0])
        self.assertIn("Away ML +105", " ".join(card.get("list_items")))
        self.assertIn("Jayson Tatum | Over 28.5 PTS", " ".join(card.get("list_items")))

    def test_live_lens_card_surface_does_not_fallback_to_cards_total(self) -> None:
        with patch(
            "syndicate.features.nba.live_lens.build_cards_page_context",
            return_value={
                "date": "2026-05-21",
                "source_path": "nba_cards.json",
                "games": [
                    {
                        "event_id": "evt-2",
                        "away": {"abbr": "BOS", "score": 104},
                        "home": {"abbr": "NYK", "score": 102},
                        "status": "Live",
                        "detail": "Q4 02:11",
                        "summary": "Live scoring pace is tracking toward the over.",
                        "betting": {"total": 221.5},
                        "panels": [],
                        "shared_prop_rows": [],
                        "shared_top_play_rows": [],
                    }
                ],
            },
        ), patch(
            "syndicate.features.nba.live_lens.build_live_lines_payload",
            return_value={"games": []},
        ):
            from syndicate.features.nba.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context("2026-05-21")

        card = (context.get("rank_cards") or [{}])[0]
        metrics = card.get("metrics") or []
        metric_labels = " ".join(str(row.get("label")) for row in metrics if isinstance(row, dict))

        self.assertNotIn("Live line", card.get("summary"))
        self.assertNotIn("Live line", metric_labels)

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
                        "player": "Jayson Tatum",
                        "team": "BOS",
                        "opponent": "NYK",
                        "stat": "pts",
                        "line": 27.5,
                        "proj": 30.2,
                        "sim_mu": 29.2,
                        "klass": "BET",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]), patch(
                # snapshot/artifact reads now resolve via the odds-control-plane processed root
                "syndicate.features.nba.sources.artifact_processed_root",
                return_value=root / "data" / "processed",
            ), patch(
                "syndicate.features.nba.cards.build_cards_page_context",
                return_value={"date": "2026-05-21"},
            ), patch(
                "syndicate.features.nba.cards._resolve_games_for_event_ids",
                return_value={"evt-2": {"event_id": "evt-2", "gamePk": "0401", "away_tri": "BOS", "home_tri": "NYK"}},
            ), patch(
                "syndicate.features.nba.cards.build_live_player_boxscore_payload",
                return_value={
                    "games": [
                        {
                            "event_id": "evt-2",
                            "players": [
                                {"team_tri": "BOS", "player": "Jayson Tatum", "pts": 20, "reb": 5, "ast": 3, "mp": 24}
                            ],
                        }
                    ]
                },
            ):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_player_lens_payload("2026-05-21", ["evt-2"], ttl=20)
                _local_live_snapshot_payload.cache_clear()

        row = ((payload.get("games") or [{}])[0].get("rows") or [{}])[0]
        self.assertEqual(row.get("player"), "Jayson Tatum")
        self.assertEqual(row.get("line_source"), "live_lens_projection_artifact")
        self.assertEqual(row.get("actual"), 20)
        self.assertEqual(row.get("live_projection"), 30.2)

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
                                    "away": "BOS",
                                    "home": "NYK",
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
                                "home": "NYK",
                                "away": "BOS",
                                "live_line": 221.5,
                            }
                        ),
                        json.dumps(
                            {
                                "market": "quarter_total",
                                "game_id": "0401",
                                "home": "NYK",
                                "away": "BOS",
                                "horizon": "q1",
                                "live_line": 56.5,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]), patch(
                # snapshot/artifact reads now resolve via the odds-control-plane processed root
                "syndicate.features.nba.sources.artifact_processed_root",
                return_value=root / "data" / "processed",
            ), patch(
                "syndicate.features.nba.cards.build_cards_page_context",
                return_value={"date": "2026-05-21"},
            ), patch(
                "syndicate.features.nba.cards._resolve_games_for_event_ids",
                return_value={"evt-2": {"event_id": "evt-2", "gamePk": "0401", "away_tri": "BOS", "home_tri": "NYK"}},
            ), patch(
                "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
                return_value=None,
            ):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_lines_payload("2026-05-21", ["evt-2"], ttl=20, include_period_totals=True)
                _local_live_snapshot_payload.cache_clear()

        game = (payload.get("games") or [{}])[0]
        self.assertEqual(game.get("total"), 221.5)
        self.assertEqual((((game.get("lines") or {}).get("period_totals") or {}).get("q1")), 56.5)
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
                        "home": "NYK",
                        "away": "BOS",
                        "live_line": 221.5,
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
                                    "away": "BOS",
                                    "home": "NYK",
                                    "found": True,
                                    "lines": {
                                        "total": 219.5,
                                        "period_totals": {"q1": 54.5},
                                        "period_spreads": {"q1": -1.5},
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

            with patch("syndicate.features.nba.sources._artifact_roots", return_value=[root]), patch(
                # snapshot/artifact reads now resolve via the odds-control-plane processed root
                "syndicate.features.nba.sources.artifact_processed_root",
                return_value=root / "data" / "processed",
            ), patch(
                "syndicate.features.nba.cards.build_cards_page_context",
                return_value={"date": "2026-05-21"},
            ), patch(
                "syndicate.features.nba.cards._resolve_games_for_event_ids",
                return_value={"evt-2": {"event_id": "evt-2", "gamePk": "0401", "away_tri": "BOS", "home_tri": "NYK"}},
            ), patch(
                "syndicate.features.nba.cards._filtered_local_live_snapshot_payload",
                return_value=None,
            ):
                _local_live_snapshot_payload.cache_clear()
                payload = build_live_lines_payload("2026-05-21", ["evt-2"], ttl=20, include_period_totals=True)
                _local_live_snapshot_payload.cache_clear()

        game = (payload.get("games") or [{}])[0]
        lines = game.get("lines") or {}
        self.assertEqual(lines.get("total"), 219.5)
        self.assertEqual((lines.get("period_totals") or {}).get("q1"), 54.5)
        self.assertEqual((lines.get("period_spreads") or {}).get("q1"), -1.5)
        self.assertEqual(payload.get("source"), "syndicate_live_snapshot_artifact")


if __name__ == "__main__":
    unittest.main()
