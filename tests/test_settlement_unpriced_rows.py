"""A graded win with no price must not book a fabricated payout.

WHAT THIS CATCHES, stated as the defect it was written against. Two settlement
paths carried a price fallback:

    nba/betting_recap.py   `_settlement_decimal_price` returned 2.0  (even money)
    nba/betting_recap.py   `_settle_prop_pick`         used 1.909090909  (-110)
    shared/live_lens_local.py  `_american_to_decimal(price) or 1.909090909`

So a WIN whose price was missing or zero booked the profit of a winner nobody
had quoted, summed it into `profit_total`, and divided it into `roi_pct`. It was
silent by construction -- no counter, no log line, and a fabricated payout looks
exactly like a real one in every field the payload carries.

`syndicate/features/nhl/betting_recap.py` is the shape these now match, and it
is why this is a correction rather than a new policy: it adds `payout` only
`if payout is not None`, and a row with no payout still counts as a win.

The asymmetry is deliberate and is asserted below: GRADING needs a result and
PRICING needs a price, so a win with no price still moves `wins` and
`accuracy_pct`, and moves `unpriced` instead of `profit_total`. A LOSS costs the
stake at any price, so it is still booked in full.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from syndicate.features.nba.betting_recap import (  # noqa: E402
    _empty_bucket,
    _settle_game_pick,
    _settle_prop_pick,
    _settlement_decimal_price,
)
from syndicate.features.shared.live_lens_local import (  # noqa: E402
    _apply_accuracy_result,
    _finalize_accuracy_bucket,
    _init_accuracy_bucket,
)

# A home ML pick the home team won, so it grades as a WIN with no ambiguity.
WINNING_ML = {"market": "ML", "side": "HOME", "home": "HOME", "away": "AWAY", "tier": "High"}
LOSING_ML = {"market": "ML", "side": "AWAY", "home": "HOME", "away": "AWAY", "tier": "High"}
HOME_WON = {"home_pts": "110", "visitor_pts": "100"}


@pytest.mark.parametrize("price", [None, "", 0, "0", "  ", "abc"])
def test_no_price_means_no_payout_not_even_money(price):
    """The defect itself: `(2.0 - 1.0) * 1.0` == +1.00 booked out of nothing."""
    assert _settlement_decimal_price(price) is None

    resolved, is_win, is_push, profit = _settle_game_pick({**WINNING_ML, "price": price}, HOME_WON)
    assert (resolved, is_win, is_push) == (True, True, False), "the row still GRADES"
    assert profit is None, f"a win with price={price!r} booked {profit!r} instead of refusing"


def test_a_priced_win_is_unchanged():
    """The fix must not touch the rows that were always correct."""
    _, _, _, profit = _settle_game_pick({**WINNING_ML, "price": -110}, HOME_WON)
    assert profit == pytest.approx(100.0 / 110.0)
    _, _, _, profit = _settle_game_pick({**WINNING_ML, "price": "+150"}, HOME_WON)
    assert profit == pytest.approx(1.5)


def test_a_loss_is_still_booked_without_a_price():
    """Asymmetric on purpose: a loss costs the stake at any price, so it is
    knowable where a win is not. Returning None here would understate losses --
    the mirror image of the bug, and the easier one to introduce while fixing it."""
    resolved, is_win, is_push, profit = _settle_game_pick({**LOSING_ML, "price": None}, HOME_WON)
    assert (resolved, is_win, is_push, profit) == (True, False, False, -1.0)


def test_prop_settlement_does_not_fabricate_minus_110():
    row = {"player": "A", "team": "XXX"}
    play = {"market": "pts", "side": "OVER", "line": 20.0, "price": None}
    resolved, is_win, is_push, profit, actual = _settle_prop_pick(row, play, {"pts": 30.0})
    assert (resolved, is_win, is_push) == (True, True, False)
    assert actual == 30.0
    assert profit is None, "a prop win with no price booked the -110 payout"

    play_priced = {**play, "price": -110}
    _, _, _, profit, _ = _settle_prop_pick(row, play_priced, {"pts": 30.0})
    assert profit == pytest.approx(100.0 / 110.0)


def test_the_bucket_reports_the_shortfall_rather_than_hiding_it():
    """`unpriced` is the instrument. Without it, an ROI computed over 1 of 2
    rows is indistinguishable from one computed over both -- which is exactly
    why the fabricated payout survived: nothing reported the gap."""
    bucket = _init_accuracy_bucket()
    _apply_accuracy_result(bucket, "win", -110)
    _apply_accuracy_result(bucket, "win", None)
    final = _finalize_accuracy_bucket(bucket)

    assert final["resolved"] == 2
    assert final["wins"] == 2, "both wins count toward accuracy"
    assert final["accuracy_pct"] == pytest.approx(100.0)
    assert final["unpriced"] == 1, "the unpriced win must be COUNTED, not dropped silently"
    assert final["stake_total"] == 1.0, "ROI is a rate over the rows it could be computed for"
    assert final["profit_total"] == pytest.approx(100.0 / 110.0)


def test_live_lens_loss_without_a_price_is_still_a_full_stake():
    bucket = _init_accuracy_bucket()
    _apply_accuracy_result(bucket, "loss", None)
    assert bucket["profit_total"] == -1.0
    assert bucket["unpriced"] == 0


def test_every_bucket_shape_carries_the_counter():
    """Both modules keep their own bucket dict; a counter added to one and not
    the other is a gap that only shows up in whichever payload nobody reads."""
    for bucket in (_empty_bucket(), _init_accuracy_bucket()):
        assert "unpriced" in bucket
