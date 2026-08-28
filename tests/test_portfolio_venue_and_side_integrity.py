"""The 2026-08-28 portfolio pass: venue filter, sport/type pivots, the
straggler sweep, the unknown-submit split, and the venue-vs-scoreboard check
that caught Polymarket buying the wrong team.

Every fixture here is shaped from a REAL row in the live execution ledger read
at 2026-08-28T14:0xZ -- the two `http_503` submits, the three moneylines the
venue graded against the actual result, and the WNBA pair that fell out of the
two-day settlement window. A fixture invented from the docstring would have
agreed with whatever the code did.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.portfolio_periods import period_rollup


# ---------------------------------------------------------------------------
# Fixtures, from the live book
# ---------------------------------------------------------------------------


def _order(**kw):
    row = {
        "mode": "live",
        "venue": "kalshi",
        "sport": "mlb",
        "market": "totals",
        "selected_date": "2026-08-27",
        "status": "filled",
        "fill_stake_dollars": 1.0,
    }
    row.update(kw)
    return row


def _unknown_submit(**kw):
    """The real shape of the two 2026-08-27 Polymarket failures.

    `venue_order_id` absent is the load-bearing field: the 503 came back before
    the venue told us an id, which is why no read available to us can settle
    whether a position exists.
    """
    row = _order(
        venue="polymarket",
        status="failed",
        error=(
            'PolymarketUSAuthError: http_503: https://api.polymarket.us/v1/orders:'
            ' {"code":14,"message":"The server was unable to process your request."}'
        ),
        venue_order_id=None,
        fill_price=None,
        fill_stake_dollars=None,
        requested_stake_dollars=6.22,
        outcome=None,
    )
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# (5) sport and bet-type pivots
# ---------------------------------------------------------------------------


def test_sport_and_type_pivots_cover_exactly_the_orders_the_day_pivot_does():
    """The whole reason these live in `period_rollup` instead of beside
    `settlement_summary.by_sport`: a reader can add the two tables up."""
    rows = [
        _order(sport="mlb", market="h2h"),
        _order(sport="mlb", market="totals"),
        _order(sport="wnba", market="player_threes", selected_date="2026-08-26"),
        _order(sport="nfl", market="totals", selected_date="2026-08-26"),
    ]
    out = period_rollup(rows)
    assert sum(b["orders"] for b in out["by_day"]) == 4
    assert sum(b["orders"] for b in out["by_sport"]) == 4
    assert sum(b["orders"] for b in out["by_market"]) == 4
    assert {b["key"] for b in out["by_sport"]} == {"mlb", "wnba", "nfl"}
    assert {b["key"] for b in out["by_market"]} == {"h2h", "totals", "player_threes"}


def test_sport_and_type_pivots_are_ordered_biggest_first_not_alphabetically():
    """A date pivot opens on today; these have no chronology, so they open on
    the answer to "where is the book"."""
    rows = [_order(sport="wnba")] + [_order(sport="mlb") for _ in range(3)]
    out = period_rollup(rows)
    assert [b["key"] for b in out["by_sport"]] == ["mlb", "wnba"]


def test_an_order_with_no_sport_is_bucketed_not_dropped():
    """`dimension_key` never returns "": a row missing from the sport table but
    present in the day table beside it makes both tables untrustworthy."""
    out = period_rollup([_order(sport=None), _order(sport="mlb")])
    assert sum(b["orders"] for b in out["by_sport"]) == 2
    assert "(unspecified)" in {b["key"] for b in out["by_sport"]}


# ---------------------------------------------------------------------------
# (4) the unknown submits, and the arithmetic they used to break
# ---------------------------------------------------------------------------


def test_orders_equals_open_plus_unknown_plus_settled():
    """`[user 2026-08-28]` "yesterday has 2 positions that were errors showing
    as an actual position." The two 503s are counted in `orders` because they
    consumed the day's budget, and they are neither open nor settled. Before
    `unknown` existed the column did not add up and nothing said why.
    """
    rows = [
        _order(outcome="won", pnl_dollars=1.0),
        _order(outcome="lost", pnl_dollars=-1.0),
        _order(outcome=None),
        _unknown_submit(),
        _unknown_submit(),
    ]
    day = period_rollup(rows)["by_day"][0]
    assert day["orders"] == 5
    assert day["settled"] == 2
    assert day["pending"] == 1
    assert day["unknown"] == 2
    assert day["orders"] == day["settled"] + day["pending"] + day["unknown"]


def test_an_unknown_submit_is_not_counted_as_a_settled_break_even():
    """The failure mode `unknown` exists to prevent: a row with no outcome
    folded into `settled` would make an unresolved book read as break-even."""
    day = period_rollup([_unknown_submit()])["by_day"][0]
    assert day["settled"] == 0
    assert day["won"] == day["lost"] == day["push"] == 0
    assert day["roi_pct"] is None


def test_a_venue_refusal_is_still_not_a_row_at_all():
    """Unchanged, and asserted so the new `unknown` bucket cannot quietly
    capture the 4xx rows that must stay out of the rollup entirely."""
    refused = _unknown_submit(error="KalshiError: http_404 market_not_found")
    out = period_rollup([refused])
    assert out["by_day"] == []
    assert out["counted_orders"] == 0


# ---------------------------------------------------------------------------
# (4) the payload's own split
# ---------------------------------------------------------------------------


def test_is_unknown_submit_separates_the_three_states():
    from syndicate.blueprints.intelligence import _is_unknown_submit

    assert _is_unknown_submit(_unknown_submit()) is True
    # A 4xx is a refusal: the venue answered. Already hidden, not in question.
    assert _is_unknown_submit(_unknown_submit(error="http_404 market_not_found")) is False
    # An id means the venue told us about it, so it is reconcilable, not unknown.
    assert _is_unknown_submit(_unknown_submit(venue_order_id="C4VCZPMHAKDF")) is False
    # Something graded it, so it was a position after all.
    assert _is_unknown_submit(_unknown_submit(outcome="lost")) is False
    # An ordinary fill is a position.
    assert _is_unknown_submit(_order()) is False


# ---------------------------------------------------------------------------
# (1) the venue filter
# ---------------------------------------------------------------------------


def test_resolve_live_venue_treats_absent_and_all_the_same_way():
    from syndicate.blueprints.intelligence import _resolve_live_venue

    assert _resolve_live_venue(None) is None
    assert _resolve_live_venue("") is None
    assert _resolve_live_venue("  ") is None
    assert _resolve_live_venue("all") is None
    assert _resolve_live_venue("Polymarket") == "polymarket"
    # NOT validated against a hardcoded pair: a third venue's first order must
    # be filterable the day it lands.
    assert _resolve_live_venue("novig") == "novig"


# ---------------------------------------------------------------------------
# (3) the straggler sweep
# ---------------------------------------------------------------------------


def _with_ledger(monkeypatch, orders):
    from syndicate.features.shared import execution_ledger as ledger

    monkeypatch.setattr(ledger, "_load", lambda *a, **k: {"orders": orders})


def test_a_slate_older_than_yesterday_is_found_when_it_still_holds_a_filled_ungraded_row(monkeypatch):
    """The measured case: two FILLED WNBA totals on 2026-08-26, still ungraded
    on 2026-08-28 with a working WNBA resolver, because "today and yesterday"
    had walked past them.
    """
    from syndicate.features.shared.paper_settlement import dates_needing_settlement

    _with_ledger(
        monkeypatch,
        [
            _order(selected_date="2026-08-26", sport="wnba", outcome=None),
            _order(selected_date="2026-08-26", sport="wnba", outcome=None),
            _order(selected_date="2026-08-26", sport="mlb", outcome="won"),
        ],
    )
    found = dates_needing_settlement(today="2026-08-28")
    assert [e["date"] for e in found] == ["2026-08-26"]
    assert found[0]["orders"] == 2
    # The SPORTS come back so the caller can skip a boxscore refresh it does not
    # need -- `#241`, periodic worker work is never free.
    assert found[0]["sports"] == ["wnba"]


def test_a_fully_graded_slate_is_not_swept():
    """The steady state has to be free, or this becomes the periodic cost it is
    supposed to avoid."""
    from syndicate.features.shared.paper_settlement import dates_needing_settlement

    import syndicate.features.shared.execution_ledger as ledger

    original = ledger._load
    ledger._load = lambda *a, **k: {
        "orders": [_order(selected_date="2026-08-26", outcome="won")]
    }
    try:
        assert dates_needing_settlement(today="2026-08-28") == []
    finally:
        ledger._load = original


def test_an_unfilled_row_never_makes_a_slate_look_like_it_needs_settling(monkeypatch):
    """`settle_orders` refuses a non-filled row on every pass, so counting one
    here would pin a date as permanently pending and spend the budget on it
    forever."""
    from syndicate.features.shared.paper_settlement import dates_needing_settlement

    _with_ledger(monkeypatch, [_unknown_submit(selected_date="2026-08-26")])
    assert dates_needing_settlement(today="2026-08-28") == []


def test_the_window_is_bounded_on_both_axes(monkeypatch):
    from syndicate.features.shared.paper_settlement import dates_needing_settlement

    _with_ledger(
        monkeypatch,
        [_order(selected_date=f"2026-08-{d:02d}", outcome=None) for d in range(1, 28)],
    )
    found = dates_needing_settlement(today="2026-08-28", max_age_days=5, max_dates=3)
    assert [e["date"] for e in found] == ["2026-08-27", "2026-08-26", "2026-08-25"]


def test_an_unreadable_today_returns_nothing_rather_than_the_whole_book(monkeypatch):
    """A guard must not map "unknown" onto its permissive branch: a bad date
    widening the sweep to every slate ever is the outcome the bound exists to
    prevent."""
    from syndicate.features.shared.paper_settlement import dates_needing_settlement

    _with_ledger(monkeypatch, [_order(selected_date="2026-08-26", outcome=None)])
    assert dates_needing_settlement(today="not-a-date") == []
    assert dates_needing_settlement(today="") == []


# ---------------------------------------------------------------------------
# (2) the venue-vs-scoreboard cross-check
# ---------------------------------------------------------------------------


def _resolver_saying(outcome_value, *, line=None):
    """A feed that reports one number. `resolve_bet_status` does the rest."""

    def _resolve(order):
        return {
            "current_value": outcome_value,
            "line": order.get("line") if line is None else line,
            "is_final": True,
            "started": True,
        }

    return _resolve


def _graded_by_venue(**kw):
    """`aec-mlb-az-sf-2026-08-27`, reduced to a totals row so the check can be
    exercised without a boxscore feed. The property under test is the
    COMPARISON, which is market-agnostic."""
    row = _order(
        venue="polymarket",
        market="totals",
        side="over",
        line=8.5,
        fill_price=0.38,
        fill_stake_dollars=5.87,
        outcome="lost",
        pnl_dollars=-5.871,
        settled_by="venue",
    )
    row.update(kw)
    return row


def test_a_venue_grade_the_scoreboard_contradicts_is_flagged_and_never_rewritten():
    from syndicate.features.shared.paper_settlement import _check_venue_grade

    order = _graded_by_venue()
    # The game went OVER 8.5, so our reading is `won`; the venue booked `lost`.
    assert _check_venue_grade(order, _resolver_saying(11.0)) == "conflict"
    assert order["grade_check"]["agrees"] is False
    assert order["grade_check"]["our_outcome"] == "won"
    assert order["grade_check"]["venue_outcome"] == "lost"
    # THE MONEY IS UNTOUCHED. This records a disagreement; it does not
    # adjudicate one, because which authority is right is a question about the
    # venue's YES leg and a wrong cross-check would rewrite settled money.
    assert order["outcome"] == "lost"
    assert order["pnl_dollars"] == -5.871


def test_a_venue_grade_the_scoreboard_confirms_is_not_flagged():
    from syndicate.features.shared.paper_settlement import _check_venue_grade

    order = _graded_by_venue(outcome="won", pnl_dollars=9.58)
    assert _check_venue_grade(order, _resolver_saying(11.0)) == "agrees"
    assert order["grade_check"]["agrees"] is True


def test_our_own_grades_are_never_cross_checked_against_our_own_resolver():
    """The control that keeps this from being an unfed field. Our grade applies
    the order's own `side`, so checking it against our own resolver compares a
    reading with itself and reports agreement forever -- which looks exactly
    like a working check."""
    from syndicate.features.shared.paper_settlement import _check_venue_grade

    order = _graded_by_venue(settled_by=None)
    assert _check_venue_grade(order, _resolver_saying(11.0)) is None
    assert "grade_check" not in order


def test_an_unreadable_game_is_recorded_as_unverifiable_and_not_as_a_conflict():
    """"The venue said won and the game says lost" and "the venue said won and
    we cannot read the game" are opposite findings. Folding the second into the
    first turns every feed outage into a wall of money alarms."""
    from syndicate.features.shared.paper_settlement import _check_venue_grade

    order = _graded_by_venue()
    verdict = _check_venue_grade(order, lambda o: {"unavailable_reason": "no_feed"})
    assert verdict == "no_feed"
    assert order["grade_check"]["agrees"] is None
    assert order["grade_check"]["reason"] == "no_feed"


def test_the_check_runs_once_per_order():
    """`grade_check` is the memo, exactly as `outcome` gates grading. A re-run
    must cost no feed lookup."""
    from syndicate.features.shared.paper_settlement import _check_venue_grade

    calls = []

    def _counting(order):
        calls.append(order)
        return {"current_value": 11.0, "is_final": True, "started": True}

    order = _graded_by_venue()
    assert _check_venue_grade(order, _counting) == "conflict"
    assert _check_venue_grade(order, _counting) is None
    assert len(calls) == 1


def test_settle_orders_reports_the_cross_check_beside_the_grades(monkeypatch):
    """`conflicts=0` beside `verified=0` means nothing was checked, which is
    why both numbers are returned rather than just the alarming one."""
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared.paper_settlement import settle_orders

    state = {
        "orders": [
            _graded_by_venue(selected_date="2026-08-27"),
            _graded_by_venue(selected_date="2026-08-27", outcome="won", pnl_dollars=9.58),
        ]
    }
    monkeypatch.setattr(ledger, "_load", lambda *a, **k: state)
    monkeypatch.setattr(ledger, "_persist", lambda *a, **k: None)

    out = settle_orders("2026-08-27", resolver=_resolver_saying(11.0))
    assert out["conflicts"] == 1
    assert out["verified"] == 1
    assert out["graded"] == 0


# ---------------------------------------------------------------------------
# (2) the refusal itself -- REACHABILITY BEFORE CORRECTNESS
# ---------------------------------------------------------------------------


def test_a_team_side_is_refused_on_polymarket_and_the_env_flag_is_the_only_way_back(monkeypatch):
    """`off != on`, asserted before any claim about what the refusal buys.

    A guard that is inert reads exactly like a guard that is working, and this
    one's whole job is to STOP an order being built.
    """
    from syndicate.features.shared import polymarket_us_orders as orders

    monkeypatch.delenv(orders._ALLOW_TEAM_SIDE_ENV, raising=False)
    for side in ("home", "away", "Home", " AWAY "):
        with pytest.raises(orders.OrderBuildError) as caught:
            orders._resolve_outcome_side(side, 0)
        assert "team_side_needs_verified_yes_leg" in str(caught.value)

    # ON: the previous behaviour, unchanged, so the escape hatch is real and the
    # positional arithmetic is still pinned by its own tests.
    monkeypatch.setenv(orders._ALLOW_TEAM_SIDE_ENV, "1")
    assert orders._resolve_outcome_side("home", 0) == orders._SIDE_YES
    assert orders._resolve_outcome_side("home", 1) == orders._SIDE_NO


def test_the_refusal_names_the_venue_property_rather_than_the_symptom(monkeypatch):
    """On a money path the reason is the useful half -- the same argument
    `side_needs_outcome_index` already makes one branch down."""
    from syndicate.features.shared import polymarket_us_orders as orders

    monkeypatch.delenv(orders._ALLOW_TEAM_SIDE_ENV, raising=False)
    with pytest.raises(orders.OrderBuildError) as caught:
        orders._resolve_outcome_side("home", 0)
    message = str(caught.value)
    assert "outcomes[0]" in message
    assert orders._ALLOW_TEAM_SIDE_ENV in message


def test_over_and_under_are_untouched_by_the_team_refusal(monkeypatch):
    """The control. Totals resolve by NAME and measured 9 of 9 correct on the
    same venue over the same window, so the refusal must not reach them --
    turning off a working market would be a worse regression than the defect.
    """
    from syndicate.features.shared import polymarket_us_orders as orders

    monkeypatch.delenv(orders._ALLOW_TEAM_SIDE_ENV, raising=False)
    assert orders._resolve_outcome_side("over", 1) == orders._SIDE_YES
    assert orders._resolve_outcome_side("under", 0) == orders._SIDE_NO
    assert orders._resolve_outcome_side("yes", None) == orders._SIDE_YES
    assert orders._resolve_outcome_side("no", None) == orders._SIDE_NO


def test_an_unmappable_side_still_raises_rather_than_picking_a_leg(monkeypatch):
    from syndicate.features.shared import polymarket_us_orders as orders

    monkeypatch.delenv(orders._ALLOW_TEAM_SIDE_ENV, raising=False)
    for side in ("draw", "", "ovre"):
        with pytest.raises(orders.OrderBuildError):
            orders._resolve_outcome_side(side, 0)
