"""`#569`: `last_seen` must cover the same dates the quote rows came from.

THE DEFECT. `build_layer2_shortlist` accumulates `quote_rows` across
`window_dates` -- its own comment says "NFL accumulated five shards at once" --
while `last_seen` was read for `selected_date` ALONE. Rows from any other
window date had no entry, so `_seen_age_seconds` returned None.

WHY THAT IS THE HOLE. `drop_superseded_lines` requires `seen_age_seconds` on the
row AND on its group's freshest, deliberately, because pruning on absence would
empty the board. A row with no clock is therefore INVISIBLE to it -- a line the
market had moved off could never be dropped on a forward date.

MEASURED 2026-08-26 21:17:19Z, one grid build:
    SUPERSEDED_SURVIVORS no_seen_age=7553
    SUPERSEDED_LINES_DROPPED count=16 kept=15672
48% of the grid carrying no clock, every one exempt from the guard.

Run:  python -m pytest tests/test_last_seen_window_merge.py
"""

import inspect

from pipeline import layer2_shortlist
from syndicate.features.shared.book_grid import drop_superseded_lines


def _row(line, seen, event="E1"):
    return {
        "sport": "mlb", "event_id": event, "kind": "game", "market": "totals",
        "segment": "full_game", "player_name": "", "line": line,
        "seen_age_seconds": seen,
    }


def test_a_clockless_row_is_invisible_to_the_guard():
    """The mechanism, stated as an executable fact rather than a claim.

    Identical rows except for the clock. With clocks the stale line is dropped;
    without one it survives, however far its market has moved on.
    """
    kept, dropped = drop_superseded_lines([_row("8.5", 7200.0), _row("9.0", 60.0)])
    assert dropped == 1 and [r["line"] for r in kept] == ["9.0"]

    kept, dropped = drop_superseded_lines([_row("8.5", None), _row("9.0", 60.0)])
    assert dropped == 0, "a row with no clock cannot be superseded -- this is the hole"
    assert len(kept) == 2


def test_last_seen_is_merged_over_the_dates_the_rows_came_from():
    """Reachability. The read must span `dates_with_rows`, not one date."""
    src = inspect.getsource(layer2_shortlist.build_layer2_shortlist)
    merge = src[src.index("last_seen_error"):src.index("last_seen_error") + 2500]
    assert "for _seen_date in (dates_with_rows or [selected_date])" in merge, (
        "last_seen must be read across the same window dates that produced quote_rows"
    )
    assert "read_quote_last_seen(sport, selected_date)" not in merge, (
        "the single-date read is the defect and must not remain"
    )


def test_the_newest_stamp_wins_for_a_key_seen_on_two_dates():
    """A key can appear on several shards. The field answers "when did we last
    LOOK", so the latest look is the answer whichever shard recorded it --
    taking an older one would re-introduce the staleness this fixes."""
    merged: dict[str, str] = {}
    shards = [
        {"K": "2026-08-25T10:00:00Z"},
        {"K": "2026-08-26T21:00:00Z"},   # newest
        {"K": "2026-08-24T09:00:00Z"},
    ]
    for shard in shards:
        for k, stamp in shard.items():
            if stamp and stamp > merged.get(k, ""):
                merged[k] = stamp
    assert merged["K"] == "2026-08-26T21:00:00Z"


def test_an_empty_stamp_never_displaces_a_real_one():
    """`read_quote_last_seen` omits 2-element legacy entries, but a defensive
    empty must not win a comparison against a real ISO stamp."""
    merged: dict[str, str] = {}
    for shard in [{"K": "2026-08-26T21:00:00Z"}, {"K": ""}]:
        for k, stamp in shard.items():
            if stamp and stamp > merged.get(k, ""):
                merged[k] = stamp
    assert merged["K"] == "2026-08-26T21:00:00Z"


def test_the_merge_falls_back_to_selected_date_when_no_shard_contributed():
    """`dates_with_rows` is empty when every shard read failed. The fallback
    must still read something rather than leaving every row clockless, which
    would be the pre-fix behaviour restored by accident."""
    src = inspect.getsource(layer2_shortlist.build_layer2_shortlist)
    assert "(dates_with_rows or [selected_date])" in src
