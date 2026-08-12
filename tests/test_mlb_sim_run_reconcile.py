"""`#388`. A killed MLB sim must leave a death certificate.

MEASURED on production 2026-08-12: 21 of 41 MLB sim runs that still had a
status record sat at `state: "running"` forever -- one 40.7h old -- while every
run that DID finish read `exit_code: 0`. **There was not a single recorded
failure, because the failure mode could not be recorded.** Correlated against
the Render events API: a deploy during the run on 9/9 orphans and 0/4
completions.

`_persist_finished_mlb_sim_run` is the only writer that can record an outcome,
and it reads the module-global `_MLB_SIM_RUN_META` -- which the container
restart that kills the sim also clears.

**These tests drive the REAL `_shared_mlb_sim_still_running` against a REAL
state directory on disk**, rather than calling the reconcile helper with a
hand-built payload. The defect class this fixes is precisely "the branch works
given the input, and nothing asserted the input arrives", so a test that
constructs the input proves the wrong half.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import live_refresh_loop


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class MlbSimRunReconcileTests(unittest.TestCase):
    DATE = "2026-08-12"
    STAMP = "20260812_180745"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.reports_root = Path(self._tmp.name)
        self.sim_dir = self.reports_root / "live_refresh_loop" / "mlb_sim_runs"
        self.sim_dir.mkdir(parents=True, exist_ok=True)
        patcher = patch.object(live_refresh_loop, "reports_root", return_value=self.reports_root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    # -- helpers ---------------------------------------------------------

    def _status_path(self) -> Path:
        return self.sim_dir / f"{self.DATE}_{self.STAMP}_status.json"

    def _write(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _read_status(self) -> dict:
        return json.loads(self._status_path().read_text(encoding="utf-8"))

    def _seed_pointer(self, *, started_at: str, pid: int = 4242) -> dict:
        meta = {
            "date": self.DATE,
            "run_stamp": self.STAMP,
            "pid": pid,
            "reason": "fingerprint_change",
            "command": ["python", "run_mlb_daily_sim_job.py"],
            "started_at": started_at,
        }
        self._write(self.sim_dir / "_active.json", meta)
        return meta

    # -- the measured case -----------------------------------------------

    def test_restart_orphan_is_recorded_not_silently_cleared(self) -> None:
        """A pointer predating this process means the container restarted and
        took the sim with it. That decision must become a record."""
        started = _iso(live_refresh_loop._PROCESS_STARTED_AT - timedelta(minutes=9))
        meta = self._seed_pointer(started_at=started)
        self._write(self._status_path(), {**meta, "state": "running"})

        self.assertFalse(live_refresh_loop._shared_mlb_sim_still_running())

        status = self._read_status()
        self.assertEqual(status["state"], "killed_by_restart")
        self.assertIn("finished_at", status)
        # The number nobody should have to re-derive from two differently
        # zoned timestamps. For an ORPHAN this is an UPPER BOUND: the run died
        # when the container did, and we only notice on the next tick, so the
        # gap includes however long the restart took. Asserted as a bound
        # rather than an equality so the test states what the field means.
        self.assertGreaterEqual(status["duration_seconds"], 9 * 60)
        self.assertLess(status["duration_seconds"], 9 * 60 + 300)
        self.assertEqual(status["finalized_by"], "orphan_reconcile")
        self.assertEqual(status["reason"], "fingerprint_change")
        # Existing behaviour preserved: the pointer is still cleared, so a
        # dead run cannot wedge future launches.
        self.assertFalse(json.loads((self.sim_dir / "_active.json").read_text(encoding="utf-8")))

    def test_status_file_absent_still_produces_a_record(self) -> None:
        """The launcher writes the status file at launch, but a run whose
        record is missing must not vanish silently either -- the pointer alone
        carries enough identity to file one."""
        started = _iso(live_refresh_loop._PROCESS_STARTED_AT - timedelta(minutes=3))
        self._seed_pointer(started_at=started)
        self.assertFalse(self._status_path().exists())

        self.assertFalse(live_refresh_loop._shared_mlb_sim_still_running())

        status = self._read_status()
        self.assertEqual(status["state"], "killed_by_restart")
        self.assertEqual(status["run_stamp"], self.STAMP)

    # -- the guard that the two-writer schema split makes necessary -------

    def test_wrapper_written_completion_is_never_overwritten(self) -> None:
        """`run_mlb_daily_sim_job.py` writes camelCase with NO `state` key.

        A naive "state != running" check reads that as unfinalized and would
        stamp a completed run as killed. This is the single most dangerous
        false positive in the fix.
        """
        started = _iso(live_refresh_loop._PROCESS_STARTED_AT - timedelta(minutes=20))
        meta = self._seed_pointer(started_at=started)
        wrapper_record = {
            **meta,
            "ok": True,
            "returnCode": 0,
            "timedOut": False,
            "publishedArtifacts": 68,
            "startedAt": started,
            "finishedAt": "2026-08-12T13:13:07-05:00",
        }
        self._write(self._status_path(), wrapper_record)

        self.assertFalse(live_refresh_loop._shared_mlb_sim_still_running())

        status = self._read_status()
        self.assertNotIn("state", status)
        self.assertEqual(status["returnCode"], 0)
        self.assertEqual(status["publishedArtifacts"], 68)
        self.assertNotIn("finalized_by", status)

    def test_already_finalized_snake_case_record_is_not_reopened(self) -> None:
        started = _iso(live_refresh_loop._PROCESS_STARTED_AT - timedelta(minutes=20))
        meta = self._seed_pointer(started_at=started)
        self._write(self._status_path(), {**meta, "state": "finished", "exit_code": 0, "finished_at": started})

        self.assertFalse(live_refresh_loop._shared_mlb_sim_still_running())

        status = self._read_status()
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["exit_code"], 0)

    # -- the other ways a run ends ---------------------------------------

    def test_dead_pid_is_recorded_as_died_untracked(self) -> None:
        """A run started AFTER this process began, whose pid is gone: not a
        restart, but still an ending nobody was recording. Must start after
        _PROCESS_STARTED_AT or the restart branch claims it first."""
        started = _iso(live_refresh_loop._PROCESS_STARTED_AT + timedelta(seconds=1))
        meta = self._seed_pointer(started_at=started)
        self._write(self._status_path(), {**meta, "state": "running"})

        with patch.object(live_refresh_loop, "_mlb_sim_progress_is_stalled", return_value=False), \
                patch.object(live_refresh_loop, "_process_exists", return_value=False):
            self.assertFalse(live_refresh_loop._shared_mlb_sim_still_running())

        self.assertEqual(self._read_status()["state"], "died_untracked")

    def test_runtime_ceiling_is_recorded(self) -> None:
        started = _iso(datetime.now(timezone.utc) - timedelta(seconds=live_refresh_loop._MLB_SIM_MAX_RUNTIME_SECONDS + 120))
        meta = self._seed_pointer(started_at=started)
        self._write(self._status_path(), {**meta, "state": "running"})

        self.assertFalse(live_refresh_loop._shared_mlb_sim_still_running())

        self.assertEqual(self._read_status()["state"], "killed_runtime_ceiling")

    # -- a genuinely live run must be left alone --------------------------

    def test_live_run_is_not_finalized(self) -> None:
        """The failure that would be worst: filing a death certificate for a
        sim that is still working."""
        started = _iso(live_refresh_loop._PROCESS_STARTED_AT + timedelta(seconds=1))
        meta = self._seed_pointer(started_at=started)
        self._write(self._status_path(), {**meta, "state": "running"})

        with patch.object(live_refresh_loop, "_mlb_sim_progress_is_stalled", return_value=False), \
                patch.object(live_refresh_loop, "_process_exists", return_value=True), \
                patch.object(live_refresh_loop, "_process_matches_lock", return_value=True):
            self.assertTrue(live_refresh_loop._shared_mlb_sim_still_running())

        status = self._read_status()
        self.assertEqual(status["state"], "running")
        self.assertNotIn("finished_at", status)
        # And the pointer survives, so the concurrency guard still holds.
        self.assertTrue(json.loads((self.sim_dir / "_active.json").read_text(encoding="utf-8")))


class MlbSimNonOwnerTests(unittest.TestCase):
    """A non-owner must not record someone else's run as dead. `#388`.

    MEASURED IN PRODUCTION 2026-08-12 20:34:43Z, two minutes after `#388` went
    live: live-odds-worker stamped run 20260812_203340 `died_untracked` with
    "pid 110 no longer exists" -- while pid 110 was alive on refresh-worker and
    climbing 1014MB -> 2251MB. The active pointer is SHARED cross-service state;
    `_process_exists` is a LOCAL probe. A non-owner asking "is pid 110 here?" is
    answering a different question than the pointer poses, and always gets no.

    This is the false positive the whole ticket warns about, arriving by a route
    the original tests did not model: they all ran as the owner.
    """

    DATE = "2026-08-12"
    STAMP = "20260812_203340"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.reports_root = Path(self._tmp.name)
        self.sim_dir = self.reports_root / "live_refresh_loop" / "mlb_sim_runs"
        self.sim_dir.mkdir(parents=True, exist_ok=True)
        patcher = patch.object(live_refresh_loop, "reports_root", return_value=self.reports_root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.status_path = self.sim_dir / f"{self.DATE}_{self.STAMP}_status.json"
        self.meta = {
            "date": self.DATE, "run_stamp": self.STAMP, "pid": 110,
            "reason": "fingerprint_change", "command": ["python", "run_mlb_daily_sim_job.py"],
            # AFTER _PROCESS_STARTED_AT, or the restart branch claims it before
            # the pid branch these tests are about ever runs.
            "started_at": _iso(live_refresh_loop._PROCESS_STARTED_AT + timedelta(seconds=1)),
        }
        (self.sim_dir / "_active.json").write_text(json.dumps(self.meta), encoding="utf-8")
        self.status_path.write_text(json.dumps({**self.meta, "state": "running"}), encoding="utf-8")

    def _run_as(self, *, owner: bool) -> dict:
        with patch.object(live_refresh_loop, "_mlb_sim_tick_owner_here", return_value=owner),                 patch.object(live_refresh_loop, "_mlb_sim_progress_is_stalled", return_value=False),                 patch.object(live_refresh_loop, "_process_exists", return_value=False):
            live_refresh_loop._shared_mlb_sim_still_running()
        return json.loads(self.status_path.read_text(encoding="utf-8"))

    def test_non_owner_does_not_write_a_death_certificate(self) -> None:
        """The production incident, reproduced."""
        status = self._run_as(owner=False)
        self.assertEqual(status["state"], "running")
        self.assertNotIn("finalized_by", status)

    def test_owner_still_records_it(self) -> None:
        """And the fix must not silence the owner too."""
        status = self._run_as(owner=True)
        self.assertEqual(status["state"], "died_untracked")
        self.assertEqual(status["finalized_by"], "orphan_reconcile")

    def test_non_owner_does_not_clear_the_pointer_either(self) -> None:
        """A non-owner must OBSERVE, not mutate.

        MEASURED IN PRODUCTION 2026-08-12: gating only the WRITE was not enough.
        Run 20260812_220813 was killed by a refresh-worker restart at 22:19Z and
        still read `state: running` with no orphan line anywhere -- because
        live-odds-worker had already cleared the shared pointer (it can never see
        the owner's pid), so when the owner rebooted there was nothing left to
        reconcile from. The gate stopped the false record AND removed the trace
        the real record needed.
        """
        self._run_as(owner=False)
        pointer = json.loads((self.sim_dir / "_active.json").read_text(encoding="utf-8"))
        self.assertTrue(pointer, "a non-owner erased the pointer the owner needs")
        self.assertEqual(pointer["run_stamp"], self.STAMP)

    def test_owner_still_clears_the_pointer(self) -> None:
        """And the owner must still clear, or a dead run wedges every future
        launch -- the failure the ungated clear existed to prevent."""
        self._run_as(owner=True)
        self.assertFalse(json.loads((self.sim_dir / "_active.json").read_text(encoding="utf-8")))


class MlbSimFinalizeMergeTests(unittest.TestCase):
    """`#388` second defect: two writers, one path, last writer wins.

    MEASURED: 40 of 41 records carried the launcher schema, so the wrapper's
    `publishedArtifacts`/`timedOut` were destroyed in 98% of runs.
    """

    DATE = "2026-08-12"
    STAMP = "20260812_052043"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.reports_root = Path(self._tmp.name)
        self.sim_dir = self.reports_root / "live_refresh_loop" / "mlb_sim_runs"
        self.sim_dir.mkdir(parents=True, exist_ok=True)
        patcher = patch.object(live_refresh_loop, "reports_root", return_value=self.reports_root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_launcher_finalize_preserves_wrapper_fields(self) -> None:
        started = _iso(datetime.now(timezone.utc) - timedelta(minutes=15))
        status_path = self.sim_dir / f"{self.DATE}_{self.STAMP}_status.json"
        status_path.write_text(
            json.dumps({"ok": True, "returnCode": 0, "timedOut": False, "publishedArtifacts": 68,
                        "sims": 1000, "workers": 2, "startedAt": started}),
            encoding="utf-8",
        )

        class _FakeProcess:
            returncode = 0

        with patch.object(live_refresh_loop, "_MLB_SIM_RUN_META",
                          {"date": self.DATE, "run_stamp": self.STAMP, "pid": 99,
                           "reason": "fingerprint_change", "started_at": started}), \
                patch.object(live_refresh_loop, "_MLB_SIM_PROCESS", _FakeProcess()), \
                patch.object(live_refresh_loop, "_MLB_SIM_LOG_HANDLE", None), \
                patch.object(live_refresh_loop, "_MLB_SIM_LOG_PATH", None):
            live_refresh_loop._persist_finished_mlb_sim_run()

        status = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["exit_code"], 0)
        # The whole point: these came from the OTHER writer and survived.
        self.assertEqual(status["publishedArtifacts"], 68)
        self.assertEqual(status["timedOut"], False)
        self.assertEqual(status["sims"], 1000)
        self.assertEqual(status["duration_seconds"], 15 * 60)


if __name__ == "__main__":
    unittest.main()
