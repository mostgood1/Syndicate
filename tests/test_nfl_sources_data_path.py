"""`#672`: NFL data files must resolve to where the pipeline PUT them, not to the checkout.

The production shape, measured 2026-09-17 on refresh-worker: the repo checkout
carries the git-tracked `upcoming_recs_*.csv` that `_first_existing_root` probes
for, and the mounted disk does not. So `default_nfl_source_root()` answered the
checkout, and every caller of `data_path` read git's copy of the season instead
of the pipeline's. Two symptoms, one line:

  * `schedule_2026.csv` in the checkout has 272 of 272 rows with blank scores,
    so `nfl_target_week` returned 1 all season and the prop autorun rebuilt week
    1 sixty-four times in 24 h;
  * `tracking/nflverse/pbp/` is gitignored, so the play-by-play was looked for in
    the one place it cannot exist and every build refused `zero_sim_rows`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl import sources
from syndicate.features.shared import source_roots


@pytest.fixture
def two_roots(tmp_path, monkeypatch):
    """A mounted disk holding the real files, and a checkout holding git's copies."""
    disk = tmp_path / "disk"
    nfl_disk = disk / "nfl_source"
    nfl_disk.mkdir(parents=True)
    checkout = tmp_path / "src" / "data" / "nfl_source"
    checkout.mkdir(parents=True)
    # The probe file that decides `default_nfl_source_root()` -- git-tracked, so
    # it exists in the checkout only. This is the trap, reproduced.
    (checkout / "upcoming_recs_2026.csv").write_text("x", encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(disk))
    monkeypatch.delenv("SYNDICATE_NFL_SOURCE_ROOT", raising=False)
    monkeypatch.setattr(sources, "_source_roots", lambda: [nfl_disk, checkout])
    monkeypatch.setattr(sources, "nfl_artifact_output_root", lambda: nfl_disk)
    source_roots.clear_source_root_caches()
    yield {"disk": nfl_disk, "checkout": checkout}
    source_roots.clear_source_root_caches()


PLAYED = (
    "game_id,season,game_type,week,gameday,gametime,away_team,home_team,away_score,home_score\n"
    "2026_01_NE_SEA,2026,REG,1,2026-09-09,20:20,NE,SEA,10,13\n"
    "2026_02_BUF_NYJ,2026,REG,2,2026-09-16,20:20,BUF,NYJ,24,17\n"
    "2026_03_DET_BAL,2026,REG,3,2026-09-21,20:20,DET,BAL,,\n"
)
UNPLAYED = (
    "game_id,season,game_type,week,gameday,gametime,away_team,home_team,away_score,home_score\n"
    "2026_01_NE_SEA,2026,REG,1,2026-09-09,20:20,NE,SEA,,\n"
    "2026_02_BUF_NYJ,2026,REG,2,2026-09-16,20:20,BUF,NYJ,,\n"
    "2026_03_DET_BAL,2026,REG,3,2026-09-21,20:20,DET,BAL,,\n"
)


def test_the_mounted_file_wins_over_the_checkout_copy(two_roots):
    (two_roots["disk"] / "schedule_2026.csv").write_text(PLAYED, encoding="utf-8")
    (two_roots["checkout"] / "schedule_2026.csv").write_text(UNPLAYED, encoding="utf-8")
    assert sources.data_path("schedule_2026.csv") == two_roots["disk"] / "schedule_2026.csv"
    # The trap is real: the probe-based selector still answers the checkout.
    assert sources.default_nfl_source_root() == two_roots["checkout"]


def test_the_target_week_follows_the_played_schedule_not_gits_copy(two_roots):
    (two_roots["disk"] / "schedule_2026.csv").write_text(PLAYED, encoding="utf-8")
    (two_roots["checkout"] / "schedule_2026.csv").write_text(UNPLAYED, encoding="utf-8")
    assert sources.nfl_target_week(2026) == 3          # weeks 1 and 2 are played
    # Pre-change behaviour, asserted directly so the regression is visible: the
    # checkout's copy would have answered 1 -- which is what production did, 64
    # launches in 24 h after week 1 had finished (the real current week was 2).
    monkey = two_roots["checkout"] / "schedule_2026.csv"
    assert "2026_01_NE_SEA,2026,REG,1,2026-09-09,20:20,NE,SEA,,\n" in monkey.read_text(encoding="utf-8")


def test_a_file_that_exists_nowhere_falls_back_to_the_write_root(two_roots):
    path = sources.data_path("schedule_2031.csv")
    assert path == two_roots["disk"] / "schedule_2031.csv"
    assert not path.exists()          # a path to create, on the disk that survives a deploy


def test_nested_parts_resolve_per_file_too(two_roots):
    target = two_roots["disk"] / "tracking" / "nflverse" / "pbp" / "pbp_2026.csv"
    target.parent.mkdir(parents=True)
    target.write_text("play_id\n1\n", encoding="utf-8")
    assert sources.data_path("tracking", "nflverse", "pbp", "pbp_2026.csv") == target


def test_the_player_stats_pbp_reader_uses_the_resolving_path(two_roots, monkeypatch):
    """The reader whose silence produced `zero_sim_rows` for 64 straight builds."""
    from syndicate.features.nfl import player_stats

    target = two_roots["disk"] / "tracking" / "nflverse" / "pbp" / "pbp_2025.csv"
    target.parent.mkdir(parents=True)
    target.write_text("play_id\n1\n", encoding="utf-8")
    monkeypatch.setattr(sources, "nfl_pbp_path", lambda season: sources.data_path(
        "tracking", "nflverse", "pbp", f"pbp_{season}.csv"))
    assert player_stats._pbp_path(2025) == target
    assert player_stats._pbp_path(2025).exists()
