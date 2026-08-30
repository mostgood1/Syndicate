"""The venue CAPTURE-TO-BUILD lag series, and what it does to the ceiling.

This is the decision input for `venue_basis_edge.MAX_VENUE_QUOTE_AGE_SECONDS`.
Run it over a window that contains several board builds -- an evening slate is
the useful one, because a single build gives a single point per sport.

--------------------------------------------------------------------------
WHY THIS IS A SERIES OF ONE VALUE PER BUILD, NOT A DISTRIBUTION OF QUOTES
--------------------------------------------------------------------------

Measured 2026-08-30 17:28Z, the first emission of `VENUE_QUOTE_AGE`:

    sport=mlb    n=32  min=4.9  p25=4.9  p50=4.9  p75=4.9  p90=4.9  max=4.9
    sport=soccer n=2   min=34.5 ...      max=34.5

**Thirty-two values identical to the decimal.** `age_seconds` is not a per-quote
age at all -- it is the age of the whole venue CAPTURE for that sport, and every
quote in a build inherits it. So the ceiling is not filtering stale quotes out
of fresh ones; it is an ALL-OR-NOTHING gate on one number per sport per build,
decided by a race between the capture cycle and the board build cycle:

    16:57Z  capture 64s old   ->  0 of 6 passed
    17:28Z  capture 4.9s old  ->  32 of 32 passed

Same mechanism, not two slates. The percentile fields inside one build are
therefore meaningless and this script IGNORES them: it takes `min` (== every
other percentile) as that build's single value and builds the series ACROSS
builds, which is the quantity that should set the bar.

--------------------------------------------------------------------------
WHAT IT REFUSES TO CONCLUDE
--------------------------------------------------------------------------

A ceiling must not be set from a handful of points, and above all must not be
set to whatever makes edges appear. This prints `n` per sport and declines to
recommend below `MIN_BUILDS_TO_RECOMMEND`. A recommendation it does make is
expressed as a percentile of observed lag, so it is traceable to data rather
than taste.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import sys

MIN_BUILDS_TO_RECOMMEND = 12

LINE = re.compile(
    r"VENUE_QUOTE_AGE sport=(?P<sport>\S+) n=(?P<n>\d+) min=(?P<min>[\d.]+).*?"
    r"ceiling=(?P<ceiling>[\d.]+) would_pass=(?P<pass>\d+)/(?P<of>\d+)"
)
STAMP = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T[\d:.]+Z)")


def _fetch(start: str, end: str | None, service: str) -> list[str]:
    cmd = [
        sys.executable, "scripts/render_logs.py",
        "--service", service, "--text", "VENUE_QUOTE_AGE",
        "--start", start, "--tail", "400",
    ]
    if end:
        cmd += ["--end", end]
    out = subprocess.run(cmd, capture_output=True, timeout=600)
    return out.stdout.decode("utf-8", "replace").splitlines()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="ISO instant to read from")
    ap.add_argument("--end")
    ap.add_argument("--service", default="refresh-worker")
    args = ap.parse_args()

    rows: list[tuple[str, str, float, int, float]] = []
    for line in _fetch(args.start, args.end, args.service):
        if line.startswith("#"):
            continue
        found = LINE.search(line)
        if not found:
            continue
        stamp = STAMP.search(line.strip())
        rows.append((
            stamp.group("ts") if stamp else "?",
            found.group("sport"),
            float(found.group("min")),
            int(found.group("n")),
            float(found.group("ceiling")),
        ))

    if not rows:
        print(
            "NO SAMPLES in this window.\n"
            "  `VENUE_QUOTE_AGE` emits only when a build has LIVE rows carrying a\n"
            "  venue quote, so an empty result means either no build ran or no\n"
            "  sport had live venue quotes. Check `VENUE_BASIS`, which prints\n"
            "  unconditionally, to tell those two apart before concluding anything.",
            file=sys.stderr,
        )
        return 3

    by_sport: dict[str, list[tuple[str, float, int]]] = collections.defaultdict(list)
    ceiling = rows[0][4]
    for stamp, sport, lag, n, ceil in rows:
        by_sport[sport].append((stamp, lag, n))
        ceiling = ceil

    print(f"capture-to-build lag, one value per BUILD per SPORT   ceiling={ceiling}\n")
    print(f"{'sport':9s}{'builds':>7s}{'min':>8s}{'p50':>8s}{'p90':>8s}{'max':>8s}"
          f"{'builds<=ceil':>14s}{'quotes':>8s}")
    total_builds = 0
    for sport, series in sorted(by_sport.items()):
        lags = sorted(v for _, v, _ in series)
        total_builds += len(lags)

        def pct(f: float) -> float:
            return lags[min(len(lags) - 1, max(0, int(round(f * (len(lags) - 1)))))]

        under = sum(1 for v in lags if v <= ceiling)
        quotes = sum(n for _, _, n in series)
        print(f"{sport:9s}{len(lags):7d}{lags[0]:8.1f}{pct(0.5):8.1f}{pct(0.9):8.1f}"
              f"{lags[-1]:8.1f}{under:>9d}/{len(lags):<4d}{quotes:8d}")

    print()
    for sport, series in sorted(by_sport.items()):
        print(f"  {sport}: " + ", ".join(f"{v:.1f}" for _, v, _ in series[-24:]))

    print()
    if total_builds < MIN_BUILDS_TO_RECOMMEND:
        print(
            f"NO RECOMMENDATION: {total_builds} build-samples, under the "
            f"{MIN_BUILDS_TO_RECOMMEND} minimum.\n"
            "  A ceiling set from a handful of points is a guess wearing a "
            "measurement's clothes,\n"
            "  which is exactly how the current 45s got there. Re-run over a "
            "fuller slate."
        )
        return 0

    all_lags = sorted(v for s in by_sport.values() for _, v, _ in s)
    p90 = all_lags[min(len(all_lags) - 1, int(round(0.9 * (len(all_lags) - 1))))]
    p95 = all_lags[min(len(all_lags) - 1, int(round(0.95 * (len(all_lags) - 1))))]
    passing = sum(1 for v in all_lags if v <= ceiling)
    print(
        f"OBSERVED over {len(all_lags)} builds: p90={p90:.1f}s p95={p95:.1f}s\n"
        f"  current ceiling {ceiling}s admits {passing}/{len(all_lags)} builds.\n\n"
        "  A ceiling at the observed p95 would admit 95% of builds and is\n"
        "  traceable to this series. BUT PREFER REMOVING THE RACE: this lag is a\n"
        "  property of two SCHEDULES, not of market data, and widening the bar\n"
        "  treats a scheduling artifact as a data-quality tolerance. Having the\n"
        "  build read (or trigger) the capture it needs makes the number moot.\n"
        "  If the bar is kept, RENAME it -- it gates how far behind the build a\n"
        "  capture may be, not how stale a quote may be, and that mis-description\n"
        "  is what made 45s look defensible."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
