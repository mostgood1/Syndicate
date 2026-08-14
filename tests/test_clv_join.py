"""Pairing an opening to a close must never guess which side it read.

Lane `clv-without-settlement`, audit §7 ranked fix #1, joiner half.

Shapes here are copied from the real 2026-08-14 payload, not invented:
    props  `player_name=<lower>|market=<m>|selection=<over|under>`, no bookmaker
    game   `event_id|home_team|away_team|market|bookmaker`, no side
    every point has `current_odds: None`; the price is in `last_odds` and `line`
    game points carry BOTH sides as `{"home_odds": "-150", "away_odds": "+118"}`
"""

from __future__ import annotations

from syndicate.features.shared.clv_join import (
    clv_pct_from_prices,
    compute_clv_for_date,
    resolve_close,
)


def _game_opening(**over):
    row = {
        "sport": "mlb",
        "event_id": "2124d4bb5569819a30020e5b907ca202",
        "home_team": "Cincinnati Reds",
        "away_team": "Miami Marlins",
        "market": "h2h",
        "side": "home",
        "bookmaker": "betmgm",
        "price": -120,
        "commence_time": "2026-08-14T23:00:00Z",
        "player_name": None,
    }
    row.update(over)
    return row


def _point(captured_at, **over):
    point = {
        "captured_at": captured_at,
        "entity": "Cincinnati Reds",
        "last_odds": -150.0,
        "line": {"home_odds": "-150", "away_odds": "+118"},
    }
    point.update(over)
    return point


def _state(points, **over):
    state = {"history": list(points), "closing_price": None, "closing_line": None}
    state.update(over)
    return state


def test_the_close_is_the_last_observation_before_kickoff():
    state = _state([
        _point("2026-08-14T18:00:00+00:00", line={"home_odds": "-105", "away_odds": "-115"}),
        _point("2026-08-14T22:30:00+00:00", line={"home_odds": "-150", "away_odds": "+118"}),
    ])
    out = resolve_close(_game_opening(), state)
    assert out["close_price"] == -150.0
    assert out["close_source"] == "last_pregame_quote"
    assert out["close_age_seconds"] == 1800.0


def test_an_observation_after_kickoff_is_not_a_close():
    """A live price is not a closing price."""
    state = _state([_point("2026-08-14T23:30:00+00:00")])
    out = resolve_close(_game_opening(), state)
    assert out["close_price"] is None
    assert out["unresolved_reason"] == "no_pregame_observation"


def test_a_stamped_transition_wins_and_is_labelled_as_such():
    state = _state([_point("2026-08-14T22:30:00+00:00")],
                   closing_price=-140.0, closing_captured_at="2026-08-14T22:55:00Z")
    out = resolve_close(_game_opening(), state)
    assert out["close_price"] == -140.0
    assert out["close_source"] == "observed_transition"
    assert out["close_age_seconds"] == 300.0


def test_the_away_side_gets_the_away_price_not_the_entitys():
    """The bug this ordering exists to prevent.

    `entity` is the home team and `last_odds` is the home price. Reading
    `last_odds` first would hand -150 to the away row -- a wrong number, which
    is worse than a missing one.
    """
    out = resolve_close(_game_opening(side="away", price=110), _state([_point("2026-08-14T22:30:00+00:00")]))
    assert out["close_price"] == 118.0, "away row was given the home team's closing price"


def test_a_game_close_is_marked_same_book():
    out = resolve_close(_game_opening(), _state([_point("2026-08-14T22:30:00+00:00")]))
    assert out["close_book_scope"] == "same_book"


def test_a_prop_close_is_marked_book_agnostic():
    """Prop keys carry no bookmaker, so the close is market-wide. Say so."""
    opening = _game_opening(player_name="A.J. Ewing", market="batter_hits",
                            side="over", line=0.5, price=145)
    state = _state([_point("2026-08-14T22:30:00+00:00", entity="a.j. ewing",
                           last_odds=-125.0, line={"line": 0.5, "price": "-125"})])
    out = resolve_close(opening, state)
    assert out["close_price"] == -125.0
    assert out["close_book_scope"] == "book_agnostic_close"


def test_a_props_closing_line_is_never_read_as_a_price():
    """`closing_line: 1.5` on a total-bases prop is a LINE.

    Trusting it would fabricate a +150 closing price out of a 1.5 line.
    """
    opening = _game_opening(player_name="A.J. Ewing", market="batter_total_bases",
                            side="over", line=1.5, price=155)
    state = _state([_point("2026-08-14T22:30:00+00:00", entity="a.j. ewing",
                           last_odds=-125.0, line={"line": 1.5, "price": "-125"})],
                   closing_line=1.5)
    out = resolve_close(opening, state)
    assert out["close_price"] == -125.0, "the 1.5 LINE was used as a closing PRICE"
    assert out["close_source"] == "last_pregame_quote"


def test_a_mismatched_player_is_refused_not_guessed():
    opening = _game_opening(player_name="Someone Else", market="batter_hits", side="over", price=145)
    state = _state([_point("2026-08-14T22:30:00+00:00", entity="a.j. ewing",
                           last_odds=-125.0, line={})])
    out = resolve_close(opening, state)
    assert out["close_price"] is None
    assert out["unresolved_reason"] == "entity_player_mismatch"


def test_a_missing_market_is_a_named_reason():
    out = resolve_close(_game_opening(), None)
    assert out["unresolved_reason"] == "no_market_in_history"


def test_clv_sign_convention_matches_the_ledger():
    assert clv_pct_from_prices(-110, -130) > 0   # market moved toward us
    assert clv_pct_from_prices(-130, -110) < 0
    assert clv_pct_from_prices(-110, None) is None


def test_compute_pairs_openings_and_reports_every_unresolved_reason(tmp_path):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    rows = [
        {**_game_opening(), "quote": {"price": -120, "bookmaker": "betmgm"}, "line": None},
        {**_game_opening(side="away"), "quote": {"price": 110, "bookmaker": "betmgm"}, "line": None},
    ]
    record_openings(rows, date="2026-08-14", root=tmp_path)

    key = ("event_id=2124d4bb5569819a30020e5b907ca202|home_team=Cincinnati Reds|"
           "away_team=Miami Marlins|market=h2h|bookmaker=betmgm")
    payload = {"markets": {key: _state([_point("2026-08-14T22:30:00+00:00")])}}

    report = compute_clv_for_date("2026-08-14", "mlb", root=tmp_path, history_payload=payload)
    assert report["openings"] == 2
    assert report["resolved"] == 2
    assert report["by_close_source"] == {"last_pregame_quote": 2}
    assert report["avg_clv_pct"] is not None
    sides = {r["side"]: r["close_price"] for r in report["rows"]}
    assert sides == {"home": -150.0, "away": 118.0}


def test_an_opening_with_no_matching_market_is_counted_not_dropped(tmp_path):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings([{**_game_opening(), "quote": {"price": -120, "bookmaker": "betmgm"}, "line": None}],
                    date="2026-08-14", root=tmp_path)
    report = compute_clv_for_date("2026-08-14", "mlb", root=tmp_path, history_payload={"markets": {}})
    assert report["resolved"] == 0
    assert report["unresolved_reasons"] == {"no_market_in_history": 1}


def test_a_different_books_close_is_used_but_labelled(tmp_path):
    """41% of real openings were lost to this before it existed.

    The board publishes the BEST price (often polymarket/prophetx/betfair_ex);
    odds history tracks mainstream books. Same event, same market, different
    book is a real CLV signal -- but it is not same-book, and it says so.
    """
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(
        [{**_game_opening(bookmaker="polymarket"),
          "quote": {"price": -120, "bookmaker": "polymarket"}, "line": None}],
        date="2026-08-14", root=tmp_path,
    )
    other_book = ("event_id=2124d4bb5569819a30020e5b907ca202|home_team=Cincinnati Reds|"
                  "away_team=Miami Marlins|market=h2h|bookmaker=fanduel")
    report = compute_clv_for_date(
        "2026-08-14", "mlb", root=tmp_path,
        history_payload={"markets": {other_book: _state([_point("2026-08-14T22:30:00+00:00")])}},
    )
    assert report["resolved"] == 1
    assert report["rows"][0]["close_book_scope"] == "different_book_close"
    assert report["rows"][0]["close_price"] == -150.0


def test_the_fallback_never_crosses_events_or_markets(tmp_path):
    """A close from a different GAME is not a fallback, it is a wrong number."""
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(
        [{**_game_opening(bookmaker="polymarket"),
          "quote": {"price": -120, "bookmaker": "polymarket"}, "line": None}],
        date="2026-08-14", root=tmp_path,
    )
    wrong_event = ("event_id=DIFFERENT|home_team=Chicago Cubs|away_team=St. Louis Cardinals|"
                   "market=h2h|bookmaker=fanduel")
    wrong_market = ("event_id=2124d4bb5569819a30020e5b907ca202|home_team=Cincinnati Reds|"
                    "away_team=Miami Marlins|market=totals|bookmaker=fanduel")
    report = compute_clv_for_date(
        "2026-08-14", "mlb", root=tmp_path,
        history_payload={"markets": {
            wrong_event: _state([_point("2026-08-14T22:30:00+00:00")]),
            wrong_market: _state([_point("2026-08-14T22:30:00+00:00")]),
        }},
    )
    assert report["resolved"] == 0
    assert report["unresolved_reasons"] == {"no_market_in_history": 1}


def test_a_same_book_close_is_still_preferred_when_it_exists(tmp_path):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(
        [{**_game_opening(bookmaker="betmgm"),
          "quote": {"price": -120, "bookmaker": "betmgm"}, "line": None}],
        date="2026-08-14", root=tmp_path,
    )
    same = ("event_id=2124d4bb5569819a30020e5b907ca202|home_team=Cincinnati Reds|"
            "away_team=Miami Marlins|market=h2h|bookmaker=betmgm")
    other = ("event_id=2124d4bb5569819a30020e5b907ca202|home_team=Cincinnati Reds|"
             "away_team=Miami Marlins|market=h2h|bookmaker=fanduel")
    report = compute_clv_for_date(
        "2026-08-14", "mlb", root=tmp_path,
        history_payload={"markets": {
            same: _state([_point("2026-08-14T22:30:00+00:00", line={"home_odds": "-150", "away_odds": "+118"})]),
            other: _state([_point("2026-08-14T22:30:00+00:00", line={"home_odds": "-200", "away_odds": "+170"})]),
        }},
    )
    assert report["rows"][0]["close_book_scope"] == "same_book"
    assert report["rows"][0]["close_price"] == -150.0


def test_the_headline_clv_excludes_book_biased_rows(tmp_path):
    """The most flattering wrong number this repo could produce.

    Our opening is the best price across books; another book's close is a
    single draw. That comparison is biased upward regardless of the bet --
    measured at +6.2 pts and a 91% beat rate on 32 real rows. It must never
    reach `avg_clv_pct`.
    """
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(
        [{**_game_opening(bookmaker="polymarket"),
          "quote": {"price": -120, "bookmaker": "polymarket"}, "line": None}],
        date="2026-08-14", root=tmp_path,
    )
    other = ("event_id=2124d4bb5569819a30020e5b907ca202|home_team=Cincinnati Reds|"
             "away_team=Miami Marlins|market=h2h|bookmaker=fanduel")
    report = compute_clv_for_date(
        "2026-08-14", "mlb", root=tmp_path,
        history_payload={"markets": {other: _state([_point("2026-08-14T22:30:00+00:00")])}},
    )
    assert report["resolved"] == 1
    assert report["same_book_n"] == 0
    assert report["book_biased_n"] == 1
    assert report["avg_clv_pct"] is None, "a book-biased row reached the headline number"
    assert report["by_book_scope"]["different_book_close"]["n"] == 1
    assert report["by_book_scope"]["different_book_close"]["avg_clv_pct"] is not None


def test_a_same_book_row_does_reach_the_headline(tmp_path):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(
        [{**_game_opening(bookmaker="betmgm"),
          "quote": {"price": -120, "bookmaker": "betmgm"}, "line": None}],
        date="2026-08-14", root=tmp_path,
    )
    same = ("event_id=2124d4bb5569819a30020e5b907ca202|home_team=Cincinnati Reds|"
            "away_team=Miami Marlins|market=h2h|bookmaker=betmgm")
    report = compute_clv_for_date(
        "2026-08-14", "mlb", root=tmp_path,
        history_payload={"markets": {same: _state([_point("2026-08-14T22:30:00+00:00")])}},
    )
    assert report["same_book_n"] == 1
    assert report["avg_clv_pct"] is not None


def test_a_same_book_pair_is_preferred_and_uses_that_books_own_opening(tmp_path):
    """The whole point of recording `book_prices`.

    History keeps a median of 2 books per (event, market); the board publishes
    the best of ~13. Our price AT the tracked book, against THAT book's close,
    is the only pairing free of the best-of-N selection effect.
    """
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(
        [{**_game_opening(bookmaker="polymarket"),
          "quote": {"price": -120, "bookmaker": "polymarket",
                    "book_prices": {"polymarket": -120, "fanduel": -135}},
          "line": None}],
        date="2026-08-14", root=tmp_path,
    )
    tracked = ("event_id=2124d4bb5569819a30020e5b907ca202|home_team=Cincinnati Reds|"
               "away_team=Miami Marlins|market=h2h|bookmaker=fanduel")
    report = compute_clv_for_date(
        "2026-08-14", "mlb", root=tmp_path,
        history_payload={"markets": {tracked: _state([_point("2026-08-14T22:30:00+00:00")])}},
    )
    row = report["rows"][0]
    assert row["close_book_scope"] == "same_book"
    assert row["matched_bookmaker"] == "fanduel"
    assert row["open_price"] == -135, "used the best-book price, not fanduel's own opening"
    assert row["open_price_best_book"] == -120
    assert report["avg_clv_pct"] is not None, "a genuine same-book pair must reach the headline"


def test_without_our_price_at_that_book_it_stays_a_biased_fallback(tmp_path):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(
        [{**_game_opening(bookmaker="polymarket"),
          "quote": {"price": -120, "bookmaker": "polymarket",
                    "book_prices": {"polymarket": -120}},
          "line": None}],
        date="2026-08-14", root=tmp_path,
    )
    tracked = ("event_id=2124d4bb5569819a30020e5b907ca202|home_team=Cincinnati Reds|"
               "away_team=Miami Marlins|market=h2h|bookmaker=fanduel")
    report = compute_clv_for_date(
        "2026-08-14", "mlb", root=tmp_path,
        history_payload={"markets": {tracked: _state([_point("2026-08-14T22:30:00+00:00")])}},
    )
    assert report["rows"][0]["close_book_scope"] == "different_book_close"
    assert report["avg_clv_pct"] is None
