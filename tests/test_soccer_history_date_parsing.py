"""The as-of filter must work on the date format the leagues actually ship.

`soccer-backtest-leakage` made `as_of` required and was closed as verified. It
was also INERT for nine of ten leagues, because `compute_team_ratings` compared
`str(date)[:10] >= cutoff` as raw text and every `history/*.csv` carries
`DD/MM/YYYY`. `'17/05/2026' >= '2026-08-14'` is False, so no row was ever
filtered.

`tests/test_soccer_team_ratings_as_of.py` passed throughout, because its
fixtures are ISO. That is the whole lesson: a date test written in the format
the code already handles cannot detect that the code only handles that format.
Every test here is therefore written in the format the DATA uses.
"""

from __future__ import annotations

import pytest

from syndicate.features.soccer.features.loaders import (
    _as_iso_day,
    compute_team_ratings,
    team_rows_from_match_history,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("17/05/2026", "2026-05-17"),
        ("01/08/2023", "2023-08-01"),
        ("30/05/2024", "2024-05-30"),  # the day that used to read as "future"
        ("31/12/2025", "2025-12-31"),
        ("1/8/23", "2023-08-01"),
        ("2026-08-14", "2026-08-14"),
        ("2026-08-14T19:30:00Z", "2026-08-14"),
    ],
)
def test_parses_both_formats_the_sources_ship(raw, expected):
    assert _as_iso_day(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "garbage", "13/13/2026", "00/05/2026", "2026-13"])
def test_unparseable_is_none_so_it_takes_the_undated_branch(raw):
    """Unknown must not default permissive -- it is dropped, not kept."""
    assert _as_iso_day(raw) is None


def _match(date: str, home: str, away: str, hg: int, ag: int) -> dict:
    return {
        "league": "eredivisie",
        "season": 2025,
        "date": date,
        "home_team": home,
        "away_team": away,
        "home_goals": hg,
        "away_goals": ag,
    }


def test_as_of_actually_excludes_later_matches_in_dd_mm_yyyy():
    """The regression itself, in the format that broke it.

    Ajax scores heavily in August and is held scoreless in May. A rating taken
    as of 2026-01-01 must not know about the May result.
    """
    rows = team_rows_from_match_history(
        [
            _match("11/08/2025", "Ajax", "Feyenoord", 5, 0),
            _match("17/05/2026", "Ajax", "Utrecht", 0, 4),
        ]
    )

    early = compute_team_ratings(rows, as_of="2026-01-01")
    late = compute_team_ratings(rows, as_of="2026-08-14")

    assert early["Ajax"]["matches"] == 1.0, "the May match leaked into a January rating"
    assert late["Ajax"]["matches"] == 2.0
    assert early["Ajax"]["xg_for_per_match"] == 5.0
    assert late["Ajax"]["xg_for_per_match"] == 2.5


def test_a_match_on_the_30th_is_not_dropped_as_future():
    """`'30/05/2024' >= '2026-08-14'` was True, so it vanished from every rating."""
    rows = team_rows_from_match_history([_match("30/05/2024", "PSV", "Ajax", 3, 1)])

    ratings = compute_team_ratings(rows, as_of="2026-08-14")

    assert ratings["PSV"]["matches"] == 1.0
    assert ratings["PSV"]["xg_for_per_match"] == 3.0


def test_window_selects_the_most_recent_matches_not_the_latest_in_the_month():
    """`rows[-window:]` after a TEXT sort took the 45 highest days-of-month.

    Here the recent form (3 goals a game, September) must win over the older
    form (0 goals, but dated the 28th) -- text sorting puts '28/08' after
    '02/09' and would select exactly backwards.
    """
    rows = team_rows_from_match_history(
        [
            _match("28/08/2025", "Ajax", "Twente", 0, 0),
            _match("02/09/2025", "Ajax", "Vitesse", 3, 0),
        ]
    )

    ratings = compute_team_ratings(rows, as_of="2026-01-01", window=1)

    assert ratings["Ajax"]["matches"] == 1.0
    assert ratings["Ajax"]["xg_for_per_match"] == 3.0, "window took the older match"


def test_real_committed_history_is_actually_filtered_by_as_of():
    """Against the real files, because fixtures are what hid this for a session.

    Selected row counts must strictly INCREASE with the cutoff. Before the fix
    eredivisie returned an identical 923 at every date from 2023 to 2026.
    """
    import glob

    import pandas as pd

    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    paths = sorted(glob.glob(str(repo_root / "data" / "soccer_source" / "eredivisie" / "history" / "*.csv")))
    if not paths:
        pytest.skip("eredivisie history mirror not present in this checkout")

    match_rows: list[dict] = []
    for path in paths:
        match_rows.extend(pd.read_csv(path).to_dict("records"))
    rows = team_rows_from_match_history(match_rows)

    totals = [
        sum(rating["matches"] for rating in compute_team_ratings(rows, as_of=as_of).values())
        for as_of in ("2023-09-01", "2024-06-01", "2025-01-01", "2026-05-01")
    ]

    assert totals == sorted(totals), f"as-of is not monotonic: {totals}"
    assert len(set(totals)) == len(totals), f"as-of changed nothing between dates: {totals}"
