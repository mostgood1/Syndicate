"""#338. The read-side shapes `/api/ops/intelligence/candidate-trace` inspects.

The endpoint reported `board_snapshot_read_candidate_count: None` for a healthy
board carrying 220 candidates, which sent a debugging session after the trace
instead of the board. Two independent defects, pinned here as the payload
properties the endpoint depends on rather than by driving Flask:

  1. it looked for top-level `candidates`/`top_opportunities`, which do not
     exist -- the snapshot nests them under `response` -- while ignoring the
     literal `candidate_count` int at the top level;
  2. it read `STATE_PATH` RAW, and #322 compresses that file's `snapshots`,
     so the envelope passed `isinstance(..., dict)` and the key lookup missed.

Both are "the instrument answers rather than errs", the same class as #334's
stale-but-`fresh` and #327's invisible stage.
"""
from __future__ import annotations

import json
import unittest

import pipeline.intelligence_state as intelligence_state


def _board_state(pool: int = 220, cap: int = 150) -> dict:
    return {
        "selected_date": "2026-08-10",
        "candidate_count": pool,
        "top_opportunities": [{"a": i} for i in range(cap)],
        "recommendations": [{"a": i} for i in range(cap)],
        "by_sport": {"mlb": [{"a": i} for i in range(120)], "wnba": [{"a": i} for i in range(100)]},
    }


class BoardSnapshotShapeTests(unittest.TestCase):
    def _persisted(self) -> dict:
        snapshot = intelligence_state._board_snapshot_persist_payload(
            _board_state(), selected_date="2026-08-10", latest_key="k1"
        )
        return intelligence_state._compress_oversized_values(snapshot)

    def test_the_keys_the_old_code_looked_for_do_not_exist(self) -> None:
        # This is WHY it returned None, and it is the assertion that would have
        # caught it: both `.get()`s missed and `else None` reported "absent".
        expanded = intelligence_state.expand_persisted_state(self._persisted())
        self.assertNotIn("candidates", expanded)
        self.assertNotIn("top_opportunities", expanded)

    def test_the_true_count_is_the_top_level_int(self) -> None:
        expanded = intelligence_state.expand_persisted_state(self._persisted())
        self.assertEqual(expanded.get("candidate_count"), 220)

    def test_the_lists_live_under_response_and_are_cap_length(self) -> None:
        # 150 here is _default_unbounded_candidate_cap and is CORRECT -- the
        # trace must not report it as the candidate count.
        response = intelligence_state.expand_persisted_state(self._persisted())["response"]
        self.assertEqual(len(response["top_opportunities"]), 150)
        self.assertEqual(sum(len(v) for v in response["by_sport"].values()), 220)


class StatePathMustBeExpandedBeforeReadingSnapshotsTests(unittest.TestCase):
    """#322 compresses `snapshots`, so a raw read gets an envelope that still
    passes `isinstance(..., dict)`. That is the dangerous shape: not a crash, a
    dict with the wrong three keys."""

    def _big_state(self) -> dict:
        return {
            "latest_key": "k1",
            "updated_at": "t",
            "snapshots": {"k1": {"key": "k1", "computed_at": "t", "response": {
                "top_opportunities": [{"cand": f"c{i}", "pad": "y" * 80} for i in range(4000)]}}},
        }

    def test_the_fixture_is_actually_large_enough_to_compress(self) -> None:
        # Without this the test passes for the wrong reason -- a small payload
        # is never compressed and the raw read looks fine. (It caught me.)
        state = self._big_state()
        self.assertGreater(
            len(json.dumps(state["snapshots"])), intelligence_state._COMPRESS_MIN_BYTES
        )

    def test_a_raw_read_yields_an_envelope_that_still_looks_like_a_dict(self) -> None:
        packed = intelligence_state._compress_oversized_values(self._big_state())
        snapshots = packed["snapshots"]
        self.assertIsInstance(snapshots, dict, "the trap: it passes the isinstance check")
        self.assertIn(intelligence_state._COMPRESSED_VALUE_KEY, snapshots)
        self.assertNotIn("k1", snapshots, "so the latest_key lookup silently misses")

    def test_expanding_first_restores_the_snapshot_keys(self) -> None:
        expanded = intelligence_state.expand_persisted_state(
            intelligence_state._compress_oversized_values(self._big_state())
        )
        self.assertIn("k1", expanded["snapshots"])
        self.assertIn(expanded["latest_key"], expanded["snapshots"])


if __name__ == "__main__":
    unittest.main()
