"""The MC live probability now travels on the path that is actually alive.

`_carry_live_probability` was written 2026-08-30 (`5bab0685`) to cure exactly
this -- its commit message says "produced 27, published 0" -- and has never run:
`11815f8b` (2026-07-28) removed both call sites of
`_merge_cards_context_into_report` and left the subtree standing, so the carry
sat inside dead code. Measured on live-odds-worker 2026-09-23 with 10 MLB games
live: `LIVE_MC_PRICED` priced 29 rows for 824785 and 52 for 824223,
`TICK_COMPLETE` ran, and NONE of `CARDS_MERGE` / `CARDS_MERGE_SKIPPED` /
`LIVE_PROB_CARRIED` emitted -- three lines covering every exit that function
has.

`_enhance_card_row_with_live_projection` is the surviving merge. It receives the
vendor MC payload on every tick (`_live_projection_enhancement_payload` ->
`flask_frontend._live_lens_payload`, whose prop rows come from
`_current_live_prop_rows`, the `LIVE_MC_PRICED` function that writes
`live_model_prob_over`) and deliberately skipped its props. The probability
arrived and was discarded.
"""

from __future__ import annotations

from syndicate.features.mlb.live_lens import _enhance_card_row_with_live_projection

# The card side: real rows, a live projection, no probability. Normalised shape.
CARD_ROW = {
    "gamePk": 824785,
    "liveProps": [
        {"playerName": "Bo Bichette", "market": "batter_hits", "prop": "batter_hits",
         "selection": "Over", "line": 0.5, "liveProjection": 0.8,
         "liveModelProbOver": None, "liveEdge": None},
        {"playerName": "Gunnar Henderson", "market": "batter_hits", "prop": "batter_hits",
         "selection": "Over", "line": 1.5, "liveProjection": 0.9,
         "liveModelProbOver": None, "liveEdge": None},
    ],
}

# The vendor MC side: snake_case, as `flask_frontend.py:14763` writes it.
MC_ROW = {
    "gamePk": 824785,
    "liveProps": [
        {"player_name": "Bo Bichette", "market": "batter_hits", "prop": "batter_hits",
         "selection": "Over", "threshold": 0.5,
         "live_model_prob_over": 0.58, "live_edge": 6.1},
    ],
}


def test_the_probability_reaches_the_card_rows():
    out = _enhance_card_row_with_live_projection(dict(CARD_ROW), dict(MC_ROW))
    hit = next(p for p in out["liveProps"] if p["playerName"] == "Bo Bichette")
    assert hit["liveModelProbOver"] == 0.58


def test_its_own_edge_travels_with_it():
    out = _enhance_card_row_with_live_projection(dict(CARD_ROW), dict(MC_ROW))
    hit = next(p for p in out["liveProps"] if p["playerName"] == "Bo Bichette")
    assert hit["liveEdge"] == 6.1


def test_a_card_row_with_no_mc_counterpart_keeps_its_absent_probability():
    # "no live probability" must stay distinguishable from "here is one".
    out = _enhance_card_row_with_live_projection(dict(CARD_ROW), dict(MC_ROW))
    miss = next(p for p in out["liveProps"] if p["playerName"] == "Gunnar Henderson")
    assert miss["liveModelProbOver"] is None


def test_the_card_rows_are_not_replaced_by_the_mc_rows():
    # `5bab0685`'s trade-off: keep the ~124 card rows, do NOT swap to the ~27 MC
    # rows. Row COUNT and identity must be the card side's.
    out = _enhance_card_row_with_live_projection(dict(CARD_ROW), dict(MC_ROW))
    assert len(out["liveProps"]) == 2
    assert [p["playerName"] for p in out["liveProps"]] == ["Bo Bichette", "Gunnar Henderson"]


def test_every_alias_carries_the_same_rows():
    # A probability on `liveProps` but not `props` reads as coverage and is a bug.
    out = _enhance_card_row_with_live_projection(dict(CARD_ROW), dict(MC_ROW))
    assert out["props"] == out["liveProps"]
    assert out["trackedProps"] == out["liveProps"]


def test_an_existing_probability_is_never_overwritten():
    card = {"gamePk": 824785, "liveProps": [
        dict(CARD_ROW["liveProps"][0], liveModelProbOver=0.91)]}
    out = _enhance_card_row_with_live_projection(card, dict(MC_ROW))
    assert out["liveProps"][0]["liveModelProbOver"] == 0.91


def test_no_mc_props_leaves_the_card_rows_untouched():
    out = _enhance_card_row_with_live_projection(dict(CARD_ROW), {"gamePk": 824785, "liveProps": []})
    assert all(p["liveModelProbOver"] is None for p in out["liveProps"])
    assert len(out["liveProps"]) == 2


def test_a_card_row_with_no_props_is_still_gap_filled_not_crashed():
    # The pre-existing gap-fill path (card artifact has none, projection does)
    # must keep working and must not be broken by the carry running after it.
    out = _enhance_card_row_with_live_projection({"gamePk": 824785}, dict(MC_ROW))
    assert len(out.get("liveProps") or []) == 1
