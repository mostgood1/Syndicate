"""What the per-series cap COSTS, dated on the markets it actually cuts.

`BY_GAME_DATE` is built from the working set, so it can only ever show
SURVIVORS. Inferring the cut markets' dates from the kept markets' dates is the
same move that produced `#370` and its diagnostic sequel -- a number describing
one population read as if it described another. These tests pin that
`PRECAP_CUT_BY_DATE` counts the CUT slice, because a line that counted
survivors would look identical in the log and answer the opposite question.
"""

from __future__ import annotations

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
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SYNDICATE_KALSHI_REQUEST_SPACING_MS", "0")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


def _market(series: str, event: str, index: int):
    """A market whose GAME date lives in the ticker's event segment."""
    return {
        "ticker": f"{series}-{event}-{index}",
        "yes_ask_dollars": 0.4,
        "no_ask_dollars": 0.6,
        "series": series,
        "title": f"Player X: {index}+ hits?",
        # Deliberately a DIFFERENT date from every event segment below: if the
        # histogram ever reads this field the tests break, which is the point.
        "close_time": "2026-09-30T23:10:00Z",
    }


def _run_with(monkeypatch, capsys, markets_by_series):
    monkeypatch.setattr(mod, "sports_series", lambda: tuple(sorted(markets_by_series)))
    monkeypatch.setattr(
        mod,
        "fetch_series_markets",
        lambda series: {"markets": markets_by_series.get(series, []), "strategy": "series_filter"},
    )
    mod.run_kalshi_odds_refresh(force=True)
    for line in capsys.readouterr().out.splitlines():
        if "PRECAP_CUT_BY_DATE" in line:
            return line
    return ""


def test_the_dates_counted_are_the_CUT_markets_not_the_survivors(monkeypatch, capsys):
    """The whole point. Survivors and cuts carry DIFFERENT dates here.

    The first 400 are the board's date and the overflow is a week out. A line
    that counted survivors would report 2026-08-25; the honest one reports
    2026-09-01, because those are the markets that stopped existing.
    """
    kept = [_market("KXMLBHIT", "26AUG251945BALSTL", i) for i in range(mod.MAX_MARKETS_PER_SERIES)]
    cut = [_market("KXMLBHIT", "26SEP011945BALSTL", i) for i in range(120)]
    line = _run_with(monkeypatch, capsys, {"KXMLBHIT": kept + cut})

    assert "PRECAP_CUT_BY_DATE" in line
    assert "'2026-09-01': 120" in line, line
    assert "2026-08-25" not in line, "it counted the survivors, which answers the wrong question"
    assert "cut_total=120" in line
    assert "'fetched': 520" in line


def test_a_series_under_the_cap_is_not_reported_at_all(monkeypatch, capsys):
    # Nothing was cut, so there is no cost to report. A zero row for every
    # uncapped series would bury the ones that matter.
    kept = [_market("KXMLBKS", "26AUG251945BALSTL", i) for i in range(10)]
    assert _run_with(monkeypatch, capsys, {"KXMLBKS": kept}) == ""


def test_an_undatable_cut_ticker_is_named_not_dropped(monkeypatch, capsys):
    # Same rule `board_by_game_date` follows: refusing to date a market is a
    # real answer and must not silently shrink a total.
    kept = [_market("KXFUTURES", "26AUG251945BALSTL", i) for i in range(mod.MAX_MARKETS_PER_SERIES)]
    cut = [{**_market("KXFUTURES", "X", i), "ticker": "KXFUTURES"} for i in range(7)]
    line = _run_with(monkeypatch, capsys, {"KXFUTURES": kept + cut})

    assert "'<undatable_ticker>': 7" in line, line
    assert "cut_total=7" in line


def test_the_list_is_bounded_but_the_TOTAL_never_is(monkeypatch, capsys):
    """A bounded sample must not be able to read as a complete one.

    `MAX_UNREADABLE_SAMPLES` cost a cycle exactly here: the noisiest families
    reached the cap first, so eight soccer series were COUNTED as unreadable
    while not one soccer title was sampled.
    """
    over = mod.MAX_CAP_COST_SERIES + 5
    by_series = {
        f"KXS{n:02d}": (
            [_market(f"KXS{n:02d}", "26AUG251945BALSTL", i) for i in range(mod.MAX_MARKETS_PER_SERIES)]
            + [_market(f"KXS{n:02d}", "26SEP011945BALSTL", i) for i in range(n + 1)]
        )
        for n in range(over)
    }
    line = _run_with(monkeypatch, capsys, by_series)

    assert f"capped_series={over}" in line, line
    assert f"shown={mod.MAX_CAP_COST_SERIES}" in line
    assert f"cut_total={sum(n + 1 for n in range(over))}" in line
    # Biggest loss first -- a truncated list sorted arbitrarily would hide the
    # series the change is meant to be decided on.
    assert f"KXS{over - 1:02d}" in line
    assert "KXS00" not in line
