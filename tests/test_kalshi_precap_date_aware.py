"""The per-series cap spends its 400 slots on the BOARD'S games, not on order.

`markets[:400]` is date-blind, so which rungs survived was whichever order
Kalshi answered in. Measured 2026-09-09 by replaying the mirrored production
artifact of the 2026-09-08T18:41:03Z tick through `select_markets_for_cap`:
`KXNCAAFTOTAL` fetched 1,577 and the retained 400 were ALL 2026-09-12, so all
114 rungs of the two nearer game dates (09-10 and 09-11) were destroyed. Under
the same budget the date-aware rule keeps 19 + 95 + 286.

The cap itself is NOT the defect and is not touched here -- the keyvalue store
refuses at 8MB and the module's own note says "Shrink the payload rather than
raising the ceiling". So every test below asserts the SAME budget: the retained
count is identical under both modes, and identical to the input under the cap.
What changes is which 400 those are.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from pipeline import kalshi_odds_refresh as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    for name in (
        "SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS",
        "SYNDICATE_KALSHI_SERIES",
        "SYNDICATE_KALSHI_SERIES_PER_TICK",
        "SYNDICATE_KALSHI_DORMANT_INTERVAL_SECONDS",
        "SYNDICATE_KALSHI_PRECAP_DATE_AWARE",
        "SYNDICATE_KALSHI_PRECAP_WINDOW_AHEAD_DAYS",
        "SYNDICATE_KALSHI_PRECAP_WINDOW_BACK_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SYNDICATE_KALSHI_REQUEST_SPACING_MS", "0")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


WINDOW = ("2026-09-08", "2026-09-11")
CAP = mod.MAX_MARKETS_PER_SERIES


def _market(series: str, event: str, index: int) -> dict:
    return {
        "ticker": f"{series}-{event}-{index}",
        "series": series,
        "yes_ask_dollars": 0.4,
        "no_ask_dollars": 0.6,
        "title": f"Over {index}.5 points scored",
        # A settlement deadline, days after the game. Any code that dated a
        # market off this field would put every market below on one date.
        "close_time": "2026-09-30T23:10:00Z",
    }


def _dated(series: str, event: str, n: int, start: int = 0) -> list[dict]:
    return [_market(series, event, i) for i in range(start, start + n)]


def _undated(series: str, n: int) -> list[dict]:
    # A real shape: a ticker whose event segment carries no readable date, which
    # is what an unparseable player prop looks like to `game_date_from_ticker`.
    return [{**_market(series, "SEASON", i), "ticker": f"{series}-SEASON-{i}"} for i in range(n)]


# --------------------------------------------------------------------------
# The budget. Asserted first, because a selection fix that grows the payload is
# the write-rejection incident again.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("date_aware", [False, True])
def test_the_retained_count_is_the_same_cap_under_both_modes(date_aware):
    markets = _dated("KXNCAAFTOTAL", "26SEP20WIUWIS", 1200) + _dated(
        "KXNCAAFTOTAL", "26SEP09BALSTL", 767
    )
    kept, cut, counts = mod.select_markets_for_cap(
        markets, CAP, WINDOW, date_aware=date_aware
    )
    assert len(kept) == CAP
    assert len(cut) == len(markets) - CAP
    assert counts["fetched"] == 1967
    assert counts["kept"] == CAP
    assert counts["cut"] == 1567


@pytest.mark.parametrize("date_aware", [False, True])
def test_under_the_cap_the_input_is_returned_unchanged(date_aware):
    markets = _dated("KXMLBHIT", "26SEP20WIUWIS", 12)
    kept, cut, counts = mod.select_markets_for_cap(
        markets, CAP, WINDOW, date_aware=date_aware
    )
    assert kept == markets, "an under-cap series must not be reordered or shrunk"
    assert cut == []
    assert counts["cut"] == 0


# --------------------------------------------------------------------------
# off != on. The reachability proof: same input, two rules, different survivors.
# --------------------------------------------------------------------------


def test_off_keeps_arrival_order_and_on_keeps_the_board_window():
    """The in-window rungs arrive LAST, so arrival order destroys all of them."""
    markets = _dated("KXNCAAFTOTAL", "26SEP20WIUWIS", 1200) + _dated(
        "KXNCAAFTOTAL", "26SEP09BALSTL", 767
    )

    kept_off, _, counts_off = mod.select_markets_for_cap(
        markets, CAP, WINDOW, date_aware=False
    )
    kept_on, _, counts_on = mod.select_markets_for_cap(
        markets, CAP, WINDOW, date_aware=True
    )

    assert kept_off == markets[:CAP], "off must be byte-identical to the old slice"
    assert counts_off["kept_in_window"] == 0
    assert counts_off["cut_in_window"] == 767

    assert counts_on["kept_in_window"] == CAP
    assert counts_on["cut_in_window"] == 767 - CAP
    assert kept_on != kept_off, "off == on means the flag is inert"


def test_nearest_game_first_then_forward_then_the_recent_past():
    """Rank order, on one series small enough to read the whole result."""
    markets = (
        _dated("KXNFLTOTAL", "26DEC24AAABBB", 3)  # far forward
        + _dated("KXNFLTOTAL", "26SEP05CCCDDD", 3)  # past, before the window
        + _dated("KXNFLTOTAL", "26SEP11EEEFFF", 3)  # in window, late
        + _dated("KXNFLTOTAL", "26SEP09GGGHHH", 3)  # in window, today
    )
    kept, cut, counts = mod.select_markets_for_cap(markets, 7, WINDOW, date_aware=True)
    kept_events = {m["ticker"].split("-")[1] for m in kept}

    assert "26SEP09GGGHHH" in kept_events and "26SEP11EEEFFF" in kept_events
    assert counts["kept_in_window"] == 6
    # The seventh slot goes to the nearest FUTURE game, not to a played one.
    assert "26DEC24AAABBB" in kept_events
    assert {m["ticker"].split("-")[1] for m in cut} == {"26SEP05CCCDDD", "26DEC24AAABBB"}


# --------------------------------------------------------------------------
# Undated markets. The decision is a RESERVE, not a drop.
# --------------------------------------------------------------------------


def test_undated_markets_keep_a_reserved_minority_when_dated_ones_could_fill_the_cap():
    """Dropping them was tried and reverted: props skip the join's date check.

    In-window markets alone exceed the budget here, so a pure date-first order
    would evict every undated market. The reserve is what stops this fix from
    repeating the defect it removes.
    """
    markets = _dated("KXMLBHRR", "26SEP09BALSTL", 600) + _undated("KXMLBHRR", 200)
    kept, _, counts = mod.select_markets_for_cap(markets, CAP, WINDOW, date_aware=True)

    assert counts["kept_undated"] == mod.PRECAP_UNDATED_RESERVE == 40
    assert counts["kept_in_window"] == CAP - mod.PRECAP_UNDATED_RESERVE
    assert len(kept) == CAP
    assert counts["cut_undated"] == 160


def test_an_entirely_undated_series_is_unaffected_by_the_reserve():
    """A futures ladder has no in-window rival, so it still fills the budget."""
    markets = _undated("KXNCAAFWINS", 618)
    kept_off, _, counts_off = mod.select_markets_for_cap(
        markets, CAP, WINDOW, date_aware=False
    )
    kept_on, _, counts_on = mod.select_markets_for_cap(
        markets, CAP, WINDOW, date_aware=True
    )
    assert len(kept_on) == len(kept_off) == CAP
    assert counts_on["kept_undated"] == CAP
    assert counts_off["kept_undated"] == CAP


def test_undated_markets_are_preferred_over_dated_ones_outside_the_window():
    """A future with no readable date can still join; a December rung cannot.

    Ordering them behind out-of-window games would have made the reserve the
    only thing keeping them alive, which is a much weaker guarantee than it
    reads as.
    """
    markets = _dated("KXNBAGAME", "26DEC24AAABBB", 500) + _undated("KXNBAGAME", 100)
    _, _, counts = mod.select_markets_for_cap(markets, CAP, WINDOW, date_aware=True)
    assert counts["kept_undated"] == 100


# --------------------------------------------------------------------------
# The counters, and the artifact the board actually reads.
# --------------------------------------------------------------------------


def _run_with(monkeypatch, capsys, markets_by_series):
    monkeypatch.setattr(mod, "sports_series", lambda: tuple(sorted(markets_by_series)))
    monkeypatch.setattr(
        mod,
        "fetch_series_markets",
        lambda series: {"markets": markets_by_series.get(series, []), "strategy": "series_filter"},
    )
    mod.run_kalshi_odds_refresh(force=True)
    out = capsys.readouterr().out
    line = ""
    for candidate in out.splitlines():
        if "PRECAP_SELECT" in candidate:
            line = candidate
    return line


_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _event(day: date, teams: str) -> str:
    """Kalshi's own event segment: `26SEP12WIUWIS`."""
    return f"{day.year % 100:02d}{_MONTHS[day.month - 1]}{day.day:02d}{teams}"


def _slate(series: str) -> tuple[list[dict], str]:
    """500 far-forward rungs arriving BEFORE 300 on a real board date.

    Dates are derived from `board_window_dates()` rather than hard-coded, so
    the test asserts against the window production would compute today.
    """
    start, _end = mod.board_window_dates()
    board_day = date.fromisoformat(start)
    far = board_day + timedelta(days=90)
    return (
        _dated(series, _event(far, "XXXYYY"), 500)
        + _dated(series, _event(board_day, "BALSTL"), 300),
        start,
    )


def test_the_counters_report_what_the_cut_cost_inside_the_board_window(monkeypatch, capsys):
    markets, start = _slate("KXNCAAFTOTAL")
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_DATE_AWARE", "1")
    line = _run_with(monkeypatch, capsys, {"KXNCAAFTOTAL": markets})

    assert "mode=date_aware" in line, line
    assert f"window={start}.." in line
    assert "cap=400" in line and "undated_reserve=40" in line
    assert "fetched_total=800" in line
    assert "kept_total=400" in line
    assert "cut_total=400" in line
    assert "kept_in_window_total=300" in line
    assert "cut_in_window_total=0" in line
    assert "'fetched': 800" in line and "'cut_in_window': 0" in line


def test_the_same_slate_under_the_old_slice_reports_the_loss_it_causes(monkeypatch, capsys):
    markets, _start = _slate("KXNCAAFTOTAL")
    line = _run_with(monkeypatch, capsys, {"KXNCAAFTOTAL": markets})

    assert "mode=arrival" in line, line
    # The whole finding, in one number: 300 in-window rungs destroyed while 400
    # far-forward ones were kept, on the same budget.
    assert "kept_in_window_total=0" in line
    assert "cut_in_window_total=300" in line
    assert "kept_total=400" in line, "the budget is unchanged -- only the choice is bad"


def test_the_persisted_artifact_holds_the_selected_markets_not_a_second_slice(
    monkeypatch, capsys
):
    """The board reads the ARTIFACT, so a fix that stops at the working set ships nothing."""
    markets, start = _slate("KXMLBTB")
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_DATE_AWARE", "1")
    _run_with(monkeypatch, capsys, {"KXMLBTB": markets})

    from syndicate.features.shared.kalshi_catalogue import game_date_from_ticker

    stored = json.loads(mod.markets_artifact_path().read_text(encoding="utf-8"))
    rows = stored["series"]["KXMLBTB"]["markets"]
    assert len(rows) == mod.MAX_MARKETS_PER_SERIES, "the payload must not grow"
    dated = [game_date_from_ticker(r.get("ticker")) for r in rows]
    # Every rung of the board's own date survived into the payload the board
    # reads back; the arbitrary slice persisted none of them.
    assert sum(1 for d in dated if d == start) == 300, dated[:3]


def test_absent_flag_is_the_old_behaviour(monkeypatch):
    monkeypatch.delenv("SYNDICATE_KALSHI_PRECAP_DATE_AWARE", raising=False)
    assert mod.precap_date_aware_enabled() is False
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_DATE_AWARE", "1")
    assert mod.precap_date_aware_enabled() is True
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_DATE_AWARE", "off")
    assert mod.precap_date_aware_enabled() is False


def test_a_bad_window_env_falls_back_to_the_default_not_to_zero(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_WINDOW_AHEAD_DAYS", "")
    start, end = mod.board_window_dates()
    assert (date.fromisoformat(end) - date.fromisoformat(start)).days == 3
