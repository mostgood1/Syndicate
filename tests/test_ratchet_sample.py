"""The ratchet sampler must not repeat the two defects that made attempt 1 unreadable.

Attempt 1 produced -17.63, +7.39 and -0.28 pts/h inside one hour, against a
signal of 0.59 pts/h. Two causes, one test each:

1. It took the LAST of 3 rows. Most CONTAINER_MEMORY rows carry no
   `memory_unreclaimable_pct_of_max`, so it silently produced nothing about half
   the time -- 4 of 8 samples printed `?` and were lost.
2. It used the LATEST value. Unreclaimable oscillates ~10 points within an hour
   as board builds allocate and release, so a two-point slope over a sub-hour
   span measures the cycle phase, not the ratchet. The floor is what ratchets.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import ratchet_sample as rs


def _row(**fields):
    return {"message": "CONTAINER_MEMORY " + json.dumps(fields)}


# --- defect 1: silent drops ---------------------------------------------------

def test_rows_without_the_field_are_skipped_not_fatal():
    rows = [
        _row(memory_pct_of_max=50.0),                                   # no field
        _row(memory_unreclaimable_pct_of_max=30.0),
        {"message": "not json at all"},
        _row(memory_unreclaimable_pct_of_max=25.0),
        {"message": "CONTAINER_MEMORY {malformed"},
    ]
    trough, usable, total = rs.trough_from_rows(rows)
    assert trough == 25.0
    assert usable == 2, "must count only rows that carried the field"
    assert total == 5, "must report how many were scanned, so a thin batch is visible"


def test_no_usable_rows_returns_none_rather_than_a_wrong_number():
    trough, usable, total = rs.trough_from_rows([_row(memory_pct_of_max=80.0)] * 4)
    assert trough is None and usable == 0 and total == 4


def test_empty_batch_is_safe():
    assert rs.trough_from_rows([]) == (None, 0, 0)


# --- defect 2: latest vs trough ----------------------------------------------

def test_returns_the_minimum_not_the_last_value():
    """The last value is whatever phase of the board cycle we sampled."""
    rows = [
        _row(memory_unreclaimable_pct_of_max=22.0),   # the floor
        _row(memory_unreclaimable_pct_of_max=31.0),
        _row(memory_unreclaimable_pct_of_max=28.0),   # last, but not the trough
    ]
    trough, _, _ = rs.trough_from_rows(rows)
    assert trough == 22.0, "peaks oscillate; the floor is what ratchets"


def test_a_single_high_spike_cannot_raise_the_trough():
    base = [_row(memory_unreclaimable_pct_of_max=20.0)]
    spiked = base + [_row(memory_unreclaimable_pct_of_max=95.0)]
    assert rs.trough_from_rows(base)[0] == rs.trough_from_rows(spiked)[0]


# --- the guard against reporting a rate too early -----------------------------

def test_analysis_refuses_a_rate_under_two_hours(tmp_path, monkeypatch, capsys):
    """Reporting early is exactly what produced the garbage figures."""
    csv = tmp_path / "r.csv"
    csv.write_text(
        "ts_utc,commit,uptime_h,trough_pct,usable_rows,total_rows\n"
        "t,c,0.10,24.0,50,100\n"
        "t,c,0.60,18.0,50,100\n"
        "t,c,1.10,28.0,50,100\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rs, "CSV", csv)
    rs.analyse()
    out = capsys.readouterr().out
    assert "NO RATE YET" in out
    assert "pts/h over" not in out, "must not emit a rate from under 2h of buckets"


def test_analysis_reports_a_rate_once_the_span_is_long_enough(tmp_path, monkeypatch, capsys):
    csv = tmp_path / "r.csv"
    lines = ["ts_utc,commit,uptime_h,trough_pct,usable_rows,total_rows"]
    # troughs rising 20 -> 24 over 4h == +1.0 pts/h, with noisy peaks in between
    for i in range(17):
        h = i * 0.25
        lines.append(f"t,c,{h:.2f},{20.0 + h:.1f},50,100")
        lines.append(f"t,c,{h:.2f},{40.0 + h:.1f},50,100")  # peaks must not matter
    csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(rs, "CSV", csv)
    rs.analyse()
    out = capsys.readouterr().out
    assert "trough rate:" in out
    assert "NO RATE YET" not in out
