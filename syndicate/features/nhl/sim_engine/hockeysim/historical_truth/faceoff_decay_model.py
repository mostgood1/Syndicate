"""Discrete-event faceoff decay model — the engine redesign
`hockeysim_faceoff_segment_validation_report.md` flagged as the properly-faithful way to model a
real, measured effect that a uniform per-segment multiplier cannot represent.

WHY THIS EXISTS. That report measured a real, large, SHARP, SHORT-LIVED shot-generation edge for
the team that wins a real faceoff (3.84x in the first 10s, decaying to ~1.0x by 60-90s) — and
explicitly flagged that `engine.py`'s existing `_faceoff_multipliers` (one CONSTANT multiplier
applied across an entire ~40-45s segment, derived from SEASON-LONG win rate) is the wrong
functional form for an effect this concentrated: "directly recalibrating `faceoff_alpha` to match
a ~2-4x per-draw ratio would be a category error." This module is that redesign: simulate a
DISCRETE faceoff win/loss draw at the start of each EV segment, then apply a TIME-WEIGHTED AVERAGE
of the real measured decay curve over that segment's actual duration — the winner gets the boost,
the loser the (also real, measured) suppression, both decaying toward baseline as the segment goes
on, exactly matching what the underlying real event looks like.

THE CURVE IS REAL, MEASURED DATA, NOT A FITTED/ASSUMED SHAPE. `scripts/build_nhl_faceoff_decay_curve.py`
parsed 58,762 real EVEN-STRENGTH faceoffs across 1,312 games (the same `playbyplay` cache the
season-aggregate and cumulative-window checks already used), bucketing shots by MARGINAL (adjacent,
non-overlapping) time-since-draw windows -- (0,5]/(5,10]/(10,15]/(15,20]/(20,30]/(30,45]/(45,60]/
(60,90] seconds -- each bucket independently truncated at the next real faceoff so no shot is ever
double-counted. Buckets beyond 90s are treated as fully converged (winner/100s 0.6569 vs other/100s
0.6557 in the last measured bucket -- a 0.2% gap, noise-level) and held flat at multiplier 1.0.

WHY NORMALIZED TO MEAN 1.0 PER BUCKET, SAME DISCIPLINE AS EVERY OTHER PER-TEAM INDEX THIS SESSION
BUILT. Each bucket's `winner_mult`/`other_mult` = that bucket's raw rate divided by the bucket's
OWN average rate (`(winner_rate + other_rate) / 2`) -- so `(winner_mult + other_mult) / 2 == 1.0`
in every bucket by construction. This means a segment applying these multipliers to a 50/50 coin
flip of who wins the draw leaves the segment's EXPECTED total shot count unchanged versus not
knowing who wins at all -- the model redistributes shots between the two teams based on who won,
it does not inflate or deflate the league-wide total, the same property verified empirically (via a
round-robin re-simulation) for `block_rate_index`/`pp_shot_index`/`faceoff_oz_index`/etc.

WHAT THIS DOES NOT MODEL, STATED PLAINLY. Not every ~40-45s engine segment corresponds to a real
faceoff at its exact start (some shifts begin on the fly, off a line change, with no stoppage) --
this treats every EV segment as if it does, which overstates real faceoff frequency somewhat. Real
per-game EV faceoff counts (58,762 / 1,312 games ≈ 44.8/game) are the same order of magnitude as
this engine's own EV segment count per game, so the approximation is directionally reasonable, not
wildly off -- but it is an approximation, not a literal event-by-event reconstruction of a real
game clock, and is documented as such rather than presented as more precise than it is.

DZ-SPECIFIC CURVE (`segment_average_multipliers_dz`), added in a second pass, replacing the sign-
flip fix `hockeysim_faceoff_dz_direction_fix_report.md` shipped first. That fix corrected the
DIRECTION of a still-flat per-segment constant; this replaces the constant itself with the DZ
mechanism's own real decay curve -- the same treatment this module already gave the general
EV/OZ case, applied to the population `hockeysim_faceoff_dz_segment_validation_report.md` measured
(19,458 real draws the winner took in their OWN defensive zone, via `winner_zone="D"`).

THE DZ CURVE IS REAL, NOISIER, AND NOT SMOOTHLY MONOTONIC -- REPORTED AS MEASURED, NOT SMOOTHED.
Unlike the general curve's clean decay, the DZ-specific curve shows a SHARP initial suppression
(0.24x in the first 5s) that partially rebounds and briefly exceeds 1.0x at (10,15]s (1.157x)
before settling into a sustained MILD suppression (~0.85-0.95x) through 90s -- never fully
reconverging to 1.0x within the measured range, unlike the general curve. With roughly a third the
sample size per bucket (19,458 draws vs 58,762), more bucket-to-bucket noise is expected; the brief
positive excursion at (10,15]s is used as measured rather than smoothed away, matching this
session's standing discipline of reporting real data honestly over presenting a cleaner-looking
but partly invented curve. Buckets beyond 90s are held flat at the LAST measured bucket's own
values (winner_mult≈0.973, other_mult≈1.027, per `reports/phase7/nhl_faceoff_dz_decay_curve.json`)
rather than the general curve's 1.0/1.0 -- the DZ population never actually reached parity within
the measured window, so assuming full convergence beyond it would be extrapolation the general
curve's own 60-90s bucket (a 0.2% gap) did not need.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

# Real, measured marginal buckets (seconds since the faceoff, non-overlapping, each independently
# truncated at the next real EV faceoff). `winner_mult`/`other_mult` are the bucket's own raw
# shots/100s rate divided by the bucket's own average rate -- mean 1.0 by construction.
#
#   bucket        winner/100s  other/100s   winner_mult  other_mult
#   (0, 5]           1.1641      0.1628       1.7548       0.2452
#   (5, 10]          0.9305      0.3999       1.3987       0.6013
#   (10, 15]         0.9778      0.5994       1.2401       0.7599
#   (15, 20]         0.9053      0.7391       1.1013       0.8987
#   (20, 30]         0.8289      0.7582       1.0446       0.9554
#   (30, 45]         0.7228      0.7414       0.9874       1.0126
#   (45, 60]         0.6735      0.6636       1.0074       0.9926
#   (60, 90]         0.6569      0.6557       1.0009       0.9991
#
# `reports/phase7/nhl_faceoff_decay_curve.json` carries the raw counts behind every value here.
_DECAY_CURVE: List[Tuple[float, float, float, float]] = [
    # (lo, hi, winner_mult, other_mult)
    (0.0, 5.0, 1.7548, 0.2452),
    (5.0, 10.0, 1.3987, 0.6013),
    (10.0, 15.0, 1.2401, 0.7599),
    (15.0, 20.0, 1.1013, 0.8987),
    (20.0, 30.0, 1.0446, 0.9554),
    (30.0, 45.0, 0.9874, 1.0126),
    (45.0, 60.0, 1.0074, 0.9926),
    (60.0, 90.0, 1.0009, 0.9991),
]
_CONVERGED_MULT = 1.0  # beyond 90s: real data shows winner/other rates within 0.2% -- fully decayed

# Real, measured marginal buckets for draws the WINNER took in their own DEFENSIVE zone only
# (`winner_zone="D"`, 19,458 real draws -- roughly a third the general curve's sample per bucket,
# so more bucket-to-bucket noise is expected and reported as measured, not smoothed). Note the
# curve does NOT fully reconverge to 1.0 by the last measured bucket (unlike the general curve) --
# the (60,90] tail multipliers are held flat beyond 90s instead of assuming parity.
#
#   bucket        winner/100s  other/100s   winner_mult  other_mult
#   (0, 5]           0.0960      0.3976       0.3890       1.6110
#   (5, 10]          0.6002      0.6298       0.9759       1.0241
#   (10, 15]         0.8666      0.7488       1.0729       0.9271
#   (15, 20]         0.8174      0.8353       0.9892       1.0108
#   (20, 30]         0.7390      0.8712       0.9179       1.0821
#   (30, 45]         0.7230      0.7605       0.9748       1.0252
#   (45, 60]         0.6702      0.6871       0.9876       1.0124
#   (60, 90]         0.6257      0.6610       0.9726       1.0274
#
# `reports/phase7/nhl_faceoff_dz_decay_curve.json` carries the raw counts behind every value here.
_DZ_DECAY_CURVE: List[Tuple[float, float, float, float]] = [
    (0.0, 5.0, 0.3890, 1.6110),
    (5.0, 10.0, 0.9759, 1.0241),
    (10.0, 15.0, 1.0729, 0.9271),
    (15.0, 20.0, 0.9892, 1.0108),
    (20.0, 30.0, 0.9179, 1.0821),
    (30.0, 45.0, 0.9748, 1.0252),
    (45.0, 60.0, 0.9876, 1.0124),
    (60.0, 90.0, 0.9726, 1.0274),
]
_DZ_CONVERGED_MULT_WINNER = 0.9726  # held flat at the LAST measured bucket, not assumed parity --
_DZ_CONVERGED_MULT_OTHER = 1.0274   # see the module docstring's DZ section for why


@dataclass(frozen=True)
class SegmentFaceoffMultipliers:
    """The winner's and the other team's TIME-WEIGHTED AVERAGE shot-generation multiplier over one
    engine segment, assuming a single faceoff at the segment's start."""

    winner_mult: float
    other_mult: float


def _integrate_curve(
    seg_len_seconds: float,
    curve: List[Tuple[float, float, float, float]],
    *,
    converged_winner: float,
    converged_other: float,
) -> SegmentFaceoffMultipliers:
    """Integrate a real decay curve over `[0, seg_len_seconds]`, time-weighted, assuming the
    studied event occurs at the segment's start. Pure function, never raises -- a non-positive or
    non-finite `seg_len_seconds` returns the no-effect baseline (1.0, 1.0). Shared by both the
    general and DZ-specific curves so the integration logic itself is identical either way -- only
    the curve data and the tail-convergence values differ."""
    try:
        seg_len = float(seg_len_seconds)
    except (TypeError, ValueError):
        return SegmentFaceoffMultipliers(1.0, 1.0)
    if not (seg_len > 0.0):
        return SegmentFaceoffMultipliers(1.0, 1.0)

    winner_area = 0.0
    other_area = 0.0
    covered = 0.0

    for lo, hi, wm, om in curve:
        overlap_lo = max(lo, 0.0)
        overlap_hi = min(hi, seg_len)
        if overlap_hi <= overlap_lo:
            continue
        span = overlap_hi - overlap_lo
        winner_area += span * wm
        other_area += span * om
        covered += span

    if seg_len > covered:
        remaining = seg_len - covered
        winner_area += remaining * converged_winner
        other_area += remaining * converged_other
        covered += remaining

    if covered <= 0.0:
        return SegmentFaceoffMultipliers(1.0, 1.0)
    return SegmentFaceoffMultipliers(
        winner_mult=round(winner_area / covered, 6),
        other_mult=round(other_area / covered, 6),
    )


def segment_average_multipliers(seg_len_seconds: float) -> SegmentFaceoffMultipliers:
    """The general (EV/OZ-population) decay curve -- see the module docstring."""
    return _integrate_curve(
        seg_len_seconds, _DECAY_CURVE,
        converged_winner=_CONVERGED_MULT, converged_other=_CONVERGED_MULT,
    )


def segment_average_multipliers_dz(seg_len_seconds: float) -> SegmentFaceoffMultipliers:
    """The DZ-specific decay curve -- see the module docstring's DZ section. Note the direction is
    REVERSED relative to the general curve: `winner_mult < 1` and `other_mult > 1` in most buckets,
    since real data shows the team that wins its own DZ draw is OUT-SHOT, not out-shooting, in the
    following seconds."""
    return _integrate_curve(
        seg_len_seconds, _DZ_DECAY_CURVE,
        converged_winner=_DZ_CONVERGED_MULT_WINNER, converged_other=_DZ_CONVERGED_MULT_OTHER,
    )
