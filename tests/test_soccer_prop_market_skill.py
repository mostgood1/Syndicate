"""Soccer player props carry their MEASURED skill at the line, not a market-wide withhold.

`[2026-10-05, lane layer2-unmeasured-per-line]`. The 2026-09-11 unmeasured-model withhold
dropped 3,111 soccer prop rows from one fleet build; lane `stop-market-withholding` removed
it. These rows now reach the board, so what they carry about the model's record matters:
anytime scorer and shots on target were graded at the PRICE on 2026-10-02 (flat ROI on the
model's EV>0 side; one-sided, no de-vig) and must say so instead of "never backtested".
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import measured_market_skill as mms
from syndicate.features.shared.layer2_board import _apply_skill_reliability, select_shortlist
from syndicate.features.shared.opportunity_signals import expected_value_pct
from syndicate.features.shared.projection_skill import attach_projection_skill

_NOW = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)

_REGISTERED = ("player_goal_scorer_anytime", "player_shots_on_target")
_UNGRADED = ("player_first_goal_scorer", "player_last_goal_scorer")


def _grid_row(market: str) -> dict:
    return {"market": market, "segment": "full", "projection": {"mean": 0.31}}


@pytest.mark.parametrize("market", _REGISTERED)
def test_the_boards_soccer_prop_spelling_reaches_its_measurement(market):
    grid = [_grid_row(market)]
    coverage = attach_projection_skill(grid, sport="soccer")
    note = grid[0]["projection"]["model_skill"]
    assert note["status"] == "measured"
    assert note["basis"] == mms.NOTE_BASIS
    assert "at the price" in note["verdict"]
    assert coverage["rows_with_measured_skill_from_registry"] == 1


@pytest.mark.parametrize("market", _UNGRADED)
def test_ungraded_scorer_races_keep_the_declared_absence(market):
    grid = [_grid_row(market)]
    attach_projection_skill(grid, sport="soccer")
    assert grid[0]["projection"]["model_skill"]["status"] == "unmeasured"


def test_a_soccer_prop_measurement_never_labels_a_live_row():
    grid = [{"market": "player_shots_on_target", "segment": "full",
             "projection": {"mean": 0.4, "live_aware": True}}]
    attach_projection_skill(grid, sport="soccer")
    assert grid[0]["projection"]["model_skill"]["status"] == "unmeasured"


# ------------------------------------------------------------- the ROI scale

def test_an_roi_ci_reaching_above_zero_establishes_no_loss():
    for market in _REGISTERED:
        entry = mms.MEASURED_MARKET_SKILL[("soccer", market, "full", mms.PHASE_PREGAME)]
        assert entry["roi_ci95"][1] > 0
        assert mms.established_loss_rel(entry) == 0.0


def test_an_roi_ci_wholly_below_zero_DOES_move_the_score():
    """Reachability for the ROI branch: off != on. Shots' real reading (-22.4%
    [-40.6, -1.7]) is an established 1.7% loss, so it discounts."""
    entry = {"roi_ci95": (-0.406, -0.017)}
    assert mms.established_loss_rel(entry) == pytest.approx(0.017)
    note = {"status": "measured", "established_loss_rel": mms.established_loss_rel(entry)}
    assert mms.skill_reliability(note) == pytest.approx(1.0 - mms.SKILL_GAIN * 0.017)


def test_a_brier_entry_still_reads_its_lower_bound_not_the_roi_branch():
    entry = mms.MEASURED_MARKET_SKILL[("soccer", "totals", "full", mms.PHASE_PREGAME)]
    assert "roi_ci95" not in entry
    assert mms.established_loss_rel(entry) == pytest.approx(round(0.0032 / 0.2293, 5))


@pytest.mark.parametrize("market", _REGISTERED)
def test_each_soccer_prop_verdict_class_agrees_with_its_roi_ci(market):
    entry = mms.MEASURED_MARKET_SKILL[("soccer", market, "full", mms.PHASE_PREGAME)]
    lo, hi = entry["roi_ci95"]
    assert lo <= entry["roi_model"] <= hi
    expected = mms.VERDICT_LOSES if hi < 0 else mms.VERDICT_PARITY
    assert entry["verdict_class"] == expected


# ------------------------------------------------------------- end to end on a line

def _soccer_prop_row(market: str, *, price: int = 240, hold: float = 8.0) -> dict:
    implied = 100.0 / (price + 100.0)
    fair = round(implied * (1.0 - hold / 100.0), 4)
    grid = [_grid_row(market)]
    attach_projection_skill(grid, sport="soccer")
    return {
        "sport": "soccer",
        "market": market,
        "side": "over",
        "event_id": f"evt-soccer-{market}-{price}",
        "commence_time": "2026-10-05T19:00:00Z",
        "ev_pct": expected_value_pct(price, fair),
        "model_edge_pct": 6.5,
        "quote": {"price": price, "fair_probability": fair, "fair_method": "book_margin_model",
                  "assumed_hold_pct": hold, "books_quoting": 3},
        "projection": grid[0]["projection"],
        "score": {"score": 2.0, "value_pct": 6.5},
    }


@pytest.mark.parametrize("market", _REGISTERED + _UNGRADED)
def test_a_row_the_old_withhold_dropped_is_admitted_and_counted(market):
    row = _soccer_prop_row(market)
    result = select_shortlist([row], now=_NOW)
    assert [r["market"] for r in result["rows"]] == [market]
    assert "rows_unmeasured_model_only" not in result


@pytest.mark.parametrize("market", _REGISTERED + _UNGRADED)
def test_its_rank_and_its_sizing_factor_are_untouched(market):
    """No ESTABLISHED loss, so neither rank nor (since lane stop-market-withholding has
    portfolio sizing read `skill_reliability` too) stake is discounted. A point estimate
    is not an established loss."""
    row = _soccer_prop_row(market)
    assert _apply_skill_reliability(row["score"], row["projection"]) == row["score"]
    assert mms.skill_reliability(row["projection"]["model_skill"]) == 1.0
