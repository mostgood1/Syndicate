"""WNBA history builders read the data-root schedule, not the vendored one (lane nba-source-cli-native, 2026-10-13).

`build_player_logs` and `compute_home_court_advantage` (both run by the WNBA props refresh's derived-artifacts step)
joined `boxscores_history.csv` to `vendor/wnba_betting_repo/data/processed/schedule_2026.csv`, frozen at the last
vendor pull (ends 09-25, no post-season). Every later game was dropped as unjoinable: on the fleet 2026-10-13,
player_logs.csv stopped at 09-24 through the whole playoffs. Pinned here:
  * both builders resolve `schedule_<season>.csv` beside boxscores_history.csv under the league's data root, never vendor/;
  * player_logs keeps post-season games (user decision 2026-10-13);
  * home-court advantage stays a regular-season fit unless `include_postseason=True` (same decision: one phase per fit).
"""
from __future__ import annotations

import pandas as pd

from scripts import build_basketball_home_court_advantage as hca
from scripts import build_basketball_player_logs as bpl


def test_both_builders_read_the_schedule_from_the_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("WNBA_BETTING_DATA_ROOT", str(tmp_path / "data"))
    for mod in (bpl, hca):
        path = mod._schedule_path("wnba", 2026)
        assert path == tmp_path / "data" / "processed" / "schedule_2026.csv"
        assert "vendor" not in path.parts


def _write(processed, games):
    """games: (game_id, season_type_slug, home pts, away pts). Home LVA, away IND, one player each side."""
    box, sched = [], []
    for gid, slug, hp, ap in games:
        box += [{"game_id": gid, "TEAM_ABBREVIATION": "LVA", "PLAYER_NAME": "A Wilson", "MIN": 35, "PTS": hp, "date": "2026-10-09"},
                {"game_id": gid, "TEAM_ABBREVIATION": "IND", "PLAYER_NAME": "C Clark", "MIN": 30, "PTS": ap, "date": "2026-10-09"}]
        sched.append({"game_id": gid, "home_tricode": "LVA", "away_tricode": "IND", "season_type_slug": slug})
    processed.mkdir(parents=True)
    pd.DataFrame(box).to_csv(processed / "boxscores_history.csv", index=False)
    pd.DataFrame(sched).to_csv(processed / "schedule_2026.csv", index=False)


def test_player_logs_keep_post_season_games(tmp_path, monkeypatch):
    monkeypatch.setenv("WNBA_BETTING_DATA_ROOT", str(tmp_path / "data"))
    _write(tmp_path / "data" / "processed", [("r1", "regular-season", 80, 70), ("p1", "post-season", 90, 85)])
    result = bpl.build_player_logs(league_code="wnba", season=2026, min_rows=1)
    assert result["ok"] and result["rows_dropped_unjoinable"] == 0
    assert set(result["frame"]["GAME_ID"]) == {"r1", "p1"}


def test_home_court_advantage_excludes_post_season_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("WNBA_BETTING_DATA_ROOT", str(tmp_path / "data"))
    games = [(f"r{i}", "regular-season", 80 + (i % 3), 78) for i in range(6)] + [(f"p{i}", "post-season", 60, 90) for i in range(3)]
    _write(tmp_path / "data" / "processed", games)
    regular = hca.compute_home_court_advantage(league_code="wnba", season=2026, min_games=1, min_t_stat=0.0)
    both = hca.compute_home_court_advantage(league_code="wnba", season=2026, min_games=1, min_t_stat=0.0, include_postseason=True)
    assert regular["games_used"] == 6 and regular["include_postseason"] is False
    assert both["games_used"] == 9 and both["mean_margin"] < regular["mean_margin"]
