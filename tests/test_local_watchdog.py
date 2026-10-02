"""scripts/local_watchdog.py -- what counts as a problem, and when it alerts."""

from __future__ import annotations

import datetime as dt

from scripts import local_watchdog as wd

NOW = dt.datetime(2026, 10, 2, 15, 0, tzinfo=dt.timezone.utc)   # a Friday, every daily job past due


def _healthy(**overrides):
    jobs = {job.name: {"last_run_date": "2026-10-02", "last_rc": 0} for job in wd.lp.SCHEDULED_JOBS}
    readings = {
        "pidfile_present": True,
        "supervisor_alive": True,
        "roles_alive": {"web": True, "refresh-worker": True, "live-odds-worker": True},
        "restarts": {"web": 0, "refresh-worker": 1, "live-odds-worker": 0},
        "healthz": 200,
        "log_ages": {"web": 5.0, "refresh-worker": 30.0, "live-odds-worker": 60.0},
        "jobs": jobs,
        "backup_age_seconds": 6 * 3600.0,
        "backup_dir": "/b",
        "disk_free": {"/data": 500 * 1024 ** 3},
    }
    readings.update(overrides)
    return readings


def _keys(findings):
    return {f.key: f.severity for f in findings}


def test_a_healthy_fleet_has_no_findings():
    assert wd.evaluate(_healthy(), NOW, previous_restarts={"refresh-worker": 1}) == []


def test_no_pidfile_is_one_fail_and_nothing_else():
    assert _keys(wd.evaluate({"pidfile_present": False}, NOW)) == {"supervisor": wd.FAIL}


def test_each_hard_failure_is_a_fail():
    r = _healthy(supervisor_alive=False, roles_alive={"web": True, "refresh-worker": False, "live-odds-worker": True},
                 healthz="URLError: refused")
    assert _keys(wd.evaluate(r, NOW)) == {"supervisor": wd.FAIL, "role:refresh-worker": wd.FAIL, "healthz": wd.FAIL}


def test_a_crash_loop_is_measured_against_the_previous_check():
    r = _healthy(restarts={"web": 0, "refresh-worker": 4, "live-odds-worker": 0})
    assert "crashloop:refresh-worker" in _keys(wd.evaluate(r, NOW, previous_restarts={"refresh-worker": 1}))
    # The first check has no baseline, so a historical count is not a burst.
    assert "crashloop:refresh-worker" not in _keys(wd.evaluate(r, NOW, previous_restarts={}))


def test_a_hung_role_is_caught_by_its_silent_log_but_a_dead_one_is_not_double_counted():
    r = _healthy(log_ages={"web": 5.0, "refresh-worker": 20 * 60.0, "live-odds-worker": None})
    keys = _keys(wd.evaluate(r, NOW))
    assert keys["heartbeat:refresh-worker"] == wd.FAIL and keys["heartbeat:live-odds-worker"] == wd.FAIL
    r = _healthy(roles_alive={"web": True, "refresh-worker": False, "live-odds-worker": True},
                 log_ages={"web": 5.0, "refresh-worker": 9999.0, "live-odds-worker": 5.0})
    assert "heartbeat:refresh-worker" not in _keys(wd.evaluate(r, NOW))


def test_jobs_missed_failed_and_running_too_long():
    jobs = {job.name: {"last_run_date": "2026-10-02", "last_rc": 0} for job in wd.lp.SCHEDULED_JOBS}
    jobs["sim-input-reports"] = {"last_run_date": "2026-10-01", "last_rc": 0}                 # missed today
    jobs["ci-suite"] = {"last_run_date": "2026-10-02", "last_rc": 1}                          # failed
    jobs["data-backup"] = {"last_run_date": "2026-10-02", "started_at": "2026-10-02T09:15:00+00:00"}  # 5h45m running
    keys = _keys(wd.evaluate(_healthy(jobs=jobs), NOW))
    assert keys == {"job:sim-input-reports": wd.WARN, "job:ci-suite": wd.WARN, "job:data-backup": wd.WARN}


def test_a_job_not_yet_past_its_grace_is_not_missed():
    early = dt.datetime(2026, 10, 2, 8, 30, tzinfo=dt.timezone.utc)   # ci-suite due 08:00, grace 2 h
    jobs = {job.name: {"last_run_date": "2026-10-01", "last_rc": 0} for job in wd.lp.SCHEDULED_JOBS}
    assert "job:ci-suite" not in _keys(wd.evaluate(_healthy(jobs=jobs), early))


def test_backup_and_disk_warnings():
    keys = _keys(wd.evaluate(_healthy(backup_age_seconds=40 * 3600.0, disk_free={"/data": 2 * 1024 ** 3}), NOW))
    assert keys == {"backup": wd.WARN, "disk:/data": wd.WARN}
    assert _keys(wd.evaluate(_healthy(backup_age_seconds=None), NOW)) == {"backup": wd.WARN}


def test_alerts_on_new_then_quiet_then_repeats_then_recovers():
    fail = [wd.Finding("healthz", wd.FAIL, "down")]
    result, state = wd.decide(fail, {}, NOW)
    assert result["alert"] and result["status"] == "down" and len(result["new"]) == 1

    result, state = wd.decide(fail, state, NOW + dt.timedelta(minutes=5))
    assert not result["alert"], "a persisting problem must not alert every 5 minutes"

    result, state = wd.decide(fail, state, NOW + dt.timedelta(hours=6, minutes=1))
    assert result["alert"] and len(result["repeat"]) == 1

    result, state = wd.decide([], state, NOW + dt.timedelta(hours=7))
    assert result["alert"] and result["status"] == "ok" and result["title"] == "Syndicate fleet recovered"
    assert state["active"] == {}

    result, _ = wd.decide([], state, NOW + dt.timedelta(hours=8))
    assert not result["alert"], "a healthy fleet stays quiet"


def test_warnings_repeat_daily_not_six_hourly():
    warn = [wd.Finding("job:ci-suite", wd.WARN, "rc=1")]
    _, state = wd.decide(warn, {}, NOW)
    result, state = wd.decide(warn, state, NOW + dt.timedelta(hours=7))
    assert not result["alert"]
    result, _ = wd.decide(warn, state, NOW + dt.timedelta(hours=24, minutes=1))
    assert result["alert"]


def test_main_runs_against_an_empty_home_and_reports_down(tmp_path, capsys):
    import json

    rc = wd.main(["--home", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out.strip())
    assert rc == 1 and out["status"] == "down" and out["alert"] is True
    assert (tmp_path / "run" / wd.STATE_NAME).is_file()
    assert "no supervisor pidfile" in (tmp_path / "logs" / wd.LOG_NAME).read_text(encoding="utf-8")
