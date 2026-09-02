"""`#626`(h) -- the cumulative byte budget on the accuracy-summary ledger load.

WHY THESE TESTS EXIST. The autorun that calls `build_accuracy_summary` was armed
on 2026-09-02 believing a 50-segment OUTPUT cap bounded its memory. It did not,
and could not: 98.8-99.9% of peak is set by the record materialisation, upstream
of any output. It OOM-killed refresh-worker (anon 1,833 -> 3,868 MiB of 4,096).

Peak was then measured as PROPORTIONAL to accepted chunk bytes -- 4.01-4.41x,
R2 0.999998, intercept zero -- so a byte budget is the bound, and these tests
pin the properties that make it one:

  * it actually BOUNDS (accepted <= budget, exactly, not within one record);
  * it is REACHABLE (off != on) -- the model-engine standard's first rule, and
    the thing that caught four inert features in one session;
  * it takes the NEWEST data, not an arbitrary slice;
  * it does NOT invert record order, because `_latest_by_recommendation_id`
    keeps the LAST record per id;
  * it is never VACUOUS -- the trap that makes
    `load_recent_evaluation_records(max_chunk_bytes=64MB)` useless here, where
    it accepts 0 of 8 real production chunks;
  * absent env means BOUNDED, not unlimited (CLAUDE.md: absent is not off);
  * every OTHER caller of the streamer is untouched.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import intelligence_evaluation as ie


ENV_KEY = "SYNDICATE_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES"


def _write_chunks(root, spec):
    """spec: {date_token: n_records}. Records are uniform so byte counts are
    predictable and a budget maps onto a record count."""
    chunk_root = root / "evaluation_ledger_chunks"
    chunk_root.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for date_token, count in spec.items():
        path = chunk_root / f"{date_token}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for i in range(count):
                handle.write(json.dumps({
                    "recommendation_id": f"{date_token}-{i}",
                    "record_type": "recommendation",
                    "result": "win" if i % 2 else "loss",
                    "created_at": f"{date_token}T12:00:00Z",
                    "recommendation": {"sport": "mlb", "market": "moneyline"},
                    "artifact_metadata": {"sport": "mlb", "selected_date": date_token},
                    "padding": "x" * 400,
                }, separators=(",", ":")) + "\n")
        sizes[date_token] = path.stat().st_size
    return chunk_root, sizes


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "evaluation_ledger.jsonl"
    monkeypatch.setattr(ie, "DEFAULT_LEDGER_PATH", path)
    return path


def _collect(path, budget):
    stats: dict = {}
    rows = list(ie._stream_chunked_ledger_records(path, max_total_bytes=budget, stats=stats))
    return rows, stats


def test_budget_bounds_accepted_bytes_exactly(ledger, tmp_path):
    _write_chunks(tmp_path, {"2026-08-01": 200, "2026-08-02": 200, "2026-08-03": 200})
    budget = 100_000
    rows, stats = _collect(ledger, budget)
    assert stats["bytes_accepted"] <= budget, "the budget must be a HARD bound"
    assert rows, "a bounded read must not be empty"
    # Not merely under budget -- close to it, or the bound is not the binding
    # constraint and the test would pass on a broken reader that returns nothing.
    assert stats["bytes_accepted"] > budget * 0.9


def test_off_does_not_equal_on(ledger, tmp_path):
    _write_chunks(tmp_path, {"2026-08-01": 200, "2026-08-02": 200, "2026-08-03": 200})
    unbounded, _ = _collect(ledger, None)
    bounded, _ = _collect(ledger, 100_000)
    assert len(unbounded) > len(bounded) > 0, (
        "budget is INERT: bounded and unbounded reads returned the same set"
    )


def test_selection_takes_the_newest_dates(ledger, tmp_path):
    _write_chunks(tmp_path, {"2026-08-01": 200, "2026-08-02": 200, "2026-08-03": 200})
    rows, stats = _collect(ledger, 100_000)
    seen = {row["artifact_metadata"]["selected_date"] for row in rows}
    assert "2026-08-03" in seen, "the newest date must survive the budget"
    assert "2026-08-01" not in seen, "the oldest date must be the one dropped"
    assert stats["chunks_skipped_budget"] >= 1
    assert stats["truncated"] is True


def test_yield_order_stays_ascending(ledger, tmp_path):
    """Selection is newest-first; emission must NOT be.

    `_latest_by_recommendation_id` keeps the LAST record per id, so reversing
    emission order would silently flip last-wins into first-wins for every
    consumer of the ledger."""
    _write_chunks(tmp_path, {"2026-08-01": 40, "2026-08-02": 40, "2026-08-03": 40})
    rows, _ = _collect(ledger, 10_000_000)
    dates = [row["artifact_metadata"]["selected_date"] for row in rows]
    assert dates == sorted(dates), "records must be emitted oldest-first"


def test_last_wins_semantics_preserved_under_budget(ledger, tmp_path):
    chunk_root, _ = _write_chunks(tmp_path, {"2026-08-02": 5, "2026-08-03": 5})
    for date_token, marker in (("2026-08-02", "older"), ("2026-08-03", "newer")):
        path = chunk_root / f"{date_token}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "recommendation_id": "shared-id",
                "record_type": "recommendation",
                "result": "win",
                "marker": marker,
                "recommendation": {"sport": "mlb", "market": "moneyline"},
                "artifact_metadata": {"sport": "mlb", "selected_date": date_token},
            }, separators=(",", ":")) + "\n")
    rows, _ = _collect(ledger, 10_000_000)
    reduced = ie._latest_by_recommendation_id(rows)
    shared = [r for r in reduced if r.get("recommendation_id") == "shared-id"]
    assert len(shared) == 1
    assert shared[0]["marker"] == "newer", "budget must not invert last-wins"


def test_never_vacuous_when_one_chunk_exceeds_the_whole_budget(ledger, tmp_path):
    """The failure mode that rules out the existing bounded reader.

    `load_recent_evaluation_records(max_chunk_bytes=64MB)` drops any FILE over
    its ceiling; against real production chunks (95-332 MB/day) it accepts 0 of
    8 and the summary is computed on an empty set. A per-record budget must read
    INTO the oversized chunk instead."""
    _write_chunks(tmp_path, {"2026-08-03": 2000})
    rows, stats = _collect(ledger, 50_000)
    assert rows, "a single oversized chunk must still yield records"
    assert stats["bytes_accepted"] <= 50_000
    assert stats["chunks_partial"] == 1


def test_absent_env_is_bounded_not_unlimited(monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    assert ie._accuracy_summary_ledger_budget_bytes() == ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES
    assert ie._accuracy_summary_ledger_budget_bytes() > 0, (
        "absent must mean BOUNDED -- an unbounded default is the arming that OOMed"
    )


def test_env_zero_opts_out_and_garbage_falls_back_to_bounded(monkeypatch):
    monkeypatch.setenv(ENV_KEY, "0")
    assert ie._accuracy_summary_ledger_budget_bytes() == 0
    monkeypatch.setenv(ENV_KEY, "not-a-number")
    assert ie._accuracy_summary_ledger_budget_bytes() == ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES


def test_build_accuracy_summary_publishes_its_coverage(ledger, tmp_path, monkeypatch):
    _write_chunks(tmp_path, {"2026-08-01": 200, "2026-08-02": 200, "2026-08-03": 200})
    monkeypatch.setenv(ENV_KEY, "100000")
    summary = ie.build_accuracy_summary(sport="mlb")
    coverage = summary["ledger_coverage"]
    assert coverage["budget_bytes"] == 100000
    assert coverage["bytes_accepted"] <= 100000
    assert coverage["truncated"] is True
    assert coverage["dates_covered"] >= 1
    assert coverage["date_max"] == "2026-08-03"
    # A narrowed sample that cannot be SEEN to be narrow is the real hazard:
    # this summary's drift window is recent_days=7 + baseline_days=21.
    assert set(coverage) >= {
        "budget_bytes", "bytes_accepted", "chunks_accepted", "chunks_partial",
        "chunks_skipped_budget", "dates_covered", "date_min", "date_max",
        "truncated", "records",
    }


def test_other_callers_are_unchanged(ledger, tmp_path):
    """The budget is opt-in per call. Every existing caller passes nothing and
    must read exactly what it read before."""
    _write_chunks(tmp_path, {"2026-08-01": 50, "2026-08-02": 50, "2026-08-03": 50})
    default_rows = list(ie._stream_chunked_ledger_records(ledger))
    explicit_none = list(ie._stream_chunked_ledger_records(ledger, max_total_bytes=None))
    assert len(default_rows) == len(explicit_none) == 150
    assert list(ie._stream_record_payloads(ledger_path=ledger)) == default_rows
