"""Layer 2 does not seat a basketball prop whose player is OUT on the injury feed.

Board rows are built from bookmaker quotes, so an OUT player's quote reached
Layer 2 and -- with no projection -- ranked on market EV alone.
`board_enrichment._flag_out_player_props` stamps `player_availability` (Layer 1
keeps the row, marked); `select_shortlist` leaves the line unseated, pre-bucket,
and counts it. A property of the line (the bet voids), not a market verdict, so
it fits the 2026-10-05 stop-market-withholding directive. Questionable and
doubtful players are never flagged upstream and stay priced.
"""

from __future__ import annotations

from datetime import datetime, timezone

from syndicate.features.shared.layer2_board import select_shortlist

_NOW = datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc)
_MEASURED = {"model_skill": {"status": "measured", "sample_games": 120}}


def _prop(player: str, sport: str = "wnba", **extra: object) -> dict:
    row = {
        "sport": sport,
        "kind": "prop",
        "market": "player_threes",
        "player_name": player,
        "side": "over",
        "event_id": f"evt-{player}",
        "commence_time": "2026-10-07T23:30:00Z",
        "ev_pct": 2.5,
        "model_edge_pct": 4.1,
        "projection": _MEASURED,
        "quote": {"price": 118, "fair_probability": 0.44, "fair_method": "consensus_no_vig", "books_quoting": 4},
        "score": {"score": 2.5, "value_pct": 2.5},
    }
    row.update(extra)
    return row


def _out(status: str = "OUT") -> dict:
    return {"player_availability": {"status": status, "reason": "player OUT on the injury feed"}}


def test_an_out_player_is_not_seated_and_is_counted():
    rows = [_prop("Allisha Gray", **_out()), _prop("Jewell Loyd"), _prop("Rhyne Howard")]
    result = select_shortlist(rows, now=_NOW)
    seated = {row.get("player_name") for row in result["rows"]}
    assert "Allisha Gray" not in seated
    assert {"Jewell Loyd", "Rhyne Howard"} <= seated
    assert result["rows_player_out_on_feed"] == 1
    assert result["rows_player_out_on_feed_by_sport"] == {"wnba": 1}


def test_off_is_not_on_the_same_row_seats_without_the_flag():
    # Reachability: identical row, flag removed -> seated. So the exclusion above
    # is this gate, not some other rule.
    result = select_shortlist([_prop("Allisha Gray"), _prop("Rhyne Howard")], now=_NOW)
    assert "Allisha Gray" in {row.get("player_name") for row in result["rows"]}
    assert result["rows_player_out_on_feed"] == 0
    assert result["rows_player_out_on_feed_by_sport"] == {}


def test_only_confirmed_out_statuses_gate():
    rows = [_prop("A One", **_out("SUSPENDED")), _prop("B Two", **_out("DOUBTFUL")), _prop("C Three")]
    result = select_shortlist(rows, now=_NOW)
    seated = {row.get("player_name") for row in result["rows"]}
    assert "A One" not in seated
    assert "B Two" in seated
    assert result["rows_player_out_on_feed"] == 1


def test_counted_per_sport():
    rows = [_prop("Gray", **_out()), _prop("Butler", sport="nba", **_out()), _prop("Howard")]
    result = select_shortlist(rows, now=_NOW)
    assert result["rows_player_out_on_feed_by_sport"] == {"nba": 1, "wnba": 1}
