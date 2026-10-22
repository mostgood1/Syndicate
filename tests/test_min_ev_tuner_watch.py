"""The min_ev tuner's fleet readout job and watchdog alert (lane min-ev-tuner-readout-fleet).

Reachability first: the job is in the supervisor's SCHEDULED_JOBS and run_due_jobs launches it; the watchdog's
main() raises the alert from a fixture refresh-worker.log that lacks today's pass line.
"""

from __future__ import annotations

import datetime as dt
import json
import types
from pathlib import Path

from scripts import local_production as lp
from scripts import local_watchdog as wd
from scripts import min_ev_tuner_daily_readout as dr
from scripts import min_ev_tuner_watch as tw

REPO = Path(__file__).resolve().parents[1]
DAY = "2026-10-22"
AT_1305 = dt.datetime(2026, 10, 22, 13, 5, tzinfo=dt.timezone.utc)
AT_1155 = dt.datetime(2026, 10, 22, 11, 55, tzinfo=dt.timezone.utc)
PASS = "[min_ev_tuner] MIN_EV_TUNER mode={mode} date={date} cells=68 actions={{'hold': 68}} skipped={{}} base=2.0 moves=0\n"
FAILED = "[min_ev_tuner] MIN_EV_TUNER_FAILED RuntimeError: boom\n"
HOOK_FAILED = "[intelligence_state] MIN_EV_TUNER_HOOK_FAILED error=ImportError\n"


def _job():
    return next(j for j in lp.SCHEDULED_JOBS if j.name == "min-ev-tuner-readout")


def _keys(findings):
    return {key: sev for key, sev, _ in findings}


def _write_log(home: Path, text: str) -> Path:
    path = home / "logs" / tw.LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # byte offsets: no CRLF translation
    return path


def _check(home: Path, now, state=None):
    return tw.run(home, home / "logs", home / "data", state or {}, now)


# ---- the supervisor job -----------------------------------------------------------------------------------------


def test_the_readout_job_is_registered_daily_at_1315z_and_its_script_exists():
    job = _job()
    assert (job.hour, job.minute, job.weekday, job.every_minutes) == (13, 15, None, None)
    assert job.argv == ("scripts/min_ev_tuner_daily_readout.py",)
    assert (REPO / job.argv[0]).is_file()
    assert not lp.job_is_due(job, dt.datetime(2026, 10, 22, 13, 14, tzinfo=dt.timezone.utc), "2026-10-21")
    assert lp.job_is_due(job, dt.datetime(2026, 10, 22, 13, 15, tzinfo=dt.timezone.utc), "2026-10-21")
    assert not lp.job_is_due(job, dt.datetime(2026, 10, 22, 20, 0, tzinfo=dt.timezone.utc), DAY)


def test_run_due_jobs_launches_the_readout_script(tmp_path, monkeypatch):
    launched = []

    class FakePopen:
        pid = 4242

        def __init__(self, argv, **kwargs):
            launched.append(argv)

        def poll(self):
            return None

    monkeypatch.setattr(lp.subprocess, "Popen", FakePopen)
    settings = lp.Settings(home=tmp_path)
    settings.run_dir.mkdir(parents=True)
    settings.logs_dir.mkdir(parents=True)
    # Every other job already ran today, so only the readout is due at 13:16Z.
    state = {j.name: {"last_run_date": DAY, "started_at": f"{DAY}T13:16:00+00:00", "last_rc": 0}
             for j in lp.SCHEDULED_JOBS if j.name != "min-ev-tuner-readout"}
    (settings.run_dir / "scheduled_jobs.json").write_text(json.dumps(state), encoding="utf-8")
    lp.run_due_jobs(settings, {}, {}, now=dt.datetime(2026, 10, 22, 13, 16, tzinfo=dt.timezone.utc))
    assert [argv[1:] for argv in launched] == [["scripts/min_ev_tuner_daily_readout.py"]]
    saved = json.loads((settings.run_dir / "scheduled_jobs.json").read_text(encoding="utf-8"))
    assert saved["min-ev-tuner-readout"]["last_run_date"] == DAY


def test_the_job_writes_a_dated_artifact_rc0_when_the_state_is_todays(tmp_path, monkeypatch):
    from syndicate.features.shared import min_ev_tuner as T

    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    state = {"mode": "shadow", "last_run_date": today, "last_run_at": f"{today}T12:04:42Z", "cells": {},
             "actions": {"hold": 68}, "audit": [{"at": f"{today}T12:04:42Z", "cell": "c"}, {"at": "2026-01-01T12:00:00Z"}]}
    monkeypatch.setattr(T, "load_state", lambda: state)
    assert dr.main(["--reports-root", str(tmp_path)]) == 0
    payload = json.loads((tmp_path / "intelligence" / "min_ev_tuner_readout" / f"{today}.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "shadow" and payload["state_is_today"] is True and payload["readout_rc"] == 0
    assert len(payload["moves_today"]) == 1 and "mode=shadow" in payload["text"]


def test_the_job_still_writes_but_exits_2_on_a_missing_state(tmp_path, monkeypatch):
    from syndicate.features.shared import min_ev_tuner as T

    monkeypatch.setattr(T, "load_state", lambda: {})
    assert dr.main(["--reports-root", str(tmp_path)]) == 2
    (written,) = (tmp_path / "intelligence" / "min_ev_tuner_readout").glob("*.json")
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["state_present"] is False and "NO STATE" in payload["text"]


# ---- the watchdog checks ----------------------------------------------------------------------------------------


def test_missing_line_alerts_after_1300z_and_not_before(tmp_path):
    _write_log(tmp_path, "cycle\n" + PASS.format(mode="shadow", date="2026-10-21") + "cycle\n")
    assert _keys(_check(tmp_path, AT_1155)[0]) == {}
    assert _keys(_check(tmp_path, AT_1305)[0]) == {"exec:min_ev_tuner:missing": tw.WARN}


def test_a_missing_log_file_also_alerts(tmp_path):
    findings, _ = _check(tmp_path, AT_1305)
    assert _keys(findings) == {"exec:min_ev_tuner:missing": tw.WARN}


def test_todays_shadow_pass_is_healthy(tmp_path):
    _write_log(tmp_path, PASS.format(mode="shadow", date=DAY) + "[min_ev_tuner] MIN_EV_TUNER_MOVE at=x\n")
    findings, row = _check(tmp_path, AT_1305)
    assert findings == [] and row["pass_mode"] == "shadow"


def test_failure_lines_alert_and_a_later_pass_clears_them(tmp_path):
    log = _write_log(tmp_path, PASS.format(mode="shadow", date="2026-10-21"))
    _, row = _check(tmp_path, AT_1155)
    with log.open("a", encoding="utf-8", newline="") as handle:
        handle.write(FAILED + HOOK_FAILED + "[min_ev_tuner] MIN_EV_TUNER_SAVE_FAILED OSError: disk\n")
    findings, row = _check(tmp_path, AT_1155 + dt.timedelta(minutes=10), {"min_ev_tuner": row})
    assert _keys(findings) == {"exec:min_ev_tuner:failed": tw.WARN} and row["failures_today"] == 3
    with log.open("a", encoding="utf-8", newline="") as handle:
        handle.write(PASS.format(mode="shadow", date=DAY))
    findings, row = _check(tmp_path, AT_1305, {"min_ev_tuner": row})
    assert findings == []


def test_first_scan_does_not_blame_today_for_failures_before_the_last_pass(tmp_path):
    _write_log(tmp_path, FAILED + PASS.format(mode="shadow", date="2026-10-21") + "cycle\n")
    findings, row = _check(tmp_path, AT_1155)
    assert findings == [] and row["failures_today"] == 0
    _write_log(tmp_path, PASS.format(mode="shadow", date="2026-10-21") + FAILED)
    findings, _ = _check(tmp_path, AT_1155)  # no saved offset: a fresh first scan
    assert _keys(findings) == {"exec:min_ev_tuner:failed": tw.WARN}


def test_markers_inside_another_line_are_not_tuner_lines(tmp_path):
    """The fleet's ALL_PROCESS_MEMORY line embeds process cmdlines -- including a peer's grep for these markers."""
    embedded = ('2026-10-22T14:23:45.326Z ALL_PROCESS_MEMORY {"cmdline": ["grep", "MIN_EV_TUNER_FAILED", '
                f'"[min_ev_tuner] MIN_EV_TUNER mode=apply date={DAY}"]}}\n')
    _write_log(tmp_path, PASS.format(mode="shadow", date="2026-10-21") + embedded)
    findings, row = _check(tmp_path, AT_1305)
    assert _keys(findings) == {"exec:min_ev_tuner:missing": tw.WARN} and row["failures_today"] == 0


def test_the_fleets_stamped_lines_parse_and_a_stamp_dates_a_failure(tmp_path):
    stamped_pass = "2026-10-22T12:01:51.256Z " + PASS.format(mode="shadow", date=DAY)
    assert tw.parse_pass_line(stamped_pass) == {"mode": "shadow", "date": DAY}
    _write_log(tmp_path, "2026-10-21T12:00:01.000Z " + FAILED + "2026-10-22T12:00:01.000Z " + HOOK_FAILED)
    findings, row = _check(tmp_path, AT_1155)
    assert row["failures_today"] == 1 and "HOOK_FAILED" in row["failures"][0]


def test_reads_are_incremental_and_survive_copy_truncate_rotation(tmp_path):
    log = _write_log(tmp_path, "x" * 500 + "\n")
    _, row = _check(tmp_path, AT_1155)
    assert row["offset"] == 501
    # rotate_running_log: copy to .1, truncate; the pass line landed in the copy past our offset.
    (log.parent / f"{tw.LOG_NAME}.1").write_bytes(("x" * 500 + "\n" + PASS.format(mode="shadow", date=DAY)).encode())
    log.write_bytes(b"short\n")
    findings, row = _check(tmp_path, AT_1305, {"min_ev_tuner": row})
    assert findings == [] and row["pass_mode"] == "shadow" and row["offset"] == 6


def test_a_partial_last_line_is_not_consumed(tmp_path):
    log = _write_log(tmp_path, "[min_ev_tuner] MIN_EV_TUNER mode=shadow da")
    _, row = _check(tmp_path, AT_1305)
    assert row["offset"] == 0
    with log.open("a", encoding="utf-8", newline="") as handle:
        handle.write(f"te={DAY} cells=1\n")
    findings, _ = _check(tmp_path, AT_1305, {"min_ev_tuner": row})
    assert findings == []


def test_a_non_shadow_mode_without_a_recorded_decision_fails(tmp_path):
    _write_log(tmp_path, PASS.format(mode="apply", date=DAY))
    assert _keys(_check(tmp_path, AT_1305)[0]) == {"exec:min_ev_tuner:mode": tw.FAIL}
    (tmp_path / tw.DECISION_NAME).write_text(json.dumps({"mode": "apply", "decided_by": "user"}), encoding="utf-8")
    assert _check(tmp_path, AT_1305)[0] == []


def test_the_readout_artifact_mode_is_checked_too(tmp_path):
    _write_log(tmp_path, PASS.format(mode="shadow", date=DAY))
    readouts = tmp_path / "data" / "reports" / "intelligence" / "min_ev_tuner_readout"
    readouts.mkdir(parents=True)
    (readouts / "2026-10-21.json").write_text(json.dumps({"date": "2026-10-21", "mode": "apply"}), encoding="utf-8")
    assert _keys(_check(tmp_path, AT_1305)[0]) == {"exec:min_ev_tuner:mode": tw.FAIL}


def test_a_crash_in_the_check_is_a_warning_not_an_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(tw, "scan_log", lambda *a, **k: 1 / 0)
    assert _keys(_check(tmp_path, AT_1305)[0]) == {"exec:min_ev_tuner:watch_error": tw.WARN}


def test_watchdog_main_alerts_on_a_fixture_log_missing_todays_line(tmp_path, monkeypatch, capsys):
    """Reachability: local_watchdog.main() -> min_ev_tuner_watch, on disk, at 13:05Z."""

    class FixedDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return AT_1305

    monkeypatch.setattr(wd, "dt", types.SimpleNamespace(datetime=FixedDateTime, timezone=dt.timezone, timedelta=dt.timedelta))
    monkeypatch.setenv("SYNDICATE_WATCHDOG_EXECUTION", "0")
    _write_log(tmp_path, PASS.format(mode="shadow", date="2026-10-21"))
    wd.main(["--home", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out.strip())
    assert "exec:min_ev_tuner:missing" in {f["key"] for f in out["new"]}
    saved = json.loads((tmp_path / "run" / wd.STATE_NAME).read_text(encoding="utf-8"))
    assert saved["min_ev_tuner"]["last_pass_date"] == "2026-10-21"
    # Switched off, the same fixture raises nothing from this check (off != on).
    monkeypatch.setenv("SYNDICATE_WATCHDOG_MIN_EV_TUNER", "0")
    (tmp_path / "run" / wd.STATE_NAME).unlink()
    wd.main(["--home", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out.strip())
    assert not any(f["key"].startswith(tw.PREFIX) for f in out["findings"])
