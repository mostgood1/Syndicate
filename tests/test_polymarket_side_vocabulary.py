"""Polymarket sides, translated into the vocabulary the board actually asks in.

MEASURED 2026-08-25T00:46:19Z -- `VENUE_REPRICE_KEYS`, the first log line to
print both halves of the join side by side:

    board wanted      mlb|h2h|home            mlb|totals|over|6.5
    polymarket gave   mlb|h2h|chicago cubs    mlb|spreads|-2.50

polymarket_us offered 3,106 quotes across mlb/wnba/nfl and won ZERO of 237
selections while every other counter looked like a working feed. Not a
freshness loss -- the two sides never shared a key space at all, exactly as the
OddsAPI adapter had not for an entire evening.

Three distinct mismatches were in that one line:
  1. h2h side is a ROLE on the board, an IDENTITY at the venue.
  2. spreads keys differ in LENGTH -- `spreads|away|-1.5` (4 parts) against
     `spreads|-2.50` (3), the handicap standing in for the side and no line.
  3. totals carried no line at all, because `row["line"]` is absent on the
     persisted rows and only the slug has the number.
"""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared import venue_quote_adapters as adapters
from syndicate.features.shared.venue_quote_fanin import _candidate_keys, apply_venue_quotes


def _slate(*markets):
    return {"fetched_at": time.time(), "markets": list(markets)}


def _moneyline(slug, outcomes, prices=('0.55', '0.45')):
    return {"slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
            "outcomes": str(list(outcomes)).replace("'", '"'),
            "outcomePrices": str(list(prices)).replace("'", '"')}


def _total(slug):
    return {"slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
            "outcomes": '["Over","Under"]', "outcomePrices": '["0.52","0.48"]'}


def _spread(slug):
    return {"slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD",
            "outcomes": '["-1.50","+1.50"]', "outcomePrices": '["0.5","0.5"]'}


@pytest.fixture
def _slate_of(monkeypatch):
    def install(*markets):
        payload = _slate(*markets)
        monkeypatch.setattr(adapters, "_artifact", lambda _p: (payload, time.time()))
    return install


# ---------------------------------------------------------------------------
# 1. h2h -- role against identity
# ---------------------------------------------------------------------------


def test_a_moneyline_is_keyed_by_the_CANONICAL_CLUB_not_the_venues_wording(_slate_of):
    _slate_of(_moneyline("aec-mlb-chc-ari-2026-08-24",
                         ["Chicago Cubs", "Arizona Diamondbacks"]))

    keys = {q.key for q in adapters.polymarket_us_outcome("mlb", "2026-08-24").quotes}

    assert keys == {"mlb|h2h|chicago cubs", "mlb|h2h|arizona diamondbacks"}


def test_a_wnba_NICKNAME_resolves_to_the_same_canonical_club(_slate_of):
    """Production sends bare nicknames for wnba (`sky`, `sun`, `wings`) and full
    names for mlb. One resolver has to absorb both."""
    _slate_of(_moneyline("aec-wnba-chi-con-2026-08-24", ["Sky", "Sun"]))

    keys = {q.key for q in adapters.polymarket_us_outcome("wnba", "2026-08-24").quotes}

    assert keys == {"wnba|h2h|chicago sky", "wnba|h2h|connecticut sun"}


def test_the_board_row_derives_the_SAME_key_from_its_own_teams():
    """The two halves must be built by ONE resolver or they drift apart.

    ASSERTION WIDENED 2026-08-27, and the reason is worth keeping. This read
    `== ["mlb|h2h|home", "mlb|h2h|arizona diamondbacks"]` and had been FAILING
    since `0acabd09` the same evening, which added a third key shape -- the
    city/nickname token, so a Kalshi quote titled "Arizona wins" can be met --
    and shipped its own suite (`test_kalshi_side_vocabulary.py`) without
    touching this file's exact-equality assertions. The commit reported "655
    tests green" over a filtered set that did not include this one.

    The property this test is named for is unharmed: role key first, club key
    second, both from `canonical_team`. The token keys ride behind them.
    """
    row = {"sport": "mlb", "market": "h2h", "side": "home", "line": None,
           "home_team": "Arizona Diamondbacks", "away_team": "Chicago Cubs"}

    assert _candidate_keys(row, "mlb") == [
        "mlb|h2h|home",
        "mlb|h2h|arizona diamondbacks",
        "mlb|h2h|arizona",
        "mlb|h2h|diamondbacks",
    ]


def test_the_ROLE_key_is_still_tried_FIRST_so_nothing_that_worked_breaks():
    """Additive by construction. Kalshi and OddsAPI keep their key shape."""
    row = {"sport": "mlb", "market": "h2h", "side": "away", "line": None,
           "home_team": "Arizona Diamondbacks", "away_team": "Chicago Cubs"}

    keys = _candidate_keys(row, "mlb")

    assert keys[0] == "mlb|h2h|away"
    assert keys[1] == "mlb|h2h|chicago cubs"


def test_an_unresolvable_club_adds_NO_second_key(monkeypatch):
    """A bare team string would build a key matching nothing while hiding that
    the row could not be placed.

    THIS ONE WAS NOT A STALE ASSERTION -- it was reporting a real defect, and
    had been since `0acabd09`. That commit's city/nickname block called
    `team_quote_token`, which falls back to a normalised RAW string when
    `canonical_team` returns None. That fallback is CORRECT at the venue
    (Kalshi says "Texas" and no club map carries it) and wrong on the board
    side, so "Not A Real Club" offered four keys made of words with no team
    behind them: `mlb|h2h|club`, `mlb|h2h|not`, `mlb|h2h|real`, and the whole
    raw string. `real` is a live soccer token. It contradicted the refusal
    written three lines above it in the same function.
    """
    row = {"sport": "mlb", "market": "h2h", "side": "home", "line": None,
           "home_team": "Not A Real Club", "away_team": "Chicago Cubs"}

    assert _candidate_keys(row, "mlb") == ["mlb|h2h|home"]


def test_a_sport_with_NO_club_map_offers_no_token_keys():
    """The absence has to be present, or the rule above is only tested where a
    map exists to disagree with.

    `_alias_map` returns `{}` for ncaaf, ncaab and nhl, so nothing in those
    sports can be shown unambiguous. Before the guard, every one of their rows
    fell through the raw-string path -- "Ohio State Buckeyes" against "Michigan
    Wolverines" offered `ncaaf|h2h|state`, a word shared by a large fraction of
    the sport. NCAAF reached the board side on 2026-08-27.
    """
    row = {"sport": "ncaaf", "market": "h2h", "side": "home", "line": None,
           "home_team": "Ohio State Buckeyes", "away_team": "Michigan Wolverines"}

    assert _candidate_keys(row, "ncaaf") == ["ncaaf|h2h|home"]


def test_a_token_SHARED_ACROSS_THE_SPORT_is_refused_even_against_a_clean_opponent():
    """The bound is the sport's vocabulary, not the row's opponent.

    Manchester City v Arsenal share no words, so the opponent subtraction --
    the only check that existed before -- passes `city` and `manchester`
    straight through. `apply_venue_quotes` then resolves that key against the
    sport's WHOLE quote pool, where `city` names 14 clubs and Bristol City's
    quote from another fixture answers to it just as well.
    """
    row = {"sport": "soccer", "market": "h2h", "side": "home", "line": None,
           "home_team": "Manchester City", "away_team": "Arsenal"}

    keys = _candidate_keys(row, "soccer")

    assert keys == ["soccer|h2h|home", "soccer|h2h|manchester city"]
    assert "soccer|h2h|city" not in keys
    assert "soccer|h2h|manchester" not in keys


def test_an_UNAMBIGUOUS_token_still_survives_so_the_guard_is_not_a_blanket_refusal():
    """Paired with the two refusals above deliberately: a filter that dropped
    everything would pass both of them and take the Kalshi city match with it.

    "Texas" is the measured case `0acabd09` was built for -- Kalshi titles say
    "Texas wins", the board carries "Texas Rangers" -- and it names exactly one
    MLB club, so it must still be offered.
    """
    row = {"sport": "mlb", "market": "h2h", "side": "home", "line": None,
           "home_team": "Texas Rangers", "away_team": "Chicago White Sox"}

    keys = _candidate_keys(row, "mlb")

    assert "mlb|h2h|texas" in keys
    assert "mlb|h2h|rangers" in keys
    # The opponent's own tokens are ambiguous sport-wide and must not appear on
    # either side of this game.
    assert "mlb|h2h|chicago" not in keys
    assert "mlb|h2h|sox" not in keys


def test_an_unresolvable_club_at_the_VENUE_is_counted_by_name(_slate_of):
    """The counter is what makes a vocabulary gap visible instead of a feed
    that quietly halves.

    FIXTURE CHANGED 2026-08-27, and the reason is the point. This used to send
    `["Pirates", "Padres"]`, because `canonical_team` resolved a WNBA nickname
    and not an MLB one -- exactly as this docstring used to say. That gap is now
    closed (nicknames are derived from the alias map's own values), so those two
    RESOLVE and can no longer stand in for an unresolvable club.

    "Sox" is the replacement and is a better one: it is ambiguous by nature --
    it names both Chicago and Boston -- so it is refused BY DESIGN rather than
    by omission, and no future alias work can quietly resolve it. Paired with a
    nonsense token so the read still yields no quotes at all.
    """
    _slate_of(_moneyline("aec-mlb-sox-xxx-2026-08-24", ["Sox", "Not A Real Club"]))

    outcome = adapters.polymarket_us_outcome("mlb", "2026-08-24")

    assert outcome.quotes == []
    assert "clubs_unresolved" in (outcome.reason or ""), outcome.reason
    assert "Sox" in outcome.reason


# ---------------------------------------------------------------------------
# 2. spreads -- refused by name, not guessed
# ---------------------------------------------------------------------------


def test_a_spread_is_REFUSED_and_counted_rather_than_guessed(_slate_of):
    """Nothing measured says WHICH team a handicap belongs to. Guessing is the
    error the sign-token trap already cost once: 1 of 5 sampled rows would have
    been priced on the opposite handicap."""
    _slate_of(_moneyline("aec-mlb-chc-ari-2026-08-24", ["Chicago Cubs", "Arizona Diamondbacks"]),
              _spread("asc-mlb-chc-ari-2026-08-24-gs-neg-1pt5"))

    outcome = adapters.polymarket_us_outcome("mlb", "2026-08-24")

    assert not any("spreads" in q.key for q in outcome.quotes)
    # Carried on a SUCCESSFUL read: a drop only visible when everything else
    # fails is a drop nobody reads.
    assert outcome.status == "ok"
    assert "spreads_refused:1" in (outcome.reason or "")


def test_a_league_of_ONLY_spreads_says_so_rather_than_looking_empty(_slate_of):
    """"not listed here" and "listed but unplaceable" are different work."""
    _slate_of(_spread("asc-nfl-lac-ten-2026-08-28-gs-neg-21pt5"))

    outcome = adapters.polymarket_us_outcome("nfl", "2026-08-28")

    assert outcome.status == "no_rows"
    assert "no_placeable_polymarket_row_for_league_nfl" in outcome.reason
    assert "spreads_refused:1" in outcome.reason


# ---------------------------------------------------------------------------
# 3. totals -- the line comes from the slug when the row omits it
# ---------------------------------------------------------------------------


def test_a_total_takes_its_line_from_the_SLUG_when_the_row_has_none(_slate_of):
    """MEASURED: the offered keys carried no line at all, because `row["line"]`
    is absent on the persisted rows. `totals|over` with no number would match
    any line -- worse than matching none."""
    _slate_of(_total("tsc-mlb-chc-ari-2026-08-24-tg-8pt5"))

    keys = {q.key for q in adapters.polymarket_us_outcome("mlb", "2026-08-24").quotes}

    assert keys == {"mlb|totals|over|8.5", "mlb|totals|under|8.5"}


def test_a_total_with_NO_line_anywhere_is_refused(_slate_of):
    _slate_of(_total("tsc-mlb-chc-ari-2026-08-24-tg"))

    assert adapters.polymarket_us_outcome("mlb", "2026-08-24").quotes == []


def test_a_SEGMENT_total_is_not_keyed_as_a_full_game_total(_slate_of):
    """The board's `totals` means the whole game. A first-quarter market keyed
    plain `totals` would re-price a full-game row at a period's number --
    `polymarket_board_join` already refuses these and the two consumers of this
    venue must not disagree."""
    _slate_of(_total("tsc-mlb-chc-ari-2026-08-24-1q-3pt5"))

    assert adapters.polymarket_us_outcome("mlb", "2026-08-24").quotes == []


# ---------------------------------------------------------------------------
# End to end -- the rows that produced the measured zero now stamp
# ---------------------------------------------------------------------------


def test_the_board_rows_that_matched_NOTHING_now_get_priced(_slate_of):
    _slate_of(
        _moneyline("aec-mlb-chc-ari-2026-08-24", ["Chicago Cubs", "Arizona Diamondbacks"]),
        _total("tsc-mlb-chc-ari-2026-08-24-tg-8pt5"),
        _moneyline("aec-wnba-chi-con-2026-08-24", ["Sky", "Sun"], prices=("0.4", "0.6")),
    )
    rows = [
        {"sport": "mlb", "market": "h2h", "side": "home", "line": None,
         "home_team": "Arizona Diamondbacks", "away_team": "Chicago Cubs"},
        {"sport": "mlb", "market": "totals", "side": "over", "line": 8.5},
        {"sport": "wnba", "market": "h2h", "side": "away", "line": None,
         "home_team": "Connecticut Sun", "away_team": "Chicago Sky"},
    ]

    result = apply_venue_quotes(rows, "2026-08-24")

    assert result["stamped"] == 3, result["unmatched_sample"]
    assert result["selected_by_source"] == {"polymarket_us": 3}
    assert result["unmatched_sample"] == []
