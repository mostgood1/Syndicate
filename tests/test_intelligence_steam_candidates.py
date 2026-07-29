from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.intelligence import _classify_candidate_with_reason
from syndicate.features.intelligence import _steam_candidates_for_sport


LIVE_PROP_STEAM_EVENT = {
    "capture_phase": "live",
    "timestamp": "2026-07-29T23:05:00+00:00",
    "game_id": "824003",
    "sport": "mlb",
    "market_id": "mlb:824003:batter_hits:willy_adames",
    "player_id": None,
    "player_name": "willy adames",
    "selection": "Over",
    "market_type": "batter_hits",
    "event_type": "update",
    "line": 1.5,
    "price": 145.0,
    "implied_prob": 0.408,
    "source": "oddsapi",
    "is_live": True,
    "steam": {
        "line_delta": 0.5,
        "odds_delta": 30.0,
        "window_seconds": 120.0,
        "capture_phase": "live",
        "previous_line": 1.0,
        "previous_odds": 115.0,
    },
}

PREGAME_TEAM_STEAM_EVENT = {
    "capture_phase": "closing",
    "timestamp": "2026-07-29T22:00:00+00:00",
    "game_id": "823598",
    "sport": "mlb",
    "player_name": "Los Angeles Dodgers",
    "selection": None,
    "market_type": "totals",
    "event_type": "update",
    "line": 8.5,
    "price": -114.0,
    "implied_prob": 0.532,
    "source": "oddsapi",
    "is_live": False,
    "steam": {
        "line_delta": 1.0,
        "odds_delta": None,
        "window_seconds": 300.0,
        "capture_phase": "closing",
        "previous_line": 7.5,
        "previous_odds": -114.0,
    },
}


def _sport(slug: str = "mlb", context_label: str = "2026-07-29") -> dict:
    return {"slug": slug, "name": slug.upper(), "context_label": context_label}


class SteamCandidatesForSportTests(unittest.TestCase):
    def test_live_prop_steam_event_becomes_a_live_prop_candidate(self) -> None:
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[LIVE_PROP_STEAM_EVENT],
        ):
            candidates = _steam_candidates_for_sport(_sport())

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate["candidate_type"], "steam")
        self.assertEqual(candidate["lane"], "live")
        self.assertTrue(candidate["is_live"])
        # Case-inconsistent source data ("willy adames") title-cased for display.
        self.assertEqual(candidate["player_name"], "Willy Adames")
        self.assertIn("Over 1.5", candidate["pick"])
        self.assertEqual(candidate["line_odds_movement"]["opening_line"], 1.0)
        self.assertEqual(candidate["line_odds_movement"]["latest_line"], 1.5)
        self.assertEqual(candidate["line_odds_movement"]["line_direction"], "up")
        classified, reason = _classify_candidate_with_reason(candidate)
        self.assertIsNone(reason)
        self.assertIsNotNone(classified)

    def test_pregame_team_total_steam_event_has_no_player_name(self) -> None:
        # #131-adjacent: a team/game-level steam move must not carry a
        # player_name -- the frontend's market-family filter
        # (matchesClientFilters, intelligence.html) treats any candidate
        # with a truthy player_name as a "prop", which would wrongly hide a
        # team total's steam move from "Game markets" and misfile it under
        # "Player props".
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[PREGAME_TEAM_STEAM_EVENT],
        ):
            candidates = _steam_candidates_for_sport(_sport())

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate["lane"], "pregame")
        self.assertFalse(candidate["is_live"])
        self.assertIsNone(candidate["player_name"])
        classified, reason = _classify_candidate_with_reason(candidate)
        self.assertIsNone(reason)
        self.assertIsNotNone(classified)

    def test_events_for_a_different_sport_are_excluded(self) -> None:
        wnba_event = dict(LIVE_PROP_STEAM_EVENT, sport="wnba")
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[wnba_event],
        ):
            candidates = _steam_candidates_for_sport(_sport("mlb"))
        self.assertEqual(candidates, [])

    def test_event_without_a_steam_signal_is_skipped(self) -> None:
        plain_event = {key: value for key, value in LIVE_PROP_STEAM_EVENT.items() if key != "steam"}
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[plain_event],
        ):
            candidates = _steam_candidates_for_sport(_sport())
        self.assertEqual(candidates, [])

    def test_duplicate_events_collapse_to_one_candidate(self) -> None:
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[LIVE_PROP_STEAM_EVENT, dict(LIVE_PROP_STEAM_EVENT)],
        ):
            candidates = _steam_candidates_for_sport(_sport())
        self.assertEqual(len(candidates), 1, candidates)

    def test_no_context_label_or_events_returns_empty(self) -> None:
        self.assertEqual(_steam_candidates_for_sport({"slug": "mlb", "context_label": ""}), [])
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=[]):
            self.assertEqual(_steam_candidates_for_sport(_sport()), [])


if __name__ == "__main__":
    unittest.main()
