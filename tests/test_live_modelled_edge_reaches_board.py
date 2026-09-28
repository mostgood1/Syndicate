"""A live one-sided prop's modelled edge must reach the BOARD, not just the projection.

`[2026-09-28, lane live-props-model-probability]`. `#539`'s branch in
`live_projection_join` priced one-sided live markets against the modelled fair and
wrote `edge_vs_modelled_fair_pct` -- and its tests asserted exactly that field. But
the board reads the edge through `layer2_board._model_edge_for`, whose modelled
fallback refuses any edge that does not name the side it was priced for
(`modelled_fair_side`). The live branch never stamped it, so every one of those
edges reached `model_edge_pct` as None. Measured: refresh-worker logged
`edged_modelled=20..47` for soccer on 2026-09-27 23:16-23:49Z, and the
opportunity-population ledger carried a model edge on 0 of 3,547 live-aware soccer
props over 09-14..09-28 -- so the model scorecard could grade none of them.

These tests drive the REAL producer into the REAL consumer, because the field-only
tests were green the whole time the join was inert.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import layer2_board
from syndicate.features.shared import live_projection_join as join
from syndicate.features.shared.book_margin_model import EDGE_FIELD as MODELLED_EDGE_FIELD


def _row(side: str = "over", fair: float = 0.40) -> dict:
    return {
        "sport": "soccer",
        "kind": "prop",
        "market": "player_shots",
        "player_name": "Asier Villalibre",
        "line": 1.5,
        "sides": [side],
        "game": {"state": "live"},
        "modelled_fair": {
            side: {
                "fair_method": "book_margin_model",
                "fair_probability": fair,
                "basis": "measured_hold",
                "assumed_hold_pct": 6.5,
            }
        },
        "projection": {
            "basis": "poisson_shots",
            "side": "over",
            "market_fair_unavailable_reason": "one_sided_quote",
        },
    }


def _indexed(live_prob_over: float = 0.45) -> dict:
    return {
        "index": {
            ("asier villalibre", "player_shots", 1.5): {
                "live_prob_over": live_prob_over,
                "live_projection": 1.9,
                "model_prob_over": None,
                "actual_so_far": 0,
                "side": "over",
            }
        },
        "players_seen": {"asier villalibre"},
        "lines_by_player_market": {("asier villalibre", "player_shots"): {1.5}},
    }


def _board_edge(row: dict, live_prob_over: float = 0.45):
    grid = [row]
    coverage = join.attach_live_projections(grid, _indexed(live_prob_over))
    side = row["sides"][0]
    return layer2_board._model_edge_for(grid[0], side, None), grid[0]["projection"], coverage


def test_the_board_reads_the_live_modelled_edge():
    """THE DEFECT. 0.45 live vs 0.40 modelled fair -> +5.0 at the board.
    Before the fix the projection carried 5.0 and the board read None."""
    edge, projection, coverage = _board_edge(_row())
    assert coverage["rows_live_edged_modelled"] == 1
    assert projection[MODELLED_EDGE_FIELD] == pytest.approx(5.0)
    assert projection["modelled_fair_side"] == "over"
    assert edge == pytest.approx(5.0)


def test_a_negative_side_row_prices_the_complement():
    """The index carries P(OVER). An `under`-only quote must be priced at
    1 - P(over); stamping `under` on an edge computed from P(over) would put an
    inverted number on a board that sorts by edge."""
    edge, projection, _ = _board_edge(_row(side="under", fair=0.50), live_prob_over=0.45)
    assert projection["modelled_fair_side"] == "under"
    assert edge == pytest.approx(5.0)  # 0.55 - 0.50


def test_a_row_side_with_unknown_polarity_refuses():
    """A side token outside the closed set is not guessed at."""
    edge, projection, coverage = _board_edge(_row(side="villalibre"))
    assert projection.get(MODELLED_EDGE_FIELD) is None
    assert (coverage.get("rows_live_edged_modelled") or 0) == 0
    assert edge is None


def test_the_board_ceiling_still_applies():
    """`_MODEL_EDGE_MAX_POINTS` drops an implausible edge; stamping the side must
    not route around it."""
    edge, projection, _ = _board_edge(_row(), live_prob_over=0.95)
    assert projection[MODELLED_EDGE_FIELD] == pytest.approx(55.0)
    assert edge is None
