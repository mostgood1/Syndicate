"""Tests for the hockeysim data-coverage audit (data-gap detection).

Verifies the audit turns silent loader fallbacks into explicit, structured gap reports: missing
team xG flags a degraded projection, empty/absent scoreboards are reported honestly, and a fully
populated slate reports zero gaps.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.features import coverage


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def full_root(tmp_path: Path) -> Path:
    """A slate with every input present (BOS vs CHI, 2026-03-15)."""
    date = "2026-03-15"
    proc = tmp_path / "data" / "processed"
    games = tmp_path / "data" / "odds" / "games" / f"date={date}"
    _write(proc / "team_xg_2025-2026.csv", "abbr,xgf60,xga60\nBOS,3.6,2.5\nCHI,2.4,3.6\n")
    _write(
        proc / f"lineups_{date}.csv",
        "player_id,full_name,position,line_slot,pp_unit,pk_unit,proj_toi,confidence,team\n"
        "101,Bruin One,C,L1,1,,19,0.9,Boston Bruins\n"
        "102,Bruin Goalie,G,,,,60,0.9,Boston Bruins\n"
        "201,Hawk One,LW,L1,1,,18,0.8,Chicago Blackhawks\n"
        "202,Hawk Goalie,G,,,,60,0.8,Chicago Blackhawks\n",
    )
    _write(
        proc / f"starting_goalies_{date}.csv",
        "team,goalie,status,confidence,source\n"
        "Boston Bruins,Bruin Goalie,confirmed,0.9,test\n"
        "Chicago Blackhawks,Hawk Goalie,confirmed,0.8,test\n",
    )
    _write(
        games / "scoreboard.csv",
        "gamePk,gameDate,home,away,home_goals,away_goals,gameState\n"
        f"9001,{date}T23:00:00Z,Boston Bruins,Chicago Blackhawks,,,FUT\n",
    )
    return tmp_path


def test_full_slate_reports_no_gaps(full_root):
    cov = coverage.build_slate_coverage("2026-03-15", root=full_root)
    assert cov.scoreboard_present is True
    assert cov.team_xg_available is True
    assert cov.game_count == 1
    g = cov.games[0]
    assert g.projection_degraded is False
    # team_xg + lineups + goalies present -> none of those listed missing.
    assert "team_xg" not in g.missing
    assert "lineups" not in g.missing
    assert "starting_goalie" not in g.missing
    # market_lines are not wired into the slate loader yet (Phase 5) -> still a known gap.
    assert g.has_market_lines is False
    assert g.missing == ("market_lines",)


def test_missing_team_xg_flags_degraded(full_root):
    # Remove the xG file -> projection must be flagged degraded and team_xg listed missing.
    (full_root / "data" / "processed" / "team_xg_2025-2026.csv").unlink()
    cov = coverage.build_slate_coverage("2026-03-15", root=full_root)
    assert cov.team_xg_available is False
    g = cov.games[0]
    assert g.projection_degraded is True
    assert "team_xg" in g.missing
    assert cov.degraded_games == 1


def test_empty_scoreboard_reported_absent(tmp_path):
    # A 2-byte (newline-only) scoreboard is effectively empty -> reported absent, no games.
    games = tmp_path / "data" / "odds" / "games" / "date=2026-03-15"
    _write(games / "scoreboard.csv", "\n")
    cov = coverage.build_slate_coverage("2026-03-15", root=tmp_path)
    assert cov.scoreboard_present is False
    assert cov.game_count == 0
    assert cov.degraded_games == 0


def test_missing_lineups_and_goalies_listed(full_root):
    (full_root / "data" / "processed" / "lineups_2026-03-15.csv").unlink()
    (full_root / "data" / "processed" / "starting_goalies_2026-03-15.csv").unlink()
    cov = coverage.build_slate_coverage("2026-03-15", root=full_root)
    g = cov.games[0]
    assert "lineups" in g.missing
    assert "starting_goalie" in g.missing
    # xG still present -> not degraded even though rosters are gone.
    assert g.projection_degraded is False


def test_summary_shape(full_root):
    summary = coverage.build_slate_coverage("2026-03-15", root=full_root).summary()
    assert set(summary) >= {
        "date", "scoreboard_present", "team_xg_available",
        "games", "degraded_games", "fully_covered_games", "missing_by_game",
    }
    assert summary["date"] == "2026-03-15"


def test_market_lines_flag_included_when_present(full_root):
    # Directly exercise the per-game builder with market lines present.
    g = coverage.build_game_coverage(
        "9001", "2026-03-15", "Boston Bruins", "Chicago Blackhawks",
        root=full_root, has_market_lines=True,
    )
    assert g.has_market_lines is True
    assert "market_lines" not in g.missing
