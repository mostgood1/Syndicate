"""The real-money book, and the wall between it and paper.

MERGED 2026-08-26: this book renders on `/portfolio`, the primary page, and
`/portfolio/live` is now a redirect there. The page assertions below therefore
GET `/portfolio`; `/api/portfolio/live` is unchanged and still the payload
under test. The wall this file exists to guard is unmoved -- it was never
between live and the user's own logged bets, both of which are real. It is
between live and PAPER, and paper is still its own page.

Two things are worth testing here and they are both about CONFUSION, not
arithmetic:

1. A live order must never render on `/portfolio/paper`. That page's banner
   says "Simulated fills only. No money moves, no book is contacted, nothing
   here is a real wager." A real position under that sentence is the single
   most dangerous thing either surface could show, and until 2026-08-23 the
   paper payload had no mode filter at all -- the first live order would have
   appeared there.
2. An unreadable ledger must never render as "no live positions". "We cannot
   see the money" and "there is no money at risk" are opposite facts that an
   empty table renders identically.
"""

from __future__ import annotations

import pytest

from syndicate.app import app as flask_app
from syndicate.blueprints import intelligence as intelligence_bp


DATE = "2026-08-23"


@pytest.fixture
def app_client():
    return flask_app.test_client()


def _order(**overrides):
    order = {
        "idempotency_key": "k-live-1",
        "position_key": "pos-1",
        "selected_date": DATE,
        "mode": "live",
        "sport": "wnba",
        "market": "player_points",
        "player_name": "Test Guard",
        "side": "Over",
        "line": 17.5,
        "home_team": "LAS",
        "away_team": "SEA",
        "book": "kalshi",
        "venue": "kalshi",
        "venue_ticker": "KXWNBAPTS-25AUG23-TG-17.5",
        "requested_price": -110.0,
        "requested_stake_dollars": 5.0,
        "submitted_at": "2026-08-23T23:10:05Z",
        "status": "filled",
        "fill_price": -115.0,
        "fill_stake_dollars": 5.0,
        "error": None,
    }
    order.update(overrides)
    return order


@pytest.fixture
def live_env(monkeypatch):
    """Inject the ledger rather than reading disk.

    `data/` in this checkout is a lossy mirror, so a test that read it would
    pass or fail on mirror vintage instead of on this code.
    """
    state = {
        "orders": [],
        "raise_on_load": None,
        "mode": "live",
        "armed": True,
        "execution": True,
        "kill_switch": {"engaged": False, "source": "env"},
    }

    import pipeline.execute_portfolio as exec_mod
    import pipeline.portfolio_commit as commit_mod
    import syndicate.features.shared.execution_guard as guard_mod
    import syndicate.features.shared.execution_ledger as ledger_mod

    def fake_load():
        if state["raise_on_load"] is not None:
            raise state["raise_on_load"]
        return {"orders": list(state["orders"])}

    monkeypatch.setattr(ledger_mod, "_load", fake_load)
    monkeypatch.setattr(ledger_mod, "execution_mode", lambda: state["mode"])
    monkeypatch.setattr(ledger_mod, "live_execution_armed", lambda: state["armed"])
    monkeypatch.setattr(exec_mod, "execution_enabled", lambda: state["execution"])
    monkeypatch.setattr(guard_mod, "kill_switch_engaged", lambda: state["kill_switch"])
    # NO WORKER STAMP BY DEFAULT. The page prefers `execution_state.json` when
    # the worker has written one, and a real one can be sitting on disk from an
    # earlier run -- these tests drive the web-env fallback and must not pass or
    # fail on whether that file happens to exist. The tests that DO exercise the
    # stamp override this themselves.
    monkeypatch.setattr(ledger_mod, "read_execution_state", lambda: None)
    # TODAY IS PINNED, and this is load-bearing rather than tidy. The view
    # defaults to TODAY'S slate as of 2026-08-27, so an unpinned clock would
    # make every assertion below pass or fail on the date the suite happens to
    # run -- and on any day but 2026-08-23 the "default shows today's order"
    # tests would go green against an EMPTY page, which is the exact shape of
    # a fixture that cannot violate the property it claims to guard.
    monkeypatch.setattr(intelligence_bp, "central_today_iso", lambda: DATE)
    # The paper page reads these too; a live-only test must not depend on
    # whatever plan happens to be on disk.
    monkeypatch.setattr(commit_mod, "read_portfolio_plan", lambda date: None)
    monkeypatch.setattr(commit_mod, "paper2_venues", lambda: ())
    return state


def _payload(_live_env):
    return intelligence_bp._live_portfolio_payload(DATE)


# --------------------------------------------------------------------------
# The wall
# --------------------------------------------------------------------------


def test_a_live_order_is_not_on_the_paper_page(live_env):
    """The defect this page was built around.

    `_paper_portfolio_payload` filtered by DATE and by nothing else, so the
    first real Kalshi fill would have rendered under a banner promising no
    money moves.
    """
    live_env["orders"] = [_order()]
    paper = intelligence_bp._paper_portfolio_payload(DATE)
    # No plan is injected, so a paper order on this date would land in
    # `orphan_orders` -- which is exactly where a live one must NOT.
    assert paper["orphan_orders"] == []
    assert paper["rows"] == []


def test_a_live_order_does_not_reach_the_rendered_paper_page(app_client, live_env):
    live_env["orders"] = [_order()]
    body = app_client.get(f"/portfolio/paper?date={DATE}").get_data(as_text=True)
    assert "Test Guard" not in body


def test_a_live_order_is_excluded_from_the_paper_all_dates_record(live_env):
    """The all-dates rollup is computed from the unfiltered list, so it is the
    one place the mode filter is easy to forget."""
    live_env["orders"] = [
        _order(outcome="won", pnl_dollars=4.35, fill_stake_dollars=5.0),
    ]
    paper = intelligence_bp._paper_portfolio_payload(DATE)
    assert paper["settlement_all_time"]["total"]["settled"] == 0


def test_an_order_with_no_mode_is_treated_as_paper(live_env):
    """Absent mode predates the field. It must default to the SAFE reading --
    paper -- rather than to live."""
    live_env["orders"] = [_order(mode=None)]
    assert _payload(live_env)["orders"] == []
    assert len(intelligence_bp._paper_portfolio_payload(DATE)["orphan_orders"]) == 1


def test_the_live_page_shows_only_live_orders(live_env):
    live_env["orders"] = [_order(), _order(idempotency_key="k-paper", mode="paper")]
    payload = _payload(live_env)
    assert [o["idempotency_key"] for o in payload["orders"]] == ["k-live-1"]


# --------------------------------------------------------------------------
# Absence vs failure
# --------------------------------------------------------------------------


def test_an_unreadable_ledger_is_never_rendered_as_no_positions(app_client, live_env):
    live_env["raise_on_load"] = RuntimeError("keyvalue unreachable")
    payload = _payload(live_env)
    assert "keyvalue unreachable" in payload["ledger_error"]

    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "not claiming there are no positions" in body
    assert "No live positions have ever been placed" not in body


def test_no_positions_says_so_plainly(app_client, live_env):
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "No live positions have ever been placed" in body


def test_nothing_settled_is_not_a_zero_pnl(app_client, live_env):
    live_env["orders"] = [_order(outcome=None, pnl_dollars=None)]
    body = app_client.get("/portfolio").get_data(as_text=True)
    # "+0.00" on nothing decided and "+0.00" on fifty decided are the same
    # string, and only one of them means the book is flat.
    assert "nothing settled yet" in body


# --------------------------------------------------------------------------
# Positions carry all dates, not the selected one
# --------------------------------------------------------------------------


def test_yesterdays_open_position_is_held_back_but_counted(live_env):
    """THE OLD GUARANTEE, AND WHAT REPLACED IT.

    Until 2026-08-27 this book was all-dates by construction, because "a real
    position is not interesting only on the day it was opened, and a page that
    hides yesterday's open bet behind a date picker will one day let one expire
    unwatched". `[user 2026-08-27]` asked for today-by-default, so that bet IS
    hidden now and the risk is real rather than designed out.

    `hidden_open_dated` is the whole of what stands in for the old default, so
    this asserts BOTH halves. Dropping the second assertion would leave a test
    that passes while the page silently swallows a live position.
    """
    live_env["orders"] = [_order(selected_date="2026-08-22")]
    payload = _payload(live_env)
    assert payload["orders"] == []
    assert payload["hidden_open_dated"] == 1


# --------------------------------------------------------------------------
# THE SLATE FILTER AT THE TOP OF THE PAGE. [user 2026-08-27] "Add a date filter
# to the top of the portfolio page similar to the one on the paper page", then
# "the date needs to default to today with an all dates option - that should
# mean this selector goes away".
#
# The control defaults to TODAY and `?on=all` is the whole book. That reverses
# the never-default rule these tests were originally written to protect, so
# what they guard now is the replacement: the page may hide an open position,
# but it may never hide one SILENTLY.
# --------------------------------------------------------------------------


def test_the_date_control_is_on_the_page(app_client, live_env):
    """REACHABILITY BEFORE CORRECTNESS, per this repo's own standard."""
    live_env["orders"] = [_order()]
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert 'class="live-datefilter__input"' in body
    assert 'aria-label="Filter to one slate date"' in body


def test_the_control_writes_on_not_date(app_client, live_env):
    """The two parameters are not interchangeable and only one of them filters.

    `?date=` defaults to today and merely builds links; `?on=` is the opt-in
    filter. An input bound to `?date=` would look like a filter and do nothing,
    which is worse than having no control at all.
    """
    live_env["orders"] = [_order()]
    body = app_client.get("/portfolio").get_data(as_text=True)
    control = body[body.index('class="live-datefilter__input"'):][:400]
    assert 'name="on"' in control


def test_the_control_opens_on_today(app_client, live_env):
    """[user 2026-08-27] "the date needs to default to today"."""
    live_env["orders"] = [
        _order(selected_date=DATE, player_name="Today Guard"),
        _order(idempotency_key="k-live-2", position_key="pos-2",
               selected_date="2026-08-21", player_name="Older Guard"),
    ]
    body = app_client.get("/portfolio").get_data(as_text=True)
    control = body[body.index('class="live-datefilter__input"'):][:400]
    assert f'value="{DATE}"' in control
    assert "Today Guard" in body
    assert "Older Guard" not in body


def test_the_default_view_says_what_it_is_holding_back(app_client, live_env):
    """The count has to REACH THE PAGE in the default state, not just the
    payload. It was previously gated on the reader having picked a date, which
    is now precisely the case it must not be gated on."""
    live_env["orders"] = [_order(selected_date="2026-08-22")]
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "1 open position(s) on other dates are not shown here" in body
    assert "on=all" in body


def test_all_dates_is_one_click_and_restores_the_whole_book(app_client, live_env):
    """[user 2026-08-27] "with an all dates option". It has to actually bring
    the other slates back, not merely relabel the header."""
    live_env["orders"] = [
        _order(selected_date=DATE, player_name="Today Guard"),
        _order(idempotency_key="k-live-2", position_key="pos-2",
               selected_date="2026-08-21", player_name="Older Guard"),
    ]
    body = app_client.get("/portfolio?on=all").get_data(as_text=True)
    control = body[body.index('class="live-datefilter__input"'):][:400]
    assert 'value=""' in control
    assert "Today Guard" in body and "Older Guard" in body
    assert "across all dates" in body


def test_the_positions_tile_does_not_call_a_filtered_count_all_dates(app_client, live_env):
    """[user 2026-08-27] "the first box says this is the number of picks all
    time but its really for the selected date."

    THE TILE WAS RIGHT UNTIL THE DEFAULT CHANGED. Its value has always been the
    view's count and its label was hardcoded `all dates` -- true while the view
    was every date, a false statement the moment today became the default. The
    whole-book figure is carried beside it so the two tie off.
    """
    live_env["orders"] = [
        _order(selected_date=DATE),
        _order(idempotency_key="k-2", position_key="p-2", selected_date="2026-08-21"),
        _order(idempotency_key="k-3", position_key="p-3", selected_date="2026-08-20"),
    ]
    body = app_client.get("/portfolio").get_data(as_text=True)
    tile = body[body.index(">Positions<"):][:400]
    assert ">1<" in tile                      # the view: today only
    assert "on this slate" in tile
    assert "3 all dates" in tile              # the whole book, stated
    assert "all dates" not in tile.split("on this slate")[0]


def test_the_positions_tile_counts_positions_not_orders(app_client, live_env):
    """The whole-book figure must not be `book_count`, which counts every live
    ORDER including the ones that never opened a position -- that would put
    "1 of 3" beside a table showing 2."""
    live_env["orders"] = [
        _order(selected_date=DATE),
        _order(idempotency_key="k-2", position_key="p-2", selected_date="2026-08-21"),
        # Refused at the venue: an order, never a position.
        _order(idempotency_key="k-3", position_key="p-3", selected_date="2026-08-20",
               status="failed", error="http_404: market_not_found",
               fill_price=None, fill_stake_dollars=None),
    ]
    payload = intelligence_bp._live_portfolio_payload(DATE)
    assert payload["book_count"] == 3               # every live order
    assert payload["position_count_all_dates"] == 2  # only the ones that opened


def test_the_tiles_follow_the_date_selection(live_env):
    """[user 2026-08-27] "we need tiles to match date selection. some tiles are
    ytd instead of matching date."

    They did not. Settled and Profit/loss ran over the whole book whatever the
    picker said, so a one-slate view showed that slate's Positions beside an
    all-time W/L. Labelling them "all dates" made that honest but not useful --
    the point of picking a date is to see that date.

    Asserted on the COUNTS, not the label: a label can be right while the
    number behind it never moved.
    """
    live_env["orders"] = [
        _order(idempotency_key="a", position_key="a", outcome="won"),
        _order(idempotency_key="b", position_key="b", outcome="lost"),
        _order(idempotency_key="c", position_key="c",
               selected_date="2026-08-21", outcome="won"),
        _order(idempotency_key="d", position_key="d",
               selected_date="2026-08-21", outcome="won"),
    ]

    today = intelligence_bp._live_portfolio_payload(DATE)
    st = (today["settlement"] or {}).get("total") or {}
    assert (st["won"], st["lost"]) == (1, 1), "today's slate only"

    older = intelligence_bp._live_portfolio_payload(DATE, on_date="2026-08-21")
    st = (older["settlement"] or {}).get("total") or {}
    assert (st["won"], st["lost"]) == (2, 0), "the picked slate only"

    everything = intelligence_bp._live_portfolio_payload(DATE, on_date="all")
    st = (everything["settlement"] or {}).get("total") or {}
    assert (st["won"], st["lost"]) == (3, 1), "all dates when asked for all dates"


def test_the_tiles_name_the_scope_they_are_showing(app_client, live_env):
    """The number moves with the picker, so the words have to as well -- a tile
    reading "all dates" over one slate is the mislabel this started from."""
    live_env["orders"] = [_order()]
    default = app_client.get("/portfolio").get_data(as_text=True)
    assert "· this slate" in default
    everything = app_client.get("/portfolio?on=all").get_data(as_text=True)
    assert "· all dates" in everything


def test_the_show_all_toggle_does_not_move_the_tiles(live_env):
    """SCOPED FROM `whole_book`, NOT FROM the display list. `?show=all` puts
    the never-opened rows back into the table; the tiles must not follow it,
    or a display toggle would appear to change the book's record."""
    live_env["orders"] = [
        _order(idempotency_key="a", position_key="a", outcome="won"),
        _order(idempotency_key="r", position_key="r", status="failed",
               error="http_404: market_not_found",
               fill_price=None, fill_stake_dollars=None),
    ]
    hidden = intelligence_bp._live_portfolio_payload(DATE)
    shown = intelligence_bp._live_portfolio_payload(DATE, show_all=True)
    assert (hidden["settlement"] or {}).get("total") == (shown["settlement"] or {}).get("total")


def test_the_old_slate_chip_row_is_gone(app_client, live_env):
    """[user 2026-08-27] "that should mean this selector goes away".

    Asserted on the CLASS rather than the word "Slate", which still appears in
    the staking copy below and would make this pass for the wrong reason.
    """
    live_env["orders"] = [_order()]
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert 'class="live-dates"' not in body
    assert 'class="live-dates__label"' not in body


def test_the_api_and_the_page_cannot_drift_apart(app_client, live_env):
    """`_resolve_live_slate` exists so one function answers `?on=` for both.
    An API that quietly disagrees with the page it backs is worse than one that
    is plainly wrong, because nothing surfaces the disagreement."""
    live_env["orders"] = [
        _order(selected_date=DATE),
        _order(idempotency_key="k-2", position_key="p-2", selected_date="2026-08-21"),
    ]
    default = app_client.get("/api/portfolio/live").get_json()
    assert default["on_date"] == DATE and default["all_dates"] is False
    assert len(default["orders"]) == 1
    everything = app_client.get("/api/portfolio/live?on=all").get_json()
    assert everything["on_date"] is None and everything["all_dates"] is True
    assert len(everything["orders"]) == 2


def test_picking_a_date_filters_and_says_what_it_is_holding_back(app_client, live_env):
    live_env["orders"] = [
        _order(selected_date=DATE, player_name="Today Guard"),
        _order(idempotency_key="k-live-2", position_key="pos-2",
               selected_date="2026-08-21", player_name="Older Guard"),
    ]
    body = app_client.get(f"/portfolio?on={DATE}").get_data(as_text=True)
    assert "Today Guard" in body
    assert "Older Guard" not in body
    # The count is the guarantee: you cannot lose sight of a live bet without
    # the page telling you it is holding one back.
    assert "1 open position(s) on other dates are not shown here" in body


def test_both_directions_are_one_click(app_client, live_env):
    """All dates reachable from today, and today from all dates. Without the
    second half the whole-book view is sticky and the default stops being one.
    """
    live_env["orders"] = [_order()]
    default = app_client.get("/portfolio").get_data(as_text=True)
    assert 'class="live-datefilter__all"' in default
    assert "on=all" in default
    everything = app_client.get("/portfolio?on=all").get_data(as_text=True)
    assert ">today</a>" in everything


def test_the_control_does_not_drop_the_show_all_toggle(app_client, live_env):
    """A GET form REPLACES the query string rather than merging into it, so the
    other parameters have to be carried as hidden fields. Without them, picking
    a date would silently undo the reader's `?show=all`."""
    live_env["orders"] = [_order()]
    body = app_client.get("/portfolio?show=all").get_data(as_text=True)
    form = body[body.index('class="live-datefilter__form"'):][:600]
    assert '<input type="hidden" name="show" value="all">' in form


def test_the_arrows_step_between_slates_that_exist(live_env):
    """Not plus/minus one calendar day. This book is sparse -- a live order
    exists only on a day somebody traded -- so a calendar arrow would spend
    most of its clicks on empty slates and read as a broken control."""
    live_env["orders"] = [
        _order(selected_date="2026-08-23"),
        _order(idempotency_key="k-2", position_key="p-2", selected_date="2026-08-19"),
        _order(idempotency_key="k-3", position_key="p-3", selected_date="2026-08-12"),
    ]
    payload = intelligence_bp._live_portfolio_payload(DATE, on_date="2026-08-19")
    assert payload["on_prev_date"] == "2026-08-12"   # older
    assert payload["on_next_date"] == "2026-08-23"   # newer


def test_the_ends_of_the_sequence_have_no_arrow(live_env):
    live_env["orders"] = [
        _order(selected_date="2026-08-23"),
        _order(idempotency_key="k-2", position_key="p-2", selected_date="2026-08-19"),
    ]
    newest = intelligence_bp._live_portfolio_payload(DATE, on_date="2026-08-23")
    assert newest["on_next_date"] is None
    oldest = intelligence_bp._live_portfolio_payload(DATE, on_date="2026-08-19")
    assert oldest["on_prev_date"] is None


def test_all_dates_has_no_forward_arrow_and_enters_at_the_newest_slate(live_env):
    """All-dates is not a position in the sequence, so there is nothing to step
    forward to."""
    live_env["orders"] = [
        _order(selected_date="2026-08-23"),
        _order(idempotency_key="k-2", position_key="p-2", selected_date="2026-08-19"),
    ]
    payload = intelligence_bp._live_portfolio_payload(DATE, on_date="all")
    assert payload["on_next_date"] is None
    assert payload["on_prev_date"] == "2026-08-23"


def test_a_default_day_the_book_never_traded_still_reaches_the_newest_slate(live_env):
    """Today is not necessarily IN the sequence -- most mornings it is not.
    The back arrow has to land on the newest slate that has rows rather than
    dying, or the default view is a dead end on every quiet day."""
    live_env["orders"] = [_order(selected_date="2026-08-19")]
    payload = _payload(live_env)          # today == DATE, and nothing traded
    assert payload["orders"] == []
    assert payload["on_prev_date"] == "2026-08-19"


def test_the_back_arrow_does_not_call_the_newest_slate_an_older_one(app_client, live_env):
    """The arrow does two different things and must not claim to do one.

    From all dates it ENTERS the filter at the newest slate; from a slate it
    steps one older. A single "Older slate" tooltip was live briefly and named
    today's date as older than nothing.
    """
    live_env["orders"] = [_order(selected_date="2026-08-23"),
                          _order(idempotency_key="k-2", position_key="p-2",
                                 selected_date="2026-08-19")]
    unfiltered = app_client.get("/portfolio?on=all").get_data(as_text=True)
    assert 'title="Filter to the newest slate (2026-08-23)"' in unfiltered
    filtered = app_client.get("/portfolio?on=2026-08-23").get_data(as_text=True)
    assert 'title="Older slate (2026-08-19)"' in filtered


def test_an_empty_slate_is_not_reported_as_an_empty_book(app_client, live_env):
    """The defect the control makes one click away.

    "No live positions have ever been placed" is a claim about every live order
    ever placed. Rendered over a one-slate view it is the page telling the
    reader the book is empty while it holds orders. Reachable before this change
    by hand-typing `?on=`; a picker at the top of the page makes it routine.
    """
    live_env["orders"] = [_order(selected_date="2026-08-21")]
    body = app_client.get("/portfolio?on=2026-08-14").get_data(as_text=True)
    assert "No live positions have ever been placed" not in body
    assert "No live positions on" in body
    assert "The book is not empty" in body


def test_a_genuinely_empty_book_still_says_so_under_a_filter(app_client, live_env):
    """The opposite error: the softer sentence must not paper over a book that
    really has nothing in it."""
    body = app_client.get("/portfolio?on=2026-08-14").get_data(as_text=True)
    assert "No live positions have ever been placed" in body


def test_the_header_names_the_view_it_is_actually_showing(app_client, live_env):
    """The banner sits under a LIVE - REAL MONEY badge. It claiming "all dates"
    over a one-slate view is the page misreporting how much of the real book
    the reader is looking at."""
    live_env["orders"] = [_order()]
    default = app_client.get("/portfolio").get_data(as_text=True)
    assert f"on the {DATE} slate" in default
    assert "across all dates" not in default
    everything = app_client.get("/portfolio?on=all").get_data(as_text=True)
    assert "across all dates" in everything


# --------------------------------------------------------------------------
# The arming badge is DERIVED, never a label
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "off",
    ["execution", "mode", "armed", "kill"],
)
def test_any_one_switch_off_means_the_badge_is_not_real_money(app_client, live_env, off):
    if off == "execution":
        live_env["execution"] = False
    elif off == "mode":
        live_env["mode"] = "paper"
    elif off == "armed":
        live_env["armed"] = False
    else:
        live_env["kill_switch"] = {"engaged": True, "source": "env"}

    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "LIVE MODE OFF" in body
    assert "LIVE — REAL MONEY" not in body


def test_all_four_on_is_the_only_state_that_says_real_money(app_client, live_env):
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "LIVE — REAL MONEY" in body
    assert "real submissions to a real venue" in body


def test_a_kill_switch_read_failure_reads_as_engaged(live_env, monkeypatch):
    """Fail CLOSED. A switch we cannot read is a switch we must assume is on."""
    import syndicate.features.shared.execution_guard as guard_mod

    def boom():
        raise RuntimeError("store down")

    monkeypatch.setattr(guard_mod, "kill_switch_engaged", boom)
    payload = _payload(live_env)
    assert payload["kill_switch"]["engaged"] is True
    assert payload["kill_switch"]["source"] == "read_failed"


# --------------------------------------------------------------------------
# The rows a person has to look at first
# --------------------------------------------------------------------------


def test_a_submitted_order_is_flagged_as_unreconciled(app_client, live_env):
    """Sent, or possibly sent, with an unknown result. A restart between submit
    and record produces exactly these, and the answer is to check the venue --
    never to re-submit."""
    live_env["orders"] = [_order(status="submitted", fill_price=None, fill_stake_dollars=None)]
    payload = _payload(live_env)
    assert len(payload["unreconciled"]) == 1

    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "unknown result" in body
    assert "do not re-submit" in body


def test_a_filled_order_is_not_flagged_as_unreconciled(live_env):
    live_env["orders"] = [_order(status="filled")]
    assert _payload(live_env)["unreconciled"] == []


def test_the_page_shows_the_venue_ticker_and_the_slippage(app_client, live_env):
    live_env["orders"] = [_order()]
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "KXWNBAPTS-25AUG23-TG-17.5" in body
    # Requested -110, filled -115: the gap is what a person checks first after
    # a real submit, so both numbers have to be on the row.
    assert "-110" in body
    assert "-115" in body


def test_the_caps_in_force_are_on_the_page(app_client, live_env, monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "5")
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "$5" in body


# --------------------------------------------------------------------------
# Reachability -- a page nobody can navigate to is a page nobody watches
# --------------------------------------------------------------------------


def test_the_paper_page_links_to_the_live_book(app_client, live_env):
    body = app_client.get(f"/portfolio/paper?date={DATE}").get_data(as_text=True)
    assert 'href="/portfolio#live"' in body


# --------------------------------------------------------------------------
# THE MERGE. [user decision 2026-08-26] The live book is anchored to
# `/portfolio`; `/portfolio/live` is a redirect and not a second render.
# --------------------------------------------------------------------------


def test_the_old_live_url_redirects_to_the_primary_page(app_client, live_env):
    """Bookmarked, and linked from months of history. A 404 on a real-money
    book is a bad way to learn about a rename."""
    r = app_client.get("/portfolio/live")
    assert r.status_code == 302
    assert r.headers["Location"] == "/portfolio#live"


def test_the_redirect_carries_the_query_string(app_client, live_env):
    """`?show=all`, `?period=` and `?date=` all belong to the merged page.
    Dropping them silently resets the reader's view."""
    r = app_client.get("/portfolio/live?date=2026-08-23&show=all&period=month")
    assert r.status_code == 302
    assert r.headers["Location"] == "/portfolio?date=2026-08-23&show=all&period=month#live"


def test_only_one_template_renders_the_live_book(app_client, live_env):
    """The reason `/portfolio/live` redirects instead of rendering.

    Two copies of a real-money surface drift, and the one nobody edits is the
    one somebody trusts -- the same argument `/portfolio/settings` already
    made about the bankroll form.
    """
    from pathlib import Path

    import syndicate

    templates = Path(syndicate.__file__).resolve().parent / "templates"
    assert not (templates / "portfolio_live.html").exists()


def test_the_editable_inputs_survived_the_merge(app_client, live_env):
    """[user decision 2026-08-26] "all the editable inputs remain editable on
    the page". Every field `portfolio_settings` will accept has to be on the
    merged page, or an edit to it silently becomes impossible."""
    from syndicate.features.shared.portfolio_settings import EDITABLE_FIELDS

    body = app_client.get("/portfolio").get_data(as_text=True)
    for name in EDITABLE_FIELDS:
        assert f'name="{name}"' in body, name
    assert 'action="/portfolio/settings"' in body


def test_the_live_and_logged_books_are_both_on_the_page_and_labelled(app_client, live_env):
    """Two ledgers, one page. They are never summed, so they must never read
    as one table -- each half carries its own heading."""
    live_env["orders"] = [_order()]
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert 'id="live"' in body
    assert 'id="tracked"' in body
    # The live half's own row, and the logged half's own container.
    assert "KXWNBAPTS-25AUG23-TG-17.5" in body
    assert 'id="portfolio-positions"' in body


def test_the_live_links_carry_a_real_date(app_client, live_env):
    """`L.selected_date` was never a key of this payload -- the key is `date`.
    Jinja renders an undefined as nothing and raises nothing, so every link the
    page built came out as `?date=`, which is the URL a user pasted back."""
    live_env["orders"] = [_order(), _order(idempotency_key="k-2", status="rejected", error="refused")]
    body = app_client.get(f"/portfolio?date={DATE}").get_data(as_text=True)
    assert "?date=" in body
    assert f"?date={DATE}" in body


def test_the_api_and_the_page_read_the_same_payload(app_client, live_env):
    live_env["orders"] = [_order()]
    data = app_client.get(f"/api/portfolio/live?date={DATE}").get_json()
    assert data["execution_mode"] == "live"
    assert data["live_armed"] is True
    assert len(data["orders"]) == 1


# --------------------------------------------------------------------------
# The switches must report the WORKER, not this web process
# --------------------------------------------------------------------------


def test_the_page_shows_the_workers_switches_not_the_webs(app_client, live_env, monkeypatch):
    """MEASURED 2026-08-24: `/portfolio/live` read "LIVE MODE OFF", "Mode
    paper", "Armed no" and caps of $25/$100 while live-odds-worker was live,
    armed and capped at $10/$40.

    Every one of those was true of the WEB process, which has none of the
    execution env vars, and worthless to a person looking at a live book. It is
    the same defect the paper page had with "COMMIT JOB off" beside filled
    orders, and it needs the same fix: the worker stamps its state and the page
    reports that.
    """
    import syndicate.features.shared.execution_ledger as ledger_mod

    # Web's own env says nothing is on...
    live_env["execution"] = False
    live_env["mode"] = "paper"
    live_env["armed"] = False
    # ...while the worker reports live, armed, and the real caps.
    monkeypatch.setattr(
        ledger_mod,
        "read_execution_state",
        lambda: {
            "recorded_by": "live-odds-worker",
            "recorded_at": "2026-08-24T02:00:00Z",
            "execution_mode": "live",
            "live_armed": True,
            "execution_enabled": True,
            "kill_switch": {"engaged": False},
            "limits": {"max_order_dollars": 10.0, "max_day_dollars": 40.0, "max_day_orders": 10},
        },
    )

    payload = intelligence_bp._live_portfolio_payload(DATE)
    assert payload["execution_mode"] == "live"
    assert payload["live_armed"] is True
    assert payload["state_source"] == "worker"
    assert payload["limits"]["max_order_dollars"] == 10.0

    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "LIVE — REAL MONEY" in body
    assert "$10" in body
    assert "live-odds-worker" in body


def test_no_worker_stamp_is_reported_as_unknown_not_as_off(app_client, live_env, monkeypatch):
    """"The worker has not reported" and "execution is off" are different facts
    with opposite responses, and an unlabelled fallback renders them the same."""
    import syndicate.features.shared.execution_ledger as ledger_mod

    monkeypatch.setattr(ledger_mod, "read_execution_state", lambda: None)
    payload = intelligence_bp._live_portfolio_payload(DATE)
    assert payload["state_source"] == "web_env"

    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "worker has not reported" in body
    assert "Treat them as unknown, not as off" in body


def test_a_stale_stamp_says_so(app_client, live_env, monkeypatch):
    """A stopped worker's last known state looks identical to its current one."""
    import syndicate.features.shared.execution_ledger as ledger_mod

    monkeypatch.setattr(
        ledger_mod,
        "read_execution_state",
        lambda: {
            "recorded_by": "live-odds-worker",
            "recorded_at": "2020-01-01T00:00:00Z",
            "execution_mode": "live",
            "live_armed": True,
            "execution_enabled": True,
            "kill_switch": {"engaged": False},
            "limits": {"max_order_dollars": 10.0, "max_day_dollars": 40.0, "max_day_orders": 10},
        },
    )
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "may be stale" in body


def test_a_kalshi_dollar_price_renders_as_cents_not_american_odds(app_client, live_env):
    """MEASURED from the live page 2026-08-24: a Kalshi fill price of $0.54
    rendered as "+0".

    `"%+d"|format(0.54|int)` is `+0` — the column destroyed the number it
    existed to show, beside a REQUESTED column carrying American odds from the
    board. Two units in one table with nothing to tell them apart.
    """
    live_env["orders"] = [_order(fill_price=0.54, requested_price=0.46)]
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "54&cent;" in body or "54¢" in body
    assert "+0" not in body


def test_an_american_price_still_renders_as_american(app_client, live_env):
    """The other venues quote American odds and must not become cents."""
    live_env["orders"] = [_order(fill_price=-117.0, requested_price=163.0)]
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "-117" in body
    assert "+163" in body


def _live_order(status, error="", key="k1"):
    return {
        "mode": "live", "selected_date": "2026-08-25", "venue": "kalshi",
        "status": status, "error": error, "position_key": key,
        "submitted_at": "2026-08-25T23:00:00Z", "requested_stake_dollars": 1.0,
    }


def test_orders_that_never_opened_a_position_are_hidden_by_default(monkeypatch):
    """[USER DECISION 2026-08-25] Default to hiding them, with a toggle.

    HIDDEN, NOT DROPPED, and counted either way: a page that silently omitted
    them would make "we placed nothing" and "we tried and were refused" look
    identical, which is the distinction this whole system keeps paying to
    preserve. They are also the rows that say WHY a bet did not happen.
    """
    from syndicate.blueprints import intelligence as mod
    from syndicate.features.shared import execution_ledger as ledger_mod

    orders = [
        _live_order("filled", key="a"),
        _live_order("rejected", "OrderBuildError: no_venue_ticker", key="b"),
        _live_order("failed", "KalshiAuthError: http_404: market_not_found", key="c"),
    ]
    monkeypatch.setattr(ledger_mod, "_load", lambda: {"orders": orders})

    # `on_date="all"` keeps the DATE filter out of a test about the
    # NON-POSITION filter. Without it these rows fall outside the
    # default-today view and the test would go green on an empty page.
    default = mod._live_portfolio_payload("2026-08-25", on_date="all")
    assert [o["position_key"] for o in default["orders"]] == ["a"]
    assert default["hidden_count"] == 2
    assert default["show_all"] is False

    shown = mod._live_portfolio_payload("2026-08-25", show_all=True, on_date="all")
    assert len(shown["orders"]) == 3
    assert shown["hidden_count"] == 2
    assert shown["show_all"] is True


def test_a_failed_order_of_UNKNOWN_outcome_stays_visible(monkeypatch):
    """The row a person must see FIRST -- and since 2026-08-28, NOT in the
    positions table.

    A submit that timed out may well have landed; that gap is why the
    write-ahead record exists, and hiding these would bury the one order that
    needs checking against the venue before anything else is placed. Only a
    failure the venue ANSWERED (a 4xx) is certainly not a position, and that one
    is still hidden.

    WHAT CHANGED, AND WHY IT IS NOT A WEAKENING. `[user 2026-08-28]` "yesterday
    has 2 positions that were errors showing as an actual position." They were
    rendered as rows in a table headed as though everything in it is a position,
    which overstates the book -- while deleting them would understate the
    exposure, since nothing available to us can settle whether they landed
    (`GET /v1/orders` answers 501 and the per-order read needs the id the 503
    lost). So they move to `unknown_submits`, which the page renders ABOVE the
    table in its own block with the dollars at risk named.

    The guarantee this test has always defended is unchanged and is asserted
    twice below: a 5xx row is still surfaced, and a 4xx row is still not.
    """
    from syndicate.blueprints import intelligence as mod
    from syndicate.features.shared import execution_ledger as ledger_mod

    orders = [
        _live_order("failed", "ReadTimeout", key="unknown"),
        _live_order("failed", "http_500: internal", key="broke"),
        _live_order("failed", "http_404: market_not_found", key="refused"),
    ]
    monkeypatch.setattr(ledger_mod, "_load", lambda: {"orders": orders})

    payload = mod._live_portfolio_payload("2026-08-25", on_date="all")

    # STILL SURFACED, in the block that describes what they actually are.
    surfaced = {o["position_key"] for o in payload["unknown_submits"]}
    assert surfaced == {"unknown", "broke"}, surfaced

    # AND NO LONGER COUNTED AS POSITIONS.
    assert {o["position_key"] for o in payload["orders"]} == set()

    # The venue's own refusal is still hidden and still not in either place --
    # "we placed nothing" and "we tried and were refused" stay distinct.
    assert "refused" not in surfaced
    assert payload["hidden_count"] == 1
    assert payload["hidden_count"] == 1


def test_the_page_and_the_cap_agree_on_what_is_not_a_position(monkeypatch):
    """One rule, two readers. The page's filter and the day-budget's spend
    accounting both come from `_is_venue_refusal`, so a row that is hidden is
    exactly a row that did not consume an order slot -- rather than two
    functions that agree today and drift apart later."""
    from syndicate.blueprints.intelligence import _is_non_position
    from syndicate.features.shared.execution_guard import _is_venue_refusal

    refused = _live_order("failed", "http_404: market_not_found")
    assert _is_non_position(refused) is True
    assert _is_venue_refusal(refused) is True

    timed_out = _live_order("failed", "ReadTimeout")
    assert _is_non_position(timed_out) is False
    assert _is_venue_refusal(timed_out) is False


# ---------------------------------------------------------------------------
# THE PIVOTS. [USER DECISION 2026-08-25] daily, monthly, yearly views.
#
# REACHABILITY FIRST, per this repo's own standard: a rollup that computes
# correctly and never reaches the page is indistinguishable from one that was
# never built, at every level except looking at it.
# ---------------------------------------------------------------------------


def test_the_period_pivot_reaches_the_page(app_client, live_env):
    live_env["orders"] = [
        _order(idempotency_key="k1", selected_date="2026-08-25", status="filled",
               fill_stake_dollars=2.0, outcome="won", pnl_dollars=1.5),
        _order(idempotency_key="k2", selected_date="2026-07-04", status="filled",
               fill_stake_dollars=2.0, outcome="lost", pnl_dollars=-2.0),
    ]
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "Performance" in body
    assert "2026-08-25" in body
    # The day view is the default, so July's own DAY row is present too.
    assert "2026-07-04" in body


def test_the_month_and_year_views_are_selectable(app_client, live_env):
    live_env["orders"] = [
        _order(idempotency_key="k1", selected_date="2026-08-25", status="filled",
               fill_stake_dollars=2.0, outcome="won", pnl_dollars=1.5),
        _order(idempotency_key="k2", selected_date="2026-07-04", status="filled",
               fill_stake_dollars=2.0, outcome="lost", pnl_dollars=-2.0),
    ]
    month = app_client.get("/portfolio?period=month").get_data(as_text=True)
    assert "2026-08<" in month or ">2026-08<" in month
    year = app_client.get("/portfolio?period=year").get_data(as_text=True)
    # One row for 2026 -- both orders, collapsed.
    assert ">2026<" in year


def test_the_pivot_does_not_move_when_the_show_toggle_flips(app_client, live_env):
    """The `?show=` toggle changes what is DISPLAYED, never what is counted.
    A rollup that moved with a display toggle would not be quotable."""
    live_env["orders"] = [
        _order(idempotency_key="k1", selected_date="2026-08-25", status="filled",
               fill_stake_dollars=2.0),
        _order(idempotency_key="k2", selected_date="2026-08-25", status="rejected",
               error="zero_kelly_stake"),
    ]
    hidden = intelligence_bp._live_portfolio_payload("2026-08-25")
    shown = intelligence_bp._live_portfolio_payload("2026-08-25", show_all=True)
    assert hidden["periods"] == shown["periods"]
    # And the refused order is not in the count either way.
    assert hidden["periods"]["by_day"][0]["orders"] == 1


# ---------------------------------------------------------------------------
# THE BANNER COLOUR. [USER DECISION 2026-08-25] green when healthy, red when
# anything is an issue.
#
# This INVERTED the previous scheme, where `on` was red because red meant
# "real money is live, pay attention". A working system rendered as a wall of
# red and a broken one looked the same. These tests pin the new direction so
# it cannot quietly drift back.
# ---------------------------------------------------------------------------


def test_a_healthy_live_book_is_green(app_client, live_env, monkeypatch):
    """A WORKER STAMP IS PART OF HEALTHY. The fixture's default leaves
    `read_execution_state` returning None, which is `web env (worker silent)`
    -- correctly not green, however the switches read."""
    from syndicate.features.shared import execution_ledger as ledger_mod

    live_env["orders"] = [_order()]
    monkeypatch.setattr(ledger_mod, "read_execution_state", lambda: {
        "execution_mode": "live", "live_armed": True, "execution_enabled": True,
        "kill_switch": {"engaged": False}, "limits": {},
        "recorded_by": "live-odds-worker",
        "recorded_at": _now_iso(),
    })
    payload = intelligence_bp._live_portfolio_payload(DATE)
    assert payload["health"]["ok"] is True
    body = app_client.get("/portfolio").get_data(as_text=True)
    # ANCHORED ON THE MARKUP. Both class names appear in the stylesheet, so a
    # bare substring test passes whatever the badge actually renders.
    assert 'class="live-badge live-badge--ok"' in body
    assert 'class="live-badge live-badge--bad"' not in body
    assert "LIVE — REAL MONEY" in body
    assert 'class="live-banner is-ok"' in body


def test_each_broken_switch_turns_the_line_red(app_client, live_env, monkeypatch):
    """One field is enough. The verdict is `all()`, not a majority.

    Given a healthy worker stamp first, so each case fails on the field under
    test rather than on a silent worker -- a test that is red for the wrong
    reason proves nothing about the reason it names."""
    from syndicate.features.shared import execution_ledger as ledger_mod

    def stamp(**over):
        base = {
            "execution_mode": "live", "live_armed": True, "execution_enabled": True,
            "kill_switch": {"engaged": False}, "limits": {},
            "recorded_by": "live-odds-worker", "recorded_at": _now_iso(),
        }
        base.update(over)
        monkeypatch.setattr(ledger_mod, "read_execution_state", lambda: base)

    for field, break_it in (
        ("job", lambda: stamp(execution_enabled=False)),
        ("mode", lambda: stamp(execution_mode="paper")),
        ("armed", lambda: stamp(live_armed=False)),
        ("kill_switch", lambda: stamp(kill_switch={"engaged": True, "source": "env"})),
    ):
        stamp()
        assert intelligence_bp._live_portfolio_payload(DATE)["health"]["ok"] is True
        break_it()
        health = intelligence_bp._live_portfolio_payload(DATE)["health"]
        assert health[field] is False, field
        assert health["ok"] is False, field
        body = app_client.get("/portfolio").get_data(as_text=True)
        assert 'class="live-badge live-badge--bad"' in body, field
        assert 'class="live-banner is-bad"' in body, field


def _now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def test_an_engaged_kill_switch_is_red(app_client, live_env):
    """DELIBERATE REVERSAL. Engaged used to be painted as fine ("the SAFE
    state"). It is still safe, and it is also a system that cannot trade --
    which is exactly what this banner reports."""
    live_env["kill_switch"] = {"engaged": True, "source": "env"}
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert "ENGAGED" in body
    assert intelligence_bp._live_portfolio_payload(DATE)["health"]["kill_switch"] is False


def test_a_silent_worker_is_red_even_with_every_switch_on(app_client, live_env):
    """"The worker has not reported" and "execution is off" are different
    facts. Neither is healthy, and web's own env is not a reading of the
    process that places orders."""
    health = intelligence_bp._live_portfolio_payload(DATE)["health"]
    # The fixture leaves `read_execution_state` returning None -> web_env.
    payload = intelligence_bp._live_portfolio_payload(DATE)
    if payload["state_source"] != "worker":
        assert health["source"] is False
        assert health["ok"] is False


def test_a_stale_worker_stamp_is_red(monkeypatch):
    """A stamp from forty minutes ago is not current state. A stopped worker's
    last known settings look identical to its live ones."""
    from syndicate.blueprints.intelligence import _live_health, _STATE_STALE_SECONDS

    healthy = {
        "execution_enabled": True, "execution_mode": "live", "live_armed": True,
        "kill_switch": {"engaged": False}, "state_source": "worker",
        "state_age_seconds": 60,
    }
    assert _live_health(healthy)["ok"] is True
    stale = {**healthy, "state_age_seconds": _STATE_STALE_SECONDS + 1}
    assert _live_health(stale)["source"] is False
    assert _live_health(stale)["ok"] is False
    # The boundary belongs to fresh.
    assert _live_health({**healthy, "state_age_seconds": _STATE_STALE_SECONDS})["source"] is True


def test_the_api_answers_the_same_health_question_as_the_page(app_client, live_env):
    """A caller must not have to re-derive green from six fields."""
    api = app_client.get("/api/portfolio/live").get_json()
    assert "health" in api
    assert set(api["health"]) == {"job", "mode", "armed", "kill_switch", "source", "ok"}


# ---------------------------------------------------------------------------
# `/portfolio/settings` WAS A TRAP. It is the form's POST action, not a page,
# so a browser typing it got 405 with no hint where the form lives. Measured
# 2026-08-26T01:21:20Z on production, from a URL this assistant had just told
# the user to open.
# ---------------------------------------------------------------------------


def test_the_settings_url_a_browser_would_guess_reaches_the_form(app_client):
    r = app_client.get("/portfolio/settings")
    assert r.status_code == 303
    assert r.headers["Location"].endswith("/portfolio#bankroll")


def test_the_form_anchor_exists_on_the_page_it_points_at(app_client):
    """A redirect to a fragment that no element carries scrolls to the top and
    looks like the redirect failed."""
    body = app_client.get("/portfolio").get_data(as_text=True)
    assert 'id="bankroll"' in body
    # And the form it anchors is really there, with the two fields that matter.
    assert 'name="bankroll_units"' in body
    assert 'name="max_positions"' in body


def test_saving_returns_to_the_form_not_the_top_of_the_page(app_client, monkeypatch):
    from syndicate.features.shared import portfolio_settings as ps

    seen = {}
    monkeypatch.setattr(ps, "update_settings", lambda changes: seen.update(changes) or (None, {}))
    r = app_client.post("/portfolio/settings", data={"bankroll_units": "1000", "max_positions": "25"})
    assert r.status_code == 303
    assert r.headers["Location"].endswith("/portfolio#bankroll")
    assert seen == {"bankroll_units": "1000", "max_positions": "25"}


# --------------------------------------------------------------------------
# BALANCE EVIDENCE IN THE BANNER. The block used to tell the reader that only a
# person at the venue's screen could settle one of these. True of the ORDER
# routes, never true of the ACCOUNT -- `/account/balances` settled a real $1.84
# case on 2026-08-29.
# --------------------------------------------------------------------------


def _bal_trail(*pairs):
    return [{"recorded_at": at, "kalshi": {"status": "ok", "dollars": d}} for at, d in pairs]


def _unknown_with_trail(monkeypatch, trail, **over):
    from syndicate.blueprints import intelligence as mod
    from syndicate.features.shared import execution_ledger as ledger_mod

    order = _live_order("failed", "http_503: {\"code\":14}", key="lost")
    order["idempotency_key"] = "idem-lost"
    order["venue_resolved_at"] = "2026-08-25T23:00:02Z"
    order.update(over)
    monkeypatch.setattr(ledger_mod, "_load", lambda: {"orders": [order]})
    monkeypatch.setattr(
        "syndicate.features.shared.venue_balances.read_balance_history", lambda: trail
    )
    return mod._live_portfolio_payload("2026-08-25", on_date="all")


def test_a_flat_balance_reaches_the_payload_as_not_placed(monkeypatch):
    payload = _unknown_with_trail(
        monkeypatch,
        _bal_trail(("2026-08-25T22:59:00Z", 50.0), ("2026-08-25T23:05:00Z", 50.0)),
    )
    be = payload["unknown_submits"][0]["balance_evidence"]
    assert be["verdict"] == "not_placed"


def test_the_banner_renders_the_verdict(app_client, monkeypatch):
    _unknown_with_trail(
        monkeypatch,
        _bal_trail(("2026-08-25T22:59:00Z", 50.0), ("2026-08-25T23:05:00Z", 50.0)),
    )
    body = app_client.get("/portfolio?on=all").get_data(as_text=True)
    assert "Balance unchanged across the submit" in body
    # The warning itself must survive -- evidence annotates it, never replaces it.
    assert "do not re-submit" in body


def test_the_banner_no_longer_claims_nothing_can_confirm_or_deny(app_client, monkeypatch):
    """The sentence `/account/balances` disproved. Its removal is the point of
    this change, so a regression that restores it must fail here."""
    _unknown_with_trail(
        monkeypatch,
        _bal_trail(("2026-08-25T22:59:00Z", 50.0), ("2026-08-25T23:05:00Z", 50.0)),
    )
    body = app_client.get("/portfolio?on=all").get_data(as_text=True)
    assert "confirm or deny that a position exists" not in body


def test_an_unknown_verdict_renders_no_verdict_word(app_client, monkeypatch):
    """THE FALSIFICATION TEST NAMED IN THE LANE. A banner asserting a verdict
    while the payload says `unknown` would prove the join wrong -- and on a busy
    slate `unknown` is the COMMON answer, so this is the usual path."""
    payload = _unknown_with_trail(monkeypatch, [])  # no trail at all
    assert payload["unknown_submits"][0]["balance_evidence"]["verdict"] == "unknown"

    body = app_client.get("/portfolio?on=all").get_data(as_text=True)
    assert "strong evidence it never reached the venue" not in body
    assert "evidence a position WAS taken" not in body
    assert "No balance reading either side of this submit" in body


def test_the_banner_still_renders_when_the_evidence_lookup_explodes(app_client, monkeypatch):
    """Losing the annotation is a degraded answer; losing the WARNING about
    money we cannot account for is a silent one."""
    from syndicate.blueprints import intelligence as mod
    from syndicate.features.shared import execution_ledger as ledger_mod

    order = _live_order("failed", "http_503: boom", key="lost")
    order["idempotency_key"] = "idem-lost"
    monkeypatch.setattr(ledger_mod, "_load", lambda: {"orders": [order]})

    def _boom():
        raise RuntimeError("store down")

    monkeypatch.setattr(
        "syndicate.features.shared.venue_balances.read_balance_history", _boom
    )
    payload = mod._live_portfolio_payload("2026-08-25", on_date="all")
    assert len(payload["unknown_submits"]) == 1
    assert payload["unknown_submits"][0]["balance_evidence"] is None

    body = app_client.get("/portfolio?on=all").get_data(as_text=True)
    assert "do not re-submit" in body
