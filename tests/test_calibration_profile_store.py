"""Tests for syndicate.features.shared.calibration_profile_store -- the
generic versioned-artifact load/save for sim-engine CalibrationProfiles.
Verified against the REAL football CalibrationProfile dataclass (not just
a synthetic stand-in), since the whole point is genericity over whatever
dataclass shape a given engine's profile happens to have."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import CalibrationProfile
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.shared.calibration_profile_store import load_versioned_profile
from syndicate.features.shared.calibration_profile_store import profile_with_overrides
from syndicate.features.shared.calibration_profile_store import save_versioned_profile


@dataclass(frozen=True)
class _FakeProfile:
    name: str
    multiplier: float = 1.0
    base: float = 0.5

    def to_dict(self) -> dict:
        return {"name": self.name, "multiplier": self.multiplier, "base": self.base}


class ProfileWithOverridesTests(unittest.TestCase):
    def test_applies_known_fields_only(self) -> None:
        result = profile_with_overrides(_FakeProfile(name="x"), {"multiplier": 2.0, "unknown_field": 999})
        self.assertEqual(result.multiplier, 2.0)
        self.assertEqual(result.base, 0.5)  # untouched
        self.assertFalse(hasattr(result, "unknown_field"))

    def test_empty_overrides_returns_same_instance(self) -> None:
        default = _FakeProfile(name="x")
        result = profile_with_overrides(default, {})
        self.assertIs(result, default)

    def test_real_football_profile_accepts_overrides(self) -> None:
        overridden = profile_with_overrides(NFL_CALIBRATION_PROFILE, {"explosive_play_multiplier": 1.15, "field_goal_make_base": 0.95})
        self.assertEqual(overridden.explosive_play_multiplier, 1.15)
        self.assertEqual(overridden.field_goal_make_base, 0.95)
        # every other field stays exactly the frozen default
        self.assertEqual(overridden.drive_yardage_multiplier, NFL_CALIBRATION_PROFILE.drive_yardage_multiplier)
        self.assertEqual(overridden.name, NFL_CALIBRATION_PROFILE.name)

    def test_original_default_is_never_mutated(self) -> None:
        profile_with_overrides(NFL_CALIBRATION_PROFILE, {"explosive_play_multiplier": 99.0})
        self.assertEqual(NFL_CALIBRATION_PROFILE.explosive_play_multiplier, 1.0)


class LoadVersionedProfileTests(unittest.TestCase):
    def test_missing_artifact_returns_default_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "does_not_exist.json"
            profile, metadata = load_versioned_profile(default_profile=NFL_CALIBRATION_PROFILE, artifact_path=path)
            self.assertIs(profile, NFL_CALIBRATION_PROFILE)
            self.assertEqual(metadata["source"], "default")

    def test_valid_artifact_overrides_fields_and_reports_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "nfl.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "2026-08-04-v1",
                        "generated_at": "2026-08-04T00:00:00Z",
                        "fit_from": {"window_days": 30, "n_games": 128},
                        "fields": {"explosive_play_multiplier": 1.08, "touchdown_weight_multiplier": 0.95},
                    }
                ),
                encoding="utf-8",
            )
            profile, metadata = load_versioned_profile(default_profile=NFL_CALIBRATION_PROFILE, artifact_path=path)
            self.assertEqual(profile.explosive_play_multiplier, 1.08)
            self.assertEqual(profile.touchdown_weight_multiplier, 0.95)
            self.assertEqual(profile.field_goal_make_base, NFL_CALIBRATION_PROFILE.field_goal_make_base)
            self.assertEqual(metadata["source"], "artifact")
            self.assertEqual(metadata["version"], "2026-08-04-v1")
            self.assertEqual(metadata["fit_from"], {"window_days": 30, "n_games": 128})

    def test_corrupt_json_degrades_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "bad.json"
            path.write_text("{not valid json", encoding="utf-8")
            profile, metadata = load_versioned_profile(default_profile=NFL_CALIBRATION_PROFILE, artifact_path=path)
            self.assertIs(profile, NFL_CALIBRATION_PROFILE)
            self.assertEqual(metadata["source"], "default")

    def test_artifact_without_fields_key_degrades_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "shapeless.json"
            path.write_text(json.dumps({"version": "v1"}), encoding="utf-8")
            profile, metadata = load_versioned_profile(default_profile=NFL_CALIBRATION_PROFILE, artifact_path=path)
            self.assertIs(profile, NFL_CALIBRATION_PROFILE)

    def test_non_dict_json_degrades_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "array.json"
            path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            profile, metadata = load_versioned_profile(default_profile=NFL_CALIBRATION_PROFILE, artifact_path=path)
            self.assertIs(profile, NFL_CALIBRATION_PROFILE)


class SaveVersionedProfileTests(unittest.TestCase):
    def test_round_trips_through_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "profiles" / "nfl.json"
            candidate = profile_with_overrides(NFL_CALIBRATION_PROFILE, {"explosive_play_multiplier": 1.2, "drive_yardage_multiplier": 0.93})
            save_versioned_profile(candidate, artifact_path=path, version="test-v1", fit_from={"n_games": 50})

            loaded_profile, metadata = load_versioned_profile(default_profile=NFL_CALIBRATION_PROFILE, artifact_path=path)
            self.assertEqual(loaded_profile.explosive_play_multiplier, 1.2)
            self.assertEqual(loaded_profile.drive_yardage_multiplier, 0.93)
            self.assertEqual(loaded_profile.to_dict(), candidate.to_dict())
            self.assertEqual(metadata["version"], "test-v1")

    def test_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "a" / "b" / "c" / "profile.json"
            save_versioned_profile(NFL_CALIBRATION_PROFILE, artifact_path=path, version="v1")
            self.assertTrue(path.exists())

    def test_profile_without_to_dict_raises_immediately(self) -> None:
        class NoToDict:
            pass

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "x.json"
            with self.assertRaises(TypeError):
                save_versioned_profile(NoToDict(), artifact_path=path, version="v1")


if __name__ == "__main__":
    unittest.main()
