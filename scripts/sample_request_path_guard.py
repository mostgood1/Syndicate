"""Sample web's request-path-guard counters and turn them into a RATE, honestly.

WHY THIS EXISTS RATHER THAN A curl IN A LOOP. Two reasons, both of which have
already produced a wrong number in this repo.

**1. The counters are PER-PROCESS and web runs more than one gunicorn worker.**
`WEB_CONCURRENCY=2` at the time of writing. Consecutive reads land on whichever
worker serves them, so differencing two reads WITHOUT keying on `pid` subtracts
one worker's count from the other's. That does not produce a slightly-off rate;
it produces a fictional one, and it can be negative. Every delta here is
computed WITHIN a pid, and a count that DECREASES for a pid means that worker
restarted and its counter reset -- reported, never silently treated as zero
work.

**2. A per-minute rate off a handful of BURST events is not a rate.** Measured
2026-09-04: `mlb_cards_fetch_current_feed_live` arrives in bursts of exactly 32
(the whole 16-game slate, twice). A 7.4-minute window containing two bursts
reads as "8.7/min"; the SAME run at 11.9 minutes reads as 5.4/min. Nothing
changed but the denominator. So this tool reports the EVENT COUNT next to any
rate, and refuses to present a rate as trustworthy below `--min-events`
(default 5). `learnings.md`: a rate, not a count -- and state the denominator.

The secret stays out of argv: `ADMIN_TOKEN` comes from the gitignored `.env` via
the same loader `deploy_preflight` uses, so this can be permitted as exactly
`Bash(python scripts/sample_request_path_guard.py *)`.

    py -3 scripts/sample_request_path_guard.py --minutes 30
    py -3 scripts/sample_request_path_guard.py --minutes 45 --operation mlb_cards_fetch_current_feed_live
    py -3 scripts/sample_request_path_guard.py --minutes 20 --json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy_preflight import WEB_BASE_URL, _admin_token  # noqa: E402

EXIT_OK, EXIT_READER_FAILED = 0, 2

# Below this many distinct increase EVENTS, a per-minute figure is one number
# pretending to be a distribution. See the module docstring.
_DEFAULT_MIN_EVENTS = 5


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def read_counters(base_url: str, token: str) -> dict:
    """One sample, or a dict carrying `error`. Never raises -- a sampler that
    dies partway through leaves a window nobody can characterise."""
    url = base_url.rstrip("/") + "/api/ops/request-path-guard"
    request = urllib.request.Request(url, headers={"X-Admin-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        guard = (payload or {}).get("request_path_guard") or {}
        by_operation = guard.get("by_operation") if isinstance(guard.get("by_operation"), dict) else {}
        return {
            "at": _utc_now().isoformat(),
            "pid": guard.get("pid"),
            "warned": guard.get("warned"),
            "refused": guard.get("refused"),
            "by_operation": {k: (v or {}).get("warned", 0) for k, v in by_operation.items()},
            "refused_by_operation": {k: (v or {}).get("refused", 0) for k, v in by_operation.items()},
        }
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"at": _utc_now().isoformat(), "error": f"{type(exc).__name__}: {exc}"}


def _series(samples: list[dict], operation: str | None) -> dict[int, list[tuple[dt.datetime, int]]]:
    """Per-pid (time, count) series for one operation, or for the warned total."""
    out: dict[int, list[tuple[dt.datetime, int]]] = {}
    for sample in samples:
        if "error" in sample or sample.get("pid") is None:
            continue
        if operation:
            value = int((sample.get("by_operation") or {}).get(operation, 0))
        else:
            value = int(sample.get("warned") or 0)
        out.setdefault(int(sample["pid"]), []).append((dt.datetime.fromisoformat(sample["at"]), value))
    return out


def summarise(samples: list[dict], operation: str | None, min_events: int) -> dict:
    series = _series(samples, operation)
    per_pid, total_delta, events, restarts = [], 0, 0, []
    widest = 0.0
    for pid, points in sorted(series.items()):
        span = (points[-1][0] - points[0][0]).total_seconds() / 60.0
        widest = max(widest, span)
        reset = False
        for (_, before), (at_b, after) in zip(points, points[1:]):
            if after < before:
                # A restart, not negative work. Counting this as a delta would
                # subtract a whole worker's history from the total.
                reset = True
                restarts.append({"pid": pid, "at": at_b.isoformat()})
                continue
            if after > before:
                events += 1
        delta = points[-1][1] - points[0][1] if not reset else None
        if delta:
            total_delta += delta
        per_pid.append({
            "pid": pid,
            "samples": len(points),
            "span_minutes": round(span, 1),
            "first": points[0][1],
            "last": points[-1][1],
            "delta": delta,
            "restarted": reset,
        })
    rate = (total_delta / widest) if widest else None
    return {
        "operation": operation or "(all warnings)",
        "pids_observed": [p["pid"] for p in per_pid],
        "per_pid": per_pid,
        "total_delta": total_delta,
        "widest_span_minutes": round(widest, 1),
        "increase_events": events,
        "restarts": restarts,
        "rate_per_minute": round(rate, 2) if rate is not None else None,
        # The whole point: a rate is only quotable once enough distinct events
        # have accrued that the denominator is not doing all the work.
        "rate_is_quotable": events >= min_events,
        "min_events_required": min_events,
    }


def _print_report(summary: dict, samples: list[dict], requested_minutes: float) -> None:
    errors = [s for s in samples if "error" in s]
    print(f"# request-path-guard   operation={summary['operation']}")
    print(f"# requested  {requested_minutes:.0f} min   samples {len(samples)}   failed reads {len(errors)}")
    print(f"# READ       {summary['widest_span_minutes']} min actually spanned, pids seen {summary['pids_observed']}")
    print("#            Counters are PER-PROCESS. Every delta below is computed WITHIN a pid;")
    print("#            web runs more than one worker, so a cross-worker difference is fiction.")
    print("#")
    for row in summary["per_pid"]:
        note = "  <-- RESTARTED mid-window, delta withheld" if row["restarted"] else ""
        print(f"#   pid {row['pid']:<6} n={row['samples']:<3} span={row['span_minutes']:>5} min   "
              f"{row['first']} -> {row['last']}   delta={row['delta']}{note}")
    print("#")
    print(f"# TOTAL      +{summary['total_delta']} over {summary['widest_span_minutes']} min, "
          f"across {summary['increase_events']} increase event(s)")
    if summary["rate_is_quotable"]:
        print(f"# RATE       {summary['rate_per_minute']}/min   "
              f"({summary['increase_events']} events >= {summary['min_events_required']} required)")
    else:
        print(f"# RATE       NOT QUOTABLE -- only {summary['increase_events']} increase event(s), "
              f"{summary['min_events_required']} required.")
        print(f"#            The arithmetic gives {summary['rate_per_minute']}/min and it would be "
              "one number pretending")
        print("#            to be a distribution. Measured 2026-09-04: the same run read 8.7/min at")
        print("#            7.4 min and 5.4/min at 11.9 min, on two events. Report the COUNT:")
        print(f"#            +{summary['total_delta']} over {summary['widest_span_minutes']} min "
              f"in {summary['increase_events']} event(s).")
    if summary["restarts"]:
        print(f"# RESTARTS   {len(summary['restarts'])} worker restart(s) inside the window -- "
              "those pids' deltas are withheld, not zeroed.")
    if errors:
        print(f"# NOTE       {len(errors)} read(s) failed; the window is thinner than requested.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--minutes", type=float, default=20.0, help="how long to sample (default 20)")
    parser.add_argument("--interval", type=float, default=30.0, help="seconds between samples (default 30)")
    parser.add_argument("--operation", default="", help="one operation key; omit for all warnings")
    parser.add_argument("--min-events", type=int, default=_DEFAULT_MIN_EVENTS,
                        help=f"increase events required before a rate is quotable (default {_DEFAULT_MIN_EVENTS})")
    parser.add_argument("--base-url", default=WEB_BASE_URL)
    parser.add_argument("--out", default="", help="append raw samples as JSONL here")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    token = _admin_token()
    if not token:
        print("# ADMIN_TOKEN not set in the environment or .env -- this is a READER failure, not a null result.")
        return EXIT_READER_FAILED

    deadline = _utc_now() + dt.timedelta(minutes=args.minutes)
    samples: list[dict] = []
    handle = open(args.out, "a", encoding="utf-8") if args.out else None
    try:
        while True:
            sample = read_counters(args.base_url, token)
            samples.append(sample)
            if handle:
                handle.write(json.dumps(sample) + "\n")
                handle.flush()
            if _utc_now() >= deadline:
                break
            time.sleep(max(1.0, args.interval))
    except KeyboardInterrupt:
        print("# interrupted -- reporting the window actually covered, which is shorter than requested.")
    finally:
        if handle:
            handle.close()

    good = [s for s in samples if "error" not in s]
    if not good:
        print("# EVERY READ FAILED. This is a READER FAILURE, not a quiet service. Conclude nothing.")
        return EXIT_READER_FAILED

    summary = summarise(samples, args.operation or None, args.min_events)
    if args.json:
        print(json.dumps({"summary": summary, "samples": samples}, indent=2))
    else:
        _print_report(summary, samples, args.minutes)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
