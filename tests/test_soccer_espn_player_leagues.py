"""The four ESPN-only leagues get a CURRENT-season player source.

`--kind players` could only serve eredivisie, primeira_liga, championship and
belgian_pro_league if the caller handed it `--espn-date-windows`; without them
it raised `SystemExit`. So the weekly producer step had to exclude those four
outright -- including them would have made every refresh tick a FAILING step --
and they ran the sim against a hand-committed `players_2025.csv`, i.e. the
COMPLETED 2025-26 season.

The windows COULD NOT BE HARD-CODED. The step runs weekly and forever; a literal
window list stops covering the season the moment it rolls, and the failure is
not an error, it is a correct-looking roster built from last year's matches.
`season_date_windows` derives them from the same season calendar `default_season`
is the inverse of.

MEASURED BEFORE ANY OF THIS WAS WIRED (2026-09-04, real ESPN fetches, not
fixtures) -- the command was executed for all four leagues, and these are the
numbers those runs produced:

    eredivisie          224 rows  max 450.0 min  17 teams   9.0s
    primeira_liga       230 rows  max 360.0 min  17 teams   9.3s
    championship        348 rows  max 360.0 min  24 teams  13.0s
    belgian_pro_league  256 rows  max 450.0 min  18 teams  10.7s

COMPARABILITY, checked before wiring rather than after. `build_usage_profiles`
normalises a squad's rates into shares that sum to ~1.0, so a per-90 and an
appearance rate inside one squad would mis-allocate volume with no symptom. All
three sources emit true per-90 over real minutes (ESPN via
`compute_minutes_played`), and the source is a pure function of the LEAGUE, so
no squad can mix them. `test_no_league_is_served_by_two_sources` pins that as an
invariant instead of leaving it as an observation -- it is the assumption every
other test here rests on.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_player_stats import season_date_windows
from syndicate.features.soccer.ingestion.player_history import UNDERSTAT_LEAGUES

_REPO = Path(__file__).resolve().parents[1]

#: The four this work exists for.
ESPN_ONLY_LEAGUES = ("eredivisie", "primeira_liga", "championship", "belgian_pro_league")


@pytest.fixture(scope="module")
def fetcher():
    spec = importlib.util.spec_from_file_location(
        "_fetch_soccer_history_local", _REPO / "scripts" / "fetch_soccer_history_local.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules["_fetch_soccer_history_local"] = module
    spec.loader.exec_module(module)
    return module


def _spans(windows: list[str]) -> list[tuple[date, date]]:
    out = []
    for window in windows:
        start_text, end_text = window.split("-")
        out.append(
            (
                date(int(start_text[:4]), int(start_text[4:6]), int(start_text[6:])),
                date(int(end_text[:4]), int(end_text[4:6]), int(end_text[6:])),
            )
        )
    return out


# ---------------------------------------------------------------------------
# The windows are DERIVED
# ---------------------------------------------------------------------------


def test_windows_start_at_the_season_and_stop_at_TODAY():
    """Requesting months that have not happened yet costs a call each and
    returns nothing -- `fetch_completed_events` keeps only `post` events."""
    windows = season_date_windows("eredivisie", 2026, today=date(2026, 9, 4))
    spans = _spans(windows)
    assert spans[0][0] == date(2026, 8, 1), "a European season starts 1 August"
    assert spans[-1][1] == date(2026, 9, 4), "and must not run past today"


def test_the_windows_are_CONTIGUOUS_and_cover_every_played_day():
    """A gap here is the worst failure this module can have: the rows still
    look like a season, they are just missing matches, and nothing downstream
    can tell."""
    spans = _spans(season_date_windows("championship", 2026, today=date(2026, 12, 31)))
    assert spans[0][0] == date(2026, 8, 1)
    for earlier, later in zip(spans, spans[1:]):
        assert (later[0] - earlier[1]).days == 1, f"gap or overlap at {earlier} -> {later}"


def test_no_window_is_wide_enough_to_hit_ESPN_TRUNCATION():
    """ESPN's scoreboard silently truncates around ~100 events per call. The
    widest league here is the Championship: 24 clubs, 12 matches a round."""
    spans = _spans(season_date_windows("championship", 2026, today=date(2027, 5, 31)))
    assert spans, "a completed season must produce windows"
    for start, end in spans:
        assert (end - start).days + 1 <= 15


def test_a_season_that_has_not_STARTED_yields_no_windows():
    """A real answer, not a failure to compute one. The caller decides whether
    that means 'skip this week'."""
    assert season_date_windows("eredivisie", 2026, today=date(2026, 7, 15)) == []


def test_a_COMPLETED_season_stops_at_the_season_end_not_at_today():
    spans = _spans(season_date_windows("eredivisie", 2025, today=date(2026, 9, 4)))
    assert spans[0][0] == date(2025, 8, 1)
    assert spans[-1][1] == date(2026, 5, 31), "must not fetch past the season's end"


def test_MLS_uses_its_OWN_calendar_year_season():
    """MLS runs Feb-Dec, not Aug-May. A single hard-coded August start would be
    wrong for it by six months."""
    spans = _spans(season_date_windows("mls", 2026, today=date(2026, 9, 4)))
    assert spans[0][0] == date(2026, 2, 1)
    assert spans[-1][1] == date(2026, 9, 4)


def test_the_windows_ROLL_WITH_THE_SEASON_which_is_why_they_cannot_be_literals():
    """The producer runs weekly and forever. This is the property a hard-coded
    list would silently lose."""
    this_year = season_date_windows("eredivisie", 2026, today=date(2026, 9, 4))
    next_year = season_date_windows("eredivisie", 2027, today=date(2027, 9, 4))
    assert this_year and next_year
    assert this_year != next_year
    assert _spans(next_year)[0][0] == date(2027, 8, 1)


# ---------------------------------------------------------------------------
# The fetcher branch the four leagues could not reach
# ---------------------------------------------------------------------------


def test_an_ESPN_league_no_longer_needs_the_caller_to_supply_windows(fetcher, tmp_path):
    """THE DEFECT THIS CLOSES. Without `--espn-date-windows` this raised
    SystemExit, which is exactly why the producer's allowlist excluded these
    four leagues."""
    captured = {}

    def _fake(league, *, date_windows):
        captured["league"] = league
        captured["windows"] = list(date_windows)
        return [{"player_id": "p1", "player_name": "A", "minutes_played": 900.0}]

    with patch.object(fetcher, "aggregate_season_player_stats", side_effect=_fake):
        fetcher.fetch_players("eredivisie", [2026], tmp_path)

    assert captured["league"] == "eredivisie"
    assert captured["windows"], "windows must have been DERIVED, not left empty"
    assert (tmp_path / "players_2026.csv").exists()


@pytest.mark.parametrize("league", ESPN_ONLY_LEAGUES)
def test_every_one_of_THE_FOUR_reaches_the_ESPN_branch(fetcher, tmp_path, league):
    with patch.object(
        fetcher,
        "aggregate_season_player_stats",
        return_value=[{"player_id": "p1", "player_name": "A", "minutes_played": 900.0}],
    ) as aggregate:
        fetcher.fetch_players(league, [2026], tmp_path / league)
    assert aggregate.call_count == 1


def test_an_EXPLICIT_window_list_still_overrides_the_derived_one(fetcher, tmp_path):
    """Backfilling a season other than the current one is the reason the flag
    survives."""
    with patch.object(
        fetcher,
        "aggregate_season_player_stats",
        return_value=[{"player_id": "p1", "player_name": "A", "minutes_played": 900.0}],
    ) as aggregate:
        fetcher.fetch_players(
            "eredivisie", [2025], tmp_path, espn_date_windows=["20250801-20250815"]
        )
    assert aggregate.call_args.kwargs["date_windows"] == ["20250801-20250815"]


def test_a_season_with_nothing_played_REFUSES_rather_than_writing_an_empty_roster(
    fetcher, tmp_path
):
    """Never overwrite a good roster with a season that has not begun."""
    with patch.object(fetcher, "aggregate_season_player_stats") as aggregate:
        with pytest.raises(SystemExit):
            fetcher.fetch_players("eredivisie", [2099], tmp_path)
    aggregate.assert_not_called()
    assert not list(tmp_path.glob("*.csv"))


def test_a_league_NO_source_covers_still_refuses(fetcher, tmp_path):
    with pytest.raises(SystemExit):
        fetcher.fetch_players("not_a_league", [2026], tmp_path)


def test_the_EMPTY_FRAME_REFUSAL_is_not_weakened_by_the_new_branch(fetcher, tmp_path):
    """`_write_csv` refuses to publish 0 rows because an empty frame serialises
    to a bare newline that every reader hits as pandas EmptyDataError. The
    derived-window branch must not become a way around it."""
    existing = tmp_path / "players_2026.csv"
    existing.write_text("league,player_id\neredivisie,p1\n", encoding="utf-8")
    with patch.object(fetcher, "aggregate_season_player_stats", return_value=[]):
        with pytest.raises(SystemExit):
            fetcher.fetch_players("eredivisie", [2026], tmp_path)
    assert "p1" in existing.read_text(encoding="utf-8"), "the good roster must survive"


# ---------------------------------------------------------------------------
# The invariant every comparability argument rests on
# ---------------------------------------------------------------------------


def test_no_league_is_served_by_two_sources():
    """`build_usage_profiles` normalises a squad's rates into shares summing to
    ~1.0. ESPN's `xg_per90` is REALISED goals per 90; Understat's and ASA's are
    model xG. Same unit and same quantity in expectation, different estimator --
    which is safe ONLY because no squad ever mixes them.

    `fetch_players` dispatches MLS -> ASA, Understat leagues -> Understat,
    everything else with an ESPN slug -> ESPN, in that order. So the source is a
    pure function of the league. This test is what stops that from silently
    becoming untrue.
    """
    asa = {"mls"}
    understat = set(UNDERSTAT_LEAGUES)
    espn = set(LEAGUE_ESPN_SLUGS) - asa - understat

    assert asa & understat == set()
    assert asa & espn == set()
    assert understat & espn == set()
    assert espn == set(ESPN_ONLY_LEAGUES), (
        "a league moved between sources -- re-check that its players_*.csv files "
        "are all from ONE source before shipping"
    )
    assert asa | understat | espn == set(LEAGUE_ESPN_SLUGS)
