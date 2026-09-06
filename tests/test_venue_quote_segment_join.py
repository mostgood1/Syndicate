"""A segment board row must never take a FULL-GAME venue contract's price.

WHAT THIS PINS, AND WHY IT IS NOT THE GUARD THAT ALREADY EXISTED
--------------------------------------------------------------------------
`kalshi_board_join._segments_agree` guards the ORDER path -- the two
`matches.append` sites `kalshi_ticker_resolver` reads. The board's PRICE comes
from `venue_quote_fanin` instead, and that path had no segment check at all.

Measured on production 2026-09-06 ~16:20Z, `/api/board/layer2-shortlist`:

    segment=first5 market=totals line=4.5 side=over   MIL @ CIN (live)
    price_source=kalshi   book_prices['kalshi'] = -669
    venue_basis.reason = "kalshi at 0.870 plus 0.0080 commission against a
                          7-book consensus"
    consensus_probability = 0.492611     edge_pct = -38.535

Seven books priced the first five at 0.4926. 0.870 is a WHOLE-GAME over 4.5.

THE FIRST TEST IS A REACHABILITY TEST, NOT A CORRECTNESS TEST, and it is first
on purpose (`model_engine_standard.md`: "reachability test before correctness
tests -- `off != on`"). It asserts the defect is REPRODUCIBLE with the guard
bypassed. Without it, every assertion below would pass just as happily against
a join that never paired the two in the first place, and a test that cannot
express the failure cannot witness the fix.
"""

from __future__ import annotations

import json
import time

import pytest

from syndicate.features.shared import venue_quote_fanin as fanin
from syndicate.features.shared.venue_quote_fanin import (
    Quote,
    _segment_disagrees,
    apply_venue_quotes,
    apply_venue_quotes_to_grid,
)


@pytest.fixture
def refusing(monkeypatch):
    """Turn the refusal ON for the tests that are about the refusal.

    `_SEGMENT_REFUSAL_ENABLED` ships **False** by explicit user decision
    ("instrument first, fix second", 2026-09-06): the first deploy MEASURES the
    defect and changes no price, and a second flips the constant. So the
    behaviour tests have to say which stage they are describing, and
    `test_the_shipped_default_counts_without_refusing` pins the other one.

    Forced here rather than left implicit: a suite that passes only because a
    flag happens to be on today is a suite that stops testing the day it is
    turned off, and this one has to survive the flip in BOTH directions.
    """
    monkeypatch.setattr(fanin, "_SEGMENT_REFUSAL_ENABLED", True)

BOOKS = ("draftkings", "fanduel", "betmgm", "caesars", "pointsbet", "betrivers", "bet365")

# Kalshi's own titles, verbatim from the refresh-worker's `[kalshi_odds] TITLE`
# lines on 2026-09-06, so the grammar under test is the venue's and not mine.
F5_CONTRACT = {
    "ticker": "KXMLBF5TOTAL-26SEP061340MILCIN-4",
    "event_ticker": "KXMLBF5TOTAL-26SEP061340MILCIN",
    "series": "KXMLBF5TOTAL",
    "title": "First 5 innings: Over 4.5 runs",
    "yes_ask_dollars": 0.49,
    "no_ask_dollars": 0.53,
}
FULL_GAME_CONTRACT = {
    "ticker": "KXMLBTOTAL-26SEP061340MILCIN-4",
    "event_ticker": "KXMLBTOTAL-26SEP061340MILCIN",
    "series": "KXMLBTOTAL",
    "title": "Full Game: Over 4.5 runs",
    "yes_ask_dollars": 0.870,
    "no_ask_dollars": 0.145,
}


@pytest.fixture
def kalshi_artifact(tmp_path, monkeypatch):
    """Write a real-shaped `kalshi_markets.json` and point the reader at it."""

    def _write(*contracts, fetched_at=None):
        series: dict[str, dict] = {}
        for contract in contracts:
            series.setdefault(contract["series"], {"markets": []})["markets"].append(contract)
        payload = {"fetched_at": fetched_at or time.time(), "series": series}
        root = tmp_path / "reports"
        (root / "intelligence").mkdir(parents=True, exist_ok=True)
        (root / "intelligence" / "kalshi_markets.json").write_text(json.dumps(payload))
        monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(root))
        return payload

    return _write


def _grid_row(segment, market="totals", line=4.5, price=103):
    """A grid row exactly as `book_grid.py` builds one -- `market` and
    `segment` as SEPARATE fields, which is the whole point."""
    cells = {
        book: {
            "over": {"price": price, "line": line},
            "under": {"price": price, "line": line},
        }
        for book in BOOKS
    }
    return {
        "sport": "mlb",
        "kind": "game",
        "event_id": "mlb-2026-09-06-MIL-CIN",
        "segment": segment,
        "market": market,
        "player_name": None,
        "line": line,
        "home_team": "Cincinnati Reds",
        "away_team": "Milwaukee Brewers",
        "commence_time": "2026-09-06T17:40:00Z",
        "sides": ["over", "under"],
        "game": {"state": "live"},
        "cells": cells,
        "best": {
            "over": {
                "price": price,
                "bookmaker": "fanduel",
                "age_seconds": 30.0,
                "books_quoting": len(BOOKS),
            },
            "under": {
                "price": price,
                "bookmaker": "draftkings",
                "age_seconds": 30.0,
                "books_quoting": len(BOOKS),
            },
        },
    }


def _reprice(rows, now=None):
    now = now or time.time()
    return apply_venue_quotes_to_grid(rows, "mlb", "2026-09-06", now=now)


# ---------------------------------------------------------------------------
# 1. REACHABILITY -- the defect is real and this fixture expresses it.
# ---------------------------------------------------------------------------


def test_off_vs_on_the_first5_row_takes_the_full_game_contract_without_the_guard(
    kalshi_artifact, monkeypatch
):
    """OFF: the exact production row is reproduced, ticker and price included.

    Without this the suite could not tell a working guard from a join that
    never pairs the two -- the confound the 2026-09-05 audit named as the one
    thing that made its null meaningful.
    """
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)
    monkeypatch.setattr(fanin, "_segment_disagrees", lambda *a, **k: False)

    row = _grid_row("first5")
    result = _reprice([row])

    over = row["best"]["over"]
    assert over["price_source"] == "kalshi"
    # The production number, to the dollar: 0.870 -> -669.
    assert over["price"] == -669
    assert over["venue_ref"] == "KXMLBTOTAL-26SEP061340MILCIN-4"
    assert result["repriced"] == 2


def test_off_the_under_leg_of_the_same_mis_binding_manufactures_an_edge(
    kalshi_artifact, monkeypatch
):
    """The side production did NOT show is the dangerous one.

    The observed `over` read `edge_pct = -38.5` and ranked nowhere. The `under`
    leg of the same contract is `+590` American against a book consensus of
    0.4926 -- `state_kalshi.md`'s "a mis-keyed join presents as the best line on
    the board", which is how the 2026-08-28 orders came to be selected.
    """
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)
    monkeypatch.setattr(fanin, "_segment_disagrees", lambda *a, **k: False)

    row = _grid_row("first5")
    _reprice([row])

    under = row["best"]["under"]
    assert under["price"] == 590
    assert under["venue_ref"] == "KXMLBTOTAL-26SEP061340MILCIN-4"
    basis = under.get("venue_basis") or {}
    assert basis.get("edge_pct", 0) > 30


# ---------------------------------------------------------------------------
# 2. THE GUARD -- both directions, and what it must NOT cost.
# ---------------------------------------------------------------------------


def test_a_first5_row_refuses_the_full_game_contract(kalshi_artifact, refusing):
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)

    row = _grid_row("first5")
    result = _reprice([row])

    assert row["best"]["over"].get("price_source") is None
    assert row["best"]["over"]["price"] == 103, "the book price must be left alone"
    assert row["best"]["over"].get("venue_ref") is None
    assert result["repriced"] == 0
    assert result["segment_mismatch_detected"] == 2
    assert result["matched_series"] == {}


def test_a_full_game_row_still_takes_the_full_game_contract(kalshi_artifact):
    """THE COVERAGE THIS MUST NOT COST. Every reprice production is doing today
    is on a full-game row against `KXMLBTOTAL`; a guard that also removed those
    would be a regression dressed as a fix."""
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)

    row = _grid_row("full")
    result = _reprice([row])

    assert row["best"]["over"]["price_source"] == "kalshi"
    assert row["best"]["over"]["venue_ref"] == "KXMLBTOTAL-26SEP061340MILCIN-4"
    assert result["repriced"] == 2
    assert result["segment_mismatch_detected"] == 0
    assert result["matched_series"] == {"full|kalshi|KXMLBTOTAL": 2}


def test_a_full_game_row_refuses_a_segment_contract(kalshi_artifact):
    """The mirror case. `kalshi_outcome` keys F5 contracts under the fused
    spelling, so this is already unreachable through the artifact -- asserted
    at the predicate so it stays true if that spelling ever changes."""
    quote = Quote(
        key="mlb|totals|over|4.5",
        source="kalshi",
        sport="mlb",
        market="totals_1st_5_innings",
        side="over",
        probability=0.49,
        american=104,
        line=4.5,
        fetched_at=time.time(),
        venue_ref="KXMLBF5TOTAL-26SEP061340MILCIN-4",
    )
    assert _segment_disagrees("mlb", _grid_row("full"), quote) is True
    assert _segment_disagrees("mlb", _grid_row("first5"), quote) is False


def test_the_defect_spans_polymarket_too(kalshi_artifact, refusing):
    """`polymarket_us_outcome` DROPS every segment contract ("A FIRST-QUARTER
    TOTAL IS NOT A GAME TOTAL"), which protects a full-game row from a segment
    price and does nothing at all for a segment row -- so a first5 row would
    take Polymarket's whole-game total. The 2026-08-28 defect spanned both
    venues; so does this one, and one guard covers both."""
    kalshi_artifact(FULL_GAME_CONTRACT)
    now = time.time()
    collected = {
        "quotes": {
            "mlb|totals|over|4.5": Quote(
                key="mlb|totals|over|4.5",
                source="polymarket_us",
                sport="mlb",
                market="totals",
                side="over",
                probability=0.87,
                american=-669,
                line=4.5,
                fetched_at=now,
                venue_ref="tsc-mlb-mil-cin-2026-09-06-tot-4pt5",
            )
        }
    }
    row = _grid_row("first5")
    result = apply_venue_quotes_to_grid(
        [row], "mlb", "2026-09-06", now=now, collected=collected
    )
    assert row["best"]["over"].get("price_source") is None
    assert result["segment_mismatch_detected"] == 1


def test_an_unsegmented_sport_is_untouched(kalshi_artifact):
    """`split_segment_market_key` is per sport. A sport with no segment
    vocabulary must behave exactly as before rather than start refusing."""
    kalshi_artifact(FULL_GAME_CONTRACT)
    now = time.time()
    collected = {
        "quotes": {
            "ncaab|totals|over|4.5": Quote(
                key="ncaab|totals|over|4.5",
                source="kalshi",
                sport="ncaab",
                market="totals",
                side="over",
                probability=0.55,
                american=-122,
                line=4.5,
                fetched_at=now,
                venue_ref="KXNCAABTOTAL-X-4",
            )
        }
    }
    row = _grid_row("full")
    row["sport"] = "ncaab"
    result = apply_venue_quotes_to_grid(
        [row], "ncaab", "2026-09-06", now=now, collected=collected
    )
    assert row["best"]["over"]["price_source"] == "kalshi"
    assert result["segment_mismatch_detected"] == 0


# ---------------------------------------------------------------------------
# 3. THE OTHER PATH -- `apply_venue_quotes`, guarded by the same helper.
# ---------------------------------------------------------------------------


def test_the_freshness_path_carries_the_same_rule(kalshi_artifact, refusing):
    """`apply_venue_quotes` stamps `last_updated`, which decides the staleness
    gate. Two paths disagreeing about whether a quote may answer a row is a
    join that works on whichever one you happen to read -- the failure `#603`
    already paid for in this module."""
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)
    rows = [
        {"sport": "mlb", "segment": "first5", "market": "totals", "side": "over", "line": 4.5,
         "home_team": "Cincinnati Reds", "away_team": "Milwaukee Brewers"},
        {"sport": "mlb", "segment": "full", "market": "totals", "side": "over", "line": 4.5,
         "home_team": "Cincinnati Reds", "away_team": "Milwaukee Brewers"},
    ]
    result = apply_venue_quotes(rows, "2026-09-06", now=time.time())

    assert result["segment_mismatch_detected"] == 1
    assert result["stamped"] == 1
    assert any("first5" in entry for entry in result["segment_mismatch_sample"])


# ---------------------------------------------------------------------------
# 4. THE INSTRUMENT -- what could not be read off a board row on 2026-09-06.
# ---------------------------------------------------------------------------


def test_the_match_record_names_the_series_behind_every_surviving_price(
    kalshi_artifact, refusing
):
    """`layer2_board`'s quote projection copies a FIXED field list that omits
    `venue_ref`, so no board row has ever carried the contract that priced it.
    This counter is where that answer lives.

    Asserted with the refusal ON, so `matched_series` holds only pairings a
    fixed board would keep. `test_the_match_record_names_a_mis_binding_as_such`
    is the same counter under the SHIPPED default, where the mis-binding
    appears in it by name -- which is the point of measuring first."""
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)
    result = _reprice([_grid_row("full"), _grid_row("first5")])
    assert result["matched_series"] == {"full|kalshi|KXMLBTOTAL": 2}


def test_the_mismatch_sample_names_both_halves_of_the_refused_pairing(
    kalshi_artifact,
):
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)
    result = _reprice([_grid_row("first5")])
    sample = result["segment_mismatch_sample"]
    assert len(sample) == 1, "one distinct shape, not one entry per side"
    assert "mlb|first5|totals|4.5" in sample[0]
    assert "KXMLBTOTAL-26SEP061340MILCIN-4" in sample[0]
    assert "|full|" in sample[0]


# ---------------------------------------------------------------------------
# 5. THE FOLD -- the thing that made the first version of this guard an outage.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spelling", ["full", "full_game", "game", "", None])
def test_every_spelling_of_whole_game_still_takes_a_whole_game_contract(
    kalshi_artifact, spelling
):
    """A REFUSAL THAT REMOVES COVERAGE IS NOT A FIX.

    The first version compared `normalize_segment(...)` against `full`, which
    folds only the empty string -- and 10 tests across `test_venue_basis_wiring`
    and `test_venue_unnamed_quote_ambiguity` build grid rows with
    `segment="full_game"`. That version would have stripped the venue price off
    every whole-game row spelled that way.

    Production writes `full` (`fetch_mlb_oddsapi_local.py:955`, and the ORDER
    path's own unfolded `_segments_agree` matched 545-845 board rows per join on
    2026-09-06, which rows spelled `full_game` could not have done). The synonym
    is folded anyway: the cost of being wrong is asymmetric, and folding can only
    ever refuse less.
    """
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)
    row = _grid_row("full")
    if spelling is None:
        row.pop("segment")
    else:
        row["segment"] = spelling

    result = _reprice([row])

    assert row["best"]["over"]["price_source"] == "kalshi"
    assert result["segment_mismatch_detected"] == 0
    assert result["matched_series"] == {"full|kalshi|KXMLBTOTAL": 2}


def test_a_row_whose_segment_lives_only_in_its_market_name_is_still_a_segment_row(
    kalshi_artifact, refusing
):
    """`segment_for_board_row` is reused for exactly this case: an empty
    `segment` field with the suffix carried by the MARKET name instead. A plain
    field read would call this row full-game and let the defect straight back
    through."""
    kalshi_artifact(FULL_GAME_CONTRACT)
    now = time.time()
    collected = {
        "quotes": {
            "mlb|totals_1st_5_innings|over|4.5": Quote(
                key="mlb|totals_1st_5_innings|over|4.5",
                source="kalshi",
                sport="mlb",
                market="totals",
                side="over",
                probability=0.87,
                american=-669,
                line=4.5,
                fetched_at=now,
                venue_ref="KXMLBTOTAL-26SEP061340MILCIN-4",
            )
        }
    }
    row = _grid_row("", market="totals_1st_5_innings")
    result = apply_venue_quotes_to_grid(
        [row], "mlb", "2026-09-06", now=now, collected=collected
    )
    assert row["best"]["over"].get("price_source") is None
    assert result["segment_mismatch_detected"] == 1


# ---------------------------------------------------------------------------
# 6. THE SHIPPED DEFAULT -- this deploy measures, it does not repair.
# ---------------------------------------------------------------------------


def test_the_shipped_default_counts_without_refusing(kalshi_artifact):
    """`_SEGMENT_REFUSAL_ENABLED` is False as shipped, BY DECISION, and the
    counter must still fire.

    A staged fix has one failure mode worth a test of its own: shipping the
    flag off AND the measurement off, so the deploy that was supposed to size
    the defect returns a zero that reads exactly like a healthy board. That is
    this repo's instrument-blindness failure with an extra step, so the two are
    pinned apart here -- the price is UNCHANGED (still the venue's) and the
    count is NON-ZERO on the same call.
    """
    assert fanin._SEGMENT_REFUSAL_ENABLED is False, (
        "the refusal ships inert; flipping this constant is the SECOND deploy"
    )
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)

    row = _grid_row("first5")
    result = _reprice([row])

    # Still mis-priced -- this commit changes no price.
    assert row["best"]["over"]["price_source"] == "kalshi"
    assert row["best"]["over"]["price"] == -669
    assert row["best"]["over"]["venue_ref"] == "KXMLBTOTAL-26SEP061340MILCIN-4"
    # And now it is COUNTED, and the match record names the mis-binding.
    assert result["segment_mismatch_detected"] == 2
    assert result["segment_refusal_enabled"] is False
    assert result["matched_series"] == {"first5|kalshi|KXMLBTOTAL": 2}


def test_the_match_record_names_a_mis_binding_as_such(kalshi_artifact):
    """`first5|kalshi|KXMLBTOTAL` is the whole finding in one token, and it is
    what the production log will carry on the measuring deploy."""
    kalshi_artifact(F5_CONTRACT, FULL_GAME_CONTRACT)
    result = _reprice([_grid_row("first5"), _grid_row("full")])
    assert result["matched_series"] == {
        "first5|kalshi|KXMLBTOTAL": 2,
        "full|kalshi|KXMLBTOTAL": 2,
    }
