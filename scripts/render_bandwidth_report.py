"""Attribute Render bandwidth to services, hours, paths and callers.

WHY THIS EXISTS RATHER THAN A DASHBOARD SCREENSHOT. On 2026-09-05 the
workspace stood at **24.4 GB of its 25 GB included bandwidth on day 5 of the
month**, and the dashboard's only breakdown was "HTTP Responses 19.34 GB /
Service-Initiated 5.06 GB", which names no service, no route and no caller.
Four things had to be measured before anything could be fixed, and every one
of them is a trap:

1. **WHICH SERVICE.** `/v1/metrics/bandwidth` per resource. 09-01..09-05: web
   19.50 GB, live-odds-worker 3.88 GB, refresh-worker 1.07 GB, total 24.45 GB
   against the dashboard's 24.4 -- so the metric IS the billed number, and web
   is 80% of it.

2. **THE BUCKETS ARE RIGHT-LABELLED.** A value stamped `18:00:00Z` covers
   17:00-18:00. Confirmed twice by counting request-log lines in each window
   against `/v1/metrics/http-requests` (1,366 observed vs 1,338; 131 vs 115).
   Reading them as left-labelled attributes a 4 GB hour to the wrong hour, and
   the wrong hour had 3 deploys in it, which is a very convincing wrong story.

3. **RENDER'S `type=request` LOG IS NOT THE TRAFFIC.** It carries only what
   came through the PUBLIC edge. The 4,050 MB hour of 2026-09-04 17:00-18:00Z
   shows **2.6 MB** there. Everything else was service-to-service over the
   internal hostname, which appears ONLY in gunicorn's own access lines
   (`type=app`, client IP `10.x`). Attributing from the request log alone
   exonerates the actual cause.

4. **ONE HOUR THAT AGREES IS NOT EVIDENCE. ALWAYS RUN THE CONTROL.** That same
   hour: 699 MB of outbound responses + 3,461 MB of INBOUND artifact publishes
   = 4,160 MB against a 4,050 MB bucket. A 97% match on a 4 GB figure, and it
   is a COINCIDENCE. The control hour 2026-09-05 04:00-05:00Z carried
   **5,243 MB of the identical transport and metered 33.9 MB** -- 150x apart.
   **Internal service-to-service traffic is not billed**, exactly as
   `render.yaml`'s `SYNDICATE_WEB_PUBLISH_URL` comment has said since the
   1.62 TB incident. This tool prints "OUT + IN vs metered" so the next reader
   sees BOTH hours' shape, not one.

5. **RENDER'S EDGE ALREADY GZIPS.** The same request in the two logs:
   `export?pattern=*book_quotes/2026-08-26.jsonl` is 198.8 MB in gunicorn and
   4.2 MB at the edge (n=2 in both). So gunicorn's byte count is the ORIGIN
   body and the edge's is the WIRE body, and they differ by up to 47x on JSON.
   Never compare one against the other as though they measured the same thing.

WHAT THIS TOOL HAS NOT MANAGED TO EXPLAIN, as of 2026-09-05: web is 19.57 GB of
the workspace's 24.55 GB (all 16 resources measured; the 9 legacy sport
services are at ~0), and that figure survives the elimination of internal
traffic, public responses AND deploys. The remaining candidate class is web's
own OUTBOUND connections, which no HTTP log records. `/v1/metrics/bandwidth`
has no egress/ingress split and no sub-hourly resolution (60/300/900s all
return hourly), so the next step is instrumenting the service, not another
API read.

    py -3 scripts/render_bandwidth_report.py --start 2026-09-01 --end 2026-09-05
    py -3 scripts/render_bandwidth_report.py --hour 2026-09-04T17:00:00Z
    py -3 scripts/render_bandwidth_report.py --hour 2026-09-04T17:00:00Z --publishes

`RENDER_API_KEY` is read from the gitignored `.env` by the same loader
`deploy_preflight` uses, so this can be permitted as exactly
`Bash(python scripts/render_bandwidth_report.py *)`.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy_preflight import FLEET, OWNER_ID, SERVICE_IDS, _api_key, _get  # noqa: E402

# `SERVICE_IDS` also carries `syndicate` as an ALIAS for `web`, and iterating it
# blind double-counts the fleet -- this tool reported 44.05 GB against a real
# 24.45 GB on its first run for exactly that reason, which is the shape of
# error a total is least likely to catch. `FLEET` is the three real services
# and `deploy_preflight` already keeps it for this purpose.
_SERVICES = {name: SERVICE_IDS[name] for name in FLEET}

_API = "https://api.render.com/v1"

# One page is the API's cap. Paging BACKWARD (lowering endTime to the oldest
# line seen) is what makes a window whole -- the API returns the NEWEST `limit`
# lines inside the window, so a forward pager re-reads the same tail forever.
# Same rule, same reason, as `render_logs.py`.
_PAGE = 100
_MAX_PAGES = 900

# gunicorn's combined access line. The trailing integer is the RESPONSE BODY
# size, which is the only per-route byte count that exists for internal
# traffic -- Render's `responseBytes` field is edge-only.
_ACCESS = re.compile(
    r'^(\d+\.\d+\.\d+\.\d+) - - \[[^\]]+\] "(\w+) ([^"]*?) HTTP/[\d.]+" (\d{3}) (\d+|-) "[^"]*" "([^"]*)"'
)
_PUBLISH_BYTES = re.compile(r"\bbytes=(\d+)")
_PUBLISH_PATH = re.compile(r"\bpath=(\S+)")


def _metric(name: str, service_id: str, start: str, end: str, resolution: int = 3600):
    url = f"{_API}/metrics/{name}?" + urllib.parse.urlencode(
        {"resource": service_id, "startTime": start, "endTime": end, "resolutionSeconds": resolution}
    )
    return _get(url, _api_key())


def _logs(service_id: str, start: str, end: str, *, log_type: str, text: str | None = None):
    """Every log line in [start, end], paged backward. Returns (rows, oldest)."""
    key = _api_key()
    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    cursor = end
    oldest = end
    for _ in range(_MAX_PAGES):
        params = {
            "ownerId": OWNER_ID,
            "resource": service_id,
            "limit": str(_PAGE),
            "startTime": start,
            "endTime": cursor,
            "type": log_type,
        }
        if text:
            params["text"] = text
        payload = _get(f"{_API}/logs?" + urllib.parse.urlencode(params, doseq=True), key)
        entries = payload.get("logs") or []
        if not entries:
            break
        fresh = 0
        for entry in entries:
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            fresh += 1
            rows.append((entry["timestamp"], entry.get("message") or ""))
        span_start = min(e["timestamp"] for e in entries)
        oldest = min(oldest, span_start)
        if fresh == 0 or span_start <= start:
            break
        cursor = span_start
    rows.sort()
    return rows, oldest


def _normalise(path: str) -> str:
    """Collapse a URL to the shape that identifies the COST, not the request.

    `?path=` and `?pattern=` are the two forms that carry real payload weight,
    and a per-date/per-file breakdown of them is a histogram of the slate
    rather than an answer about where the bytes go.
    """
    base = path.split("?")[0]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    if "pattern" in query:
        return f"{base}?pattern={query['pattern'][0][:60]}"
    if "path" in query:
        return f"{base}?path={'/'.join(query['path'][0].split('/')[:3])}/..."
    return base


def _table(title: str, buckets: dict[str, list[int]], top: int) -> None:
    print(f"\n  --- top by {title} ---")
    for key, (total, count) in sorted(buckets.items(), key=lambda kv: -kv[1][0])[:top]:
        print(
            f"    {total / 1024 / 1024:9.1f} MB  n={count:6d}  "
            f"avg={total / max(count, 1) / 1024:9.1f} KB  {key[:100]}"
        )


def report_period(start: str, end: str) -> None:
    totals: dict[str, float] = {}
    per_day: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    hourly: dict[str, dict[str, float]] = defaultdict(dict)
    for name, service_id in _SERVICES.items():
        for series in _metric("bandwidth", service_id, start, end):
            for point in series["values"]:
                value = float(point["value"])
                totals[name] = totals.get(name, 0.0) + value
                per_day[name][point["timestamp"][:10]] += value
                hourly[name][point["timestamp"]] = value

    print(f"=== bandwidth {start} .. {end} (buckets are RIGHT-labelled) ===")
    grand = 0.0
    for name, value in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"  {name:20s} {value / 1024:8.2f} GB")
        grand += value
    print(f"  {'ALL':20s} {grand / 1024:8.2f} GB   (25 GB included / month)")

    days = sorted({day for service in per_day.values() for day in service})
    print("\n  per day (GB)")
    print("    day        " + "".join(f"{n:>20s}" for n in _SERVICES))
    for day in days:
        print(f"    {day} " + "".join(f"{per_day[n][day] / 1024:20.3f}" for n in _SERVICES))

    print("\n  worst 12 hours, any service (MB)")
    worst = sorted(
        ((ts, name, mb) for name, series in hourly.items() for ts, mb in series.items()),
        key=lambda row: -row[2],
    )[:12]
    for ts, name, mb in worst:
        print(f"    {ts}  {name:20s} {mb:9.1f}   (covers the hour ENDING here)")


def report_hour(bucket: str, *, top: int, publishes: bool) -> None:
    """Attribute one RIGHT-labelled bucket, i.e. the hour ENDING at `bucket`."""
    end = bucket
    start = bucket[:11] + f"{int(bucket[11:13]) - 1:02d}" + bucket[13:] if bucket[11:13] != "00" else None
    if start is None:
        raise SystemExit("Pass a bucket after 01:00Z, or widen this by hand -- a 00:00Z bucket spans a day boundary.")

    web = _SERVICES["web"]
    rows, oldest = _logs(web, start, end, log_type="app")
    by_path: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_ip: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_agent: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    total = 0
    served = 0
    for _ts, message in rows:
        match = _ACCESS.match(message.strip())
        if not match:
            continue
        ip, _method, path, _status, size, agent = match.groups()
        value = int(size) if size.isdigit() else 0
        total += value
        served += 1
        for bucket_map, key in ((by_path, _normalise(path)), (by_ip, ip), (by_agent, agent)):
            bucket_map[key][0] += value
            bucket_map[key][1] += 1

    metered = 0.0
    for series in _metric("bandwidth", web, start, end):
        for point in series["values"]:
            if point["timestamp"] == bucket:
                metered = float(point["value"])

    print(f"=== web, hour {start} .. {end} ===")
    print(f"  Render metered (BOTH directions): {metered:9.1f} MB")
    print(f"  OUTBOUND responses (gunicorn):    {total / 1024 / 1024:9.1f} MB over {served} requests")
    print(f"  log window actually covered: {oldest} .. {end}")
    _table("PATH", by_path, top)
    _table("CLIENT IP (10.x = Render's internal network, never the public edge)", by_ip, top)
    _table("USER-AGENT", by_agent, top)

    if not publishes:
        print("\n  (pass --publishes for the INBOUND half; it is usually the larger one)")
        return

    publish_rows, publish_oldest = _logs(web, start, end, log_type="app", text="[ops.publish]")
    by_family: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    inbound = 0
    counted = 0
    for _ts, message in publish_rows:
        size_match = _PUBLISH_BYTES.search(message)
        if not size_match:
            continue
        value = int(size_match.group(1))
        inbound += value
        counted += 1
        path_match = _PUBLISH_PATH.search(message)
        family = "/".join(path_match.group(1).split("/")[:3]) if path_match else "?"
        by_family[family][0] += value
        by_family[family][1] += 1
    print(f"\n  INBOUND publishes: {inbound / 1024 / 1024:9.1f} MB over {counted} uploads")
    print(f"  log window actually covered: {publish_oldest} .. {end}")
    _table("PUBLISHED FAMILY (inbound)", by_family, top)
    print(
        f"\n  OUT + IN = {(total + inbound) / 1024 / 1024:9.1f} MB   "
        f"vs metered {metered:9.1f} MB   "
        f"({(total + inbound) / 1024 / 1024 / metered * 100 if metered else 0:.0f}% accounted)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", help="ISO date or timestamp, e.g. 2026-09-01")
    parser.add_argument("--end", help="ISO date or timestamp, e.g. 2026-09-05")
    parser.add_argument("--hour", help="Attribute one RIGHT-labelled bucket, e.g. 2026-09-04T18:00:00Z")
    parser.add_argument("--publishes", action="store_true", help="Also sum the INBOUND publish half (slower)")
    parser.add_argument("--top", type=int, default=14)
    args = parser.parse_args()

    if args.hour:
        report_hour(args.hour, top=args.top, publishes=args.publishes)
        return 0

    if not (args.start and args.end):
        parser.error("pass --hour, or both --start and --end")
    start = args.start if "T" in args.start else f"{args.start}T00:00:00Z"
    end = args.end if "T" in args.end else f"{args.end}T23:59:59Z"
    report_period(start, end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
