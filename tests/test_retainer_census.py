"""Name the object graph the web workers retain between requests. `#632`.

Everything upstream narrowed WHERE the memory lives (8-64MB anonymous mappings)
and ruled out WHO allocates it per request: no single route owns it, merges were
absent through 155 polls while the container ramped 52% -> 97%, and per-request
deltas do not compose into net process change under churn. What is left is what
the process keeps BETWEEN requests.

Static analysis produced suspects and not an answer -- no `lru_cache(maxsize=None)`
anywhere, but many plain `dict` caches with no eviction. Picking the
likely-looking one off that list is exactly the move this investigation has been
punished for repeatedly, so the census MEASURES instead.

THE TEST THAT MATTERS MOST is `test_it_measures_DEEP_size_not_shallow`: a dict of
large payloads reports a few hundred bytes to `sys.getsizeof` while holding
megabytes. A census built on the shallow number would report every cache as
harmless and close the investigation on a false negative.

And `coverage_pct` is why the census reports its own limits: if module globals
account for a small share of process anon, the retainer is in C-extension or
per-thread state that a Python object walk cannot see. That is a RESULT -- the
next reader must not read a small census as "nothing is retained".
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


def _fake_module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class DeepSizeTests(unittest.TestCase):

    def test_it_measures_DEEP_size_not_shallow(self) -> None:
        """THE point of the census. `sys.getsizeof` on a dict of payloads reports
        the dict's own table, not the payloads -- so a 50 MB cache reads as a few
        hundred bytes and looks harmless."""
        payloads = {f"k{i}": "x" * 20000 for i in range(20)}

        shallow = sys.getsizeof(payloads)
        deep = MOD._deep_size(payloads, [400000], set())

        self.assertLess(shallow, 5000, "shallow size is small by construction")
        self.assertGreater(deep, 380000, "deep size must include the values")
        self.assertGreater(deep, shallow * 50)

    def test_a_CYCLE_does_not_hang(self) -> None:
        """Module globals routinely contain cycles. Without the `seen` set this
        walk never returns, and a diagnostic that hangs a worker is worse than
        no diagnostic."""
        a: dict = {"name": "a"}
        b: dict = {"name": "b", "peer": a}
        a["peer"] = b

        size = MOD._deep_size(a, [400000], set())

        self.assertGreater(size, 0)

    def test_shared_objects_are_counted_ONCE(self) -> None:
        """Two caches holding the same payload must not double-count it, or the
        census total exceeds the process and reads as nonsense."""
        shared = ["y" * 10000]
        seen: set = set()
        budget = [400000]

        first = MOD._deep_size({"a": shared}, budget, seen)
        second = MOD._deep_size({"b": shared}, budget, seen)

        self.assertGreater(first, 10000)
        self.assertLess(second, 1000, "the shared payload is already counted")

    def test_the_node_budget_STOPS_the_walk(self) -> None:
        """A deep walk on a 600 MB worker is not free -- `#241` is the precedent
        for periodic work assumed cheap taking a service down."""
        big = {f"k{i}": [i] * 10 for i in range(5000)}
        budget = [500]

        MOD._deep_size(big, budget, set())

        self.assertLessEqual(budget[0], 0)


class CensusTests(unittest.TestCase):

    def setUp(self) -> None:
        self._name = "syndicate._census_probe_"
        sys.modules[self._name] = _fake_module(
            self._name,
            _BIG_CACHE={f"k{i}": "z" * 20000 for i in range(30)},
            _SMALL={"a": 1},
            _EMPTY={},
            NOT_A_CONTAINER=42,
        )

    def tearDown(self) -> None:
        sys.modules.pop(self._name, None)

    def test_it_FINDS_a_large_module_level_cache_and_ranks_it_first(self) -> None:
        census = MOD.module_retainer_census(top=5)

        names = [(r["module"], r["name"]) for r in census["top"]]
        self.assertIn((self._name, "_BIG_CACHE"), names)
        self.assertEqual(census["top"][0]["name"], "_BIG_CACHE",
                         "the biggest retainer must rank first")
        self.assertGreater(census["top"][0]["mb"], 0.5)

    def test_it_skips_EMPTY_containers_and_non_containers(self) -> None:
        census = MOD.module_retainer_census(top=100)

        rows = [r for r in census["top"] if r["module"] == self._name]
        found = {r["name"] for r in rows}
        self.assertNotIn("_EMPTY", found)
        self.assertNotIn("NOT_A_CONTAINER", found)

    def test_it_reports_COVERAGE_against_process_anon(self) -> None:
        """The number to read first. A low coverage says the retainer is not a
        module-level Python container, which is a result rather than a failure."""
        with mock.patch.object(MOD, "_process_anon_mb", return_value=500.0):
            census = MOD.module_retainer_census(top=3)

        self.assertEqual(census["process_anon_mb"], 500.0)
        self.assertIsNotNone(census["coverage_pct"])
        self.assertAlmostEqual(
            census["coverage_pct"],
            round(100.0 * census["census_total_mb"] / 500.0, 1), places=1)

    def test_coverage_is_None_when_anon_is_UNREADABLE(self) -> None:
        """Not zero. A zero would assert the census explains none of the memory;
        None says the comparison could not be made."""
        with mock.patch.object(MOD, "_process_anon_mb", return_value=None):
            census = MOD.module_retainer_census(top=3)

        self.assertIsNone(census["coverage_pct"])
        self.assertIsNone(census["process_anon_mb"])

    def test_budget_exhaustion_is_REPORTED_not_silent(self) -> None:
        """An under-count that looked clean would send the next reader hunting C
        extensions for no reason."""
        census = MOD.module_retainer_census(top=5, node_cap=1200)

        self.assertTrue(census["node_budget_exhausted"])
        self.assertGreater(census["nodes_used"], 0)

    def test_it_identifies_the_worker_it_ran_on(self) -> None:
        """Two workers retain different amounts; a census without a pid is not
        attributable to either."""
        census = MOD.module_retainer_census(top=1)

        self.assertEqual(census["proc_token"], MOD._proc_token())
        self.assertIsInstance(census["pid"], int)


if __name__ == "__main__":
    unittest.main()
