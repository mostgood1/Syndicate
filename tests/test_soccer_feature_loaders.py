from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer.features.loaders import build_soccer_player_features
from syndicate.features.soccer.features.loaders import build_soccer_simulation_input
from syndicate.features.soccer.features.loaders import compute_team_ratings
from syndicate.features.soccer.features.loaders import team_rows_from_match_history
from syndicate.features.soccer.features.team_names import canonical_team_name
from syndicate.features.soccer.features.team_names import match_team_name


# `compute_team_ratings` requires an as-of date (audit §7 #6) and drops rows it
# cannot date, so these fixtures carry real dates. They had none before -- the
# function had no notion of time at all, which is what let the backtest score a
# March match with May results.
_AS_OF = "2026-06-01"


def _team_rows() -> list[dict]:
    rows = []
    for index in range(10):
        day = f"2026-03-{index + 1:02d}"
        rows.append({"team": "Manchester City", "date": day, "xg_for": 2.3, "xg_against": 0.8, "ppda": 9.0})
        rows.append({"team": "Everton", "date": day, "xg_for": 1.1, "xg_against": 2.2, "ppda": 13.0})
        rows.append({"team": "Arsenal", "date": day, "xg_for": 2.0, "xg_against": 0.9, "ppda": 10.0})
    return rows


class TeamNameTests(unittest.TestCase):
    def test_canonical_aliases(self) -> None:
        self.assertEqual(canonical_team_name("Man City"), "manchester city")
        self.assertEqual(canonical_team_name("Nott'm Forest"), "nottingham forest")
        self.assertEqual(canonical_team_name("Wolverhampton Wanderers"), "wolverhampton")
        self.assertEqual(canonical_team_name("Tottenham Hotspur"), "tottenham")

    def test_lafc_does_not_collide_with_galaxy(self) -> None:
        candidates = ["Los Angeles FC", "LA Galaxy"]
        self.assertEqual(match_team_name("Los Angeles FC", candidates), "Los Angeles FC")
        self.assertEqual(match_team_name("LA Galaxy", candidates), "LA Galaxy")
        self.assertEqual(match_team_name("Los Angeles Galaxy", candidates), "LA Galaxy")

    def test_match_team_name_fuzzy_and_missing(self) -> None:
        candidates = ["Manchester City", "Manchester United", "Everton"]
        self.assertEqual(match_team_name("Man City", candidates), "Manchester City")
        self.assertEqual(match_team_name("Man Utd", candidates), "Manchester United")
        self.assertIsNone(match_team_name("Real Madrid", candidates))

    def test_red_bull_new_york_matches_odds_api_new_york_red_bulls(self) -> None:
        # ESPN's own full club name ("Red Bull New York") and the Odds
        # API's market name ("New York Red Bulls") share every token but in
        # a different order with a singular/plural mismatch -- confirmed
        # 2026-07-24 that without an explicit alias, match_team_name's
        # SequenceMatcher-based fuzzy fallback scores this pair too low to
        # clear the default threshold and returns None.
        candidates = ["New York Red Bulls", "Charlotte FC"]
        self.assertEqual(match_team_name("Red Bull New York", candidates), "New York Red Bulls")


class BuildSoccerPlayerFeaturesTests(unittest.TestCase):
    # #148 follow-up. build_soccer_player_features silently dropped any
    # player whose roster-CSV team name doesn't resolve against the
    # fixture's ESPN team names -- no log, no count, same "no error path
    # for an unmatched case" shape as #146's _load_player_rows. Confirming
    # the drop behavior is unchanged (still correctly excludes an
    # unmatched-team player from the fixture) while also confirming the new
    # visibility print actually fires for the dropped row and stays quiet
    # when nothing was dropped.
    def _rows(self) -> list[dict]:
        return [
            {"player_id": "p1", "player_name": "Real Player", "team": "Manchester City", "position": "FW"},
            {"player_id": "p2", "player_name": "Ghost Player", "team": "Real Madrid", "position": "MF"},
        ]

    def test_matched_player_is_kept_and_unmatched_player_is_dropped(self) -> None:
        features = build_soccer_player_features(
            self._rows(), league="epl", date="2026-08-01", fixture_teams=["Manchester City", "Everton"]
        )
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0].player_name, "Real Player")
        self.assertEqual(features[0].team, "Manchester City")

    def test_unmatched_team_prints_a_visible_drop_summary(self) -> None:
        with patch("builtins.print") as mocked_print:
            build_soccer_player_features(
                self._rows(), league="epl", date="2026-08-01", fixture_teams=["Manchester City", "Everton"]
            )
        mocked_print.assert_called_once()
        printed_text = mocked_print.call_args.args[0]
        self.assertIn("SOCCER_PLAYER_ROWS_UNMATCHED_TEAM", printed_text)
        self.assertIn("Real Madrid", printed_text)

    def test_no_print_when_every_row_matches(self) -> None:
        rows = [{"player_id": "p1", "player_name": "Real Player", "team": "Manchester City", "position": "FW"}]
        with patch("builtins.print") as mocked_print:
            features = build_soccer_player_features(rows, league="epl", date="2026-08-01", fixture_teams=["Manchester City", "Everton"])
        self.assertEqual(len(features), 1)
        mocked_print.assert_not_called()


class TeamRatingTests(unittest.TestCase):
    def test_ratings_are_relative_to_league_mean(self) -> None:
        ratings = compute_team_ratings(_team_rows(), as_of=_AS_OF)

        self.assertGreater(ratings["Manchester City"]["attack_rating"], 0.0)
        self.assertGreater(ratings["Manchester City"]["defense_rating"], 0.0)
        self.assertLess(ratings["Everton"]["attack_rating"], 0.0)
        self.assertLess(ratings["Everton"]["defense_rating"], 0.0)
        self.assertAlmostEqual(ratings["Manchester City"]["xg_for_per_match"], 2.3, places=4)

    def test_window_limits_rows(self) -> None:
        rows = _team_rows()
        # Append a late collapse for City; a short window should see only it.
        # Dated AFTER the base rows (March) and before `_AS_OF`, because the
        # window now selects the most recent rows *that predate as_of* -- undated
        # rows are dropped, which is what makes the leak un-reintroducible.
        for index in range(5):
            rows.append({
                "team": "Manchester City", "date": f"2026-04-{index + 1:02d}",
                "xg_for": 0.5, "xg_against": 2.5, "ppda": 14.0,
            })
        full = compute_team_ratings(rows, as_of=_AS_OF)
        recent = compute_team_ratings(rows, as_of=_AS_OF, window=5)
        self.assertLess(recent["Manchester City"]["attack_rating"], full["Manchester City"]["attack_rating"])

    def test_team_rows_from_match_history(self) -> None:
        match_rows = [
            {"league": "epl", "season": 2025, "date": "x", "home_team": "A", "away_team": "B", "home_goals": 3, "away_goals": 1},
        ]
        rows = team_rows_from_match_history(match_rows)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["team"], "A")
        self.assertEqual(rows[0]["xg_for"], 3.0)
        self.assertEqual(rows[1]["team"], "B")
        self.assertEqual(rows[1]["xg_against"], 3.0)


class SimulationInputBuilderTests(unittest.TestCase):
    def test_build_input_matches_ratings_and_players(self) -> None:
        ratings = compute_team_ratings(_team_rows(), as_of=_AS_OF)
        player_rows = [
            {"player_id": "p1", "player_name": "City Striker", "team": "Man City", "position": "FW",
             "shots_per90": 3.5, "xg_per90": 0.6, "xa_per90": 0.2, "expected_minutes_share": 0.9},
            {"player_id": "p2", "player_name": "Everton Mid", "team": "Everton", "position": "MF",
             "shots_per90": 1.5, "xg_per90": 0.2, "xa_per90": 0.2, "expected_minutes_share": 0.8},
            {"player_id": "p3", "player_name": "Elsewhere", "team": "Real Madrid", "position": "FW",
             "shots_per90": 3.0, "xg_per90": 0.5, "xa_per90": 0.2},
        ]
        simulation_input = build_soccer_simulation_input(
            league="epl",
            date="2026-08-21",
            fixtures=[{"home_team": "Manchester City", "away_team": "Everton"}],
            ratings=ratings,
            player_rows=player_rows,
            simulations=25,
        )

        self.assertEqual(len(simulation_input.matches), 1)
        match = simulation_input.matches[0]
        self.assertGreater(match.team_metrics["home_attack_rating"], 0.0)
        self.assertLess(match.team_metrics["away_attack_rating"], 0.0)
        self.assertTrue(match.adapter_metadata["home_rating_matched"])
        # Player from an unrelated team is excluded; matched players are
        # rewritten to fixture naming.
        self.assertEqual(len(simulation_input.players), 2)
        self.assertEqual(simulation_input.players[0].team, "Manchester City")
        self.assertEqual(simulation_input.metadata["simulations"], 25)

    def test_unrated_team_gets_neutral_rating_and_flag(self) -> None:
        ratings = compute_team_ratings(_team_rows(), as_of=_AS_OF)
        simulation_input = build_soccer_simulation_input(
            league="epl",
            date="2026-08-21",
            fixtures=[{"home_team": "Arsenal", "away_team": "Coventry City"}],
            ratings=ratings,
        )
        match = simulation_input.matches[0]
        self.assertEqual(match.team_metrics["away_attack_rating"], 0.0)
        self.assertFalse(match.adapter_metadata["away_rating_matched"])


if __name__ == "__main__":
    unittest.main()
