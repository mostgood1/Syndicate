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
    """The two halves must be built by ONE resolver or they drift apart."""
    row = {"sport": "mlb", "market": "h2h", "side": "home", "line": None,
           "home_team": "Arizona Diamondbacks", "away_team": "Chicago Cubs"}

    assert _candidate_keys(row, "mlb") == ["mlb|h2h|home", "mlb|h2h|arizona diamondbacks"]


def test_the_ROLE_key_is_still_tried_FIRST_so_nothing_that_worked_breaks():
    """Additive by construction. Kalshi and OddsAPI keep their key shape."""
    row = {"sport": "mlb", "market": "h2h", "side": "away", "line": None,
           "home_team": "Arizona Diamondbacks", "away_team": "Chicago Cubs"}

    keys = _candidate_keys(row, "mlb")

    assert keys[0] == "mlb|h2h|away"
    assert keys[1] == "mlb|h2h|chicago cubs"


def test_an_unresolvable_club_adds_NO_second_key(monkeypatch):
    """A bare team string would build a key matching nothing while hiding that
    the row could not be placed."""
    row = {"sport": "mlb", "market": "h2h", "side": "home", "line": None,
           "home_team": "Not A Real Club", "away_team": "Chicago Cubs"}

    assert _candidate_keys(row, "mlb") == ["mlb|h2h|home"]


def test_an_unresolvable_club_at_the_VENUE_is_counted_by_name(_slate_of):
    """`canonical_team` resolves a wnba nickname but NOT an mlb one -- "Padres"
    returns None. Production sends mlb clubs in full today, so nothing is lost
    right now; the counter is what makes the day that changes visible instead
    of a feed that quietly halves."""
    _slate_of(_moneyline("aec-mlb-pit-sd-2026-08-24", ["Pirates", "Padres"]))

    outcome = adapters.polymarket_us_outcome("mlb", "2026-08-24")

    assert outcome.quotes == []
    assert "clubs_unresolved" in (outcome.reason or ""), outcome.reason
    assert "Padres" in outcome.reason


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
