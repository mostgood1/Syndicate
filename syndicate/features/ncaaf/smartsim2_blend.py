"""ATS margin policy and totals blend for the legacy NCAAF engine and SmartSim 2.0.

ATS policy (see ``smartsim_betting_policy_report.md`` / this module's own
implementation report, ``smartsim_ats_policy_implementation_report.md``):
margin is **Engine's margin by default; SmartSim's margin specifically when
Engine and SmartSim pick opposite sides** (a side disagreement). This
replaces two earlier mechanisms in full: the fixed-weight margin blend
(``MARGIN_WEIGHT_ENGINE``/``MARGIN_WEIGHT_SMARTSIM``) and the large-mismatch
override from ``smartsim_policy_revision_report.md`` (Phase 4). Both were
justified by straight-up forecast accuracy; ``smartsim_betting_performance_report.md``
found that accuracy improvement does not reliably translate into ATS
profitability, and a direct real-game counterfactual in
``smartsim_betting_policy_report.md`` showed the large-mismatch override
measurably reduced ATS ROI in exactly the subset it targeted, while a
disagreement-triggered rule beat every alternative tested (including plain
Engine-only and plain SmartSim-only) in every category. This module
implements that finding. ``MARGIN_WEIGHT_ENGINE``, ``MARGIN_WEIGHT_SMARTSIM``,
and ``LARGE_MISMATCH_MARGIN_THRESHOLD`` are retained, unmodified, only
because other code still reads them (``blend_margin()`` for historical/
counterfactual reference, and ``smartsim2_performance_tracking.py``'s
independent ``large_mismatch`` reporting category) -- neither is used by
``compute_blend()`` any longer.

Totals policy is completely unchanged by this implementation: ``blend_total()``
and its weights/bias correction are untouched, still validated in
``smartsim_ensemble_evaluation_report.md`` and reconfirmed as the best totals
performer in every category in ``smartsim_betting_performance_report.md``.

This module does not modify SmartSim 2.0 or the legacy engine; it only
combines numbers each already produced.
"""

from __future__ import annotations

from dataclasses import dataclass

# Retained, unmodified: no longer read by compute_blend()'s margin decision,
# but blend_margin() (used for historical/counterfactual comparisons in
# smartsim_betting_policy_report.md) still depends on these values.
MARGIN_WEIGHT_ENGINE = 0.395
MARGIN_WEIGHT_SMARTSIM = 0.605
TOTAL_WEIGHT_ENGINE = 0.114
TOTAL_WEIGHT_SMARTSIM = 0.886

# SmartSim's measured systematic total-scoring bias (real-rating backtest,
# smartsim_integration_assessment.md) -- subtracted before blending totals.
# Totals policy is unchanged by the ATS policy implementation.
SMARTSIM_TOTAL_BIAS = 6.11

# Retained, unmodified: TOSSUP_MARGIN_THRESHOLD was never read by any
# conditional (a pre-existing, disclosed dead constant -- see
# smartsim_betting_policy_report.md's audit). LARGE_MISMATCH_MARGIN_THRESHOLD
# is still read by smartsim2_performance_tracking.py's own, independent
# "large_mismatch" reporting category; compute_blend() no longer uses it.
TOSSUP_MARGIN_THRESHOLD = 5.0
LARGE_MISMATCH_MARGIN_THRESHOLD = 10.0


@dataclass(frozen=True)
class BlendResult:
    margin: float
    total: float
    smartsim_margin_used: bool
    total_blended: bool


def blend_margin(engine_margin: float, smartsim_margin: float) -> float:
    """Retained for historical/counterfactual reference (see module docstring)
    -- no longer called by ``compute_blend()``."""
    return MARGIN_WEIGHT_ENGINE * engine_margin + MARGIN_WEIGHT_SMARTSIM * smartsim_margin


def blend_total(engine_total: float, smartsim_total: float) -> float:
    corrected_smartsim_total = smartsim_total - SMARTSIM_TOTAL_BIAS
    return TOTAL_WEIGHT_ENGINE * engine_total + TOTAL_WEIGHT_SMARTSIM * corrected_smartsim_total


def compute_blend(
    *,
    engine_margin: float,
    smartsim_margin: float,
    engine_total: float,
    smartsim_total: float,
) -> BlendResult:
    """ATS margin: Engine's margin by default; SmartSim's margin when the two
    sources pick opposite sides (``sign(engine_margin) != sign(smartsim_margin)``).
    Neither the large-mismatch threshold nor the fixed-weight blend factors
    into this decision at all -- see the module docstring for why.

    Totals: unchanged. ``blend_total()`` runs unconditionally, exactly as it
    always has.
    """
    side_disagreement = (engine_margin > 0) != (smartsim_margin > 0)
    margin = smartsim_margin if side_disagreement else engine_margin
    total = blend_total(engine_total, smartsim_total)
    return BlendResult(margin=margin, total=total, smartsim_margin_used=side_disagreement, total_blended=True)


__all__ = [
    "LARGE_MISMATCH_MARGIN_THRESHOLD",
    "MARGIN_WEIGHT_ENGINE",
    "MARGIN_WEIGHT_SMARTSIM",
    "SMARTSIM_TOTAL_BIAS",
    "TOSSUP_MARGIN_THRESHOLD",
    "TOTAL_WEIGHT_ENGINE",
    "TOTAL_WEIGHT_SMARTSIM",
    "BlendResult",
    "blend_margin",
    "blend_total",
    "compute_blend",
]
