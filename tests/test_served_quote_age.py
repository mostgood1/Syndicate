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


# ---------------------------------------------------------------------------
# `#569` part 2: WHY a row never repolls. orphaned_line vs market_gone.
# ---------------------------------------------------------------------------

from pipeline.layer2_shortlist import _classify_stale_row, _report_stale_row_causes

NOW = "2026-08-26T16:00:00Z"


def _grid_row(line="8.5", seen=7200.0, event="E1", market="totals", player=""):
    return {
        "sport": "mlb", "kind": "game", "event_id": event, "segment": "full_game",
        "market": market, "player_name": player, "line": line,
        "quote": {"quote_seen_age_seconds": seen},
    }


def _key(line="8.5", book="fanduel", sel="over", event="E1", market="totals", player=""):
    # _KEY_FIELDS order: sport|kind|event_id|bookmaker|segment|market|selection|player_name|line
    return f"mlb|game|{event}|{book}|full_game|{market}|{sel}|{player}|{line}"


def test_a_live_market_whose_line_moved_is_an_ORPHANED_LINE():
    """The book moved 8.5 -> 9.0. The 8.5 key can never be observed again, but
    the market is plainly live. drop_superseded_lines should have caught it."""
    last_seen = {
        _key(line="8.5"): "2026-08-26T14:00:00Z",   # 2h old, the orphan
        _key(line="9.0"): "2026-08-26T15:58:00Z",   # 2m old, the live sibling
    }
    assert _classify_stale_row(_grid_row(line="8.5", seen=7200.0), last_seen, NOW, 30.0) == "orphaned_line"


def test_a_market_the_feed_stopped_quoting_is_MARKET_GONE():
    """Every line in the group is equally old. No fresher sibling exists, so
    drop_superseded_lines has nothing to compare and correctly drops nothing."""
    last_seen = {
        _key(line="8.5"): "2026-08-26T14:00:00Z",
        _key(line="9.0"): "2026-08-26T14:00:30Z",
    }
    assert _classify_stale_row(_grid_row(line="8.5", seen=7200.0), last_seen, NOW, 30.0) == "market_gone"


def test_a_different_market_never_counts_as_a_fresh_sibling():
    """A collision here would attribute one market's freshness to another and
    report a dead feed as a tidy grid bug."""
    last_seen = {
        _key(line="8.5"): "2026-08-26T14:00:00Z",
        _key(line="9.0", market="spreads"): "2026-08-26T15:58:00Z",
        _key(line="9.0", event="E2"): "2026-08-26T15:58:00Z",
        _key(line="9.0", player="Ohtani"): "2026-08-26T15:58:00Z",
    }
    assert _classify_stale_row(_grid_row(line="8.5", seen=7200.0), last_seen, NOW, 30.0) == "market_gone"


def test_the_same_line_on_another_book_is_not_the_orphan_test():
    """Another book quoting the SAME line does not mean this line was
    superseded -- supersession is about the line moving, not about coverage."""
    last_seen = {
        _key(line="8.5", book="fanduel"): "2026-08-26T14:00:00Z",
        _key(line="8.5", book="draftkings"): "2026-08-26T15:58:00Z",
    }
    assert _classify_stale_row(_grid_row(line="8.5", seen=7200.0), last_seen, NOW, 30.0) == "market_gone"


def test_a_reordered_key_schema_reports_unknown_rather_than_guessing():
    """This function slices a positional string. If `_KEY_FIELDS` is reordered
    the slice silently means something else, so it is asserted at call time and
    the answer degrades to `unknown`, never to a plausible label."""
    import pipeline.layer2_shortlist as mod
    real = mod._QUOTE_KEY_ORDER
    try:
        mod._QUOTE_KEY_ORDER = ("sport", "line")  # disagree with _KEY_FIELDS
        got = _classify_stale_row(_grid_row(), {_key(): NOW}, NOW, 30.0)
    finally:
        mod._QUOTE_KEY_ORDER = real
    assert got == "unknown_key_order_changed"


def test_the_report_never_raises_on_junk(capsys):
    for rows in (None, [], "nope", [None, 7], [{"quote": {"quote_seen_age_seconds": True}}]):
        _report_stale_row_causes(rows, "2026-08-26")
    assert "STALE_ROW_CAUSE_FAILED" not in capsys.readouterr().out


def test_rows_under_the_threshold_are_reported_as_none_rather_than_silence(capsys):
    _report_stale_row_causes([_grid_row(seen=60.0)], "2026-08-26")
    assert "STALE_ROW_CAUSE none_over_900s" in capsys.readouterr().out


def test_the_cause_report_is_wired_into_the_build():
    import inspect
    from pipeline import layer2_shortlist
    src = inspect.getsource(layer2_shortlist.build_layer2_shortlist)
    assert "_report_stale_row_causes(" in src, "computed and never called"


# ---------------------------------------------------------------------------
# `#569` part 3: the FALSE POSITIVE that part 2 shipped, and its fix.
# ---------------------------------------------------------------------------

def test_a_staggered_freeze_is_NOT_an_orphaned_line():
    """THE PRODUCTION WRONG ANSWER, 2026-08-26 19:15Z.

    wnba read `orphaned_line=2 of 3` while `ODDS_SWEEP_OUTCOME` said
    `wrote=False` -- its sidecar was not being written at all. When writes stop
    every key freezes at a STAGGERED moment, so a key frozen shortly before the
    stop looks hours fresher than one frozen well before it, and the
    fresher-sibling test read that as supersession.

    Identical sibling stamps to `test_a_live_market_whose_line_moved_is_an
    ORPHANED_LINE` -- the ONLY difference is that the sidecar itself is stale.
    That is the whole point: sibling stamps cannot separate these two, and only
    the file's own freshness can.
    """
    last_seen = {
        _key(line="8.5"): "2026-08-26T14:00:00Z",
        _key(line="9.0"): "2026-08-26T15:58:00Z",
    }
    row = _grid_row(line="8.5", seen=7200.0)
    assert _classify_stale_row(row, last_seen, NOW, 30.0) == "orphaned_line"      # live file
    assert _classify_stale_row(row, last_seen, NOW, 14400.0) == "sidecar_frozen"  # frozen file


def test_a_frozen_sidecar_also_overrides_market_gone():
    """`sidecar_frozen` replaces BOTH labels, not just the wrong one. Reporting
    `market_gone` off a dead file would be right by accident and would send the
    next reader to the feed when the answer is that we stopped looking."""
    last_seen = {_key(line="8.5"): "2026-08-26T14:00:00Z", _key(line="9.0"): "2026-08-26T14:00:30Z"}
    row = _grid_row(line="8.5", seen=7200.0)
    assert _classify_stale_row(row, last_seen, NOW, 30.0) == "market_gone"
    assert _classify_stale_row(row, last_seen, NOW, 14400.0) == "sidecar_frozen"


def test_an_unknown_sidecar_age_refuses_to_classify():
    """Absent, not assumed live. Defaulting to "the file is fine" is how the
    first version got wnba wrong, and it must not be reachable by omission."""
    last_seen = {_key(line="8.5"): "2026-08-26T14:00:00Z", _key(line="9.0"): "2026-08-26T15:58:00Z"}
    assert _classify_stale_row(_grid_row(line="8.5", seen=7200.0), last_seen, NOW, None) == "unknown_no_sidecar_age"
    # And the parameter's DEFAULT must not smuggle a live file in either.
    assert _classify_stale_row(_grid_row(line="8.5", seen=7200.0), last_seen, NOW) == "unknown_no_sidecar_age"


def test_the_report_line_carries_the_sidecar_age(capsys, monkeypatch):
    """A reader must be able to see the file was live, not take it on trust.

    Patches the state reader: with no real state file this path correctly
    short-circuits to `unknown_empty_state_file`, which is right behaviour and
    the wrong thing to assert against.
    """
    from datetime import datetime, timedelta, timezone
    import syndicate.features.shared.odds_book_quotes as obq

    fresh = (datetime.now(timezone.utc) - timedelta(seconds=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old_stamp = (datetime.now(timezone.utc) - timedelta(seconds=7200)).strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setattr(obq, "read_quote_last_seen",
                        lambda sport, date: {_key(line="8.5"): old_stamp, _key(line="9.0"): fresh})

    _report_stale_row_causes([_grid_row(line="8.5", seen=7200.0)], "2026-08-26")
    out = capsys.readouterr().out
    assert "STALE_ROW_CAUSE" in out
    assert "sidecar=" in out
    # A live file (20s) must reach a real verdict, not the frozen escape hatch.
    assert "sidecar_frozen" not in out
    assert "orphaned_line=1" in out


def test_a_frozen_sidecar_is_visible_on_the_report_line(capsys, monkeypatch):
    """The wnba shape end to end: every stamp old, so the file is frozen and
    every row says so rather than reporting a manufactured supersession."""
    from datetime import datetime, timedelta, timezone
    import syndicate.features.shared.odds_book_quotes as obq

    def _ago(s):
        return (datetime.now(timezone.utc) - timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Staggered freeze -- exactly what fooled the first version.
    monkeypatch.setattr(obq, "read_quote_last_seen",
                        lambda sport, date: {_key(line="8.5"): _ago(30000), _key(line="9.0"): _ago(4000)})

    _report_stale_row_causes([_grid_row(line="8.5", seen=30000.0)], "2026-08-26")
    out = capsys.readouterr().out
    assert "sidecar_frozen=1" in out
    assert "orphaned_line" not in out
