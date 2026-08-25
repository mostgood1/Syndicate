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


def test_the_mlb_player_prop_series_the_board_was_already_asking_for():
    """CONFIRMED BY THE USER 2026-08-25 from live Kalshi market pages -- six
    series we never fetched, while the board was already asking for four of
    them by name.

    `VENUE_REPRICE_KEYS board_wanted`, measured 2026-08-25T16:13:44Z:

        mlb|batter_rbis|over|0.5        (x3)   -> KXMLBRBI
        mlb|batter_total_bases|over|1.5        -> KXMLBTB
        mlb|earned_runs|under|1.5              -> KXMLBERA
        mlb|hits_allowed|over|4.5              -> KXMLBHA

    Every one of those rows found nothing and reported it as Kalshi having no
    market, when Kalshi had the market and we were not asking for it.
    """
    from syndicate.features.shared.kalshi_catalogue import sport_for_series

    for series in (
        "KXMLBHIT", "KXMLBHRR", "KXMLBTB",
        "KXMLBRBI", "KXMLBERA", "KXMLBWA", "KXMLBHA",
    ):
        assert sport_for_series(series) == "mlb", series


def test_the_real_prop_tickers_classify_to_the_market_the_board_wants():
    """Registration is necessary, not sufficient. Tickers are the user's,
    verbatim; titles are Kalshi's own "N+ stat" wording."""
    from syndicate.features.shared.kalshi_catalogue import classify_market

    cases = (
        ("KXMLBHIT", "KXMLBHIT-26AUG251840BOSMIA-MIAARAMREZ50-1",
         "Agustin Ramirez: 1+ hits?", "batter_hits", 0.5),
        ("KXMLBTB", "KXMLBTB-26AUG251840BOSMIA-MIAARAMREZ50-2",
         "Agustin Ramirez: 2+ total bases?", "batter_total_bases", 1.5),
        ("KXMLBRBI", "KXMLBRBI-26AUG251840BOSMIA-MIAARAMREZ50-1",
         "Agustin Ramirez: 1+ RBIs?", "batter_rbis", 0.5),
        ("KXMLBERA", "KXMLBERA-26AUG251840BOSMIA-BOSPTOLLE70-1",
         "Payton Tolle: 1+ earned runs?", "earned_runs", 0.5),
        ("KXMLBWA", "KXMLBWA-26AUG251840BOSMIA-MIATPHILLIPS30-2",
         "Tyler Phillips: 2+ walks allowed?", "walks_allowed", 1.5),
        ("KXMLBHA", "KXMLBHA-26AUG251840BOSMIA-BOSPTOLLE70-5",
         "Payton Tolle: 5+ hits allowed?", "hits_allowed", 4.5),
    )
    for series, ticker, title, market, line in cases:
        verdict = classify_market({
            "ticker": ticker, "series": series, "title": title,
            "yes_ask_dollars": 0.5, "no_ask_dollars": 0.5,
        })
        assert verdict["status"] == "ok", (series, verdict)
        assert verdict["market"] == market, (series, verdict)
        assert verdict["line"] == line, (series, verdict)
        assert verdict["side"] == "over", (series, verdict)
        # A prop names a human, so it needs neither an event resolution nor
        # the game-lines flag.
        assert not verdict.get("needs_event_identity"), (series, verdict)


def test_soccer_registers_from_the_competition_in_kalshis_own_title():
    """Soccer was the one sport `sport_for_ticker` could never see, because
    Kalshi names soccer series by COMPETITION -- `KXLALIGAGAME`, `KXUCL1HTOTAL`
    -- and there is no token to scan for. `prop_candidates` has said so in its
    own docstring since it was written.

    MEASURED 2026-08-25T19:12:01Z in `kalshi_discovery GAP`: KXLALIGASCORE,
    KXLALIGA1HSCORE, KXUECLSCORE, KXUECLTEAMTOTAL, KXUELTEAMTOTAL,
    KXUCL1HTOTAL, KXEFLCUPTOTAL -- all `reason=unmapped_series`.
    """
    from syndicate.features.shared.kalshi_catalogue import soccer_league_from_title

    assert soccer_league_from_title("La Liga Game") == "la_liga"
    assert soccer_league_from_title("EPL Total") == "epl"
    assert soccer_league_from_title("MLS Spread") == "mls"
    assert soccer_league_from_title("Championship Game") == "championship"


def test_the_soccer_title_gate_is_a_prefix_and_not_a_substring():
    """Two collisions this would otherwise cause, and both are the exact shape
    of the `KXWNBAREB`-contains-`NBA` trap already documented above.

    "Championship" is a substring of "UEFA Champions League"... it is not,
    quite, but "Champion" is, and a looser match files a competition we do not
    model under one we do. And a competition code as a TICKER substring is
    worse still: `UCL` sits inside `KXNUCLEARTEST`.
    """
    from syndicate.features.shared.kalshi_catalogue import soccer_league_from_title

    # Competitions Syndicate does not model stay unmapped -- and stay in the
    # COVERAGE_GAPS work queue, which is the point.
    for title in (
        "UEFA Champions League 1st Half Total",
        "UEFA Europa Conference League Final Score",
        "EFL Cup Total",
        "Nuclear test in 2026",
        "MLSomething Total",
    ):
        assert soccer_league_from_title(title) is None, title


def test_soccer_discovery_registers_game_lines_and_refuses_what_we_cannot_price():
    """The whole gate, end to end. Correct-score and corners have no board row
    and no `market_keys` entry, so they must be REFUSED rather than registered
    -- a series we register but cannot name would be fetched forever for
    nothing."""
    from syndicate.features.shared.kalshi_catalogue import (
        auto_game_series_from_catalogue,
        auto_series_from_catalogue,
    )

    titles = {
        "KXLALIGAGAME": "La Liga Game",
        "KXLALIGATOTAL": "La Liga Total",
        "KXLALIGASPREAD": "La Liga Spread",
        "KXLALIGAGOAL": "La Liga Player Goals",
        "KXLALIGASCORE": "La Liga Final Score",
        "KXLALIGATCORNERS": "La Liga Team Corners",
        "KXUCL1HTOTAL": "UEFA Champions League 1st Half Total",
    }
    games = auto_game_series_from_catalogue(titles)
    assert games == {
        "KXLALIGAGAME": "soccer",
        "KXLALIGATOTAL": "soccer",
        "KXLALIGASPREAD": "soccer",
    }
    assert auto_series_from_catalogue(titles) == {"KXLALIGAGOAL": "soccer"}


def test_the_soccer_gate_does_not_disturb_the_sports_that_have_tickers():
    """The title gate is a FALLBACK, consulted only when the ticker carries no
    sport token. A soccer-shaped title on an MLB ticker must stay MLB."""
    from syndicate.features.shared.kalshi_catalogue import (
        auto_game_series_from_catalogue,
    )

    found = auto_game_series_from_catalogue({
        "KXMLBGAME": "Professional Baseball Game",
        "KXWNBATOTAL": "Women's Pro Basketball Total",
    })
    assert found == {"KXMLBGAME": "mlb", "KXWNBATOTAL": "wnba"}


def test_the_real_wnba_tickers_from_a_live_game_all_classify():
    """CONFIRMED BY THE USER 2026-08-25 from the live Chicago/Connecticut game
    page. Seven tickers, every market family the venue offers on one game.

    THE EVENT SEGMENT CARRIES NO TIME -- `26AUG25CHICONN`, where MLB's is
    `26AUG251840BOSMIA`. Both shapes are in production and a parser that
    assumed the longer one would drop every WNBA and soccer market on the
    venue while reporting nothing.

    `KXWNBA3PT` is the one that was failing: the series is hand-registered and
    its comment claims `market_keys` resolves it, which was true of the SERIES
    title ("Player Threes") and false of the MARKET titles. It refused
    `stat_not_in_market_vocabulary` on every wording but the bare word.
    """
    from syndicate.features.shared.kalshi_catalogue import (
        classify_market,
        event_blob_from_ticker,
        game_date_from_ticker,
        sport_for_series,
    )

    cases = (
        ("KXWNBAGAME", "KXWNBAGAME-26AUG25CHICONN-CHI",
         "Chicago Sky wins", "h2h", None, True),
        ("KXWNBATOTAL", "KXWNBATOTAL-26AUG25CHICONN-172",
         "Over 171.5 points scored?", "totals", 171.5, True),
        ("KXWNBASPREAD", "KXWNBASPREAD-26AUG25CHICONN-CHI7",
         "Will the Chicago Sky win by over 6.5 points?", "spreads", 6.5, True),
        ("KXWNBAPTS", "KXWNBAPTS-26AUG25CHICONN-CHIDCARRINGTON3-10",
         "DiJonai Carrington: 10+ points?", "player_points", 9.5, False),
        ("KXWNBAREB", "KXWNBAREB-26AUG25CHICONN-CHIDCARRINGTON3-2",
         "DiJonai Carrington: 2+ rebounds?", "player_rebounds", 1.5, False),
        ("KXWNBA3PT", "KXWNBA3PT-26AUG25CHICONN-CONNSRIVERS22-1",
         "Saniya Rivers: 1+ three pointers made?", "player_threes", 0.5, False),
    )
    for series, ticker, title, market, line, needs_event in cases:
        assert sport_for_series(series) == "wnba", series
        assert game_date_from_ticker(ticker) == "2026-08-25", ticker
        assert event_blob_from_ticker(ticker) == "CHICONN", ticker
        verdict = classify_market({
            "ticker": ticker, "series": series, "title": title,
            "yes_ask_dollars": 0.5, "no_ask_dollars": 0.5,
        })
        assert verdict["status"] == "ok", (series, verdict)
        assert verdict["market"] == market, (series, verdict)
        assert verdict["line"] == line, (series, verdict)
        assert bool(verdict.get("needs_event_identity")) is needs_event, (series, verdict)


def test_a_made_three_resolves_however_the_market_title_spells_it():
    """The failure was one spelling wide. Kalshi words a market title per
    market, and only the bare word "threes" resolved -- so a registered series
    refused every market on it, which reads exactly like a series Kalshi does
    not list."""
    from syndicate.features.shared.market_keys import canonical_market_key

    for spelling in (
        "threes", "threes made", "made threes",
        "three pointers", "three pointers made",
        "three-pointers", "three-pointers made",
        "3 pointers made", "3-pointers made", "3PT made", "3pts",
    ):
        for sport in ("wnba", "nba"):
            assert canonical_market_key(sport, spelling) == "player_threes", (sport, spelling)


def test_the_wnba_half_total_the_user_confirmed_classifies_once_registered():
    """`KXWNBA1HTOTAL-26AUG25CHICONN-78`, confirmed on the live game page and
    present in production's `AUTO_SERIES game_sample` the same day -- so
    discovery registers it and the static table deliberately does not.

    Pinned anyway, because the REGISTRATION was never the fragile part. When
    this test was first written it asserted only status/line/side and PASSED
    while the market resolved to `totals` -- the full-game key -- because the
    totals grammar threw its stat away. See
    `test_a_game_total_is_refused_unless_it_counts_this_sports_scoring_unit`.
    """
    from syndicate.features.shared import kalshi_catalogue as cat

    absent = object()
    prior = cat.SERIES_SPORT.get("KXWNBA1HTOTAL", absent)
    cat.SERIES_SPORT["KXWNBA1HTOTAL"] = "wnba"
    try:
        verdict = cat.classify_market({
            "ticker": "KXWNBA1HTOTAL-26AUG25CHICONN-78",
            "series": "KXWNBA1HTOTAL",
            "title": "Over 77.5 1st half points scored?",
            "yes_ask_dollars": 0.5, "no_ask_dollars": 0.5,
        })
    finally:
        if prior is absent:
            cat.SERIES_SPORT.pop("KXWNBA1HTOTAL", None)
        else:
            cat.SERIES_SPORT["KXWNBA1HTOTAL"] = prior

    assert verdict["status"] == "ok", verdict
    # `totals_h1`, NOT `totals`. This assertion is the whole test: the grammar
    # matched `Over <line> <anything>?` and hardcoded `totals`, so a half line
    # was indistinguishable from a full-game line and joined on (market, line).
    assert verdict["market"] == "totals_h1", verdict
    assert verdict["line"] == 77.5, verdict
    assert verdict["side"] == "over", verdict


def test_a_game_total_is_refused_unless_it_counts_this_sports_scoring_unit():
    """THE CONFIDENT WRONG MATCH THIS FILE EXISTS TO PREVENT, found while
    registering soccer 2026-08-25.

    `_TEAM_TOTAL` matches `Over <line> <anything>?` and then set the market to
    the literal string "totals", discarding the stat it had just parsed. So
    every one of these became a full-game points/runs total:

        "Over 4.5 corners?"                  -> totals 4.5
        "Over 77.5 1st half points scored?"  -> totals 77.5
        "Over 2.5 1H goals scored"           -> totals 2.5   (real, KXUCL1HTOTAL)

    The first is a WRONG BET rather than a miscount. Soccer boards carry a
    goals total at 4.5, the join matches on (market, line, side), and our goals
    model would have priced a corners market with nothing anywhere reading
    wrong.
    """
    from syndicate.features.shared import kalshi_catalogue as cat

    absent = object()
    added = {"KXLALIGATOTAL": "soccer", "KXLALIGATCORNERS": "soccer"}
    before = {k: cat.SERIES_SPORT.get(k, absent) for k in added}
    cat.SERIES_SPORT.update(added)
    try:
        goals = cat.classify_market({
            "ticker": "KXLALIGATOTAL-26AUG25VCFRBB-2", "series": "KXLALIGATOTAL",
            "title": "Over 2.5 goals scored?",
            "yes_ask_dollars": 0.5, "no_ask_dollars": 0.5,
        })
        corners = cat.classify_market({
            "ticker": "KXLALIGATCORNERS-26AUG25VCFRBB-VCF5", "series": "KXLALIGATCORNERS",
            "title": "Over 4.5 corners?",
            "yes_ask_dollars": 0.5, "no_ask_dollars": 0.5,
        })
    finally:
        for key, prior in before.items():
            if prior is absent:
                cat.SERIES_SPORT.pop(key, None)
            else:
                cat.SERIES_SPORT[key] = prior

    assert goals["status"] == "ok" and goals["market"] == "totals", goals
    assert corners["status"] == "refused", corners
    assert corners["reason"] == "stat_not_in_market_vocabulary", corners
    # The stat VERBATIM, so the work queue names what to add rather than a
    # count. A refusal that says "corners" is actionable; `totals 4.5` is a bet.
    assert corners["detail"] == "corners", corners


def test_the_scoring_unit_is_per_sport_and_the_period_survives_it():
    """A goals line is not a runs line. Reading either as the other is the same
    error as reading corners as goals, one sport over."""
    from syndicate.features.shared.market_keys import total_market_from_stat

    assert total_market_from_stat("mlb", "runs scored") == "totals"
    assert total_market_from_stat("soccer", "goals scored") == "totals"
    assert total_market_from_stat("nhl", "goals") == "totals"
    assert total_market_from_stat("wnba", "points scored") == "totals"

    # Right shape, wrong sport's unit.
    assert total_market_from_stat("mlb", "goals scored") is None
    assert total_market_from_stat("soccer", "runs scored") is None
    assert total_market_from_stat("wnba", "goals") is None

    # The period is carried through, never flattened onto the full game.
    assert total_market_from_stat("wnba", "1st half points scored") == "totals_h1"
    assert total_market_from_stat("nba", "1st quarter points scored") == "totals_q1"
    assert total_market_from_stat("soccer", "1H goals scored") == "totals_h1"
    assert total_market_from_stat("nhl", "1st period goals") == "totals_p1"

    # A period with no unit after it is not a total.
    assert total_market_from_stat("nba", "1st half") is None
    assert total_market_from_stat("nba", "") is None
    assert total_market_from_stat("chess", "points") is None


def test_the_kalshi_adapter_reads_the_per_series_artifact_shape(monkeypatch):
    """THE REGRESSION THAT COST AN EVENING, pinned behaviourally.

    `kalshi_markets.json` stopped persisting a top-level `markets` key on
    2026-08-25: storing the merged list beside `series[<ticker>]["markets"]`
    wrote the payload twice and pushed the document past the keyvalue store's
    8MB ceiling, at which point it stopped being written at all.

    The writer changed and TWO READERS DID NOT. Measured 2026-08-25T20:15:10Z,
    every sport, every cycle:

        'kalshi': {'status': 'error', 'reason': 'markets_key_absent',
                   'quotes': 0, 'age_seconds': None}

    Kalshi offered zero quotes, so it won zero selections, so the plan held
    zero Kalshi positions, so `ORDER_PATH venue=kalshi` read
    `status=no_positions` -- which reads exactly like "Kalshi has no markets
    for us" and was one dictionary key.

    THE FIXTURE IS THE POINT. A unit test of this reader would have passed
    throughout, because its fixture was written in the old shape and agreed
    with the old reader. This one is written in the shape the WRITER actually
    persists.
    """
    from syndicate.features.shared import venue_quote_adapters as adapters

    payload = {
        "fetched_at": "2026-08-25T20:15:00Z",
        "series": {
            "KXMLBTOTAL": {
                "markets": [{
                    "ticker": "KXMLBTOTAL-26AUG251840BOSMIA-7",
                    "series": "KXMLBTOTAL",
                    "title": "Over 7.5 runs scored?",
                    "yes_ask_dollars": 0.54,
                    "no_ask_dollars": 0.48,
                }]
            }
        },
    }
    import time

    monkeypatch.setattr(adapters, "_artifact", lambda parts: (payload, time.time()))
    outcome = adapters.kalshi_outcome("mlb", "2026-08-25")

    assert outcome.reason != "markets_key_absent", outcome
    assert outcome.status != "error", outcome


def test_the_kalshi_adapter_still_names_a_document_with_neither_shape():
    """`markets_key_absent` must stay REACHABLE. A helper that turns every
    unreadable document into an empty market list would replace a named error
    with a silent zero -- the same absence/failure confusion one layer down."""
    from syndicate.features.shared import venue_quote_adapters as adapters

    outcome = adapters.kalshi_outcome.__wrapped__ if hasattr(
        adapters.kalshi_outcome, "__wrapped__"
    ) else adapters.kalshi_outcome

    import time
    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            adapters, "_artifact", lambda parts: ({"fetched_at": "x"}, time.time())
        )
        verdict = outcome("mlb", "2026-08-25")
    finally:
        monkeypatch.undo()

    assert verdict.status == "error", verdict
    assert verdict.reason == "markets_key_absent", verdict


def test_the_legacy_top_level_markets_payload_still_reads():
    """An artifact written before the split must not go dark on deploy."""
    from syndicate.features.shared import venue_quote_adapters as adapters

    import time
    import pytest as _pytest

    payload = {
        "fetched_at": "2026-08-25T20:15:00Z",
        "markets": [{
            "ticker": "KXMLBTOTAL-26AUG251840BOSMIA-7",
            "series": "KXMLBTOTAL",
            "title": "Over 7.5 runs scored?",
            "yes_ask_dollars": 0.54,
            "no_ask_dollars": 0.48,
        }],
    }
    monkeypatch = _pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(adapters, "_artifact", lambda parts: (payload, time.time()))
        verdict = adapters.kalshi_outcome("mlb", "2026-08-25")
    finally:
        monkeypatch.undo()

    assert verdict.reason != "markets_key_absent", verdict


def test_every_reader_of_the_kalshi_artifact_goes_through_the_merge_helper():
    """THE SAME BUG THREE TIMES, found one at a time over three hours.

    `kalshi_markets.json` stopped persisting a top-level `markets` key when the
    artifact was split to fit the store's 8MB ceiling. `markets_from_state`
    became the accessor. Readers that were missed, in the order they were
    found:

      venue_quote_adapters.kalshi_outcome      -> markets_key_absent, 0 quotes
      kalshi_polymarket_arb.run_arb_scan       -> no_kalshi_markets
      portfolio_commit._venue_price_resolver   -> (None, None), venue_priced=0

    The third was the worst and the last found, because it did not error:
    `.get("markets") or []` became `[]`, which returns the value meaning "this
    venue has no direct feed" -- indistinguishable from Novig, which genuinely
    has none. Kalshi silently priced off the aggregator while the fan-in was
    producing 2,344 of its own quotes.

    IT WAS HIDDEN BY A `| head -20` ON THE GREP THAT WENT LOOKING FOR IT, so
    this walks the repo rather than trusting anyone to grep exhaustively.

    AND THE FIRST VERSION OF THIS TEST WAS VACUOUS. It scanned a 12-line window
    below each mention of the filename, and the offending line sat 20 lines
    below its own explanatory comment -- so reintroducing the bug still passed.
    A scan is worth exactly what it can be shown to CATCH, which is why the
    partner test reintroduces the defect and asserts this fails.

    Scoped by FUNCTION via the AST rather than by line distance: a module may
    legitimately read some other payload's `markets` key (Polymarket's slate,
    OddsAPI's shard), and flagging those would make this noisy and therefore
    ignored.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = _kalshi_artifact_offenders(root)
    assert not offenders, (
        "these read the Kalshi artifact's top-level `markets` key, which is no "
        "longer persisted; use markets_from_state:\n  " + "\n  ".join(offenders)
    )


def _kalshi_artifact_offenders(root) -> list[str]:
    """Functions that bind `markets` straight off the ARTIFACT PAYLOAD.

    THREE THINGS HAD TO BE RIGHT and the first two versions each got one
    wrong, which is worth stating because a scan is worth exactly what it can
    be shown to catch:

    1. SCOPED TO THE PAYLOAD VARIABLE. `run_arb_scan` legitimately reads
       `kalshi_resolved["markets"]` -- the return value of a resolver, a
       different object that happens to share a key name. Flagging by key name
       alone produced five false positives in one function and would have made
       this noisy enough to ignore.
    2. BINDING, NOT CHECKING. `isinstance(payload.get("markets"), list)` is a
       presence check and must stay: it is how a document carrying neither
       shape is told from one holding no markets. Only an ASSIGNMENT or a
       RETURN turns that value into the markets list.
    3. NO WHOLE-FUNCTION EXEMPTION. An earlier version excused any function
       mentioning `markets_from_state` anywhere, so a function that imported
       the helper and then still read the key directly passed clean -- exactly
       the regression it existed to catch.
    """
    import ast

    artifact = "kalshi_markets.json"
    exempt = {"pipeline/kalshi_odds_refresh.py"}  # defines the fallback itself
    offenders: list[str] = []

    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(("tests/", ".venv/", "vendor/")) or relative in exempt:
            continue
        text = path.read_text(errors="ignore")
        if artifact not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if artifact not in (ast.get_source_segment(text, node) or ""):
                continue

            # Which local names hold the artifact PAYLOAD.
            #
            # Propagated across ONE hop and no further, because the read is
            # usually two statements -- the path is built, then handed to
            # `read_json_file` -- and matching only the statement containing the
            # filename misses the payload itself. The meta-test below is written
            # that way and caught that gap.
            #
            # ONLY THROUGH A READER CALL. Propagating through any call whose
            # argument was tainted marked `kalshi_resolved =
            # resolve_kalshi_moneylines(kalshi_markets, ...)` as a payload, so
            # its perfectly correct `kalshi_resolved["markets"]` was flagged. A
            # resolver returns a NEW object that merely shares a key name.
            readers = {"read_json_file", "_artifact", "read_json"}

            def _called(value) -> str:
                if not isinstance(value, ast.Call):
                    return ""
                func = value.func
                if isinstance(func, ast.Attribute):
                    return func.attr
                if isinstance(func, ast.Name):
                    return func.id
                return ""

            assigns = [
                statement
                for statement in ast.walk(node)
                if isinstance(statement, ast.Assign) and statement.value is not None
            ]
            payloads: set[str] = set()
            for _ in range(len(assigns) + 1):
                grew = False
                for statement in assigns:
                    value = statement.value
                    source = ast.get_source_segment(text, value) or ""
                    referenced = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
                    seeded = artifact in source
                    carried = bool(referenced & payloads) and _called(value) in readers
                    if not (seeded or carried):
                        continue
                    for target in statement.targets:
                        for name in ast.walk(target):
                            if isinstance(name, ast.Name) and name.id not in payloads:
                                payloads.add(name.id)
                                grew = True
                if not grew:
                    break
            if not payloads:
                continue

            for statement in ast.walk(node):
                if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    value = statement.value
                elif isinstance(statement, ast.Return):
                    value = statement.value
                else:
                    continue
                if value is None:
                    continue
                source = ast.get_source_segment(text, value) or ""
                if "markets_from_state" in source:
                    continue
                for inner in ast.walk(value):
                    base = literal = None
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "get"
                        and inner.args
                        and isinstance(inner.args[0], ast.Constant)
                    ):
                        base, literal = inner.func.value, inner.args[0].value
                    elif isinstance(inner, ast.Subscript) and isinstance(
                        inner.slice, ast.Constant
                    ):
                        base, literal = inner.value, inner.slice.value
                    if literal != "markets" or base is None:
                        continue
                    names = {n.id for n in ast.walk(base) if isinstance(n, ast.Name)}
                    if names & payloads:
                        offenders.append(
                            f"{relative}:{getattr(inner, 'lineno', '?')}: in {node.name}()"
                        )
    return offenders


def test_that_scan_actually_catches_a_reintroduced_reader(tmp_path):
    """The partner test. A source scan that cannot be shown to FAIL is
    decoration -- and the first version of the scan above was exactly that."""
    module = tmp_path / "pipeline"
    module.mkdir()
    (module / "regressed.py").write_text(
        'def read_it(payload):\n'
        '    path = reports_root() / "intelligence" / "kalshi_markets.json"\n'
        '    payload = read_json_file(path)\n'
        '    return (payload or {}).get("markets") or []\n'
    )
    assert _kalshi_artifact_offenders(tmp_path), "the scan must catch this"

    (module / "regressed.py").write_text(
        'def read_it(payload):\n'
        '    path = reports_root() / "intelligence" / "kalshi_markets.json"\n'
        '    payload = read_json_file(path)\n'
        '    from pipeline.kalshi_odds_refresh import markets_from_state\n'
        '    return markets_from_state(payload)\n'
    )
    assert not _kalshi_artifact_offenders(tmp_path)
def test_kxmlbhrr_classifies_instead_of_refusing_the_stat():
    """The 136-market refusal, end to end through `classify_market`.

    MEASURED 2026-08-25T20:33:06Z, twelve minutes after the deploy that
    registered `KXMLBHRR`: every one of its 136 markets came back
    `stat_not_in_market_vocabulary detail='hits + runs + RBIs'`. Registering a
    series and being able to READ its markets are two different gates, and
    asserting only the registry is what let this ship.
    """
    from syndicate.features.shared.kalshi_catalogue import classify_market

    verdict = classify_market({
        "series": "KXMLBHRR",
        "title": "William Contreras: 5+ hits + runs + RBIs?",
        "ticker": "KXMLBHRR-26AUG251840MILCHC-MILWCONTRERAS5",
    })

    assert verdict["status"] == "ok", verdict
    assert verdict["market"] == "batter_hits_runs_rbis", verdict
    assert verdict["subject"] == "William Contreras", verdict
    # "5+" is 4.5, never 5.0 and never 5.5. Matching 5+ against a line of 5.0
    # finds nothing; matching it against 5.5 finds a DIFFERENT bet and prices
    # it confidently.
    assert verdict["line"] == 4.5, verdict
    assert verdict["side"] == "over", verdict


def test_kxmlbsb_registers_and_reads():
    """`KXMLBSB` was refused at `unmapped_series` -- the FIRST gate, before any
    title was read -- so its 44 markets were never fetched and the board row
    reported Kalshi as having no market.

    Asserted through `classify_market` rather than against `SERIES_SPORT`
    directly, because a registry line whose stat does not resolve just moves
    the refusal one gate later. That is precisely what `KXMLBHRR` did.
    """
    from syndicate.features.shared.kalshi_catalogue import classify_market

    verdict = classify_market({
        "series": "KXMLBSB",
        "title": "William Contreras: 1+ stolen bases?",
        "ticker": "KXMLBSB-26AUG251840MILCHC-MILWCONTRERAS1",
    })

    assert verdict["status"] == "ok", verdict
    assert verdict["market"] == "batter_stolen_bases", verdict
    assert verdict["subject"] == "William Contreras", verdict
    assert verdict["line"] == 0.5, verdict
    assert verdict["side"] == "over", verdict
    # A prop names a human, so it needs no event resolution to be joinable.
    assert verdict["needs_event_identity"] is False, verdict


def test_neither_new_series_is_reported_as_a_coverage_gap_any_more():
    """`unmapped_series` is the WORK QUEUE. A series that now classifies must
    leave it, or the queue keeps naming work that is already done and stops
    being read -- the same reason `SERIES_OUT_OF_SCOPE` exists."""
    from syndicate.features.shared.kalshi_catalogue import unmapped_series

    gaps = unmapped_series([
        {"series": "KXMLBHRR", "title": "William Contreras: 5+ hits + runs + RBIs?"},
        {"series": "KXMLBSB", "title": "William Contreras: 1+ stolen bases?"},
    ])

    assert gaps == {}, gaps
