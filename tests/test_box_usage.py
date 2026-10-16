"""Box-score usage for result cards (lane result-cards): the graded game's opportunity against the player's usual."""
from __future__ import annotations

from syndicate.features.shared import box_usage as bu


def _nhl_fetch(url):
    if "/game-log/20262027/" in url:
        return {"gameLog": [{"gameDate": "2026-10-15", "toi": "16:16"}, {"gameDate": "2026-10-13", "toi": "18:20"},
                            {"gameDate": "2026-10-10", "toi": "17:25"}]}
    if "/game-log/20252026/" in url:
        return {"gameLog": [{"gameDate": "2026-04-15", "toi": "15:45"}, {"gameDate": "2026-04-13", "toi": "16:56"}]}
    return None


def test_nhl_ice_time_against_the_usual_across_the_season_boundary(tmp_path):
    card = {"sport": "nhl", "date": "2026-10-15", "market": "SOG"}
    item = {"kind": "prop", "headshot_url": "https://assets.nhle.com/mugs/nhl/latest/8484471.png"}
    u = bu.usage_for(card, item, cache=tmp_path, fetch=_nhl_fetch)
    assert u["metric"] == "Ice time" and u["actual"] == 16.3 and u["games"] == 4                # 2 this season + 2 last
    assert u["usual"] == round((18 + 20 / 60 + 17 + 25 / 60 + 15 + 45 / 60 + 16 + 56 / 60) / 4, 1)
    assert bu.usage_for(dict(card, market="saves"), item, cache=tmp_path, fetch=_nhl_fetch) is None   # a goalie: not minutes
    assert bu.usage_for(dict(card, date="2026-10-14"), item, cache=tmp_path, fetch=_nhl_fetch) is None  # no game that day


def _mlb_fetch(url):
    if "group=pitching" in url and "gameType=P" in url:
        return {"stats": [{"splits": [{"date": "2026-10-15", "stat": {"battersFaced": 18, "gamesStarted": 1}},
                                      {"date": "2026-10-07", "stat": {"battersFaced": 20, "gamesStarted": 1}}]}]}
    if "group=pitching" in url:
        return {"stats": [{"splits": [{"date": "2026-09-25", "stat": {"battersFaced": 24, "gamesStarted": 1}},
                                      {"date": "2026-09-20", "stat": {"battersFaced": 4, "gamesStarted": 0}},
                                      {"date": "2026-09-14", "stat": {"battersFaced": 22, "gamesStarted": 1}}]}]}
    if "group=hitting" in url and "gameType=P" in url:
        return {"stats": [{"splits": [{"date": "2026-10-15", "stat": {"plateAppearances": 4}},
                                      {"date": "2026-10-15", "stat": {"plateAppearances": 3}}]}]}       # a doubleheader
    return {"stats": [{"splits": []}]}


def test_mlb_workload_counts_starts_only_for_a_starter_and_never_guesses_a_doubleheader(tmp_path):
    card = {"sport": "mlb", "date": "2026-10-15", "market": "hits_allowed"}
    item = {"kind": "prop", "headshot_url": "https://img.mlbstatic.com/mlb-photos/image/upload/w_360/v1/people/607192/headshot/67/current"}
    u = bu.usage_for(card, item, cache=tmp_path, fetch=_mlb_fetch)
    assert u["metric"] == "Batters faced" and u["actual"] == 18 and u["of"] == "starts" and u["games"] == 3
    assert u["usual"] == round((20 + 24 + 22) / 3, 1)                                  # the relief outing (4) left out
    batter = bu.usage_for(dict(card, market="batter_hits"), item, cache=tmp_path, fetch=_mlb_fetch)
    assert batter is None                                                               # two games that day: not guessed


def test_only_supported_props_get_usage(tmp_path):
    item = {"kind": "prop", "player_id": "1"}
    assert bu.usage_for({"sport": "nfl", "date": "2026-10-15", "market": "Receptions"}, item, cache=tmp_path) is None
    assert bu.usage_for({"sport": "mlb", "date": "2026-10-15", "market": "h2h"}, {"kind": "game"}, cache=tmp_path) is None
    assert bu.player_id("nhl", {"headshot_url": "https://assets.nhle.com/mugs/nhl/latest/8478402.png"}) == "8478402"
    assert bu.player_id("mlb", {"player_id": 607192}) == "607192"
