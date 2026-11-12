"""NBA prop rows get the player's side and face from the CURRENT roster (lane nba-prop-side-face-current-roster, #793).

Measured on the served board 2026-11-11 23:47-23:51Z: 126 of 477 NBA prop rows (36 players) had no `player_side`
and 67 (18 players) no headshot. `_player_team` / `headshot_url` read `player_ids.csv`, the 2025-26 table, with a
lowercase-only key: 17 players are filed under two teams (traded: Tyler Herro MIA/MIL), 11 are absent (rookies,
Damian Lillard), 6 miss on spelling (Luka Doncic), 2 are filed on their old team (Anthony Davis DAL). The fleet's
current ESPN roster (`rosters_2026-27.csv`, `nba_current_rosters`) placed all 36 in their game and carried a stats.nba
id for all 18 faceless players.

Each behaviour has an OFF arm -- no roster, the pre-fix path -- that must differ (off != on).
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import nba_current_rosters as ncr
from syndicate.features.shared import player_headshots as H

D = "2026-11-11"
FETCHED = datetime(2026, 11, 11, 22, 49, tzinfo=timezone.utc)
CDN = "https://cdn.nba.com/headshots/nba/latest/1040x760/{}.png"

# name -> (current team, stats.nba id or "")
CURRENT = {
    "Tyler Herro": ("MIL", "1629639"),
    "Brayden Burries": ("MIL", "1642400"),
    "Anthony Davis": ("WAS", "203076"),
    "Luka Doncic": ("LAL", "1629029"),
    "Saddiq Bey": ("NOP", "1630180"),
    "Kelly Oubre Jr.": ("IND", "1626162"),
}

# The 2025-26 table as the fleet holds it (`home._basketball_player_id_index` shape).
STALE = {
    ("MIA", "tyler herro"): 1629639, ("MIL", "tyler herro"): 1629639, ("", "tyler herro"): 1629639,
    ("DAL", "anthony davis"): 203076, ("", "anthony davis"): 203076,
    ("LAL", "luka dončić"): 1629029, ("", "luka dončić"): 1629029,
    ("NOP", "saddiq bey"): 1630180, ("", "saddiq bey"): 1630180,
}


def write_roster(processed: Path, current: dict[str, tuple[str, str]], *, fetched: datetime = FETCHED) -> Path:
    path = ncr.roster_path(processed, "2026-27")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [(name, tri, pid) for name, (tri, pid) in current.items()]
    rows += [(f"Filler {tri} {i}", tri, "") for tri in ncr.STATS_TEAM_ID for i in range(ncr.MIN_TEAM_PLAYERS)]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ncr.COLUMNS)
        writer.writeheader()
        for name, tri, pid in rows:
            writer.writerow({"PLAYER": name, "PLAYER_ID": pid, "TEAM_ABBREVIATION": tri, "ROSTER_SOURCE": ncr.SOURCE,
                             "FETCHED_AT": fetched.isoformat()})
    return path


@pytest.fixture
def board(tmp_path, monkeypatch):
    from syndicate.blueprints import home
    from syndicate.features.nba import sources

    processed = tmp_path / "nba_source" / "data" / "processed"
    write_roster(processed, CURRENT)
    monkeypatch.setattr(sources, "artifact_processed_root", lambda: processed)
    monkeypatch.delenv(ncr.FLAG, raising=False)
    monkeypatch.setitem(home._BASKETBALL_PLAYER_ID_CACHE, "nba", dict(STALE))
    H._basketball_teams.cache_clear()
    H._nba_roster_for.cache_clear()
    yield processed
    H._basketball_teams.cache_clear()
    H._nba_roster_for.cache_clear()


def prop(player: str, *, home: str = "Milwaukee Bucks", away: str = "Los Angeles Lakers", **extra) -> dict:
    return {"sport": "nba", "kind": "prop", "market": "player_points", "player_name": player, "line": 19.5,
            "home_team": home, "away_team": away, "date": D, **extra}


def no_roster(monkeypatch) -> None:
    """The pre-fix path: no current roster, so only `player_ids.csv`."""
    monkeypatch.setattr(H, "_nba_current_roster", lambda row: None)


# ------------------------------------------------------------------------------------------------- the four causes

def test_a_traded_player_on_two_teams_in_the_old_table_gets_his_current_side(board, monkeypatch):
    row = prop("Tyler Herro")
    assert H.player_side(row) == "home"
    no_roster(monkeypatch)
    assert H.player_side(row) is None  # off: MIA and MIL in the table, so the table names no team


def test_a_player_filed_on_his_old_team_gets_his_current_side(board, monkeypatch):
    row = prop("Anthony Davis", home="Indiana Pacers", away="Washington Wizards")
    assert H.player_side(row) == "away"
    no_roster(monkeypatch)
    assert H.player_side(row) is None  # off: DAL, which is in neither side of the game


def test_a_rookie_gets_a_face_and_a_side(board, monkeypatch):
    row = prop("Brayden Burries")
    assert H.headshot_url(row) == CDN.format("1642400")
    assert H.player_side(row) == "home"
    no_roster(monkeypatch)
    assert H.headshot_url(row) is None and H.player_side(row) is None  # off: not in the 2025-26 table


def test_a_spelling_the_old_key_misses_gets_a_face_and_a_side(board, monkeypatch):
    """The table's key is lowercase only, so "Luka Doncic" misses "luka dončić"; the roster's key folds accents."""
    row = prop("Luka Doncic")
    assert H.headshot_url(row) == CDN.format("1629029")
    assert H.player_side(row) == "away"
    no_roster(monkeypatch)
    assert H.headshot_url(row) is None and H.player_side(row) is None


def test_a_suffix_the_book_prints_still_matches(board):
    """"Kelly Oubre Jr." on the roster, "Kelly Oubre" in a book: the roster key drops the suffix."""
    assert H.player_side(prop("Kelly Oubre", home="Indiana Pacers", away="Philadelphia 76ers")) == "home"


# ------------------------------------------------------------------------------------------- what must not change

def test_a_face_the_table_already_gives_is_unchanged(board, monkeypatch):
    """The table's id comes first: a roster id that differs never replaces a face that already resolved."""
    write_roster(board, {**CURRENT, "Saddiq Bey": ("NOP", "999")})
    os.utime(ncr.roster_path(board, "2026-27"), ns=(1_800_000_000_000_000_000, 1_800_000_000_000_000_000))
    row = prop("Saddiq Bey", home="New Orleans Pelicans", away="Golden State Warriors")
    assert H.headshot_url(row) == CDN.format("1630180")
    assert H.player_side(row) == "home"


def test_wnba_rows_never_read_the_nba_roster(board, monkeypatch):
    def boom(row):
        raise AssertionError("the NBA roster was read for a WNBA row")

    monkeypatch.setattr(H, "_nba_current_roster", boom)
    row = {**prop("Tyler Herro"), "sport": "wnba"}
    assert H.player_side(row) is None
    assert H.headshot_url(row) is None


def test_the_switch_off_is_the_pre_fix_path(board, monkeypatch):
    monkeypatch.setenv(ncr.FLAG, "0")
    assert H.player_side(prop("Tyler Herro")) is None
    assert H.headshot_url(prop("Brayden Burries")) is None


def test_a_roster_fetched_after_the_slate_is_not_used(board):
    """An as-of replay of a past date must not see later moves: the producer's own one-day rule."""
    write_roster(board, CURRENT, fetched=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))
    assert H.player_side(prop("Tyler Herro")) is None


def test_no_roster_file_is_the_pre_fix_path(board):
    ncr.roster_path(board, "2026-27").unlink()
    assert H.player_side(prop("Tyler Herro")) is None
    assert H.headshot_url(prop("Saddiq Bey")) == CDN.format("1630180")  # the table still works


def test_the_roster_is_reread_when_the_file_changes(board):
    assert H.player_side(prop("Tyler Herro")) == "home"
    write_roster(board, {**CURRENT, "Tyler Herro": ("LAL", "1629639")})
    os.utime(ncr.roster_path(board, "2026-27"), ns=(1_900_000_000_000_000_000, 1_900_000_000_000_000_000))
    assert H.player_side(prop("Tyler Herro")) == "away"


# ------------------------------------------------------------------------------------------------ index and date

def test_a_name_on_two_ids_has_no_roster_face(tmp_path):
    write_roster(tmp_path, {"Jalen Williams": ("OKC", "1631114"), "Jalen  Williams": ("OKC", "1631116")})
    idx = ncr.current_roster_index(tmp_path, D, env={})
    assert idx is not None
    assert "jalen williams" not in idx.stats_id_by_key  # two players, one key: never guess a face
    assert idx.team_by_key["jalen williams"] == "OKC"  # same team, so the side is still known


def test_the_slate_date_comes_from_the_row():
    assert H._row_slate_date({"date": "2026-11-10"}) == "2026-11-10"
    # A 7 PM Central tip is 01:00Z the next day: the slate is the Central date.
    assert H._row_slate_date({"commence_time": "2026-11-12T01:00:00Z"}) == "2026-11-11"


# ---------------------------------------------------------------------------------------------------- reachability

def test_the_board_row_identity_carries_the_roster_side_and_face(board, monkeypatch):
    """Reachability: the board build's entry point (`layer2_row_context.row_identity`) gains both fields."""
    from syndicate.features.shared.layer2_row_context import row_identity

    row = prop("Brayden Burries")
    assert row_identity(row, None) == {"headshot_url": CDN.format("1642400"), "player_side": "home"}
    no_roster(monkeypatch)
    assert row_identity(row, None) == {}
