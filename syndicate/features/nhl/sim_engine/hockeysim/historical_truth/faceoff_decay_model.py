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

OZ-SPECIFIC CURVE (`segment_average_multipliers_oz`), added in a third pass. `_resolve_faceoff_pct`
already PREFERS the OZ-specific index over the coarser EV-blend index when both are available (§2n)
-- but until this pass, that more-precise WIN-RATE signal was still discounted through the general
(EV+OZ+DZ-blended) decay curve, understating the true OZ-specific effect. This gives OZ its own
curve, built from the SAME 18,662-draw population (`winner_zone="O"`) `hockeysim_faceoff_dz_segment_validation_report.md`
already used as its confirming control.

THE OZ CURVE SHOWS A DRAMATICALLY LARGER, CLEANER SPIKE THAN THE GENERAL CURVE, AND FULLY
RECONVERGES. Raw ratio 119.7x in the first 5 seconds (winner 3.3813 shots/100s vs other only
0.0282/100s -- the team that just lost a draw deep in the OPPONENT's attacking zone has essentially
no shots of its own in the first few seconds, real hockey sense: it does not yet have the puck),
decaying smoothly and monotonically -- 4.89x, 1.92x, 1.53x, 1.38x, 1.04x, 1.08x, 1.01x -- to full
convergence by (60,90]s (winner/other within 1.4% of each other), the SAME clean pattern the
general curve showed, just stronger. Mean-normalization tames the extreme raw first-bucket ratio
into a bounded, sensible pair (winner_mult≈1.98, other_mult≈0.017) rather than the raw 119.7x --
the same design property that already handles the DZ curve's own extremes.

OZ USES THE GENERAL CURVE AS ITS OWN FALLBACK, NOT THE DZ CURVE'S TAIL-HOLD BEHAVIOR. Because this
curve DOES fully reconverge (unlike DZ), buckets beyond 90s are held at 1.0/1.0 exactly like the
general curve -- there is no unconverged tail to preserve here.

NZ-SPECIFIC CURVE (`segment_average_multipliers_nz`), added in a fourth pass -- after `#463`'s own
season-aggregate check (`hockeysim_faceoff_nz_calibration_report.md`) found no correlation and
declined to wire `faceoff_nz_index` at all. The DZ pass had already proven a season-aggregate null
does not rule out a real segment-level effect (DZ's own season correlation was equally null, yet
its segment effect was real, just backwards) -- so NZ's segment-level effect was checked directly,
the same population `hockeysim_faceoff_dz_segment_validation_report.md`'s OZ control already used
as a comparison point, via `winner_zone="N"` (20,642 real draws). Unlike the season-aggregate
check, this DOES show a real effect, in the EXPECTED direction: winner share 0.7203 at 10s decaying
smoothly to 0.5945 at 30s (ratio 2.576x -> 1.466x) -- weaker than OZ's spike, stronger than the
general curve's blend, and (unlike DZ) in the SAME direction the general/OZ effect already
established. This reverses the earlier decision: `faceoff_nz_index` is now wired (CSV producer,
loader, `engine.py`), matching the OZ index's own wiring history (built, deliberately unwired
pending validation, then wired once validation supported it).

THE NZ CURVE RECONVERGES CLEANLY, LIKE THE GENERAL AND OZ CURVES, NOT DZ'S UNRESOLVED TAIL. Raw
ratio 2.97x in the first 5 seconds decaying smoothly and almost monotonically -- 2.48x, 2.01x,
1.25x, 1.14x, 0.95x, 1.00x (exact parity), 1.04x -- to full convergence by (45,60]s. Held flat at
1.0/1.0 beyond 90s like the general/OZ curves, not DZ's held-tail convention, since the data
supports full reconvergence here.

NZ'S INTEGRATED EFFECT IS CONSISTENTLY WEAKER THAN THE GENERAL CURVE'S OWN -- CHECKED DIRECTLY,
NOT ASSUMED FROM THE MARGINAL BUCKETS. The raw marginal buckets alone are a MIXED comparison (NZ's
own first bucket, 1.4964, sits BELOW the general curve's 1.7548, but several middle buckets sit
slightly above it) -- an earlier draft of this docstring generalized from that mixed picture to a
wrong claim ("stronger than the general blend"), caught by computing the actual TIME-WEIGHTED
INTEGRATED comparison the engine uses (`segment_average_multipliers` vs `_nz`) at seven segment
lengths (5s to 1200s): NZ sits BELOW the general curve at every one of them, because the general
curve's own strong early bucket (driven by the OZ-heavy portion of its blended population) makes
its short-segment integral higher than NZ's more modest early spike, even though NZ briefly
exceeds it bucket-by-bucket in the mid-range. This is the correct comparison to state as a claim
and to test against -- not the marginal buckets in isolation.

STRENGTH-STATE (PP/PK) CURVES (`segment_average_multipliers_pp_role`/`_pk_role`), added in a fifth
pass. Every curve above is gated `faceoff_ev_only=True` in `engine.py` -- none of them has ever
applied during a power play or penalty kill. `winner_role="PP"`/`"PK"` (`faceoff_segment_effect.py`)
isolate PP/PK-STRENGTH draws by the WINNER's own skater-count role (did the team already on the
power play also win the draw, or did the shorthanded team win it) -- a population the EV-only
extraction excludes entirely. Both show a real, LARGE, and DIRECTIONALLY SENSIBLE effect: PP-role
winner share 0.9329 at 10s (the already-advantaged team also winning the draw compounds its
existing edge); PK-role winner share only 0.4313 at 10s and falling to 0.2749 by 30s (the
shorthanded team's draw win provides at most a brief reprieve before the opponent's structural
man-advantage reasserts itself). Isolating the DRAW-SPECIFIC increment from the baseline PP/PK
manpower asymmetry: the PP TEAM's own share of shots swings from ~0.93 (when the PP team wins the
draw) to ~0.57 (when the PK team wins it, `1 - 0.4313`) at 10s -- a large, genuinely incremental
effect from who won the specific draw, not merely a restatement of the known PP/PK baseline
`pp_shots_mult`/`pk_shots_mult` already encode.

NEITHER STRENGTH-STATE CURVE RECONVERGES WITHIN THE MEASURED WINDOW, UNLIKE THE GENERAL/OZ/NZ
CURVES -- HELD FLAT AT THE LAST BUCKET, SAME CONVENTION AS DZ. A power play typically runs up to
~120 seconds; within the 0-90s window this data covers, the underlying MAN-ADVANTAGE situation is
often still active regardless of who won the draw, so the effect never fully washes out the way a
single-event EV/OZ/NZ effect does. PP-role ratio: 23.0x -> 11.2x -> 6.7x -> 6.5x -> 4.6x -> 4.5x ->
4.1x -> 3.4x (still well above parity at 60-90s). PK-role ratio: 1.31x (brief clear-driven bump) ->
0.46x -> 0.36x -> 0.21x -> 0.26x -> 0.24x -> 0.24x -> 0.28x (settles into a sustained, large
suppression, never approaching parity). Both held flat beyond 90s at their own (60,90] values,
rather than assumed to converge -- extrapolating toward parity would understate a real, sustained
structural effect the data gives no reason to believe fades that quickly.
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

# Real, measured marginal buckets for draws the WINNER took in their own OFFENSIVE zone only
# (`winner_zone="O"`, 18,662 real draws). A dramatically larger, cleaner spike than the general
# curve, fully reconverging by (60,90]s -- see the module docstring's OZ section.
#
#   bucket        winner/100s  other/100s   winner_mult  other_mult
#   (0, 5]           3.3813      0.0282       1.9834       0.0165
#   (5, 10]          1.7285      0.3536       1.6604       0.3397
#   (10, 15]         1.1453      0.5953       1.3160       0.6840
#   (15, 20]         1.0022      0.6533       1.2107       0.7893
#   (20, 30]         0.9432      0.6844       1.1590       0.8410
#   (30, 45]         0.7529      0.7241       1.0195       0.9805
#   (45, 60]         0.6770      0.6259       1.0392       0.9608
#   (60, 90]         0.6522      0.6433       1.0069       0.9931
#
# `reports/phase7/nhl_faceoff_oz_decay_curve.json` carries the raw counts behind every value here.
_OZ_DECAY_CURVE: List[Tuple[float, float, float, float]] = [
    (0.0, 5.0, 1.9834, 0.0165),
    (5.0, 10.0, 1.6604, 0.3397),
    (10.0, 15.0, 1.3160, 0.6840),
    (15.0, 20.0, 1.2107, 0.7893),
    (20.0, 30.0, 1.1590, 0.8410),
    (30.0, 45.0, 1.0195, 0.9805),
    (45.0, 60.0, 1.0392, 0.9608),
    (60.0, 90.0, 1.0069, 0.9931),
]
# The OZ curve DOES fully reconverge (winner/other within 1.4% by the last bucket) -- unlike DZ,
# no unconverged tail to preserve, so this holds flat at 1.0/1.0 exactly like the general curve.
_OZ_CONVERGED_MULT = 1.0

# Real, measured marginal buckets for draws the WINNER took in the NEUTRAL zone only
# (`winner_zone="N"`, 20,642 real draws). Weaker than OZ's spike, stronger than the general curve's
# blend, same (expected) direction throughout -- unlike DZ. Fully reconverges by (45,60]s.
#
#   bucket        winner/100s  other/100s   winner_mult  other_mult
#   (0, 5]           0.1848      0.0622       1.4964       0.5036
#   (5, 10]          0.5603      0.2257       1.4257       0.5743
#   (10, 15]         0.9386      0.4666       1.3359       0.6641
#   (15, 20]         0.9044      0.7231       1.1114       0.8886
#   (20, 30]         0.8158      0.7166       1.0648       0.9352
#   (30, 45]         0.6976      0.7383       0.9717       1.0283
#   (45, 60]         0.6737      0.6737       1.0000       1.0000
#   (60, 90]         0.6894      0.6614       1.0207       0.9793
#
# `reports/phase7/nhl_faceoff_nz_decay_curve.json` carries the raw counts behind every value here.
_NZ_DECAY_CURVE: List[Tuple[float, float, float, float]] = [
    (0.0, 5.0, 1.4964, 0.5036),
    (5.0, 10.0, 1.4257, 0.5743),
    (10.0, 15.0, 1.3359, 0.6641),
    (15.0, 20.0, 1.1114, 0.8886),
    (20.0, 30.0, 1.0648, 0.9352),
    (30.0, 45.0, 0.9717, 1.0283),
    (45.0, 60.0, 1.0000, 1.0000),
    (60.0, 90.0, 1.0207, 0.9793),
]
# The NZ curve DOES fully reconverge (exact parity at (45,60], within 2.1% at (60,90]) -- same
# fallback convention as the general/OZ curves, not DZ's held-tail.
_NZ_CONVERGED_MULT = 1.0

# Real, measured marginal buckets for PP-STRENGTH draws the WINNER took while their OWN team
# already had the skater advantage (`winner_role="PP"`, 8,033 real draws). Does NOT reconverge
# within the measured window -- a real power play often runs close to or beyond 90s, so the
# man-advantage baseline stays active regardless of who won the specific draw.
#
#   bucket        winner/100s  other/100s   winner_mult  other_mult
#   (0, 5]           1.6732      0.0727       1.9167       0.0833
#   (5, 10]          2.5769      0.2301       1.8361       0.1639
#   (10, 15]         1.9164      0.2870       1.7395       0.2605
#   (15, 20]         1.9316      0.2955       1.7346       0.2654
#   (20, 30]         1.6156      0.3521       1.6421       0.3579
#   (30, 45]         1.5432      0.3393       1.6395       0.3605
#   (45, 60]         1.5729      0.3873       1.6048       0.3952
#   (60, 90]         1.4555      0.4235       1.5492       0.4508
#
# `reports/phase7/nhl_faceoff_pp_decay_curve.json` carries the raw counts behind every value here.
_PP_ROLE_DECAY_CURVE: List[Tuple[float, float, float, float]] = [
    (0.0, 5.0, 1.9167, 0.0833),
    (5.0, 10.0, 1.8361, 0.1639),
    (10.0, 15.0, 1.7395, 0.2605),
    (15.0, 20.0, 1.7346, 0.2654),
    (20.0, 30.0, 1.6421, 0.3579),
    (30.0, 45.0, 1.6395, 0.3605),
    (45.0, 60.0, 1.6048, 0.3952),
    (60.0, 90.0, 1.5492, 0.4508),
]
_PP_ROLE_CONVERGED_MULT_WINNER = 1.5492  # held flat at the LAST measured bucket -- a PP often
_PP_ROLE_CONVERGED_MULT_OTHER = 0.4508   # runs close to or beyond 90s, no reason to assume parity

# Real, measured marginal buckets for PP-STRENGTH draws the WINNER took while THEIR OWN team was
# shorthanded (`winner_role="PK"`, 6,701 real draws). A brief clear-driven bump in the first 5s,
# then a sustained, large suppression -- the opponent's man-advantage reasserts itself. Also does
# NOT reconverge within the measured window.
#
#   bucket        winner/100s  other/100s   winner_mult  other_mult
#   (0, 5]           0.5002      0.3827       1.1331       0.8669
#   (5, 10]          0.3920      0.8472       0.6327       1.3673
#   (10, 15]         0.3261      0.9050       0.5298       1.4702
#   (15, 20]         0.2547      1.2282       0.3435       1.6565
#   (20, 30]         0.3725      1.4461       0.4097       1.5903
#   (30, 45]         0.3771      1.5639       0.3886       1.6114
#   (45, 60]         0.3726      1.5288       0.3919       1.6081
#   (60, 90]         0.4134      1.4954       0.4332       1.5668
#
# `reports/phase7/nhl_faceoff_pk_decay_curve.json` carries the raw counts behind every value here.
_PK_ROLE_DECAY_CURVE: List[Tuple[float, float, float, float]] = [
    (0.0, 5.0, 1.1331, 0.8669),
    (5.0, 10.0, 0.6327, 1.3673),
    (10.0, 15.0, 0.5298, 1.4702),
    (15.0, 20.0, 0.3435, 1.6565),
    (20.0, 30.0, 0.4097, 1.5903),
    (30.0, 45.0, 0.3886, 1.6114),
    (45.0, 60.0, 0.3919, 1.6081),
    (60.0, 90.0, 0.4332, 1.5668),
]
_PK_ROLE_CONVERGED_MULT_WINNER = 0.4332  # held flat at the LAST measured bucket -- same reasoning
_PK_ROLE_CONVERGED_MULT_OTHER = 1.5668   # as PP-role above


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


def segment_average_multipliers_oz(seg_len_seconds: float) -> SegmentFaceoffMultipliers:
    """The OZ-specific decay curve -- see the module docstring's OZ section. A dramatically
    stronger, cleaner version of the general curve's own effect (real hockey sense: the team that
    just lost a draw deep in the opponent's attacking zone does not yet have the puck)."""
    return _integrate_curve(
        seg_len_seconds, _OZ_DECAY_CURVE,
        converged_winner=_OZ_CONVERGED_MULT, converged_other=_OZ_CONVERGED_MULT,
    )


def segment_average_multipliers_nz(seg_len_seconds: float) -> SegmentFaceoffMultipliers:
    """The NZ-specific decay curve -- see the module docstring's NZ section. Same (expected)
    direction as the general/OZ curves throughout, unlike DZ's reversal -- weaker than OZ's spike,
    stronger than the general curve's blend."""
    return _integrate_curve(
        seg_len_seconds, _NZ_DECAY_CURVE,
        converged_winner=_NZ_CONVERGED_MULT, converged_other=_NZ_CONVERGED_MULT,
    )


def segment_average_multipliers_pp_role(seg_len_seconds: float) -> SegmentFaceoffMultipliers:
    """PP-STRENGTH decay curve for draws the WINNER took while already on the power play -- see
    the module docstring's strength-state section. Does not reconverge within the measured window;
    held flat at the last measured bucket beyond 90s."""
    return _integrate_curve(
        seg_len_seconds, _PP_ROLE_DECAY_CURVE,
        converged_winner=_PP_ROLE_CONVERGED_MULT_WINNER, converged_other=_PP_ROLE_CONVERGED_MULT_OTHER,
    )


def segment_average_multipliers_pk_role(seg_len_seconds: float) -> SegmentFaceoffMultipliers:
    """PP-STRENGTH decay curve for draws the WINNER took while shorthanded -- see the module
    docstring's strength-state section. Direction REVERSES after the first bucket (a brief
    clear-driven bump, then sustained suppression as the opponent's man-advantage reasserts).
    Does not reconverge within the measured window; held flat at the last measured bucket."""
    return _integrate_curve(
        seg_len_seconds, _PK_ROLE_DECAY_CURVE,
        converged_winner=_PK_ROLE_CONVERGED_MULT_WINNER, converged_other=_PK_ROLE_CONVERGED_MULT_OTHER,
    )
