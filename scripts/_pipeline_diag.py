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
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]

WEB_BASE = os.environ.get("SYNDICATE_DIAG_BASE_URL", "https://syndicate-an21.onrender.com")
RENDER_API = "https://api.render.com/v1"

SERVICES = {
    "web": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d91dpertqb8s73co8lt0",
}

SPORTS = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")


def _load_dotenv() -> dict[str, str]:
    """Read .env without a dependency. Values may be quoted."""
    out: dict[str, str] = {}
    path = REPO_ROOT / ".env"
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


_ENV = _load_dotenv()


def secret(name: str) -> str:
    return os.environ.get(name) or _ENV.get(name) or ""


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
        token = secret("ADMIN_TOKEN")
        if not token:
            return None, None, "ADMIN_TOKEN not set"
        headers["X-Admin-Token"] = token
    return http_json(f"{WEB_BASE}{path}", headers=headers, timeout=timeout)


def render_json(path: str, *, timeout: int = 60) -> tuple[Any, int | None, str]:
    key = secret("RENDER_API_KEY")
    if not key:
        return None, None, "RENDER_API_KEY not set"
    return http_json(f"{RENDER_API}{path}", headers={"Authorization": f"Bearer {key}"}, timeout=timeout)


def render_owner_id() -> str:
    payload, _, _ = render_json("/owners?limit=1")
    if isinstance(payload, list) and payload:
        return str((payload[0].get("owner") or {}).get("id") or "")
    return ""


RENDER_LOG_LIMIT_MAX = 1000
"""Measured 2026-08-09: `limit=1000` returns 1000 rows, `limit=1500` returns
HTTP 400 with an EMPTY BODY. Same trap as the env-vars endpoint refusing
`limit` > 100. Silently fatal for a diagnostic, because an over-limit request
yields zero logs, which every downstream stage then reports as "the loop may
not be running" -- a tool defect wearing the costume of a production defect.
Clamped here so no caller can reproduce it.
"""


def fetch_logs(
    service_id: str, *, limit: int = 1000, owner_id: str | None = None
) -> tuple[list[dict[str, Any]], str]:
    """Returns (logs, error). An EMPTY LIST WITH NO ERROR means the service
    genuinely emitted nothing; an empty list WITH an error means we failed to
    ask. Callers must distinguish these -- conflating them is how a broken
    query becomes a false production finding.
    """
    owner = owner_id or render_owner_id()
    if not owner:
        return [], "could not resolve Render ownerId"
    capped = max(1, min(int(limit), RENDER_LOG_LIMIT_MAX))
    payload, status, error = render_json(
        f"/logs?ownerId={owner}&resource={service_id}&limit={capped}", timeout=90
    )
    if isinstance(payload, dict):
        return list(payload.get("logs") or []), ""
    return [], error or f"log fetch failed (http {status})"


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


def service_commits() -> dict[str, str]:
    """Live commit per service, read in one pass.

    Read this BEFORE any measurement. Two services on different commits can
    answer the same question differently and both look authoritative.

    Uses `/deploys`, NOT `/services/<id>` -- the service object carries no
    commit at all (verified 2026-08-09: `serviceDetails` has plan, disk, env,
    region and no deploy info). The first version of this function read a
    field that does not exist and returned "?" for all three services, which
    is exactly the silent-blindness the whole check exists to prevent: a
    guard that cannot see is worse than no guard, because it reports.
    """
    out: dict[str, str] = {}
    for name, service_id in SERVICES.items():
        payload, _, error = render_json(f"/services/{service_id}/deploys?limit=5")
        rows = payload if isinstance(payload, list) else []
        commit = ""
        for row in rows:
            deploy = row.get("deploy", row) if isinstance(row, dict) else {}
            if str(deploy.get("status") or "").lower() == "live":
                commit = str((deploy.get("commit") or {}).get("id") or "")[:8]
                break
        out[name] = commit or (f"?({error})" if error else "?")
    return out


def oom_events(service_id: str, *, limit: int = 20) -> list[tuple[str, str]]:
    """(timestamp, kind) for restarts/OOMs.

    Read `details.reason.oomKilled` -- the event TYPE alone says
    `server_failed` for both a controlled restart and an OOM kill, and
    calling one the other cost a full evening once.
    """
    payload, _, _ = render_json(f"/services/{service_id}/events?limit={limit}")
    rows = payload if isinstance(payload, list) else (payload or {}).get("events") or []
    out: list[tuple[str, str]] = []
    for row in rows:
        event = row.get("event", row) if isinstance(row, dict) else {}
        details = event.get("details") or {}
        reason = details.get("reason") or {}
        kind = str(event.get("type") or "")
        if reason.get("oomKilled"):
            limit_str = (reason.get("oomKilled") or {}).get("memoryLimit", "?")
            kind = f"OOM KILLED ({limit_str})"
        elif reason.get("unhealthy"):
            kind = f"unhealthy: {reason.get('unhealthy')}"
        elif reason.get("triggeredByUser"):
            kind = f"{kind} (user-triggered)"
        out.append((str(event.get("timestamp") or "")[:19], kind))
    return out


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
