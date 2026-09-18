"""The MLB sim's fingerprint re-runs are rate-limited, and a limited change is DEFERRED, never lost.

WHY (lane `mlb-sim-retrigger-churn`, 2026-09-17). Measured on refresh-worker over
12 h: 19 `fingerprint_change` re-sims, back to back from 20:10Z to 23:04Z, 44%
of the worker's wall time, with the memory guard refusing the board 31 times
while they ran. A run's cost does not scale with its scope -- one game took
14.9 min, five took 15.8 -- so the lever is how often a run may START, not how
little it covers.

THE PROPERTY THAT MATTERS MOST is `test_a_debounced_change_is_not_absorbed`:
recording the current fingerprints during the gap would mark the changed games
as seen and they would never re-sim. Every other test is about which triggers
the gap may and may not hold back.
"""

from __future__ import annotations

import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from syndicate.features.shared import live_refresh_loop as lrl

DATE = "2026-09-17"
STORED = {"100": "aaa", "200": "bbb", "300": "ccc"}
CURRENT = {"100": "aaa", "200": "CHANGED", "300": "ccc"}


def _events():
    return [
        lrl.ScheduleEvent(sport="mlb", event_id=pk, home=f"H{pk}", away=f"A{pk}", start_time_utc=None)
        for pk in ("100", "200", "300")
    ]


class _Harness:
    """The existing decision-test patch stack (tests/test_live_refresh_loop.py), made reusable."""

    def __init__(self, *, now: float, last_check_epoch: float, env: dict | None = None,
                 current=None, join=None, board_missing=None, props_regen=False, tip_off=None):
        self.now = now
        self.last_check_epoch = last_check_epoch
        self.env = {"SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER": "true", **(env or {})}
        self.current = dict(CURRENT if current is None else current)
        self.join = list(join or [])
        self.board_missing = list(board_missing or [])
        self.props_regen = props_regen
        self.tip_off = list(tip_off or [])

    def run(self):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, self.env, clear=False))
            p = lambda name, **kw: stack.enter_context(patch.object(lrl, name, **kw))  # noqa: E731
            p("_mlb_daily_sim_process_still_running", return_value=False)
            p("is_refresh_run_active", return_value=False)
            p("fetch_schedule_for_date", return_value=_events())
            summary = p("_mlb_daily_summary_path")
            summary.return_value.exists.return_value = True
            p("events_starting_within", return_value=[e for e in _events() if e.event_id in self.tip_off])
            p("_read_last_mlb_sim_check", return_value={"epoch": self.last_check_epoch, "date": DATE, "fingerprints": dict(STORED)})
            p("_fetch_mlb_injuries", return_value=True)
            p("_fetch_mlb_lineup_state", return_value=True)
            p("_mlb_sim_input_fingerprint_by_game", return_value=dict(self.current))
            p("_mlb_join_mismatch_game_pks", return_value=list(self.join))
            p("_mlb_board_missing_game_pks", return_value=list(self.board_missing))
            p("_mlb_props_now_available_needs_regen", return_value=self.props_regen)
            p("_mlb_sim_memory_headroom_snapshot", return_value=None)
            p("_sim_pipeline_deferral_reason", return_value=None)
            self.recorded = p("_record_mlb_sim_check")
            return lrl._mlb_daily_sim_decision(now_epoch=self.now, date_str=DATE)


class KnobTests(unittest.TestCase):
    def test_default_is_one_hour(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_MLB_SIM_FINGERPRINT_MIN_GAP_SECONDS", None)
            self.assertEqual(lrl._mlb_sim_fingerprint_min_gap_seconds(), 3600)

    def test_zero_disables_and_garbage_falls_back_to_the_default(self):
        cases = {"0": 0, "-5": 0, "900": 900, "not a number": 3600}
        for raw, expected in cases.items():
            with self.subTest(raw=raw), patch.dict(os.environ, {"SYNDICATE_MLB_SIM_FINGERPRINT_MIN_GAP_SECONDS": raw}):
                self.assertEqual(lrl._mlb_sim_fingerprint_min_gap_seconds(), expected)


class DebounceTests(unittest.TestCase):
    """now=10_000; the last fingerprint launch at 9_000 is 1,000 s ago, inside a 3,600 s gap."""

    def setUp(self):
        lrl._record_mlb_fingerprint_launch(now_epoch=9_000.0, date_str=DATE, game_pks=["100"])

    def test_reachability_off_is_not_on(self):
        # The flag's two positions must produce different decisions on the same
        # inputs, or the feature is inert (model_engine_standard.md).
        on = _Harness(now=10_000.0, last_check_epoch=9_000.0).run()
        off = _Harness(now=10_000.0, last_check_epoch=9_000.0,
                       env={"SYNDICATE_MLB_SIM_FINGERPRINT_MIN_GAP_SECONDS": "0"}).run()
        self.assertEqual(on["reason"], "fingerprint_debounced")
        self.assertFalse(on["force"])
        self.assertEqual(off["reason"], "fingerprint_change")
        self.assertTrue(off["force"])

    def test_a_debounced_change_is_not_absorbed(self):
        h = _Harness(now=10_000.0, last_check_epoch=9_000.0)
        decision = h.run()
        self.assertEqual(decision["changed_game_pks"], ["200"])
        # The check IS recorded (so the interval keeps pacing it) ...
        h.recorded.assert_called_once()
        args, kwargs = h.recorded.call_args
        # ... but with the OLD fingerprints, so game 200 is still "changed" next time.
        self.assertEqual(args[2], STORED)
        self.assertEqual(args[2]["200"], "bbb")
        self.assertFalse(kwargs.get("launched"))

    def test_after_the_gap_the_deferred_games_launch_together(self):
        later = {"100": "aaa", "200": "CHANGED", "300": "ALSO_CHANGED"}
        decision = _Harness(now=9_000.0 + 3_601.0, last_check_epoch=12_000.0, current=later).run()
        self.assertTrue(decision["force"])
        self.assertEqual(decision["reason"], "fingerprint_change")
        self.assertEqual(decision["game_pks"], ["200", "300"])

    def test_a_launch_starts_the_gap(self):
        _Harness(now=20_000.0, last_check_epoch=19_000.0).run()  # 11,000 s after the setUp mark: launches
        self.assertEqual(lrl._read_last_mlb_fingerprint_launch_epoch(DATE), 20_000.0)
        again = _Harness(now=20_600.0, last_check_epoch=20_000.0).run()
        self.assertEqual(again["reason"], "fingerprint_debounced")

    def test_repair_triggers_are_never_held_back(self):
        # These fix a board that is visibly wrong; they launch at once and carry
        # the changed games with them.
        for label, kw in (("join_mismatch", {"join": ["300"]}),
                          ("board_missing", {"board_missing": ["300"]}),
                          ("props_regen", {"props_regen": True})):
            with self.subTest(label):
                decision = _Harness(now=10_000.0, last_check_epoch=9_000.0, **kw).run()
                self.assertTrue(decision["force"], decision)
                self.assertIn("200", decision["game_pks"])

    def test_the_tip_off_window_is_untouched(self):
        # It returns before the interval and the debounce are consulted, which
        # is what makes throttling the fingerprint path safe near first pitch.
        decision = _Harness(now=10_000.0, last_check_epoch=9_000.0, tip_off=["300"],
                            env={"SYNDICATE_EVENT_SIM_FORCE_WINDOW_MINUTES": "30"}).run()
        self.assertEqual(decision["reason"], "tip_off_window")
        self.assertTrue(decision["force"])

    def test_a_new_day_launches_at_once(self):
        lrl._record_mlb_fingerprint_launch(now_epoch=9_900.0, date_str="2026-09-16", game_pks=["100"])
        decision = _Harness(now=10_000.0, last_check_epoch=9_000.0).run()
        self.assertEqual(decision["reason"], "fingerprint_change")

    def test_an_unreadable_marker_fails_open(self):
        with patch.object(lrl, "read_json_file", side_effect=OSError("disk")):
            self.assertEqual(lrl._read_last_mlb_fingerprint_launch_epoch(DATE), 0.0)


if __name__ == "__main__":
    unittest.main()
