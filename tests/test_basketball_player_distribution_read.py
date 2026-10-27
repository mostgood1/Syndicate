"""Phase 1 readout of lane basketball-player-distribution: the PIT / coverage arithmetic and the flag rule."""
from __future__ import annotations

import numpy as np

from scripts import basketball_player_distribution_read as r


def _rows(sim_scale: float, n_games: int = 300, per_game: int = 8, seed: int = 1):
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        for _ in range(per_game):
            draws = rng.normal(20.0, 5.0 * sim_scale, 200)
            y = rng.normal(20.0, 5.0)
            rows.append({"game": g, "u": r.pit(draws, y, rng.random()), "err": y - draws.mean(), "sd": draws.std()})
    return rows


def test_pit_is_randomised_on_ties():
    assert r.pit([1, 2, 2, 3], 2, 0.0) == 0.25 and r.pit([1, 2, 2, 3], 2, 1.0) == 0.75


def test_calibrated_sim_reads_nominal_and_is_not_flagged():
    c = r.cell_summary(_rows(1.0), np.random.default_rng(0), n_boot=300)
    assert abs(c["miss"] - 0.20) < 0.03 and abs(c["width_ratio"] - 1.0) < 0.05
    assert not r.flagged(c)


def test_narrow_sim_is_flagged_with_width_above_one():
    c = r.cell_summary(_rows(0.6), np.random.default_rng(0), n_boot=300)
    assert c["miss"] > 0.30 and c["width_ratio"] > 1.5
    assert r.flagged(c)


def test_norm_strips_suffixes_and_accents():
    assert r.norm("Hugo González Jr.") == "hugo gonzalez"


def test_join_rule_matches_name_variants():
    assert r.names_match(r.norm("Nicolas Claxton"), r.norm("Nic Claxton"))
    assert r.names_match(r.norm("Herb Jones"), r.norm("Herbert Jones"))
    assert not r.names_match(r.norm("Jalen Williams"), r.norm("Kenrich Williams"))
    # Known limitation of the pre-registered rule (bf73ce71): same last name + first initial also matches real
    # teammates. It can only misfire when one is sim-only and the other real-only in the same game.
    assert r.names_match(r.norm("Jalen Williams"), r.norm("Jaylin Williams"))


def test_absent_classes_by_real_box_timeline():
    # Step 1b (7eaaa4ef): the sim put the player on IND on 11-01.
    assert r.classify_absent([("2025-10-25", "LAC"), ("2026-02-10", "IND")], "IND", "2025-11-01") == "LEAK_FUTURE"
    assert r.classify_absent([("2025-10-25", "IND"), ("2025-11-05", "LAC")], "IND", "2025-11-01") == "STALE_PAST"
    assert r.classify_absent([("2025-10-25", "IND"), ("2025-11-05", "IND")], "IND", "2025-11-01") == "T_AROUND"
    assert r.classify_absent([("2026-01-05", "IND")], "IND", "2025-11-01") == "T_ONLY_AFTER_NO_OTHER"
    assert r.classify_absent([("2025-10-25", "IND")], "IND", "2025-11-01") == "T_ONLY_BEFORE_NO_OTHER"
    assert r.classify_absent([("2025-11-01", "LAC")], "IND", "2025-11-01") == "NEVER_T_OTHER_TEAM"
    assert r.classify_absent([], "IND", "2025-11-01") == "NO_BOX"


def test_real_only_classes_by_sim_roster_dates():
    assert r.classify_real_only([], "2025-11-10") == "SIM_NEVER_T"
    assert r.classify_real_only(["2025-12-01"], "2025-11-10") == "SIM_LATER_ONLY"
    assert r.classify_real_only(["2025-11-01"], "2025-11-10") == "SIM_EARLIER_ONLY"
    assert r.classify_real_only(["2025-11-01", "2025-12-01"], "2025-11-10") == "SIM_AROUND"
