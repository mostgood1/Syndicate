"""The per-line `suggested` flag (lane `layer2-suggested-opps`).

Every criterion is a property of the LINE; nothing is removed -- the flag only labels.
"""
from __future__ import annotations

from syndicate.features.shared import layer2_board as lb
from syndicate.features.shared.opportunity_population_ledger import population_record


def _row(**over) -> dict:
    row = {
        "sport": "ncaaf", "kind": "game", "event_id": "e1", "market": "totals", "segment": "full",
        "side": "over", "line": 52.5, "board_lane": "opportunity", "ev_pct": 3.1,
        "quote": {"fair_method": "consensus", "suspect_stale": False, "price": 105, "bookmaker": "fanduel",
                  "books_quoting": 4},
        "score_v2": {"fee_basis": "none", "ev_net_pct": 3.1},
    }
    row.update(over)
    return row


def test_a_two_sided_plus_ev_line_is_suggested() -> None:
    row = _row()
    assert lb._stamp_suggested([row]) == {"ncaaf": 1}
    assert row["suggested"] is True and row["suggested_reasons"] == []


def test_each_failed_line_property_is_named() -> None:
    cases = {
        "ev_below_min": _row(ev_pct=1.9),
        "no_market_ev": _row(ev_pct=None),
        "one_sided_fair": _row(quote={"fair_method": "book_margin_model", "books_quoting": 4}),
        "no_fair_method": _row(quote={"books_quoting": 4}),
        "suspect_stale_quote": _row(quote={"fair_method": "consensus", "suspect_stale": True, "books_quoting": 4}),
        "single_book_fair": _row(quote={"fair_method": "consensus", "bookmaker": "kalshi", "books_quoting": 1}),
        "books_quoting_unknown": _row(quote={"fair_method": "consensus", "bookmaker": "fanduel"}),
        "not_opportunity_lane": _row(board_lane="dead"),
        "implausible_book": _row(ev_pct=40.0, score_v2={"fee_basis": "none", "ev_net_pct": 40.0}),
        "ev_net_of_fee_below_min": _row(score_v2={"fee_basis": "kalshi_series", "ev_net_pct": 1.2}),
    }
    for reason, row in cases.items():
        lb._stamp_suggested([row])
        assert row["suggested"] is False, reason
        assert reason in row["suggested_reasons"], (reason, row["suggested_reasons"])


def test_one_side_per_line_keeps_the_higher_net_ev() -> None:
    over = _row(side="over", ev_pct=2.5, score_v2={"fee_basis": "none", "ev_net_pct": 2.5})
    under = _row(side="under", ev_pct=3.4, score_v2={"fee_basis": "none", "ev_net_pct": 3.4})
    spread_home = _row(market="spreads", side="home", line=-3.5)
    spread_away = _row(market="spreads", side="away", line=3.5, ev_pct=2.2,
                       score_v2={"fee_basis": "none", "ev_net_pct": 2.2})
    rows = [over, under, spread_home, spread_away]
    assert lb._stamp_suggested(rows) == {"ncaaf": 2}
    assert (over["suggested"], under["suggested"]) == (False, True)
    assert over["suggested_reasons"] == ["other_side_suggested"]
    assert (spread_home["suggested"], spread_away["suggested"]) == (True, False)


def test_threshold_is_a_setting(monkeypatch) -> None:
    monkeypatch.setenv("SYNDICATE_SUGGESTED_MIN_EV_PCT", "3.5")
    row = _row()
    lb._stamp_suggested([row])
    assert row["suggested"] is False and row["suggested_reasons"] == ["ev_below_min"]


def test_flag_reaches_the_recorder() -> None:
    row = _row()
    lb._stamp_suggested([row])
    record = population_record(row, "k", "2026-10-13T00:00:00Z", sport="ncaaf")
    assert record["sg"] is True
    assert population_record({"quote": {}}, "k", "2026-10-13T00:00:00Z", sport="ncaaf")["sg"] is None


def test_paper_book_stakes_only_suggested_rows() -> None:
    from pipeline.portfolio_commit import suggested_rows

    kept, gate = suggested_rows([{"suggested": True, "id": 1}, {"suggested": False}, {"no": "flag"}, "junk"])
    assert [row["id"] for row in kept] == [1]
    assert gate == {"rows_in": 4, "suggested": 1, "not_suggested": 1, "flag_absent": 2}


def test_board_template_offers_all_and_suggested_with_all_default() -> None:
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "intelligence.html").read_text(encoding="utf-8")
    assert 'id="board-suggested-tabs"' in html
    assert 'suggestedOnly: urlParams.get("opps") === "suggested"' in html   # default All: only the param turns it on
    assert "if (state.suggestedOnly && item.suggested !== true) return false;" in html


def test_a_fair_anchored_on_a_different_book_is_two_venues_and_stays_eligible() -> None:
    # User 2026-10-16 "Block them": no pick unless the fair comes from 2+ books. A sharp anchor (fair from
    # Pinnacle, price at FanDuel) is two venues; a venue priced against its own de-vig is one.
    anchored = _row(quote={"fair_method": "consensus", "bookmaker": "fanduel", "books_quoting": 1,
                           "fair_anchor_book": "pinnacle"})
    self_priced = _row(quote={"fair_method": "consensus", "bookmaker": "kalshi", "books_quoting": 1,
                              "fair_anchor_book": "kalshi"})
    lb._stamp_suggested([anchored])
    lb._stamp_suggested([self_priced])
    assert anchored["suggested"] is True
    assert self_priced["suggested"] is False and "single_book_fair" in self_priced["suggested_reasons"]
