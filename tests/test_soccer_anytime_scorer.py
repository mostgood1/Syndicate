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


if __name__ == "__main__":
    unittest.main()
