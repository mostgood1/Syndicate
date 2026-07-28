from __future__ import annotations

import unittest

from syndicate.features.shared.market_id import attach_market_id


class AttachMarketIdEventIdFallbackOrderTests(unittest.TestCase):
    """#117. matchup ("CLE @ CIN") is identical for both games of a same-day
    doubleheader, so it must never outrank a real per-game identifier in the
    event_id fallback chain -- previously matchup was tried before gamePk/
    game_id, which silently merged two distinct games' market_id (and
    therefore their odds-history identity) the moment a candidate's own
    event_id was empty.
    """

    def test_real_event_id_wins_even_when_gamePk_is_also_present(self) -> None:
        payload = attach_market_id(
            {"event_id": "real-event-abc", "gamePk": 824489, "matchup": "CLE @ CIN"},
            sport="mlb",
        )
        self.assertIn("real_event_abc", payload["market_id"])

    def test_gamePk_wins_over_matchup_when_event_id_is_absent(self) -> None:
        payload = attach_market_id(
            {"gamePk": 824489, "matchup": "CLE @ CIN"},
            sport="mlb",
        )
        self.assertIn("824489", payload["market_id"])
        self.assertNotIn("CLE @ CIN", payload["market_id"])

    def test_two_doubleheader_games_get_distinct_market_ids_via_gamePk(self) -> None:
        first = attach_market_id({"gamePk": 824489, "matchup": "CLE @ CIN", "market": "h2h"}, sport="mlb")
        second = attach_market_id({"gamePk": 824490, "matchup": "CLE @ CIN", "market": "h2h"}, sport="mlb")
        self.assertNotEqual(first["market_id"], second["market_id"])

    def test_matchup_is_still_the_last_resort_when_no_game_id_exists(self) -> None:
        # Some candidate types (certain prop paths) never carry a numeric
        # game identifier at all -- matchup must still work as a fallback
        # for those; this fix only reorders the preference, it doesn't
        # remove matchup from the chain.
        payload = attach_market_id({"matchup": "CLE @ CIN"}, sport="mlb")
        self.assertIn("cle_cin", payload["market_id"])


if __name__ == "__main__":
    unittest.main()
