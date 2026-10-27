"""`scripts/ev_lb_funnel_read.py`: the bucket split is exactly the ev_lb qualify condition, and the summary counts."""
import importlib.util
from pathlib import Path

from syndicate.features.shared import decision_policy_v1 as dp

_SPEC = importlib.util.spec_from_file_location(
    "ev_lb_funnel_read", Path(__file__).resolve().parents[1] / "scripts" / "ev_lb_funnel_read.py")
funnel = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(funnel)


def test_bucket_boundaries():
    assert funnel.bucket(0.0, 0.017, 0.01) == "A_no_raw_edge"
    assert funnel.bucket(-0.02, 0.017, 0.01) == "A_no_raw_edge"
    assert funnel.bucket(0.017, 0.017, 0.01) == "B_fee_eats"
    assert funnel.bucket(0.027, 0.017, 0.01) == "C_haircut_eats"
    assert funnel.bucket(0.0271, 0.017, 0.01) == "D_qualifies"


def test_d_bucket_is_the_policy_qualify_condition():
    """D <=> EV_lb > 0 as decision_policy_v1 computes it, on a grid of prices, fees and sigmas."""
    for p in (0.3, 0.5, 0.62):
        for ask in (0.25, 0.45, 0.5, 0.6):
            for fee in (0.0, 0.0087, 0.0175):
                for sigma in (0.0, 0.05, 0.2):
                    p_lb = dp.sigmoid(dp.logit(p) - 1.0 * sigma)
                    ev_lb_pos = p_lb / (ask + fee) - 1.0 > 0
                    b = funnel.bucket(p - ask, fee, p - p_lb)
                    assert (b == "D_qualifies") == ev_lb_pos, (p, ask, fee, sigma, b)


def test_summarise_counts_and_counterfactuals():
    rows = [
        {"bucket": "A_no_raw_edge", "g": -0.01, "fee": 0.017, "h": 0.01},
        {"bucket": "B_fee_eats", "g": 0.01, "fee": 0.017, "h": 0.01},
        {"bucket": "C_haircut_eats", "g": 0.02, "fee": 0.017, "h": 0.01},
        {"bucket": "C_haircut_eats", "g": 0.025, "fee": 0.017, "h": 0.01},
    ]
    s = funnel.summarise(rows)
    assert s["n"] == 4
    assert s["buckets"]["C_haircut_eats"] == [2, 50.0]
    assert s["buckets"]["D_qualifies"] == [0, 0.0]
    assert s["net_ev_pos"] == 2
    assert s["at_half_haircut"] == 1  # 0.025 > 0.017 + 0.005; 0.02 is not
