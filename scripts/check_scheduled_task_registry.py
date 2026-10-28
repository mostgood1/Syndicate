"""Alert when the Claude desktop app's scheduled-task registry is lost -- from OUTSIDE that registry.

Lane `scheduled-task-registry-alert` [2026-10-28].

WHY. Between 05:45Z and 07:38Z on 2026-10-28 the desktop app's task registry emptied: all 46 enabled
tasks, the missed-dispatch watchdog (`syndicate-dispatch-watchdog`) among them. The watchdog was the
only monitor and it lived in the registry it watched, so nothing alerted; a session found the loss
~5 h later by chance (learnings.md 2026-10-28). This check is meant to run from Windows Task
Scheduler, which the app cannot delete.

TWO SIGNALS. Either one alerts.

1. THE REGISTRY FILE. The app keeps its tasks in
   %LOCALAPPDATA%\\Claude-Data\\<install>\\claude-code-sessions\\<org>\\<account>\\scheduled-tasks.json
   (found 2026-10-28; an undocumented internal file, so treat its shape as a guess that can break).
   The newest-modified candidate must parse and hold the watchdog, enabled. This one is fast: it
   catches a wipe at the next check, whatever the clock says. A file that is missing or will not
   parse ALERTS -- the 10-28 update moved the app's data directory, and "unknown" must not read as
   healthy.

2. THE WATCHDOG'S OWN HEARTBEAT. Every watchdog run ends by writing `last_run_utc` to its
   `state.json`. A due time of its cron that passed more than --grace-minutes ago with no run at or
   after it means the watchdog is not completing runs: the registry is gone, the app is not
   dispatching, or a run is frozen on a permission prompt (the 2026-10-01 failure, which blocked every
   later firing of the task). Slower than signal 1, but end-to-end.

THE WATCHDOG'S GAPS ARE NOT EVEN. Its cron is `15 9,13,17,21 * * *` in local time, so the overnight
gap is 12 h. A flat age threshold of ~5 h would alarm every morning. This evaluates the cron (read
from the registry entry when it parses, else DEFAULT_CRON) instead.

MODERN STANDBY. Nothing fires while this host is in standby (S0 low-power idle), and Task Scheduler
runs a missed check on wake (StartWhenAvailable), so a stale reading right after wake is expected. A
due time is judged only if:
  - the machine was awake from it until --awake-minutes after it (System log: Kernel-Power 506/507
    and 42/107, Power-Troubleshooter 1, Kernel-General 13/12), with the first --settle-minutes after
    every wake or boot counted as asleep; and
  - the desktop app's process had been running for --settle-minutes before it.
If no due time in the last --lookback-hours qualifies, the verdict is UNJUDGED: silent, exit 0. If
the power history or the process list cannot be read, that guard is dropped rather than assumed --
the check may then alarm, and its output says why.

Read-only: reads two files, the System event log and the process list; writes only --log. Never
prints a secret: the registry file is reduced to counts and the watchdog's enabled flag.

Exit: 0 OK or UNJUDGED; 1 ALERT (plus a Windows toast unless --no-toast).

  py -3 scripts/check_scheduled_task_registry.py                    # one check
  py -3 scripts/check_scheduled_task_registry.py --no-toast --json  # look without notifying
  py -3 scripts/check_scheduled_task_registry.py --state <copy> --now 2026-10-28T15:50:00Z   # drill
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import glob
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Callable, Optional

UTC = dt.timezone.utc
WATCHDOG_ID = "syndicate-dispatch-watchdog"
DEFAULT_CRON = "15 9,13,17,21 * * *"
DEFAULT_STATE = pathlib.Path.home() / ".claude" / "scheduled-tasks" / WATCHDOG_ID / "state.json"
# Newest-modified match wins, so a stale copy left behind by a data-directory move cannot mask an
# empty registry that the app is actually using.
REGISTRY_GLOBS = (
    r"%LOCALAPPDATA%\Claude-Data\*\claude-code-sessions\*\*\scheduled-tasks.json",
    r"%APPDATA%\Claude\claude-code-sessions\*\*\scheduled-tasks.json",
)

# (provider, event id) -> True when the machine goes to sleep or off, False when it comes back.
POWER_EVENTS = {
    ("Microsoft-Windows-Kernel-Power", 506): True,    # entering Modern Standby
    ("Microsoft-Windows-Kernel-Power", 507): False,   # exiting Modern Standby
    ("Microsoft-Windows-Kernel-Power", 42): True,     # entering sleep / hibernate
    ("Microsoft-Windows-Kernel-Power", 107): False,   # resumed from sleep
    ("Microsoft-Windows-Power-Troubleshooter", 1): False,  # returned from a low power state
    ("Microsoft-Windows-Kernel-General", 13): True,   # operating system shutting down
    ("Microsoft-Windows-Kernel-General", 12): False,  # operating system started
}
BOOT = ("Microsoft-Windows-Kernel-General", 12)
EVENT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"

# A run dispatched a little before its due time still counts for it. The app adds a positive per-task
# jitter (648 s for the watchdog on 10-28); this only absorbs clock noise.
RUN_TOLERANCE = dt.timedelta(minutes=5)
# A pythonw.exe parent has no console, so every console child would flash a window.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PowerEvent = tuple  # (datetime UTC, provider, event id)


@dataclasses.dataclass
class AppState:
    running: bool
    started: Optional[dt.datetime]  # earliest start of a desktop-app process, UTC


@dataclasses.dataclass
class Verdict:
    status: str  # OK | UNJUDGED | ALERT
    problems: list
    notes: list
    facts: dict

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "ALERT" else 0


def parse_utc(text: str) -> dt.datetime:
    """ISO 8601 -> aware UTC. Accepts `Z` and the event log's 7-digit fractions."""
    s = text.strip().replace("Z", "+00:00")
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def parse_cron(expr: str) -> Optional[tuple]:
    """`M H1,H2,... * * *` -> (minute, [hours]); anything richer -> None (caller falls back)."""
    m = re.fullmatch(r"\s*(\d{1,2})\s+(\d{1,2}(?:,\d{1,2})*)\s+\*\s+\*\s+\*\s*", expr or "")
    if not m:
        return None
    minute = int(m.group(1))
    hours = sorted({int(h) for h in m.group(2).split(",")})
    if minute > 59 or any(h > 23 for h in hours):
        return None
    return minute, hours


def _to_local(t: dt.datetime, tz) -> dt.datetime:
    return t.astimezone(tz) if tz is not None else t.astimezone()


def due_times(cron: tuple, start: dt.datetime, end: dt.datetime, tz=None) -> list:
    """Every fire time of `cron` (local wall clock; `tz=None` = this machine's) in [start, end], UTC."""
    minute, hours = cron
    day = _to_local(start, tz).date() - dt.timedelta(days=1)
    last = _to_local(end, tz).date() + dt.timedelta(days=1)
    out = []
    while day <= last:
        for hour in hours:
            naive = dt.datetime(day.year, day.month, day.day, hour, minute)
            local = naive.replace(tzinfo=tz) if tz is not None else naive.astimezone()
            when = local.astimezone(UTC)
            if start <= when <= end:
                out.append(when)
        day += dt.timedelta(days=1)
    return sorted(out)


def sleep_intervals(events: list, since: dt.datetime, now: dt.datetime) -> list:
    """Power events -> [(asleep_from, awake_at)] in UTC.

    Deliberately pessimistic about being awake: a wake with no sleep seen before it (its sleep fell
    before `since`) and a boot with no shutdown before it (crash, power loss) both count as asleep
    from the previous event we saw, and an unclosed sleep runs to `now`.
    """
    out = []
    asleep_from = None
    last_seen = since
    for when, provider, event_id in sorted(events, key=lambda e: e[0]):
        key = (provider, event_id)
        if key not in POWER_EVENTS:
            continue
        if POWER_EVENTS[key]:
            if asleep_from is None:
                asleep_from = when
        elif asleep_from is not None:
            out.append((asleep_from, when))
            asleep_from = None
        elif key == BOOT or last_seen == since:
            out.append((last_seen, when))
        last_seen = when
    if asleep_from is not None:
        out.append((asleep_from, now))
    return out


def parse_event_xml(text: str) -> list:
    """`wevtutil qe ... /f:xml` output (concatenated <Event> elements) -> [(UTC, provider, id)]."""
    if not text.strip():
        return []
    root = ET.fromstring("<Events>" + text + "</Events>")
    out = []
    for ev in root.iter(EVENT_NS + "Event"):
        system = ev.find(EVENT_NS + "System")
        provider = system.find(EVENT_NS + "Provider").get("Name")
        event_id = int(system.find(EVENT_NS + "EventID").text)
        when = parse_utc(system.find(EVENT_NS + "TimeCreated").get("SystemTime"))
        out.append((when, provider, event_id))
    return out


def read_power_events(since: dt.datetime) -> list:
    """The System log's sleep/wake/boot events since `since` (real clock; raises when unreadable)."""
    ms = max(0, int((dt.datetime.now(UTC) - since).total_seconds() * 1000))
    clauses = " or ".join(f"(Provider[@Name='{p}'] and EventID={i})" for p, i in POWER_EVENTS)
    query = f"*[System[({clauses}) and TimeCreated[timediff(@SystemTime) <= {ms}]]]"
    proc = subprocess.run(["wevtutil", "qe", "System", "/q:" + query, "/f:xml"],
                          capture_output=True, text=True, errors="replace", timeout=60,
                          creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"wevtutil exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    return parse_event_xml(proc.stdout)


_APP_PS = (
    "Get-Process -Name claude -ErrorAction SilentlyContinue | ForEach-Object { "
    "[pscustomobject]@{ path = $_.Path; start = $_.StartTime.ToUniversalTime().ToString('o') } } "
    "| ConvertTo-Json -Compress"
)


def desktop_app_state(processes: list) -> AppState:
    """`claude.exe` processes -> the desktop app's state. The Claude Code CLI ships under a
    `\\claude-code\\<version>\\` folder and runs as `claude.exe` too; it cannot fire a scheduled task."""
    starts = [parse_utc(p["start"]) for p in processes
              if p.get("start") and "\\claude-code\\" not in (p.get("path") or "").lower()]
    return AppState(running=bool(starts), started=min(starts) if starts else None)


def read_app_state() -> AppState:
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _APP_PS],
                          capture_output=True, text=True, errors="replace", timeout=60,
                          creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"Get-Process exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    raw = proc.stdout.strip()
    data = json.loads(raw) if raw else []
    return desktop_app_state(data if isinstance(data, list) else [data])


def registry_candidates() -> list:
    out = []
    for pattern in REGISTRY_GLOBS:
        out.extend(pathlib.Path(p) for p in glob.glob(os.path.expandvars(pattern)))
    return out


def _load_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        time.sleep(1)  # caught mid-write by the app: one retry, then let it raise
        return json.loads(path.read_text(encoding="utf-8"))


def check_registry(paths: list) -> tuple:
    """-> (problems, facts, the watchdog's cron expression or None)."""
    existing = [p for p in paths if p.is_file()]
    if not existing:
        return (["the app's task registry file was not found under %LOCALAPPDATA%\\Claude-Data or "
                 "%APPDATA%\\Claude: lost, or the app moved its data again"], {"registry_path": None}, None)
    path = max(existing, key=lambda p: p.stat().st_mtime)
    facts = {"registry_path": str(path), "registry_candidates": len(existing)}
    try:
        data = _load_json(path)
    except (OSError, ValueError) as exc:
        return [f"the task registry file does not parse ({type(exc).__name__})"], facts, None
    tasks = data.get("scheduledTasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list):
        return ["the task registry file has no `scheduledTasks` list (format changed?)"], facts, None
    tasks = [t for t in tasks if isinstance(t, dict)]
    enabled = sum(1 for t in tasks if t.get("enabled"))
    facts.update(registry_tasks=len(tasks), registry_enabled=enabled)
    watchdog = next((t for t in tasks if t.get("id") == WATCHDOG_ID), None)
    if watchdog is None:
        return ([f"REGISTRY LOST: {WATCHDOG_ID} is not in the app's task registry "
                 f"({len(tasks)} tasks, {enabled} enabled)"], facts, None)
    facts["watchdog_enabled"] = bool(watchdog.get("enabled"))
    if not watchdog.get("enabled"):
        return [f"{WATCHDOG_ID} is DISABLED in the app's task registry"], facts, watchdog.get("cronExpression")
    return [], facts, watchdog.get("cronExpression")


def _fmt(t: Optional[dt.datetime], tz) -> str:
    return _to_local(t, tz).strftime("%m-%d %H:%M CT") if t is not None else "never"


def _why_unjudgeable(due: dt.datetime, *, asleep: list, app: Optional[AppState],
                     awake: dt.timedelta, settle: dt.timedelta) -> Optional[str]:
    if app is not None and app.started is not None and app.started > due - settle:
        return "app started after it"
    for begin, end in asleep:
        if begin < due + awake and end + settle > due:
            return "machine asleep around it"
    return None


def evaluate(*, now: dt.datetime, state_path: pathlib.Path, registry_paths: list,
             cron_override: Optional[str] = None,
             grace: dt.timedelta = dt.timedelta(minutes=90),
             awake: dt.timedelta = dt.timedelta(minutes=20),
             settle: dt.timedelta = dt.timedelta(minutes=15),
             lookback: dt.timedelta = dt.timedelta(hours=48),
             power_events: Optional[list] = None, power_error: Optional[str] = None,
             app: Optional[AppState] = None, app_error: Optional[str] = None,
             tz=None) -> Verdict:
    problems, notes = [], []
    reg_problems, facts, reg_cron = check_registry(registry_paths)
    problems += reg_problems
    facts["now_utc"] = now.isoformat()

    cron_expr = cron_override or reg_cron or DEFAULT_CRON
    cron = parse_cron(cron_expr)
    if cron is None:
        notes.append(f"cron {cron_expr!r} is not `M H,H * * *`; judged against {DEFAULT_CRON!r}")
        cron_expr, cron = DEFAULT_CRON, parse_cron(DEFAULT_CRON)
    facts["cron"] = cron_expr

    if app_error:
        notes.append(f"process list unreadable ({app_error}); app-start guard OFF")
        app = None
    elif app is not None:
        facts["app_running"] = app.running
        facts["app_started_utc"] = app.started.isoformat() if app.started else None
        if not app.running:
            problems.append("the Claude desktop app is NOT RUNNING: no scheduled task can fire")
    if power_error:
        notes.append(f"power history unreadable ({power_error}); standby NOT excluded")
    asleep = sleep_intervals(power_events or [], now - lookback - dt.timedelta(hours=24), now)
    facts["sleep_intervals_in_window"] = sum(1 for _, end in asleep if end >= now - lookback)

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        last_run = parse_utc(state["last_run_utc"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        problems.append(f"the watchdog's state.json is unreadable ({type(exc).__name__}): "
                        "it has never run here, or its file is gone")
        last_run = None
    facts["watchdog_last_run_utc"] = last_run.isoformat() if last_run else None

    judged, skipped = None, 0
    if last_run is not None:
        for due in reversed(due_times(cron, now - lookback, now - grace, tz)):
            why = _why_unjudgeable(due, asleep=asleep, app=app if (app and app.running) else None,
                                   awake=awake, settle=settle)
            if why is None:
                judged = due
                break
            skipped += 1
            if skipped == 1:
                notes.append(f"due {_fmt(due, tz)} not judged: {why}")
    facts["judged_due_utc"] = judged.isoformat() if judged else None
    facts["due_times_skipped"] = skipped

    if last_run is not None and judged is not None and last_run < judged - RUN_TOLERANCE:
        hours = (now - judged).total_seconds() / 3600
        problems.append(f"the dispatch watchdog has not completed a run since {_fmt(last_run, tz)}; "
                        f"its {_fmt(judged, tz)} run is {hours:.1f} h overdue with the machine awake")

    registry = (f"registry {facts.get('registry_tasks')} tasks, {facts.get('registry_enabled')} enabled, "
                f"incl. {WATCHDOG_ID}")
    if problems:
        status = "ALERT"
    elif last_run is not None and judged is None:
        status = "UNJUDGED"
        notes.append(f"no due time in the last {lookback.total_seconds() / 3600:.0f} h had the machine "
                     f"awake and the app up, so only the registry was checked: {registry}")
    else:
        status = "OK"
        notes.append(f"watchdog last ran {_fmt(last_run, tz)}, covering its {_fmt(judged, tz)} due time; "
                     f"{registry}")
    return Verdict(status, problems, notes, facts)


_TOAST_PS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [Security.SecurityElement]::Escape($env:SYNDICATE_ALERT_TITLE)
$b = [Security.SecurityElement]::Escape($env:SYNDICATE_ALERT_BODY)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast duration='long'><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
# The registered AppUserModelID of Windows PowerShell, as deploy/local/watchdog.ps1 uses: no installer needed.
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def notify(title: str, body: str) -> str:
    """Windows toast; `msg.exe` to the console session if the toast fails. -> what was shown."""
    env = dict(os.environ, SYNDICATE_ALERT_TITLE=title, SYNDICATE_ALERT_BODY=body[:400])
    try:
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _TOAST_PS],
                              env=env, capture_output=True, text=True, errors="replace", timeout=60,
                              creationflags=_NO_WINDOW)
        if proc.returncode == 0:
            return "toast"
        failure = f"toast exit {proc.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        failure = f"toast {type(exc).__name__}"
    try:
        proc = subprocess.run(["msg.exe", "*", f"{title}: {body}"[:255]], capture_output=True,
                              timeout=30, creationflags=_NO_WINDOW)
        return f"{failure}; msg exit {proc.returncode}" if proc.returncode else f"{failure}; msg"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{failure}; msg {type(exc).__name__}"


def summary(v: Verdict) -> str:
    return f"{v.status}: " + " | ".join(v.problems or v.notes)


def main(argv=None, *, now: Optional[dt.datetime] = None,
         power_reader: Callable = read_power_events, app_reader: Callable = read_app_state,
         notifier: Callable = notify, registry_finder: Callable = registry_candidates, tz=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default=str(DEFAULT_STATE), help="the watchdog's state.json")
    ap.add_argument("--registry", action="append", help="registry file(s); default: discover")
    ap.add_argument("--cron", help="override the watchdog's cron (default: its registry entry)")
    ap.add_argument("--now", help="judge as of this UTC instant (drills); power/app reads stay real")
    ap.add_argument("--grace-minutes", type=float, default=90)
    ap.add_argument("--awake-minutes", type=float, default=20)
    ap.add_argument("--settle-minutes", type=float, default=15)
    ap.add_argument("--lookback-hours", type=float, default=48)
    ap.add_argument("--no-toast", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--log", help="append one line per run here")
    a = ap.parse_args(argv)

    when = parse_utc(a.now) if a.now else (now or dt.datetime.now(UTC))
    lookback = dt.timedelta(hours=a.lookback_hours)
    power_events, power_error = None, None
    try:
        power_events = power_reader(when - lookback - dt.timedelta(hours=24))
    except Exception as exc:  # noqa: BLE001 -- any failure here means "standby unknown", reported
        power_error = f"{type(exc).__name__}: {str(exc)[:120]}"
    app, app_error = None, None
    try:
        app = app_reader()
    except Exception as exc:  # noqa: BLE001
        app_error = f"{type(exc).__name__}: {str(exc)[:120]}"
    registry_paths = [pathlib.Path(p) for p in a.registry] if a.registry else registry_finder()

    v = evaluate(now=when, state_path=pathlib.Path(a.state), registry_paths=registry_paths,
                 cron_override=a.cron, grace=dt.timedelta(minutes=a.grace_minutes),
                 awake=dt.timedelta(minutes=a.awake_minutes), settle=dt.timedelta(minutes=a.settle_minutes),
                 lookback=lookback, power_events=power_events, power_error=power_error,
                 app=app, app_error=app_error, tz=tz)

    shown = "-"
    if v.status == "ALERT" and not a.no_toast:
        # A --now run is a drill; say so, so a drill toast is never mistaken for the real thing.
        shown = notifier(("[DRILL] " if a.now else "") + "Syndicate: scheduled tasks are NOT running",
                         "; ".join(v.problems) + ". Check Claude > Scheduled tasks; restore recipe in "
                         "learnings.md 2026-10-28.")
    line = summary(v)
    if a.json:
        print(json.dumps({"status": v.status, "exit": v.exit_code, "problems": v.problems,
                          "notes": v.notes, "notified": shown, "facts": v.facts}, indent=1))
    else:
        print(line)
    if a.log:
        stamp = dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(a.log, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} exit={v.exit_code} notified={shown} {line}\n")
    return v.exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- a check that crashes must not be as quiet as one that passes
        if "--no-toast" not in sys.argv:
            notify("Syndicate: task-registry check CRASHED", f"{type(exc).__name__}: {exc}"[:300])
        raise
