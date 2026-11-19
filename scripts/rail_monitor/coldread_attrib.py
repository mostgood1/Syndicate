"""Why is the Layer 2 board query's `board_read` cold?  READ-ONLY; run at nice 19 on the fleet.

    cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/<path>/coldread_attrib.py <from_utc> <to_utc> [--rows]

Lane `board-read-cold-share` (rail monitor I-28). Arguments are UTC, ``YYYY-MM-DDTHH:MM:SS``.
Hour rows are printed in Central time (UTC-6, CST).

ATTRIBUTION. Every /api/intelligence/query whose `board_read` stage took > 2,000 ms goes in
ONE class, by the marker lines printed INSIDE its board_read window. The window is
[start, start + board_read], with start = line ts - total_ms, because board_read is the
first stage and QUERY_STAGE_MS prints after the last:

  boot_cold    `COMBINED_BOARD_OVERLAY_WARMER_STARTED pid=X` in the window. That line prints
               once per process, at its first combined-board call, so this is the first board
               read in a NEW worker. Each worker has its own in-process cache, which starts empty.
  overlay      `COMBINED_BOARD_OVERLAY_EXPIRED` in the window: a newer in-play overlay refused
               the cached entry inside its TTL.
  ttl_sure     neither, and no board build of ANY kind ended in the TTL (180 s) before the read.
               No worker can hold an entry younger than the TTL, so this is TTL expiry (or an
               eviction).
  ttl_or_peer  neither, and some build ended < TTL ago, on a worker we cannot name, because
               QUERY_STAGE_MS carries no pid. This is TTL expiry on THIS worker, or an eviction.

PROJECTION, a MODEL and labelled as one. It asks what a cross-worker shared copy would have
served each cold read. Builds are every cold query's board_read and every
`COMBINED_BOARD_OVERLAY_WARMED` rebuild (start = ts - build_s). Overlay landings come from the
warmed lines (start - overlay_age_s). A cold read at s ADOPTS:
  fresh   the newest build that ended by s ended < TTL ago, and no overlay landed after that
          build's own overlay while the copy was >= the overlay min age (22 s on web). These are
          the same two rules the in-process cache applies.
  stale   no fresh copy, but another build was IN FLIGHT at s and a copy <= TTL x 10 old
          existed. The in-process single-flight already serves the previous value in exactly
          this case (COMBINED_BOARD_SERVED_STALE).
  for a boot_cold read only: a boot worker has no build of its own, so any build is another
  worker's. For the other classes, the newest build may have been this worker's own; the
  projection counts those too, so it is an upper bound for them.
"""
from __future__ import annotations

import bisect
import calendar
import collections
import datetime as dt
import glob
import json
import re
import subprocess
import sys

TTL_S = 180.0          # SYNDICATE_INTELLIGENCE_COMBINED_BOARD_CACHE_SECONDS on fleet web (read 11-19)
OVERLAY_MIN_AGE_S = 22.0   # SYNDICATE_INPLAY_OVERLAY_CACHE_MIN_AGE_SECONDS on fleet web (read 11-19)
STALE_MULTIPLE = 10.0  # _COMBINED_BOARD_STALE_TTL_MULTIPLE
COLD_MS = 2000.0
PAT = ("QUERY_STAGE_MS|COMBINED_BOARD_OVERLAY_WARMER_STARTED|COMBINED_BOARD_OVERLAY_EXPIRED|"
       "COMBINED_BOARD_OVERLAY_WARMED|COMBINED_BOARD_SERVED_STALE|WEB_WORKER_MEMORY_RECYCLE |"
       "Booting worker with pid|COMBINED_BOARD_SHARED_")


def utc_epoch(line: str) -> float:
    """The line's own UTC stamp as an epoch. NOT strptime().timestamp(): that reads a naive
    time as LOCAL, and the fleet's WSL clock is Central."""
    base = dt.datetime.strptime(line[:19], "%Y-%m-%dT%H:%M:%S")
    frac = float("0" + line[19:23]) if line[19:20] == "." else 0.0
    return calendar.timegm(base.timetuple()) + frac


def cst_hour(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch - 6 * 3600, dt.timezone.utc).strftime("%m-%d %H:00 CST")


def q(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))]) if xs else None


def main(argv: list[str]) -> int:
    a, b = argv[1][:19], argv[2][:19]
    show_rows = "--rows" in argv
    lines: list[str] = []
    for path in sorted(glob.glob("logs/web.log*")):
        out = subprocess.run(["grep", "-a", "-E", PAT, path], capture_output=True, text=True,
                             errors="replace").stdout
        for line in out.splitlines():
            # ALL_PROCESS_MEMORY quotes other processes' command lines, a grep's included.
            if "ALL_PROCESS_MEMORY" in line or len(line) < 24 or not line[:4].isdigit():
                continue
            if a <= line[:19] < b:
                lines.append(line)
    lines = sorted(set(lines))

    ev: dict[str, list] = collections.defaultdict(list)
    queries: list[tuple[float, dict]] = []
    for line in lines:
        try:
            t = utc_epoch(line)
        except ValueError:
            continue
        if "QUERY_STAGE_MS" in line:
            try:
                queries.append((t, json.loads(line[line.index("{"):])))
            except Exception:  # noqa: BLE001
                continue
        elif "WARMER_STARTED" in line:
            ev["first_board_call"].append((t, line))
        elif "OVERLAY_EXPIRED" in line:
            ev["overlay_expired"].append((t, line))
        elif "OVERLAY_WARMED" in line:
            if "rebuilt=False" in line:
                # With the shared copy on, a warmer pass that ADOPTED or served a copy built
                # nothing: it is not a build (its own SHARED_ line says what it did).
                ev["warmed_no_build"].append((t, line))
                continue
            bs = re.search(r"build_s=([0-9.]+)", line)
            oa = re.search(r"overlay_age_s=(-?[0-9.]+)", line)
            ev["warmed"].append((t, float(bs.group(1)) if bs else 0.0, float(oa.group(1)) if oa else None))
        elif "SERVED_STALE" in line and "SHARED" not in line:
            ev["served_stale"].append((t, line))
        elif "WEB_WORKER_MEMORY_RECYCLE " in line:
            ev["recycle"].append((t, line))
        elif "Booting worker" in line:
            ev["boot"].append((t, line))
        elif "COMBINED_BOARD_SHARED_" in line:
            kind = line.split("COMBINED_BOARD_SHARED_", 1)[1].split(" ", 1)[0]
            ev["shared_" + kind.lower()].append((t, line))

    def any_in(kind: str, lo: float, hi: float) -> bool:
        xs = [x[0] for x in ev[kind]]
        i = bisect.bisect_left(xs, lo)
        return i < len(xs) and xs[i] <= hi

    # Builds: (start, end).
    builds: list[tuple[float, float]] = []
    for t, d in queries:
        br = (d.get("stages") or {}).get("board_read", 0.0)
        if br > COLD_MS:
            s = t - d.get("total_ms", 0.0) / 1000.0
            builds.append((s, s + br / 1000.0))
    landings: list[float] = []
    for t, build_s, overlay_age in ev["warmed"]:
        builds.append((t - build_s, t))
        if overlay_age is not None:
            landings.append(t - build_s - overlay_age)
    builds.sort(key=lambda x: x[1])
    ends = [e for _, e in builds]
    landings.sort()

    def newest_landing(at: float) -> float | None:
        i = bisect.bisect_right(landings, at)
        return landings[i - 1] if i else None

    def project(s: float) -> str:
        i = bisect.bisect_right(ends, s - 0.05)
        if i:
            b_start, b_end = builds[i - 1]
            age = s - b_end
            built_against = newest_landing(b_start)
            now_overlay = newest_landing(s)
            overlay_newer = now_overlay is not None and (built_against is None or now_overlay > built_against)
            if age < TTL_S and not (overlay_newer and age >= OVERLAY_MIN_AGE_S):
                return "adopt_fresh"
            # STARTED BEFORE this read: a cold read's own build starts at s and must not count
            # as "another worker's build in flight".
            in_flight = any(bs_ < s - 0.25 and s < be_ for bs_, be_ in builds)
            if in_flight and age <= TTL_S * STALE_MULTIPLE:
                return "adopt_stale"
        return "still_cold"

    cls = collections.Counter()
    shared_by_query = collections.Counter()
    proj = collections.defaultdict(collections.Counter)
    by_hour: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    cold_br = collections.defaultdict(list)
    totals = collections.defaultdict(list)
    rows = []
    for t, d in queries:
        br = (d.get("stages") or {}).get("board_read", 0.0)
        tot = d.get("total_ms", 0.0)
        s = t - tot / 1000.0
        e = s + br / 1000.0
        hour = cst_hour(t)
        by_hour[hour]["queries"] += 1
        for marker in ("shared_adopted", "shared_served_stale", "shared_build"):
            if any_in(marker, s - 1.0, e + 1.0):
                shared_by_query[marker] += 1
                by_hour[hour]["q_" + marker] += 1
        if br <= COLD_MS:
            c = "warm"
        elif any_in("first_board_call", s - 1.0, e + 1.0):
            c = "boot_cold"
        elif any_in("overlay_expired", s - 1.0, e + 1.0):
            c = "overlay"
        else:
            i = bisect.bisect_left(ends, s - 0.5)
            prev = ends[i - 1] if i > 0 else None
            c = "ttl_sure" if prev is None or (s - prev) >= TTL_S else "ttl_or_peer"
        cls[c] += 1
        by_hour[hour][c] += 1
        totals[c].append(tot)
        p = None
        if c != "warm":
            cold_br[c].append(br)
            p = project(s)
            proj[c][p] += 1
        rows.append((dt.datetime.fromtimestamp(t - 6 * 3600, dt.timezone.utc).strftime("%H:%M:%S CST"),
                     c, p, round(br), round(tot)))

    for kind in ("recycle", "boot", "first_board_call", "overlay_expired", "served_stale"):
        for item in ev[kind]:
            by_hour[cst_hour(item[0])][kind] += 1
    for t, *_ in ev["warmed"]:
        by_hour[cst_hour(t)]["warmed"] += 1

    n = len(queries)
    cold_n = n - cls["warm"]
    adopted = sum(v for c in proj.values() for k, v in c.items() if k != "still_cold")
    all_tot = [d.get("total_ms", 0.0) for _, d in queries]
    span_h = max((utc_epoch(b + ".000") - utc_epoch(a + ".000")) / 3600.0, 1e-9)
    print(json.dumps({
        "window_utc": [a, b],
        "queries": n,
        "cold": [cold_n, round(100.0 * cold_n / n, 1) if n else None],
        "class": {k: [v, round(100.0 * v / n, 1) if n else None] for k, v in cls.most_common()},
        "class_share_of_cold_pct": {k: round(100.0 * v / cold_n, 1) for k, v in cls.items() if k != "warm" and cold_n},
        "cold_board_read_p50_ms": {k: q(v, .5) for k, v in cold_br.items()},
        "total_p50_ms": {k: q(v, .5) for k, v in totals.items()},
        "all_total_p50_p90_ms": [q(all_tot, .5), q(all_tot, .9)],
        "warmer_rebuilds": len(ev["warmed"]),
        "warmer_build_s_p50_p90": [q([x[1] for x in ev["warmed"]], .5), q([x[1] for x in ev["warmed"]], .9)],
        "recycles": len(ev["recycle"]), "recycles_per_h": round(len(ev["recycle"]) / span_h, 1),
        "boots": len(ev["boot"]), "first_board_calls": len(ev["first_board_call"]),
        "served_stale": len(ev["served_stale"]),
        "shared_markers": {k[len("shared_"):]: len(v) for k, v in ev.items() if k.startswith("shared_")},
        "queries_with_shared_marker": dict(shared_by_query),
        "warmer_passes_without_build": len(ev["warmed_no_build"]),
        "PROJECTION_model": {k: dict(v) for k, v in proj.items()},
        "PROJECTION_cold_after": [cold_n - adopted, round(100.0 * (cold_n - adopted) / n, 1) if n else None],
    }))
    print("hour (CST)         q  warm boot ovl ttlS ttlP | recyc boots 1stcall warmed ovlexp stale | q_adopt q_sstale")
    for h in sorted(by_hour):
        c = by_hour[h]
        print(f"{h:17s} {c['queries']:4d} {c['warm']:5d} {c['boot_cold']:4d} {c['overlay']:3d} "
              f"{c['ttl_sure']:4d} {c['ttl_or_peer']:4d} | {c['recycle']:5d} {c['boot']:5d} "
              f"{c['first_board_call']:7d} {c['warmed']:6d} {c['overlay_expired']:6d} {c['served_stale']:5d} | "
              f"{c['q_shared_adopted']:7d} {c['q_shared_served_stale']:7d}")
    if show_rows:
        for r in rows:
            print(*r)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
