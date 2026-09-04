"""The live LANE is restated from the scoreboard chip, and the join must not be
an exact name match between two different feeds.

USER-REPORTED 2026-09-04T00:3xZ: "we still dont have any NCAAF live lines
hitting the layer 2 board", with 9 of 11 NCAAF chips reading `state=live` and
carrying real scores.

MEASURED on the served board the same minute:

    sport   rows    (market_state, lane)
    mlb    3,100    (live, live)    104     <- works
    ncaaf  6,240    (live, pregame) 184     <- EVERY live row stuck pregame

288 rows carried `market_state: live`; only 104 carried `lane: live`, all MLB.

`_refresh_layer2_live_state` indexed chips by `(sport, away.name, home.name)`
lowercased and looked cards up by `(sport, away_team, home_team)` lowercased.
The feeds disagree:

    chip away.name          card away_team
    "Akron"                 "Akron Zips"
    "Colorado"              "Colorado Buffaloes"
    "Massachusetts"         "UMass Minutemen"
    "San Francisco Giants"  "San Francisco Giants"   <- why MLB was fine

So MLB worked by luck of naming and NCAAF could never match. This is the SECOND
place the same two feeds are joined on a raw name -- `chipForGame` in the
template was the first, fixed the same day with `chip_join_key`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import intelligence_state as st  # noqa: E402

MODULE = "syndicate.features.shared.game_chip_scoreboard.build_game_chips"


def _chip(sport, away, home, state, away_key=None, home_key=None):
    return {
        "sport": sport, "state": state,
        "away": {"name": away, "abbr": away[:3].upper(), "key": away_key, "score": 27},
        "home": {"name": home, "abbr": home[:3].upper(), "key": home_key, "score": 7},
    }


def _card(sport, away, home, away_key=None, home_key=None):
    return {"sport": sport, "away_team": away, "home_team": home,
            "away_key": away_key, "home_key": home_key,
            "lane": "pregame", "market_state": "pregame"}


def test_the_reported_ncaaf_row_now_restates_to_live():
    """THE BUG, with the production spellings. "Akron" vs "Akron Zips"."""
    cards = [_card("ncaaf", "Akron Zips", "Wake Forest Demon Deacons",
                   away_key="akron", home_key="wake forest")]
    with patch(MODULE, return_value=[_chip("ncaaf", "Akron", "Wake Forest", "live",
                                           away_key="akron", home_key="wake forest")]):
        n = st._refresh_layer2_live_state(cards, ["2026-09-03"])
    assert n == 1
    assert cards[0]["lane"] == "live"
    assert cards[0]["market_state"] == "live"
    assert cards[0]["is_live"] is True


def test_it_still_joins_when_NEITHER_side_publishes_a_key():
    """The canonical function is the fallback, so a row that predates the key
    field still joins. Narrowing this while widening it would trade one silent
    miss for another."""
    cards = [_card("ncaaf", "Colorado Buffaloes", "Georgia Tech Yellow Jackets")]
    with patch(MODULE, return_value=[_chip("ncaaf", "Colorado", "Georgia Tech", "live")]):
        n = st._refresh_layer2_live_state(cards, ["2026-09-03"])
    assert n == 1 and cards[0]["lane"] == "live"


def test_mlb_the_sport_that_ALREADY_worked_is_unchanged():
    """MLB matched on the raw name and must keep matching on it -- this is the
    regression guard for the 104 rows that were already correct."""
    cards = [_card("mlb", "San Francisco Giants", "Pittsburgh Pirates")]
    with patch(MODULE, return_value=[_chip("mlb", "San Francisco Giants",
                                           "Pittsburgh Pirates", "live")]):
        n = st._refresh_layer2_live_state(cards, ["2026-09-03"])
    assert n == 1 and cards[0]["lane"] == "live"


def test_a_pregame_chip_leaves_the_lane_alone():
    """Restating is not the same as stamping. A chip that says pregame must not
    move a card, or the join would manufacture state rather than read it."""
    cards = [_card("ncaaf", "Akron Zips", "Wake Forest Demon Deacons")]
    with patch(MODULE, return_value=[_chip("ncaaf", "Akron", "Wake Forest", "pregame")]):
        n = st._refresh_layer2_live_state(cards, ["2026-09-03"])
    assert n == 0 and cards[0]["lane"] == "pregame"


def test_a_DIFFERENT_game_must_not_match():
    """The widening must not become a wildcard. Two NCAAF games on one slate,
    and the wrong chip must not restate the wrong card."""
    cards = [_card("ncaaf", "Akron Zips", "Wake Forest Demon Deacons")]
    with patch(MODULE, return_value=[_chip("ncaaf", "Colorado", "Georgia Tech", "live")]):
        n = st._refresh_layer2_live_state(cards, ["2026-09-03"])
    assert n == 0 and cards[0]["lane"] == "pregame"


def test_a_final_chip_still_reaches_final():
    cards = [_card("ncaaf", "Akron Zips", "Wake Forest Demon Deacons")]
    with patch(MODULE, return_value=[_chip("ncaaf", "Akron", "Wake Forest", "final")]):
        n = st._refresh_layer2_live_state(cards, ["2026-09-03"])
    assert n == 1 and cards[0]["lane"] == "final" and cards[0]["is_live"] is False
