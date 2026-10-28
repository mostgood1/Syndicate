"""scripts/check_scheduled_task_registry.py -- the out-of-app alert for a lost scheduled-task registry.

Hermetic: temp files for the registry and the watchdog's state.json, a fixed CDT offset, injected
power events and app state. Nothing reads the real event log, process list or registry.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from scripts import check_scheduled_task_registry as chk

UTC = dt.timezone.utc
CDT = dt.timezone(dt.timedelta(hours=-5))
KP, PT, KG = ("Microsoft-Windows-Kernel-Power", "Microsoft-Windows-Power-Troubleshooter",
              "Microsoft-Windows-Kernel-General")
APP_UP = chk.AppState(running=True, started=dt.datetime(2026, 10, 26, 12, 0, tzinfo=UTC))


def z(text: str) -> dt.datetime:
    return chk.parse_utc(text)


def _registry(tmp_path, tasks=None, name="scheduled-tasks.json"):
    if tasks is None:
        tasks = [{"id": chk.WATCHDOG_ID, "enabled": True, "cronExpression": chk.DEFAULT_CRON},
                 {"id": "some-reading", "enabled": True, "fireAt": "2026-10-29T14:00:00Z"}]
    path = tmp_path / name
    path.write_text(json.dumps({"scheduledTasks": tasks, "recordedSkips": {}}), encoding="utf-8")
    return path


def _state(tmp_path, last_run: str):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"reported": {}, "last_run_utc": last_run}), encoding="utf-8")
    return path


def _eval(tmp_path, *, now, last_run, power_events=None, app=APP_UP, registry=None, **kw):
    reg = registry if registry is not None else [_registry(tmp_path)]
    return chk.evaluate(now=z(now), state_path=_state(tmp_path, last_run), registry_paths=reg,
                        power_events=power_events or [], app=app, tz=CDT, **kw)


# --- the heartbeat: fresh, stale, and the 12 h overnight gap ---------------------------------------

def test_run_after_the_due_time_is_ok(tmp_path):
    # 11:00 CDT; the 09:15 CDT run happened at 09:27.
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-28T14:27:40Z")
    assert v.status == "OK" and v.exit_code == 0 and v.problems == []
    assert v.facts["judged_due_utc"] == "2026-10-28T14:15:00+00:00"


def test_missed_due_time_with_the_machine_awake_alerts(tmp_path):
    # The 10-28 shape: last run 21:27 CDT on 10-27, registry wiped overnight, 09:15 CDT never ran.
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-28T02:27:40Z")
    assert v.status == "ALERT" and v.exit_code == 1
    assert "has not completed a run since 10-27 21:27 CT" in v.problems[0]
    assert "10-28 09:15 CT run is 1.8 h overdue" in v.problems[0]


def test_overnight_gap_is_not_stale(tmp_path):
    # 08:00 CDT: 10.5 h since the 21:15 run, but no due time has passed since. A flat ~5 h rule alarms here.
    v = _eval(tmp_path, now="2026-10-28T13:00:00Z", last_run="2026-10-28T02:27:40Z")
    assert v.status == "OK"
    assert v.facts["judged_due_utc"] == "2026-10-28T02:15:00+00:00"


def test_due_time_inside_the_grace_window_is_not_judged_yet(tmp_path):
    # 10:00 CDT: the 09:15 run may still be in flight (dispatch jitter + run time).
    v = _eval(tmp_path, now="2026-10-28T15:00:00Z", last_run="2026-10-28T02:27:40Z")
    assert v.status == "OK"
    assert v.facts["judged_due_utc"] == "2026-10-28T02:15:00+00:00"


# --- Modern Standby and app restarts must not false-alarm --------------------------------------------

STANDBY_OVERNIGHT = [(z("2026-10-28T01:00:00Z"), KP, 506), (z("2026-10-28T15:30:00Z"), KP, 507),
                     (z("2026-10-28T15:30:02Z"), PT, 1)]


def test_standby_across_the_due_times_is_not_judged(tmp_path):
    # Asleep 20:00 CDT -> 10:30 CDT, so 21:15 and 09:15 never had a chance; 17:15 on 10-27 did, and ran.
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-27T22:27:00Z",
              power_events=STANDBY_OVERNIGHT)
    assert v.status == "OK", v.problems
    assert v.facts["judged_due_utc"] == "2026-10-27T22:15:00+00:00"
    assert v.facts["due_times_skipped"] == 2


def test_the_standby_guard_is_reachable(tmp_path):
    # Same inputs without the power history: the guard is what made the previous test pass.
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-27T22:27:00Z", power_events=[])
    assert v.status == "ALERT"


def test_unreadable_power_history_does_not_exclude_standby(tmp_path):
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-27T22:27:00Z",
              power_events=None, power_error="RuntimeError: wevtutil exit 5")
    assert v.status == "ALERT"
    assert any("standby NOT excluded" in n for n in v.notes)


def test_first_minutes_after_wake_count_as_asleep(tmp_path):
    # Woke at 09:10 CDT, five minutes before the 09:15 due time: the app may not have caught up.
    events = [(z("2026-10-28T03:00:00Z"), KP, 506), (z("2026-10-28T14:10:00Z"), KP, 507)]
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-28T02:27:40Z", power_events=events)
    assert v.status == "OK", v.problems
    assert v.facts["judged_due_utc"] == "2026-10-28T02:15:00+00:00"


def test_app_started_after_the_due_time_is_unjudged(tmp_path):
    # The live reading at 08:03 CDT on 10-28: the update restarted the app at 01:44 CDT.
    restarted = chk.AppState(running=True, started=z("2026-10-28T06:44:45Z"))
    v = _eval(tmp_path, now="2026-10-28T13:03:00Z", last_run="2026-10-28T02:27:40Z", app=restarted)
    assert v.status == "UNJUDGED" and v.exit_code == 0
    # ...and once 09:15 CDT has passed with the app up, it is judged.
    v = _eval(tmp_path, now="2026-10-28T15:50:00Z", last_run="2026-10-28T02:27:40Z", app=restarted)
    assert v.status == "ALERT"


def test_app_not_running_alerts(tmp_path):
    v = _eval(tmp_path, now="2026-10-28T13:00:00Z", last_run="2026-10-28T02:27:40Z",
              app=chk.AppState(running=False, started=None))
    assert v.status == "ALERT"
    assert "NOT RUNNING" in v.problems[0]


# --- the registry file -------------------------------------------------------------------------------

def test_registry_without_the_watchdog_alerts_even_with_a_fresh_heartbeat(tmp_path):
    reg = _registry(tmp_path, tasks=[])
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-28T14:27:40Z", registry=[reg])
    assert v.status == "ALERT"
    assert v.problems == [f"REGISTRY LOST: {chk.WATCHDOG_ID} is not in the app's task registry "
                          "(0 tasks, 0 enabled)"]


def test_disabled_watchdog_alerts(tmp_path):
    reg = _registry(tmp_path, tasks=[{"id": chk.WATCHDOG_ID, "enabled": False}])
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-28T14:27:40Z", registry=[reg])
    assert v.status == "ALERT" and "DISABLED" in v.problems[0]


@pytest.mark.parametrize("content", ["{not json", json.dumps({"tasks": []}), json.dumps([1, 2])])
def test_unparseable_or_reshaped_registry_alerts(tmp_path, content):
    reg = tmp_path / "scheduled-tasks.json"
    reg.write_text(content, encoding="utf-8")
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-28T14:27:40Z", registry=[reg])
    assert v.status == "ALERT"


def test_missing_registry_file_alerts(tmp_path):
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-28T14:27:40Z",
              registry=[tmp_path / "nope.json"])
    assert v.status == "ALERT" and "not found" in v.problems[0]


def test_the_newest_registry_file_wins(tmp_path):
    import os
    old = _registry(tmp_path, name="old.json")
    new = _registry(tmp_path, tasks=[], name="new.json")
    os.utime(old, (1_000_000, 1_000_000))
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-28T14:27:40Z", registry=[old, new])
    assert v.status == "ALERT" and v.facts["registry_candidates"] == 2


def test_cron_comes_from_the_registry_entry(tmp_path):
    reg = _registry(tmp_path, tasks=[{"id": chk.WATCHDOG_ID, "enabled": True, "cronExpression": "0 12 * * *"}])
    v = _eval(tmp_path, now="2026-10-28T19:00:00Z", last_run="2026-10-28T17:05:00Z", registry=[reg])
    assert v.status == "OK" and v.facts["cron"] == "0 12 * * *"
    assert v.facts["judged_due_utc"] == "2026-10-28T17:00:00+00:00"


def test_unsupported_cron_falls_back_to_the_default(tmp_path):
    reg = _registry(tmp_path, tasks=[{"id": chk.WATCHDOG_ID, "enabled": True, "cronExpression": "*/5 * * * 1-5"}])
    v = _eval(tmp_path, now="2026-10-28T16:00:00Z", last_run="2026-10-28T14:27:40Z", registry=[reg])
    assert v.status == "OK" and v.facts["cron"] == chk.DEFAULT_CRON


def test_missing_state_file_alerts(tmp_path):
    v = chk.evaluate(now=z("2026-10-28T16:00:00Z"), state_path=tmp_path / "absent.json",
                     registry_paths=[_registry(tmp_path)], power_events=[], app=APP_UP, tz=CDT)
    assert v.status == "ALERT" and "state.json is unreadable" in v.problems[0]


# --- the pieces ---------------------------------------------------------------------------------------

def test_sleep_intervals():
    since, now = z("2026-10-27T00:00:00Z"), z("2026-10-28T00:00:00Z")
    events = [
        (z("2026-10-27T01:00:00Z"), KP, 507),   # wake whose sleep began before the window
        (z("2026-10-27T02:00:00Z"), KP, 506), (z("2026-10-27T03:00:00Z"), KP, 507),
        (z("2026-10-27T03:00:01Z"), PT, 1),     # duplicate wake: ignored
        (z("2026-10-27T05:00:00Z"), "Microsoft-Windows-FilterManager", 1),  # same id, other provider
        (z("2026-10-27T08:00:00Z"), KG, 12),    # boot with no shutdown before it (crash)
        (z("2026-10-27T20:00:00Z"), KP, 506),   # still asleep at `now`
    ]
    assert chk.sleep_intervals(events, since, now) == [
        (since, z("2026-10-27T01:00:00Z")),
        (z("2026-10-27T02:00:00Z"), z("2026-10-27T03:00:00Z")),
        (z("2026-10-27T03:00:01Z"), z("2026-10-27T08:00:00Z")),
        (z("2026-10-27T20:00:00Z"), now),
    ]


def test_parse_event_xml():
    ns = "xmlns='http://schemas.microsoft.com/win/2004/08/events/event'"
    text = "".join(
        f"<Event {ns}><System><Provider Name='{p}' Guid='{{x}}'/><EventID>{i}</EventID>"
        f"<TimeCreated SystemTime='{t}'/></System><EventData/></Event>"
        for p, i, t in [(KP, 506, "2026-10-22T16:18:40.1234567Z"), (KG, 12, "2026-10-14T06:33:54.6664443Z")])
    assert chk.parse_event_xml(text) == [(z("2026-10-22T16:18:40.123456Z"), KP, 506),
                                          (z("2026-10-14T06:33:54.666444Z"), KG, 12)]
    assert chk.parse_event_xml("\r\n") == []


def test_due_times_follow_the_local_clock_across_dst():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        chicago = zoneinfo.ZoneInfo("America/Chicago")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("no tz database")
    got = chk.due_times((15, [9]), z("2026-10-31T00:00:00Z"), z("2026-11-02T00:00:00Z"), chicago)
    assert got == [z("2026-10-31T14:15:00Z"), z("2026-11-01T15:15:00Z")]


def test_desktop_app_state_ignores_the_cli():
    procs = [
        {"path": r"C:\Users\u\AppData\Local\Claude-Data\claude_x\claude-code\2.1.309\abc\claude.exe",
         "start": "2026-10-20T00:00:00Z"},
        {"path": r"C:\Program Files\WindowsApps\Claude_4.29.0.0_arm64__x\app\claude.exe",
         "start": "2026-10-28T06:44:45.3962840Z"},
        {"path": r"C:\Program Files\WindowsApps\Claude_4.29.0.0_arm64__x\app\claude.exe",
         "start": "2026-10-28T06:45:10Z"},
    ]
    assert chk.desktop_app_state(procs) == chk.AppState(True, z("2026-10-28T06:44:45.396284Z"))
    assert chk.desktop_app_state(procs[:1]) == chk.AppState(False, None)


# --- main(): exit code, one notification, the log line ------------------------------------------------

def _main(tmp_path, last_run, *extra):
    sent, log = [], tmp_path / "check.log"
    argv = ["--state", str(_state(tmp_path, last_run)), "--registry", str(_registry(tmp_path)),
            "--log", str(log), *extra]
    code = chk.main(argv, now=z("2026-10-28T16:00:00Z"), power_reader=lambda since: [],
                    app_reader=lambda: APP_UP, notifier=lambda t, b: sent.append((t, b)) or "toast", tz=CDT)
    return code, sent, log.read_text(encoding="utf-8")


def test_main_stale_exits_1_and_notifies_once(tmp_path):
    code, sent, log = _main(tmp_path, "2026-10-28T02:27:40Z")
    assert code == 1 and len(sent) == 1
    assert "NOT running" in sent[0][0] and "overdue" in sent[0][1]
    assert "exit=1 notified=toast ALERT:" in log


def test_main_fresh_is_silent(tmp_path):
    code, sent, log = _main(tmp_path, "2026-10-28T14:27:40Z")
    assert (code, sent) == (0, [])
    assert "exit=0 notified=- OK:" in log


def test_main_no_toast_still_exits_1(tmp_path):
    code, sent, _ = _main(tmp_path, "2026-10-28T02:27:40Z", "--no-toast")
    assert (code, sent) == (1, [])


def test_main_reader_failures_are_reported_not_fatal(tmp_path):
    def boom(*_):
        raise OSError("no wevtutil")
    code = chk.main(["--state", str(_state(tmp_path, "2026-10-28T14:27:40Z")),
                     "--registry", str(_registry(tmp_path)), "--no-toast"],
                    now=z("2026-10-28T16:00:00Z"), power_reader=boom, app_reader=boom, tz=CDT)
    assert code == 0
