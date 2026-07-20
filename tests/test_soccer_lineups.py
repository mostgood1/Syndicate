from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer.features.lineups import attach_confirmed_starters
from syndicate.features.soccer.features.lineups import fetch_confirmed_starter_ids
from syndicate.features.soccer.features.lineups import find_event_for_fixture
from syndicate.features.soccer.features.lineups import resolve_starter_ids


def _player_rows() -> list[dict]:
    return [
        {"player_id": "h1", "player_name": "Home Striker"},
        {"player_id": "h2", "player_name": "Home Winger"},
        {"player_id": "h3", "player_name": "Home Bench"},
    ]


def _fake_summary(*, home_starters: int, away_starters: int) -> dict:
    def rows(side: str, count: int, total: int) -> list[dict]:
        entries = []
        for i in range(total):
            entries.append(
                {
                    "starter": i < count,
                    "subbedIn": False,
                    "athlete": {"id": f"{side}{i}", "displayName": f"{side.title()} Player{i}"},
                    "position": {"name": "Forward"},
                    "stats": [],
                }
            )
        return entries

    return {
        "rosters": [
            {"homeAway": "home", "team": {"displayName": "Home FC"}, "roster": rows("home", home_starters, 11)},
            {"homeAway": "away", "team": {"displayName": "Away FC"}, "roster": rows("away", away_starters, 11)},
        ]
    }


class ResolveStarterIdsTests(unittest.TestCase):
    def test_resolves_by_normalized_name(self) -> None:
        ids = resolve_starter_ids(_player_rows(), {"home striker", "home winger"})
        self.assertEqual(ids, {"h1", "h2"})

    def test_accent_insensitive(self) -> None:
        rows = [{"player_id": "p1", "player_name": "José Álvarez"}]
        self.assertEqual(resolve_starter_ids(rows, {"jose alvarez"}), {"p1"})

    def test_no_matches_returns_empty(self) -> None:
        self.assertEqual(resolve_starter_ids(_player_rows(), {"nobody here"}), set())


class FindEventForFixtureTests(unittest.TestCase):
    def test_matches_by_fuzzy_team_names(self) -> None:
        events = [
            {"event_id": "e1", "home_team": "Manchester City", "away_team": "Arsenal"},
            {"event_id": "e2", "home_team": "Liverpool", "away_team": "Chelsea"},
        ]
        found = find_event_for_fixture(events, home_team="Man City", away_team="Arsenal")
        self.assertEqual(found["event_id"], "e1")

    def test_no_match_returns_none(self) -> None:
        events = [{"event_id": "e1", "home_team": "Manchester City", "away_team": "Arsenal"}]
        self.assertIsNone(find_event_for_fixture(events, home_team="Man City", away_team="Everton"))

    def test_empty_events_returns_none(self) -> None:
        self.assertIsNone(find_event_for_fixture([], home_team="Man City", away_team="Arsenal"))


class FetchConfirmedStarterIdsTests(unittest.TestCase):
    def test_returns_none_when_lineup_not_posted_yet(self) -> None:
        events = [{"event_id": "e1", "home_team": "Home FC", "away_team": "Away FC"}]
        with patch(
            "syndicate.features.soccer.features.lineups.fetch_match_summary",
            return_value=_fake_summary(home_starters=0, away_starters=0),
        ):
            result = fetch_confirmed_starter_ids(
                "epl",
                home_team="Home FC",
                away_team="Away FC",
                home_player_rows=[],
                away_player_rows=[],
                events=events,
            )
        self.assertIsNone(result)

    def test_returns_none_when_no_matching_event(self) -> None:
        result = fetch_confirmed_starter_ids(
            "epl", home_team="Home FC", away_team="Away FC", home_player_rows=[], away_player_rows=[], events=[]
        )
        self.assertIsNone(result)

    def test_returns_starter_ids_when_lineup_posted_and_matched(self) -> None:
        events = [{"event_id": "e1", "home_team": "Home FC", "away_team": "Away FC"}]
        home_rows = [{"player_id": f"home{i}", "player_name": f"Home Player{i}"} for i in range(11)]
        away_rows = [{"player_id": f"away{i}", "player_name": f"Away Player{i}"} for i in range(11)]
        with patch(
            "syndicate.features.soccer.features.lineups.fetch_match_summary",
            return_value=_fake_summary(home_starters=11, away_starters=11),
        ):
            result = fetch_confirmed_starter_ids(
                "epl",
                home_team="Home FC",
                away_team="Away FC",
                home_player_rows=home_rows,
                away_player_rows=away_rows,
                events=events,
            )
        self.assertIsNotNone(result)
        home_ids, away_ids = result
        self.assertEqual(len(home_ids), 11)
        self.assertEqual(len(away_ids), 11)


class AttachConfirmedStartersTests(unittest.TestCase):
    def test_unmatched_fixture_is_returned_unchanged(self) -> None:
        fixtures = [{"home_team": "Nowhere FC", "away_team": "Nobody FC"}]
        with patch("syndicate.features.soccer.features.lineups.fetch_events", return_value=[]):
            updated = attach_confirmed_starters(
                fixtures, league="epl", player_rows_by_team={}, date_windows=["20260101-20260107"]
            )
        self.assertEqual(updated, fixtures)
        self.assertNotIn("home_starter_ids", updated[0])

    def test_matched_fixture_with_posted_lineup_gets_starter_ids(self) -> None:
        fixtures = [{"home_team": "Home FC", "away_team": "Away FC"}]
        events = [{"event_id": "e1", "home_team": "Home FC", "away_team": "Away FC"}]
        player_rows_by_team = {
            "Home FC": [{"player_id": f"home{i}", "player_name": f"Home Player{i}"} for i in range(11)],
            "Away FC": [{"player_id": f"away{i}", "player_name": f"Away Player{i}"} for i in range(11)],
        }
        with patch("syndicate.features.soccer.features.lineups.fetch_events", return_value=events), patch(
            "syndicate.features.soccer.features.lineups.fetch_match_summary",
            return_value=_fake_summary(home_starters=11, away_starters=11),
        ):
            updated = attach_confirmed_starters(
                fixtures, league="epl", player_rows_by_team=player_rows_by_team, date_windows=["20260101-20260107"]
            )
        self.assertEqual(len(updated[0]["home_starter_ids"]), 11)
        self.assertEqual(len(updated[0]["away_starter_ids"]), 11)
        # Input list is not mutated.
        self.assertNotIn("home_starter_ids", fixtures[0])

    def test_does_not_mutate_input_fixtures_list(self) -> None:
        fixtures = [{"home_team": "Nowhere FC", "away_team": "Nobody FC"}]
        original = dict(fixtures[0])
        with patch("syndicate.features.soccer.features.lineups.fetch_events", return_value=[]):
            attach_confirmed_starters(fixtures, league="epl", player_rows_by_team={}, date_windows=["20260101-20260107"])
        self.assertEqual(fixtures[0], original)


if __name__ == "__main__":
    unittest.main()
