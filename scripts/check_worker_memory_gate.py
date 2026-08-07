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
    WRONG answer #2, this tool's OWN until 2026-08-07: peak
    container_memory_mb. That is cgroup memory.current, which counts CLEAN PAGE
    CACHE -- 600-1200MB of it on this worker, swinging independently of the
    workload. A 1500MB bar on that number cannot be met by an IDLE process, and
    it reported MARGINAL all day against ~2.3GB of real headroom.
    RIGHT answer: peak accounted_rss_mb BETWEEN consecutive BOOTED events. RSS
    is the anonymous set -- the part the kernel cannot evict, and therefore the
    part that gets a container OOM-killed. Both numbers are printed; only RSS is
    judged. The bar was RE-DERIVED on this basis by measuring RSS at the three
    real kills of 2026-08-07 rather than carried over from the memory.current
    observations -- see RSS_LETHAL_MB / GATE_PASS_MB for the measurement.
    Reference (memory.current basis, so comparable to the CONTAINER column
    only): pre-fix per-cycle peaks 2797-4048MB; post-#253 steady state
    380-870MB.

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

# ---------------------------------------------------------------------------
# The bar, RE-DERIVED ON THE RSS BASIS 2026-08-07.
#
# The old 1500MB bar was derived from memory.current observations (the two
# reference ranges above). Once the gate was corrected to judge accounted_rss_mb,
# carrying that number across unchanged was a units mismatch -- the same error as
# barring on memory.current, one layer in. So it was measured instead.
#
# MEASURED at the three real OOM kills of 2026-08-07 (14:11:07, 14:14:50,
# 14:18:47; oomKilled={'memoryLimit': '4Gi'}):
#
#   time      container    rss    cache   note
#   14:02:01     3912.6  3387.8   524.8
#   14:14:19     3977.7  3476.3   501.4   31s before the 14:14:50 kill
#   (idle samples the same day carried 1100-1200MB of cache)
#
# Two things fall out, and the second is the load-bearing one:
#
# 1. Death is at container ~4096MB, as expected.
# 2. Under real memory pressure the kernel RECLAIMS, and cache compresses to
#    ~500MB -- the two highest-RSS samples carry the LOWEST cache in the whole
#    window. So cache is not a fixed tax on the ceiling; it gets out of the way.
#    The anonymous set can therefore reach ~4096 - 500 = ~3600MB before the
#    container dies, and the highest RSS actually observed before a kill was
#    3476.3MB. That is the lethal level on this basis.
RSS_LETHAL_MB = 3500.0

# Largest within-boot RSS excursion observed on a live slate (21:58:54Z boot:
# floor 858MB -> peak 1767MB). The bar is the lethal level minus one full
# excursion, so a worker sitting AT the bar can still absorb its worst observed
# working-set swing without reaching a kill. Rounded down from 2700 for margin.
#
# This is a stated safety rationale, not a number carried over from a different
# metric -- if you change it, say what evidence moved it.
GATE_PASS_MB = 2600.0

_CONTAINER_MB = re.compile(r"container_memory_mb[\"']?\s*[:=]\s*([0-9.]+)")
_ACCOUNTED_RSS_MB = re.compile(r"accounted_rss_mb[\"']?\s*[:=]\s*([0-9.]+)")


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


def _boot_boundaries(key: str, since: datetime) -> list[datetime]:
    """When the process actually restarted, from the EVENTS API.

    NOT from log text. refresh-worker emits >1000 lines per 20 minutes, the logs
    API caps a window at 1000, and `BOOTED` lines are therefore dropped
    unpredictably -- which made this tool report a boot at 15:31:42 that never
    happened, while the events API showed the process had been up continuously
    since the 14:31:49 deploy.

    Events are authoritative, small, and cheap. `deploy_ended` and
    `server_failed` are the only two ways this process restarts.
    """
    boots: list[datetime] = []
    cursor = None
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
            if str(event.get("type")) in {"deploy_ended", "server_failed"}:
                when = _ts(event.get("timestamp"))
                if when:
                    boots.append(when)
        if len(batch) < 100:
            break
    return sorted(b for b in boots if b >= since)


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


def section_gate(rows: list[dict], kills: list[datetime], boots: list[datetime], window_start: datetime) -> None:
    print("=" * 84)
    print("GATE -- peak accounted_rss_mb per boot  (NOT 'no kills', NOT memory.current)")
    print("=" * 84)

    # CORRECTED 2026-08-07. This barred on `container_memory_mb` -- the cgroup's
    # own memory.current -- which counts RECLAIMABLE PAGE CACHE. Measured on the
    # 21:58:54Z boot, mid-slate:
    #
    #     container_memory_mb  peak 2804.9      <- what this used to judge
    #     accounted_rss_mb     peak 1766.8      <- the unreclaimable part
    #     cache + slab              601..1185   <- swings independently
    #
    # The cache floor alone runs 600-1200MB, so a 1500MB bar on memory.current
    # could not be met by an IDLE worker. It was structurally unpassable, not
    # merely strict, and it reported MARGINAL all day for a worker with ~2.3GB
    # of real headroom. memory_observability.py:223 already treats
    # inactive_file + slab_reclaimable as available; this never inherited it.
    #
    # The BAR VALUE is deliberately unchanged. Only the metric it points at is
    # corrected -- the goalposts have not moved, they were aimed at the wrong
    # field. An OOM kill happens when the anonymous set cannot fit; clean page
    # cache is evicted first.
    #
    # CAVEAT on the reference numbers: PREFIX_PEAK_LOW/HIGH and STEADY_LOW/HIGH
    # were measured as memory.current, so they OVERSTATE the anon component by
    # whatever cache was resident at the time. Compare them to the container
    # column below, never to the RSS column.
    container_samples: list[tuple[datetime, float]] = []
    samples: list[tuple[datetime, float]] = []
    for row in rows:
        when = _ts(row.get("timestamp"))
        if not when:
            continue
        message = str(row.get("message", ""))
        container_hit = _CONTAINER_MB.search(message)
        if container_hit:
            container_samples.append((when, float(container_hit.group(1))))
        # ALL_PROCESS_MEMORY carries both numbers on one line, so the split is
        # always same-instant -- never pair a container reading with an RSS
        # reading from a different log line.
        rss_hit = _ACCOUNTED_RSS_MB.search(message)
        if rss_hit:
            samples.append((when, float(rss_hit.group(1))))
    container_samples.sort()
    samples.sort()
    # Boot boundaries come from the events API, not log text -- see
    # `_boot_boundaries`. If none fall inside the window the process has been up
    # the whole time, so the window start is the boundary.
    boots = sorted(boots) or [window_start]

    if not samples:
        # A worker that emits CONTAINER_MEMORY but no ALL_PROCESS_MEMORY leaves
        # the gate unable to separate anon from cache. Say so rather than
        # silently falling back to the number this fix exists to stop trusting.
        if container_samples:
            print(f"  {len(container_samples)} container_memory_mb samples but NO accounted_rss_mb.")
            print("  memory.current alone cannot separate anon from reclaimable cache, which is")
            print("  the whole point of this gate. Check that log_all_process_memory() still runs.")
        else:
            print("  no memory samples in window -- cannot judge. NOT a pass.")
        return

    bounds = boots or [samples[0][0]]
    print(f"  {'boot':>10} {'window':>9} {'n':>5} {'peak RSS':>9} {'final RSS':>10} {'peak cont':>10}")
    peaks = []
    for i, boot in enumerate(bounds):
        end = bounds[i + 1] if i + 1 < len(bounds) else samples[-1][0] + timedelta(seconds=1)
        inside = [(t, mb) for t, mb in samples if boot <= t < end]
        if not inside:
            continue
        peak = max(mb for _, mb in inside)
        peaks.append(peak)
        # The container column is context, not the verdict: it is what the old
        # bar judged, kept visible so a reading can be compared against the
        # historical references and against every verdict quoted before today.
        container_inside = [mb for t, mb in container_samples if boot <= t < end]
        container_peak = f"{max(container_inside):>10.1f}" if container_inside else f"{'-':>10}"
        print(f"  {boot:%H:%M:%S} {(end-boot).total_seconds()/60:>8.0f}m {len(inside):>5} "
              f"{peak:>9.1f} {inside[-1][1]:>10.1f} {container_peak}")

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

    current_container = [mb for t, mb in container_samples if t >= current_boot]

    print()
    print(f"  CURRENT BOOT {current_boot:%H:%M:%S}  uptime {current_span:.0f}m  "
          f"PEAK RSS {current_peak:.1f}MB   <-- this is the number that matters")
    if current_container:
        cache_gap = max(current_container) - current_peak
        print(f"  same boot, memory.current peaked {max(current_container):.1f}MB "
              f"-- {cache_gap:.0f}MB of it reclaimable cache, NOT a kill risk")
    print(f"  worst RSS peak anywhere in window: {worst:.1f}MB (context only; earlier boots may predate the fix)")
    print(f"  reference (memory.current basis -- compare to the container column, NOT to RSS):")
    print(f"    pre-fix cycles {PREFIX_PEAK_LOW:.0f}-{PREFIX_PEAK_HIGH:.0f}MB, "
          f"steady state {STEADY_LOW:.0f}-{STEADY_HIGH:.0f}MB")
    print(f"  RSS basis: lethal ~{RSS_LETHAL_MB:.0f}MB (measured 3476MB 31s before a real kill;")
    print(f"             cache compresses to ~500MB under pressure, so anon can reach ~3600)")
    print(f"  container limit 4096MB, pass bar {GATE_PASS_MB:.0f}MB RSS "
          f"= lethal minus one full observed excursion")
    if current_peak >= RSS_LETHAL_MB:
        print(f"  !! current peak is AT OR ABOVE the measured lethal level")
    print(f"  OOM kills since current boot: {len(kills_current)}")
    if kills_earlier:
        print(f"  ({len(kills_earlier)} earlier kills in the window predate this boot -- not counted)")

    if kills_current:
        print("  VERDICT: FAIL -- killed on the CURRENT build. Do not proceed to WIN A.")
    elif current_span < 30:
        print(f"  VERDICT: TOO EARLY -- {current_span:.0f}m uptime. The floor is a function of")
        print("           time-since-boot, so a young boot always looks good. Wait.")
    elif current_peak < GATE_PASS_MB:
        print(f"  VERDICT: PASS -- current boot peaked at {current_peak:.0f}MB RSS over {current_span:.0f}m,")
        print(f"           under the {GATE_PASS_MB:.0f}MB bar, with {4096 - current_peak:.0f}MB of headroom.")
    else:
        print(f"  VERDICT: MARGINAL -- no kills, but the current boot peaked at {current_peak:.0f}MB RSS,")
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
    boots = _boot_boundaries(key, start)
    print(f"log lines: {len(rows):,}   oom kills: {len(kills)}   restarts (events API): {len(boots)}")
    # The logs API caps a window at 1000 rows and this worker emits well over
    # that; subdivision recovers most of it but not provably all. So the peak
    # below is a LOWER BOUND on the true peak -- which is the safe direction for
    # a gate (it can only make us hold longer, never ship early).
    print("note: memory peak is a LOWER BOUND -- log sampling is not exhaustive.\n")

    if args.section in ("gate", "all"):
        section_gate(rows, kills, boots, start)
    if args.section in ("win-a", "all"):
        section_win_a(rows)
    if args.section in ("win-b", "all"):
        section_win_b(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
