"""NHL quote rows are sharded by the GAME's date, in the BOARD's timezone.

THE FAILURE THIS PINS, measured on production 2026-09-25. NHL had four games
that night and ZERO rows on the Layer 1 board:

    rows_in_grid: 18   rows_other_dates: 18   other_dates: {"2026-09-24": 18}
    enrichment: "no_rows"

Two independent date errors stacked:

1. `_append_nhl_book_quotes` filed EVERY row under the collector's RUN date.
   The fetch window is deliberately +/-8h (`_date_range_utc`), so a run for
   2026-09-25 sweeps up the previous evening's Central games -- and filed them
   as 09-25.
2. A game's date was taken as `commence_time[:10]`, the UTC date. A 7pm-Central
   game is `T00:00:00Z` the NEXT day, so it read 09-26 while the board
   (`layer1_board._BOARD_TZ`, America/Chicago) scoped 09-25.

Either one alone empties the NHL board. The live re-sim -- whose whole chain was
repaired the same day -- had nothing to join to, and `considered=0` sat in every
join line while that work went on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pd = pytest.importorskip("pandas")

import syndicate.local_nhl_odds as mod  # noqa: E402


def _row(commence_time: str, away: str = "Bruins", home: str = "Flyers") -> dict:
    return {
        "event_id": f"{away}{home}{commence_time}",
        "commence_time": commence_time,
        "home_team": home,
        "away_team": away,
        "book": "fanduel",
        "market": "h2h",
        "outcome_name": away,
        "odds": 120,
        "line": None,
        "book_last_update": None,
    }


@pytest.fixture
def captured(monkeypatch):
    seen: list[tuple[str, int]] = []

    def _fake(*, sport, date_str, rows, captured_at):
        seen.append((date_str, len(rows)))

    import syndicate.features.shared.odds_book_quotes as obq

    monkeypatch.setattr(obq, "append_book_quotes", _fake)
    return seen


# --------------------------------------------------- the timezone half

def test_an_evening_central_game_is_not_the_next_utc_day():
    """7:00 PM CDT on 09-25 is 2026-09-26T00:00:00Z. The board scopes Central."""
    seven_pm_central = "2026-09-26T00:00:00Z"
    assert seven_pm_central[:10] == "2026-09-26", "precondition: the UTC slice disagrees"
    assert mod._commence_date_board(seven_pm_central) == "2026-09-25"


def test_a_late_west_coast_start_is_still_the_same_central_day():
    assert mod._commence_date_board("2026-09-26T02:30:00Z") == "2026-09-25"


def test_the_helper_reads_the_boards_own_timezone_variable(monkeypatch):
    """Hard-coding the zone would be right today and silently wrong later."""
    monkeypatch.setenv("SYNDICATE_BOARD_TZ", "UTC")
    assert mod._board_tz_name() == "UTC"
    assert mod._commence_date_board("2026-09-26T00:00:00Z") == "2026-09-26"


def test_an_unparseable_commence_time_is_none_not_a_guess():
    assert mod._commence_date_board("not-a-time") is None
    assert mod._commence_date_board(None) is None


# --------------------------------------------------- the run-date half

def test_rows_are_sharded_by_game_date_not_the_run_date(captured):
    """The +/-8h window sweeps two slates; they must not land in one shard."""
    frame = pd.DataFrame([
        _row("2026-09-25T00:00:00Z", away="Bruins", home="Flyers"),      # 7pm CDT 09-24
        _row("2026-09-26T00:00:00Z", away="Bruins", home="Capitals"),    # 7pm CDT 09-25
    ])
    mod._append_nhl_book_quotes(frame, date="2026-09-25", kind="game")
    assert sorted(captured) == [("2026-09-24", 1), ("2026-09-25", 1)]


def test_the_previous_evenings_games_never_land_in_todays_shard(captured):
    """Exactly the production failure: 18 rows of yesterday filed as today."""
    frame = pd.DataFrame([_row("2026-09-25T00:00:00Z") for _ in range(18)])
    mod._append_nhl_book_quotes(frame, date="2026-09-25", kind="game")
    dates = {d for d, _ in captured}
    assert dates == {"2026-09-24"}, captured
    assert "2026-09-25" not in dates


def test_a_row_without_a_commence_time_falls_back_and_is_counted(captured, capsys):
    """Fallback is allowed; silence is not."""
    # A dated row on the PREVIOUS slate plus an undated one, so the fallback is
    # visible instead of being absorbed into the same bucket.
    frame = pd.DataFrame([_row("2026-09-25T00:00:00Z"), _row("")])
    dist = mod._append_nhl_book_quotes(frame, date="2026-09-25", kind="game")
    assert dist["undated"] == 1
    assert dist["by_game_date"] == {"2026-09-24": 1, "2026-09-25": 1}


def test_the_distribution_is_RETURNED_not_only_printed(captured):
    """A print cannot verify a deploy here, and that is not a style preference.

    `refresh_odds_sources._run_command` runs producers under
    `subprocess.run(capture_output=True)` and DISCARDS a successful step's
    stdout. A deploy was gated on the printed line on 2026-09-25 and the gate
    could not fire -- 298 odds-refresh control lines since boot, 0 of these.
    The RETURN VALUE is what the caller writes to a published artifact.
    """
    frame = pd.DataFrame([_row("2026-09-26T00:00:00Z")])
    dist = mod._append_nhl_book_quotes(frame, date="2026-09-25", kind="game")
    assert dist["by_game_date"] == {"2026-09-25": 1}
    assert dist["tz"] == "America/Chicago"
    assert dist["run_date"] == "2026-09-25"


def test_the_shard_report_is_written_where_the_publisher_sweeps(tmp_path):
    """And the path must be ALLOWLISTED, or it is another silent instrument."""
    import fnmatch

    from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS

    dist = {"kind": "game", "run_date": "2026-09-25",
            "by_game_date": {"2026-09-25": 4}, "undated": 0, "tz": "America/Chicago"}
    written = mod._write_quote_shard_report(
        artifact_root=tmp_path, date="2026-09-25", distribution=dist
    )
    assert written is not None
    rel = str(Path(written).relative_to(tmp_path)).replace("\\", "/")
    assert rel == "data/odds/quote_shards/2026-09-25.json"

    published = f"nhl_source/{rel}"
    assert any(fnmatch.fnmatch(published, pat) for pat in HOT_ARTIFACT_PATTERNS), (
        f"{published} is not allowlisted -- it would never reach production"
    )


def test_a_failed_append_still_returns_a_reading():
    """"The append blew up" must not read as "nothing was captured"."""
    import syndicate.features.shared.odds_book_quotes as obq

    original = obq.append_book_quotes
    try:
        def _boom(**_kw):
            raise RuntimeError("redis down")

        obq.append_book_quotes = _boom
        frame = pd.DataFrame([_row("2026-09-26T00:00:00Z")])
        dist = mod._append_nhl_book_quotes(frame, date="2026-09-25", kind="game")
    finally:
        obq.append_book_quotes = original
    assert "error" in dist and "RuntimeError" in dist["error"]
    assert dist["by_game_date"] == {}
