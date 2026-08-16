"""`batter_home_runs` is projectable at 1.5 and 2.5, not only at 0.5.

THE DEFECT, measured on production 2026-08-16: `batter_home_runs` was
**240/290 projected at line 0.5, 1/260 at 1.5 and 0/244 at 2.5** -- 504 dark
rows, the largest single coverage gap on the MLB board.

Three layers each enforced a limit none of them needed:

  1. `daily_update` counted `hr_1plus` with a bare `if hr >= 1`, the only
     multi-valued hitter stat on that screen NOT using `_inc_ge_thresholds`,
     which the line above it uses for hits and the lines below for
     hits_runs_rbis / runs / rbi / total_bases.
  2. `_hr_row` published only `p_hr_1plus`.
  3. `project()` refused outright with `abs(line_value - 0.5) > 0.01`.

Nothing in the model changed. Each sim already produces a whole-game HR count
per batter; the >=2 and >=3 tallies were being dropped in the same loop that
keeps them for four other stats.

These tests exercise `PropProjectionIndex.project` -- the real entry point the
board calls -- not `_bucket_for_line` alone. A helper checked with
self-supplied arguments proves the function and not that production reaches it,
which is a mistake this session already made once.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.prop_projections import PropProjectionIndex, _bucket_for_line


def _index(**hr_fields):
    """An index holding one HR row, shaped like `hitter_hr_likelihood_all`."""
    idx = PropProjectionIndex()
    row = {"name": "Aaron Judge", "hr_mean": 0.62}
    row.update(hr_fields)
    idx._hitters[("aaron judge", "hr_1plus")] = row
    return idx


def _project(idx, line):
    return idx.project(player_name="Aaron Judge", market="batter_home_runs", line=line)


def test_the_line_selects_the_rung():
    idx = _index(p_hr_1plus=0.41, p_hr_2plus=0.09, p_hr_3plus=0.01)
    assert _project(idx, 0.5)["model_prob_over"] == 0.41
    assert _project(idx, 1.5)["model_prob_over"] == 0.09
    assert _project(idx, 2.5)["model_prob_over"] == 0.01


def test_each_rung_states_its_own_basis():
    """`basis` is what makes a served row auditable back to a sim quantity.

    Reporting every HR row as `hr_1plus` would have made the 1.5 and 2.5 rows
    look like they were priced off P(HR>=1).
    """
    idx = _index(p_hr_1plus=0.41, p_hr_2plus=0.09, p_hr_3plus=0.01)
    assert _project(idx, 0.5)["basis"] == "hr_1plus"
    assert _project(idx, 1.5)["basis"] == "hr_2plus"
    assert _project(idx, 2.5)["basis"] == "hr_3plus"


def test_the_calibrated_value_wins_where_it_exists():
    """`_cal` is fitted for hr_1plus only, so only that rung should have one."""
    idx = _index(p_hr_1plus=0.41, p_hr_1plus_cal=0.38, p_hr_2plus=0.09)
    assert _project(idx, 0.5)["model_prob_over"] == 0.38
    assert _project(idx, 1.5)["model_prob_over"] == 0.09


def test_an_uncounted_rung_is_ABSENT_not_zero():
    """The load-bearing refusal.

    An artifact written before the sim counted this rung has no field. Reading
    that as 0.0 would be indistinguishable from "the model says it will not
    happen" -- and the board would price against it, confidently, at a line the
    sim has no opinion on.
    """
    idx = _index(p_hr_1plus=0.41)          # pre-change artifact
    assert _project(idx, 0.5) is not None
    assert _project(idx, 1.5) is None
    assert _project(idx, 2.5) is None


def test_a_genuine_zero_is_still_a_projection():
    """0.0 from a rung that WAS counted is a real estimate, not a gap.

    The other side of the test above: absence and zero must not collapse into
    each other in either direction.
    """
    idx = _index(p_hr_1plus=0.41, p_hr_2plus=0.0)
    out = _project(idx, 1.5)
    assert out is not None and out["model_prob_over"] == 0.0


def test_a_whole_number_line_is_still_refused():
    """"over 2" carries push mass a `Nplus` bucket cannot express."""
    idx = _index(p_hr_1plus=0.41, p_hr_2plus=0.09)
    assert _bucket_for_line("hr", 2.0) is None
    assert _project(idx, 2.0) is None


def test_a_rung_beyond_what_the_sim_counts_is_refused():
    """Depth is 3. A 3.5 line derives `hr_4plus`, which nothing publishes."""
    idx = _index(p_hr_1plus=0.41, p_hr_2plus=0.09, p_hr_3plus=0.01)
    assert _bucket_for_line("hr", 3.5) == "hr_4plus"
    assert _project(idx, 3.5) is None


def test_an_unknown_player_is_still_none():
    idx = _index(p_hr_1plus=0.41, p_hr_2plus=0.09)
    assert idx.project(player_name="Nobody At All", market="batter_home_runs", line=1.5) is None


def test_the_projected_mean_is_carried_on_every_rung():
    """`projected` is the HR mean and describes the player, not the line."""
    idx = _index(p_hr_1plus=0.41, p_hr_2plus=0.09)
    assert _project(idx, 0.5)["projected"] == 0.62
    assert _project(idx, 1.5)["projected"] == 0.62
