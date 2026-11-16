"""Shared plumbing for the pipeline diagnostics.

Both `diagnose_betting_pipeline.py` and `diagnose_sim_pipeline.py` read
PRODUCTION, never the local checkout. That is deliberate and is the single
most important property of these tools: `data/**` in git is a lossy mirror
refreshed on its own schedule, so a diagnosis built from the working tree
describes a machine nobody is running.

Design rules learned the expensive way on 2026-08-09, all encoded here:

- **A failed read is a finding, not a crash.** Web OOM-cycles; a 502 is a
  RESULT ("web was down when asked"), and every probe records how it failed
  so a zero is never silently indistinguishable from an unanswered question.
- **State the window.** Every rate carries the interval it was measured over.
  "Absent in this log window" is not "absent".
- **Read every service's live commit at the same instant, BEFORE any number.**
  A stale service produces clean, decisive, wrong numbers.
- **A count needs a denominator.** `rows=155` means nothing without
  `considered=3324`.

PRODUCTION means the local WSL fleet (`http://127.0.0.1:10000`, logs in
`~/syndicate-prod/logs`) since 2026-09-30. Until 2026-11-15 the logs, commits and
kill events came from the Render API; that path was retired (lane render-retirement).
"""

from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts._base_url import admin_token as resolve_admin_token, default_base_url
except ImportError:  # run as `python scripts/<name>.py`
    from _base_url import admin_token as resolve_admin_token, default_base_url

WEB_BASE = default_base_url("SYNDICATE_DIAG_BASE_URL")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Probe:
    """One read of one surface. Carries HOW it failed, not just whether."""

    label: str
    ok: bool
    detail: str = ""
    value: Any = None
    status: int | None = None

    def render(self) -> str:
        mark = "OK  " if self.ok else "FAIL"
        status = f" [http {self.status}]" if self.status is not None else ""
        return f"  {mark} {self.label}{status}{(' - ' + self.detail) if self.detail else ''}"


def http_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 60) -> tuple[Any, int | None, str]:
    """Fetch JSON. Returns (payload, status, error). NEVER raises.

    A 502 from a restarting web service must reach the report as a status,
    not as a traceback that hides every check after it.
    """
    request = urllib.request.Request(url, headers=headers or {})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = response.read()
            status = response.getcode()
    except urllib.error.HTTPError as exc:
        return None, exc.code, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - a diagnostic must survive anything
        return None, None, f"{type(exc).__name__}: {exc}"
    try:
        return json.loads(body.decode("utf-8", errors="replace")), status, ""
    except Exception:
        return None, status, f"non-JSON body ({len(body)} bytes)"


def web_json(path: str, *, admin: bool = False, timeout: int = 60) -> tuple[Any, int | None, str]:
    headers = {}
    if admin:
        token = resolve_admin_token(WEB_BASE)
        if not token:
            return None, None, "ADMIN_TOKEN not set"
        headers["X-Admin-Token"] = token
    return http_json(f"{WEB_BASE}{path}", headers=headers, timeout=timeout)


# PRODUCTION IS THE LOCAL WSL FLEET `[since 2026-09-30; the Render API reads here were
# retired 2026-11-15, lane render-retirement]`. Logs, live commits, kill events and env
# flags come from the fleet host -- through `wsl.exe` on Windows, a plain shell on the
# host itself -- and never from Render, which the user said on 2026-11-15 must not be
# used or needed for anything.
FLEET_WSL_DISTRO = os.environ.get("SYNDICATE_FLEET_WSL_DISTRO", "Ubuntu-24.04")
# A POSIX path on the fleet host; `$HOME` is expanded there, not here.
FLEET_LOG_DIR = os.environ.get("SYNDICATE_FLEET_LOG_DIR", "$HOME/syndicate-prod/logs")

# Service name -> the fleet role's log name (`<FLEET_LOG_DIR>/<role>.log`). The keys are
# the names the diagnostics have always used; the values were Render service ids.
SERVICES = {
    "web": "web",
    "refresh-worker": "refresh-worker",
    "live-odds-worker": "live-odds-worker",
}

SPORTS = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")

# `local_logstamp` prefixes every line a role prints with `2026-10-02T14:36:49.123Z `.
_STAMPED = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z (.*)$")
_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def fleet_shell(command: str, *, timeout: int = 120) -> tuple[str, str]:
    """(stdout, error) of one `sh -c` on the fleet host. NEVER raises.

    A non-zero exit with output is returned WITH its error, so a caller can tell a
    partial read from an empty one.
    """
    argv = ["sh", "-c", command]
    if os.name == "nt":
        argv = ["wsl.exe", "-d", FLEET_WSL_DISTRO, "-e", *argv]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"fleet shell failed: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return proc.stdout or "", f"fleet shell rc {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
    return proc.stdout or "", ""


def _parse_log_lines(text: str) -> list[dict[str, Any]]:
    """`{timestamp, message}` rows, oldest-first. An unstamped line (a traceback, a
    supervisor line) inherits the previous stamp and is marked `approximate`; one
    before any stamp is dropped, because a row with no time cannot sit in a window."""
    out: list[dict[str, Any]] = []
    last = ""
    for line in text.splitlines():
        found = _STAMPED.match(line)
        if found:
            last = found.group(1)
            out.append({"timestamp": last, "message": found.group(2)})
        elif last and line.strip():
            out.append({"timestamp": last, "message": line, "approximate": True})
    return out


def fetch_logs(service: str, *, limit: int = 20000) -> tuple[list[dict[str, Any]], str]:
    """The newest `limit` lines of one fleet role's log. Returns (logs, error).

    An EMPTY LIST WITH NO ERROR means the role genuinely printed nothing; an empty list
    WITH an error means we failed to ask. Callers must distinguish these -- conflating
    them is how a broken query becomes a false production finding.

    Only the CURRENT log file is read (`tail`), so the window is at most what that file
    holds since its last rotation. `log_window()` says what was actually covered.
    """
    role = SERVICES.get(service, service)
    if role not in SERVICES.values():
        return [], f"unknown service {service!r}"
    lines = max(1, int(limit))
    text, error = fleet_shell(f'tail -n {lines} "{FLEET_LOG_DIR}/{role}.log"', timeout=180)
    if error and not text:
        return [], error
    return _parse_log_lines(text), error


def log_window(logs: Iterable[dict[str, Any]]) -> tuple[str, str, float]:
    """(earliest, latest, minutes). The denominator for every rate below."""
    stamps = sorted(str(entry.get("timestamp") or "")[:19] for entry in logs if entry.get("timestamp"))
    if not stamps:
        return "", "", 0.0
    try:
        first = datetime.fromisoformat(stamps[0]).replace(tzinfo=timezone.utc)
        last = datetime.fromisoformat(stamps[-1]).replace(tzinfo=timezone.utc)
        return stamps[0], stamps[-1], (last - first).total_seconds() / 60.0
    except ValueError:
        return stamps[0], stamps[-1], 0.0


def matches(logs: Iterable[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    compiled = re.compile(pattern, re.IGNORECASE)
    hits = [entry for entry in logs if compiled.search(str(entry.get("message") or ""))]
    return sorted(hits, key=lambda entry: str(entry.get("timestamp") or ""))


def cadence(hits: list[dict[str, Any]]) -> tuple[float | None, str]:
    """Mean gap in minutes between occurrences, plus a human summary.

    Returns (None, reason) when there are fewer than two samples -- one
    occurrence tells you a thing happened, never how often.
    """
    stamps = []
    for entry in hits:
        raw = str(entry.get("timestamp") or "")[:19]
        try:
            stamps.append(datetime.fromisoformat(raw).replace(tzinfo=timezone.utc))
        except ValueError:
            continue
    if len(stamps) < 2:
        return None, f"{len(stamps)} sample(s) - cannot infer a rate"
    stamps.sort()
    gaps = [(b - a).total_seconds() / 60.0 for a, b in zip(stamps, stamps[1:])]
    mean = sum(gaps) / len(gaps)
    return mean, f"{len(stamps)} in window, mean gap {mean:.1f} min (min {min(gaps):.1f}, max {max(gaps):.1f})"


def _fleet_status() -> tuple[str, dict[str, dict]]:
    """`deploy_preflight.fleet_status()`: (checkout HEAD, {role: {pid, up, live_commit}})."""
    try:
        from scripts.deploy_preflight import fleet_status
    except ImportError:  # run as `python scripts/<name>.py`
        from deploy_preflight import fleet_status
    return fleet_status()


def service_commits() -> dict[str, str]:
    """The commit each fleet role LOADED, read in one pass (`local_production.py status`).

    Read this BEFORE any measurement. Two roles on different commits can answer the
    same question differently and both look authoritative. A role that is down or
    unreadable reads `?(...)`, never a commit.
    """
    try:
        _, status = _fleet_status()
    except Exception as exc:  # noqa: BLE001 - a diagnostic must survive anything
        return {name: f"?(fleet status: {type(exc).__name__})" for name in SERVICES}
    out: dict[str, str] = {}
    for name, role in SERVICES.items():
        row = status.get(role)
        if row is None:
            out[name] = "?(not in local_production.py status)"
        elif not row.get("up"):
            out[name] = "?(role DOWN)"
        else:
            out[name] = str(row.get("live_commit") or "?(no commit stamp)")
    return out


_GUNICORN_KILL = "was sent SIGKILL|WORKER TIMEOUT|Perhaps out of memory"


def oom_events(service: str, *, limit: int = 20) -> list[tuple[str, str]] | None:
    """(timestamp, kind) for the role's recent kills/restarts, newest first, or None
    when the fleet keeps NO record for this role (an unknown, not a clean bill).

    - refresh-worker: `role_restarts.jsonl`, which the supervisor appends on every exit
      with its code, signal and whether a deploy claim covered it. A SIGKILL is the
      kernel OOM killer or a `kill -9`; the record cannot tell which.
    - web: gunicorn's own worker-kill lines in `web.log` (`was sent SIGKILL! Perhaps out
      of memory?`, `WORKER TIMEOUT`), current file only.
    - live-odds-worker: None. The supervisor records its exits only in unstamped
      `supervisor.log` lines.
    """
    role = SERVICES.get(service, service)
    count = max(1, int(limit))
    out: list[tuple[str, str]] = []
    if role == "refresh-worker":
        text, error = fleet_shell(f'tail -n 2000 "{FLEET_LOG_DIR}/role_restarts.jsonl"')
        if error and not text:
            return None
        for line in text.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("role") != role or entry.get("event") != "exit":
                continue
            sig = entry.get("signal")
            if sig == "SIGKILL":
                kind = "OOM KILLED? (SIGKILL: the kernel OOM killer or a kill -9)"
            elif sig:
                kind = f"exit {sig}"
            else:
                kind = f"exit code={entry.get('code')}"
            kind += " (claimed restart)" if entry.get("claimed") else " (UNCLAIMED)"
            out.append((str(entry.get("at") or "")[:19], kind))
        return list(reversed(out))[:count]
    if role == "web":
        text, error = fleet_shell(
            f'grep -E "{_GUNICORN_KILL}" "{FLEET_LOG_DIR}/web.log" | tail -n {count}; exit 0'
        )
        if error and not text:
            return None
        for row in _parse_log_lines(text) or [{"timestamp": "", "message": line} for line in text.splitlines()]:
            message = str(row.get("message") or "")
            if "SIGKILL" in message or "out of memory" in message.lower():
                kind = "OOM KILLED? (gunicorn worker SIGKILL)"
            else:
                kind = "unhealthy: gunicorn WORKER TIMEOUT"
            out.append((str(row.get("timestamp") or "")[:19], kind))
        return list(reversed(out))[:count]
    return None


def fleet_role_env(service: str, keys: Iterable[str]) -> tuple[dict[str, str], str]:
    """The named env keys of one running fleet role, from its `/proc/<pid>/environ`.
    Returns (values, error).

    ONLY the keys asked for cross the boundary -- a grep on the fleet host, never the
    whole environ -- and each must be a plain env-var NAME. Ask for flags and intervals,
    never a credential. A key absent from the role is absent from the result: absent is
    not off, so callers print `<unset>` and check the code's default.
    """
    wanted = sorted({str(key) for key in keys if key})
    bad = [key for key in wanted if not _ENV_KEY.match(key)]
    if bad:
        return {}, f"refusing non-name keys {bad}"
    if not wanted:
        return {}, ""
    role = SERVICES.get(service, service)
    try:
        _, status = _fleet_status()
    except Exception as exc:  # noqa: BLE001
        return {}, f"fleet status: {type(exc).__name__}: {exc}"
    pid = str((status.get(role) or {}).get("pid") or "")
    if not pid.isdigit():
        return {}, f"no running pid for {role}"
    pattern = "|".join(wanted)
    text, error = fleet_shell(f"tr '\\0' '\\n' < /proc/{pid}/environ | grep -E '^({pattern})=' ; exit 0")
    values: dict[str, str] = {}
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if sep and name in wanted:
            values[name] = value
    return values, error


@dataclass
class Stage:
    """One pipeline stage. `count` is the thing that must not be zero."""

    name: str
    count: int | None = None
    denominator: int | None = None
    cadence_note: str = ""
    probes: list[Probe] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unknown: bool = False  # could not be measured -- NOT the same as zero

    @property
    def healthy(self) -> bool:
        if self.unknown:
            return False
        return bool(self.count)

    def render(self) -> str:
        if self.unknown:
            head = f"  ??  {self.name}: UNMEASURED"
        else:
            total = f" of {self.denominator}" if self.denominator is not None else ""
            head = f"  {'OK ' if self.healthy else 'ZERO'} {self.name}: {self.count}{total}"
        lines = [head]
        if self.cadence_note:
            lines.append(f"        cadence: {self.cadence_note}")
        for note in self.notes:
            lines.append(f"        {note}")
        for probe in self.probes:
            if not probe.ok:
                lines.append(f"      {probe.render().strip()}")
        return "\n".join(lines)


def first_broken(stages: list[Stage]) -> Stage | None:
    """The first stage that is zero or unmeasured.

    The whole point of the ordering. Do not spend time on readers,
    endpoints or the UI until the earliest zero is known -- every stage
    downstream of a zero reads as broken and none of them are the cause.
    """
    for stage in stages:
        if not stage.healthy:
            return stage
    return None


def banner(title: str) -> str:
    return f"\n{'=' * 78}\n{title}\n{'=' * 78}"


# --------------------------------------------------------------------------
# STALENESS GUARD
#
# Reading local `data/**` is not the mistake. Reading it WITHOUT KNOWING ITS
# AGE is, and no warning prevents that -- `CLAUDE.md` has carried one for
# months and on 2026-08-10 a five-day-old book-quotes shard was still profiled
# and reported as current, with the contradicting evidence in hand (production
# said 122k rows, the file had 34k) and explained away as "today's shard is
# bigger".
#
# So these make the age unavoidable rather than remembered: `require_fresh`
# returns False and says why, and `freshness_note` is what a report prints
# above any number that came off local disk.
# --------------------------------------------------------------------------

_DATE_IN_NAME = re.compile(r"(20\d{2})[-_](\d{2})[-_](\d{2})")


def local_artifact_freshness(pattern: str) -> tuple[str | None, float | None, int]:
    """(newest date in the filenames, age in days, file count) for a glob.

    Dates come from the FILENAME, not mtime: a mirror refresh rewrites mtimes
    wholesale, so mtime says when the copy happened and the filename says which
    slate the data is actually about. Only the second one matters for whether a
    conclusion is safe.
    """
    dates: set[str] = set()
    count = 0
    for path in REPO_ROOT.glob(pattern):
        count += 1
        found = _DATE_IN_NAME.search(path.name)
        if found:
            dates.add(f"{found.group(1)}-{found.group(2)}-{found.group(3)}")
    if not dates:
        return None, None, count
    newest = max(dates)
    try:
        parsed = datetime.strptime(newest, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return newest, None, count
    return newest, (utcnow() - parsed).total_seconds() / 86400.0, count


def require_fresh(pattern: str, *, max_age_days: float = 1.0, purpose: str = "this analysis") -> bool:
    """False (loudly) when local data is too old to support a conclusion.

    Call this BEFORE reading local artifacts, and stop if it returns False.
    It deliberately does not raise -- a diagnostic that dies on a stale mirror
    is less useful than one that reports the staleness as its finding.
    """
    newest, age, count = local_artifact_freshness(pattern)
    if count == 0:
        print(f"  !! NO LOCAL FILES match {pattern}")
        print(f"     {purpose} cannot use local data. Read production, or pull with scripts/mirror_pull.py.")
        return False
    if age is None:
        print(f"  !! {count} local file(s) for {pattern} carry no parseable date -- age UNKNOWN, not fresh.")
        return False
    if age > max_age_days:
        print(f"  !! LOCAL DATA IS {age:.1f} DAYS OLD (newest {newest}, {count} files) for {pattern}")
        print(f"     {purpose} must not rest on this. `py -3 scripts/mirror_pull.py --family ... --date ...`")
        print("     Shape is still safe to read from a stale mirror; dates, counts and coverage are NOT.")
        return False
    return True


def freshness_note(pattern: str) -> str:
    """One line describing what a local read is actually resting on."""
    newest, age, count = local_artifact_freshness(pattern)
    if count == 0:
        return f"local: NO FILES for {pattern}"
    if age is None:
        return f"local: {count} files, newest date UNKNOWN"
    return f"local: {count} files, newest {newest} ({age:.1f}d old)"
