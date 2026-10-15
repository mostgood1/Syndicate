"""NHL roster snapshots are PER SLATE: the headshot / team index must union them, newest first (2026-10-14: the newest
file held no Colorado row, so every Avalanche player had no face and no side on the board or the cheat sheets)."""
from __future__ import annotations

import pytest

from syndicate.features.shared import player_headshots as ph

HEADER = "full_name,player_id,team,position,team_id\n"


@pytest.fixture()
def roster(tmp_path, monkeypatch):
    folder = tmp_path / "data" / "processed"
    folder.mkdir(parents=True)

    def write(day: str, rows: str) -> None:
        (folder / f"roster_snapshot_{day}.csv").write_text(HEADER + rows, encoding="utf-8")

    monkeypatch.setattr(ph, "_roots", lambda sport: [tmp_path])
    for fn in (ph._nhl_rows, ph._nhl_teams, ph._nhl_ids):
        fn.cache_clear()
    yield write
    for fn in (ph._nhl_rows, ph._nhl_teams, ph._nhl_ids):
        fn.cache_clear()


def test_a_team_off_the_newest_slate_still_resolves(roster):
    roster("2026-10-14", "Cale Makar,8480069,COL,D,\nRoope Hintz,8478449,DAL,F,\n")
    roster("2026-10-17", "Auston Matthews,8479318,TOR,F,\n")                        # newest slate: no Colorado
    assert ph._nhl_ids()["calemakar"] == "8480069" and ph._nhl_teams()["calemakar"] == "COL"
    assert ph._nhl_ids()["austonmatthews"] == "8479318"
    row = {"sport": "nhl", "player_name": "Cale Makar"}
    assert ph.headshot_url(row) == "https://assets.nhle.com/mugs/nhl/latest/8480069.png"


def test_the_newest_file_a_player_is_in_wins_so_a_trade_shows_the_new_team(roster):
    roster("2026-06-29", "Mikko Rantanen,8478420,COL,F,\n")
    roster("2026-10-13", "Mikko Rantanen,8478420,DAL,F,\n")
    assert ph._nhl_teams()["mikkorantanen"] == "DAL"


def test_one_name_on_two_players_in_one_file_is_dropped_not_guessed(roster):
    roster("2026-10-14", "Sebastian Aho,8478427,CAR,F,\nSebastian Aho,8480222,NYI,D,\n")
    roster("2026-06-29", "Sebastian Aho,8478427,CAR,F,\n")                           # an older file cannot rescue it
    assert "sebastianaho" not in ph._nhl_ids() and "sebastianaho" not in ph._nhl_teams()


def test_accented_names_match_the_plain_spelling_a_book_prints():
    # "Slafkovský" used to normalise to "slafkovsk" -- no face for 2 of 42 NHL and 3 of 100 soccer players (2026-10-15).
    from syndicate.features.shared import player_headshots as ph

    assert ph._norm("Juraj Slafkovský") == ph._norm("Juraj Slafkovsky") == "jurajslafkovsky"
    assert ph._norm("Martin Fehérváry") == ph._norm("Martin Fehervary")
    assert ph._norm("Agustín Bouzat") == "agustinbouzat"
