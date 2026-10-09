import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "mlb_bettingv2"))

import mlb_game_line_config_ab as ab  # noqa: E402


def test_crps_perfect_point_mass_is_zero():
    assert ab.crps_discrete(Counter({7: 10}), 10, 7) == 0.0


def test_crps_penalises_distance():
    near = ab.crps_discrete(Counter({7: 10}), 10, 8)
    far = ab.crps_discrete(Counter({7: 10}), 10, 12)
    assert 0 < near < far
    assert far == 5.0  # point mass at 7, outcome 12: F=1 vs 0 on k=7..11


def test_arms_differ_only_in_pitch_model():
    assert ab.arm_pm("none") == {}
    fwd = ab.arm_pm("fwd")
    assert "hr_rate_mult" in fwd and not any(k.startswith("_") for k in fwd)


def test_paired_sign_is_fwd_minus_none():
    rows = [{"none": {"x": 1.0}, "fwd": {"x": 0.5}}, {"none": {"x": 2.0}, "fwd": {"x": 1.0}}]
    p = ab.paired(rows, "x")
    assert p["diff_fwd_minus_none"] == -0.75 and p["ci95"][0] < p["ci95"][1]


def test_actual_from_linescore():
    ls = {"teams": {"away": {"runs": 3}, "home": {"runs": 5}},
          "innings": [{"away": {"runs": 1}, "home": {"runs": 0}}] * 5 + [{"away": {"runs": 0}, "home": {"runs": 2}}] * 4}
    box = {"teams": {"away": {"teamStats": {"batting": {"homeRuns": 1}}},
                     "home": {"teamStats": {"batting": {"homeRuns": 2}}}}}
    a = ab.actual_from_linescore(ls, box)
    assert a == {"total": 8, "home_win": 1.0, "f5": 5, "hr": 3}
