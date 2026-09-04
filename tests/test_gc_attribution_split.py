"""Is the garbage collector `#632`'s third contamination source? (instrumentation)

TWO EXPLANATIONS ARE ALREADY DEAD, both by measurement rather than argument:

  * cross-worker contamination -- fixed by attributing against THIS PROCESS's
    anon (`/proc/self/smaps_rollup`) instead of the container cgroup;
  * background loops -- FALSIFIED. Neither runs on web
    (`SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false`,
    `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false`, the code gate
    defaults False, and web has logged ZERO loop lines). A correct gate was
    built for a mechanism that is not there.

What remains is not concurrency. `note_request_start`/`end` DIFFERENCE the
process's anon, and in a garbage-collected runtime that window contains whatever
the collector frees -- garbage produced by requests that ended earlier. A request
that triggers a gen-2 pass is charged a large negative it did not cause; one
running while garbage accumulates is charged a positive that is deferred cost.
That is the observed signature exactly: a route at **-49.46 MB across 252 solo
requests**, and a solo-sample sum EXCEEDING total process growth (175%).

THIS ONLY RECORDS. It splits attributed deltas by whether a generation-2
collection ran inside the window and publishes both halves. If the negatives
concentrate in the collected half, the collector is the source and a gate is
justified. Building the gate first is what went wrong last time, and the cost of
being wrong again is another inert change.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


class GcCounterTests(unittest.TestCase):

    def test_the_generation_2_counter_is_READABLE_here(self) -> None:
        """The reachability check the background-loop gate never got. If this
        cannot be read, the split is meaningless and the probe is inert."""
        self.assertGreaterEqual(MOD._gc_gen2_collections(), 0)

    def test_it_reports_minus_one_rather_than_guessing_when_unreadable(self) -> None:
        with mock.patch.object(MOD.gc, "get_stats", side_effect=RuntimeError("no stats")):
            self.assertEqual(MOD._gc_gen2_collections(), -1)

    def test_a_short_stats_list_is_unreadable_not_zero(self) -> None:
        """Zero would read as "no collections have ever run", which is a claim."""
        with mock.patch.object(MOD.gc, "get_stats", return_value=[{}, {}]):
            self.assertEqual(MOD._gc_gen2_collections(), -1)


class SplitTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD.reset_request_memory_attribution()

    tearDown = setUp

    def _request(self, before, after, gc_pair=None):
        patches = [
            mock.patch.dict(os.environ, {"SYNDICATE_REQUEST_MEMORY_PROFILE": "on"}, clear=False),
            mock.patch.object(MOD, "_process_anon_mb", side_effect=[before, after]),
        ]
        if gc_pair is not None:
            patches.append(mock.patch.object(MOD, "_gc_gen2_collections", side_effect=gc_pair))
        with patches[0], patches[1]:
            if gc_pair is not None:
                with patches[2]:
                    token = MOD.note_request_start()
                    MOD.note_request_end(token, "/r", emit_every=10_000)
            else:
                token = MOD.note_request_start()
                MOD.note_request_end(token, "/r", emit_every=10_000)

    def test_a_request_with_NO_collection_lands_in_the_no_gc_bucket(self) -> None:
        self._request(100.0, 140.0, gc_pair=[7, 7])

        split = MOD.request_memory_attribution_payload()["gc2_split"]
        self.assertEqual(split["no_gc2_n"], 1)
        self.assertAlmostEqual(split["no_gc2_mb"], 40.0)
        self.assertEqual(split["with_gc2_n"], 0)

    def test_a_request_DURING_a_collection_lands_in_the_gc_bucket(self) -> None:
        """The case the whole probe exists for: a big NEGATIVE that the request
        did not cause."""
        self._request(100.0, 55.0, gc_pair=[7, 8])

        split = MOD.request_memory_attribution_payload()["gc2_split"]
        self.assertEqual(split["with_gc2_n"], 1)
        self.assertAlmostEqual(split["with_gc2_mb"], -45.0)
        self.assertEqual(split["no_gc2_n"], 0)

    def test_an_UNREADABLE_counter_is_not_treated_as_collected(self) -> None:
        """-1 means "do not know". Counting it as collected would move real
        allocations into the bucket meant to hold the collector's noise."""
        self._request(100.0, 130.0, gc_pair=[-1, -1])

        split = MOD.request_memory_attribution_payload()["gc2_split"]
        self.assertEqual(split["with_gc2_n"], 0)
        self.assertEqual(split["no_gc2_n"], 1)

    def test_the_route_total_still_includes_BOTH_halves(self) -> None:
        """The split records; it must not quietly exclude. Excluding would hide
        the very evidence this is here to gather."""
        self._request(100.0, 140.0, gc_pair=[7, 7])
        self._request(100.0, 55.0, gc_pair=[7, 8])

        payload = MOD.request_memory_attribution_payload()
        row = payload["routes"][0]
        self.assertEqual(row["solo_n"], 2)
        self.assertAlmostEqual(row["total_mb"], -5.0, places=3)
        split = payload["gc2_split"]
        self.assertAlmostEqual(split["no_gc2_mb"] + split["with_gc2_mb"], row["total_mb"], places=3)

    def test_reset_clears_the_split(self) -> None:
        self._request(100.0, 140.0, gc_pair=[7, 7])
        MOD.reset_request_memory_attribution()

        split = MOD.request_memory_attribution_payload()["gc2_split"]
        self.assertEqual(split, {"with_gc2_n": 0, "with_gc2_mb": 0.0,
                                 "no_gc2_n": 0, "no_gc2_mb": 0.0})


if __name__ == "__main__":
    unittest.main()
