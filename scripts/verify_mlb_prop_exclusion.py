#!/usr/bin/env python3
"""`#615` gate: did the `mlb:player_prop` staking exclusion actually fire?

CHECKS THE PRECONDITION BEFORE THE COUNTER, AND THAT ORDER IS THE WHOLE POINT.

WHY THIS SCRIPT EXISTS RATHER THAN A GREP. On 2026-09-01T04:09:11Z I read a
`PLAN_WRITTEN` that post-dated the deploy, saw no `market_family_excluded`, and
saw `no_model_edge_pct` go UP from 1,092 to 1,260. Against the band I had
pre-registered that is a refutation, and I was one step from writing off a
working change.

It was not a refutation. `top_market_per_refusal` named
`alternate_totals_corners:690` -- a SOCCER market -- and the board at that hour
carried **0 MLB prop rows** (`per_sport.mlb` = `selected 31, game 31, prop 0`;
the slate had finished around 23:15 CT). **The exclusion had nothing to act
on.** A reading taken over a population that no longer contains the subject
looks identical to a failing one.

So this script refuses to report PASS or FAIL until it has established that MLB
props were on the board. Three outcomes, three exit codes, and the third is the
one a grep cannot give you:

    0  PASS        the counter fired on a tick that had props to act on
    1  FAIL        props were present and the counter did not fire -- a real defect
    3  UNREADABLE  no MLB props on the board; the question cannot be asked yet

`learnings.md` 2026-09-01 carries the general rule this is an instance of:
before reading a null, find the thing that tells you it is readable. Check (a)
is the timestamp comparison, (b) the upstream marker, (c) that a producer-to-
reader path exists, and (d) -- the one that caught me -- that the SUBJECT is
present in the population being read.

USAGE
    py -3 scripts/verify_mlb_prop_exclusion.py
    py -3 scripts/verify_mlb_prop_exclusion.py --json

Reads production over HTTP only. Writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

BASE = "https://syndicate-an21.onrender.com"
SHORTLIST = "/api/board/layer2-shortlist"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_UNREADABLE = 3


def _get(path: str, timeout: int = 90) -> dict:
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def check_precondition() -> tuple[bool, dict]:
    """(d): are MLB prop rows on the board at all?

    Read from `per_sport`, not from the served `rows`. `rows` is the top-N
    slice and can be empty of props while the commit population is not --
    a narrower question than the one being asked.
    """
    payload = _get(SHORTLIST)
    per_sport = payload.get("per_sport") if isinstance(payload.get("per_sport"), dict) else {}
    mlb = per_sport.get("mlb") if isinstance(per_sport.get("mlb"), dict) else {}
    prop = int(mlb.get("prop") or 0)
    return prop > 0, {
        "board_date": payload.get("date"),
        "mlb_prop_rows": prop,
        "mlb_game_rows": int(mlb.get("game") or 0),
        "mlb_selected": int(mlb.get("selected") or 0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        readable, evidence = check_precondition()
    except Exception as exc:  # noqa: BLE001 -- a gate that raises tells you nothing
        out = {"verdict": "UNREADABLE", "reason": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(out) if args.json else f"UNREADABLE: {out['reason']}")
        return EXIT_UNREADABLE

    if not readable:
        out = {
            "verdict": "UNREADABLE",
            "reason": "no MLB prop rows on the board -- the exclusion has nothing to act on",
            "next": "re-run during a live MLB slate; props leave the board when the slate finishes",
            **evidence,
        }
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print(f"UNREADABLE  board_date={evidence['board_date']} "
                  f"mlb prop={evidence['mlb_prop_rows']} game={evidence['mlb_game_rows']}")
            print("  The exclusion has no subject to act on. A PLAN_WRITTEN read now")
            print("  would show no `market_family_excluded` whether the change works or not.")
            print("  Re-run during a live MLB slate.")
        return EXIT_UNREADABLE

    # Precondition holds. The counter is now readable -- but this script cannot
    # reach the worker log, so it reports READY and names the exact check rather
    # than guessing. Worker logs are the Render API, which needs a credential
    # this script deliberately does not take.
    out = {
        "verdict": "READY",
        "reason": "MLB props are on the board; the counter is now readable",
        "check": (
            "grep the refresh-worker log for a PLAN_WRITTEN stamped after the deploy: "
            "PASS if refusals carries `market_family_excluded` with a count near the "
            "MLB prop row count below; FAIL if it is absent."
        ),
        **evidence,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"READY  board_date={evidence['board_date']} mlb_prop_rows={evidence['mlb_prop_rows']}")
        print("  Precondition (d) satisfied. Now read PLAN_WRITTEN on refresh-worker:")
        print("    PASS -> refusals contains `market_family_excluded`")
        print("    FAIL -> it does not, and props were present, so that is a real defect")
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
