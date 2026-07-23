from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.wnba.cards import _resolved_source_cards_date


class ResolvedSourceCardsDateScheduleAuthorityTests(unittest.TestCase):
    # Real bug found 2026-07-23: an All-Star-break date with zero real WNBA
    # games kept serving the prior day's real 6-game slate under today's
    # request. Root cause: this function checked has_games_for_date() (the
    # authoritative schedule) but only respected a "no games" result when
    # allow_stored_date_fallback was False -- and every API caller in
    # wnba.py passes allow_stored_date_fallback=True unconditionally, so the
    # schedule's "nothing today" answer was always ignored and the function
    # fell through to substituting the most recent earlier date with data.

    def test_returns_requested_date_when_schedule_confirms_no_games_even_with_fallback_allowed(self) -> None:
        with patch("syndicate.features.wnba.cards.has_games_for_date", return_value=False), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            side_effect=AssertionError("must not look for artifact data once the schedule confirms no games"),
        ), patch(
            "syndicate.features.wnba.cards.available_dates",
            side_effect=AssertionError("must not search for a fallback date once the schedule confirms no games"),
        ):
            resolved = _resolved_source_cards_date("2026-07-23", allow_stored_date_fallback=True)

        self.assertEqual(resolved, "2026-07-23")

    def test_returns_requested_date_when_schedule_confirms_no_games_and_fallback_disallowed(self) -> None:
        with patch("syndicate.features.wnba.cards.has_games_for_date", return_value=False):
            resolved = _resolved_source_cards_date("2026-07-23", allow_stored_date_fallback=False)

        self.assertEqual(resolved, "2026-07-23")

    def test_still_falls_back_when_schedule_has_games_but_todays_artifact_is_missing(self) -> None:
        # The legitimate case this function exists for: the schedule
        # confirms real games today, but today's specific game_cards
        # artifact hasn't landed yet -- falling back to the most recent
        # earlier date WITH data is the intended recovery behavior here,
        # and must be preserved.
        with patch("syndicate.features.wnba.cards.has_games_for_date", return_value=True), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value={"rows": []},
        ), patch(
            "syndicate.features.wnba.cards.available_dates",
            return_value=["2026-07-21", "2026-07-22", "2026-07-23"],
        ), patch(
            "syndicate.features.wnba.cards.central_today_iso",
            return_value="2026-07-23",
        ):
            resolved = _resolved_source_cards_date("2026-07-23", allow_stored_date_fallback=True)

        self.assertEqual(resolved, "2026-07-22")

    def test_uses_todays_artifact_when_schedule_has_games_and_data_exists(self) -> None:
        with patch("syndicate.features.wnba.cards.has_games_for_date", return_value=True), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value={"rows": [{"game_id": "1"}]},
        ):
            resolved = _resolved_source_cards_date("2026-07-23", allow_stored_date_fallback=True)

        self.assertEqual(resolved, "2026-07-23")


if __name__ == "__main__":
    unittest.main()
