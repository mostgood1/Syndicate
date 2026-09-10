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



# ---------------------------------------------------------------------------
# FOOTBALL CHIPS ARE FETCHED FOR THE KICKOFF'S ESPN DATE (2026-09-10)
# ---------------------------------------------------------------------------
# FAMU @ MIA: commence 2026-09-11T00:00Z, filed by ESPN under 2026-09-10. The
# 09-11 book grid used to ask only for 09-11 chips, so it never saw the game.


@pytest.fixture
def chips_by_date(monkeypatch):
    def install(by_date, ids=_IDS):
        calls = []

        def build(date, sports):
            calls.append(date)
            return list(by_date.get(date, []))

        monkeypatch.setattr(game_chip_scoreboard, "build_game_chips", build)
        monkeypatch.setattr(ncaaf_team_registry, "resolve_ncaaf_team_id", lambda name: ids.get(str(name)))
        return calls
    return install


def test_a_NIGHT_kickoff_on_the_NEXT_UTC_day_still_finds_its_ESPN_chip(chips_by_date):
    calls = chips_by_date({"2026-09-10": [_chip("Miami", "Florida A&M", home_abbr="MIA", away_abbr="FAM")]})
    grid = [_row("Miami Hurricanes", "Florida A&M Rattlers")]  # commence 2026-09-11T00:00:00Z

    coverage = board_enrichment.attach_game_state(grid, sport="ncaaf", selected_date="2026-09-11")

    assert coverage["rows_matched"] == 1
    assert grid[0]["game"]["matchup"] == "Florida A&M @ Miami"
    assert "2026-09-10" in calls


def test_WITHOUT_the_ESPN_date_the_09_11_grid_cannot_see_the_game(chips_by_date, monkeypatch):
    # The falsifier: with the helper unavailable, only UTC dates are asked for,
    # which is exactly the pre-fix behaviour -- and both teams go unmatched.
    import syndicate.features.shared.bet_status_nfl as bsn

    monkeypatch.setattr(bsn, "kickoff_capture_dates", lambda _raw: [])
    # 09-11 HAS chips, as production's does (85 of them), just not this game's.
    chips_by_date({
        "2026-09-10": [_chip("Miami", "Florida A&M", home_abbr="MIA", away_abbr="FAM")],
        "2026-09-11": [_chip("Boston College", "Rutgers")],
    })
    grid = [_row("Miami Hurricanes", "Florida A&M Rattlers")]

    coverage = board_enrichment.attach_game_state(grid, sport="ncaaf", selected_date="2026-09-11")

    assert coverage["rows_matched"] == 0
    assert set(coverage.get("unmatched_teams", [])) == {"Miami Hurricanes", "Florida A&M Rattlers"}


def test_a_SMALL_HOURS_kickoff_also_asks_for_the_previous_day(chips_by_date):
    # NMSU @ Hawai'i: OddsAPI 2026-09-13T04:00Z, ESPN files it under 09-12.
    ids = dict(_IDS, **{"Hawaii Rainbow Warriors": "62", "Hawai'i": "62", "New Mexico State Aggies": "166", "New Mexico State": "166"})
    calls = chips_by_date({"2026-09-12": [_chip("Hawai'i", "New Mexico State")]}, ids=ids)
    row = _row("Hawaii Rainbow Warriors", "New Mexico State Aggies")
    row["commence_time"] = "2026-09-13T04:00:00Z"

    coverage = board_enrichment.attach_game_state([row], sport="ncaaf", selected_date="2026-09-13")

    assert coverage["rows_matched"] == 1
    assert "2026-09-12" in calls


def test_MLB_asks_only_for_its_UTC_dates_as_before(chips_by_date):
    # Other sports are unchanged: no ESPN-date expansion, so a series cannot be
    # joined to the previous day's game through an extra date.
    calls = chips_by_date({})
    row = _row("Los Angeles Dodgers", "San Francisco Giants", sport="mlb")
    row["commence_time"] = "2026-09-11T02:10:00Z"

    board_enrichment.attach_game_state([row], sport="mlb", selected_date="2026-09-10")

    assert sorted(calls) == ["2026-09-10", "2026-09-11"]
