#!/usr/bin/env python3
"""Score the arm A fire gate against every captured hour -- POSITIVE AND NEGATIVE.

This exists because arming a detector that has only been reasoned about is how
this lane already produced two pre-firing defects (a metered-MB-only trigger
that would have fired into one human's browsing hour, and a 900 s time guard on
a transfer needing ~1,376 s). Both were caught by exercising the detector
against ground truth rather than reading it.

It imports `arm_a_verdict` from the watcher itself, so what is scored is the
predicate that actually ships -- not a restatement of it that can drift.

The expectation is pre-registered in EXPECTED below, taken from the scoring in
`bandwidth-excess-vs-ratio` (lane note 2026-09-10, evidence `42d4794b`): of the
hours captured, exactly five are anomalous, `09-08 15:00Z` is the false fire the
old `metered/edge >= 6.0` bar admitted and must now be declined, and the hours
with a dead access-line emitter must read UNDECIDABLE rather than firing.

    py -3 scripts/score_arm_a_gate.py

Exits non-zero if the shipped gate disagrees with the pre-registration.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.controlled_transfer_arm2_watch import (  # noqa: E402
    DEFAULT_SPIKE_APP_RATIO, DEFAULT_SPIKE_MB, arm_a_verdict,
)

#: bucket -> expected decision. Only hours over the MB bar can differ, but the
#: quiet ones are listed too so a gate that started firing on them would fail.
EXPECTED = {
    "20260908T000000Z": "ARM_A",
    "20260908T160000Z": "ARM_A",
    "20260908T170000Z": "ARM_A",
    "20260908T180000Z": "ARM_A",
    "20260908T190000Z": "ARM_A",
    # 927.2 MB but metered/app 2.85 -- big, not anomalous. The switch's own
    # scoring puts the anomalous set at five, and this is not in it.
    "20260908T010000Z": "not a spike",
    # THE FALSE FIRE THE OLD GATE ADMITTED: 420.6 MB, edge ratio 7.09 (fires),
    # app ratio 3.05 (does not). This row is the whole reason for the switch.
    "20260908T150000Z": "not a spike",
    # One human browsing for an hour -- the third reader's entry exists to stop
    # this being counted as a spike.
    "20260909T000000Z": "not a spike",
    "20260908T230000Z": "not a spike",
    "20260909T230000Z": "not a spike",
    "20260910T010000Z": "not a spike",
    # Arm 1's own probe hour. 401.1 MB metered, access-line emitter DEAD.
    "20260909T010000Z": "UNDECIDABLE",
}


def main() -> int:
    captures = sorted((REPO_ROOT / "reports" / "bandwidth_spikes").glob("web_*.json"))
    if not captures:
        print("no captures found -- run this in a tree that has reports/bandwidth_spikes/")
        return 2

    failures = []
    fires = []
    unscored = []
    print(f"gate: metered >= {DEFAULT_SPIKE_MB} MB and metered/app >= {DEFAULT_SPIKE_APP_RATIO}")
    print(f"{'bucket':20} {'metered':>9} {'served':>8} {'m/app':>7}  decision")
    for path in captures:
        data = json.loads(path.read_text(encoding="utf-8"))
        bucket = path.name[4:-5]
        app = data.get("app") or {}
        edge = data.get("edge") or {}
        served = app.get("served_mb")
        metered = data.get("metered_mb")
        # A CAPTURE WITH NO `metered_mb` MUST NOT SCORE AS "under MB bar" -- that
        # is the numerator missing, not a small hour, and reading it as a pass is
        # the same permissive-default this gate was rewritten to remove. Two
        # committed captures (`09-09 00:00Z`, `09-09 01:00Z`) carry a null here
        # while the primary tree holds DIFFERENT snapshots of the same hours that
        # have it -- they are not supersets of each other, so neither was
        # overwritten. Every row the switch actually turns on is fully recorded.
        if metered is None:
            unscored.append(bucket)
            print(f"{bucket:20} {'--':>9} {str(served):>8} {'-':>7}  UNSCORED (no metered_mb in this capture)")
            continue
        # A capture records `served_mb: null` when the tripwire itself judged the
        # instrument blind. Feeding 0 access lines through reproduces that here.
        access_lines = app.get("access_lines") or 0
        decision, reason, ratio = arm_a_verdict(
            metered=metered,
            edge_mb=edge.get("mb") or 0.0,
            edge_requests=edge.get("requests") or 0,
            served_mb=served if served is not None else 0.0,
            access_lines=access_lines,
            # Captures are written by `capture()` at 200 pages; the largest hour
            # on record is 15,644 lines, so none of them is truncated.
            covered=True,
            spike_mb=DEFAULT_SPIKE_MB,
            spike_app_ratio=DEFAULT_SPIKE_APP_RATIO,
        )
        if decision == "ARM_A":
            fires.append(bucket)
        expected = EXPECTED.get(bucket, "under MB bar")
        mark = ""
        if decision != expected:
            mark = f"   <-- EXPECTED {expected}"
            failures.append((bucket, expected, decision))
        print(f"{bucket:20} {metered:9.1f} {str(served):>8} "
              f"{(f'{ratio:.2f}' if ratio else '-'):>7}  {decision}{mark}")

    print()
    print(f"fires: {len(fires)} -> {', '.join(fires) if fires else '(none)'}")
    if unscored:
        print(f"UNSCORED (capture has no metered_mb): {len(unscored)} -> {', '.join(unscored)}")
    if failures:
        print(f"MISMATCH on {len(failures)} bucket(s):")
        for bucket, expected, got in failures:
            print(f"  {bucket}: expected {expected}, got {got}")
        return 1
    print("gate agrees with the pre-registration on every captured hour")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
