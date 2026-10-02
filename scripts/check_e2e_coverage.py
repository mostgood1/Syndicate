"""The end-to-end coverage gate: is every active sport's state KNOWABLE?

`[2026-09-29, lane e2e-coverage-contract]`. Prints one matrix over
(sport x {pregame, live} x {games, props}) and exits non-zero when any cell is
in a state that makes "end to end working" unverifiable.

WHAT IT FAILS ON, and what it deliberately does NOT:

  FAILS  `unattributed_zero` -- a zero with no stated reason. Unactionable: there
         is no way to tell a code gap from an empty slate, so it is a defect of
         the instrument rather than of the sport.
  FAILS  `not_reported` -- the sport emits no such metric. That is schema drift,
         and it is the failure mode that misreported MLB's 87.6% as 0% while this
         matrix was being built.
  PASSES `attributed_zero` -- a zero WITH a reason ("no live re-sim wired for
         nhl", "no soccer match in play"). A known gap is not an instrument
         defect, and failing on it would make the gate red for months over work
         that is already tracked in a lane.
  PASSES `degraded` -- partial coverage. Thresholds belong in a recorded
         baseline, not in a first gate; a floor invented here would encode an
         assumption about a healthy rate that nobody has measured per sport.

    py -3 scripts/check_e2e_coverage.py
    py -3 scripts/check_e2e_coverage.py --base-url http://127.0.0.1:5000
    py -3 scripts/check_e2e_coverage.py --payload reports/shortlist.json --json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.coverage_contract import (  # noqa: E402
    CELLS, NOT_REPORTED, UNATTRIBUTED_ZERO, all_defects, read_shortlist,
)

try:
    from scripts._base_url import default_base_url
except ImportError:  # run as `python scripts/<name>.py`
    from _base_url import default_base_url

DEFAULT_BASE = default_base_url()
_LABEL = {"pregame_games": "PRE games", "pregame_props": "PRE props",
          "live_games": "LIVE games", "live_props": "LIVE props"}


def fetch(base_url: str, timeout: int) -> dict:
    url = base_url.rstrip("/") + "/api/board/layer2-shortlist"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--payload", default="", help="read a saved shortlist JSON instead of HTTP")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--json", action="store_true", help="emit the matrix as JSON")
    args = ap.parse_args(argv)

    if args.payload:
        payload = json.loads(pathlib.Path(args.payload).read_text(encoding="utf-8"))
        source = args.payload
    else:
        try:
            payload = fetch(args.base_url, args.timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"shortlist unavailable from {args.base_url}: {type(exc).__name__}: {exc}")
            return 2
        source = args.base_url

    matrix = read_shortlist(payload)
    if args.json:
        print(json.dumps({
            s: {"candidates": c.candidates,
                "cells": {n: {"projected": c.cell(n).projected,
                              "considered": c.cell(n).considered,
                              "rate": c.cell(n).rate,
                              "status": c.cell(n).status,
                              "reason": c.cell(n).reason,
                              "source_key": c.cell(n).source_key}
                          for n in CELLS}}
            for s, c in matrix.items()}, indent=2))
    else:
        print(f"source: {source}")
        print(f"written_at: {payload.get('written_at')}   date: {payload.get('date')}")
        print(f"active_sports: {payload.get('active_sports')}\n")
        width = 26
        print(f"{'sport':8} {'cands':>6} " + " ".join(f"{_LABEL[n]:>{width}}" for n in CELLS))
        print("-" * (16 + (width + 1) * len(CELLS)))
        for sport in sorted(matrix):
            cov = matrix[sport]
            row = " ".join(f"{cov.cell(n).describe()[:width]:>{width}}" for n in CELLS)
            # An out-of-season sport is SHOWN and MARKED, never hidden: hiding it
            # would lose that it is reported-but-idle, which is itself worth
            # seeing. The marker is why its cells raise no defect below.
            label = sport if cov.active is not False else f"{sport} (off)"
            print(f"{label:8} {str(cov.candidates):>6} {row}")
        print("\nper-cell status and the key each was resolved from:")
        for sport in sorted(matrix):
            cov = matrix[sport]
            for n in CELLS:
                c = cov.cell(n)
                print(f"  {sport:8} {n:15} {c.status:20} "
                      f"src={c.source_key or '-'}")

    defects = all_defects(matrix)
    inactive = sorted(s for s, c in matrix.items() if c.active is False)
    if inactive:
        # Stated explicitly: a reader must see WHAT was exempted, or the
        # gate's clean verdict is unfalsifiable.
        print("\nnot counted (absent from active_sports, out of season): "
              + ", ".join(inactive))
    print("\n" + "=" * 78)
    if not defects:
        print("PASS: every cell is a number with its denominator, or a zero with a "
              "stated reason.")
        return 0
    print(f"FAIL: {len(defects)} cell(s) make end-to-end state unverifiable")
    print("=" * 78)
    for d in defects:
        kind = UNATTRIBUTED_ZERO if UNATTRIBUTED_ZERO in d else NOT_REPORTED
        why = ("zero with NO stated reason -- a code gap and an empty slate are "
               "indistinguishable here"
               if kind == UNATTRIBUTED_ZERO
               else "this sport emits no such metric -- schema drift, the reader "
                    "cannot see this cell")
        print(f"  {d}\n      {why}")
    print("\nThese are defects of the INSTRUMENT, not coverage gaps. A known gap "
          "carrying a reason passes.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
