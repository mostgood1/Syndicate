"""Today's slate must reach the board it is the board FOR.

Measured on the served shortlist 2026-08-21, soccer, 100 rows: 4 were that
day's four fixtures, 96 were dated 08-22..08-27, and Marseille v Strasbourg --
kicking off in three hours -- had ZERO rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.shared import layer2_board


NOW = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)


def _row(idx, *, days_out, ev, event=None):
    start = NOW + timedelta(days=days_out)
    return {
        "sport": "soccer",
        "kind": "game",
        "market": "h2h",
        "side": "home",
        "home_team": f"H{event if event is not None else idx}",
        "away_team": f"A{event if event is not None else idx}",
        "event_id": f"e{event if event is not None else idx}",
        "commence_time": start.isoformat(),
        "ev_pct": ev,
        # _score_of reads score.score -- without it every row ties at -inf and
        # the ranking this test is about does not happen.
        "score": {"score": ev},
        "quote": {"price": -110, "bookmaker": "bk", "age_seconds": 30},
        "projection": {"model_prob_over": 0.55, "basis": "win_probability"},
        "model_edge_pct": ev,
    }


# THE POOL MUST OUTNUMBER THE CAP OR THIS FILE TESTS NOTHING (`#521`).
#
# It was written against a hard 100 rows/sport with a 150-row tomorrow pool, so
# tomorrow genuinely crowded today out. `SHORTLIST_ROWS_PER_SPORT` became the
# configurable `_shortlist_rows_per_sport()` at 400 the same day the cap was
# raised, and 160 rows then fit inside the budget with room to spare -- so
# everything was selected, today included, and the starvation these tests exist
# to reproduce simply stopped happening.
#
# `test_without_the_floor_today_is_crowded_out` says it in its own docstring:
# "If this ever stops showing starvation the fixture no longer models the bug."
# It did, and the test failed loudly rather than passing vacuously, which is the
# only reason this was caught -- the two sibling files broken by the same cap
# raise had to be found by reading.
#
# Sized off the limit rather than pinned to a new number, so the next change to
# the cap cannot quietly repeat this.
def _limit():
    return int(layer2_board._shortlist_rows_per_sport())


def _pool():
    """Today's rows are genuinely WORSE on merit -- that is the real situation,
    and the reason a pure ranking excludes them."""
    rows = [_row(i, days_out=0, ev=0.2, event=f"today{i}") for i in range(10)]
    rows += [_row(100 + i, days_out=1, ev=5.0, event=f"tmw{i}") for i in range(_limit() + 50)]
    return rows


def _run(**kw):
    return layer2_board.select_shortlist(
        _pool(), now=NOW, horizon_days=7, min_value_pct=-100.0, **kw
    )


def test_without_the_floor_today_is_crowded_out():
    """OFF: the pre-change behaviour, reproduced. If this ever stops showing
    starvation the fixture no longer models the bug."""
    result = _run(imminence_floor=0)
    soccer = result["per_sport"]["soccer"]
    assert soccer["available_today"] == 10
    assert soccer["selected_today"] == 0, soccer


def test_with_the_floor_today_is_seated():
    """ON. off != on, on the same pool."""
    result = _run(imminence_floor=25)
    soccer = result["per_sport"]["soccer"]
    assert soccer["selected_today"] == 10, soccer
    assert soccer["imminence_seated"] == 10


def test_floor_is_a_floor_not_a_takeover():
    """Merit still fills the rest -- today does not get the whole board just
    for being today."""
    result = _run(imminence_floor=25)
    soccer = result["per_sport"]["soccer"]
    assert soccer["selected"] == _limit()
    assert soccer["selected_today"] < soccer["selected"]


def test_unused_floor_is_not_wasted():
    """A sport with nothing today must still fill its budget."""
    rows = [_row(100 + i, days_out=1, ev=5.0, event=f"tmw{i}") for i in range(_limit() + 50)]
    result = layer2_board.select_shortlist(
        rows, now=NOW, horizon_days=7, min_value_pct=-100.0, imminence_floor=25
    )
    soccer = result["per_sport"]["soccer"]
    assert soccer["available_today"] == 0
    assert soccer["selected"] == _limit()


def test_row_without_a_start_time_is_not_treated_as_today():
    """Keeping an unknown row is safe; SEATING one on today's guarantee spends
    reserved slots on rows that may not be today at all."""
    assert layer2_board._kicks_off_on_date({}, NOW) is False
    assert layer2_board._kicks_off_on_date({"commence_time": "not-a-date"}, NOW) is False
    assert layer2_board._kicks_off_on_date({"commence_time": NOW.isoformat()}, NOW) is True
