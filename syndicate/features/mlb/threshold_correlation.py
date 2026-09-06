"""Convert a rank correlation of COUNTS into a correlation of THRESHOLDED bets.

THE UNIT ERROR THIS FIXES, measured 2026-09-05 on 6,396 realised leg pairs
(`scripts/measure_joint_pair_pricing.py`). The MLB sim's joint publishes
SPEARMAN RANK CORRELATION OF COUNTS -- how a batter's hits move with his total
bases across 1,000 simulations. A parlay does not bet counts. It bets
`hits > 0.5` AND `total_bases > 1.5`, so what it needs is the correlation of the
two THRESHOLDED INDICATORS at the traded lines. Those are different quantities,
and thresholding ATTENUATES dependence:

    p=0.30, rho_S=0.575  ->  phi = 0.374   (65% of rho)
    p=0.20, rho_S=0.575  ->  phi = 0.350   (61%)
    p=0.45, rho_S=0.300  ->  phi = 0.193   (64%)

So feeding `rho_S` straight into a joint-probability estimator overstates
dependence by roughly 1.5-1.9x. Measured consequence: the joint BEAT the
hand-authored heuristic it replaced (-0.027 log-loss) and LOST to plain
independence (+0.007 pooled, +0.101 same-player with the parlay cap lifted) --
and lost MONOTONICALLY MORE the further the estimator was allowed to move,
because a bigger allowance lets more of the overstatement through.

THE CONVERSION. Under a Gaussian copula, which is the standard reference for
exactly this problem:

    rho_gauss = 2 * sin(pi * rho_spearman / 6)          Spearman -> copula
    z_p       = Phi^-1(1 - p)                            upper-tail threshold
    phi       = (P(Z_A > z_A, Z_B > z_B) - p_A*p_B) / sqrt(p_A q_A p_B q_B)

WHY THIS LIVES IN THE RESOLVER AND NOT IN THE SIM. The conversion needs the
MARGINALS at the traded line. The sim does not know the line -- lines arrive
from the book long after the simulation runs, and the same distribution is
priced against several rungs. The marginals ARE available where the price is
formed. So the sim publishes the line-free quantity it can actually compute, and
the conversion happens at the point of use.

A GAUSSIAN COPULA IS AN ASSUMPTION, and it is stated rather than hidden. Real
count outcomes are discrete, skewed and zero-inflated, so the true attenuation
is not exactly this. But the correction is ~1.5-1.9x and the copula's own error
across the plausible marginal range is far smaller than that, so applying it
gets closer than not applying it. The alternative -- assuming no attenuation --
is the thing that was measured to lose to independence.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Optional

#: Used when a marginal is unavailable. The attenuation ratio is remarkably
#: stable across the marginals actually seen on this board (54-68% over
#: p in 0.20..0.45, rho in 0.30..0.575), so a fixed factor carries bounded error
#: -- and far less error than the 1.5-1.9x overstatement of applying none.
#: A pair with no marginal is still better served by an attenuated coefficient
#: than by the heuristic it would otherwise fall back to, which overstates
#: cross-player dependence ~17x (+0.530 asserted against +0.031 measured).
_FALLBACK_ATTENUATION = 0.60

#: Gauss-Legendre nodes for the tail integral. 48 is far more than the
#: 3-decimal cache key can resolve, so accuracy is bounded by the rounding.
_QUAD_N = 48


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal. Acklam's rational approximation, |err| < 1.15e-9."""
    if p <= 0.0:
        return -40.0
    if p >= 1.0:
        return 40.0
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


@lru_cache(maxsize=200_000)
def _bvn_upper(z_a: float, z_b: float, rho: float) -> float:
    """P(Z_A > z_a, Z_B > z_b) for standard bivariate normal with correlation rho.

    Cached because `compute_correlation` is O(n^2) over a candidate set and
    carries `warn_if_compute_in_request_path` -- an uncached quadrature per pair
    would be a real cost. Keys are rounded by the caller.
    """
    if rho >= 0.999999:
        return 1.0 - _norm_cdf(max(z_a, z_b))
    if rho <= -0.999999:
        tail = 1.0 - _norm_cdf(z_a) - _norm_cdf(z_b)
        return max(0.0, tail)
    if abs(rho) < 1e-9:
        return (1.0 - _norm_cdf(z_a)) * (1.0 - _norm_cdf(z_b))
    # Integrate P(Z_B > z_b | Z_A = z) * phi(z) over z > z_a.
    lo, hi = z_a, max(z_a + 1e-9, z_a + 12.0)
    total = 0.0
    root = math.sqrt(1.0 - rho * rho)
    for i in range(_QUAD_N):
        u = (i + 0.5) / _QUAD_N
        z = lo + (hi - lo) * u
        dens = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
        total += dens * (1.0 - _norm_cdf((z_b - rho * z) / root))
    return max(0.0, min(1.0, total * (hi - lo) / _QUAD_N))


def spearman_to_gaussian(rho_spearman: float) -> float:
    """Spearman rank correlation -> Gaussian copula correlation."""
    r = max(-1.0, min(1.0, float(rho_spearman)))
    return max(-1.0, min(1.0, 2.0 * math.sin(math.pi * r / 6.0)))


def threshold_correlation(
    rho_spearman: float,
    p_a: Optional[float],
    p_b: Optional[float],
) -> float:
    """Correlation of the two OVER indicators, given the counts' rank correlation.

    Returns the attenuated coefficient. When either marginal is missing or
    degenerate, falls back to a fixed attenuation rather than to the RAW value:
    returning the raw rank correlation is the specific error this module exists
    to correct, so it must not be the fallback.
    """
    rho = max(-1.0, min(1.0, float(rho_spearman)))
    if abs(rho) < 1e-9:
        # Independence in ranks is independence in indicators. Preserve the
        # exact zero -- it is a measurement, and a large one.
        return 0.0
    def _ok(p):
        return p is not None and 1e-4 < float(p) < 1.0 - 1e-4
    if not (_ok(p_a) and _ok(p_b)):
        return rho * _FALLBACK_ATTENUATION
    pa, pb = float(p_a), float(p_b)
    key_rho = round(spearman_to_gaussian(rho), 3)
    z_a = round(_norm_ppf(1.0 - pa), 3)
    z_b = round(_norm_ppf(1.0 - pb), 3)
    joint = _bvn_upper(z_a, z_b, key_rho)
    denom = math.sqrt(pa * (1.0 - pa) * pb * (1.0 - pb))
    if denom <= 0.0:
        return rho * _FALLBACK_ATTENUATION
    phi = (joint - pa * pb) / denom
    return max(-1.0, min(1.0, phi))


def candidate_probability(candidate) -> Optional[float]:
    """The marginal a candidate carries, read the way the parlay pricer reads it.

    Same field order as `intelligence_parlay_runtime._candidate_parlay_probability`
    on purpose: the conversion must use the SAME number the estimator will
    combine, or the attenuation is computed for a different bet than the one
    being priced.
    """
    if not isinstance(candidate, dict):
        return None
    for key in ("model_probability", "fair_probability", "confidence"):
        raw = candidate.get(key)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 1.0:
            value /= 100.0
        if 0.0 < value < 1.0:
            return value
    return None
