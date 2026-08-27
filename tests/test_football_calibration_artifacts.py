"""The NCAAF calibration artifact must actually reach the engine — and NFL must not.

WHY THESE EXIST. Promoting a re-fit is a chain of four things, and three of them
failed silently in the making of this one:

  1. NCAAF's profile was a HARDCODED CONSTANT. `calibration_profile_path("ncaaf")`
     existed and was read by nothing, so an artifact would have been written,
     looked correct, and changed no simulation at all. NFL has resolved through
     `load_versioned_profile` since `#440` Part 4 Phase 5; NCAAF was never wired.

  2. `goal_line_touchdown` was missing from `to_dict()`. `save_versioned_profile`
     serialises `to_dict()` and `profile_with_overrides` reads the same keys back,
     so a candidate opting into the mechanism would have round-tripped to its
     DEFAULT — the whole re-fit inert while appearing to apply.

  3. The mechanism was a GLOBAL env flag. Measured over all four combinations,
     one switch is the wrong shape:

         ncaaf shipped off  15.00%      ncaaf candidate ON   7.24%
         nfl   shipped off   4.22%      nfl   candidate ON   4.18%
         nfl   candidate off             7.42%   <- worse than either

     NCAAF gains ~7.8 points. NFL is ALREADY at its best and the same treatment
     costs it. And the last row is the reason profile and mechanism can never
     ship apart: a re-fitted profile with the mechanism off is worse than the
     profile it replaces.

TRUTH: `docs/reports/ncaaf_historical_truth_report.md`, 53,548 real NCAAF drives.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import (
    NFL_CALIBRATION_PROFILE,
    NFL_CALIBRATION_PROFILE_DEFAULT,
)
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
    NCAAF_CALIBRATION_PROFILE,
    NCAAF_CALIBRATION_PROFILE_DEFAULT,
    NCAAF_CALIBRATION_PROFILE_METADATA,
)
from syndicate.features.shared.calibration_profile_paths import calibration_profile_path
from syndicate.features.shared.calibration_profile_store import (
    load_versioned_profile,
    save_versioned_profile,
)


def test_the_new_field_survives_a_round_trip():
    """DEFECT 2. A field absent from `to_dict()` round-trips to its default,
    so the artifact loads with the mechanism OFF while looking applied."""
    candidate = dataclasses.replace(
        NCAAF_CALIBRATION_PROFILE_DEFAULT, goal_line_touchdown=True, drive_yardage_multiplier=0.95
    )
    assert "goal_line_touchdown" in candidate.to_dict(), "to_dict() drops the field"


def test_a_written_artifact_loads_back_identically(tmp_path):
    candidate = dataclasses.replace(
        NCAAF_CALIBRATION_PROFILE_DEFAULT, goal_line_touchdown=True, drive_yardage_multiplier=0.95
    )
    path = tmp_path / "p.json"
    save_versioned_profile(candidate, artifact_path=path, version="t")
    back, meta = load_versioned_profile(default_profile=NCAAF_CALIBRATION_PROFILE_DEFAULT, artifact_path=path)
    assert meta["source"] == "artifact"
    assert back.goal_line_touchdown is True
    assert back.drive_yardage_multiplier == pytest.approx(0.95)


def test_ncaaf_resolves_through_the_versioned_seam():
    """DEFECT 1. Without this the artifact is read by nothing."""
    assert NCAAF_CALIBRATION_PROFILE_METADATA["source"] in {"artifact", "default"}
    assert "path" in NCAAF_CALIBRATION_PROFILE_METADATA


def test_an_absent_artifact_degrades_to_the_shipped_default(tmp_path):
    """A missing or corrupt artifact must behave exactly as if it never existed."""
    missing, meta = load_versioned_profile(
        default_profile=NCAAF_CALIBRATION_PROFILE_DEFAULT, artifact_path=tmp_path / "nope.json"
    )
    assert missing is NCAAF_CALIBRATION_PROFILE_DEFAULT
    assert meta["source"] == "default"

    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{not json", encoding="utf-8")
    back, meta2 = load_versioned_profile(
        default_profile=NCAAF_CALIBRATION_PROFILE_DEFAULT, artifact_path=corrupt
    )
    assert back is NCAAF_CALIBRATION_PROFILE_DEFAULT
    assert meta2["source"] == "default"


def test_the_promoted_ncaaf_artifact_is_present_and_carries_the_refit():
    """The committed artifact is what reaches Render with the code deploy —
    `data/calibration/` is NOT in HOT_ARTIFACT_PATTERNS, so git is the transport."""
    path = calibration_profile_path("ncaaf")
    assert path.exists(), f"promoted artifact missing at {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = payload["fields"]
    assert fields["goal_line_touchdown"] is True
    assert fields["drive_yardage_multiplier"] == pytest.approx(0.95)
    assert payload["fit_from"]["scored_metrics"], "provenance must record what was optimised"


def test_the_live_ncaaf_profile_differs_from_the_shipped_default():
    """Reachability: the artifact must actually be what the engine holds."""
    assert NCAAF_CALIBRATION_PROFILE is not NCAAF_CALIBRATION_PROFILE_DEFAULT
    assert NCAAF_CALIBRATION_PROFILE.goal_line_touchdown is True
    assert NCAAF_CALIBRATION_PROFILE.drive_yardage_multiplier != NCAAF_CALIBRATION_PROFILE_DEFAULT.drive_yardage_multiplier


def test_NFL_IS_UNTOUCHED():
    """DEFECT 3, and the whole reason the mechanism moved onto the profile.

    NFL measures BEST exactly as it ships (4.22%). A global switch would have
    made it pay for NCAAF's gain.
    """
    assert NFL_CALIBRATION_PROFILE.goal_line_touchdown is False
    assert NFL_CALIBRATION_PROFILE.drive_yardage_multiplier == pytest.approx(1.0)
    assert NFL_CALIBRATION_PROFILE.touchdown_weight_multiplier == pytest.approx(1.0)
    assert NFL_CALIBRATION_PROFILE == NFL_CALIBRATION_PROFILE_DEFAULT


def test_no_impossible_drives_under_the_promoted_profile():
    """The physical invariant the mechanism exists for. 6.60% of drives gained
    more than the field is long before it; the longest reached 249 yards."""
    from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
    from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game

    worst = 0.0
    for i in range(40):
        out = simulate_game(
            SmartSim2SimulationInput(
                home_team="A", away_team="B", seed=5100 + i,
                home_offense_rating=0.0, home_defense_rating=0.0,
                away_offense_rating=0.0, away_defense_rating=0.0,
            ),
            profile=NCAAF_CALIBRATION_PROFILE,
        )
        for drive in out.drive_log or []:
            worst = max(worst, float(drive.get("yards_gained") or 0))
    assert worst <= 100, f"a drive gained {worst} yards; the field is 100 long"


def test_the_env_override_can_only_turn_the_mechanism_ON(monkeypatch):
    """It exists for shadow runs against a profile that has not opted in. It
    must never be able to disable a calibrated engine's own choice."""
    from syndicate.features.football.sim_engine.smartsim2 import play_simulator

    monkeypatch.delenv("SYNDICATE_FOOTBALL_GOAL_LINE_TOUCHDOWN", raising=False)
    assert play_simulator._goal_line_touchdown_enabled(NCAAF_CALIBRATION_PROFILE) is True
    assert play_simulator._goal_line_touchdown_enabled(NFL_CALIBRATION_PROFILE) is False

    monkeypatch.setenv("SYNDICATE_FOOTBALL_GOAL_LINE_TOUCHDOWN", "true")
    assert play_simulator._goal_line_touchdown_enabled(NFL_CALIBRATION_PROFILE) is True, "override must force ON"
    assert play_simulator._goal_line_touchdown_enabled(NCAAF_CALIBRATION_PROFILE) is True, "must not undo a profile's own choice"
