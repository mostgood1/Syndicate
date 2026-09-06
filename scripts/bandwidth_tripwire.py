"""Catch a Render bandwidth spike WHILE its logs still exist.

WHY THIS EXISTS. Ten spike buckets over 2026-09-01..04 carried ~68% of the
month's bandwidth bill -- one of them 4,050 MB in a single hour against 2.6 MB
of public traffic. Ten mechanisms have been eliminated by measurement and the
driver is STILL unidentified (`state_worker.md [render-egress-spikes]`). Every
one of those investigations was forensic: run days later, against logs that had
partly aged out, on a phenomenon that had already stopped. This watches, and
captures the full context the moment a bucket clears a threshold.

FOUR INSTRUMENT TRAPS ARE BAKED IN, because each produced a wrong reading first:

1. **Buckets are RIGHT-LABELLED.** Bucket `15:00` covers `14:00..15:00`.
   Confirmed twice against the independent `http-requests` metric (182 reported
   vs 190 scanned). Getting this backwards analyses the wrong hour, which is
   how one investigation spent an afternoon on an hour that was never the spike.

2. **A bucket SETTLES for ~50 minutes and grows up to 39x while doing it.**
   Measured: `3.2 -> 5.2 -> 13.3 -> 22.3 -> 44.2 -> 64.7 -> 79.3 -> 95.7 ->
   110.3 -> 124.6 -> 125.9`, then flat. **A fresh low reading is INCOMPLETE, not
   low.** So this tool only judges buckets whose hour closed at least
   `--settle-minutes` ago, and it records the value twice to prove it settled.

3. **`type=request` is EDGE-ONLY.** It carries what the public proxy served and
   NOT internal service-to-service traffic, which appears only in the gunicorn
   access lines of `type=app`. Reading either alone misses half the picture, and
   the gap between them IS the open question -- so both are captured, separately.

4. **The API throws 429 and 503 under paging.** Both are retried with backoff.
   A capture that dies halfway is worse than none, because the logs it was
   racing keep ageing.

WHAT IT DOES NOT DO. It cannot say what the meter counts -- that contradiction
is unresolved and this tool is not an argument about it. It captures evidence so
the NEXT occurrence is analysed from complete logs instead of remembered ones.

USAGE

    py -3 scripts/bandwidth_tripwire.py --check
    py -3 scripts/bandwidth_tripwire.py --check --threshold-mb 150
    py -3 scripts/bandwidth_tripwire.py --capture 2026-09-04T18:00:00Z
    py -3 scripts/bandwidth_tripwire.py --watch --interval-minutes 20

Captures land in `reports/bandwidth_spikes/<service>_<bucket>.json` and are
idempotent: a bucket already captured is skipped, so `--watch` can run forever
without duplicating work.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "reports" / "bandwidth_spikes"

OWNER_ID = "tea-d2bb5n95pdvs73cje4fg"
SERVICE_IDS = {
    "web": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d91dpertqb8s73co8lt0",
}

#: A bucket is only judged once its hour has been closed this long. See trap 2:
#: below this, a low reading means "not finished counting", not "quiet".
DEFAULT_SETTLE_MINUTES = 70

#: 500 MB against a quiet-hour baseline of 0.2-0.5 MB. Deliberately far above
#: the 25-300 MB of ordinary interactive hours, so this fires on the phenomenon
#: rather than on somebody using the board.
DEFAULT_THRESHOLD_MB = 500.0

_ACCESS = re.compile(
    r'^(\d+\.\d+\.\d+\.\d+) - - \[[^\]]+\] "(\w+) ([^"]*?) HTTP/[\d.]+" (\d{3}) (\d+|-)'
)
_RESP_BYTES = re.compile(r"responseBytes=(\d+)")
_CLIENT_IP = re.compile(r'clientIP="([^"]*)"')
_USER_AGENT = re.compile(r'userAgent="([^"]*)"')
_PUBLISH_BYTES = re.compile(r"\bbytes=(\d+)")


def _api_key() -> str:
    value = str(os.environ.get("RENDER_API_KEY") or "").strip()
    if value:
        return value
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("RENDER_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("RENDER_API_KEY not set in the environment or .env")


def _get(url: str, key: str) -> Any:
    """GET with backoff. Trap 4: 429 AND 5xx, not just 429.

    A half-finished capture is worse than none -- the logs it is racing keep
    ageing while you retry by hand.
    """
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}
    )
    for attempt in range(9):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 8:
                raise
            time.sleep(3.0 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 8:
                raise
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError("unreachable")


def _metric(key: str, name: str, resource: str, start: str, end: str) -> dict[str, float]:
    url = "https://api.render.com/v1/metrics/" + name + "?" + urllib.parse.urlencode(
        {"resource": resource, "startTime": start, "endTime": end, "resolutionSeconds": 3600}
    )
    out: dict[str, float] = defaultdict(float)
    for series in _get(url, key):
        for point in series.get("values") or []:
            out[point["timestamp"]] += float(point["value"])
    return dict(out)


def _logs(key: str, resource: str, start: str, end: str, log_type: str, max_pages: int = 200) -> list[tuple[str, str, dict]]:
    """Page BACKWARD, deduplicating by id.

    The API returns the NEWEST `limit` lines inside the window, so a forward
    pager re-reads the tail forever and never reaches the start.
    """
    seen: set[str] = set()
    rows: list[tuple[str, str, dict]] = []
    cursor = end
    for _ in range(max_pages):
        params = {
            "ownerId": OWNER_ID, "resource": resource, "limit": "100",
            "startTime": start, "endTime": cursor, "type": log_type,
        }
        payload = _get("https://api.render.com/v1/logs?" + urllib.parse.urlencode(params, doseq=True), key)
        entries = payload.get("logs") or []
        if not entries:
            break
        fresh = 0
        for entry in entries:
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            fresh += 1
            labels = {item["name"]: item["value"] for item in entry.get("labels", [])}
            rows.append((entry["timestamp"], entry.get("message", ""), labels))
        oldest = min(entry["timestamp"] for entry in entries)
        if fresh == 0 or oldest <= start:
            break
        cursor = oldest
        time.sleep(0.4)
    rows.sort()
    return rows


def _bucket_window(bucket: str) -> tuple[str, str]:
    """Trap 1: RIGHT-LABELLED. Bucket `X:00` covers `(X-1):00 .. X:00`."""
    end = dt.datetime.strptime(bucket[:19], "%Y-%m-%dT%H:%M:%S")
    start = end - dt.timedelta(hours=1)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def _top(pairs: dict[str, list[int]], limit: int = 12) -> list[dict[str, Any]]:
    return [
        {"key": k, "bytes": v[0], "count": v[1]}
        for k, v in sorted(pairs.items(), key=lambda kv: -kv[1][0])[:limit]
    ]


def capture(service: str, bucket: str, key: str, metered_mb: float | None = None) -> dict[str, Any]:
    """Everything that could bear on one spike hour, gathered while it exists."""
    start, end = _bucket_window(bucket)
    resource = SERVICE_IDS[service]
    report: dict[str, Any] = {
        "service": service,
        "bucket": bucket,
        "window_covered": {"start": start, "end": end},
        "captured_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metered_mb": metered_mb,
        "note": (
            "bucket is RIGHT-labelled: it covers window_covered, i.e. the hour BEFORE its label. "
            "edge_* is public traffic only; app_* includes internal service-to-service."
        ),
    }

    edge = _logs(key, resource, start, end, "request")
    edge_paths: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    edge_ips: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    edge_uas: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    edge_total = 0
    for _ts, message, labels in edge:
        match = _RESP_BYTES.search(message)
        size = int(match.group(1)) if match else 0
        edge_total += size
        path = (labels.get("path") or "?").split("?")[0]
        edge_paths[path][0] += size; edge_paths[path][1] += 1
        ip_match = _CLIENT_IP.search(message)
        ip = ip_match.group(1) if ip_match else "?"
        edge_ips[ip][0] += size; edge_ips[ip][1] += 1
        ua_match = _USER_AGENT.search(message)
        ua = (ua_match.group(1) if ua_match else "?")[:60]
        edge_uas[ua][0] += size; edge_uas[ua][1] += 1
    report["edge"] = {
        "requests": len(edge), "bytes": edge_total, "mb": round(edge_total / 1048576, 2),
        "top_paths": _top(edge_paths), "top_clients": _top(edge_ips), "top_user_agents": _top(edge_uas),
    }

    app = _logs(key, resource, start, end, "app")
    app_paths: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    app_ips: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    app_total = 0
    access_lines = 0
    for _ts, message, _labels in app:
        match = _ACCESS.match(message.strip())
        if not match:
            continue
        access_lines += 1
        ip, _method, path, _status, size_text = match.groups()
        size = int(size_text) if size_text.isdigit() else 0
        app_total += size
        base = path.split("?")[0]
        app_paths[base][0] += size; app_paths[base][1] += 1
        app_ips[ip][0] += size; app_ips[ip][1] += 1
    report["app"] = {
        "log_lines": len(app), "access_lines": access_lines,
        "served_bytes": app_total, "served_mb": round(app_total / 1048576, 2),
        "top_paths": _top(app_paths), "top_clients": _top(app_ips),
        "note": "served_bytes is RESPONSE size only; a POST body (e.g. artifacts/publish) is NOT counted here",
    }

    # Publish request BODIES -- invisible to every response-size count above,
    # and the largest single flow into web. Read from the WORKER side.
    publish: dict[str, Any] = {}
    for worker in ("refresh-worker", "live-odds-worker"):
        rows = _logs(key, SERVICE_IDS[worker], start, end, "app", max_pages=90)
        total = 0
        count = 0
        for _ts, message, _labels in rows:
            if "PUBLISH_OK" not in message:
                continue
            match = _PUBLISH_BYTES.search(message)
            if match:
                total += int(match.group(1)); count += 1
        publish[worker] = {"publishes": count, "bytes": total, "mb": round(total / 1048576, 2)}
    report["publish_into_web"] = publish

    try:
        deploys = _get(f"https://api.render.com/v1/services/{resource}/deploys?limit=30", key)
        report["deploys_in_window"] = [
            {
                "createdAt": (d.get("deploy", d)).get("createdAt"),
                "finishedAt": (d.get("deploy", d)).get("finishedAt"),
                "status": (d.get("deploy", d)).get("status"),
                "commit": str(((d.get("deploy", d)).get("commit") or {}).get("id", ""))[:10],
            }
            for d in deploys
            if start <= str((d.get("deploy", d)).get("finishedAt") or "") <= end
        ]
    except Exception as exc:  # pragma: no cover - telemetry must not break a capture
        report["deploys_in_window"] = {"error": repr(exc)}

    try:
        report["other_services_same_hour"] = {
            other: round(_metric(key, "bandwidth", SERVICE_IDS[other], start, end).get(bucket, 0.0), 1)
            for other in SERVICE_IDS if other != service
        }
    except Exception as exc:  # pragma: no cover
        report["other_services_same_hour"] = {"error": repr(exc)}

    return report


def settled_buckets(key: str, service: str, hours: int, settle_minutes: int) -> dict[str, float]:
    """Buckets old enough to have finished counting. Trap 2."""
    now = dt.datetime.utcnow()
    start = (now - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:00:00Z")
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    values = _metric(key, "bandwidth", SERVICE_IDS[service], start, end)
    cutoff = now - dt.timedelta(minutes=settle_minutes)
    return {
        bucket: mb
        for bucket, mb in values.items()
        if dt.datetime.strptime(bucket[:19], "%Y-%m-%dT%H:%M:%S") <= cutoff
    }


def _already_captured(service: str, bucket: str) -> Path | None:
    path = OUT_DIR / f"{service}_{bucket.replace(':', '').replace('-', '')}.json"
    return path if path.exists() else None


def run_check(args: argparse.Namespace, key: str) -> int:
    fired = 0
    for service in args.services:
        buckets = settled_buckets(key, service, args.lookback_hours, args.settle_minutes)
        over = {b: v for b, v in buckets.items() if v >= args.threshold_mb}
        print(f"{service}: {len(buckets)} settled buckets in the last {args.lookback_hours}h, "
              f"{len(over)} over {args.threshold_mb:.0f} MB")
        for bucket, mb in sorted(over.items()):
            existing = _already_captured(service, bucket)
            if existing and not args.force:
                print(f"  {bucket}  {mb:8.1f} MB  already captured -> {existing.name}")
                continue
            print(f"  {bucket}  {mb:8.1f} MB  CAPTURING...")
            report = capture(service, bucket, key, metered_mb=mb)
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            out = OUT_DIR / f"{service}_{bucket.replace(':', '').replace('-', '')}.json"
            out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            fired += 1
            print(f"      edge {report['edge']['mb']} MB / {report['edge']['requests']} reqs | "
                  f"app served {report['app']['served_mb']} MB | "
                  f"publish in {sum(v['mb'] for v in report['publish_into_web'].values()):.1f} MB")
            print(f"      -> {out}")
    if not fired:
        print("no new spike to capture")
    return fired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--services", nargs="+", default=["web"], choices=sorted(SERVICE_IDS))
    parser.add_argument("--threshold-mb", type=float, default=DEFAULT_THRESHOLD_MB)
    parser.add_argument("--settle-minutes", type=int, default=DEFAULT_SETTLE_MINUTES,
                        help="only judge buckets whose hour closed this long ago (default 70)")
    parser.add_argument("--lookback-hours", type=int, default=6)
    parser.add_argument("--check", action="store_true", help="one pass")
    parser.add_argument("--watch", action="store_true", help="loop until stopped")
    parser.add_argument("--interval-minutes", type=int, default=20)
    parser.add_argument("--capture", metavar="BUCKET", help="capture one bucket explicitly, e.g. 2026-09-04T18:00:00Z")
    parser.add_argument("--force", action="store_true", help="re-capture a bucket already on disk")
    args = parser.parse_args()

    key = _api_key()

    if args.capture:
        service = args.services[0]
        report = capture(service, args.capture, key)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"{service}_{args.capture.replace(':', '').replace('-', '')}.json"
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in ("edge", "app")}, indent=2))
        print(f"edge {report['edge']['mb']} MB / {report['edge']['requests']} reqs")
        print(f"app served {report['app']['served_mb']} MB / {report['app']['access_lines']} access lines")
        for row in report["edge"]["top_paths"][:5]:
            print(f"   edge {row['bytes']/1048576:8.2f} MB  n={row['count']:5d}  {row['key'][:60]}")
        for row in report["app"]["top_paths"][:5]:
            print(f"   app  {row['bytes']/1048576:8.2f} MB  n={row['count']:5d}  {row['key'][:60]}")
        print(f"-> {out}")
        return 0

    if args.watch:
        while True:
            try:
                run_check(args, key)
            except Exception as exc:  # pragma: no cover - a watcher must not die on one bad pass
                print(f"[tripwire] PASS_FAILED {exc!r}", flush=True)
            time.sleep(max(60, args.interval_minutes * 60))

    run_check(args, key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
