"""A game still in play at midnight Central must keep a rebuilding Layer 2 board.

WHY THESE TESTS EXIST. Measured on refresh-worker 2026-09-13: the board window
(`_default_board_window_dates`) starts at Central today, so at 05:00:08Z the loop
stopped queuing 2026-09-12, and `LAYER2_FAST_REFRESH date=2026-09-12` never ran
after 04:58:57Z while NMS @ HAW (kickoff 11:05 PM CT) was still being played.
`/api/board/layer2-shortlist?date=2026-09-12` then served that build's 28 `live`
rows for eight more hours.

Apart from `tests/test_intelligence_state.py` (~15 minutes) for the same reason
`tests/test_layer2_fast_refresh.py` is: these gate a worker loop change and must
be cheap enough to run on every edit.
"""

from __future__ import annotations

import inspect
import os
import unittest
from datetime import datetime
from unittest.mock import patch

import pipeline.intelligence_state as intelligence_state_module
from pipeline.intelligence_state import IntelligenceStateService, _shortlist_live_signal
from syndicate.features.shared.timezone import CENTRAL_TIMEZONE

PRIOR = "2026-09-12"


def _central(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 13, hour, minute, tzinfo=CENTRAL_TIMEZONE)


def _live_row() -> dict:
    return {"sport": "ncaaf", "game_state": "live", "game": {"state": "live", "matchup": "NMS @ HAW"}}


def _pregame_row() -> dict:
    return {"sport": "ncaaf", "game_state": "pregame", "game": {"state": "pregame"}}


class PriorDateCarryoverTests(unittest.TestCase):
    def setUp(self) -> None:
        for name in ("SYNDICATE_LAYER2_CARRYOVER_MAX_HOURS", "SYNDICATE_LAYER2_FAST_REFRESH_SECONDS"):
            previous = os.environ.pop(name, None)
            if previous is not None:
                self.addCleanup(os.environ.__setitem__, name, previous)
        self.service = IntelligenceStateService()
        self.built: list[str] = []
        self.written: list[str] = []
        self.printed: list[str] = []
        # What the NEXT build returns. Default: the game has finished.
        self.next_shortlist: dict = {"rows": [_pregame_row()], "chips_live": 0, "opportunities_considered": 5}

    def _build(self, selected_date, sport_slugs):
        self.built.append(selected_date)
        return dict(self.next_shortlist)

    def _run(self, now: datetime, *, sim: bool = False, drain: str | None = None):
        """Drive the REAL carryover and the REAL fast path; stub only their IO.

        `build_layer2_shortlist` and `pull_hot_artifacts` are imported inside the
        fast path, so they are patched on their defining modules -- the same
        trap `tests/test_layer2_fast_refresh.py` records.
        """
        patches = [
            patch.object(intelligence_state_module, "central_now", return_value=now),
            patch(
                "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
                return_value={"sufficient": True, "basis": "unreclaimable", "anon_mb": 900.0},
            ),
            patch("pipeline.layer2_shortlist.build_layer2_shortlist", side_effect=self._build),
            patch("syndicate.features.shared.artifact_publisher.pull_hot_artifacts", return_value=None),
            patch.object(IntelligenceStateService, "_available_sport_manifests", return_value={"ncaaf": {}}),
            patch.object(
                intelligence_state_module,
                "write_layer2_shortlist",
                side_effect=lambda date, payload: self.written.append(date),
            ),
            patch.object(intelligence_state_module, "_mlb_sim_subprocess_running", return_value=sim),
            patch("syndicate.features.shared.deploy_drain.drain_hold_reason", return_value=drain),
            # The whole point: the carryover must never go through the queue that
            # `_watched_payload_eviction_reason` guards, nor run a full publication.
            patch.object(
                IntelligenceStateService,
                "queue_refresh",
                side_effect=AssertionError("carryover queued a board payload"),
            ),
            patch.object(
                IntelligenceStateService,
                "_compute_board_publication_response",
                side_effect=AssertionError("carryover ran a full board publication"),
            ),
            patch("builtins.print", side_effect=lambda *a, **k: self.printed.append(" ".join(str(x) for x in a))),
        ]
        for p in patches:
            p.start()
        try:
            return self.service._maybe_carry_over_prior_date_layer2()
        finally:
            for p in reversed(patches):
                p.stop()

    def _allow_next_build(self) -> None:
        """Step past the fast path's 300 s per-date rate limit."""
        self.service._layer2_fast_refresh_at.clear()

    # -- the point of the change ---------------------------------------------

    def test_a_prior_date_still_live_at_its_last_build_rebuilds_after_the_roll(self) -> None:
        self.service._note_layer2_live_signal(PRIOR, {"rows": [_live_row(), _pregame_row()], "chips_live": 1})
        result = self._run(_central(0, 30))
        self.assertIsNotNone(result, "the prior date did not rebuild after midnight CT")
        self.assertEqual(self.built, [PRIOR])
        self.assertEqual(self.written, [PRIOR])
        built_lines = [line for line in self.printed if "LAYER2_CARRYOVER" in line and "decision=built" in line]
        self.assertEqual(len(built_lines), 1, self.printed)
        self.assertIn(f"date={PRIOR}", built_lines[0])
        self.assertIn("reason=live_at_last_build", built_lines[0])

    def test_live_chips_alone_keep_the_prior_date_rebuilding(self) -> None:
        """A live game whose rows all failed the gate must not read as finished."""
        self.service._note_layer2_live_signal(PRIOR, {"rows": [_pregame_row()], "chips_live": 2})
        self._run(_central(1, 0))
        self.assertEqual(self.built, [PRIOR])

    def test_it_stops_after_a_build_that_found_nothing_live(self) -> None:
        """The LAST rebuild is the first that finds nothing in play, so the artifact
        left behind is not presenting a finished game as live."""
        self.service._note_layer2_live_signal(PRIOR, {"rows": [_live_row()], "chips_live": 1})
        self._run(_central(0, 30))
        self.assertEqual(self.built, [PRIOR])
        self.assertEqual(self.service._layer2_live_signal[PRIOR]["live_rows"], 0)
        self._allow_next_build()
        self.assertIsNone(self._run(_central(0, 45)))
        self.assertEqual(self.built, [PRIOR], "kept rebuilding a date with nothing live")
        self.assertTrue(any("reason=nothing_live_at_last_build" in line for line in self.printed), self.printed)

    def test_while_still_live_it_keeps_rebuilding(self) -> None:
        self.service._note_layer2_live_signal(PRIOR, {"rows": [_live_row()], "chips_live": 1})
        self.next_shortlist = {"rows": [_live_row()], "chips_live": 1}
        self._run(_central(0, 30))
        self._allow_next_build()
        self._run(_central(0, 40))
        self.assertEqual(self.built, [PRIOR, PRIOR])

    def test_unknown_after_a_restart_builds_once_to_learn(self) -> None:
        self._run(_central(0, 10))
        self.assertEqual(self.built, [PRIOR], "a restart after midnight left the prior date unbuilt")
        self.assertTrue(any("reason=unknown_since_restart" in line for line in self.printed), self.printed)
        self._allow_next_build()
        self._run(_central(0, 20))
        self.assertEqual(self.built, [PRIOR], "built again after learning nothing was live")

    # -- its bounds ---------------------------------------------------------

    def test_no_carryover_past_the_cap(self) -> None:
        self.service._note_layer2_live_signal(PRIOR, {"rows": [_live_row()], "chips_live": 1})
        self.assertIsNone(self._run(_central(6, 0)))
        os.environ["SYNDICATE_LAYER2_CARRYOVER_MAX_HOURS"] = "2"
        self.addCleanup(os.environ.pop, "SYNDICATE_LAYER2_CARRYOVER_MAX_HOURS", None)
        self.assertIsNone(self._run(_central(3, 0)))
        self.assertEqual(self.built, [])

    def test_zero_hours_disables_it(self) -> None:
        self.service._note_layer2_live_signal(PRIOR, {"rows": [_live_row()], "chips_live": 1})
        os.environ["SYNDICATE_LAYER2_CARRYOVER_MAX_HOURS"] = "0"
        self.addCleanup(os.environ.pop, "SYNDICATE_LAYER2_CARRYOVER_MAX_HOURS", None)
        self.assertIsNone(self._run(_central(0, 10)))
        self.assertEqual(self.built, [])
        self.assertTrue(any("reason=disabled" in line for line in self.printed), self.printed)

    def test_it_respects_the_fast_path_rate_limit_before_any_work(self) -> None:
        self.service._note_layer2_live_signal(PRIOR, {"rows": [_live_row()], "chips_live": 1})
        self.service._mark_layer2_fast_refresh(PRIOR, intelligence_state_module.time.time())
        self.assertIsNone(self._run(_central(0, 30)))
        self.assertEqual(self.built, [])
        self.assertTrue(any("reason=rate_limited" in line for line in self.printed), self.printed)

    def test_it_yields_to_a_resident_sim_and_a_deploy_drain(self) -> None:
        self.service._note_layer2_live_signal(PRIOR, {"rows": [_live_row()], "chips_live": 1})
        self.assertIsNone(self._run(_central(0, 30), sim=True))
        self.assertIsNone(self._run(_central(0, 31), drain="deploy_drain_active"))
        self.assertEqual(self.built, [])

    def test_it_yields_to_a_board_build_holding_the_guard_and_releases_its_own(self) -> None:
        self.service._note_layer2_live_signal(PRIOR, {"rows": [_live_row()], "chips_live": 1})
        self.assertTrue(self.service._execution_guard.acquire(blocking=False))
        try:
            self.assertIsNone(self._run(_central(0, 30)))
        finally:
            self.service._execution_guard.release()
        self.assertEqual(self.built, [])
        self._run(_central(0, 31))
        self.assertEqual(self.built, [PRIOR])
        self.assertFalse(self.service._execution_guard.locked(), "the carryover leaked the execution guard")

    # -- reachability: `off != on` --------------------------------------------

    def test_the_background_loop_calls_the_carryover(self) -> None:
        """Without this call every test above passes against an inert feature."""
        source = inspect.getsource(IntelligenceStateService._background_loop)
        self.assertIn("self._maybe_carry_over_prior_date_layer2()", source)

    def test_both_shortlist_build_sites_record_the_live_signal(self) -> None:
        heavy = inspect.getsource(IntelligenceStateService._build_candidate_pool)
        self.assertIn('self._note_layer2_live_signal(str(selected_date or ""), layer2_shortlist)', heavy)
        self.next_shortlist = {"rows": [_live_row(), _live_row()], "chips_live": 1}
        self._run(_central(0, 5))  # unknown -> one build through the real fast path
        self.assertEqual(self.service._layer2_live_signal[PRIOR]["live_rows"], 2)
        self.assertEqual(self.service._layer2_live_signal[PRIOR]["chips_live"], 1)


class ShortlistLiveSignalTests(unittest.TestCase):
    def test_either_state_field_counts_and_unknown_chips_stay_unknown(self) -> None:
        signal = _shortlist_live_signal(
            {
                "rows": [
                    {"game_state": "live"},
                    {"game_state": "pregame", "game": {"state": "live"}},
                    {"game_state": "final", "game": {"state": "final"}},
                    "not-a-row",
                ]
            }
        )
        self.assertEqual(signal, {"live_rows": 2, "chips_live": None})

    def test_a_boolean_is_not_a_chip_count(self) -> None:
        self.assertIsNone(_shortlist_live_signal({"rows": [], "chips_live": True})["chips_live"])
        self.assertEqual(_shortlist_live_signal({"rows": [], "chips_live": 3})["chips_live"], 3)


class LiveChipCountTests(unittest.TestCase):
    def test_counts_live_chips_and_reports_no_chips_as_unknown(self) -> None:
        from pipeline.layer2_shortlist import _live_chip_count

        self.assertIsNone(_live_chip_count([]))
        self.assertEqual(
            _live_chip_count([{"state": "live"}, {"state": "LIVE"}, {"state": "final"}, {"state": None}, "x"]),
            2,
        )

    def test_the_shortlist_carries_it(self) -> None:
        from pipeline import layer2_shortlist

        source = inspect.getsource(layer2_shortlist.build_layer2_shortlist)
        self.assertIn('shortlist["chips_live"] = _live_chip_count(_published_chips)', source)


if __name__ == "__main__":
    unittest.main()
