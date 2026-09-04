"""The projected evaluation-ledger mirror -- `evaluation_ledger_projection.py`.

WHY THESE TESTS EXIST. The raw ledger cannot leave refresh-worker: chunks are
95-332 MB/day against a 12 MiB publish ceiling, and the worker serves no HTTP,
so `/api/ops/artifacts/stream` reads a disk that never holds them. The projected
copy is the ONLY form that can cross, which makes two properties load-bearing:

  * the allowlist must admit the PROJECTED path and must NOT admit the RAW
    chunks -- a glob that matched both would hand the sweep a 332 MB file, which
    is exactly the `odds_events` failure the allowlist comments refuse; and
  * the producer must be INCREMENTAL and BOUNDED, because it rides a once-daily
    job on a 4 GB box that is also running board builds and sims. An unbounded
    first pass would stream ~8 GB inside a job that already takes ~669 s.

The size claim itself (~3.3 MB per 250 MB chunk) rests on a per-record cost that
SATURATES, and is asserted here only as "materially smaller" -- the real number
is a production reading (`ledger_coverage.projected_bytes`), not a fixture's.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import evaluation_ledger_projection as proj
from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path


def _write_chunk(root, date_token, count, padding=400):
    """`padding` is NOT a projected field, so it is exactly the bulk the
    projection must drop."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{date_token}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for i in range(count):
            handle.write(json.dumps({
                "recommendation_id": f"{date_token}-{i}",
                "record_type": "recommendation",
                "result": "win" if i % 2 else "loss",
                "recommendation": {"sport": "mlb", "market": "moneyline"},
                "artifact_metadata": {"sport": "mlb", "selected_date": date_token},
                "padding": "x" * padding,
            }, separators=(",", ":")) + "\n")
    return path


@pytest.fixture()
def roots(tmp_path):
    return tmp_path / "evaluation_ledger_chunks", tmp_path / "evaluation_ledger_projected"


# --------------------------------------------------------------------------
# The allowlist. Highest consequence in the file.
# --------------------------------------------------------------------------

def test_projected_path_is_allowlisted():
    assert is_hot_artifact_relative_path(
        "reports/intelligence/evaluation_ledger_projected/2026-09-01.jsonl"
    ), "the projected mirror cannot cross to web unless it is allowlisted"


def test_RAW_chunks_are_NOT_allowlisted():
    """The whole point of projecting. A glob loose enough to match the raw
    chunks would hand the sweep a 332 MB file on every cycle."""
    assert not is_hot_artifact_relative_path(
        "reports/intelligence/evaluation_ledger_chunks/2026-09-01.jsonl"
    ), "RAW chunks must never be publishable -- they are 8-27x the 12 MiB ceiling"


def test_projected_root_is_a_sibling_not_a_child_of_the_chunk_root(roots):
    chunk_root, _ = roots
    out = proj.projected_chunk_root(chunk_root)
    assert out.name == "evaluation_ledger_projected"
    assert out.parent == chunk_root.parent
    assert chunk_root not in out.parents, (
        "nesting the mirror inside the chunk root would let one glob match both"
    )


# --------------------------------------------------------------------------
# Producing
# --------------------------------------------------------------------------

def test_projects_and_materially_shrinks(roots):
    chunk_root, out_root = roots
    _write_chunk(chunk_root, "2026-09-01", 40)

    stats = proj.project_ledger_chunks(chunk_root=chunk_root, out_root=out_root, publish=False)

    assert stats["chunks_written"] == 1
    assert stats["records"] == 40
    assert (out_root / "2026-09-01.jsonl").is_file()
    assert stats["bytes_out"] < stats["bytes_in"] * 0.5, (
        f"ratio {stats['ratio']} -- the mirror exists to shrink the ledger"
    )


def test_output_is_valid_jsonl_and_carries_projected_fields_only(roots):
    chunk_root, out_root = roots
    _write_chunk(chunk_root, "2026-09-01", 5)
    proj.project_ledger_chunks(chunk_root=chunk_root, out_root=out_root, publish=False)

    lines = (out_root / "2026-09-01.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 5
    for line in lines:
        record = json.loads(line)
        assert "recommendation_id" in record, "identity must survive projection"
        assert "padding" not in record, "unprojected bulk must be dropped"


def test_malformed_lines_are_skipped_not_fatal(roots):
    chunk_root, out_root = roots
    path = _write_chunk(chunk_root, "2026-09-01", 3)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
        handle.write("\n")

    stats = proj.project_ledger_chunks(chunk_root=chunk_root, out_root=out_root, publish=False)
    assert stats["chunks_failed"] == 0
    assert stats["records"] == 3, "a bad line costs its record, never the day"


# --------------------------------------------------------------------------
# Incremental + bounded. These are what keep it off the worker's critical path.
# --------------------------------------------------------------------------

def test_second_run_is_a_no_op(roots):
    chunk_root, out_root = roots
    _write_chunk(chunk_root, "2026-09-01", 10)
    proj.project_ledger_chunks(chunk_root=chunk_root, out_root=out_root, publish=False)

    again = proj.project_ledger_chunks(chunk_root=chunk_root, out_root=out_root, publish=False)
    assert again["chunks_written"] == 0
    assert again["chunks_fresh"] == 1, "an unchanged chunk must not be re-streamed"


def test_a_changed_source_is_reprojected(roots):
    chunk_root, out_root = roots
    _write_chunk(chunk_root, "2026-09-01", 10)
    proj.project_ledger_chunks(chunk_root=chunk_root, out_root=out_root, publish=False)

    # Today's chunk is appended to continuously; the mirror must follow it.
    _write_chunk(chunk_root, "2026-09-01", 20)
    again = proj.project_ledger_chunks(chunk_root=chunk_root, out_root=out_root, publish=False)
    assert again["chunks_written"] == 1
    assert again["records"] == 20


def test_max_chunks_bounds_a_run_and_the_rest_is_deferred_not_lost(roots):
    chunk_root, out_root = roots
    for day in range(1, 6):
        _write_chunk(chunk_root, f"2026-09-0{day}", 4)

    first = proj.project_ledger_chunks(
        chunk_root=chunk_root, out_root=out_root, max_chunks=2, publish=False
    )
    assert first["chunks_written"] == 2
    assert first["chunks_deferred"] == 3, "the remainder must be reported, not silently dropped"

    second = proj.project_ledger_chunks(
        chunk_root=chunk_root, out_root=out_root, max_chunks=2, publish=False
    )
    assert second["chunks_written"] == 2
    assert second["chunks_fresh"] == 2, "already-done chunks must not be redone"


def test_newest_chunks_are_projected_first(roots):
    chunk_root, out_root = roots
    for day in range(1, 5):
        _write_chunk(chunk_root, f"2026-09-0{day}", 4)

    proj.project_ledger_chunks(
        chunk_root=chunk_root, out_root=out_root, max_chunks=2, publish=False
    )
    written = sorted(p.name for p in out_root.glob("*.jsonl"))
    assert written == ["2026-09-03.jsonl", "2026-09-04.jsonl"], (
        "the budget must buy the RECENT days -- drift and reliability want those"
    )


def test_no_temp_file_is_left_behind(roots):
    chunk_root, out_root = roots
    _write_chunk(chunk_root, "2026-09-01", 5)
    proj.project_ledger_chunks(chunk_root=chunk_root, out_root=out_root, publish=False)

    assert list(out_root.glob("*.tmp")) == [], (
        "a stray .tmp is a partial artifact a glob could publish"
    )


def test_missing_chunk_root_is_survivable(tmp_path):
    stats = proj.project_ledger_chunks(
        chunk_root=tmp_path / "nope", out_root=tmp_path / "out", publish=False
    )
    assert stats["chunks_seen"] == 0
    assert stats["chunks_written"] == 0


def test_over_ceiling_is_reported_rather_than_shipped(roots, monkeypatch, capsys):
    """The falsifier for the ~3.3 MB sizing. If a projection ever approaches the
    sweep's 12 MiB refusal threshold it must SAY SO -- a silently refused file
    is how the biggest artifacts ended up with no repair path (`468faace`)."""
    chunk_root, out_root = roots
    _write_chunk(chunk_root, "2026-09-01", 10)
    monkeypatch.setattr(proj, "PROJECTION_CEILING_WARN_BYTES", 10)

    stats = proj.project_ledger_chunks(chunk_root=chunk_root, out_root=out_root, publish=False)
    assert stats["over_ceiling"] == 1
    assert "PROJECTION_OVER_CEILING" in capsys.readouterr().out
