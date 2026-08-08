"""#273 -- the NFL grader read a directory nothing writes, and repairing that
alone would have fabricated settlements.

Both halves are pinned, because they fail in opposite directions: the path fix
turns a permanent zero into rows, and the status guard is the only thing keeping
those rows from being invented. A regression in either one is silent -- a dead
read looks like an offseason date, and a placeholder 0-0 looks like a real tie.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from syndicate.features.shared import graded_outcomes


COLUMNS = [
    "game_id", "season", "game_type", "week", "gameday", "gametime",
    "away_team", "home_team", "away_score", "home_score", "status", "venue",
]


def _write_schedule(path: Path, rows: list[dict[str, str]], *, with_status: bool = True) -> None:
    columns = COLUMNS if with_status else [c for c in COLUMNS if c != "status"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})


@pytest.fixture()
def nfl_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "nfl_source"
    root.mkdir()
    monkeypatch.setattr(
        "syndicate.features.nfl.sources.default_nfl_source_root", lambda: root, raising=False
    )
    return root


def test_schedule_at_the_source_root_is_found(nfl_root: Path) -> None:
    """`nfl/sources.py`'s data_path() puts schedule_{season}.csv AT the root.
    The grader used to glob root/"data" (correct for ncaaf, wrong here) and so
    returned [] for every date."""
    _write_schedule(
        nfl_root / "schedule_preseason_2026.csv",
        [{"gameday": "2026-08-07", "away_team": "CAR", "home_team": "ARI",
          "away_score": "17", "home_score": "20", "status": "Final"}],
    )
    assert [p.name for p in graded_outcomes._nfl_schedule_paths()] == ["schedule_preseason_2026.csv"]
    rows = graded_outcomes._nfl_graded_rows_for_date("2026-08-07")
    assert {(row["market"], row["selection"], row["result"]) for row in rows} >= {
        ("moneyline", "ARI", "win"),
        ("moneyline", "CAR", "loss"),
    }


def test_a_data_subdirectory_still_works(nfl_root: Path) -> None:
    """Both locations are searched, so a mirror that grows a data/ subdir later
    does not silently go dark again."""
    _write_schedule(
        nfl_root / "data" / "schedule_preseason_2025.csv",
        [{"gameday": "2025-08-07", "away_team": "BAL", "home_team": "IND",
          "away_score": "24", "home_score": "16", "status": "Final"}],
    )
    rows = graded_outcomes._nfl_graded_rows_for_date("2025-08-07")
    assert any(row["selection"] == "BAL" and row["result"] == "win" for row in rows)


def test_placeholder_zeros_on_an_unplayed_game_grade_NOTHING(nfl_root: Path) -> None:
    """The real 2026 preseason mirror: status "Scheduled", scores "0"/"0" on all
    49 games. Blank-score filtering cannot see these -- "0" is not blank -- so
    without the status guard every unplayed game would emit two moneyline PUSHES
    and a 0-0 spread/total, and settlement would persist them as results."""
    _write_schedule(
        nfl_root / "schedule_preseason_2026.csv",
        [{"gameday": "2026-08-07", "away_team": "CAR", "home_team": "ARI",
          "away_score": "0", "home_score": "0", "status": "Scheduled"}],
    )
    assert graded_outcomes._nfl_graded_rows_for_date("2026-08-07") == []


def test_an_unrecognised_status_does_not_grade(nfl_root: Path) -> None:
    """Allowlist, not denylist. A new upstream status string should cost a missed
    settlement, never an invented one."""
    _write_schedule(
        nfl_root / "schedule_preseason_2026.csv",
        [{"gameday": "2026-08-07", "away_team": "CAR", "home_team": "ARI",
          "away_score": "17", "home_score": "20", "status": "In Progress"}],
    )
    assert graded_outcomes._nfl_graded_rows_for_date("2026-08-07") == []


def test_a_file_with_no_status_column_keeps_the_blank_score_rule(nfl_root: Path) -> None:
    """schedule_{season}.csv (regular season) carries no status column and no
    0-0 rows; its existing blank-score guard is correct and must not be
    tightened into grading nothing."""
    _write_schedule(
        nfl_root / "schedule_2026.csv",
        [
            {"gameday": "2026-09-10", "away_team": "KC", "home_team": "BUF",
             "away_score": "27", "home_score": "24"},
            {"gameday": "2026-09-17", "away_team": "SF", "home_team": "SEA",
             "away_score": "", "home_score": ""},
        ],
        with_status=False,
    )
    assert any(row["selection"] == "KC" for row in graded_outcomes._nfl_graded_rows_for_date("2026-09-10"))
    assert graded_outcomes._nfl_graded_rows_for_date("2026-09-17") == []
