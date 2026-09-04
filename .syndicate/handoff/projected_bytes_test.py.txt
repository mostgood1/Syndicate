"""`#626`(h) -- `projected_bytes`: what a PROJECTED ledger would cost on disk.

WHY THIS TEST EXISTS. On 2026-09-04 the question "can a projected daily chunk
publish under the 12 MiB sweep ceiling, so the ledger can be mirrored and the
summary computed off the worker?" was answered by an INFERENCE joining two
substrates: a CHECKOUT per-record projection cost (~560 B, saturating) against
production's RENDER raw density (42,595 B/record). Two substrates is not one
measurement. This field is what makes it a reading on the next autorun.

The property pinned here is deliberately NOT the exact byte count, which moves
with the records. It is that `projected_bytes`:

  * is PRESENT in the published `ledger_coverage` -- not only on stdout. The
    2026-09-04 truncation was discoverable only off the worker's log, which is
    the failure this repo has already paid for once;
  * survives the `stats.update()` inside `_stream_chunked_ledger_records`,
    which runs when the generator drains and would clobber a key set earlier;
  * is MATERIALLY smaller than `bytes_accepted`, because a projection that does
    not shrink the record is not a projection, and the entire mirror design
    rests on it shrinking;
  * is 0 rather than ABSENT when nothing was read -- absent and zero are
    different facts, and collapsing them is how "no data" gets read as "not
    instrumented".
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import intelligence_evaluation as ie


ENV_KEY = "SYNDICATE_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES"


def _write_chunk(root, date_token, count, padding=400):
    """`padding` is deliberately NOT in any projected field list, so it is
    exactly the bulk a projection is supposed to drop."""
    chunk_root = root / "evaluation_ledger_chunks"
    chunk_root.mkdir(parents=True, exist_ok=True)
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
                "padding": "x" * padding,
            }, separators=(",", ":")) + "\n")
    return chunk_root


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_KEY, "0")  # unlimited: this test is about size, not the bound
    path = tmp_path / "evaluation_ledger.jsonl"
    # REQUIRED, and its absence fails in a way that looks like a code bug:
    # `_is_chunked_ledger_path` compares against DEFAULT_LEDGER_PATH, so an
    # un-patched tmp path is not recognised as chunked, the chunk dir is never
    # read, and `ledger_coverage` comes back with the stream's keys MISSING
    # rather than zero. Same convention as test_accuracy_summary_ledger_budget.
    monkeypatch.setattr(ie, "DEFAULT_LEDGER_PATH", path)
    _write_chunk(tmp_path, "2026-09-01", 50)
    return path


def test_projected_bytes_is_published_in_ledger_coverage(ledger):
    summary = ie.build_accuracy_summary(ledger_path=ledger, sport="mlb")
    coverage = summary.get("ledger_coverage") or {}

    assert "projected_bytes" in coverage, (
        "projected_bytes must reach the PUBLISHED artifact, not just stdout -- "
        "a number only visible in the worker's log is the exact gap this closes."
    )
    assert coverage["projected_bytes"] > 0
    assert coverage["bytes_accepted"] > 0


def test_projection_materially_shrinks_the_record(ledger):
    summary = ie.build_accuracy_summary(ledger_path=ledger, sport="mlb")
    coverage = summary["ledger_coverage"]

    accepted = coverage["bytes_accepted"]
    projected = coverage["projected_bytes"]

    assert projected < accepted, "a projection that does not shrink is not a projection"
    # The fixture is ~400 B of unprojected padding per record against a handful
    # of projected scalars, so the reduction is large. Asserted as a RATIO with
    # slack rather than a byte count, because the count moves with the fixture.
    assert projected < accepted * 0.5, (
        f"projected {projected} B is {projected / accepted:.3f} of accepted "
        f"{accepted} B -- the mirror design needs a material reduction here"
    )


def test_projected_bytes_survives_the_streams_stats_update(ledger):
    """`_stream_chunked_ledger_records` ends with `stats.update({...})`, which
    runs when the generator DRAINS -- i.e. after the projection has been
    counting. A key written before that call is silently clobbered, and the
    symptom is an absent field rather than a wrong one."""
    summary = ie.build_accuracy_summary(ledger_path=ledger, sport="mlb")
    coverage = summary["ledger_coverage"]

    for key in ("bytes_accepted", "records", "dates_covered", "projected_bytes"):
        assert key in coverage, f"{key} missing -- ordering regression around stats.update()"


def test_zero_records_reports_zero_not_absent(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_KEY, "0")
    path = tmp_path / "evaluation_ledger.jsonl"
    monkeypatch.setattr(ie, "DEFAULT_LEDGER_PATH", path)
    # An EMPTY chunk dir, not a missing one: this must exercise the real read
    # path and find nothing, otherwise it passes without the instrument ever
    # running -- which is how a test comes back green for the wrong reason.
    (tmp_path / "evaluation_ledger_chunks").mkdir(parents=True, exist_ok=True)
    summary = ie.build_accuracy_summary(ledger_path=path, sport="mlb")
    coverage = summary.get("ledger_coverage") or {}

    assert coverage.get("projected_bytes") == 0, (
        "absent and zero are different facts: absent means the instrument is "
        "not there, zero means it ran and read nothing."
    )
