"""`#569`: is the BOARD stale, or is the QUOTE stale?

WHY THIS EXISTS. Asked by syndicate-43 on 2026-08-26, and nothing in this repo
could answer it. Every measurement the `board-staleness-visibility` lane shipped
is on artifact PUBLICATION time -- `written_at` on the chip artifact, artifact
stamps on `state_meta`. None of it touches the age of the quote INSIDE the
artifact, so a board republished every 60s carrying twenty-minute-old venue
quotes read FRESH on all of it.

That is the failure mode a direct Kalshi/Polymarket feed would fix and a
publication fix would not, and `test_the_case_that_every_publication_instrument_missed`
below is exactly it.

Run:  python -m pytest tests/test_served_quote_age.py
"""

import pytest

from pipeline.layer2_shortlist import _quote_age_percentiles, _report_served_quote_ages


def _row(sport="mlb", seen=None, book=None, quote=True):
    row = {"sport_slug": sport}
    if quote:
        q = {}
        if seen is not None:
            q["quote_seen_age_seconds"] = seen
        if book is not None:
            q["book_age_seconds"] = book
        row["quote"] = q
    return row


def _line(capsys):
    out = [l for l in capsys.readouterr().out.splitlines() if "QUOTE_AGE_SERVED" in l]
    assert len(out) == 1, f"expected exactly one report line, got {out}"
    return out[0]


def _field(line, key):
    return line.split(f"{key}=")[1].split()[0]


def test_the_case_that_every_publication_instrument_missed(capsys):
    """A PROMPTLY PUBLISHED BOARD FULL OF STALE QUOTES.

    This is the shape the whole lane was blind to: publication is healthy, so
    `written_at` is seconds old and no stale badge renders, while the quotes
    themselves are ~20 minutes old. The report must make that visible.
    """
    rows = [_row(seen=1200.0, book=1800.0) for _ in range(10)]
    _report_served_quote_ages(rows)
    line = _line(capsys)
    assert _field(line, "seen_p50") == "1200"
    assert float(_field(line, "seen_max")) >= 1200
    # And it must be attributable to a sport, not just an aggregate.
    assert "worst_seen_by_sport mlb=1200" in line


def test_the_two_clocks_are_reported_separately_not_collapsed(capsys):
    """`#370` measured wnba book=376.2m against seen=68.5m. A motionless market
    ages without limit on the book clock while our observation stays current, so
    collapsing them would report an outage that is not there."""
    rows = [_row(sport="wnba", seen=4110.0, book=22572.0) for _ in range(5)]
    _report_served_quote_ages(rows)
    line = _line(capsys)
    assert _field(line, "seen_p50") == "4110"
    assert _field(line, "book_p50") == "22572"
    assert _field(line, "seen_p50") != _field(line, "book_p50")


def test_a_fresh_board_reads_fresh(capsys):
    """BOTH DIRECTIONS. Without this, a report hard-coded to a large number --
    the same defect as the hard-coded `is_fresh: True` this lane just removed,
    pointing the other way -- would pass every assertion above."""
    rows = [_row(seen=12.0, book=30.0) for _ in range(10)]
    _report_served_quote_ages(rows)
    line = _line(capsys)
    assert _field(line, "seen_p50") == "12"
    assert _field(line, "book_p50") == "30"


def test_a_missing_clock_reads_absent_and_never_zero(capsys):
    """Zero would read as "our observation is current", the exact opposite of
    "we have no clock". Same rule `#566` states for unreadable memory."""
    rows = [_row(quote=False) for _ in range(3)]
    _report_served_quote_ages(rows)
    line = _line(capsys)
    assert "seen_p50=absent" in line
    assert "book_p50=absent" in line
    assert _field(line, "no_clock") == "3"


def test_one_clock_present_does_not_count_as_no_clock(capsys):
    """A source publishing only a book clock is measured, not discarded."""
    rows = [_row(seen=None, book=99.0) for _ in range(4)]
    _report_served_quote_ages(rows)
    line = _line(capsys)
    assert _field(line, "no_clock") == "0"
    assert _field(line, "book_n") == "4"
    assert "seen_p50=absent" in line


def test_a_bool_is_not_an_age(capsys):
    """`isinstance(True, int)` is True in Python, so an unguarded numeric check
    would record `True` as a 1-second-old quote."""
    rows = [_row(seen=True, book=False)]
    _report_served_quote_ages(rows)
    line = _line(capsys)
    assert _field(line, "no_clock") == "1"
    assert "seen_p50=absent" in line


@pytest.mark.parametrize("rows", [None, [], "not a list", [None, 3, "x"]])
def test_junk_input_never_raises_and_never_lies(rows, capsys):
    _report_served_quote_ages(rows)  # must not raise
    out = capsys.readouterr().out
    assert "QUOTE_AGE_SERVED_FAILED" not in out


def test_percentiles_are_real_observations_not_interpolations():
    """Nearest-rank on purpose: an interpolated age is not an age any quote had."""
    p50, p90, worst = _quote_age_percentiles([10.0, 20.0, 30.0, 40.0, 1000.0])
    assert p50 in {10.0, 20.0, 30.0, 40.0, 1000.0}
    assert worst == 1000.0
    assert p90 >= p50
    assert _quote_age_percentiles([]) is None


def test_the_report_is_wired_into_the_shortlist_build():
    """Reachability. A report nothing calls measures nothing."""
    import inspect
    from pipeline import layer2_shortlist

    source = inspect.getsource(layer2_shortlist.build_layer2_shortlist)
    assert "_report_served_quote_ages(" in source, "computed and never called"
