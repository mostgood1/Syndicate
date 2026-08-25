"""Series -> sport, title -> bet, and the refusals that form the work queue."""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_catalogue as cat


def _market(title, series="KXMLBKS", **kw):
    market = {"ticker": "KXMLBKS-26AUG24ABBOTT-7", "series": series, "title": title}
    market.update(kw)
    return market


# --- the mapping this file owns is series -> sport, and nothing else --------


def test_the_market_name_comes_from_the_shared_vocabulary_not_a_private_table():
    """CLAUDE.md's rule against a third private normaliser, enforced.

    Kalshi's own title wording already resolves through `market_keys`, so this
    module needs one fact per series and the title supplies the rest.
    """
    import inspect

    assert "canonical_market_key" in inspect.getsource(cat.classify_market)

    # No second market table hiding in the module's DATA. Checked against the
    # namespace rather than the source text, so the docstring may name examples
    # without the test mistaking prose for a mapping.
    canonical_names = {"batter_hits", "player_points", "batter_total_bases", "strikeouts", "outs"}
    for name, value in vars(cat).items():
        if name.startswith("__") or not isinstance(value, dict):
            continue
        assert not (set(value.values()) & canonical_names), f"{name} is a private market table"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Andrew Abbott: 7+ strikeouts?", "strikeouts"),
        ("Cal Quantrill: 17+ Outs Recorded?", "outs"),
        ("Pete Crow-Armstrong: 2+ home runs?", "batter_home_runs"),
    ],
)
def test_kalshis_own_wording_resolves_to_our_market_keys(title, expected):
    series = {"strikeouts": "KXMLBKS", "outs": "KXMLBOUTS", "batter_home_runs": "KXMLBHR"}[expected]
    verdict = cat.classify_market(_market(title, series=series))
    assert verdict["status"] == "ok"
    assert verdict["market"] == expected
    assert verdict["sport"] == "mlb"


def test_an_unseen_series_is_refused_by_name_never_guessed_from_its_ticker():
    """Inventing plausible tickers is the false-negative trap: a series that
    does not exist returns an empty page indistinguishable from a venue that
    lists nothing."""
    verdict = cat.classify_market(_market("Somebody: 3+ things?", series="KXNBAPTS"))
    assert verdict["status"] == "refused"
    assert verdict["reason"] == cat.REASON_UNMAPPED_SERIES


def test_a_seen_but_uncovered_series_is_named_separately_from_an_unseen_one():
    verdict = cat.classify_market(_market("Over 7.5 runs scored?", series="KXNPBTOTAL"))
    # "We do not model this" and "we have not looked at this yet" are different
    # states, and the work queue is only useful if it means the second.
    assert verdict["reason"] == cat.REASON_OUT_OF_SCOPE
    assert verdict["detail"] == "npb"


def test_parlay_series_are_refused_before_anything_else():
    verdict = cat.classify_market(_market("yes Houston,yes Texas", series="KXMVECROSSCATEGORY"))
    assert verdict["reason"] == cat.REASON_COMBINATORIAL


def test_a_stat_our_vocabulary_lacks_is_refused_with_the_TEXT_to_add():
    verdict = cat.classify_market(_market("Andrew Abbott: 3+ pickoffs?"))
    assert verdict["reason"] == cat.REASON_UNMAPPED_STAT
    # Verbatim, so the `market_keys` entry to add reads straight off the log.
    assert verdict["detail"] == "pickoffs"


# --- the line conversion, still the most mismatch-prone number -------------


def test_N_plus_becomes_the_half_point_line_below_it():
    # 7+ matched against a line of 7.0 finds nothing; against 7.5 it finds a
    # DIFFERENT bet and prices it confidently.
    assert cat.threshold_to_line(7) == 6.5
    assert cat.classify_market(_market("Andrew Abbott: 7+ strikeouts?"))["line"] == 6.5


# --- grammars --------------------------------------------------------------


def test_a_spread_is_not_read_as_a_moneyline():
    """Ordering, not luck. "Will the Giants win by over 2.5 runs?" contains
    "win", and a looser moneyline pattern would swallow it -- a spread read as a
    moneyline is a bet on a different outcome at a confident price."""
    parsed = cat._parse_title("Will the Yomiuri Giants win by over 2.5 runs?")
    assert parsed["grammar"] == cat.GRAMMAR_TEAM_SPREAD
    assert parsed["subject"] == "Yomiuri Giants"
    assert parsed["line"] == 2.5


def test_a_moneyline_title_is_read_as_one():
    parsed = cat._parse_title("Mexico wins")
    assert parsed["grammar"] == cat.GRAMMAR_MONEYLINE
    assert parsed["subject"] == "Mexico"


def test_a_total_is_read_but_flagged_as_not_identifying_its_game():
    parsed = cat._parse_title("Over 7.5 runs scored?")
    assert parsed["grammar"] == cat.GRAMMAR_TEAM_TOTAL
    assert parsed["line"] == 7.5
    # It names neither team.
    assert parsed["subject"] is None


def test_a_player_prop_does_not_need_an_event_mapping_but_a_game_line_does():
    prop = cat.classify_market(_market("Andrew Abbott: 7+ strikeouts?"))
    assert prop["needs_event_identity"] is False

    # A total joined to the wrong game is a confidently-priced bet on strangers,
    # so the join must refuse these until `event_ticker` is mapped to our ids.
    cat.SERIES_SPORT["KXTESTTOTAL"] = "mlb"
    try:
        total = cat.classify_market(_market("Over 7.5 runs scored?", series="KXTESTTOTAL"))
        assert total["status"] == "ok"
        assert total["needs_event_identity"] is True
    finally:
        del cat.SERIES_SPORT["KXTESTTOTAL"]


def test_an_unreadable_title_is_refused_rather_than_half_parsed():
    assert cat.classify_market(_market("???"))["reason"] == cat.REASON_UNREADABLE_TITLE


# --- the work queue --------------------------------------------------------


def test_the_work_queue_names_the_series_and_shows_an_example():
    queue = cat.unmapped_series(
        [
            _market("Somebody: 3+ points?", series="KXNBAPTS"),
            _market("Another: 5+ points?", series="KXNBAPTS"),
            _market("Andrew Abbott: 7+ strikeouts?"),
        ]
    )
    # A count of unmapped markets says nothing actionable; a series name beside
    # a sample title says exactly which registry line to add.
    assert set(queue) == {"KXNBAPTS"}
    assert queue["KXNBAPTS"]["count"] == 2
    assert "points" in queue["KXNBAPTS"]["sample_title"]


def test_the_queue_excludes_what_we_have_already_decided_not_to_cover():
    queue = cat.unmapped_series(
        [
            _market("Over 7.5 runs scored?", series="KXNPBTOTAL"),
            _market("yes Houston", series="KXMVECROSSCATEGORY"),
        ]
    )
    # Otherwise the queue drowns in things nobody intends to do.
    assert queue == {}


# --------------------------------------------------------------------------
# Auto-discovery -- 13,389 series, four registered by hand
# --------------------------------------------------------------------------


def test_wnba_is_not_swallowed_by_the_nba_token():
    """The whole trap. `KXWNBAREB` contains "NBA", so a naive scan registers
    every WNBA series as NBA and prices women's rebounds off a men's box."""
    assert cat.sport_for_ticker("KXWNBAREB") == "wnba"
    assert cat.sport_for_ticker("KXNBAPTS") == "nba"
    assert cat.sport_for_ticker("KXWNBATEAMTOTAL") == "wnba"


def test_only_player_props_are_registered():
    found = cat.auto_series_from_catalogue({
        "KXWNBAREB": "Women's Pro Basketball Player Rebounds",
        "KXWNBAPTS": "Women's Pro Basketball Player Points",
        "KXWNBATEAMTOTAL": "Women's Pro Basketball Team Totals",
        "KXWNBA1QSPREAD": "Women's Pro Basketball 1st Quarter Spread",
        "KXWNBAROY": "WNBA Rookie of the Year",
        "KXWNBAGAME": "Women's Pro Basketball Game",
    })
    # A game line has no player to join on and needs an event mapping that does
    # not exist; a future has no game at all.
    assert set(found) == {"KXWNBAREB", "KXWNBAPTS"}


def test_a_player_shaped_title_we_cannot_PRICE_is_still_refused():
    found = cat.auto_series_from_catalogue({
        "KXWNBADUNK": "Women's Pro Basketball Player to Dunk",
        "KXWNBAREB": "Women's Pro Basketball Player Rebounds",
    })
    # Both conditions or neither: a stat `market_keys` cannot name would price
    # nothing however player-shaped the title looks.
    assert set(found) == {"KXWNBAREB"}


def test_an_unknown_sport_is_skipped_rather_than_guessed():
    assert cat.auto_series_from_catalogue({"KXCRICKETRUNS": "Cricket Player Runs"}) == {}


def test_discovery_never_overwrites_a_hand_written_entry():
    before = dict(cat.SERIES_SPORT)
    cat.register_discovered({"KXMLBKS": "wnba"})
    try:
        # "We chose this" and "a title matched" are different confidence levels
        # and must not become indistinguishable.
        assert cat.sport_for_series("KXMLBKS") == "mlb"
    finally:
        cat._DISCOVERED.clear()
        assert dict(cat.SERIES_SPORT) == before


def test_register_reports_what_was_ADDED_not_what_was_seen():
    try:
        first = cat.register_discovered({"KXTESTPTS": "wnba"})
        second = cat.register_discovered({"KXTESTPTS": "wnba"})
        assert first["added"] == {"KXTESTPTS": "wnba"}
        # Idempotent: a re-run adds nothing and says so.
        assert second["added"] == {}
        assert cat.sport_for_series("KXTESTPTS") == "wnba"
        assert "KXTESTPTS" in cat.all_series()
    finally:
        cat._DISCOVERED.clear()


# --------------------------------------------------------------------------
# The game date, which is in the TICKER and was being read from `close_time`
# --------------------------------------------------------------------------


def test_the_game_date_comes_out_of_the_ticker():
    """Both production shapes, copied verbatim from the 2026-08-23T23:51Z logs."""
    from syndicate.features.shared.kalshi_catalogue import game_date_from_ticker

    # WNBA: no start time after the date.
    assert game_date_from_ticker("KXWNBAPTS-26AUG23LVTOR-TORJALLEMAND22-15") == "2026-08-23"
    # MLB: `2140` between the date and the teams.
    assert game_date_from_ticker("KXMLBHR-26AUG242140MINATH-MINBBUXTON25-2") == "2026-08-24"
    assert game_date_from_ticker("KXMLBKS-26AUG242140MINATH-MINZMATTHEWS52-8") == "2026-08-24"


def test_an_unreadable_ticker_returns_none_rather_than_a_guess():
    """None is what makes the caller refuse by name. Every one of these would
    have been silently mis-dated off `close_time` under the old code."""
    from syndicate.features.shared.kalshi_catalogue import game_date_from_ticker

    assert game_date_from_ticker("KXMLBKS") is None          # no event segment
    assert game_date_from_ticker("KXMLBKS-GARBAGE-6") is None  # not a date
    assert game_date_from_ticker("KXMLBKS-26XXX24MIN-6") is None  # not a month
    assert game_date_from_ticker("KXMLBKS-26FEB30MIN-6") is None  # not a real day
    assert game_date_from_ticker("") is None
    assert game_date_from_ticker(None) is None


def test_the_month_is_read_as_a_name_not_a_number():
    """`26AUG24` is August 24th, not the 26th of an eighth month. Getting this
    backwards produces a plausible date every time and would never crash."""
    from syndicate.features.shared.kalshi_catalogue import game_date_from_ticker

    assert game_date_from_ticker("KXMLBKS-26AUG24TEAM-1") == "2026-08-24"
    assert game_date_from_ticker("KXMLBKS-26DEC01TEAM-1") == "2026-12-01"
    assert game_date_from_ticker("KXMLBKS-27JAN31TEAM-1") == "2027-01-31"


def test_every_hand_registered_series_dates_from_a_realistic_ticker():
    """A registry entry whose tickers cannot be dated prices nothing, and does
    it silently -- the exact failure mode this whole change is fixing."""
    from syndicate.features.shared.kalshi_catalogue import SERIES_SPORT, game_date_from_ticker

    for series in SERIES_SPORT:
        ticker = f"{series}-26AUG23LVTOR-TORPLAYER22-15"
        assert game_date_from_ticker(ticker) == "2026-08-23", series


# --------------------------------------------------------------------------
# Football and soccer: the vocabulary that was missing entirely
# --------------------------------------------------------------------------


def test_football_and_soccer_stats_resolve_to_the_boards_own_keys():
    """`KALSHI_SPORT NFL ticker_substring_n=317 classified_n=0` -- 317 series
    listed and none classifiable, because `market_keys` had no football map at
    all. Discovery requires the stat to resolve, so a sport with no vocabulary
    can never register anything however player-shaped its titles are.

    The expected VALUES are OddsAPI's keys, which is what the board emits and
    what the join compares against. Asserting the exact key is the point: a map
    to a plausible-but-wrong name would join to nothing and look like Kalshi
    simply not quoting the market.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    assert canonical_market_key("nfl", "Passing Yards") == "player_pass_yds"
    assert canonical_market_key("nfl", "Rushing Yards") == "player_rush_yds"
    assert canonical_market_key("nfl", "Receiving Yards") == "player_reception_yds"
    assert canonical_market_key("nfl", "Receptions") == "player_receptions"
    assert canonical_market_key("nfl", "Anytime Touchdown") == "player_anytime_td"
    # NCAAF shares the football vocabulary -- same stats, different rosters.
    assert canonical_market_key("ncaaf", "Passing Yards") == "player_pass_yds"
    assert canonical_market_key("soccer", "Goals") == "player_goals"
    assert canonical_market_key("soccer", "Shots on Target") == "player_shots_on_target"
    assert canonical_market_key("soccer", "Anytime Goalscorer") == "player_goal_scorer_anytime"


def test_a_football_series_now_auto_discovers():
    """The end-to-end consequence: with a vocabulary, discovery keeps it."""
    from syndicate.features.shared.kalshi_catalogue import auto_series_from_catalogue

    found = auto_series_from_catalogue(
        {
            "KXNFLPASSYDS": "Pro Football Player Passing Yards",
            "KXNCAAFRUSHYDS": "College Football Player Rushing Yards",
            # Still refused: a game line has no player to join on.
            "KXNFLGAMETOTAL": "Pro Football Game Total",
        }
    )
    assert found.get("KXNFLPASSYDS") == "nfl"
    assert found.get("KXNCAAFRUSHYDS") == "ncaaf"
    assert "KXNFLGAMETOTAL" not in found


def test_a_bare_game_title_registers_as_the_moneyline():
    """Measured 2026-08-24: KXMLBGAME's real series-level title on Kalshi is
    exactly "Professional Baseball Game" -- confirmed against a live,
    $6.7M-volume moneyline market a user found on kalshi.com that this
    vocabulary gap was silently dropping from discovery entirely (not
    misclassified -- never fetched into the artifact at all, because
    `auto_game_series_from_catalogue` never registered the series in the
    first place). No "moneyline"/"winner" word appears anywhere in the
    title, only the bare word "game" -- which is Kalshi's OWN wording for
    the straight moneyline series, not a synonym invented here. The same
    "<Sport> Game" pattern is Kalshi's title for the moneyline series on
    every other sport carried in this repo (KXNFLGAME "Professional
    Football Game", KXNBAGAME "Pro Basketball Game", KXNHLGAME "NHL Game"),
    so this was never an MLB-only gap.
    """
    from syndicate.features.shared.kalshi_catalogue import auto_game_series_from_catalogue

    found = auto_game_series_from_catalogue(
        {
            "KXMLBGAME": "Professional Baseball Game",
            "KXNFLGAME": "Professional Football Game",
            "KXNBAGAME": "Pro Basketball Game",
            "KXNHLGAME": "NHL Game",
        }
    )
    assert found.get("KXMLBGAME") == "mlb"
    assert found.get("KXNFLGAME") == "nfl"
    assert found.get("KXNBAGAME") == "nba"
    assert found.get("KXNHLGAME") == "nhl"


def test_prop_candidates_reports_what_it_CANNOT_price():
    """A list of only what already works cannot tell "Kalshi does not list it"
    from "we have no vocabulary for it" -- the confusion that hid 317 NFL
    series. Both failure modes have to be visible and distinguishable."""
    from syndicate.features.shared.kalshi_catalogue import prop_candidates

    by_ticker = {
        c["ticker"]: c
        for c in prop_candidates(
            {
                "KXNFLPASSYDS": "Pro Football Player Passing Yards",
                "KXNFLKICKRET": "Pro Football Player Kick Return Yards",
                "KXEPLGOALS": "English Premier League Player Goals",
                "KXWNBATOTAL": "Women's Pro Basketball Total",
            }
        )
    }

    # Mapped.
    assert by_ticker["KXNFLPASSYDS"]["market"] == "player_pass_yds"
    # Sport known, stat not in the table -- a spelling to add.
    assert by_ticker["KXNFLKICKRET"]["sport"] == "nfl"
    assert by_ticker["KXNFLKICKRET"]["market"] is None
    # Ticker carries no token we recognise. This is the ONLY way soccer can
    # surface: Kalshi names those series by competition, never "soccer".
    assert by_ticker["KXEPLGOALS"]["sport"] is None
    # Not a player prop at all -- never a candidate.
    assert "KXWNBATOTAL" not in by_ticker


# --------------------------------------------------------------------------
# Game-line titles -- the 302 that came back `unreadable_title`
# --------------------------------------------------------------------------


def test_the_game_line_titles_kalshi_actually_uses_parse():
    """Every title here is COPIED VERBATIM from production, 2026-08-24T02:12Z.

    The first build after game-line series were registered returned
    `unreadable_title: 302` — the existing `_TEAM_SPREAD` was written against
    "Will the X win by over N runs?" and Kalshi says "X wins by over N runs?".
    Close enough to look handled, different enough to match nothing, which is
    why the count was 302 rather than a partial number.
    """
    from syndicate.features.shared.kalshi_catalogue import _parse_title

    full = _parse_title("Texas wins by over 3.5 runs?")
    assert full["stat_text"] == "spreads"
    assert full["subject"] == "Texas"
    assert full["line"] == 3.5

    # The PERIOD suffix is the board's own (`spreads_1st_5_innings`), not a
    # spelling invented here -- one only Kalshi's side understands joins to
    # nothing.
    f5 = _parse_title("Texas wins first 5 innings by over 2.5 runs?")
    assert f5["stat_text"] == "spreads_1st_5_innings"

    total = _parse_title("First 5 innings: Over 6.5 runs")
    assert total["stat_text"] == "totals_1st_5_innings"
    # A total names no team, so the game must come from the ticker.
    assert total["subject"] is None

    # A TEAM total is not the game total -- conflating them prices one side's
    # runs as though they were both sides'.
    team = _parse_title("Will Texas score over 7.5 runs?")
    assert team["stat_text"] == "team_totals"
    assert team["subject"] == "Texas"


def test_a_period_the_board_cannot_key_is_refused_not_flattened():
    """`9th inning: Over 1.5 runs` has no board key. Dropping the period and
    calling it a game total would be a bet on a different thing entirely."""
    from syndicate.features.shared.kalshi_catalogue import _parse_title

    assert _parse_title("9th inning: Over 1.5 runs") is None


def test_the_tie_leg_is_refused():
    """A draw is a THIRD outcome. The board carries no MLB first-innings
    three-way, and reading it as either side of a two-way line would price the
    wrong wager."""
    from syndicate.features.shared.kalshi_catalogue import _parse_title

    assert _parse_title("first 5 innings tie") is None


def test_a_spread_is_never_read_as_a_moneyline():
    """`_MONEYLINE` is `<team> wins`, and every one of these contains "wins".
    A spread read as a moneyline is a bet on a different outcome at a
    confident price -- the ordering in `_parse_title` is what prevents it."""
    from syndicate.features.shared.kalshi_catalogue import (
        GRAMMAR_TEAM_SPREAD,
        _parse_title,
    )

    for title in (
        "Texas wins by over 3.5 runs?",
        "Texas wins first 5 innings by over 2.5 runs?",
    ):
        assert _parse_title(title)["grammar"] == GRAMMAR_TEAM_SPREAD


def test_a_futures_market_still_refuses():
    """Division winners have no game date in the ticker and no game to join."""
    from syndicate.features.shared.kalshi_catalogue import (
        _parse_title,
        game_date_from_ticker,
    )

    assert _parse_title("Will Texas be the 2026 AL West Division Winner") is None
    # And the ticker cannot be dated either -- two independent refusals.
    assert game_date_from_ticker("KXMLBALWEST-26-TEX") is None


# --------------------------------------------------------------------------
# The full-game total: registered by hand, because the title gate misses it
# --------------------------------------------------------------------------


def test_the_full_game_totals_series_are_registered():
    """CONFIRMED BY THE USER 2026-08-25 against a live Kalshi market page:

        KXMLBTOTAL-26AUG251840BOSMIA-7

    A full-game total on today's Boston/Miami game. It exists and is
    tradeable, and `KXMLBTOTAL` appeared NOWHERE in our logs -- never
    registered, never fetched -- so every MLB `totals` board row had nothing to
    join to and every Kalshi order refused `no_live_price`.

    We DO fetch `KXMLBF5TOTAL` (first five), `KXMLBINNINGTOTAL` (one inning)
    and `KXMLBTEAMTOTAL` (one team). None is the full-game total, and that
    near-miss is what made the gap read as coverage rather than absence.
    """
    from syndicate.features.shared.kalshi_catalogue import sport_for_series

    assert sport_for_series("KXMLBTOTAL") == "mlb"
    for series, sport in (
        ("KXNBATOTAL", "nba"), ("KXNFLTOTAL", "nfl"),
        ("KXNCAAFTOTAL", "ncaaf"), ("KXNCAABTOTAL", "ncaab"),
        ("KXWNBATOTAL", "wnba"),
    ):
        assert sport_for_series(series) == sport, series


def test_the_moneyline_and_spread_survive_a_title_rewording():
    """`KXMLBGAME` registered only because a vocabulary entry happens to match
    "Professional Baseball Game". A title Kalshi rewords would silently
    un-register the most valuable market on the venue -- again. A registry
    entry cannot be reworded out from under us."""
    from syndicate.features.shared.kalshi_catalogue import SERIES_SPORT

    for series in ("KXMLBGAME", "KXMLBSPREAD", "KXWNBAGAME", "KXWNBASPREAD"):
        assert SERIES_SPORT.get(series), series


def test_a_real_full_game_total_ticker_classifies_end_to_end():
    """Registration is necessary, not sufficient -- the market's own title must
    still classify. Ticker and title shape are the ones measured in
    production, not invented."""
    from syndicate.features.shared.kalshi_catalogue import (
        classify_market,
        event_blob_from_ticker,
        game_date_from_ticker,
    )

    ticker = "KXMLBTOTAL-26AUG251840BOSMIA-7"
    assert game_date_from_ticker(ticker) == "2026-08-25"
    assert event_blob_from_ticker(ticker) == "BOSMIA"

    verdict = classify_market({
        "ticker": ticker, "series": "KXMLBTOTAL",
        "title": "Over 7.5 runs scored?",
        "yes_ask_dollars": 0.5, "no_ask_dollars": 0.5,
    })
    assert verdict["status"] == "ok"
    assert verdict["market"] == "totals"
    assert verdict["line"] == 7.5
    assert verdict["side"] == "over"
    # A total names no team, so the game must come from the ticker.
    assert verdict["needs_event_identity"] is True
