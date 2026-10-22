"""`clv_departure_ledger` ceilings (lane clv-departures-ceiling, 2026-10-22).

The departures log is one file per date for every sport, and it stopped at
8 MiB. On the fleet 10-17 reached 7,938,374 B (94.6%) before NBA's season, and
NBA alone wrote 2.35 MiB on Wednesday 10-21. The old loop `break`s at the first
record over the ceiling, so the first sport to fill the file costs every sport
its evening, the heartbeat goes with it, and the state moves on so those
departures are never written. These pin the sibling of `22e3a0aa`'s openings
fix: per-sport and per-date ceilings, refused per record, loud and counted,
with the heartbeat kept and a refused sport censored rather than read as kept.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import clv_departure_ledger as mod
from syndicate.features.shared.clv_departure_ledger import (
    departure_ledger_path,
    departure_state_path,
    load_departures,
    record_departures,
)

_DATE = "2026-10-17"
_T0 = datetime(2026, 10, 17, 22, 0, tzinfo=timezone.utc)
_MIB = 1024 * 1024

_SCORECARD = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "layer2_live_scorecard.py"
_spec = importlib.util.spec_from_file_location("layer2_live_scorecard_for_ceiling", _SCORECARD)
scorecard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scorecard)


def _at(minutes: int) -> datetime:
    return _T0 + timedelta(minutes=minutes)


def _stamp(minutes: int) -> str:
    return _at(minutes).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(sport: str, event_id: str, **over):
    row = {
        "sport": sport,
        "event_id": event_id,
        "market": "spreads",
        "segment": "full",
        "side": "away",
        "line": -6.5,
        "player_name": None,
        "ev_pct": 4.75,
        "game_state": "live",
        "quote": {"price": 107, "bookmaker": "prophetx"},
    }
    row.update(over)
    return row


def _build(rows, minutes, root):
    return record_departures(rows, date=_DATE, now=_at(minutes), root=root)


def _fill(root, sport: str, target_bytes: int) -> None:
    """Append `sport` departure-shaped lines until the file is exactly `target_bytes`.

    Stands in for a busy day's earlier builds without running thousands of them.
    """
    path = departure_ledger_path(_DATE, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    size = path.stat().st_size if path.exists() else 0
    lines = []
    line = json.dumps({"type": "departure", "sport": sport, "identity": "x", "pad": "p" * 300},
                      sort_keys=True, separators=(",", ":")) + "\n"
    while size + len(line) <= target_bytes:
        lines.append(line)
        size += len(line)
    pad = target_bytes - size
    if pad:
        # One last line padded to land exactly on the target.
        lines.append(json.dumps({"type": "departure", "sport": sport, "identity": "x", "pad": "p" * max(0, pad - 60)},
                                sort_keys=True, separators=(",", ":")).ljust(pad - 1) + "\n")
    with path.open("ab") as handle:
        handle.write("".join(lines).encode("utf-8"))


def _real(root, kind=None):
    return [r for r in load_departures(_DATE, root=root)
            if r.get("identity") != "x" and (kind is None or r.get("type") == kind)]


@pytest.fixture(autouse=True)
def publishes(monkeypatch):
    import syndicate.features.shared.artifact_publisher as pub

    calls = []
    monkeypatch.setattr(pub, "publish_hot_artifact", lambda path: calls.append(path) or True)
    return calls


def test_the_10_17_shape_an_nba_departure_after_ncaaf_filled_8_mib_is_written(tmp_path):
    # 10-17 measured 7,938,374 B with NCAAF the largest sport; add 10-21's NBA.
    _build([_row("nba", "g1"), _row("ncaaf", "c1")], 0, tmp_path)
    _fill(tmp_path, "ncaaf", 8 * _MIB - 50)
    report = _build([_row("nba", "g2"), _row("ncaaf", "c1")], 5, tmp_path)
    departed = _real(tmp_path, "departure")
    assert [(r["sport"], r["event_id"]) for r in departed] == [("nba", "g1")], (
        "the NBA departure was refused by an all-sports 8 MiB file NCAAF had filled"
    )
    assert report["truncated_at_ceiling"] is False
    beats = [r for r in load_departures(_DATE, root=tmp_path) if r["type"] == "build"]
    assert [b["at"] for b in beats] == [_stamp(0), _stamp(5)], "the build's heartbeat was dropped"


def test_one_sport_over_its_ceiling_never_costs_another_sport(tmp_path, monkeypatch):
    # The day ceiling has room for NFL; NCAAF is over its own. Records are written
    # in sport order, so NCAAF's refusals come BEFORE NFL's departure.
    monkeypatch.setattr(mod, "_MAX_SPORT_BYTES", 20_000, raising=False)
    monkeypatch.setattr(mod, "_MAX_LEDGER_BYTES", 22_000)
    ncaaf = [_row("ncaaf", f"c{i}") for i in range(10)]
    _build(ncaaf + [_row("nfl", "f1")], 0, tmp_path)
    _fill(tmp_path, "ncaaf", 20_000)
    report = _build([_row("ncaaf", "c-new"), _row("nfl", "f2")], 5, tmp_path)
    departed = {(r["sport"], r["event_id"]) for r in _real(tmp_path, "departure")}
    assert ("nfl", "f1") in departed, "NFL's departure was refused because NCAAF filled the file"
    assert not any(sport == "ncaaf" for sport, _ in departed)
    assert report["dropped_by_sport"] == {"ncaaf": 10}


def test_a_fired_ceiling_is_loud_and_counted(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mod, "_MAX_LEDGER_BYTES", 5_000)
    _build([_row("ncaaf", f"c{i}") for i in range(30)], 0, tmp_path)
    capsys.readouterr()
    report = _build([_row("ncaaf", "c-new")], 5, tmp_path)
    out = capsys.readouterr().out
    assert report.get("dropped_at_ceiling", 0) > 0, "a fired tripwire must say what it cost"
    assert report["dropped_at_ceiling"] == 30 - len(_real(tmp_path, "departure"))
    assert report["dropped_by_sport"] == {"ncaaf": report["dropped_at_ceiling"]}
    assert "DEPARTURES_CEILING_HIT" in out and "scope=day sport=ncaaf" in out
    assert report["bytes_on_disk"] == departure_ledger_path(_DATE, root=tmp_path).stat().st_size


def test_the_heartbeat_survives_a_full_day_and_names_the_censored_sport(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_MAX_LEDGER_BYTES", 5_000)
    _build([_row("ncaaf", f"c{i}") for i in range(30)] + [_row("nhl", "h1")], 0, tmp_path)
    _build([_row("ncaaf", "c-new"), _row("nhl", "h1")], 5, tmp_path)
    _build([_row("ncaaf", "c-new"), _row("nhl", "h1")], 10, tmp_path)
    beats = [r for r in load_departures(_DATE, root=tmp_path) if r["type"] == "build"]
    assert [b["at"] for b in beats] == [_stamp(0), _stamp(5), _stamp(10)], (
        "builds that ran must stay visible after the day ceiling fires"
    )
    # NHL lost nothing and stays observed; NCAAF lost departures and is censored
    # for the rest of the date, so its later builds do not claim completeness.
    assert beats[1]["sports"] == {"nhl": 1} and beats[1]["censored"] == {"ncaaf": 1}
    assert beats[2]["sports"] == {"nhl": 1} and beats[2]["censored"] == {"ncaaf": 1}


def test_a_refused_departure_reads_unobserved_in_the_scorecard_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_MAX_SPORT_BYTES", 2_000, raising=False)
    filler = [_row("ncaaf", f"c{i}") for i in range(8)]
    _build(filler + [_row("ncaaf", "target")], 0, tmp_path)
    _build([_row("ncaaf", "target")], 5, tmp_path)   # the 8 fillers depart: over 2,000 B
    _build([], 10, tmp_path)
    _build([_row("ncaaf", "other")], 15, tmp_path)  # target departs: refused
    records = load_departures(_DATE, root=tmp_path)
    builds, timeline = scorecard.index_departures(records)
    sighting = {**_row("ncaaf", "target"), "captured_at": _stamp(5)}
    look = scorecard.look_after(sighting, builds, timeline, horizon_seconds=600)
    assert look == "unobserved", "a departure the ceiling refused was read as a price still on the board"


def test_a_refused_departure_leaves_no_orphan_return(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_MAX_LEDGER_BYTES", 300)  # a heartbeat fits, a departure does not
    _build([_row("ncaaf", "c1")], 0, tmp_path)
    _build([_row("ncaaf", "c2")], 5, tmp_path)       # c1 departs: refused at the day ceiling
    report = _build([_row("ncaaf", "c1"), _row("ncaaf", "c2")], 10, tmp_path)  # c1 is back
    assert _real(tmp_path, "departure") == []
    assert report["returned"] == 0 and _real(tmp_path, "return") == []


def test_a_torn_final_line_does_not_swallow_the_next_departure(tmp_path):
    _build([_row("nba", "g1")], 0, tmp_path)
    path = departure_ledger_path(_DATE, root=tmp_path)
    with path.open("ab") as handle:
        handle.write(b'{"type":"departure","sport":"nba","ident')  # a crash mid-write
    _build([_row("nba", "g2")], 5, tmp_path)
    assert [(r["sport"], r["event_id"]) for r in _real(tmp_path, "departure")] == [("nba", "g1")]


def test_the_state_sidecar_carries_the_byte_tally_and_a_changed_file_is_recounted(tmp_path):
    _build([_row("nba", "g1"), _row("nfl", "f1")], 0, tmp_path)
    _build([_row("nba", "g2"), _row("nfl", "f2")], 5, tmp_path)
    path = departure_ledger_path(_DATE, root=tmp_path)
    state = json.loads(departure_state_path(_DATE, root=tmp_path).read_text(encoding="utf-8"))
    ledger = state.get("ledger") or {}
    assert ledger.get("bytes") == path.stat().st_size
    assert sum(ledger["sport_bytes"].values()) == path.stat().st_size
    assert set(ledger["sport_bytes"]) == {"", "nba", "nfl"}
    # Something else appended (another writer, a restored file): the tally must
    # be re-read from the file rather than trusted.
    _fill(tmp_path, "nba", path.stat().st_size + 5_000)
    report = _build([_row("nba", "g2"), _row("nfl", "f2")], 10, tmp_path)
    state = json.loads(departure_state_path(_DATE, root=tmp_path).read_text(encoding="utf-8"))
    assert state["ledger"]["bytes"] == path.stat().st_size == report["bytes_on_disk"]
    assert sum(state["ledger"]["sport_bytes"].values()) == path.stat().st_size


def test_ceilings_are_sized_from_the_measured_week():
    # Fleet, 24 dates 09-30..10-23: largest sport-day NCAAF 10-10 at 3.80 MiB;
    # largest day 10-17 at 7.57 MiB; a Saturday plus 10-21's NBA ~10 MiB.
    sport_ceiling = getattr(mod, "_MAX_SPORT_BYTES", mod._MAX_LEDGER_BYTES)
    assert sport_ceiling >= 2 * 3.80 * _MIB
    assert mod._MAX_LEDGER_BYTES >= 2 * 10 * _MIB
    assert sport_ceiling < mod._MAX_LEDGER_BYTES, "one sport must not be able to fill the day"
