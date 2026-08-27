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


def _p(pid, ppid, cmdline, rss=10.0, name="python"):
    return {"pid": pid, "ppid": ppid, "cmdline": cmdline, "rss_mb": rss, "name": name}


WORKER_SHELL = _p(1, 0, ["bash", "/home/render/graceful-shell-command.sh", "python", "scripts/run_refresh_worker.py"])
WORKER_MAIN = _p(38, 1, ["python", "scripts/run_refresh_worker.py"], 820.0)
NFL_CHILD = _p(1693, 38, ["/opt/render/project/src/.venv/bin/python",
                          "/opt/render/project/src/scripts/generate_smartsim2_nfl_preseason_projections.py",
                          "--season", "2026", "--week", "2"], 26.1)


class ClassifyTests(unittest.TestCase):
    def test_the_real_15_54_topology_is_a_hold(self) -> None:
        # Exactly the process list that was live when the old check said CLEAR.
        infra, jobs, defunct, unknown = deploy_preflight.classify([WORKER_SHELL, WORKER_MAIN, NFL_CHILD])
        self.assertEqual({p["pid"] for p in infra}, {1, 38})
        self.assertEqual([p["pid"] for p in jobs], [1693])
        self.assertEqual(unknown, [])

    def test_idle_worker_is_clear(self) -> None:
        infra, jobs, defunct, unknown = deploy_preflight.classify([WORKER_SHELL, WORKER_MAIN])
        self.assertEqual(len(infra), 2)
        self.assertFalse(jobs)
        self.assertFalse(unknown)

    def test_a_zombie_is_reported_but_does_not_block(self) -> None:
        # #324, measured: pid 1457 sat in 108/342 samples over 15 minutes. Under
        # the first version this returned UNKNOWN forever, which would have made
        # the check useless on the one service it was built for. A zombie is
        # already dead -- a deploy cannot kill it.
        # name readable + no VmRSS + no cmdline == state Z.
        infra, jobs, defunct, unknown = deploy_preflight.classify(
            [WORKER_SHELL, WORKER_MAIN, _p(1457, 38, [], None, name="python")]
        )
        self.assertEqual([p["pid"] for p in defunct], [1457])
        self.assertFalse(jobs)
        self.assertFalse(unknown)

    def test_a_process_we_cannot_read_at_all_still_blocks(self) -> None:
        # No name either -> we genuinely do not know what it is, so it might be
        # live work. This is the case that must NOT be relaxed by the zombie fix.
        infra, jobs, defunct, unknown = deploy_preflight.classify(
            [WORKER_SHELL, WORKER_MAIN, _p(1457, 38, [], None, name="")]
        )
        self.assertEqual([p["pid"] for p in unknown], [1457])
        self.assertFalse(defunct)

    def test_an_unrecognised_process_blocks_rather_than_passes(self) -> None:
        # THE load-bearing property. The old design could only find hazards it
        # already knew the name of; this one must treat a never-before-seen
        # child as work. Being wrong here costs a spurious HOLD, not a dead job.
        infra, jobs, defunct, unknown = deploy_preflight.classify(
            [WORKER_SHELL, WORKER_MAIN, _p(999, 38, ["python", "scripts/some_job_invented_next_year.py"])]
        )
        self.assertEqual([p["pid"] for p in jobs], [999])

    def test_gunicorn_workers_are_infrastructure_not_jobs(self) -> None:
        # Web forks its workers from the gunicorn MASTER, not from the shell, so
        # a purely topological rule marks them as jobs and web can never deploy.
        gunicorn = ["/opt/render/project/src/.venv/bin/python3.11", "/opt/render/project/src/.venv/bin/gunicorn", "wsgi:app"]
        infra, jobs, defunct, unknown = deploy_preflight.classify([
            _p(1, 0, ["bash", "/home/render/graceful-shell-command.sh", "sh", "-c", "exec gunicorn wsgi:app"]),
            _p(62, 1, gunicorn), _p(79, 62, gunicorn), _p(80, 62, gunicorn),
        ])
        self.assertEqual(len(infra), 4)
        self.assertFalse(jobs, "gunicorn workers must not read as work in flight")

    def test_a_job_on_web_is_still_caught(self) -> None:
        gunicorn = ["/opt/render/project/src/.venv/bin/python3.11", "/opt/render/project/src/.venv/bin/gunicorn", "wsgi:app"]
        infra, jobs, defunct, unknown = deploy_preflight.classify([
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


class FleetCommitTests(unittest.TestCase):
    """D5. The commit you need is the one for the service you are NOT deploying.

    Deploy drift reached four audits because the pre-flight reported a single
    service. These pin the two properties that make the fleet block trustworthy:
    it covers all three services exactly once, and a per-service read failure
    degrades that row instead of taking down the gate.
    """

    def test_fleet_is_the_three_real_services_not_the_alias(self) -> None:
        # SERVICE_IDS carries `syndicate` as an alias for `web`; counting both
        # would report the same container twice and hide one of the workers.
        self.assertEqual(len(deploy_preflight.FLEET), 3)
        ids = [deploy_preflight.SERVICE_IDS[n] for n in deploy_preflight.FLEET]
        self.assertEqual(len(set(ids)), 3, "a service is double-counted")

    def test_every_service_is_reported(self) -> None:
        calls = []

        def fake_live_deploy(service_id, key):
            calls.append(service_id)
            return {"commit": {"id": "abcdef1234567890"}, "finishedAt": "2026-08-15T00:00:00Z"}

        original = deploy_preflight.live_deploy
        deploy_preflight.live_deploy = fake_live_deploy
        try:
            fleet = deploy_preflight.fleet_live_commits("key")
        finally:
            deploy_preflight.live_deploy = original

        self.assertEqual(set(fleet), set(deploy_preflight.FLEET))
        self.assertEqual(len(calls), 3)
        self.assertEqual(fleet["web"]["live_commit"], "abcdef12")

    def test_one_unreadable_service_does_not_take_down_the_others(self) -> None:
        """A throttled or failing read must render as UNREADABLE, never as a
        commit of `None` indistinguishable from 'never deployed'."""

        def flaky_live_deploy(service_id, key):
            if service_id == deploy_preflight.SERVICE_IDS["refresh-worker"]:
                raise RuntimeError("429 throttled")
            return {"commit": {"id": "0" * 40}, "finishedAt": "2026-08-15T00:00:00Z"}

        original = deploy_preflight.live_deploy
        deploy_preflight.live_deploy = flaky_live_deploy
        try:
            fleet = deploy_preflight.fleet_live_commits("key")
        finally:
            deploy_preflight.live_deploy = original

        self.assertIn("error", fleet["refresh-worker"])
        self.assertIsNone(fleet["refresh-worker"]["live_commit"])
        self.assertEqual(fleet["web"]["live_commit"], "00000000")
        self.assertNotIn("error", fleet["live-odds-worker"])


# --------------------------------------------------------------------------
# `#563` -- SPACING. The third independent property, after serialisation
# (CLAIMED) and composition (OFF_MAIN).
#
# Measured 2026-08-25/26: refresh-worker took 15 deploys in 6h15m, all
# trigger=api, and logged 15 SIGTERM shutdowns with a median instance uptime of
# 1202 s against a 20 min 41 s boot-to-first-publish. Every one of those deploys
# was correctly claimed and released, and on main. The board was frozen all
# evening anyway. Serialisation is not spacing.
# --------------------------------------------------------------------------
import os
from datetime import datetime, timedelta, timezone
from unittest import mock


def _deploy(status="live", minutes_ago=30.0, deploy_id="dep-x", trigger="api", field="finishedAt"):
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {"deploy": {"id": deploy_id, "status": status, "trigger": trigger,
                       "commit": {"id": "abc123def456"},
                       field: moment.strftime("%Y-%m-%dT%H:%M:%SZ")}}


class MinDeployIntervalTests(unittest.TestCase):
    def test_refresh_worker_is_spaced_past_its_measured_cycle(self) -> None:
        # Boot-to-first-publish was 20 min 41 s. Any limit at or under that
        # guarantees a board that never publishes, so this is the assertion that
        # actually encodes the measurement.
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS"):
                    del os.environ[key]
            self.assertGreater(deploy_preflight.min_deploy_interval_seconds("refresh-worker"), 1241)

    def test_unmeasured_services_are_zero_rather_than_a_guess(self) -> None:
        # live-odds-worker has no WORKER_SHUTDOWN handler, so the uptime figure
        # that made refresh-worker's case does not exist for it. Inventing a
        # number here is the failure mode; 0 plus a printed "not rate-limited"
        # is the honest one.
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS"):
                    del os.environ[key]
            self.assertEqual(deploy_preflight.min_deploy_interval_seconds("live-odds-worker"), 0)
            self.assertEqual(deploy_preflight.min_deploy_interval_seconds("web"), 0)

    def test_per_service_override_beats_the_global_one(self) -> None:
        with mock.patch.dict(os.environ, {
            "SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS": "60",
            "SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS_REFRESH_WORKER": "999",
        }):
            self.assertEqual(deploy_preflight.min_deploy_interval_seconds("refresh-worker"), 999)
            self.assertEqual(deploy_preflight.min_deploy_interval_seconds("web"), 60)

    def test_a_malformed_override_falls_back_instead_of_raising(self) -> None:
        # A preflight that dies on a bad env var teaches people to skip the
        # preflight, which costs more than the bad value did.
        with mock.patch.dict(os.environ, {"SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS_WEB": "banana"}):
            self.assertEqual(deploy_preflight.min_deploy_interval_seconds("web"), 0)

    def test_zero_disables_the_check(self) -> None:
        with mock.patch.dict(os.environ, {"SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS_REFRESH_WORKER": "0"}):
            self.assertEqual(deploy_preflight.min_deploy_interval_seconds("refresh-worker"), 0)


class LastRestartingDeployTests(unittest.TestCase):
    def _last(self, rows):
        with mock.patch.object(deploy_preflight, "_get", return_value=rows):
            return deploy_preflight.last_restarting_deploy("srv-x", "key")

    def test_newest_is_selected_by_SORTING_not_by_position(self) -> None:
        # This file's own header records that the Render endpoints do not return
        # what their ordering suggests, and that reading rows[0] as newest
        # produced a four-hour error in the direction that says "safe to deploy".
        rows = [
            _deploy(minutes_ago=90, deploy_id="dep-old"),
            _deploy(minutes_ago=3, deploy_id="dep-new"),
            _deploy(minutes_ago=45, deploy_id="dep-mid"),
        ]
        self.assertEqual(self._last(rows).get("id"), "dep-new")

    def test_a_failed_build_never_restarted_the_service_so_it_does_not_count(self) -> None:
        rows = [
            _deploy(status="build_failed", minutes_ago=1, deploy_id="dep-failed"),
            _deploy(status="live", minutes_ago=60, deploy_id="dep-live"),
        ]
        self.assertEqual(self._last(rows).get("id"), "dep-live")

    def test_a_cancelled_deploy_DOES_count(self) -> None:
        # This module's header measures it: cancelling after build_ended does not
        # avoid a restart, it causes one -- a second MALLOC_ARENA_INIT 29 s later
        # with the child pid namespace reset. Over-counting costs a wait;
        # under-counting costs the board.
        rows = [_deploy(status="canceled", minutes_ago=2, deploy_id="dep-cancel")]
        self.assertEqual(self._last(rows).get("id"), "dep-cancel")

    def test_an_unrecognised_status_counts_rather_than_passes(self) -> None:
        # Rule 1 of this file: unknown must not land on the permissive branch.
        rows = [_deploy(status="some_new_render_status", minutes_ago=2, deploy_id="dep-weird")]
        self.assertEqual(self._last(rows).get("id"), "dep-weird")

    def test_an_in_flight_deploy_is_dated_from_its_start(self) -> None:
        # It has no finishedAt, and it is the "one build cancelled another" case.
        rows = [{"deploy": {"id": "dep-flight", "status": "update_in_progress",
                            "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}}]
        found = self._last(rows)
        self.assertEqual(found.get("id"), "dep-flight")
        self.assertTrue(deploy_preflight._deploy_restart_moment(found))

    def test_nothing_restarting_returns_empty_rather_than_raising(self) -> None:
        self.assertEqual(self._last([_deploy(status="build_failed")]), {})
        self.assertEqual(self._last([]), {})


class AgeSecondsTests(unittest.TestCase):
    def test_a_negative_age_is_NOT_clamped(self) -> None:
        # The sample-age caller treats a negative as "a receipt nobody should
        # trust the rest of". Clamping here would hide that.
        now = datetime.now(timezone.utc)
        ahead = (now + timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertLess(deploy_preflight._age_seconds(ahead, now), 0)

    def test_unreadable_is_None(self) -> None:
        now = datetime.now(timezone.utc)
        for bad in ("", None, "not a date"):
            with self.subTest(bad=bad):
                self.assertIsNone(deploy_preflight._age_seconds(bad, now))


class ExitCodeContractTests(unittest.TestCase):
    def test_too_soon_has_its_own_code_distinct_from_hold(self) -> None:
        # HOLD means "something is running, wait for a lull". TOO_SOON means
        # "nothing is running BECAUSE you just restarted it". Same refusal,
        # different remedy, so they cannot share a code.
        self.assertEqual(deploy_preflight.EXIT_TOO_SOON, 5)
        for other in (deploy_preflight.EXIT_CLEAR, deploy_preflight.EXIT_HOLD,
                      deploy_preflight.EXIT_UNKNOWN, deploy_preflight.EXIT_CLAIMED,
                      deploy_preflight.EXIT_OFF_MAIN):
            self.assertNotEqual(deploy_preflight.EXIT_TOO_SOON, other)

    def test_too_soon_is_non_zero_so_every_existing_caller_still_blocks(self) -> None:
        # Anything already treating non-zero as "do not deploy" keeps working
        # without being taught the new code.
        self.assertNotEqual(deploy_preflight.EXIT_TOO_SOON, 0)


class TooSoonVerdictTests(unittest.TestCase):
    """REACHABILITY FIRST. The constants and helpers above can all be correct
    while the branch that uses them never fires -- the `off != on` property
    `model_engine_standard.md` requires of anything behind a gate.

    Drives `main()` end to end against a mocked Render API and asserts on the
    EXIT CODE and the RECEIPT, which are the two things the guard actually
    reads.
    """

    def _run(self, argv, *, last_deploy_minutes_ago, jobs=(), env=None):
        receipts = {}

        def fake_write_receipt(args, report, verdict, reason, live_commit):
            receipts["verdict"] = verdict
            receipts["reason"] = reason
            receipts["report"] = report

        # A CLEAR-shaped world in every respect except the deploy spacing, so a
        # TOO_SOON can only come from the thing under test.
        sample_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        processes = [WORKER_SHELL, WORKER_MAIN, *jobs]
        with mock.patch.object(deploy_preflight, "_api_key", return_value="k"), \
             mock.patch.object(deploy_preflight, "live_deploy", return_value={"commit": {"id": "f" * 40}}), \
             mock.patch.object(deploy_preflight, "fleet_live_commits", return_value={}), \
             mock.patch.object(deploy_preflight, "newest_log",
                               return_value=(sample_now, "ALL_PROCESS_MEMORY " + __import__("json").dumps(
                                   {"processes": processes, "process_count": len(processes)}))), \
             mock.patch.object(deploy_preflight, "last_restarting_deploy",
                               return_value=(_deploy(minutes_ago=last_deploy_minutes_ago,
                                                     deploy_id="dep-recent")["deploy"]
                                             if last_deploy_minutes_ago is not None else {})), \
             mock.patch.object(deploy_preflight, "_write_receipt", side_effect=fake_write_receipt), \
             mock.patch.object(deploy_preflight.sys, "argv", ["deploy_preflight.py", *argv]), \
             mock.patch.dict(os.environ, env or {}):
            code = deploy_preflight.main()
        return code, receipts

    def test_a_deploy_three_minutes_after_the_last_one_is_refused(self) -> None:
        code, receipt = self._run(["--service", "refresh-worker"], last_deploy_minutes_ago=3)
        self.assertEqual(code, deploy_preflight.EXIT_TOO_SOON)
        self.assertEqual(receipt["verdict"], "TOO_SOON")
        # The remedy must be a WAIT with a number in it, not "re-run preflight".
        self.assertIn("Wait", receipt["reason"])
        self.assertIn("--allow-rapid", receipt["reason"])

    def test_the_same_world_thirty_minutes_later_is_CLEAR(self) -> None:
        # off != on. Without this, every assertion above would also pass on a
        # preflight that refused unconditionally.
        code, receipt = self._run(["--service", "refresh-worker"], last_deploy_minutes_ago=30)
        self.assertEqual(code, deploy_preflight.EXIT_CLEAR)
        self.assertEqual(receipt["verdict"], "CLEAR")

    def test_allow_rapid_lets_a_revert_through(self) -> None:
        # A rate limit with no override turns an outage into a longer one.
        code, receipt = self._run(["--service", "refresh-worker", "--allow-rapid"],
                                  last_deploy_minutes_ago=1)
        self.assertEqual(code, deploy_preflight.EXIT_CLEAR)
        self.assertTrue(receipt["report"]["allow_rapid"])

    def test_an_unrate_limited_service_is_unaffected(self) -> None:
        # web is 0 by judgement (it loses no cycle), so a rapid web deploy must
        # still reach the process checks rather than being refused here.
        code, receipt = self._run(["--service", "live-odds-worker"], last_deploy_minutes_ago=1)
        self.assertEqual(code, deploy_preflight.EXIT_CLEAR)
        self.assertEqual(receipt["report"]["min_deploy_interval_seconds"], 0)

    def test_an_unreadable_deploy_history_does_NOT_refuse(self) -> None:
        # The one deliberately permissive unknown in this file. Refusing on a
        # Render API blip would block every deploy INCLUDING a revert, which is
        # worse than the problem. The unknown is recorded, not swallowed.
        code, receipt = self._run(["--service", "refresh-worker"], last_deploy_minutes_ago=None)
        self.assertEqual(code, deploy_preflight.EXIT_CLEAR)
        self.assertIsNone(receipt["report"]["last_deploy"])

    def test_a_job_in_flight_still_HOLDs_when_spacing_is_fine(self) -> None:
        # The pre-existing property must survive the new branch.
        code, receipt = self._run(["--service", "refresh-worker"],
                                  last_deploy_minutes_ago=60, jobs=[NFL_CHILD])
        self.assertEqual(code, deploy_preflight.EXIT_HOLD)

    def test_spacing_is_decided_BEFORE_the_stale_sample_check(self) -> None:
        # THE ORDERING, and it is the point rather than an accident. Right after
        # a deploy the worker has usually not printed ALL_PROCESS_MEMORY yet, so
        # the sample IS stale -- and UNKNOWN would mask TOO_SOON behind a reason
        # that tells the operator to wait for a log line when what they need is
        # to wait 22 more minutes. Both refuse; only one is true.
        with mock.patch.object(deploy_preflight, "_api_key", return_value="k"), \
             mock.patch.object(deploy_preflight, "live_deploy", return_value={"commit": {"id": "f" * 40}}), \
             mock.patch.object(deploy_preflight, "fleet_live_commits", return_value={}), \
             mock.patch.object(deploy_preflight, "newest_log", return_value=None), \
             mock.patch.object(deploy_preflight, "last_restarting_deploy",
                               return_value=_deploy(minutes_ago=2)["deploy"]), \
             mock.patch.object(deploy_preflight, "_write_receipt"), \
             mock.patch.object(deploy_preflight.sys, "argv",
                               ["deploy_preflight.py", "--service", "refresh-worker"]):
            code = deploy_preflight.main()
        self.assertEqual(code, deploy_preflight.EXIT_TOO_SOON,
                         "a stale sample must not mask the real blocker")

    def test_the_receipt_carries_the_numbers_for_after_the_fact_audit(self) -> None:
        _code, receipt = self._run(["--service", "refresh-worker"], last_deploy_minutes_ago=3)
        report = receipt["report"]
        self.assertEqual(report["min_deploy_interval_seconds"], 1500)
        self.assertAlmostEqual(report["last_deploy"]["age_seconds"], 180, delta=30)
        self.assertEqual(report["last_deploy"]["trigger"], "api")


class WouldItHavePreventedTheIncidentTests(unittest.TestCase):
    """Replay the REAL 2026-08-25 refresh-worker deploy timeline through the check.

    Not a synthetic scenario: these are the fifteen deploys read from
    `/v1/services/srv-d91dpertqb8s73co8ls0/deploys` while diagnosing `#563`,
    with their real statuses and triggers. Every one was `trigger=api`, on main,
    and correctly claimed -- so `CLAIMED` and `OFF_MAIN` both passed on all
    fifteen, which is precisely why a third property was needed.

    A guard justified by an incident should be able to say what it would have
    done during that incident. This is that statement, and it is a number rather
    than a claim.
    """

    # (finishedAt, status) in chronological order.
    REAL_TIMELINE = [
        ("2026-08-25T19:26:55Z", "deactivated"),
        ("2026-08-25T20:20:57Z", "deactivated"),
        ("2026-08-25T20:37:48Z", "deactivated"),
        ("2026-08-25T21:18:45Z", "deactivated"),
        ("2026-08-25T21:27:42Z", "deactivated"),
        ("2026-08-25T21:50:14Z", "deactivated"),
        ("2026-08-25T22:08:59Z", "canceled"),
        ("2026-08-25T22:11:36Z", "deactivated"),
        ("2026-08-25T22:20:28Z", "deactivated"),
        ("2026-08-25T22:32:25Z", "deactivated"),
        ("2026-08-25T22:36:13Z", "deactivated"),
        ("2026-08-25T23:48:19Z", "deactivated"),
        ("2026-08-25T23:56:56Z", "deactivated"),
        ("2026-08-26T00:45:13Z", "live"),
        ("2026-08-26T01:13:38Z", "update_in_progress"),
    ]

    def _gaps(self):
        stamps = [datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                  for t, _status in self.REAL_TIMELINE]
        return [(stamps[i + 1] - stamps[i]).total_seconds() for i in range(len(stamps) - 1)]

    def test_it_would_have_refused_most_of_that_evenings_deploys(self) -> None:
        limit = deploy_preflight.DEFAULT_MIN_DEPLOY_INTERVAL_SECONDS["refresh-worker"]
        gaps = self._gaps()
        refused = [g for g in gaps if g < limit]
        # 9 of the 14 intervals were inside the 25-minute spacing.
        #
        # A FLOOR, NOT AN EXACT COUNT, and the direction matters: these are
        # finish-to-finish gaps, while the preflight measures last-restart-to-NOW
        # and "now" is a few minutes BEFORE the next deploy finishes. So the real
        # gaps at preflight time were shorter than these and the true refusal
        # count is at least this.
        self.assertGreaterEqual(len(refused), 9)
        self.assertEqual(len(gaps), 14)

    def test_the_five_legitimate_gaps_would_still_have_gone_through(self) -> None:
        # The check has to let normal work happen or it will be switched off.
        # The five gaps over 25 minutes (54, 41, 72, 48 and 28 min) are deploys
        # nobody should have been stopped from making.
        limit = deploy_preflight.DEFAULT_MIN_DEPLOY_INTERVAL_SECONDS["refresh-worker"]
        allowed = [g for g in self._gaps() if g >= limit]
        self.assertEqual(len(allowed), 5)

    def test_the_worst_burst_is_caught(self) -> None:
        # 22:08:59 -> 22:11:36 is 157 seconds. Five deploys landed inside the
        # 54-minute publish gap that followed, and the board published nothing
        # for the whole of it.
        self.assertIn(157.0, self._gaps())

    def test_a_cancelled_deploy_in_the_real_timeline_still_starts_the_clock(self) -> None:
        # 22:08:59 was `canceled` and the deploy 157 s later must still be
        # refused. If cancels did not count, the tightest burst of the evening
        # would have passed.
        statuses = {s for _t, s in self.REAL_TIMELINE}
        self.assertIn("canceled", statuses)
        self.assertNotIn("canceled", deploy_preflight.NON_RESTARTING_DEPLOY_STATUSES)
