"""`fair_unresolved_reason`: a row with no fair says why (lane `fair-price-v2`, handed over by peer lane
`ncaaf-skipped-no-fair` 2026-10-19). Measured that day: 73 NCAAF spreads quoted by Polymarket alone at the same
deep-negative price on both sides (-9900 / -9900, implied sum 1.96) carried `fair_method` None, no anchor refusal
and an empty refusal list -- an unevaluable row that read exactly like an unevaluated one."""
from __future__ import annotations

from typing import Any

from syndicate.features.shared import layer2_board
from syndicate.features.shared.layer2_board import _resolve_fair, build_layer2_rows

SIDES = ["home", "away"]


def _cell(price: int) -> dict[str, Any]:
    return {"price": price, "age_seconds": 30.0, "stale": False}


def _row(cells: dict[str, Any], best_book: str = "polymarket", prices: tuple[int, int] = (-9900, -9900)) -> dict[str, Any]:
    return {
        "sport": "ncaaf", "event_id": "evt1", "kind": "game", "market": "spreads", "segment": "full", "line": -0.5,
        "player_name": None, "home_team": "Home U", "away_team": "Away State",
        "commence_time": "2026-10-24T19:00:00Z", "sides": list(SIDES), "books_quoting": 1,
        "game": {"state": "pregame", "status_token": "2:00P CT"},
        "best": {side: {"price": price, "bookmaker": best_book, "age_seconds": 30.0, "books_quoting": 1}
                 for side, price in zip(SIDES, prices)},
        "cells": cells,
    }


def test_a_lone_degenerate_pair_says_the_devig_refused_it():
    row = _row({"polymarket": {"home": _cell(-9900), "away": _cell(-9900)}})
    got = _resolve_fair(row, SIDES)
    assert got.fair_by_side == {} and got.method is None
    assert got.unresolved_reason == layer2_board.FAIR_UNRESOLVED_DEVIG_REFUSED == "two_sided_devig_refused"


def test_no_book_quoting_both_sides_says_so():
    row = _row({"polymarket": {"home": _cell(-110)}, "draftkings": {"away": _cell(-110)}},
               best_book="draftkings", prices=(-110, -105))
    row["best"]["home"]["bookmaker"] = "polymarket"                # two books: the same-book fallback cannot run
    got = _resolve_fair(row, SIDES)
    assert got.fair_by_side == {} and got.unresolved_reason == "no_two_sided_book"


def test_a_resolved_row_carries_no_reason():
    row = _row({"draftkings": {"home": _cell(-110), "away": _cell(-110)},
                "fanduel": {"home": _cell(-112), "away": _cell(-108)}}, best_book="draftkings", prices=(-110, -110))
    got = _resolve_fair(row, SIDES)
    assert got.method == "consensus" and got.unresolved_reason is None


def test_the_reason_is_stamped_on_every_priced_candidate_and_only_where_there_is_no_fair():
    # Read through the population sink: every candidate, scored or not, as the recorder and the ledger see it. (The 73
    # were also RANKED on the served board, scored by production's projections.)
    degenerate = _row({"polymarket": {"home": _cell(-9900), "away": _cell(-9900)}})
    healthy = dict(_row({"draftkings": {"home": _cell(-110), "away": _cell(100)},
                         "fanduel": {"home": _cell(-112), "away": _cell(102)}}, best_book="draftkings", prices=(-110, 100)),
                   event_id="evt2")
    seen: list[dict[str, Any]] = []
    build_layer2_rows([degenerate, healthy], population_sink=seen.extend)
    quotes = [c["quote"] for c in seen]
    unresolved = [q for q in quotes if q.get("fair_probability") is None]
    resolved = [q for q in quotes if q.get("fair_probability") is not None]
    assert len(unresolved) == 2 and len(resolved) == 2, "the fixture must price both rows' two sides"
    assert {q["fair_unresolved_reason"] for q in unresolved} == {"two_sided_devig_refused"}
    assert {q["fair_unresolved_reason"] for q in resolved} == {None}
