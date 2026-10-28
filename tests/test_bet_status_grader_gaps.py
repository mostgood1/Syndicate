"""The grader gaps behind 981 stale paper orders (lane `paper-evicted-grading`, `#744`).

Read on the fleet 2026-10-27 23:15Z: 0 of 981 orders whose game started more
than 48 h ago could grade, and the refusals were named gaps, not eviction.
Pre-registered as H1-H4 in `.syndicate/findings_2026-10-27_paper_evicted_ungraded.md`:

  H1  soccer bound every read to the SLATE date; a forward bet's match is days later
  H2  soccer had no corners or both-teams-to-score rule (`unmapped_market`)
  H3  NCAAF names: "San José State" (accent) and "McNeese State" (OddsAPI's long form)
  H4  MLB never fetched a missing feed, and nothing cached the postseason

Each group's FIRST test proves the new branch is reached: the old code refused
every one of these orders by name.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import bet_status_mlb as mlb
from syndicate.features.shared import bet_status_soccer as soccer
from syndicate.features.shared.bet_status import STATUS_LOST, STATUS_WON, resolve_bet_status
from syndicate.features.shared.ncaaf_team_registry import resolve_ncaaf_team_id


def _status(order, resolved):
    return resolve_bet_status(
        market=order.get("market"),
        side=resolved.get("side", order.get("side")),
        line=resolved.get("line", order.get("line")),
        current_value=resolved.get("current_value"),
        is_final=bool(resolved.get("is_final")),
        started=bool(resolved.get("started", True)),
    )["status"]


# ---------------------------------------------------------------------------
# H1 / H2 -- soccer
# ---------------------------------------------------------------------------

def _record(home="Chelsea", away="Bournemouth", sh="2", sa="1", *, final=True, state="post", corners=("6", "8")):
    def stats(count):
        return {"Shots": "11", "Corners": count} if count is not None else {"Shots": "11"}

    return {
        "home_team": home, "away_team": away, "score_home": sh, "score_away": sa,
        "final": final, "status_state": state, "status_period": 2,
        "home_linescores": [1, 1], "away_linescores": [0, 1],
        "teams": {"home": {"team": home, "stats": stats(corners[0])},
                  "away": {"team": away, "stats": stats(corners[1])}},
    }


def _forward(**over):
    """Placed on the 10-04 slate for a match on 10-10 -- the fleet's typical row."""
    order = {
        "sport": "soccer", "market": "h2h", "side": "home", "line": None,
        "home_team": "Chelsea", "away_team": "Bournemouth", "segment": "full",
        "selected_date": "2026-10-04", "commence_time": "2026-10-10T14:00:00Z",
    }
    order.update(over)
    return order


@pytest.fixture
def boxes(monkeypatch):
    """`{date: [match_box records]}`, and the date lists the resolver asked for."""
    store: dict[str, list[dict]] = {}
    asked: list[list[str]] = []

    def load(dates):
        asked.append(list(dates))
        return [dict(r) for day in dates for r in store.get(day, [])]

    monkeypatch.setattr(soccer, "_load_match_box_records", load)
    # The slate's own state has rolled away, as it has for every archived row.
    monkeypatch.setattr(soccer, "_load_matches", lambda _date: None)
    monkeypatch.setattr(soccer, "_load_player_boxes", lambda _date: [])
    return store, asked


def test_a_forward_soccer_bet_grades_off_its_own_kickoff_date(boxes):
    store, asked = boxes
    store["2026-10-10"] = [_record(sh="2", sa="1")]
    order = _forward()
    resolved = soccer.soccer_status_resolver("2026-10-04")(order)
    assert "unavailable_reason" not in resolved, resolved
    assert asked and asked[0] == ["2026-10-10"]          # the kickoff date, read first
    assert _status(order, resolved) == STATUS_WON


def test_without_the_box_the_same_forward_bet_still_refuses(boxes):
    order = _forward()
    resolved = soccer.soccer_status_resolver("2026-10-04")(order)
    assert resolved == {"unavailable_reason": soccer.REASON_MATCH_NOT_FOUND}


def test_a_forward_bet_never_reads_the_slate_dates_state(monkeypatch, boxes):
    """The same pair on the slate date is ANOTHER match, so it must not answer."""
    store, _ = boxes
    store["2026-10-10"] = [_record(sh="2", sa="1")]
    monkeypatch.setattr(soccer, "_load_matches", lambda _date: [
        {"home_team": "Chelsea", "away_team": "Bournemouth", "home_score": 0, "away_score": 3, "final": True}])
    order = _forward()
    assert _status(order, soccer.soccer_status_resolver("2026-10-04")(order)) == STATUS_WON


def test_an_on_slate_bet_still_reads_the_slate_state_first(monkeypatch, boxes):
    """In-play grading is unchanged: the aggregate answers while it holds the match."""
    store, asked = boxes
    store["2026-10-10"] = [_record(sh="2", sa="1")]
    monkeypatch.setattr(soccer, "_load_matches", lambda _date: [
        {"home_team": "Chelsea", "away_team": "Bournemouth", "home_score": 1, "away_score": 0, "final": False}])
    order = _forward(selected_date="2026-10-10")
    resolved = soccer.soccer_status_resolver("2026-10-10")(order)
    assert resolved["is_final"] is False
    assert asked == []


def test_a_finished_copy_beats_an_in_play_one_and_pre_is_not_started(boxes):
    store, _ = boxes
    store["2026-10-10"] = [_record(sh="0", sa="0", final=False, state="in")]
    store["2026-10-09"] = [_record(sh="2", sa="1")]
    order = _forward()
    resolved = soccer.soccer_status_resolver("2026-10-04")(order)
    assert resolved["is_final"] is True
    store["2026-10-09"] = []
    store["2026-10-10"] = [_record(sh=None, sa=None, final=False, state="pre")]
    assert soccer.soccer_status_resolver("2026-10-04")(order)["started"] is False


@pytest.mark.parametrize("side,line,expected", [("over", 10.5, STATUS_WON), ("under", 10.5, STATUS_LOST),
                                                ("under", 14.5, STATUS_WON)])
def test_corners_grade_off_both_teams_counts(boxes, side, line, expected):
    store, _ = boxes
    store["2026-10-10"] = [_record(corners=("6", "8"))]
    order = _forward(market="alternate_totals_corners", side=side, line=line)
    resolved = soccer.soccer_status_resolver("2026-10-04")(order)
    assert resolved["current_value"] == 14.0
    assert _status(order, resolved) == expected


def test_corners_read_the_box_even_on_slate_and_a_missing_count_is_not_zero(monkeypatch, boxes):
    store, _ = boxes
    monkeypatch.setattr(soccer, "_load_matches", lambda _date: [
        {"home_team": "Chelsea", "away_team": "Bournemouth", "home_score": 2, "away_score": 1, "final": True}])
    store["2026-10-10"] = [_record(corners=("6", None))]
    order = _forward(market="alternate_totals_corners", side="under", line=10.5, selected_date="2026-10-10")
    assert soccer.soccer_status_resolver("2026-10-10")(order) == {"unavailable_reason": soccer.REASON_NO_CORNERS}


@pytest.mark.parametrize("score,side,expected", [(("2", "1"), "yes", STATUS_WON), (("2", "1"), "no", STATUS_LOST),
                                                 (("1", "0"), "yes", STATUS_LOST), (("0", "0"), "no", STATUS_WON)])
def test_both_teams_to_score(boxes, score, side, expected):
    store, _ = boxes
    store["2026-10-10"] = [_record(sh=score[0], sa=score[1])]
    order = _forward(market="btts", side=side, line=None)
    resolved = soccer.soccer_status_resolver("2026-10-04")(order)
    assert resolved["line"] == 0.5
    assert _status(order, resolved) == expected


def test_half_corners_and_half_btts_refuse_by_name(boxes):
    store, _ = boxes
    store["2026-10-10"] = [_record()]
    for market in ("alternate_totals_corners", "btts"):
        resolved = soccer.soccer_status_resolver("2026-10-04")(_forward(market=market, side="over", line=4.5, segment="h1"))
        assert resolved["unavailable_reason"].endswith("h1")


def test_the_box_files_are_read_off_disk_by_kickoff_date(monkeypatch, tmp_path):
    """End to end over the real reader: a 10-04 corners order, its match filed under 10-10."""
    from syndicate.features.shared import refresh_state_store

    path = tmp_path / "soccer_source" / "epl" / "api" / "live_state" / "live_state_2026-10-10.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"match_box": {"401": _record(corners=("3", "4"))}}), encoding="utf-8")
    monkeypatch.setattr(refresh_state_store, "data_root", lambda: tmp_path)
    monkeypatch.setattr(soccer, "_load_matches", lambda _date: None)
    order = _forward(market="alternate_totals_corners", side="under", line=9.5)
    resolved = soccer.soccer_status_resolver("2026-10-04")(order)
    assert resolved["current_value"] == 7.0
    assert _status(order, resolved) == STATUS_WON


def test_a_store_miss_falls_back_to_the_pollers_file_on_disk(monkeypatch, tmp_path):
    """The poller writes these files to DISK; on the keyvalue backend a bare store
    read asks Redis only, where a dated key lives ten days. Fleet, 2026-10-27:
    25 of 497 stale soccer orders graded through the store alone, 494 with this."""
    from syndicate.features.shared import refresh_state_store
    from syndicate.features.soccer import sources

    disk = tmp_path / "disk" / "live_state_2026-10-10.json"
    disk.parent.mkdir(parents=True, exist_ok=True)
    disk.write_text(json.dumps({"match_box": {"401": _record(corners=("5", "5"))}}), encoding="utf-8")
    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: None)   # Redis: expired
    monkeypatch.setattr(sources, "live_state_path",
                        lambda league, day: disk if (league, day) == ("epl", "2026-10-10") else tmp_path / "absent.json")
    records = soccer._load_match_box_records(["2026-10-10"])
    assert [r["home_team"] for r in records] == ["Chelsea"]


# ---------------------------------------------------------------------------
# H3 -- NCAAF names
# ---------------------------------------------------------------------------

def test_san_jose_state_resolves_with_or_without_the_accent():
    team = resolve_ncaaf_team_id("San José State")
    assert team is not None
    assert resolve_ncaaf_team_id("San Jose State Spartans") == team
    assert resolve_ncaaf_team_id("San Jose State") == team


def test_mcneese_state_is_mcneese():
    assert resolve_ncaaf_team_id("McNeese State Cowboys") == resolve_ncaaf_team_id("McNeese") is not None


def test_the_fold_merges_spellings_and_never_two_schools():
    assert resolve_ncaaf_team_id("Michigan State Spartans") != resolve_ncaaf_team_id("Michigan Wolverines")
    assert resolve_ncaaf_team_id("Spartans") is None          # still ambiguous, still refused


# ---------------------------------------------------------------------------
# H4 -- MLB finished-game fetch
# ---------------------------------------------------------------------------

HOME, AWAY = "Milwaukee Brewers", "Tampa Bay Rays"


def _final_feed(home_runs=5, away_runs=4):
    return {
        "gameData": {"status": {"abstractGameState": "Final", "detailedState": "Final"},
                     "datetime": {"officialDate": "2026-10-24"},
                     "teams": {"home": {"name": HOME}, "away": {"name": AWAY}}},
        "liveData": {"linescore": {"teams": {"home": {"runs": home_runs}, "away": {"runs": away_runs}}}},
    }


@pytest.fixture
def mlb_feed(monkeypatch):
    """A cache that holds nothing, and a statsapi that answers -- counted."""
    calls: list[bool] = []
    monkeypatch.setattr(mlb, "_FETCH_ATTEMPTED_AT", {})
    monkeypatch.setattr(
        "syndicate.features.mlb.cards._schedule_raw_games",
        lambda date: [{"gamePk": 849802, "gameDate": "2026-10-25T00:08:00Z",
                       "teams": {"home": {"team": {"name": HOME}}, "away": {"team": {"name": AWAY}}}}],
    )

    def load(date, pk, fetch_if_missing=True):
        calls.append(bool(fetch_if_missing))
        return _final_feed() if fetch_if_missing else None

    monkeypatch.setattr("syndicate.features.mlb.box_score_stats.load_final_feed", load)
    return calls


def _mlb_order(**over):
    order = {"sport": "mlb", "market": "totals", "side": "over", "line": 8.5, "home_team": HOME,
             "away_team": AWAY, "selected_date": "2026-10-24", "commence_time": "2026-10-25T00:08:00Z"}
    order.update(over)
    return order


def test_a_finished_game_with_no_cached_feed_is_fetched_and_grades(mlb_feed):
    order = _mlb_order()
    resolved = mlb.mlb_status_resolver("2026-10-24")(order)
    assert "unavailable_reason" not in resolved, resolved
    assert mlb_feed == [False, True]                      # the cache first, then one fetch
    assert _status(order, resolved) == STATUS_WON         # 5 + 4 = 9 > 8.5


def test_a_game_still_in_its_first_six_hours_is_never_fetched(mlb_feed, monkeypatch):
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    resolved = mlb.mlb_status_resolver("2026-10-24")(_mlb_order(commence_time=recent))
    assert resolved == {"unavailable_reason": mlb.REASON_NO_FEED}
    assert mlb_feed == [False]


def test_one_fetch_per_game_per_hour_across_resolvers(mlb_feed):
    mlb.mlb_status_resolver("2026-10-24")(_mlb_order())
    second = mlb.mlb_status_resolver("2026-10-24")(_mlb_order())
    assert mlb_feed == [False, True, False]               # the second build does not refetch
    assert second == {"unavailable_reason": mlb.REASON_NO_FEED}
