"""`#429` producer fix — the sim must SUM H+R+RBI, not divide zero by the sim count.

THE DEFECT. `daily_update.py` builds each topn row's mean as
`_stat(pid, stat_key) / denom_sims`, and `_stat` reads ONLY what `_inc_sum`
accumulated. The `hits_runs_rbis_*` entries pass `stat_key="H+R+RBI"` — and
that key was never passed to `_inc_sum` anywhere in the file. So the numerator
was always 0 and every hitter's `hrr_mean` was `0.0 / sims`.

Every sibling mean worked precisely because its `_inc_sum` line exists:
`_inc_sum(pid, "PA", pa)`, `"AB"`, `"H"`, `"R"`, `"RBI"`, `"TB"`. H+R+RBI was
the one COMPOSITE in the mapping and the one stat never summed.

Measured before the fix on `daily_summary_2026_07_09.json`: `hrr_mean` present
on 936 of 936 topn rows, nonzero on 0, while `p_hrr_2plus` on the same rows was
genuine — the row was real and exactly one field was dead.

WHY THIS TEST IS STRUCTURAL. Running the accumulator for real needs a full MLB
sim, which is far too heavy for a unit test. But the defect is a missing LINE,
and the file carries TWO copies of the per-sim hitter accumulation. Fixing only
the copy you happen to find is the `#334` failure this repo has recorded
repeatedly, so the load-bearing assertion is that the two copies AGREE.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "vendor" / "mlb_bettingv2" / "tools" / "daily_update.py"


@pytest.fixture(scope="module")
def source() -> str:
    return SRC.read_text(encoding="utf-8", errors="surrogateescape")


def test_the_source_file_exists(source):
    """Positive control: if this file moves, every assertion below would pass
    vacuously on an empty string."""
    assert len(source) > 100_000, "daily_update.py is unexpectedly small -- did it move?"
    assert "_HITTER_PROP_DIST_SPECS" in source


def test_hrr_is_accumulated_at_every_site_the_other_hitter_stats_are(source):
    """THE LOAD-BEARING ONE. Two copies of the accumulation exist; a fix to one
    is not a fix. Anchored on TB, which sits on the line directly above."""
    tb_sites = len(re.findall(r'_inc_sum\(pid, "TB", tb\)', source))
    hrr_sites = len(re.findall(r'_inc_sum\(pid, "H\+R\+RBI", hrr\)', source))
    assert tb_sites >= 2, "expected two copies of the hitter accumulation"
    assert hrr_sites == tb_sites, (
        f"H+R+RBI accumulated at {hrr_sites} site(s) but TB at {tb_sites} -- "
        "the two copies have drifted and one still writes hrr_mean 0.0"
    )


def test_the_composite_is_summed_not_recomputed(source):
    """`hrr` is already computed as int(h + rr + rbi) beside the distribution
    loop that bins it. Recomputing it at the accumulator would let the mean and
    the distribution drift apart on any future edit."""
    assert source.count("hrr = int(h + rr + rbi)") >= 2
    # the accumulator must pass the existing variable, not an inline expression
    assert not re.search(r'_inc_sum\(pid, "H\+R\+RBI", *int\(', source)
    assert re.search(r'_inc_sum\(pid, "H\+R\+RBI", hrr\)', source)


def test_the_mapping_still_asks_for_this_stat_key(source):
    """If the mapping ever stops using "H+R+RBI", this fix becomes dead code and
    the test should say so rather than silently guarding nothing."""
    assert '"hits_runs_rbis_2plus": ("p_hrr_2plus", "H+R+RBI", "hrr_mean")' in source


# --------------------------------------------------------------------------
# the arithmetic contract, replicated exactly
# --------------------------------------------------------------------------


def _accumulate(sims, *, include_composite):
    """Replicates _inc_sum / _stat, which is all the mean depends on."""
    sum_stats = {}

    def inc(pid, key, v):
        row = sum_stats.setdefault(int(pid), {})
        row[key] = float(row.get(key, 0.0)) + float(v)

    for h, r, rbi in sims:
        inc(1, "H", h)
        inc(1, "R", r)
        inc(1, "RBI", rbi)
        if include_composite:
            inc(1, "H+R+RBI", int(h + r + rbi))

    def stat(key):
        return float((sum_stats.get(1) or {}).get(key) or 0.0)

    return stat


SIMS = [(2, 1, 1), (1, 0, 2), (0, 1, 0)]


def test_pre_fix_behaviour_reproduces_the_reported_zero():
    """Without this, the test below proves only that addition works."""
    stat = _accumulate(SIMS, include_composite=False)
    assert stat("H+R+RBI") / len(SIMS) == 0.0


def test_post_fix_mean_is_the_true_mean():
    stat = _accumulate(SIMS, include_composite=True)
    expected = sum(h + r + rbi for h, r, rbi in SIMS) / len(SIMS)
    assert stat("H+R+RBI") / len(SIMS) == pytest.approx(expected)


def test_producer_agrees_with_the_read_time_derivation():
    """`#429`'s shipped read-time fix derives the mean as h+r+rbi. The producer
    must compute the SAME quantity, or the board would change value when the
    producer starts working and `prop_projections` stands aside."""
    stat = _accumulate(SIMS, include_composite=True)
    n = len(SIMS)
    produced = stat("H+R+RBI") / n
    derived = (stat("H") + stat("R") + stat("RBI")) / n
    assert produced == pytest.approx(derived)
