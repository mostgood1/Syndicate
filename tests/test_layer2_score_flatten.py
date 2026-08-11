"""`#361` -- Layer 2's `score` breakdown broke the board twice, loudly and silently.

`layer2_board.py:688` carries `"score": dict(score)` on purpose, so the board can
show WHY a row ranks. Two consumers read that key as a scalar:

LOUD -- `intelligence._normalize_opportunity_item` used `if score in {None, ""}`,
a SET-MEMBERSHIP test, which hashes its operand and raises
`TypeError: unhashable type: 'dict'`. Measured in production 2026-08-11:
`/api/intelligence/query` returned HTTP 500 on 2/2 requests with the page's own
payload (`question: "top edges today"`), and `intelligence.html:2196` turns that
into a permanent "Refresh failed".

SILENT, AND MORE EXPENSIVE -- `_number()` returns None for a dict and the sort key
wraps it `or 0.0`, so all 259 rendered cards ranked at 0.0 and the board ordered
on raw EV instead of Layer 2's composite. A card scoring 0.9724 rendered third,
below two at 0.7276 whose `freshness_factor` was half its own.

Fixing only the crash site would have restored the endpoint and left the ranking
inert -- which is why the flatten lives where every card is built.
"""

from __future__ import annotations

from syndicate.features.intelligence import _attach_intelligence_response_aliases
from syndicate.features.intelligence_board import _flatten_layer2_score, _number

BREAKDOWN = {
    "score": 0.9724,
    "freshness_factor": 0.5,
    "book_confidence": 0.8,
    "price_reliability": 0.9,
    "sim_component": 0.3,
}


def test_the_composite_becomes_a_number_the_sort_can_use():
    """The silent half. `_number` is what the board's sort key calls, and it
    returns None for a Mapping -- which the `or 0.0` fallback then flattens into
    a tie across every card."""
    assert _number(BREAKDOWN) is None, "fixture must reproduce the defect: a dict scores as nothing"

    card = {"score": dict(BREAKDOWN)}
    _flatten_layer2_score(card)
    assert _number(card["score"]) == 0.9724, "the composite still is not reaching the sort"


def test_the_breakdown_is_preserved_not_discarded():
    """The dict is deliberate -- the board shows why a row ranks. Flattening must
    not cost that."""
    card = {"score": dict(BREAKDOWN)}
    _flatten_layer2_score(card)
    assert card["score_breakdown"] == BREAKDOWN


def test_a_genuine_zero_composite_survives():
    """0.0 is a real ranking, not a missing one. A truthiness fallback here would
    hand the row straight back to the `or 0.0` path this exists to escape."""
    card = {"score": {"score": 0.0, "freshness_factor": 0.25}}
    _flatten_layer2_score(card)
    assert card["score"] == 0.0
    assert card["score"] is not None


def test_non_mapping_scores_are_untouched():
    for value in (0.42, None, "", "1.5"):
        card = {"score": value}
        _flatten_layer2_score(card)
        assert card["score"] == value
    empty: dict = {}
    _flatten_layer2_score(empty)
    assert empty == {}


def test_an_existing_breakdown_is_not_clobbered():
    card = {"score": dict(BREAKDOWN), "score_breakdown": {"pre": "existing"}}
    _flatten_layer2_score(card)
    assert card["score_breakdown"] == {"pre": "existing"}
    assert card["score"] == 0.9724


def test_the_endpoint_survives_any_unhashable_value_not_just_score():
    """Belt-and-braces at the crash site. The hazard is the COMPARISON, not the
    one field that tripped it: `x in {None, ""}` raises for any dict or list on
    any of these keys. `is None or == ""` cannot."""
    for key in ("score", "edge", "normalized_edge"):
        payload = {"recommendations": [{key: {"nested": 1}, "selection": "Over 1.5"}]}
        _attach_intelligence_response_aliases(payload)  # must not raise

    payload = {"recommendations": [{"edge": ["a", "b"], "selection": "Over 1.5"}]}
    _attach_intelligence_response_aliases(payload)


def test_a_flattened_card_passes_through_the_endpoint():
    card = {"selection": "Over 1.5", "score": dict(BREAKDOWN)}
    _flatten_layer2_score(card)
    out = _attach_intelligence_response_aliases({"recommendations": [card]})
    assert out["recommendations"][0]["score"] == 0.9724


def test_the_card_edge_is_a_fraction_not_a_percent():
    """`#364`. `ev_pct` is in PERCENT units; the card contract's `edge` is a
    FRACTION, because the board renders it as `(edge * 100).toFixed(1)`
    (`intelligence.html:1115`). Assigning one to the other multiplied every edge
    on the live board by 100.

    Measured on production 2026-08-11 BEFORE the fix: 245 cards showed a
    percentage, 123 of them above 100%, spanning -725% to +163.3%, for rows whose
    true edges are ~1.6%. The API card for the top row read `ev_pct: 1.6332` and
    the page rendered "163.3%".

    The unit is confirmed from the other side too: `intelligence.html:944` filters
    with `edgeValue(item) * 100 < state.minEdge`, a percent threshold against a
    fractional operand.
    """
    from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

    row = {
        "event_id": "e1",
        "sport": "mlb",
        "market": "spreads",
        "side": "away",
        "kind": "game",
        "ev_pct": 1.6332,
        "home_team": "Toronto Blue Jays",
        "away_team": "Boston Red Sox",
        "quote": {"price": -178, "bookmaker": "novig"},
        "score": {"score": 1.3882},
    }
    cards = layer2_rows_to_board_cards([row])
    assert cards, "no card produced"
    card = cards[0]

    assert card["ev_pct"] == 1.6332, "ev_pct must stay in percent -- the shortlist floors are expressed against it"
    assert abs(card["edge"] - 0.016332) < 1e-9, f"edge is not a fraction: {card['edge']}"
    # The board's own arithmetic, applied to what we now emit.
    assert abs(card["edge"] * 100 - 1.6332) < 1e-9, "the rendered percentage does not equal ev_pct"


def test_a_missing_ev_pct_does_not_become_zero_edge():
    """None must stay None. Coercing an absent edge to 0.0 would render "0.0%",
    which reads as a measured no-edge rather than an unknown one."""
    from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

    row = {
        "event_id": "e2", "sport": "mlb", "market": "h2h", "side": "home", "kind": "game",
        "ev_pct": None, "home_team": "A", "away_team": "B",
        "quote": {"price": -110}, "score": {"score": 0.5},
    }
    cards = layer2_rows_to_board_cards([row])
    if cards:
        assert cards[0]["edge"] is None
