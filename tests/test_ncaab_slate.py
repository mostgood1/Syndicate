"""The NCAAB D1 slate (`ncaab/slate.py`) and the three surfaces it feeds.

2026-11-02 opener: 0 NCAAB chips, an empty `/ncaab` page, and every Layer 1
NCAAB game `unknown`, because no NCAAB game list existed. These pin the pieces:
D1-vs-D1 only, neutral-site orientation, halves on the clock, the odds feed's
spellings, and the cards page drawing from the slate.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.ncaab import slate
from syndicate.features.shared.game_chip_scoreboard import build_game_chip
from syndicate.features.shared.team_aliases import chip_join_key


def _competitor(team_id, name, abbr, side, score="0", linescores=()):
    return {
        "homeAway": side,
        "score": score,
        "linescores": [{"value": v} for v in linescores],
        "team": {"id": team_id, "displayName": name, "abbreviation": abbr, "shortDisplayName": abbr, "logo": f"https://logo/{team_id}.png", "color": "112233"},
    }


def _event(event_id, away, home, *, state="pre", period=0, clock="0:00", detail="7:00 PM", neutral=False, date="2026-11-03T00:00Z"):
    return {
        "id": event_id,
        "date": date,
        "competitions": [{
            "neutralSite": neutral,
            "venue": {"fullName": "Arena"},
            "competitors": [away, home],
            "status": {"period": period, "displayClock": clock, "type": {"state": state, "completed": state == "post", "shortDetail": detail}},
        }],
    }


D1 = frozenset({"1", "2", "3", "4"})


def test_only_d1_vs_d1_games_are_kept():
    payload = {"events": [
        _event("10", _competitor("1", "Duke Blue Devils", "DUKE", "away"), _competitor("2", "Army Black Knights", "ARMY", "home")),
        _event("11", _competitor("3", "Purdue Boilermakers", "PUR", "away"), _competitor("999", "McMurry War Hawks", "MCM", "home")),
    ]}
    games, dropped = slate.parse_scoreboard(payload, d1_ids=D1)
    assert [g["event_id"] for g in games] == ["10"]
    assert dropped == 1


def test_pregame_scores_are_not_observations_and_live_carries_clock_and_halves():
    payload = {"events": [
        _event("20", _competitor("1", "A Team", "AAA", "away"), _competitor("2", "B Team", "BBB", "home")),
        _event("21", _competitor("3", "C Team", "CCC", "away", "41", (35, 6)), _competitor("4", "D Team", "DDD", "home", "38", (30, 8)),
               state="in", period=2, clock="12:34", detail="12:34 - 2nd Half"),
    ]}
    games, _ = slate.parse_scoreboard(payload, d1_ids=D1)
    pre, live = games
    assert pre["away"]["score"] is None and pre["live_state"]["in_progress"] is False
    assert live["live_state"] == {
        "in_progress": True, "final": False, "period": 2, "clock": "12:34", "status": "12:34 - 2nd Half",
        "away_linescores": [35, 6], "home_linescores": [30, 8],
    }
    chip = build_game_chip("ncaab", live)
    assert chip["state"] == "live"
    assert chip["status_token"] == "H2 12:34"
    assert (chip["away"]["score"], chip["home"]["score"]) == ("41", "38")


@pytest.mark.parametrize("period,token", [(1, "H1 5:00"), (2, "H2 5:00"), (3, "OT 5:00"), (4, "2OT 5:00")])
def test_ncaab_clock_reads_halves_and_overtimes_not_quarters(period, token):
    game = {"live_state": {"in_progress": True, "period": period, "clock": "5:00"}, "away": {"abbr": "A", "score": 1}, "home": {"abbr": "B", "score": 2}}
    assert build_game_chip("ncaab", game)["status_token"] == token
    assert build_game_chip("nba", game)["status_token"] == f"Q{period} 5:00"


def test_ncaab_linescore_is_two_halves():
    from syndicate.features.shared.game_chip_linescore import linescore

    box = linescore("ncaab", {"live_state": {"away_linescores": [35, 40], "home_linescores": [30, 41]}}, "2026-11-02")
    assert box["labels"] == ["1", "2"]
    assert box["away"] == [35, 40]


def test_neutral_site_game_takes_the_odds_feed_orientation_and_a_home_game_never_does():
    games = [
        {"neutral_site": True, "away": {"name": "Miami Hurricanes"}, "home": {"name": "Florida Gators"}, "live_state": {"away_linescores": [1], "home_linescores": [2]}},
        {"neutral_site": False, "away": {"name": "Gonzaga Bulldogs"}, "home": {"name": "Purdue Boilermakers"}, "live_state": {}},
    ]
    pairs = {
        (chip_join_key("ncaab", "Florida Gators"), chip_join_key("ncaab", "Miami Hurricanes")),
        (chip_join_key("ncaab", "Purdue Boilermakers"), chip_join_key("ncaab", "Gonzaga Bulldogs")),
    }
    out, swapped = slate.orient_neutral_site_games(games, pairs)
    assert swapped == 1
    assert out[0]["away"]["name"] == "Florida Gators" and out[0]["live_state"]["away_linescores"] == [2]
    assert out[0]["matchup"] == "Florida Gators @ Miami Hurricanes"
    assert out[1]["away"]["name"] == "Gonzaga Bulldogs"


@pytest.mark.parametrize("odds_feed,espn", [
    ("Georgia St Panthers", "Georgia State Panthers"),
    ("Appalachian St Mountaineers", "App State Mountaineers"),
    ("GW Revolutionaries", "George Washington Revolutionaries"),
    ("LIU Sharks", "Long Island University Sharks"),
    ("Army Knights", "Army Black Knights"),
    ("American Eagles", "American University Eagles"),
    ("Boston Univ. Terriers", "Boston University Terriers"),
    ("Loyola (MD) Greyhounds", "Loyola Maryland Greyhounds"),
    ("Mt. St. Mary's Mountaineers", "Mount St. Mary's Mountaineers"),
    ("UMKC Kangaroos", "Kansas City Roos"),
    ("Queens University Royals", "Queens University Royals"),
])
def test_odds_feed_spellings_join_the_espn_team(odds_feed, espn):
    key = chip_join_key("ncaab", odds_feed)
    assert key is not None and key == chip_join_key("ncaab", espn)


def test_derived_spellings_do_not_make_ambiguous_mascots_keys():
    from syndicate.features.shared.team_aliases import canonical_team

    for mascot in ("Wildcats", "Bulldogs", "Tigers", "Eagles"):
        assert canonical_team("ncaab", mascot) is None


def test_registry_carries_the_d1_programmes_espns_team_list_omits():
    from syndicate.features.shared.ncaab_team_registry import registry_rows

    ids = {row["espn_id"] for row in registry_rows()}
    assert {"2511", "88", "2815"} <= ids
    assert len(ids) == len(registry_rows())


def test_web_reads_the_artifact_and_never_fetches(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(slate, "refresh_slate", lambda *a, **k: pytest.fail("web must not fetch"))
    assert slate.slate_games("2026-11-02", refresh=False) == []
    path = slate.slate_artifact_path("2026-11-02")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"games": [{"event_id": "1"}]}), encoding="utf-8")
    assert slate.slate_games("2026-11-02", refresh=False) == [{"event_id": "1"}]


def test_worker_refresh_writes_the_artifact_and_a_failed_fetch_keeps_the_last_one(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(slate, "_d1_ids", lambda: D1)
    payload = {"events": [_event("30", _competitor("1", "A Team", "AAA", "away"), _competitor("2", "B Team", "BBB", "home"))]}
    art = slate.refresh_slate("2026-11-02", fetch_json=lambda url: payload)
    assert [g["event_id"] for g in art["games"]] == ["30"]
    assert "groups=50" in slate.SCOREBOARD_URL
    assert json.loads(slate.slate_artifact_path("2026-11-02").read_text())["games"][0]["event_id"] == "30"

    def boom(url):
        raise OSError("espn down")

    assert slate.refresh_slate("2026-11-02", fetch_json=boom) is None
    assert slate.read_slate("2026-11-02")["games"][0]["event_id"] == "30"


def test_cards_page_draws_the_slate_when_no_recommendation_groups_exist(monkeypatch):
    from syndicate.features.ncaab import cards

    game = {
        "event_id": "401", "start_time_utc": "2026-11-03T00:00Z", "neutral_site": False, "venue": "Arena",
        "away": {"name": "Duke Blue Devils", "abbr": "DUKE", "score": None},
        "home": {"name": "Army Black Knights", "abbr": "ARMY", "score": None},
        "live_state": {"in_progress": False, "final": False, "status": "7:00 PM"},
    }
    monkeypatch.setattr(cards, "mirrored_recommendations_payload", lambda d: None)
    monkeypatch.setattr("syndicate.features.ncaab.slate.slate_games", lambda d: [game])
    context = cards.build_cards_page_context("2026-11-02")
    assert [g["gamePk"] for g in context["games"]] == ["401"]
    assert context["empty_state"] is None
    assert context["games"][0]["status"] == "Pregame"
    # The chip fields ride on the card, so the provider feeds the rail from it.
    chip = build_game_chip("ncaab", context["games"][0])
    assert chip["state"] == "pregame" and chip["start_time_utc"] == "2026-11-03T00:00:00+00:00"
    assert (context["prev_date"], context["next_date"]) == ("2026-11-01", "2026-11-03")
