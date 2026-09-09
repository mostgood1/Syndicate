"""S4a -- the NCAAF drive-structure fit, its flag, and the harness that measured it.

The reachability test comes FIRST here on purpose. A profile variant behind an
env flag is exactly the shape that ships inert: the code is present, the tests
pass, and the simulation never sees it. `off != on` is what distinguishes a
reachable variant from a decorative one, and it is asserted before anything
about whether the variant's numbers are good.
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import CalibrationProfile
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
    NCAAF_CALIBRATION_PROFILE,
    NCAAF_CALIBRATION_PROFILE_DEFAULT,
    NCAAF_DRIVE_PROFILE_ACTIVE,
    NCAAF_DRIVE_PROFILE_ENV,
    NCAAF_DRIVE_PROFILE_VARIANTS,
    NCAAF_DRIVE_PROFILE_VARIANT_BASE_VERSION,
    NCAAF_DRIVE_PROFILE_VARIANT_OVERRIDES,
    resolve_ncaaf_drive_profile,
)
from syndicate.features.shared.calibration_profile_paths import calibration_profile_path
from syndicate.features.shared.calibration_profile_store import load_versioned_profile

VARIANT = "s4a_drive_fit_v1"


def _fingerprint(profile: CalibrationProfile, *, games: int = 6, seed0: int = 9001) -> str:
    """A fixed-seed run of the engine, serialised. Equal strings == equal simulation."""
    out = []
    for index in range(games):
        result = simulate_game(
            SmartSim2SimulationInput(
                home_team="A", away_team="B", seed=seed0 + index,
                home_offense_rating=0.0, home_defense_rating=0.0,
                away_offense_rating=0.0, away_defense_rating=0.0,
            ),
            profile=profile,
        )
        out.append({
            "final_score": result.final_score,
            "quarters": [dict(entry) for entry in result.quarter_log],
            "drives": [
                {
                    "outcome": drive.get("outcome"),
                    "play_count": drive.get("play_count"),
                    "yards_gained": drive.get("yards_gained"),
                    "clock_consumed": drive.get("clock_consumed"),
                    "points_scored": drive.get("points_scored"),
                }
                for drive in result.drive_log
            ],
        })
    return json.dumps(out, sort_keys=True)


# ---------------------------------------------------------------------------
# REACHABILITY -- before correctness, per the model-engine standard.
# ---------------------------------------------------------------------------

def test_variant_is_registered_and_carries_overrides():
    assert VARIANT in NCAAF_DRIVE_PROFILE_VARIANTS
    assert NCAAF_DRIVE_PROFILE_VARIANT_OVERRIDES[VARIANT], "an empty override set is an inert variant"


def test_off_is_not_on():
    """The variant must CHANGE the simulation. This is the whole reachability check."""
    shipped, name = resolve_ncaaf_drive_profile(NCAAF_CALIBRATION_PROFILE, None)
    variant, variant_name = resolve_ncaaf_drive_profile(NCAAF_CALIBRATION_PROFILE, VARIANT)
    assert name == "shipped" and variant_name == VARIANT
    assert variant != shipped
    assert _fingerprint(variant) != _fingerprint(shipped)


def test_every_override_names_a_real_profile_field():
    """A typo'd key would be silently accepted by nothing -- `replace` raises -- but
    this says so at the registry, not at the first run that happens to resolve it."""
    known = {item.name for item in dataclasses.fields(CalibrationProfile)}
    for name, overrides in NCAAF_DRIVE_PROFILE_VARIANT_OVERRIDES.items():
        unknown = set(overrides) - known
        assert not unknown, f"variant {name} sets unknown fields {sorted(unknown)}"


# ---------------------------------------------------------------------------
# ABSENT MEANS TODAY'S PROFILE, EXACTLY
# ---------------------------------------------------------------------------

def test_flag_absent_resolves_to_the_versioned_profile_object_itself():
    resolved, name = resolve_ncaaf_drive_profile(NCAAF_CALIBRATION_PROFILE, None)
    assert name == "shipped"
    assert resolved is NCAAF_CALIBRATION_PROFILE


def test_flag_absent_reproduces_the_pre_change_profile_byte_for_byte():
    """The reference is rebuilt the way the module built it BEFORE the variant seam:
    the versioned loader over the default profile. Nothing about the flag may change it."""
    pre_change, _ = load_versioned_profile(
        default_profile=NCAAF_CALIBRATION_PROFILE_DEFAULT,
        artifact_path=calibration_profile_path("ncaaf"),
    )
    assert NCAAF_CALIBRATION_PROFILE == pre_change
    assert _fingerprint(NCAAF_CALIBRATION_PROFILE) == _fingerprint(pre_change)


def test_this_process_is_running_the_shipped_profile():
    assert NCAAF_DRIVE_PROFILE_ACTIVE == "shipped"
    assert not os.environ.get(NCAAF_DRIVE_PROFILE_ENV)


# ---------------------------------------------------------------------------
# THE EXACT ENV VALUES, AND WHAT AN UNKNOWN ONE DOES
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [None, "", "  ", "default", "shipped", "off", "none", "OFF", "Shipped"])
def test_documented_shipped_aliases_select_the_shipped_profile(raw):
    resolved, name = resolve_ncaaf_drive_profile(NCAAF_CALIBRATION_PROFILE, raw)
    assert (resolved, name) == (NCAAF_CALIBRATION_PROFILE, "shipped")


@pytest.mark.parametrize("raw", [VARIANT, VARIANT.upper(), f"  {VARIANT}  "])
def test_documented_variant_values_select_the_variant(raw):
    resolved, name = resolve_ncaaf_drive_profile(NCAAF_CALIBRATION_PROFILE, raw)
    assert name == VARIANT
    assert resolved != NCAAF_CALIBRATION_PROFILE


@pytest.mark.parametrize("raw", ["s4a", "drive_fit", "s4a_drive_fit_v2", "on", "1", "true"])
def test_an_unknown_value_raises_rather_than_falling_back(raw):
    """UNKNOWN MUST NOT DEFAULT PERMISSIVE. Silently serving the shipped profile
    for a typo'd variant makes a measurement of production look like a
    measurement of the candidate."""
    with pytest.raises(ValueError) as excinfo:
        resolve_ncaaf_drive_profile(NCAAF_CALIBRATION_PROFILE, raw)
    assert VARIANT in str(excinfo.value)


_PROBE = (
    "from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import ("
    "    NCAAF_CALIBRATION_PROFILE as P, NCAAF_DRIVE_PROFILE_ACTIVE as A,"
    "    NCAAF_CALIBRATION_PROFILE_METADATA as M)\n"
    "print('ACTIVE=' + A + ' SRC=' + str(M.get('source')) + ' FGPEN=' + repr(P.field_goal_make_distance_penalty)"
    " + ' FGAB=' + repr(P.field_goal_attempt_base_probability))\n"
)


@pytest.fixture
def base_version_artifact(tmp_path):
    """A calibration directory whose ncaaf artifact reports the version the variant
    was fitted against.

    Built here rather than read from `data/calibration/`: a session worktree
    excludes `data/` entirely, so a test that depends on it passes or fails for
    reasons that have nothing to do with the code under test.
    """
    from syndicate.features.shared.calibration_profile_store import save_versioned_profile

    profile = dataclasses.replace(
        NCAAF_CALIBRATION_PROFILE_DEFAULT, goal_line_touchdown=True, drive_yardage_multiplier=0.95
    )
    directory = tmp_path / "calibration"
    directory.mkdir()
    save_versioned_profile(
        profile,
        artifact_path=directory / "ncaaf_profile.json",
        version="ncaaf-goal-line-refit-1",
    )
    return directory


def _probe(directory, value: str | None):
    env = dict(os.environ)
    env.pop(NCAAF_DRIVE_PROFILE_ENV, None)
    if value is not None:
        env[NCAAF_DRIVE_PROFILE_ENV] = value
    env["SYNDICATE_CALIBRATION_PROFILE_DIR"] = str(directory)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, cwd=str(REPO_ROOT), env=env, timeout=180,
    )


def test_the_env_var_actually_reaches_the_module_constant(base_version_artifact):
    """PRESENCE IS NOT REACHABILITY. `resolve_...` being correct says nothing about
    whether the module CALLS it, and the call happens at import -- so this has to
    be a fresh interpreter."""
    absent = _probe(base_version_artifact, None)
    on = _probe(base_version_artifact, VARIANT)
    assert absent.returncode == 0, absent.stderr
    assert on.returncode == 0, on.stderr

    def _line(completed):
        return [line for line in completed.stdout.splitlines() if line.startswith("ACTIVE=")][0]

    assert "ACTIVE=shipped" in _line(absent)
    assert f"ACTIVE={VARIANT}" in _line(on)
    assert _line(absent) != _line(on), "the env var did not reach the module-level profile"


def test_an_unknown_env_value_fails_the_import_loudly(base_version_artifact):
    completed = _probe(base_version_artifact, "s4a_typo")
    assert completed.returncode != 0
    assert "s4a_typo" in completed.stderr


def test_the_variant_refuses_a_base_it_was_not_fitted_against():
    """A DELTA APPLIED TO THE WRONG BASE IS A PROFILE NOBODY MEASURED.

    This is the failure that actually happened while fitting: `data/` is excluded
    from a session worktree, `load_versioned_profile` falls back to the in-source
    default without raising (correctly -- an absent artifact is its normal case),
    and a full sweep ran against a profile production had not used since
    2026-08-27.
    """
    with pytest.raises(ValueError) as excinfo:
        resolve_ncaaf_drive_profile(NCAAF_CALIBRATION_PROFILE, VARIANT, base_version="")
    assert NCAAF_DRIVE_PROFILE_VARIANT_BASE_VERSION in str(excinfo.value)

    resolved, name = resolve_ncaaf_drive_profile(
        NCAAF_CALIBRATION_PROFILE, VARIANT, base_version=NCAAF_DRIVE_PROFILE_VARIANT_BASE_VERSION
    )
    assert name == VARIANT and resolved != NCAAF_CALIBRATION_PROFILE


def test_a_base_version_mismatch_never_blocks_the_shipped_path():
    """The guard must be reachable ONLY from an opted-in variant. If it could fire
    with the flag absent it would take the engine down for everyone."""
    for raw in (None, "", "shipped"):
        resolved, name = resolve_ncaaf_drive_profile(NCAAF_CALIBRATION_PROFILE, raw, base_version="anything")
        assert (resolved, name) == (NCAAF_CALIBRATION_PROFILE, "shipped")


# ---------------------------------------------------------------------------
# NFL IS NOT TOUCHED
# ---------------------------------------------------------------------------

def test_nfl_profile_is_unaffected_by_the_ncaaf_variant():
    before = _fingerprint(NFL_CALIBRATION_PROFILE)
    resolve_ncaaf_drive_profile(NCAAF_CALIBRATION_PROFILE, VARIANT)
    assert _fingerprint(NFL_CALIBRATION_PROFILE) == before
    assert NFL_CALIBRATION_PROFILE.goal_line_touchdown is False
    assert NFL_CALIBRATION_PROFILE.drive_yardage_multiplier == 1.0


# ---------------------------------------------------------------------------
# THE HARNESS: truth comes from the report, and missed kicks are not made kicks
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def harness():
    import importlib.util

    path = REPO_ROOT / "scripts" / "calibrate_ncaaf_drive_structure.py"
    spec = importlib.util.spec_from_file_location("_s4a_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_truth_is_parsed_from_the_report_not_retyped(harness):
    """The parser is the source; the literal table exists only so a divergence is
    a test failure instead of a silently stale constant."""
    parsed = harness._truth_from_report()
    assert parsed == pytest.approx(harness._TRUTH_FALLBACK, abs=1e-9)
    # ... and the value actually in use came from the parser.
    for key, value in parsed.items():
        assert harness.TRUTH[key] == pytest.approx(value)


def test_truth_parser_reads_the_ncaaf_column_and_not_the_nfl_one(harness):
    """The pooled table puts NFL truth in the next column; the NCAAF value is the
    bolded one. `possessions_per_game` is 23.65 for NCAAF and 21.66 for NFL, so
    a column slip is visible here."""
    parsed = harness._truth_from_report()
    assert parsed["possessions_per_game"] == 23.65
    assert parsed["game_total"] == 53.35
    assert parsed["touchdown_rate"] == pytest.approx(0.264)


def test_truth_parser_refuses_a_report_missing_rows(harness, tmp_path):
    stub = tmp_path / "truncated.md"
    stub.write_text("| Possessions per game | **23.65** | 21.66 |\n", encoding="utf-8")
    with pytest.raises(ValueError):
        harness._truth_from_report(stub)


def test_missed_field_goal_is_not_counted_as_a_made_field_goal(harness):
    """`"field_goal" in "missed_field_goal"` is True. Scanning in the wrong order
    put every missed kick in the made-FG bucket, which truth counts made-only."""
    assert harness._outcome({"outcome": "missed_field_goal"}) == "missed_field_goal"
    assert harness._outcome({"outcome": "field_goal"}) == "field_goal"
    assert harness._outcome({"outcome": "turnover_on_downs"}) == "turnover_on_downs"
    assert harness._outcome({"outcome": "turnover"}) == "turnover"


def test_harness_measures_outcome_quality_alongside_structure(harness):
    """Per-quarter scoring is scored, not checked afterwards -- the NFL
    recalibration's failure mode was that nobody scored it while fitting."""
    for key in ("quarter_1_scoring", "quarter_2_scoring", "quarter_3_scoring",
                "quarter_4_scoring", "h1_scoring", "h2_scoring", "game_total"):
        assert key in harness.SECONDARY
    measured = harness.measure(NCAAF_CALIBRATION_PROFILE, games=3)
    for key in harness.SECONDARY + harness.PRIMARY + harness.UNSCORED:
        assert key in measured
