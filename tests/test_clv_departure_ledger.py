"""`clv_departure_ledger` (lane layer2-live-scorecard-gate, 2026-09-13).

The number this replaces came from one PC for one night: on the 09-12 NCAAF
board, 61% of live +EV prices served under 5 minutes old, and 75% of those
served 10+ minutes old, were gone 10 minutes later. These pin what makes the
worker's version of that number trustworthy: a market leaving the board is
recorded once, with the price it left at; a build that simply lacks a sport
fires nothing; a line that flickers back is a `return`; and the openings path
actually reaches the recorder, with the flag able to turn it off.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import clv_departure_ledger as mod
from syndicate.features.shared.clv_departure_ledger import (
    departure_ledger_path,
    departure_state_path,
    load_departures,
    market_identity,
    record_departures,
)

_DATE = "2026-09-12"
_T0 = datetime(2026, 9, 12, 23, 0, tzinfo=timezone.utc)


def _at(minutes: int) -> datetime:
    return _T0 + timedelta(minutes=minutes)


def _stamp(minutes: int) -> str:
    return _at(minutes).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(**over):
    # 2026-09-12 WF @ PUR, the row that opened the lane.
    row = {
        "sport": "ncaaf",
        "event_id": "5a8d98c3",
        "market": "spreads",
        "segment": "full",
        "side": "away",
        "line": -6.5,
        "player_name": None,
        "ev_pct": 4.75,
        "game_state": "live",
        "quote": {"price": 107, "bookmaker": "prophetx"},
    }
    quote = over.pop("quote", None)
    row.update(over)
    if quote:
        row["quote"] = {**row["quote"], **quote}
    return row


def _other(**over):
    return _row(event_id="other-game", **over)


def _build(rows, minutes, root):
    return record_departures(rows, date=_DATE, now=_at(minutes), root=root)


def _moves(root, kind=None):
    records = [r for r in load_departures(_DATE, root=root) if r["type"] != "build"]
    return [r for r in records if kind is None or r["type"] == kind]


@pytest.fixture(autouse=True)
def publishes(monkeypatch):
    import syndicate.features.shared.artifact_publisher as pub

    calls = []
    monkeypatch.setattr(pub, "publish_hot_artifact", lambda path: calls.append(path) or True)
    return calls


def test_identity_is_the_market_not_the_book_and_reads_opening_records_too():
    assert market_identity(_row()) == market_identity(_row(quote={"bookmaker": "draftkings", "price": -111}))
    assert market_identity(_row()) != market_identity(_row(line=-7.0))
    assert market_identity(_row()) != market_identity(_row(segment="h1"))
    # An opening record is flat (no `quote`) and keeps `segment` as the row had it.
    record = {"sport": "NCAAF", "event_id": "5a8d98c3", "market": "spreads", "segment": "FULL",
              "side": "away", "line": -6.5, "player_name": None, "bookmaker": "prophetx"}
    assert market_identity(record) == market_identity(_row())
    assert market_identity(_row(event_id="")) is None


def test_a_first_build_records_a_heartbeat_and_no_departure(tmp_path, publishes):
    report = _build([_row()], 0, tmp_path)
    assert (report["departed"], report["tracked"], report["published"]) == (0, 1, None)
    assert load_departures(_DATE, root=tmp_path) == [{"type": "build", "at": _stamp(0), "sports": {"ncaaf": 1}}]
    assert publishes == [], "a heartbeat-only build pushed the file"


def test_a_market_that_leaves_is_recorded_once_with_the_price_it_left_at(tmp_path, publishes):
    _build([_row()], 0, tmp_path)
    _build([_row(quote={"price": -105})], 7, tmp_path)  # still up, repriced
    report = _build([_row(line=-7.5)], 14, tmp_path)  # the -6.5 line is gone
    _build([_row(line=-7.5)], 21, tmp_path)

    assert report["departed"] == 1
    (gone,) = _moves(tmp_path)
    assert gone["identity"] == market_identity(_row())
    assert (gone["last_seen_at"], gone["gone_by"], gone["first_ev_at"]) == (_stamp(7), _stamp(14), _stamp(0))
    assert (gone["last_price"], gone["last_bookmaker"], gone["line"]) == (-105, "prophetx", -6.5)
    assert len(publishes) == 1, "only the build where something left should push"


def test_a_market_that_was_positive_once_is_still_tracked_after_its_ev_drops(tmp_path):
    _build([_row()], 0, tmp_path)
    _build([_row(ev_pct=-1.0)], 7, tmp_path)
    _build([_other()], 14, tmp_path)
    (gone,) = _moves(tmp_path)
    assert (gone["last_ev_pct"], gone["first_ev_at"]) == (-1.0, _stamp(0))


def test_a_market_never_positive_is_not_tracked(tmp_path):
    assert _build([_row(ev_pct=-2.0)], 0, tmp_path)["tracked"] == 0
    _build([_other()], 7, tmp_path)
    assert _moves(tmp_path) == []


def test_a_sport_missing_from_a_build_fires_nothing_until_it_is_back(tmp_path):
    mlb = _row(sport="mlb", event_id="mlb-1", market="h2h", side="home", line=None)
    _build([_row(), mlb], 0, tmp_path)
    assert _build([mlb], 7, tmp_path)["departed"] == 0, "a build without NCAAF rows emptied the NCAAF board"
    _build([_other(), mlb], 14, tmp_path)
    (gone,) = _moves(tmp_path)
    assert (gone["sport"], gone["last_seen_at"], gone["gone_by"]) == ("ncaaf", _stamp(0), _stamp(14))


def test_an_empty_build_writes_nothing(tmp_path):
    report = _build([], 0, tmp_path)
    assert report["sports"] == 0
    assert not departure_ledger_path(_DATE, root=tmp_path).exists()
    assert not departure_state_path(_DATE, root=tmp_path).exists()


def test_a_market_that_comes_back_is_a_return_and_can_leave_again(tmp_path):
    _build([_row()], 0, tmp_path)
    _build([_other()], 7, tmp_path)
    report = _build([_row(), _other()], 14, tmp_path)
    _build([_other()], 21, tmp_path)

    assert report["returned"] == 1
    (back,) = _moves(tmp_path, "return")
    assert (back["gone_by"], back["back_at"]) == (_stamp(7), _stamp(14))
    assert [r["gone_by"] for r in _moves(tmp_path, "departure")] == [_stamp(7), _stamp(21)]


def test_two_books_on_one_market_are_one_market(tmp_path):
    report = _build([_row(), _row(quote={"bookmaker": "draftkings", "price": -111}, ev_pct=1.0)], 0, tmp_path)
    assert report["tracked"] == 1
    _build([_row(quote={"bookmaker": "draftkings", "price": -111}, ev_pct=1.0)], 7, tmp_path)
    assert _moves(tmp_path) == [], "a best-book change was recorded as the price leaving the board"


def test_the_log_is_allowlisted_for_publish_and_the_state_file_is_not(tmp_path):
    from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path

    assert is_hot_artifact_relative_path(f"reports/intelligence/clv_departures/{_DATE}.jsonl"), (
        "the departure log is not allowlisted; the worker's file can never reach web"
    )
    assert departure_state_path(_DATE, root=tmp_path).name == f"{_DATE}.state.json"
    assert not is_hot_artifact_relative_path(f"reports/intelligence/clv_departures/{_DATE}.state.json"), (
        "the whole-file state would be swept to web on every build"
    )


def test_the_ceiling_truncates_rather_than_growing(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_MAX_LEDGER_BYTES", 150)
    _build([_row()], 0, tmp_path)
    report = _build([_other()], 7, tmp_path)
    assert report["truncated_at_ceiling"] is True
    assert departure_ledger_path(_DATE, root=tmp_path).stat().st_size <= 150


def test_an_unreadable_state_undercounts_and_says_so(tmp_path):
    _build([_row()], 0, tmp_path)
    departure_state_path(_DATE, root=tmp_path).write_text("{not json", encoding="utf-8")
    report = _build([_other()], 7, tmp_path)
    assert (report["departed"], report["state_unreadable"]) == (0, True)


def test_a_publish_failure_never_breaks_the_recorder(tmp_path, monkeypatch):
    import syndicate.features.shared.artifact_publisher as pub

    def boom(_path):
        raise RuntimeError("network gone")

    monkeypatch.setattr(pub, "publish_hot_artifact", boom)
    _build([_row()], 0, tmp_path)
    report = _build([_other()], 7, tmp_path)
    assert (report["departed"], report["published"]) == (1, False)
    assert len(_moves(tmp_path)) == 1


# ---- reachability through the openings recorder (off != on) ----------------


def test_record_openings_reaches_it_and_the_flag_turns_it_off(tmp_path, monkeypatch):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    monkeypatch.delenv("SYNDICATE_CLV_DEPARTURE_LEDGER_ENABLED", raising=False)
    on = record_openings([_row()], date=_DATE, now=_at(0), root=tmp_path / "on")
    assert on["departures"]["tracked"] == 1
    assert departure_ledger_path(_DATE, root=tmp_path / "on").exists()

    monkeypatch.setenv("SYNDICATE_CLV_DEPARTURE_LEDGER_ENABLED", "off")
    off = record_openings([_row()], date=_DATE, now=_at(0), root=tmp_path / "off")
    assert off["departures"] == {"enabled": False}
    assert not departure_ledger_path(_DATE, root=tmp_path / "off").exists()


def test_openings_and_departures_share_one_build_clock(tmp_path):
    from syndicate.features.shared.clv_opening_ledger import load_openings, record_openings

    record_openings([_row()], date=_DATE, now=_at(0), root=tmp_path)
    record_openings([_other()], date=_DATE, now=_at(7), root=tmp_path)
    (gone,) = _moves(tmp_path)
    opened = {r["event_id"]: r["captured_at"] for r in load_openings(_DATE, root=tmp_path)}
    assert gone["gone_by"] == opened["other-game"] == _stamp(7)


def test_a_departure_failure_never_loses_the_openings(tmp_path, monkeypatch):
    from syndicate.features.shared.clv_opening_ledger import load_openings, record_openings

    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(mod, "record_departures", boom)
    report = record_openings([_row()], date=_DATE, now=_at(0), root=tmp_path)
    assert "disk on fire" in report["departures"]["error"]
    assert report["openings_written"] == 1
    assert len(load_openings(_DATE, root=tmp_path)) == 1


def test_a_generator_of_rows_still_feeds_both_recorders(tmp_path):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    report = record_openings((row for row in [_row()]), date=_DATE, now=_at(0), root=tmp_path)
    assert (report["openings_written"], report["departures"]["tracked"]) == (1, 1)
