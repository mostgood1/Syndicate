"""A model edge with no market price behind it must not be ranked.

`_MIN_IMPLIED_BOOK_TOTAL_PCT` refuses a book whose implied total is impossibly
LOW. The opposite failure never reaches that test: both it and `ev_pct` derive
from the fair, and the fair is what is missing, so `_implied_book_total_pct`
reads None and the row ranks on a model edge alone. `_no_market_price` is the
mirror, and these tests pin each clause of it separately -- a predicate whose
clauses are not tested apart is a predicate that can silently widen.
"""

from syndicate.features.shared.layer2_board import _no_market_price


def _row(*, edge=12.5, ev=None, fair=None, top_fair=None):
    row = {"model_edge_pct": edge, "ev_pct": ev, "quote": {}}
    if fair is not None:
        row["quote"]["fair_probability"] = fair
    if top_fair is not None:
        row["fair_probability"] = top_fair
    return row


def test_the_devig_refused_row_is_refused():
    """The shape this exists for: model edge, no fair, no ev."""
    assert _no_market_price(_row(edge=25.65)) is True


def test_a_row_with_a_market_ev_is_KEPT_even_without_a_fair_on_the_quote():
    """`ev_pct` present means something priced it; this rule must not touch it.

    This is the clause that keeps the refusal surgical. On the served board
    3,651 of 3,706 rows carry an `ev_pct`, and not one may be affected.
    """
    assert _no_market_price(_row(ev=4.2)) is False


def test_a_row_with_a_fair_is_KEPT():
    assert _no_market_price(_row(fair=0.52)) is False


def test_a_fair_at_the_TOP_LEVEL_also_keeps_the_row():
    """A candidate mid-build may still hold the fair off `quote`."""
    assert _no_market_price(_row(top_fair=0.52)) is False


def test_a_row_with_NO_model_edge_is_left_to_rows_no_projection():
    """Without this clause the predicate would swallow `no_projection` rows.

    Those carry no opinion at all and are counted separately; stealing them
    would make two different absences read as one.
    """
    assert _no_market_price(_row(edge=None)) is False


def test_neither_an_edge_nor_a_price_is_still_NOT_this_rule():
    assert _no_market_price({"quote": {}}) is False


def test_a_zero_edge_is_a_real_opinion_and_is_refused():
    """0.0 is a number. A truthiness test here would have let it through."""
    assert _no_market_price(_row(edge=0.0)) is True


def test_a_zero_ev_KEEPS_the_row():
    """Same trap on the other side: `ev_pct` 0.0 means it WAS priced."""
    assert _no_market_price(_row(ev=0.0)) is False


def test_a_non_numeric_edge_does_not_fire():
    assert _no_market_price(_row(edge="n/a")) is False


def test_a_non_numeric_ev_is_treated_as_ABSENT_not_as_present():
    """A junk `ev_pct` must not shield a row that has no usable price."""
    assert _no_market_price(_row(edge=9.0, ev="n/a")) is True


def test_a_missing_quote_mapping_is_handled():
    assert _no_market_price({"model_edge_pct": 9.0, "ev_pct": None}) is True


def test_a_non_mapping_quote_is_handled():
    assert _no_market_price(
        {"model_edge_pct": 9.0, "ev_pct": None, "quote": "nonsense"}) is True


def test_the_counter_is_reported_so_the_refusal_is_never_silent():
    """A rule that trims silently is the defect this board already learned once.

    The summary must carry `rows_no_market_price` beside
    `rows_implausible_book`, because the two are one rule read from both ends.
    """
    import inspect

    from syndicate.features.shared import layer2_board

    src = inspect.getsource(layer2_board.select_shortlist)
    assert '"rows_no_market_price": no_market_price' in src
    assert '"rows_implausible_book": implausible_book' in src


def test_the_refusal_sits_in_the_row_loop_and_skips_the_row():
    """It must `continue`, not merely count."""
    import inspect

    from syndicate.features.shared import layer2_board

    src = inspect.getsource(layer2_board.select_shortlist)
    lines = src.splitlines()
    start = next(i for i, l in enumerate(lines)
                 if l.strip() == "if _no_market_price(row):")
    indent = len(lines[start]) - len(lines[start].lstrip())
    # The BLOCK, not a character window: an earlier version of this test
    # asserted `continue` within 220 chars of the `if`, and adding the
    # by-family breakdown pushed it past that. Proximity was never the
    # property worth pinning -- being inside the branch is.
    block = []
    for line in lines[start + 1:]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        block.append(line.strip())
    assert "no_market_price += 1" in block
    assert "continue" in block


def test_the_refusal_is_ATTRIBUTABLE_not_merely_counted():
    """Once live, this refusal REMOVES the rows, so the served board cannot
    show which ones went. A bare count rising would be the only signal, and
    an unattributable refusal is the exact failure this row family took a
    whole session to diagnose. The breakdown is keyed by `sport|market` so a
    future change that costs another market its fair reads as a NEW FAMILY
    rather than as a bigger number.
    """
    import inspect

    from syndicate.features.shared import layer2_board

    src = inspect.getsource(layer2_board.select_shortlist)
    assert "no_market_price_by_family" in src
    assert '"rows_no_market_price_by_family"' in src
    # keyed by sport AND market, not sport alone
    idx = src.index("no_market_price_by_family[_family]")
    window = src[max(0, idx - 400):idx]
    assert 'row.get("sport")' in window
    assert 'row.get("market")' in window


def test_the_family_key_survives_a_missing_sport_or_market():
    """An unknown family must still be counted, never dropped or crashed."""
    import inspect

    from syndicate.features.shared import layer2_board

    src = inspect.getsource(layer2_board.select_shortlist)
    idx = src.index('_family = "%s|%s"')
    window = src[idx:idx + 320]
    assert window.count('or "unknown"') == 2
