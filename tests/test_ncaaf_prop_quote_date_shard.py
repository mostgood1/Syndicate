"""NCAAF prop quotes must land in the shard the BOARD asks for.

THE DEFECT, the identical one `2290d685` fixed for NFL, diagnosed on production
2026-09-09 with counts either side of the boundary.
`fetch_ncaaf_oddsapi_props_local._append_ncaaf_book_quotes` wrote every prop
quote under `date_str=f"{season}_wk{week}"` -- a 26.98 MB
`ncaaf_source/tracking/book_quotes/2026_wk1.jsonl` plus a 0.85 MB `2026_wk2`,
together holding 17,012 live prop quote keys across 76 events. Capture was, and
is, healthy.

Nothing in the app has ever read a week key. Every board reader asks for
CALENDAR dates: `layer1_board.resolve_window_dates` emits `YYYY-MM-DD` and can
emit nothing else, `layer2_shortlist` loops those dates, and
`book_grid_artifact` is built one file per date. So
`/api/board/book-grid?sport=ncaaf` served `market_kinds={h2h, spreads, totals}`
on every date in the window -- **0 props of 503 rows on 2026-09-12, 0 of 33 on
09-11, 0 of 66 on 09-13, 0 of 650 on the last Saturday played (09-05)** -- while
MLB served 1,796 prop rows and NFL (fixed hours earlier) 149 on the same
instant. No day had ever had an NCAAF prop on that board.

UNLIKE NFL, there is no offline week-key reader to protect: a repo-wide search
found no consumer of `ncaaf_source/tracking/book_quotes/*_wk*.jsonl` at all.
The week shard is kept anyway, written first and unchanged, so the two sports'
capture stays one shape.

WHY THESE TESTS ASSERT AGAINST `resolve_window_dates` AND NOT A LITERAL. The
failure mode being fixed is "written to a key nobody asks for", and a test that
hand-writes the expected key reproduces exactly that mistake in the assertion.
Every path test here derives the expectation from the reader.
"""

from __future__ import annotations

import json

import pytest

from scripts import fetch_ncaaf_oddsapi_props_local as ncaaf_props_fetch
from syndicate.features.shared import odds_book_quotes
from syndicate.features.shared.layer1_board import resolve_window_dates


#: The real production fixture, and the whole reason the timezone question is
#: not academic for THIS sport in particular. `MEM @ UNLV` commences
#: 2026-08-30T02:19:00Z, which is 9:19pm Central on the TWENTY-NINTH -- the game
#: `layer1_board.artifact_read_dates` documents Saturday's board already losing
#: to precisely this off-by-one. On a football Saturday the late window is the
#: marquee one, so a UTC-derived shard key mis-files the best games on the card.
_CROSSES_UTC_MIDNIGHT = "2026-08-30T02:19:00Z"
_ITS_CENTRAL_DATE = "2026-08-29"
_ITS_UTC_DATE = "2026-08-30"

#: A second event that does NOT cross, so the tests can tell "everything lands
#: on one date" from "the rule actually splits by kickoff". 16:00Z is 11:00 CT.
_SATURDAY_MORNING = "2026-09-12T16:00:00Z"
_SATURDAY_CENTRAL_DATE = "2026-09-12"


def _event(event_id: str, commence_time: str, *, player: str) -> dict:
    """One OddsAPI player-prop event in the real response shape, two books."""
    return {
        "id": event_id,
        "sport_key": "americanfootball_ncaaf",
        "commence_time": commence_time,
        "home_team": "UNLV Rebels",
        "away_team": "Memphis Tigers",
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
    monkeypatch.delenv(ncaaf_props_fetch._NCAAF_PROP_DATE_SHARD_ENV, raising=False)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv(ncaaf_props_fetch._NCAAF_PROP_DATE_SHARD_ENV, "1")


def _events() -> list[dict]:
    return [
        _event("evt_late_saturday", _CROSSES_UTC_MIDNIGHT, player="Seth Henigan"),
        _event("evt_early_saturday", _SATURDAY_MORNING, player="Ahmad Hardy"),
    ]


# --------------------------------------------------------------------------
# REACHABILITY FIRST: off must differ from on, and off must be today's paths.
# --------------------------------------------------------------------------


def test_flag_absent_writes_the_week_shard_and_nothing_else(captured, flag_off):
    """Absent = today's behaviour, byte-identically. The whole safety argument."""
    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)

    assert [call["date_str"] for call in captured] == ["2026_wk1"]


def test_flag_on_adds_date_shards_and_keeps_the_week_shard(captured, flag_on):
    """`off != on`, and the difference is ADDITIVE. Reachability before correctness."""
    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)

    written = [call["date_str"] for call in captured]
    assert written[0] == "2026_wk1", "the week shard must still be written FIRST"
    assert sorted(written[1:]) == sorted([_ITS_CENTRAL_DATE, _SATURDAY_CENTRAL_DATE])


def test_the_flag_only_accepts_explicit_truthy_values(monkeypatch):
    """A typo'd value must read as OFF, never as ON. Unknown is not permissive."""
    for value in ("", "0", "false", "no", "off", "maybe", "  "):
        monkeypatch.setenv(ncaaf_props_fetch._NCAAF_PROP_DATE_SHARD_ENV, value)
        assert ncaaf_props_fetch._ncaaf_prop_date_shard_enabled() is False, value
    for value in ("1", "true", "TRUE", "yes", "on", " On "):
        monkeypatch.setenv(ncaaf_props_fetch._NCAAF_PROP_DATE_SHARD_ENV, value)
        assert ncaaf_props_fetch._ncaaf_prop_date_shard_enabled() is True, value


def test_the_flag_is_independent_of_the_nfl_one(captured, monkeypatch):
    """Two sports, two switches. Turning NFL's on must not ship NCAAF's influx.

    The names are deliberately parallel (`SYNDICATE_<SPORT>_PROP_QUOTES_DATE_SHARD`)
    so an operator can find both; parallel names are only safe if they are also
    genuinely separate, and NCAAF is by far the larger slate of the two.
    """
    monkeypatch.delenv(ncaaf_props_fetch._NCAAF_PROP_DATE_SHARD_ENV, raising=False)
    monkeypatch.setenv("SYNDICATE_NFL_PROP_QUOTES_DATE_SHARD", "1")

    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)

    assert [call["date_str"] for call in captured] == ["2026_wk1"]


def test_the_week_shard_content_is_identical_with_the_flag_either_way(
    captured, monkeypatch
):
    """Turning the flag on must not perturb the shard that already exists."""
    monkeypatch.delenv(ncaaf_props_fetch._NCAAF_PROP_DATE_SHARD_ENV, raising=False)
    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)
    off_rows = captured[0]["rows"]

    captured.clear()
    monkeypatch.setenv(ncaaf_props_fetch._NCAAF_PROP_DATE_SHARD_ENV, "1")
    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)
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
    ncaaf_props_fetch._append_ncaaf_book_quotes(
        [_event("evt_late_saturday", _CROSSES_UTC_MIDNIGHT, player="Seth Henigan")],
        season=2026,
        week=1,
    )

    date_shards = {call["date_str"] for call in captured} - {"2026_wk1"}
    assert len(date_shards) == 1
    shard = next(iter(date_shards))

    # THE READER decides what is correct. Anchored on the Central day the board
    # itself calls this game's day.
    window = resolve_window_dates("ncaaf", _ITS_CENTRAL_DATE, window="slate")
    assert shard in window, (
        f"prop quotes written to {shard!r}, which is not in the board window "
        f"{window} -- this is the defect, moved rather than fixed"
    )
    # And specifically the FIRST day of that window: a `window=day` reader (which
    # is what `/api/board/book-grid?date=` is) asks for exactly one date.
    assert shard == resolve_window_dates("ncaaf", _ITS_CENTRAL_DATE, window="day")[0]
    assert shard != _ITS_UTC_DATE, "a UTC-derived key is off by one for every 7pm CT kickoff"


def test_the_shared_rule_is_used_rather_than_a_second_derivation(captured, flag_on):
    """The fetcher's shard keys must be exactly what `kickoff_shard_date` returns.

    Two date resolvers disagreeing is how the halves of a join end up on
    different vocabularies. This pins the fetcher to the shared rule so a future
    edit that inlines its own `commence_time[:10]` (soccer's convention, and
    WRONG for a Central-scoped board) fails here rather than on the board.
    """
    events = _events()
    ncaaf_props_fetch._append_ncaaf_book_quotes(events, season=2026, week=1)

    week_rows = captured[0]["rows"]
    expected = {odds_book_quotes.kickoff_shard_date(row) for row in week_rows}
    assert None not in expected
    assert {call["date_str"] for call in captured[1:]} == expected


def test_rows_are_split_by_kickoff_not_all_dropped_on_one_date(captured, flag_on):
    """Two kickoffs a fortnight apart must not share a shard."""
    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)

    by_date = {
        call["date_str"]: call["rows"] for call in captured if call["date_str"] != "2026_wk1"
    }
    assert set(by_date) == {_ITS_CENTRAL_DATE, _SATURDAY_CENTRAL_DATE}
    assert {row["event_id"] for row in by_date[_ITS_CENTRAL_DATE]} == {"evt_late_saturday"}
    assert {row["event_id"] for row in by_date[_SATURDAY_CENTRAL_DATE]} == {"evt_early_saturday"}


def test_every_date_row_also_reached_the_week_shard(captured, flag_on):
    """The two copies must agree -- no row may exist in one and not the other."""
    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)

    week_rows = captured[0]["rows"]
    date_rows = [row for call in captured[1:] for row in call["rows"]]
    identity = lambda row: (  # noqa: E731
        row["event_id"], row["bookmaker"], row["market"], row["selection"],
        row["player_name"], row["line"],
    )
    assert sorted(map(identity, date_rows)) == sorted(map(identity, week_rows))


def test_one_clock_read_is_shared_by_both_writes(captured, flag_on):
    """Two `captured_at` values microseconds apart would double-count one observation."""
    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)

    assert len({call["captured_at"] for call in captured}) == 1


# --------------------------------------------------------------------------
# Undated rows: reported, not misfiled.
# --------------------------------------------------------------------------


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


def test_a_row_with_no_kickoff_never_reaches_a_date_shard(captured, flag_on):
    """End to end: the fetcher must not invent a date for an undated event."""
    event = _event("evt_undated", _CROSSES_UTC_MIDNIGHT, player="Seth Henigan")
    event.pop("commence_time")

    ncaaf_props_fetch._append_ncaaf_book_quotes([event], season=2026, week=1)

    assert [call["date_str"] for call in captured] == ["2026_wk1"], (
        "an undated event produced a date shard -- it was filed under a guessed day"
    )


def test_an_undated_event_is_counted_in_the_report_line(capsys, captured, flag_on):
    """The unfiled count must be PRINTED, not swallowed.

    This writer can run as a sweep child with `stdout=DEVNULL`, so the line is
    not always visible in production -- which is exactly why it must at least
    exist and carry a denominator when it is.
    """
    dated = _event("evt_early_saturday", _SATURDAY_MORNING, player="Ahmad Hardy")
    undated = _event("evt_undated", _CROSSES_UTC_MIDNIGHT, player="Seth Henigan")
    undated.pop("commence_time")

    ncaaf_props_fetch._append_ncaaf_book_quotes([dated, undated], season=2026, week=1)

    line = capsys.readouterr().out
    assert "ncaaf prop date-shard" in line
    assert "unfiled_no_commence_time=" in line
    unfiled = int(line.split("unfiled_no_commence_time=")[1].split()[0])
    assert unfiled > 0, "an undated event was not reported as unfiled"
    total = int(line.split("rows=")[1].split()[0])
    assert 0 < unfiled < total, "the count needs its denominator to be readable"


# --------------------------------------------------------------------------
# Real files on disk, not a monkeypatch.
# --------------------------------------------------------------------------


def test_both_keys_hold_the_same_capture_on_disk(tmp_path, monkeypatch):
    """The dual write, against real bytes.

    No consumer of the NCAAF week key exists today (unlike NFL, whose
    `report_nfl_props_roi.py` reads it), but it is kept so the two sports' quote
    capture stays one shape -- and if it is kept it must stay whole.
    """
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv(ncaaf_props_fetch._NCAAF_PROP_DATE_SHARD_ENV, "1")
    # The publish sweep is a cross-service side effect; this test is about files.
    monkeypatch.setattr(
        "syndicate.features.shared.artifact_publisher.publish_hot_artifact",
        lambda path: None,
    )

    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)

    quotes_dir = tmp_path / "ncaaf_source" / "tracking" / "book_quotes"
    written = sorted(p.name for p in quotes_dir.glob("*.jsonl"))
    assert written == sorted(
        [f"{_ITS_CENTRAL_DATE}.jsonl", f"{_SATURDAY_CENTRAL_DATE}.jsonl", "2026_wk1.jsonl"]
    )

    def _parse(name: str) -> list[dict]:
        text = (quotes_dir / name).read_text(encoding="utf-8").strip()
        return [json.loads(line) for line in text.splitlines() if line]

    week_rows = _parse("2026_wk1.jsonl")
    assert week_rows
    assert {row["kind"] for row in week_rows} == {"prop"}
    assert all(row.get("player_name") for row in week_rows), (
        "a prop row is identified by `player_name`; without it the board "
        "classifies these as game rows"
    )

    identity = lambda row: (  # noqa: E731
        row["event_id"], row["bookmaker"], row["market"], row["selection"],
        row["player_name"], row["line"],
    )
    date_rows = _parse(f"{_ITS_CENTRAL_DATE}.jsonl") + _parse(f"{_SATURDAY_CENTRAL_DATE}.jsonl")
    assert sorted(map(identity, date_rows)) == sorted(map(identity, week_rows))

    # And the date shards hold the same capture, split by Central kickoff.
    for shard_date, event_id in (
        (_ITS_CENTRAL_DATE, "evt_late_saturday"),
        (_SATURDAY_CENTRAL_DATE, "evt_early_saturday"),
    ):
        parsed = _parse(f"{shard_date}.jsonl")
        assert parsed, f"{shard_date} shard is empty"
        assert {row["event_id"] for row in parsed} == {event_id}
        # `date` is the shard key stamped onto the row, and readers group on it.
        assert {row["date"] for row in parsed} == {shard_date}


def test_flag_absent_writes_exactly_one_file_on_disk(tmp_path, monkeypatch):
    """The byte-level half of the reachability proof."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv(ncaaf_props_fetch._NCAAF_PROP_DATE_SHARD_ENV, raising=False)
    monkeypatch.setattr(
        "syndicate.features.shared.artifact_publisher.publish_hot_artifact",
        lambda path: None,
    )

    ncaaf_props_fetch._append_ncaaf_book_quotes(_events(), season=2026, week=1)

    quotes_dir = tmp_path / "ncaaf_source" / "tracking" / "book_quotes"
    assert sorted(p.name for p in quotes_dir.glob("*.jsonl")) == ["2026_wk1.jsonl"]
