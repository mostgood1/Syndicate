"""Tests for `scripts/mlb_win_expectancy.py` (`#454`, second half)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "mlb_win_expectancy",
    Path(__file__).resolve().parents[1] / "scripts" / "mlb_win_expectancy.py",
)
mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(mod)


def _dist(*probs: float) -> list[float]:
    """Pad a short run distribution out to the module's bucket width."""
    out = list(probs) + [0.0] * (mod._MAX_RUNS + 1 - len(probs))
    return out[: mod._MAX_RUNS + 1]


# --------------------------------------------------------------------------
# convolution
# --------------------------------------------------------------------------


def test_convolving_with_a_certain_zero_is_the_identity():
    a = [0.5, 0.3, 0.2]
    assert mod._convolve(a, [1.0]) == a


def test_convolution_adds_the_run_counts():
    """Two innings that each score exactly 1 must give exactly 2."""
    one = [0.0, 1.0]
    out = mod._convolve(one, one)
    assert out[2] == 1.0
    assert sum(out) == 1.0


def test_convolution_preserves_total_probability():
    a = [0.6, 0.3, 0.1]
    b = [0.5, 0.25, 0.25]
    assert abs(sum(mod._convolve(a, b)) - 1.0) < 1e-12


# --------------------------------------------------------------------------
# win probability
# --------------------------------------------------------------------------


def test_a_lead_that_cannot_be_overcome_is_a_certain_win():
    """Nobody scores again; home leads. Must be 1.0, not 'close to 1'."""
    none = [1.0]
    assert mod._win_probability(none, none, 3, extra_p=0.5) == 1.0
    assert mod._win_probability(none, none, -3, extra_p=0.5) == 0.0


def test_a_tie_with_no_scoring_left_resolves_to_the_extra_innings_constant():
    none = [1.0]
    assert mod._win_probability(none, none, 0, extra_p=0.5) == 0.5
    assert mod._win_probability(none, none, 0, extra_p=0.6) == 0.6
    # The constant must be USED, not ignored -- guards against a hardcoded 0.5.
    assert mod._win_probability(none, none, 0, extra_p=0.0) == 0.0


def test_win_probability_is_monotonic_in_the_margin():
    home = _dist(0.7, 0.2, 0.1)
    away = _dist(0.7, 0.2, 0.1)
    values = [mod._win_probability(home, away, m, extra_p=0.5) for m in range(-4, 5)]
    assert values == sorted(values)
    assert all(0.0 <= v <= 1.0 for v in values)


def test_symmetric_distributions_and_a_level_score_give_one_half():
    home = _dist(0.6, 0.25, 0.15)
    away = _dist(0.6, 0.25, 0.15)
    assert abs(mod._win_probability(home, away, 0, extra_p=0.5) - 0.5) < 1e-12


def test_a_better_offence_wins_more_at_the_same_score():
    weak = _dist(0.8, 0.15, 0.05)
    strong = _dist(0.4, 0.3, 0.3)
    assert mod._win_probability(strong, weak, 0, extra_p=0.5) > 0.5
    assert mod._win_probability(weak, strong, 0, extra_p=0.5) < 0.5


# --------------------------------------------------------------------------
# the composed table
# --------------------------------------------------------------------------


def _distributions(n: int = 5000) -> dict:
    fresh = _dist(0.72, 0.15, 0.07, 0.06)
    return {(state, outs): {"n": n, "p": fresh}
            for state in mod._STATE_ORDER for outs in (0, 1, 2)}


def test_build_table_refuses_without_a_usable_fresh_inning_distribution():
    """Everything is composed from the `---|0` cell; without it there is no table."""
    thin = {(s, o): {"n": 5, "p": _dist(1.0)} for s in mod._STATE_ORDER for o in (0, 1, 2)}
    out = mod.build_table(thin, extra_p=0.5, min_n=100)
    assert out["rows"] == []
    assert "error" in out


def test_thin_states_are_omitted_rather_than_estimated():
    dists = _distributions()
    dists[("123", 0)] = {"n": 12, "p": _dist(0.1, 0.9)}
    rows = mod.build_table(dists, extra_p=0.5, min_n=100)["rows"]
    assert not any(r["state"] == "123" and r["outs"] == 0 for r in rows)
    assert any(r["state"] == "123" and r["outs"] == 1 for r in rows)


def test_every_produced_row_is_a_probability():
    rows = mod.build_table(_distributions(), extra_p=0.5, min_n=100)["rows"]
    assert rows
    assert all(0.0 <= r["we"] <= 1.0 for r in rows)


def test_a_bigger_lead_never_lowers_win_expectancy():
    """Monotonicity across the whole composed table, not just one cell."""
    rows = mod.build_table(_distributions(), extra_p=0.5, min_n=100)["rows"]
    grouped: dict[tuple, list[tuple[int, float]]] = {}
    for row in rows:
        grouped.setdefault((row["inning"], row["half"], row["state"], row["outs"]), []).append(
            (row["margin"], row["we"])
        )
    for key, pairs in grouped.items():
        ordered = [we for _, we in sorted(pairs)]
        assert ordered == sorted(ordered), f"non-monotonic in margin at {key}"


def test_a_late_lead_is_worth_more_than_the_same_early_lead():
    """The whole point of an inning term: 3 up in the 9th beats 3 up in the 1st."""
    rows = {(r["inning"], r["half"], r["state"], r["outs"], r["margin"]): r["we"]
            for r in mod.build_table(_distributions(), extra_p=0.5, min_n=100)["rows"]}
    early = rows[(1, "top", "---", 0, 3)]
    late = rows[(9, "top", "---", 2, 3)]
    assert late > early
    assert late > 0.95


def test_symmetric_league_average_start_of_game_is_one_half():
    """With one shared run distribution and no home-field term, it MUST be 0.5.

    The published ~0.540 gap is the home-field advantage this model omits, and
    the script prints that rather than closing it with a fudge factor. If this
    ever drifts off 0.5, an asymmetry has crept in that nobody declared.
    """
    rows = {(r["inning"], r["half"], r["state"], r["outs"], r["margin"]): r["we"]
            for r in mod.build_table(_distributions(), extra_p=0.5, min_n=100)["rows"]}
    assert abs(rows[(1, "top", "---", 0, 0)] - 0.5) < 1e-9
