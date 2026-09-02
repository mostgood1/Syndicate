"""In-sim position-player substitution is ON by default — `#624` step 3.

Without it the nine listed starters bat all game, every game, so opportunity is
over-projected and every counting prop inherits it. Measured 2026-09-01 against
an actual starter AB of 3.495: OFF 3.880 (+11.0%), ON 3.708 (+6.1%) — 44.7% of
the gap closed. Accuracy on a controlled A/B (same rosters, seeds, odds and
outcomes, one input differing): three of four markets better, rbis marginally
worse, and the market still beats both arms everywhere — a bias correction, not
an edge.

`test_replace_preserves_the_flag` is the one that matters most. The original
defect was that this lived as a `setattr` attribute, and `dataclasses.replace()`
rebuilds from DECLARED FIELDS ONLY — the sim calls `replace(cfg, rng_seed=...)`
on every single run, so the feature was silently discarded before the first
pitch and read as permanently disabled. A default flip is worthless if that
regresses.
"""
from __future__ import annotations

import sys
import unittest
from dataclasses import fields, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "vendor" / "mlb_bettingv2"))

from sim_engine.models import GameConfig  # noqa: E402


class DefaultIsOnTests(unittest.TestCase):
    def test_the_default_is_enabled(self) -> None:
        self.assertTrue(GameConfig().position_substitutions)

    def test_it_is_a_declared_field_not_an_attribute(self) -> None:
        """A `setattr` would survive construction and vanish at the first
        `replace()`, which is exactly how it stayed off for months."""
        names = {f.name for f in fields(GameConfig)}
        self.assertIn("position_substitutions", names)

    def test_replace_preserves_the_flag(self) -> None:
        """The sim reseeds via `replace(cfg, rng_seed=...)` on every run."""
        cfg = GameConfig()
        for seed in (1, 2, 99):
            self.assertTrue(replace(cfg, rng_seed=seed).position_substitutions)

    def test_it_can_still_be_turned_off_explicitly(self) -> None:
        """Off-is-not-on in the other direction: the A/B harnesses
        (`measure_substitution_effect.py`, `reproject_mlb_props_with_subs.py`)
        depend on being able to construct the OFF arm."""
        off = GameConfig(position_substitutions=False)
        self.assertFalse(off.position_substitutions)
        self.assertFalse(replace(off, rng_seed=5).position_substitutions)


class InteractingMechanismsStayOffTests(unittest.TestCase):
    """The measured negative interaction (-0.00331, worse in 4 of 4 markets) was
    substitution AND the batted-ball/pitch-split mechanisms TOGETHER. Enabling
    substitution alone is the safe subset, and this pins that the pair is not
    quietly created later without a fresh measurement."""

    def test_batted_ball_weight_is_still_neutral_by_default(self) -> None:
        import os

        self.assertEqual(
            str(os.environ.get("SYNDICATE_MLB_BATTED_BALL_WEIGHT") or "0.0").strip(),
            "0.0",
            "enabling batted-ball weight alongside substitution recreates the measured "
            "negative interaction; do it only with a fresh A/B",
        )


class ProductionReachabilityTests(unittest.TestCase):
    """Presence is not reachability: a default nothing reads changes nothing."""

    def test_production_does_not_override_the_flag(self) -> None:
        """`daily_update.py` builds `GameConfig(**cfg_kwargs)`. If the flag ever
        appears in that dict, the default stops governing the daily sim and this
        change silently becomes inert."""
        source = (REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "daily_update.py").read_text(
            encoding="utf-8-sig", errors="replace"
        )
        self.assertIn("GameConfig(", source)
        self.assertNotIn("position_substitutions", source,
                         "production now sets this explicitly -- the dataclass default no longer governs")


if __name__ == "__main__":
    unittest.main()
