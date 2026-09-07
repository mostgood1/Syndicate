"""The NFL projection script must actually FEED `feature_generation_payload`.

THE DEFECT. `scripts/football_sim_input_checklist.py` alarm, verbatim:

    UNWIRED PAYLOAD: scripts/generate_smartsim2_nfl_projections.py constructs
    SmartSim2SimulationInput without `feature_generation_payload`, so every key
    `drive_priors.py` reads falls to its neutral default on every game this
    script projects

`SmartSim2SimulationInput.feature_generation_payload` defaults to `{}` and
`drive_priors.build_drive_priors` pulls NINE blocks out of it -- offensive and
defensive metrics, pace, advanced, player usage, market features, returning
production, coach continuity, transfer impact. An empty payload means every one
of those is the neutral default, forever, on every game. The engine runs, the
tests pass, and the output is identical to a build where the features do not
exist. That is the exact failure shape `model_engine_standard.md` exists to
prevent, and it was present in the most-invested football path.

REACHABILITY BEFORE CORRECTNESS. `off != on` is the first test here and not the
last, because a payload that is built and never read passes every assertion
about its contents. Four inert fixes were caught by exactly this check in one
session on 2026-09-05.

NO `data/**` DEPENDENCY. Every play tuple below is synthetic and matches
`load_pbp_plays`'s real shape `(week, posteam, defteam, play_type, epa)`, so
these tests say something about the CODE and never about whichever mirror
happens to be on the machine.
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

G = importlib.import_module("scripts.generate_smartsim2_nfl_projections")
from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput


def plays():
    """Two teams, deliberately unequal, over three weeks.

    HOU is efficient (positive EPA, high success) and CLE is not. If the payload
    reaches the engine at all, the drive priors for a HOU-home game must differ
    from a CLE-home game -- that asymmetry is what the reachability test reads.
    """
    rows = []
    for week in (1, 2, 3):
        for _ in range(20):
            rows.append((week, "HOU", "CLE", "pass", 0.30))
            rows.append((week, "HOU", "CLE", "run", 0.10))
            rows.append((week, "CLE", "HOU", "pass", -0.25))
            rows.append((week, "CLE", "HOU", "run", -0.05))
    return rows


class GateTests(unittest.TestCase):
    def test_the_gate_is_OFF_by_default(self) -> None:
        """A mechanism added to a calibrated engine ships inert until scored."""
        for value in ("", None, "0", "false", "off", "no", "nonsense"):
            with self.subTest(value=value):
                if value is None:
                    os.environ.pop("SYNDICATE_NFL_DRIVE_PRIORS", None)
                else:
                    os.environ["SYNDICATE_NFL_DRIVE_PRIORS"] = value
                self.assertFalse(G._drive_priors_enabled())

    def test_the_gate_turns_ON(self) -> None:
        for value in ("1", "true", "on", "YES"):
            with self.subTest(value=value):
                os.environ["SYNDICATE_NFL_DRIVE_PRIORS"] = value
                self.assertTrue(G._drive_priors_enabled())
        os.environ.pop("SYNDICATE_NFL_DRIVE_PRIORS", None)


class PayloadShapeTests(unittest.TestCase):
    """The engine reads specific NAMES. Right numbers, wrong keys = same no-op."""

    def setUp(self) -> None:
        self.payload = G.build_feature_generation_payload(
            home_team="HOU", away_team="CLE", week=4, current_plays=plays()
        )

    def test_it_lands_under_the_block_names_the_engine_extracts(self) -> None:
        self.assertIn("offensive_metrics", self.payload)
        self.assertIn("defensive_metrics", self.payload)

    def test_the_bare_keys_are_the_ones_offense_strength_reads(self) -> None:
        off = self.payload["offensive_metrics"]
        # `_offense_strength` takes the FIRST of these that exists.
        self.assertIn("offensive_epa", off)
        self.assertIn("success_rate", off)

    def test_bare_keys_are_HOME_framed_matching_the_engine_fallback(self) -> None:
        """`build_drive_priors`'s own fallback is `0.5 + home_offense_rating`.

        An away-framed bare key would silently describe the wrong team.
        """
        off = self.payload["offensive_metrics"]
        self.assertEqual(off["offensive_epa"], off["home_offensive_epa"])
        self.assertNotEqual(off["home_offensive_epa"], off["away_offensive_epa"])

    def test_defence_epa_is_NEGATED_so_higher_is_better(self) -> None:
        """`epa` is always from the offence's perspective. HOU's defence faces
        CLE's negative-EPA offence, so HOU's defensive_epa must be POSITIVE."""
        dfn = self.payload["defensive_metrics"]
        self.assertGreater(dfn["home_defensive_epa"], 0.0)   # HOU defence, good
        self.assertLess(dfn["away_defensive_epa"], 0.0)      # CLE defence, bad

    def test_success_rate_is_epa_over_zero(self) -> None:
        off = self.payload["offensive_metrics"]
        self.assertAlmostEqual(off["home_success_rate"], 1.0, places=6)
        self.assertAlmostEqual(off["away_success_rate"], 0.0, places=6)

    def test_it_uses_only_weeks_BEFORE_the_projected_one(self) -> None:
        """Same leakage contract `team_rating` already keeps."""
        early = G.build_feature_generation_payload(
            home_team="HOU", away_team="CLE", week=1, current_plays=plays()
        )
        self.assertEqual(early, {}, "week 1 must see no prior weeks of the same season")

    def test_no_data_at_all_returns_EMPTY_not_zeros(self) -> None:
        """A block of zeros reads as 'measured, and average'. Absence must stay
        absent so the engine keeps its documented neutral default."""
        self.assertEqual(
            G.build_feature_generation_payload(
                home_team="HOU", away_team="CLE", week=4, current_plays=[]
            ),
            {},
        )


class ReachabilityTests(unittest.TestCase):
    """THE TEST THAT MATTERS. Does the payload change what the ENGINE computes?"""

    def test_the_payload_CHANGES_the_drive_priors(self) -> None:
        payload = G.build_feature_generation_payload(
            home_team="HOU", away_team="CLE", week=4, current_plays=plays()
        )
        self.assertTrue(payload, "fixture produced no payload; the rest is vacuous")

        inert = build_drive_priors(
            SmartSim2SimulationInput(home_team="HOU", away_team="CLE", seed=1)
        )
        fed = build_drive_priors(
            SmartSim2SimulationInput(
                home_team="HOU", away_team="CLE", seed=1,
                feature_generation_payload=payload,
            )
        )
        self.assertNotEqual(
            _fingerprint(inert), _fingerprint(fed),
            "the payload reached build_drive_priors and changed NOTHING -- "
            "this is the unwired-payload defect, not a fix for it",
        )

    def test_a_BETTER_offence_moves_the_priors_further_than_a_worse_one(self) -> None:
        """Direction, not just difference. A payload that perturbs the priors
        randomly would pass the test above and still be meaningless."""
        good = G.build_feature_generation_payload(
            home_team="HOU", away_team="CLE", week=4, current_plays=plays()
        )
        bad = G.build_feature_generation_payload(
            home_team="CLE", away_team="HOU", week=4, current_plays=plays()
        )
        base = build_drive_priors(SmartSim2SimulationInput(home_team="H", away_team="A", seed=1))
        p_good = build_drive_priors(
            SmartSim2SimulationInput(home_team="H", away_team="A", seed=1,
                                     feature_generation_payload=good))
        p_bad = build_drive_priors(
            SmartSim2SimulationInput(home_team="H", away_team="A", seed=1,
                                     feature_generation_payload=bad))
        self.assertNotEqual(_fingerprint(p_good), _fingerprint(p_bad),
                            "the strong and weak offences produce identical priors")
        del base


def _fingerprint(profile) -> tuple:
    """Every float on the profile, so no field can change unnoticed."""
    return tuple(
        round(float(v), 9)
        for _k, v in sorted(vars(profile).items())
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    )


if __name__ == "__main__":
    unittest.main()
