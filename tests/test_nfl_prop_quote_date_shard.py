"""NFL prop quotes must land in the shard the BOARD asks for.

THE DEFECT, diagnosed on production 2026-09-09 with counts either side of the
boundary. `fetch_nfl_oddsapi_props_local._append_nfl_book_quotes` wrote every
prop quote under `date_str=f"{season}_wk{week}"` -- one 48.4 MB
`nfl_source/tracking/book_quotes/2026_wk1.jsonl` holding 16,119 live keys across
16 events, 8 books and 9 markets, freshest seven minutes old. Capture was, and
is, healthy.

Nothing in the app has ever read a week key. Every board reader asks for
CALENDAR dates: `layer1_board.resolve_window_dates` emits `YYYY-MM-DD` and can
emit nothing else, `layer2_shortlist` loops those dates, and
`book_grid_artifact` is built one file per date. The only week-key reader in the
repo is the OFFLINE `scripts/report_nfl_props_roi.py`. So
`/api/board/book-grid?sport=nfl` served `market_kinds={h2h, spreads, totals}` --
**0 props of 1,219 rows** -- while MLB served 1,926 prop rows on the same
instant. No day had ever had an NFL prop on that board.

WHY THESE TESTS ASSERT AGAINST `resolve_window_dates` AND NOT A LITERAL. The
failure mode being fixed is "written to a key nobody asks for", and a test that
hand-writes the expected key reproduces exactly that mistake in the assertion.
Every path test here derives the expectation from the reader.
"""

from __future__ import annotations

import json

import pytest

from scripts import fetch_nfl_oddsapi_props_local as nfl_props_fetch
from syndicate.features.shared import odds_book_quotes
from syndicate.features.shared.layer1_board import resolve_window_dates


#: The real production fixture, and the whole reason the timezone question is
#: not academic. `NE @ SEA` commences 2026-09-10T00:20:00Z; the board renders it
#: `7:20P CT` on the NINTH. A UTC-derived shard key files it under the 10th and a
#: reader asking for the 9th finds nothing -- which is indistinguishable, from
#: the board, from the week-key bug this change removes.
_CROSSES_UTC_MIDNIGHT = "2026-09-10T00:20:00Z"
_ITS_CENTRAL_DATE = "2026-09-09"
_ITS_UTC_DATE = "2026-09-10"

#: A second event that does NOT cross, so the tests can tell "everything lands
#: on one date" from "the rule actually splits by kickoff".
_SUNDAY_AFTERNOON = "2026-09-13T17:00:00Z"
_SUNDAY_CENTRAL_DATE = "2026-09-13"


def _event(event_id: str, commence_time: str, *, player: str) -> dict:
    """One OddsAPI player-prop event in the real response shape, two books."""
    return {
        "id": event_id,
        "sport_key": "americanfootball_nfl",
        "commence_time": commence_time,
        "home_team": "Seattle Seahawks",
        "away_team": "New England Patriots",
        "bookmakers": [
            {
                "key": book,
                "markets": [
                    {
                        "key": "player_pass_yds",
                        "outcomes": [
                            {"name": "Over", "description": player, "price": -114, "point": 245.5},
                            {"name": "Under", "description": player, "price": -106, "point": 245.5},
                        ],
                    },
                    {
                        "key": "player_anytime_td",
                        "outcomes": [
                            {"name": "Yes", "description": player, "price": 320},
                        ],
                    },
                ],
            }
            for book in ("draftkings", "fanduel")
        ],
    }


@pytest.fixture
def captured(monkeypatch):
    """Intercept every append, recording (date_str, rows) in call order."""
    calls: list[dict] = []

    def _fake_append(*, sport, date_str, rows, captured_at, publish=True, extra=None):
        materialized = [dict(row) for row in rows]
        calls.append(
            {
                "sport": sport,
                "date_str": date_str,
                "rows": materialized,
                "captured_at": captured_at,
            }
        )
        return {"appended": len(materialized), "considered": len(materialized)}

    monkeypatch.setattr(
        "syndicate.features.shared.odds_book_quotes.append_book_quotes",
        _fake_append,
    )
    return calls


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv(nfl_props_fetch._NFL_PROP_DATE_SHARD_ENV, raising=False)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv(nfl_props_fetch._NFL_PROP_DATE_SHARD_ENV, "1")


def _events() -> list[dict]:
    return [
        _event("evt_thursday", _CROSSES_UTC_MIDNIGHT, player="Sam Darnold"),
        _event("evt_sunday", _SUNDAY_AFTERNOON, player="Drake Maye"),
    ]


# --------------------------------------------------------------------------
# REACHABILITY FIRST: off must differ from on, and off must be today's paths.
# --------------------------------------------------------------------------


def test_flag_absent_writes_the_week_shard_and_nothing_else(captured, flag_off):
    """Absent = today's behaviour, byte-identically. The whole safety argument."""
    nfl_props_fetch._append_nfl_book_quotes(_events(), season=2026, week=1)

    assert [call["date_str"] for call in captured] == ["2026_wk1"]


def test_flag_on_adds_date_shards_and_keeps_the_week_shard(captured, flag_on):
    """`off != on`, and the difference is ADDITIVE. Reachability before correctness."""
    nfl_props_fetch._append_nfl_book_quotes(_events(), season=2026, week=1)

    written = [call["date_str"] for call in captured]
    assert written[0] == "2026_wk1", "the week shard must still be written FIRST"
    assert sorted(written[1:]) == [_ITS_CENTRAL_DATE, _SUNDAY_CENTRAL_DATE]


def test_the_flag_only_accepts_explicit_truthy_values(monkeypatch):
    """A typo'd value must read as OFF, never as ON. Unknown is not permissive."""
    for value in ("", "0", "false", "no", "off", "maybe", "  "):
        monkeypatch.setenv(nfl_props_fetch._NFL_PROP_DATE_SHARD_ENV, value)
        assert nfl_props_fetch._nfl_prop_date_shard_enabled() is False, value
    for value in ("1", "true", "TRUE", "yes", "on", " On "):
        monkeypatch.setenv(nfl_props_fetch._NFL_PROP_DATE_SHARD_ENV, value)
        assert nfl_props_fetch._nfl_prop_date_shard_enabled() is True, value


def test_the_week_shard_content_is_identical_with_the_flag_either_way(
    captured, monkeypatch
):
    """Turning the flag on must not perturb the shard the offline reader reads."""
    monkeypatch.delenv(nfl_props_fetch._NFL_PROP_DATE_SHARD_ENV, raising=False)
    nfl_props_fetch._append_nfl_book_quotes(_events(), season=2026, week=1)
    off_rows = captured[0]["rows"]

    captured.clear()
    monkeypatch.setenv(nfl_props_fetch._NFL_PROP_DATE_SHARD_ENV, "1")
    nfl_props_fetch._append_nfl_book_quotes(_events(), season=2026, week=1)
    on_rows = captured[0]["rows"]

    assert captured[0]["date_str"] == "2026_wk1"
    # `captured_at` is a wall clock and legitimately differs between the two
    # runs; everything that identifies a quote must not.
    strip = lambda rows: [  # noqa: E731
        {k: v for k, v in row.items() if k not in {"captured_at", "snapshot_ts"}}
        for row in rows
    ]
    assert strip(on_rows) == strip(off_rows)


# --------------------------------------------------------------------------
# THE DATE RULE: Central kickoff day, asserted against the reader.
# --------------------------------------------------------------------------


def test_a_game_crossing_utc_midnight_lands_in_the_shard_the_board_asks_for(
    captured, flag_on
):
    """The production trap, pinned. Assert against `resolve_window_dates`, never a literal."""
    nfl_props_fetch._append_nfl_book_quotes(
        [_event("evt_thursday", _CROSSES_UTC_MIDNIGHT, player="Sam Darnold")],
        season=2026,
        week=1,
    )

    date_shards = {call["date_str"] for call in captured} - {"2026_wk1"}
    assert len(date_shards) == 1
    shard = next(iter(date_shards))

    # THE READER decides what is correct. Anchored on the Central day the board
    # itself calls this game's day.
    window = resolve_window_dates("nfl", _ITS_CENTRAL_DATE, window="slate")
    assert shard in window, (
        f"prop quotes written to {shard!r}, which is not in the board window "
        f"{window} -- this is the defect, moved rather than fixed"
    )
    # And specifically the FIRST day of that window: a `window=day` reader (which
    # is what `/api/board/book-grid?date=` is) asks for exactly one date.
    assert shard == resolve_window_dates("nfl", _ITS_CENTRAL_DATE, window="day")[0]
    assert shard != _ITS_UTC_DATE, "a UTC-derived key is off by one for every 7pm CT kickoff"


def test_rows_are_split_by_kickoff_not_all_dropped_on_one_date(captured, flag_on):
    """Two kickoffs three days apart must not share a shard."""
    nfl_props_fetch._append_nfl_book_quotes(_events(), season=2026, week=1)

    by_date = {
        call["date_str"]: call["rows"] for call in captured if call["date_str"] != "2026_wk1"
    }
    assert set(by_date) == {_ITS_CENTRAL_DATE, _SUNDAY_CENTRAL_DATE}
    assert {row["event_id"] for row in by_date[_ITS_CENTRAL_DATE]} == {"evt_thursday"}
    assert {row["event_id"] for row in by_date[_SUNDAY_CENTRAL_DATE]} == {"evt_sunday"}


def test_every_date_row_also_reached_the_week_shard(captured, flag_on):
    """The two copies must agree -- no row may exist in one and not the other."""
    nfl_props_fetch._append_nfl_book_quotes(_events(), season=2026, week=1)

    week_rows = captured[0]["rows"]
    date_rows = [row for call in captured[1:] for row in call["rows"]]
    identity = lambda row: (  # noqa: E731
        row["event_id"], row["bookmaker"], row["market"], row["selection"],
        row["player_name"], row["line"],
    )
    assert sorted(map(identity, date_rows)) == sorted(map(identity, week_rows))


def test_one_clock_read_is_shared_by_both_writes(captured, flag_on):
    """Two `captured_at` values microseconds apart would double-count one observation."""
    nfl_props_fetch._append_nfl_book_quotes(_events(), season=2026, week=1)

    assert len({call["captured_at"] for call in captured}) == 1


# --------------------------------------------------------------------------
# The bucketing rule itself.
# --------------------------------------------------------------------------


def test_kickoff_shard_date_is_central_not_utc():
    assert odds_book_quotes.kickoff_shard_date({"commence_time": _CROSSES_UTC_MIDNIGHT}) == _ITS_CENTRAL_DATE
    assert odds_book_quotes.kickoff_shard_date({"commence_time": _SUNDAY_AFTERNOON}) == _SUNDAY_CENTRAL_DATE


def test_an_unknown_kickoff_is_reported_not_filed_under_today():
    """A row with no commence_time must NOT default onto today's shard.

    Filed under today it is indistinguishable from a game that really kicks off
    today, and it would put a phantom row on the board. Unfiled and counted is
    the honest branch -- and the row still reaches the week shard, so nothing is
    lost.
    """
    rows = [
        {"commence_time": _CROSSES_UTC_MIDNIGHT, "event_id": "a"},
        {"commence_time": None, "event_id": "b"},
        {"commence_time": "not a timestamp", "event_id": "c"},
        {"event_id": "d"},
    ]
    buckets, unfiled = odds_book_quotes.bucket_quote_rows_by_kickoff_date(rows)

    assert set(buckets) == {_ITS_CENTRAL_DATE}
    assert [row["event_id"] for row in unfiled] == ["b", "c", "d"]


def test_a_row_with_no_kickoff_never_reaches_a_date_shard(captured, flag_on, monkeypatch):
    """End to end: the fetcher must not invent a date for an undated event."""
    event = _event("evt_undated", _CROSSES_UTC_MIDNIGHT, player="Sam Darnold")
    event.pop("commence_time")

    nfl_props_fetch._append_nfl_book_quotes([event], season=2026, week=1)

    assert [call["date_str"] for call in captured] == ["2026_wk1"], (
        "an undated event produced a date shard -- it was filed under a guessed day"
    )


# --------------------------------------------------------------------------
# The offline reader must survive. Real files, not a monkeypatch.
# --------------------------------------------------------------------------


def test_the_offline_roi_reader_still_finds_its_week_shard(tmp_path, monkeypatch):
    """`scripts/report_nfl_props_roi.py` reads `{season}_wk{week}.jsonl` directly.

    It is the only thing in this repo that turns an NFL prop prediction into a
    P&L. Dropping the week key would orphan it for the live season while its
    2023-2025 backfill stayed readable -- a half-broken tool. This asserts the
    dual write keeps it whole, against real bytes on disk.
    """
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv(nfl_props_fetch._NFL_PROP_DATE_SHARD_ENV, "1")
    # The publish sweep is a cross-service side effect; this test is about files.
    monkeypatch.setattr(
        "syndicate.features.shared.artifact_publisher.publish_hot_artifact",
        lambda path: None,
    )

    nfl_props_fetch._append_nfl_book_quotes(_events(), season=2026, week=1)

    quotes_dir = tmp_path / "nfl_source" / "tracking" / "book_quotes"
    written = sorted(p.name for p in quotes_dir.glob("*.jsonl"))
    assert written == sorted(
        [f"{_ITS_CENTRAL_DATE}.jsonl", f"{_SUNDAY_CENTRAL_DATE}.jsonl", "2026_wk1.jsonl"]
    )

    from scripts import report_nfl_props_roi

    monkeypatch.setattr(
        report_nfl_props_roi,
        "default_nfl_source_root",
        lambda: tmp_path / "nfl_source",
    )
    assert report_nfl_props_roi.quote_path(2026, 1).is_file()
    roi_rows = report_nfl_props_roi.load_quotes(2026, 1)
    assert roi_rows, "the ROI reader found no prop rows -- the week shard was orphaned"
    assert {row["kind"] for row in roi_rows} == {"prop"}

    # And the date shards hold the same capture, split by Central kickoff.
    for shard_date, event_id in (
        (_ITS_CENTRAL_DATE, "evt_thursday"),
        (_SUNDAY_CENTRAL_DATE, "evt_sunday"),
    ):
        lines = (quotes_dir / f"{shard_date}.jsonl").read_text(encoding="utf-8").strip().splitlines()
        parsed = [json.loads(line) for line in lines]
        assert parsed, f"{shard_date} shard is empty"
        assert {row["event_id"] for row in parsed} == {event_id}
        # `date` is the shard key stamped onto the row, and readers group on it.
        assert {row["date"] for row in parsed} == {shard_date}


def test_flag_absent_writes_exactly_one_file_on_disk(tmp_path, monkeypatch):
    """The byte-level half of the reachability proof."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv(nfl_props_fetch._NFL_PROP_DATE_SHARD_ENV, raising=False)
    monkeypatch.setattr(
        "syndicate.features.shared.artifact_publisher.publish_hot_artifact",
        lambda path: None,
    )

    nfl_props_fetch._append_nfl_book_quotes(_events(), season=2026, week=1)

    quotes_dir = tmp_path / "nfl_source" / "tracking" / "book_quotes"
    assert sorted(p.name for p in quotes_dir.glob("*.jsonl")) == ["2026_wk1.jsonl"]
