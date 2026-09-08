"""Pricing plane v1 -- a SHARP anchor for the board's fair probability.

`_fair_by_side` took the MEDIAN of every book's own de-vig (`#384`), which made
Pinnacle one vote in ~44. `SYNDICATE_FAIR_ANCHOR=sharp` lets ONE sharp book's
two-sided market (then one exchange's) BE the fair, power-de-vigged. The default
is today's behaviour, and the first test here is the one that proves it.

Every tier still de-vigs within ONE book: the anchor is Pinnacle's home AND
Pinnacle's away, or nothing. A cross-book pair launders the line-shopping gap
into the fair (`tests/test_layer2_fair_value.py` carries that measurement).
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import pytest

from syndicate.features.shared import layer2_board, live_gameline_ledger, sharp_books
from syndicate.features.shared.book_shortlist import DIRECT_FEED_BOOKS
from syndicate.features.shared.layer2_board import _fair_by_side, _resolve_fair, build_layer2_rows
from syndicate.features.shared.opportunity_signals import consensus_fair_probability, devig

SIDES = ["home", "away"]

# THE FIELDS THIS CHANGE ADDS TO EVERY QUOTE. Named once, here, so the
# byte-identity test strips exactly these and nothing else.
NEW_QUOTE_FIELDS = ("fair_anchor_book", "fair_devig_method", "fair_consensus_prob")


def _cell(price: int, age: float = 30.0, **extra: Any) -> dict[str, Any]:
    return {"price": price, "age_seconds": age, "stale": False, **extra}


def _cells(**books: tuple[int, int]) -> dict[str, dict[str, dict[str, Any]]]:
    """`_cells(pinnacle=(-115, 105), ...)` -> the grid's `cells` shape."""
    return {book: {"home": _cell(home), "away": _cell(away)} for book, (home, away) in books.items()}


def _row(cells: Mapping[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sport": "mlb",
        "event_id": "evt1",
        "kind": "game",
        "market": "h2h",
        "segment": "full",
        "line": None,
        "player_name": None,
        "home_team": "St. Louis Cardinals",
        "away_team": "Colorado Rockies",
        "commence_time": "2026-08-08T00:15:00Z",
        "sides": list(SIDES),
        "books_quoting": 3,
        "game": {"state": "pregame", "status_token": "7:15P CT"},
        # Bettable on both sides at ONE book (see `test_layer2_board._row`).
        "best": {
            "home": {"price": -108, "bookmaker": "draftkings", "age_seconds": 30.0, "books_quoting": 3},
            "away": {"price": 100, "bookmaker": "draftkings", "age_seconds": 30.0, "books_quoting": 3},
        },
    }
    if cells is not None:
        row["cells"] = cells
    row.update(overrides)
    return row


# A grid where the sharp anchor, the exchange and the soft median all DISAGREE,
# so a mode that silently used the wrong one is visible in the numbers.
def _grid() -> list[dict[str, Any]]:
    return [
        _row(
            _cells(
                pinnacle=(-125, 115),
                kalshi=(-140, 125),
                draftkings=(-108, 100),
                fanduel=(-110, -102),
                betmgm=(-105, -105),
            )
        ),
    ]


def _legacy_fair_by_side(row: Mapping[str, Any], sides: list[str]) -> tuple[dict[str, float], str | None]:
    """`_fair_by_side` EXACTLY as it stood before the anchor tiers (origin/main
    at 2026-09-08, `layer2_board.py:929-1005`), comments removed. The
    differential test below runs the board against THIS to prove the default
    is unchanged, rather than trusting that the refactor moved code verbatim."""
    from syndicate.features.shared.layer2_board import _as_float

    best = row.get("best") or {}
    cells = row.get("cells")
    if isinstance(cells, Mapping):
        prices_by_book: dict[str, dict[str, Any]] = {}
        for book, sides_map in cells.items():
            if not isinstance(sides_map, Mapping):
                continue
            per_side = {
                side: price
                for side in sides
                if isinstance(sides_map.get(side), Mapping)
                and (price := _as_float(sides_map[side].get("price"))) is not None
            }
            if len(per_side) == len(sides) and len(per_side) >= 2:
                prices_by_book[str(book)] = per_side
        if prices_by_book:
            consensus = consensus_fair_probability(prices_by_book)
            if consensus and len(consensus) == len(sides):
                return ({str(side): value for side, value in consensus.items()}, "consensus")
    prices = [(_as_float((best.get(side) or {}).get("price")), side) for side in sides]
    books_used = {str((best.get(side) or {}).get("bookmaker") or "") for side in sides}
    if (
        len(prices) >= 2
        and all(price is not None for price, _ in prices)
        and len(books_used) == 1
        and "" not in books_used
    ):
        probabilities = devig([price for price, _ in prices])
        if probabilities and len(probabilities) == len(prices):
            return ({side: probabilities[i] for i, (_, side) in enumerate(prices)}, "two_sided_same_book")
    modelled = row.get("modelled_fair") or {}
    out: dict[str, float] = {}
    for side in sides:
        probability = _as_float((modelled.get(side) or {}).get("fair_probability"))
        if probability is not None:
            out[side] = probability
    return (out, "book_margin_model" if out else None)


def _serialised_without_new_fields(result: Mapping[str, Any]) -> str:
    stripped = json.loads(json.dumps(result, sort_keys=True, default=str))
    for candidate in stripped.get("opportunities") or []:
        for field in NEW_QUOTE_FIELDS:
            candidate.get("quote", {}).pop(field, None)
    return json.dumps(stripped, sort_keys=True)


@pytest.fixture(autouse=True)
def _default_env(monkeypatch):
    monkeypatch.delenv(layer2_board.FAIR_ANCHOR_ENV, raising=False)
    monkeypatch.delenv(layer2_board.FAIR_DEVIG_METHOD_ENV, raising=False)


# --------------------------------------------------------------------------
# (a) The default is today's behaviour.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("flag", [None, "median", "MEDIAN", "", "garbage"])
def test_flag_absent_or_median_is_byte_identical_to_the_legacy_board(monkeypatch, flag):
    """The grid carries a two-sided Pinnacle AND a two-sided Kalshi -- every
    anchor tier COULD fire -- and the board must not notice.

    Compared against the legacy function itself, not against a golden file:
    the output carries no wall-clock field, and a golden would go stale on the
    next unrelated column while a legacy body cannot.
    """
    if flag is not None:
        monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, flag)
    with_anchor_code = build_layer2_rows(_grid())
    assert with_anchor_code["opportunities"], "fixture produced no scored candidates"

    def _legacy_resolution(row, sides):
        fair, method = _legacy_fair_by_side(row, sides)
        return layer2_board._FairResolution(fair, method, None, None, {})

    monkeypatch.setattr(layer2_board, "_resolve_fair", _legacy_resolution)
    legacy = build_layer2_rows(_grid())

    assert _serialised_without_new_fields(with_anchor_code) == _serialised_without_new_fields(legacy)
    for candidate in with_anchor_code["opportunities"]:
        quote = candidate["quote"]
        assert quote["fair_method"] == "consensus"
        assert quote["fair_anchor_book"] is None
        assert quote["fair_devig_method"] == "multiplicative"
        assert quote["fair_consensus_prob"] == quote["fair_probability"]


def test_the_default_fair_is_the_median_over_every_book_pinnacle_included():
    row = _grid()[0]
    fair, method = _fair_by_side(row, SIDES)
    expected = consensus_fair_probability(
        {book: {side: cell["price"] for side, cell in sides.items()} for book, sides in row["cells"].items()}
    )
    assert method == "consensus"
    assert fair == {side: expected[side] for side in SIDES}


# --------------------------------------------------------------------------
# (b) `sharp`: Pinnacle's own two sides, power-de-vigged.
# --------------------------------------------------------------------------


def test_sharp_anchors_on_pinnacles_power_devig(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    row = _grid()[0]
    resolved = _resolve_fair(row, SIDES)
    expected = devig([-125, 115], method="power")
    assert resolved.method == "sharp_anchor"
    assert resolved.anchor_book == "pinnacle"
    assert resolved.devig_method == "power"
    assert resolved.fair_by_side == {"home": expected[0], "away": expected[1]}
    # The counterfactual is still computed, and it is the default's answer.
    assert resolved.consensus_by_side == _legacy_fair_by_side(row, SIDES)[0]
    # And the two genuinely differ on this grid -- otherwise the test is vacuous.
    assert resolved.fair_by_side["home"] != resolved.consensus_by_side["home"]


def test_sharp_changes_only_the_fair_never_the_price_side_of_ev(monkeypatch):
    """The anchor is a REFERENCE. The price EV is measured at is still the best
    bettable book, and `fair_consensus_prob` still says what the median was."""
    median = {c["side"]: c for c in build_layer2_rows(_grid())["opportunities"]}
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    sharp = {c["side"]: c for c in build_layer2_rows(_grid())["opportunities"]}
    assert set(sharp) == set(median) == set(SIDES)
    for side in SIDES:
        assert sharp[side]["quote"]["price"] == median[side]["quote"]["price"]
        # Best BETTABLE book on the grid, whichever it is -- and pinnacle and
        # kalshi are both in `DEFAULT_BOOKS`, so the anchor book being chosen
        # as the PRICE would be legitimate line-shopping, not a leak. What may
        # not happen is the anchor MOVING the price, so the two modes must agree.
        assert sharp[side]["quote"]["bookmaker"] == median[side]["quote"]["bookmaker"]
        assert sharp[side]["quote"]["fair_method"] == "sharp_anchor"
        assert sharp[side]["quote"]["fair_anchor_book"] == "pinnacle"
        assert sharp[side]["quote"]["fair_devig_method"] == "power"
        assert sharp[side]["quote"]["fair_consensus_prob"] == median[side]["quote"]["fair_probability"]
        assert sharp[side]["quote"]["fair_probability"] != median[side]["quote"]["fair_probability"]
        assert sharp[side]["ev_pct"] != median[side]["ev_pct"]


# --------------------------------------------------------------------------
# (c) Pinnacle one-sided -> exchange mid, else the consensus chain.
# --------------------------------------------------------------------------


def test_pinnacle_one_sided_falls_to_the_exchange_mid(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    cells = _cells(kalshi=(-140, 125), draftkings=(-108, 100), fanduel=(-110, -102))
    cells["pinnacle"] = {"home": _cell(-125)}
    resolved = _resolve_fair(_row(cells), SIDES)
    expected = devig([-140, 125], method="power")
    assert resolved.method == "exchange_mid"
    assert resolved.anchor_book == "kalshi"
    assert resolved.fair_by_side == {"home": expected[0], "away": expected[1]}


def test_no_two_sided_sharp_or_exchange_falls_to_the_unchanged_consensus(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    cells = _cells(draftkings=(-108, 100), fanduel=(-110, -102), betmgm=(-105, -105))
    cells["pinnacle"] = {"home": _cell(-125)}
    cells["kalshi"] = {"away": _cell(125)}
    row = _row(cells)
    resolved = _resolve_fair(row, SIDES)
    assert resolved.method == "consensus"
    assert resolved.anchor_book is None
    assert (resolved.fair_by_side, resolved.method) == _legacy_fair_by_side(row, SIDES)


def test_sharp_with_no_cells_still_reaches_the_same_book_fallback(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    row = _row()  # `best` only, one book on both sides
    resolved = _resolve_fair(row, SIDES)
    assert (resolved.fair_by_side, resolved.method) == _legacy_fair_by_side(row, SIDES)
    assert resolved.method == "two_sided_same_book"
    assert resolved.anchor_book == "draftkings"


def test_exchange_tier_order_is_depth_then_the_direct_venues(monkeypatch):
    """betfair_ex_eu outranks kalshi when both are two-sided, and the priority
    is the registry's order, not the dict order of `cells`."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    cells = _cells(kalshi=(-140, 125), betfair_ex_eu=(-118, 112), draftkings=(-108, 100))
    resolved = _resolve_fair(_row(cells), SIDES)
    assert resolved.method == "exchange_mid"
    assert resolved.anchor_book == "betfair_ex_eu"


# --------------------------------------------------------------------------
# (d) A stale or non-simultaneous second side is NOT an anchor.
# --------------------------------------------------------------------------


def test_a_second_side_beyond_the_simultaneity_tolerance_is_not_used(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    cells = _cells(draftkings=(-108, 100), fanduel=(-110, -102))
    cells["pinnacle"] = {"home": _cell(-125, age=10.0), "away": _cell(115, age=10.0 + 601.0)}
    resolved = _resolve_fair(_row(cells), SIDES)
    assert resolved.method == "consensus", "a 601s-apart pair was de-vigged as one market"
    cells["pinnacle"]["away"] = _cell(115, age=10.0 + 600.0)
    assert _resolve_fair(_row(cells), SIDES).method == "sharp_anchor", "600s is inside the tolerance"


def test_a_grid_flagged_stale_cell_is_not_an_anchor(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    cells = _cells(draftkings=(-108, 100), fanduel=(-110, -102))
    cells["pinnacle"] = {"home": _cell(-125), "away": _cell(115, stale=True)}
    assert _resolve_fair(_row(cells), SIDES).method == "consensus"


def test_an_unknown_age_is_refused_not_admitted(monkeypatch):
    """Unknown must not default permissive: a cell with no `age_seconds` cannot
    be shown simultaneous with anything, so it cannot anchor."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    cells = _cells(draftkings=(-108, 100), fanduel=(-110, -102))
    cells["pinnacle"] = {"home": {"price": -125}, "away": {"price": 115}}
    assert _resolve_fair(_row(cells), SIDES).method == "consensus"


def test_a_three_way_anchor_needs_every_leg(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    sides = ["home", "draw", "away"]
    full = {"home": _cell(150), "draw": _cell(230), "away": _cell(190)}
    row = _row({"pinnacle": full, "draftkings": full}, sides=sides, market="h2h_3_way")
    resolved = _resolve_fair(row, sides)
    assert resolved.method == "sharp_anchor"
    assert abs(sum(resolved.fair_by_side.values()) - 1.0) < 1e-9
    two_legs = {"home": _cell(150), "away": _cell(190)}
    row = _row({"pinnacle": two_legs, "draftkings": full}, sides=sides, market="h2h_3_way")
    assert _resolve_fair(row, sides).method == "consensus"


# --------------------------------------------------------------------------
# `SYNDICATE_FAIR_DEVIG_METHOD` on the consensus chain, independent of anchor.
# --------------------------------------------------------------------------


def test_devig_method_flag_changes_the_consensus_and_is_recorded(monkeypatch):
    row = _grid()[0]
    multiplicative = _resolve_fair(row, SIDES)
    monkeypatch.setenv(layer2_board.FAIR_DEVIG_METHOD_ENV, "power")
    power = _resolve_fair(row, SIDES)
    assert multiplicative.method == power.method == "consensus"
    assert multiplicative.devig_method == "multiplicative"
    assert power.devig_method == "power"
    assert power.fair_by_side["home"] != multiplicative.fair_by_side["home"]
    assert abs(sum(power.fair_by_side.values()) - 1.0) < 1e-9


def test_an_unknown_devig_method_falls_back_to_multiplicative(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_DEVIG_METHOD_ENV, "additive")
    assert _resolve_fair(_grid()[0], SIDES).devig_method == "multiplicative"


# --------------------------------------------------------------------------
# (e) power vs multiplicative on known pairs.
# --------------------------------------------------------------------------


def test_devig_methods_agree_on_a_symmetric_pair_and_differ_on_a_skewed_one():
    assert devig([-110, -110]) == pytest.approx([0.5, 0.5])
    assert devig([-110, -110], method="power") == pytest.approx([0.5, 0.5])

    multiplicative = devig([-200, 170])
    power = devig([-200, 170], method="power")
    assert abs(sum(power) - 1.0) < 1e-9
    assert abs(sum(multiplicative) - 1.0) < 1e-9
    assert power != pytest.approx(multiplicative)
    # Power takes more from the longshot: +170's fair is LOWER under power.
    assert power[1] < multiplicative[1]


# --------------------------------------------------------------------------
# (f) One definition of the sharp set; no drift.
# --------------------------------------------------------------------------


def test_the_ledger_reads_the_shared_sharp_set_not_a_copy():
    assert live_gameline_ledger._SHARP_BOOKS is sharp_books.SHARP_BOOKS
    assert sharp_books.SHARP_BOOKS == frozenset({"pinnacle", "betfair_ex_eu", "matchbook", "novig", "prophetx"})


def test_the_anchor_tiers_are_drawn_from_the_registries():
    assert set(sharp_books.SHARP_ANCHOR_PRIORITY) <= sharp_books.SHARP_BOOKS
    assert sharp_books.SHARP_ANCHOR_PRIORITY[0] == "pinnacle"
    # The direct-feed venues are in the exchange tier under the SAME keys the
    # grid writes them with (`venue_quote_fanin._VENUE_BOOK_NAME` values).
    assert DIRECT_FEED_BOOKS <= set(sharp_books.EXCHANGE_ANCHOR_PRIORITY)
    assert not (set(sharp_books.SHARP_ANCHOR_PRIORITY) & set(sharp_books.EXCHANGE_ANCHOR_PRIORITY))
    assert len(set(sharp_books.EXCHANGE_ANCHOR_PRIORITY)) == len(sharp_books.EXCHANGE_ANCHOR_PRIORITY)
