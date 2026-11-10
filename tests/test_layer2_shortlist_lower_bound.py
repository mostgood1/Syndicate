"""A date's shortlist holds only that Central date's games and later ones (todo #779, lane layer2-lookahead-live-dedupe).

User decision 2026-11-10, "Yes, fix it too": add a lower date bound to the shortlist. `_within_horizon` bounded a board
from above only, so the 11-11 look-ahead shortlist carried that night's NCAAB games (tip 5-9 PM CT 11-10). The 11-11
`portfolio_commit` plan is built from that shortlist (`pipeline/portfolio_commit.py` `run_portfolio_commit`), so only
the venues' commence-time refusals kept those rows from trading.

The bound is the board's OWN midnight Central, never the wall clock, so the prior date's carryover rebuild
(`layer2-prior-date-live-carryover`) keeps its own games after midnight.
"""
from __future__ import annotations

import itertools
import os
from datetime import datetime, timezone
from unittest.mock import patch

from pipeline.layer2_shortlist import _date_start_central
from syndicate.features.shared.layer2_board import select_shortlist, shortlist_lower_date_bound_enabled

_SEQ = itertools.count()
BUILT_EVENING = datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc)     # 4:00 PM CT 11-10
AFTER_MIDNIGHT = datetime(2026, 11, 11, 7, 30, tzinfo=timezone.utc)    # 1:30 AM CT 11-11
TODAY = _date_start_central("2026-11-10")
TOMORROW = _date_start_central("2026-11-11")


def _cand(start, sport="ncaab", score=10.0, **extra):
    row = {"sport": sport, "kind": "game", "market": "totals", "event_id": f"evt{next(_SEQ)}",
           "commence_time": start, "score": {"score": score}}
    row.update(extra)
    return row


def _tonight_and_tomorrow():
    return [
        _cand("2026-11-10T23:00:00Z"),   # 5:00 PM CT 11-10: tonight
        _cand("2026-11-11T02:00:00Z"),   # 8:00 PM CT 11-10: tonight, UTC date already 11-11
        _cand("2026-11-11T18:00:00Z"),   # 12:00 PM CT 11-11
        _cand("2026-11-12T01:00:00Z"),   # 7:00 PM CT 11-11, UTC date 11-12
    ]


def _starts(result):
    return sorted(r["commence_time"] for r in result["rows"])


def _env_without_flag():
    return {k: v for k, v in os.environ.items() if k != "SYNDICATE_SHORTLIST_LOWER_DATE_BOUND"}


def test_absent_flag_is_on():
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        assert shortlist_lower_date_bound_enabled() is True


def test_a_look_ahead_board_drops_tonights_games_and_keeps_its_whole_own_day():
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        result = select_shortlist(_tonight_and_tomorrow(), now=BUILT_EVENING, horizon_anchor=TOMORROW)
    assert _starts(result) == ["2026-11-11T18:00:00Z", "2026-11-12T01:00:00Z"]
    assert result["rows_before_board_date"] == 2
    assert result["rows_before_board_date_by_sport"] == {"ncaab": 2}
    assert result["lower_date_bound"] == "2026-11-11T06:00:00Z"
    assert result["rows_beyond_horizon"] == 0


def test_the_bound_is_midnight_central_to_the_second():
    rows = [_cand("2026-11-11T05:59:59Z"), _cand("2026-11-11T06:00:00Z")]
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        result = select_shortlist(rows, now=BUILT_EVENING, horizon_anchor=TOMORROW)
    assert _starts(result) == ["2026-11-11T06:00:00Z"]
    assert result["rows_before_board_date"] == 1


def test_todays_board_keeps_tonights_games():
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        result = select_shortlist(_tonight_and_tomorrow(), now=BUILT_EVENING, horizon_anchor=TODAY)
    assert "2026-11-10T23:00:00Z" in _starts(result) and "2026-11-11T02:00:00Z" in _starts(result)
    assert result["rows_before_board_date"] == 0


def test_the_carryover_rebuild_after_midnight_keeps_its_own_dates_live_game():
    """`layer2-prior-date-live-carryover` rebuilds 11-10 at 1:30 AM CT 11-11. Its 10 PM CT game is still in play and
    must stay on 11-10's shortlist. An 11-09 game the pool still holds goes."""
    live = {"game": {"state": "live"}}
    rows = [
        _cand("2026-11-11T04:00:00Z", **live),   # 10:00 PM CT 11-10, still in play
        _cand("2026-11-10T05:30:00Z", **live),   # 11:30 PM CT 11-09
    ]
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        result = select_shortlist(rows, now=AFTER_MIDNIGHT, horizon_anchor=TODAY)
    assert _starts(result) == ["2026-11-11T04:00:00Z"]
    assert result["rows_before_board_date"] == 1
    assert result["lower_date_bound"] == "2026-11-10T06:00:00Z"


def test_after_the_roll_the_new_dates_board_drops_last_nights_late_game():
    live = {"game": {"state": "live"}}
    rows = [_cand("2026-11-11T04:00:00Z", **live), _cand("2026-11-11T23:00:00Z")]
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        result = select_shortlist(rows, now=AFTER_MIDNIGHT, horizon_anchor=TOMORROW)
    assert _starts(result) == ["2026-11-11T23:00:00Z"]
    assert result["rows_before_board_date_by_sport"] == {"ncaab": 1}


def test_a_week_board_keeps_its_forward_days_and_drops_only_earlier_ones():
    rows = [_cand("2026-11-10T20:00:00Z", sport="soccer"),
            _cand("2026-11-11T20:00:00Z", sport="soccer"),
            _cand("2026-11-16T20:00:00Z", sport="soccer")]
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        result = select_shortlist(rows, now=BUILT_EVENING, horizon_anchor=TOMORROW)
    assert _starts(result) == ["2026-11-11T20:00:00Z", "2026-11-16T20:00:00Z"]
    assert result["rows_before_board_date_by_sport"] == {"soccer": 1}


def test_a_row_with_no_or_a_bad_start_time_is_kept():
    rows = [_cand(None), _cand("not-a-date")]
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        result = select_shortlist(rows, now=BUILT_EVENING, horizon_anchor=TOMORROW)
    assert len(result["rows"]) == 2
    assert result["rows_before_board_date"] == 0


def test_an_unanchored_call_has_no_lower_bound():
    """The in-play overlay calls `select_shortlist(opportunities)` with no board date."""
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        result = select_shortlist(_tonight_and_tomorrow(), now=BUILT_EVENING)
    assert result["lower_date_bound"] is None
    assert result["rows_before_board_date"] == 0
    assert "2026-11-10T23:00:00Z" in _starts(result)


def test_off_switch_restores_the_old_selection_reachability():
    """off != on, on the same input: the flag reaches the rule."""
    rows = _tonight_and_tomorrow()
    with patch.dict(os.environ, {"SYNDICATE_SHORTLIST_LOWER_DATE_BOUND": "off"}, clear=False):
        off = select_shortlist(rows, now=BUILT_EVENING, horizon_anchor=TOMORROW)
    with patch.dict(os.environ, _env_without_flag(), clear=True):
        on = select_shortlist(rows, now=BUILT_EVENING, horizon_anchor=TOMORROW)
    assert off["lower_date_bound"] is None and off["rows_before_board_date"] == 0
    assert len(off["rows"]) == 4 and len(on["rows"]) == 2
    assert _starts(off) != _starts(on)


def test_the_shortlist_builder_anchors_on_the_selected_date():
    """The plan reads `read_layer2_shortlist(date)`, written by `build_layer2_shortlist`, which must pass the
    board's own date as the anchor or the bound never applies to the plan."""
    import inspect

    from pipeline import layer2_shortlist

    source = inspect.getsource(layer2_shortlist.build_layer2_shortlist)
    assert "anchor = _date_start_central(selected_date)" in source
    assert source.count("horizon_anchor=anchor") == 2
