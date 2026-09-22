"""NFL week lists must not offer weeks whose only projection is the pre-season backfill.

Measured 2026-09-22: web's disk held the 2026-08-01 backfill for weeks 4-18
(`prior_season_fallback` on every team) beside the live pipeline's weeks 1-3, so
every NFL week list offered weeks 4-18 with pre-season numbers.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl import cards, sources

PRIOR = "nflverse_pbp_epa_rolling[prior_season_fallback/prior_season_fallback]"
ROLLING = "nflverse_pbp_epa_rolling[current_season_rolling/current_season_rolling]"
BLEND = "nflverse_pbp_epa_rolling[current_season_blend/current_season_blend]"


def _write(root: Path, week: int, sources_: list[str]) -> Path:
    path = root / f"smartsim2_projections_2026_wk{week}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["game_id", "week", "rating_source"])
        writer.writeheader()
        for index, source in enumerate(sources_):
            writer.writerow({"game_id": f"2026_{week:02d}_G{index}", "week": week, "rating_source": source})
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    nfl = tmp_path / "nfl_source"
    nfl.mkdir()
    _write(nfl, 1, [PRIOR] * 16)       # live week 1: prior-season only BY DESIGN
    _write(nfl, 2, [ROLLING] * 16)     # live week 2 (built before the blend)
    _write(nfl, 3, [BLEND] * 16)       # live week 3
    _write(nfl, 4, [PRIOR] * 16)       # the 2026-08-01 backfill
    _write(nfl, 18, [PRIOR] * 16)      # the 2026-08-01 backfill
    monkeypatch.setattr(sources, "default_nfl_source_root", lambda: nfl)
    monkeypatch.setattr(cards, "default_nfl_source_root", lambda: nfl)
    monkeypatch.setattr(sources, "_BACKFILL_VERDICTS", {}, raising=False)
    return nfl


def test_the_predicate(root):
    assert sources.is_preseason_backfill_projection(root / "smartsim2_projections_2026_wk4.csv")
    assert sources.is_preseason_backfill_projection(root / "smartsim2_projections_2026_wk18.csv")
    assert not sources.is_preseason_backfill_projection(root / "smartsim2_projections_2026_wk1.csv")
    assert not sources.is_preseason_backfill_projection(root / "smartsim2_projections_2026_wk2.csv")
    assert not sources.is_preseason_backfill_projection(root / "smartsim2_projections_2026_wk3.csv")


def test_one_live_row_is_enough_to_keep_a_week(root):
    _write(root, 5, [PRIOR] * 15 + [BLEND])
    assert not sources.is_preseason_backfill_projection(root / "smartsim2_projections_2026_wk5.csv")


def test_an_empty_file_is_not_called_a_backfill(root):
    _write(root, 6, [])
    assert not sources.is_preseason_backfill_projection(root / "smartsim2_projections_2026_wk6.csv")


def test_a_rebuilt_week_reappears(root):
    path = root / "smartsim2_projections_2026_wk4.csv"
    assert sources.is_preseason_backfill_projection(path)
    stat = path.stat()
    _write(root, 4, [BLEND] * 16)      # the pipeline builds week 4
    os.utime(path, (stat.st_atime, stat.st_mtime + 60))
    assert not sources.is_preseason_backfill_projection(path)


def test_cards_picks_and_lens_weeks_hide_the_backfill(root):
    assert sources.available_weeks(2026) == [1, 2, 3]


def test_market_board_weeks_hide_the_backfill(root):
    assert cards.nfl_projection_available_weeks(2026) == [1, 2, 3]
