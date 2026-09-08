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


def test_the_pinnacle_tier_is_not_gated_on_hold(monkeypatch):
    """A wide Pinnacle pair still anchors -- the gates are the EXCHANGE tier's."""
    monkeypatch.setenv(layer2_board.FAIR_ANCHOR_ENV, "sharp")
    resolved = _resolve_fair(_row(_cells(pinnacle=WIDE_PAIR, **SOFT)), SIDES)
    assert resolved.method == "sharp_anchor"
    assert resolved.anchor_hold_pct == hold_pct(list(WIDE_PAIR))


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
    # And with the gate relaxed it WOULD have -- the gate, not the pair, is
    # what changed the answer.
    monkeypatch.setenv(layer2_board.FAIR_EXCHANGE_MAX_HOLD_PCT_ENV, "20")
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
