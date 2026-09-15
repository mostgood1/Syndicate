"""Anytime scorer, fix #3: ESPN goal and assist rates are shrunk toward a positional prior.

ESPN-league rows carry REALISED goals per 90, so every player who had not scored
was priced at an anytime probability of exactly 0.000: 53% of appeared players in
those four leagues, measured 2026-09-15 (0.2% in the Understat/ASA leagues, whose
rates were already shrunk). Held out, shrinking toward a (league, position) prior
with the 180-minute curve cut the ESPN leagues' anytime log loss from 0.3551 to
0.2666 (lane soccer-anytime-scorer).

The last class is the reachability test. It drives the real
`aggregate_season_player_stats` with only the ESPN fetches stubbed, so a helper that
exists but is never called fails here.
"""

from __future__ import annotations

import unittest
from unittest import mock

from syndicate.features.soccer.ingestion import espn_player_stats as EPS


def _row(pid, position, minutes, xg90, xa90=0.0, shots90=2.0):
    return {"player_id": pid, "player_name": pid.upper(), "position": position,
            "minutes_played": minutes, "xg_per90": xg90, "xa_per90": xa90, "shots_per90": shots90}


class ShrinkGoalRatesTowardPosition(unittest.TestCase):
    def test_a_player_with_no_goals_gets_a_nonzero_rate(self):
        rows = [_row("scorer", "Center Left Defender", 180.0, 0.5),
                _row("blank", "Center Right Defender", 180.0, 0.0)]
        EPS._shrink_goal_rates_toward_position(rows)
        self.assertGreater(rows[1]["xg_per90"], 0.0)
        self.assertLess(rows[1]["xg_per90"], rows[0]["xg_per90"])

    def test_the_weight_and_prior_are_the_documented_curve(self):
        rows = [_row("a", "Forward", 180.0, 0.6), _row("b", "Forward", 540.0, 0.2)]
        EPS._shrink_goal_rates_toward_position(rows)
        prior = (0.6 * 180.0 + 0.2 * 540.0) / 720.0
        weight_a = 180.0 / (180.0 + 180.0)
        weight_b = 540.0 / (540.0 + 180.0)
        self.assertAlmostEqual(rows[0]["xg_per90"], round(weight_a * 0.6 + (1 - weight_a) * prior, 4), places=4)
        self.assertAlmostEqual(rows[1]["xg_per90"], round(weight_b * 0.2 + (1 - weight_b) * prior, 4), places=4)
        self.assertEqual(rows[0]["rate_own_weight"], 0.5)

    def test_positions_bucket_by_keyword_not_first_token(self):
        self.assertEqual(EPS._position_bucket("Center Left Defender"), "D")
        self.assertEqual(EPS._position_bucket("Left Back"), "D")
        self.assertEqual(EPS._position_bucket("Attacking Midfielder Right"), "M")
        self.assertEqual(EPS._position_bucket("Center Right Forward"), "F")
        self.assertEqual(EPS._position_bucket("Goalkeeper"), "GK")
        self.assertEqual(EPS._position_bucket("Substitute"), "?")
        self.assertEqual(EPS._position_bucket(None), "?")

    def test_a_substitute_takes_the_league_outfield_prior(self):
        rows = [_row("d", "Center Left Defender", 360.0, 0.0), _row("f", "Forward", 360.0, 0.6),
                _row("s", "Substitute", 90.0, 0.0)]
        league_prior = (0.0 * 360 + 0.6 * 360 + 0.0 * 90) / 810.0
        EPS._shrink_goal_rates_toward_position(rows)
        weight = 90.0 / 270.0
        self.assertAlmostEqual(rows[2]["xg_per90"], round((1 - weight) * league_prior, 4), places=4)

    def test_goalkeepers_are_neither_shrunk_nor_counted(self):
        rows = [_row("gk", "Goalkeeper", 900.0, 0.0), _row("f1", "Forward", 180.0, 0.4), _row("f2", "Forward", 180.0, 0.0)]
        EPS._shrink_goal_rates_toward_position(rows)
        self.assertEqual(rows[0]["xg_per90"], 0.0)
        self.assertNotIn("rate_own_weight", rows[0])
        self.assertAlmostEqual(rows[2]["xg_per90"], round(0.5 * 0.2, 4), places=4)

    def test_shots_are_not_shrunk(self):
        rows = [_row("f1", "Forward", 180.0, 0.4, shots90=5.0), _row("f2", "Forward", 180.0, 0.0, shots90=0.0)]
        EPS._shrink_goal_rates_toward_position(rows)
        self.assertEqual(rows[0]["shots_per90"], 5.0)
        self.assertEqual(rows[1]["shots_per90"], 0.0)


def _match_rows(event_id):
    base = {"team": "Test FC", "is_goalkeeper": False, "starter": True, "total_shots": 1.0, "shots_on_target": 0.0,
            "goal_assists": 0.0}
    return [
        dict(base, player_id="d1", player_name="Def One", position="Center Left Defender",
             total_goals=1.0 if event_id == "e1" else 0.0),
        dict(base, player_id="d2", player_name="Def Two", position="Center Right Defender", total_goals=0.0),
        dict(base, player_id="gk", player_name="Keeper", position="Goalkeeper", is_goalkeeper=True, total_goals=0.0),
    ]


class TheProducerPublishesShrunkRates(unittest.TestCase):
    def test_aggregate_season_player_stats_shrinks_before_it_returns(self):
        with mock.patch.object(EPS, "fetch_completed_events", lambda league, date_windows: [{"event_id": "e1"}, {"event_id": "e2"}]), \
                mock.patch.object(EPS, "fetch_match_summary", lambda league, event_id: {"event_id": event_id}), \
                mock.patch.object(EPS, "extract_match_player_rows", lambda summary, event_id: _match_rows(event_id)), \
                mock.patch.object(EPS, "extract_key_events", lambda summary: []), \
                mock.patch.object(EPS, "compute_minutes_played", lambda key_events, rows: {r["player_id"]: 90.0 for r in rows}):
            rows = {r["player_id"]: r for r in EPS.aggregate_season_player_stats("championship", date_windows=["x"], min_appearances=1)}
        # d1: 1 goal in 180 min -> 0.5/90 raw; d2: 0. Defender prior = 0.25; weight = 0.5.
        self.assertAlmostEqual(rows["d2"]["xg_per90"], 0.125, places=4)
        self.assertAlmostEqual(rows["d1"]["xg_per90"], 0.375, places=4)
        self.assertEqual(rows["d2"]["rate_own_weight"], 0.5)
        self.assertEqual(rows["gk"]["xg_per90"], 0.0)


if __name__ == "__main__":
    unittest.main()
