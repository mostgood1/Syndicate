"""The prop producers must REPORT the null-win_prob rate, not just avoid 0.5.

Why this test exists: the fix that removed `... or 0.5` writes `win_prob=None`
instead, and emitted nothing. Measured on production 2026-08-15, the live WNBA
artifact had 15 win_prob rows and ZERO price-missing rows -- so "0 fabricated"
was indistinguishable from "never exercised", and grepping the producer log
returned nothing because there was nothing to find. NBA was worse: out of
season, no artifact at all.

So the assertions here are about OBSERVABILITY, not arithmetic:
  * both branches are counted, so the denominator is real;
  * the counter sits on the chokepoint, so a future call site is counted
    automatically rather than silently missed;
  * the line is emitted even when everything is zero, because `null=0` with no
    `rows` cannot be read -- it means "the fix held" or "nothing ran", and those
    demand opposite responses.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PRODUCERS = {
    "wnba": SCRIPTS / "refresh_wnba_oddsapi_props.py",
    "nba": SCRIPTS / "refresh_nba_oddsapi_props.py",
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_producer_{name}", PRODUCERS[name])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module._WIN_PROB_STATS.update(rows=0, null_no_price=0)
    return module


@pytest.mark.parametrize("sport", sorted(PRODUCERS))
def test_chokepoint_counts_both_branches(sport):
    m = _load(sport)
    m._clamp_probability(0.62)
    m._clamp_probability(None)
    m._clamp_probability(1.4)
    m._clamp_probability(None)
    # Assert the two counters this test is ABOUT, not dict identity. Exact
    # equality made the test fail the moment a THIRD counter was added
    # (`certainty_clamped`), which is a brittleness that punishes adding
    # observability -- the opposite of what this file exists to encourage.
    assert m._WIN_PROB_STATS["rows"] == 4, "every call must be counted"
    assert m._WIN_PROB_STATS["null_no_price"] == 2, "the None branch must be counted"


@pytest.mark.parametrize("sport", sorted(PRODUCERS))
def test_clamp_behaviour_is_unchanged(sport):
    """Counting must not alter what the producer publishes.

    The BOUNDS are now sport-specific and that is deliberate, not drift. WNBA
    was measured on 2026-08-31 publishing `p_win = 1.000` on 36 of 466
    recommendations against a realized 47.62%, so its clamp refuses certainty at
    [0.01, 0.99]. NBA has NOT been measured, and tightening it here on WNBA's
    evidence would be exactly the assume-symmetry error this repo keeps paying
    for -- so NBA keeps [0, 1] until someone measures it.

    What this test still guards, for both, is the original invariant: counting
    did not change the mapping of an ORDINARY probability.
    """
    m = _load(sport)
    assert m._clamp_probability(None) is None
    assert m._clamp_probability(0.5) == 0.5  # a REAL 0.5 still survives
    assert m._clamp_probability(0.73) == 0.73

    if sport == "wnba":
        assert m._clamp_probability(1.4) == m._CERTAINTY_CEILING
        assert m._clamp_probability(-0.2) == m._CERTAINTY_FLOOR
        assert m._CERTAINTY_CEILING < 1.0 and m._CERTAINTY_FLOOR > 0.0
    else:
        assert m._clamp_probability(1.4) == 1.0
        assert m._clamp_probability(-0.2) == 0.0


@pytest.mark.parametrize("sport", sorted(PRODUCERS))
def test_emits_a_rate_with_a_denominator(sport, capsys):
    m = _load(sport)
    m._clamp_probability(None)
    m._clamp_probability(0.7)
    m._emit_win_prob_stats()
    line = capsys.readouterr().out
    assert "WIN_PROB_NULL_NO_PRICE" in line
    assert "null=1" in line and "rows=2" in line, "a count without a denominator is unreadable"
    assert "pct=50.0" in line


@pytest.mark.parametrize("sport", sorted(PRODUCERS))
def test_emits_even_when_nothing_ran(sport, capsys):
    """The all-zero run is the one that distinguishes 'held' from 'never ran'."""
    m = _load(sport)
    m._emit_win_prob_stats()
    out = capsys.readouterr().out
    assert "null=0 rows=0" in out


@pytest.mark.parametrize("sport", sorted(PRODUCERS))
def test_no_win_prob_branch_bypasses_the_chokepoint(sport):
    """A bare `else None` would be invisible to the counter -- pin that it is gone."""
    src = PRODUCERS[sport].read_text(encoding="utf-8")
    import re

    bypass = re.findall(r"if implied_prob is not None\s*\n(?:\s*#[^\n]*\n)*\s*else None", src)
    assert not bypass, f"{len(bypass)} win_prob branch(es) skip _clamp_probability and would not be counted"

@pytest.mark.parametrize("sport", sorted(PRODUCERS))
def test_per_build_emit_reports_a_DELTA_not_a_running_total(sport, capsys):
    """Consecutive builds must not print a growing cumulative number.

    The exit emit fires from `finally`, so it only lands when the process ends —
    measured 2026-08-16, the producer was still mid-run 70+ minutes after deploy
    with nothing logged. The per-build emit exists to make the branch observable
    when the artifact lands, and it is only readable if each line is attributable
    to the build that caused it.
    """
    m = _load(sport)

    m._clamp_probability(None)          # build 1: 1 null of 2
    m._clamp_probability(0.7)
    m._emit_win_prob_build("first")
    first = capsys.readouterr().out
    assert "build=first" in first and "null=1 rows=2" in first

    m._clamp_probability(0.6)           # build 2: 0 nulls of 1
    m._emit_win_prob_build("second")
    second = capsys.readouterr().out
    assert "build=second" in second
    assert "null=0 rows=1" in second, "second build must report ITS OWN counts, not 1/3"

    m._emit_win_prob_stats()            # exit emit: the cumulative total
    total = capsys.readouterr().out
    assert "build=TOTAL" in total and "null=1 rows=3" in total


@pytest.mark.parametrize("sport", sorted(PRODUCERS))
def test_every_artifact_writer_emits(sport):
    """A writer added later without an emit is silent exactly where it matters."""
    src = PRODUCERS[sport].read_text(encoding="utf-8")
    for build in ("recommendations_slate", "top_by_game", "cards_props_snapshot"):
        assert f'_emit_win_prob_build("{build}")' in src, f"{build} writes an artifact but emits nothing"
