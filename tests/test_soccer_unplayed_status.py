"""A postponed, canceled or abandoned match is never FINAL and never a result.

MEASURED ON PRODUCTION 2026-09-16 20:15-20:18Z: La Liga ATH @ LEV (`401882870`)
moved to ESPN `STATUS_POSTPONED`, and `/api/board/game-chips?sports=soccer` served
it as `state: final`, `status_token: FINAL`, `0-0` on three consecutive reads.
ESPN files a postponement under `status.type.state: "post"` -- the state of a
finished match -- and distinguishes it only by `completed: false` and the status
name. `fetch_events` copied `state` verbatim, so every `== "post"` reader took it
as a finished 0-0, including the aggregate's `finals`, which settlement grades.

One test per point the value passes through: the ESPN parse, the finals
collector, and the card state that the chip is built from.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from syndicate.features.soccer.ingestion import espn_lineups


def _event(event_id: str, status_type: dict) -> dict:
    return {
        "id": event_id,
        "competitions": [
            {
                "status": {"type": status_type, "displayClock": "0'", "period": 0},
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Levante"}, "score": "0"},
                    {"homeAway": "away", "team": {"displayName": "Athletic Club"}, "score": "0"},
                ],
            }
        ],
    }


VOID = "void"  # spelled out so a pre-change run fails on the assertion, not an import


def test_the_unplayed_state_is_void():
    assert getattr(espn_lineups, "UNPLAYED_STATE", None) == VOID


# The two status blocks read off ESPN's La Liga scoreboard on 2026-09-16.
_POSTPONED = {"id": "6", "name": "STATUS_POSTPONED", "state": "post", "completed": False,
              "description": "Postponed", "detail": "Postponed", "shortDetail": "Postponed"}
_FULL_TIME = {"id": "28", "name": "STATUS_FULL_TIME", "state": "post", "completed": True,
              "description": "Full Time", "detail": "FT", "shortDetail": "FT"}


def _fetch(events: list[dict], statuses=None) -> dict:
    with patch.object(espn_lineups, "fetch_espn_scoreboard", return_value={"events": events}):
        rows = espn_lineups.fetch_events("la_liga", date_windows=["20260916"], statuses=statuses)
    return {row["event_id"]: row for row in rows}


# --- the ESPN parse -------------------------------------------------------------


def test_a_postponed_match_is_parsed_as_void_not_post():
    rows = _fetch([_event("401882870", _POSTPONED), _event("401882875", _FULL_TIME)])
    assert rows["401882870"]["status_state"] == VOID
    assert rows["401882870"]["status_completed"] is False
    assert rows["401882875"]["status_state"] == "post"


def test_a_caller_asking_for_finished_matches_does_not_get_a_postponement():
    """The poller asks for `{"in", "post"}`; that is how a box got written."""
    rows = _fetch([_event("401882870", _POSTPONED), _event("401882875", _FULL_TIME)], statuses={"in", "post"})
    assert set(rows) == {"401882875"}


def test_a_final_whose_payload_lacks_the_completed_flag_stays_final():
    """Absent is not unplayed: the rule must not un-finish a real result."""
    rows = _fetch([_event("e1", {"state": "post", "detail": "FT"})])
    assert rows["e1"]["status_state"] == "post"


def test_canceled_and_abandoned_are_unplayed_by_name():
    rows = _fetch([
        _event("c", {"state": "post", "name": "STATUS_CANCELED"}),
        _event("a", {"state": "post", "name": "STATUS_ABANDONED"}),
        _event("i", {"state": "in", "completed": False}),
    ])
    assert rows["c"]["status_state"] == VOID
    assert rows["a"]["status_state"] == VOID
    assert rows["i"]["status_state"] == "in"


# --- the finals collector (what settlement grades from) -------------------------


def test_the_finals_collector_skips_a_stale_postponed_box(tmp_path):
    """The exact record already on disk on 2026-09-16: written before the parse
    fix, so `status_state: "post"`, `final: true`, detail "Postponed"."""
    from scripts.poll_soccer_live_state import _finished_matches

    league_dir = tmp_path / "la_liga" / "api" / "live_state"
    league_dir.mkdir(parents=True)
    (league_dir / "live_state_2026-09-16.json").write_text(json.dumps({
        "match_box": {
            "401882870": {"home_team": "Levante", "away_team": "Athletic Club", "score_home": "0",
                          "score_away": "0", "status_state": "post", "final": True,
                          "status_detail": "Postponed"},
            "401882875": {"home_team": "Atletico Madrid", "away_team": "Osasuna", "score_home": "4",
                          "score_away": "0", "status_state": "post", "final": True, "status_detail": "FT"},
        }
    }), encoding="utf-8")

    finals = {row["event_id"] for row in _finished_matches(["la_liga"], "2026-09-16", source_root=tmp_path)}

    assert finals == {"401882875"}


# --- the card state the chip is built from ---------------------------------------


def _kicked_off(hours_ago: float = 1.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_a_stale_postponed_box_does_not_make_the_card_final():
    from syndicate.features.soccer.cards import _effective_state_with_box

    box = {"event_id": "401882870", "status_state": "post", "final": True, "status_detail": "Postponed"}
    assert _effective_state_with_box("post", _kicked_off(), box) == VOID
    assert _effective_state_with_box("pre", _kicked_off(), box) == VOID


def test_a_real_final_box_is_still_final():
    from syndicate.features.soccer.cards import _effective_state_with_box

    box = {"event_id": "401882875", "status_state": "post", "final": True, "status_detail": "FT"}
    assert _effective_state_with_box("in", _kicked_off(2.0), box) == "post"


def test_the_chip_for_a_void_match_is_not_final():
    """End of the path: the chip reads `live_state`, which `_live_state_block`
    builds from the effective state."""
    from syndicate.features.shared.game_chip_scoreboard import build_game_chip
    from syndicate.features.soccer.cards import _live_state_block

    block = _live_state_block(VOID, _kicked_off())
    assert block["final"] is False and block["in_progress"] is False

    chip = build_game_chip("soccer", {
        "away_team": "Athletic Club", "home_team": "Levante", "gamePk": "401882870",
        "scheduled_start_utc": _kicked_off(), "live_state": block,
    })
    assert chip["state"] != "final"
    assert chip["status_token"] != "FINAL"
