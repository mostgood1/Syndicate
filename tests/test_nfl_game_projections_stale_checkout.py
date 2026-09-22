"""The board must not take an NFL projection from the git checkout's pre-season
backfill once the live pipeline is producing regular-season files.

Measured 2026-09-21 23:48Z: NYG @ LA, absent from a partial live week-2 file,
was served on the Layer 2 board at `generated_at 2026-08-01T14:33:19-05:00` --
the checkout's backfill, reached because the loader keeps the newest row PER
GAME and the live file had no row for that game. On 2026-09-22 the index held
321 games against 16 live ones.
"""

from __future__ import annotations

import csv
from pathlib import Path

import syndicate.features.shared.nfl_game_projections as mod

FIELDS = ["game_id", "season", "week", "home_team", "away_team", "home_score_mean", "away_score_mean",
          "margin_mean", "total_mean", "margin_stdev", "total_stdev", "home_win_rate", "seeds_used",
          "profile_name", "rating_source", "generated_at"]
GOOD = "nflverse_pbp_epa_rolling[current_season_blend/current_season_blend]"


def _write(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _projection(game_id, home, away, margin, generated_at):
    return {"game_id": game_id, "season": "2026", "week": game_id[5:7].lstrip("0"), "home_team": home,
            "away_team": away, "margin_mean": margin, "total_mean": "44.0", "margin_stdev": "13.0",
            "total_stdev": "12.0", "home_win_rate": "0.6", "profile_name": "nfl_v1", "rating_source": GOOD,
            "generated_at": generated_at}


def _setup(tmp_path, monkeypatch, *, with_live: bool):
    live, checkout = tmp_path / "disk" / "nfl_source", tmp_path / "repo" / "data" / "nfl_source"
    _write(checkout / "schedule_2026.csv", [
        {"game_id": "2026_03_NYJ_DET", "gameday": "2026-09-27", "home_team": "DET", "away_team": "NYJ"},
        {"game_id": "2026_03_TEN_NYG", "gameday": "2026-09-27", "home_team": "NYG", "away_team": "TEN"},
        {"game_id": "2026_04_KC_BUF", "gameday": "2026-10-04", "home_team": "BUF", "away_team": "KC"},
    ], ["game_id", "gameday", "home_team", "away_team"])
    old = "2026-08-01T14:33:19-05:00"
    _write(checkout / "smartsim2_projections_2026_wk3.csv", [
        _projection("2026_03_NYJ_DET", "DET", "NYJ", "9.9", old),
        _projection("2026_03_TEN_NYG", "NYG", "TEN", "-7.7", old),   # absent from the live file
    ], FIELDS)
    _write(checkout / "smartsim2_projections_2026_wk4.csv", [
        _projection("2026_04_KC_BUF", "BUF", "KC", "12.3", old),     # week not built live yet
    ], FIELDS)
    roots = [checkout]
    if with_live:
        _write(live / "smartsim2_projections_2026_wk3.csv", [
            _projection("2026_03_NYJ_DET", "DET", "NYJ", "3.1", "2026-09-22T04:42:42+00:00"),
        ], FIELDS)
        roots = [live, checkout]
    monkeypatch.setattr(mod, "_source_roots", lambda: roots)
    monkeypatch.setattr(mod, "_checkout_root", lambda: checkout.resolve(), raising=False)
    return mod.load_nfl_game_projections("2026-09-27")


def test_checkout_backfill_cannot_fill_a_gap_once_the_live_pipeline_runs(tmp_path, monkeypatch):
    index = _setup(tmp_path, monkeypatch, with_live=True)
    assert index.lookup("2026-09-27", "DET", "NYJ")["margin_mean"] == 3.1
    # The two production failure shapes: a game the live week lacks, and a week
    # the live pipeline has not built. Both must be EMPTY, not a stale number.
    assert index.lookup("2026-09-27", "NYG", "TEN") is None
    assert index.lookup("2026-10-04", "BUF", "KC") is None
    assert index.games == 1
    assert index.rows_skipped_stale_checkout == 3


def test_checkout_is_still_read_when_there_is_no_live_file(tmp_path, monkeypatch):
    # Cold start / local development: the checkout is all there is.
    index = _setup(tmp_path, monkeypatch, with_live=False)
    assert index.lookup("2026-09-27", "NYG", "TEN")["margin_mean"] == -7.7
    assert index.lookup("2026-10-04", "BUF", "KC")["margin_mean"] == 12.3
    assert index.rows_skipped_stale_checkout == 0


def test_preseason_series_is_not_touched(tmp_path, monkeypatch):
    checkout = tmp_path / "repo" / "data" / "nfl_source"
    _write(checkout / "schedule_preseason_2026.csv", [
        {"game_id": "2026_P2_CHI_KC", "gameday": "2026-08-15", "home_team": "KC", "away_team": "CHI"},
    ], ["game_id", "gameday", "home_team", "away_team"])
    _write(checkout / "smartsim2_preseason_projections_2026_wk2.csv", [
        _projection("2026_P2_CHI_KC", "KC", "CHI", "2.5", "2026-08-14T10:00:00-05:00"),
    ], FIELDS)
    _setup(tmp_path, monkeypatch, with_live=True)   # a live regular-season file exists
    index = mod.load_nfl_game_projections("2026-08-15")
    assert index.lookup("2026-08-15", "KC", "CHI")["margin_mean"] == 2.5


def test_the_skip_count_reaches_the_served_coverage(tmp_path, monkeypatch):
    index = _setup(tmp_path, monkeypatch, with_live=True)
    coverage = mod.attach_nfl_game_projections([], index)
    assert coverage["rows_skipped_stale_checkout"] == 3
