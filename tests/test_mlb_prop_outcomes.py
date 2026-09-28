"""MLB prop outcomes for the bucket search, settled with the MLB page's own box-score readers.

Offline: every schedule and box score here is a fixture served by a fake fetch.
"""

from __future__ import annotations

import pytest

from syndicate.features.mlb import prop_outcomes as po


def _player(name, batting=None, pitching=None):
    return {"person": {"fullName": name}, "stats": {"batting": batting or {}, "pitching": pitching or {}}}


BOX = {
    "teams": {
        "away": {
            "players": {
                "ID1": _player("Aaron Judge", batting={"hits": 2, "runs": 1, "rbi": 3, "totalBases": 5,
                                                       "homeRuns": 1, "atBats": 4}),
                "ID2": _player("Gerrit Cole", pitching={"strikeOuts": 9, "outs": 18, "hits": 4, "earnedRuns": 2,
                                                        "baseOnBalls": 1, "inningsPitched": "6.0"}),
            }
        },
        "home": {
            "players": {
                "ID3": _player("Mike Trout", batting={"hits": 0, "runs": 0, "rbi": 0, "totalBases": 0,
                                                      "homeRuns": 0, "atBats": 4}),
                "ID4": _player("Bench Guy"),
            }
        },
    }
}
FEED = {"liveData": {"boxscore": BOX}}
HOME, AWAY = "Boston Red Sox", "New York Yankees"


@pytest.mark.parametrize("market, name, expected", [
    ("batter_hits", "aaron judge", 2.0),
    ("batter_total_bases", "aaron judge", 5.0),
    ("batter_rbis", "aaron judge", 3.0),
    ("batter_hits_runs_rbis", "aaron judge", 6.0),
    ("batter_home_runs", "aaron judge", 1.0),
    ("batter_runs_scored", "aaron judge", 1.0),
    ("strikeouts", "gerrit cole", 9.0),
    ("pitcher_strikeouts", "gerrit cole", 9.0),
    ("outs", "gerrit cole", 18.0),
    ("hits_allowed", "gerrit cole", 4.0),
    ("earned_runs", "gerrit cole", 2.0),
    ("walks_allowed", "gerrit cole", 1.0),
    ("batter_hits", "mike trout", 0.0),
])
def test_every_mapped_market_reads_its_box_score_field(market, name, expected):
    assert po.player_actual(market, name, FEED) == (expected, None)


def test_a_nickname_matches_through_the_pages_own_name_variants():
    assert po.player_actual("batter_hits", "Michael Trout", FEED) == (0.0, None)


def _feed_with(*players):
    return {"liveData": {"boxscore": {"teams": {
        "away": {"players": {f"ID{i}": p for i, p in enumerate(players)}},
        "home": {"players": {}},
    }}}}


# The two production misses, 2026-09-28: 150 of 2,882 `player_not_in_boxscore` rows over four
# dates were these two players, who DID play (the other 94.8% genuinely did not).
@pytest.mark.parametrize("odds_name, box_name", [
    ("rafael flores", "Rafael Flores Jr."),
    ("leonardo bernal", "Leo Bernal"),
    ("J.P. Crawford", "JP Crawford"),
])
def test_the_measured_name_misses_now_find_the_player(odds_name, box_name):
    feed = _feed_with(_player(box_name, batting={"hits": 2, "atBats": 4}))
    assert po.player_actual("batter_hits", odds_name, feed) == (2.0, None)


def test_a_folded_name_that_matches_two_players_stays_unmatched():
    feed = _feed_with(_player("Luis Garcia Jr.", batting={"hits": 1}), _player("Luis Garcia", batting={"hits": 3}))
    # The page's exact match still wins where it exists ...
    assert po.player_actual("batter_hits", "luis garcia", feed) == (3.0, None)
    # ... and a name only the fold can reach, reaching two players, is a void, not a guess.
    feed = _feed_with(_player("Leo Bernal", batting={"hits": 1}), _player("Leon Bernal", batting={"hits": 3}))
    assert po.player_actual("batter_hits", "leonardo bernal", feed) == (None, "player_not_in_boxscore")


def test_an_initial_or_another_surname_never_matches():
    feed = _feed_with(_player("Leo Bernal", batting={"hits": 1}))
    assert po.player_actual("batter_hits", "L. Bernal", feed) == (None, "player_not_in_boxscore")
    assert po.player_actual("batter_hits", "Le Bernal", feed) == (None, "player_not_in_boxscore")
    assert po.player_actual("batter_hits", "leonardo bernardo", feed) == (None, "player_not_in_boxscore")


def test_a_bench_player_is_still_a_void_after_the_fold():
    feed = _feed_with(_player("Rafael Flores Jr."), _player("Leo Bernal", pitching={"strikeOuts": 1}))
    assert po.player_actual("batter_hits", "rafael flores", feed) == (None, "player_not_in_boxscore")
    assert po.player_actual("batter_hits", "leonardo bernal", feed) == (None, "player_not_in_boxscore")


def test_a_player_who_did_not_play_settles_nothing():
    assert po.player_actual("batter_hits", "Bench Guy", FEED) == (None, "player_not_in_boxscore")
    assert po.player_actual("strikeouts", "aaron judge", FEED) == (None, "player_not_in_boxscore")
    assert po.player_actual("batter_stolen_bases", "aaron judge", FEED) == (None, "prop_market_unmapped")


@pytest.mark.parametrize("side, line, actual, expected", [
    ("over", 0.5, 0, "loss"),
    ("under", 0.5, 0, "win"),
    ("over", 1.5, 2, "win"),
    ("under", 6, 6, "push"),
    ("yes", 0.5, 1, None),
    ("over", None, 1, None),
    ("over", 0.5, None, None),
])
def test_settle_prop(side, line, actual, expected):
    assert po.settle_prop(side, line, actual) == expected


def _schedule(*games):
    return {"dates": [{"games": [
        {"gamePk": pk, "gameDate": when, "status": {"abstractGameState": state, "detailedState": detailed},
         "teams": {"home": {"team": {"name": home}}, "away": {"team": {"name": away}}}}
        for pk, when, home, away, state, detailed in games
    ]}]}


def _record(**overrides):
    record = {"market": "batter_hits", "player_name": "aaron judge", "side": "over", "line": 1.5,
              "home_team": HOME, "away_team": AWAY, "commence_time": "2026-09-01T23:10:00Z"}
    record.update(overrides)
    return record


class FakeFetch:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        for fragment, payload in self.responses.items():
            if fragment in url:
                return payload
        return None


def _final_fetch():
    return FakeFetch({"date=2026-09-01": _schedule((111, "2026-09-01T23:10:00Z", HOME, AWAY, "Final", "Final")),
                      "/game/111/boxscore": BOX})


def test_a_final_game_settles_and_nothing_is_fetched_twice(tmp_path):
    fetch = _final_fetch()
    grader = po.MlbPropGrader(fetch=fetch, cache_dir=tmp_path)
    assert grader.settle(_record()) == ("win", None)
    assert grader.settle(_record(side="under")) == ("loss", None)
    assert len(fetch.calls) == 2                      # one schedule, one box score
    again = po.MlbPropGrader(fetch=FakeFetch({}), cache_dir=tmp_path)
    assert again.settle(_record()) == ("win", None)   # served from the on-disk cache


def test_a_push_is_named_by_the_settlement():
    grader = po.MlbPropGrader(fetch=_final_fetch())
    assert grader.settle(_record(market="outs", player_name="gerrit cole", line=18)) == ("push", None)


def test_a_doubleheader_matches_the_game_nearest_the_quoted_start():
    empty_box = {"teams": {"away": {"players": {}}, "home": {"players": {}}}}
    fetch = FakeFetch({
        "date=2026-09-01": _schedule((111, "2026-09-01T17:05:00Z", HOME, AWAY, "Final", "Final"),
                                     (222, "2026-09-01T23:10:00Z", HOME, AWAY, "Final", "Final")),
        "/game/222/boxscore": BOX,
        "/game/111/boxscore": empty_box,
    })
    assert po.MlbPropGrader(fetch=fetch).settle(_record()) == ("win", None)
    assert any("/game/222/" in url for url in fetch.calls)
    assert not any("/game/111/" in url for url in fetch.calls)


@pytest.mark.parametrize("state, detailed, reason", [
    ("Live", "In Progress", "game_not_final"),
    ("Preview", "Scheduled", "game_not_final"),
    ("Final", "Postponed", "game_not_played"),
])
def test_an_unplayed_or_unfinished_game_settles_nothing(state, detailed, reason):
    fetch = FakeFetch({"date=2026-09-01": _schedule((111, "2026-09-01T23:10:00Z", HOME, AWAY, state, detailed))})
    assert po.MlbPropGrader(fetch=fetch).settle(_record()) == (None, reason)


def test_another_day_of_the_same_series_is_never_matched():
    """The same two teams play on consecutive days; a match far from the quoted start is not this game."""
    fetch = FakeFetch({"date=2026-09-01": _schedule((111, "2026-08-31T23:10:00Z", HOME, AWAY, "Final", "Final")),
                       "/game/111/boxscore": BOX})
    assert po.MlbPropGrader(fetch=fetch).settle(_record()) == (None, "game_not_found")


def test_a_failed_schedule_fetch_is_named():
    assert po.MlbPropGrader(fetch=FakeFetch({})).settle(_record()) == (None, "schedule_unavailable")


def test_nothing_unfinished_is_cached(tmp_path):
    fetch = FakeFetch({"date=2026-09-01": _schedule((111, "2026-09-01T23:10:00Z", HOME, AWAY, "Live", "In Progress"))})
    po.MlbPropGrader(fetch=fetch, cache_dir=tmp_path).settle(_record())
    assert list(tmp_path.iterdir()) == []


def test_a_west_coast_evening_start_asks_for_its_eastern_date():
    """7:10 PM PT is 02:10Z on the NEXT UTC day but 10:10 PM ET on the same day, the date StatsAPI files it under."""
    fetch = FakeFetch({"date=2026-09-01": _schedule((111, "2026-09-02T02:10:00Z", HOME, AWAY, "Final", "Final")),
                       "/game/111/boxscore": BOX})
    assert po.MlbPropGrader(fetch=fetch).settle(_record(commence_time="2026-09-02T02:10:00Z")) == ("win", None)
    assert any("date=2026-09-01" in url for url in fetch.calls)


def _scored(state="Final", detailed="Final", away=4, home=6):
    payload = _schedule((111, "2026-09-01T23:10:00Z", HOME, AWAY, state, detailed))
    teams = payload["dates"][0]["games"][0]["teams"]
    teams["away"]["score"], teams["home"]["score"] = away, home
    return payload


def test_a_final_games_score_comes_from_the_schedule():
    """For game lines whose scoreboard chip is scoreless (past MLB dates were served null scores)."""
    grader = po.MlbPropGrader(fetch=FakeFetch({"date=2026-09-01": _scored()}))
    assert grader.final_score(_record()) == ((4, 6), None)


@pytest.mark.parametrize("payload, reason", [
    (_scored(state="Live", detailed="In Progress"), "game_not_final"),
    (_scored(away=None, home=None), "score_absent"),
])
def test_no_final_score_is_invented(payload, reason):
    assert po.MlbPropGrader(fetch=FakeFetch({"date=2026-09-01": payload})).final_score(_record()) == (None, reason)


def test_the_scorecards_mlb_grader_version_covers_the_name_match(monkeypatch):
    """A name-match change must RESET MLB scorecard history, never pool two grader versions.

    Until 2026-09-28 the digest hashed only `settle` and `final_score`, so this change itself
    would have been pooled.
    """
    import importlib.util
    import pathlib

    from syndicate.features.shared import model_scorecard as msc

    src = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "publish_model_scorecard.py"
    spec = importlib.util.spec_from_file_location("publish_model_scorecard_for_digest", src)
    pms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pms)

    class _Settler:
        sport_versions, versions, unavailable = {}, {}, set()

    bs = msc.load_bucket_search()
    before = pms.grader_signature(bs, _Settler())[1]["mlb"]

    def other_match(player_name, contexts):  # a different name match
        return None

    monkeypatch.setattr(po, "_folded_match", other_match)
    after = pms.grader_signature(bs, _Settler())[1]["mlb"]
    assert before != after
