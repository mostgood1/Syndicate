"""`#569`: WHY a stale line survives `drop_superseded_lines`.

WHY THIS EXISTS RATHER THAN A FIX. Three rows on the served board 2026-08-26
were classified `orphaned_line` -- a fresher sibling line demonstrably existed
in the quote state file -- and this guard did not drop them. It drops plenty
(`count=1560 kept=946` on one MLB build), so the rule works; something about
those three differs.

The guard decides what the BOARD SHOWS. Three rows survive wrongly against ~946
kept correctly per build, so loosening it on a guess risks emptying a board to
fix a rounding error -- exactly what `book_grid`'s own docstring warns about.
This counter names the gap before anything is loosened.

Run:  python -m pytest tests/test_superseded_survivors.py
"""

from syndicate.features.shared.book_grid import drop_superseded_lines

LAG = 15 * 60


def _row(line, seen, event="E1", market="totals", player=""):
    return {
        "sport": "mlb", "event_id": event, "kind": "game", "market": market,
        "segment": "full_game", "player_name": player, "line": line,
        "seen_age_seconds": seen,
    }


def _reasons(capsys):
    out = [l for l in capsys.readouterr().out.splitlines() if "SUPERSEDED_SURVIVORS" in l]
    if not out:
        return {}
    return dict(
        (p.split("=")[0], int(p.split("=")[1]))
        for p in out[-1].split("SUPERSEDED_SURVIVORS ")[1].split()
    )


def test_the_rule_still_drops_what_it_always_dropped(capsys):
    """THE 946 ROWS. Any change here must leave the working case untouched."""
    grid = [_row("8.5", 7200.0), _row("9.0", 60.0)]
    kept, dropped = drop_superseded_lines(grid)
    assert dropped == 1
    assert [r["line"] for r in kept] == ["9.0"]


def test_a_lone_stale_row_reports_no_group_sibling(capsys):
    """THE LEADING HYPOTHESIS. The classifier that found these reads the STATE
    FILE, which holds every key ever observed; this guard sees only rows in THIS
    grid. If the fresher sibling never became a grid row, the guard has nothing
    to compare and the difference between those two sources IS the hole."""
    kept, dropped = drop_superseded_lines([_row("8.5", 7200.0)])
    assert dropped == 0
    assert _reasons(capsys) == {"no_group_sibling": 1}


def test_a_sibling_without_a_clock_is_reported_as_such(capsys):
    """Distinct from having no sibling: the row EXISTS and cannot be compared.
    Different gap, different fix, so it must not collapse into the other."""
    kept, dropped = drop_superseded_lines([_row("8.5", 7200.0), _row("9.0", None)])
    assert dropped == 0
    # The stale row is attributed to its clockless sibling; the clockless row is
    # itself reported, because a row with no clock can never be judged either.
    assert _reasons(capsys) == {"sibling_no_seen_age": 1, "no_seen_age": 1}


def test_a_sibling_fresher_but_inside_the_lag_reports_within_lag(capsys):
    """The rule working as specified -- 14 minutes is not 15. Counted so it can
    be told apart from a genuine gap, since the fix for it would be a threshold
    change and the fix for the others would not."""
    kept, dropped = drop_superseded_lines([_row("8.5", 1600.0), _row("9.0", 800.0)])
    assert dropped == 0
    assert _reasons(capsys)["within_lag"] == 1


def test_a_fresh_surviving_row_is_not_counted_as_a_gap(capsys):
    """A fresh row surviving is the rule working. Counting it would bury the
    three rows that matter under hundreds that do not."""
    drop_superseded_lines([_row("8.5", 30.0), _row("9.0", 20.0)])
    assert _reasons(capsys) == {}


def test_different_markets_are_not_each_others_siblings(capsys):
    """A collision would report a real gap as `within_lag` and hide it."""
    grid = [_row("8.5", 7200.0), _row("9.0", 60.0, market="spreads")]
    kept, dropped = drop_superseded_lines(grid)
    assert dropped == 0
    assert _reasons(capsys) == {"no_group_sibling": 1}


def test_the_counter_never_breaks_the_guard(capsys):
    """An instrument must not take down the filter it measures.

    Exercised against the REAL contract: `_seen_age_seconds` returns a float or
    None and nothing else, so those are the two inputs worth pinning.

    A first draft of this passed `"not a number"` and failed -- inside the
    PRE-EXISTING `float(seen)` at `book_grid.py:718`, which my counter does not
    touch. Recorded rather than silently hardened: that path is unreachable
    today because of the contract above, and widening a filter's error handling
    is a separate change from measuring it. If `seen_age_seconds` ever gains a
    third source, this is where it will bite.
    """
    kept, dropped = drop_superseded_lines([_row("8.5", None), _row("9.0", 7200.0)])
    assert len(kept) == 2
    kept, dropped = drop_superseded_lines([])
    assert kept == [] and dropped == 0
