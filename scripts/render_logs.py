"""Read a bounded window of one Syndicate service's Render logs, correctly.

WHY THIS EXISTS RATHER THAN A curl OR A THROWAWAY SNIPPET. `#434`.

**The Render logs API returns the NEWEST `limit` lines inside the window, and
presents them oldest-first.** `deploy_preflight.newest_log`'s docstring already
says so, and three sessions in a row have written a pager that ignores it:

    # WRONG -- re-reads the same tail and terminates
    while True:
        page = get(startTime=cursor, ...)
        cursor = newest_timestamp_in(page)

On 2026-08-14 that shape reported `PEAK 606.2 MB ... samples 99` for a
51-second overview pass while having covered **1.2 seconds** of it. The number
was plausible, carried a sample count, and was wrong by 200MB. Paging must go
BACKWARD: lower `endTime` to the oldest line seen until the window is exhausted.

**A window you did not cover is the failure mode, so this tool always prints the
window it ACTUALLY covered next to the one you asked for.** A sample count does
not reveal truncation -- 99 samples looks like coverage until you notice they
span 1.2s of a 51s request.

Also here because the secret must stay out of argv: `RENDER_API_KEY` is read
from the gitignored `.env` by the same loader `deploy_preflight` uses, so this
can be permitted as exactly `Bash(python scripts/render_logs.py *)` rather than
opening up `curl`.

    py -3 scripts/render_logs.py --text OVERVIEW_SPORT_BEGIN --start 2026-08-14T22:56:00Z
    py -3 scripts/render_logs.py --text CONTAINER_MEMORY --start ... --end ... --max-field memory_anon_mb
    py -3 scripts/render_logs.py --service live-odds-worker --text ODDS_ --start ... --tail 20
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy_preflight import OWNER_ID, SERVICE_IDS, _api_key, _get  # noqa: E402

# ---------------------------------------------------------------------------
# LOCAL BACKEND `[2026-10-02, lane local-logs-backend]`
# ---------------------------------------------------------------------------
# Render has been billing-suspended since 2026-09-30 and production runs on the
# local WSL fleet (`scripts/local_production.py`), whose roles write
# `<home>/logs/<service>.log` (rotated to `.log.1` .. `.log.5`). Every caller of
# `fetch_window` read NOTHING there -- the lines exist, just not on Render.
#
# THE SOURCE IS CHOSEN, AND SAID: `--local` / `--render`, else
# `SYNDICATE_LOG_SOURCE=local|render|auto`, else LOCAL (since 2026-10-06; it was
# AUTO, which called the Render API first). AUTO: local when there is no Render
# key (a fleet checkout) or Render reports the web service suspended (cached 10
# min). Every result names its source.
#
# TIMESTAMPS ARE THE HARD PART, AND ARE NEVER FAKED SILENTLY. Render stamped
# every line; the supervisor wrote raw stdout until `SYNDICATE_LOCAL_LOG_TIMESTAMPS`
# (measured 2026-10-02: 1.5-2.6% of worker lines carried any time of their own).
# A line's time is, in order: the supervisor's `<ISO>Z ` prefix (EXACT); web's
# access-log stamp (EXACT); else the nearest EARLIER exact line or `==== start`
# marker (APPROXIMATE -- a lower bound). Approximate lines are counted and
# reported, suffixed `~`; `--exact-only` drops them.

_LOCAL_SERVICES = ("web", "refresh-worker", "live-odds-worker")
_PREFIX = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) (.*)$")
_START = re.compile(r"^==== start (\S+)")
_APACHE_IN = re.compile(r"\[(\d\d/[A-Z][a-z]{2}/20\d\d:\d\d:\d\d:\d\d [+-]\d{4})\]")
_SUSPENDED_CACHE = Path(tempfile.gettempdir()) / "syndicate_render_suspended.json"
_SUSPENDED_TTL = 600


def _to_utc(text: str) -> dt.datetime | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        if re.match(r"^\d\d/[A-Z][a-z]{2}/", raw):
            value = dt.datetime.strptime(raw, "%d/%b/%Y:%H:%M:%S %z")
        else:
            value = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def local_log_dir() -> Path | None:
    """`SYNDICATE_LOCAL_LOG_DIR`, else `<SYNDICATE_LOCAL_HOME>/logs`, else the
    fleet's default home; from Windows, the same directory through
    `\\\\wsl.localhost\\<distro>\\home\\<user>\\syndicate-prod\\logs`."""
    for key in ("SYNDICATE_LOCAL_LOG_DIR",):
        if os.environ.get(key):
            return Path(os.environ[key]).expanduser()
    if os.environ.get("SYNDICATE_LOCAL_HOME"):
        return Path(os.environ["SYNDICATE_LOCAL_HOME"]).expanduser() / "logs"
    if os.name != "nt":
        candidate = Path.home() / "syndicate-prod" / "logs"
        return candidate if candidate.is_dir() else None
    distro = os.environ.get("SYNDICATE_WSL_DISTRO", "Ubuntu-24.04")
    homes = Path(rf"\\wsl.localhost\{distro}\home")
    try:
        for user_home in sorted(homes.iterdir()):
            candidate = user_home / "syndicate-prod" / "logs"
            if candidate.is_dir():
                return candidate
    except OSError:
        return None
    return None


def render_suspended(key: str) -> bool | None:
    """Whether Render reports the web service suspended; cached; None if unknown."""
    try:
        cached = json.loads(_SUSPENDED_CACHE.read_text(encoding="utf-8"))
        if time.time() - float(cached.get("at", 0)) < _SUSPENDED_TTL:
            return cached.get("suspended")
    except (OSError, ValueError):
        pass
    try:
        payload = _get(f"https://api.render.com/v1/services/{SERVICE_IDS['web']}", key)
        value = str((payload or {}).get("suspended") or "").lower() == "suspended"
    except Exception:  # noqa: BLE001 -- unknown, not "not suspended"
        return None
    try:
        _SUSPENDED_CACHE.write_text(json.dumps({"at": time.time(), "suspended": value}), encoding="utf-8")
    except OSError:
        pass
    return value


def resolve_source(explicit: str | None = None) -> tuple[str, str]:
    """(source, why). `local` or `render`.

    UNSET MEANS LOCAL, with no Render API call `[2026-10-06, lane scripts-fleet-default]`.
    Until then unset meant AUTO, which asked the Render API whether Render was
    suspended on every cold cache -- a network round trip to a billing-suspended
    platform before reading a file on this machine. AUTO is still there, by name:
    `SYNDICATE_LOG_SOURCE=auto` (or `explicit="auto"`).
    """
    choice = (explicit or os.environ.get("SYNDICATE_LOG_SOURCE") or "").strip().lower()
    if choice in ("local", "render"):
        return choice, "explicit" if explicit else "SYNDICATE_LOG_SOURCE"
    if choice != "auto":
        return "local", "default: production runs on the local fleet (--render for the Render API)"
    try:
        key = _api_key()
    except (Exception, SystemExit):  # noqa: BLE001 -- _api_key EXITS when absent
        key = ""
    if not key:
        return "local", "auto: no RENDER_API_KEY here"
    suspended = render_suspended(key)
    if suspended:
        return "local", "auto: Render reports the web service suspended"
    if suspended is None and local_log_dir() is not None:
        return "local", "auto: Render state unknown, local fleet logs present"
    return "render", "auto: Render is serving"


def _local_files(log_dir: Path, service: str) -> list[Path]:
    rotated = sorted(log_dir.glob(f"{service}.log.[0-9]*"),
                     key=lambda p: int(p.suffix.lstrip(".") or 0), reverse=True)
    current = log_dir / f"{service}.log"
    return [*rotated, *([current] if current.is_file() else [])]


def fetch_local_window(
    *,
    service: str,
    text: str,
    start: str,
    end: str = "",
    log_dir: Path | None = None,
    exact_only: bool = False,
) -> tuple[list[tuple[str, str]], dict]:
    """Matching lines in [start, end] from the fleet's own logs, oldest-first.

    Returns (lines, info). A line is `(timestamp, message)` with the timestamp
    suffixed `~` when it is APPROXIMATE (see the block comment above)."""
    if service not in _LOCAL_SERVICES:
        raise SystemExit(f"--local reads {_LOCAL_SERVICES}; {service!r} has no local log")
    log_dir = log_dir or local_log_dir()
    if log_dir is None or not log_dir.is_dir():
        raise SystemExit("no local fleet log directory found (set SYNDICATE_LOCAL_LOG_DIR)")
    lo = _to_utc(start)
    hi = _to_utc(end) if end else None
    needle = text.lower()
    out: list[tuple[str, str]] = []
    info = {"source": "local", "log_dir": str(log_dir), "files": [], "exact": 0, "approximate": 0,
            "unstamped_skipped": 0, "approximate_dropped": 0}
    for path in _local_files(log_dir, service):
        info["files"].append(path.name)
        last: dt.datetime | None = None
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.rstrip("\n")
                marker = _START.match(line)
                if marker:
                    last = _to_utc(marker.group(1)) or last
                    continue
                stamp, message, exact = None, line, False
                prefixed = _PREFIX.match(line)
                if prefixed:
                    stamp, message, exact = _to_utc(prefixed.group(1)), prefixed.group(2), True
                else:
                    # ONLY the access-log stamp is an emission time. An ISO time
                    # INSIDE a message is usually a DATA time (`generated_at
                    # 2026-09-30T22:54Z` printed hours later), so it is never
                    # trusted -- a confident wrong time is worse than an honest
                    # approximate one.
                    found = _APACHE_IN.search(line)
                    if found:
                        stamp, exact = _to_utc(found.group(1)), True
                if stamp is not None and exact:
                    last = stamp
                if needle not in message.lower():
                    continue
                if stamp is None:
                    stamp = last
                if stamp is None:
                    info["unstamped_skipped"] += 1
                    continue
                if (lo and stamp < lo) or (hi and stamp > hi):
                    continue
                if not exact and exact_only:
                    info["approximate_dropped"] += 1
                    continue
                info["exact" if exact else "approximate"] += 1
                out.append((_iso(stamp) + ("" if exact else "~"), message))
    return out, info

# One page is the API's cap. Paging backward is what makes the window whole;
# raising this would not.
_PAGE = 100
# A backstop, not a budget. 200 pages of 100 lines is far more than any window
# worth reading interactively, and it stops a pathological loop rather than
# bounding normal use.
_MAX_PAGES = 200


# What the most recent `fetch_window` read and how: source, files, timestamp
# quality. The return shape stays (lines, pages) for existing callers.
LAST_FETCH: dict = {}


def fetch_window(
    *,
    service: str,
    text: str,
    start: str,
    end: str = "",
    max_pages: int = _MAX_PAGES,
    source: str | None = None,
    exact_only: bool = False,
) -> tuple[list[tuple[str, str]], int]:
    """Every line matching `text` in [start, end], oldest-first, de-duplicated.

    Returns (lines, pages_fetched). Pages BACKWARD -- see the module docstring.
    With the LOCAL source (`resolve_source`), `pages` is the number of log files
    read and approximate timestamps end in `~`; `LAST_FETCH` says which ran.
    """
    chosen, why = resolve_source(source)
    if chosen == "local":
        lines, info = fetch_local_window(service=service, text=text, start=start, end=end, exact_only=exact_only)
        LAST_FETCH.clear()
        LAST_FETCH.update(info, why=why)
        return lines, len(info["files"])
    LAST_FETCH.clear()
    LAST_FETCH.update(source="render", why=why)
    return _fetch_render_window(service=service, text=text, start=start, end=end, max_pages=max_pages)


def _fetch_render_window(
    *,
    service: str,
    text: str,
    start: str,
    end: str = "",
    max_pages: int = _MAX_PAGES,
) -> tuple[list[tuple[str, str]], int]:
    service_id = SERVICE_IDS[service]
    key = _api_key()
    seen: dict[str, str] = {}
    cursor_end = end
    pages = 0

    for _ in range(max_pages):
        params = {
            "ownerId": OWNER_ID,
            "resource": service_id,
            "limit": str(_PAGE),
            "text": text,
            "startTime": start,
        }
        if cursor_end:
            params["endTime"] = cursor_end
        payload = _get("https://api.render.com/v1/logs?" + urllib.parse.urlencode(params), key)
        pages += 1
        rows = (payload or {}).get("logs") or []

        oldest = cursor_end
        fresh = 0
        for row in rows:
            stamp = str(row.get("timestamp") or "")
            message = str(row.get("message") or "")
            # The API's filter is a case-insensitive SUBSTRING match and
            # over-matches longer tokens, so re-check -- same reason
            # `deploy_preflight.newest_log` does.
            if text.lower() not in message.lower():
                continue
            if stamp not in seen:
                seen[stamp] = message
                fresh += 1
            if not oldest or stamp < oldest:
                oldest = stamp

        # `fresh == 0` means this page held nothing new; `oldest <= start` means
        # we have walked back to the requested edge. Either way the window is
        # done. `oldest == cursor_end` guards the degenerate no-progress case.
        if fresh == 0 or not oldest or oldest <= start or oldest == cursor_end:
            break
        cursor_end = oldest

    return sorted(seen.items()), pages


def _max_numeric_field(lines: list[tuple[str, str]], field: str) -> tuple[str, float] | None:
    pattern = re.compile(rf'"{re.escape(field)}":\s*(-?[0-9.]+)')
    best: tuple[str, float] | None = None
    for stamp, message in lines:
        match = pattern.search(message)
        if not match:
            continue
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        if best is None or value > best[1]:
            best = (stamp, value)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="refresh-worker", choices=sorted(SERVICE_IDS))
    parser.add_argument("--text", required=True, help="substring to match (case-insensitive)")
    parser.add_argument("--start", required=True, help="ISO8601, e.g. 2026-08-14T22:56:00Z")
    parser.add_argument("--end", default="", help="ISO8601; omit for 'up to now'")
    parser.add_argument("--tail", type=int, default=0, help="print only the last N matches")
    parser.add_argument(
        "--max-field",
        default="",
        help="numeric JSON field to report the maximum of, e.g. memory_anon_mb",
    )
    parser.add_argument("--width", type=int, default=200, help="truncate each message to N chars")
    parser.add_argument("--json", action="store_true")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--local", dest="source", action="store_const", const="local",
                       help="read the local fleet's log files (the default; see resolve_source)")
    where.add_argument("--render", dest="source", action="store_const", const="render",
                       help="read the Render logs API")
    parser.add_argument("--exact-only", action="store_true",
                        help="local: drop lines whose time is only approximate (carried forward)")
    args = parser.parse_args()

    lines, pages = fetch_window(
        service=args.service, text=args.text, start=args.start, end=args.end,
        source=args.source, exact_only=args.exact_only,
    )
    info = dict(LAST_FETCH)

    if args.json:
        payload = {
            "service": args.service,
            "source": info,
            "text": args.text,
            "requested": {"start": args.start, "end": args.end or None},
            "covered": {
                "start": lines[0][0] if lines else None,
                "end": lines[-1][0] if lines else None,
            },
            "matches": len(lines),
            "pages": pages,
            "lines": [{"timestamp": t, "message": m} for t, m in lines],
        }
        if args.max_field:
            peak = _max_numeric_field(lines, args.max_field)
            payload["max_field"] = (
                {"field": args.max_field, "value": peak[1], "timestamp": peak[0]} if peak else None
            )
        print(json.dumps(payload, indent=2))
        return 0

    # THE COVERED WINDOW IS NOT DECORATION -- it is the check that this read is
    # a measurement rather than a sliver. Printed even when it equals the
    # request, because the case that matters is the one nobody looks at.
    print(f"# {args.service}  text={args.text!r}")
    if info.get("source") == "local":
        print(f"# SOURCE     local fleet logs {info['log_dir']} ({', '.join(info['files'])}) -- {info['why']}")
        print(f"# TIMES      {info['exact']} exact, {info['approximate']} APPROXIMATE (suffix ~, a lower bound), "
              f"{info['unstamped_skipped']} unstamped skipped, {info['approximate_dropped']} dropped by --exact-only")
    else:
        print(f"# SOURCE     Render logs API -- {info.get('why')}")
    print(f"# requested  {args.start} .. {args.end or '(now)'}")
    unit = "file(s)" if info.get("source") == "local" else "pages"
    if lines:
        print(f"# COVERED    {lines[0][0]} .. {lines[-1][0]}   ({len(lines)} matches, {pages} {unit})")
    else:
        print(f"# COVERED    nothing matched   ({pages} {unit} read)")
        return 0

    if args.max_field:
        peak = _max_numeric_field(lines, args.max_field)
        if peak is None:
            print(f"# max {args.max_field}: FIELD NOT PRESENT in any matched line")
        else:
            print(f"# max {args.max_field}: {peak[1]} at {peak[0]}")

    shown = lines[-args.tail :] if args.tail > 0 else lines
    if args.tail > 0 and len(lines) > args.tail:
        print(f"# showing last {args.tail} of {len(lines)}")
    for stamp, message in shown:
        print(f"{stamp}  {message.strip()[: args.width]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
