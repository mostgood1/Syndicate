"""Soccer's live game-state join on the Layer 1/2 boards.

REACHABILITY FIRST, then correctness -- the order `model_engine_standard.md`
requires. `off != on` is asserted before any behaviour, because every defect
this file guards against is silent: an unwired sport and a wired-but-matching-
nothing sport both render as a blank live column.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import board_enrichment


def _write_live_state(root, league, date, match_box, generated_at):
    path = root / "soccer_source" / league / "api" / "live_state"
    path.mkdir(parents=True, exist_ok=True)
    (path / f"live_state_{date}.json").write_text(
        json.dumps(
            {
                "league": league,
                "date": date,
                "generated_at": generated_at,
                "count": 0,
                "games": {},
                "match_box": match_box,
                "match_box_count": len(match_box),
            }
        ),
        encoding="utf-8",
    )


def _now_iso(offset_seconds=0):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)).isoformat()


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path
    )
    return tmp_path


def _grid(state="pregame"):
    return [
        {
            "home_team": "Rayo Vallecano",
            "away_team": "Alaves",
            "game": {"state": state, "status_token": "Fri, Aug 21 - 2:00 PM CT"},
        }
    ]


def test_unwired_sport_still_reports_unsupported():
    """The stated reason is the contract. A sport with no source must never
    read as `supported: true, corrected 0` -- that is indistinguishable from a
    working join over an empty slate."""
    result = board_enrichment.attach_live_game_state_from_lens(
        _grid(), sport="nhl", selected_date="2026-08-21"
    )
    assert result["supported"] is False
    assert "nhl" in result["reason"]


def test_soccer_is_reachable_off_vs_on(data_root):
    """OFF != ON. Without an artifact soccer corrects nothing; with one it
    corrects. If this test can be made to pass by deleting the soccer branch,
    the branch is inert."""
    grid_off = _grid()
    off = board_enrichment.attach_live_game_state_from_lens(
        grid_off, sport="soccer", selected_date="2026-08-21"
    )
    assert off["rows_corrected"] == 0
    assert grid_off[0]["game"]["state"] == "pregame"

    _write_live_state(
        data_root,
        "la_liga",
        "2026-08-21",
        {
            "401882908": {
                "event_id": "401882908",
                "home_team": "Rayo Vallecano",
                "away_team": "Alaves",
                "status_state": "in",
                "status_detail": "70'",
                "score_home": 1,
                "score_away": 0,
                "final": False,
            }
        },
        _now_iso(),
    )
    grid_on = _grid()
    on = board_enrichment.attach_live_game_state_from_lens(
        grid_on, sport="soccer", selected_date="2026-08-21"
    )
    assert on["rows_corrected"] == 1, on
    assert grid_on[0]["game"]["state"] == "live"
    assert grid_on[0]["game"]["home_score"] == 1
    assert grid_on[0]["game"]["state_source"] == "soccer_live_state"


def test_soccer_reads_match_box_not_games(data_root):
    """A FINISHED match lives only in `match_box`; `games` is in-play only by
    the poller's own contract. Reading `games` would leave every completed
    match frozen -- the exact bug gate 1 exists to fix."""
    _write_live_state(
        data_root,
        "la_liga",
        "2026-08-21",
        {
            "401882908": {
                "home_team": "Rayo Vallecano",
                "away_team": "Alaves",
                "status_state": "post",
                "status_detail": "FT",
                "score_home": 1,
                "score_away": 1,
                "final": True,
            }
        },
        _now_iso(),
    )
    grid = _grid(state="live")
    result = board_enrichment.attach_live_game_state_from_lens(
        grid, sport="soccer", selected_date="2026-08-21"
    )
    assert result["rows_corrected"] == 1
    assert grid[0]["game"]["state"] == "final"
    assert grid[0]["game"]["status_token"] == "FINAL"
    assert result["transitions"] == {"live->final": 1}


def test_final_is_terminal(data_root):
    """A settled market must never re-open. Final only ever becomes wrong in
    one direction."""
    _write_live_state(
        data_root,
        "la_liga",
        "2026-08-21",
        {
            "1": {
                "home_team": "Rayo Vallecano",
                "away_team": "Alaves",
                "status_state": "in",
                "score_home": 0,
                "score_away": 0,
                "final": False,
            }
        },
        _now_iso(),
    )
    grid = _grid(state="final")
    result = board_enrichment.attach_live_game_state_from_lens(
        grid, sport="soccer", selected_date="2026-08-21"
    )
    assert result["rows_corrected"] == 0
    assert grid[0]["game"]["state"] == "final"


def test_stale_artifact_refuses_to_correct(data_root):
    """A wedged poller must not freeze the board harder than the bug."""
    _write_live_state(
        data_root,
        "la_liga",
        "2026-08-21",
        {
            "1": {
                "home_team": "Rayo Vallecano",
                "away_team": "Alaves",
                "status_state": "in",
                "score_home": 3,
                "score_away": 0,
                "final": False,
            }
        },
        _now_iso(offset_seconds=board_enrichment._LENS_STATE_MAX_AGE_SECONDS + 120),
    )
    grid = _grid()
    result = board_enrichment.attach_live_game_state_from_lens(
        grid, sport="soccer", selected_date="2026-08-21"
    )
    assert result["rows_corrected"] == 0
    assert "stale" in result["reason"]
    assert grid[0]["game"]["state"] == "pregame"


def test_absent_artifact_is_distinguishable_from_empty_slate(data_root):
    """Three zeros with three different fixes must not render identically."""
    absent = board_enrichment.attach_live_game_state_from_lens(
        _grid(), sport="soccer", selected_date="2026-08-21"
    )
    assert absent["reason"] == "no published live-state artifact for any league"

    _write_live_state(data_root, "epl", "2026-08-21", {}, _now_iso())
    empty = board_enrichment.attach_live_game_state_from_lens(
        _grid(), sport="soccer", selected_date="2026-08-21"
    )
    assert empty["reason"] == "live-state artifacts carry no in-play or finished matches"
    assert absent["reason"] != empty["reason"]
