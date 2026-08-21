"""The soccer live joins must work from the service that BUILDS THE BOARD.

Measured 2026-08-21 17:05Z: gate 1 reported "no published live-state artifact
for any league" while all ten per-league files existed and were seconds old.
They are a filesystem write on live-odds-worker; the board is built on
refresh-worker, a different box. `Path.iterdir()` cannot cross that.

`live/soccer_live_lens.json` goes through `refresh_state_store` (keyvalue,
shared key space), so it is the only soccer live data the board build can read.
These tests pin the AGGREGATE path specifically -- the per-league tests pass
whether or not the aggregate works, which is exactly how the inert version
shipped green.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import board_enrichment
from syndicate.features.shared import soccer_live_gameline_source as src

# The loader only accepts a snapshot whose `date` matches the requested one,
# so the fixture must speak about the same day the assertions ask about.
_TODAY = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat()


def _projection():
    return {
        "simulations": 400,
        "home_win_probability": 0.62,
        "draw_probability": 0.23,
        "away_win_probability": 0.15,
        "projected_final_home_goals": 1.9,
        "projected_final_away_goals": 1.1,
        "projected_final_total": 3.0,
        "over_2_5_probability": 0.58,
    }


def _aggregate_game():
    return {
        "league": "epl",
        "event_id": "401879301",
        "home_team": "Arsenal",
        "away_team": "Coventry City",
        "score_home": 2,
        "score_away": 0,
        "status_display_clock": "63'",
        "projection": _projection(),
        "live_player_props": [{
            "player_name": "Kai Havertz",
            "shots_so_far": 2,
            "projected_final_shots": 3.4,
            "shots_over_probabilities": {"0.5": 0.97, "2.5": 0.61},
        }],
    }


def _now_iso(offset_seconds: int = 0) -> str:
    """A RELATIVE timestamp, because gate 1 refuses an artifact older than
    `_LENS_STATE_MAX_AGE_SECONDS`. The first version of this fixture hardcoded
    `2026-08-21T19:20:00+00:00`; it passed when written and failed an hour
    later as wall-clock moved past the staleness bound -- the code was right
    and the test was time-dependent."""
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)).isoformat()


def _write_aggregate(root, games, *, date=_TODAY, generated_at=None):
    generated_at = generated_at or _now_iso()
    d = root / "live"
    d.mkdir(parents=True, exist_ok=True)
    (d / "soccer_live_lens.json").write_text(
        json.dumps({
            "date": date,
            "generated_at": generated_at,
            "leagues_checked": ["epl"],
            "leagues_with_games": ["epl"] if games else [],
            "count": len(games),
            "games": games,
            "errors": [],
        }),
        encoding="utf-8",
    )


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path
    )
    return tmp_path


def test_aggregate_alone_feeds_the_games_loader(root):
    """NO per-league tree exists here -- exactly the board build's situation."""
    _write_aggregate(root, [_aggregate_game()])
    games = src.soccer_live_games(_TODAY)
    assert len(games) == 1
    assert games[0]["home_team"] == "Arsenal"
    assert games[0]["projection"]["simulations"] == 400


def test_gate3_index_builds_from_the_aggregate_alone(root):
    _write_aggregate(root, [_aggregate_game()])
    idx = src.soccer_live_gameline_index(_TODAY)
    assert list(idx) == [("coventry city", "arsenal")]
    hit = idx[("coventry city", "arsenal")]
    assert hit["home_win_prob"] == 0.62
    assert hit["sims_run"] == 400
    assert hit["analytic_markets"]["totals"]["prob_over"] == 0.58


def test_gate2_index_builds_from_the_aggregate_alone(root):
    _write_aggregate(root, [_aggregate_game()])
    report = src.soccer_live_prop_index(_TODAY)
    assert report["live_games"] == 1
    assert report["rows_indexed"] == 2
    assert ("kai havertz", "player_shots", 2.5) in report["index"]


def test_gate1_corrects_from_the_aggregate_alone(root):
    """The reading that was false in production: no per-league tree, aggregate
    present, chip must move pregame -> live."""
    _write_aggregate(root, [_aggregate_game()])
    grid = [{
        "home_team": "Arsenal", "away_team": "Coventry City",
        "game": {"state": "pregame", "status_token": "2:00 PM CT"},
    }]
    out = board_enrichment.attach_live_game_state_from_lens(
        grid, sport="soccer", selected_date=_TODAY)
    assert out["supported"] is True
    assert out["rows_corrected"] == 1, out
    assert grid[0]["game"]["state"] == "live"
    assert grid[0]["game"]["home_score"] == 2


def test_a_stale_dated_aggregate_is_refused(root):
    """A snapshot for another date must not price today's board."""
    _write_aggregate(root, [_aggregate_game()], date="1999-01-01")
    assert src.soccer_live_games(_TODAY) == []


def test_empty_aggregate_falls_through_rather_than_masking(root):
    """An aggregate with no games must not shadow a readable per-league tree --
    otherwise live-odds-worker, where the files ARE local, would go blind."""
    _write_aggregate(root, [])
    d = root / "soccer_source" / "epl" / "api" / "live_state"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"live_state_{_TODAY}.json").write_text(
        json.dumps({
            "league": "epl", "date": _TODAY,
            "generated_at": "2026-08-21T19:20:00+00:00",
            "games": {"1": _aggregate_game()}, "match_box": {},
        }),
        encoding="utf-8",
    )
    games = src.soccer_live_games(_TODAY)
    assert len(games) == 1, "per-league fallback was shadowed by an empty aggregate"
