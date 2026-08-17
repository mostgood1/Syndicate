"""The evaluation bundle must load a BOUNDED ledger window on the hot path.

Named by stack dump 2026-08-17 03:48:28-33Z: three dumps inside one excursion
put the intelligence-state background loop inside this bundle twice, in two
frames of the same chain, while anon climbed 100+ MB/s --
`_latest_by_recommendation_id` over `_stream_chunked_ledger_records`, and
`_aggregate_performance_rows`. Region #1 grew 764.7 -> 1041.3 -> 1260.4 MB
across those samples with every other mapping static.

The unbounded load was `LEDGER_CHUNKS_ACCEPTED count=8 bytes=830,832,574
records=22,078` feeding a bundle reporting `recommendation_count=60` and
`sample_size=0` in `duration_ms=49706`.

`load_recent_evaluation_records` already existed for exactly this ("Bounded,
safe evaluation-record load for hot paths ... an instant OOM") and the bundle
was not using it. It applies TWO bounds: a date window AND a 64MB per-chunk
ceiling, four times tighter than the 256MB global one that lets 830MB through.
"""

from __future__ import annotations

import inspect

import pytest

from syndicate.features.shared import intelligence_evaluation as ie


# --- the window helper --------------------------------------------------------

def test_default_window_matches_the_function_it_feeds():
    """A constant that disagrees with the function it feeds is how the
    3000MB/1500MB headroom floors drifted out of meaning."""
    sig = inspect.signature(ie.load_recent_evaluation_records)
    assert ie._bundle_ledger_window_days() == sig.parameters["days"].default


def test_window_is_env_tunable(monkeypatch):
    """Widening must not need a code deploy; narrowing must be fast."""
    monkeypatch.setenv("SYNDICATE_BUNDLE_LEDGER_WINDOW_DAYS", "3")
    assert ie._bundle_ledger_window_days() == 3


@pytest.mark.parametrize("bad", ["0", "-5", "not-a-number", ""])
def test_window_never_collapses_to_nothing(monkeypatch, bad):
    """A zero window would load nothing and report empty analytics as though the
    ledger were empty -- indistinguishable from a broken ledger."""
    monkeypatch.setenv("SYNDICATE_BUNDLE_LEDGER_WINDOW_DAYS", bad)
    assert ie._bundle_ledger_window_days() >= 1


# --- the call site, which is the whole point ----------------------------------

def test_bundle_uses_the_bounded_reader_not_the_unbounded_stream():
    src = inspect.getsource(ie.build_intelligence_evaluation_bundle)
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "load_recent_evaluation_records(" in code, "bundle is not using the bounded reader"
    assert "_stream_record_payloads(ledger_path=" not in code.replace(" ", ""), (
        "bundle still has an UNBOUNDED ledger stream -- that is the allocator the "
        "stack dump named"
    )


def test_bundle_still_threads_one_shared_load_to_both_consumers():
    """Bounding must not undo the single-scan fix."""
    src = inspect.getsource(ie.build_intelligence_evaluation_bundle)
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#")).replace(" ", "")
    assert "shared_ledger_records" in code
    assert "records=None" not in code, "a consumer is back to re-loading for itself"


def test_the_bounded_reader_keeps_its_own_chunk_ceiling():
    """The date window alone is not the protection.

    The 64MB per-chunk ceiling is four times tighter than the 256MB global one,
    and the chunks this worker ACCEPTS today average ~104MB -- exactly what a
    hot path should refuse.
    """
    sig = inspect.signature(ie.load_recent_evaluation_records)
    ceiling = sig.parameters["max_chunk_bytes"].default
    assert ceiling <= 64_000_000
    assert ceiling < 256_000_000, "hot-path ceiling must be tighter than the global one"
