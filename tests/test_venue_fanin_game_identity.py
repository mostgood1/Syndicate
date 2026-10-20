"""A venue quote for ANOTHER DATE is not this row's price (lane `venue-fanin-game-identity`).

MEASURED on the fleet's Layer 2 shortlist 2026-10-20 18:10Z (2,000 rows): 35 of
the 87 rows carrying a Kalshi `venue_ref` held a ticker for a DIFFERENT game --
NCAAF 24 of 29, soccer 9 of 17, NHL 2 of 2 -- and Polymarket 2 of 136 dated
slugs. One was `suggested`:

    UM @ TRO   2026-10-24   KXNCAAFGAME-26OCT29TROYJMU-TROY   (Troy v JMU, 10-29)
    DET @ SEA  2026-10-20   KXNHLGAME-26OCT26DETEDM-DET       best_any_book kalshi +144
    PHI @ NYK  2026-10-20   tsc-nba-gs-lal-2026-10-21-232pt5  (a GS@LAL total)

WHY NOTHING REFUSED THEM. Every existing guard is about the GAME TOKEN, and on
exactly these rows neither half can be named:

* `game_token` returns None for NCAAF (deliberately) and for NHL (no club map),
  so `Quote.game` is None and `_quote_is_for_another_game` cannot prove a
  mismatch.
* An h2h key is the CLUB (`ncaaf|h2h|<club>`), and `_key_claimants` maps role
  keys only, so the club key is "uncontested" and
  `_unconfirmed_on_a_contested_key` lets it through.
* `kalshi_outcome` never reads `selected_date`; `kalshi_markets.json` carries
  every listed date, so next week's game of the same club answers this week's
  row.

THE RULE. The venue's own identifier carries the fixture's date (Kalshi ticker
`-26OCT29...`, Polymarket slug `...-2026-10-21`). When it does and it is not the
row's own game date, the quote is refused and COUNTED. Unknown on either side
is not a mismatch here; that is the existing guards' job.
"""

from __future__ import annotations

from syndicate.features.shared.venue_quote_fanin import (
    Quote,
    _h2h_alias_keys_shaped,
    _quote_is_for_another_date,
    apply_venue_quotes,
    apply_venue_quotes_to_grid,
)

NOW = 1_000_010.0


def _grid_h2h(sport, event_id, away, home, commence_time):
    """A grid h2h row whose book price is STALE, so a matching venue quote WOULD
    win the freshness check -- "0 repriced" is then evidence of the refusal,
    not of an inert fixture."""
    return {
        "sport": sport, "event_id": event_id, "market": "h2h", "line": None,
        "away_team": away, "home_team": home, "commence_time": commence_time,
        "sides": ["home", "away"],
        "best": {
            "home": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
            "away": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
        },
        "game": {"state": "pregame"},
    }


def _grid_totals(sport, event_id, away, home, commence_time, line):
    row = _grid_h2h(sport, event_id, away, home, commence_time)
    row.update({"market": "totals", "line": line, "sides": ["over", "under"]})
    row["best"] = {
        "over": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
        "under": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
    }
    return row


def _club_key(row, side):
    """The club key the fan-in itself asks for -- read from its own builder, so
    the test cannot drift from the vocabulary production uses."""
    shaped = _h2h_alias_keys_shaped(row, row["sport"], "h2h", side, [])
    assert shaped, f"the fan-in offers no club key for {row['home_team']!r}"
    return shaped[0][1]


def _kalshi(key, ticker, *, probability=0.30):
    from syndicate.features.shared.venue_quote_adapters import probability_to_american

    return Quote(
        key=key, source="kalshi", sport="", market="h2h", side="", line=None,
        probability=probability, american=probability_to_american(probability),
        fetched_at=1_000_000.0, venue_ref=ticker, game=None,
    )


# --- the measured defect, on the grid path (the one the board build runs) ----


def test_ncaaf_h2h_takes_no_kalshi_quote_for_the_clubs_NEXT_game():
    row = _grid_h2h("ncaaf", "evt-um-tro", "UL Monroe Warhawks", "Troy Trojans",
                    "2026-10-24T20:00:00Z")
    key = _club_key(row, "home")
    foreign = _kalshi(key, "KXNCAAFGAME-26OCT29TROYJMU-TROY")

    out = apply_venue_quotes_to_grid(
        [row], "ncaaf", "2026-10-20", now=NOW, collected={"quotes": {key: foreign}}
    )

    assert out["repriced"] == 0, "Troy v JMU (10-29) priced UM @ TRO (10-24)"
    assert out["cross_date_rejected"] == 1
    assert row["best"]["home"]["bookmaker"] == "draftkings"
    assert "venue_ref" not in row["best"]["home"]


def test_the_SAME_quote_dated_for_this_game_still_prices_it():
    """The positive control. Without it the refusal above would pass against an
    implementation that refuses every Kalshi h2h quote."""
    row = _grid_h2h("ncaaf", "evt-um-tro", "UL Monroe Warhawks", "Troy Trojans",
                    "2026-10-24T20:00:00Z")
    key = _club_key(row, "home")
    own = _kalshi(key, "KXNCAAFGAME-26OCT24ULMTROY-TROY")

    out = apply_venue_quotes_to_grid(
        [row], "ncaaf", "2026-10-20", now=NOW, collected={"quotes": {key: own}}
    )

    assert out["cross_date_rejected"] == 0
    assert out["repriced"] == 1
    assert row["best"]["home"]["bookmaker"] == "kalshi"


def test_nhl_h2h_takes_no_kalshi_quote_for_another_date():
    """DET @ SEA carried `KXNHLGAME-26OCT26DETEDM-DET` and showed kalshi +144 as
    its best price against a ~-110 consensus."""
    row = _grid_h2h("nhl", "evt-det-sea", "Detroit Red Wings", "Seattle Kraken",
                    "2026-10-21T01:50:00Z")
    key = _club_key(row, "away")
    foreign = _kalshi(key, "KXNHLGAME-26OCT26DETEDM-DET", probability=0.41)

    out = apply_venue_quotes_to_grid(
        [row], "nhl", "2026-10-20", now=NOW, collected={"quotes": {key: foreign}}
    )

    assert out["repriced"] == 0
    assert out["cross_date_rejected"] == 1
    assert row["best"]["away"]["price"] == -110


def test_a_polymarket_total_dated_for_another_game_is_refused():
    """PHI @ NYK (10-20) carried a GS @ LAL 10-21 total. The slug's date is the
    only identity the quote has -- its `game` is None on this path."""
    row = _grid_totals("nba", "evt-phi-nyk", "Philadelphia 76ers", "New York Knicks",
                       "2026-10-20T23:30:00Z", 232.5)
    foreign = Quote(
        key="nba|totals|over|232.5", source="polymarket_us", sport="nba",
        market="totals", side="over", probability=0.5, american=-100, line=232.5,
        fetched_at=1_000_000.0, venue_ref="tsc-nba-gs-lal-2026-10-21-232pt5", game=None,
    )

    out = apply_venue_quotes_to_grid(
        [row], "nba", "2026-10-20", now=NOW, collected={"quotes": {foreign.key: foreign}}
    )

    assert out["repriced"] == 0
    assert out["cross_date_rejected"] == 1


# --- the date rule itself ----------------------------------------------------


def test_a_late_kickoff_is_dated_by_the_US_calendar_not_UTC():
    """AF @ WYO kicks off 2026-10-24T01:00Z, which is Friday 10-23 8:00 PM CT,
    and Kalshi dates it `26OCT23` (measured on the same board). Comparing UTC
    dates would refuse every evening game in the country."""
    row = {"commence_time": "2026-10-24T01:00:00Z"}
    assert not _quote_is_for_another_date(
        _kalshi("k", "KXNCAAFGAME-26OCT23AFAWYO-AFA"), row
    )
    # A Hawaii-time kickoff (09:00Z = 11 PM HST the previous day) is on the
    # previous local date; either US calendar date is accepted, nothing wider.
    late = {"commence_time": "2026-10-25T09:00:00Z"}
    assert not _quote_is_for_another_date(_kalshi("k", "KXNCAAFGAME-26OCT24HAWUNLV-HAW"), late)
    assert not _quote_is_for_another_date(_kalshi("k", "KXNCAAFGAME-26OCT25HAWUNLV-HAW"), late)
    assert _quote_is_for_another_date(_kalshi("k", "KXNCAAFGAME-26OCT27HAWUNLV-HAW"), late)


def test_unknown_on_either_side_is_not_a_date_mismatch():
    """No date in the identifier (Polymarket soccer slugs carry none: 126 of 126
    on the measured board) or no kickoff on the row is UNKNOWN, which the game
    guards own. This rule refuses only what it can prove."""
    undated = Quote(
        key="k", source="polymarket_us", sport="soccer", market="h2h", side="",
        probability=0.5, american=-100, line=None, fetched_at=1.0,
        venue_ref="atc-sea-liv-vil", game=None,
    )
    assert not _quote_is_for_another_date(undated, {"commence_time": "2026-10-20T19:00:00Z"})
    assert not _quote_is_for_another_date(
        _kalshi("k", "KXNHLGAME-26OCT26DETEDM-DET"), {"commence_time": None}
    )
    assert not _quote_is_for_another_date(
        _kalshi("k", None), {"commence_time": "2026-10-20T19:00:00Z"}
    )


# --- the candidate path must agree with the grid path ------------------------


def test_the_CANDIDATE_path_refuses_it_too():
    """`apply_venue_quotes` and the grid path must agree about a row's identity;
    a join that works on whichever one you read is the failure `#603` paid for."""
    row = {
        "sport": "ncaaf", "event_id": "evt-um-tro", "market": "h2h", "side": "home",
        "line": None, "away_team": "UL Monroe Warhawks", "home_team": "Troy Trojans",
        "commence_time": "2026-10-24T20:00:00Z",
    }
    from syndicate.features.shared.venue_quote_fanin import _candidate_keys

    # Every key the candidate path asks for answers with the foreign quote, so
    # the outcome cannot depend on which shape that path happens to try first.
    keys = [str(k) for k in _candidate_keys(row, "ncaaf")]
    assert keys, "the candidate path offers no key for an ncaaf h2h row"
    foreign = {k: _kalshi(k, "KXNCAAFGAME-26OCT29TROYJMU-TROY") for k in keys}

    out = apply_venue_quotes(
        [row], "2026-10-20", collected_by_sport={"ncaaf": {"quotes": foreign}}, now=NOW
    )

    assert out["cross_date_rejected"] >= 1
    assert out["stamped"] == 0
