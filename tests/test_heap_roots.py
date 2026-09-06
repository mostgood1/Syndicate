"""Is `#632`'s retained memory in the Python heap AT ALL? And under which root?

The narrow census explains **6.1% of a worker's anon growth**, but it walks only
container-typed module globals. From that number alone, "the bytes are elsewhere
in Python" and "the bytes are not Python objects" are indistinguishable -- and
they lead to opposite next steps, so the ambiguity has to be removed rather than
argued about.

Two additions, and the tests below pin the reasoning behind each:

* WIDER ROOTS, ordered specific-first. The shared `seen` set means the first root
  to reach an object owns it, so a broad root running first would swallow every
  named cache and report one useless number.
* A WHOLE-HEAP DENOMINATOR from `gc.get_objects()`. Summing `sys.getsizeof` over
  that list would undercount badly -- `str` and `bytes` are NOT gc-tracked, and
  this leak is 8-64MB mappings, exactly the shape of large buffers.
"""

from __future__ import annotations

import gc
import sys
import types
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD

# Every walk in this file is CAPPED. These tests exercise behaviour, not the size
# of whatever process happens to be running them -- and an uncapped walk under
# pytest hung for minutes while the same call took ~1 s against the real app.
NODE_CAP = 40000

# ...BUT A CAP IS ALSO A WAY TO DEPEND ON THE RUNNER, IN THE OTHER DIRECTION, AND
# THAT IS WHAT 40,000 WAS DOING TO `WiderRootTests` `[measured 2026-09-05]`.
#
# The census walks the interpreter's EXISTING object graph; its cost is a
# function of the ambient heap, not of the ~0.5 MB these tests allocate. Run the
# file alone and 40,000 nodes reaches this probe. Run it in a process that has
# already imported 40 other test modules -- which is what a `--dist=loadscope`
# worker is -- and the budget is spent before the walk arrives:
#
#     cap=   40,000   nodes_used=  40,000   TRUNCATED   probe=['_PLAIN_CACHE']
#     cap=  400,000   nodes_used=  74,925   complete    probe=all three   0.21s
#     cap=2,000,000   nodes_used=  74,925   complete    probe=all three   0.19s
#
# The real requirement is 74,925 -- 1.87x the old cap -- and the walk stops on
# its own at that point, so raising the ceiling costs 0.14 s and not more. The
# failure it produced was silent and misleading: `assertIn('Holder', rows)` with
# `Holder` simply absent, which reads as the CENSUS being broken rather than as
# the walk never having got there.
#
# 400,000 is ~5.3x the measured requirement of a 40-module process. That is
# headroom, not a guarantee -- so `_rows()` asserts the census's OWN
# `node_budget_exhausted` flag, and a future process big enough to spend even
# this budget fails by NAMING the truncation instead of mis-reporting a missing
# root. `PythonHeapTotalTests` keeps `NODE_CAP`: its assertions are ratios and
# identity, they do not require a complete walk, and `python_heap_total` is the
# call the docstring below records as hanging for minutes when uncapped.
CENSUS_NODE_CAP = 400_000



class WiderRootTests(unittest.TestCase):

    def setUp(self) -> None:
        class Holder:
            CLASS_CACHE = {f"c{i}": "c" * 8000 for i in range(20)}

        class Singleton:
            def __init__(self) -> None:
                self.instance_cache = {f"i{i}": "i" * 8000 for i in range(20)}

        self._name = "syndicate._roots_probe_"
        # A class root only counts if the module DEFINES it -- an imported class
        # is a world-root (walking `Flask` absorbed 27.0 MB of application
        # graph), so the census requires `__module__` to match. Stamping it here
        # is what makes this probe a faithful stand-in for a real module.
        Holder.__module__ = self._name
        Singleton.__module__ = self._name
        module = types.ModuleType(self._name)
        module._PLAIN_CACHE = {f"p{i}": "p" * 8000 for i in range(20)}
        module.Holder = Holder
        module.SINGLETON = Singleton()
        sys.modules[self._name] = module

    def tearDown(self) -> None:
        sys.modules.pop(self._name, None)

    def _rows(self, census):
        # A TRUNCATED WALK CANNOT SUPPORT AN ABSENCE CLAIM. Every assertion below
        # is `assertIn`, so an exhausted budget turns "the census does not reach
        # this root" into "the census stopped early" while reading identically.
        # The payload already carries the flag; nothing here used to look at it.
        self.assertFalse(
            census.get("node_budget_exhausted"),
            "the census ran out of node budget before finishing, so a missing root "
            "here says nothing about the census -- raise CENSUS_NODE_CAP "
            f"(nodes_used={census.get('nodes_used')})",
        )
        return {r["name"]: r for r in census["top"] if r["module"] == self._name}

    def test_a_CLASS_ATTRIBUTE_cache_is_now_reached(self) -> None:
        """Invisible to the old census, which only looked at module globals that
        were themselves containers."""
        rows = self._rows(MOD.module_retainer_census(top=100, node_cap=CENSUS_NODE_CAP))

        self.assertIn("Holder", rows)
        self.assertGreater(rows["Holder"]["mb"], 0.1)
        self.assertEqual(rows["Holder"]["root_pass"], "class_attr")

    def test_a_MODULE_LEVEL_OBJECT_holding_a_cache_is_now_reached(self) -> None:
        """A singleton with caches in its `__dict__` -- the shape the old root
        set skipped before the walk even started."""
        rows = self._rows(MOD.module_retainer_census(top=100, node_cap=CENSUS_NODE_CAP))

        self.assertIn("SINGLETON", rows)
        self.assertGreater(rows["SINGLETON"]["mb"], 0.1)
        self.assertEqual(rows["SINGLETON"]["root_pass"], "module_object")

    def test_the_plain_container_still_reports_under_its_OWN_pass(self) -> None:
        rows = self._rows(MOD.module_retainer_census(top=100, node_cap=CENSUS_NODE_CAP))

        self.assertEqual(rows["_PLAIN_CACHE"]["root_pass"], "module_container")

    def test_an_IMPORTED_class_is_not_used_as_a_root(self) -> None:
        """An imported class reaches the whole program through its own class
        attributes. Measured: `Flask`, imported into `pipeline.intelligence_state`,
        absorbed 27.0 MB and starved every later root against the shared `seen`
        set -- the row said "intelligence_state" and meant "the application"."""
        import json as _json

        sys.modules[self._name].SomeImportedClass = _json.JSONDecoder

        rows = self._rows(MOD.module_retainer_census(top=100, node_cap=CENSUS_NODE_CAP))

        self.assertNotIn("SomeImportedClass", rows)

    def test_a_MODULE_is_never_used_as_a_root(self) -> None:
        """A module root reaches the whole world and would make every figure in
        the table meaningless."""
        sys.modules[self._name].SOME_MODULE = sys.modules["json"]

        rows = self._rows(MOD.module_retainer_census(top=100, node_cap=CENSUS_NODE_CAP))

        self.assertNotIn("SOME_MODULE", rows)

    def test_an_object_is_counted_ONCE_under_the_MOST_SPECIFIC_root(self) -> None:
        """The ordering rule. The same payload referenced by a plain container and
        by an object must land on the container -- pass 1 runs first -- so the
        broad root reports only the residual."""
        shared = {"payload": "s" * 60000}
        module = sys.modules[self._name]
        module._SHARED_CONTAINER = shared
        module.SINGLETON.also_holds = shared

        rows = self._rows(MOD.module_retainer_census(top=100, node_cap=CENSUS_NODE_CAP))

        self.assertGreater(rows["_SHARED_CONTAINER"]["mb"], 0.05)
        self.assertEqual(rows["_SHARED_CONTAINER"]["root_pass"], "module_container")


class PythonHeapTotalTests(unittest.TestCase):

    def test_it_reports_the_ratio_against_process_anon(self) -> None:
        """THE number. Near 100% means the bytes are Python objects and the
        census had the wrong roots; small means they are not Python at all."""
        with mock.patch.object(MOD, "_process_anon_mb", return_value=400.0):
            heap = MOD.python_heap_total(node_cap=NODE_CAP)

        self.assertEqual(heap["process_anon_mb"], 400.0)
        self.assertIsNotNone(heap["heap_pct_of_anon"])
        self.assertAlmostEqual(
            heap["heap_pct_of_anon"],
            round(100.0 * heap["python_heap_mb"] / 400.0, 1), places=1)

    def test_the_ratio_is_None_when_anon_is_unreadable(self) -> None:
        """Not zero -- a zero would assert the heap explains none of the memory."""
        with mock.patch.object(MOD, "_process_anon_mb", return_value=None):
            heap = MOD.python_heap_total(node_cap=NODE_CAP)

        self.assertIsNone(heap["heap_pct_of_anon"])

    def test_it_reaches_UNTRACKED_children_of_tracked_roots(self) -> None:
        """The reason this walks referents instead of summing getsizeof over
        `gc.get_objects()`: a large `str` is not gc-tracked, and `#632`'s memory
        is 8-64MB mappings -- exactly the shape of large buffers. A getsizeof sum
        would miss the payload and report a comfortingly small heap.

        Asserted on the WALK ITSELF rather than on a whole-process total. The
        first version called `python_heap_total(node_cap=4_000_000)`, which made
        the assertion depend on the size of the test runner's own heap -- it hung
        for minutes under pytest while taking ~1 s against the real app, because
        pytest's object graph is much larger than the one being measured. A test
        must not be a function of its runner.
        """
        payload = "z" * 2_000_000
        holder = {"big": payload}          # the dict IS tracked; the str is NOT

        self.assertFalse(gc.is_tracked(payload), "premise: a large str is untracked")

        budget = [100000]
        size = MOD._deep_size(holder, budget, set())
        getsizeof_only = sys.getsizeof(holder)

        self.assertGreater(size, 1_900_000, "the untracked 2 MB string must be counted")
        self.assertLess(getsizeof_only, 10_000,
                        "and a shallow sum would have reported ~0 for the same object")

    def test_budget_exhaustion_is_REPORTED(self) -> None:
        heap = MOD.python_heap_total(node_cap=10000)

        self.assertTrue(heap["node_budget_exhausted"])
        self.assertGreater(heap["nodes_used"], 0)

    def test_it_identifies_the_worker(self) -> None:
        heap = MOD.python_heap_total(node_cap=NODE_CAP)

        self.assertEqual(heap["proc_token"], MOD._proc_token())
        self.assertIsInstance(heap["pid"], int)
        self.assertGreater(heap["gc_tracked_objects"], 0)


if __name__ == "__main__":
    unittest.main()
