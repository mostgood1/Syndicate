"""NCAAF must FEED `feature_generation_payload` -- and map the key that doesn't match.

THE DEFECT, from `football_sim_input_checklist`: the NCAAF projection script
built `SmartSim2SimulationInput` with no `feature_generation_payload`, so all
nine blocks `drive_priors.build_drive_priors` reads were at their neutral default
on every game.

WHAT MAKES NCAAF WORSE THAN NFL. Three snapshots were already being BUILT and
read by nothing: `pace_snapshot_path()`, `returning_production_snapshot_path()`
and `coach_continuity_snapshot_path()` all have producers
(`build_ncaaf_*_snapshot.py`, `cfbd.py`) and no consumer outside those producers.
Three producers, zero consumers.

And the cost was already measured, in `pace_snapshot_path`'s own docstring: with
no pace block `_pace_index` falls back to **24.0 s/play**, so EVERY NCAAF game
ran at `pace_index = +0.400` against a real 2025 league mean of 26.56 (sd 2.08,
266 teams / 37,263 drives). A constant is not a neutral default -- it pinned
every game 18% faster than the average team plays.

THE TEST THAT MATTERS MOST HERE IS THE KEY-MAPPING ONE. The pace snapshot writes
`seconds_per_play`; `_pace_index` reads `["pace_seconds_per_play",
"secs_per_play", "home_pace_secs_play", "away_pace_secs_play"]`. `seconds_per_play`
is in NEITHER list. Passing the snapshot straight through would look wired, read
as fed, and change nothing -- the same silent no-op the alarm exists to remove,
one layer down. `percent_ppa` and `continuity_score` DO match, which is exactly
what makes the pace mismatch easy to miss.

Snapshots are written to a tmp dir and the path helpers monkeypatched, so nothing
here depends on `data/**` -- a lossy mirror that says nothing about production.
"""
from __future__ import annotations

import csv
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

G = importlib.import_module("scripts.generate_smartsim2_ncaaf_projections")
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


class _Snapshots(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pace = root / "pace.csv"
        self.ret = root / "ret.csv"
        self.coach = root / "coach.csv"
        # Oregon plays FAST (20.0 s/play), Baylor SLOW (31.0) -- both far from the
        # 24.0 constant the engine falls back to, so a wired payload cannot be
        # mistaken for the default.
        _write(self.pace, [
            {"team": "Oregon", "season": 2026, "seconds_per_play": 20.0},
            {"team": "Baylor", "season": 2026, "seconds_per_play": 31.0},
        ])
        _write(self.ret, [
            {"team_name": "Oregon", "season": 2026, "percent_ppa": 0.82},
            {"team_name": "Baylor", "season": 2026, "percent_ppa": 0.31},
        ])
        _write(self.coach, [
            {"team_name": "Oregon", "season": 2026, "continuity_score": 0.95},
            {"team_name": "Baylor", "season": 2026, "continuity_score": 0.20},
        ])
        import syndicate.features.ncaaf.sources as S
        self._orig = (S.pace_snapshot_path, S.returning_production_snapshot_path,
                      S.coach_continuity_snapshot_path)
        S.pace_snapshot_path = lambda: self.pace
        S.returning_production_snapshot_path = lambda: self.ret
        S.coach_continuity_snapshot_path = lambda: self.coach
        G._NCAAF_FEATURE_SNAPSHOT_CACHE.clear()

    def tearDown(self) -> None:
        import syndicate.features.ncaaf.sources as S
        (S.pace_snapshot_path, S.returning_production_snapshot_path,
         S.coach_continuity_snapshot_path) = self._orig
        G._NCAAF_FEATURE_SNAPSHOT_CACHE.clear()
        os.environ.pop("SYNDICATE_NCAAF_DRIVE_PRIORS", None)
        self.tmp.cleanup()


class GateTests(_Snapshots):
    def test_off_by_default(self) -> None:
        for value in ("", "0", "false", "off", "nonsense"):
            with self.subTest(value=value):
                os.environ["SYNDICATE_NCAAF_DRIVE_PRIORS"] = value
                self.assertFalse(G._ncaaf_drive_priors_enabled())
        os.environ.pop("SYNDICATE_NCAAF_DRIVE_PRIORS", None)
        self.assertFalse(G._ncaaf_drive_priors_enabled())

    def test_turns_on(self) -> None:
        for value in ("1", "true", "on", "YES"):
            with self.subTest(value=value):
                os.environ["SYNDICATE_NCAAF_DRIVE_PRIORS"] = value
                self.assertTrue(G._ncaaf_drive_priors_enabled())


class KeyMappingTests(_Snapshots):
    """The whole point. Right numbers under the wrong names change nothing."""

    def test_pace_is_REMAPPED_to_a_key_the_engine_actually_reads(self) -> None:
        payload = G.build_ncaaf_feature_generation_payload("Oregon", "Baylor")
        pace = payload["pace"]
        # The snapshot's own column name must NOT be what we publish...
        self.assertNotIn("seconds_per_play", pace)
        # ...because `_pace_index` reads these, and only these.
        self.assertIn("pace_seconds_per_play", pace)
        self.assertEqual(pace["pace_seconds_per_play"], 20.0)
        self.assertEqual(pace["away_pace_secs_play"], 31.0)

    def test_the_pass_through_keys_keep_their_snapshot_names(self) -> None:
        payload = G.build_ncaaf_feature_generation_payload("Oregon", "Baylor")
        self.assertEqual(payload["returning_production"]["percent_ppa"], 0.82)
        self.assertEqual(payload["coach_continuity"]["continuity_score"], 0.95)

    def test_bare_keys_are_HOME_framed(self) -> None:
        home_first = G.build_ncaaf_feature_generation_payload("Oregon", "Baylor")
        G._NCAAF_FEATURE_SNAPSHOT_CACHE.clear()
        away_first = G.build_ncaaf_feature_generation_payload("Baylor", "Oregon")
        self.assertEqual(home_first["pace"]["pace_seconds_per_play"], 20.0)
        self.assertEqual(away_first["pace"]["pace_seconds_per_play"], 31.0)

    def test_absent_snapshots_return_EMPTY_not_zeros(self) -> None:
        """A block of zeros reads as 'measured, and average'."""
        import syndicate.features.ncaaf.sources as S
        S.pace_snapshot_path = lambda: Path(self.tmp.name) / "nope.csv"
        S.returning_production_snapshot_path = lambda: Path(self.tmp.name) / "nope2.csv"
        S.coach_continuity_snapshot_path = lambda: Path(self.tmp.name) / "nope3.csv"
        G._NCAAF_FEATURE_SNAPSHOT_CACHE.clear()
        self.assertEqual(G.build_ncaaf_feature_generation_payload("Oregon", "Baylor"), {})

    def test_an_unknown_team_is_absent_not_defaulted(self) -> None:
        payload = G.build_ncaaf_feature_generation_payload("Nowhere State", "Oregon")
        # Home is unknown, so the HOME-framed bare key must not exist.
        self.assertNotIn("pace_seconds_per_play", payload.get("pace", {}))
        self.assertEqual(payload["pace"]["away_pace_secs_play"], 20.0)


class ReachabilityTests(_Snapshots):
    def test_the_payload_CHANGES_what_the_engine_computes(self) -> None:
        payload = G.build_ncaaf_feature_generation_payload("Oregon", "Baylor")
        self.assertTrue(payload, "no payload built; the rest would be vacuous")
        inert = build_drive_priors(SmartSim2SimulationInput(home_team="O", away_team="B", seed=1))
        fed = build_drive_priors(SmartSim2SimulationInput(
            home_team="O", away_team="B", seed=1, feature_generation_payload=payload))
        self.assertNotEqual(_fp(inert), _fp(fed),
                            "payload reached build_drive_priors and changed NOTHING")

    def test_real_pace_moves_the_index_OFF_the_24_second_constant(self) -> None:
        """The measured defect, pinned: 24.0 s/play -> pace_index +0.400 on every
        game. A 20.0 s/play team and a 31.0 s/play team must not share it."""
        fast = build_drive_priors(SmartSim2SimulationInput(
            home_team="O", away_team="B", seed=1,
            feature_generation_payload={"pace": {"pace_seconds_per_play": 20.0}}))
        slow = build_drive_priors(SmartSim2SimulationInput(
            home_team="O", away_team="B", seed=1,
            feature_generation_payload={"pace": {"pace_seconds_per_play": 31.0}}))
        default = build_drive_priors(SmartSim2SimulationInput(home_team="O", away_team="B", seed=1))
        self.assertNotEqual(_fp(fast), _fp(slow))
        self.assertNotEqual(_fp(fast), _fp(default))
        self.assertNotEqual(_fp(slow), _fp(default))


def _fp(profile) -> tuple:
    return tuple(
        round(float(v), 9)
        for _k, v in sorted(vars(profile).items())
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    )


if __name__ == "__main__":
    unittest.main()
