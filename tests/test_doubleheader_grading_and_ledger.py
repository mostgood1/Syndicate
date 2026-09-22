"""The grading and ledger joins keyed a game by its TEAM PAIR too.

Two separate defects, both measured on production 2026-09-22:

1. `live_gameline_ledger.record_key` had no `event_id`. `game_pk` comes from
   the live-gameline projection and is absent on the segment-refusal path, so
   most records carry no game identity at all (25 of 132 that day had one) and
   two different games collide whenever segment, market, line and `books_key`
   agree. Counted over production ledgers:

       date        records  old keys  keys spanning >1 game  worst
       2026-09-20    1,250       653                     13  ONE key over 14 games
       2026-09-21      746       407                      2  3 games
       2026-09-04    3,041       639                      1  a doubleheader's halves
       2026-08-29    5,554       383                      2  same

   On 09-04 and 08-29 both halves carried the SAME `game_pk` (824424, 823177),
   so even a present gamePk did not separate them.

2. The vendored grading manifest (`build_season_betting_cards_manifest`) keyed
   the day's odds rows on `(away_team, home_team)` and kept the last, so on a
   doubleheader BOTH games graded against the later event's lines.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from syndicate.features.shared.live_gameline_ledger import record_key

MANIFEST = Path(__file__).resolve().parents[1] / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "build_season_betting_cards_manifest.py"


def _manifest_module():
    spec = importlib.util.spec_from_file_location("bscm_for_test", MANIFEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the ledger key ---------------------------------------------------------


def _record(event_id, game_pk=None, market="h2h", line=None, books="bookA,bookB"):
    return {"game_pk": game_pk, "segment": "first5", "market": market, "line": line,
            "books_key": books, "event_id": event_id}


def test_two_games_sharing_every_other_field_are_two_records():
    # The 2026-09-20 shape: game_pk None, same segment/market/line/book set.
    assert record_key(_record("09a8d217")) != record_key(_record("b93df181"))


def test_a_doubleheaders_halves_are_two_records_even_on_one_game_pk():
    # The 2026-09-04 shape: both halves carried gamePk 824424.
    left = _record("a78d8674", game_pk=824424)
    right = _record("062e69d4", game_pk=824424)
    assert record_key(left) != record_key(right)


def test_the_same_market_on_one_game_is_still_one_record():
    # Dedupe must still work: the whole point of the key.
    assert record_key(_record("09a8d217")) == record_key(_record("09a8d217"))


def test_the_existing_key_prefix_is_unchanged():
    # `event_id` is appended, so an old reader comparing the first five slots
    # still sees what it saw (and an existing file re-keys consistently).
    key = record_key(_record("09a8d217", game_pk=824424, line=8.5))
    assert key[:5] == (824424, "first5", "h2h", "8.5", "bookA,bookB")
    assert key[5] == "09a8d217"


def test_a_record_with_no_event_id_still_keys():
    assert record_key(_record(None))[5] == ""


# --- the grading manifest ---------------------------------------------------


G1 = {"away_team": "Tampa Bay Rays", "home_team": "New York Yankees",
      "event_id": "394e1e2b", "commence_time": "2026-09-22T17:06:00Z"}
G2 = {"away_team": "Tampa Bay Rays", "home_team": "New York Yankees",
      "event_id": "574050c1", "commence_time": "2026-09-22T23:06:00Z"}
STARTS = {"823543": "2026-09-22T17:05:00Z", "823494": "2026-09-22T23:05:00Z"}


@pytest.mark.parametrize("game_pk, expected", [(823543, "394e1e2b"), (823494, "574050c1")])
def test_each_half_grades_against_its_own_event(game_pk, expected):
    module = _manifest_module()
    hit = module._match_report_game_row({"game_pk": game_pk}, [G1, G2], STARTS)
    assert (hit or {}).get("event_id") == expected


def test_row_order_does_not_decide():
    module = _manifest_module()
    hit = module._match_report_game_row({"game_pk": 823543}, [G2, G1], STARTS)
    assert (hit or {}).get("event_id") == "394e1e2b"


def test_an_ordinary_game_is_unchanged():
    module = _manifest_module()
    assert module._match_report_game_row({"game_pk": 823543}, [G1], {})["event_id"] == "394e1e2b"


def test_without_a_scheduled_start_it_refuses_rather_than_guesses():
    module = _manifest_module()
    assert module._match_report_game_row({"game_pk": 823543}, [G1, G2], {}) is None


def test_two_events_inside_the_separation_window_are_refused():
    module = _manifest_module()
    near = dict(G2, commence_time="2026-09-22T17:36:00Z")
    assert module._match_report_game_row({"game_pk": 823543}, [G1, near], STARTS) is None


def test_the_lookup_keeps_every_row_for_a_pair(tmp_path):
    module = _manifest_module()
    path = tmp_path / "oddsapi_game_lines_2026_09_22.json"
    path.write_text(json.dumps({"games": [G1, G2]}), encoding="utf-8")
    lookup = module._load_game_lines_lookup(path)
    assert [row["event_id"] for row in lookup[("Tampa Bay Rays", "New York Yankees")]] == ["394e1e2b", "574050c1"]


def test_the_schedule_snapshot_supplies_the_starts(tmp_path, monkeypatch):
    module = _manifest_module()
    snapshot = tmp_path / "daily" / "snapshots" / "2026-09-22"
    snapshot.mkdir(parents=True)
    (snapshot / "schedule_raw.json").write_text(
        json.dumps([{"gamePk": 823543, "gameDate": "2026-09-22T17:05:00Z"},
                    {"gamePk": 823494, "gameDate": "2026-09-22T23:05:00Z"}]), encoding="utf-8")
    monkeypatch.setattr(module, "_odds_data_roots", lambda: [tmp_path])
    assert module._schedule_starts_by_game_pk("2026-09-22") == STARTS


def test_a_missing_schedule_snapshot_is_empty_not_an_error(tmp_path, monkeypatch):
    module = _manifest_module()
    monkeypatch.setattr(module, "_odds_data_roots", lambda: [tmp_path])
    assert module._schedule_starts_by_game_pk("2026-09-22") == {}


# --- the regrade research script -------------------------------------------


def _statsapi_payload():
    """Two TB @ NYY finals on one date, plus an ordinary game."""
    def game(pk, away, home, away_runs, home_runs):
        return {"gamePk": pk, "status": {"abstractGameState": "Final"},
                "teams": {"away": {"team": {"name": away}, "score": away_runs},
                          "home": {"team": {"name": home}, "score": home_runs}}}
    return {"dates": [{"games": [
        game(823543, "Tampa Bay Rays", "New York Yankees", 2, 5),
        game(823494, "Tampa Bay Rays", "New York Yankees", 7, 1),
        game(824785, "Toronto Blue Jays", "Baltimore Orioles", 3, 4),
    ]}]}


def _regrade_module():
    spec = importlib.util.spec_from_file_location(
        "regrade_for_test", Path(__file__).resolve().parents[1] / "scripts" / "regrade_mlb_game_markets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_half_keeps_its_own_final(monkeypatch):
    module = _regrade_module()
    monkeypatch.setattr(module, "_http_json", lambda url: _statsapi_payload())
    finals = module._final_scores_for_date("2026-09-22")
    assert finals["823543"] == (2, 5)
    assert finals["823494"] == (7, 1)


def test_a_doubleheader_pair_is_absent_from_the_name_index(monkeypatch):
    # Absent, not wrong: an older summary with no gamePk gets no score rather
    # than the other half's.
    module = _regrade_module()
    monkeypatch.setattr(module, "_http_json", lambda url: _statsapi_payload())
    finals = module._final_scores_for_date("2026-09-22")
    assert ("Tampa Bay Rays", "New York Yankees") not in finals
    assert finals[("Toronto Blue Jays", "Baltimore Orioles")] == (3, 4)
