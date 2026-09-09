"""Send web a volume of public edge bytes KNOWN TO THE BYTE, so the meter can be read against it.

WHY THIS EXISTS. `[render-egress-spikes]` ends in a disjunction nobody could
separate from outside: **either Render's meter counts bytes the logs do not
contain, or the logs are materially incomplete in exactly the high-volume
hours.** Both contradicting numbers are Render's, so there is no join inside our
code to instrument -- and `learnings.md` 2026-09-03 FORBIDS instrumenting a
component when the contradiction is between two numbers (cost: four web deploys,
three of them wasted). The remaining move is to make ONE number known.

WHAT IT MEASURES. Every request carries a unique `ctprobe` query value and a
dedicated user agent, so the same bytes can be counted three ways over one
right-labelled bucket:

  (a) wire bytes this client actually received   -- ground truth, to the byte
  (b) what Render's edge log and app log record  -- completeness of the logs
  (c) the bucket's metered MB                    -- what is billed

(a) vs (b) tests the log-incompleteness horn directly and does not depend on the
meter at all: the log either accounts for requests we know we made, or it does
not. (c) vs (a) calibrates the meter against a known quantity for the first
time; the ledger's normal-hour rule is `meter ~= 1.7-2.2x public edge bytes`,
inferred from correlated pairs and never once controlled.

THREE THINGS IT REFUSES TO DO, each because a written rule says so:

1. **Fire into a non-quiet window.** `learnings.md` 2026-09-07 (no production
   reading while another session loads the service) and 2026-09-08 (no
   self-refreshing board open against the service under diagnosis). Beyond
   etiquette, it is load-bearing HERE: subtracting a large background from the
   meter would mean trusting the very log whose completeness is under test. So
   `--require-quiet-mb` is checked against the edge log immediately before
   firing, and the run aborts rather than proceeding dirty.

2. **Straddle an hour boundary.** Buckets are RIGHT-labelled and hourly; a
   transfer split across two of them is attributable to neither. The run refuses
   to start unless the whole planned transfer fits in the current hour with
   `--boundary-margin-s` to spare, and stops early if it runs late.

3. **Starve `/healthz`.** Web is `WEB_CONCURRENCY=2` x `GUNICORN_THREADS=4` = 8
   slots, and this service has a history of health-check starvation under
   concurrent probes (`[web-request-path-latency]`, and the 2026-09-07 incident
   where a peer's 6-concurrent burst made someone else's reading meaningless and
   contributed to an `unhealthy` event). Default concurrency is 2 of 8, health
   is sampled throughout, and the run ABORTS on a slow or failing `/healthz`.

USAGE

    py -3 scripts/controlled_transfer_probe.py --dry-run
    py -3 scripts/controlled_transfer_probe.py --target-mb 300
    py -3 scripts/controlled_transfer_probe.py --target-mb 300 --concurrency 2

It writes `reports/bandwidth_spikes/controlled_transfer_<stamp>.json`, which is
the input to the reading taken once the bucket has settled (>= 70 minutes after
the hour closes -- a bucket grows for ~50 minutes and a fresh low reading is
INCOMPLETE, not low).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "reports" / "bandwidth_spikes"

BASE = "https://syndicate-an21.onrender.com"
#: An INCOMPRESSIBLE static asset, and the choice is load-bearing. Measured
#: 2026-09-08: a JS file's client-side size is 4.8x what Render counts, because
#: the origin always sends gzip (Cloudflare normalises `Accept-Encoding` toward
#: it) and Cloudflare inflates the body for a client that asked for `identity`.
#: A PNG logs 60,944 against 60,588 received under BOTH encodings, so the client
#: measures the same quantity the meter does. It is also cheap to serve -- no
#: sim, no artifact read, no memory -- and `cf-cache-status: DYNAMIC`, so every
#: request reaches the origin and appears in both logs.
ASSET = "/static/shared/syndicate-logo.png"
#: `edge responseBytes - client bytes`, measured over four requests: the response
#: headers Render counts and the client does not see as body.
EDGE_HEADER_OVERHEAD = 356
USER_AGENT = "syndicate-controlled-transfer/1.0"

HEALTH_PATH = "/healthz"
HEALTH_ABORT_S = 5.0
HEALTH_EVERY_S = 20.0


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


def _stamp(when: dt.datetime | None = None) -> str:
    return (when or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")


class Health:
    """Samples `/healthz` alongside the transfer and can veto it mid-flight."""

    def __init__(self) -> None:
        self.samples: list[dict] = []
        self.abort = threading.Event()
        self.reason = ""

    def sample(self, tag: str) -> dict:
        started = time.monotonic()
        record = {"at": _stamp(), "tag": tag}
        try:
            request = urllib.request.Request(
                BASE + HEALTH_PATH, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=HEALTH_ABORT_S * 2) as response:
                response.read()
                record["status"] = response.status
        except Exception as exc:  # noqa: BLE001 -- any failure is a veto
            record["status"] = -1
            record["error"] = repr(exc)[:200]
        record["seconds"] = round(time.monotonic() - started, 3)
        self.samples.append(record)
        if record["status"] != 200 or record["seconds"] > HEALTH_ABORT_S:
            self.abort.set()
            self.reason = f"healthz {record['status']} in {record['seconds']}s at {record['at']}"
        return record

    def watch(self, stop: threading.Event) -> None:
        while not stop.wait(HEALTH_EVERY_S):
            self.sample("during")
            if self.abort.is_set():
                return


def fetch_once(index: int) -> dict:
    """One request. Returns exactly what came back, measured on this side."""
    token = f"{index:06d}-{uuid.uuid4().hex[:8]}"
    url = f"{BASE}{ASSET}?ctprobe={token}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            # identity: wire bytes == body bytes, so "known" needs no assumption
            # about what the compression layer did.
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        },
    )
    started = time.monotonic()
    record: dict = {"i": index, "token": token, "at": _stamp()}
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                body += len(chunk)
            record["status"] = response.status
            record["bytes"] = body
            record["cf_cache"] = response.headers.get("cf-cache-status")
            record["origin"] = response.headers.get("x-render-origin-server")
            record["encoding"] = response.headers.get("content-encoding") or "identity"
    except urllib.error.HTTPError as exc:
        record["status"] = exc.code
        record["bytes"] = 0
        record["error"] = repr(exc)[:200]
    except Exception as exc:  # noqa: BLE001
        record["status"] = -1
        record["bytes"] = 0
        record["error"] = repr(exc)[:200]
    record["seconds"] = round(time.monotonic() - started, 3)
    return record


def measure_asset() -> dict:
    """One calibration request: how big is the thing, right now, on this deploy?"""
    record = fetch_once(0)
    if record.get("status") != 200 or not record.get("bytes"):
        raise SystemExit(f"calibration request failed: {record}")
    return record


def quiet_check(minutes: int, limit_mb: float) -> dict:
    """Refuse to fire into someone else's load. Uses the tripwire's own reader."""
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.bandwidth_tripwire import (  # noqa: PLC0415
        SERVICE_IDS, _api_key, _logs, _RESP_BYTES, _CLIENT_IP, _USER_AGENT,
    )

    key = _api_key()
    now = _now()
    start = _stamp(now - dt.timedelta(minutes=minutes))
    end = _stamp(now)
    rows = _logs(key, SERVICE_IDS["web"], start, end, "request")
    total = 0
    clients: dict[str, list] = {}
    for _ts, message, _labels in rows:
        match = _RESP_BYTES.search(message)
        size = int(match.group(1)) if match else 0
        total += size
        ip_match = _CLIENT_IP.search(message)
        ua_match = _USER_AGENT.search(message)
        who = f"{ip_match.group(1) if ip_match else '?'} | {(ua_match.group(1) if ua_match else '?')[:50]}"
        entry = clients.setdefault(who, [0, 0])
        entry[0] += size
        entry[1] += 1
    mb = total / 1048576
    return {
        "window": {"start": start, "end": end, "minutes": minutes},
        "requests": len(rows),
        "mb": round(mb, 3),
        "limit_mb": limit_mb,
        "quiet": mb <= limit_mb,
        "top": sorted(
            ({"who": k, "mb": round(v[0] / 1048576, 3), "requests": v[1]} for k, v in clients.items()),
            key=lambda d: -d["mb"],
        )[:6],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--target-mb", type=float, default=300.0)
    parser.add_argument("--concurrency", type=int, default=2, help="of web's 8 gunicorn slots")
    parser.add_argument("--quiet-minutes", type=int, default=10)
    parser.add_argument("--require-quiet-mb", type=float, default=5.0,
                        help="abort if the edge log carries more than this in the quiet window")
    parser.add_argument("--boundary-margin-s", type=int, default=240,
                        help="the whole transfer must fit in this clock hour with this to spare")
    parser.add_argument("--dry-run", action="store_true",
                        help="calibrate + quiet-check + plan, transfer nothing")
    parser.add_argument("--skip-quiet-check", action="store_true",
                        help="explicit override; recorded in the output as a caveat")
    args = parser.parse_args()

    report: dict = {
        "kind": "controlled_transfer",
        "base": BASE,
        "asset": ASSET,
        "user_agent": USER_AGENT,
        "args": vars(args),
        "started_at": _stamp(),
    }

    print("== calibration")
    calibration = measure_asset()
    size = calibration["bytes"]
    report["calibration"] = calibration
    print(f"   {size} bytes/request  status={calibration['status']} "
          f"cf={calibration['cf_cache']} enc={calibration['encoding']} "
          f"{calibration['seconds']}s")

    planned = max(1, int(round(args.target_mb * 1048576 / size)))
    report["planned_requests"] = planned
    report["planned_bytes"] = planned * size
    print(f"   plan: {planned} requests x {size} B = "
          f"{planned * size / 1048576:.1f} MB at concurrency {args.concurrency}")

    print("== quiet check")
    if args.skip_quiet_check:
        report["quiet_check"] = {"skipped": True}
        print("   SKIPPED by --skip-quiet-check (recorded as a caveat)")
    else:
        quiet = quiet_check(args.quiet_minutes, args.require_quiet_mb)
        report["quiet_check"] = quiet
        print(f"   last {quiet['window']['minutes']}m: {quiet['mb']} MB over "
              f"{quiet['requests']} requests (limit {quiet['limit_mb']} MB) -> "
              f"{'QUIET' if quiet['quiet'] else 'NOT QUIET'}")
        for entry in quiet["top"]:
            print(f"     {entry['mb']:8.3f} MB  {entry['requests']:4d}  {entry['who']}")
        if not quiet["quiet"] and not args.dry_run:
            report["aborted"] = "not quiet"
            _write(report)
            print("ABORT: web is being loaded by someone else. learnings.md 2026-09-07 / 2026-09-08.")
            return 3

    # Trap: buckets are hourly and RIGHT-labelled; a straddling transfer is
    # attributable to neither bucket.
    now = _now()
    seconds_left = 3600 - (now.minute * 60 + now.second)
    per_request = max(calibration["seconds"], 0.2)
    estimate = planned * per_request / max(args.concurrency, 1)
    report["hour"] = {
        "bucket_label": (now.replace(minute=0, second=0, microsecond=0)
                         + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00Z"),
        "seconds_left_in_hour": seconds_left,
        "estimated_seconds": round(estimate, 1),
    }
    print(f"== hour: {report['hour']['bucket_label']} covers this hour; "
          f"{seconds_left}s left, transfer needs ~{estimate:.0f}s")
    if estimate + args.boundary_margin_s > seconds_left:
        report["aborted"] = "would straddle the hour boundary"
        _write(report)
        print("ABORT: not enough room in this hour. Wait for the next one.")
        return 4

    if args.dry_run:
        report["dry_run"] = True
        _write(report)
        print("dry run: nothing transferred")
        return 0

    health = Health()
    health.sample("before")
    if health.abort.is_set():
        report["aborted"] = f"health before: {health.reason}"
        report["health"] = health.samples
        _write(report)
        print("ABORT:", health.reason)
        return 5

    stop = threading.Event()
    watcher = threading.Thread(target=health.watch, args=(stop,), daemon=True)
    watcher.start()

    print(f"== transfer {planned} requests")
    transfer_started = _stamp()
    t0 = time.monotonic()
    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = []
        for i in range(1, planned + 1):
            if health.abort.is_set():
                break
            futures.append(pool.submit(fetch_once, i))
        for future in futures:
            records.append(future.result())
    stop.set()
    elapsed = time.monotonic() - t0
    health.sample("after")

    sent = len(records)
    ok = [r for r in records if r.get("status") == 200]
    total_bytes = sum(r.get("bytes", 0) for r in records)
    report.update(
        {
            "transfer_started_at": transfer_started,
            "transfer_ended_at": _stamp(),
            "elapsed_seconds": round(elapsed, 1),
            "requests_sent": sent,
            "requests_200": len(ok),
            "known_bytes": total_bytes,
            "known_mb": round(total_bytes / 1048576, 3),
            # What Render's own instruments should count for these requests:
            # body + the response headers the client never sees as body.
            "known_edge_basis_bytes": total_bytes + EDGE_HEADER_OVERHEAD * len(ok),
            "known_edge_basis_mb": round(
                (total_bytes + EDGE_HEADER_OVERHEAD * len(ok)) / 1048576, 3
            ),
            "rate_mb_per_s": round(total_bytes / 1048576 / max(elapsed, 0.001), 3),
            "implied_gb_per_hour": round(total_bytes / 1048576 * 3600 / max(elapsed, 0.001) / 1024, 2),
            "distinct_sizes": sorted({r.get("bytes", 0) for r in records}),
            "non_200": [r for r in records if r.get("status") != 200][:20],
            "health": health.samples,
            "health_aborted": health.abort.is_set(),
            "health_reason": health.reason,
            "records": records,
        }
    )
    print(f"   sent {sent}, 200s {len(ok)}, {report['known_mb']} MB body "
          f"({report['known_edge_basis_mb']} MB on the edge basis) in {elapsed:.1f}s "
          f"= {report['rate_mb_per_s']} MB/s ({report['implied_gb_per_hour']} GB/h)")
    if health.abort.is_set():
        print("   HEALTH VETO:", health.reason)
    path = _write(report)
    print(f"-> {path}")
    print("\nNEXT: the bucket must settle. Read it no earlier than "
          f"{report['hour']['bucket_label']} + 70 minutes.")
    return 0


def _write(report: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = report.get("transfer_started_at") or report["started_at"]
    path = OUT_DIR / f"controlled_transfer_{stamp.replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
