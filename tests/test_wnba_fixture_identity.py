"""The stable WNBA fixture identity.

WHY THIS EXISTS. `game_cards_<date>.csv` carried three incompatible `game_id`
schemes -- 1395 sequential indices, 39 hex hashes, 16 long numerics across 62
local files -- and two CONSECUTIVE production dates disagreed. Nothing could
join on it. `schedule_2026.csv` already held the ESPN event id, the same
namespace the live feed uses, and nobody was using it.

Most of these tests pin REFUSALS rather than lookups. That is deliberate: a
resolver that answers generously is how the sequential-index scheme survived,
and every refusal below corresponds to a wrong join that would otherwise be
silent.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import wnba_fixture_identity as ident


@pytest.fixture(autouse=True)
def _clean():
    ident._clear_cache()
    yield
    ident._clear_cache()


def _has_schedule() -> bool:
    return ident.schedule_path() is not None


requires_schedule = pytest.mark.skipif(
    not _has_schedule(), reason="schedule_2026.csv not present in this checkout"
)


# --------------------------------------------------------------------------
# The claim the whole design rests on.
# --------------------------------------------------------------------------


@requires_schedule
def test_the_schedule_ids_are_the_espn_event_ids():
    """Measured 2026-08-17 against ESPN's own scoreboard for the same date.

    If this ever fails, the pregame/live join is broken at the root and the
    identity is no longer shared -- which is the entire reason this module
    chose the schedule's id over minting a new one.
    """
    fixtures = ident.fixtures_for_date("2026-08-16")
    assert {f.fixture_id for f in fixtures} == {"401857148", "401857150", "401857149"}
    by_id = {f.fixture_id: f for f in fixtures}
    assert (by_id["401857148"].away_tricode, by_id["401857148"].home_tricode) == ("CHI", "SEA")
    assert (by_id["401857150"].away_tricode, by_id["401857150"].home_tricode) == ("IND", "ATL")
    assert (by_id["401857149"].away_tricode, by_id["401857149"].home_tricode) == ("POR", "PHX")


@requires_schedule
def test_the_denominator_is_three_on_the_date_game_cards_wrote_one():
    """The coverage defect, stated as a ratio.

    `game_cards_2026-08-16.csv` held 1 row while the sim had run for all three
    fixtures. A bare row count could not say that; this can.
    """
    assert len(ident.fixtures_for_date("2026-08-16")) == 3
    # ...and the neighbouring date is genuinely a one-game slate, so "1 row" is
    # CORRECT there. Pinned so nobody "fixes" a date that was never broken.
    assert len(ident.fixtures_for_date("2026-08-17")) == 1


# --------------------------------------------------------------------------
# Refusals.
# --------------------------------------------------------------------------


@requires_schedule
def test_orientation_is_part_of_the_identity():
    """A swapped home/away must NOT resolve.

    Matching it would join the row to the right game with the sides reversed,
    flipping the sign of every spread and margin -- a real number against the
    wrong side, which the repo already treats as worse than a blank.
    """
    right = ident.resolve_fixture_id("2026-08-16", "Phoenix Mercury", "Portland Fire")
    assert right == "401857149"
    assert ident.resolve_fixture_id("2026-08-16", "Portland Fire", "Phoenix Mercury") is None


@requires_schedule
def test_nba_contamination_resolves_to_none_rather_than_a_nearest_match():
    """Both of these really appear in WNBA `game_cards`, one row each.

    A permissive matcher would silently absorb them. None is the correct answer
    and lets the caller report genuine upstream contamination.
    """
    assert ident.normalize_team("Oklahoma City Thunder") is None
    assert ident.normalize_team("San Antonio Spurs") is None


@requires_schedule
def test_a_team_playing_itself_is_refused():
    assert ident.resolve_fixture_id("2026-08-16", "Phoenix Mercury", "Phoenix Mercury") is None


@requires_schedule
def test_a_date_with_no_fixtures_is_empty_not_an_error():
    assert ident.fixtures_for_date("2026-12-25") == ()
    assert ident.fixtures_for_date("") == ()
    assert ident.fixtures_for_date(None) == ()


def test_a_missing_schedule_yields_empty_and_never_raises(monkeypatch, tmp_path):
    """This module is imported by an artifact BUILD path.

    A lookup that raises would take down the build it exists to serve, which is
    the `#375` census lesson: a diagnostic must never break its subject.
    """
    monkeypatch.setenv("SYNDICATE_WNBA_SCHEDULE_PATH", str(tmp_path / "nope.csv"))
    ident._clear_cache()
    assert ident.schedule_path() is None
    assert ident.load_schedule() == ()
    assert ident.fixtures_for_date("2026-08-16") == ()
    assert ident.resolve_fixture_id("2026-08-16", "Phoenix Mercury", "Portland Fire") is None
    assert ident.normalize_team("Phoenix Mercury") is None


def test_a_corrupt_schedule_yields_empty_and_never_raises(monkeypatch, tmp_path):
    bad = tmp_path / "schedule_2026.csv"
    bad.write_bytes(b"\xff\xfe not,a,valid\x00 csv\nrow")
    monkeypatch.setenv("SYNDICATE_WNBA_SCHEDULE_PATH", str(bad))
    ident._clear_cache()
    assert ident.load_schedule() == ()


def test_rows_missing_any_part_of_their_identity_are_dropped(monkeypatch, tmp_path):
    """A fixture with no id is exactly what this module exists to stop."""
    csv_path = tmp_path / "schedule_2026.csv"
    csv_path.write_text(
        "game_id,date_est,home_tricode,away_tricode,home_city,home_name,"
        "away_city,away_name,datetime_utc,season_type_slug\n"
        ",2026-08-16,PHX,POR,Phoenix,Mercury,Portland,Fire,2026-08-16 23:00:00+00:00,regular-season\n"
        "401857149,2026-08-16,PHX,POR,Phoenix,Mercury,Portland,Fire,2026-08-16 23:00:00+00:00,regular-season\n"
        "401857999,,PHX,SEA,Phoenix,Mercury,Seattle,Storm,2026-08-16 23:00:00+00:00,regular-season\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SYNDICATE_WNBA_SCHEDULE_PATH", str(csv_path))
    ident._clear_cache()
    fixtures = ident.load_schedule()
    assert [f.fixture_id for f in fixtures] == ["401857149"]


def test_a_duplicated_matchup_refuses_rather_than_picking_one(monkeypatch, tmp_path):
    """Ambiguity is not resolved by taking the first.

    Same rule `wnba_game_projections.lookup` already uses: two candidates means
    the join cannot know which, and a wrong fixture is worse than none.
    """
    csv_path = tmp_path / "schedule_2026.csv"
    header = (
        "game_id,date_est,home_tricode,away_tricode,home_city,home_name,"
        "away_city,away_name,datetime_utc,season_type_slug\n"
    )
    row = "{gid},2026-08-16,PHX,POR,Phoenix,Mercury,Portland,Fire,2026-08-16 23:00:00+00:00,regular-season\n"
    csv_path.write_text(header + row.format(gid="1001") + row.format(gid="1002"), encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_WNBA_SCHEDULE_PATH", str(csv_path))
    ident._clear_cache()
    assert len(ident.fixtures_for_date("2026-08-16")) == 2
    assert ident.resolve_fixture_id("2026-08-16", "Phoenix Mercury", "Portland Fire") is None


@requires_schedule
def test_the_fixture_carries_no_status_field():
    """THE MOST IMPORTANT REFUSAL HERE.

    `schedule_2026.csv` has a `game_status_text` column and it is STALE:
    measured 2026-08-17 it read "In Progress" for CHI@SEA and IND@ATL and
    "Scheduled" for POR@PHX while ESPN had all three Final. The only way to
    guarantee nobody joins a board to a dead status is not to expose it.
    """
    fixture = ident.fixtures_for_date("2026-08-16")[0]
    for banned in ("status", "game_status", "game_status_text", "state", "is_final"):
        assert not hasattr(fixture, banned), f"{banned} must not be reachable from Fixture"


# --------------------------------------------------------------------------
# Lookups.
# --------------------------------------------------------------------------


@requires_schedule
@pytest.mark.parametrize(
    "spelling,expected",
    [
        ("Phoenix Mercury", "PHX"),
        ("phoenix mercury", "PHX"),
        ("  Phoenix   Mercury  ", "PHX"),
        ("PHX", "PHX"),
        ("phx", "PHX"),
        ("Golden State Valkyries", "GSV"),
        ("Las Vegas Aces", "LVA"),
        ("Washington Mystics", "WSH"),
        ("", None),
        (None, None),
    ],
)
def test_team_spellings_that_appear_in_real_artifacts_resolve(spelling, expected):
    assert ident.normalize_team(spelling) == expected


@requires_schedule
def test_resolve_accepts_tricodes_as_well_as_full_names():
    assert ident.resolve_fixture_id("2026-08-16", "PHX", "POR") == "401857149"
    assert ident.resolve_fixture_id("2026-08-16", "Phoenix Mercury", "POR") == "401857149"


@requires_schedule
def test_season_type_is_exposed_so_preseason_can_be_excluded():
    fixtures = ident.load_schedule()
    assert any(f.season_type == "preseason" for f in fixtures)
    assert all(f.is_regular_season for f in ident.fixtures_for_date("2026-08-16", regular_season_only=True))


# --------------------------------------------------------------------------
# Coverage reporting.
# --------------------------------------------------------------------------


@requires_schedule
def test_coverage_reports_the_real_defect_as_a_ratio():
    rows = [{"home_team": "Phoenix Mercury", "visitor_team": "Portland Fire"}]
    out = ident.coverage_against_schedule("2026-08-16", rows)
    assert out["scheduled"] == 3
    assert out["covered"] == 1
    assert sorted(out["missing_matchups"]) == ["CHI@SEA", "IND@ATL"]
    assert out["unresolved_rows"] == []


@requires_schedule
def test_coverage_separates_a_missing_fixture_from_an_unresolvable_row():
    """Two different bugs with two different fixes; they must not look alike."""
    rows = [
        {"home_team": "Phoenix Mercury", "visitor_team": "Portland Fire"},
        {"home_team": "Oklahoma City Thunder", "visitor_team": "San Antonio Spurs"},
    ]
    out = ident.coverage_against_schedule("2026-08-16", rows)
    assert out["covered"] == 1
    assert len(out["missing_fixture_ids"]) == 2
    assert out["unresolved_rows"] == [
        {"home": "Oklahoma City Thunder", "away": "San Antonio Spurs"}
    ]


@requires_schedule
def test_coverage_does_not_double_count_a_repeated_fixture():
    rows = [{"home_team": "PHX", "visitor_team": "POR"}] * 4
    assert ident.coverage_against_schedule("2026-08-16", rows)["covered"] == 1
