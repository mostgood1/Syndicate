"""Progress-stall watchdog for a hung MLB daily sim.

_MLB_SIM_MAX_RUNTIME_SECONDS is a TOTAL-runtime ceiling (90 min), so a sim
that dies early still holds the slot for the remainder. Observed live
2026-08-04: pid 2517 wrote progress once at game 1 of 15, twenty seconds in,
then never again, and was still reported "running" 93 minutes later. For
that entire window no further sim could launch -- which silently disables
the props self-heal -- and every deploy was refused.

The guiding constraint in these tests: a MISSING or unreadable progress file
must never be treated as a hang. Killing a healthy run on absent evidence is
far worse than waiting for the runtime ceiling.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from syndicate.features.shared import live_refresh_loop


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class MlbSimProgressWatchdogTests(unittest.TestCase):
    META = {"date": "2026-08-04", "run_stamp": "20260804_175808"}

    def _stalled(self, progress: object) -> bool:
        with patch.object(live_refresh_loop, "read_json_file", return_value=progress):
            return live_refresh_loop._mlb_sim_progress_is_stalled(dict(self.META))

    def test_fresh_progress_is_not_stalled(self) -> None:
        recent = _iso(datetime.now(timezone.utc) - timedelta(minutes=2))
        self.assertFalse(self._stalled({"done": False, "updated_at": recent, "game_index": 4}))

    def test_progress_older_than_threshold_is_stalled(self) -> None:
        old = _iso(datetime.now(timezone.utc) - timedelta(minutes=40))
        self.assertTrue(self._stalled({"done": False, "updated_at": old, "game_index": 1}))

    def test_the_real_incident_shape_is_caught(self) -> None:
        # pid 2517: game 1 of 15, 20 seconds in, then silent for 93 minutes.
        old = _iso(datetime.now(timezone.utc) - timedelta(minutes=93))
        self.assertTrue(
            self._stalled(
                {
                    "done": False,
                    "elapsed_seconds": 20.0,
                    "game_index": 1,
                    "game_total": 15,
                    "last_line": "Simulating (1000, workers=2): LAA @ BAL",
                    "updated_at": old,
                }
            )
        )

    def test_completed_run_is_never_stalled(self) -> None:
        old = _iso(datetime.now(timezone.utc) - timedelta(hours=5))
        self.assertFalse(self._stalled({"done": True, "updated_at": old}))

    def test_missing_progress_file_is_not_a_hang(self) -> None:
        # A run that has not written its first snapshot yet must fall through
        # to the runtime ceiling, not be killed on absent evidence.
        self.assertFalse(self._stalled(None))
        self.assertFalse(self._stalled({}))

    def test_unparsable_timestamp_is_not_a_hang(self) -> None:
        self.assertFalse(self._stalled({"done": False, "updated_at": "not-a-timestamp"}))
        self.assertFalse(self._stalled({"done": False, "updated_at": ""}))

    def test_meta_without_run_identity_is_not_a_hang(self) -> None:
        with patch.object(live_refresh_loop, "read_json_file", return_value={"done": False, "updated_at": _iso(datetime.now(timezone.utc) - timedelta(hours=2))}):
            self.assertFalse(live_refresh_loop._mlb_sim_progress_is_stalled({"date": "", "run_stamp": ""}))
            self.assertFalse(live_refresh_loop._mlb_sim_progress_is_stalled(None))

    def test_read_failure_is_not_a_hang(self) -> None:
        with patch.object(live_refresh_loop, "read_json_file", side_effect=OSError("disk gone")):
            self.assertFalse(live_refresh_loop._mlb_sim_progress_is_stalled(dict(self.META)))

    def test_threshold_floor_prevents_killing_healthy_runs(self) -> None:
        # A single game takes ~3 minutes; the floor must stay above that even
        # if the env var is set absurdly low.
        with patch.dict("os.environ", {"SYNDICATE_MLB_SIM_MAX_PROGRESS_STALL_SECONDS": "1"}, clear=False):
            self.assertGreaterEqual(live_refresh_loop._mlb_sim_max_progress_stall_seconds(), 300)

    def test_threshold_is_env_tunable_and_defaults_to_15_minutes(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("SYNDICATE_MLB_SIM_MAX_PROGRESS_STALL_SECONDS", None)
            self.assertEqual(live_refresh_loop._mlb_sim_max_progress_stall_seconds(), 900)
        with patch.dict("os.environ", {"SYNDICATE_MLB_SIM_MAX_PROGRESS_STALL_SECONDS": "1800"}, clear=False):
            self.assertEqual(live_refresh_loop._mlb_sim_max_progress_stall_seconds(), 1800)
        with patch.dict("os.environ", {"SYNDICATE_MLB_SIM_MAX_PROGRESS_STALL_SECONDS": "garbage"}, clear=False):
            self.assertEqual(live_refresh_loop._mlb_sim_max_progress_stall_seconds(), 900)


class SharedPointerClearsOnStallTests(unittest.TestCase):
    def test_shared_pointer_is_cleared_when_progress_stalls(self) -> None:
        """The cross-container path is the one that wedged production."""
        started = _iso(datetime.now(timezone.utc) - timedelta(minutes=30))  # well under the 90m ceiling
        pointer = {"pid": 2517, "started_at": started, "date": "2026-08-04", "run_stamp": "20260804_175808"}
        with patch.object(live_refresh_loop, "read_json_file", return_value=pointer), patch.object(
            live_refresh_loop, "_mlb_sim_progress_is_stalled", return_value=True
        ), patch.object(live_refresh_loop, "_clear_active_pointer") as mocked_clear:
            still_running = live_refresh_loop._shared_mlb_sim_still_running()
        self.assertFalse(still_running, "a stalled run must not report as running")
        mocked_clear.assert_called_once()

    # NOTE: there is deliberately no end-to-end "healthy run survives" test
    # here. _shared_mlb_sim_still_running has other legitimate reasons to
    # clear the pointer -- most notably a PID that is not alive on this
    # container -- so asserting "not cleared" would pass or fail for reasons
    # unrelated to the stall branch, and would have to fake a live PID to
    # mean anything. An early version of this test did exactly that and
    # failed against correct code.
    #
    # The guarantee that matters (a healthy run is never killed by THIS
    # change) is covered precisely by the _mlb_sim_progress_is_stalled cases
    # above: fresh progress, missing file, unparsable stamp, read failure and
    # done=True all return False, and the new branch only ever fires on True.


if __name__ == "__main__":
    unittest.main()
