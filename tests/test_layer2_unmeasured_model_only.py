"""A one-sided row whose ONLY value is an unmeasured model's edge is COUNTED, never withheld.

`[2026-10-05, user directive]`, lane `stop-market-withholding`: "STOP WITHHOLDING
MARKETS ... All lines are judged individually - models are tested for accuracy
but each bet is at the line level". Before that, `[2026-09-11, user decision:
"Withhold, all sports"]` (lane `pricing-plane-v1`) dropped these rows; the
evidence it rested on is kept below as history.

Measured on the served board that morning: all 116 MLB `batter_home_runs` rows
were one-sided (`book_margin_model`) with `model_skill.sample_games: 0`, 8 of
them in the top 25; NFL carried 93 `Anytime TD` rows and soccer 221 shots /
assists rows of the same shape. A one-sided row's `ev_pct` is the book's own
hold restated, so the model's edge was the only thing seating it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import layer2_board
from syndicate.features.shared.layer2_board import (
    _row_rests_on_unmeasured_model,
    select_shortlist,
)
from syndicate.features.shared.opportunity_signals import expected_value_pct

_NOW = datetime(2026, 9, 11, 16, 0, tzinfo=timezone.utc)

_UNMEASURED = {"model_skill": {"status": "unmeasured", "sample_games": 0}}
_MEASURED = {"model_skill": {"status": "measured", "sample_games": 180}}


def _one_sided(*, price: int = 410, hold: float = 6.6, market: str = "batter_home_runs",
               sport: str = "mlb", **extra: object) -> dict:
    """A one-sided row priced the way `book_margin_model` prices one, with a model view."""
    implied = 100.0 / (price + 100.0) if price > 0 else abs(price) / (abs(price) + 100.0)
    fair = round(implied * (1.0 - hold / 100.0), 4)
    row = {
        "sport": sport,
        "market": market,
        "side": "over",
        "event_id": f"evt-{sport}-{market}-{price}",
        "commence_time": "2026-09-11T23:05:00Z",
        "ev_pct": expected_value_pct(price, fair),
        "model_edge_pct": 13.8,
        "quote": {
            "price": price,
            "fair_probability": fair,
            "fair_method": "book_margin_model",
            "assumed_hold_pct": hold,
            "books_quoting": 2,
        },
        "projection": dict(_UNMEASURED),
        "score": {"score": 2.0, "value_pct": 13.8},
    }
    row.update(extra)
    return row


def _two_sided_total(**extra: object) -> dict:
    row = {
        "sport": "mlb",
        "market": "totals",
        "side": "over",
        "event_id": "evt-mlb-totals",
        "commence_time": "2026-09-11T23:05:00Z",
        "ev_pct": 4.2,
        "model_edge_pct": 3.0,
        "quote": {"price": 113, "fair_probability": 0.49, "fair_method": "consensus", "books_quoting": 27},
        "projection": dict(_UNMEASURED),
        "score": {"score": 4.2, "value_pct": 4.2},
    }
    row.update(extra)
    return row


# --------------------------------------------------------------------------- predicate

def test_a_one_sided_row_on_an_unmeasured_model_rests_on_it():
    assert _row_rests_on_unmeasured_model(_one_sided()) is True


def test_an_ABSENT_skill_note_is_unmeasured_not_permissive():
    row = _one_sided()
    row.pop("projection")
    assert _row_rests_on_unmeasured_model(row) is True


def test_a_MEASURED_model_does_not():
    assert _row_rests_on_unmeasured_model(_one_sided(projection=dict(_MEASURED))) is False


def test_a_two_sided_consensus_row_is_never_touched_even_on_an_unmeasured_model():
    assert _row_rests_on_unmeasured_model(_two_sided_total()) is False


# ---------------------------------------------------- a MEASURED loss `[2026-09-14]`

_MEASURED_LOSS = {"model_skill": {"status": "measured", "sample_games": 196,
                                  "verdict_class": "loses_to_market"}}


def test_a_MEASURED_LOSS_rests_on_the_model_exactly_like_an_unmeasured_one():
    """Lane `accuracy-assessment-0914` stamps measured notes on markets that read
    "never backtested", and most say the model loses. A model known to be worse
    than the book must not seat a one-sided row an unknown model could not."""
    assert _row_rests_on_unmeasured_model(_one_sided(projection=dict(_MEASURED_LOSS))) is True


@pytest.mark.parametrize("verdict_class", ["parity", "beats_market"])
def test_a_measured_parity_or_win_does_not(verdict_class):
    note = {"model_skill": {"status": "measured", "sample_games": 180, "verdict_class": verdict_class}}
    assert _row_rests_on_unmeasured_model(_one_sided(projection=note)) is False


def test_a_measured_loss_on_a_TWO_SIDED_row_is_still_never_touched():
    assert _row_rests_on_unmeasured_model(_two_sided_total(projection=dict(_MEASURED_LOSS))) is False


def test_a_one_sided_row_with_NO_model_view_is_left_to_the_hold_restatement_rule():
    assert _row_rests_on_unmeasured_model(_one_sided(model_edge_pct=None)) is False


# --------------------------------------------------------------------------- the shortlist

def test_the_shortlist_KEEPS_them_and_counts_them_by_market():
    rows = [
        _one_sided(price=410 + i, market="batter_home_runs") for i in range(3)
    ] + [
        _one_sided(price=150, market="Anytime TD", sport="nfl"),
        _one_sided(price=410, market="outs", projection=dict(_MEASURED_LOSS)),
        _two_sided_total(),
        _one_sided(price=500, market="batter_home_runs", projection=dict(_MEASURED)),
    ]
    result = select_shortlist(rows, now=_NOW)

    assert len(result["rows"]) == len(rows)
    assert result["rows_on_unmeasured_model"] == 5
    assert result["on_unmeasured_model_by_market"] == {
        "mlb:batter_home_runs": 3, "mlb:outs": 1, "nfl:Anytime TD": 1,
    }


def test_no_env_value_brings_the_withhold_back(monkeypatch):
    """The rule was REMOVED, not defaulted off: the old switch is inert."""
    for value in ("withhold", "admit", ""):
        monkeypatch.setenv("SYNDICATE_LAYER2_UNMEASURED_MODEL_ONLY", value)
        result = select_shortlist([_one_sided(price=410)], now=_NOW)
        assert [r["market"] for r in result["rows"]] == ["batter_home_runs"]
    assert not hasattr(layer2_board, "_unmeasured_model_only_mode")
    assert "rows_unmeasured_model_only" not in result


def test_a_measured_LOSS_stays_on_the_board_instead_of_vanishing():
    """Accuracy moves RANK: a known-losing model's line stays on the board, scored
    down by `_apply_skill_reliability`, rather than being hidden."""
    result = select_shortlist(
        [_one_sided(price=410, market="outs", projection=dict(_MEASURED_LOSS))], now=_NOW
    )
    assert [r["market"] for r in result["rows"]] == ["outs"]


def test_the_rules_never_double_count():
    no_view = _one_sided(price=2200, model_edge_pct=None)
    unmeasured = _one_sided(price=410)
    result = select_shortlist([no_view, unmeasured], now=_NOW)
    assert result["rows_uninformative_ev"] == 1
    assert result["rows_on_unmeasured_model"] == 1
    assert len(result["rows"]) == 1


def test_the_counter_is_present_and_zero_when_nothing_rests_on_an_unmeasured_model():
    result = select_shortlist([_two_sided_total()], now=_NOW)
    assert result["rows_on_unmeasured_model"] == 0
    assert result["on_unmeasured_model_by_market"] == {}
