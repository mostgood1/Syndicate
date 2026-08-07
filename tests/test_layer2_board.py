"""L2-A candidate builder over the Layer 1 grid.

Two tests carry most of the weight:

`test_mean_based_projection_is_not_added_to_ev` — WNBA and soccer-away-from-2.5
emit `edge_vs_line` in units of the stat (rebounds, goals). Adding that to an EV
percentage would be adding rebounds to percent. Only `edge_vs_market_pct`, which
is probability-space, may contribute.

`test_dead_market_is_never_ranked` — eligibility runs before scoring, so a
settled or stale market cannot appear on a shortlist however good its number
looks.
"""

from __future__ import annotations

from syndicate.features.shared.layer2_board import build_layer2_rows


def _row(**overrides):
    row = {
        "sport": "mlb",
        "event_id": "evt1",
        "kind": "game",
        "market": "totals",
        "segment": "full",
        "line": 8.5,
        "player_name": None,
        "home_team": "St. Louis Cardinals",
        "away_team": "Colorado Rockies",
        "commence_time": "2026-08-08T00:15:00Z",
        "sides": ["over", "under"],
        "books_quoting": 11,
        "game": {"state": "pregame", "status_token": "7:15P CT"},
        "best": {
            "over": {"price": -110, "bookmaker": "betopenly", "age_seconds": 52.0, "books_quoting": 9},
            "under": {"price": -105, "bookmaker": "betmgm", "age_seconds": 60.0, "books_quoting": 9},
        },
    }
    row.update(overrides)
    return row


def test_each_side_becomes_its_own_candidate():
    """A bet is one side; the grid row holds both."""
    result = build_layer2_rows([_row()])
    assert result["sides_priced"] == 2
    assert {c["side"] for c in result["opportunities"]} == {"over", "under"}


def test_two_sided_fair_is_devigged_and_drives_ev():
    result = build_layer2_rows([_row()])
    for candidate in result["opportunities"]:
        assert candidate["quote"]["fair_method"] == "two_sided"
        assert candidate["quote"]["fair_probability"] is not None
        assert candidate["ev_pct"] is not None


def test_dead_market_is_never_ranked():
    row = _row(game={"state": "final", "status_token": "F"})
    result = build_layer2_rows([row])
    assert result["opportunities"] == []
    assert result["by_lane"].get("dead") == 2


def test_unpriced_side_is_skipped_not_zero_filled():
    row = _row(best={"over": {"price": -110, "bookmaker": "b", "age_seconds": 10.0}, "under": {}})
    result = build_layer2_rows([row])
    assert result["sides_priced"] == 1


def test_one_sided_row_falls_back_to_the_margin_model_and_says_so():
    row = _row(
        sides=["over"],
        best={"over": {"price": 450, "bookmaker": "dk", "age_seconds": 20.0, "books_quoting": 11}},
        modelled_fair={"over": {"fair_probability": 0.2}},
    )
    result = build_layer2_rows([row])
    assert result["opportunities"]
    assert result["opportunities"][0]["quote"]["fair_method"] == "book_margin_model"


def test_probability_projection_contributes_a_model_edge():
    row = _row(projection={"edge_vs_market_pct": 6.0, "side": "over"})
    result = build_layer2_rows([row])
    over = [c for c in result["opportunities"] if c["side"] == "over"][0]
    under = [c for c in result["opportunities"] if c["side"] == "under"][0]
    assert over["model_edge_pct"] == 6.0
    # The projection is stated from one side; the other side inherits its inverse.
    assert under["model_edge_pct"] == -6.0


def test_mean_based_projection_is_not_added_to_ev():
    """WNBA/soccer means are in stat units, not probability points."""
    row = _row(
        projection={
            "projected": 9.1,
            "edge_vs_line": 0.6,
            "side": "over",
            "model_prob_over": None,
            "edge_vs_market_pct": None,
        }
    )
    result = build_layer2_rows([row])
    for candidate in result["opportunities"]:
        assert candidate["model_edge_pct"] is None


def test_rows_without_a_value_term_are_excluded_not_zeroed():
    """blended_score returns None with no EV and no model view; zeroing such a
    row would rank it above genuinely negative ones."""
    row = _row(
        sides=["over"],
        best={"over": {"price": 120, "bookmaker": "dk", "age_seconds": 15.0}},
    )
    result = build_layer2_rows([row])
    assert result["opportunities"] == []


def test_ranked_best_first():
    strong = _row(event_id="strong", projection={"edge_vs_market_pct": 20.0, "side": "over"})
    weak = _row(event_id="weak", projection={"edge_vs_market_pct": 1.0, "side": "over"})
    result = build_layer2_rows([weak, strong])
    assert result["opportunities"][0]["event_id"] == "strong"


def test_cells_are_not_copied_into_the_shortlist():
    """The grid row carries every book x every side; a shortlist payload must not."""
    row = _row(cells={"betmgm": {"over": {"price": -110}}})
    result = build_layer2_rows([row])
    assert "cells" not in result["opportunities"][0]


def test_identity_survives_onto_the_candidate():
    result = build_layer2_rows([_row()])
    candidate = result["opportunities"][0]
    assert candidate["market"] == "totals"
    assert candidate["line"] == 8.5
    assert candidate["home_team"] == "St. Louis Cardinals"
