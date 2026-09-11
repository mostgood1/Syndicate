"""NCAAF TBD kickoffs: the schedule's 00:00-Eastern placeholder is a DATE, not a time.

User-reported 2026-09-11 ("games on the wrong day"). CFBD dates a game whose
kickoff is not set yet at 00:00 US/Eastern of the game day and flags it
`startTimeTBD: true` -- 443 of 888 2026 games. Read as a real time and converted
to Central, that is 11:00 PM the PREVIOUS day, so production's Friday 09-11 chip
strip carried four Saturday games (Mercyhurst @ New Mexico, Southern Miss @
Auburn, NMSU @ Hawai'i, Cal Poly @ SJSU) at "11:00P CT", while the board's own
odds rows put them on Saturday afternoon and evening.

THE FLAG DECIDES, NEVER THE CLOCK: a genuine 11:00 PM CT Hawai'i kickoff has the
same 04:00Z timestamp as the placeholder, and it must stay on its own day.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _row(week, away, home, start, tbd, classes=("fbs", "fbs")):
    return {
        "week": week,
        "awayTeam": away,
        "homeTeam": home,
        "startDate": start,
        "startTimeTBD": tbd,
        "awayClassification": classes[0],
        "homeClassification": classes[1],
    }


_FRIDAY_REAL = _row(2, "Villanova", "Louisville", "2026-09-11T23:00:00.000Z", False)
_SAT_TBD_1 = _row(2, "Mercyhurst", "New Mexico", "2026-09-12T04:00:00.000Z", True, ("fcs", "fbs"))
_SAT_TBD_2 = _row(2, "Southern Miss", "Auburn", "2026-09-12T04:00:00.000Z", True)
# A REAL 11:00 PM CT kickoff on Saturday night: the same 04:00Z shape, no flag.
_SAT_REAL_LATE = _row(2, "New Mexico State", "Hawai'i", "2026-09-13T04:00:00.000Z", False)


def test_a_TBD_placeholder_is_the_eastern_game_day():
    from syndicate.features.ncaaf.sources import ncaaf_game_calendar_date

    assert ncaaf_game_calendar_date(_SAT_TBD_1) == date(2026, 9, 12)
    # After the November clock change the placeholder is 05:00Z.
    assert ncaaf_game_calendar_date(_row(12, "A", "B", "2026-11-21T05:00:00.000Z", True)) == date(2026, 11, 21)


def test_a_REAL_late_kickoff_keeps_its_central_day():
    """The falsification test. A fix keyed on the clock would move this to Sunday."""
    from syndicate.features.ncaaf.sources import ncaaf_game_calendar_date

    assert ncaaf_game_calendar_date(_SAT_REAL_LATE) == date(2026, 9, 12)
    # MEM @ UNLV, the case the Central comparison was written for: 9 PM CT.
    assert ncaaf_game_calendar_date(_row(1, "Memphis", "UNLV", "2026-08-30T02:00:00.000Z", False)) == date(2026, 8, 29)


def test_unreadable_input_is_None_not_a_guess():
    from syndicate.features.ncaaf.sources import ncaaf_game_calendar_date

    assert ncaaf_game_calendar_date(None) is None
    assert ncaaf_game_calendar_date({"startTimeTBD": True, "startDate": ""}) is None
    assert ncaaf_game_calendar_date({"startTimeTBD": True, "startDate": "not a date"}) is None


def _schedule(monkeypatch, rows):
    from syndicate.features.football.sim_engine.smartsim2.historical_truth import ncaaf_historical_loader
    from syndicate.features.ncaaf import cards

    monkeypatch.setattr(ncaaf_historical_loader, "load_games_season", lambda season: list(rows))
    monkeypatch.setattr(cards, "load_games_season", lambda season: list(rows), raising=False)


def test_the_date_resolver_files_TBD_games_on_their_own_day(monkeypatch):
    from syndicate.features.ncaaf.sources import ncaaf_week_and_card_keys_for_date

    _schedule(monkeypatch, [_FRIDAY_REAL, _SAT_TBD_1, _SAT_TBD_2, _SAT_REAL_LATE])
    assert ncaaf_week_and_card_keys_for_date(2026, "2026-09-11") == (2, {"2_Villanova_Louisville"})
    assert ncaaf_week_and_card_keys_for_date(2026, "2026-09-12") == (
        2,
        {"2_Mercyhurst_New_Mexico", "2_Southern_Miss_Auburn", "2_New_Mexico_State_Hawai'i"},
    )


def test_OFF_IS_NOT_ON_without_the_flag_the_placeholder_lands_on_friday(monkeypatch):
    """The control: the same rows without `startTimeTBD` reproduce the production defect."""
    from syndicate.features.ncaaf.sources import ncaaf_week_and_card_keys_for_date

    unflagged = [dict(row, startTimeTBD=False) for row in (_FRIDAY_REAL, _SAT_TBD_1, _SAT_TBD_2)]
    _schedule(monkeypatch, unflagged)
    _, keys = ncaaf_week_and_card_keys_for_date(2026, "2026-09-11")
    assert {"2_Mercyhurst_New_Mexico", "2_Southern_Miss_Auburn"} <= keys


def test_a_TBD_chip_reads_TBD_on_its_own_day_never_11PM(monkeypatch):
    from syndicate.features.ncaaf import cards
    from syndicate.features.shared.game_chip_scoreboard import build_game_chip

    _schedule(monkeypatch, [_FRIDAY_REAL, _SAT_TBD_1, _SAT_TBD_2, _SAT_REAL_LATE])
    monkeypatch.setattr(cards, "_attach_live_state", lambda *a, **k: None)
    monkeypatch.setattr(cards, "_resolve_branding", lambda *a, **k: None)
    monkeypatch.setattr(cards, "_resolve_team", lambda *a, **k: None)

    saturday = {g["gamePk"]: g for g in cards.build_ncaaf_chip_games("2026-09-12", season=2026)}
    tbd = saturday["2_Mercyhurst_New_Mexico"]
    assert tbd["startTime"] is None
    assert tbd["game_date"] == "2026-09-12"
    assert tbd["start_time_tbd"] is True
    chip = build_game_chip("ncaaf", tbd)
    assert chip["status_token"].endswith("TBD")
    assert "11:00P" not in chip["status_token"]
    assert chip["start_time_utc"].startswith("2026-09-12")

    # The real late kickoff keeps its real clock.
    real = build_game_chip("ncaaf", saturday["2_New_Mexico_State_Hawai'i"])
    assert real["start_time_utc"] == "2026-09-13T04:00:00+00:00"
    assert real["status_token"].endswith("11:00P CT")

    friday = cards.build_ncaaf_chip_games("2026-09-11", season=2026)
    assert [g["gamePk"] for g in friday] == ["2_Villanova_Louisville"]
    assert friday[0]["startTime"] == "2026-09-11T23:00:00.000Z"
