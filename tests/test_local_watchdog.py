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

# ---- auto-recovery (lane fleet-watchdog-auto-recovery; 2026-10-04 08:39-13:53Z outage) -----------------------

T0 = dt.datetime(2026, 10, 4, 8, 40, tzinfo=dt.timezone.utc)
DOWN = [wd.Finding("supervisor", wd.FAIL, "no supervisor pidfile")]


def _at(minutes):
    return T0 + dt.timedelta(minutes=minutes)


def test_first_failing_check_waits_for_a_second_one():
    d, s = wd.recovery(DOWN, {}, T0, paused=False)
    assert d["recover"] is False and s["down_since"] == T0.isoformat()


def test_a_second_failing_check_starts_the_fleet():
    _, s = wd.recovery(DOWN, {}, T0, paused=False)
    d, s2 = wd.recovery(DOWN, s, _at(10), paused=False)
    assert d["recover"] is True and len(s2["recovery_attempts"]) == 1


def test_attempts_are_capped_per_hour_then_alert_only():
    state = {"down_since": T0.isoformat(), "recovery_attempts": []}
    took = 0
    for m in range(10, 60, 5):
        d, state = wd.recovery(DOWN, state, _at(m), paused=False)
        took += d["recover"]
    assert took == wd.RECOVER_MAX_PER_HOUR
    assert "alert only" in d["reason"]


def test_the_pause_file_blocks_recovery():
    d, _ = wd.recovery(DOWN, {"down_since": T0.isoformat()}, _at(30), paused=True)
    assert d["recover"] is False and "paused" in d["reason"]


def test_a_healthy_check_clears_down_since():
    d, s = wd.recovery([], {"down_since": T0.isoformat()}, _at(30), paused=False)
    assert d["recover"] is False and s["down_since"] is None


def test_a_role_failure_under_a_live_supervisor_is_not_recovered_here():
    role = [wd.Finding("healthz", wd.FAIL, "/healthz did not answer 200")]
    d, _ = wd.recovery(role, {"down_since": T0.isoformat()}, _at(30), paused=False)
    assert d["recover"] is False


def test_old_attempts_age_out_of_the_hourly_cap():
    state = {"down_since": T0.isoformat(), "recovery_attempts": [_at(0).isoformat()] * 3}
    d, _ = wd.recovery(DOWN, state, _at(61), paused=False)
    assert d["recover"] is True


# --- refused vs slow (lane web-restart-healthz, 2026-10-06) -----------------

def test_refused_is_DOWN_and_a_timeout_is_UP_BUT_SLOW():
    refused = wd.evaluate(_healthy(healthz="URLError [ConnectionRefusedError]: <urlopen error [Errno 111] Connection refused>"), NOW)
    slow = wd.evaluate(_healthy(healthz="TimeoutError: timed out"), NOW)
    assert _keys(refused) == {"healthz": wd.FAIL} and "DOWN" in refused[0].message
    assert _keys(slow) == {"healthz:slow": wd.FAIL} and "UP" in slow[0].message and "not down" in slow[0].message


def test_other_failures_keep_the_old_healthz_finding():
    assert _keys(wd.evaluate(_healthy(healthz=500), NOW)) == {"healthz": wd.FAIL}
    assert wd.healthz_kind("URLError [TimeoutError]: <urlopen error timed out>") == "slow"
    assert wd.healthz_kind(None) == "error"


def test_a_slow_web_does_not_trigger_fleet_recovery():
    findings = wd.evaluate(_healthy(healthz="TimeoutError: timed out"), NOW)
    decision, _ = wd.recovery(findings, {}, NOW, paused=False)
    assert decision["recover"] is False


def test_real_socket_readings_classify_correctly(monkeypatch):
    """The labels must come from what urllib ACTUALLY raises, not from strings we typed."""
    import socket

    with socket.socket() as probe:              # a port with nothing listening
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    assert wd.healthz_kind(wd._healthz(closed_port)) == "refused"

    monkeypatch.setattr(wd, "HEALTHZ_TIMEOUT_SECONDS", 1)
    with socket.socket() as listener:           # listening, never answers: a saturated web
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        assert wd.healthz_kind(wd._healthz(listener.getsockname()[1])) == "slow"
