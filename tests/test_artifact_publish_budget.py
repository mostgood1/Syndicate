"""`#394`/`#395` -- the publisher had no notion of how much it had sent.

On 2026-08-12 outbound bandwidth reached 1.62 TB for the month climbing
~7.8 GB/hr, and both workers had to be suspended BY HAND to stop it. Nothing in
the publisher could have stopped it automatically. Two defects underneath:

  #394  the sha256 was computed, sent in the request body, and never compared,
        so unchanged artifacts re-uploaded in full on every sweep
  #395  no egress ceiling existed at any layer

These are separate and neither substitutes for the other: de-duplication does
nothing for artifacts that genuinely change every cycle, which odds artifacts
legitimately do.
"""

from __future__ import annotations

import importlib

import pytest

ap = importlib.import_module("syndicate.features.shared.artifact_publisher")


@pytest.fixture(autouse=True)
def _clean_budget_state(monkeypatch):
    monkeypatch.setattr(ap, "_PUBLISH_BYTES", [])
    monkeypatch.setattr(ap, "_LAST_PUBLISHED_CHECKSUM", {})
    monkeypatch.setattr(ap, "_PUBLISH_BUDGET_COUNTER", [0])
    yield


def test_a_publish_under_the_ceiling_is_allowed():
    assert ap._publish_budget_blocks("a.json", 1024) is False


def test_the_ceiling_blocks_before_the_upload_not_after():
    """The breaker must PREVENT the spend. A check after the request would
    report the overage having already paid for it."""
    ceiling = ap._publish_budget_max_bytes()
    ap._publish_budget_record(ceiling)
    assert ap._publish_budget_blocks("a.json", 1) is True


def test_bytes_accumulate_across_publishes():
    for _ in range(4):
        ap._publish_budget_record(1024 * 1024)
    assert ap._publish_budget_used_bytes() == 4 * 1024 * 1024


def test_the_window_rolls_so_a_breaker_recovers(monkeypatch):
    """A tripped breaker must clear itself as the window moves. A latched
    refusal that nothing can reset is an outage, not a safety mechanism."""
    ceiling = ap._publish_budget_max_bytes()
    ap._publish_budget_record(ceiling)
    assert ap._publish_budget_blocks("a.json", 1) is True

    real_time = ap.time.time
    monkeypatch.setattr(
        ap.time, "time", lambda: real_time() + ap._PUBLISH_BUDGET_WINDOW_SECONDS + 1
    )
    assert ap._publish_budget_used_bytes() == 0
    assert ap._publish_budget_blocks("a.json", 1) is False


def test_the_budget_is_env_tunable(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PUBLISH_HOURLY_BYTE_BUDGET", "4096")
    assert ap._publish_budget_max_bytes() == 4096
    ap._publish_budget_record(4096)
    assert ap._publish_budget_blocks("a.json", 1) is True


def test_a_junk_env_value_falls_back_to_the_default_rather_than_zero(monkeypatch):
    """A ceiling of 0 would block every upload. An unparseable value must not
    silently become the most restrictive possible setting."""
    for junk in ("", "nope", "-5", "0"):
        monkeypatch.setenv("SYNDICATE_PUBLISH_HOURLY_BYTE_BUDGET", junk)
        assert ap._publish_budget_max_bytes() == ap._PUBLISH_BUDGET_DEFAULT_BYTES


def test_an_oversized_single_file_is_refused_rather_than_sent():
    monkeypatch_size = ap._publish_budget_max_bytes() + 1
    assert ap._publish_budget_blocks("huge.json", monkeypatch_size) is True


def test_the_dedupe_store_records_only_after_success():
    """A failed upload must retry on the next sweep. If the checksum were
    stored on attempt, one transient failure would suppress the file forever."""
    assert ap._LAST_PUBLISHED_CHECKSUM == {}
