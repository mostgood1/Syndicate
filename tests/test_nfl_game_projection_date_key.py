"""The NFL projection join compared a UTC day against an ET day.

MEASURED ON PRODUCTION 2026-09-04T20:56:12Z, `GET /api/board/book-grid?sport=nfl`:
`unmatched_game_rows: 299` of `rows_considered: 1252` -- 23.9% of the NFL board
-- with a signature that names the cause on sight. Every Sunday-AFTERNOON UTC
date was fully projected and every prime-time UTC date was empty:

    2026-09-13   74 rows   74 projected     (Sun 13:00 / 16:25 ET)
    2026-09-14    5 rows    0 projected     (SNF, 20:20 ET on 09-13)
    2026-09-15    7 rows    0 projected     (MNF, 20:15 ET on 09-14)
    2026-09-20   57 rows   57 projected
    2026-09-21    6 rows    0 projected
    ... the same pattern on all 18 weeks in the grid ...

`NflGameProjectionIndex.lookup` keyed on `commence_time[:10]`, which is UTC,
while `load_nfl_game_projections` builds the index from the schedule's
`gameday`, which is local Eastern. Those disagree for every kickoff at or after
20:00 ET, because it rolls into the next UTC day:

    schedule   2026_01_NE_SEA   gameday 2026-09-09   gametime 20:20   (ET)
    board      commence_time    2026-09-10T00:20:00Z                  (UTC)

The `teams_match` fallback was pinned to `d == date_key`, so it missed too --
the join had no second chance.

WHY THESE TESTS EXIST IN THIS SHAPE. The three cases are not decoration:

  * a PRIME-TIME case, which is the defect;
  * an AFTERNOON case, because a fix that shifts every row by a day would
    "fix" prime time by breaking the 74 rows that already worked;
  * a DST case, because a fixed `-4` offset passes the first two and is wrong
    for the whole January playoff slate. The season spans the boundary; the
    zone must be looked up, not assumed.

Every test here was run RED against `origin/main` before the fix landed, and
`test_dst_is_resolved_from_the_zone_not_a_fixed_offset` was separately run red
against a fixed-offset implementation of the fix. See the lane block in
`.syndicate/lanes.md` (`nfl-projection-et-datekey`) for the mutation results.
"""

from __future__ import annotations

from syndicate.features.shared.nfl_game_projections import (
    NflGameProjectionIndex,
    attach_nfl_game_projections,
    schedule_date_key,
)

# Real rows off the served production board, not invented ones.
SNF_HOME, SNF_AWAY = "Seattle Seahawks", "New England Patriots"
SNF_GAMEDAY = "2026-09-09"          # schedule `gameday`, ET
SNF_COMMENCE = "2026-09-10T00:20:00Z"  # board `commence_time`, UTC -- 20:20 EDT

AFTERNOON_HOME, AFTERNOON_AWAY = "Pittsburgh Steelers", "Atlanta Falcons"
AFTERNOON_GAMEDAY = "2026-09-13"
AFTERNOON_COMMENCE = "2026-09-13T17:00:00Z"  # 13:00 EDT, same UTC day

# January is EST (UTC-5), not EDT. A 20:15 ET kickoff is 01:15Z the next day.
EST_HOME, EST_AWAY = "Buffalo Bills", "Miami Dolphins"
EST_GAMEDAY = "2027-01-10"
EST_COMMENCE = "2027-01-11T01:15:00Z"

_ENTRY = {
    "margin_mean": -0.035,
    "total_mean": 46.275,
    "margin_stdev": 24.466,
    "total_stdev": 22.554,
    "home_win_rate": 0.53,
    "generated_at": "2026-09-02T17:17:40+00:00",
    "profile": "nfl_v1",
}


def _index(*entries: tuple[str, str, str]) -> NflGameProjectionIndex:
    """Index keyed the way `load_nfl_game_projections` keys it: ET `gameday`."""
    index = NflGameProjectionIndex()
    for gameday, home, away in entries:
        index.by_date_teams[(gameday, home, away)] = dict(_ENTRY)
    index.games = len(index.by_date_teams)
    return index


def _row(commence: str, home: str, away: str, *, market: str = "h2h") -> dict:
    return {
        "kind": "game",
        "market": market,
        "segment": "full",
        "line": None,
        "commence_time": commence,
        "home_team": home,
        "away_team": away,
    }


# --------------------------------------------------------------------------
# The defect.
# --------------------------------------------------------------------------


def test_a_prime_time_kickoff_joins_across_the_utc_day_boundary():
    """20:20 ET on 09-09 is 00:20Z on 09-10. Both must name 2026-09-09."""
    index = _index((SNF_GAMEDAY, "seattle seahawks", "new england patriots"))
    row = _row(SNF_COMMENCE, SNF_HOME, SNF_AWAY)
    coverage = attach_nfl_game_projections([row], index)
    assert row.get("projection") is not None, (
        "SNF kickoff at 20:20 ET rolls into the next UTC day; the index is keyed "
        "on the schedule's ET gameday, so the join must convert before comparing"
    )
    assert coverage["rows_with_projection"] == 1
    assert coverage["unmatched_game_rows"] == 0


def test_the_tri_code_fallback_also_crosses_the_boundary():
    """The `teams_match` second chance was pinned to the same wrong date.

    The board carries full names and the sim carries tri-codes, so prime-time
    rows failed the direct lookup AND the alias fallback -- `d == date_key`
    scanned a day the game is not on.
    """
    index = _index((SNF_GAMEDAY, "sea", "ne"))
    row = _row(SNF_COMMENCE, SNF_HOME, SNF_AWAY)
    coverage = attach_nfl_game_projections([row], index)
    assert row.get("projection") is not None
    assert coverage["unmatched_game_rows"] == 0


def test_an_est_prime_time_kickoff_joins():
    """January is EST. 20:15 ET on 2027-01-10 is 01:15Z on 2027-01-11."""
    index = _index((EST_GAMEDAY, "buffalo bills", "miami dolphins"))
    row = _row(EST_COMMENCE, EST_HOME, EST_AWAY)
    coverage = attach_nfl_game_projections([row], index)
    assert row.get("projection") is not None
    assert coverage["unmatched_game_rows"] == 0


# --------------------------------------------------------------------------
# What the fix must not break.
# --------------------------------------------------------------------------


def test_an_afternoon_kickoff_still_joins():
    """13:00 ET is 17:00Z the SAME day -- these 74 rows already worked.

    This is the test a `date_key - 1` fix fails. Shifting every row back a day
    recovers prime time and loses the afternoon slate, which is the larger half
    of the board.
    """
    index = _index((AFTERNOON_GAMEDAY, "pittsburgh steelers", "atlanta falcons"))
    row = _row(AFTERNOON_COMMENCE, AFTERNOON_HOME, AFTERNOON_AWAY)
    coverage = attach_nfl_game_projections([row], index)
    assert row.get("projection") is not None
    assert coverage["rows_with_projection"] == 1
    assert coverage["unmatched_game_rows"] == 0


def test_a_late_afternoon_kickoff_still_joins():
    """16:25 ET / 20:25Z -- the latest kickoff that does NOT cross midnight UTC."""
    index = _index(("2026-09-13", "los angeles chargers", "arizona cardinals"))
    row = _row("2026-09-13T20:25:00Z", "Los Angeles Chargers", "Arizona Cardinals")
    attach_nfl_game_projections([row], index)
    assert row.get("projection") is not None


def test_a_projection_still_never_crosses_a_real_date():
    """The date guard is the thing stopping a pair that meets twice a season.

    A conversion must not degrade into "match on teams alone". 2026-12-20 is a
    genuinely different game from 2026-09-09, in either timezone.
    """
    index = _index((SNF_GAMEDAY, "seattle seahawks", "new england patriots"))
    row = _row("2026-12-21T01:20:00Z", SNF_HOME, SNF_AWAY)
    coverage = attach_nfl_game_projections([row], index)
    assert row.get("projection") is None
    assert coverage["unmatched_game_rows"] == 1


def test_a_date_only_commence_time_is_not_shifted():
    """"2026-09-13" is already a calendar day, not midnight UTC.

    Parsing it yields naive 00:00, which read as UTC converts to the PREVIOUS
    ET day -- a brand-new off-by-one, in the one case that was never broken.
    """
    index = _index((AFTERNOON_GAMEDAY, "pittsburgh steelers", "atlanta falcons"))
    row = _row(AFTERNOON_GAMEDAY, AFTERNOON_HOME, AFTERNOON_AWAY)
    attach_nfl_game_projections([row], index)
    assert row.get("projection") is not None
    assert schedule_date_key("2026-09-13") == "2026-09-13"


def test_an_unreadable_commence_time_falls_back_to_the_old_slice():
    assert schedule_date_key("not a timestamp at all") == "not a time"
    assert schedule_date_key("") == ""
    assert schedule_date_key(None) == ""


# --------------------------------------------------------------------------
# DST -- why this is a named zone and not an offset.
# --------------------------------------------------------------------------


def test_dst_is_resolved_from_the_zone_not_a_fixed_offset():
    """The same UTC clock time is a different ET day in September and January.

    04:30Z is 00:30 EDT (UTC-4, same day) and 23:30 EST (UTC-5, previous day).
    A hardcoded `-4` gets the September answer right and the January answer
    wrong, which is exactly the failure mode a fixed offset has: correct for
    most of the season, silently wrong for the playoffs.
    """
    assert schedule_date_key("2026-09-14T04:30:00Z") == "2026-09-14", "EDT is UTC-4"
    assert schedule_date_key("2027-01-11T04:30:00Z") == "2027-01-10", "EST is UTC-5"


def test_the_dst_transition_weekend_resolves_on_both_sides():
    """2026-11-01 is the fall-back Sunday. Games are played that weekend.

    The Saturday-night stamp is still EDT and the Sunday-night one is already
    EST, five hours apart in offset terms, and both must land on their own ET
    day.
    """
    assert schedule_date_key("2026-11-01T00:20:00Z") == "2026-10-31", "still EDT"
    assert schedule_date_key("2026-11-02T01:20:00Z") == "2026-11-01", "now EST"


def test_the_key_matches_the_schedules_own_gameday_for_every_kickoff_slot():
    """Every real NFL kickoff slot, ET wall clock -> UTC stamp -> ET key.

    Enumerated rather than sampled because the bug was a boundary: 09:30 ET
    (London) through 20:20 ET (SNF) spans 13:30Z to 00:20Z-next-day, and only
    the last two cross midnight UTC.
    """
    slots = {
        "2026-09-13T13:30:00Z": "2026-09-13",  # 09:30 ET, London
        "2026-09-13T17:00:00Z": "2026-09-13",  # 13:00 ET
        "2026-09-13T20:05:00Z": "2026-09-13",  # 16:05 ET
        "2026-09-13T20:25:00Z": "2026-09-13",  # 16:25 ET
        "2026-09-14T00:20:00Z": "2026-09-13",  # 20:20 ET, SNF -- crosses
        "2026-09-15T00:15:00Z": "2026-09-14",  # 20:15 ET, MNF -- crosses
        "2026-09-11T00:15:00Z": "2026-09-10",  # 20:15 ET, TNF -- crosses
    }
    for stamp, expected in slots.items():
        assert schedule_date_key(stamp) == expected, stamp
