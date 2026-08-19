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


@dataclass(frozen=True)
class SegmentFaceoffMultipliers:
    """The winner's and the other team's TIME-WEIGHTED AVERAGE shot-generation multiplier over one
    engine segment, assuming a single faceoff at the segment's start."""

    winner_mult: float
    other_mult: float


def segment_average_multipliers(seg_len_seconds: float) -> SegmentFaceoffMultipliers:
    """Integrate the real decay curve over `[0, seg_len_seconds]`, time-weighted, assuming a
    faceoff occurs at the segment's start. Pure function, never raises -- a non-positive or
    non-finite `seg_len_seconds` returns the no-effect baseline (1.0, 1.0)."""
    try:
        seg_len = float(seg_len_seconds)
    except (TypeError, ValueError):
        return SegmentFaceoffMultipliers(1.0, 1.0)
    if not (seg_len > 0.0):
        return SegmentFaceoffMultipliers(1.0, 1.0)

    winner_area = 0.0
    other_area = 0.0
    covered = 0.0

    for lo, hi, wm, om in _DECAY_CURVE:
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
        winner_area += remaining * _CONVERGED_MULT
        other_area += remaining * _CONVERGED_MULT
        covered += remaining

    if covered <= 0.0:
        return SegmentFaceoffMultipliers(1.0, 1.0)
    return SegmentFaceoffMultipliers(
        winner_mult=round(winner_area / covered, 6),
        other_mult=round(other_area / covered, 6),
    )
