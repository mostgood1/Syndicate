"""Measure the refresh-worker memory gate and the two deploy-window criteria.

Built 2026-08-07, after an eleven-hour OOM outage in which nine mechanisms were
proposed from source and eight were wrong. Its whole purpose is that the three
questions below get answered by measurement rather than re-derived under
pressure, because every one of them has an obvious-but-wrong answer.

    python scripts/check_worker_memory_gate.py                # all three
    python scripts/check_worker_memory_gate.py --hours 6
    python scripts/check_worker_memory_gate.py --section gate

THE GATE -- "did the floor survive a real slate?"
    WRONG answer: "no kills". A floor that reaches 3GB on a 15-game slate and
    merely fails to cross 4GiB reads as "fine" by kill count and "one game away"
    by margin. The margin is the signal.
    RIGHT answer: peak container_memory_mb BETWEEN consecutive BOOTED events.
    Reference: pre-fix per-cycle peaks 2797-4048MB; post-#253 steady state
    380-870MB. Pass = slate peak under ~1500MB.

WIN A -- "did #255 work?"
    WRONG answer: "no kills". #255 makes #251 execute for the FIRST TIME (its
    cache entries were being evicted on a 10s TTL while it asked for 300s-old
    ones), so if the code did not run, the memory result is meaningless.
    RIGHT answer: the hydrated MLB overview rebuild interval should move from
    ~90s to ~300s. Confirm the code ran before interpreting the memory.

WIN B -- "did settlement work?"
    WRONG answer: "the worker survived". A run that survives because it was
    SKIPPED says nothing about settled:0 of 8,276.
    RIGHT answer: a run that COMPLETES and writes its status, then
    unmatched_no_key_match. #247 unblocked 4,560 records and nobody has seen the
    result, because it crash-looped every time it tried.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REFRESH_WORKER = "srv-d91dpertqb8s73co8ls0"
OWNER = "tea-d2bb5n95pdvs73cje4fg"

PREFIX_PEAK_LOW, PREFIX_PEAK_HIGH = 2797.0, 4048.0     # pre-#253 per-cycle peaks
STEADY_LOW, STEADY_HIGH = 380.0, 870.0                 # post-#253 steady state
GATE_PASS_MB = 1500.0

_CONTAINER_MB = re.compile(r"container_memory_mb[\"']?\s*[:=]\s*([0-9.]+)")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _render_key() -> str:
    for line in (_repo_root() / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "RENDER_API_KEY":
            # Quote-stripping is not cosmetic: a quoted value yields a 401 that
            # looks like an auth problem rather than a parsing one.
            return value.strip().strip('"').strip("'")
    raise SystemExit("RENDER_API_KEY not found in .env")


def _api(path: str, params: dict | None = None, *, key: str, attempts: int = 5):
    """Render's logs API rate-limits, and a dropped window is not a neutral
    failure here -- 429s land on the MOST RECENT chunks (they are requested
    last), which is exactly the data the gate depends on. A silent gap would
    read as 'quiet worker'. So: back off and retry, and pace every call."""
    url = "https://api.render.com/v1" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            body = json.loads(urllib.request.urlopen(req, timeout=180).read())
            time.sleep(0.35)  # pace: stay under the limit rather than recover from it
            return body
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == attempts:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def _ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


_LOG_LIMIT = 1000
_MIN_CHUNK_SECONDS = 60


def _fetch_log_chunk(key: str, start: datetime, end: datetime, depth: int = 0) -> list[dict]:
    """One window, SUBDIVIDED whenever it comes back full.

    A chunk that returns exactly `limit` rows is truncated, and the rows you did
    not get are silently missing -- which is how the first version of this tool
    reported two different "current boot" values for the same worker depending on
    the lookback: busy hours hit the cap, later BOOTED lines fell off, and the
    kill attribution keyed off an hours-old boot.

    Silent truncation reading as complete data is the exact error class this
    whole incident was made of, so it is detected rather than hoped against.
    """
    try:
        resp = _api(
            "/logs",
            {
                "ownerId": OWNER,
                "resource": REFRESH_WORKER,
                "limit": _LOG_LIMIT,
                "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            key=key,
        )
        rows = (resp.get("logs") if isinstance(resp, dict) else resp) or []
    except Exception as exc:
        print(f"  ! log window {start:%H:%M:%S}-{end:%H:%M:%S} failed: {exc}")
        return []

    span = (end - start).total_seconds()
    if len(rows) < _LOG_LIMIT or span <= _MIN_CHUNK_SECONDS or depth >= 8:
        if len(rows) >= _LOG_LIMIT:
            print(f"  ! {start:%H:%M:%S}-{end:%H:%M:%S} still truncated at {len(rows)} rows "
                  f"({span:.0f}s) -- some lines in this window are NOT accounted for")
        return rows

    mid = start + timedelta(seconds=span / 2)
    return _fetch_log_chunk(key, start, mid, depth + 1) + _fetch_log_chunk(key, mid, end, depth + 1)


def _fetch_logs(key: str, start: datetime, end: datetime) -> list[dict]:
    """The logs API returns inconsistent windows for a bare `limit`, so always
    pass explicit start/end. Chunks are subdivided on truncation -- see
    `_fetch_log_chunk`."""
    rows: list[dict] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(minutes=30), end)
        rows.extend(_fetch_log_chunk(key, cursor, chunk_end))
        cursor = chunk_end

    # Dedupe: subdivision can re-fetch boundary rows.
    seen: set[tuple] = set()
    unique: list[dict] = []
    for row in rows:
        marker = (str(row.get("timestamp")), str(row.get("message"))[:200])
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(row)
    return unique


def _oom_kills(key: str, since: datetime) -> list[datetime]:
    kills, cursor = [], None
    for _ in range(8):
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        batch = _api(f"/services/{REFRESH_WORKER}/events", params, key=key)
        if not batch:
            break
        for item in batch:
            event = item.get("event", item)
            cursor = item.get("cursor") or cursor
            reason = (event.get("details") or {}).get("reason") or {}
            if reason.get("oomKilled") is not None:
                when = _ts(event.get("timestamp"))
                if when:
                    kills.append(when)
        if len(batch) < 100:
            break
    return sorted(k for k in kills if k >= since)


def section_gate(rows: list[dict], kills: list[datetime]) -> None:
    print("=" * 84)
    print("GATE -- peak container_memory_mb per boot  (NOT 'no kills')")
    print("=" * 84)

    samples: list[tuple[datetime, float]] = []
    boots: list[datetime] = []
    for row in rows:
        message = str(row.get("message", ""))
        when = _ts(row.get("timestamp"))
        if not when:
            continue
        if "BOOTED" in message or "Instance restarted" in message:
            boots.append(when)
        hit = _CONTAINER_MB.search(message)
        if hit:
            samples.append((when, float(hit.group(1))))
    samples.sort()
    boots.sort()

    if not samples:
        print("  no container_memory_mb samples in window -- cannot judge. NOT a pass.")
        return

    bounds = boots or [samples[0][0]]
    print(f"  {'boot':>10} {'window':>9} {'n':>5} {'peak MB':>9} {'final MB':>9}")
    peaks = []
    for i, boot in enumerate(bounds):
        end = bounds[i + 1] if i + 1 < len(bounds) else samples[-1][0] + timedelta(seconds=1)
        inside = [(t, mb) for t, mb in samples if boot <= t < end]
        if not inside:
            continue
        peak = max(mb for _, mb in inside)
        peaks.append(peak)
        print(f"  {boot:%H:%M:%S} {(end-boot).total_seconds()/60:>8.0f}m {len(inside):>5} "
              f"{peak:>9.1f} {inside[-1][1]:>9.1f}")

    if not peaks:
        print("  no samples inside any boot window. NOT a pass.")
        return

    # Judge the CURRENT boot, not the worst boot in the window. A lookback that
    # reaches into the outage contains 4GB peaks from builds that were dying
    # every four minutes; verdicting on max(all boots) reports FAIL forever and
    # is the same "which population am I measuring" error as counting kills
    # across the whole window. `worst` is kept for context only.
    worst = max(peaks)
    current_peak = peaks[-1]
    current_span = (samples[-1][0] - bounds[-1]).total_seconds() / 60
    # Kills BEFORE the current boot belong to whatever was running then -- almost
    # always the outage itself. Counting them against the current build reports
    # FAIL forever for any window that reaches back far enough, which is exactly
    # the "a count is not a rate" error this incident was made of.
    current_boot = bounds[-1]
    kills_current = [k for k in kills if k >= current_boot]
    kills_earlier = [k for k in kills if k < current_boot]

    print()
    print(f"  CURRENT BOOT {current_boot:%H:%M:%S}  uptime {current_span:.0f}m  "
          f"PEAK {current_peak:.1f}MB   <-- this is the number that matters")
    print(f"  worst peak anywhere in window: {worst:.1f}MB (context only; earlier boots may predate the fix)")
    print(f"  reference: pre-fix cycles {PREFIX_PEAK_LOW:.0f}-{PREFIX_PEAK_HIGH:.0f}MB, "
          f"container limit 4096MB, pass bar {GATE_PASS_MB:.0f}MB")
    print(f"  OOM kills since current boot: {len(kills_current)}")
    if kills_earlier:
        print(f"  ({len(kills_earlier)} earlier kills in the window predate this boot -- not counted)")

    if kills_current:
        print("  VERDICT: FAIL -- killed on the CURRENT build. Do not proceed to WIN A.")
    elif current_span < 30:
        print(f"  VERDICT: TOO EARLY -- {current_span:.0f}m uptime. The floor is a function of")
        print("           time-since-boot, so a young boot always looks good. Wait.")
    elif current_peak < GATE_PASS_MB:
        print(f"  VERDICT: PASS -- current boot peaked at {current_peak:.0f}MB over {current_span:.0f}m,")
        print(f"           under the {GATE_PASS_MB:.0f}MB bar, with {4096 - current_peak:.0f}MB of headroom.")
    else:
        print(f"  VERDICT: MARGINAL -- no kills, but the current boot peaked at {current_peak:.0f}MB,")
        print(f"           over the {GATE_PASS_MB:.0f}MB bar. {4096 - current_peak:.0f}MB headroom left.")
        print("           Survived on margin, not headroom. Find out why the floor is climbing")
        print("           before deploying anything on top of it.")


def section_win_a(rows: list[dict]) -> None:
    print()
    print("=" * 84)
    print("WIN A -- did #255 make #251 EXECUTE?  (NOT 'no kills')")
    print("=" * 84)
    stamps = [
        _ts(r.get("timestamp"))
        for r in rows
        if "OVERVIEW_SPORT_BEGIN" in str(r.get("message", ""))
        and "sport=mlb" in str(r.get("message", ""))
        and "skip_game_hydration=False" in str(r.get("message", ""))
    ]
    stamps = sorted(s for s in stamps if s)
    print(f"  hydrated MLB overview builds seen: {len(stamps)}")
    # A median over one or two gaps is not a measurement. During the outage a
    # build was killed mid-cycle every few minutes, so gaps are wildly bimodal
    # (a 77s real interval next to a 3518s gap spanning a restart) and a small
    # sample will confidently report whichever one it happened to catch.
    if len(stamps) < 6:
        print("  fewer than 6 builds -- too few for an interval. NOT evidence either way.")
        print("  Widen --hours, or wait; do not interpret memory until this is answered.")
        return
    gaps = [(stamps[i + 1] - stamps[i]).total_seconds() for i in range(len(stamps) - 1)]
    median = statistics.median(gaps)
    print(f"  interval: median {median:.0f}s   min {min(gaps):.0f}s   max {max(gaps):.0f}s   n={len(gaps)}")
    print("  expected: ~90s BEFORE #255, ~300s AFTER")
    if median >= 240:
        print("  VERDICT: #251 IS EXECUTING. Memory results from this window are interpretable.")
    elif median <= 150:
        print("  VERDICT: #251 STILL A NO-OP -- rebuilds unchanged. The floor result means")
        print("           NOTHING; do not attribute anything to #255. Find what evicts it.")
    else:
        print("  VERDICT: ambiguous interval. Widen the window before concluding.")


def section_win_b(rows: list[dict]) -> None:
    print()
    print("=" * 84)
    print("WIN B -- did settlement COMPLETE?  (NOT 'the worker survived')")
    print("=" * 84)
    started = completed = never_completed = 0
    unmatched: list[str] = []
    for row in rows:
        message = str(row.get("message", ""))
        if "PREVIOUS_RUN_NEVER_COMPLETED" in message:
            never_completed += 1
        if "settle_ledger" in message or "SETTLEMENT_AUTORUN" in message:
            started += 1
        if "closing_rows=" in message or "graded_rows=" in message:
            completed += 1
        if "unmatched_no_key_match" in message or '"settled"' in message:
            unmatched.append(f"{str(row.get('timestamp',''))[11:19]}  {message[:150]}")

    print(f"  settlement-ish lines      : {started}")
    print(f"  completion-shaped lines   : {completed}")
    print(f"  PREVIOUS_RUN_NEVER_COMPLETED : {never_completed}")
    if never_completed:
        print("  -> a previous run DIED inside settlement. #256 stopped the retry loop,")
        print("     but the run itself is still too expensive. Pull the env var.")
    for line in unmatched[-8:]:
        print(f"    {line}")
    if not started:
        print("  no settlement activity -- autorun still disabled, or it never fired.")
        print("  A quiet worker here is NOT a pass: it means the test did not run.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=float, default=3.0, help="lookback window (default 3)")
    parser.add_argument("--section", choices=["gate", "win-a", "win-b", "all"], default="all")
    args = parser.parse_args()

    key = _render_key()
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=args.hours)
    print(f"refresh-worker {REFRESH_WORKER}")
    print(f"window {start:%Y-%m-%d %H:%M}Z .. {end:%H:%M}Z ({args.hours}h)\n")

    rows = _fetch_logs(key, start, end)
    kills = _oom_kills(key, start)
    print(f"log lines: {len(rows):,}   oom kills: {len(kills)}\n")

    if args.section in ("gate", "all"):
        section_gate(rows, kills)
    if args.section in ("win-a", "all"):
        section_win_a(rows)
    if args.section in ("win-b", "all"):
        section_win_b(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
