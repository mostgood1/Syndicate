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
from syndicate.features.shared.opportunity_signals import consensus_fair_probability, devig, hold_pct

SIDES = ["home", "away"]

# THE FIELDS THIS CHANGE ADDS TO EVERY QUOTE. Named once, here, so the
# byte-identity test strips exactly these and nothing else.
NEW_QUOTE_FIELDS = (
    "fair_anchor_book",
    "fair_devig_method",
    "fair_consensus_prob",
    # P1b -- the exchange gates' working.
    "fair_anchor_hold_pct",
    "fair_anchor_refusal",
    # P1c -- every refusal that fired, and the evaluated pair's median gap.
    "fair_anchor_refusals",
    "fair_anchor_median_gap_pp",
)


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
        # `median` has no anchor tier, so it never evaluated a pair to refuse.
        assert quote["fair_anchor_hold_pct"] is None
        assert quote["fair_anchor_refusal"] is None
        # P1c: None, not an empty list -- no tier ran, so there is no list.
        assert quote["fair_anchor_refusals"] is None
        assert quote["fair_anchor_median_gap_pp"] is None


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
    """The Kalshi pair here sits ~1 pp from the two-book median (P1c's
    distance gate admits it); the original -140/+125 sat 6.1 pp away and would
    now be `exchange_far_from_median` -- see section (k) for that case."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    cells = _cells(kalshi=(-112, 104), draftkings=(-108, 100), fanduel=(-110, -102))
    cells["pinnacle"] = {"home": _cell(-125)}
    resolved = _resolve_fair(_row(cells), SIDES)
    expected = devig([-112, 104], method="power")
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


# --------------------------------------------------------------------------
# (g) P1b -- the exchange tier anchors only when TIGHT and CORROBORATED.
#
# The reading that made these gates (refresh-worker d8ed991a, 2026-09-08
# 23:10Z, 331 anchored rows): Pinnacle mean |sharp - median| 0.885 pp, 1 row
# past 5 pp; Kalshi 2.699 pp and 17 rows past 5 pp; the ten largest gaps on
# the board all `exchange_mid`. A wide or thin exchange pair has a mid; that
# mid is not a fair.
# --------------------------------------------------------------------------

SOFT = dict(draftkings=(-108, 100), fanduel=(-110, -102), betmgm=(-105, -105))

#: Exchange pairs by the hold they carry (`hold_pct`, pp). Asserted below so a
#: change to `hold_pct`'s definition cannot silently move a test to the other
#: side of the 4.0 line.
TIGHT_PAIR = (-106, -102)  # ~1.9%
MID_PAIR = (-113, -113)  # ~5.8%: over the default, under a relaxed 20.0
WIDE_PAIR = (-132, -132)  # ~12.1%


@pytest.fixture(autouse=True)
def _default_gate_env(monkeypatch):
    monkeypatch.delenv(layer2_board.FAIR_EXCHANGE_MAX_HOLD_PCT_ENV, raising=False)
    monkeypatch.delenv(layer2_board.FAIR_EXCHANGE_MIN_BOOKS_ENV, raising=False)


def test_the_fixture_pairs_sit_where_the_test_names_say():
    assert 1.5 < hold_pct(list(TIGHT_PAIR)) < 2.5
    assert 4.0 < hold_pct(list(MID_PAIR)) < 8.0
    assert 11.0 < hold_pct(list(WIDE_PAIR)) < 13.0
    assert layer2_board.FAIR_EXCHANGE_MAX_HOLD_PCT_DEFAULT == 4.0
    assert layer2_board.FAIR_EXCHANGE_MIN_BOOKS_DEFAULT == 3


def _with_books(row: dict[str, Any], count: int) -> dict[str, Any]:
    row["books_quoting"] = count
    for side in row["best"].values():
        side["books_quoting"] = count
    return row


def test_a_kalshi_pair_at_twelve_percent_hold_is_refused_and_the_row_reads_consensus(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    row = _row(_cells(kalshi=WIDE_PAIR, **SOFT))
    resolved = _resolve_fair(row, SIDES)
    assert resolved.method == "consensus"
    assert resolved.anchor_book is None
    assert resolved.anchor_refusal == "exchange_hold_too_wide"
    assert resolved.anchor_hold_pct == hold_pct(list(WIDE_PAIR))
    # The consensus it fell to is THE consensus -- Kalshi is still one vote in it.
    assert (resolved.fair_by_side, resolved.method) == _legacy_fair_by_side(row, SIDES)
    assert resolved.consensus_by_side == resolved.fair_by_side


def test_a_kalshi_pair_at_two_percent_hold_anchors_and_stamps_its_hold(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    resolved = _resolve_fair(_row(_cells(kalshi=TIGHT_PAIR, **SOFT)), SIDES)
    expected = devig(list(TIGHT_PAIR), method="power")
    assert resolved.method == "exchange_mid"
    assert resolved.anchor_book == "kalshi"
    assert resolved.anchor_refusal is None
    assert resolved.anchor_hold_pct == hold_pct(list(TIGHT_PAIR))
    assert resolved.fair_by_side == {"home": expected[0], "away": expected[1]}


def test_a_lone_exchange_is_uncorroborated_but_a_lone_pinnacle_still_anchors(monkeypatch):
    """Pinnacle IS the corroboration; an exchange with nobody else on the line is not."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    exchange_alone = _resolve_fair(_with_books(_row(_cells(kalshi=TIGHT_PAIR)), 1), SIDES)
    assert exchange_alone.method == "consensus"
    assert exchange_alone.anchor_refusal == "exchange_uncorroborated"
    assert exchange_alone.anchor_hold_pct == hold_pct(list(TIGHT_PAIR))

    pinnacle_alone = _resolve_fair(_with_books(_row(_cells(pinnacle=(-125, 115))), 1), SIDES)
    assert pinnacle_alone.method == "sharp_anchor"
    assert pinnacle_alone.anchor_book == "pinnacle"
    assert pinnacle_alone.anchor_refusal is None
    assert pinnacle_alone.anchor_hold_pct == hold_pct([-125, 115])


def test_an_unknown_book_count_is_refused_not_admitted(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    row = _row(_cells(kalshi=TIGHT_PAIR, **SOFT))
    row["books_quoting"] = None
    for side in row["best"].values():
        side.pop("books_quoting", None)
    resolved = _resolve_fair(row, SIDES)
    assert resolved.method == "consensus"
    assert resolved.anchor_refusal == "exchange_uncorroborated"


def test_the_row_count_falls_back_to_the_per_side_counts(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    row = _row(_cells(kalshi=TIGHT_PAIR, **SOFT))
    row["books_quoting"] = None  # per-side `best` still says 3
    assert _resolve_fair(row, SIDES).method == "exchange_mid"


def test_the_pinnacle_tier_is_not_gated_on_the_exchanges_hold_cap(monkeypatch):
    """P1b: the 4.0 hold cap is the EXCHANGE tier's. P1c gave Pinnacle its own
    cap at 5.0, so a pair between the two anchors as Pinnacle and is refused
    as an exchange -- and a 12% Pinnacle pair, which P1b admitted, no longer
    is (section (k))."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    between = (-111, -109)  # ~4.54%: over the exchange's 4.0, under Pinnacle's 5.0
    assert 4.0 < hold_pct(list(between)) < 5.0
    as_pinnacle = _resolve_fair(_row(_cells(pinnacle=between, **SOFT)), SIDES)
    assert as_pinnacle.method == "sharp_anchor"
    assert as_pinnacle.anchor_hold_pct == hold_pct(list(between))
    as_exchange = _resolve_fair(_row(_cells(kalshi=between, **SOFT)), SIDES)
    assert as_exchange.method == "consensus"
    assert as_exchange.anchor_refusal == "exchange_hold_too_wide"


def test_a_refused_deep_exchange_does_not_stop_a_tighter_one_below_it(monkeypatch):
    """The refusal recorded is the FIRST in priority order, but the tier keeps
    looking: betfair wide, kalshi tight -> kalshi anchors, no refusal."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    resolved = _resolve_fair(_row(_cells(betfair_ex_eu=WIDE_PAIR, kalshi=TIGHT_PAIR, **SOFT)), SIDES)
    assert resolved.method == "exchange_mid"
    assert resolved.anchor_book == "kalshi"
    assert resolved.anchor_refusal is None
    both_wide = _resolve_fair(_row(_cells(betfair_ex_eu=WIDE_PAIR, kalshi=MID_PAIR, **SOFT)), SIDES)
    assert both_wide.anchor_refusal == "exchange_hold_too_wide"
    assert both_wide.anchor_hold_pct == hold_pct(list(WIDE_PAIR)), "the deepest refused venue's hold"


def test_the_refusal_and_hold_reach_the_served_quote(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    refused = build_layer2_rows([_row(_cells(kalshi=WIDE_PAIR, **SOFT))])["opportunities"]
    anchored = build_layer2_rows([_row(_cells(kalshi=TIGHT_PAIR, **SOFT))])["opportunities"]
    assert refused and anchored
    for candidate in refused:
        quote = candidate["quote"]
        assert quote["fair_method"] == "consensus"
        assert quote["fair_anchor_refusal"] == "exchange_hold_too_wide"
        assert quote["fair_anchor_hold_pct"] == hold_pct(list(WIDE_PAIR))
        assert quote["fair_consensus_prob"] == quote["fair_probability"]
    for candidate in anchored:
        quote = candidate["quote"]
        assert quote["fair_method"] == "exchange_mid"
        assert quote["fair_anchor_refusal"] is None
        assert quote["fair_anchor_hold_pct"] == hold_pct(list(TIGHT_PAIR))
        assert quote["fair_consensus_prob"] != quote["fair_probability"]


# --------------------------------------------------------------------------
# (h) `sharp_only`: the Pinnacle tier, then the consensus chain. No exchanges.
# --------------------------------------------------------------------------


def test_sharp_only_never_produces_an_exchange_mid(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp_only")
    tight_exchange_no_pinnacle = _row(_cells(kalshi=TIGHT_PAIR, betfair_ex_eu=TIGHT_PAIR, **SOFT))
    resolved = _resolve_fair(tight_exchange_no_pinnacle, SIDES)
    assert resolved.method == "consensus"
    assert resolved.anchor_refusal is None, "no exchange tier ran, so nothing was refused"
    assert resolved.anchor_hold_pct is None
    assert (resolved.fair_by_side, resolved.method) == _legacy_fair_by_side(tight_exchange_no_pinnacle, SIDES)

    with_pinnacle = _resolve_fair(_grid()[0], SIDES)
    assert with_pinnacle.method == "sharp_anchor"
    assert with_pinnacle.anchor_book == "pinnacle"

    board = build_layer2_rows([tight_exchange_no_pinnacle, _grid()[0]])["opportunities"]
    assert board
    assert {c["quote"]["fair_method"] for c in board} == {"consensus", "sharp_anchor"}


def test_sharp_still_anchors_the_exchange_that_sharp_only_skips(monkeypatch):
    """The two modes differ on exactly the exchange tier -- otherwise the flag
    value would be a synonym."""
    row = _row(_cells(kalshi=TIGHT_PAIR, **SOFT))
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    assert _resolve_fair(row, SIDES).method == "exchange_mid"
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp_only")
    assert _resolve_fair(row, SIDES).method == "consensus"


# --------------------------------------------------------------------------
# (i) The gates are reachable from the environment: off != on.
# --------------------------------------------------------------------------


def test_max_hold_env_is_reachable_off_is_not_on(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    row = _row(_cells(kalshi=MID_PAIR, **SOFT))
    assert _resolve_fair(row, SIDES).method == "consensus", "absent env must be the 4.0 default"
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_HOLD_PCT_ENV, "4.0")
    assert _resolve_fair(row, SIDES).anchor_refusal == "exchange_hold_too_wide"
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_HOLD_PCT_ENV, "20.0")
    assert _resolve_fair(row, SIDES).method == "exchange_mid"
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_HOLD_PCT_ENV, "garbage")
    assert _resolve_fair(row, SIDES).method == "consensus", "unparseable falls back to the default"


def test_min_books_env_is_reachable_off_is_not_on(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    row = _with_books(_row(_cells(kalshi=TIGHT_PAIR, **SOFT)), 2)
    assert _resolve_fair(row, SIDES).anchor_refusal == "exchange_uncorroborated"
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MIN_BOOKS_ENV, "2")
    assert _resolve_fair(row, SIDES).method == "exchange_mid"
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MIN_BOOKS_ENV, "0")
    assert _resolve_fair(row, SIDES).anchor_refusal == "exchange_uncorroborated", "0 is not a count; default"


def test_the_gate_readers_default_on_absent_or_garbage(monkeypatch):
    assert layer2_board._fair_exchange_max_hold_pct() == 4.0
    assert layer2_board._fair_exchange_min_books() == 3
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_HOLD_PCT_ENV, "-1")
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MIN_BOOKS_ENV, "x")
    assert layer2_board._fair_exchange_max_hold_pct() == 4.0
    assert layer2_board._fair_exchange_min_books() == 3


@pytest.mark.parametrize("flag", ["sharp_only", "SHARP_ONLY", " sharp_only "])
def test_sharp_only_is_parsed_and_garbage_is_median(monkeypatch, flag):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, flag)
    assert layer2_board._fair_anchor_mode() == "sharp_only"
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp-only")
    assert layer2_board._fair_anchor_mode() == "median"


# --------------------------------------------------------------------------
# (j) The production extreme, reproduced.
# --------------------------------------------------------------------------


def test_the_production_extreme_a_wide_kalshi_under_does_not_anchor_under_defaults(monkeypatch):
    """The largest gap on the 2026-09-08 `sharp` board: a Kalshi MLB under 3.5
    at an exchange-mid fair of 0.093 against a four-book median of 0.380.

    The real Kalshi pair was not captured in the reading (the +950 it recorded
    is the best BETTABLE price, not Kalshi's own), and a 12% hold with the
    under at +950 is arithmetically impossible -- the over would need an
    implied probability above 1. So this is the SYNTHETIC pair the brief asked
    for: a Kalshi under/over whose own hold is ~12%, whose power-de-vigged under
    sits far below the soft median, against four soft books at ~0.38.
    """
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    sides = ["over", "under"]
    soft = {"over": _cell(-178), "under": _cell(152)}
    kalshi = {"over": _cell(-1100), "under": _cell(350)}
    kalshi_hold = hold_pct([-1100, 350])
    assert 11.0 < kalshi_hold < 13.0, kalshi_hold
    row = _row(
        {"kalshi": kalshi, "draftkings": soft, "fanduel": soft, "betmgm": soft, "caesars": soft},
        sides=sides,
        market="totals_alt",
        line=3.5,
        books_quoting=5,
        best={
            "over": {"price": -178, "bookmaker": "draftkings", "age_seconds": 30.0, "books_quoting": 5},
            "under": {"price": 350, "bookmaker": "kalshi", "age_seconds": 30.0, "books_quoting": 5},
        },
    )
    resolved = _resolve_fair(row, sides)
    # The mid this pair WOULD have anchored, and how far from the median it is.
    mid_under = devig([-1100, 350], method="power")[1]
    assert mid_under < 0.15
    assert 0.37 < resolved.consensus_by_side["under"] < 0.40
    # Under the defaults it does not anchor; the row reads the consensus.
    assert resolved.method == "consensus"
    assert resolved.anchor_refusal == "exchange_hold_too_wide"
    assert resolved.anchor_hold_pct == kalshi_hold
    assert resolved.fair_by_side == resolved.consensus_by_side
    # With the HOLD gate relaxed it is STILL refused -- by P1c's distance gate,
    # which is the one that actually discriminates this pair: a mid of 0.09
    # against a median of 0.38 is ~28 pp away. Only with both relaxed does it
    # anchor, so the gates, not the pair, are what changed the answer.
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_HOLD_PCT_ENV, "20")
    hold_relaxed = _resolve_fair(row, sides)
    assert hold_relaxed.method == "consensus"
    assert hold_relaxed.anchor_refusal == "exchange_far_from_median"
    assert hold_relaxed.anchor_median_gap_pp == pytest.approx(
        abs(mid_under - resolved.consensus_by_side["under"]) * 100.0
    )
    assert hold_relaxed.anchor_median_gap_pp > 25.0
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_ENV, "50")
    relaxed = _resolve_fair(row, sides)
    assert relaxed.method == "exchange_mid"
    assert relaxed.fair_by_side["under"] == mid_under


def test_the_other_production_extreme_a_books_one_row_is_uncorroborated(monkeypatch):
    """Two of the ten largest gaps were `books=1` rows -- an in-play Kalshi
    total and a Polymarket HRR prop. However tight the pair, nobody else was on
    the line, and that is the corroboration gate."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    for venue in ("kalshi", "polymarket"):
        row = _with_books(_row(_cells(**{venue: TIGHT_PAIR})), 1)
        resolved = _resolve_fair(row, SIDES)
        assert resolved.method == "consensus", venue
        assert resolved.anchor_refusal == "exchange_uncorroborated", venue


# --------------------------------------------------------------------------
# (k) P1c -- the Pinnacle tier is gated on its OWN quality; the exchange tier
# on its DISTANCE from the median; every refusal is stamped.
#
# The readings (refresh-worker, served board, 2,000 rows each):
#   00:04Z `sharp`+P1b   Kalshi survivors n=66 mean|d| 3.089 pp, 14 > 5 pp, at
#                        hold mean 1.41% -- TIGHT BUT WRONG. Pinnacle n=60
#                        1.640 pp, 3 > 5 pp, holds to 7.26% in play.
#   00:55Z `sharp_only`  Pinnacle n=203 mean|d| 1.136 pp, 2 > 5 pp -- both
#                        in-play MLB `spreads_alt`, `books=1`, hold 5.8%.
# --------------------------------------------------------------------------

#: Pinnacle pairs by hold: the production extreme and one under the cap.
PINNACLE_WIDE_PAIR = MID_PAIR  # -113/-113, ~5.75%: the 00:55Z extreme's hold
PINNACLE_OK_PAIR = (-109, -108)  # ~3.9%: under the 5.0 cap

#: Exchange pairs by DISTANCE from a 19-book -110/-110 median (0.500), both
#: well under the 4.0 hold cap -- so only the distance gate can separate them.
NEAR_PAIR = (-112, 105)  # mid 0.520, ~2.0 pp away, hold ~1.6%
FAR_PAIR = (-134, 121)  # mid 0.561, ~6.1 pp away, hold ~2.5%
NINETEEN_SOFT = {f"soft{i:02d}": (-110, -110) for i in range(19)}

LIVE = {"state": "live", "status_token": "Top 5"}


@pytest.fixture(autouse=True)
def _default_p1c_env(monkeypatch):
    monkeypatch.delenv(layer2_board.FAIR_SHARP_MAX_HOLD_PCT_ENV, raising=False)
    monkeypatch.delenv(layer2_board.FAIR_SHARP_MIN_BOOKS_LIVE_ENV, raising=False)
    monkeypatch.delenv(layer2_board.FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_ENV, raising=False)


def _gap_pp(pair: tuple[int, int], consensus: Mapping[str, float]) -> float:
    return abs(devig(list(pair), method="power")[0] - consensus["home"]) * 100.0


def test_the_p1c_fixture_pairs_sit_where_the_test_names_say():
    assert 5.0 < hold_pct(list(PINNACLE_WIDE_PAIR)) < 6.0
    assert 3.5 < hold_pct(list(PINNACLE_OK_PAIR)) < 4.5
    assert layer2_board.FAIR_SHARP_MAX_HOLD_PCT_DEFAULT == 5.0
    assert layer2_board.FAIR_SHARP_MIN_BOOKS_LIVE_DEFAULT == 2
    assert layer2_board.FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_DEFAULT == 3.0
    median = _resolve_fair(_row(_cells(**NINETEEN_SOFT)), SIDES).consensus_by_side
    assert median["home"] == pytest.approx(0.5)
    assert hold_pct(list(NEAR_PAIR)) < 4.0 and hold_pct(list(FAR_PAIR)) < 4.0
    assert 1.5 < _gap_pp(NEAR_PAIR, median) < 2.5
    assert 5.5 < _gap_pp(FAR_PAIR, median) < 6.5


# -- the Pinnacle tier's hold cap ------------------------------------------


def test_a_pinnacle_pair_at_five_point_eight_is_refused_and_four_anchors(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp_only")
    wide = _resolve_fair(_row(_cells(pinnacle=PINNACLE_WIDE_PAIR, **SOFT)), SIDES)
    assert wide.method == "consensus"
    assert wide.anchor_book is None
    assert wide.anchor_refusal == "sharp_hold_too_wide"
    assert wide.anchor_refusals == ("sharp_hold_too_wide",)
    assert wide.anchor_hold_pct == hold_pct(list(PINNACLE_WIDE_PAIR))
    assert wide.fair_by_side == wide.consensus_by_side, "fell to consensus as if Pinnacle had not quoted"

    ok = _resolve_fair(_row(_cells(pinnacle=PINNACLE_OK_PAIR, **SOFT)), SIDES)
    assert ok.method == "sharp_anchor"
    assert ok.anchor_book == "pinnacle"
    assert ok.anchor_refusal is None
    assert ok.anchor_refusals == ()
    assert ok.anchor_hold_pct == hold_pct(list(PINNACLE_OK_PAIR))


def test_a_refused_pinnacle_falls_to_the_exchange_under_sharp_and_to_consensus_under_sharp_only(monkeypatch):
    """Exactly as if Pinnacle had not quoted -- and the passed-over refusal is
    still on the row, so the reading can count exchange_mid rows that exist
    because Pinnacle was gated."""
    row = _row(_cells(pinnacle=PINNACLE_WIDE_PAIR, kalshi=TIGHT_PAIR, **SOFT))
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    via_exchange = _resolve_fair(row, SIDES)
    assert via_exchange.method == "exchange_mid"
    assert via_exchange.anchor_book == "kalshi"
    assert via_exchange.anchor_refusal is None, "a non-None refusal means ON CONSENSUS because of a gate"
    assert via_exchange.anchor_refusals == ("sharp_hold_too_wide",)
    assert via_exchange.anchor_hold_pct == hold_pct(list(TIGHT_PAIR)), "the ANCHOR's hold, not the refused one's"
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp_only")
    via_consensus = _resolve_fair(row, SIDES)
    assert via_consensus.method == "consensus"
    assert via_consensus.anchor_refusal == "sharp_hold_too_wide"
    assert via_consensus.anchor_refusals == ("sharp_hold_too_wide",)


# -- the Pinnacle tier's in-play corroboration ------------------------------


def test_a_live_row_with_pinnacle_alone_is_refused_but_a_pregame_one_anchors(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp_only")
    pregame = _resolve_fair(_with_books(_row(_cells(pinnacle=(-125, 115))), 1), SIDES)
    assert pregame.method == "sharp_anchor", "a pregame Pinnacle line IS the corroboration"
    assert pregame.anchor_refusals == ()

    live = _resolve_fair(_with_books(_row(_cells(pinnacle=(-125, 115)), game=LIVE), 1), SIDES)
    assert live.method == "consensus"
    assert live.anchor_refusal == "sharp_uncorroborated_live"
    assert live.anchor_hold_pct == hold_pct([-125, 115])

    corroborated = _resolve_fair(_with_books(_row(_cells(pinnacle=(-125, 115), draftkings=(-108, 100)), game=LIVE), 2), SIDES)
    assert corroborated.method == "sharp_anchor", "two books on a live line is enough"


def test_an_unknown_book_count_on_a_live_row_is_refused_not_admitted(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp_only")
    row = _row(_cells(pinnacle=(-125, 115), **SOFT), game=LIVE)
    row["books_quoting"] = None
    for side in row["best"].values():
        side.pop("books_quoting", None)
    assert _resolve_fair(row, SIDES).anchor_refusal == "sharp_uncorroborated_live"
    row["game"] = {"state": "pregame"}
    assert _resolve_fair(row, SIDES).method == "sharp_anchor", "pregame has no count gate"


@pytest.mark.parametrize(
    "row_state, expected",
    [
        ({"game": {"state": "live"}}, True),
        ({"game": {"state": "IN_PROGRESS"}}, True),
        ({"game": {"state": "in"}}, True),
        ({"game": None, "is_live": True}, True),
        ({"game": None, "game_state": "live"}, True),
        ({"game": None, "market_state": "live"}, True),
        ({"game": {"state": "pregame"}}, False),
        ({"game": {"state": "final"}}, False),
        ({"game": {"state": "scheduled"}}, False),
        ({"game": None}, False),
        ({"game": None, "is_live": False}, False),
    ],
)
def test_row_is_live_reads_the_grids_state_and_the_translated_fields(row_state, expected):
    """`game.state` is what the grid carries at `_resolve_fair` time; the
    top-level fields are what `build_layer2_rows` writes afterwards. Only an
    affirmed in-play token counts -- final, pregame, unknown and absent do not."""
    assert layer2_board._row_is_live(_row(**row_state)) is expected


# -- the exchange tier's distance gate --------------------------------------


def test_an_exchange_two_pp_from_the_median_anchors_and_six_pp_is_refused(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    near = _resolve_fair(_row(_cells(kalshi=NEAR_PAIR, **NINETEEN_SOFT)), SIDES)
    assert near.method == "exchange_mid"
    assert near.anchor_book == "kalshi"
    assert near.anchor_refusals == ()
    assert near.anchor_median_gap_pp == pytest.approx(_gap_pp(NEAR_PAIR, near.consensus_by_side))

    far = _resolve_fair(_row(_cells(kalshi=FAR_PAIR, **NINETEEN_SOFT)), SIDES)
    assert far.method == "consensus"
    assert far.anchor_refusal == "exchange_far_from_median"
    assert far.anchor_refusals == ("exchange_far_from_median",)
    assert far.anchor_hold_pct == hold_pct(list(FAR_PAIR)), "the hold is stamped even when distance refused it"
    assert far.anchor_median_gap_pp == pytest.approx(_gap_pp(FAR_PAIR, far.consensus_by_side))
    assert far.anchor_median_gap_pp > 3.0


def test_an_exchange_with_no_median_to_check_is_refused_not_admitted(monkeypatch):
    """Kalshi alone in `cells` but `books_quoting` says 3 (one-sided books the
    grid counted): P1b's gates pass, and the "median" would be Kalshi's own
    de-vig. One book is not a median, so there is nothing to check against."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    resolved = _resolve_fair(_row(_cells(kalshi=TIGHT_PAIR)), SIDES)
    assert resolved.method == "consensus"
    assert resolved.anchor_refusal == "exchange_no_median_to_check"
    assert resolved.anchor_refusals == ("exchange_no_median_to_check",)
    # A second two-sided book is a median, and the pair is within 3 pp of it.
    with_one_more = _resolve_fair(_row(_cells(kalshi=TIGHT_PAIR, draftkings=(-108, 100))), SIDES)
    assert with_one_more.method == "exchange_mid"


def test_the_pinnacle_tier_is_not_gated_on_distance(monkeypatch):
    """The same pair that is `exchange_far_from_median` as Kalshi anchors as
    Pinnacle: a sharp book disagreeing with the soft median is the SIGNAL, and
    the gap is stamped so the reading can see it."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    as_pinnacle = _resolve_fair(_row(_cells(pinnacle=FAR_PAIR, **NINETEEN_SOFT)), SIDES)
    assert as_pinnacle.method == "sharp_anchor"
    assert as_pinnacle.anchor_refusals == ()
    assert as_pinnacle.anchor_median_gap_pp == pytest.approx(_gap_pp(FAR_PAIR, as_pinnacle.consensus_by_side))
    assert as_pinnacle.anchor_median_gap_pp > 5.0
    as_kalshi = _resolve_fair(_row(_cells(kalshi=FAR_PAIR, **NINETEEN_SOFT)), SIDES)
    assert as_kalshi.anchor_refusal == "exchange_far_from_median"


# -- the stamps ---------------------------------------------------------------


def test_the_refusal_list_is_pinnacle_then_each_exchange_in_priority_order(monkeypatch):
    """Pinnacle wide, betfair wide, kalshi far: three refusals in tier order,
    the single-valued stamps all the FIRST refused pair's (Pinnacle's)."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    row = _row(_cells(pinnacle=PINNACLE_WIDE_PAIR, betfair_ex_eu=WIDE_PAIR, kalshi=FAR_PAIR, **NINETEEN_SOFT))
    resolved = _resolve_fair(row, SIDES)
    assert resolved.method == "consensus"
    assert resolved.anchor_refusals == (
        "sharp_hold_too_wide",
        "exchange_hold_too_wide",
        "exchange_far_from_median",
    )
    assert resolved.anchor_refusal == resolved.anchor_refusals[0]
    assert resolved.anchor_hold_pct == hold_pct(list(PINNACLE_WIDE_PAIR))
    assert resolved.anchor_median_gap_pp == pytest.approx(_gap_pp(PINNACLE_WIDE_PAIR, resolved.consensus_by_side))


def test_both_new_stamps_reach_the_served_quote(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    anchored = build_layer2_rows([_row(_cells(pinnacle=(-125, 115), **SOFT))])["opportunities"]
    passed_over = build_layer2_rows([_row(_cells(pinnacle=PINNACLE_WIDE_PAIR, kalshi=TIGHT_PAIR, **SOFT))])["opportunities"]
    refused = build_layer2_rows([_row(_cells(kalshi=FAR_PAIR, **NINETEEN_SOFT))])["opportunities"]
    assert anchored and passed_over and refused
    for candidate in anchored:
        quote = candidate["quote"]
        assert quote["fair_method"] == "sharp_anchor"
        assert quote["fair_anchor_refusals"] == []
        assert quote["fair_anchor_median_gap_pp"] == pytest.approx(
            abs(quote["fair_probability"] - quote["fair_consensus_prob"]) * 100.0
        )
    for candidate in passed_over:
        quote = candidate["quote"]
        assert quote["fair_method"] == "exchange_mid"
        assert quote["fair_anchor_refusal"] is None
        assert quote["fair_anchor_refusals"] == ["sharp_hold_too_wide"]
        assert quote["fair_anchor_hold_pct"] == hold_pct(list(TIGHT_PAIR))
    for candidate in refused:
        quote = candidate["quote"]
        assert quote["fair_method"] == "consensus"
        assert quote["fair_anchor_refusal"] == "exchange_far_from_median"
        assert quote["fair_anchor_refusals"] == ["exchange_far_from_median"]
        assert quote["fair_anchor_median_gap_pp"] > 3.0
        assert quote["fair_consensus_prob"] == quote["fair_probability"]


def test_an_anchor_mode_row_with_nothing_fresh_carries_an_empty_list_not_none(monkeypatch):
    """None means `median` (no tier ran). An anchor mode that evaluated
    nothing says so with an empty list, so the mode is readable per row."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    soft_only = _resolve_fair(_row(_cells(**SOFT)), SIDES)
    assert soft_only.method == "consensus"
    assert soft_only.anchor_refusals == ()
    assert soft_only.anchor_median_gap_pp is None
    no_cells = _resolve_fair(_row(), SIDES)
    assert no_cells.method == "two_sided_same_book"
    assert no_cells.anchor_refusals == ()
    monkeypatch.delenv(layer2_board.FAIR_ANCHOR_ENV)
    assert _resolve_fair(_row(_cells(**SOFT)), SIDES).anchor_refusals is None


# -- each gate is reachable from the environment: off != on -------------------


def test_sharp_max_hold_env_is_reachable_off_is_not_on(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp_only")
    row = _row(_cells(pinnacle=PINNACLE_WIDE_PAIR, **SOFT))
    assert _resolve_fair(row, SIDES).anchor_refusal == "sharp_hold_too_wide", "absent env must be the 5.0 default"
    monkeypatch.setenv(layer2_board.FAIR_SHARP_MAX_HOLD_PCT_ENV, "8.0")
    assert _resolve_fair(row, SIDES).method == "sharp_anchor"
    monkeypatch.setenv(layer2_board.FAIR_SHARP_MAX_HOLD_PCT_ENV, "garbage")
    assert _resolve_fair(row, SIDES).anchor_refusal == "sharp_hold_too_wide", "unparseable is the default"


def test_sharp_min_books_live_env_is_reachable_off_is_not_on(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp_only")
    row = _with_books(_row(_cells(pinnacle=(-125, 115)), game=LIVE), 1)
    assert _resolve_fair(row, SIDES).anchor_refusal == "sharp_uncorroborated_live"
    monkeypatch.setenv(layer2_board.FAIR_SHARP_MIN_BOOKS_LIVE_ENV, "1")
    assert _resolve_fair(row, SIDES).method == "sharp_anchor"
    monkeypatch.setenv(layer2_board.FAIR_SHARP_MIN_BOOKS_LIVE_ENV, "0")
    assert _resolve_fair(row, SIDES).anchor_refusal == "sharp_uncorroborated_live", "0 is not a count; default"


def test_max_median_gap_env_is_reachable_off_is_not_on(monkeypatch):
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    row = _row(_cells(kalshi=FAR_PAIR, **NINETEEN_SOFT))
    assert _resolve_fair(row, SIDES).anchor_refusal == "exchange_far_from_median", "absent env must be the 3.0 default"
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_ENV, "10")
    assert _resolve_fair(row, SIDES).method == "exchange_mid"
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_ENV, "1.0")
    near = _row(_cells(kalshi=NEAR_PAIR, **NINETEEN_SOFT))
    assert _resolve_fair(near, SIDES).anchor_refusal == "exchange_far_from_median", "tightened, 2 pp is far"
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_ENV, "-3")
    assert _resolve_fair(near, SIDES).method == "exchange_mid", "negative is not a distance; default"


def test_the_p1c_gate_readers_default_on_absent_or_garbage(monkeypatch):
    assert layer2_board._fair_sharp_max_hold_pct() == 5.0
    assert layer2_board._fair_sharp_min_books_live() == 2
    assert layer2_board._fair_exchange_max_median_gap_pp() == 3.0
    monkeypatch.setenv(layer2_board.FAIR_SHARP_MAX_HOLD_PCT_ENV, "-1")
    monkeypatch.setenv(layer2_board.FAIR_SHARP_MIN_BOOKS_LIVE_ENV, "x")
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_ENV, "")
    assert layer2_board._fair_sharp_max_hold_pct() == 5.0
    assert layer2_board._fair_sharp_min_books_live() == 2
    assert layer2_board._fair_exchange_max_median_gap_pp() == 3.0


# -- the three production extremes, reproduced --------------------------------


def test_production_extreme_a_an_in_play_spreads_alt_pinnacle_alone_at_five_point_eight(monkeypatch):
    """00:55Z `sharp_only`: both rows past 5 pp were in-play MLB `spreads_alt`
    with `books=1` -- Pinnacle the lone book on the line -- at a 5.8% hold.
    Under the defaults the corroboration gate names it first (the gates run
    books, then hold, as P1b's do); relax that and the hold cap still stops
    it; only with both relaxed does it anchor. The row's own median is
    Pinnacle's own de-vig, so the stamped gap is ~0 and says nothing -- which
    is exactly why a lone in-play Pinnacle needed a gate that is not distance."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp_only")
    row = _with_books(
        _row(
            _cells(pinnacle=PINNACLE_WIDE_PAIR),
            market="spreads_alt",
            line=-1.5,
            game={"state": "live", "status_token": "Bot 7"},
        ),
        1,
    )
    resolved = _resolve_fair(row, SIDES)
    assert resolved.method == "consensus"
    assert resolved.anchor_refusal == "sharp_uncorroborated_live"
    assert resolved.anchor_refusals == ("sharp_uncorroborated_live",)
    assert 5.0 < resolved.anchor_hold_pct < 6.0
    monkeypatch.setenv(layer2_board.FAIR_SHARP_MIN_BOOKS_LIVE_ENV, "1")
    assert _resolve_fair(row, SIDES).anchor_refusal == "sharp_hold_too_wide"
    monkeypatch.setenv(layer2_board.FAIR_SHARP_MAX_HOLD_PCT_ENV, "8")
    assert _resolve_fair(row, SIDES).method == "sharp_anchor"
    # The same line PREGAME at the same hold is still refused -- by hold alone.
    row["game"] = {"state": "pregame"}
    monkeypatch.delenv(layer2_board.FAIR_SHARP_MIN_BOOKS_LIVE_ENV)
    monkeypatch.delenv(layer2_board.FAIR_SHARP_MAX_HOLD_PCT_ENV)
    assert _resolve_fair(row, SIDES).anchor_refusal == "sharp_hold_too_wide"


def test_production_extreme_b_a_tight_kalshi_pair_three_pp_from_a_nineteen_book_median(monkeypatch):
    """00:04Z `sharp`+P1b: the Kalshi survivors -- hold mean 1.41%, mean |d|
    3.089 pp. Tight but wrong. P1b admitted this pair; P1c's distance gate
    refuses it and stamps the gap it was refused for."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    survivor = (-117, 110)
    assert 1.2 < hold_pct(list(survivor)) < 1.6
    row = _with_books(_row(_cells(kalshi=survivor, **NINETEEN_SOFT)), 20)
    resolved = _resolve_fair(row, SIDES)
    assert 3.0 < resolved.anchor_median_gap_pp < 3.3, resolved.anchor_median_gap_pp
    assert resolved.method == "consensus"
    assert resolved.anchor_refusal == "exchange_far_from_median"
    assert resolved.anchor_hold_pct == hold_pct(list(survivor))
    assert resolved.fair_by_side == resolved.consensus_by_side
    # P1b's gates alone would have let it through -- the distance gate is the
    # discriminator the hold gate was not.
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_ENV, "100")
    assert _resolve_fair(row, SIDES).method == "exchange_mid"


def test_production_extreme_c_a_tight_kalshi_pair_within_one_pp_of_the_median_anchors(monkeypatch):
    """The pair the gates are FOR: a 1.0% hold within 1 pp of a 19-book median
    is a sharper estimate of the same thing, and it anchors."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    close = (-103, -101)
    assert 0.8 < hold_pct(list(close)) < 1.2
    row = _with_books(_row(_cells(kalshi=close, **NINETEEN_SOFT)), 20)
    resolved = _resolve_fair(row, SIDES)
    assert resolved.anchor_median_gap_pp < 1.0
    assert resolved.method == "exchange_mid"
    assert resolved.anchor_book == "kalshi"
    assert resolved.anchor_refusals == ()
    assert resolved.fair_by_side["home"] == devig(list(close), method="power")[0]
    assert resolved.fair_by_side["home"] != resolved.consensus_by_side["home"]
