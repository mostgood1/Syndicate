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


def test_the_counter_reaches_the_payload_the_ui_reads(tmp_path, monkeypatch):
    """End to end: an unpriced winner in the CSV must surface as `unpriced` in
    the recap payload, because that is the field the recap table now draws.

    A producer-level unit test proves the arithmetic; this proves the value
    survives the aggregation and lands in the published shape. Without it a
    later refactor could keep `_settle_game_pick` correct and still drop the
    counter on the way out, which is exactly the class of silence this whole
    change is about."""
    from syndicate.features.nba import betting_recap as recap

    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / "recommendations_2026-01-02.csv").write_text(
        """market,side,home,away,date,ev,price,tier
ML,HOME,HOME,AWAY,2026-01-02,5.0,-110,High
ML,HOME2,HOME2,AWAY2,2026-01-02,5.0,,High
""",  # row 2 is the UNPRICED winner: same result, empty price cell
        encoding="utf-8",
    )
    (processed / "recon_games_2026-01-02.csv").write_text(
        """home_team,visitor_team,home_pts,visitor_pts
HOME,AWAY,110,100
HOME2,AWAY2,110,100
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(recap, "_artifact_root", lambda: processed)
    recap.build_betting_recap_payload.cache_clear()
    payload = recap.build_betting_recap_payload("since=2026-01-02&until=2026-01-02")
    recap.build_betting_recap_payload.cache_clear()

    bucket = payload["items"][0]["games"]["buckets"]["Overall"]
    assert bucket["resolved"] == 2 and bucket["wins"] == 2
    assert bucket["unpriced"] == 1, "the unpriced winner vanished between settlement and the payload"
    assert bucket["stake_total"] == 1.0, "ROI must be a rate over the priced row only"
    assert bucket["profit_total"] == pytest.approx(100.0 / 110.0)
    assert bucket["roi_pct"] == pytest.approx(90.9, abs=0.1)

    flags = sorted(bool(pick["unpriced"]) for pick in payload["items"][0]["games"]["picks"])
    assert flags == [False, True], "the per-pick flag the row view reads is missing"


def test_every_bucket_shape_carries_the_counter():
    """Both modules keep their own bucket dict; a counter added to one and not
    the other is a gap that only shows up in whichever payload nobody reads."""
    for bucket in (_empty_bucket(), _init_accuracy_bucket()):
        assert "unpriced" in bucket


# ---------------------------------------------------------------------------
# NHL: the mirror-image defect, in the module that was the correct precedent
# ---------------------------------------------------------------------------
# `nhl/betting_recap.py` never fabricated a payout -- it is why the NBA fix
# exists in the shape it does -- but it added `stake` and `payout`
# INDEPENDENTLY, so a settled row with a stake and no payout enlarged the ROI
# DENOMINATOR while contributing no numerator. That understates ROI, which is
# the opposite error from NBA's fabricated even money and the one that looks
# like conservatism rather than a bug.
#
# MEASURED BEFORE IT WAS CHANGED: 0 mismatched rows in 7,902 settled rows across
# both git-tracked logs, and production's `stake_total / 100` equalled `resolved`
# exactly on 365 game and 1,702 prop rows over 90 days. The published numbers do
# not move. These tests exist because the hole was structural, not because a
# number was wrong -- so they assert the INVARIANT, which no population can.

NL = chr(10)  # written without an escape on purpose: the shell layer that
              # generated this file un-escapes backslashes in a heredoc.
NHL_LOG_HEADER = "date,home,away,market,bet,ev,price,result,stake,payout"


def _nhl_payload(tmp_path, monkeypatch, log_lines):
    from syndicate.features.nhl import betting_recap as nhl_recap

    root = tmp_path / "processed"
    root.mkdir(parents=True, exist_ok=True)
    (root / "reconciliations_log.csv").write_text(
        NL.join([NHL_LOG_HEADER, *log_lines, ""]), encoding="utf-8"
    )
    (root / "props_reconciliations_log.csv").write_text(NHL_LOG_HEADER + NL, encoding="utf-8")
    monkeypatch.setattr(nhl_recap, "_artifact_root", lambda: root)
    nhl_recap.build_betting_recap_payload.cache_clear()
    try:
        payload = nhl_recap.build_betting_recap_payload("since=2026-01-02&until=2026-01-02")
    finally:
        nhl_recap.build_betting_recap_payload.cache_clear()
    return payload["items"][0]["games"]["buckets"]["Overall"]


def test_nhl_a_stake_without_its_payout_does_not_enlarge_the_roi_denominator(tmp_path, monkeypatch):
    """THE DEFECT. Row 2 is settled and staked but has no payout. Under the old
    code its 100 joined `stake_total` while contributing nothing to
    `profit_total`, halving a +10% ROI to +5%."""
    bucket = _nhl_payload(tmp_path, monkeypatch, [
        "2026-01-02,HOME,AWAY,ML,HOME,0.12,-110,win,100,10",
        "2026-01-02,HOME2,AWAY2,ML,HOME2,0.12,-110,win,100,",
    ])
    assert bucket["resolved"] == 2 and bucket["wins"] == 2, "both rows still GRADE"
    assert bucket["unpriced"] == 1
    assert bucket["stake_total"] == 100.0, "the unpaid row must be out of the DENOMINATOR"
    assert bucket["profit_total"] == 10.0
    assert bucket["roi_pct"] == pytest.approx(10.0), "was 5.0 when the terms were added independently"


def test_nhl_a_payout_without_its_stake_does_not_inflate_the_roi_numerator(tmp_path, monkeypatch):
    """The other half of the same asymmetry, and the one that flatters the
    number rather than understating it."""
    bucket = _nhl_payload(tmp_path, monkeypatch, [
        "2026-01-02,HOME,AWAY,ML,HOME,0.12,-110,win,100,10",
        "2026-01-02,HOME2,AWAY2,ML,HOME2,0.12,-110,win,,10",
    ])
    assert bucket["resolved"] == 2
    assert bucket["unpriced"] == 1
    assert bucket["stake_total"] == 100.0
    assert bucket["profit_total"] == 10.0, "was 20.0, a return on a stake nobody recorded"
    assert bucket["roi_pct"] == pytest.approx(10.0)


def test_nhl_complete_rows_are_untouched(tmp_path, monkeypatch):
    """The fix must not move a number for the rows that were always complete --
    which, measured, is every row in both logs and in production."""
    bucket = _nhl_payload(tmp_path, monkeypatch, [
        "2026-01-02,HOME,AWAY,ML,HOME,0.12,-110,win,100,90.91",
        "2026-01-02,HOME2,AWAY2,ML,HOME2,0.12,-110,loss,100,-100",
    ])
    assert bucket["unpriced"] == 0
    assert bucket["stake_total"] == 200.0
    assert bucket["profit_total"] == pytest.approx(-9.09)
    assert bucket["roi_pct"] == pytest.approx(-4.545, abs=0.01)


def test_nhl_market_accuracy_carries_the_same_rule(tmp_path, monkeypatch):
    """`nhl/market_accuracy.py` held a byte-identical copy of the independent
    guards. A fix applied to one of two copies is the harder bug to find later,
    so the rule is asserted on both."""
    from syndicate.features.nhl import market_accuracy as nhl_market

    bucket = nhl_market._init_bucket() if hasattr(nhl_market, "_init_bucket") else None
    assert bucket is not None and "unpriced" in bucket
    nhl_market._apply_row(bucket, {"result": "win", "stake": "100", "payout": "10"})
    nhl_market._apply_row(bucket, {"result": "win", "stake": "100", "payout": ""})
    nhl_market._apply_row(bucket, {"result": "win", "stake": "", "payout": "10"})
    assert bucket["resolved"] == 3
    assert bucket["unpriced"] == 2
    assert bucket["stake_total"] == 100.0
    assert bucket["profit_total"] == 10.0
