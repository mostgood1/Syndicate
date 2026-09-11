"""A one-sided row whose ONLY value is an unmeasured model's edge is withheld.

`[2026-09-11, user decision: "Withhold, all sports"]`, lane `pricing-plane-v1`.

Measured on the served board that morning: all 116 MLB `batter_home_runs` rows
were one-sided (`book_margin_model`) with `model_skill.sample_games: 0`, 8 of
them in the top 25; NFL carried 93 `Anytime TD` rows and soccer 221 shots /
assists rows of the same shape. A one-sided row's `ev_pct` is the book's own
hold restated, so the model's edge was the only thing seating it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared.layer2_board import (
    _row_rests_on_unmeasured_model,
    _unmeasured_model_only_mode,
    select_shortlist,
)
from syndicate.features.shared.opportunity_signals import expected_value_pct

_NOW = datetime(2026, 9, 11, 16, 0, tzinfo=timezone.utc)

_UNMEASURED = {"model_skill": {"status": "unmeasured", "sample_games": 0}}
_MEASURED = {"model_skill": {"status": "measured", "sample_games": 180}}


@pytest.fixture(autouse=True)
def _default_mode(monkeypatch):
    monkeypatch.delenv("SYNDICATE_LAYER2_UNMEASURED_MODEL_ONLY", raising=False)


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


def test_a_one_sided_row_with_NO_model_view_is_left_to_the_hold_restatement_rule():
    assert _row_rests_on_unmeasured_model(_one_sided(model_edge_pct=None)) is False


# --------------------------------------------------------------------------- the switch

def test_absent_means_withhold():
    assert _unmeasured_model_only_mode() == "withhold"


def test_only_the_exact_word_admit_reverts(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LAYER2_UNMEASURED_MODEL_ONLY", "admit")
    assert _unmeasured_model_only_mode() == "admit"
    monkeypatch.setenv("SYNDICATE_LAYER2_UNMEASURED_MODEL_ONLY", "yes please")
    assert _unmeasured_model_only_mode() == "withhold"


# --------------------------------------------------------------------------- the shortlist

def test_the_shortlist_withholds_them_counts_them_and_names_the_market():
    rows = [
        _one_sided(price=410 + i, market="batter_home_runs") for i in range(3)
    ] + [
        _one_sided(price=150, market="Anytime TD", sport="nfl"),
        _two_sided_total(),
        _one_sided(price=500, market="batter_home_runs", projection=dict(_MEASURED)),
    ]
    result = select_shortlist(rows, now=_NOW)

    assert result["rows_unmeasured_model_only"] == 4
    assert result["unmeasured_model_only_by_market"] == {"mlb:batter_home_runs": 3, "nfl:Anytime TD": 1}
    assert result["unmeasured_model_only_mode"] == "withhold"
    kept = {(r["market"], r["projection"]["model_skill"]["status"]) for r in result["rows"]}
    assert kept == {("totals", "unmeasured"), ("batter_home_runs", "measured")}


def test_the_rules_never_double_count():
    no_view = _one_sided(price=2200, model_edge_pct=None)
    unmeasured = _one_sided(price=410)
    result = select_shortlist([no_view, unmeasured], now=_NOW)
    assert result["rows_uninformative_ev"] == 1
    assert result["rows_unmeasured_model_only"] == 1


def test_the_counter_is_present_and_zero_when_nothing_is_withheld():
    result = select_shortlist([_two_sided_total()], now=_NOW)
    assert result["rows_unmeasured_model_only"] == 0
    assert result["unmeasured_model_only_by_market"] == {}


def test_admit_restores_todays_behaviour(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LAYER2_UNMEASURED_MODEL_ONLY", "admit")
    result = select_shortlist([_one_sided(price=410)], now=_NOW)
    assert result["rows_unmeasured_model_only"] == 0
    assert result["unmeasured_model_only_mode"] == "admit"
    assert [r["market"] for r in result["rows"]] == ["batter_home_runs"]
