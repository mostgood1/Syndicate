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
    # Newly reachable this session (`docs/ai_context/hockeysim_engine_reference.md` §2c) via
    # `scripts/calibrate_nhl_special_teams_goal_mult.py`/`calibrate_nhl_special_teams_shot_mult.py`
    # against the 1,312-game truth snapshot (§2d/§2e). Block rates calibrated too, see §2h below.
    #
    # pp_shot_cal_mult: measured 0.9108 against real pp_shot_share (0.1488) -- a real, modest
    # (~9%) correction. `scripts/calibrate_nhl_special_teams_shot_mult.py`, full round-robin (992
    # ordered team pairs, eliminates composition bias), 3 JOINT alternating rounds with
    # pk_shot_cal_mult (fitting pp against a stale pk=1.0 placeholder left a ~5% verification gap
    # even at 260k simulated shots -- pk's correction shrinks the shared total-shots denominator
    # substantially, since uncalibrated SH shots ran ~3x the real rate, which biases pp_shot_share
    # if pk hasn't been corrected first). Final joint verification: 318,093 simulated shots,
    # pp_shot_share 0.1476 vs target 0.1488.
    pp_shot_cal_mult=0.9108,
    # pk_shot_cal_mult: measured 0.3369 against real sh_shot_share (0.0272) -- a real, substantial,
    # and highly stable correction across all 3 joint rounds (0.3366/0.3341/0.3369). Uncalibrated
    # (1.0), the engine simulated shots-while-shorthanded at ~2.8x the real rate (0.0755-0.0780 vs
    # 0.0272 truth) -- the same over-simulation direction and similar relative magnitude as the
    # shorthanded-GOAL rate (`pk_goal_cal_mult`, below), consistent with one root cause rather than
    # two independent ones. Final joint verification: sh_shot_share 0.0272, an exact match.
    pk_shot_cal_mult=0.3369,
    # pp_goal_cal_mult: measured 1.0021 against real pp_goal_share (0.1944) -- statistically
    # indistinguishable from neutral (iteration range 1.0013-1.0029 on a 2,000-game/iter sample).
    # The PP-goal mechanism (pp_pct + the existing pp_shots_mult=1.4) was ALREADY well-calibrated;
    # left at 1.0 rather than encoding sampling noise as a "correction."
    pp_goal_cal_mult=1.0,
    # pk_goal_cal_mult: measured 0.4645 against real sh_goal_share (0.0250) -- a real, substantial,
    # converged correction. Uncalibrated (1.0), the engine simulated shorthanded goals at MORE THAN
    # DOUBLE the real rate (0.0538 vs 0.0250 truth). Verified: final joint run at both fitted
    # values reproduces both targets simultaneously (pp 0.1971 vs 0.1944, sh 0.0246 vs 0.0250).
    #
    # NOTE: unlike this file's shot-multiplier pair above, the goal-multiplier calibration was
    # NOT re-run with a joint alternating fit -- it predates the discovery (this session) that a
    # sequential pp-then-pk fit can leave a shared-denominator bias. The goal case's own
    # verification match was already tight (pp 0.1971 vs 0.1944, within noise), so this is flagged
    # as a documented gap in methodology consistency, not a known error -- re-running it jointly
    # is cheap and worth doing before trusting `pp_goal_cal_mult` to more decimal places than 1.0.
    pk_goal_cal_mult=0.4645,
    # block_rate_ev/pk/pp_def: the vendor's shipped defaults (0.45/0.55/0.35) were never checked
    # against a real block rate before `scripts/calibrate_nhl_block_rate.py` (§2h). Unlike the
    # goal/shot multipliers above, the truth source (`historical_truth.boxscore_block_rate`) has
    # only ONE league-wide target -- blocks have no strength-state breakdown in the `boxscore`
    # payload at all -- so this is a SINGLE shared scale factor (`block_scale=1.0631`) applied
    # uniformly to all three, preserving their existing structural ratio (higher on the PK, lower
    # on the PP) rather than fitting 3 independent, underdetermined constants against 1 number.
    # Fit against real blocks_per_game(team)=14.1905 (1,312 games) with `block_rate_index` (§2g)
    # held NEUTRAL to isolate the absolute-level fit from the per-team layer; converged in 5
    # iterations (13.2613 -> 14.2800 -> 14.1821 -> 14.1958 -> 14.1975). Verified TWICE with a fresh
    # seed on the full round-robin (992 pairings x 20 sims = 19,840 games each): 14.2606 with the
    # index still neutral, 14.2583 with the REAL per-team `block_rate_index` active -- confirming
    # (again, post-calibration) that the per-team layer does not disturb the league-wide level.
    # Both ~0.5% above target, well within simulation noise.
    block_rate_ev=0.4784,
    block_rate_pk=0.5847,
    block_rate_pp_def=0.3721,
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
    # §2r: discrete-event redesign, on by default. `hockeysim_faceoff_segment_validation_report.md`
    # measured a real, large, sharp, short-lived post-faceoff shot effect (3.84x at 10s, decayed to
    # ~1.0x by 60-90s, 58,762 real EV faceoffs) that the diff-based mechanism above (`faceoff_alpha`
    # etc, still used when this is False) cannot represent -- it applies one constant multiplier
    # across an entire ~40-45s segment from season-long win rate, a category error for an effect
    # this concentrated. `historical_truth/faceoff_decay_model.py` simulates a discrete draw per EV
    # segment and applies the real measured decay curve's time-weighted average instead. Round-robin
    # verified: -0.12% league-wide shot delta vs the legacy mechanism, well within noise.
    faceoff_discrete_event_model=True,
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
