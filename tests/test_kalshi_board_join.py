"""Matching a Kalshi market to the board row for the same bet.

#505 is the cautionary case: the settlement join matched on an id that changed
whenever the price moved and reported 4,560 no_key_match of 8,276. So these
tests are weighted toward the ways a join produces a CONFIDENT WRONG MATCH
rather than an obvious failure.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.kalshi_board_join import (
    REASON_NO_BOARD_ROW,
    REASON_COMBINATORIAL,
    REASON_UNMAPPED_SERIES,
    REASON_UNREADABLE_TITLE,
    join_kalshi_to_board,
    normalize_person,
)


# --- the half-point convention --------------------------------------------


def test_names_normalise_across_accents_and_punctuation():
    """Feeds disagree on accents and suffixes; a period must not decide whether
    a bet matches."""
    assert normalize_person("José Ramírez") == normalize_person("Jose Ramirez")
    assert normalize_person("Ronald Acuña Jr.") == normalize_person("Ronald Acuna Jr")


def _kalshi(title="Andrew Abbott: 7+ strikeouts?", series="KXMLBKS", **kw):
    market = {
        # THE GAME DATE LIVES HERE, and this fixture is shaped like the real
        # thing for that reason: `KXMLBKS-26AUG242140MINATH-MINZMATTHEWS52-8`,
        # measured in production 2026-08-23T23:51Z. Until 2026-08-24 these
        # tests passed a date via `close_time` and the join read it there --
        # which is why a suite this size stayed green while production matched
        # ZERO markets for hours.
        "ticker": "KXMLBKS-26AUG22ABBOTT-7",
        "series": series,
        "title": title,
        "yes_american": -120,
        "no_american": 105,
        "yes_probability": 0.545,
        "no_probability": 0.488,
    }
    market.update(kw)
    return market


def _row(side="Over", line=6.5, market="pitcher_strikeouts", player="Andrew Abbott", **kw):
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": market,
        "player_name": player,
        "line": line,
        "side": side,
        "model_edge_pct": 2.0,
        "quote": {"bookmaker": "draftkings", "price": -110},
    }
    row.update(kw)
    return row


def test_a_matching_bet_pairs_over_with_YES():
    report = join_kalshi_to_board([_kalshi()], [_row(side="Over")])
    assert report["matched"] == 1
    match = report["matches"][0]
    assert match["kalshi_side"] == "yes"
    assert match["kalshi_american"] == -120
    assert match["line"] == 6.5


def test_under_pairs_with_NO_and_takes_NOs_own_price():
    """yes and no are separately quoted and do not sum to 1 — the gap is the
    spread. Deriving one from the other would invent edge."""
    report = join_kalshi_to_board([_kalshi()], [_row(side="Under")])
    match = report["matches"][0]
    assert match["kalshi_side"] == "no"
    assert match["kalshi_american"] == 105


def test_both_sides_of_one_market_match_independently():
    report = join_kalshi_to_board([_kalshi()], [_row(side="Over"), _row(side="Under")])
    assert report["matched"] == 2
    assert {m["kalshi_american"] for m in report["matches"]} == {-120, 105}


def test_a_line_that_does_not_correspond_does_not_match():
    """The half-point test again, through the join: 7+ must not pair with 7.5."""
    report = join_kalshi_to_board([_kalshi()], [_row(line=7.5)])
    assert report["matched"] == 0
    assert report["reasons"][REASON_NO_BOARD_ROW] == 1


def test_a_different_player_does_not_match():
    report = join_kalshi_to_board([_kalshi()], [_row(player="Shane Baz")])
    assert report["matched"] == 0


def test_a_different_market_family_does_not_match():
    """A strikeouts market must never pair with an outs row at the same number."""
    report = join_kalshi_to_board([_kalshi()], [_row(market="pitcher_outs")])
    assert report["matched"] == 0


def test_parlay_markets_are_refused_by_name():
    report = join_kalshi_to_board(
        [_kalshi(series="KXMVECROSSCATEGORY", title="yes Tampa Bay,yes Shane Baz: 2+")],
        [_row()],
    )
    assert report["reasons"][REASON_COMBINATORIAL] == 1


def test_an_unparseable_title_is_named_separately_from_a_missing_row():
    """'We could not read this market' and 'Kalshi has nothing we bet' are
    different facts and must not share a counter."""
    report = join_kalshi_to_board([_kalshi(title="Will over 8.5 goals be scored?")], [_row()])
    assert report["reasons"][REASON_UNREADABLE_TITLE] == 1
    assert REASON_NO_BOARD_ROW not in report["reasons"]


def test_accented_names_still_join():
    report = join_kalshi_to_board(
        [_kalshi(title="José Ramírez: 3+ strikeouts?")],
        [_row(player="Jose Ramirez", line=2.5)],
    )
    assert report["matched"] == 1


def test_every_market_is_accounted_for():
    """matched + refusals == markets in, or the join is not a measurement."""
    markets = [_kalshi(), _kalshi(series="KXMVECROSSCATEGORY"), _kalshi(title="junk")]
    report = join_kalshi_to_board(markets, [_row()])
    assert report["matched"] + sum(report["reasons"].values()) == len(markets)


def test_the_price_resolver_is_keyed_as_tightly_as_the_join():
    """A resolver looser than the join would silently reintroduce exactly the
    mismatches the join refuses."""
    from syndicate.features.shared.kalshi_board_join import kalshi_price_resolver

    resolve = kalshi_price_resolver([{
        "market": "pitcher_strikeouts", "player_name": "Andrew Abbott",
        "line": 6.5, "board_side": "over", "kalshi_american": -120,
    }])
    assert resolve(_row(side="Over", line=6.5)) == -120
    # Every one of these is a different bet and must not resolve.
    assert resolve(_row(side="Under", line=6.5)) is None
    assert resolve(_row(side="Over", line=7.5)) is None
    assert resolve(_row(side="Over", line=6.5, player="Shane Baz")) is None
    assert resolve(_row(side="Over", line=6.5, market="pitcher_outs")) is None


# --- the join must stay inside one slate -----------------------------------


def test_a_market_for_another_date_is_refused():
    """MEASURED 2026-08-23T04:22Z: Kalshi was quoting tomorrow's MLB while the
    board had rolled to European soccer. Nothing matched — correct, but only by
    luck that the vocabularies did not overlap. A pitcher with the same line on
    two different days WOULD have matched the wrong game."""
    from syndicate.features.shared.kalshi_board_join import REASON_WOULD_MATCH_WRONG_DATE

    market = _kalshi(
        title="Lake Bachar: 6+ strikeouts?", ticker="KXMLBKS-26AUG24BACHAR-6"
    )
    row = _row(player="Lake Bachar", line=5.5)
    assert join_kalshi_to_board([market], [row], selected_date="2026-08-24")["matched"] == 1
    stale = join_kalshi_to_board([market], [row], selected_date="2026-08-22")
    assert stale["matched"] == 0
    # The player, market and line all matched -- ONLY the date disagreed, and
    # that is a different diagnosis from a market nothing on the board pairs.
    assert stale["reasons"][REASON_WOULD_MATCH_WRONG_DATE] == 1


def test_a_wrong_date_and_a_wrong_key_are_counted_separately():
    """The ordering bug that cost a whole diagnostic cycle.

    The date check used to run FIRST, so `market_closes_on_another_date: 213`
    swallowed every market before anything could report whether the names
    agreed -- one wrong assumption hiding another. Refusing late means one run
    answers both questions.
    """
    from syndicate.features.shared.kalshi_board_join import (
        REASON_WOULD_MATCH_WRONG_DATE,
        REASON_WRONG_DATE,
    )

    pairs = _kalshi(
        title="Lake Bachar: 6+ strikeouts?", ticker="KXMLBKS-26AUG24BACHAR-6"
    )
    unpaired = _kalshi(
        title="Nobody Here: 6+ strikeouts?", ticker="KXMLBKS-26AUG24NOBODY-6"
    )
    report = join_kalshi_to_board(
        [pairs, unpaired], [_row(player="Lake Bachar", line=5.5)], selected_date="2026-08-22"
    )
    assert report["reasons"][REASON_WOULD_MATCH_WRONG_DATE] == 1
    assert report["reasons"][REASON_WRONG_DATE] == 1


def test_close_time_is_a_settlement_deadline_and_must_not_date_the_market():
    """THE BUG THAT COST A WHOLE SLATE, reproduced from the production reading.

        ticker  KXMLBHR-26AUG242140MINATH-MINBBUXTON25-2
        open    2026-08-23T23:11:00Z
        close   2026-08-28T01:40:00Z      <- FOUR DAYS after the game
        expiration 2026-08-28T01:40:00Z

    Kalshi closes a market days after the event so late settlement data can
    land. The join compared `close_time[:10]` against the slate date, so it
    refused everything -- `matched=0 reasons={'market_closes_on_another_date':
    190}`, on every build for hours, straight through a live slate.

    The game is on the 24th and this must match on the 24th, with a
    `close_time` four days later sitting right there in the market.
    """
    market = _kalshi(
        title="Lake Bachar: 6+ strikeouts?",
        ticker="KXMLBKS-26AUG242140MINATH-BACHAR-6",
        close_time="2026-08-28T01:40:00Z",
    )
    row = _row(player="Lake Bachar", line=5.5)
    assert join_kalshi_to_board([market], [row], selected_date="2026-08-24")["matched"] == 1


def test_a_wnba_ticker_without_a_start_time_still_dates():
    """Two ticker shapes are in production and only the date is common to both.

    `KXWNBAPTS-26AUG23LVTOR-TORJALLEMAND22-15` has no `HHMM` after the date;
    `KXMLBHR-26AUG242140MINATH-...` does. A parser that required the time would
    have dated every MLB market and no WNBA one -- and WNBA was the slate this
    was built for.
    """
    market = _kalshi(
        title="Julie Allemand: 15+ points",
        series="KXWNBAPTS",
        ticker="KXWNBAPTS-26AUG23LVTOR-TORJALLEMAND22-15",
    )
    row = _row(player="Julie Allemand", line=14.5, market="player_points", sport="wnba")
    assert join_kalshi_to_board([market], [row], selected_date="2026-08-23")["matched"] == 1


def test_no_selected_date_skips_the_check_rather_than_guessing():
    """A caller that does not know the slate date gets the old behaviour, not a
    silent filter."""
    market = _kalshi(title="Lake Bachar: 6+ strikeouts?")
    assert join_kalshi_to_board([market], [_row(player="Lake Bachar", line=5.5)])["matched"] == 1


def test_an_undatable_ticker_is_refused_by_name_never_dated_from_close_time():
    """No fallback. Falling back to `close_time` would reinstate the bug, and
    would do it silently on exactly the markets we understand least."""
    from syndicate.features.shared.kalshi_board_join import REASON_UNDATABLE

    market = _kalshi(
        title="Lake Bachar: 6+ strikeouts?",
        ticker="KXMLBKS-NOTADATE-6",
        # A `close_time` that WOULD have matched, so a fallback would show up
        # as a match rather than as this refusal.
        close_time="2026-08-24T02:10:00Z",
    )
    report = join_kalshi_to_board(
        [market], [_row(player="Lake Bachar", line=5.5)], selected_date="2026-08-24"
    )
    assert report["matched"] == 0
    assert report["reasons"][REASON_UNDATABLE] == 1


# --- multi-sport, via the catalogue ----------------------------------------


def test_a_board_row_spelled_the_old_way_still_joins():
    """`market_keys` knows `pitcher_strikeouts` IS `strikeouts` (#224).

    Canonicalising the board row means the aliases live in the module that owns
    them. An alias tuple in the join was a second place for the two vocabularies
    to drift apart -- which is the exact failure this join exists to avoid.
    """
    market = _kalshi(title="Andrew Abbott: 7+ strikeouts?")
    for spelling in ("strikeouts", "pitcher_strikeouts"):
        report = join_kalshi_to_board([market], [_row(market=spelling)])
        assert report["matched"] == 1, spelling


def test_a_home_run_market_joins_without_this_module_naming_the_sport():
    """The point of routing through the catalogue: one registry line per series,
    and the market vocabulary comes from `market_keys`."""
    market = _kalshi(
        series="KXMLBHR",
        title="Pete Crow-Armstrong: 2+ home runs?",
        ticker="KXMLBHR-26AUG24PCA-2",
    )
    report = join_kalshi_to_board(
        [market], [_row(market="batter_home_runs", player="Pete Crow-Armstrong", line=1.5)]
    )
    assert report["matched"] == 1


def test_a_game_line_is_refused_because_its_title_names_no_game():
    """A player prop names a human, and a human plays one game a day. A total
    names neither team, so pairing it needs `event_ticker` mapped to our event
    id -- which does not exist. A total joined to the wrong game is a
    confidently-priced bet on strangers."""
    from syndicate.features.shared import kalshi_catalogue as cat
    from syndicate.features.shared.kalshi_board_join import REASON_EVENT_UNMATCHED

    cat.SERIES_SPORT["KXTESTTOTAL"] = "mlb"
    try:
        market = _kalshi(series="KXTESTTOTAL", title="Over 7.5 runs scored?")
        report = join_kalshi_to_board([market], [_row()])
        assert report["matched"] == 0
        # Counted separately: this is the SIZE OF THE GAP, not a defect.
        # The reason is now specific -- this fixture's ticker carries a player
        # name where the club codes go, so the event resolves to nothing on our
        # board rather than merely "we have no mapping at all".
        assert report["reasons"][REASON_EVENT_UNMATCHED] == 1
    finally:
        del cat.SERIES_SPORT["KXTESTTOTAL"]


# --------------------------------------------------------------------------
# Game lines: the event identity was in the ticker all along
# --------------------------------------------------------------------------


def _total(ticker="KXTESTTOTAL-26AUG242140MINATH-8", **kw):
    """A real Kalshi total. The TITLE grammar is the one this file already
    carried from production (`Over 7.5 runs scored?`); the TICKER is the shape
    measured 2026-08-23T23:51Z. Neither is invented here -- a fixture that
    guesses at Kalshi's wording tests only my imagination, which is how three
    game-date tests passed while production matched zero."""
    market = {
        "ticker": ticker,
        "series": "KXTESTTOTAL",
        "title": "Over 7.5 runs scored?",
        "yes_american": -110,
        "no_american": -110,
    }
    market.update(kw)
    return market


def _game_row(**kw):
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "totals",
        "away_team": "MIN",
        "home_team": "ATH",
        "side": "Over",
        "line": 7.5,
    }
    row.update(kw)
    return row


def _with_total_series(fn):
    from syndicate.features.shared import kalshi_catalogue as cat

    cat.SERIES_SPORT["KXTESTTOTAL"] = "mlb"
    try:
        return fn()
    finally:
        cat.SERIES_SPORT.pop("KXTESTTOTAL", None)


def test_game_lines_resolve_but_stay_unpriced_by_default(monkeypatch):
    """The measurement arrives BEFORE the money. The resolver runs on every
    build so the log can answer "would this work?", and the flag decides only
    whether a resolved game may be priced -- the opposite of the first live
    night, where the first measurement was a real order."""
    from syndicate.features.shared.kalshi_board_join import REASON_GAME_LINES_DISABLED

    monkeypatch.delenv("SYNDICATE_KALSHI_GAME_LINES", raising=False)
    report = _with_total_series(
        lambda: join_kalshi_to_board([_total()], [_game_row()], selected_date="2026-08-24")
    )
    assert report["matched"] == 0
    assert report["reasons"][REASON_GAME_LINES_DISABLED] == 1


def test_a_game_we_do_not_have_is_refused_by_its_own_name(monkeypatch):
    """`event_not_on_our_board` is the count that says which club-code ALIASES
    to add -- our `OAK` against Kalshi's `ATH`. It must never soften into a
    best guess."""
    from syndicate.features.shared.kalshi_board_join import REASON_EVENT_UNMATCHED

    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    report = _with_total_series(
        lambda: join_kalshi_to_board(
            [_total(ticker="KXTESTTOTAL-26AUG242140NYYBOS-8")],
            [_game_row()],
            selected_date="2026-08-24",
        )
    )
    assert report["matched"] == 0
    assert report["reasons"][REASON_EVENT_UNMATCHED] == 1


def test_a_doubleheader_is_refused_rather_than_guessed(monkeypatch):
    """Two real games behind one code pair. A coin flip between them is worse
    than no bet, because it looks exactly like a bet."""
    from syndicate.features.shared.kalshi_board_join import REASON_EVENT_AMBIGUOUS

    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    report = _with_total_series(
        lambda: join_kalshi_to_board(
            [_total()],
            [_game_row(event_id="evt-1"), _game_row(event_id="evt-2")],
            selected_date="2026-08-24",
        )
    )
    assert report["matched"] == 0
    assert report["reasons"][REASON_EVENT_AMBIGUOUS] == 1


def test_the_game_line_flag_actually_changes_behaviour(monkeypatch):
    """Reachability before correctness: `off != on`. Four inert features in one
    session were caught by this check and by nothing else."""
    from syndicate.features.shared.kalshi_board_join import REASON_GAME_LINES_DISABLED

    monkeypatch.delenv("SYNDICATE_KALSHI_GAME_LINES", raising=False)
    off = _with_total_series(
        lambda: join_kalshi_to_board([_total()], [_game_row()], selected_date="2026-08-24")
    )
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    on = _with_total_series(
        lambda: join_kalshi_to_board([_total()], [_game_row()], selected_date="2026-08-24")
    )
    assert off["reasons"].get(REASON_GAME_LINES_DISABLED) == 1
    assert on["reasons"].get(REASON_GAME_LINES_DISABLED) is None


def test_only_distinct_games_are_considered(monkeypatch):
    """The board carries one row per market per game, so feeding every row in
    would make an ordinary slate look like a doubleheader."""
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    rows = [
        _game_row(market="totals", line=7.5),
        _game_row(market="spreads", line=-1.5),
        _game_row(market="h2h", line=0.0),
    ]
    report = _with_total_series(
        lambda: join_kalshi_to_board([_total()], rows, selected_date="2026-08-24")
    )
    from syndicate.features.shared.kalshi_board_join import REASON_EVENT_AMBIGUOUS

    assert report["reasons"].get(REASON_EVENT_AMBIGUOUS) is None


# --------------------------------------------------------------------------
# Club-code aliases: ATH vs OAK, CWS vs CHW
# --------------------------------------------------------------------------


def test_a_club_alias_still_matches_the_game(monkeypatch):
    """MEASURED 2026-08-24: `event_not_on_our_board: 66`.

    Kalshi writes `CWS` where our board may write `CHW`, and `ATH` where it may
    write `OAK`. Comparing the raw concatenation calls those different games
    and refuses a real match. Resolution goes through `team_aliases`, the
    repo's EXISTING club resolver, rather than a second table -- two
    normalisers that disagree about one club is a silent mismatch nobody sees.
    """
    from syndicate.features.shared.kalshi_catalogue import match_event_blob

    ours = [{"event_id": "e1", "away_team": "TEX", "home_team": "CHW"}]
    assert match_event_blob("TEXCWS", ours, sport="mlb")["status"] == "ok"


def test_the_sport_decides_which_club_map_is_used():
    """`WSH` is the Nationals in mlb and the Mystics in wnba. Resolving against
    the wrong map is how a bet lands on the wrong league's game."""
    from syndicate.features.shared.kalshi_catalogue import match_event_blob

    ours = [{"event_id": "e1", "away_team": "TEX", "home_team": "CHW"}]
    # The right map pairs it; a sport whose map has neither club must not.
    assert match_event_blob("TEXCWS", ours, sport="mlb")["status"] == "ok"
    assert match_event_blob("TEXCWS", ours, sport="wnba")["status"] == "no_match"


def test_an_alias_match_still_refuses_the_wrong_game():
    """Widening the matcher must not widen what it will PAIR."""
    from syndicate.features.shared.kalshi_catalogue import match_event_blob

    ours = [{"event_id": "e1", "away_team": "TEX", "home_team": "CHW"}]
    assert match_event_blob("NYYBOS", ours, sport="mlb")["status"] == "no_match"


def test_an_alias_match_still_refuses_a_doubleheader():
    """Two real games behind one code pair stays a refusal, aliases or not."""
    from syndicate.features.shared.kalshi_catalogue import match_event_blob

    ours = [
        {"event_id": "e1", "away_team": "TEX", "home_team": "CHW"},
        {"event_id": "e2", "away_team": "TEX", "home_team": "CHW"},
    ]
    assert match_event_blob("TEXCWS", ours, sport="mlb")["status"] == "ambiguous"


def test_an_unresolvable_club_on_our_side_is_skipped_not_matched_loosely():
    """An unresolvable name is not evidence. Matching on it would pair a game
    we cannot even identify."""
    from syndicate.features.shared.kalshi_catalogue import match_event_blob

    ours = [{"event_id": "e1", "away_team": "ZZZ", "home_team": "QQQ"}]
    assert match_event_blob("TEXCWS", ours, sport="mlb")["status"] == "no_match"
