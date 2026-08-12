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


def test_a_stale_artifact_is_repaired_at_read_time():
    """`#364` part two. Fixing the producer was NOT enough: the cards are baked
    into the shortlist artifact by the worker, so every card written before the
    fix keeps its percent-unit `edge` until the next rebuild.

    Measured 2026-08-11: the producer fix went live at 23:06:59Z and the served
    artifact was still the 22:38:33Z one, so the board kept rendering "163.3%"
    for a 1.63% edge with the corrected code already deployed. A producer-side
    fix does not repair data already on disk.
    """
    from pipeline.intelligence_state import _normalize_card_edge_units

    stale = {"edge": 1.6332, "ev_pct": 1.6332}
    _normalize_card_edge_units(stale)
    assert abs(stale["edge"] - 0.016332) < 1e-9


def test_the_repair_is_idempotent_and_narrow():
    """It has to run alongside the producer fix, so it must not double-convert.
    The discriminator is `edge == ev_pct` -- the signature of the copy-across.
    A card already carrying a fraction satisfies `edge * 100 == ev_pct` and is
    left alone. Anything it does not recognise is passed through untouched,
    because an unfamiliar shape is not a licence to rewrite someone's number."""
    from pipeline.intelligence_state import _normalize_card_edge_units

    already = {"edge": 0.016332, "ev_pct": 1.6332}
    _normalize_card_edge_units(already)
    assert abs(already["edge"] - 0.016332) < 1e-9

    twice = {"edge": 1.6332, "ev_pct": 1.6332}
    _normalize_card_edge_units(twice)
    once = twice["edge"]
    _normalize_card_edge_units(twice)
    assert twice["edge"] == once, "double conversion"

    for untouched in ({"edge": 0.5, "ev_pct": 9.9}, {"edge": None, "ev_pct": 1.6},
                      {"edge": 0.0, "ev_pct": 0.0}, {"edge": True, "ev_pct": 1.0}):
        before = dict(untouched)
        _normalize_card_edge_units(untouched)
        assert untouched == before, f"rewrote a shape it should not touch: {before}"

    negative = {"edge": -7.25, "ev_pct": -7.25}
    _normalize_card_edge_units(negative)
    assert abs(negative["edge"] + 0.0725) < 1e-9


def test_the_board_columns_are_populated_from_the_row(monkeypatch):
    """`#366`. FAIR, EV, PROJECTED, CONFIDENCE and SCORE rendered blank on every
    L2-A card once `#363` made Layer 2 the board. The data was never missing --
    it sat one level down in `quote`, `projection` and `score`, under names the
    card contract does not read. A naming gap, not a modelling one.

    Field names verified against `intelligence.html`, not guessed, because
    populating something nothing reads is the inert fix this repo keeps paying
    for: fairPriceValue:1600, evVsFairValue:1605, displayProjection:580,
    confidenceValue:292, boardScoreValue:1978.
    """
    from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

    row = {
        "event_id": "e1", "sport": "mlb", "market": "spreads", "side": "away", "kind": "game",
        "ev_pct": 1.6332, "home_team": "Toronto Blue Jays", "away_team": "Boston Red Sox",
        "quote": {"price": -178, "bookmaker": "novig", "fair_probability": 0.6507449935928038,
                  "book_age_seconds": 101.1},
        "projection": {"projected": -0.672, "model_prob_over": 0.3144},
        "score": {"score": 1.3882, "book_confidence": 0.85, "freshness_factor": 1.0},
    }
    card = layer2_rows_to_board_cards([row])[0]

    # 0.6507 fair probability -> -186 American. The book price is -178, i.e.
    # BETTER than fair, which is what a +1.63% EV means. The two must agree.
    assert card["fair_price"] == -186.0
    assert card["ev_vs_fair_pct"] == 1.6332
    assert card["projected"] == -0.672 and card["sim_projection"] == -0.672
    assert card["confidence"] == 0.85
    assert card["board_score"] == 1.3882
    assert card["board_score_components"]["freshness_factor"] == 1.0
    assert card["book_age_seconds"] == 101.1


def test_a_row_without_a_projection_leaves_projected_blank():
    """70 of 200 rows carry a projection. The rest must render an empty cell, not
    a fabricated 0.0 -- a made-up projection is worse than an absent one."""
    from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

    row = {
        "event_id": "e2", "sport": "wnba", "market": "h2h", "side": "home", "kind": "game",
        "ev_pct": 0.8, "home_team": "A", "away_team": "B",
        "quote": {"price": -110, "fair_probability": 0.5}, "score": {"score": 0.2},
    }
    card = layer2_rows_to_board_cards([row])[0]
    assert "projected" not in card or card["projected"] is None
    assert card["fair_price"] is not None, "fair should still resolve without a projection"


def test_the_read_time_backfill_never_overwrites_the_producer():
    """The producer is the authority; the backfill only fills gaps in artifacts
    written before `#366`. Overwriting would let a re-derivation silently
    disagree with what the worker computed and persisted."""
    from pipeline.intelligence_state import _backfill_layer2_board_columns

    card = {"fair_price": -999.0, "ev_pct": 1.0, "confidence": 0.11,
            "quote": {"fair_probability": 0.65, "book_age_seconds": 5.0},
            "score": {"book_confidence": 0.9, "score": 7.0}}
    _backfill_layer2_board_columns(card)
    assert card["fair_price"] == -999.0
    assert card["confidence"] == 0.11
    # ...but genuinely absent ones are filled.
    assert card["board_score"] == 7.0
    assert card["book_age_seconds"] == 5.0

    once = dict(card)
    _backfill_layer2_board_columns(card)
    assert card == once, "backfill is not idempotent"


CHIP_LIVE = {"sport": "mlb", "state": "live",
             "away": {"name": "Boston Red Sox", "score": 2},
             "home": {"name": "Toronto Blue Jays", "score": 5}}


def _card(**over):
    base = {"sport": "mlb", "away_team": "Boston Red Sox", "home_team": "Toronto Blue Jays",
            "kind": "game", "market": "totals", "is_live": False, "lane": "pregame",
            "market_state": "pregame"}
    base.update(over)
    return base


def test_a_live_game_restates_a_frozen_pregame_card(monkeypatch):
    """`#367`. `is_live`/`lane`/`market_state` are stamped when the worker writes
    the shortlist and never move. Measured 2026-08-11 23:41Z: all 258 cards said
    `is_live: false, lane: pregame` while five MLB games were past the third
    inning, because the artifact was written at 22:38Z. The State column is gated
    on that field, so it could not show a live game at any hour."""
    import syndicate.features.shared.game_chip_scoreboard as gcs
    from pipeline.intelligence_state import _refresh_layer2_live_state

    monkeypatch.setattr(gcs, "build_game_chips", lambda date, sports: [CHIP_LIVE])
    cards = [_card()]
    assert _refresh_layer2_live_state(cards, ["2026-08-11"]) == 1
    assert cards[0]["is_live"] is True
    assert cards[0]["lane"] == "live" and cards[0]["market_state"] == "live"


def test_the_join_is_on_names_because_ids_do_not_overlap(monkeypatch):
    """Chips carry statsapi ids, L2-A rows carry OddsAPI event ids -- measured
    overlap 0 of 27. The full-name pair matched 18 of 18, so that is the key."""
    import syndicate.features.shared.game_chip_scoreboard as gcs
    from pipeline.intelligence_state import _refresh_layer2_live_state

    monkeypatch.setattr(gcs, "build_game_chips", lambda date, sports: [CHIP_LIVE])
    mismatched = [_card(away_team="Someone Else")]
    assert _refresh_layer2_live_state(mismatched, ["2026-08-11"]) == 0
    assert mismatched[0]["is_live"] is False, "a non-matching game must not be re-stated"


def test_actual_is_derived_only_where_the_mapping_is_unambiguous(monkeypatch):
    """A totals bet settles on the combined score and a spread on the margin, so
    both are derivations. h2h has no numeric actual and a prop settles on a player
    stat the scoreboard does not carry -- giving those a number would mean
    something else entirely."""
    from pipeline.intelligence_state import _attach_layer2_live_actual

    totals = _card(market="totals")
    _attach_layer2_live_actual(totals, CHIP_LIVE)
    assert totals["actual"] == 7.0

    spread = _card(market="spreads")
    _attach_layer2_live_actual(spread, CHIP_LIVE)
    assert spread["actual"] == 3.0

    for market in ("h2h", "h2h_3_way"):
        row = _card(market=market)
        _attach_layer2_live_actual(row, CHIP_LIVE)
        assert row.get("actual") is None, f"{market} was given a meaningless actual"

    prop = _card(kind="prop", market="batter_hits")
    _attach_layer2_live_actual(prop, CHIP_LIVE)
    assert prop.get("actual") is None


def test_a_scoreless_chip_leaves_actual_alone(monkeypatch):
    """A game that has started but has no score yet must render blank, not 0.0."""
    from pipeline.intelligence_state import _attach_layer2_live_actual

    row = _card(market="totals")
    _attach_layer2_live_actual(row, {"sport": "mlb", "state": "live",
                                     "away": {"name": "Boston Red Sox", "score": None},
                                     "home": {"name": "Toronto Blue Jays", "score": None}})
    assert row.get("actual") is None


def test_a_scoreboard_failure_leaves_the_board_stale_not_empty(monkeypatch):
    """This runs on the serving path. A scoreboard blip must cost accuracy of the
    State column, never the board itself."""
    import syndicate.features.shared.game_chip_scoreboard as gcs
    from pipeline.intelligence_state import _refresh_layer2_live_state

    def _boom(date, sports):
        raise RuntimeError("scoreboard unavailable")

    monkeypatch.setattr(gcs, "build_game_chips", _boom)
    cards = [_card()]
    assert _refresh_layer2_live_state(cards, ["2026-08-11"]) == 0
    assert cards[0]["lane"] == "pregame"


def test_only_tracked_markets_are_joined_and_the_rest_are_labelled():
    """`#368`. The odds tracker keeps history for h2h/totals/spreads only.
    Measured on the served board: event+market overlap 11 of 73, so joining
    everything would light up a fifth of the column and leave the rest
    indistinguishable from a bug.

    EXACT match, not prefix -- `totals_alt` and `spreads_alt` begin with a
    tracked name and are not tracked. `startswith` here would relabel 95 of 200
    rows as "has history" and put the column straight back to looking broken.
    """
    from syndicate.features.shared.layer2_board import _movement_is_tracked

    for tracked in ("h2h", "totals", "spreads", "H2H", " totals "):
        assert _movement_is_tracked(tracked) is True
    for untracked in ("totals_alt", "spreads_alt", "h2h_lay", "h2h_3_way",
                      "batter_hits", "player_points", "", None):
        assert _movement_is_tracked(untracked) is False, f"{untracked!r} has no history series"


def test_movement_is_built_from_the_history_shard():
    """Joined on event_id + market, which works because the shard and the L2-A
    row share the OddsAPI id space -- unlike the scoreboard chips, whose statsapi
    ids overlap these 0 of 27."""
    from syndicate.features.shared.layer2_board import _line_movement_for_row

    history = {"markets": {
        "event_id=abc|home_team=H|away_team=A|market=totals|bookmaker=dk": {
            "closing_line": 9.5, "closing_price": -105.0,
            "history_first": {"previous_line": 8.5},
        }
    }}
    out = _line_movement_for_row({"event_id": "abc", "market": "totals"}, history)
    assert out["opening_line"] == 8.5 and out["latest_line"] == 9.5
    assert out["line_delta"] == 1.0 and out["line_direction"] == "up"

    # A different event must not borrow this series.
    assert _line_movement_for_row({"event_id": "zzz", "market": "totals"}, history) is None
    # Nor a different market on the same event.
    assert _line_movement_for_row({"event_id": "abc", "market": "spreads"}, history) is None
    # Unreadable history is not a crash.
    assert _line_movement_for_row({"event_id": "abc", "market": "totals"}, None) is None


def test_an_untracked_row_is_labelled_even_when_history_is_unreadable():
    """The label comes from the market name, not from a successful load, so a
    shard outage cannot turn "not tracked" back into an unexplained dash."""
    from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

    row = {"event_id": "e", "sport": "mlb", "market": "batter_hits", "side": "over",
           "kind": "prop", "ev_pct": 1.0, "home_team": "H", "away_team": "A",
           "quote": {"price": -110}, "score": {"score": 0.4}}
    card = layer2_rows_to_board_cards([row])[0]
    assert card["movement_not_tracked"] is True
    assert "line_odds_movement" not in card


def test_an_impossible_book_is_rejected_not_ranked_first():
    """`#369`. `ev_pct` is the no-vig surplus, so implied total == 100/(1+ev/100).
    Measured 2026-08-12 00:11Z: the #1 board row was Baltimore +107 AND Minnesota
    +200 on the same two-way h2h -- 81.6% implied, an 18-point underround, which
    became a 22.49% "edge" and ranked first. 20 of the top 20 were this shape,
    and `suspect_stale` caught 1 of 63.

    The threshold is a magnitude test on ev_pct and `#369` warned against those.
    What makes this one legitimate is that it is DERIVED from a stated
    impossibility rather than chosen to trim the board: no book prices a market
    under 95%. A genuine cross-book arb runs 0-3%.
    """
    from syndicate.features.shared.layer2_board import (
        _implied_book_total_pct,
        _MIN_IMPLIED_BOOK_TOTAL_PCT,
    )

    assert round(_implied_book_total_pct(22.4852), 2) == 81.64
    assert _implied_book_total_pct(22.4852) < _MIN_IMPLIED_BOOK_TOTAL_PCT

    # A NORMAL market holds a margin, so its implied total is ABOVE 100 and it
    # must never be touched by this -- rejecting normal pricing would empty the
    # board, which is exactly how the value floor went wrong at 0.0.
    assert _implied_book_total_pct(-1.0953) > 100.0
    assert _implied_book_total_pct(-1.0953) > _MIN_IMPLIED_BOOK_TOTAL_PCT

    # A small real arb survives.
    assert _implied_book_total_pct(1.6332) > _MIN_IMPLIED_BOOK_TOTAL_PCT

    # Unknown is not rejected: absent ev_pct must not be treated as impossible.
    assert _implied_book_total_pct(None) is None
    assert _implied_book_total_pct("nonsense") is None
