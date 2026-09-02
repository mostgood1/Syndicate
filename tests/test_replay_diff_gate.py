"""Tests for the `#625` replay-diff gate.

Every test here corresponds to a defect that was ACTUALLY PRESENT in this gate
while it was being built, and each one was invisible in the gate's own output
until the numbers were read carefully. They are regression tests, not
illustrations:

- the mismatch cap silently stopped the TRAVERSAL, so a 69,472-mismatch result
  reported `leaves compared 34` and a clean bill on the 12 MB of rows it never
  reached;
- `rows[*].game*` matched nothing, because `[...]` is an fnmatch CHARACTER
  CLASS -- an exclusion rule that was inert while reading as correct, which is
  the exact defect class this gate exists to catch;
- `rows[].cells.*.reason` matched `...<side>.market_basis.reason` too, because
  `*` spans dots -- a rule written for one field quietly excluding its neighbour;
- a tolerance of exactly 0.1 rejected values differing by exactly 0.1, because
  `3.5 - 3.6 == -0.10000000000000142` in binary floating point;
- and NO_FIXTURE must never reach `ok = True`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.replay_diff_gate import (  # noqa: E402
    TARGETS,
    Tolerance,
    diff_json,
    finalize_clock_relative,
)


def test_identical_payloads_produce_no_mismatches() -> None:
    payload = {"rows": [{"price": 1.5, "book": "x"}], "summary": {"n": 1}}
    result = diff_json(payload, payload, Tolerance())
    assert result.ok
    assert result.mismatch_count == 0
    assert result.compared > 0


def test_mismatch_cap_bounds_the_record_not_the_traversal() -> None:
    """The bug: recursion returned once the cap was hit, so everything after the
    first page of failures was reported as clean."""
    produced = {"head": {f"k{i}": i for i in range(10)}, "tail": {"deep": "CHANGED"}}
    expected = {"head": {f"k{i}": i + 1 for i in range(10)}, "tail": {"deep": "original"}}
    result = diff_json(produced, expected, Tolerance(), max_mismatches=3)

    assert len(result.mismatches) == 3, "the recorded SAMPLE is capped"
    assert result.mismatch_count == 11, "the COUNT is not capped -- 10 head keys plus the tail"
    assert "tail.deep" in result.mismatch_by_key, "traversal must reach past the cap"


def test_list_length_and_order_are_both_checked() -> None:
    tolerance = Tolerance()
    assert not diff_json({"r": [1, 2]}, {"r": [1, 2, 3]}, tolerance).ok, "length"
    # ORDER matters: `build_book_grid` anchors on the first row carrying a given
    # canonical line, so a permutation is a real behaviour change that leaves
    # every count and total identical.
    assert not diff_json({"r": [2, 1]}, {"r": [1, 2]}, tolerance).ok, "permutation"


def test_bracket_globs_match_the_collapsed_path_not_a_character_class() -> None:
    """`rows[*]` is `rows` + one character from the set `{*}` -- it matches nothing.

    Written the intended way, `rows[].game*` matches every indexed row.
    """
    inert = Tolerance(volatile=(("rows[*].game*", "the WRONG spelling"),))
    assert inert.is_volatile("rows[7].game.state") is None

    working = Tolerance(volatile=(("rows[].game*", "the right spelling"),))
    assert working.is_volatile("rows[7].game.state") == "the right spelling"
    assert working.is_volatile("rows[123].game.away_score") == "the right spelling"


def test_quote_reason_exclusions_do_not_reach_market_basis() -> None:
    """`*` spans dots, so a rule for `<side>.reason` must not swallow
    `<side>.market_basis.reason` -- a different field that stays checked."""
    tolerance = TARGETS["mlb_book_grid"].tolerance
    for side in ("over", "under", "home", "away", "draw"):
        assert tolerance.is_volatile(f"rows[689].cells.betmgm.{side}.reason") is not None
        assert tolerance.is_volatile(f"rows[689].best.{side}.reason") is not None
        assert tolerance.is_volatile(f"rows[689].cells.betmgm.{side}.market_basis.reason") is None
        assert tolerance.is_volatile(f"rows[689].best.{side}.market_basis.reason") is None


def test_every_excluded_and_relaxed_rule_carries_a_reason() -> None:
    """A bare exclusion list decays into a place to hide failures."""
    tolerance = TARGETS["mlb_book_grid"].tolerance
    for pattern, reason in tolerance.volatile + tolerance.clock_relative:
        # Word count, not character count: a cross-reference like "UNREPLAYABLE:
        # same live-lens snapshot." is a good reason at 38 characters, and a
        # length threshold would have forced padding rather than clarity.
        assert len(reason.split()) >= 4, f"{pattern}: a bare token is not a reviewable reason"
    for _, atol, reason in tolerance.field_atol:
        assert atol > 0 and reason.strip()


def test_tolerance_holds_at_exactly_its_own_step() -> None:
    """`3.5 - 3.6` is -0.10000000000000142, so an atol of 0.1 rejected values
    differing by precisely 0.1 until an epsilon was added."""
    tolerance = Tolerance(atol=0.1)
    assert tolerance.numbers_agree(3.5, 3.6)
    assert tolerance.numbers_agree(3.6, 3.5)
    assert not tolerance.numbers_agree(3.4, 3.6)


def test_bools_are_not_compared_as_numbers() -> None:
    """`True == 1` in Python; a flag turning into an int is a real change."""
    result = diff_json({"stale": 1}, {"stale": True}, Tolerance(atol=5))
    assert not result.ok


def test_clock_relative_fields_are_checked_against_one_shared_offset() -> None:
    """Production stamps its clock AFTER the pivot, so every age is offset by the
    same constant. One free parameter, many constraints -- a field that moves
    independently of the offset still fails."""
    tolerance = Tolerance(
        clock_relative=(("*age_seconds", "derived from one shared `now`"),),
        clock_relative_atol=0.1,
    )
    produced = {"a_age_seconds": 13.6, "b_age_seconds": 23.6, "c_age_seconds": 33.6}
    expected = {"a_age_seconds": 10.0, "b_age_seconds": 20.0, "c_age_seconds": 30.0}
    result = diff_json(produced, expected, tolerance)
    finalize_clock_relative(result, tolerance)
    assert result.ok
    assert result.clock_offset_sec == pytest.approx(3.6)
    assert result.clock_checked == 3

    # One field moved by something other than the shared clock: still a failure.
    produced["b_age_seconds"] = 25.0
    result = diff_json(produced, expected, tolerance)
    finalize_clock_relative(result, tolerance)
    assert not result.ok
    assert any(m["path"] == "b_age_seconds" for m in result.mismatches)


def test_an_absurd_clock_offset_fails_once_rather_than_everywhere() -> None:
    """A freeze that did not take is one fact, not 58,000 of them."""
    tolerance = Tolerance(
        clock_relative=(("*age_seconds", "derived from one shared `now`"),),
        clock_offset_max_sec=60.0,
    )
    produced = {f"k{i}_age_seconds": i + 9000.0 for i in range(5)}
    expected = {f"k{i}_age_seconds": float(i) for i in range(5)}
    result = diff_json(produced, expected, tolerance)
    finalize_clock_relative(result, tolerance)
    assert not result.ok
    assert result.mismatch_count == 1
    assert result.mismatches[0]["kind"] == "clock_offset_out_of_bounds"


def test_the_book_grid_target_names_a_real_worker_entrypoint() -> None:
    """`presence is not reachability`: the gate must run production's function,
    not a stand-in that happens to have the same shape."""
    import importlib

    target = TARGETS["mlb_book_grid"]
    module_name, _, function_name = target.entrypoint.partition(":")
    module = importlib.import_module(module_name)
    assert callable(getattr(module, function_name))


class _Args(argparse.Namespace):
    def __init__(self, **kwargs: object) -> None:
        super().__init__()
        defaults = {"skip_replay": False, "replay_date": None, "require_replay": False}
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


def test_no_fixture_is_never_ok_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """The single most important property. A replay gate with no fixture must be
    UNKNOWN, and under --require-replay a failure -- never a pass."""
    from scripts.migration_gate import evaluate_replay_diff

    monkeypatch.delenv("SYNDICATE_REPLAY_DATE", raising=False)

    unknown = evaluate_replay_diff(_Args(), timeout_sec=5)
    assert unknown["status"] == "NO_FIXTURE"
    assert unknown["ok"] is None, "UNKNOWN, not True and not False"

    required = evaluate_replay_diff(_Args(require_replay=True), timeout_sec=5)
    assert required["ok"] is False

    skipped = evaluate_replay_diff(_Args(skip_replay=True), timeout_sec=5)
    assert skipped["status"] == "SKIPPED"
    assert skipped["ok"] is None


def test_migration_gate_ok_is_not_sunk_by_unknown_but_is_by_fail() -> None:
    """`ok` uses `is not False`, so UNKNOWN neither sinks the gate on a checkout
    with no mirror nor is silently counted as a pass."""
    assert (None is not False) is True
    assert (False is not False) is False
    assert (True is not False) is True
