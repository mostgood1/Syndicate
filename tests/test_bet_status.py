"""Where a placed bet stands against the LIVE game.

Nearly every test here is about monotonicity, because that is the difference
between a tracker and a tracker that lies. `current vs line` alone renders a
settled fact and a coin still in the air identically.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.bet_status import (
    STATUS_LIVE_AHEAD,
    STATUS_LIVE_BEHIND,
    STATUS_LIVE_TIED,
    STATUS_LOST,
    STATUS_NOT_STARTED,
    STATUS_WON,
    bet_status_report_line,
    is_monotone_market,
    resolve_bet_status,
    statuses_for_orders,
)


def _status(**kw):
    base = dict(market="batter_total_bases", side="Over", line=1.5, current_value=0)
    base.update(kw)
    return resolve_bet_status(**base)


# --- monotonicity: the whole point ----------------------------------------


def test_a_crossed_over_on_a_counting_stat_is_WON_immediately():
    """2 total bases in the 3rd inning cannot become 1. The bet is won, and
    nothing later in the game can undo it."""
    out = _status(side="Over", line=1.5, current_value=2)
    assert out["status"] == STATUS_WON
    assert out["decided"] is True


def test_a_crossed_under_on_a_counting_stat_is_LOST_immediately():
    out = _status(side="Under", line=1.5, current_value=2)
    assert out["status"] == STATUS_LOST
    assert out["decided"] is True


def test_an_uncrossed_UNDER_is_alive_but_NEVER_won_before_final():
    """THE TEST THIS MODULE EXISTS FOR. Under 1.5 at 0 total bases in the 1st
    would read as 'winning' under a naive comparison. It is a coin in the air."""
    out = _status(side="Under", line=1.5, current_value=0)
    assert out["status"] == STATUS_LIVE_AHEAD
    assert out["status"] != STATUS_WON
    assert out["decided"] is False


def test_an_uncrossed_over_is_behind_not_merely_pending():
    out = _status(side="Over", line=1.5, current_value=1)
    assert out["status"] == STATUS_LIVE_BEHIND
    assert out["decided"] is False


def test_a_big_lead_on_a_NON_monotone_market_decides_nothing():
    """A margin swings. Five runs up in the 2nd is not a won spread."""
    out = _status(market="spreads", side="Over", line=-1.5, current_value=5)
    assert out["status"] == STATUS_LIVE_AHEAD
    assert out["decided"] is False


def test_monotone_lookup_is_exact_never_prefix():
    """`spreads_alt` shares a prefix with `spreads` and `totals_alt` with
    `totals`, and only one of each pair is monotone. A prefix rule would declare
    spread bets won in the second inning."""
    assert is_monotone_market("totals") is True
    assert is_monotone_market("totals_alt") is True
    assert is_monotone_market("spreads") is False
    assert is_monotone_market("spreads_alt") is False


def test_an_unknown_market_is_treated_as_non_monotone():
    """The conservative direction: an unknown family can only be decided at
    final, so it is under-called rather than declared won early."""
    out = _status(market="some_new_market", side="Over", line=1.5, current_value=99)
    assert out["decided"] is False
    assert out["status"] == STATUS_LIVE_AHEAD


# --- final ----------------------------------------------------------------


def test_final_decides_a_non_monotone_market():
    out = _status(market="spreads", side="Over", line=-1.5, current_value=5, is_final=True)
    assert out["status"] == STATUS_WON
    assert out["decided"] is True


def test_final_settles_an_under_that_stayed_alive():
    out = _status(side="Under", line=1.5, current_value=1, is_final=True)
    assert out["status"] == STATUS_WON
    assert out["decided"] is True


def test_exactly_on_the_line_at_final_is_a_push_not_a_loss():
    """A push returns the stake and is neither outcome."""
    out = _status(market="totals", side="Over", line=7.0, current_value=7.0, is_final=True)
    assert out["status"] == STATUS_LIVE_TIED
    assert out["decided"] is True


# --- margin ---------------------------------------------------------------


def test_margin_is_signed_toward_the_bet_for_both_sides():
    """One column has to read correctly for overs and unders, so positive
    always means in our favour."""
    over = _status(side="Over", line=1.5, current_value=3)
    under = _status(side="Under", line=1.5, current_value=0)
    assert over["margin"] > 0
    assert under["margin"] > 0


# --- absences stay named --------------------------------------------------


def test_an_unseeable_bet_is_named_not_rendered_as_behind():
    """"We cannot see this bet" and "this bet is behind" must never share a
    rendering: one is a data problem, the other is a bet to sweat."""
    out = _status(current_value=None)
    assert out["status"] is None
    assert out["unavailable_reason"] == "no_current_value"


def test_a_market_with_no_line_is_named():
    out = _status(line=None, current_value=2)
    assert out["unavailable_reason"] == "no_line"


def test_an_unrecognised_side_is_named_not_guessed():
    out = _status(side="home", current_value=2)
    assert out["unavailable_reason"] == "unknown_side"


def test_a_game_that_has_not_started_is_its_own_state():
    out = _status(started=False)
    assert out["status"] == STATUS_NOT_STARTED


# --- the batch layer ------------------------------------------------------


def _order(key="k1", **kw):
    order = {
        "idempotency_key": key,
        "position_key": "p1",
        "venue": "paper",
        "sport": "mlb",
        "market": "batter_total_bases",
        "side": "Over",
        "line": 1.5,
        "player_name": "Steven Kwan",
        "fill_stake_dollars": 5.0,
    }
    order.update(kw)
    return order


def test_statuses_counts_and_reasons_are_both_reported():
    orders = [_order("k1"), _order("k2", side="Under"), _order("k3")]
    values = {"k1": 2, "k2": 0, "k3": None}
    report = statuses_for_orders(
        orders, resolver=lambda o: {"current_value": values[o["idempotency_key"]]}
    )
    assert report["counts"][STATUS_WON] == 1
    assert report["counts"][STATUS_LIVE_AHEAD] == 1
    assert report["reasons"]["no_current_value"] == 1
    assert report["decided"] == 1


def test_a_resolver_that_raises_does_not_lose_the_other_orders():
    """A sport whose live feed is down degrades to a named reason on its own
    orders instead of taking down every other sport's."""
    def resolver(order):
        if order["sport"] == "wnba":
            raise RuntimeError("feed down")
        return {"current_value": 2}

    report = statuses_for_orders(
        [_order("k1"), _order("k2", sport="wnba")], resolver=resolver
    )
    assert report["counts"][STATUS_WON] == 1
    assert any("resolver_error" in r for r in report["reasons"])


def test_rows_carry_venue_so_the_two_paper_books_stay_separable():
    report = statuses_for_orders(
        [_order("k1"), _order("k2", venue="paper:kalshi")],
        resolver=lambda o: {"current_value": 2},
    )
    assert {row["venue"] for row in report["rows"]} == {"paper", "paper:kalshi"}


def test_report_line_names_the_counters_worth_acting_on():
    line = bet_status_report_line(
        statuses_for_orders([_order()], resolver=lambda o: {"current_value": 2})
    )
    assert "BET_STATUS" in line
    for token in ("orders=", "resolved=", "decided=", "won=", "lost=", "reasons="):
        assert token in line, token


def test_every_monotone_name_is_the_one_the_board_emits():
    """The drift that switched this whole mechanism off for MLB pitcher props.

    `_MONOTONE_MARKETS` listed `pitcher_strikeouts` and `pitcher_outs`, but
    `market_keys` canonicalises those to `strikeouts` and `outs` (`#224`) and the
    board emits the canonical form. So `is_monotone_market("strikeouts")` was
    False and the early-decision path never ran for the markets it was written
    for -- inert, with passing tests, reporting `live_behind` on bets that were
    already won.

    `is_monotone_market` takes no sport, so it cannot canonicalise on lookup.
    This is what keeps the two vocabularies together instead.
    """
    from syndicate.features.shared.bet_status import _MONOTONE_MARKETS, is_monotone_market
    from syndicate.features.shared.market_keys import canonical_market_key

    missing = []
    for name in _MONOTONE_MARKETS:
        for sport in ("mlb", "nba", "wnba"):
            canonical = canonical_market_key(sport, name)
            if canonical and not is_monotone_market(canonical):
                missing.append((name, sport, canonical))
    assert not missing, f"canonical spellings absent from the monotone set: {missing}"


def test_the_mlb_stat_table_absorbs_both_market_spellings():
    """The fourth instance of the same drift, found in one day.

    This table read `pitcher_strikeouts` while the board emits `strikeouts`
    (`#224`), so every MLB pitcher prop resolved to `unmapped_market` and could
    never be graded -- which would have made the settlement figures quietly
    hitter-only rather than visibly incomplete.
    """
    from syndicate.features.shared.bet_status_mlb import _MARKET_TO_STAT, _stat_for_market
    from syndicate.features.shared.market_keys import canonical_market_key

    for spelling in ("strikeouts", "pitcher_strikeouts", "outs", "pitcher_outs"):
        assert _stat_for_market(spelling) is not None, spelling

    # And the table's own keys are the canonical ones, so it cannot drift back.
    for key in _MARKET_TO_STAT:
        assert canonical_market_key("mlb", key) in (key, None), f"{key} is not canonical"


def test_an_unmapped_market_is_still_refused_rather_than_guessed():
    from syndicate.features.shared.bet_status_mlb import _stat_for_market

    # A wrong stat produces a confident wrong verdict.
    assert _stat_for_market("spreads") is None
    assert _stat_for_market("h2h") is None
