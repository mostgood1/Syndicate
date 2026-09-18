"""`#673`: a soccer projection's as-of is its OWN match's file, not its league's last-loaded one.

`_load_one` wrote `generated_at_by_league[league]` once per FILE, and the board
stamped every row from that map. Across a 7-date slate window the last date
loaded won, so a row carried another file's age. The production shape that makes
it matter, read 2026-09-18: mls `recommendations_2026-09-19.json` built 13:02:22Z
and `..._2026-09-20.json` built 04:16:51Z -- every 09-19 MLS row would have read
nine hours older than its own sim.

Both tests fail on the pre-change code.
"""
from __future__ import annotations

import json
from pathlib import Path

from syndicate.features.shared.soccer_projections import attach_soccer_projections, load_soccer_projections

NEWER = "2026-09-18T13:02:22+00:00"   # the 09-19 file, rebuilt this morning
OLDER = "2026-09-18T04:16:51+00:00"   # the 09-20 file, built overnight


def _write(root: Path, date: str, generated_at: str, home: str, away: str, match_id: str) -> None:
    folder = root / "mls" / "api" / "recommendations"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"recommendations_{date}.json").write_text(json.dumps({
        "league": "mls",
        "date": date,
        "generated_at": generated_at,
        "matches": [{
            "match_id": match_id, "event_id": match_id, "league": "mls", "date": date,
            "matchup": {"home_team": home, "away_team": away},
            "win_probability": {"home": 0.5, "draw": 0.25, "away": 0.25},
        }],
    }), encoding="utf-8")


def _game_row(home: str, away: str) -> dict:
    return {"sport": "soccer", "kind": "game", "market": "h2h", "league": "mls",
            "home_team": home, "away_team": away, "side": "home"}


def test_each_row_carries_its_own_files_as_of(tmp_path: Path) -> None:
    _write(tmp_path, "2026-09-19", NEWER, "FC Dallas", "Austin FC", "761822")
    _write(tmp_path, "2026-09-20", OLDER, "Inter Miami CF", "San Diego FC", "761900")
    index = load_soccer_projections([tmp_path], "2026-09-18", window_dates=["2026-09-19", "2026-09-20"])

    dallas, miami = _game_row("FC Dallas", "Austin FC"), _game_row("Inter Miami CF", "San Diego FC")
    attach_soccer_projections([dallas, miami], index)

    assert dallas["projection"]["generated_at"] == NEWER   # pre-change: OLDER, the last file read
    assert miami["projection"]["generated_at"] == OLDER


def test_the_league_stamp_is_the_OLDEST_file_whatever_the_load_order(tmp_path: Path) -> None:
    _write(tmp_path, "2026-09-19", OLDER, "FC Dallas", "Austin FC", "761822")
    _write(tmp_path, "2026-09-20", NEWER, "Inter Miami CF", "San Diego FC", "761900")
    index = load_soccer_projections([tmp_path], "2026-09-18", window_dates=["2026-09-19", "2026-09-20"])

    # Pre-change this read NEWER: the 09-20 file loaded last.
    assert index.generated_at_by_league == {"mls": OLDER}
    coverage = attach_soccer_projections([_game_row("FC Dallas", "Austin FC")], index)
    assert coverage["generated_at_by_league"] == {"mls": OLDER}
