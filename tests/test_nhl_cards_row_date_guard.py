"""An NHL predictions row must not be served under a date it does not claim.

Measured 2026-09-28 18:2xZ on production. The Layer 2 compact rail carried
SEVEN NHL chips on a date the NHL's own API says has ZERO games -- preseason
ended 09-26 and opening night is 09-29. The seven were
`predictions_2026-09-19.csv` row-for-row and in order (DAL@STL, MTL@TOR,
TOR@MTL, WPG@EDM, CHI@MIN, VGK@LAK, VAN@SEA -- the first seven preseason games
of the season, `gamePk` 1..7), served under `date=2026-09-28` off a
`worker_artifact` 46 SECONDS old.

The rows carried a populated `date` column the whole time. Nothing read it.

The first test is the REACHABILITY test (`off != on`): without the guard the
mis-dated rows are served, so it is the one that proves the guard is wired in at
all. The rest pin the behaviour either side of it -- in particular that a BLANK
date is kept, because absence is not disagreement and the permissive branch must
be the one that cannot silently empty a board.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from syndicate.features.nhl import cards

_HEADER = "home,away,date,p_home_ml,p_away_ml,model_total\n"

# The real seven, in the order production served them.
_SEPT_19_SLATE = [
    ("St. Louis Blues", "Dallas Stars"),
    ("Toronto Maple Leafs", "Montreal Canadiens"),
    ("Montreal Canadiens", "Toronto Maple Leafs"),
    ("Edmonton Oilers", "Winnipeg Jets"),
    ("Minnesota Wild", "Chicago Blackhawks"),
    ("Los Angeles Kings", "Vegas Golden Knights"),
    ("Seattle Kraken", "Vancouver Canucks"),
]


def _write(root: Path, filename: str, rows: list[tuple[str, str, str]]) -> Path:
    """`rows` are (home, away, row_date) -- row_date deliberately independent of
    the filename, which is the whole point of this file."""
    body = _HEADER + "".join(f"{home},{away},{row_date},0.55,0.45,6.1\n" for home, away, row_date in rows)
    path = root / filename
    path.write_text(body, encoding="utf-8")
    return path


def _patched(root: Path, dates: list[str]):
    return (
        patch.object(cards, "processed_path", side_effect=lambda *parts: root.joinpath(*parts)),
        patch.object(cards, "scoreboard_snapshot_path", side_effect=lambda d: root / "scoreboard" / f"{d}.csv"),
        patch.object(cards, "source_available_dates", return_value=list(dates)),
    )


def test_mis_dated_rows_are_dropped_and_the_unguarded_read_still_sees_them(tmp_path: Path) -> None:
    """REACHABILITY. `_load_csv_rows` is the pre-guard behaviour: it must still
    return all seven, or this test would pass on a no-op guard."""
    path = _write(tmp_path, "predictions_2026-09-28.csv", [(h, a, "2026-09-19") for h, a in _SEPT_19_SLATE])

    assert len(cards._load_csv_rows(path)) == 7, "unguarded read changed -- this test no longer discriminates"
    assert cards._prediction_rows_for_date(path, "2026-09-28") == []


def test_rows_whose_date_matches_are_kept(tmp_path: Path) -> None:
    path = _write(tmp_path, "predictions_2026-09-29.csv", [
        ("Carolina Hurricanes", "Florida Panthers", "2026-09-29"),
        ("Toronto Maple Leafs", "Montreal Canadiens", "2026-09-29"),
    ])

    assert len(cards._prediction_rows_for_date(path, "2026-09-29")) == 2


def test_a_blank_date_column_is_kept_not_dropped(tmp_path: Path) -> None:
    """Absence is not disagreement. A row that says nothing about its date keeps
    the old behaviour; only a row naming a DIFFERENT date is refused."""
    path = _write(tmp_path, "predictions_2026-09-29.csv", [("Carolina Hurricanes", "Florida Panthers", "")])

    assert len(cards._prediction_rows_for_date(path, "2026-09-29")) == 1


def test_a_mixed_file_keeps_only_the_rows_for_the_requested_date(tmp_path: Path) -> None:
    path = _write(tmp_path, "predictions_2026-09-29.csv", [
        ("Carolina Hurricanes", "Florida Panthers", "2026-09-29"),
        ("Minnesota Wild", "Chicago Blackhawks", "2026-09-19"),
        ("Boston Bruins", "New York Rangers", "2026-09-29"),
    ])

    kept = cards._prediction_rows_for_date(path, "2026-09-29")
    assert [row["away"] for row in kept] == ["Florida Panthers", "New York Rangers"]


def test_a_timestamp_is_compared_in_the_BOARD_timezone_not_by_truncation(tmp_path: Path) -> None:
    """THIS TEST REPLACES ONE THAT ASSERTED THE BUG.

    The version here before 2026-09-29 pinned `str(...)[:10]` as correct, using a
    fixture I invented (a 21:00Z row under a 09-29 filename -- a time of day where
    UTC and Central agree, so it could not fail). It passed while production dropped
    real games. A test written from the same wrong model as the code confirms the
    model, not the behaviour.

    Every row below is READ FROM PRODUCTION: `predictions_2026-01-25.csv`, whose two
    late games are 6:00 PM and 7:00 PM Central ON THE 25th and were being thrown
    away. `str(...)[:10]` on those gives 2026-01-26, so this test fails on the old
    code -- which is the property the old one lacked.
    """
    path = _write(tmp_path, "predictions_2026-01-25.csv", [
        ("Toronto Maple Leafs", "Colorado Avalanche", "2026-01-25T18:30:00Z"),
        ("Seattle Kraken", "New Jersey Devils", "2026-01-25T20:00:00Z"),
        ("Ottawa Senators", "Vegas Golden Knights", "2026-01-25T22:00:00Z"),
        ("Vancouver Canucks", "Pittsburgh Penguins", "2026-01-25T23:00:00Z"),
        ("Chicago Blackhawks", "Florida Panthers", "2026-01-26T00:00:00Z"),
        ("Calgary Flames", "Anaheim Ducks", "2026-01-26T01:00:00Z"),
    ])

    kept = cards._prediction_rows_for_date(path, "2026-01-25")

    assert len(kept) == 6, "the two late games belong to the 25th in the board's timezone"
    assert [row["away"] for row in kept][-2:] == ["Florida Panthers", "Anaheim Ducks"]
    # ...and the truncation the old test enshrined would have dropped exactly those.
    assert [r[2][:10] for r in (("", "", "2026-01-26T00:00:00Z"), ("", "", "2026-01-26T01:00:00Z"))] ==         ["2026-01-26", "2026-01-26"], "if this ever equals 2026-01-25 the test stops discriminating"


def test_a_single_late_game_is_not_a_zero_game_slate(tmp_path: Path) -> None:
    """The worst measured case: on the playoff dates the file holds ONE game, it
    starts after midnight UTC, and truncation took the board to zero.
    `predictions_2026-05-24.csv` -- COL @ VGK at 7:00 PM Central on the 24th."""
    path = _write(tmp_path, "predictions_2026-05-24.csv", [
        ("Vegas Golden Knights", "Colorado Avalanche", "2026-05-25T00:00:00Z"),
    ])

    assert len(cards._prediction_rows_for_date(path, "2026-05-24")) == 1


def test_a_timestamp_naming_a_genuinely_different_slate_is_still_dropped(tmp_path: Path) -> None:
    """The guard must not be softened into uselessness: a timestamp that resolves to
    another date in the BOARD timezone is still refused."""
    path = _write(tmp_path, "predictions_2026-01-25.csv", [
        ("Chicago Blackhawks", "Florida Panthers", "2026-01-26T00:00:00Z"),
        ("Toronto Maple Leafs", "Colorado Avalanche", "2026-01-27T18:30:00Z"),
    ])

    kept = cards._prediction_rows_for_date(path, "2026-01-25")
    assert [row["away"] for row in kept] == ["Florida Panthers"]


def test_an_unparseable_stamp_falls_back_to_truncation_not_to_no_date(tmp_path: Path) -> None:
    """Never map "cannot parse" onto the permissive branch: that would let a
    genuinely mis-dated row through with nothing emitted."""
    path = _write(tmp_path, "predictions_2026-09-29.csv", [
        ("Carolina Hurricanes", "Florida Panthers", "2026-09-19Tnot-a-time"),
    ])

    assert cards._prediction_rows_for_date(path, "2026-09-29") == []


def test_date_has_rows_is_false_for_a_file_of_only_mis_dated_rows(tmp_path: Path) -> None:
    """The gate lookahead reads. If this stayed True the guard would empty the
    slate WITHOUT letting lookahead rescue it -- a blank board instead of a wrong
    one, which is not the fix."""
    _write(tmp_path, "predictions_2026-09-28.csv", [(h, a, "2026-09-19") for h, a in _SEPT_19_SLATE])

    p1, p2, p3 = _patched(tmp_path, ["2026-09-28"])
    with p1, p2, p3:
        assert cards._date_has_rows("2026-09-28") is False


def test_a_mis_dated_today_file_looks_ahead_to_the_real_next_slate(tmp_path: Path) -> None:
    """End to end, production's exact shape: a 09-28 file holding 09-19's rows
    beside a correct 09-29 file. 09-28 must resolve to 09-29, not serve 09-19."""
    _write(tmp_path, "predictions_2026-09-28.csv", [(h, a, "2026-09-19") for h, a in _SEPT_19_SLATE])
    _write(tmp_path, "predictions_2026-09-29.csv", [
        ("Carolina Hurricanes", "Florida Panthers", "2026-09-29"),
        ("Toronto Maple Leafs", "Montreal Canadiens", "2026-09-29"),
    ])

    p1, p2, p3 = _patched(tmp_path, ["2026-09-28", "2026-09-29"])
    with p1, p2, p3:
        assert cards._resolve_cards_date("2026-09-28") == ("2026-09-28", "2026-09-29", True)


def test_games_from_artifact_serves_nothing_for_a_mis_dated_file(tmp_path: Path) -> None:
    _write(tmp_path, "predictions_2026-09-28.csv", [(h, a, "2026-09-19") for h, a in _SEPT_19_SLATE])

    p1, p2, p3 = _patched(tmp_path, ["2026-09-28"])
    with p1, p2, p3:
        games, _source = cards._games_from_artifact("2026-09-28")

    assert games == []


def test_the_sim_fallback_is_guarded_too(tmp_path: Path) -> None:
    """`predictions_sim_<date>.csv` is the second source `_games_from_artifact`
    tries, and `_date_has_rows` reads it as well -- guarding only the primary
    would leave the same hole one file over."""
    _write(tmp_path, "predictions_sim_2026-09-28.csv", [(h, a, "2026-09-19") for h, a in _SEPT_19_SLATE])

    p1, p2, p3 = _patched(tmp_path, ["2026-09-28"])
    with p1, p2, p3:
        games, _source = cards._games_from_artifact("2026-09-28")
        assert games == []
        assert cards._date_has_rows("2026-09-28") is False


def test_without_the_guard_the_same_fixture_reproduces_the_production_bug(tmp_path: Path) -> None:
    """`off != on`, for the two call sites where the guard's effect is INDIRECT.

    Patching `_prediction_rows_for_date` back to `_load_csv_rows` is exactly the
    pre-fix code path, in-process. If this ever starts agreeing with the guarded
    case, the guard has stopped being load-bearing and the tests above are
    passing for some other reason.
    """
    _write(tmp_path, "predictions_2026-09-28.csv", [(h, a, "2026-09-19") for h, a in _SEPT_19_SLATE])
    _write(tmp_path, "predictions_2026-09-29.csv", [("Carolina Hurricanes", "Florida Panthers", "2026-09-29")])

    p1, p2, p3 = _patched(tmp_path, ["2026-09-28", "2026-09-29"])
    unguarded = patch.object(cards, "_prediction_rows_for_date", side_effect=lambda path, _date: cards._load_csv_rows(path))
    with p1, p2, p3, unguarded:
        assert cards._date_has_rows("2026-09-28") is True
        assert cards._resolve_cards_date("2026-09-28") == ("2026-09-28", "2026-09-28", False)
        games, _source = cards._games_from_artifact("2026-09-28")
        assert len(games) == 7
        assert [g["away_tri"] for g in games] == ["DAL", "MTL", "TOR", "WPG", "CHI", "VGK", "VAN"]
        assert [str(g["gamePk"]) for g in games] == ["1", "2", "3", "4", "5", "6", "7"]


def test_without_the_timezone_resolver_the_regression_comes_back(tmp_path: Path) -> None:
    """`off != on` for the timezone fix.

    Patching `_row_slate_date` back to the truncation is exactly the code that was
    live on web and refresh-worker between `fae9aab8` (2026-09-28T23:48Z) and this
    change. If this ever stops dropping rows, the resolver has stopped mattering and
    the tests above are passing for some other reason.
    """
    rows = [
        ("Toronto Maple Leafs", "Colorado Avalanche", "2026-01-25T18:30:00Z"),
        ("Seattle Kraken", "New Jersey Devils", "2026-01-25T20:00:00Z"),
        ("Ottawa Senators", "Vegas Golden Knights", "2026-01-25T22:00:00Z"),
        ("Vancouver Canucks", "Pittsburgh Penguins", "2026-01-25T23:00:00Z"),
        ("Chicago Blackhawks", "Florida Panthers", "2026-01-26T00:00:00Z"),
        ("Calgary Flames", "Anaheim Ducks", "2026-01-26T01:00:00Z"),
    ]
    path = _write(tmp_path, "predictions_2026-01-25.csv", rows)
    truncating = patch.object(cards, "_row_slate_date",
                              side_effect=lambda v: str(v or "").strip()[:10] or None)

    with truncating:
        kept = cards._prediction_rows_for_date(path, "2026-01-25")

    assert len(kept) == 4, "the pre-fix truncation must lose the two late games"
    assert [row["away"] for row in kept] == [
        "Colorado Avalanche", "New Jersey Devils", "Vegas Golden Knights", "Pittsburgh Penguins",
    ]
    # and the single-game playoff case went to ZERO, which is the worst of it
    lone = _write(tmp_path, "predictions_2026-05-24.csv",
                  [("Vegas Golden Knights", "Colorado Avalanche", "2026-05-25T00:00:00Z")])
    with truncating:
        assert cards._prediction_rows_for_date(lone, "2026-05-24") == []
