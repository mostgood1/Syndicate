from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.wnba.cards import build_cards_page_context
from syndicate.features.wnba.cards import build_live_state_payload
from syndicate.features.wnba.cards import build_source_cards_sim_detail_payload


class WnbaCardsArtifactFirstTests(unittest.TestCase):
    def test_sim_detail_payload_does_not_use_remote_base_url_without_explicit_fallback(self) -> None:
        # The remote source-app-fallback code this test used to pin as
        # unreachable (_remote_source_fallback_enabled/_remote_source_base_url/
        # _remote_live_snapshot_payload) was itself dead -- confirmed zero
        # callers anywhere in wnba/cards.py -- and removed. Nothing left to
        # assert isn't called; this now just confirms the artifact-only path.
        with patch("syndicate.features.wnba.cards._artifact_bundle", return_value={"sim": {}, "paths": {}, "rows": []}), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"games": []},
        ):
            payload = build_source_cards_sim_detail_payload("2026-05-22", "GSV", "NYL")

        self.assertEqual(payload["games"], [])
        self.assertEqual(payload["requested_date"], "2026-05-22")

    def test_live_state_payload_stays_local_only_when_artifacts_are_missing(self) -> None:
        with patch("syndicate.features.wnba.cards._local_live_state_payload", return_value=None), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-22", "games": []},
        ), patch(
            "syndicate.features.wnba.cards._public_scoreboard_live_state_payload",
            side_effect=AssertionError("public scoreboard should not be used"),
        ):
            payload = build_live_state_payload("2026-05-22", allow_stored_date_fallback=False)

        self.assertEqual(payload["source"], "syndicate_cards_fallback")
        self.assertEqual(payload["games"], [])

    def test_cards_page_context_skips_artifact_loading_on_no_game_dates(self) -> None:
        with patch("syndicate.features.wnba.cards.has_games_for_date", return_value=False), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            side_effect=AssertionError("artifact bundle should not load for no-game dates"),
        ):
            context = build_cards_page_context("2026-06-29")

        self.assertEqual(context["games"], [])
        self.assertEqual(context["source_title"], "WNBA cards unavailable")


if __name__ == "__main__":
    unittest.main()
