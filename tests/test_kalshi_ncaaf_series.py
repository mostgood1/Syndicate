"""NCAAF Kalshi moneylines reach the board (lane kalshi-ncaaf-series).

Measured 2026-10-16 04:12Z on the fleet's `kalshi_markets.json`: all 400
`KXNCAAFGAME` markets classified `unmapped_series`, so 51 Kalshi-best NCAAF h2h
rows on the 10-16 shortlist priced from the aggregator with no ticker and could
not be placed.

Every fixture below is a REAL Kalshi ticker and title, and goes through
`join_kalshi_to_board` end to end and then through the resolvers the commit
builds -- a helper-level test is how a grammar shipped inert once already.

THE ORDER BUILDER BUYS YES ON WHATEVER TICKER AN h2h ROW CARRIES
(`kalshi_orders._side_to_kalshi`), so each club's row may only ever be matched
from its own `-CODE` market, on YES.

Needs the NCAAF team registry under `data/`: run with `SYNDICATE_DATA_ROOT`
pointing at a tree that has it (the primary checkout's mirror).
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.kalshi_board_join import (
    REASON_ML_OTHER_CLUB,
    REASON_NO_BOARD_ROW,
    REASON_TEAM_SIDE_UNRESOLVED,
    REASON_UNMAPPED_SERIES,
    _side_for_team,
    join_kalshi_to_board,
    kalshi_price_resolver,
    kalshi_ticker_resolver,
)
from syndicate.features.shared.kalshi_catalogue import (
    classify_market,
    segment_for_series,
    sport_for_series,
)


def _registry_available() -> bool:
    from syndicate.features.shared.team_aliases import chip_join_key

    return chip_join_key("ncaaf", "Troy Trojans") is not None


pytestmark = pytest.mark.skipif(
    not _registry_available(),
    reason="NCAAF team registry not on disk; set SYNDICATE_DATA_ROOT to a data/ mirror",
)


def _market(ticker, title, yes, no):
    return {
        "ticker": ticker,
        "series": ticker.split("-", 1)[0],
        "title": title,
        "yes_american": yes,
        "no_american": no,
        "yes_probability": 0.6,
        "no_probability": 0.4,
    }


def _rows(away, home, event_id):
    return [
        {
            "sport": "ncaaf",
            "event_id": event_id,
            "market": "h2h",
            "away_team": away,
            "home_team": home,
            "side": side,
            "line": None,
            "segment": "full",
            "model_edge_pct": 2.0,
            "quote": {"bookmaker": "kalshi", "price": 100},
        }
        for side in ("away", "home")
    ]


def _join(markets, rows, monkeypatch, date):
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    return join_kalshi_to_board(markets, rows, selected_date=date)


def _resolved(report, row):
    matches = report["matches"]
    return kalshi_price_resolver(matches)(row), kalshi_ticker_resolver(matches)(row)


# Southern Miss @ Troy, 2026-10-06; James Madison @ Georgia Southern and
# South Carolina St. (FCS) @ Charleston Southern (FCS), 2026-10-10. Copied from
# the fleet's kalshi_markets.json.
_USM_TROY = [
    _market("KXNCAAFGAME-26OCT06USMTROY-USM", "Southern Miss wins", 150, -170),
    _market("KXNCAAFGAME-26OCT06USMTROY-TROY", "Troy wins", -160, 140),
]
_JMU_GASO = [
    _market("KXNCAAFGAME-26OCT10JMUGASO-JMU", "James Madison wins", -400, 320),
    _market("KXNCAAFGAME-26OCT10JMUGASO-GASO", "Georgia Southern wins", 310, -390),
]
_SCST_CHSO = [
    _market("KXNCAAFGAME-26OCT10SCSTCHSO-SCST", "South Carolina St. wins", 120, -140),
    _market("KXNCAAFGAME-26OCT10SCSTCHSO-CHSO", "Charleston Southern wins", -130, 110),
]


def test_kxncaafgame_is_a_registered_full_game_ncaaf_series():
    assert sport_for_series("KXNCAAFGAME") == "ncaaf"
    assert segment_for_series("KXNCAAFGAME") == "full"
    verdict = classify_market(_USM_TROY[1])
    assert verdict.get("status") == "ok", verdict
    assert verdict["market"] == "h2h"
    assert verdict.get("reason") != REASON_UNMAPPED_SERIES


@pytest.mark.parametrize(
    "markets, away, home, event_id, date",
    [
        (_USM_TROY, "Southern Miss Golden Eagles", "Troy Trojans", "evt-usm-troy", "2026-10-06"),
        (_JMU_GASO, "James Madison Dukes", "Georgia Southern Eagles", "evt-jmu-gaso", "2026-10-10"),
        # FCS on both sides: the FBS-only alias map cannot name either club.
        (_SCST_CHSO, "South Carolina State Bulldogs", "Charleston Southern Buccaneers",
         "evt-scst-chso", "2026-10-10"),
    ],
)
def test_ncaaf_moneyline_each_row_takes_its_own_clubs_contract_on_yes(
    markets, away, home, event_id, date, monkeypatch
):
    rows = _rows(away, home, event_id)
    for order in (markets, list(reversed(markets))):
        report = _join(order, rows, monkeypatch, date)
        reasons = report["reasons"]
        assert reasons.get(REASON_UNMAPPED_SERIES) is None, reasons
        assert reasons.get(REASON_NO_BOARD_ROW) is None, reasons
        assert reasons.get(REASON_TEAM_SIDE_UNRESOLVED) is None, reasons
        pairs = {(m["board_side"], m["kalshi_side"], m["ticker"]) for m in report["matches"]}
        assert pairs == {
            ("away", "yes", markets[0]["ticker"]),
            ("home", "yes", markets[1]["ticker"]),
        }, pairs
        # The other club's row is never priced off this contract's NO leg.
        assert reasons.get(REASON_ML_OTHER_CLUB) == 2, reasons
        assert _resolved(report, rows[0]) == (markets[0]["yes_american"], markets[0]["ticker"])
        assert _resolved(report, rows[1]) == (markets[1]["yes_american"], markets[1]["ticker"])


def test_every_ncaaf_moneyline_match_is_the_leg_the_order_builder_buys(monkeypatch):
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    report = _join(_USM_TROY, _rows("Southern Miss Golden Eagles", "Troy Trojans", "e1"),
                   monkeypatch, "2026-10-06")
    assert len(report["matches"]) == 2
    for match in report["matches"]:
        assert _side_to_kalshi(match["board_side"], match["market"], match["line"]) == (
            match["kalshi_side"]
        ), match


@pytest.mark.parametrize(
    "kalshi_name, away, home, expected",
    [
        ("South Carolina St.", "South Carolina State Bulldogs", "Charleston Southern Buccaneers", "away"),
        ("North Texas", "Charlotte 49ers", "North Texas Mean Green", "home"),
        ("Appalachian St.", "Old Dominion Monarchs", "Appalachian State Mountaineers", "home"),
        ("Kennesaw St.", "Kennesaw State Owls", "Missouri State Bears", "away"),
        ("Miami (OH)", "Miami (OH) RedHawks", "Ohio Bobcats", "away"),
    ],
)
def test_side_for_team_places_kalshis_ncaaf_spellings(kalshi_name, away, home, expected):
    resolution = {"away_team": away, "home_team": home}
    assert _side_for_team(kalshi_name, resolution, sport="ncaaf") == expected


@pytest.mark.parametrize(
    "kalshi_name, away, home",
    [
        # A club playing in neither slot.
        ("Troy", "Southern Miss Golden Eagles", "Georgia Southern Eagles"),
        # "Miami" (FL) is not Miami (OH): never folded onto the other school.
        ("Miami (FL)", "Miami (OH) RedHawks", "Ohio Bobcats"),
        # A Kalshi spelling no registry entry places.
        ("Florida Intl.", "Florida International Panthers", "Liberty Flames"),
        # "Texas" sits inside "North Texas": the subset fallback must not take it.
        ("Texas", "North Texas Mean Green", "Rice Owls"),
    ],
)
def test_side_for_team_refuses_an_ncaaf_name_it_cannot_place(kalshi_name, away, home):
    resolution = {"away_team": away, "home_team": home}
    assert _side_for_team(kalshi_name, resolution, sport="ncaaf") is None


def test_ncaaf_full_game_spread_names_the_club_that_must_cover(monkeypatch):
    """`KXNCAAFSPREAD` is a MARGIN: "Kennesaw St. wins by over 7.5 points" is the
    board's KENN -7.5 (YES) and JVST +7.5 (NO). The NO leg on the other club is
    correct for a two-way spread, unlike a moneyline."""
    assert sport_for_series("KXNCAAFSPREAD") == "ncaaf"
    assert segment_for_series("KXNCAAFSPREAD") == "full"
    market = _market(
        "KXNCAAFSPREAD-26OCT07JVSTKENN-KENN8",
        "Kennesaw St. wins by over 7.5 points",
        130,
        -150,
    )
    rows = [
        {
            "sport": "ncaaf",
            "event_id": "evt-jvst-kenn",
            "market": "spreads",
            "away_team": "Jacksonville State Gamecocks",
            "home_team": "Kennesaw State Owls",
            "side": side,
            "line": line,
            "segment": "full",
        }
        for side, line in (("away", 7.5), ("home", -7.5))
    ]
    # The event's own moneyline markets ride along, as on the fleet: they are
    # where the join learns Kalshi's code -> name pairing (`JVST`, `KENN`).
    game = [
        _market("KXNCAAFGAME-26OCT07JVSTKENN-JVST", "Jacksonville St. wins", 200, -240),
        _market("KXNCAAFGAME-26OCT07JVSTKENN-KENN", "Kennesaw St. wins", -250, 210),
    ]
    report = _join([market, *game], rows, monkeypatch, "2026-10-07")
    report["matches"] = [m for m in report["matches"] if m["market"] == "spreads"]
    by_side = {m["board_side"]: m for m in report["matches"]}
    assert set(by_side) == {"away", "home"}, report["reasons"]
    assert (by_side["home"]["kalshi_side"], by_side["home"]["line"]) == ("yes", -7.5)
    assert (by_side["away"]["kalshi_side"], by_side["away"]["line"]) == ("no", 7.5)
