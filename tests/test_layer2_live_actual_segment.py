"""A live interval card never takes the full-game score as its actual (lane layer2-live-segment-actuals, 2026-10-25).

Measured that day: not-yet-started NFL q2 / q3 / q4 / h2 totals showed the full-game score (12:49 PM CT 13 of 13), and
`_mark_layer2_decided` then pruned them as settled (1:34 PM: 11 of 14 gone; "total already reached: 39 scored vs line
9.5" on a q3 9.5)."""
from __future__ import annotations

from pipeline.intelligence_state import _attach_layer2_live_actual, _prune_decided_layer2_cards

CHIP = {"away": {"score": 17}, "home": {"score": 22}}


def _card(segment, line=9.5, market="totals"):
    return {"kind": "game", "market": market, "segment": segment, "side": "over", "line": line, "actual": None}


def test_a_not_started_period_stays_blank_and_is_not_pruned():
    cards = [_card("q3"), _card("h2", line=20.5), _card("q4", market="spreads", line=-3.5)]
    for c in cards:
        _attach_layer2_live_actual(c, CHIP)
    assert [c["actual"] for c in cards] == [None, None, None]
    assert _prune_decided_layer2_cards(cards) == 0 and len(cards) == 3


def test_the_full_game_total_still_gets_the_game_score_and_is_decided_when_passed():
    full = _card("full", line=38.5)
    _attach_layer2_live_actual(full, CHIP)
    assert full["actual"] == 39.0 and full.get("decided") is True
    legacy = _card(None, line=44.5)                       # no segment field = full game
    _attach_layer2_live_actual(legacy, CHIP)
    assert legacy["actual"] == 39.0 and not legacy.get("decided")


def test_a_started_period_keeps_the_actual_it_already_carries():
    q2 = dict(_card("q2", line=13.5), actual=10.0)        # stamped from segment_actuals upstream
    _attach_layer2_live_actual(q2, CHIP)
    assert q2["actual"] == 10.0 and not q2.get("decided")
