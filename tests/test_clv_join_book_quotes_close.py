"""The per-book quote log as a close source, for markets odds history lacks.

Lane `clv-close-from-book-quotes`. NCAAF, WNBA and NFL resolved 0 closes on
2026-09-20 -- every row `no_market_in_history` -- while `odds_book_quotes` held
the same bets, keyed by the opening's own identity fields (wnba 98.9%, nfl 92.0%
exact same-book coverage, read from the production state sidecars).

Quote rows here use the shape `odds_book_quotes._normalize` writes; openings go
through the real `record_openings`, so the join sees what production sees.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

from syndicate.features.shared.clv_join import (
    BOOK_QUOTES_CLOSE_SOURCE,
    _iter_quote_rows,
    compute_clv_for_date,
)

_DATE = "2026-09-20"
_OPEN_AT = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
_KICKOFF = "2026-09-20T17:00:00Z"
_EVENT = "2143ade9684fd876b68a4e8cbf451f05"


def _opening(**over):
    row = {
        "sport": "nfl",
        "event_id": _EVENT,
        "home_team": "Baltimore Ravens",
        "away_team": "Cleveland Browns",
        "market": "spreads",
        "side": "home",
        "line": -6.5,
        "segment": "full",
        "player_name": None,
        "commence_time": _KICKOFF,
        "quote": {"price": -105, "bookmaker": "fanduel"},
    }
    quote = over.pop("quote", None)
    row.update(over)
    if quote is not None:
        row["quote"] = quote
    return row


def _quote(captured_at, price, **over):
    row = {
        "captured_at": captured_at,
        "snapshot_ts": captured_at,
        "sport": "nfl",
        "date": _DATE,
        "kind": "game",
        "event_id": _EVENT,
        "commence_time": _KICKOFF,
        "bookmaker": "fanduel",
        "market": "spreads",
        "segment": "full",
        "selection": "home",
        "player_name": None,
        "line": -6.5,
        "price": price,
    }
    row.update(over)
    return row


def _record(tmp_path, *rows):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(list(rows), date=_DATE, now=_OPEN_AT, root=tmp_path)


def _loader(rows_by_shard, calls=None):
    def load(sport, shard, event_ids):
        if calls is not None:
            calls.append((sport, shard, event_ids))
        if shard not in rows_by_shard:
            return None
        return [row for row in rows_by_shard[shard] if row.get("event_id") in event_ids]
    return load


def _report(tmp_path, rows_by_shard, calls=None):
    return compute_clv_for_date(
        _DATE, "nfl", root=tmp_path, history_payload={"markets": {}},
        quote_rows=_loader(rows_by_shard, calls),
    )


def test_a_market_history_lacks_resolves_from_the_quote_log_same_book(tmp_path):
    """The reachability test: 0 -> 1 on the exact shape that read 0 in production."""
    _record(tmp_path, _opening())
    report = _report(tmp_path, {_DATE: [
        _quote("2026-09-20T13:00:00+00:00", -110),
        _quote("2026-09-20T16:30:00+00:00", -120),   # the close
        _quote("2026-09-20T17:40:00+00:00", +150),   # in-play, never a close
    ]})
    assert report["resolved"] == 1, report["unresolved_reasons"]
    row = report["rows"][0]
    assert row["close_source"] == BOOK_QUOTES_CLOSE_SOURCE
    assert row["close_price"] == -120.0
    assert row["close_book_scope"] == "same_book"
    assert row["close_bookmaker"] == "fanduel"
    assert row["close_timing"] == "pregame"
    assert row["close_age_seconds"] == 1800.0
    assert report["same_book_n"] == 1 and report["avg_clv_pct"] is not None
    assert report["book_quotes_fallback"]["resolved"] == 1


def test_our_own_clock_decides_pregame_not_the_books(tmp_path):
    """Seen by us only after kickoff -> not a close, whatever the book stamp says."""
    _record(tmp_path, _opening())
    late = _quote("2026-09-20T17:05:00+00:00", -120, snapshot_ts="2026-09-20T16:00:00+00:00")
    report = _report(tmp_path, {_DATE: [late]})
    assert report["resolved"] == 0
    assert report["unresolved_reasons"] == {"quotes_no_pregame_quote": 1}


def test_a_different_line_is_a_different_bet(tmp_path):
    _record(tmp_path, _opening())
    report = _report(tmp_path, {_DATE: [_quote("2026-09-20T16:30:00+00:00", -120, line=-7.0)]})
    assert report["resolved"] == 0
    assert report["unresolved_reasons"] == {"quotes_no_matching_quote": 1}


def test_our_price_at_another_book_we_quoted_is_still_same_book(tmp_path):
    """The best book's close is missing; DraftKings' is present and we priced it."""
    _record(tmp_path, _opening(quote={"price": -105, "bookmaker": "prophetx",
                                      "book_prices": {"DraftKings": -112, "fanduel": -110}}))
    report = _report(tmp_path, {_DATE: [
        _quote("2026-09-20T16:30:00+00:00", -125, bookmaker="draftkings"),
        _quote("2026-09-20T16:40:00+00:00", -118, bookmaker="fanduel"),
    ]})
    row = report["rows"][0]
    assert row["close_book_scope"] == "same_book"
    # Sorted, deterministic: draftkings before fanduel.
    assert row["matched_bookmaker"] == "draftkings"
    assert row["open_price"] == -112
    assert row["close_price"] == -125.0


def test_another_books_close_is_used_but_kept_out_of_the_headline(tmp_path):
    _record(tmp_path, _opening(quote={"price": -105, "bookmaker": "prophetx"}))
    report = _report(tmp_path, {_DATE: [
        _quote("2026-09-20T16:10:00+00:00", -115, bookmaker="betmgm"),
        _quote("2026-09-20T16:30:00+00:00", -120, bookmaker="caesars"),
    ]})
    row = report["rows"][0]
    assert row["close_book_scope"] == "different_book_close"
    assert row["close_bookmaker"] == "caesars", "the most recently observed book"
    assert report["same_book_n"] == 0 and report["avg_clv_pct"] is None
    assert report["book_biased_n"] == 1


def test_props_match_on_player_case_insensitively(tmp_path):
    _record(tmp_path, _opening(market="player_reception_yds", side="over", line=52.5,
                               player_name="Luther Burden III",
                               quote={"price": -110, "bookmaker": "draftkings"}))
    report = _report(tmp_path, {_DATE: [
        _quote("2026-09-20T16:30:00+00:00", -130, kind="prop", market="player_reception_yds",
               selection="over", player_name="luther burden iii", line=52.5, bookmaker="draftkings"),
    ]})
    assert report["resolved"] == 1
    assert report["rows"][0]["close_price"] == -130.0


def test_a_segment_bet_takes_only_its_own_segments_close(tmp_path):
    _record(tmp_path, _opening(segment="h1", line=-3.5))
    report = _report(tmp_path, {_DATE: [
        _quote("2026-09-20T16:30:00+00:00", -140, line=-3.5, segment="full"),
        _quote("2026-09-20T16:31:00+00:00", -108, line=-3.5, segment="h1"),
    ]})
    assert report["rows"][0]["close_price"] == -108.0


def test_the_shard_is_the_central_kickoff_date_and_is_read_once(tmp_path):
    """A 7:20 PM CT kickoff is 00:20Z the next day; the shard is the CENTRAL date."""
    late = "2026-09-21T00:20:00Z"
    _record(
        tmp_path,
        _opening(commence_time=late),
        _opening(commence_time=late, side="away", line=6.5, quote={"price": -110, "bookmaker": "fanduel"}),
    )
    calls: list = []
    report = _report(tmp_path, {_DATE: [
        _quote("2026-09-20T23:00:00+00:00", -118, commence_time=late),
        _quote("2026-09-20T23:00:00+00:00", -102, commence_time=late, selection="away", line=6.5),
    ]}, calls)
    assert [call[1] for call in calls] == [_DATE], "one read, keyed by the Central date"
    assert calls[0][2] == frozenset({_EVENT})
    assert report["resolved"] == 2


def test_a_price_unchanged_since_before_the_opening_is_refused_under_its_own_name(tmp_path):
    """Change log: the last change predates the opening. Flat, or pulled -- unknowable."""
    _record(tmp_path, _opening())
    report = _report(tmp_path, {_DATE: [_quote("2026-09-20T11:00:00+00:00", -105)]})
    assert report["resolved"] == 0
    assert report["unresolved_reasons"] == {"quotes_unchanged_since_open": 1}


def test_a_missing_shard_and_a_missing_kickoff_are_named(tmp_path):
    _record(tmp_path, _opening(), _opening(event_id="no-kickoff", commence_time=None))
    report = _report(tmp_path, {})
    assert report["unresolved_reasons"] == {"quotes_shard_absent": 1, "quotes_no_kickoff_time": 1}


def test_a_read_that_fails_midway_is_discarded_not_used(tmp_path):
    """A truncated read would make an EARLIER price look like the close."""
    _record(tmp_path, _opening())

    def load(sport, shard, event_ids):
        def rows():
            yield _quote("2026-09-20T13:00:00+00:00", -110)
            raise OSError("disk went away")
        return rows()

    report = compute_clv_for_date(_DATE, "nfl", root=tmp_path, history_payload={"markets": {}},
                                  quote_rows=load)
    assert report["resolved"] == 0
    assert report["unresolved_reasons"] == {"quotes_read_error": 1}
    assert _DATE in report["book_quotes_fallback"]["shards_failed"]


def test_a_history_resolved_row_is_untouched_and_the_log_is_not_read(tmp_path):
    """B3's predicate: history wins where it has the market, byte for byte."""
    opening = _opening(sport="mlb", market="h2h", side="home", line=None,
                       quote={"price": -120, "bookmaker": "betmgm"})
    _record(tmp_path, opening)
    key = (f"event_id={_EVENT}|home_team=Baltimore Ravens|away_team=Cleveland Browns"
           "|market=h2h|bookmaker=betmgm")
    payload = {"markets": {key: {"history": [{
        "captured_at": "2026-09-20T16:00:00+00:00", "entity": "Baltimore Ravens",
        "last_odds": -150.0, "line": {"home_odds": "-150", "away_odds": "+118"},
    }], "closing_price": None, "closing_line": None}}}

    without = compute_clv_for_date(_DATE, "mlb", root=tmp_path, history_payload=payload)
    calls: list = []
    with_log = compute_clv_for_date(
        _DATE, "mlb", root=tmp_path, history_payload=payload,
        quote_rows=_loader({_DATE: [_quote("2026-09-20T16:30:00+00:00", -999, sport="mlb",
                                           market="h2h", line=None, bookmaker="betmgm")]}, calls),
    )
    assert with_log["rows"] == without["rows"]
    assert with_log["rows"][0]["close_source"] == "last_pregame_quote"
    assert calls == [], "nothing was pending, so the quote log must not be read"


def test_an_injected_history_without_a_loader_never_reads_the_disk(tmp_path, monkeypatch):
    import syndicate.features.shared.clv_join as clv_join

    def boom(*args, **kwargs):
        raise AssertionError("read production quote shards during an injected-history call")

    monkeypatch.setattr(clv_join, "read_quote_rows_for_events", boom)
    _record(tmp_path, _opening())
    report = compute_clv_for_date(_DATE, "nfl", root=tmp_path, history_payload={"markets": {}})
    assert report["unresolved_reasons"] == {"no_market_in_history": 1}
    assert report["book_quotes_fallback"]["skipped"] == "history_payload_injected"


def test_the_default_reader_streams_plain_and_gzip_and_parses_only_wanted_events(tmp_path):
    rows = [
        _quote("2026-09-20T16:30:00+00:00", -120),
        _quote("2026-09-20T16:30:00+00:00", -110, event_id="someone-else"),
    ]
    text = "".join(json.dumps(row) + "\n" for row in rows) + "not json at all\n"
    plain = tmp_path / f"{_DATE}.jsonl"
    plain.write_text(text, encoding="utf-8")
    packed = tmp_path / f"{_DATE}.jsonl.gz"
    with gzip.open(packed, "wt", encoding="utf-8") as handle:
        handle.write(text)

    for path in (plain, packed):
        got = list(_iter_quote_rows(path, frozenset({_EVENT})))
        assert [row["event_id"] for row in got] == [_EVENT], path.name
