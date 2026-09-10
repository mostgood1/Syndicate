"""Catch a Render bandwidth spike WHILE its logs still exist.

WHY THIS EXISTS. Ten spike buckets over 2026-09-01..04 carried ~68% of the
month's bandwidth bill -- one of them 4,050 MB in a single hour against 2.6 MB
of public traffic. Ten mechanisms have been eliminated by measurement and the
driver is STILL unidentified (`state_worker.md [render-egress-spikes]`). Every
one of those investigations was forensic: run days later, against logs that had
partly aged out, on a phenomenon that had already stopped. This watches, and
captures the full context the moment a bucket clears a threshold.

FOUR INSTRUMENT TRAPS ARE BAKED IN, because each produced a wrong reading first:

1. **A BANDWIDTH bucket is labelled by its hour's START.** Bucket `15:00`
   covers `15:00..16:00`. This said the opposite until 2026-09-10, and that was
   true of a DIFFERENT metric: `http-requests` IS end-labelled (arm 1's 2,596
   requests sit in its `01:00Z`), and that check was applied to bandwidth. A
   same-instant read at 15:13:07Z filed the hour in flight under `16:00Z` in
   `http-requests` and `15:00Z` in `bandwidth`. A lag scan over 180 poll
   intervals put metered increments 1-4 min behind served bytes, not 60.
   Getting this backwards analyses the wrong hour: every capture before the fix
   paired a metered hour with the logs of the hour before it. See
   `.syndicate/findings_2026-09-10_spike_crossing_and_labelling.md`.

2. **A bucket keeps growing for ~60 minutes after its label.** That is its
   own hour filling in, 1-4 min behind real time. It was recorded as "settling
   after the hour closes". Measured: `3.2 -> 5.2 -> 13.3 -> 22.3 -> 44.2 ->
   64.7 -> 79.3 -> 95.7 -> 110.3 -> 124.6 -> 125.9`, then flat. **A fresh low
   reading is INCOMPLETE, not low.** So this tool only judges buckets whose
   LABEL is at least `--settle-minutes` old. At 70 that is ~6-10 min after the
   hour ends; watcher polls on 2026-09-10 reached 99-100% at minute 61-62.

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
    """Trap 1: a BANDWIDTH bucket `X:00` covers `X:00 .. (X+1):00`.

    It was `(X-1):00 .. X:00` until 2026-09-10, which is true of the
    `http-requests` metric and FALSE for `bandwidth`. Every capture before
    then paired a metered hour with the previous hour's logs.
    """
    start = dt.datetime.strptime(bucket[:19], "%Y-%m-%dT%H:%M:%S")
    end = start + dt.timedelta(hours=1)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def _served_display(app: dict) -> str:
    """`None` reads as a glitch; an unreadable instrument must SAY it is unreadable.

    The JSON already refuses (`served_mb` is null when `instrument_blind`), but
    both print paths interpolated that null straight into the line, so a dead
    emitter rendered as the literal `app served None MB` -- which a reader
    skims as noise rather than as the refusal it is.
    """
    if app.get("instrument_blind"):
        return "UNREADABLE (access-log emitter off)"
    return f"{app['served_mb']} MB"


#: Every public request reaches gunicorn and is logged there, so an edge request
#: with no access line within this long is a GAP IN THE EMITTER (or an app-log
#: page budget that ran out), not a quiet stretch.
EMITTER_GAP_MINUTES = 10


def _emitter_gap(edge_ts: list[str], access_ts: list[str]) -> str | None:
    """Did the access-log emitter die or come back INSIDE this window?

    `instrument_blind` only catches an emitter that is off for the WHOLE hour.
    Moving the window to label..label+1h put two known transitions inside one:
    the emitter died at 2026-09-08T23:45:58Z (bucket `23:00Z` now holds 46 min
    of lines and 14 of none) and came back at ~2026-09-09T14:38Z. A partial
    served total reads as a SMALL one, which is the permissive default this
    tool already refuses for a dead hour. Zero access lines is left to the
    blind check.
    """
    if not access_ts or not edge_ts:
        return None
    parse = lambda s: dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")  # noqa: E731
    first, last = min(access_ts), max(access_ts)
    margin = dt.timedelta(minutes=EMITTER_GAP_MINUTES)
    before = sum(1 for t in edge_ts if parse(t) < parse(first) - margin)
    after = sum(1 for t in edge_ts if parse(t) > parse(last) + margin)
    parts = []
    if before:
        parts.append(f"{before} edge requests before the first access line ({first[:19]}Z)")
    if after:
        parts.append(f"{after} edge requests after the last access line ({last[:19]}Z)")
    if not parts:
        return None
    return ("access-log emitter gap inside the window: " + "; ".join(parts)
            + " -- served_mb is a PARTIAL total, do not divide by it")


def _prior_numbers(old: dict[str, Any]) -> dict[str, Any]:
    """What a capture said before it was re-derived on the corrected window.

    Kept, not discarded: ledger entries quote these numbers, and they remain
    true -- of the hour BEFORE the bucket's label.
    """
    edge = old.get("edge") or {}
    app = old.get("app") or {}
    publish = old.get("publish_into_web") or {}
    return {
        "captured_at": old.get("captured_at"),
        "window_covered": old.get("window_covered"),
        "metered_mb": old.get("metered_mb"),
        "edge_mb": edge.get("mb"),
        "edge_requests": edge.get("requests"),
        "app_served_mb": app.get("served_mb"),
        "app_access_lines": app.get("access_lines"),
        "app_instrument_blind": app.get("instrument_blind"),
        "publish_into_web_mb": round(sum(float((v or {}).get("mb") or 0) for v in publish.values()), 2)
        if isinstance(publish, dict) else None,
    }


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
            "bucket is labelled by its hour's START: window_covered is label..label+1h "
            "(changed 2026-09-10; captures before then read the hour BEFORE the label -- see "
            "`rederived.prior` where present). edge_* is public traffic only; app_* includes "
            "internal service-to-service."
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
    access_ts: list[str] = []
    for ts, message, _labels in app:
        match = _ACCESS.match(message.strip())
        if not match:
            continue
        access_lines += 1
        access_ts.append(ts)
        ip, _method, path, _status, size_text = match.groups()
        size = int(size_text) if size_text.isdigit() else 0
        app_total += size
        base = path.split("?")[0]
        app_paths[base][0] += size; app_paths[base][1] += 1
        app_ips[ip][0] += size; app_ips[ip][1] += 1
    # A DEAD EMITTER MUST NOT RENDER AS A SMALL NUMBER. web stopped emitting
    # gunicorn access lines at 2026-09-08T23:45:58Z and served_mb has been a
    # structural 0.0 ever since -- while `metered / app-served` is the ratio the
    # whole `[render-egress-spikes]` finding rests on (11.25, 2.85, 3.05, 16.84,
    # 9.32). Dividing by this silently would manufacture an infinite gap out of a
    # broken instrument. Zero access lines against a NON-EMPTY edge log is the
    # discriminator: it separates "nothing was served" (edge empty too, a real
    # quiet hour) from "nobody wrote it down".
    app_blind = access_lines == 0 and report["edge"]["requests"] > 0
    report["app"] = {
        "log_lines": len(app), "access_lines": access_lines,
        "served_bytes": None if app_blind else app_total,
        "served_mb": None if app_blind else round(app_total / 1048576, 2),
        "top_paths": _top(app_paths), "top_clients": _top(app_ips),
        "instrument_blind": app_blind,
        "note": "served_bytes is RESPONSE size only; a POST body (e.g. artifacts/publish) is NOT counted here",
    }
    gap = None if app_blind else _emitter_gap([ts for ts, _m, _l in edge], access_ts)
    report["app"]["instrument_partial"] = gap is not None
    if gap:
        report["app"]["partial_reason"] = gap
    if app_blind:
        report["app"]["blind_reason"] = (
            "0 gunicorn access lines while the edge log carried "
            + str(report["edge"]["requests"]) + " requests -- the access-log EMITTER is off, "
            "so served_mb is UNKNOWN, not zero. Do not compute metered/app-served from this "
            "bucket. See .syndicate/findings_2026-09-09_web_access_log_dead.md"
        )

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
                  f"app served {_served_display(report['app'])} | "
                  f"publish in {sum(v['mb'] for v in report['publish_into_web'].values()):.1f} MB")
            print(f"      -> {out}")
    if not fired:
        print("no new spike to capture")
    return fired


_CAPTURE_NAME = re.compile(r"^(?P<service>[a-z-]+)_\d{8}T\d{6}Z\.json$")


def rederive_all(services: list[str], key: str) -> int:
    """Re-capture every capture on disk on the corrected window (2026-09-10).

    Idempotent: a capture already on the new window is skipped. What each file
    said before is kept under `rederived.prior`. `metered_mb` is re-read, which
    also fills the captures that recorded it as null.
    """
    done = 0
    for service in services:
        for path in sorted(OUT_DIR.glob(f"{service}_*.json")):
            named = _CAPTURE_NAME.match(path.name)
            if not named or named.group("service") != service:
                continue
            old = json.loads(path.read_text(encoding="utf-8"))
            bucket = old.get("bucket")
            if not bucket:
                continue
            start, end = _bucket_window(bucket)
            if (old.get("window_covered") or {}).get("start") == start:
                print(f"  {bucket}  already on the corrected window -- skipped", flush=True)
                continue
            metered = _metric(key, "bandwidth", SERVICE_IDS[service], start, end).get(bucket)
            report = capture(service, bucket, key,
                             metered_mb=metered if metered is not None else old.get("metered_mb"))
            report["rederived"] = {
                "at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "reason": ("window corrected to label..label+1h -- a BANDWIDTH bucket is labelled by "
                           "its hour's START. See .syndicate/findings_2026-09-10_spike_crossing_and_labelling.md"),
                "prior": _prior_numbers(old),
            }
            path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            done += 1
            prior = report["rederived"]["prior"]
            app = report["app"]
            flag = " BLIND" if app.get("instrument_blind") else (" PARTIAL" if app.get("instrument_partial") else "")
            print(f"  {bucket}  metered {report['metered_mb']}  edge {prior['edge_mb']} -> "
                  f"{report['edge']['mb']} MB ({prior['edge_requests']} -> {report['edge']['requests']} reqs)  "
                  f"served {prior['app_served_mb']} -> {app['served_mb']}{flag}", flush=True)
    print(f"re-derived {done} capture(s)")
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--services", nargs="+", default=["web"], choices=sorted(SERVICE_IDS))
    parser.add_argument("--threshold-mb", type=float, default=DEFAULT_THRESHOLD_MB)
    parser.add_argument("--settle-minutes", type=int, default=DEFAULT_SETTLE_MINUTES,
                        help="only judge buckets whose LABEL is at least this old (default 70)")
    parser.add_argument("--lookback-hours", type=int, default=6)
    parser.add_argument("--check", action="store_true", help="one pass")
    parser.add_argument("--watch", action="store_true", help="loop until stopped")
    parser.add_argument("--interval-minutes", type=int, default=20)
    parser.add_argument("--capture", metavar="BUCKET", help="capture one bucket explicitly, e.g. 2026-09-04T18:00:00Z")
    parser.add_argument("--force", action="store_true", help="re-capture a bucket already on disk")
    parser.add_argument("--rederive", action="store_true",
                        help="re-capture every capture on disk on the corrected window, keeping the prior numbers")
    args = parser.parse_args()

    key = _api_key()

    if args.rederive:
        rederive_all(args.services, key)
        return 0

    if args.capture:
        service = args.services[0]
        report = capture(service, args.capture, key)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"{service}_{args.capture.replace(':', '').replace('-', '')}.json"
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in ("edge", "app")}, indent=2))
        print(f"edge {report['edge']['mb']} MB / {report['edge']['requests']} reqs")
        print(f"app served {_served_display(report['app'])} / {report['app']['access_lines']} access lines")
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
