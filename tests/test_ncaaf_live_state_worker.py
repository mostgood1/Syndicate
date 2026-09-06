"""NCAAF live state: web READS the worker's record instead of fetching ESPN.

The point of these tests is not that the happy path works. It is that **every
degenerate record shape still falls back to fetching**, because the failure
this change could introduce is far worse than the one it fixes: an empty index
means STATE UNKNOWN (`live_game_state`'s own docstring), and a live Saturday
slate rendered as pregame is a visibly broken board, whereas the fetch it
replaces merely costs bytes.

So the ordering is deliberate: prove the fetch is REMOVED on the happy path
first (otherwise the change is inert and the tests below prove nothing), then
prove it RETURNS for absent / stale / unkeyed / unreadable records.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from syndicate.features.ncaaf import live_game_state as lgs


FRESH_RECORD = {
    "date": "2026-09-06",
    "fetched_at": time.time(),
    "count": 2,
    "games": [
        {
            "away_id": "153", "home_id": "2628",
            "away_team": "Team A", "home_team": "Team B",
            "away_score": 14, "home_score": 21,
            "in_progress": True, "final": False,
            "period": 3, "clock": "07:12",
        },
        {
            "away_id": "99", "home_id": "100",
            "away_team": "Team C", "home_team": "Team D",
            "in_progress": False, "final": True,
        },
    ],
}


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    """The module keeps a wall-clock TTL cache; a leak across tests would make
    a later test read an earlier test's record. Same reasoning as conftest's
    WNBA cache fixture."""
    monkeypatch.delenv("SYNDICATE_NCAAF_LIVE_STATE_MAX_AGE_SECONDS", raising=False)
    with lgs._cache_lock:
        lgs._cache.clear()
    yield
    with lgs._cache_lock:
        lgs._cache.clear()


def _patch(monkeypatch, *, record: Any, fetch_rows: list[dict] | None = None) -> dict[str, int]:
    """Stub the store read and the ESPN fetch; count the fetches."""
    calls = {"fetch": 0}

    def fake_read(_path):
        if isinstance(record, Exception):
            raise record
        return record

    def fake_rows(iso_date):
        calls["fetch"] += 1
        return list(fetch_rows or [])

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", fake_read, raising=False
    )
    monkeypatch.setattr(lgs, "_state_rows_for_date", fake_rows)
    return calls


def test_a_fresh_worker_record_is_used_and_NO_espn_fetch_happens(monkeypatch):
    """REACHABILITY FIRST. If this fails the change is inert and every test
    below is passing for the wrong reason."""
    calls = _patch(monkeypatch, record=FRESH_RECORD)

    index = lgs.ncaaf_game_state_index(["2026-09-06"])

    assert calls["fetch"] == 0, "web must not fetch ESPN when a fresh record exists"
    assert "153@2628" in index
    assert index["153@2628"]["period"] == 3
    assert index["153@2628"]["clock"] == "07:12"
    assert index["153@2628"]["in_progress"] is True
    assert "99@100" in index


def test_a_missing_record_falls_back_to_fetching(monkeypatch):
    """This is what makes the change safe to land before the producer exists."""
    calls = _patch(monkeypatch, record=None,
                   fetch_rows=[{"away_id": "1", "home_id": "2", "in_progress": True}])

    index = lgs.ncaaf_game_state_index(["2026-09-06"])

    assert calls["fetch"] == 1
    assert "1@2" in index


def test_a_stale_record_falls_back_rather_than_pinning_dead_scores(monkeypatch):
    """A stale record is worse than a fetch: it renders confidently wrong."""
    stale = {**FRESH_RECORD, "fetched_at": time.time() - 10_000}
    calls = _patch(monkeypatch, record=stale,
                   fetch_rows=[{"away_id": "1", "home_id": "2", "in_progress": True}])

    index = lgs.ncaaf_game_state_index(["2026-09-06"])

    assert calls["fetch"] == 1, "a stale record must not be used"
    assert "153@2628" not in index


def test_a_record_with_no_timestamp_cannot_be_aged_so_is_refused(monkeypatch):
    """Written by a producer predating `fetched_at`. Unageable == untrustable."""
    no_stamp = {k: v for k, v in FRESH_RECORD.items() if k != "fetched_at"}
    calls = _patch(monkeypatch, record=no_stamp, fetch_rows=[])

    lgs.ncaaf_game_state_index(["2026-09-06"])

    assert calls["fetch"] == 1


def test_a_fresh_but_UNKEYED_record_falls_back_and_says_so(monkeypatch, capfd):
    """DEPLOY SKEW: producer running an older build with no home_id/away_id.

    The record is present and fresh, so a naive reader would return `{}` and
    the board would render a live slate as pregame. `{}` is a positive claim
    ('no games keyed'); this must be a refusal instead.
    """
    unkeyed = {
        "date": "2026-09-06", "fetched_at": time.time(),
        "games": [{"home_team": "B", "away_team": "A", "in_progress": True}],
    }
    calls = _patch(monkeypatch, record=unkeyed,
                   fetch_rows=[{"away_id": "1", "home_id": "2", "in_progress": True}])

    index = lgs.ncaaf_game_state_index(["2026-09-06"])

    assert calls["fetch"] == 1
    assert "1@2" in index
    assert "NCAAF_LIVE_STATE_RECORD_UNKEYED" in capfd.readouterr().out


def test_an_unreadable_store_falls_back_and_is_named(monkeypatch, capfd):
    """A Redis hiccup must degrade to a fetch, not to an empty board."""
    calls = _patch(monkeypatch, record=RuntimeError("redis down"),
                   fetch_rows=[{"away_id": "1", "home_id": "2", "in_progress": True}])

    index = lgs.ncaaf_game_state_index(["2026-09-06"])

    assert calls["fetch"] == 1
    assert "1@2" in index
    assert "NCAAF_LIVE_STATE_RECORD_READ_FAILED" in capfd.readouterr().out


def test_max_age_is_configurable_and_absent_means_240(monkeypatch):
    assert lgs._worker_record_max_age_seconds() == 240.0
    monkeypatch.setenv("SYNDICATE_NCAAF_LIVE_STATE_MAX_AGE_SECONDS", "30")
    assert lgs._worker_record_max_age_seconds() == 30.0
    monkeypatch.setenv("SYNDICATE_NCAAF_LIVE_STATE_MAX_AGE_SECONDS", "nonsense")
    assert lgs._worker_record_max_age_seconds() == 240.0


def test_producer_persists_the_board_fields_the_reader_needs():
    """END TO END on the SHAPE: what the producer writes is what the reader keys on.

    These two live in different files and are only correct together, which is
    exactly the seam a shape change would silently break.
    """
    from scripts.poll_ncaaf_live_state import _board_fields_from_event

    event = {
        "id": "401",
        "status": {"period": 2, "displayClock": "13:45", "type": {"description": "In Progress"}},
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "team": {"id": "2628", "displayName": "Team B", "abbreviation": "TB"}, "score": "21"},
                {"homeAway": "away", "team": {"id": "153", "displayName": "Team A", "abbreviation": "TA"}, "score": "14"},
            ]
        }],
    }
    fields = _board_fields_from_event(event)

    assert fields["home_id"] == "2628"
    assert fields["away_id"] == "153"
    assert fields["period"] == 2
    assert fields["clock"] == "13:45"
    # The reader's key is built from exactly these two.
    assert f"{fields['away_id']}@{fields['home_id']}" == "153@2628"


def test_board_fields_are_absent_not_fabricated_on_a_thin_event():
    """Never invent a key. A missing id must leave the game unkeyed so the
    reader refuses the record rather than joining on a made-up pair."""
    from scripts.poll_ncaaf_live_state import _board_fields_from_event

    fields = _board_fields_from_event({"competitions": [{"competitors": []}], "status": {}})
    assert "home_id" not in fields and "away_id" not in fields
    assert "period" not in fields and "clock" not in fields


def test_sources_out_param_names_the_path_that_served(monkeypatch):
    """A WORKING FALLBACK AND A WORKING FEATURE LOOK IDENTICAL WITHOUT THIS.

    The board's coverage counters (`matched`/`live`/`final`) are the same
    whether the worker produced the state or web fetched it. `sources` is the
    only thing that distinguishes "the producer is running" from "web quietly
    went back to fetching", which is the regression this change exists to
    prevent and would otherwise be invisible.
    """
    calls = _patch(monkeypatch, record=FRESH_RECORD)
    sources: dict[str, str] = {}
    lgs.ncaaf_game_state_index(["2026-09-06"], sources=sources)
    assert sources == {"2026-09-06": "worker"}
    assert calls["fetch"] == 0

    with lgs._cache_lock:
        lgs._cache.clear()
    calls = _patch(monkeypatch, record=None,
                   fetch_rows=[{"away_id": "1", "home_id": "2", "in_progress": True}])
    sources = {}
    lgs.ncaaf_game_state_index(["2026-09-06"], sources=sources)
    assert sources == {"2026-09-06": "fetch"}, "a fallback must be nameable, not silent"
    assert calls["fetch"] == 1


def test_sources_is_optional_so_existing_callers_are_unaffected(monkeypatch):
    """The signature change must not break any caller that does not care."""
    _patch(monkeypatch, record=FRESH_RECORD)
    index = lgs.ncaaf_game_state_index(["2026-09-06"])
    assert "153@2628" in index


def test_the_worker_producer_step_exists_and_runs_first_and_ungated():
    """The reader is INERT without this step, so its absence is the whole risk.

    Asserts three separate things, each of which has bitten this repo before:
      - the step EXISTS (otherwise web silently keeps fetching forever)
      - it runs FIRST, because `refresh_odds_sources`'s own soccer block records
        that a cheap step queued behind expensive ones goes stale exactly when
        games are running
      - it is in BOTH phases and carries no extra gate -- that file's `#520`
        note records that re-applying an upstream gate at the launch site is
        how NFL lost 24 hours of capture
    """
    import argparse
    from scripts import refresh_odds_sources as ros

    steps = ros._build_ncaaf_steps(
        argparse.Namespace(date="2026-09-06", season=None, week=None)
    )
    names = [s.name for s in steps]
    assert "ncaaf_live_state" in names, "the producer step is missing; the reader is inert without it"

    step = steps[names.index("ncaaf_live_state")]
    assert names[0] == "ncaaf_live_state", f"must run first, got order {names}"
    assert set(step.phases) == {"pregame", "live"}
    command = [str(part) for part in step.command]
    assert any("poll_ncaaf_live_state.py" in part for part in command)
    assert "--date" in command and "2026-09-06" in command


def test_producer_covers_exactly_the_readers_date_set():
    """THE PRODUCER MUST COVER THE READER'S DATES OR IT ONLY PARTLY WORKS.

    The board asks for every past-or-current kickoff date in the week, and an
    NCAAF week is not a calendar window (2026 week 1 spans 08-29..09-07).
    Measured in production before this was fixed: the board requested SIX dates
    (`source=fetch=6`). A `--date`-only producer covers one of six and leaves
    web fetching the rest -- while looking correct to any check that only reads
    today, which is precisely how this nearly shipped.
    """
    from scripts.poll_ncaaf_live_state import week_state_dates
    from syndicate.features.ncaaf.cards import _ncaaf_week_kickoff_dates

    reader = set(lgs.past_or_current_dates(_ncaaf_week_kickoff_dates(2026, 1)))
    if not reader:
        pytest.skip("no schedule available in this checkout")
    assert set(week_state_dates(2026, 1)) == reader


def test_week_dates_failure_degrades_to_the_single_date(monkeypatch):
    """A schedule read that fails must not stop the producer polling today."""
    import scripts.poll_ncaaf_live_state as poller

    monkeypatch.setattr(
        "syndicate.features.ncaaf.cards._ncaaf_week_kickoff_dates",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("schedule gone")),
    )
    assert poller.week_state_dates(2026, 1) == ()


def test_the_step_passes_season_and_week_so_coverage_is_not_one_date():
    import argparse
    from scripts import refresh_odds_sources as ros

    step = ros._build_ncaaf_steps(
        argparse.Namespace(date="2026-09-06", season=2026, week=1)
    )[0]
    command = [str(c) for c in step.command]
    assert "--season" in command and "--week" in command, (
        "without these the producer covers ONE date and web keeps fetching the rest"
    )
