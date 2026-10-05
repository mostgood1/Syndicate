"""NHL props fetch requests and parses goalie saves (lane `nhl-confirmed-goalies`, user: "Add saves only").

`collect_oddsapi_props` runs unmodified with a fake OddsAPI client. The event payload shape is the one the
function already parses for the other player markets (outcome name Over/Under, player in `description`, `point`).
"""
from __future__ import annotations

import syndicate.local_nhl_odds as M

EVENT = {"id": "evt1", "commence_time": "2026-10-07T23:00:00Z", "home_team": "Buffalo Sabres", "away_team": "Minnesota Wild"}


class FakeClient:
    calls: list = []

    def __init__(self, *a, **k):
        pass

    def event_odds(self, sport_key, event_id, markets, regions=None, bookmakers=None):
        FakeClient.calls.append(markets)
        return ({**EVENT, "bookmakers": [{"key": "fanduel", "markets": [
            {"key": "player_total_saves", "outcomes": [
                {"name": "Over", "description": "Ukko-Pekka Luukkonen", "point": 25.5, "price": -115},
                {"name": "Under", "description": "Ukko-Pekka Luukkonen", "point": 25.5, "price": -105}]},
            {"key": "player_shots_on_goal", "outcomes": [
                {"name": "Over", "description": "Tage Thompson", "point": 3.5, "price": 110}]},
        ]}]}, {})


def test_saves_are_requested_and_parsed(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(M, "OddsApiClient", FakeClient)
    monkeypatch.setattr(M, "list_nhl_events", lambda client, **k: [EVENT])
    df = M.collect_oddsapi_props("2026-10-07")
    assert FakeClient.calls and "player_total_saves" in FakeClient.calls[0].split(",")
    saves = df[df["market"] == "SAVES"]
    assert len(saves) == 2 and set(saves["side"]) == {"OVER", "UNDER"}
    assert saves["player"].iloc[0] == "Ukko-Pekka Luukkonen" and float(saves["line"].iloc[0]) == 25.5
    assert set(df["market"]) == {"SAVES", "SOG"}
