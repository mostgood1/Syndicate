"""Bound `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` by CONTENT, not entry count.

`#632`. The cache measured **37.50 MB** on a live worker WHILE OBEYING its
32-entry cap. A cap on entry count cannot bound bytes when entry size varies by
orders of magnitude with slate size, which is exactly what an intelligence
response does.

NOT AN OOM FIX, and the tests say so because the ledger entry does: `#632`'s
bytes are not Python objects at all (28.3% of anon, 0.3% of the growth). This
bounds a genuinely unbounded cache on its own merits.

WHY ROW COUNT AND NOT BYTES -- measured, not assumed:

* an accurate deep walk costs **228 ms** on a 3,000-row payload;
* a cheap truncated walk reported **11.31 MB as 1.44 MB**, an 8x under-report
  that would admit huge entries while believing them small;
* `json.dumps` costs **70-174 ms** AND allocates a multi-MB transient string on
  a service that is already OOMing.

`len(top_opportunities)` is O(1) and tracks the term that varies.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import pipeline.intelligence_state as STATE


def _entry(rows: int, timestamp: float):
    return (timestamp, {"top_opportunities": [{"i": i} for i in range(rows)]})


def _rows_in_cache() -> int:
    return sum(len(value[1]["top_opportunities"])
               for value in STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE.values())


class RowBudgetTests(unittest.TestCase):

    def setUp(self) -> None:
        STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()

    tearDown = setUp

    def test_the_ROW_budget_is_enforced_where_the_entry_cap_would_not_be(self) -> None:
        """THE defect. Ten entries is well inside the 32-entry cap, so the old
        eviction never fired -- while the rows they carry are what occupies the
        memory."""
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS": "100"}, clear=False):
            for i in range(10):
                STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE[(f"k{i}",)] = _entry(30, 1000.0 + i)
                STATE._prune_combined_intelligence_response_cache()

            self.assertLessEqual(_rows_in_cache(), 100)
            self.assertLess(len(STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE), 10)

    def test_it_evicts_OLDEST_first(self) -> None:
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS": "100"}, clear=False):
            for i in range(10):
                STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE[(f"k{i}",)] = _entry(30, 1000.0 + i)
                STATE._prune_combined_intelligence_response_cache()

        kept = sorted(key[0] for key in STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE)
        self.assertEqual(kept, ["k7", "k8", "k9"])

    def test_eviction_LOOPS_until_under_budget(self) -> None:
        """The old code popped exactly ONE entry per insert, so a cache that got
        over budget by more than one could never catch up -- and nothing
        reported that it was over."""
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_INTELLIGENCE_CACHE_MAX_ENTRIES": "2"}, clear=False):
            for i in range(20):
                STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE[(f"b{i}",)] = _entry(1, 4000.0 + i)

            STATE._prune_combined_intelligence_response_cache()

            self.assertEqual(len(STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE), 2,
                             "one pop per prune would have left 19")

    def test_a_SINGLE_oversized_entry_is_KEPT(self) -> None:
        """The floor that makes this safe. Without it, a slate bigger than the
        row budget would be evicted immediately after every insert -- a
        permanent cache miss, rebuilding the board on every request, which costs
        far more than the memory saved."""
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS": "10"}, clear=False):
            STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE[("huge",)] = _entry(5000, 2000.0)

            STATE._prune_combined_intelligence_response_cache()

            self.assertEqual(list(STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE), [("huge",)])

    def test_the_entry_cap_still_applies(self) -> None:
        """The row budget ADDS a bound; it does not replace the old one."""
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS": "1000000",
                              "SYNDICATE_INTELLIGENCE_CACHE_MAX_ENTRIES": "3"}, clear=False):
            for i in range(9):
                STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE[(f"e{i}",)] = _entry(1, 3000.0 + i)
                STATE._prune_combined_intelligence_response_cache()

            self.assertEqual(len(STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE), 3)

    def test_an_empty_cache_prunes_without_error(self) -> None:
        STATE._prune_combined_intelligence_response_cache()

        self.assertEqual(len(STATE._COMBINED_INTELLIGENCE_RESPONSE_CACHE), 0)


class LimitParsingTests(unittest.TestCase):

    def test_an_unparseable_limit_falls_back_to_the_DEFAULT(self) -> None:
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS": "lots"}, clear=False):
            self.assertEqual(
                STATE._combined_intelligence_cache_limit(
                    "SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS", 4000),
                4000)

    def test_a_ZERO_or_negative_limit_falls_back_rather_than_emptying_the_cache(self) -> None:
        """`0` must not read as "cache nothing". An operator typing 0 means
        "unset", and honouring it literally would disable caching entirely on a
        service whose whole design is to read precomputed state."""
        for value in ("0", "-5"):
            with mock.patch.dict(os.environ,
                                 {"SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS": value}, clear=False):
                self.assertEqual(
                    STATE._combined_intelligence_cache_limit(
                        "SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS", 4000),
                    4000)

    def test_a_valid_override_is_honoured(self) -> None:
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS": "250"}, clear=False):
            self.assertEqual(
                STATE._combined_intelligence_cache_limit(
                    "SYNDICATE_INTELLIGENCE_CACHE_MAX_ROWS", 4000),
                250)


class RowCountingTests(unittest.TestCase):

    def test_a_payload_with_no_rows_counts_zero(self) -> None:
        self.assertEqual(STATE._combined_intelligence_cache_rows({}), 0)

    def test_a_non_mapping_payload_counts_zero_rather_than_raising(self) -> None:
        """Pruning runs on every insert; one malformed entry must not take the
        whole cache path down with it."""
        for payload in (None, "not-a-mapping", 7):
            self.assertEqual(STATE._combined_intelligence_cache_rows(payload), 0)


if __name__ == "__main__":
    unittest.main()
