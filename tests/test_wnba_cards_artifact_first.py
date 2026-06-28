from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.wnba.cards import build_live_state_payload
from syndicate.features.wnba.cards import build_source_cards_sim_detail_payload


class WnbaCardsArtifactFirstTests(unittest.TestCase):
    def test_sim_detail_payload_does_not_use_remote_base_url_without_explicit_fallback(self) -> None:
        with patch("syndicate.features.wnba.cards._artifact_bundle", return_value={"sim": {}, "paths": {}, "rows": []}), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"games": []},
        ), patch(
            "syndicate.features.wnba.cards._remote_source_fallback_enabled",
            return_value=False,
        ), patch(
            "syndicate.features.wnba.cards._remote_source_base_url",
            return_value="https://source-app.example",
        ), patch(
            "syndicate.features.wnba.cards._remote_live_snapshot_payload",
            side_effect=AssertionError("remote source fetch should not be used when fallback is disabled"),
        ):
            payload = build_source_cards_sim_detail_payload("2026-05-22", "GSV", "NYL")

        self.assertEqual(payload["games"], [])
        self.assertEqual(payload["requested_date"], "2026-05-22")

    def test_live_state_payload_stays_local_only_when_artifacts_are_missing(self) -> None:
        with patch("syndicate.features.wnba.cards._local_live_state_payload", return_value=None), patch(
            "syndicate.features.wnba.cards.build_cards_page_context",
            return_value={"date": "2026-05-22", "games": []},
        ), patch(
            "syndicate.features.wnba.cards._remote_live_snapshot_payload",
            side_effect=AssertionError("remote live snapshot should not be used"),
        ), patch(
            "syndicate.features.wnba.cards._public_scoreboard_live_state_payload",
            side_effect=AssertionError("public scoreboard should not be used"),
        ):
            payload = build_live_state_payload("2026-05-22", allow_stored_date_fallback=False)

        self.assertEqual(payload["source"], "syndicate_cards_fallback")
        self.assertEqual(payload["games"], [])


if __name__ == "__main__":
    unittest.main()
