"""The NBA live lens showed games ESPN and the re-sim had in play as `Scheduled 0-0` (lane `nba-lens-live-state`, `#762`).

Mechanism, measured on the fleet 2026-11-07 for the 11-06 slate: `live_state_<date>.jsonl` is written once pregame and
never during play, so the live state `build_cards_page_context` merges comes from its ESPN fallback -- and the context
cache key covered the files but not that ESPN read. The first build of the evening was then served all evening.

Second defect: `live_projection_join.build_live_prop_index` read a game's `status` only when it was a Mapping, and
NBA's is a string, so `lens_live_games` was 0 for NBA whatever was in play.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from syndicate.features.nba import cards as c
from syndicate.features.nba import live_lens as lens
from syndicate.features.shared import basketball_pbp
from syndicate.features.shared import live_projection_join as lpj

EVENT = "401909999"


def _scoreboard(state: str, *, away_pts: int = 0, home_pts: int = 0, detail: str = "") -> dict:
    tip = (datetime.now(timezone.utc) + (timedelta(hours=1) if state == "pre" else -timedelta(minutes=30)))
    return {"events": [{"id": EVENT, "date": tip.strftime("%Y-%m-%dT%H:%MZ"), "competitions": [{
        "status": {"period": 0 if state == "pre" else 2, "displayClock": "5:12",
                   "type": {"state": state, "completed": state == "post",
                            "shortDetail": detail or ("7:30 PM" if state == "pre" else "5:12 - 2nd")}},
        "competitors": [{"homeAway": "home", "team": {"abbreviation": "BOS"}, "score": str(home_pts)},
                        {"homeAway": "away", "team": {"abbreviation": "MIL"}, "score": str(away_pts)}]}]}]}


@pytest.fixture()
def slate(monkeypatch):
    """A one-game slate whose cards artifact never changes, read through the real ESPN path with ESPN faked."""
    day = datetime.now(timezone.utc).date().isoformat()
    feed = {"scoreboard": _scoreboard("pre"), "calls": []}

    def fake_espn_get(league, path, *, timeout=30.0, attempts=3):
        feed["calls"].append((league, path, timeout, attempts))
        return feed["scoreboard"]

    monkeypatch.setattr(basketball_pbp, "espn_get", fake_espn_get)
    monkeypatch.setattr(c, "_render_web_dyno", lambda: False)
    monkeypatch.setattr(c, "_local_live_state_payload", lambda _d: None)   # the pregame file is absent or stale
    monkeypatch.setattr(c, "_live_snapshot_or_state_signature", lambda _p: 0)
    monkeypatch.setattr(c, "available_dates", lambda: [day])
    # The artifact game: built once, pregame, from the same converter production's fallback uses. It never changes,
    # exactly like `game_cards_2026-11-06.csv` after 17:30 CST.
    artifact_games, _src = c._games_from_live_state_fallback(day)
    assert artifact_games and artifact_games[0]["status"] == "Scheduled"
    monkeypatch.setattr(c, "_games_from_artifacts", lambda _d: ([dict(g) for g in artifact_games], "game_cards.csv", "recs.json"))
    monkeypatch.setattr(c, "_ESPN_LIVE_STATE_MEMO_SECONDS", 0.0)            # every read refetches (memo tested apart)
    c._ESPN_LIVE_STATE_MEMO.clear()
    c._NBA_CARDS_CONTEXT_CACHE.clear()
    feed["calls"].clear()
    return SimpleNamespace(day=day, feed=feed)


def _game(ctx: dict) -> dict:
    (game,) = [g for g in ctx["games"] if str(g.get("event_id")) == EVENT]
    return game


def test_a_game_that_tips_after_the_first_build_reads_live_with_its_score(slate):
    before = c.build_cards_page_context(slate.day)
    assert _game(before)["status"] == "Scheduled"

    slate.feed["scoreboard"] = _scoreboard("in", away_pts=51, home_pts=55)
    after = _game(c.build_cards_page_context(slate.day))
    assert after["status"] == "Live"
    assert after["live_state"]["in_progress"] is True
    assert (after["live_state"]["away_pts"], after["live_state"]["home_pts"]) == (51.0, 55.0)


def test_off_the_old_cache_identity_serves_the_pregame_context_after_tip(slate, monkeypatch):
    """OFF != ON: with the live signature pinned (the old key, which never saw the ESPN read) the cached pregame
    context is served after tip -- the 11-06 evening. The signature is the only difference between the two runs."""
    monkeypatch.setattr(c, "_live_state_merge_signature", lambda _d: None)
    assert _game(c.build_cards_page_context(slate.day))["status"] == "Scheduled"
    slate.feed["scoreboard"] = _scoreboard("in", away_pts=51, home_pts=55)
    stale = _game(c.build_cards_page_context(slate.day))
    assert stale["status"] == "Scheduled"
    assert stale["live_state"]["in_progress"] is False


def test_an_unchanged_pregame_slate_still_hits_the_cache(slate, monkeypatch):
    first = c.build_cards_page_context(slate.day)
    built: list[str] = []
    real = c._merge_games_with_live_state
    monkeypatch.setattr(c, "_merge_games_with_live_state", lambda g, d: built.append(d) or real(g, d))
    second = c.build_cards_page_context(slate.day)
    assert built == []                                  # served from the cache: ESPN said the same thing
    assert _game(second)["status"] == _game(first)["status"] == "Scheduled"


def test_a_live_state_change_replaces_the_dates_entry_instead_of_adding_one(slate):
    c.build_cards_page_context(slate.day)
    for pts in (10, 12, 15, 18):
        slate.feed["scoreboard"] = _scoreboard("in", away_pts=pts, home_pts=pts + 2)
        assert _game(c.build_cards_page_context(slate.day))["live_state"]["away_pts"] == float(pts)
    assert len(c._NBA_CARDS_CONTEXT_CACHE) == 1


def test_the_web_dyno_never_reads_espn_for_the_cache_key(slate, monkeypatch):
    monkeypatch.setattr(c, "_render_web_dyno", lambda: True)
    assert c._live_state_merge_signature(slate.day) is None
    assert slate.feed["calls"] == []


def test_the_lens_reads_espn_through_the_resims_fetcher_once_with_a_short_timeout(slate):
    payload = c._espn_live_state_payload(slate.day)
    assert payload["games"][0]["event_id"] == EVENT
    league, path, timeout, attempts = slate.feed["calls"][-1]
    assert league == "nba" and path.startswith("scoreboard?dates=") and attempts == 1 and timeout <= 5.0


def test_the_espn_read_is_memoized_and_a_failure_is_remembered_longer_and_logged_once(monkeypatch, capsys):
    clock = [1000.0]
    monkeypatch.setattr(c, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls: list[int] = []
    outcome = {"fail": False}

    def fake_espn_get(league, path, *, timeout=30.0, attempts=3):
        calls.append(1)
        if outcome["fail"]:
            raise RuntimeError("ESPN unreachable")
        return _scoreboard("pre")

    monkeypatch.setattr(basketball_pbp, "espn_get", fake_espn_get)
    day = "2026-11-07"
    first = c._espn_live_state_payload(day)
    first["games"].clear()                              # a caller's mutation must not reach the memo
    assert c._espn_live_state_payload(day)["games"] and len(calls) == 1
    clock[0] += c._ESPN_LIVE_STATE_MEMO_SECONDS + 0.1
    outcome["fail"] = True
    assert c._espn_live_state_payload(day) is None and len(calls) == 2
    clock[0] += c._ESPN_LIVE_STATE_MEMO_SECONDS + 0.1    # past the success TTL, inside the failure TTL
    assert c._espn_live_state_payload(day) is None and len(calls) == 2
    clock[0] += c._ESPN_LIVE_STATE_FAILURE_MEMO_SECONDS
    assert c._espn_live_state_payload(day) is None and len(calls) == 3
    lines = [l for l in capsys.readouterr().out.splitlines() if "ESPN_LIVE_STATE_FETCH_FAILED" in l]
    assert len(lines) == 1 and f"date={day}" in lines[0]


# --------------------------------------------------------------------------- the prop join's instrument

def _lens_snapshot(status) -> dict:
    return {"games": [{"event_id": EVENT, "status": status, "liveProps": [
        {"playerName": "Jayson Tatum", "prop": "player_points", "line": 26.5, "selection": "over",
         "liveProjection": 28.1, "liveModelProbOver": 0.61, "actualSoFar": 14}]}]}


@pytest.mark.parametrize("status, state", [("Live", "live"), ("Final", "final"), ("Scheduled", "pregame")])
def test_nbas_string_status_is_classified(status, state):
    indexed = lpj.build_live_prop_index(_lens_snapshot(status))
    assert indexed["live_games"] == (1 if state == "live" else 0)
    assert indexed["by_game_state"][state]["rows"] == 1


def test_off_the_string_dropped_to_empty_left_nba_with_no_live_games():
    """OFF != ON: what the old call site handed `_status_text` for NBA (`{}`) counts nothing; the string counts."""
    assert lpj.build_live_prop_index(_lens_snapshot({}))["live_games"] == 0
    assert lpj.build_live_prop_index(_lens_snapshot("Live"))["live_games"] == 1


def test_the_mapping_vocabularies_are_unchanged():
    assert lpj._status_text({"abstract": "Live", "detailed": "In Progress"}) == "live in progress"
    assert lpj._status_text({"status": "In Progress", "detail": "Q3 04:12"}) == "in progress q3 04:12"
    assert lpj._status_text(None) == ""


# --------------------------------------------------------------------------- the lens's own check against the re-sim

def _resim_snapshot(day: str, event_ids) -> dict:
    return {"date": day, "generatedAt": "2026-11-07T01:00:00Z", "refusalsByReason": {},
            "games": [{"event_id": e, "status": {"detailedState": "In Progress"},
                       "gameLens": [{"source": "live_resim"}], "liveProps": []} for e in event_ids]}


def test_a_lens_game_the_resim_has_in_play_but_the_lens_calls_pregame_is_counted_and_logged(monkeypatch, capsys):
    day = "2026-11-06"
    lens._LENS_STATE_BEHIND_NOTED.clear()
    monkeypatch.setattr(lens, "read_json_file", lambda _p: _resim_snapshot(day, ["1", "2", "3"]))
    games = [
        {"event_id": "1", "status": "Scheduled", "live_state": {"in_progress": False, "final": False}},
        {"event_id": "2", "status": "Live", "live_state": {"in_progress": True, "final": False}},
        {"event_id": "3", "status": "Final", "live_state": {"in_progress": False, "final": True}},
        {"event_id": "4", "status": "Scheduled", "live_state": {}},          # not in play: not the re-sim's
    ]
    out = lens._attach_native_resim(games, day)
    assert out["merged"] == 3
    assert out["state_check"] == {"resim_in_play": 3, "lens_live": 1, "lens_final": 1, "lens_not_started": ["1"]}
    lens._attach_native_resim(games, day)
    lines = [l for l in capsys.readouterr().out.splitlines() if "LENS_STATE_BEHIND_RESIM" in l]
    assert len(lines) == 1 and "event_ids=1 " in lines[0]


def test_a_lens_that_agrees_with_the_resim_reports_nothing(monkeypatch, capsys):
    day = "2026-11-06"
    lens._LENS_STATE_BEHIND_NOTED.clear()
    monkeypatch.setattr(lens, "read_json_file", lambda _p: _resim_snapshot(day, ["2"]))
    out = lens._attach_native_resim([{"event_id": "2", "status": "Live", "live_state": {"in_progress": True}}], day)
    assert out["state_check"]["lens_not_started"] == [] and out["state_check"]["lens_live"] == 1
    assert "LENS_STATE_BEHIND_RESIM" not in capsys.readouterr().out
