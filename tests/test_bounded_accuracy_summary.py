"""`_bounded_accuracy_summary` — the two defects measured 2026-09-02.

This function is what stands between a growing reliability surface and an 8MB
keyvalue ceiling. It did neither of the things it claimed:

1. **It truncated the wrong container, so it never truncated.**
   `build_accuracy_summary` returns `segmented_reliability` as a MAPPING
   `{global, shrinkage_k, segments}` and the growing thing is the inner
   `segments` LIST. `list(mapping.items())[:50]` sliced three fixed top-level
   keys. Measured on a real summary: `segments_total` reported **3** while
   `len(segments)` was **7**, `segments_truncated` was pinned **False**, and the
   "bounded" payload was **LARGER** than the raw one (3,585 vs 3,535 bytes).
   Every existing test passed, because a cap that never fires is
   indistinguishable from a cap that is never needed.

2. **It dropped `ledger_coverage`** — it builds from a field whitelist, so the
   byte-budget coverage block added upstream for `#626`(h) never reached the
   published artifact. At a 90MB budget against 95-332 MB/day chunks the summary
   rests on ONE DAY against a 28-day drift window; without the coverage block
   nothing downstream can tell.

These tests are written so the PRE-FIX code fails them. A test that a cap
"returns a dict" would have passed throughout.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_worker():
    spec = importlib.util.spec_from_file_location(
        "run_refresh_worker_bounded_under_test", REPO_ROOT / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _summary(n_segments: int, *, weights=None, coverage=None):
    segments = []
    for i in range(n_segments):
        segments.append({
            "sport": "mlb",
            "market_family": "market_%d" % i,
            "confidence_tier": "tier_%d" % i,
            "decisive_count": (weights[i] if weights else 0),
            "win_rate": 0.5,
        })
    return {
        "sport": "mlb",
        "generated_at": "2026-09-02T00:00:00Z",
        "sample_size": 100,
        "settled_count": 40,
        "metrics": {"win_rate": 0.5},
        "drift": {"window": {}},
        "segmented_reliability": {
            "global": {"win_rate": 0.5},
            "shrinkage_k": 20.0,
            "segments": segments,
        },
        "ledger_coverage": coverage if coverage is not None else {
            "budget_bytes": 90000000,
            "bytes_accepted": 89967617,
            "chunks_accepted": 1,
            "chunks_partial": 1,
            "chunks_skipped_budget": 7,
            "dates_covered": 1,
            "date_min": "2026-08-08",
            "date_max": "2026-08-08",
            "truncated": True,
            "records": 2002,
        },
    }


class BoundedAccuracySummaryTests(unittest.TestCase):
    def setUp(self):
        self.worker = _load_worker()

    def test_segments_total_counts_segments_not_mapping_keys(self):
        """Pre-fix this returned 3 -- the count of {global, shrinkage_k,
        segments} -- for ANY number of segments."""
        out = self.worker._bounded_accuracy_summary(_summary(7), max_segments=50)
        self.assertEqual(out["segments_total"], 7)
        self.assertNotEqual(
            out["segments_total"], 3,
            "segments_total is counting the mapping's top-level keys again",
        )

    def test_truncation_actually_fires(self):
        """Pre-fix `segments_truncated` was False at any coverage, because 3 is
        never > 50."""
        out = self.worker._bounded_accuracy_summary(_summary(120), max_segments=50)
        self.assertTrue(out["segments_truncated"])
        self.assertEqual(out["segments_total"], 120)
        self.assertEqual(len(out["segmented_reliability"]["segments"]), 50)

    def test_not_truncated_when_under_cap(self):
        out = self.worker._bounded_accuracy_summary(_summary(4), max_segments=50)
        self.assertFalse(out["segments_truncated"])
        self.assertEqual(len(out["segmented_reliability"]["segments"]), 4)

    def test_bounded_payload_is_materially_smaller_than_raw(self):
        """The point of the function -- and asserted as a RATIO, not merely
        `smaller`.

        Pre-fix, `bounded < raw` was true by accident at large segment counts:
        the mapping slice kept all 400 segments, and the payload only shrank
        because `ledger_coverage` was being dropped. A bare `assertLess` passes
        against the broken function. At 400 segments capped to 50 the payload
        must fall by well over half; pre-fix it falls by ~1%."""
        raw = _summary(400)
        out = self.worker._bounded_accuracy_summary(raw, max_segments=50)
        ratio = len(json.dumps(out)) / float(len(json.dumps(raw)))
        self.assertLess(ratio, 0.5, "cap did not materially bound the payload (ratio %.3f)" % ratio)

    def test_truncation_keeps_the_largest_segments(self):
        """If the cap must drop segments it must drop the THINNEST. Dropping an
        arbitrary set leaves a surface nothing downstream can tell is skewed."""
        weights = list(range(10))  # segment i has decisive_count i
        out = self.worker._bounded_accuracy_summary(_summary(10, weights=weights), max_segments=3)
        kept = [seg["decisive_count"] for seg in out["segmented_reliability"]["segments"]]
        self.assertEqual(sorted(kept, reverse=True), [9, 8, 7])

    def test_global_and_shrinkage_survive_truncation(self):
        """The segments are only interpretable against their parent."""
        out = self.worker._bounded_accuracy_summary(_summary(120), max_segments=10)
        surface = out["segmented_reliability"]
        self.assertIn("global", surface)
        self.assertEqual(surface["shrinkage_k"], 20.0)

    def test_ledger_coverage_reaches_the_persisted_artifact(self):
        """Pre-fix the field whitelist dropped this entirely, so a summary
        computed on ONE DAY published as though it covered the full window."""
        out = self.worker._bounded_accuracy_summary(_summary(3), max_segments=50)
        coverage = out.get("ledger_coverage")
        self.assertIsNotNone(coverage, "ledger_coverage was dropped by the whitelist")
        self.assertTrue(coverage["truncated"])
        self.assertEqual(coverage["dates_covered"], 1)
        self.assertLessEqual(coverage["bytes_accepted"], coverage["budget_bytes"])

    def test_absent_coverage_is_tolerated(self):
        """An unbudgeted/offline summary carries no coverage block; that must
        not raise, and must not invent one."""
        raw = _summary(3)
        raw.pop("ledger_coverage")
        out = self.worker._bounded_accuracy_summary(raw, max_segments=50)
        self.assertIsNone(out["ledger_coverage"])

    def test_bare_list_surface_still_bounded(self):
        raw = _summary(0)
        raw["segmented_reliability"] = [
            {"sport": "mlb", "decisive_count": i} for i in range(80)
        ]
        out = self.worker._bounded_accuracy_summary(raw, max_segments=20)
        self.assertEqual(out["segments_total"], 80)
        self.assertTrue(out["segments_truncated"])
        self.assertEqual(len(out["segmented_reliability"]), 20)

    def test_end_to_end_against_a_real_summary(self):
        """Not a fixture -- the real builder, so a shape change upstream breaks
        this rather than silently un-bounding the artifact."""
        from syndicate.features.shared import intelligence_evaluation as ie

        summary = ie.build_accuracy_summary(sport="mlb")
        out = self.worker._bounded_accuracy_summary(summary, max_segments=1)
        inner = summary["segmented_reliability"]["segments"]
        self.assertEqual(out["segments_total"], len(inner))
        self.assertIn("ledger_coverage", out)
        self.assertIsNotNone(out["ledger_coverage"])
        if len(inner) > 1:
            self.assertTrue(out["segments_truncated"])
            self.assertEqual(len(out["segmented_reliability"]["segments"]), 1)


if __name__ == "__main__":
    unittest.main()
