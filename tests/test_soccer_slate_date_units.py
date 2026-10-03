"""Soccer sim units are keyed on the CENTRAL slate date, not the UTC prefix.

Lane `soccer-projections-gap`, measured on the fleet 2026-10-03 ~03:55Z. The
schedule stores kickoff as a UTC timestamp; both the refresh worker's unit
resolver and `week_date_list` sliced its first ten characters. The unit date
becomes `build_soccer_artifacts`' ESPN query (`dates=YYYYMMDD`), and ESPN files a
fixture under its US-local day:

    Chicago Fire - Vancouver   2026-10-07T00:30Z
    ESPN dates=20261007 -> 0 events     dates=20261006 -> this match

so the unit for 10-07 wrote `recommendations_2026-10-07.json` with zero matches,
10-06 never got a unit, and the served board reported
`rows_with_projection: 0, "no soccer recommendations for this date"`.

The fixtures below are the real fleet schedule rows.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from syndicate.features.soccer import sources

MLS_EVENING = {"date": "2026-10-07T00:30Z", "week": 30, "home_team": "Chicago Fire FC", "away_team": "Vancouver Whitecaps"}
MLS_LATE = {"date": "2026-10-02T01:30Z", "week": 29, "home_team": "Seattle Sounders FC", "away_team": "Sporting Kansas City"}
MLS_AFTERNOON = {"date": "2026-10-10T17:00Z", "week": 31, "home_team": "Toronto FC", "away_team": "CF Montréal"}
BUNDESLIGA = {"date": "2026-10-09T18:30Z", "week": 30, "home_team": "Borussia Dortmund", "away_team": "Werder Bremen"}


@pytest.fixture()
def worker(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SOCCER_SIM_HORIZON_DAYS", "7")
    spec = importlib.util.spec_from_file_location(
        "rw_slate_date", Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rw_slate_date"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "match, expected",
    [
        (MLS_EVENING, "2026-10-06"),  # 7:30pm CT the day BEFORE the UTC prefix
        (MLS_LATE, "2026-10-01"),
        (MLS_AFTERNOON, "2026-10-10"),  # afternoon: unchanged
        (BUNDESLIGA, "2026-10-09"),  # European kickoff: unchanged
        ({"date": "2026-10-09"}, "2026-10-09"),  # date-only: unchanged
        ({"date": ""}, ""),
    ],
)
def test_fixture_slate_date(match, expected):
    assert sources.fixture_slate_date(match) == expected


def test_unit_resolver_keys_an_evening_kickoff_on_its_local_day(worker, monkeypatch):
    payload = {"matches": [MLS_EVENING, MLS_LATE, MLS_AFTERNOON]}
    monkeypatch.setattr(sources, "schedule_payload", lambda league, season: payload)
    got = worker._soccer_schedule_dates_in_horizon("mls", 2026, "2026-10-02", 7)
    # 10-06 is the day ESPN returns Chicago-Vancouver under. On origin/main this
    # was ["2026-10-02", "2026-10-07"]: two units ESPN answers with nothing.
    assert got == ["2026-10-06"]


def test_unit_resolver_horizon_edge_uses_the_local_day(worker, monkeypatch):
    # A 00:30Z kickoff on reference+8 (UTC) is reference+7 locally -- inside the
    # horizon. Keyed on the prefix it fell outside and was never simulated.
    payload = {"matches": [{"date": "2026-10-10T00:30Z", "week": 30}]}
    monkeypatch.setattr(sources, "schedule_payload", lambda league, season: payload)
    assert worker._soccer_schedule_dates_in_horizon("mls", 2026, "2026-10-02", 7) == ["2026-10-09"]


def test_european_units_are_unchanged(worker, monkeypatch):
    payload = {"matches": [BUNDESLIGA]}
    monkeypatch.setattr(sources, "schedule_payload", lambda league, season: payload)
    assert worker._soccer_schedule_dates_in_horizon("bundesliga", 2026, "2026-10-02", 7) == ["2026-10-09"]


def test_week_date_list_uses_the_same_rule(monkeypatch):
    # The builder's `--week` path, cards, props and live_lens all locate
    # `recommendations_<date>.json` through this list, so it must agree with the
    # unit resolver that wrote them.
    payload = {"matches": [MLS_EVENING, {**MLS_AFTERNOON, "week": 30}]}
    monkeypatch.setattr(sources, "schedule_payload", lambda league, season: payload)
    assert sources.week_date_list("mls", 2026, 30) == ["2026-10-06", "2026-10-10"]
