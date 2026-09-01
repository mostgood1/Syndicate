"""The pre-registered favourite-lean test behaves as specified, including its nulls.

Written alongside the pre-registration on 2026-09-01, before the data exists.
The point of the tests is that the DECISION RULE cannot drift between now and
the 2026-09-17 read.
"""
from __future__ import annotations

from scripts import prereg_wnba_favourite_lean as prereg

SYND = "/data/wnba_source/data/processed/game_cards_2026-09-18.csv"
VENDOR = "/data/wnba_source/source_artifacts/data/processed/game_cards_2026-09-18.csv"


def _rows(n, wins, implied, source=SYND):
    return [{"implied": implied, "y": 1 if i < wins else 0, "source_path": source}
            for i in range(n)]


def test_thresholds_are_frozen():
    """Re-tuning these on the test data would make this another exploratory look."""
    assert prereg.IMPLIED_THRESHOLD == 0.528
    assert prereg.MIN_ROWS == 150


def test_too_few_rows_is_unreadable_not_refuted():
    """A window that produced too few rows says nothing either way."""
    code, detail = prereg.evaluate(_rows(100, 90, 0.55))
    assert code == prereg.UNREADABLE
    assert "NOT a refutation" in detail["reason"]


def test_a_negative_gap_refutes():
    code, _ = prereg.evaluate(_rows(200, 100, 0.60))  # 50% hit vs 60% implied
    assert code == prereg.REFUTED


def test_a_large_positive_gap_confirms():
    code, detail = prereg.evaluate(_rows(300, 210, 0.55))  # 70% vs 55%
    assert code == prereg.CONFIRMED
    assert detail["z"] >= 1.96


def test_a_small_positive_gap_is_inconclusive_not_confirmed():
    """The exploratory effect was +0.92 SE. That must NOT read as confirmation.

    NOTE the implied here is 0.53, ABOVE the 0.528 threshold. A first draft used
    0.52 and every row was correctly excluded, giving UNREADABLE -- the rule
    catching a bad fixture rather than the fixture testing the rule.
    """
    code, detail = prereg.evaluate(_rows(200, 108, 0.53))  # 54% vs 53%
    assert detail["n_selected"] == 200
    assert code == prereg.INCONCLUSIVE
    assert 0 < detail["z"] < 1.96


def test_rows_below_the_threshold_are_excluded():
    """The hypothesis is about the favourite side only."""
    rows = _rows(200, 200, 0.40) + _rows(200, 120, 0.60)
    code, detail = prereg.evaluate(rows)
    assert detail["n_selected"] == 200, "only implied >= 0.528 may be selected"
    assert code in (prereg.CONFIRMED, prereg.INCONCLUSIVE)


def test_vendor_root_rows_are_excluded():
    """The vendor root's lines correlate -0.04 with outcomes; they cannot vote."""
    code, detail = prereg.evaluate(_rows(400, 380, 0.55, source=VENDOR))
    assert detail["rows_clean_root"] == 0
    assert code == prereg.UNREADABLE


def test_impossible_prices_are_rejected_not_coerced():
    rows = [{"price": -89.125, "y": 1, "source_path": SYND} for _ in range(200)]
    code, detail = prereg.evaluate(rows)
    assert detail["rows_priced"] == 0
    assert code == prereg.UNREADABLE
