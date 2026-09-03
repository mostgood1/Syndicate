#!/usr/bin/env python3
"""Does the board-window floor actually CLIP? `#631`, the owed half.

    py -3 scripts/measure_board_window_clip_rate.py
    py -3 scripts/measure_board_window_clip_rate.py --since 2026-09-03T04:20:45Z

WHY THIS SCRIPT EXISTS RATHER THAN A ONE-OFF QUERY. The question was
unanswerable until 2026-09-03: nothing on the board-window queue path emitted
anything, so "did the floor clip?" could only be inferred from
`BUILD_SPAN_ENTER`, and a build span CANNOT separate a CLIPPED ENQUEUE from a
capacity-limited build. A lane made exactly that inference on 2026-09-02,
concluded "the throttle BINDS", and was wrong twice over -- the floor it reasoned
against (1800) was not the live value (600), and a gap sitting ABOVE a floor is
not evidence the floor caused it.

THE PREDICATE IS THE ENQUEUE, and `33b181ee` made it observable:

    BOARD_WINDOW_QUEUE_GATED date=<d> elapsed_s=<e> floor_s=<f>
    BOARD_WINDOW_QUEUED      date=<d> throttled=yes|no elapsed_s=<e> floor_s=<f>

    clip rate = GATED / (GATED + ADMITTED)   for a NON-TODAY date

**A CLIP RATE OF 0 OVER A REAL WINDOW IS A LEGITIMATE RESULT.** It means the
queue coalesces and the floor is the wrong lever -- NOT that the measurement
failed. Do not go hunting for a reading that agrees with the change.

Two things this deliberately prints that are easy to omit and fatal to omit:
the window ACTUALLY covered (never the one requested -- the logs API returns the
newest N lines inside a window), and the DENOMINATOR next to every count.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import subprocess
import sys

# Deploy that shipped the telemetry: 33b181ee, live 2026-09-03T04:20:45Z.
DEFAULT_SINCE = "2026-09-03T04:20:45Z"

# Pre-change baseline, BUILD_SPAN_ENTER stage=pull_hot_artifacts, refresh-worker,
# covered 2026-09-02T12:42:56Z -> 2026-09-03T02:16:34Z (13.6 h, 341 lines).
BASELINE = {
    "today": {"n": 46, "median_s": 940.8},
    "non_today": {"n": 5, "median_s": 3854.1, "min_s": 1331.2},
}


def logs(text: str, since: str) -> dict:
    out = subprocess.run(
        [sys.executable, "scripts/render_logs.py", "--service", "refresh-worker",
         "--text", text, "--start", since, "--json"],
        capture_output=True)
    body = out.stdout.decode("utf-8", "replace")
    try:
        return json.loads(body)
    except Exception:
        print("could not parse render_logs output for %r:" % text)
        print(body[:600])
        return {"lines": [], "matches": 0, "covered": {"start": None, "end": None}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=DEFAULT_SINCE)
    args = ap.parse_args(argv)

    # ---------- the predicate: ENQUEUES ----------
    doc = logs("BOARD_WINDOW_", args.since)
    cov = doc.get("covered") or {}
    print("requested since : %s" % args.since)
    print("COVERED         : %s -> %s   (%d line(s))"
          % (cov.get("start"), cov.get("end"), doc.get("matches", 0)))
    if not doc.get("matches"):
        print("\nNO TELEMETRY LINES. Either the loop has not ticked, or the deployed")
        print("commit does not carry them -- check the live SHA before concluding.")
        return 2

    gated = collections.Counter()
    admitted = collections.Counter()
    floors = collections.Counter()
    gated_elapsed = collections.defaultdict(list)
    for line in doc["lines"]:
        msg = line["message"]
        m = re.search(r"BOARD_WINDOW_QUEUE_GATED date=(\S+) elapsed_s=(\S+) floor_s=(\S+)", msg)
        if m:
            gated[m.group(1)] += 1
            floors[m.group(3)] += 1
            try:
                gated_elapsed[m.group(1)].append(float(m.group(2)))
            except ValueError:
                pass
            continue
        m = re.search(r"BOARD_WINDOW_QUEUED date=(\S+) throttled=(\S+) .*floor_s=(\S+)", msg)
        if m:
            admitted[m.group(1)] += 1
            floors[m.group(3)] += 1

    print("floor_s seen    : %s" % dict(floors))
    print()
    print("%-14s %8s %10s %10s   %s" % ("date", "GATED", "ADMITTED", "clip rate", "note"))
    dates = sorted(set(gated) | set(admitted))
    for d in dates:
        g, a = gated[d], admitted[d]
        total = g + a
        rate = ("%.0f%%" % (100.0 * g / total)) if total else "n/a"
        note = ""
        if g and gated_elapsed[d]:
            note = "gated elapsed_s med=%.0f" % statistics.median(gated_elapsed[d])
        print("%-14s %8d %10d %10s   %s" % (d, g, a, rate, note))

    non_today = [d for d in dates if admitted[d] and d != min(dates)]
    print()
    tg = sum(gated[d] for d in dates if d != min(dates))
    ta = sum(admitted[d] for d in dates if d != min(dates))
    if tg + ta == 0:
        print("VERDICT: no non-today enqueue attempts observed -- window too short.")
        return 2
    rate = 100.0 * tg / (tg + ta)
    print("NON-TODAY clip rate: %d/%d = %.0f%%" % (tg, tg + ta, rate))
    if tg == 0:
        print("VERDICT: the floor CLIPPED NOTHING. That is a real result -- the queue")
        print("         coalesces and the floor is the WRONG LEVER. Do not re-tune it.")
    else:
        print("VERDICT: the floor IS clipping. It is now a live constraint on")
        print("         non-today enqueues, which it was not at 600 s.")

    # ---------- the weak proxy, for continuity with the baseline ----------
    spans = logs("BUILD_SPAN_ENTER", args.since)
    per = collections.defaultdict(list)
    for line in spans.get("lines", []):
        m = re.search(r"BUILD_SPAN_ENTER stage=(\S+) date=(\S+)", line["message"])
        if m and m.group(1) == "pull_hot_artifacts":
            per[m.group(2)].append(line["timestamp"])
    print()
    print("BUILD spans (the WEAK proxy -- kept only for continuity with the baseline;")
    print("it cannot separate a clipped enqueue from a capacity-limited build):")
    for d in sorted(per):
        ts = sorted(per[d])
        gaps = []
        for a, b in zip(ts, ts[1:]):
            import datetime as _dt
            pa = _dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
            pb = _dt.datetime.fromisoformat(b.replace("Z", "+00:00"))
            gaps.append((pb - pa).total_seconds())
        med = ("%.1f" % statistics.median(gaps)) if gaps else "-"
        print("   date=%s  builds=%d  gaps=%d  median=%s s" % (d, len(ts), len(gaps), med))
    print()
    print("BASELINE (pre-change, 13.6 h): today n=%d med=%.1f s ; non-today n=%d "
          "med=%.1f s min=%.1f s"
          % (BASELINE["today"]["n"], BASELINE["today"]["median_s"],
             BASELINE["non_today"]["n"], BASELINE["non_today"]["median_s"],
             BASELINE["non_today"]["min_s"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
