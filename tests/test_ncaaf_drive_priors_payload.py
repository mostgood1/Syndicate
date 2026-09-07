"""NCAAF must FEED `feature_generation_payload` -- the WIRING, not the builder.

THE DEFECT, from `football_sim_input_checklist`: the NCAAF projection script
built `SmartSim2SimulationInput` with no `feature_generation_payload`, so all
nine blocks `drive_priors.build_drive_priors` reads were neutral on every game.

THE BUILDER WAS NEVER MISSING. `syndicate/features/ncaaf/feature_payload.py`
fills four blocks from the 2026-08-27 snapshots and has done since `#457`. What
`#457` records is that ALL THREE production entrypoints constructed the input
WITHOUT it -- a complete builder sitting behind a flag nothing consulted. So the
missing half was the WIRING, and these tests are about the wiring only. The
builder's own behaviour belongs to its module; re-asserting it here would be a
second copy of the same rule.

(I wrote a duplicate builder before finding that module. It is deleted, not kept
beside the original.)
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

G = importlib.import_module("scripts.generate_smartsim2_ncaaf_projections")
from syndicate.features.ncaaf import feature_payload
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors


class GateTests(unittest.TestCase):
    """A mechanism added to a calibrated engine ships inert until re-fitted."""

    def tearDown(self) -> None:
        os.environ.pop("SYNDICATE_NCAAF_DRIVE_PRIORS", None)

    def test_off_by_default(self) -> None:
        os.environ.pop("SYNDICATE_NCAAF_DRIVE_PRIORS", None)
        self.assertFalse(G._ncaaf_drive_priors_enabled())
        for value in ("", "0", "false", "off", "no", "nonsense"):
            with self.subTest(value=value):
                os.environ["SYNDICATE_NCAAF_DRIVE_PRIORS"] = value
                self.assertFalse(G._ncaaf_drive_priors_enabled())

    def test_turns_on(self) -> None:
        for value in ("1", "true", "on", "YES"):
            with self.subTest(value=value):
                os.environ["SYNDICATE_NCAAF_DRIVE_PRIORS"] = value
                self.assertTrue(G._ncaaf_drive_priors_enabled())


class AdapterTests(unittest.TestCase):
    """The adapter must DELEGATE, never reimplement."""

    def test_it_calls_the_real_builder_with_the_right_arguments(self) -> None:
        seen: dict[str, object] = {}

        def fake(*, home_team, away_team, season):
            seen.update(home_team=home_team, away_team=away_team, season=season)
            return {"returning_production": {"percent_ppa": 0.5}}

        original = feature_payload.build_payload
        try:
            feature_payload.build_payload = fake
            out = G._ncaaf_build_feature_payload(home_team="Oregon", away_team="Baylor", season=2026)
        finally:
            feature_payload.build_payload = original

        self.assertEqual(seen, {"home_team": "Oregon", "away_team": "Baylor", "season": 2026})
        self.assertEqual(out, {"returning_production": {"percent_ppa": 0.5}})

    def test_a_failed_snapshot_read_returns_EMPTY_not_a_half_block(self) -> None:
        """ABSENT MUST STAY ABSENT. A partially-filled block is indistinguishable
        from a working one -- the failure `model_engine_standard.md` exists for."""

        def boom(**_kwargs):
            raise OSError("snapshot unreadable")

        original = feature_payload.build_payload
        try:
            feature_payload.build_payload = boom
            self.assertEqual(
                G._ncaaf_build_feature_payload(home_team="A", away_team="B", season=2026), {}
            )
        finally:
            feature_payload.build_payload = original


class PaceAbsenceTests(unittest.TestCase):
    def test_the_builder_still_documents_why_pace_is_excluded(self) -> None:
        """`[2026-09-07, user decision: "dont enable ncaaf pace"]` -- and the
        module had reached the same conclusion independently, before I did.

        `calibrate_ncaaf_drive_structure.py` measured the ENGINE'S RESPONSE to
        real pace: possessions/game 23.65 truth -> 20.02 at profile v2 -> 17.91
        when fed the true 26.27 league mean; seconds/drive 165.4 -> 185.7 ->
        209.1. Every primary moves FURTHER from truth. Hitting truth through this
        input alone needs ~22.0 s/play, BELOW the hardcoded 24.0 and below any
        real team -- so `pace_seconds_per_play` is not on the scale its name
        implies, and recalibration does not fix that.

        Pinned so a reader who finds only `sources.pace_snapshot_path`'s
        docstring ("every game pinned 18% faster than the average team actually
        plays" -- true of the REAL WORLD, not of the engine) cannot helpfully
        add it back. If pace is ever fed, this test should be rewritten
        deliberately with a drive-structure measurement, not deleted.
        """
        source = Path(feature_payload.__file__).read_text(encoding="utf-8")
        self.assertIn("NULL AT SOURCE", source)
        self.assertIn("pace", source)


class ReachabilityTests(unittest.TestCase):
    """`off != on` must change what the ENGINE computes, not just what we build."""

    def test_a_payload_CHANGES_the_drive_priors(self) -> None:
        payload = {
            "returning_production": {"percent_ppa": 0.85},
            "coach_continuity": {"continuity_score": 0.95},
        }
        inert = build_drive_priors(SmartSim2SimulationInput(home_team="O", away_team="B", seed=1))
        fed = build_drive_priors(SmartSim2SimulationInput(
            home_team="O", away_team="B", seed=1, feature_generation_payload=payload))
        self.assertNotEqual(_fp(inert), _fp(fed),
                            "the payload reached build_drive_priors and changed NOTHING")

    def test_a_STRONGER_input_moves_the_priors_differently_than_a_weaker_one(self) -> None:
        """Direction, not merely difference: a payload that perturbed the priors
        randomly would pass the test above and mean nothing."""
        strong = build_drive_priors(SmartSim2SimulationInput(
            home_team="O", away_team="B", seed=1,
            feature_generation_payload={"returning_production": {"percent_ppa": 0.95}}))
        weak = build_drive_priors(SmartSim2SimulationInput(
            home_team="O", away_team="B", seed=1,
            feature_generation_payload={"returning_production": {"percent_ppa": 0.05}}))
        self.assertNotEqual(_fp(strong), _fp(weak))


def _fp(profile) -> tuple:
    return tuple(
        round(float(v), 9)
        for _k, v in sorted(vars(profile).items())
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    )


if __name__ == "__main__":
    unittest.main()
