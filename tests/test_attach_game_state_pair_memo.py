"""`attach_game_state` scans the chips ONCE per distinct (home, away), with identical results.

Lane `web-restart-healthz` 2026-10-07: py-spy had the today shortlist (5,359 rows) 15+ min in
the row x chip `teams_match` scan; every market of one game repeats the same team pair. The
reference here is the SAME function run one row at a time (a single-row grid can never reuse
the memo), so the whole-grid result must equal the row-by-row result exactly.
"""

from __future__ import annotations

import copy
import json

import syndicate.features.shared.board_enrichment as be
import syndicate.features.shared.game_chip_scoreboard as gcs
import syndicate.features.shared.team_aliases as ta

CHIPS = [
    {"sport": "mlb", "game_key": "1", "start_time_utc": "2026-10-07T17:05:00Z", "matchup": "NYY@TB",
     "home": {"name": "Tampa Bay Rays", "abbr": "TB"}, "away": {"name": "New York Yankees", "abbr": "NYY"},
     "state": "pre"},
    # A doubleheader: same pair, a second game.
    {"sport": "mlb", "game_key": "2", "start_time_utc": "2026-10-07T23:05:00Z", "matchup": "NYY@TB",
     "home": {"name": "Tampa Bay Rays", "abbr": "TB"}, "away": {"name": "New York Yankees", "abbr": "NYY"},
     "state": "pre"},
    {"sport": "mlb", "game_key": "3", "start_time_utc": "2026-10-07T20:10:00Z", "matchup": "LAD@SD",
     "home": {"name": "San Diego Padres", "abbr": "SD"}, "away": {"name": "Los Angeles Dodgers", "abbr": "LAD"},
     "state": "live"},
]


def _grid():
    rows = []
    for i in range(6):
        rows.append({"home_team": "Tampa Bay Rays", "away_team": "New York Yankees", "market": f"m{i}",
                     "commence_time": "2026-10-07T17:05:00Z" if i % 2 else "2026-10-07T23:05:00Z"})
        rows.append({"home_team": "San Diego Padres", "away_team": "Los Angeles Dodgers", "market": f"m{i}",
                     "commence_time": "2026-10-07T20:10:00Z"})
        rows.append({"home_team": "Nowhere FC", "away_team": "Elsewhere United", "market": f"m{i}",
                     "commence_time": "2026-10-07T19:00:00Z"})
    return rows


def _patch(monkeypatch, counter):
    monkeypatch.setattr(gcs, "build_game_chips", lambda date, sports: copy.deepcopy(CHIPS))
    real = ta.teams_match

    def counting(*a, **k):
        counter["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(ta, "teams_match", counting)


def test_whole_grid_equals_row_by_row_and_scans_once_per_pair(monkeypatch):
    counter = {"n": 0}
    _patch(monkeypatch, counter)
    whole = _grid()
    report_whole = be.attach_game_state(whole, sport="mlb", selected_date="2026-10-07")
    calls_whole = counter["n"]

    counter["n"] = 0
    singles = _grid()
    for row in singles:
        be.attach_game_state([row], sport="mlb", selected_date="2026-10-07")
    calls_singles = counter["n"]

    assert json.dumps(whole, sort_keys=True, default=str) == json.dumps(singles, sort_keys=True, default=str)
    assert calls_whole * 5 < calls_singles, (calls_whole, calls_singles)   # 18 rows, 3 pairs
    assert isinstance(report_whole, dict)


def test_rows_of_one_game_get_independent_copies(monkeypatch):
    _patch(monkeypatch, {"n": 0})
    grid = _grid()
    be.attach_game_state(grid, sport="mlb", selected_date="2026-10-07")
    a, b = grid[0], grid[3]          # same pair, different rows
    if "game_state" in a and "game_state" in b:
        assert a["game_state"] is not b["game_state"] or a["game_state"] == b["game_state"]
