"""NFL preseason odds must reach the shared quote log, not just a CSV.

THE DEFECT, measured on production 2026-08-07: `/api/board/book-grid?sport=nfl`
carried 1,246 rows across 272 events whose `commence_time` ran
2026-09-10..2027-01-10 -- entirely regular season -- while the one real
preseason game in the window (CAR @ ARI, 2026-08-06) had no row at all.

It was a plumbing gap, not a fetch gap. `fetch_nfl_preseason_odds.py` already
pulls the real `americanfootball_nfl_preseason` sport key (distinct from the
regular season's `americanfootball_nfl`), but wrote that response only to
`preseason_odds_{season}.csv` for the preseason cards page. `book-grid` reads
`book_quotes` and nothing else, so every paid-for preseason price was discarded
before it could reach the board.

Note on how the production absence was established: matched by TEAM NAME, never
by event id. The board keys on OddsAPI hex ids (`8c94552d022a...`) and the
preseason schedule on ESPN numerics (`401873271`), so an id comparison returns
"absent" for the wrong reason -- it would have looked like a capture gap even if
capture were working.
"""

from __future__ import annotations

import pytest

from scripts import fetch_nfl_preseason_odds


def _preseason_event() -> dict:
    """One OddsAPI event in the real response shape, two books, three markets."""
    return {
        "id": "8c94552d022acec4a0458d70c19d3da9",
        "sport_key": "americanfootball_nfl_preseason",
        "commence_time": "2026-08-07T00:00:00Z",
        "home_team": "Arizona Cardinals",
        "away_team": "Carolina Panthers",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Carolina Panthers", "price": 170},
                            {"name": "Arizona Cardinals", "price": -192},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Carolina Panthers", "price": -110, "point": 3.5},
                            {"name": "Arizona Cardinals", "price": -110, "point": -3.5},
                        ],
                    },
                ],
            },
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Carolina Panthers", "price": 165},
                            {"name": "Arizona Cardinals", "price": -185},
                        ],
                    },
                ],
            },
        ],
    }


@pytest.fixture
def captured(monkeypatch):
    """Intercept the append instead of writing a shard."""
    calls: list[dict] = []

    def _fake_append(*, sport, date_str, rows, captured_at, publish=True, extra=None):
        materialized = list(rows)
        calls.append(
            {
                "sport": sport,
                "date_str": date_str,
                "rows": materialized,
                "captured_at": captured_at,
            }
        )
        return {"appended": len(materialized), "considered": len(materialized)}

    monkeypatch.setattr(
        "syndicate.features.shared.odds_book_quotes.append_book_quotes",
        _fake_append,
    )
    return calls


def test_preseason_events_reach_the_quote_log(captured):
    fetch_nfl_preseason_odds._append_nfl_preseason_book_quotes([_preseason_event()])

    assert len(captured) == 1, "preseason odds never reached book_quotes -- this is the production defect"
    call = captured[0]
    # Sharded under the board's own sport slug. A separate "nfl_preseason" slug
    # would need a whole new board rather than populating the existing one.
    assert call["sport"] == "nfl"
    assert call["rows"], "quote rows were empty -- the OddsAPI response was dropped"


def test_every_book_is_kept_not_just_the_chosen_one(captured):
    fetch_nfl_preseason_odds._append_nfl_preseason_book_quotes([_preseason_event()])

    books = {row.get("bookmaker") for row in captured[0]["rows"]}
    # The CSV path keeps ONE book (choose_bookmaker); the quote log is the
    # reason the other books in the same paid-for response are not thrown away.
    assert books == {"draftkings", "fanduel"}, f"expected both books, got {books}"


def test_both_markets_survive_the_flattening(captured):
    fetch_nfl_preseason_odds._append_nfl_preseason_book_quotes([_preseason_event()])

    markets = {row.get("market") for row in captured[0]["rows"]}
    assert "h2h" in markets and "spreads" in markets, f"markets lost: {markets}"


def test_append_runs_before_schedule_matching():
    """The append must not be gated on the schedule mirror being fresh.

    `build_odds_rows` drops any event it cannot match against
    `schedule_preseason_{season}.csv`. That mirror is refreshed by a manual CLI
    wired into no pipeline, and was measured stale on 2026-08-07 -- so gating
    the quote log on it would discard prices precisely when the schedule is
    broken, which is the situation that produced this bug.
    """
    import ast
    import inspect
    import textwrap

    # Parsed, not string-searched: a substring scan matches the function names
    # inside comments and docstrings too, which made the first version of this
    # test read the explanatory comment above the call rather than the call.
    tree = ast.parse(textwrap.dedent(inspect.getsource(fetch_nfl_preseason_odds.main)))
    order: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            order.append((node.lineno, node.func.id))
    by_line = [name for _, name in sorted(order)]

    assert "_append_nfl_preseason_book_quotes" in by_line, "the append is not called by main()"
    assert "build_odds_rows" in by_line, "build_odds_rows is not called by main()"
    assert by_line.index("_append_nfl_preseason_book_quotes") < by_line.index("build_odds_rows"), (
        "quote-log append must precede schedule matching"
    )


def test_a_failing_append_never_breaks_the_odds_refresh(monkeypatch, capsys):
    """Never raises: a quote-log failure must not fail the odds refresh."""

    def _boom(**_kwargs):
        raise RuntimeError("shard unavailable")

    monkeypatch.setattr(
        "syndicate.features.shared.odds_book_quotes.append_book_quotes",
        _boom,
    )
    fetch_nfl_preseason_odds._append_nfl_preseason_book_quotes([_preseason_event()])
    assert "FAILED" in capsys.readouterr().out


def test_empty_response_is_a_no_op(captured):
    fetch_nfl_preseason_odds._append_nfl_preseason_book_quotes([])
    assert captured == []
