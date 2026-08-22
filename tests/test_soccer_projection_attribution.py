"""`unmatched_match_rows` was a bare total, and it has read ~99.6% for days.

`state.md` records the soccer join at `rows_with_projection: 4` of 1,142 with
1,138 unmatched, and the user's report is the same fact from the other side:
"none of the soccer data from sims (pregame or live) is joining with the board".

ONE NUMBER, THREE UNRELATED CAUSES. `unmatched_match_rows` cannot distinguish:

  * the league is not in the index at all -- the sim never ran it, or its
    recommendations file falls outside the read window. Fix: the producer.
  * the league IS indexed and its rows still miss -- the two feeds spell the
    club differently. Fix: `_SOCCER_VENDOR_NAME_ALIASES`, and only after seeing
    BOTH spellings.
  * the team key was dropped as ambiguous -- `match_for` refusing on purpose,
    because a wrong projection is worse than a blank one. Not a defect at all.

Those have three different owners and, until this change, one identical
symptom. Same contract `#296` set and `LIVE_PROJECTION_JOIN` already meets for
the live tier: a zero must be attributable, never bare.

WHY THE PAIRED SAMPLES. A board-side name alone answers half a name-join
question. `#374` added five vendor aliases and its note is explicit that each
was "verified against a real 0-projection fixture" -- you cannot write the alias
without knowing what the SIM calls the club, so the coverage carries both sides.
"""

from __future__ import annotations

import json
from pathlib import Path

from syndicate.features.shared.soccer_projections import (
    attach_soccer_projections,
    load_soccer_projections,
)

DATE = "2026-08-22"


def _write(root: Path, league: str, date: str, fixtures: list[tuple[str, str]]) -> None:
    path = root / league / "api" / "recommendations" / f"recommendations_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "league": league,
                "generated_at": "2026-08-22T10:00:00",
                "matches": [
                    {
                        "match_id": f"{league}-{i}",
                        "event_id": f"espn-{league}-{i}",
                        "league": league,
                        "matchup": {"home_team": home, "away_team": away},
                        "win_probability": {"home": 0.5, "draw": 0.25, "away": 0.25},
                    }
                    for i, (home, away) in enumerate(fixtures)
                ],
            }
        ),
        encoding="utf-8",
    )


def _row(league: str, home: str, away: str, event_id: str) -> dict:
    return {
        "sport": "soccer",
        "kind": "game",
        "market": "h2h",
        "league": league,
        "event_id": event_id,
        "home_team": home,
        "away_team": away,
        "line": None,
    }


def test_per_league_counts_separate_an_unrun_league_from_a_name_miss(tmp_path: Path) -> None:
    """The two causes that need completely different fixes, told apart."""
    _write(tmp_path, "serie_a", DATE, [("Internazionale", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    grid = [
        # serie_a IS indexed; this row misses on the club's spelling.
        _row("serie_a", "Inter Milan", "Monza", "oddsapi-1"),
        # epl is not in the index at all -- nothing was simulated for it.
        _row("epl", "Arsenal", "Chelsea", "oddsapi-2"),
        _row("epl", "Everton", "Fulham", "oddsapi-3"),
    ]
    coverage = attach_soccer_projections(grid, index)

    assert coverage["unmatched_match_rows"] == 3
    assert coverage["leagues_indexed"] == ["serie_a"]
    # The split is the whole point: one league needs an alias, the other needs
    # the sim to run. The bare total said "3" and named neither.
    assert coverage["unmatched_by_league"] == {"epl": 2, "serie_a": 1}
    assert coverage["rows_by_league"] == {"epl": 2, "serie_a": 1}


def test_the_sample_carries_both_spellings_of_the_same_fixture(tmp_path: Path) -> None:
    """An alias cannot be written from the board's name alone."""
    _write(tmp_path, "serie_a", DATE, [("Internazionale", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    coverage = attach_soccer_projections(
        [_row("serie_a", "Inter Milan", "Monza", "oddsapi-1")], index
    )
    assert coverage["unmatched_fixture_sample"] == ["serie_a|Inter Milan v Monza"]
    assert coverage["indexed_fixture_sample"] == ["serie_a|Internazionale v Monza"]


def test_a_missed_fixture_contributes_one_sample_not_one_per_row(tmp_path: Path) -> None:
    """A soccer fixture carries hundreds of rows and they all miss identically.

    Per-row sampling would fill the list with the same pair and name nothing --
    which is the failure mode the live tier's `unmatched_samples` was capped
    against for the same reason.
    """
    _write(tmp_path, "serie_a", DATE, [("Internazionale", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    grid = [_row("serie_a", "Inter Milan", "Monza", f"oddsapi-{i}") for i in range(300)]
    coverage = attach_soccer_projections(grid, index)

    assert coverage["unmatched_match_rows"] == 300
    assert coverage["unmatched_fixtures_count"] == 1
    assert coverage["unmatched_fixture_sample"] == ["serie_a|Inter Milan v Monza"]


def test_a_row_that_joins_is_absent_from_every_unmatched_counter(tmp_path: Path) -> None:
    """The instrument must not report a defect where there is none."""
    _write(tmp_path, "serie_a", DATE, [("Internazionale", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    coverage = attach_soccer_projections(
        [_row("serie_a", "Internazionale", "Monza", "oddsapi-1")], index
    )
    assert coverage["rows_with_projection"] == 1
    assert coverage["unmatched_match_rows"] == 0
    assert coverage["unmatched_by_league"] == {}
    assert coverage["unmatched_fixture_sample"] == []
    # Still counted as considered -- `rows_by_league` describes the SLATE, so a
    # league at 100% coverage must not vanish from it.
    assert coverage["rows_by_league"] == {"serie_a": 1}


def test_dates_read_is_reported_so_an_unread_date_is_not_read_as_a_name_miss(tmp_path: Path) -> None:
    _write(tmp_path, "serie_a", "2026-08-24", [("Internazionale", "Monza")])
    window = [DATE, "2026-08-23", "2026-08-24"]
    index = load_soccer_projections([tmp_path], DATE, window_dates=window)

    coverage = attach_soccer_projections(
        [_row("serie_a", "Internazionale", "Monza", "oddsapi-1")], index
    )
    assert coverage["dates_read"] == window
    assert coverage["rows_with_projection"] == 1


def test_a_row_with_no_league_is_bucketed_rather_than_dropped(tmp_path: Path) -> None:
    """`league` is carried, not keyed (`#330`), so it can genuinely be absent.

    Silently skipping those rows would make the per-league counts stop summing
    to the total, and a counter that does not reconcile is worse than none.
    """
    _write(tmp_path, "serie_a", DATE, [("Internazionale", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    grid = [_row("serie_a", "Inter Milan", "Monza", "oddsapi-1")]
    grid[0]["league"] = None
    coverage = attach_soccer_projections(grid, index)

    assert coverage["rows_by_league"] == {"?": 1}
    assert sum(coverage["unmatched_by_league"].values()) == coverage["unmatched_match_rows"]
