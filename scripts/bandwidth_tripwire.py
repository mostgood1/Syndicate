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

5. **A PAGE BUDGET THAT RUNS OUT IS A FLOOR, NOT A TOTAL.** `_logs` pages
   BACKWARD from the end of the window, so exhausting the budget drops the
   OLDEST part of the hour -- and until 2026-09-23 it did that silently, at
   200 pages x 100 lines = 20,000. The 2026-09-23T01:00Z web capture landed on
   exactly `log_lines: 20000` and reported `served_mb: 395.62` as a total; the
   ratio `metered / app-served` computed from it (1.04) was really a CEILING,
   and that ratio is the whole `[render-egress-spikes]` argument. Neither
   existing guard could see it: `instrument_blind` and `instrument_partial` are
   both about the EMITTER writing lines, this is about the READER not asking
   for them. Every section now carries `read` and `read_truncated`, the app
   section carries `served_is_floor`, and both print paths say `>=`.

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


#: The API serves 100 lines per page, so a page budget IS a line budget.
#: This was 200 (= 20,000 lines) until 2026-09-23, and it truncated SILENTLY:
#: see trap 5 in the module docstring. 900 matches `render_bandwidth_report.py`,
#: which has paged the same API against the same owner without trouble.
LOG_PAGE_SIZE = 100
DEFAULT_MAX_LOG_PAGES = 900

#: Reasons `_logs` stopped. Only these two mean it read the WHOLE window; every
#: other reason leaves older lines unread, so any total derived from the rows is
#: a floor. Listed explicitly rather than inferred, because "unknown" must not
#: fall through to the complete branch.
_COMPLETE_STOPS = ("reached window start", "no more lines")


def _logs(key: str, resource: str, start: str, end: str, log_type: str,
          max_pages: int = DEFAULT_MAX_LOG_PAGES,
          meta: dict[str, Any] | None = None) -> list[tuple[str, str, dict]]:
    """Page BACKWARD, deduplicating by id.

    The API returns the NEWEST `limit` lines inside the window, so a forward
    pager re-reads the tail forever and never reaches the start.

    Trap 5: this pager can run out of budget before it reaches `start`, and it
    returns the newest `max_pages * 100` lines with NO signal that the rest
    exist. Pass `meta` to find out: it is filled with `truncated`, `stop_reason`,
    `pages`, `lines` and `oldest_reached`. The return type is unchanged because
    `controlled_transfer_read.py`, `controlled_transfer_arm2_watch.py` and
    `controlled_transfer_probe.py` all import this function.
    """
    seen: set[str] = set()
    rows: list[tuple[str, str, dict]] = []
    cursor = end
    pages = 0
    stop_reason = "page budget exhausted"
    for _ in range(max_pages):
        params = {
            "ownerId": OWNER_ID, "resource": resource, "limit": str(LOG_PAGE_SIZE),
            "startTime": start, "endTime": cursor, "type": log_type,
        }
        payload = _get("https://api.render.com/v1/logs?" + urllib.parse.urlencode(params, doseq=True), key)
        entries = payload.get("logs") or []
        pages += 1
        if not entries:
            stop_reason = "no more lines"
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
        if oldest <= start:
            stop_reason = "reached window start"
            break
        if fresh == 0:
            # Every id on this page was already seen and none of them predate
            # `start`: the cursor cannot move, so older lines stay unread.
            stop_reason = "cursor stalled (a full page of duplicate ids)"
            break
        cursor = oldest
        time.sleep(0.4)
    rows.sort()
    if meta is not None:
        meta.update({
            "pages": pages,
            "max_pages": max_pages,
            "lines": len(rows),
            "stop_reason": stop_reason,
            "oldest_reached": rows[0][0] if rows else None,
            "truncated": stop_reason not in _COMPLETE_STOPS,
        })
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
    if app.get("served_is_floor"):
        # A floor rendered as a total is the same class of error as a dead
        # emitter rendered as 0.0: both read as a small number rather than as
        # the refusal they are. `>=` is the whole point -- it stops a reader
        # dividing metered by it and getting a ratio that is really a bound.
        return f">= {app['served_mb']} MB (FLOOR -- {app.get('floor_reason') or 'partial read'})"
    return f"{app['served_mb']} MB"


def _floor_reason(meta: dict[str, Any], start: str, which: str) -> str:
    """Say what was NOT read, in the units a reader needs to judge the total.

    Naming the oldest line reached is the difference between "this number is
    wrong somehow" and "this number covers 01:31Z..02:00Z of a 01:00Z hour".
    """
    oldest = meta.get("oldest_reached") or "?"
    return (
        f"{which} log read stopped at {meta.get('pages')} pages "
        f"({meta.get('lines')} lines, {meta.get('max_pages')} page budget): "
        f"{meta.get('stop_reason')}. Lines older than {oldest} were NEVER READ, so this "
        f"covers {oldest}..window end, not {start}..window end. Every total and every "
        f"top_* list below is a FLOOR. Re-run with a larger --max-log-pages for a complete "
        f"read; do NOT divide metered_mb by it."
    )


def _truncation_warnings(report: dict[str, Any]) -> list[str]:
    """Every floor in this capture, as lines a reader cannot skim past.

    The JSON carries `read_truncated` on each section, but a capture is read
    from the terminal first and the file later -- and the whole point of the
    2026-09-23 defect was that a floor printed as a total.
    """
    out: list[str] = []
    for section in ("edge", "app"):
        block = report.get(section) or {}
        if block.get("read_truncated"):
            out.append(str(block.get("floor_reason") or f"{section} log read was TRUNCATED"))
    for worker, block in (report.get("publish_into_web") or {}).items():
        if isinstance(block, dict) and block.get("read_truncated"):
            out.append(str(block.get("floor_reason") or f"{worker} log read was TRUNCATED"))
    return out


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


def _monotonic_counters(report: dict[str, Any]) -> dict[str, int]:
    """Counters that can only GROW between two reads of the same window.

    A log line is immutable once written, so a re-read that returns FEWER of
    them than the stored capture did is reading a window that has partly aged
    out -- never a smaller hour.
    """
    out: dict[str, int] = {}
    app = report.get("app") or {}
    for field in ("log_lines", "access_lines", "served_bytes"):
        value = app.get(field)
        if isinstance(value, int):
            out[f"app.{field}"] = value
    edge = report.get("edge") or {}
    for field in ("requests", "bytes"):
        value = edge.get(field)
        if isinstance(value, int):
            out[f"edge.{field}"] = value
    for worker, block in (report.get("publish_into_web") or {}).items():
        if not isinstance(block, dict):
            continue
        for field in ("publishes", "bytes"):
            value = block.get(field)
            if isinstance(value, int):
                out[f"publish_into_web.{worker}.{field}"] = value
    return out


def _expiry_regressions(stored: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    """THE REASON `--recomplete` CANNOT JUST OVERWRITE.

    Render's log retention is the whole reason this tool exists: it captures a
    spike WHILE the logs are still there. Re-reading a window whose logs have
    since aged out returns a SMALLER read, and writing that over the stored
    capture would destroy the only record of the hour. A shrinking counter is
    the discriminator, and the pass refuses on it rather than writing.
    """
    old = _monotonic_counters(stored)
    new = _monotonic_counters(fresh)
    return [f"{k}: stored {old[k]} -> re-read {new[k]}"
            for k in sorted(old) if k in new and new[k] < old[k]]


def _window_is_readable(key: str, service: str, start: str, end: str,
                        stored: dict[str, Any]) -> bool:
    """Cheap expiry check: ONE page before spending a full capture on the window.

    Render keeps logs for ~14 days (measured 2026-09-23: buckets at and before
    `2026-09-09T13:00Z` returned 0 rows, `2026-09-09T18:00Z` onward returned
    lines). `_expiry_regressions` would catch an expired window anyway, but
    only after paging the whole capture -- so this keeps a pass over the full
    archive from spending hours re-reading hours that are gone.

    A stored capture with no lines of its own cannot regress, so it is left to
    the full check rather than judged here.
    """
    stored_lines = (stored.get("app") or {}).get("log_lines")
    if not isinstance(stored_lines, int) or stored_lines <= 0:
        return True
    return bool(_logs(key, SERVICE_IDS[service], start, end, "app", max_pages=1))


def _needs_recomplete(stored: dict[str, Any]) -> bool:
    """A capture needs re-reading if it predates the `read` block (so it was
    taken on the 200-page budget and its truncation is UNKNOWN), or if it
    records a truncated read."""
    sections: list[dict[str, Any]] = [stored.get("app") or {}, stored.get("edge") or {}]
    sections += [b for b in (stored.get("publish_into_web") or {}).values() if isinstance(b, dict)]
    if any(s.get("read_truncated") for s in sections):
        return True
    return not all("read" in s for s in sections if s)


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


def capture(service: str, bucket: str, key: str, metered_mb: float | None = None,
            max_log_pages: int = DEFAULT_MAX_LOG_PAGES) -> dict[str, Any]:
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

    edge_meta: dict[str, Any] = {}
    edge = _logs(key, resource, start, end, "request", max_pages=max_log_pages, meta=edge_meta)
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
        "read": edge_meta,
        "read_truncated": bool(edge_meta.get("truncated")),
    }
    if edge_meta.get("truncated"):
        report["edge"]["floor_reason"] = _floor_reason(edge_meta, start, "edge")

    app_meta: dict[str, Any] = {}
    app = _logs(key, resource, start, end, "app", max_pages=max_log_pages, meta=app_meta)
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
    app_truncated = bool(app_meta.get("truncated"))
    report["app"] = {
        "log_lines": len(app), "access_lines": access_lines,
        "served_bytes": None if app_blind else app_total,
        "served_mb": None if app_blind else round(app_total / 1048576, 2),
        "top_paths": _top(app_paths), "top_clients": _top(app_ips),
        "instrument_blind": app_blind,
        "read": app_meta,
        "read_truncated": app_truncated,
        # THE FIELD A READER MUST CHECK BEFORE DIVIDING. `instrument_blind` and
        # `instrument_partial` are both about the EMITTER; this one is about the
        # READER running out of pages, which neither of them can see.
        "served_is_floor": app_truncated and not app_blind,
        "note": "served_bytes is RESPONSE size only; a POST body (e.g. artifacts/publish) is NOT counted here",
    }
    if app_truncated and not app_blind:
        report["app"]["floor_reason"] = _floor_reason(app_meta, start, "app")
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
        worker_meta: dict[str, Any] = {}
        rows = _logs(key, SERVICE_IDS[worker], start, end, "app",
                     max_pages=max_log_pages, meta=worker_meta)
        total = 0
        count = 0
        for _ts, message, _labels in rows:
            if "PUBLISH_OK" not in message:
                continue
            match = _PUBLISH_BYTES.search(message)
            if match:
                total += int(match.group(1)); count += 1
        publish[worker] = {
            "publishes": count, "bytes": total, "mb": round(total / 1048576, 2),
            "read": worker_meta,
            "read_truncated": bool(worker_meta.get("truncated")),
        }
        if worker_meta.get("truncated"):
            publish[worker]["floor_reason"] = _floor_reason(worker_meta, start, worker)
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
            report = capture(service, bucket, key, metered_mb=mb,
                             max_log_pages=getattr(args, "max_log_pages", DEFAULT_MAX_LOG_PAGES))
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            out = OUT_DIR / f"{service}_{bucket.replace(':', '').replace('-', '')}.json"
            out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            fired += 1
            edge_flag = " (FLOOR, truncated read)" if report["edge"].get("read_truncated") else ""
            pub_flag = " (FLOOR)" if any(
                v.get("read_truncated") for v in report["publish_into_web"].values()
            ) else ""
            print(f"      edge {report['edge']['mb']} MB{edge_flag} / {report['edge']['requests']} reqs | "
                  f"app served {_served_display(report['app'])} | "
                  f"publish in {sum(v['mb'] for v in report['publish_into_web'].values()):.1f} MB{pub_flag}")
            for line in _truncation_warnings(report):
                print(f"      !! {line}")
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
            if app.get("served_is_floor"):
                flag += " FLOOR"
            print(f"  {bucket}  metered {report['metered_mb']}  edge {prior['edge_mb']} -> "
                  f"{report['edge']['mb']} MB ({prior['edge_requests']} -> {report['edge']['requests']} reqs)  "
                  f"served {prior['app_served_mb']} -> {app['served_mb']}{flag}", flush=True)
    print(f"re-derived {done} capture(s)")
    return done


def recomplete_all(services: list[str], key: str, max_log_pages: int = DEFAULT_MAX_LOG_PAGES,
                   dry_run: bool = False) -> dict[str, int]:
    """Re-read every capture taken on a budget too small to finish the window.

    Captures written before 2026-09-23 used 200 pages for the edge and app logs
    and NINETY for the two worker publish logs -- 9,000 lines against hours that
    routinely carry 14,000-15,000. So `publish_into_web` is understated across
    the whole set, not only in the two captures that visibly hit the app cap.
    Measured on `2026-09-23T01:00Z`: 462.1 MB stored against 725.0 MB read
    completely, a 36% shortfall, while the app `served_mb` in the same capture
    was short by 0.23%.

    Idempotent, and REFUSES rather than overwrites: see `_expiry_regressions`.
    """
    counts = {"rewritten": 0, "already_complete": 0, "expired": 0, "refused_expired": 0}
    for service in services:
        for path in sorted(OUT_DIR.glob(f"{service}_*.json")):
            named = _CAPTURE_NAME.match(path.name)
            if not named or named.group("service") != service:
                continue
            stored = json.loads(path.read_text(encoding="utf-8"))
            bucket = stored.get("bucket")
            if not bucket:
                continue
            if not _needs_recomplete(stored):
                counts["already_complete"] += 1
                print(f"  {bucket}  already read completely -- skipped", flush=True)
                continue
            start, end = _bucket_window(bucket)
            if not _window_is_readable(key, service, start, end, stored):
                counts["expired"] += 1
                print(f"  {bucket}  EXPIRED (0 log lines remain) -- stored capture KEPT", flush=True)
                continue
            try:
                metered = _metric(key, "bandwidth", SERVICE_IDS[service], start, end).get(bucket)
            except Exception:  # pragma: no cover - the stored meter reading stands
                metered = None
            fresh = capture(service, bucket, key,
                            metered_mb=metered if metered is not None else stored.get("metered_mb"),
                            max_log_pages=max_log_pages)

            regressions = _expiry_regressions(stored, fresh)
            if regressions:
                counts["refused_expired"] += 1
                print(f"  {bucket}  REFUSED -- the window has partly aged out; stored capture KEPT",
                      flush=True)
                for line in regressions:
                    print(f"        {line}", flush=True)
                continue

            if stored.get("rederived"):
                fresh["rederived"] = stored["rederived"]
            fresh["recompleted"] = {
                "at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "reason": (
                    "re-read on a page budget large enough to finish the window. The stored "
                    "numbers were taken at 200 pages (edge/app) and 90 pages (worker publish "
                    "logs), both of which truncate silently and produce FLOORS. Quote the "
                    "top-level numbers; `recompleted.prior` is what the file said before."
                ),
                "max_log_pages": max_log_pages,
                "prior": _prior_numbers(stored),
                "prior_counters": _monotonic_counters(stored),
            }
            app = fresh["app"]
            old_pub = sum(float((v or {}).get("mb") or 0)
                          for v in (stored.get("publish_into_web") or {}).values())
            new_pub = sum(float((v or {}).get("mb") or 0) for v in fresh["publish_into_web"].values())
            if not dry_run:
                path.write_text(json.dumps(fresh, indent=2, sort_keys=True), encoding="utf-8")
            counts["rewritten"] += 1
            print(f"  {bucket}  served {(stored.get('app') or {}).get('served_mb')} -> "
                  f"{app['served_mb']} MB | publish {old_pub:.1f} -> {new_pub:.1f} MB"
                  f"{'  [DRY RUN]' if dry_run else ''}", flush=True)
    print(f"recompleted {counts['rewritten']}, already complete {counts['already_complete']}, "
          f"expired {counts['expired']}, refused mid-read {counts['refused_expired']}")
    return counts


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
    parser.add_argument("--max-log-pages", type=int, default=DEFAULT_MAX_LOG_PAGES,
                        help=(f"log pages per read, {LOG_PAGE_SIZE} lines each "
                              f"(default {DEFAULT_MAX_LOG_PAGES} = "
                              f"{DEFAULT_MAX_LOG_PAGES * LOG_PAGE_SIZE:,} lines). Exhausting it "
                              "marks the section a FLOOR rather than truncating silently"))
    parser.add_argument("--rederive", action="store_true",
                        help="re-capture every capture on disk on the corrected window, keeping the prior numbers")
    parser.add_argument("--recomplete", action="store_true",
                        help=("re-read every capture taken on a budget too small to finish its "
                              "window, keeping the prior numbers. REFUSES to overwrite a capture "
                              "whose logs have partly aged out"))
    parser.add_argument("--dry-run", action="store_true",
                        help="with --recomplete: read and report, write nothing")
    args = parser.parse_args()

    key = _api_key()

    if args.rederive:
        rederive_all(args.services, key)
        return 0

    if args.recomplete:
        recomplete_all(args.services, key, max_log_pages=args.max_log_pages, dry_run=args.dry_run)
        return 0

    if args.capture:
        service = args.services[0]
        report = capture(service, args.capture, key, max_log_pages=args.max_log_pages)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"{service}_{args.capture.replace(':', '').replace('-', '')}.json"
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in ("edge", "app")}, indent=2))
        edge_flag = " (FLOOR, truncated read)" if report["edge"].get("read_truncated") else ""
        print(f"edge {report['edge']['mb']} MB{edge_flag} / {report['edge']['requests']} reqs")
        print(f"app served {_served_display(report['app'])} / {report['app']['access_lines']} access lines")
        for line in _truncation_warnings(report):
            print(f"!! {line}")
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
