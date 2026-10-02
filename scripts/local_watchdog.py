"""Health watchdog for the local production fleet (`scripts/local_production.py`).

    python3 scripts/local_watchdog.py            # human summary
    python3 scripts/local_watchdog.py --json     # one JSON object, for deploy/local/watchdog.ps1

WHY. Render showed a crashed or OOM-killed service in its dashboard and events
API. On one machine the supervisor restarts a role that EXITS, but nothing says
when the whole fleet is down, a role is crash-looping, a worker has hung
without exiting, or a nightly job stopped running -- the only witnesses were
the logs and the next person who happened to look.

Run inside WSL, every 5 minutes, by `deploy/local/watchdog.ps1` (Windows Task
Scheduler). The wrapper turns `alert: true` into a Windows notification, and
raises its own alert when WSL itself does not answer -- which this script, by
construction, cannot report.

WHAT IS CHECKED (each a `fail` or a `warn`):
  supervisor      pidfile present and the supervisor process alive           fail
  role:<name>     each role process alive                                    fail
  crashloop:<n>   >= 3 restarts of a role since the previous check           fail
  healthz         GET /healthz answers 200                                   fail
  heartbeat:<n>   the role's log written within 15 min (hung, not exited)    fail
  job:<name>      a due job did not run today (2 h grace), ran > 4 h,
                  or its last run exited non-zero                            warn
  backup          newest complete snapshot younger than 30 h                 warn
  disk:<path>     < 10 GB free on the data root or the off-disk archive      warn

ALERTING. A finding alerts when it is NEW, again while it persists (fail every
6 h, warn every 24 h), and once when it clears. State lives in
`<home>/run/watchdog_state.json`; transitions append to `<home>/logs/watchdog.log`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import local_production as lp  # noqa: E402

FAIL, WARN = "fail", "warn"
REALERT_SECONDS = {FAIL: 6 * 3600, WARN: 24 * 3600}
LOG_STALE_SECONDS = 15 * 60
RESTART_BURST = 3
JOB_GRACE_SECONDS = 2 * 3600
JOB_MAX_RUNTIME_SECONDS = 4 * 3600
BACKUP_MAX_AGE_SECONDS = 30 * 3600
MIN_FREE_BYTES = 10 * 1024 ** 3
STATE_NAME = "watchdog_state.json"
LOG_NAME = "watchdog.log"


@dataclass(frozen=True)
class Finding:
    key: str
    severity: str
    message: str


# --------------------------------------------------------------------------
# readings (all I/O lives here)
# --------------------------------------------------------------------------


def _pid_alive(pid: Any) -> bool:
    try:
        import psutil

        proc = psutil.Process(int(pid))
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def _healthz(port: int) -> int | str:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=10) as response:
            return int(response.status)
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"[:160]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def collect(settings: lp.Settings, now: dt.datetime) -> dict[str, Any]:
    """Every reading the evaluator needs, as plain data."""
    pidfile = _load_json(settings.run_dir / lp.PIDFILE_NAME)
    roles = pidfile.get("roles") or {}
    log_ages: dict[str, float | None] = {}
    for name in roles:
        path = settings.logs_dir / f"{name}.log"
        log_ages[name] = (now.timestamp() - path.stat().st_mtime) if path.is_file() else None
    local = lp.parse_env_file(settings.env_file) if settings.env_file.is_file() else {}
    backup_dir = lp.default_backup_dir(settings, local)
    snaps = lp._complete_snapshots(backup_dir) if backup_dir.is_dir() else []  # noqa: SLF001
    backup_age = None
    if snaps:
        newest = dt.datetime.strptime(snaps[-1].name, lp.BACKUP_SNAPSHOT_FORMAT).replace(tzinfo=dt.timezone.utc)
        backup_age = (now - newest).total_seconds()
    disks: dict[str, int] = {}
    offdisk = lp.default_offdisk_dir(local)
    for path in (settings.data_root, offdisk):
        if path is not None and Path(path).exists():
            try:
                disks[str(path)] = shutil.disk_usage(path).free
            except OSError:
                pass
    return {
        "pidfile_present": bool(pidfile),
        "supervisor_alive": _pid_alive(pidfile.get("supervisor_pid")) if pidfile else False,
        "roles_alive": {name: _pid_alive(pid) for name, pid in roles.items()},
        "restarts": {name: int(n or 0) for name, n in (pidfile.get("restarts") or {}).items()},
        "healthz": _healthz(int(pidfile.get("port") or settings.port)) if pidfile else "no pidfile",
        "log_ages": log_ages,
        "jobs": _load_json(settings.run_dir / "scheduled_jobs.json"),
        "backup_age_seconds": backup_age,
        "backup_dir": str(backup_dir),
        "disk_free": disks,
    }


# --------------------------------------------------------------------------
# evaluation (pure)
# --------------------------------------------------------------------------


def _job_findings(jobs_state: dict[str, Any], now: dt.datetime) -> list[Finding]:
    out: list[Finding] = []
    today = now.date().isoformat()
    for job in lp.SCHEDULED_JOBS:
        row = jobs_state.get(job.name) or {}
        last_run = row.get("last_run_date")
        due_at = now.replace(hour=job.hour, minute=job.minute, second=0, microsecond=0)
        due_today = job.weekday is None or now.weekday() == job.weekday
        if due_today and last_run != today and (now - due_at).total_seconds() > JOB_GRACE_SECONDS:
            out.append(Finding(f"job:{job.name}", WARN,
                               f"{job.name} was due {job.hour:02d}:{job.minute:02d}Z and has not run today (last {last_run or 'never'})"))
            continue
        if last_run == today and "last_rc" not in row:
            try:
                started = dt.datetime.fromisoformat(str(row.get("started_at")))
                if (now - started).total_seconds() > JOB_MAX_RUNTIME_SECONDS:
                    out.append(Finding(f"job:{job.name}", WARN, f"{job.name} has been running since {row.get('started_at')}"))
            except (TypeError, ValueError):
                pass
            continue
        if row.get("last_rc") not in (None, 0):
            out.append(Finding(f"job:{job.name}", WARN, f"{job.name} last run ({last_run}) exited rc={row.get('last_rc')}"))
    return out


def evaluate(readings: dict[str, Any], now: dt.datetime, previous_restarts: dict[str, int] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    if not readings.get("pidfile_present"):
        return [Finding("supervisor", FAIL, "no supervisor pidfile -- the fleet is not running (`local_production.py up`)")]
    if not readings.get("supervisor_alive"):
        findings.append(Finding("supervisor", FAIL, "supervisor process is not alive (stale pidfile)"))
    for name, alive in sorted((readings.get("roles_alive") or {}).items()):
        if not alive:
            findings.append(Finding(f"role:{name}", FAIL, f"{name} is not running"))
    previous_restarts = previous_restarts or {}
    for name, count in sorted((readings.get("restarts") or {}).items()):
        if name in previous_restarts and count - previous_restarts[name] >= RESTART_BURST:
            findings.append(Finding(f"crashloop:{name}", FAIL,
                                    f"{name} restarted {count - previous_restarts[name]}x since the last check (now {count})"))
    health = readings.get("healthz")
    if health != 200:
        findings.append(Finding("healthz", FAIL, f"/healthz did not answer 200 ({health})"))
    for name, age in sorted((readings.get("log_ages") or {}).items()):
        if (readings.get("roles_alive") or {}).get(name) and (age is None or age > LOG_STALE_SECONDS):
            shown = "no log" if age is None else f"{int(age // 60)} min"
            findings.append(Finding(f"heartbeat:{name}", FAIL, f"{name} is running but its log has been silent for {shown}"))
    findings.extend(_job_findings(readings.get("jobs") or {}, now))
    age = readings.get("backup_age_seconds")
    if age is None:
        findings.append(Finding("backup", WARN, f"no complete backup snapshot in {readings.get('backup_dir')}"))
    elif age > BACKUP_MAX_AGE_SECONDS:
        findings.append(Finding("backup", WARN, f"newest backup snapshot is {age / 3600:.0f} h old"))
    for path, free in sorted((readings.get("disk_free") or {}).items()):
        if free < MIN_FREE_BYTES:
            findings.append(Finding(f"disk:{path}", WARN, f"{free / 1024 ** 3:.1f} GB free on {path}"))
    return findings


def decide(findings: list[Finding], state: dict[str, Any], now: dt.datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """(alert, new_state). alert = {alert, kind, title, message, new, repeat, recovered}."""
    active = dict(state.get("active") or {})
    current = {f.key: f for f in findings}
    new, repeat, recovered = [], [], []
    for key, finding in current.items():
        held = active.get(key)
        if held is None:
            new.append(finding)
            active[key] = {"severity": finding.severity, "message": finding.message,
                           "since": now.isoformat(), "last_alert": now.isoformat()}
            continue
        held.update(severity=finding.severity, message=finding.message)
        last = dt.datetime.fromisoformat(held.get("last_alert") or held.get("since"))
        if (now - last).total_seconds() >= REALERT_SECONDS[finding.severity]:
            repeat.append(finding)
            held["last_alert"] = now.isoformat()
    for key in [k for k in active if k not in current]:
        recovered.append(active.pop(key))
    alert = bool(new or repeat or recovered)
    fails = sum(1 for f in findings if f.severity == FAIL)
    if findings:
        title = f"Syndicate fleet: {fails} failing, {len(findings) - fails} warning"
    else:
        title = "Syndicate fleet recovered" if recovered else "Syndicate fleet healthy"
    lines = [f"NEW: {f.message}" for f in new] + [f"STILL: {f.message}" for f in repeat]
    lines += [f"CLEARED: {r['message']}" for r in recovered]
    result = {
        "alert": alert,
        "status": "down" if fails else ("degraded" if findings else "ok"),
        "title": title,
        "message": "\n".join(lines) if lines else "all checks passed",
        "new": [asdict(f) for f in new],
        "repeat": [asdict(f) for f in repeat],
        "recovered": recovered,
        "findings": [asdict(f) for f in findings],
    }
    return result, {"active": active, "last_check": now.isoformat()}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", help="local production home (default: as local_production.py)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SYNDICATE_LOCAL_PORT") or 10000))
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    parser.add_argument("--dry-run", action="store_true", help="evaluate without saving state")
    args = parser.parse_args(argv)

    home = Path(args.home).expanduser().resolve() if args.home else lp.default_home()
    settings = lp.Settings(home=home, port=args.port)
    now = dt.datetime.now(dt.timezone.utc)
    state_path = settings.run_dir / STATE_NAME
    state = _load_json(state_path)
    readings = collect(settings, now)
    findings = evaluate(readings, now, previous_restarts=state.get("restarts") or {})
    result, new_state = decide(findings, state, now)
    new_state["restarts"] = readings.get("restarts") or {}
    result["checked_at"] = now.isoformat()

    if not args.dry_run:
        settings.run_dir.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(new_state, indent=2), encoding="utf-8")
        if result["alert"]:
            settings.logs_dir.mkdir(parents=True, exist_ok=True)
            with (settings.logs_dir / LOG_NAME).open("a", encoding="utf-8") as handle:
                handle.write(f"{now.isoformat()} {result['status']} {result['title']} | "
                             + result["message"].replace("\n", " | ") + "\n")
    if args.json:
        print(json.dumps(result))
    else:
        print(f"{result['status'].upper()}  {result['title']}  (alert={result['alert']})")
        for f in findings:
            print(f"  [{f.severity}] {f.key}: {f.message}")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
