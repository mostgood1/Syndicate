"""`#440` Part 4 Phase 5 — the versioned-profile seam.

TWO HALVES, AND THE SECOND IS THE POINT.

1. **No behaviour change.** With no artifact present, each engine's profile is
   the in-source default — byte-for-byte. Phase 5 is a no-op deploy.
2. **REACHABILITY.** The engines must actually CALL the loader. This is not
   pedantry: `load_versioned_profile` was written, tested, and then called by
   nothing but its own test for its entire life — the plan's words are *"Stage
   3's entire foundation, complete and unreachable."* A Phase 5 that added a call
   site nothing reaches would reproduce the exact defect it exists to fix, and
   half 1 alone cannot tell the difference (a profile that equals its default
   because it IS the default looks identical to one that was never resolved).

Half 2 is tested by reloading each module with the loader patched, which is the
only way to observe an import-time resolution.
"""
from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import calibration_profile_paths as paths
from syndicate.features.shared.calibration_profile_store import load_versioned_profile

FOOTBALL = "syndicate.features.football.sim_engine.smartsim2.calibration_profile"
SOCCER = "syndicate.features.soccer.sim_engine.soccersim.calibration_profile"
NHL = "syndicate.features.nhl.sim_engine.hockeysim.calibration_profile"

ENGINES = (
    (FOOTBALL, "NFL_CALIBRATION_PROFILE"),
    (SOCCER, "SOCCER_CALIBRATION_PROFILE"),
    (NHL, "NHL_CALIBRATION_PROFILE"),
)


class NoBehaviourChange(unittest.TestCase):
    """Half 1: with no artifact, the resolved profile IS the in-source default."""

    def test_each_engine_resolves_to_its_frozen_default(self):
        for module_name, const in ENGINES:
            with self.subTest(engine=module_name.split(".")[2]):
                mod = importlib.import_module(module_name)
                resolved = getattr(mod, const)
                default = getattr(mod, f"{const}_DEFAULT")
                self.assertEqual(resolved, default)
                # IDENTITY, not just equality. The store documents that it
                # returns default_profile ITSELF when the artifact is absent, so
                # a copy here would mean something re-derived the profile.
                self.assertIs(resolved, default)

    def test_metadata_reports_the_default_source(self):
        for module_name, const in ENGINES:
            with self.subTest(engine=module_name.split(".")[2]):
                meta = getattr(importlib.import_module(module_name), f"{const}_METADATA")
                self.assertEqual(meta.get("source"), "default")
                self.assertIn("path", meta)


class Reachability(unittest.TestCase):
    """Half 2: the engines actually reach the loader.

    THE DEFECT THIS EXISTS TO PREVENT: a call site that is present but never
    executed. `load_versioned_profile` had exactly that property before Phase 5.
    """

    def test_every_engine_calls_the_loader_on_import(self):
        # PATCH THE STORE, NOT THE ENGINE MODULE. `importlib.reload` re-executes
        # `from ...calibration_profile_store import load_versioned_profile`,
        # which REBINDS the engine module's attribute back to the real function
        # before the call happens -- so patching the engine attribute is silently
        # undone by the very reload meant to observe it. Patching at the source
        # means the reload imports the spy. (This test failed 3/3 on its first
        # run for exactly that reason, while the wiring was already correct.)
        for module_name, _ in ENGINES:
            with self.subTest(engine=module_name.split(".")[2]):
                mod = importlib.import_module(module_name)
                with patch(
                    "syndicate.features.shared.calibration_profile_store.load_versioned_profile",
                    wraps=load_versioned_profile,
                ) as spy:
                    importlib.reload(mod)
                self.assertGreater(
                    spy.call_count, 0,
                    f"{module_name} does not reach load_versioned_profile -- "
                    "the seam is present but inert, which is the bug Phase 5 fixes",
                )
        # Leave the modules in their normal state for other tests.
        for module_name, _ in ENGINES:
            importlib.reload(importlib.import_module(module_name))

    def test_each_engine_asks_for_its_own_artifact_path(self):
        """A shared path with a per-engine slug, not three ad-hoc conventions."""
        seen = {}
        for module_name, const in ENGINES:
            mod = importlib.import_module(module_name)
            seen[module_name] = Path(getattr(mod, f"{const}_METADATA")["path"]).name
        self.assertEqual(len(set(seen.values())), 3, f"paths collide: {seen}")
        for name in seen.values():
            self.assertTrue(name.endswith("_profile.json"), name)


class ArtifactActuallyOverrides(unittest.TestCase):
    """If the artifact never won, the seam would be decorative."""

    def test_present_artifact_replaces_field_values(self):
        mod = importlib.import_module(SOCCER)
        default = mod.SOCCER_CALIBRATION_PROFILE_DEFAULT
        field = "name"
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "soccer_profile.json"
            art.write_text(json.dumps({"version": "test-1", "fields": {field: "calibrated"}}), encoding="utf-8")
            profile, meta = load_versioned_profile(default_profile=default, artifact_path=art)
        self.assertEqual(getattr(profile, field), "calibrated")
        self.assertEqual(meta["source"], "artifact")
        self.assertEqual(meta["version"], "test-1")
        self.assertEqual(getattr(default, field), "soccer", "the frozen default must not be mutated")

    def test_corrupt_artifact_degrades_to_default_and_does_not_raise(self):
        """A load failure must behave exactly like the artifact never existed --
        a bad file must never take a sim run down."""
        mod = importlib.import_module(NHL)
        default = mod.NHL_CALIBRATION_PROFILE_DEFAULT
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "nhl_profile.json"
            art.write_text("{ this is not json", encoding="utf-8")
            profile, meta = load_versioned_profile(default_profile=default, artifact_path=art)
        self.assertIs(profile, default)
        self.assertEqual(meta["source"], "default")


class PathConvention(unittest.TestCase):
    def test_engine_env_override_wins_over_directory_override(self):
        with patch.dict("os.environ", {
            paths._DIR_ENV: r"C:\dir-level",
            "SYNDICATE_CALIBRATION_PROFILE_PATH_NHL": r"C:\engine-level\x.json",
        }):
            self.assertEqual(paths.calibration_profile_path("nhl"), Path(r"C:\engine-level\x.json"))
            # …and an engine without its own override still follows the directory.
            self.assertEqual(paths.calibration_profile_path("nfl").parent, Path(r"C:\dir-level"))

    def test_blank_engine_is_rejected_rather_than_yielding_a_junk_path(self):
        with self.assertRaises(ValueError):
            paths.calibration_profile_path("   ")


class TheStoreWasNotBent(unittest.TestCase):
    """Phase 5's falsification test, kept as an assertion.

    'If wiring any of the three requires CHANGING calibration_profile_store.py,
    then the store is not the generic seam it was built to be, and Phase 5 should
    stop and re-scope rather than bend the store to fit one engine.'

    Two dataclass shapes go through it unchanged -- football/soccer's
    CalibrationProfile and hockey's SimConfig. This asserts the generic contract
    those rest on, so a future 'small' specialisation of the store fails here.
    """

    def test_store_is_generic_over_unrelated_dataclasses(self):
        football = importlib.import_module(FOOTBALL).NFL_CALIBRATION_PROFILE_DEFAULT
        nhl = importlib.import_module(NHL).NHL_CALIBRATION_PROFILE_DEFAULT
        self.assertIsNot(type(football), type(nhl))
        for default in (football, nhl):
            profile, meta = load_versioned_profile(
                default_profile=default, artifact_path=Path("does-not-exist.json")
            )
            self.assertIs(profile, default)
            self.assertEqual(meta["source"], "default")

    def test_replace_still_produces_an_independent_profile(self):
        nhl = importlib.import_module(NHL).NHL_CALIBRATION_PROFILE_DEFAULT
        bumped = replace(nhl, pp_shots_mult=1.9)
        self.assertEqual(nhl.pp_shots_mult, 1.4, "the frozen baseline must not move")
        self.assertEqual(bumped.pp_shots_mult, 1.9)


if __name__ == "__main__":
    unittest.main()
