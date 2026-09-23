"""SmartSim 2.0 Football Core calibration profile.

A calibration profile is the Football Core's parameterization seam for
league-specific behavior: explosive-play frequency/magnitude, ordinary
drive-yardage magnitude, field-goal success, fourth-down aggressiveness,
and touchdown-vs-field-goal scoring mix. No decision logic, control flow,
or situational/urgency model lives here -- that stays exactly as coded in
``play_simulator.py`` / ``drive_simulator.py`` / ``situation_model.py``. A
profile only rescales the numeric constants those modules already expose
as tunable seams (the constants a league's calibration report would tune).

``NFL_CALIBRATION_PROFILE`` reproduces today's hardcoded constants exactly
(multipliers of 1.0, additive bases matching the literals that used to be
hardcoded directly in play_simulator.py/drive_simulator.py). Every call
site that does not pass ``profile=`` explicitly still resolves to this
default, so the NFL calibration profile stays frozen -- byte-for-byte
identical simulated behavior -- while the Core becomes profile-aware.
"""

from __future__ import annotations

from dataclasses import dataclass

from syndicate.features.shared.calibration_profile_paths import calibration_profile_path
from syndicate.features.shared.calibration_profile_store import load_versioned_profile


@dataclass(frozen=True)
class CalibrationProfile:
    name: str

    # Explosive-play frequency: multiplies the EXPLOSIVE_GAIN outcome-selection
    # weight in play_simulator._play_outcome_weights.
    explosive_play_multiplier: float = 1.0
    # Explosive-play yardage magnitude: multiplies the EXPLOSIVE_GAIN yardage
    # base in play_simulator.simulate_play.
    explosive_yardage_multiplier: float = 1.0
    # HOW TEAM RATING CONVERTS TO YARDAGE, and why these are asymmetric.
    #
    # `play_simulator` computed `offense_rating * 3.0 - defense_rating * 2.2`
    # for ordinary gains and `* 4.0 / * 2.5` for explosive ones. Because the
    # offense weight EXCEEDS the defense weight, a strong offense adds more
    # than a strong defense subtracts -- so a game between two good teams
    # inflates the TOTAL even though the MARGIN is unaffected (margin depends
    # on the difference of these terms, total on their sum).
    #
    # Measured 2026-08-19 on the NCAAF 2026 wk1 slate: total SD 5.77 against a
    # market 3.46 (1.67x), while the total MEAN was close (51.56 vs 53.02) --
    # the scoring level right, only the spread wide.
    #
    # THAT ASYMMETRY IS *NOT* THE CAUSE OF THE WIDE TOTALS. I predicted it was
    # and swept these weights to find out; total SD barely moved, and PARITY --
    # the setting the sum-vs-difference argument says should fix it -- made
    # totals WORSE:
    #
    #     off/def   ex off/def    margin SD   total SD
    #     3.0/2.2     4.0/2.5        15.97       7.51   <- shipped
    #     3.0/2.6     4.0/3.2        16.43       7.45
    #     3.0/3.0     4.0/4.0        17.12       7.83   <- parity, worse
    #     2.6/3.0     3.4/4.0        15.96       7.69
    #     2.4/3.2     3.0/4.2        16.07       7.78
    #
    # (60 seeds, so the absolutes run ~30% high against the 300-seed
    # production figure of 5.77; the RELATIVE comparison is what matters here.)
    #
    # These fields are kept anyway -- they make a hardcoded constant tunable
    # per sport and cost nothing at their defaults -- but they DO NOT fix the
    # total spread, and re-sweeping them is a dead end. The remaining
    # over-dispersion is generated upstream, most likely in `drive_priors`
    # `scoring_environment` or the drive/touchdown probability chain, and that
    # is where the next investigation belongs.
    #
    # DEFAULTS REPRODUCE THE PREVIOUS HARDCODED VALUES EXACTLY, so NFL -- whose
    # profile is the frozen Production Candidate -- is byte-identical unless a
    # profile overrides them.
    rating_offense_weight: float = 3.0
    rating_defense_weight: float = 2.2
    explosive_rating_offense_weight: float = 4.0
    explosive_rating_defense_weight: float = 2.5

    # --------------------------------------------------------------------
    # BLOWOUT DAMPING -- OFF BY DEFAULT (`strength = 0.0` is an exact no-op).
    #
    # WHY IT EXISTS. This engine scores at FULL RATE in the fourth quarter of a
    # 30-point game. Measured 2026-09-23 (`#686`, lane
    # `smartsim2-total-nonlinearity`): the Q4/Q1 scoring ratio is 1.447 in a
    # matched game and 1.412 in a badly mismatched one -- i.e. unchanged. Real
    # football does the opposite: a leading team kneels, runs the clock, plays
    # conservatively and empties the bench.
    #
    # WHAT IT IS FOR. Points-per-drive is CONVEX in yards-per-play (converting
    # first downs is sharply nonlinear), so a mismatch raises the projected
    # TOTAL -- measured at `+7.3493*off_diff - 4.8940*def_diff`, R2 0.933, with
    # both rating SUMS pinned at zero. That convexity is real football and is
    # not the defect. The defect is that nothing pays it back, because the
    # damping that cancels it in reality is missing here. Reality's verdict on
    # the net effect: `corr(|market spread|, ACTUAL total)` on 2025 = -0.032.
    #
    # WHY IT SHIPS OFF AND MUST BE FITTED BEFORE IT IS ARMED. This is a
    # MECHANISM added to a CALIBRATED engine, which `model_engine_standard.md`
    # says requires re-fitting the rates that were absorbing it -- and this
    # ledger records two mechanisms interacting NEGATIVELY in 4 of 4 markets.
    # It also moves the MARGIN in exactly the blowout games, and the NFL margin
    # is currently calibrated (2026 wk3 spread MAE 1.89 vs the market). NCAAF
    # shares this engine and has no actual-outcome total fit at all yet.
    # Arming it for either sport is a fitting exercise, not a flag flip.
    #
    # **IT DOES NOT FIX `#686`, AND THAT WAS MEASURED, NOT ASSUMED.** It was
    # built to remove the total's spurious response to the rating DIFFERENCE.
    # It does not. Sweeping off_diff -0.4..+0.4 with the level pinned, the
    # fitted `total ~ off_diff` slope is +5.93 at strength 0.0 and +6.00 at
    # strength 0.9 -- flat. Only the mean total drifts (44.18 -> 43.86).
    #
    # The reason, obvious afterwards: at off_diff 0.4 the average margin is
    # about 5 points, which is not a blowout, so damping keyed to a 14-point
    # lead almost never fires -- while the points-per-drive convexity that
    # CAUSES the response operates at every margin, close games included. The
    # response is not a blowout phenomenon.
    #
    # So this is kept for its OWN sake: the engine genuinely has no
    # garbage-time behaviour, which matters for quarter/half markets and for
    # the tail of the score distribution. It is NOT the repair for `#686`.
    #
    # SHAPE. The damping scales the possessing team's SCORING weights
    # (touchdown, field-goal attempt, explosive) when that team is LEADING,
    # ramping from the start of Q3 to the end of Q4 and with the size of the
    # lead. It deliberately does NOT damp the trailing team: garbage-time
    # points are real, and it is the leader easing off that caps a blowout.
    blowout_damping_strength: float = 0.0
    blowout_damping_lead_threshold: float = 14.0
    blowout_damping_lead_span: float = 14.0
    blowout_damping_quarter_seconds: float = 900.0

    # --------------------------------------------------------------------
    # DRIVE-SUCCESS SENSITIVITY -- the carrier the note above points at
    # --------------------------------------------------------------------
    #
    # The comment above ends "the remaining over-dispersion is generated
    # upstream, most likely in `drive_priors` `scoring_environment` or the
    # drive/touchdown probability chain, and that is where the next
    # investigation belongs." This is that place.
    #
    # `drive_priors.build_drive_priors` computes
    #
    #     drive_success_probability = 0.24 + offense_index*0.28 + ... - defense_index*0.22
    #
    # and `drive_success_probability` drives BOTH scoring outcomes:
    # `touchdown_probability` is directly proportional to it, and
    # `field_goal_probability` carries it at 0.08. So it IS the drive-loop
    # scoring rate, which `pick_gate` records swinging **20.8 -> 53.9 percent
    # against a real 35-45**.
    #
    # The offense and defense terms alone span ~0.45 across the clamped index
    # range [0.05, 0.95], against a real per-drive scoring spread of roughly
    # 0.10. The engine is far more sensitive to team quality than football is.
    # That is what widens the TOTAL without touching the MARGIN -- margin
    # depends on the DIFFERENCE of the two teams' scoring rates, the total on
    # their SUM, which is why the measured mean was right (51.56 vs 53.02)
    # while the SD was 1.67x (5.77 vs 3.46).
    #
    # Applied as a shrink toward an anchor rather than as smaller coefficients:
    #
    #     p = anchor + sensitivity * (raw - anchor)
    #
    # so `sensitivity` is a single dial with a meaning ("how much of the raw
    # spread survives") instead of seven coefficients that must be kept in
    # proportion by hand. `anchor` is the population per-drive scoring level,
    # NOT a fitted value -- moving it moves the MEAN, which is already correct
    # and must not be disturbed while fixing the SPREAD.
    #
    # DEFAULT 1.0 IS AN EXACT NO-OP: p = anchor + 1.0*(raw - anchor) = raw, for
    # any anchor. NFL's frozen Production Candidate is byte-identical, and so
    # is NCAAF until its own profile overrides it. This field being present
    # changes nothing on its own -- it only makes the dial reachable.
    drive_success_sensitivity: float = 1.0
    # ANCHOR CORRECTED 0.40 -> 0.3271, MEASURED, 2026-09-23 (lane
    # `smartsim2-total-nonlinearity`). It is the population mean of the UNSHRUNK
    # `drive_success_probability` over production-shaped inputs, which is the
    # only value that makes the shrink mean-preserving: E[p] = anchor +
    # s*(E[raw] - anchor) equals E[raw] for ANY s only when anchor == E[raw].
    #
    # Measured on each sport's real ratings, through production's own
    # empty-payload path (drive priors default OFF, so `offense_index` reduces
    # to `0.5 + rating/2`):
    #
    #     NFL    2026 wk3 blended ratings,  n=32    mean drive_success 0.3271
    #     NCAAF  2025 as-of-week blend_ppa, n=1309  mean drive_success 0.3271
    #
    # THE TWO SPORTS AGREE TO FOUR DECIMALS, and that is the real finding: under
    # the empty-payload path this is NOT a per-sport quantity. It is the formula
    # evaluated at neutral indices, and both sports' ratings are centred (mean
    # offense_index 0.4989 / 0.4981, defence 0.4983 / 0.4971). The old 0.40 was
    # simply wrong for both, and by enough to matter -- it is what produced the
    # +3.86 mean-total drift measured when `drive_success_sensitivity` was swept
    # to 0.3, because shrinking toward 0.40 pulls a 0.3271 population UP.
    #
    # THIS CHANGE IS AN EXACT NO-OP TODAY. At `sensitivity == 1.0` the anchor
    # cancels algebraically (`a + 1.0*(raw - a) == raw`) for ANY anchor, so
    # nothing moves until a sensitivity is set. It is corrected NOW so that the
    # first person to set one does not silently inherit a mean shift.
    #
    # NOTE THE 0.405 FIGURE ELSEWHERE IN THIS FILE IS NOT THIS. That is a
    # league-mean `offense_index` under a POPULATED feature payload
    # (`SYNDICATE_NFL_DRIVE_PRIORS=1`), which production does not run. Measured
    # on the path production actually uses, the indices sit at ~0.498.
    drive_success_anchor: float = 0.3271

    # SPLIT OFFENCE/DEFENCE SENSITIVITIES. Both default 1.0, an EXACT algebraic
    # no-op, so every shipped profile is byte-identical until one is set.
    #
    # WHY THE SINGLE DIAL ABOVE IS NOT ENOUGH, measured 2026-09-23 (`#686`/`#687`,
    # lane `smartsim2-total-nonlinearity`). Fitting ACTUAL totals against the
    # ratings each sport's generator really feeds the engine, and comparing with
    # what the engine applies (5x5 grids, one direction pinned, R2 0.98+):
    #
    #                      keep offence   keep defence
    #     NFL                  0.438          0.026
    #     NCAAF                0.112          0.399
    #
    # The two sports are near MIRROR IMAGES. `drive_success_sensitivity` shrinks
    # the whole spread toward `drive_success_anchor` and therefore applies ONE
    # ratio to both, which cannot satisfy either sport. A per-sport single dial
    # would still be a compromise; this is the split that is not.
    #
    # NFL's numbers come from `backtest_nfl_rating_units.py --total-level`
    # (train 2023-24 n=544, held out 2025 n=272). NCAAF's come from
    # `backtest_ncaaf_total_units.py --asof` (train 2024 n=655, held out 2025
    # n=645), on the as-of-week `blend_ppa` k=2 rating the generator actually
    # runs mid-season -- NOT the prior-season SP+ basis, which is a DEGRADED
    # rating and returned roughly half these ratios (0.062 / 0.253).
    #
    # SHAPE. Each dial shrinks its own team-quality term toward that term's
    # value at a NEUTRAL index of 0.5 -- the engine's own convention, the same
    # 0.5 that `0.5 + rating` uses. The `returning`, `coach`, `market_prior`
    # and `transfer_volatility` terms are NOT touched: they are not team-quality
    # carriers and shrinking them would move the MEAN, which is already right.
    # With both at 1.0 the expression reduces to the original literal sum, which
    # is why the default cannot perturb a single seeded result.
    #
    # NOT FITTED, NOT ARMED. These are the dials the fits argue for; setting
    # them is a separate act that must re-check the MEAN (via
    # `drive_success_anchor`) and the MARGIN, because this is a mechanism change
    # to a calibrated engine.
    drive_success_offense_sensitivity: float = 1.0
    drive_success_defense_sensitivity: float = 1.0

    # Ordinary-gain yardage magnitude ("drive-yardage generation"): multiplies
    # the GAIN outcome's yardage base in play_simulator.simulate_play.
    drive_yardage_multiplier: float = 1.0

    # Field-goal success profile: make_probability = clamp(base - max(0, kick_distance - 25) * distance_penalty, floor, ceiling).
    field_goal_make_base: float = 0.98
    field_goal_make_distance_penalty: float = 0.012
    field_goal_make_floor: float = 0.30
    field_goal_make_ceiling: float = 0.97

    # Fourth-down aggressiveness -- field-goal attempt-probability curve
    # (drive_simulator._field_goal_decision).
    field_goal_attempt_fringe_probability: float = 0.50
    field_goal_attempt_base_probability: float = 0.88
    field_goal_attempt_distance_scale: float = 0.02

    # Fourth-down aggressiveness -- punt-probability by field-position/distance
    # band (drive_simulator._punt_decision). Lower values are more aggressive
    # (more likely to go for it instead of punting).
    fourth_down_short_distance_punt_probability: float = 0.30
    fourth_down_mid_distance_punt_probability: float = 0.60
    fourth_down_midfield_punt_probability: float = 0.97
    fourth_down_range_approach_punt_base: float = 0.86
    fourth_down_range_approach_punt_scale: float = 0.08
    fourth_down_in_range_punt_base: float = 0.18
    fourth_down_in_range_punt_scale: float = 0.30

    # Fourth-down conversion success: multiplies the existing distance-scaled
    # conversion-probability clamp in drive_simulator.simulate_drive.
    fourth_down_conversion_multiplier: float = 1.0

    # Scoring distribution: touchdown vs field-goal outcome-weight balance
    # in play_simulator._play_outcome_weights.
    touchdown_weight_multiplier: float = 1.0
    field_goal_weight_multiplier: float = 1.0

    # Red-zone-specific scoring distribution: these two isolate red-zone
    # behavior from the general touchdown_weight_multiplier/gain formulas
    # above, so a league can raise red-zone efficiency (more trips ending in
    # touchdowns instead of stalling into a field-goal attempt or
    # turnover-on-downs) without moving the overall (all-field-position)
    # touchdown rate or ordinary drive yardage.
    # Additive bonus to the touchdown outcome weight while play_state.red_zone
    # is true (play_simulator._play_outcome_weights); replaces the literal
    # `red_zone * 0.33` term.
    red_zone_touchdown_weight_bonus: float = 0.33
    # Multiplies the ordinary-GAIN outcome weight while play_state.field_goal_range
    # is true (play_simulator._play_outcome_weights); replaces the literal
    # `gain *= 0.80` scoring-zone stiffening. Lower values stall more drives
    # into field-goal attempts/turnovers-on-downs; higher values (closer to
    # 1.0) keep more red-zone possessions alive long enough to score a
    # touchdown instead.
    red_zone_gain_stiffening: float = 0.80
    # A DRIVE REACHING THE END ZONE SCORES. Per-PROFILE, not a global env flag.
    #
    # Measured 2026-08-27, all four combinations at 120 games:
    #
    #     sport  profile     goal-line   SCORED err
    #     ncaaf  shipped     off            15.19%   <- production today
    #     ncaaf  candidate   ON              7.25%   <- best
    #     nfl    shipped     off             3.87%   <- production today, BEST
    #     nfl    candidate   ON              4.18%
    #     nfl    candidate   off             7.42%
    #
    # NCAAF gains 7.94 points from the fix plus its re-fit. NFL is ALREADY at
    # its best and the same treatment costs it 0.31. A single global switch
    # forces one sport to pay for the other; a profile field does not, and the
    # profile is already in scope at every call site that needs it.
    #
    # Also note the last row: a re-fitted profile with the mechanism OFF is
    # WORSE than the profile it replaces, for both sports. The profile and the
    # mechanism are one change and can never ship apart.
    goal_line_touchdown: bool = False

    def to_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "explosive_play_multiplier": self.explosive_play_multiplier,
            "explosive_yardage_multiplier": self.explosive_yardage_multiplier,
            "drive_yardage_multiplier": self.drive_yardage_multiplier,
            "field_goal_make_base": self.field_goal_make_base,
            "field_goal_make_distance_penalty": self.field_goal_make_distance_penalty,
            "field_goal_make_floor": self.field_goal_make_floor,
            "field_goal_make_ceiling": self.field_goal_make_ceiling,
            "field_goal_attempt_fringe_probability": self.field_goal_attempt_fringe_probability,
            "field_goal_attempt_base_probability": self.field_goal_attempt_base_probability,
            "field_goal_attempt_distance_scale": self.field_goal_attempt_distance_scale,
            "fourth_down_short_distance_punt_probability": self.fourth_down_short_distance_punt_probability,
            "fourth_down_mid_distance_punt_probability": self.fourth_down_mid_distance_punt_probability,
            "fourth_down_midfield_punt_probability": self.fourth_down_midfield_punt_probability,
            "fourth_down_range_approach_punt_base": self.fourth_down_range_approach_punt_base,
            "fourth_down_range_approach_punt_scale": self.fourth_down_range_approach_punt_scale,
            "fourth_down_in_range_punt_base": self.fourth_down_in_range_punt_base,
            "fourth_down_in_range_punt_scale": self.fourth_down_in_range_punt_scale,
            "fourth_down_conversion_multiplier": self.fourth_down_conversion_multiplier,
            "touchdown_weight_multiplier": self.touchdown_weight_multiplier,
            "field_goal_weight_multiplier": self.field_goal_weight_multiplier,
            "red_zone_touchdown_weight_bonus": self.red_zone_touchdown_weight_bonus,
            "red_zone_gain_stiffening": self.red_zone_gain_stiffening,
            # MUST be here or the artifact cannot carry it: `save_versioned_profile`
            # serialises `to_dict()` and `profile_with_overrides` reads the same
            # keys back. A field absent here round-trips to its default, so a
            # candidate that opts into the goal-line rule would load with it OFF
            # and the whole re-fit would be inert while appearing to apply.
            "goal_line_touchdown": self.goal_line_touchdown,
        }


# Extracted, not invented: every value here is the literal that used to be
# hardcoded in play_simulator.py/drive_simulator.py before this profile seam
# existed. Passing this profile (or no profile at all, since call sites
# default to it) reproduces the frozen NFL Production Candidate exactly.
NFL_CALIBRATION_PROFILE_DEFAULT = CalibrationProfile(name="nfl")

# `#440` Part 4 Phase 5 -- the versioned-profile seam. See the soccer engine's
# copy of this comment for the full reasoning; the short version:
#
# RESOLVED AT IMPORT because every consumer takes this constant as a DEFAULT
# ARGUMENT (`simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE)` in the
# four generate/backtest scripts, and the engine's own defaults), and Python
# evaluates those once at import. Resolving the CONSTANT reaches every call site
# with no churn; a separate `resolve_...()` helper would have required editing
# each one, and any site missed keeps reading the frozen default -- which is
# exactly how `load_versioned_profile` came to be "complete and unreachable".
#
# NO-OP WHILE NO ARTIFACT EXISTS: the loader returns `default_profile` ITSELF
# when the file is absent, invalid or unreadable, and never raises. The comment
# above still holds verbatim -- passing this profile, or none, reproduces the
# frozen NFL Production Candidate exactly.
#
# NOTE FOR PHASE 8: this profile is currently ALL 1.0 MULTIPLIERS, i.e. NFL has
# never had a real calibration. That is what makes it the cheapest Phase 8
# target, and this seam is what lets it ship as a file rather than a code change.
NFL_CALIBRATION_PROFILE, NFL_CALIBRATION_PROFILE_METADATA = load_versioned_profile(
    default_profile=NFL_CALIBRATION_PROFILE_DEFAULT,
    artifact_path=calibration_profile_path("nfl"),
)

__all__ = [
    "CalibrationProfile",
    "NFL_CALIBRATION_PROFILE",
    "NFL_CALIBRATION_PROFILE_DEFAULT",
    "NFL_CALIBRATION_PROFILE_METADATA",
]
