"""Read a bounded window of one Syndicate fleet role's log, correctly.

Production is the local WSL fleet (`scripts/local_production.py`) since 2026-09-30.
Its roles write `<home>/logs/<service>.log`, rotated to `.log.1` .. `.log.5`; this
reads them, through `\\wsl.localhost` from Windows. It was `scripts/render_logs.py`
until 2026-11-17 (lane render-name-cleanup): it read the Render logs API until
2026-10-06 by default, and could until 2026-11-15, when the Render path was removed
(lane render-retirement, user: "render shouldnt be needed"). `render_logs.py` stays as
a shim because about fifty ledger entries and scheduled tasks call it by that name.

**A window you did not cover is the failure mode, so this tool always prints the
window it ACTUALLY covered next to the one you asked for.** A sample count does
not reveal truncation -- 99 samples looks like coverage until you notice they
span 1.2s of a 51s request (measured on Render's pager, 2026-08-14, `#434`).

    py -3 scripts/fleet_logs.py --text OVERVIEW_SPORT_BEGIN --start 2026-08-14T22:56:00Z
    py -3 scripts/fleet_logs.py --text CONTAINER_MEMORY --start ... --end ... --max-field memory_anon_mb
    py -3 scripts/fleet_logs.py --service live-odds-worker --text ODDS_ --start ... --tail 20
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# LOCAL BACKEND `[2026-10-02, lane local-logs-backend]`
# ---------------------------------------------------------------------------
# Render has been billing-suspended since 2026-09-30 and production runs on the
# local WSL fleet (`scripts/local_production.py`), whose roles write
# `<home>/logs/<service>.log` (rotated to `.log.1` .. `.log.5`). Every caller of
# `fetch_window` read NOTHING there -- the lines exist, just not on Render.
#
# THE SOURCE IS THE FLEET, AND IS SAID. `--render` and `SYNDICATE_LOG_SOURCE=render`
# were removed 2026-11-15 (lane render-retirement): asking for Render now FAILS rather
# than quietly reading the fleet. `--local` and `SYNDICATE_LOG_SOURCE=local|auto` are
# still accepted and read the fleet. Every result names its source.
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


def resolve_source(explicit: str | None = None) -> tuple[str, str]:
    """(source, why). Always `local`, the fleet's own logs.

    The Render logs API was this tool's other backend until 2026-11-15 (lane
    render-retirement). An explicit request for it -- `render` from a caller or
    `SYNDICATE_LOG_SOURCE=render` -- now EXITS, because silently answering from a
    different source than the one asked for is a wrong reading, not a fallback.
    """
    choice = (explicit or os.environ.get("SYNDICATE_LOG_SOURCE") or "").strip().lower()
    if choice == "render":
        raise SystemExit(
            "the Render logs API was retired 2026-11-15 (lane render-retirement); "
            "production is the local fleet -- drop --render / SYNDICATE_LOG_SOURCE=render"
        )
    if choice in ("local", "auto"):
        return "local", "explicit" if explicit else "SYNDICATE_LOG_SOURCE"
    return "local", "default: production runs on the local fleet"


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

# What the most recent `fetch_window` read and how: source, files, timestamp
# quality. The return shape stays (lines, pages) for existing callers.
LAST_FETCH: dict = {}


def fetch_window(
    *,
    service: str,
    text: str,
    start: str,
    end: str = "",
    source: str | None = None,
    exact_only: bool = False,
) -> tuple[list[tuple[str, str]], int]:
    """Every line matching `text` in [start, end] from the fleet's logs, oldest-first.

    Returns (lines, files_read). Approximate timestamps end in `~`; `LAST_FETCH` says
    what was read and how.
    """
    _, why = resolve_source(source)
    lines, info = fetch_local_window(service=service, text=text, start=start, end=end, exact_only=exact_only)
    LAST_FETCH.clear()
    LAST_FETCH.update(info, why=why)
    return lines, len(info["files"])


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
    parser.add_argument("--service", default="refresh-worker", choices=sorted(_LOCAL_SERVICES))
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
    parser.add_argument("--local", dest="source", action="store_const", const="local",
                        help="read the local fleet's log files -- the only source; kept so old commands still run")
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
    print(f"# SOURCE     local fleet logs {info['log_dir']} ({', '.join(info['files'])}) -- {info['why']}")
    print(f"# TIMES      {info['exact']} exact, {info['approximate']} APPROXIMATE (suffix ~, a lower bound), "
          f"{info['unstamped_skipped']} unstamped skipped, {info['approximate_dropped']} dropped by --exact-only")
    print(f"# requested  {args.start} .. {args.end or '(now)'}")
    unit = "file(s)"
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
