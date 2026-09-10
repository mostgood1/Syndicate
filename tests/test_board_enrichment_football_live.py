"""Football on the Layer 2 board: game state for every NCAAF team (2026-09-10).

Measured on production's `/api/board/layer2-shortlist?sport=ncaaf`: all 27 rows
of Florida A&M @ Miami carried no `game_state`, because `teams_match` could not
place "Florida A&M" (its NCAAF vocabulary misses the school) while the NCAAF
registry resolves both spellings to id 50.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import board_enrichment, game_chip_scoreboard, ncaaf_team_registry

_IDS = {
    "Florida A&M Rattlers": "50",
    "Florida A&M": "50",
    "Miami Hurricanes": "2390",
    "Miami": "2390",
    "MIA": "2390",
}


def _chip(home, away, *, home_abbr="", away_abbr="", state="pregame"):
    return {
        "home": {"name": home, "abbr": home_abbr, "score": None},
        "away": {"name": away, "abbr": away_abbr, "score": None},
        "state": state,
        "start_time_utc": "2026-09-11T00:00:00+00:00",
        "status_token": "7:00 PM",
        "matchup": f"{away} @ {home}",
    }


@pytest.fixture
def chips(monkeypatch):
    def install(chip_list, ids=_IDS):
        monkeypatch.setattr(game_chip_scoreboard, "build_game_chips", lambda _date, _sports: list(chip_list))
        monkeypatch.setattr(ncaaf_team_registry, "resolve_ncaaf_team_id", lambda name: ids.get(str(name)))
    return install


def _row(home, away, sport="ncaaf"):
    return {"sport": sport, "home_team": home, "away_team": away, "commence_time": "2026-09-11T00:00:00Z"}


def test_an_NCAAF_team_the_alias_vocabulary_misses_still_gets_game_state(chips):
    chips([_chip("Miami", "Florida A&M", home_abbr="MIA", away_abbr="FAM")])
    grid = [_row("Miami Hurricanes", "Florida A&M Rattlers")]

    coverage = board_enrichment.attach_game_state(grid, sport="ncaaf", selected_date="2026-09-10")

    assert coverage["rows_matched"] == 1
    assert grid[0]["game"]["state"] == "pregame"
    assert grid[0]["game"]["matchup"] == "Florida A&M @ Miami"


def test_WITHOUT_a_registry_id_the_row_stays_unmatched(chips):
    # The falsifier: the pre-fix behaviour, and what an unknown school still gets.
    chips([_chip("Miami", "Florida A&M", home_abbr="MIA", away_abbr="FAM")], ids={})
    grid = [_row("Miami Hurricanes", "Florida A&M Rattlers")]

    coverage = board_enrichment.attach_game_state(grid, sport="ncaaf", selected_date="2026-09-10")

    assert coverage["rows_matched"] == 0
    assert "game" not in grid[0]
    assert "Florida A&M Rattlers" in coverage.get("unmatched_teams", [])


def test_the_registry_never_joins_a_row_to_the_WRONG_game(chips):
    # Two chips; the registry must pick the one whose ids match on BOTH sides.
    ids = dict(_IDS, **{"Georgia": "61", "Georgia Bulldogs": "61"})
    chips([_chip("Georgia", "Florida A&M"), _chip("Miami", "Florida A&M", home_abbr="MIA")], ids=ids)
    grid = [_row("Miami Hurricanes", "Florida A&M Rattlers")]

    board_enrichment.attach_game_state(grid, sport="ncaaf", selected_date="2026-09-10")

    assert grid[0]["game"]["matchup"] == "Florida A&M @ Miami"


def test_other_sports_never_consult_the_NCAAF_registry(chips, monkeypatch):
    # An NFL row whose names fail `teams_match` must stay unmatched even if the
    # registry would have an opinion: the fallback is NCAAF-only.
    called = []
    chips([_chip("Nowhere Nobodies", "Florida A&M")])
    monkeypatch.setattr(ncaaf_team_registry, "resolve_ncaaf_team_id", lambda name: called.append(name) or "50")
    grid = [_row("Miami Hurricanes", "Florida A&M Rattlers", sport="nfl")]

    coverage = board_enrichment.attach_game_state(grid, sport="nfl", selected_date="2026-09-10")

    assert coverage["rows_matched"] == 0
    assert called == []
