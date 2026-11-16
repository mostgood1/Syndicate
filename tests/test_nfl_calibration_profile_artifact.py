"""The NFL calibration profile artifact is exactly todo #808's held-out candidate (lane `nfl-profile-load`).

`load_versioned_profile` silently DROPS any key that is not a `CalibrationProfile` field, and degrades to the
in-source default on any read error. So a typo in `data/calibration/nfl_profile.json` would ship the default
for that field with no error anywhere. These tests make the file's content a pinned fact:

  * every key in `fields` is a real field, with the default's type (a JSON `1` is not `True`);
  * the file loads to the held-out candidate EXACTLY: the seven #808 switches ON, `home_field_bonus` 0.03,
    `touchdown_weight_multiplier` 0.825, every other field at the in-source default;
  * the module constant every NFL sim reads resolves to the file (reachability), unless an env override
    points elsewhere.

A checkout without `data/` (a session worktree opened without `--with-data`) cannot see the file; that case
is skipped, by name. A `data/calibration/` WITHOUT the NFL file fails.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import fields, replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2 import calibration_profile as cp  # noqa: E402
from syndicate.features.shared.calibration_profile_store import load_versioned_profile  # noqa: E402

CALIBRATION_DIR = REPO_ROOT / "data" / "calibration"
ARTIFACT = CALIBRATION_DIR / "nfl_profile.json"
VERSION = "nfl-808-v3h0.03-t0.825"

# The held-out candidate `v3h0.03_t0.825` (findings_2026-11-15_football_end_of_half_fix.md, V3 HELD-OUT RESULTS).
CANDIDATE = {
    "halftime_kickoff": True,
    "q2_urgency_ignores_score": True,
    "end_of_half_clock": True,
    "end_of_half_kneel_out": True,
    "end_of_half_clock_by_need": True,
    "q4_kick_waits": True,
    "kneel_out_q4_only": True,
    "home_field_bonus": 0.03,
    "touchdown_weight_multiplier": 0.825,
}

pytestmark = pytest.mark.skipif(
    not CALIBRATION_DIR.is_dir(), reason="no data/calibration in this checkout (a worktree without --with-data)"
)


def _payload() -> dict:
    assert ARTIFACT.is_file(), f"{ARTIFACT} is missing while data/calibration exists"
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_every_key_is_a_real_field_with_the_defaults_type():
    payload = _payload()
    default = cp.NFL_CALIBRATION_PROFILE_DEFAULT
    real = {f.name for f in fields(default)}
    assert set(payload["fields"]) <= real, set(payload["fields"]) - real
    for key, value in payload["fields"].items():
        assert type(value) is type(getattr(default, key)), (key, value)


def test_the_file_loads_to_the_held_out_candidate_exactly():
    profile, meta = load_versioned_profile(default_profile=cp.NFL_CALIBRATION_PROFILE_DEFAULT, artifact_path=ARTIFACT)
    assert meta["source"] == "artifact" and meta["version"] == VERSION
    assert profile == replace(cp.NFL_CALIBRATION_PROFILE_DEFAULT, **CANDIDATE)
    assert profile.name == "nfl"  # the clock / fourth-down / non-offensive tables are chosen by this name


def test_the_file_changes_those_nine_fields_and_nothing_else():
    payload = _payload()
    assert {k for k in payload["fields"] if k != "name"} == set(CANDIDATE)
    default = cp.NFL_CALIBRATION_PROFILE_DEFAULT
    for key, value in CANDIDATE.items():
        assert getattr(default, key) != value, f"{key} is already {value} in the default: the file would not move it"


@pytest.mark.skipif(
    bool(os.environ.get("SYNDICATE_CALIBRATION_PROFILE_DIR") or os.environ.get("SYNDICATE_CALIBRATION_PROFILE_PATH_NFL")),
    reason="an env override points the NFL profile elsewhere",
)
def test_the_constant_every_nfl_sim_reads_resolves_to_the_file():
    assert cp.NFL_CALIBRATION_PROFILE_METADATA["source"] == "artifact"
    assert Path(cp.NFL_CALIBRATION_PROFILE_METADATA["path"]).resolve() == ARTIFACT.resolve()
    assert cp.NFL_CALIBRATION_PROFILE == replace(cp.NFL_CALIBRATION_PROFILE_DEFAULT, **CANDIDATE)
