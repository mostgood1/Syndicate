"""Did wnba totals pricing actually become REACHABLE in production? (`#499`)

WHAT THIS PROVES, and the one thing it must never do.

`d06a70d4` enabled totals pricing; `8d5d6edf` fixed the fact that it had shipped
INERT (the `sport=sport` edit silently did not apply, so `hit.get("sport")` was
None and totals refused as UNCALIBRATED while all 128 tests passed).

So the question is NOT "is the maths right" -- it is "is the code REACHED".
The proof is a change in the REFUSAL REASON:

    analytic_estimator_never_backtested_for_this_market   <- category-wide, INERT
    prob_interval_swamps_edge                             <- per-row, edge-aware, LIVE

A high `priceable` count is NOT the success signal and would be a BUG signal. At
the measured sigma=0.150 the 2-sigma bar is ~30pp; almost nothing should clear
it. Volume here means the interval is not being applied.

THE FAILURE THIS GUARDS AGAINST. An earlier verifier in this repo printed
VERIFIED having compared ZERO rows -- wrong field names plus a `continue` that
left the counter at 0. A board with no live games returns `index_size: 0` and
an EMPTY `withheld_by_reason`, which is indistinguishable from a broken feature.
So: **zero rows considered exits 3 (NOTHING CHECKABLE), never 0.** A null result
must never be able to read as a pass.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

BOARD = "https://syndicate-an21.onrender.com/api/board/book-grid?sport=wnba"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"

REASON_INERT = "analytic_estimator_never_backtested_for_this_market"
REASON_LIVE = "prob_interval_swamps_edge"


def _get(url: str, timeout: int = 120):
    with urllib.request.urlopen(url, timeout=timeout) as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    # State of the world FIRST, so a zero reading can be attributed.
    live_games = []
    try:
        for ev in _get(ESPN, 60).get("events", []):
            comp = ev["competitions"][0]
            state = comp["status"]["type"]["state"]
            if state == "in":
                live_games.append(f"{ev['shortName']} {comp['status']['type']['detail']}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN could not read espn: {exc}")

    board = _get(BOARD)
    lg = board.get("live_gamelines") or {}
    considered = int(lg.get("rows_live_gameline_considered") or 0)
    reasons = lg.get("withheld_by_reason") or {}

    print(f"espn live games   : {len(live_games)}")
    for g in live_games:
        print(f"  {g}")
    print(f"index_size        : {lg.get('index_size')}")
    print(f"considered        : {considered}")
    print(f"projected         : {lg.get('rows_live_gameline_projected')}")
    print(f"priceable         : {lg.get('rows_live_gameline_priceable')}")
    print(f"withheld          : {lg.get('rows_live_gameline_withheld')}")
    print("withheld_by_reason:")
    for key, val in sorted(reasons.items(), key=lambda kv: -int(kv[1] or 0)):
        print(f"  {val:6}  {key}")

    if considered <= 0:
        # THE GUARD. Not a pass and not a fail -- no evidence either way.
        print(f"\nNOTHING CHECKABLE: considered={considered}, "
              f"espn_live={len(live_games)}. This reading proves nothing about "
              f"`#499`; it looks identical whether the feature works or is inert.")
        return 3

    inert = int(reasons.get(REASON_INERT) or 0)
    live = int(reasons.get(REASON_LIVE) or 0)
    priceable = int(lg.get("rows_live_gameline_priceable") or 0)

    print()
    if inert > 0:
        print(f"FAIL INERT: {inert} rows still refuse as {REASON_INERT!r}. "
              f"The pricing is NOT reached in production.")
        return 1
    if live > 0:
        print(f"PASS REACHABLE: {live} rows refuse as {REASON_LIVE!r} -- per-row "
              f"and edge-aware, so the interval IS being applied.")
        if priceable > live:
            print(f"  BUT SUSPICIOUS: priceable={priceable} exceeds withheld={live}. "
                  f"At sigma=0.150 the bar is ~30pp; volume here suggests the "
                  f"interval is not being applied. INVESTIGATE.")
            return 1
        print(f"  priceable={priceable} (expected at or near 0 -- correct refusal).")
        return 0
    print(f"INCONCLUSIVE: {considered} rows considered but neither reason present. "
          f"Reasons seen: {sorted(reasons)}")
    return 3


if __name__ == "__main__":
    sys.exit(main())
