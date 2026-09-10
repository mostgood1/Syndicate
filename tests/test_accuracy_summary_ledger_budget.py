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


def test_default_budget_admits_more_than_the_first_production_read():
    """Regression guard tied to a MEASURED production number, not a round one.

    The first real autorun (2026-09-04) spent 1,999,970,055 B of a 2,000,000,000 B
    budget -- 99.9985% -- and SKIPPED 24 chunks, keeping 8 dates. Peak
    `memory_anon_mb` that run was 1,481.6 of a 4,096 ceiling, so the cap, not
    memory, was what cost coverage.

    This asserts the default stays clear of that observed ceiling. It is not a
    style rule: the 90MB budget failed the same way in 2026-09-02 and was raised
    on the same evidence, so "the budget quietly became the binding constraint
    again" is a repeat defect, not a hypothetical. A deliberate LOWERING must
    update this test and say why.
    """
    observed_production_read_bytes = 1_999_970_055
    assert ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES > observed_production_read_bytes, (
        "the default must admit strictly more than the read that was measured "
        "truncating in production, or coverage is capped by the cap again"
    )


def test_truncation_is_visible_in_coverage_not_only_in_a_log_line(ledger, tmp_path, monkeypatch):
    """A truncated read must SAY so in the published coverage dict.

    The 09-04 truncation was discoverable only by reading LEDGER_CHUNKS_ACCEPTED
    off the worker's stdout. `ledger_coverage` is the part that reaches the
    artifact, so the skip count has to survive into it -- otherwise a summary
    built on 8 of 32 chunks is indistinguishable from one built on all of them.
    """
    _write_chunks(tmp_path, {"2026-08-01": 200, "2026-08-02": 200, "2026-08-03": 200})
    monkeypatch.setenv(ENV_KEY, "300")
    coverage = ie.build_accuracy_summary(sport="mlb")["ledger_coverage"]
    assert coverage["truncated"] is True
    assert coverage["chunks_skipped_budget"] >= 1, (
        "the number of chunks the budget REFUSED must be published, not just logged"
    )
    assert coverage["dates_covered"] < 3


# --- the CHUNK-COUNT bound (2026-09-10) ---------------------------------------
#
# The pre-registered 09-04 rule said a first 4GB run skipping "~12" chunks means
# the byte budget is the wrong instrument. It skipped 12; by 09-10 the same 4GB
# bought 16 dates instead of 21 because the days got fatter. These pin the
# replacement: a day count as the primary bound, the byte budget as a backstop
# sized in the same unit.

MAX_CHUNKS_ENV = "SYNDICATE_ACCURACY_SUMMARY_LEDGER_MAX_CHUNKS"


def _collect_bounded(path, *, budget=None, max_chunks=None):
    stats: dict = {}
    rows = list(ie._stream_chunked_ledger_records(
        path, max_total_bytes=budget, max_chunks=max_chunks, stats=stats
    ))
    return rows, stats


class _FakeChunk:
    """Duck-types the two things selection reads (`.name`, `.stat().st_size`),
    so a production-sized plan can be checked without writing gigabytes."""

    def __init__(self, name, size):
        self.name = name
        self._size = size

    def stat(self):
        return type("_Stat", (), {"st_size": self._size})()


def test_chunk_bound_takes_exactly_the_newest_n_whole_chunks(ledger, tmp_path):
    _, sizes = _write_chunks(tmp_path, {
        "2026-08-01": 50, "2026-08-02": 50, "2026-08-03": 50, "2026-08-04": 50,
    })
    rows, stats = _collect_bounded(ledger, budget=10_000_000, max_chunks=2)
    seen = sorted({row["artifact_metadata"]["selected_date"] for row in rows})
    assert seen == ["2026-08-03", "2026-08-04"], "the NEWEST days must be the ones kept"
    assert len(rows) == 100, "a chunk-bounded read takes WHOLE chunks, never a partial one"
    assert stats["chunks_skipped_count"] == 2
    assert stats["chunks_skipped_budget"] == 0, "the byte backstop must not be what bound this"
    assert stats["chunks_partial"] == 0
    assert stats["bytes_skipped"] == sizes["2026-08-01"] + sizes["2026-08-02"]
    assert stats["max_chunks"] == 2
    assert stats["truncated"] is True, "a day the count refused still narrows the sample"


def test_chunk_bound_off_does_not_equal_on(ledger, tmp_path):
    _write_chunks(tmp_path, {"2026-08-01": 50, "2026-08-02": 50, "2026-08-03": 50})
    unbounded, _ = _collect_bounded(ledger, budget=10_000_000, max_chunks=None)
    bounded, _ = _collect_bounded(ledger, budget=10_000_000, max_chunks=1)
    assert len(unbounded) > len(bounded) > 0, (
        "chunk bound is INERT: bounded and unbounded reads returned the same set"
    )


def test_chunk_bound_holds_when_the_byte_budget_is_opted_out(ledger, tmp_path):
    """Budget 0 used to mean the whole ledger. With a chunk bound set it must
    still mean at most N days: EITHER bound has to switch the budgeted path on,
    or the byte opt-out falls through to the unbounded read that OOM-killed
    refresh-worker on 2026-09-02."""
    _write_chunks(tmp_path, {"2026-08-01": 50, "2026-08-02": 50, "2026-08-03": 50})
    rows, stats = _collect_bounded(ledger, budget=0, max_chunks=2)
    assert len(rows) == 100
    assert stats["chunks_skipped_count"] == 1
    assert stats["chunks_skipped_budget"] == 0
    assert stats["budget_exhausted"] is False


def test_the_byte_backstop_still_binds_behind_the_chunk_bound(ledger, tmp_path):
    """The count is checked first, but a budget smaller than N chunks must
    still bound bytes exactly -- the backstop is not decorative."""
    _write_chunks(tmp_path, {"2026-08-01": 200, "2026-08-02": 200, "2026-08-03": 200})
    rows, stats = _collect_bounded(ledger, budget=100_000, max_chunks=45)
    assert stats["bytes_accepted"] <= 100_000
    assert stats["chunks_skipped_count"] == 0
    assert stats["chunks_skipped_budget"] >= 1
    assert rows


def test_defaults_admit_the_whole_ledger_measured_in_production_2026_09_10():
    """Tied to MEASURED refresh-worker numbers, not round ones.

    2026-09-10: `LEDGER_CHUNKS_ACCEPTED count=16 bytes=3999961107
    skipped_budget=22` -- 38 chunks, average admitted 249,997,569 B -- and
    `PROJECTION_DONE seen=38`. The defaults must admit a ledger that size, with
    margin for the one chunk a day it gains, and the byte backstop must not bind
    before the count does at that density. Otherwise the backstop is the bound
    again, and coverage erodes as days get fatter: 21 dates on 09-05, 16 on
    09-10, both at a fixed 4GB.
    """
    measured_chunks = 38
    measured_avg_admitted_bytes = 3_999_961_107 // 16
    assert ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_MAX_CHUNKS > measured_chunks
    assert ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES >= (
        ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_MAX_CHUNKS * measured_avg_admitted_bytes
    )


def test_old_budget_reproduces_the_09_10_shortfall_and_the_defaults_remove_it():
    chunks = [_FakeChunk(f"2026-chunk-{i:03d}.jsonl", 249_997_569) for i in range(38)]
    _, old = ie._select_ledger_chunks_within_budget(chunks, max_total_bytes=4_000_000_000)
    assert old["chunks_skipped_budget"] >= 20, "the old 4GB default refuses most of the ledger"
    selected, new = ie._select_ledger_chunks_within_budget(
        chunks,
        max_total_bytes=ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES,
        max_chunks=ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_MAX_CHUNKS,
    )
    assert len(selected) == 38
    assert (new["chunks_skipped_budget"], new["chunks_skipped_count"], new["chunks_partial"]) == (0, 0, 0)


def test_max_chunks_env_absent_is_bounded_zero_unlimited_garbage_default(monkeypatch):
    monkeypatch.delenv(MAX_CHUNKS_ENV, raising=False)
    assert ie._accuracy_summary_ledger_max_chunks() == ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_MAX_CHUNKS
    assert ie._accuracy_summary_ledger_max_chunks() > 0, "absent must mean BOUNDED"
    monkeypatch.setenv(MAX_CHUNKS_ENV, "0")
    assert ie._accuracy_summary_ledger_max_chunks() == 0
    monkeypatch.setenv(MAX_CHUNKS_ENV, "not-a-number")
    assert ie._accuracy_summary_ledger_max_chunks() == ie.DEFAULT_ACCURACY_SUMMARY_LEDGER_MAX_CHUNKS


def test_build_accuracy_summary_reaches_the_chunk_bound(ledger, tmp_path, monkeypatch):
    """Reachability through the REAL entry point, off != on -- a bound the
    helper honours and the caller never passes is the inert-feature shape."""
    _write_chunks(tmp_path, {"2026-08-01": 50, "2026-08-02": 50, "2026-08-03": 50})
    monkeypatch.delenv(ENV_KEY, raising=False)
    monkeypatch.setenv(MAX_CHUNKS_ENV, "2")
    coverage = ie.build_accuracy_summary(sport="mlb")["ledger_coverage"]
    assert coverage["max_chunks"] == 2
    assert coverage["dates_covered"] == 2
    assert coverage["date_min"] == "2026-08-02"
    assert coverage["chunks_skipped_count"] == 1
    assert coverage["chunks_skipped_budget"] == 0
    monkeypatch.setenv(MAX_CHUNKS_ENV, "0")
    monkeypatch.setenv(ENV_KEY, "0")
    assert ie.build_accuracy_summary(sport="mlb")["ledger_coverage"]["dates_covered"] == 3


def test_log_line_names_the_chunk_bound_and_what_it_left_out(ledger, tmp_path, capsys):
    """The worker's stdout is the only place this is readable in production --
    `ledger_coverage` lands in the keyvalue store, which no ops route serves."""
    _write_chunks(tmp_path, {"2026-08-01": 50, "2026-08-02": 50, "2026-08-03": 50})
    _collect_bounded(ledger, budget=10_000_000, max_chunks=2)
    line = [l for l in capsys.readouterr().out.splitlines() if "LEDGER_CHUNKS_ACCEPTED" in l][-1]
    assert "max_chunks=2" in line
    assert "skipped_chunks=1" in line
    assert "skipped_budget=0" in line
    assert "skipped_bytes=0 " not in line and "skipped_bytes=" in line
    assert line.rstrip().endswith("truncated=1")
