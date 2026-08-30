"""The two RELIABILITY terms must still DISCRIMINATE over the board's real range.

Both used to collapse to a constant across most of their live input, so they
stopped doing ranking work exactly where the board needed it. Measured on the
served board 2026-08-30 (677 scoreable rows):

    MOVEMENT   clip saturated at 20 American-odds points -- a ROUTINE move.
               35 of 80 rows with a move sat at the bound, contributing an
               identical 1.0 whether they had moved 25 points or 2000.
    FRESHNESS  floored at 0.25 for anything over 10,800s, so a 3h01m price and a
               12.4h price ranked identically. 323 of 677 rows (47.7%) sat on
               that floor.

After: bound ties 35 -> 21, distinct movement values 22 -> 36, bottom-rung rows
323 -> 76 (11.2%), and ZERO rows promoted.

WHAT THESE TESTS PIN, and why each one is here rather than being obvious:

  * SLOPE AT THE ORIGIN. The fix must not re-weight. If small moves stop scoring
    the way they did, this became a tuning change -- which is gated on settled
    rows with CLV decomposed, and `settled` is still 0.
  * THE BOUND IS NEVER EXCEEDED. The cap exists to make domination structurally
    impossible. A curve that overshoots it would be worse than the clip.
  * STRICT MONOTONICITY. This is the property `clip` destroyed past 20 points and
    the entire reason for the change.
  * NON-PROMOTION. A freshness change that RAISES any row's factor would be the
    same inversion `blended_score`'s `min()` exists to prevent: a discount that
    can improve a score is not a discount.
  * REVERTIBILITY. Both live behind env flags, because that is the only reason
    this file considers changing a contested scoring constant defensible at all.
"""
from __future__ import annotations

import importlib

import pytest

from syndicate.features.shared import opportunity_signals as OS

# The real deltas observed on the served board, worst-first. 20 is where the old
# clip saturated, so everything from 25 up used to be indistinguishable.
OBSERVED = [3, 4, 5, 10, 11, 14, 15, 20, 25, 30, 40, 45, 50, 55, 60, 100, 130, 150, 175,
            240, 245, 250, 490, 2000]


def test_slope_at_the_origin_is_unchanged_so_this_is_not_a_re_tune():
    """A 1-point move must still score ~= weight. If it does not, the weight moved."""
    one = OS._movement_contribution(1.0)
    assert one == pytest.approx(OS._SCORE_MOVEMENT_WEIGHT, rel=0.05), (
        f"1-point move scores {one}, weight is {OS._SCORE_MOVEMENT_WEIGHT}. The curve "
        "must match the old linear behaviour where the old behaviour was RIGHT."
    )


def test_the_bound_is_never_exceeded():
    """The cap is the whole safety property, and it must hold at any magnitude.

    NOT `< cap`. Algebraically `1 - exp(-x) < 1` always, but in FLOAT the
    contribution reaches the cap exactly once `exp(-weight*|d|/cap)` underflows
    -- measured at |d| ~ 2000 (500 -> 0.9999999999, 2000 -> exactly 1.0). An
    earlier version of this test asserted strict inequality and failed on that,
    which is how the code comment claiming "never reaches the cap" was caught
    and corrected. Reaching the bound is fine; exceeding it is not.
    """
    cap = OS._SCORE_MOVEMENT_CAP_PCT
    for d in OBSERVED + [10_000, 1_000_000]:
        for signed in (d, -d):
            got = OS._movement_contribution(float(signed))
            assert abs(got) <= cap, f"move {signed} produced {got}, EXCEEDING cap {cap}"
    # And across the range the board actually occupies, it is strictly inside.
    assert abs(OS._movement_contribution(490.0)) < cap


def test_movement_is_strictly_monotone_across_the_whole_observed_range():
    """THE REGRESSION. Under the clip, every delta >= 20 tied at the cap."""
    got = [OS._movement_contribution(float(d)) for d in OBSERVED]
    for prev, nxt, a, b in zip(got, got[1:], OBSERVED, OBSERVED[1:]):
        assert nxt > prev, f"{a} and {b} both score {prev} -- resolution lost again"


def test_movement_is_odd_symmetric():
    """A move toward us and the same move against us are mirror images."""
    for d in OBSERVED:
        assert OS._movement_contribution(float(d)) == pytest.approx(
            -OS._movement_contribution(float(-d))
        )


def test_the_old_clip_is_still_reachable_for_revert():
    """Revertible without a deploy, or changing a contested constant is not defensible."""
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setenv("SYNDICATE_SCORE_MOVEMENT_SATURATING", "0")
        reloaded = importlib.reload(OS)
        # Under the clip, 20 and 2000 tie at the cap -- the behaviour being replaced.
        assert reloaded._movement_contribution(2000.0) == pytest.approx(
            reloaded._SCORE_MOVEMENT_CAP_PCT
        )
        assert reloaded._movement_contribution(20.0) == pytest.approx(
            reloaded._SCORE_MOVEMENT_CAP_PCT
        )
    finally:
        monkey.undo()
        importlib.reload(OS)


# --------------------------------------------------------------------------
# FRESHNESS
# --------------------------------------------------------------------------

_OLD_LADDER = ((300, 1.0), (1800, 0.9), (3600, 0.75), (10800, 0.5))


def _old_freshness(age: float) -> float:
    for threshold, factor in _OLD_LADDER:
        if age <= threshold:
            return factor
    return 0.25


AGES = [0, 60, 299, 300, 301, 1800, 3600, 10800, 10801, 14400, 21600, 21601,
        30000, 43200, 43201, 45102, 86400]


def test_freshness_never_promotes_a_row():
    """HARD CONSTRAINT. Every age must score the same or LOWER than before.

    A freshness term that raised a score would be the inversion `blended_score`'s
    `min()` exists to prevent. Verified on the live board too: 0 of 677 promoted.
    """
    for age in AGES:
        new = OS._freshness_factor(None, float(age))
        old = _old_freshness(float(age))
        assert new <= old, f"age {age}s promoted: {old} -> {new}"


def test_freshness_still_discriminates_past_three_hours():
    """THE REGRESSION. 3h01m and 12.4h used to be the same number."""
    just_past = OS._freshness_factor(None, 10801.0)   # 3h01m  -> its own rung
    half_day = OS._freshness_factor(None, 30000.0)    # 8h20m  -> lower
    very_old = OS._freshness_factor(None, 44000.0)    # 12h13m -> lower still
    assert just_past > half_day > very_old, (
        f"still flat past 3h: {just_past} / {half_day} / {very_old}"
    )
    # Past the final rung it is flat again, and that is deliberate -- a ladder
    # ends. 12.2h and 25h are both "very stale" and ordering them buys nothing.
    assert OS._freshness_factor(None, 90000.0) == very_old


def test_freshness_is_monotone_non_increasing():
    got = [OS._freshness_factor(None, float(a)) for a in AGES]
    for prev, nxt, a, b in zip(got, got[1:], AGES, AGES[1:]):
        assert nxt <= prev, f"freshness rose between {a}s and {b}s: {prev} -> {nxt}"


def test_the_first_four_rungs_are_untouched():
    """The fix is at the STALE end. Anything else would be a re-tune."""
    for age, expected in ((100, 1.0), (300, 1.0), (1800, 0.9), (3600, 0.75), (10800, 0.5)):
        assert OS._freshness_factor(None, float(age)) == expected


def test_unknown_age_is_still_not_treated_as_fresh():
    """Unchanged behaviour, pinned because the ladder around it moved."""
    assert OS._freshness_factor(None, None) == 0.6
    assert OS._freshness_factor(None, -1.0) == 0.6


def test_env_bool_does_not_read_the_string_false_as_true():
    """`bool(os.environ.get(...))` would. That is the documented incident shape."""
    monkey = pytest.MonkeyPatch()
    try:
        for raw, expected in (("false", False), ("0", False), ("off", False),
                              ("true", True), ("1", True), ("nonsense", True)):
            monkey.setenv("SYNDICATE_TEST_FLAG", raw)
            assert OS._env_bool("SYNDICATE_TEST_FLAG", True) is expected, raw
    finally:
        monkey.undo()
