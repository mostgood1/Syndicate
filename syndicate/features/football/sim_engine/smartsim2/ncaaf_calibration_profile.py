"""SmartSim 2.0 NCAAF Calibration Profile v2.

Defines the second Football Core calibration profile, built exclusively
from profile-level parameters on the shared ``CalibrationProfile`` seam
(``calibration_profile.py``). No engine, control-flow, or situational-model
code is forked for NCAAF -- every value below is consumed by the same
``play_simulator.py`` / ``drive_simulator.py`` functions the NFL profile
already runs through, just with different numbers.

Values are derived from the measured deltas in ``ncaaf_historical_truth_report.md``
(53,548 real NCAAF drives vs 17,677 real NFL drives, 2023-2025):

- yards/play +42.4% (7.36 vs 5.17) -> drive_yardage_multiplier, explosive_yardage_multiplier, explosive_play_multiplier
- touchdown_rate +20.0% (26.4% vs 22.0%), field_goal_rate(made) -36.3% (10.0% vs 15.7%) -> touchdown_weight_multiplier, field_goal_make_base/distance_penalty/floor/ceiling
- turnover_on_downs_rate +25.9% (7.3% vs 5.8%) -> fourth_down_conversion_multiplier (the field-goal-attempt-probability curve was tried and reverted to NFL defaults -- it moved punt_rate, a sport-invariant metric, without moving the made-FG-rate target)
- punt_rate, turnover_rate, seconds/drive, plays/drive, red_zone_conversion measured within 3% of NFL truth -> left at or near NFL defaults (sport-invariant Football Core behaviors, not NCAAF-specific levers)

This is a v1 / Experimental profile: parameters were set directly from the
measured truth deltas and one measurement pass (see
``ncaaf_calibration_profile_report.md`` and ``ncaaf_profile_validation_report.md``),
not from an iterative multi-pass calibration loop like the NFL profile's
seven iterations. Treat these values as the starting point for that process,
not its endpoint.

v2 addition (see ``ncaaf_week1_shakeout_report.md`` and
``ncaaf_calibration_profile_v2_report.md``): ``red_zone_touchdown_weight_bonus``
and ``red_zone_gain_stiffening`` were added to the shared seam and tuned to
close a red-zone-conversion gap the v1 validation pass never measured
(72.6-76.4% simulated vs 85.6% truth). Still Experimental -- one more
parameter sweep, not a multi-iteration calibration loop.
"""

from __future__ import annotations

import dataclasses
import os

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import CalibrationProfile
from syndicate.features.shared.calibration_profile_paths import calibration_profile_path
from syndicate.features.shared.calibration_profile_store import load_versioned_profile

NCAAF_CALIBRATION_PROFILE_DEFAULT = CalibrationProfile(
    name="ncaaf",
    # Yards/play is the largest measured divergence (+42.4% relative). Split
    # across three levers: more frequent explosive plays, bigger explosive
    # plays, and bigger ordinary gains -- matching the spread/tempo-offense,
    # wider-talent-mismatch signature documented in the truth report.
    explosive_play_multiplier=1.45,
    explosive_yardage_multiplier=1.35,
    drive_yardage_multiplier=1.15,
    # Field-goal success profile: college kickers are trusted over a shorter
    # effective range -- steeper distance penalty, lower ceiling.
    field_goal_make_base=0.90,
    field_goal_make_distance_penalty=0.022,
    field_goal_make_floor=0.25,
    field_goal_make_ceiling=0.82,
    # Fourth-down aggressiveness: attempt-probability curve left at NFL
    # defaults -- measurement showed the made-FG-rate gap is carried entirely
    # by the make-probability curve above; changing attempt probability only
    # perturbed punt_rate (a measured sport-invariant metric) without moving
    # the made-FG rate, so it is not a useful lever for this target.
    field_goal_attempt_fringe_probability=0.50,
    field_goal_attempt_base_probability=0.88,
    field_goal_attempt_distance_scale=0.02,
    # Punt-decision thresholds left at NFL defaults: punt_rate measured within
    # 0.1% of NFL truth, so this lever is a Football Core constant, not a
    # league-specific one.
    fourth_down_short_distance_punt_probability=0.30,
    fourth_down_mid_distance_punt_probability=0.60,
    fourth_down_midfield_punt_probability=0.97,
    fourth_down_range_approach_punt_base=0.86,
    fourth_down_range_approach_punt_scale=0.08,
    fourth_down_in_range_punt_base=0.18,
    fourth_down_in_range_punt_scale=0.30,
    # Fourth-down conversion success is lower, not higher, consistent with
    # college teams going for it more out of kicker distrust/aggression
    # rather than superior short-yardage execution -- this is the primary
    # turnover-on-downs lever.
    fourth_down_conversion_multiplier=0.55,
    # Scoring distribution: touchdown_weight_multiplier is the effective lever
    # here. The yardage multipliers above already raise touchdown frequency
    # indirectly (bigger gains reach/hold the red zone more often, and
    # red-zone presence itself raises touchdown weight), so this only needs
    # to correct, not drive, the TD/FG split -- measurement showed it
    # overshoots quickly, hence the value below 1.0.
    # field_goal_weight_multiplier is defined for symmetry/documentation of
    # the seam but is currently a no-op in practice: drive_simulator.py's 4th
    # -down handling always intercepts down==4 with its own explicit
    # _field_goal_decision/_punt_decision branch before simulate_play ever
    # runs, so play_simulator's down>=4-gated FIELD_GOAL_ATTEMPT weight is
    # unreachable. The real field-goal levers are field_goal_make_* (make
    # probability, used above) and field_goal_attempt_* (attempt probability).
    touchdown_weight_multiplier=0.66,
    field_goal_weight_multiplier=1.0,
    # v2 addition (post-Week-1-shakeout): red_zone_conversion_rate measured
    # 72.6-76.4% in simulation vs 85.6% truth -- a gap the v1 validation pass
    # never isolated because red-zone entries were increasing (via the
    # yardage multipliers above) without a matched red-zone scoring lever.
    # red_zone_touchdown_weight_bonus raised 0.33 -> 0.58: a 6-point grid
    # sweep (800-game batches per point) showed this monotonically improves
    # both red-zone success (TD+FG share of red-zone entries) and red-zone
    # touchdown share specifically, while leaving yards/drive, yards/play,
    # and possessions/game essentially unchanged (this lever only fires
    # inside play_state.red_zone, a small share of all plays). 0.58 was
    # chosen as the point where red-zone-success and red-zone-TD-share
    # normalized error both drop by roughly a fifth to a third without
    # pushing the (already near-exact) overall touchdown_rate past ~13%
    # normalized error -- more aggressive values in the sweep bought
    # further red-zone gains at a steeper cost to that already-good fit.
    red_zone_touchdown_weight_bonus=0.58,
    # red_zone_gain_stiffening measured and left at the shared/NFL default
    # (0.80): the same sweep varied this independently and found no clear
    # red-zone-success improvement, while raising it (less red-zone gain
    # suppression) pushed yards/drive and yards/play upward away from their
    # already-good fit. Not a useful NCAAF-specific lever.
    red_zone_gain_stiffening=0.80,
)

# THE VERSIONED-PROFILE SEAM, mirroring NFL's exactly (calibration_profile.py).
#
# NCAAF's profile was a hardcoded constant, so a calibration artifact written to
# `calibration_profile_path("ncaaf")` was READ BY NOTHING -- promoting a re-fit
# would have appeared to work and changed no simulation at all. NFL has resolved
# through this seam since `#440` Part 4 Phase 5; NCAAF simply never got wired.
#
# RESOLVED AT IMPORT because every consumer takes this constant as a DEFAULT
# ARGUMENT and Python evaluates those once -- resolving the CONSTANT reaches
# every call site with no churn.
#
# NO-OP WHILE NO ARTIFACT EXISTS: the loader returns `default_profile` ITSELF
# when the file is absent, invalid or unreadable, and never raises. With no
# artifact this file behaves exactly as it did before the seam.
NCAAF_CALIBRATION_PROFILE, NCAAF_CALIBRATION_PROFILE_METADATA = load_versioned_profile(
    default_profile=NCAAF_CALIBRATION_PROFILE_DEFAULT,
    artifact_path=calibration_profile_path("ncaaf"),
)

# ----------------------------------------------------------------------------
# S4a -- DRIVE-STRUCTURE VARIANTS, selected by SYNDICATE_NCAAF_DRIVE_PROFILE
# ----------------------------------------------------------------------------
#
# ABSENT MEANS TODAY'S PROFILE, EXACTLY. Not "close to", not "the default
# rebuilt from literals" -- the object resolved above, unmodified, whatever the
# versioned-profile artifact made it. A variant is a `dataclasses.replace` on
# THAT object, so it layers on a promoted artifact instead of discarding it, and
# with the flag absent no `replace` runs at all.
#
# A VARIANT IS A DICT OF OVERRIDES, NOT A WHOLE PROFILE, for the same reason.
# Writing out a full `CalibrationProfile(...)` would silently freeze every field
# it restates at the value it had the day it was written, so a later re-fit of
# the shipped profile would reach the variant in some fields and not others.
#
# WHY A FLAG AND NOT A PROMOTED ARTIFACT. `calibration_profile_path("ncaaf")` is
# how a fit SHIPS. This seam is how a fit is MEASURED next to the one in
# production, in the same process, without either becoming the served number.
# Promotion is a separate decision and needs a reading behind it.
#
# A VARIANT IS A DELTA FROM A NAMED BASE VERSION, and says which one. The fit
# below was measured against `ncaaf-goal-line-refit-1` -- the promoted artifact
# with the goal-line mechanism ON. Applied instead to the in-source DEFAULT
# (mechanism OFF, drive_yardage_multiplier 1.15) the same two absolute values
# describe a profile nobody measured. That is not hypothetical: a session
# worktree excludes `data/`, the loader's fall back to the default is silent by
# design, and a whole sweep was run against the wrong baseline before this was
# noticed. `resolve_ncaaf_drive_profile` refuses the mismatch rather than
# resolving to something plausible-looking.
NCAAF_DRIVE_PROFILE_VARIANT_BASE_VERSION = "ncaaf-goal-line-refit-1"

# MEASURED, AND RECOMMENDED AGAINST. `docs/reports/ncaaf_drive_structure_fit_report.md`
# carries the sweep, the rejected settings and the full two-dimensional table.
# The short version, so nobody flips this on the strength of the name:
#
#   at NEUTRAL ratings (800 games x 3 seed banks)
#       structure       4.16% -> 4.25%   slightly WORSE
#       outcome quality 7.36% -> 6.34%   better
#       outcome mix    26.79% -> 16.02%  much better (the FG accounting)
#       q4 normalized   0.037 -> 0.070   WORSE, from near-exact
#   at SAMPLED ratings (500 games) -- the case production actually simulates
#       outcome quality 5.33% -> 6.94%   WORSE; totals 52.43 -> 54.53 vs 53.35
#
# The two measurements disagree about whether this is an improvement, which is
# by itself enough not to ship it. Every NCAAF calibration so far, this one
# included, was scored with both teams at rating 0.0; the rated run says that is
# a different game. Re-derive at realistic ratings before promoting anything.
NCAAF_DRIVE_PROFILE_VARIANT_OVERRIDES: dict[str, dict[str, object]] = {
    "s4a_drive_fit_v1": {
        # THE MADE-FG CURVE, and the only reason it is reachable is a
        # measurement fix. `_outcome` in the harness scanned for the substring
        # "field_goal", which "missed_field_goal" CONTAINS, so every missed kick
        # was counted as a made one. Split correctly the live profile makes 8.3%
        # of drives (truth 10.0%) and MISSES 6.7% (truth 3.1%) -- the make curve
        # is far too punishing, which the merged bucket hid completely.
        # 0.022 -> 0.014 takes the missed rate to ~4.6% and the made rate to
        # ~10.5%, i.e. both toward truth at once.
        "field_goal_make_distance_penalty": 0.014,
        # RED-ZONE TOUCHDOWN WEIGHT, re-fitted because the mechanism beside it
        # changed. v2 chose 0.58 from a 6-point sweep and recorded that more
        # aggressive values cost the overall touchdown rate. That sweep ran with
        # `goal_line_touchdown` OFF; with the mechanism ON (promoted 2026-08-27)
        # a drive reaching the end zone already scores, so the weight is no
        # longer the only path to a red-zone touchdown and 0.80 is affordable.
        # This is the "adding a MECHANISM requires re-fitting the rates that
        # were absorbing it" rule applied to a rate the goal-line re-fit missed.
        "red_zone_touchdown_weight_bonus": 0.80,
    },
}


def _variant_factory(overrides: dict[str, object]):
    def apply(base: CalibrationProfile) -> CalibrationProfile:
        return dataclasses.replace(base, **overrides) if overrides else base

    return apply


NCAAF_DRIVE_PROFILE_VARIANTS = {
    name: _variant_factory(overrides)
    for name, overrides in NCAAF_DRIVE_PROFILE_VARIANT_OVERRIDES.items()
}

# THE EXACT VALUES THAT MEAN "SHIPPED". Anything else that is not a registered
# variant RAISES.
#
# An unrecognised value must not fall through to the shipped profile: that maps
# a typo onto the permissive branch, and the resulting run looks like a
# successful measurement of the variant while measuring production. The flag is
# absent in production, so this can only fire for someone who deliberately set
# it and got the name wrong -- which is exactly who needs to be told.
NCAAF_DRIVE_PROFILE_ENV = "SYNDICATE_NCAAF_DRIVE_PROFILE"
_SHIPPED_ALIASES = {"", "default", "shipped", "off", "none"}


def resolve_ncaaf_drive_profile(
    base: CalibrationProfile,
    raw: str | None,
    *,
    base_version: str | None = None,
) -> tuple[CalibrationProfile, str]:
    """`(profile, variant_name)` for a raw env value. `base` itself when absent.

    `base_version` is the version the loaded profile reports. When a variant is
    requested and that version is not the one the variant was fitted against,
    this RAISES -- a delta applied to the wrong base is a profile nobody
    measured, and it would otherwise resolve silently.
    """
    name = (raw or "").strip().lower()
    if name in _SHIPPED_ALIASES:
        return base, "shipped"
    factory = NCAAF_DRIVE_PROFILE_VARIANTS.get(name)
    if factory is None:
        raise ValueError(
            f"{NCAAF_DRIVE_PROFILE_ENV}={raw!r} is not a known NCAAF drive profile. "
            f"Known: {sorted(NCAAF_DRIVE_PROFILE_VARIANTS)} (or unset for the shipped profile)."
        )
    if base_version is not None and base_version != NCAAF_DRIVE_PROFILE_VARIANT_BASE_VERSION:
        raise ValueError(
            f"{NCAAF_DRIVE_PROFILE_ENV}={raw!r} is a delta from "
            f"{NCAAF_DRIVE_PROFILE_VARIANT_BASE_VERSION!r}, but the loaded NCAAF profile is "
            f"{base_version!r}. Applying it here would produce a profile that was never "
            f"measured. If `data/calibration/ncaaf_profile.json` is simply absent (a session "
            f"worktree excludes `data/`), point SYNDICATE_CALIBRATION_PROFILE_DIR at a copy; "
            f"if the artifact was re-promoted, the fit needs re-measuring against it."
        )
    return factory(base), name


NCAAF_CALIBRATION_PROFILE, NCAAF_DRIVE_PROFILE_ACTIVE = resolve_ncaaf_drive_profile(
    NCAAF_CALIBRATION_PROFILE,
    os.environ.get(NCAAF_DRIVE_PROFILE_ENV),
    base_version=str(NCAAF_CALIBRATION_PROFILE_METADATA.get("version") or ""),
)

# WHICH PROFILE IS LIVE MUST BE OBSERVABLE. Measured 2026-08-27: the promoted
# artifact was deployed to refresh-worker and NOTHING on the service could say
# whether it had been loaded — `render_logs --text calibration` matched nothing,
# so "the file is in the checkout" was the strongest available claim. A silent
# load is indistinguishable from a silent fallback to the default, which is
# exactly the failure `load_versioned_profile` is designed to make safe: it
# degrades to the default and never raises.
#
# `print(..., flush=True)` and not `logger.info` — `todo.md` records that
# logger.info never reaches Render's log collector.
print(
    f"[calibration] ncaaf profile source={NCAAF_CALIBRATION_PROFILE_METADATA.get('source')}"
    f" version={NCAAF_CALIBRATION_PROFILE_METADATA.get('version', '-')}"
    f" goal_line_touchdown={NCAAF_CALIBRATION_PROFILE.goal_line_touchdown}"
    f" drive_yardage_multiplier={NCAAF_CALIBRATION_PROFILE.drive_yardage_multiplier}"
    f" drive_profile={NCAAF_DRIVE_PROFILE_ACTIVE}",
    flush=True,
)

__all__ = [
    "NCAAF_CALIBRATION_PROFILE",
    "NCAAF_CALIBRATION_PROFILE_DEFAULT",
    "NCAAF_CALIBRATION_PROFILE_METADATA",
    "NCAAF_DRIVE_PROFILE_ACTIVE",
    "NCAAF_DRIVE_PROFILE_ENV",
    "NCAAF_DRIVE_PROFILE_VARIANTS",
    "NCAAF_DRIVE_PROFILE_VARIANT_BASE_VERSION",
    "NCAAF_DRIVE_PROFILE_VARIANT_OVERRIDES",
    "resolve_ncaaf_drive_profile",
]
