"""The resolver returns the RAW joint coefficient, and that is a measured choice.

HISTORY, because the next reader will otherwise re-derive the mistake. On
2026-09-05 the resolver was changed to convert its Spearman rank correlation of
COUNTS into a correlation of THRESHOLDED indicators before returning it. The
argument is correct in theory -- a parlay bets `hits > 0.5`, not hits, and under
a Gaussian copula phi(indicator) is only 54-68% of rho(counts).

IT WAS MEASURED OUT THE SAME NIGHT. Across 162,491 realised leg pairs, 151
games, 13 dates (2026-06-29..07-11), scored against whether both legs actually
won:

    same-player   RAW 0.52216   CONVERTED 0.52371
                  converted is WORSE by +0.00156, 95% CI [+0.00100, +0.00219]
    pooled        RAW 0.37086   CONVERTED 0.37091   (null)

A Gaussian copula over-attenuates for discrete, zero-inflated counts, so the raw
rank figure already sits closer to the true indicator correlation than the
conversion predicts.

AND THE FINDING THAT MOTIVATED THE CONVERSION DID NOT REPLICATE. It came from
SIX game clusters on a single date, where the joint appeared to LOSE to plain
independence. Across 149 clusters it BEATS independence by -0.02353,
CI [-0.02849, -0.01854].

THIS FILE EXISTS BECAUSE THE CONVERSION SHIPPED WITH NO TEST AT ALL. Nothing in
`tests/` referenced it, so reverting it was silently green -- and adding it had
been silently green too. A behaviour change on a live pricing path that no test
can see is the exact shape this repo's standards forbid.

`threshold_correlation.py` is deliberately KEPT. The reasoning is sound and a
future estimator fitted to discrete counts may want it; what is disqualified is
applying it to THIS estimator, on this evidence.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.mlb import sim_joint_correlation  # noqa: E402


def test_the_resolver_module_does_not_convert():
    """Source-level, deliberately. The behavioural test below needs a built
    index; this one fails the moment anyone re-adds the call, with no fixture."""
    src = Path(sim_joint_correlation.__file__).read_text(encoding="utf-8")
    assert "threshold_correlation(" not in src, (
        "the resolver is converting again -- measured WORSE on same-player "
        "(+0.00156, CI [+0.00100, +0.00219]) over 162,491 pairs. Re-run "
        "scripts/measure_joint_pair_pricing.py before reinstating it."
    )
    assert "candidate_probability(" not in src


def test_the_conversion_module_still_exists_and_still_attenuates():
    """Kept on purpose. The reasoning is correct; only its application here is
    disqualified, and deleting it would lose the record of why."""
    from syndicate.features.mlb.threshold_correlation import threshold_correlation

    phi = threshold_correlation(0.575, 0.30, 0.30)
    assert 0.0 < phi < 0.575, phi
    # The attenuation this module computes is REAL -- roughly two thirds --
    # which is exactly why it looked compelling on a small sample.
    assert 0.55 < phi / 0.575 < 0.80, phi / 0.575


def test_a_measured_zero_is_still_preserved_exactly():
    """Whatever the resolver returns, a measured independence must survive as
    0.0 rather than becoming an absence -- that distinction is what tells the
    sizer the heuristic was inventing dependence."""
    from syndicate.features.mlb.threshold_correlation import threshold_correlation

    assert threshold_correlation(0.0, 0.3, 0.3) == 0.0
