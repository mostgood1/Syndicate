"""NHL calibration profile for the ``hockeysim`` engine.

Mirrors the role of ``smartsim2.calibration_profile`` / ``soccersim.calibration_profile``:
one engine, and the sport/league differences are expressed only as a parameter object rather
than forked control flow. For hockey that parameter object is ``SimConfig`` (defined in
``engine.py``), which already externalizes every tunable lever — special-teams shot/goal
multipliers, over-dispersion, faceoff knobs, and the score/goal/assist/usage sub-models.

``NHL_CALIBRATION_PROFILE`` is the canonical frozen baseline (the values the absorbed
``nhl_betting`` engine shipped with). Downstream code should build a per-run config via
``build_nhl_sim_config(...)`` so a seed and any calibration overrides can be applied without
mutating the shared baseline. When the Phase 3 truth layer lands, calibrated deltas are
expressed here as documented field overrides — never as new control flow in ``engine.py``.
"""
from __future__ import annotations

from dataclasses import fields, replace
from typing import Any, Dict, Optional

from syndicate.features.shared.calibration_profile_paths import calibration_profile_path
from syndicate.features.shared.calibration_profile_store import load_versioned_profile

from .engine import SimConfig

# Canonical NHL baseline. These are exactly the defaults the absorbed engine shipped with;
# keeping them as an explicit named profile makes future truth-calibrated overrides auditable
# (each changed field gets a provenance comment, e.g. "# +X% shots vs 2023-25 truth").
NHL_CALIBRATION_PROFILE_DEFAULT: SimConfig = SimConfig(
    periods=3,
    seconds_per_period=20 * 60,
    overtime_seconds=5 * 60,
    ot_enabled=True,
    shootout_enabled=True,
    dispersion_shots=0.0,
    dispersion_goals=0.0,
    pp_shots_mult=1.4,
    pk_shots_mult=0.7,
    pp_goals_mult=1.0,
    pk_goals_mult=1.0,
    # Newly reachable this session (`docs/ai_context/hockeysim_engine_reference.md` §2b) -- values
    # unchanged from the old inline `special_teams_cal.get(key, DEFAULT)` fallbacks, so wiring them
    # through here is a no-op until a real calibration pass changes one.
    pp_shot_cal_mult=1.0,
    pk_shot_cal_mult=1.0,
    pp_goal_cal_mult=1.0,
    pk_goal_cal_mult=1.0,
    block_rate_ev=0.45,
    block_rate_pk=0.55,
    block_rate_pp_def=0.35,
    score_effects="dynamic",
    goal_model="from_shots",
    assist_model="onice",
    usage_model="deterministic",
    usage_noisy_sigma=0.18,
    faceoff_enabled=True,
    faceoff_alpha=0.35,
    faceoff_diff_clip=0.12,
    faceoff_mult_clip_low=0.90,
    faceoff_mult_clip_high=1.10,
    faceoff_ev_only=True,
)

# `#440` Part 4 Phase 5 -- the versioned-profile seam.
#
# This engine is the one that proves the seam is GENERIC: football and soccer
# resolve a `CalibrationProfile` dataclass, hockey resolves a `SimConfig`. The
# store is written against `dataclasses.fields`/`replace`, so all three work
# through it unchanged. Phase 5's falsification test was "if wiring an engine
# requires changing the store, stop" -- it did not, for any of the three.
#
# NO-OP WHILE NO ARTIFACT EXISTS: `load_versioned_profile` returns
# `default_profile` ITSELF when the file is absent, invalid or unreadable, and
# never raises. `build_nhl_sim_config()` defaults to this constant, so resolving
# the constant reaches every caller without touching the builder's signature.
NHL_CALIBRATION_PROFILE, NHL_CALIBRATION_PROFILE_METADATA = load_versioned_profile(
    default_profile=NHL_CALIBRATION_PROFILE_DEFAULT,
    artifact_path=calibration_profile_path("nhl"),
)

_PROFILE_FIELD_NAMES = {f.name for f in fields(SimConfig)}


def build_nhl_sim_config(
    *,
    seed: Optional[int] = None,
    profile: Optional[SimConfig] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> SimConfig:
    """Return a per-run ``SimConfig`` derived from a base profile.

    ``profile`` defaults to :data:`NHL_CALIBRATION_PROFILE`. ``overrides`` is a mapping of
    ``SimConfig`` field names to values (unknown keys are ignored so callers can pass a wider
    calibration dict safely). ``seed`` sets the run seed. The base profile is never mutated.
    """
    base = profile if profile is not None else NHL_CALIBRATION_PROFILE
    changes: Dict[str, Any] = {}
    for key, value in (overrides or {}).items():
        if key in _PROFILE_FIELD_NAMES:
            changes[key] = value
    if seed is not None:
        changes["seed"] = int(seed)
    return replace(base, **changes) if changes else base
