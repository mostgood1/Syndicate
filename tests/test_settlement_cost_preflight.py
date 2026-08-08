"""Pin the one property that makes settlement_cost_preflight safe to run on
refresh-worker: the default projection NEVER OPENS A LEDGER CHUNK.

Reading a production chunk is itself the ~1.4GB allocation the tool exists to
predict (2026-08-05 measured 367,229,260 bytes; 4.1x parsed). A prober that read
the chunks to size them would be the outage it was written to forecast, and the
regression would be invisible -- it would still print correct numbers, just after
having spent the memory. So the read-avoidance is asserted, not assumed.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from scripts import settlement_cost_preflight as preflight


@pytest.fixture()
def ledger_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    chunks = tmp_path / "evaluation_ledger_chunks"
    chunks.mkdir()
    (chunks / "2026-08-05.jsonl").write_text('{"record_type":"recommendation"}\n' * 50, encoding="utf-8")
    (chunks / "2026-08-06.jsonl").write_text('{"record_type":"recommendation"}\n' * 10, encoding="utf-8")
    (chunks / "index.json").write_text(json.dumps({"records": {"a": {"chunk": "2026-08-05"}}}), encoding="utf-8")

    ledger = tmp_path / "evaluation_ledger.jsonl"
    monkeypatch.setattr(
        "syndicate.features.shared.intelligence_evaluation.DEFAULT_LEDGER_PATH", ledger, raising=False
    )
    return chunks


def test_projection_never_opens_a_chunk(ledger_tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real_open = builtins.open
    real_path_open = Path.open

    def _record(name: object) -> None:
        text = str(name)
        if text.endswith(".jsonl"):
            opened.append(text)

    def spy_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        _record(file)
        return real_open(file, *args, **kwargs)

    def spy_path_open(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        _record(self)
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(Path, "open", spy_path_open)

    report = preflight.project(["2026-08-05", "2026-08-06", "2026-08-07"])

    assert opened == [], f"projection opened ledger chunks: {opened}"
    assert report["chunks_present"] == 2
    assert report["chunks_missing"] == 1
    assert report["peak_chunk"]["date"] == "2026-08-05"
    # The peak is the LARGEST chunk, not the sum -- the autorun holds one date at
    # a time (#256), so summing would overstate the run by ~21x.
    assert report["peak_chunk"]["json_mb"] >= report["chunks"][1]["json_mb"]


def test_projected_peak_includes_the_chunk_index_term(ledger_tree: Path) -> None:
    """The index round trip is per-SETTLED-RECORD and unbounded by the slate --
    it is the term that is invisible in production (not allowlisted, and
    refresh-worker serves no HTTP), so it must not be silently dropped."""
    report = preflight.project(["2026-08-05"])
    index = report["chunk_index"]
    assert index["exists"] is True
    assert index["bytes"] > 0
    assert report["projected_peak_rss_mb"] >= report["peak_chunk"]["projected_rss_mb"]


def test_index_term_scales_with_index_size(ledger_tree: Path) -> None:
    """The index cost is derived from FILE SIZE, never from reading the file --
    a 92MB production index costs ~238MB to load, which the projection must not
    spend in order to report it."""
    small = preflight.project(["2026-08-05"])["chunk_index"]
    (ledger_tree / "index.json").write_text(
        json.dumps({"records": {f"r{i}": {"chunk": "2026-08-05"} for i in range(20_000)}}, indent=2),
        encoding="utf-8",
    )
    large = preflight.project(["2026-08-05"])["chunk_index"]
    assert large["bytes"] > small["bytes"]
    assert large["rss_mb_per_settled_record"] > small["rss_mb_per_settled_record"]
    assert large["seconds_per_settled_record"] > small["seconds_per_settled_record"]
