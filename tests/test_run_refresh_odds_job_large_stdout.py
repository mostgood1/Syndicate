"""The odds-job wrapper keeps a bounded head + tail of each child stream.

Lane `refresh-job-parse-linear` (2026-10-06): a child that printed 106 MB of stdout and
1.6 GB of stderr left the wrapper at 2.5 GB RSS for 35+ minutes after the child exited,
holding the refresh-worker container at 91% of 4 GB.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "run_refresh_odds_job_output_cap", Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_odds_job.py"
)
job = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(job)


def test_small_output_is_kept_whole():
    chunks = job._BoundedChunks(head_chars=100, tail_chars=100)
    for line in ("a\n", "b\n"):
        chunks.append(line)
    assert "".join(chunks) == "a\nb\n"
    assert chunks.total_chars == 4 and not chunks.capped


def test_large_output_keeps_head_and_tail_and_counts_the_rest():
    chunks = job._BoundedChunks(head_chars=1_000, tail_chars=1_000)
    for i in range(100_000):
        chunks.append(f"noise line {i:06d}\n")
    text = "".join(chunks)
    assert chunks.capped
    assert chunks.total_chars == sum(len(f"noise line {i:06d}\n") for i in range(100_000))
    assert len(text) < 3_000
    assert text.startswith("noise line 000000")
    assert text.rstrip().endswith("noise line 099999")
    assert "[refresh_job_output_capped]" in text


def test_the_result_json_printed_last_survives_the_cap():
    chunks = job._BoundedChunks(head_chars=1_000, tail_chars=50_000)
    for i in range(50_000):
        chunks.append(f"noise {i}\n")
    chunks.append(json.dumps({"ok": True, "results": [1, 2, 3]}, indent=2) + "\n")
    assert job._result_payload_from_stdout("".join(chunks)).get("ok") is True


def test_the_live_echo_stops_after_the_head_with_one_notice():
    chunks = job._BoundedChunks(head_chars=100, tail_chars=100)
    pipe = io.StringIO("".join(f"line {i}\n" for i in range(1_000)))
    out = io.StringIO()
    job._stream_child_output(pipe, chunks=chunks, target_stream=out)
    echoed = out.getvalue()
    assert len(echoed) < 400
    assert echoed.count("[refresh_job_output_echo_capped]") == 1
    assert chunks.total_chars == sum(len(f"line {i}\n") for i in range(1_000))
