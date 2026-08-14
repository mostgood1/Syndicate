"""`build_intelligence_overview(consumer=...)` — peak MAX instead of SUM.

The function's own comment states the cost's shape: "every sport's fully
hydrated overview is held simultaneously, so peak is the SUM across sports, not
the max", and MLB's pass alone was measured at +2.9GB. Passing a consumer hands
each sport's row to the caller and drops it before the next hydrates.

The load-bearing tests here are EQUIVALENCE (streamed rows == list rows, in
order) and RELEASE (the previous sport is not still referenced while the next
one builds). A streaming API that quietly held on to the rows would pass every
test except the second.
"""

from __future__ import annotations

import gc
import unittest
import weakref
from unittest.mock import patch

import syndicate.features.intelligence as intel


SPORTS = [{"slug": "mlb"}, {"slug": "nfl"}, {"slug": "wnba"}]


class _Row(dict):
    """A dict subclass, because a plain dict cannot be weak-referenced and the
    release test needs to observe when a row is actually collected."""


def _fake_row(sport, effective_date, **kwargs):
    return _Row(slug=sport["slug"], dashboard_games=[], home_rails={}, payload="x" * 128)


class OverviewStreamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._patches = [
            patch.object(intel, "_configured_syndicate_sports", return_value=SPORTS),
            patch.object(intel, "_build_sport_overview", side_effect=_fake_row),
            patch.object(intel, "_overview_headroom_exhausted", return_value=False),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def test_streamed_rows_equal_list_rows_in_order(self) -> None:
        listed = intel.build_intelligence_overview(selected_date="2026-08-14")
        streamed: list[dict] = []
        returned = intel.build_intelligence_overview(
            selected_date="2026-08-14", consumer=streamed.append
        )
        self.assertEqual([r["slug"] for r in streamed], [r["slug"] for r in listed])
        self.assertEqual(streamed, listed)
        self.assertEqual(
            returned, [],
            "a consumer was given, so returning the rows too would reinstate the retention",
        )

    def test_the_previous_sport_is_released_before_the_next_builds(self) -> None:
        """The whole point. Without the `sport_row = None` drop, the previous
        sport stays alive through the loop variable for the entire next
        iteration -- and the expensive sport (MLB) runs first."""
        seen: list[weakref.ref] = []
        alive_during_build: list[int] = []

        def _consumer(row):
            seen.append(weakref.ref(row))

        def _row_then_check(sport, effective_date, **kwargs):
            # Count how many previously-emitted rows are still alive at the
            # moment this sport is being built.
            gc.collect()
            alive_during_build.append(sum(1 for ref in seen if ref() is not None))
            return _fake_row(sport, effective_date)

        with patch.object(intel, "_build_sport_overview", side_effect=_row_then_check):
            intel.build_intelligence_overview(selected_date="2026-08-14", consumer=_consumer)

        self.assertEqual(
            alive_during_build, [0, 0, 0],
            f"a previous sport was still resident while the next built: {alive_during_build}",
        )

    def test_list_mode_still_retains_every_row(self) -> None:
        """The old behaviour must be untouched for callers that did not opt in."""
        rows = intel.build_intelligence_overview(selected_date="2026-08-14")
        self.assertEqual(len(rows), 3)

    def test_counts_are_logged_per_sport_in_both_modes(self) -> None:
        """The counts moved out of a second pass. They must still be emitted --
        once per sport, in both modes, or a streamed build goes dark."""
        with patch.object(intel, "_intel_trace") as trace:
            intel.build_intelligence_overview(selected_date="2026-08-14")
            listed_sports = [c.kwargs.get("sport") for c in trace.call_args_list
                             if c.args and c.args[0] == "overview_counts"]
        with patch.object(intel, "_intel_trace") as trace:
            intel.build_intelligence_overview(selected_date="2026-08-14", consumer=lambda r: None)
            streamed_sports = [c.kwargs.get("sport") for c in trace.call_args_list
                               if c.args and c.args[0] == "overview_counts"]
        self.assertEqual(listed_sports, ["mlb", "nfl", "wnba"])
        self.assertEqual(streamed_sports, listed_sports)

    def test_the_memory_guard_sees_a_real_sports_done_count(self) -> None:
        """`sports_done` used to be `len(overview)`, which is permanently 0 when
        streaming -- a guard fed a constant is not a guard."""
        seen: list[int] = []

        def _guard(*, next_sport, sports_done, sports_total):
            seen.append(sports_done)
            return False

        with patch.object(intel, "_overview_headroom_exhausted", side_effect=_guard):
            intel.build_intelligence_overview(selected_date="2026-08-14", consumer=lambda r: None)
        self.assertEqual(seen, [0, 1, 2], "the guard was told the same count every sport")

    def test_a_raising_consumer_is_not_swallowed(self) -> None:
        def _boom(row):
            raise RuntimeError("consumer failed")

        with self.assertRaises(RuntimeError):
            intel.build_intelligence_overview(selected_date="2026-08-14", consumer=_boom)


if __name__ == "__main__":
    unittest.main()
