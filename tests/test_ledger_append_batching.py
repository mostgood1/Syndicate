"""A ledger session writes the SAME files as per-record appends, with one count per chunk.

Lane `web-restart-healthz` `[2026-10-07]`: py-spy on the fleet refresh-worker found 30.5%
of the board loop in `maybe_record_board_state_to_evaluation_ledger`, because every
appended record re-streamed the whole day chunk (`_count_jsonl_records`) and rewrote
the index and manifest. Inside `ledger_index_session` the index is written once and
each touched chunk is counted once, at exit. The files on disk must not change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features.shared import intelligence_evaluation as ie

_REAL_COUNT = ie._count_jsonl_records


def _records(n: int) -> list[dict]:
    out = []
    for i in range(n):
        day = "2026-10-06" if i % 3 else "2026-10-07"
        out.append({"record_type": "recommendation", "recommendation_id": f"r{i}", "created_at": f"{day}T12:00:00Z",
                    "query": {"selected_date": day}, "payload": {"i": i}})
    return out


def _snapshot(root: Path) -> dict:
    chunks = root / "evaluation_ledger_chunks"
    files = {p.name: p.read_text(encoding="utf-8") for p in sorted(chunks.glob("*.jsonl"))}
    index = json.loads((chunks / "index.json").read_text(encoding="utf-8"))["records"]
    index = {k: {kk: vv for kk, vv in v.items() if kk not in {"updated_at", "path"}} for k, v in index.items()}
    manifest = json.loads((chunks / "manifest.json").read_text(encoding="utf-8"))["chunks"]
    manifest = sorted((m["chunk"], m["record_count"]) for m in manifest)
    return {"files": files, "index": index, "manifest": manifest}


def _write_all(tmp: Path, monkeypatch, *, session: bool, counter: dict) -> dict:
    ledger = tmp / "reports" / "intelligence" / "evaluation_ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    monkeypatch.setattr(ie, "DEFAULT_LEDGER_PATH", ledger)
    def counting(path):
        counter["n"] += 1
        return _REAL_COUNT(path)

    monkeypatch.setattr(ie, "_count_jsonl_records", counting)
    records = _records(30)
    if session:
        with ie.ledger_index_session(None):
            for record in records:
                ie._append_evaluation_ledger_record(ledger, record)
    else:
        for record in records:
            ie._append_evaluation_ledger_record(ledger, record)
    return _snapshot(ledger.parent)


def test_a_session_writes_identical_files_with_one_count_per_chunk(tmp_path, monkeypatch):
    if ie._ledger_record_chunk_name(_records(1)[0]) == ie._ledger_record_chunk_name(_records(2)[1]):
        pytest.skip("chunking does not split these test dates")
    plain_counter, session_counter = {"n": 0}, {"n": 0}
    plain = _write_all(tmp_path / "plain", monkeypatch, session=False, counter=plain_counter)
    batched = _write_all(tmp_path / "batched", monkeypatch, session=True, counter=session_counter)
    assert batched == plain
    assert plain_counter["n"] == 30                     # once per record, as before
    assert session_counter["n"] == len(plain["files"])  # once per touched chunk


def test_outside_a_session_nothing_is_deferred(tmp_path, monkeypatch):
    counter = {"n": 0}
    snap = _write_all(tmp_path / "x", monkeypatch, session=False, counter=counter)
    assert sum(count for _chunk, count in snap["manifest"]) == 30
