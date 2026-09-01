"""`#617` — Kalshi's own prices reach `book_quotes`, so exchange PROP prices
become visible to anything that reads the quote log.

THE GAP THIS CLOSES, measured rather than assumed. `book_quotes` is fed from
OddsAPI, and OddsAPI carries GAME LINES ONLY for exchanges. On
`mlb_source/tracking/book_quotes/2026-08-31.jsonl` — 274,129 rows, 124.4 MB —
exchange quotes on game markets numbered **26,710** (kalshi 13,768, prophetx
5,605, novig 4,987, polymarket 2,350) and exchange quotes on prop markets
numbered **ZERO**. Kalshi filled 23 real MLB prop orders that same day, with
`KXMLBHR-` / `KXMLBHIT-` / `KXMLBTB-` / `KXMLBHA-` tickers.

WHAT THIS DOES NOT DO. It does not change what the board ranks or stakes. The
board reads `quote.book_prices`, which this does not touch. It makes the prop
side of the price-shopping question MEASURABLE — on game markets, where both
sources are present, adding exchanges improves the best available price on
52.5% of 13,093 paired snapshots by a mean of 1.57pp; whether props behave the
same way cannot be measured until the quotes exist.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.odds_book_quotes import quote_rows_from_kalshi_matches


def _match(**over):
    m = {
        "ticker": "KXMLBHR-26AUG311840SDCIN-SDTFRANCE4-1",
        "series": "KXMLBHR",
        "market": "batter_home_runs",
        "player_name": "Ty France",
        "line": 0.5,
        "board_side": "over",
        "kalshi_side": "yes",
        "kalshi_american": 567,
        "board_event_id": "evt-1",
    }
    m.update(over)
    return m


# ---------------------------------------------------------------------------
# The row builder
# ---------------------------------------------------------------------------


def test_a_prop_match_becomes_a_kalshi_quote_row():
    rows = quote_rows_from_kalshi_matches([_match()])
    assert len(rows) == 1
    row = rows[0]
    assert row["bookmaker"] == "kalshi"
    assert row["market"] == "batter_home_runs"
    assert row["price"] == 567
    assert row["line"] == 0.5
    assert row["selection"] == "over"
    assert row["player_name"] == "Ty France"
    assert row["kind"] == "prop"
    assert row["event_id"] == "evt-1"


def test_the_row_carries_the_contract_it_was_quoted_for():
    """Not part of the quote contract, but it is the only field that makes a
    row traceable back to a specific Kalshi market when one looks wrong."""
    assert quote_rows_from_kalshi_matches([_match()])[0]["venue_ticker"].startswith("KXMLBHR-")


def test_a_GAME_match_is_REFUSED_because_two_sources_would_share_a_dedup_key():
    """THE COLLISION THIS BOUND EXISTS TO PREVENT, and it shipped before it was
    caught. `_KEY_FIELDS` is (sport, kind, event_id, bookmaker, segment, market,
    selection, player_name, line) -- NO source field. So a directly-captured
    Kalshi game row and OddsAPI's copy of the same market share a key, and
    `append_book_quotes` appends whenever (line, price) differs from that key's
    last observation. They do not merge, they ALTERNATE, and every alternation
    reads as a Kalshi price change that never happened.

    Measured on the 2026-08-31 MLB shard: existing Kalshi rows are 13,768 GAME
    and 0 PROP. So props cannot collide and games always would."""
    assert quote_rows_from_kalshi_matches(
        [_match(player_name=None, market="totals", line=8.5)]
    ) == []


def test_a_prop_still_passes_so_the_bound_is_not_a_blanket_refusal():
    """Off is not on: a guard that refused everything would satisfy the test
    above while destroying the entire point of the capture."""
    assert len(quote_rows_from_kalshi_matches([_match()])) == 1


def test_a_match_with_no_price_is_SKIPPED_not_defaulted():
    """A quote with no price records nothing about the market, and a zero would
    be read as an even-money line."""
    assert quote_rows_from_kalshi_matches([_match(kalshi_american=None)]) == []


def test_a_match_with_no_market_is_skipped():
    assert quote_rows_from_kalshi_matches([_match(market="")]) == []


def test_the_BOARD_line_is_kept_not_kalshis_strike():
    """`_match_key`'s docstring: storing the strike instead of the board's
    signed line rebuilds the +X/-X collision. The builder must not re-derive.
    Uses a PROP with a signed line, since game rows are refused above."""
    rows = quote_rows_from_kalshi_matches(
        [_match(market="batter_total_bases", line=1.5, player_name="Nolan Arenado")]
    )
    assert rows[0]["line"] == 1.5


def test_non_mappings_and_empties_do_not_raise():
    assert quote_rows_from_kalshi_matches([]) == []
    assert quote_rows_from_kalshi_matches(None) == []
    assert quote_rows_from_kalshi_matches(["not a mapping", None]) == []


# ---------------------------------------------------------------------------
# The wiring — a builder nothing calls captures nothing
# ---------------------------------------------------------------------------


def _capture(monkeypatch, matches, board_rows, *, date="2026-08-31"):
    """Drive `_capture_kalshi_quotes` with the writer spied, so the assertion is
    on WHAT REACHED THE WRITER rather than on the call returning cleanly."""
    from pipeline import kalshi_odds_refresh as k
    import syndicate.features.shared.odds_book_quotes as obq

    seen: list[dict] = []

    def fake_append(*, sport, date_str, rows, captured_at, publish=True, extra=None):
        seen.append({"sport": sport, "date_str": date_str, "rows": list(rows),
                     "captured_at": captured_at})
        return {"appended": len(list(rows))}

    monkeypatch.setattr(obq, "append_book_quotes", fake_append)
    k._capture_kalshi_quotes({"matches": matches}, board_rows, selected_date=date)
    return seen


def test_OFF_IS_NOT_ON_no_matches_writes_nothing(monkeypatch):
    """Reachability first. If this passed while the loaded case also wrote
    nothing, every other assertion here would be vacuous."""
    assert _capture(monkeypatch, [], [{"event_id": "evt-1", "sport": "mlb"}]) == []


def test_a_matched_prop_reaches_the_writer_under_its_sport(monkeypatch):
    seen = _capture(monkeypatch, [_match()], [{"event_id": "evt-1", "sport": "mlb"}])
    assert len(seen) == 1
    assert seen[0]["sport"] == "mlb"
    assert seen[0]["date_str"] == "2026-08-31"
    assert seen[0]["rows"][0]["bookmaker"] == "kalshi"
    assert seen[0]["rows"][0]["player_name"] == "Ty France"


def test_the_SPORT_comes_from_the_board_row_because_a_match_carries_none(monkeypatch):
    """Verified against the source: neither `matches.append` block in
    `kalshi_board_join` writes a `sport`. Looking it up from the row the match
    paired with keeps one derivation rather than inventing a second."""
    seen = _capture(monkeypatch, [_match(board_event_id="evt-9")],
                    [{"event_id": "evt-9", "sport": "wnba"}])
    assert seen[0]["sport"] == "wnba"


def test_a_match_whose_event_is_not_on_the_board_is_DROPPED_not_guessed(monkeypatch):
    """A quote in the wrong shard is worse than a missing one — it would later
    be read as another sport's price."""
    assert _capture(monkeypatch, [_match(board_event_id="evt-unknown")],
                    [{"event_id": "evt-1", "sport": "mlb"}]) == []


def test_matches_are_split_across_sports(monkeypatch):
    seen = _capture(
        monkeypatch,
        [_match(board_event_id="evt-1"), _match(board_event_id="evt-2")],
        [{"event_id": "evt-1", "sport": "mlb"}, {"event_id": "evt-2", "sport": "wnba"}],
    )
    assert sorted(s["sport"] for s in seen) == ["mlb", "wnba"]


def test_a_writer_failure_never_breaks_the_join(monkeypatch):
    """The quote log is instrumentation; the join is the product. Same contract
    `append_book_quotes` itself keeps."""
    from pipeline import kalshi_odds_refresh as k
    import syndicate.features.shared.odds_book_quotes as obq

    def boom(**kw):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(obq, "append_book_quotes", boom)
    k._capture_kalshi_quotes({"matches": [_match()]},
                             [{"event_id": "evt-1", "sport": "mlb"}],
                             selected_date="2026-08-31")


def test_a_report_with_no_matches_key_is_harmless(monkeypatch):
    from pipeline import kalshi_odds_refresh as k

    k._capture_kalshi_quotes({}, [{"event_id": "evt-1", "sport": "mlb"}], selected_date="2026-08-31")
