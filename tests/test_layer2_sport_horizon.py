"""`#380` -- one global horizon is correct only for sports whose slate is one day.

MEASURED LIVE 2026-08-12, immediately after `#379` widened the READ window:

    soccer  quote_rows 16,065  opportunities 2,359  ->  0 rows on the board
    soccer fixtures: 08-14 (4) · 08-15 (25) · 08-16 (24) · 08-17 (5)
    anchor 2026-08-12, horizon_days 1

`#379` fixed which dates were READ and left which dates were KEPT at one day, so
the counter simply moved: `rows_beyond_horizon` went 2,670 -> 5,029. Half a fix,
and the other half was visible in the number that grew.

WHAT THIS IS NOT. `#268` proposed a per-sport VALUE floor for the same symptom,
on the premise that "soccer's 3-way markets hold more than MLB's 2-way". Two
measurements killed that:

    rows_below_value_floor: 0        the floor discards nothing, for any sport
    median hold: soccer 5.53%, mlb 6.35%   soccer's aggregate hold is LOWER

So a hold-scaled floor would have made soccer's floor LESS permissive, moving it
further from the board, to fix a filter that was already removing zero rows.

Reuses `slate_window_days` rather than adding a third notion of "which dates
count" -- Layer 1 boards by it, `#379` reads by it, and the disagreement between
two such notions is precisely what produced this bug.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.shared.layer2_board import _within_horizon

NOW = datetime(2026, 8, 12, 15, 0, 0, tzinfo=timezone.utc)


def _row(sport: str, *, days_out: int) -> dict:
    start = NOW + timedelta(days=days_out)
    return {"sport": sport, "commence_time": start.strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_soccer_fixtures_days_out_are_kept():
    # The exact fixtures that were discarded: 08-14 through 08-17 from an
    # 08-12 anchor, i.e. 2 to 5 days out.
    for days in (2, 3, 4, 5):
        assert _within_horizon(_row("soccer", days_out=days), NOW, 1), (
            f"soccer fixture {days}d out was dropped -- this is the #379 half-fix"
        )


def test_soccer_stops_at_its_own_window_edge():
    # 7 dates inclusive of today == a delta of 6. Off by one here would silently
    # drop each sport's last day, which is the failure this comment guards.
    assert _within_horizon(_row("soccer", days_out=6), NOW, 1)
    assert not _within_horizon(_row("soccer", days_out=7), NOW, 1)


def test_single_day_sports_are_unchanged():
    # The change must be a no-op where the global horizon was already right --
    # widening MLB would put tomorrow's slate on today's board.
    for sport in ("mlb", "nba", "wnba", "nhl", "ncaab"):
        assert _within_horizon(_row(sport, days_out=1), NOW, 1)
        assert not _within_horizon(_row(sport, days_out=2), NOW, 1), f"{sport} widened unexpectedly"


def test_multi_day_sports_match_their_layer1_windows():
    # nfl 7 dates -> delta 6; ncaaf 3 -> delta 2.
    #
    # NFL widened 5 -> 7 on 2026-08-16 so the preseason week (Fri/Sat/Sun/Mon,
    # which starts at +5 from a Sunday anchor) is reachable at all. THIS TEST
    # TRACKING IT IS THE POINT: its name says these horizons match Layer 1's
    # windows, and the shared `slate_window_days` table is what makes that true
    # by construction rather than by two constants agreeing today.
    assert _within_horizon(_row("nfl", days_out=6), NOW, 1)
    assert not _within_horizon(_row("nfl", days_out=7), NOW, 1)
    assert _within_horizon(_row("ncaaf", days_out=2), NOW, 1)
    assert not _within_horizon(_row("ncaaf", days_out=3), NOW, 1)


def test_an_explicit_wider_horizon_still_wins():
    # A caller asking for 10 days means it; the per-sport window raises the
    # floor, it must never lower a deliberate override.
    assert _within_horizon(_row("mlb", days_out=9), NOW, 10)


def test_horizon_none_still_disables_the_filter():
    assert _within_horizon(_row("soccer", days_out=99), NOW, None)


def test_an_unknown_sport_falls_back_to_the_global_horizon():
    # Never widen for a sport nobody has sized. Unknown must not mean permissive.
    assert _within_horizon(_row("cricket", days_out=1), NOW, 1)
    assert not _within_horizon(_row("cricket", days_out=2), NOW, 1)
    assert not _within_horizon({"commence_time": _row("x", days_out=2)["commence_time"]}, NOW, 1)


def test_a_row_with_no_start_time_is_still_kept():
    # Pre-existing contract: absence of a start is not evidence of being late,
    # and every non-MLB sport ships game.state as None.
    assert _within_horizon({"sport": "soccer"}, NOW, 1)
    assert _within_horizon({"sport": "mlb", "commence_time": "not-a-date"}, NOW, 1)
