"""The Layer 2 score's movement handling, 2026-10-02 (lane `layer2-freshness-1h`).

User: "we need consistency, and the movement of the market absolutely needs to
influence the ranking" -> "go ahead with 1-3":

1. The SINGLE-BOOK movement term is off by default. One book's price move since
   publish REVERTS (same-book forward CLV, consensus held: MLB 408 games, book
   drifted longer +0.39 pp [+0.29, +0.52], shortened -0.33 [-0.46, -0.21]), and
   the term rewarded the shortened rows and penalised the drifted-long ones.
2. The MARKET's move still ranks, through EV against the current consensus, and
   is now published as `market_move_component` -- inside EV, never added twice.

Reachability first: the flag is proven to change the score when ON before any
claim is made about it being inert when OFF.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import opportunity_signals as sig

BASE = dict(ev_pct=4.0, model_edge=2.0, books_quoting=4, price=106, fair_prob=0.5)


def _score(**extra):
    return sig.blended_score(**{**BASE, **extra})


def test_reachability_the_single_book_term_moves_the_score_when_switched_on(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SCORE_SINGLE_BOOK_MOVEMENT", "1")
    flat = _score()
    toward = _score(movement_price_delta=15)  # positive = shortened toward the pick
    assert toward["movement_term_enabled"] is True
    assert toward["value_pct"] > flat["value_pct"]
    assert toward["movement_kind"] == "price"


def test_by_default_a_single_book_move_no_longer_changes_the_rank(monkeypatch):
    monkeypatch.delenv("SYNDICATE_SCORE_SINGLE_BOOK_MOVEMENT", raising=False)
    flat = _score()
    shortened = _score(movement_price_delta=15)
    drifted_long = _score(movement_price_delta=-15)
    line_moved = _score(movement_line_prob_delta_pp=-2.0)
    for row in (shortened, drifted_long, line_moved):
        assert row["score"] == flat["score"]
        assert row["value_pct"] == flat["value_pct"]
        assert row["movement_term_enabled"] is False
        assert row["movement_kind"] is None
    # Still reported as a supplied-but-inert 0.0, not absent.
    assert drifted_long["movement_component"] == 0.0


def test_market_move_component_is_the_ev_share_of_the_consensus_move():
    row = _score(market_move_pp=1.0)
    implied = sig.implied_probability(106)
    assert row["market_move_component"] == pytest.approx(1.0 / implied, abs=1e-4)
    against = _score(market_move_pp=-0.5)
    assert against["market_move_component"] == pytest.approx(-0.5 / implied, abs=1e-4)


def test_market_move_is_attribution_only_never_counted_twice():
    without = _score()
    with_move = _score(market_move_pp=3.0)
    assert with_move["score"] == without["score"]
    assert with_move["value_pct"] == without["value_pct"]
    assert without["market_move_component"] is None


def test_the_layer2_caller_can_pass_the_consensus_move():
    from syndicate.features.shared import layer2_board

    assert layer2_board._blended_score_accepts("market_move_pp")
