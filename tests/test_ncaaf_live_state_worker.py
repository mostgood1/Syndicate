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


def fresh_record() -> dict:
    """`FRESH_RECORD` with a timestamp taken NOW, not at import.

    IT USED TO BE A MODULE-LEVEL DICT with `"fetched_at": time.time()`, which is
    evaluated ONCE when the module is imported. `live_game_state` refuses a
    worker record older than `_worker_record_max_age_seconds()` (240 s) for a
    date that is still moving (`live_game_state.py:342`) -- correctly. A full
    suite runs 18-42 minutes and, under `--dist=loadscope`, a worker imports
    this module long before it reaches these tests, so the "fresh" record was
    routinely older than four minutes by the time it was used and the code fell
    back to fetching exactly as designed.

    MEASURED 2026-09-06: the three tests that used the constant unmodified were
    red in a full run, green alone, and red again after being fixed once
    (`34bcecc8`). Ageing the record 300 s reproduces precisely those three and
    nothing else.

    The two tests that OVERRIDE `fetched_at` on purpose -- the stale case and
    the missing-stamp case -- never failed, which is the tell: they were the
    only ones not depending on how long the suite had been running.
    """
    return {**_RECORD_SHAPE, "fetched_at": time.time()}


_RECORD_SHAPE = {
    "date": "2026-09-06",
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
    calls = _patch(monkeypatch, record=fresh_record())

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
    stale = {**fresh_record(), "fetched_at": time.time() - 10_000}
    calls = _patch(monkeypatch, record=stale,
                   fetch_rows=[{"away_id": "1", "home_id": "2", "in_progress": True}])

    index = lgs.ncaaf_game_state_index(["2026-09-06"])

    assert calls["fetch"] == 1, "a stale record must not be used"
    assert "153@2628" not in index


def test_a_record_with_no_timestamp_cannot_be_aged_so_is_refused(monkeypatch):
    """Written by a producer predating `fetched_at`. Unageable == untrustable."""
    no_stamp = {k: v for k, v in fresh_record().items() if k != "fetched_at"}
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
    calls = _patch(monkeypatch, record=fresh_record())
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
    _patch(monkeypatch, record=fresh_record())
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


def _in_progress_event():
    return {
        "id": "401",
        "status": {"period": 2, "displayClock": "13:45", "type": {"state": "in", "description": "In Progress"}},
        "competitions": [{
            "situation": {"down": 3, "distance": 7, "yardLine": 42, "possession": "2628"},
            "competitors": [
                {"homeAway": "home", "team": {"id": "2628", "location": "Washington",
                                              "displayName": "Washington Huskies", "abbreviation": "WASH"}, "score": "21"},
                {"homeAway": "away", "team": {"id": "153", "location": "Washington State",
                                              "displayName": "Washington State Cougars", "abbreviation": "WSU"}, "score": "14"},
            ],
        }],
    }


def test_location_is_persisted_and_is_NOT_the_display_name():
    """`location` and `displayName` are not interchangeable as a JOIN KEY.

    The projections artifact carries no ESPN id, only team names. Measured by
    lane ncaaf-live-resim-wire on the live 2026-09-05 slate: `team.location`
    matched 35 of 51 board games, `team.displayName` matched ZERO. Keying off
    displayName indexes nothing while looking perfectly healthy.
    """
    from scripts.poll_ncaaf_live_state import _board_fields_from_event

    fields = _board_fields_from_event(_in_progress_event())
    assert fields["home_location"] == "Washington"
    assert fields["away_location"] == "Washington State"
    assert "Huskies" not in fields["home_location"]


def test_situation_is_persisted_RAW_for_in_progress_and_absent_for_pregame():
    """Absent on pregame is CORRECT -- verified against live ESPN 2026-09-06.

    A consumer requiring `situation` of a pregame row would refuse a correct
    record forever.
    """
    from scripts.poll_ncaaf_live_state import _board_fields_from_event

    live = _board_fields_from_event(_in_progress_event())
    assert live["situation"]["down"] == 3
    assert live["situation"]["possession"] == "2628"

    pregame = _in_progress_event()
    pregame["competitions"][0].pop("situation")
    assert "situation" not in _board_fields_from_event(pregame)


def test_the_record_is_SUFFICIENT_to_resolve_possession_without_a_second_parser():
    """ESPN names the possessor BY ID, never by side.

    The record deliberately persists `situation` unresolved: resolving it here
    would make a SECOND parser of a field `live_resim.possession_side_from_espn`
    already owns, which is the drift `_game_from_event`'s docstring exists to
    prevent. This proves the record carries enough for that ONE resolver to be
    handed a synthetic competition and get the right answer.
    """
    from scripts.poll_ncaaf_live_state import _board_fields_from_event
    from syndicate.features.ncaaf.live_resim import possession_side_from_espn

    rec = _board_fields_from_event(_in_progress_event())
    side, raw = possession_side_from_espn(
        {"situation": rec["situation"]}, home_id=rec["home_id"], away_id=rec["away_id"]
    )
    assert side == "home", f"possession must resolve to a SIDE, got {side!r}"
    assert raw.get("down") == 3


def test_a_fresh_record_with_ZERO_games_is_ACCEPTED_not_refused(monkeypatch):
    """A date with no games is a COMPLETE answer, not a missing one.

    Measured in production 2026-09-06: `RECORD_UNKEYED date=2026-08-30 games=0`
    fired on every board build for a date ESPN genuinely has no events on. The
    reader refused it and fetched, and the fetch returned the same nothing --
    a pointless call per build, per date, forever, that looked exactly like the
    producer failing.
    """
    empty = {"date": "2026-08-30", "fetched_at": time.time(), "games": []}
    calls = _patch(monkeypatch, record=empty, fetch_rows=[])

    sources = {}
    index = lgs.ncaaf_game_state_index(["2026-08-30"], sources=sources)

    assert calls["fetch"] == 0, "an empty date must NOT trigger a fetch"
    assert index == {}
    assert sources == {"2026-08-30": "worker"}


def test_a_fresh_record_with_games_but_NO_ids_is_still_refused(monkeypatch, capfd):
    """The other half of the same branch: that one IS deploy skew."""
    unkeyed = {"date": "2026-09-06", "fetched_at": time.time(),
               "games": [{"home_team": "B", "away_team": "A", "in_progress": True}]}
    calls = _patch(monkeypatch, record=unkeyed,
                   fetch_rows=[{"away_id": "1", "home_id": "2", "in_progress": True}])

    lgs.ncaaf_game_state_index(["2026-09-06"])

    assert calls["fetch"] == 1
    assert "NCAAF_LIVE_STATE_RECORD_UNKEYED" in capfd.readouterr().out


def test_a_stale_record_is_ACCEPTED_when_every_game_is_final(monkeypatch):
    """A final score cannot change, so its record cannot go stale.

    Measured in production 2026-09-06: the producer runs once per full sweep,
    so records age 247-940s against a 240s bound, and the board was re-fetching
    ALL SIX dates every time -- including five whose games finished days ago.
    """
    old_final = {
        "date": "2026-09-03", "fetched_at": time.time() - 10_000,
        "games": [{"away_id": "1", "home_id": "2", "final": True, "in_progress": False},
                  {"away_id": "3", "home_id": "4", "final": True, "in_progress": False}],
    }
    calls = _patch(monkeypatch, record=old_final, fetch_rows=[])
    sources = {}
    index = lgs.ncaaf_game_state_index(["2026-09-03"], sources=sources)

    assert calls["fetch"] == 0, "a finished date must not be re-fetched at any age"
    assert set(index) == {"1@2", "3@4"}
    assert sources == {"2026-09-03": "worker"}


def test_a_stale_record_is_still_REFUSED_when_a_game_is_unfinished(monkeypatch):
    """The live date is exactly the one freshness is for."""
    stale_live = {
        "date": "2026-09-06", "fetched_at": time.time() - 10_000,
        "games": [{"away_id": "1", "home_id": "2", "final": True},
                  {"away_id": "3", "home_id": "4", "final": False, "in_progress": True}],
    }
    calls = _patch(monkeypatch, record=stale_live,
                   fetch_rows=[{"away_id": "9", "home_id": "9", "in_progress": True}])
    lgs.ncaaf_game_state_index(["2026-09-06"])
    assert calls["fetch"] == 1


def test_a_stale_PREGAME_date_is_refused_because_kickoff_can_happen(monkeypatch):
    """Pregame counts as moving: a game can start inside the staleness window,
    and a stale record would render a started game as pregame."""
    stale_pregame = {
        "date": "2026-09-06", "fetched_at": time.time() - 10_000,
        "games": [{"away_id": "1", "home_id": "2", "final": False, "in_progress": False}],
    }
    calls = _patch(monkeypatch, record=stale_pregame, fetch_rows=[])
    lgs.ncaaf_game_state_index(["2026-09-06"])
    assert calls["fetch"] == 1
