"""#334. A freshness verdict must be computed when it is READ, not when it is written.

Measured on production 2026-08-10T17:31:44Z: the served board reported

    snapshot_generated_at  16:47:05Z      TRUE age 2679s (44.7 min)
    freshness.age_seconds  0.142836...    freshness_status "fresh"   sla 60

44x over its own SLA and self-reporting healthy, across all three blocks and
their `status.*` copies. Cause: `state_meta` is persisted INTO the snapshot
payload, so `_decorate_response_with_state_meta`'s `setdefault` found it already
present on every read, kept the stored one, and discarded the freshly computed
one. The verdict was frozen at the instant the snapshot was built.

Separate file from `test_intelligence_state.py`, which is large and edited by
several lanes.
"""
from __future__ import annotations

import datetime
import unittest

import pipeline.intelligence_state as intelligence_state


def _iso(offset_seconds: float) -> str:
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=offset_seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _persisted_response(age_seconds: float) -> dict:
    """The production shape: a stale verdict already baked into the payload."""
    block = {
        "computed_at": _iso(age_seconds),
        "age_seconds": 0.142836,        # what the write-time computation stored
        "freshness_sla_seconds": 60,
        "freshness_status": "fresh",
        "is_fresh": True,
        "source_fingerprint": "fp",
        "run_key": "k",
    }
    return {
        "candidate_count": 23,
        "state_meta": dict(block),
        "freshness": dict(block),
        "state_freshness": dict(block),
    }


class StaleBoardMustNotReportFreshTests(unittest.TestCase):
    def test_the_exact_production_case(self) -> None:
        # 2,679 seconds old against a 60-second SLA, previously "fresh".
        out = intelligence_state._decorate_response_with_state_meta(
            _persisted_response(2679), None, source="worker", run_key="k", sla_seconds=60
        )
        for key in ("state_meta", "freshness", "state_freshness"):
            block = out[key]
            self.assertGreater(block["age_seconds"], 2000, f"{key} must age")
            self.assertEqual(block["freshness_status"], "stale", key)
            self.assertFalse(block["is_fresh"], key)

    def test_a_genuinely_fresh_board_still_reads_fresh(self) -> None:
        # The fix must not simply mark everything stale -- that would be a
        # different broken instrument with the same confidence.
        out = intelligence_state._decorate_response_with_state_meta(
            _persisted_response(2), None, source="worker", run_key="k", sla_seconds=60
        )
        self.assertEqual(out["state_meta"]["freshness_status"], "fresh")
        self.assertTrue(out["state_meta"]["is_fresh"])

    def test_identity_fields_are_preserved(self) -> None:
        # Only the derived verdict is rebuilt; the snapshot's identity is not.
        out = intelligence_state._decorate_response_with_state_meta(
            _persisted_response(2679), None, source="worker", run_key="k", sla_seconds=60
        )
        block = out["state_meta"]
        self.assertEqual(block["source_fingerprint"], "fp")
        self.assertEqual(block["run_key"], "k")
        self.assertTrue(block["computed_at"])


class RecomputedFreshnessBlockTests(unittest.TestCase):
    def test_unparseable_timestamp_is_unknown_and_not_fresh(self) -> None:
        # `unknown` must not land on the healthy branch -- that is the
        # permissive-on-unknown shape #324 and #332 both turned on.
        block = intelligence_state._recomputed_freshness_block(
            {"computed_at": "not-a-timestamp", "freshness_sla_seconds": 60}
        )
        self.assertEqual(block["freshness_status"], "unknown")
        self.assertFalse(block["is_fresh"])

    def test_it_uses_the_blocks_own_sla_when_present(self) -> None:
        block = intelligence_state._recomputed_freshness_block(
            {"computed_at": _iso(120), "freshness_sla_seconds": 300}, sla_seconds=60
        )
        self.assertEqual(block["freshness_sla_seconds"], 300)
        self.assertEqual(block["freshness_status"], "fresh", "120s is inside a 300s SLA")

    def test_a_missing_sla_falls_back_rather_than_dividing_by_nothing(self) -> None:
        block = intelligence_state._recomputed_freshness_block(
            {"computed_at": _iso(5)}, sla_seconds=60
        )
        self.assertEqual(block["freshness_sla_seconds"], 60)
        self.assertEqual(block["freshness_status"], "fresh")

    def test_each_block_ages_from_its_OWN_computed_at(self) -> None:
        # A payload assembled from several sources must not inherit one age.
        response = _persisted_response(2679)
        response["freshness"]["computed_at"] = _iso(3)
        out = intelligence_state._decorate_response_with_state_meta(
            response, None, source="worker", run_key="k", sla_seconds=60
        )
        self.assertEqual(out["state_meta"]["freshness_status"], "stale")
        self.assertEqual(out["freshness"]["freshness_status"], "fresh")


if __name__ == "__main__":
    unittest.main()
