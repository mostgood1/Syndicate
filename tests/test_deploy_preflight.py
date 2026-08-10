"""#324. The pre-flight's classifier, which decides whether a deploy kills work.

The check this replaces probed three remembered log tokens and printed one
global "PREFLIGHT: CLEAR TO DEPLOY" while an NFL smartsim child had started 61
seconds earlier. So the properties worth pinning are not "does it find the
hazard I thought of" but the structural ones: unrecognised things must land on
the BLOCKING side, and the long-lived server must not.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "deploy_preflight", Path(__file__).resolve().parents[1] / "scripts" / "deploy_preflight.py"
)
deploy_preflight = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(deploy_preflight)


def _p(pid, ppid, cmdline, rss=10.0):
    return {"pid": pid, "ppid": ppid, "cmdline": cmdline, "rss_mb": rss}


WORKER_SHELL = _p(1, 0, ["bash", "/home/render/graceful-shell-command.sh", "python", "scripts/run_refresh_worker.py"])
WORKER_MAIN = _p(38, 1, ["python", "scripts/run_refresh_worker.py"], 820.0)
NFL_CHILD = _p(1693, 38, ["/opt/render/project/src/.venv/bin/python",
                          "/opt/render/project/src/scripts/generate_smartsim2_nfl_preseason_projections.py",
                          "--season", "2026", "--week", "2"], 26.1)


class ClassifyTests(unittest.TestCase):
    def test_the_real_15_54_topology_is_a_hold(self) -> None:
        # Exactly the process list that was live when the old check said CLEAR.
        infra, jobs, unknown = deploy_preflight.classify([WORKER_SHELL, WORKER_MAIN, NFL_CHILD])
        self.assertEqual({p["pid"] for p in infra}, {1, 38})
        self.assertEqual([p["pid"] for p in jobs], [1693])
        self.assertEqual(unknown, [])

    def test_idle_worker_is_clear(self) -> None:
        infra, jobs, unknown = deploy_preflight.classify([WORKER_SHELL, WORKER_MAIN])
        self.assertEqual(len(infra), 2)
        self.assertFalse(jobs)
        self.assertFalse(unknown)

    def test_child_with_no_cmdline_is_unknown_not_clear(self) -> None:
        # A zombie, or a process that exited mid-enumeration. It is not nothing,
        # and "unknown" must not fall through to the permissive branch.
        infra, jobs, unknown = deploy_preflight.classify([WORKER_SHELL, WORKER_MAIN, _p(1457, 38, [], None)])
        self.assertEqual([p["pid"] for p in unknown], [1457])
        self.assertFalse(jobs)

    def test_an_unrecognised_process_blocks_rather_than_passes(self) -> None:
        # THE load-bearing property. The old design could only find hazards it
        # already knew the name of; this one must treat a never-before-seen
        # child as work. Being wrong here costs a spurious HOLD, not a dead job.
        infra, jobs, unknown = deploy_preflight.classify(
            [WORKER_SHELL, WORKER_MAIN, _p(999, 38, ["python", "scripts/some_job_invented_next_year.py"])]
        )
        self.assertEqual([p["pid"] for p in jobs], [999])

    def test_gunicorn_workers_are_infrastructure_not_jobs(self) -> None:
        # Web forks its workers from the gunicorn MASTER, not from the shell, so
        # a purely topological rule marks them as jobs and web can never deploy.
        gunicorn = ["/opt/render/project/src/.venv/bin/python3.11", "/opt/render/project/src/.venv/bin/gunicorn", "wsgi:app"]
        infra, jobs, unknown = deploy_preflight.classify([
            _p(1, 0, ["bash", "/home/render/graceful-shell-command.sh", "sh", "-c", "exec gunicorn wsgi:app"]),
            _p(62, 1, gunicorn), _p(79, 62, gunicorn), _p(80, 62, gunicorn),
        ])
        self.assertEqual(len(infra), 4)
        self.assertFalse(jobs, "gunicorn workers must not read as work in flight")

    def test_a_job_on_web_is_still_caught(self) -> None:
        gunicorn = ["/opt/render/project/src/.venv/bin/python3.11", "/opt/render/project/src/.venv/bin/gunicorn", "wsgi:app"]
        infra, jobs, unknown = deploy_preflight.classify([
            _p(1, 0, ["bash", "/home/render/graceful-shell-command.sh"]),
            _p(62, 1, gunicorn), _p(79, 62, gunicorn),
            _p(500, 79, ["python", "scripts/daily_update.py", "--sport", "mlb"]),
        ])
        self.assertEqual([p["pid"] for p in jobs], [500])


class NewestLogOrderingTests(unittest.TestCase):
    """The API returns the newest N presented OLDEST-FIRST, with or without
    `direction=backward` (measured 2026-08-10). Reading rows[0] as "latest"
    produced a four-hour error in the direction that says "safe to deploy"."""

    def test_newest_is_selected_by_sorting_not_by_position(self) -> None:
        rows = [
            {"timestamp": "2026-08-10T15:21:55Z", "message": "ALL_PROCESS_MEMORY {}"},
            {"timestamp": "2026-08-10T15:56:02Z", "message": "ALL_PROCESS_MEMORY {}"},
        ]
        captured = {}

        def fake_get(url, key):
            captured["url"] = url
            return {"logs": rows}

        original = deploy_preflight._get
        deploy_preflight._get = fake_get
        try:
            newest = deploy_preflight.newest_log("srv-x", "k", "ALL_PROCESS_MEMORY")
        finally:
            deploy_preflight._get = original
        self.assertEqual(newest[0], "2026-08-10T15:56:02Z", "must sort, not take rows[0] or rows[-1] on faith")

    def test_substring_over_match_is_filtered_out(self) -> None:
        # The filter is a case-insensitive SUBSTRING match: MALLOC_TRIM also
        # hits MALLOC_TRIM_INIT, and CONTAINER_MEMORY hits
        # container_memory_headroom_mb. Non-matching rows must be dropped.
        rows = [
            {"timestamp": "2026-08-10T15:00:00Z", "message": 'ALL_PROCESS_MEMORY {"a":1}'},
            {"timestamp": "2026-08-10T15:59:00Z", "message": 'SOMETHING_ELSE {"container_memory_mb": 1}'},
        ]
        original = deploy_preflight._get
        deploy_preflight._get = lambda url, key: {"logs": rows}
        try:
            newest = deploy_preflight.newest_log("srv-x", "k", "ALL_PROCESS_MEMORY")
        finally:
            deploy_preflight._get = original
        self.assertEqual(newest[0], "2026-08-10T15:00:00Z")


if __name__ == "__main__":
    unittest.main()
