"""Live status and market mark on OPEN bets, joined from the worker's plan.

Nothing here computes a status. `portfolio_commit` already writes
`plan["bet_status"]` and `plan["live_marks"]` into `portfolio_plan_<date>.json`
on the worker, and that artifact already crosses to web -- so this is a join and
a rendering. The tests are therefore about the ways a join can quietly lie:

1. Decorating a SETTLED row, whose live status is stale by definition and would
   compete with the real answer.
2. Mutating the ledger dicts a display concern was only meant to read.
3. Rendering an unresolved status as a blank -- which is exactly how this
   feature hid an UnboundLocalError for months, per portfolio_commit's own note.
4. Reading an unbounded number of dated plans to decorate a book that spans
   every date.
"""

from __future__ import annotations

import pytest

from syndicate.blueprints import intelligence as bp


def _order(**over):
    order = {
        "idempotency_key": "k1",
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": "KX-TEST",
        "status": "filled",
        "selected_date": "2026-08-26",
        "submitted_at": "2026-08-26T23:10:05Z",
        "market": "player_points",
        "side": "Over",
        "line": 17.5,
    }
    order.update(over)
    return order


def _plan(status_rows=(), mark_rows=()):
    return {
        "bet_status": {"rows": list(status_rows)},
        "live_marks": {"marks": list(mark_rows)},
    }


@pytest.fixture
def plans(monkeypatch):
    """Inject dated plans; record which dates were actually read."""
    store: dict = {"by_date": {}, "reads": []}

    import pipeline.portfolio_commit as commit

    def fake_read(date):
        store["reads"].append(date)
        return store["by_date"].get(date)

    monkeypatch.setattr(commit, "read_portfolio_plan", fake_read)
    return store


# ---------------------------------------------------------------------------
# off != on
# ---------------------------------------------------------------------------


def test_an_open_order_gains_its_status_and_mark(plans):
    plans["by_date"]["2026-08-26"] = _plan(
        status_rows=[{"idempotency_key": "k1", "status": "live_ahead",
                      "current_value": 21.0, "line": 17.5, "margin": 3.5}],
        mark_rows=[{"idempotency_key": "k1", "clv_pct": 2.4, "taken_price": -110}],
    )
    out = bp._attach_open_bet_status([_order()])
    assert out[0]["live_status"]["status"] == "live_ahead"
    assert out[0]["live_status"]["current_value"] == 21.0
    assert out[0]["live_mark"]["clv_pct"] == 2.4


def test_an_order_with_no_plan_row_gains_nothing(plans):
    """The other half of off != on. If both pass, the join is inert."""
    plans["by_date"]["2026-08-26"] = _plan()
    out = bp._attach_open_bet_status([_order()])
    assert "live_status" not in out[0]
    assert "live_mark" not in out[0]


def test_a_settled_row_is_never_decorated(plans):
    """A settled bet has an outcome and a P&L. A live status on it is stale by
    definition and would compete with the real answer for the same cell."""
    plans["by_date"]["2026-08-26"] = _plan(
        status_rows=[{"idempotency_key": "k1", "status": "live_ahead", "current_value": 21.0}],
        mark_rows=[{"idempotency_key": "k1", "clv_pct": 2.4}],
    )
    out = bp._attach_open_bet_status([_order(outcome="won", pnl_dollars=4.5)])
    assert "live_status" not in out[0]
    assert "live_mark" not in out[0]


# ---------------------------------------------------------------------------
# It must not write into the money record
# ---------------------------------------------------------------------------


def test_the_ledger_dicts_are_not_mutated(plans):
    """These came out of the execution ledger. A display concern must not be
    able to write into a money record, even by accident."""
    plans["by_date"]["2026-08-26"] = _plan(
        status_rows=[{"idempotency_key": "k1", "status": "live_ahead"}],
    )
    original = _order()
    out = bp._attach_open_bet_status([original])
    assert "live_status" in out[0]
    assert "live_status" not in original


# ---------------------------------------------------------------------------
# Bounded reads
# ---------------------------------------------------------------------------


def test_at_most_two_dated_plans_are_read(plans):
    """The live book spans EVERY date; plans are per date. A three-day-old open
    order is not live, it is stuck, and giving it a status would dress up a
    problem as a scoreboard."""
    orders = [
        _order(idempotency_key=f"k{i}", selected_date=d)
        for i, d in enumerate(["2026-08-26", "2026-08-25", "2026-08-24", "2026-08-20"])
    ]
    bp._attach_open_bet_status(orders)
    assert plans["reads"] == ["2026-08-26", "2026-08-25"]


def test_no_plan_is_read_when_every_order_is_settled(plans):
    """Decoration is for open bets. Reading a plan to decorate nothing is a
    keyvalue read spent for no reason."""
    bp._attach_open_bet_status([_order(outcome="lost")])
    assert plans["reads"] == []


# ---------------------------------------------------------------------------
# Failure must never cost the page
# ---------------------------------------------------------------------------


def test_an_unreadable_plan_leaves_the_book_intact(plans, monkeypatch):
    import pipeline.portfolio_commit as commit

    monkeypatch.setattr(
        commit, "read_portfolio_plan",
        lambda date: (_ for _ in ()).throw(RuntimeError("keyvalue down")),
    )
    out = bp._attach_open_bet_status([_order()])
    assert len(out) == 1
    assert "live_status" not in out[0]


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from syndicate.app import app

    return app.test_client()


def _render(client, monkeypatch, order):
    monkeypatch.setattr(
        bp, "_live_portfolio_payload",
        # `**kwargs` rather than re-listing the route's signature. This stub
        # went stale when `?venue=` was added (2026-08-28): the real
        # `_live_portfolio_payload` grew a `venue` kwarg, the stub did not, and
        # every test routing through `_render` died with
        # `TypeError: got an unexpected keyword argument 'venue'` -- rendering a
        # 500 page, so the assertions failed on absent team names rather than on
        # anything they were written to check.
        #
        # EIGHT tests, one helper. The same defect was fixed in
        # `test_venue_balances.py` on 2026-08-29 and NOT grepped for elsewhere,
        # which is why these survived another day. Naming the exact kwargs here
        # just schedules the next occurrence for whenever a filter is added.
        lambda date, **kwargs: {
            "date": date, "orders": [order], "health": {}, "limits": {},
            "kill_switch": {}, "balances": None,
        },
    )
    return client.get("/portfolio").get_data(as_text=True)


def test_an_ahead_bet_says_so_with_the_number(client, monkeypatch):
    body = _render(client, monkeypatch, _order(
        live_status={"status": "live_ahead", "current_value": 21.0, "line": 17.5},
    ))
    assert "AHEAD" in body
    assert "21.0 vs 17.5" in body


def test_an_unresolved_status_is_NAMED_not_blank(client, monkeypatch):
    """The failure mode this feature already had once: an UnboundLocalError
    every cycle for months, invisible because an unresolved status and a missing
    one both rendered as nothing."""
    body = _render(client, monkeypatch, _order(
        live_status={"status": None, "unavailable_reason": "no_live_feed"},
    ))
    assert "no live feed" in body


def test_the_market_mark_shows_direction_on_an_open_bet(client, monkeypatch):
    body = _render(client, monkeypatch, _order(
        live_mark={"clv_pct": 2.4, "taken_price": -110},
    ))
    assert "+2.4 pts vs taken" in body


def test_a_settled_row_still_shows_its_outcome_and_pnl(client, monkeypatch):
    """The decoration must not have displaced the real answer."""
    body = _render(client, monkeypatch, _order(outcome="won", pnl_dollars=4.26))
    assert "WON" in body
    assert "+4.26" in body


# ---------------------------------------------------------------------------
# The date filter. Opt-in, and it must never lose an open bet silently.
# ---------------------------------------------------------------------------


@pytest.fixture
def book(monkeypatch):
    """A live book spanning three dates, with one open bet on each."""
    state = {"orders": [
        _order(idempotency_key="a", selected_date="2026-08-26"),
        _order(idempotency_key="b", selected_date="2026-08-25"),
        _order(idempotency_key="c", selected_date="2026-08-24", outcome="won", pnl_dollars=1.0),
    ]}
    import syndicate.features.shared.execution_ledger as led

    monkeypatch.setattr(led, "_load", lambda: dict(state))
    monkeypatch.setattr(led, "read_execution_state", lambda: None)
    monkeypatch.setattr(bp, "_attach_open_bet_status", lambda orders: orders)
    return state


def test_today_is_the_default_and_all_dates_is_explicit(book):
    """REVERSED `[user 2026-08-27]`: "the date needs to default to today with
    an all dates option".

    This test previously asserted the OPPOSITE -- that the book is all-dates by
    construction, because a filter defaulting to today would be the page that
    lets yesterday's open bet expire unwatched. That risk is now real rather
    than designed out, and what stands in for the old default is
    `hidden_open_dated`, asserted here and in the three tests below: the view
    may hold an open bet back, but never silently.
    """
    payload = bp._live_portfolio_payload("2026-08-26", on_date="all")
    assert payload["on_date"] is None
    assert payload["all_dates"] is True
    assert len(payload["orders"]) == 3
    assert payload["hidden_open_dated"] == 0


def test_filtering_shows_only_that_slate(book):
    payload = bp._live_portfolio_payload("2026-08-26", on_date="2026-08-26")
    assert [o["idempotency_key"] for o in payload["orders"]] == ["a"]


def test_the_filter_COUNTS_the_open_bets_it_is_hiding(book):
    """The number is what keeps the guarantee. You cannot lose track of a live
    bet without the page telling you it is holding one back."""
    payload = bp._live_portfolio_payload("2026-08-26", on_date="2026-08-26")
    # "b" is open on another date; "c" is settled and does not count.
    assert payload["hidden_open_dated"] == 1


def test_a_settled_bet_on_another_date_is_not_counted_as_hidden_risk(book):
    """A settled row carries no risk, so counting it would inflate the warning
    and teach the reader to ignore it."""
    payload = bp._live_portfolio_payload("2026-08-26", on_date="2026-08-25")
    assert payload["hidden_open_dated"] == 1  # only "a"


def test_the_pivots_keep_the_whole_book_but_the_TILES_follow_the_date(book):
    """SPLIT `[user 2026-08-27]`: "we need tiles to match date selection. some
    tiles are ytd instead of matching date."

    This test previously asserted that BOTH stayed whole-book. Half of that
    still holds and half was the complaint:

      * `periods` -- the performance pivots -- must not move with a display
        control, or a rollup stops being quotable. Unchanged.
      * `settlement` -- what the Settled and Profit/loss TILES render -- now
        follows the picker, because a tile showing an all-time W/L beside a
        one-slate Positions count is the thing that was reported.
    """
    everything = bp._live_portfolio_payload("2026-08-26", on_date="all")
    filtered = bp._live_portfolio_payload("2026-08-26", on_date="2026-08-26")

    assert filtered["periods"] == everything["periods"]

    whole = (everything["settlement"] or {}).get("total") or {}
    slate = (filtered["settlement"] or {}).get("total") or {}
    assert whole["orders"] > slate["orders"], "the tiles must narrow with the date"


def test_the_date_options_are_offered_newest_first(book):
    payload = bp._live_portfolio_payload("2026-08-26")
    assert payload["date_options"] == ["2026-08-26", "2026-08-25", "2026-08-24"]


# ---------------------------------------------------------------------------
# A game-line row must NAME THE TEAM. Reported by the user 2026-08-26.
# ---------------------------------------------------------------------------


def test_a_home_side_row_names_the_home_team(client, monkeypatch):
    """The row read `home` beside `aec-mlb-cle-laa-2026-08-26` and the natural
    reading of that slug is that we bought CLE. We had not: the venue's
    outcomes array is ['Los Angeles Angels', 'Cleveland Guardians'] -- REVERSED
    against its own slug -- so `home` correctly matched the Angels by name.
    The order was right; the row was unreadable."""
    body = _render(client, monkeypatch, _order(
        market="h2h", side="home", player_name=None, line=None,
        home_team="Los Angeles Angels", away_team="Cleveland Guardians",
        venue="polymarket", venue_ticker="aec-mlb-cle-laa-2026-08-26",
    ))
    assert "Los Angeles Angels" in body


def test_an_away_side_row_names_the_away_team(client, monkeypatch):
    body = _render(client, monkeypatch, _order(
        market="h2h", side="away", player_name=None, line=None,
        home_team="Los Angeles Angels", away_team="Cleveland Guardians",
    ))
    assert "Cleveland Guardians" in body


def test_a_player_prop_still_leads_with_the_player(client, monkeypatch):
    """The team rule must not displace the name a prop row already led with."""
    body = _render(client, monkeypatch, _order(
        market="player_points", side="Over", player_name="A. Wilson", line=17.5,
    ))
    assert "A. Wilson" in body


def test_a_side_that_is_neither_home_nor_away_is_unchanged(client, monkeypatch):
    """`over`/`under` carry their own meaning and must not be turned into a
    team by a lookup that does not apply to them."""
    body = _render(client, monkeypatch, _order(
        market="totals", side="under", player_name=None, line=8.5,
    ))
    assert "under" in body
