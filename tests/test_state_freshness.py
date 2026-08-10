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


class TheReadPathThatActuallyServesStatusTests(unittest.TestCase):
    """#334 second attempt. The first fix went into
    `_decorate_response_with_state_meta` and shipped INERT: the route serving
    `/api/intelligence/status` calls `_decorate_intelligence_board_snapshot_response`
    instead and hands back the persisted blocks untouched.

    Measured on deployed web: a board 436.4s old reporting `fresh` on all six
    blocks, with sub-values 0.071745 / 0.071749 / 0.071753 -- three sequential
    write-time computations microseconds apart, persisted. So the recompute now
    lives in `_expand_persisted_state`, the one function every persisted read
    funnels through, rather than in whichever decorator a route happens to use.
    """

    def _persisted(self, age_seconds: float) -> dict:
        block = {
            "computed_at": _iso(age_seconds),
            "age_seconds": 0.071745,
            "freshness_sla_seconds": 60,
            "freshness_status": "fresh",
            "is_fresh": True,
            "source_fingerprint": "fp",
        }
        return {
            "candidate_count": 150,
            "state_meta": dict(block),
            "freshness": dict(block),
            "state_freshness": dict(block),
            "response": {
                "recommendations": [{"a": 1}],
                "state_meta": dict(block),
                "freshness": dict(block),
                "state_freshness": dict(block),
            },
        }

    def test_expand_recomputes_all_six_blocks(self) -> None:
        # Six is the number oversight measured: three blocks plus their
        # `status.*` copies, which come from the nested `response`.
        out = intelligence_state._expand_persisted_state(self._persisted(436.4))
        for container, label in ((out, "top"), (out["response"], "response")):
            for key in ("state_meta", "freshness", "state_freshness"):
                block = container[key]
                self.assertGreater(block["age_seconds"], 400, f"{label}.{key}")
                self.assertEqual(block["freshness_status"], "stale", f"{label}.{key}")
                self.assertFalse(block["is_fresh"], f"{label}.{key}")

    def test_it_does_not_disturb_the_board_payload(self) -> None:
        # _expand_persisted_state is #317/#322's alias/compression choke point.
        # Touching it must not perturb what it was already doing.
        out = intelligence_state._expand_persisted_state(self._persisted(436.4))
        self.assertEqual(out["response"]["recommendations"], [{"a": 1}])
        self.assertEqual(out["candidate_count"], 150)

    def test_a_fresh_persisted_board_still_reads_fresh(self) -> None:
        out = intelligence_state._expand_persisted_state(self._persisted(3))
        self.assertEqual(out["state_meta"]["freshness_status"], "fresh")
        self.assertEqual(out["response"]["state_meta"]["freshness_status"], "fresh")

    def test_payloads_without_freshness_blocks_are_untouched(self) -> None:
        plain = {"candidate_count": 5, "response": {"recommendations": []}}
        self.assertEqual(intelligence_state._expand_persisted_state(dict(plain)), plain)
if __name__ == "__main__":
    unittest.main()
