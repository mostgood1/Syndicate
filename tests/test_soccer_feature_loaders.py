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

    def test_a_club_that_simply_is_not_playing_today_is_dropped_QUIETLY(self) -> None:
        """REPLACES `test_unmatched_team_prints_a_visible_drop_summary`, which
        asserted that every unbound source team was announced.

        That was right when binding was fuzzy: almost nothing failed to bind,
        so the list was short and meant something. Binding is exact now, so
        EVERY club not playing today fails to bind by design -- on the first
        real run of this change one la_liga fixture printed all nineteen
        other clubs. A signal that fires on normal operation is noise, and it
        would bury the condition #148 actually cared about.

        Real Madrid not playing in Manchester City v Everton is not an event.
        """
        rows = self._rows() + [
            {"player_id": "p3", "player_name": "Toffee", "team": "Everton", "position": "DF"},
        ]
        with patch("builtins.print") as mocked_print:
            features = build_soccer_player_features(
                rows, league="epl", date="2026-08-01", fixture_teams=["Manchester City", "Everton"]
            )
        self.assertEqual({f.team for f in features}, {"Manchester City", "Everton"})
        mocked_print.assert_not_called()

    def test_a_fixture_side_with_ZERO_players_alarms_and_names_the_near_miss(self) -> None:
        """The condition #148 was written for, kept and sharpened.

        A side whose schedule spelling does not resolve against the player
        CSV's spelling gets no players at all -- a silent zero for one half of
        a real match. The log now names that side AND the unbound source team
        that most plausibly IS that club, so the reader is pointed straight at
        the `_ALIASES` entry worth adding rather than at nineteen innocent
        clubs.
        """
        rows = [
            {"player_id": "p1", "player_name": "Real Player", "team": "Manchester City", "position": "FW"},
            {"player_id": "p2", "player_name": "Toffee", "team": "Everton", "position": "DF"},
        ]
        with patch("builtins.print") as mocked_print:
            build_soccer_player_features(
                rows, league="epl", date="2026-08-01",
                fixture_teams=["Manchester City", "Everton Football Club XI"],
            )
        mocked_print.assert_called_once()
        printed = mocked_print.call_args.args[0]
        self.assertIn("SOCCER_FIXTURE_TEAM_NO_PLAYERS", printed)
        self.assertIn("Everton Football Club XI", printed)
        self.assertIn("Everton", printed)

    def test_no_print_when_both_sides_have_players(self) -> None:
        rows = [
            {"player_id": "p1", "player_name": "Real Player", "team": "Manchester City", "position": "FW"},
            {"player_id": "p2", "player_name": "Toffee", "team": "Everton", "position": "DF"},
        ]
        with patch("builtins.print") as mocked_print:
            features = build_soccer_player_features(
                rows, league="epl", date="2026-08-01", fixture_teams=["Manchester City", "Everton"]
            )
        self.assertEqual(len(features), 2)
        mocked_print.assert_not_called()


class SquadAbsorptionTests(unittest.TestCase):
    """A club must never be able to absorb another club's squad.

    Measured on production 2026-08-21, la_liga, Real Sociedad @ Real Betis:
    the artifact carried 50 Real Sociedad players. 21 were genuine, 26 were
    REAL OVIEDO absorbed at fuzzy ratio 0.750, and 3 were comma-joined
    transfer rows. Every real Sociedad player's prop share was diluted across
    a squad 2.4x too large.

    Six club pairs collide this way across five leagues, including Manchester
    City vs Manchester United at 0.812. It only fires when one of a pair plays
    and the other does not, which is why it survived so long.
    """

    def _rows(self, *teams):
        return [
            {"player_id": f"p{i}", "player_name": f"P{i}", "team": team, "position": "FW"}
            for i, team in enumerate(teams)
        ]

    def test_real_oviedo_is_not_absorbed_into_real_sociedad(self) -> None:
        features = build_soccer_player_features(
            self._rows("Real Sociedad", "Real Oviedo"),
            league="la_liga", date="2026-08-21",
            fixture_teams=["Real Sociedad", "Real Betis"],
        )
        self.assertEqual([f.team for f in features], ["Real Sociedad"])

    def test_manchester_united_is_not_absorbed_into_manchester_city(self) -> None:
        """0.812 -- the highest-scoring collision found, and the one that
        would have been most visible had it landed on a City fixture."""
        features = build_soccer_player_features(
            self._rows("Manchester City", "Manchester United"),
            league="epl", date="2026-08-21",
            fixture_teams=["Manchester City", "Everton"],
        )
        self.assertEqual([f.team for f in features], ["Manchester City"])

    def test_every_measured_collision_pair(self) -> None:
        for league, absent, present, other in [
            ("la_liga", "Real Oviedo", "Real Sociedad", "Real Betis"),
            ("epl", "Manchester United", "Manchester City", "Everton"),
            ("ligue_1", "Paris FC", "Paris Saint Germain", "Lyon"),
            ("mls", "Los Angeles FC", "LA Galaxy", "Austin FC"),
            ("belgian_pro_league", "Club Brugge", "Cercle Brugge KSV", "Genk"),
            ("mls", "Minnesota United FC", "Atlanta United FC", "Austin FC"),
        ]:
            with self.subTest(league=league, absent=absent):
                features = build_soccer_player_features(
                    self._rows(present, absent),
                    league=league, date="2026-08-21", fixture_teams=[present, other],
                )
                self.assertEqual([f.team for f in features], [present])

    def test_legitimate_spelling_variants_STILL_BIND(self) -> None:
        """The other half, and the reason exact binding needed the
        canonicalizer fixed first. These clubs are spelled one way in the
        player CSV and another in the schedule; binding them is not optional
        -- dropping them would delete 11 clubs' entire squads."""
        for league, csv_name, schedule_name in [
            ("la_liga", "Alaves", "Alav\u00e9s"),
            ("la_liga", "Atletico Madrid", "Atl\u00e9tico Madrid"),
            ("bundesliga", "Borussia M.Gladbach", "Borussia M\u00f6nchengladbach"),
            ("bundesliga", "Hamburger SV", "Hamburg SV"),
            ("bundesliga", "Union Berlin", "1. FC Union Berlin"),
            ("bundesliga", "Mainz 05", "Mainz"),
            ("bundesliga", "Hoffenheim", "TSG Hoffenheim"),
            ("ligue_1", "Auxerre", "AJ Auxerre"),
            ("serie_a", "Inter", "Internazionale"),
        ]:
            with self.subTest(league=league, club=csv_name):
                features = build_soccer_player_features(
                    self._rows(csv_name),
                    league=league, date="2026-08-21",
                    fixture_teams=[schedule_name, "Some Other Club"],
                )
                self.assertEqual(len(features), 1, f"{csv_name} lost its squad")
                self.assertEqual(features[0].team, schedule_name)

    def test_a_transfer_row_binds_to_whichever_club_is_playing(self) -> None:
        """The ingested CSVs record a mid-season move as one joined value --
        "Espanyol,Real Sociedad". Under fuzzy binding these matched by
        containment; under exact binding they would silently vanish, so they
        are split and bound deliberately."""
        features = build_soccer_player_features(
            self._rows("Espanyol,Real Sociedad", "Real Sociedad,Valencia"),
            league="la_liga", date="2026-08-21",
            fixture_teams=["Real Sociedad", "Real Betis"],
        )
        self.assertEqual([f.team for f in features], ["Real Sociedad", "Real Sociedad"])

    def test_a_transfer_between_the_two_clubs_playing_binds_to_NEITHER(self) -> None:
        """Guessing which shirt they are wearing is not something this can do
        correctly, and picking one silently is how the original bug read."""
        features = build_soccer_player_features(
            self._rows("Real Sociedad,Real Betis"),
            league="la_liga", date="2026-08-21",
            fixture_teams=["Real Sociedad", "Real Betis"],
        )
        self.assertEqual(features, ())


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
