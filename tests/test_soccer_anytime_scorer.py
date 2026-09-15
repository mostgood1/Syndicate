"""Fix #3 (H19-b): the ESPN goal-rate shrink runs at LOAD TIME, after the dedupe.

WHY THESE TESTS EXIST IN THIS SHAPE. The same shrink was first written in the
PRODUCER (`espn_player_stats.py`). It was correct in isolation, had passing tests,
and reached the engine with NO EFFECT AT ALL -- `_load_player_rows` dedupes by
`player_id` keeping the row with the MOST MINUTES, and a completed prior season
outweighs eight matchweeks, so the freshly-shrunk current-season rows were thrown
away before `build_usage_profiles` saw them. Measured on production's own files:
the 2025 row wins for 129 of 196 championship players present in both files
(65.8%) and 187 of 201 in eredivisie (93.0%). H19 was falsified on exactly that.

So the first test here is REACHABILITY through the real `_load_player_rows`
(`off != on`), and the second is the dedupe-survivor case. A transform that runs
and changes nothing the engine reads looks identical to a working one at every
level except the data.
"""
from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ESPN_COLUMNS = (
    "league,player_id,player_name,team,position,is_goalkeeper,appearances,starts,"
    "minutes_played,shots_per90,xg_per90,xa_per90,shot_on_target_rate,"
    "expected_minutes_share,source"
)


def _load_module(repo_root: Path):
    script_path = repo_root / "scripts" / "build_soccer_artifacts.py"
    spec = importlib.util.spec_from_file_location("anytime_build_soccer_artifacts", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _espn_row(player_id, name, position, minutes, xg, xa=0.0, team="Wolves"):
    return (
        f"championship,{player_id},{name},{team},{position},False,6,6,"
        f"{minutes},1.0,{xg},{xa},0.3,0.8,espn_true_per90"
    )


def _write_players(source_root: Path, league: str, files: dict[str, list[str]]) -> None:
    players_dir = source_root / league / "players"
    players_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in files.items():
        (players_dir / name).write_text("\n".join([ESPN_COLUMNS, *rows]) + "\n", encoding="utf-8")


class EspnGoalShrinkReachabilityTests(unittest.TestCase):
    """The test H19 did not have: does the change reach the rows the engine reads?"""

    def _two_season_root(self, tmp_dir: str) -> Path:
        source_root = Path(tmp_dir)
        # 2025 is a completed season: MORE minutes, so its row wins the dedupe.
        # Its xg_per90 is 0.0, which is what prices an appeared player at exactly
        # 0.0 anytime-scorer probability today.
        _write_players(
            source_root,
            "championship",
            {
                "players_2025.csv": [
                    _espn_row("p1", "Survivor Striker", "Center Forward", 2500.0, 0.0),
                    _espn_row("p2", "Busy Forward", "Left Winger", 2000.0, 0.6),
                    _espn_row("p3", "Defender One", "Center Left Defender", 2200.0, 0.05),
                    _espn_row("p4", "Midfielder One", "Center Midfielder", 1800.0, 0.2),
                ],
                # Deliberately thin, so the departed-player filter refuses and the
                # `refused_too_few` return path is the one under test. Every
                # non-empty return path goes through the same finalizer.
                "players_2026.csv": [
                    _espn_row("p1", "Survivor Striker", "Center Forward", 300.0, 0.9),
                ],
            },
        )
        return source_root

    def test_off_differs_from_on_through_the_real_loader(self) -> None:
        module = _load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir:
            source_root = self._two_season_root(tmp_dir)
            with patch.dict(os.environ, {"SYNDICATE_SOCCER_ESPN_GOAL_SHRINK": "off"}):
                off_rows = module._load_player_rows("championship", source_root)
                off_audit = dict(module._PLAYER_LOAD_AUDIT)
            with patch.dict(os.environ, {"SYNDICATE_SOCCER_ESPN_GOAL_SHRINK": "on"}):
                on_rows = module._load_player_rows("championship", source_root)
                on_audit = dict(module._PLAYER_LOAD_AUDIT)

        off_by_id = {row["player_id"]: row for row in off_rows}
        on_by_id = {row["player_id"]: row for row in on_rows}
        self.assertEqual(set(off_by_id), set(on_by_id))
        self.assertTrue(off_by_id, "the loader returned no rows, so nothing was tested")
        changed = [pid for pid in off_by_id if off_by_id[pid]["xg_per90"] != on_by_id[pid]["xg_per90"]]
        self.assertTrue(changed, "off == on: the shrink did not reach any row the engine reads")
        self.assertEqual(off_audit.get("espn_goal_shrink", {}).get("state"), "disabled")
        self.assertEqual(on_audit.get("espn_goal_shrink", {}).get("state"), "applied")

    def test_the_dedupe_survivor_is_the_prior_season_row_and_is_shrunk(self) -> None:
        """The exact case that falsified H19: the row that survives is last
        season's, so a producer-side change to this season's row never lands."""
        module = _load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir:
            source_root = self._two_season_root(tmp_dir)
            with patch.dict(os.environ, {"SYNDICATE_SOCCER_ESPN_GOAL_SHRINK": "off"}):
                off_rows = module._load_player_rows("championship", source_root)
            with patch.dict(os.environ, {"SYNDICATE_SOCCER_ESPN_GOAL_SHRINK": "on"}):
                on_rows = module._load_player_rows("championship", source_root)

        off_p1 = next(row for row in off_rows if row["player_id"] == "p1")
        on_p1 = next(row for row in on_rows if row["player_id"] == "p1")
        # 2,500 minutes beat 300, so the surviving row is the 2025 one, whose
        # own rate is 0.0 -- not the 0.9 of the current-season row.
        self.assertAlmostEqual(float(off_p1["minutes_played"]), 2500.0)
        self.assertAlmostEqual(float(off_p1["xg_per90"]), 0.0)
        self.assertGreater(
            float(on_p1["xg_per90"]), 0.0,
            "the surviving prior-season row still prices at exactly 0.0 goals per 90",
        )

    def test_audit_reports_what_it_did(self) -> None:
        module = _load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir:
            source_root = self._two_season_root(tmp_dir)
            with patch.dict(os.environ, {"SYNDICATE_SOCCER_ESPN_GOAL_SHRINK": "on"}):
                module._load_player_rows("championship", source_root)
                audit = dict(module._PLAYER_LOAD_AUDIT)

        shrink = audit.get("espn_goal_shrink") or {}
        self.assertEqual(shrink.get("state"), "applied")
        self.assertEqual(shrink.get("stabilizer"), 180.0)
        self.assertEqual(shrink.get("rows"), 4)
        self.assertEqual(shrink.get("xg_zero_rows_before"), 1)
        self.assertEqual(shrink.get("xg_zero_rows_after"), 0)
        self.assertEqual(sorted(shrink.get("buckets") or {}), ["D", "F", "M"])


class EspnGoalShrinkMechanicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module(Path(__file__).resolve().parents[1])

    def test_position_buckets_follow_espn_prose(self) -> None:
        bucket = self.module._position_bucket
        self.assertEqual(bucket("Center Left Defender"), "D")
        self.assertEqual(bucket("Left Back"), "D")
        self.assertEqual(bucket("Center Midfielder"), "M")
        self.assertEqual(bucket("Left Winger"), "F")
        self.assertEqual(bucket("Center Forward"), "F")
        self.assertEqual(bucket("Striker"), "F")
        self.assertEqual(bucket("Goalkeeper"), "GK")
        # 100-213 rows per production file say only this, or nothing at all.
        self.assertEqual(bucket("Substitute"), "?")
        self.assertEqual(bucket(""), "?")
        self.assertEqual(bucket(None), "?")

    def test_formula_matches_hand_computation(self) -> None:
        rows = [
            {"source": "espn_true_per90", "position": "Center Forward",
             "minutes_played": "180", "xg_per90": "0.0", "xa_per90": "0.0"},
            {"source": "espn_true_per90", "position": "Striker",
             "minutes_played": "360", "xg_per90": "1.0", "xa_per90": "0.0"},
        ]
        self.module._shrink_espn_goal_rates(rows)
        # prior = (0.0*180 + 1.0*360) / 540 = 2/3
        # row 1: w = 180/(180+180) = 0.5     -> 0.5*0.0 + 0.5*(2/3) = 1/3
        # row 2: w = 360/(360+180) = 2/3     -> (2/3)*1.0 + (1/3)*(2/3) = 8/9
        self.assertAlmostEqual(rows[0]["xg_per90"], 1.0 / 3.0, places=12)
        self.assertAlmostEqual(rows[1]["xg_per90"], 8.0 / 9.0, places=12)

    def test_only_espn_sourced_rows_are_touched(self) -> None:
        rows = [
            {"source": "understat", "position": "F", "minutes": 900.0,
             "xg_per90": 0.0, "xa_per90": 0.0, "goals_per90": 0.0},
            {"source": "espn_true_per90", "position": "Center Forward",
             "minutes_played": 900.0, "xg_per90": 0.4, "xa_per90": 0.1},
        ]
        self.module._shrink_espn_goal_rates(rows)
        self.assertEqual(rows[0]["xg_per90"], 0.0, "an Understat row was modified")
        self.assertEqual(rows[0]["goals_per90"], 0.0)

    def test_goalkeepers_are_excluded(self) -> None:
        rows = [
            {"source": "espn_true_per90", "position": "Goalkeeper",
             "minutes_played": 2700.0, "xg_per90": 0.0, "xa_per90": 0.0},
            {"source": "espn_true_per90", "position": "Center Forward",
             "minutes_played": 900.0, "xg_per90": 0.5, "xa_per90": 0.2},
        ]
        self.module._shrink_espn_goal_rates(rows)
        self.assertEqual(rows[0]["xg_per90"], 0.0, "a goalkeeper was given a striker's prior")

    def test_unknown_position_takes_the_league_prior_not_its_own_bucket(self) -> None:
        rows = [
            {"source": "espn_true_per90", "position": "Substitute",
             "minutes_played": 180.0, "xg_per90": 0.0, "xa_per90": 0.0},
            {"source": "espn_true_per90", "position": "Center Forward",
             "minutes_played": 360.0, "xg_per90": 1.0, "xa_per90": 0.0},
        ]
        self.module._shrink_espn_goal_rates(rows)
        # League prior over both rows = (0.0*180 + 1.0*360)/540 = 2/3; the
        # Substitute row must use THAT, not a prior built from other unknowns
        # (which would be its own 0.0 and leave it at zero).
        self.assertAlmostEqual(rows[0]["xg_per90"], 0.5 * (2.0 / 3.0), places=12)

    def test_shots_are_not_touched(self) -> None:
        rows = [
            {"source": "espn_true_per90", "position": "Center Forward",
             "minutes_played": 300.0, "xg_per90": 0.0, "xa_per90": 0.0, "shots_per90": 2.5},
            {"source": "espn_true_per90", "position": "Striker",
             "minutes_played": 600.0, "xg_per90": 0.8, "xa_per90": 0.1, "shots_per90": 3.1},
        ]
        self.module._shrink_espn_goal_rates(rows)
        self.assertEqual(rows[0]["shots_per90"], 2.5, "the conditional shot ladder owns shots")
        self.assertEqual(rows[1]["shots_per90"], 3.1)

    def test_disabled_leaves_rows_identical(self) -> None:
        rows = [{"source": "espn_true_per90", "position": "Center Forward",
                 "minutes_played": 300.0, "xg_per90": 0.0, "xa_per90": 0.0}]
        with patch.dict(os.environ, {"SYNDICATE_SOCCER_ESPN_GOAL_SHRINK": "0"}):
            self.module._shrink_espn_goal_rates(rows)
        self.assertEqual(rows[0]["xg_per90"], 0.0)
        self.assertEqual(self.module._PLAYER_LOAD_AUDIT.get("espn_goal_shrink", {}).get("state"), "disabled")


class GoalRoleMixtureTests(unittest.TestCase):
    """H17: goals price on the same start/sub mixture as shots.

    The old path asked what a player would score in a FULL match and then priced it
    as though he were certain to play one. Held out, the mixture moved pooled log
    loss 0.2716 -> 0.2673 in 9 of 10 leagues and the level 1.14 -> 0.96.
    """

    def _distribution(self):
        from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary

        return MatchDistributionSummary(
            simulations=1, home_win_probability=0.4, draw_probability=0.3,
            away_win_probability=0.3, mean_home_goals=1.4, mean_away_goals=1.1,
            mean_total=2.5, mean_margin=0.3, over_2_5_probability=0.5,
            both_teams_scored_probability=0.5, scoreline_probabilities={},
            mean_home_shots=12.0, mean_away_shots=10.0,
            mean_home_shots_on_target=4.0, mean_away_shots_on_target=3.0,
        )

    def _profile(self, **overrides):
        from syndicate.features.soccer.sim_engine.soccersim.player_props import PlayerUsageProfile

        base = dict(
            player_id="p1", player_name="Sub Striker", side="home", position="F", team="Wolves",
            expected_minutes_share=0.35, shot_share=0.12, goal_share=0.15, assist_share=0.05,
            start_probability=0.6, on_pitch_shot_share=0.14, on_pitch_goal_share=0.25,
        )
        base.update(overrides)
        return PlayerUsageProfile(**base)

    def _project(self, profile):
        from syndicate.features.soccer.sim_engine.soccersim.player_props import project_player_props

        return project_player_props(self._distribution(), profile)

    def test_role_inputs_change_the_conditional_price(self) -> None:
        """Reachability: the mixture must actually replace the division."""
        with_role = self._project(self._profile())
        without_role = self._project(self._profile(on_pitch_goal_share=None))
        self.assertNotEqual(
            with_role.anytime_scorer_probability_if_playing,
            without_role.anytime_scorer_probability_if_playing,
            "off == on: the goal mixture is not reached",
        )
        self.assertNotEqual(with_role.expected_goals_if_playing, without_role.expected_goals_if_playing)

    def test_mixture_matches_hand_computation(self) -> None:
        import math

        projection = self._project(self._profile())
        full = 1.4 * 0.25
        start_mean = full * 83.1 / 90.0
        sub_mean = 1.8 * full * 15.6 / 90.0
        expected_mean = 0.6 * start_mean + 0.4 * sub_mean
        expected_anytime = 0.6 * (1 - math.exp(-start_mean)) + 0.4 * (1 - math.exp(-sub_mean))
        self.assertAlmostEqual(projection.expected_goals_if_playing, round(expected_mean, 4), places=4)
        self.assertAlmostEqual(projection.anytime_scorer_probability_if_playing, round(expected_anytime, 4), places=4)

    def test_unconditional_fields_are_untouched(self) -> None:
        with_role = self._project(self._profile())
        without_role = self._project(self._profile(on_pitch_goal_share=None))
        self.assertEqual(with_role.expected_goals, without_role.expected_goals)
        self.assertEqual(with_role.anytime_scorer_probability, without_role.anytime_scorer_probability)
        self.assertEqual(with_role.two_or_more_scorer_probability, without_role.two_or_more_scorer_probability)

    def test_assists_keep_the_old_conditioning(self) -> None:
        """H17 measured GOALS. Shipping an unmeasured assist change beside it is how
        a negative interaction gets attributed to the wrong half."""
        with_role = self._project(self._profile())
        without_role = self._project(self._profile(on_pitch_goal_share=None))
        self.assertEqual(with_role.expected_assists_if_playing, without_role.expected_assists_if_playing)
        self.assertAlmostEqual(
            with_role.expected_assists_if_playing,
            round(with_role.expected_assists / max(0.35, 0.25), 4),
            places=4,
        )

    def test_penalty_nudge_stays_on_the_unconditional_mean(self) -> None:
        plain = self._project(self._profile())
        taker = self._project(self._profile(penalty_taker=True))
        self.assertGreater(taker.expected_goals, plain.expected_goals)
        self.assertEqual(taker.expected_goals_if_playing, plain.expected_goals_if_playing)

    def test_build_usage_profiles_populates_on_pitch_goal_share(self) -> None:
        from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles

        rows = [
            {"player_id": "a", "player_name": "Scorer", "position": "F", "team": "Wolves",
             "season": "2026", "games": 6, "minutes": 540.0, "shots_per90": 3.0, "xg_per90": 0.8},
            {"player_id": "b", "player_name": "Defender", "position": "D", "team": "Wolves",
             "season": "2026", "games": 6, "minutes": 540.0, "shots_per90": 0.4, "xg_per90": 0.05},
        ]
        profiles = build_usage_profiles(rows, side="home", team="Wolves")
        shares = {p.player_id: p.on_pitch_goal_share for p in profiles}
        self.assertIsNotNone(shares["a"])
        self.assertIsNotNone(shares["b"])
        self.assertGreater(shares["a"], shares["b"])


if __name__ == "__main__":
    unittest.main()
