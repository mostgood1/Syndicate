"""The grid's soccer projection read includes the day BEFORE its UTC anchor (lane `mls-board-evening-gaps`).

A book-grid artifact is keyed by UTC kickoff date; the soccer sim files a fixture
under its LOCAL date. An MLS kickoff at 7:30pm Central is 00:30Z the next day, so
its rows sit in the next day's grid while its projections sit in
`recommendations_<local date>.json` -- one date before the grid's forward window.

Measured on production 2026-09-19: the UTC-09-20 grid read projections for
09-20..09-26, reported `unmatched_by_league: {"mls": 3730}`, and all nine MLS
fixtures kicking off after 00:00Z carried no projection. Every one was in
`mls/.../recommendations_2026-09-19.json`.

Both tests go through the production caller (`_attach_projections_by_sport`), and
both fail on the code before this change.
"""
from __future__ import annotations

import json
from pathlib import Path

from syndicate.features.shared import board_enrichment
from syndicate.features.shared import soccer_projections
from syndicate.features.shared import source_roots


def _write(root: Path, league: str, date: str, matches: list[tuple[str, str, str, str]]) -> None:
    path = root / league / "api" / "recommendations" / f"recommendations_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "league": league,
        "date": date,
        "generated_at": f"{date}T13:44:16+00:00",
        "matches": [
            {"event_id": event_id, "match_id": event_id, "date": date, "kickoff": kickoff,
             "matchup": {"home_team": home, "away_team": away}}
            for event_id, kickoff, home, away in matches
        ],
    }), encoding="utf-8")


def _row(home: str, away: str, commence: str) -> dict:
    return {"sport": "soccer", "league": "mls", "market": "h2h", "kind": "game", "segment": "full",
            "home_team": home, "away_team": away, "commence_time": commence, "line": None}


def test_the_production_caller_reads_the_day_before_its_utc_anchor(monkeypatch):
    seen: dict = {}

    def capture(roots, selected_date, window_dates=None):
        seen["window"] = list(window_dates or [])
        return soccer_projections.SoccerProjectionIndex()

    monkeypatch.setattr(soccer_projections, "load_soccer_projections", capture)
    board_enrichment._attach_projections_by_sport([], sport="soccer", selected_date="2026-09-20")
    window = seen["window"]
    # Previous day FIRST, then the unchanged forward window, anchor included.
    assert window[0] == "2026-09-19"
    assert window[1] == "2026-09-20"
    assert "2026-09-18" not in window, "one day back, not a symmetric window"


def test_an_evening_fixture_filed_under_the_previous_local_date_is_joined(tmp_path, monkeypatch):
    # The 2026-09-19 production shape, cut to two fixtures.
    _write(tmp_path, "mls", "2026-09-19", [
        ("761822", "2026-09-20T00:30Z", "FC Dallas", "Austin FC"),     # evening, filed under 09-19
        ("761818", "2026-09-19T23:30Z", "CF Montreal", "Columbus Crew"),
    ])
    _write(tmp_path, "mls", "2026-09-20", [
        ("761900", "2026-09-20T23:00Z", "Inter Miami CF", "San Diego FC"),
    ])
    monkeypatch.setattr(source_roots, "preferred_artifact_roots", lambda *a, **k: [tmp_path])

    grid = [
        _row("FC Dallas", "Austin FC", "2026-09-20T00:30:00Z"),       # in the UTC-09-20 grid
        _row("Inter Miami CF", "San Diego FC", "2026-09-20T23:00:00Z"),
    ]
    result = board_enrichment._attach_projections_by_sport(grid, sport="soccer", selected_date="2026-09-20")

    # Pre-change: 1 (FC Dallas unmatched) and `dates_read` starting 2026-09-20.
    assert result.get("unmatched_match_rows") == 0, result.get("unmatched_fixture_sample")
    assert result.get("dates_read", [])[:2] == ["2026-09-19", "2026-09-20"]
