"""A busy day must not silently lose its evening openings (lane `clv-openings-ceiling`).

Measured on the fleet 2026-10-22 (`.syndicate/findings_2026-10-22_clv_openings_ceiling.md`):
the one-file-per-date ledger stopped at 32 MiB on 6 of 24 dates, 10-11 at 19:03Z, and
10-21 lost 3,939 of 36,710 openings. The file is shared by every sport, so NFL's Sunday
props filling it cost MLB's LCS night its openings.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import syndicate.features.shared.clv_opening_ledger as ledger
from syndicate.features.shared.clv_opening_ledger import (
    load_openings,
    opening_ledger_path,
    record_openings,
)

_DATE = "2026-10-11"
_NOON = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)
_EVENING = datetime(2026, 10, 11, 23, 30, tzinfo=timezone.utc)


def _row(sport: str = "mlb", event_id: str = "lcs-g1", **over):
    row = {
        "sport": sport,
        "event_id": event_id,
        "market": "batter_hits",
        "player_name": "Player One",
        "side": "over",
        "line": 0.5,
        "commence_time": "2026-10-12T00:08:00Z",
        "quote": {"price": -150, "bookmaker": "draftkings", "fair_probability": 0.58},
    }
    row.update(over)
    return row


def _line_bytes(row) -> int:
    """Bytes one opening for `row` occupies on disk, in the recorder's own encoding."""
    record = ledger._opening_record(row, ledger._opening_key(row), "2026-10-11T17:00:00Z")
    return len((json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _fill_with_nfl(path, target_bytes: int) -> int:
    """Write NFL openings in the recorder's own shape until the file reaches `target_bytes`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pad = "x" * 900  # ~1 KB per record, the fleet's measured density
    written = 0
    with path.open("w", encoding="utf-8") as handle:
        size = 0
        while size < target_bytes:
            key = f"event_id=nfl{written}|market=player_reception_yds|player=p|segment=|side=over|line=40.5|bookmaker=fd"
            line = json.dumps({"key": key, "sport": "nfl", "pad": pad}, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            size += len(line)
            written += 1
    return written


def test_a_day_past_32_mib_still_records_the_evening(tmp_path):
    """The 10-11 shape: NFL fills the shared file to 32 MiB, then the LCS rows arrive.

    On the old ledger the MLB rows were refused (`truncated_at_ceiling`, written 0)."""
    path = opening_ledger_path(_DATE, root=tmp_path)
    nfl = _fill_with_nfl(path, 32 * 1024 * 1024)

    report = record_openings(
        [_row(player_name=f"Batter {i}") for i in range(20)], date=_DATE, now=_EVENING, root=tmp_path
    )

    assert report["openings_written"] == 20
    assert report["truncated_at_ceiling"] is False
    assert report["dropped_at_ceiling"] == 0
    assert report["already_recorded"] == nfl
    mlb = [r for r in load_openings(_DATE, root=tmp_path) if r.get("sport") == "mlb"]
    assert len(mlb) == 20


def test_a_sport_over_its_ceiling_does_not_cost_another_sport_its_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_MAX_SPORT_BYTES", 4_000, raising=False)
    nfl_rows = [_row(sport="nfl", event_id=f"nfl{i}") for i in range(40)]
    mlb_rows = [_row(event_id=f"mlb{i}") for i in range(3)]

    # NFL first in the batch, as the board orders it: the old `break` refused every row after
    # the first one over the line, MLB included.
    report = record_openings(nfl_rows + mlb_rows, date=_DATE, now=_NOON, root=tmp_path)

    records = load_openings(_DATE, root=tmp_path)
    assert sum(1 for r in records if r["sport"] == "mlb") == 3
    nfl_written = sum(1 for r in records if r["sport"] == "nfl")
    assert 0 < nfl_written < 40
    assert report["dropped_by_sport"] == {"nfl": 40 - nfl_written}
    assert report["truncated_at_ceiling"] is True
    sport_bytes = sum(
        len(line.encode("utf-8"))
        for line in opening_ledger_path(_DATE, root=tmp_path).read_text(encoding="utf-8").splitlines(True)
        if '"sport":"nfl"' in line
    )
    assert sport_bytes <= 4_000


def test_a_fired_ceiling_is_loud_and_counted(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ledger, "_MAX_SPORT_BYTES", 2 * _line_bytes(_row(event_id="e0")) + 10, raising=False)
    report = record_openings([_row(event_id=f"e{i}") for i in range(10)], date=_DATE, now=_NOON, root=tmp_path)

    out = capsys.readouterr().out
    hit = [line for line in out.splitlines() if "OPENINGS_CEILING_HIT" in line]
    assert len(hit) == 1, out
    assert "scope=sport" in hit[0] and "sport=mlb" in hit[0]
    assert f"dropped={report['dropped_at_ceiling']}" in hit[0]
    assert report["openings_written"] == 2
    assert report["dropped_at_ceiling"] == 8


def test_the_day_ceiling_still_bounds_a_dedup_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_MAX_LEDGER_BYTES", 6_000)
    for tick in range(30):
        # Every tick a fresh set of keys: what a dedup failure looks like from here.
        record_openings(
            [_row(sport=s, event_id=f"t{tick}-{s}") for s in ("mlb", "nfl", "nba")],
            date=_DATE,
            now=_NOON,
            root=tmp_path,
        )
    assert opening_ledger_path(_DATE, root=tmp_path).stat().st_size <= 6_000


def test_a_refused_opening_is_recorded_once_room_exists(tmp_path, monkeypatch):
    """Refused is not seen: the row is retried, and still recorded at its FIRST sighting's price if it fits."""
    monkeypatch.setattr(ledger, "_MAX_SPORT_BYTES", _line_bytes(_row(event_id="a")) + 10, raising=False)
    first = record_openings([_row(event_id="a"), _row(event_id="b")], date=_DATE, now=_NOON, root=tmp_path)
    assert first["openings_written"] == 1 and first["dropped_at_ceiling"] == 1
    monkeypatch.setattr(ledger, "_MAX_SPORT_BYTES", 64 * 1024 * 1024, raising=False)
    second = record_openings([_row(event_id="a"), _row(event_id="b")], date=_DATE, now=_EVENING, root=tmp_path)
    assert second["openings_written"] == 1 and second["duplicate_in_batch"] == 1
    assert sorted(r["event_id"] for r in load_openings(_DATE, root=tmp_path)) == ["a", "b"]


def test_first_sighting_only_holds_across_builds_and_other_writers(tmp_path):
    record_openings([_row(quote={"price": -150, "bookmaker": "draftkings"})], date=_DATE, now=_NOON, root=tmp_path)
    # Another process appends an opening behind this process's index.
    path = opening_ledger_path(_DATE, root=tmp_path)
    other = _row(event_id="other")
    key = ledger._opening_key(other)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"key": key, "sport": "mlb", "price": 101}) + "\n")

    report = record_openings(
        [_row(quote={"price": -110, "bookmaker": "draftkings"}), other], date=_DATE, now=_EVENING, root=tmp_path
    )
    assert report["openings_written"] == 0
    assert report["duplicate_in_batch"] == 2
    prices = sorted(r["price"] for r in load_openings(_DATE, root=tmp_path))
    assert prices == [-150, 101]


def test_a_replaced_file_is_reindexed_not_trusted(tmp_path):
    record_openings([_row(event_id="a")], date=_DATE, now=_NOON, root=tmp_path)
    path = opening_ledger_path(_DATE, root=tmp_path)
    # Restored from elsewhere: different content, at least as long, possibly the same inode.
    replacement = json.dumps({"key": ledger._opening_key(_row(event_id="b")), "sport": "mlb", "pad": "y" * 4000}) + "\n"
    path.write_text(replacement, encoding="utf-8")

    report = record_openings([_row(event_id="a"), _row(event_id="b")], date=_DATE, now=_EVENING, root=tmp_path)
    assert report["openings_written"] == 1  # "a" is no longer on disk; "b" is
    assert sorted(r["event_id"] for r in load_openings(_DATE, root=tmp_path) if "event_id" in r) == ["a"]


def test_a_torn_final_line_does_not_swallow_the_next_opening(tmp_path):
    record_openings([_row(event_id="a")], date=_DATE, now=_NOON, root=tmp_path)
    path = opening_ledger_path(_DATE, root=tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"key":"torn')  # a killed write: no newline
    record_openings([_row(event_id="b")], date=_DATE, now=_EVENING, root=tmp_path)
    assert sorted(r["event_id"] for r in load_openings(_DATE, root=tmp_path)) == ["a", "b"]


def test_the_build_does_not_reparse_the_whole_day(tmp_path, monkeypatch):
    """Dedup reads only what was appended since the last build."""
    monkeypatch.setenv("SYNDICATE_CLV_DEPARTURE_LEDGER_ENABLED", "off")
    path = opening_ledger_path(_DATE, root=tmp_path)
    _fill_with_nfl(path, 2 * 1024 * 1024)
    record_openings([_row(event_id="a")], date=_DATE, now=_NOON, root=tmp_path)

    calls = {"n": 0}
    real = json.loads

    def counting(text, *a, **k):
        calls["n"] += 1
        return real(text, *a, **k)

    monkeypatch.setattr(ledger.json, "loads", counting)
    record_openings([_row(event_id="b")], date=_DATE, now=_EVENING, root=tmp_path)
    assert calls["n"] <= 2, f"re-parsed {calls['n']} lines for a one-line append"


def test_the_ceilings_are_sized_above_the_measured_busiest_day():
    # 10-21 exact: 36,710 openings ~ 36 MiB. 10-11 projected ~46 MiB, NFL alone ~29-32 MiB.
    assert ledger._MAX_LEDGER_BYTES >= 2 * 46 * 1024 * 1024
    assert ledger._MAX_SPORT_BYTES >= 2 * 32 * 1024 * 1024
    assert ledger._MAX_SPORT_BYTES <= ledger._MAX_LEDGER_BYTES
    assert os.path.basename(str(opening_ledger_path(_DATE, root="r"))) == f"{_DATE}.jsonl"
