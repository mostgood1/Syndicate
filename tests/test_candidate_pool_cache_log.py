"""CANDIDATE_POOL_CACHE: what refresh-worker's candidate-pool cache weighs.

Lane heavy-build-child-process, hypothesis H-cache. refresh-worker's main
process keeps ~2.2 GB after its first full build, and `_candidate_pools` holds
up to `_max_snapshots` full pools trimmed by COUNT only -- nothing recorded what
those entries weigh. The line these tests pin is the instrument that answers it,
so it must (a) actually be called from the build's return path, (b) report the
cache total, not just this pool, and (c) never break a build.
"""

from __future__ import annotations

import inspect
import json
import re
import unittest
from contextlib import redirect_stdout
from io import StringIO

from pipeline.intelligence_state import IntelligenceStateService


def _cache_line(output: str) -> dict[str, str]:
    lines = [line for line in output.splitlines() if "[intelligence_state] CANDIDATE_POOL_CACHE " in line]
    if len(lines) != 1:
        raise AssertionError(f"expected exactly one CANDIDATE_POOL_CACHE line, got {len(lines)}: {output!r}")
    return dict(re.findall(r"(\w+)=(\S+)", lines[0]))


class CandidatePoolCacheLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IntelligenceStateService()

    def _log(self, key: str, pool: dict, *, cached: bool) -> dict[str, str]:
        serialized = json.dumps(pool, default=str)
        if cached:
            self.service._candidate_pools[key] = pool
        buffer = StringIO()
        with redirect_stdout(buffer):
            self.service._log_candidate_pool_cache("2026-09-14", key, serialized, cached=cached)
        return _cache_line(buffer.getvalue())

    def test_reports_this_pool_and_the_cache_total(self) -> None:
        first = {"candidate_count": 1, "global_pool": ["a" * 100]}
        second = {"candidate_count": 2, "global_pool": ["b" * 300]}
        self._log("k1", first, cached=True)
        fields = self._log("k2", second, cached=True)

        self.assertEqual(fields["cached"], "True")
        self.assertEqual(fields["entries"], "2")
        self.assertEqual(fields["limit"], str(self.service._max_snapshots))
        self.assertEqual(int(fields["pool_json_bytes"]), len(json.dumps(second)))
        self.assertEqual(int(fields["cache_json_bytes"]), len(json.dumps(first)) + len(json.dumps(second)))

    def test_evicted_pools_drop_out_of_the_total(self) -> None:
        self._log("old", {"candidate_count": 1, "global_pool": ["x" * 500]}, cached=True)
        self.service._candidate_pools.pop("old")  # what _trim_ordered_dict does at the cap
        kept = {"candidate_count": 1, "global_pool": ["y" * 50]}
        fields = self._log("new", kept, cached=True)

        self.assertEqual(fields["entries"], "1")
        self.assertEqual(int(fields["cache_json_bytes"]), len(json.dumps(kept)))
        self.assertNotIn("old", self.service._candidate_pool_json_bytes)

    def test_an_uncached_empty_pool_is_reported_but_not_counted(self) -> None:
        empty = {"candidate_count": 0, "global_pool": []}
        fields = self._log("empty", empty, cached=False)

        self.assertEqual(fields["cached"], "False")
        self.assertEqual(fields["entries"], "0")
        self.assertEqual(int(fields["pool_json_bytes"]), len(json.dumps(empty)))
        self.assertEqual(fields["cache_json_bytes"], "0")

    def test_a_logging_failure_never_breaks_the_build(self) -> None:
        self.service._candidate_pool_json_bytes = None  # type: ignore[assignment]
        buffer = StringIO()
        with redirect_stdout(buffer):
            self.service._log_candidate_pool_cache("2026-09-14", "k", "{}", cached=True)
        self.assertIn("CANDIDATE_POOL_CACHE_LOG_FAILED", buffer.getvalue())


class CandidatePoolCacheWiringTests(unittest.TestCase):
    def test_build_candidate_pool_logs_the_serialization_it_returns(self) -> None:
        # The build's full path needs mirror data and network, so the wiring is
        # pinned on the source: the return value must come from the SAME string
        # the log measured, or the byte count describes something else.
        source = inspect.getsource(IntelligenceStateService._build_candidate_pool)
        tail = source[source.rindex("serialized_pool = json.dumps(pool, default=str)"):]
        self.assertIn("self._log_candidate_pool_cache(selected_date, cache_key, serialized_pool", tail)
        self.assertTrue(tail.rstrip().endswith("return json.loads(serialized_pool)"))


if __name__ == "__main__":
    unittest.main()
