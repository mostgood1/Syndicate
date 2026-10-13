"""NFL pbp morning fetch (lane nfl-mnf-settlement-lag, 2026-10-13)."""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location("rrw", Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py")
rrw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rrw)


def _ts(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


class MorningDue(unittest.TestCase):
    def test_the_measured_case_fetches_the_next_morning(self) -> None:
        # Last fetch 2026-10-13 03:34Z (during MNF); at 10:00Z it is due again.
        self.assertTrue(rrw._nfl_pbp_fetch_morning_due(now_epoch=_ts("2026-10-13T10:00:30"), last_attempt_epoch=_ts("2026-10-13T03:34:01")))

    def test_not_before_the_morning_hour(self) -> None:
        self.assertFalse(rrw._nfl_pbp_fetch_morning_due(now_epoch=_ts("2026-10-13T09:59:00"), last_attempt_epoch=_ts("2026-10-13T03:34:01")))

    def test_once_a_day(self) -> None:
        # A fetch at 10:00:30Z resets it; later the same day it is not due.
        self.assertFalse(rrw._nfl_pbp_fetch_morning_due(now_epoch=_ts("2026-10-13T18:00:00"), last_attempt_epoch=_ts("2026-10-13T10:00:30")))

    def test_first_ever_fetch_is_left_to_the_interval_branch(self) -> None:
        self.assertFalse(rrw._nfl_pbp_fetch_morning_due(now_epoch=_ts("2026-10-13T11:00:00"), last_attempt_epoch=0.0))

    def test_hour_is_configurable(self) -> None:
        with mock.patch.dict("os.environ", {"NFL_PBP_FETCH_MORNING_HOUR_UTC": "11"}):
            self.assertFalse(rrw._nfl_pbp_fetch_morning_due(now_epoch=_ts("2026-10-13T10:30:00"), last_attempt_epoch=_ts("2026-10-13T03:34:01")))


class LaunchGateReachability(unittest.TestCase):
    """off != on: the same marker age launches only when the morning is due."""

    def _launch(self, now: str, last: str) -> bool:
        state = {"attempted_at_epoch": _ts(last)}
        store = {"read_json_file": lambda _p: state, "write_json_file": lambda _p, _d: None, "reports_root": lambda: Path(".")}
        with mock.patch.object(rrw, "_nfl_pbp_fetch_enabled", return_value=True), \
                mock.patch.object(rrw, "_active_sports_for_date", return_value="nfl"), \
                mock.patch.object(rrw, "_refresh_state_store", return_value=store), \
                mock.patch.object(rrw.time, "time", return_value=_ts(now)), \
                mock.patch.object(rrw.subprocess, "Popen") as popen, \
                mock.patch.object(rrw, "_write_worker_status"), \
                mock.patch.object(rrw, "_latest_manifest_payload", return_value={}):
            rrw._launch_autorun_nfl_pbp_fetch(latest_manifest_path=Path("x"), worker_status_path=Path("y"), refresh_cycle={})
            return popen.called

    def test_rate_limited_before_the_morning_hour(self) -> None:
        self.assertFalse(self._launch("2026-10-13T09:30:00", "2026-10-13T03:34:01"))

    def test_launches_after_the_morning_hour(self) -> None:
        self.assertTrue(self._launch("2026-10-13T10:01:00", "2026-10-13T03:34:01"))


if __name__ == "__main__":
    unittest.main()
