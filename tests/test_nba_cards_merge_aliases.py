from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.nba.cards import build_cards_page_context
from syndicate.features.nba.cards import _merge_games_with_live_state, build_cards_sim_detail_payload, build_live_lines_payload


class NbaCardsMergeAliasTests(unittest.TestCase):
    def test_merge_uses_canonical_team_aliases(self) -> None:
        processed_games = [
            {
                "gamePk": "1",
                "event_id": "",
                "away_tri": "SAS",
                "home_tri": "OKC",
                "status": "Scheduled",
                "detail": "2026-05-31T00:00:00+00:00",
            }
        ]
        live_games = [
            {
                "gamePk": "SA@OKC",
                "event_id": "",
                "away_tri": "SA",
                "home_tri": "OKC",
                "status": "Final",
                "detail": "Final",
                "live_state": {
                    "away": "SA",
                    "home": "OKC",
                    "status": "Final",
                    "final": True,
                },
            }
        ]

        with patch(
            "syndicate.features.nba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_live_fetch"),
        ):
            merged_games, _, supplemented_count, updated_count = _merge_games_with_live_state(processed_games, "2026-05-30")

        self.assertEqual(len(merged_games), 1)
        self.assertEqual(supplemented_count, 0)
        self.assertEqual(updated_count, 1)
        self.assertEqual(merged_games[0].get("away_tri"), "SAS")
        self.assertEqual(merged_games[0].get("home_tri"), "OKC")
        self.assertEqual(merged_games[0].get("status"), "Final")
        self.assertEqual(merged_games[0].get("detail"), "Final")

    def test_sim_detail_payload_does_not_use_remote_base_url_without_explicit_fallback(self) -> None:
        # The remote source-app-fallback code this test used to pin as
        # unreachable (_remote_source_fallback_enabled/_remote_source_base_url/
        # _remote_fetch_json) was itself dead -- confirmed zero callers
        # anywhere in nba/cards.py -- and removed. Nothing left to assert
        # isn't called; this now just confirms the artifact-only path.
        with patch("syndicate.features.nba.cards._artifact_bundle", return_value={"sim": {}, "paths": {}, "rows": []}), patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"games": []},
        ):
            payload = build_cards_sim_detail_payload("2026-05-22", "BOS", "NYK")

        self.assertEqual(payload["games"], [])
        self.assertEqual(payload["requested_date"], "2026-05-22")

    def test_live_lines_payload_stays_local_only_when_artifacts_are_missing(self) -> None:
        with patch("syndicate.features.nba.cards._filtered_local_live_snapshot_payload", return_value=None), patch(
            "syndicate.features.nba.cards._artifact_live_lines_payload",
            return_value=None,
        ), patch(
            "syndicate.features.nba.cards._resolve_games_for_event_ids",
            return_value={},
        ), patch(
            "syndicate.features.nba.cards.build_cards_page_context",
            return_value={"date": "2026-05-22", "games": []},
        ):
            payload = build_live_lines_payload(
                "2026-05-22",
                ["401859964"],
                include_period_totals=True,
                allow_stored_date_fallback=False,
            )

        self.assertEqual(payload["games"], [{"event_id": "401859964", "found": False}])
        self.assertEqual(payload["requested_date"], "2026-05-22")

    def test_cards_page_context_stays_artifact_first_on_render_web_dyno(self) -> None:
        with patch("syndicate.features.nba.cards._render_web_dyno", return_value=True), patch(
            "syndicate.features.nba.cards._games_from_artifacts",
            return_value=([
                {
                    "gamePk": "1",
                    "away_tri": "BOS",
                    "home_tri": "NYK",
                    "status": "Scheduled",
                    "detail": "2026-05-22",
                    "away": {"abbr": "BOS"},
                    "home": {"abbr": "NYK"},
                }
            ], "cards.csv", "recs.json"),
        ), patch(
            "syndicate.features.nba.cards._merge_games_with_live_state",
            side_effect=AssertionError("live merge should not run on render web dynos"),
        ), patch(
            "syndicate.features.nba.cards._games_from_live_state_fallback",
            side_effect=AssertionError("live fallback should not run on render web dynos"),
        ):
            context = build_cards_page_context("2026-05-22", allow_stored_date_fallback=True)

        self.assertEqual(context.get("source_title"), "NBA processed game cards")
        self.assertEqual(context.get("date"), "2026-05-22")
        self.assertEqual(len(context.get("games") or []), 1)


if __name__ == "__main__":
    unittest.main()
