"""Did wnba totals pricing actually become REACHABLE in production? (`#499`)

WHAT THIS PROVES, and the one thing it must never do.

`d06a70d4` enabled totals pricing; `8d5d6edf` fixed the fact that it had shipped
INERT (the `sport=sport` edit silently did not apply, so `hit.get("sport")` was
None and totals refused as UNCALIBRATED while all 128 tests passed).

So the question is NOT "is the maths right" -- it is "is the code REACHED".

WHY THIS FILE WAS REWRITTEN 2026-08-21. The first version watched for a flip
from `analytic_estimator_never_backtested_for_this_market` to
`prob_interval_swamps_edge`, and reported `3 NOTHING CHECKABLE` on a live slate
that had ALREADY PROVED reachability. Two defects, both of which made a PASS
look like an absence of evidence:

  1. It read the CATEGORY-WIDE `withheld_by_reason` map, which is not scoped by
     market. The 223 `analytic_probability_is_only_valid_at_its_own_line` there
     mixes spreads and totals, and a SPREAD refusing by line says nothing about
     totals. Reachability is a claim about a TOTALS row, so it has to be read
     off one.

  2. `prob_interval_swamps_edge` is not the only proof, and on a real board it
     is not even the likely one. In `live_gameline_join.py`,
     `price_analytic_line_market()` resolves
     `ANALYTIC_LIVE_STD_ERR_BY_MARKET.get((sport_key, "totals"))` at :609 and
     returns REASON_ANALYTIC_UNCALIBRATED at :612 -- STRICTLY BEFORE the
     line-match test that returns REASON_ANALYTIC_LINE_MISMATCH at :624.

     So a TOTALS row carrying `..._only_valid_at_its_own_line` could only have
     reached :624 with `totals_sigma` non-None. That IS the reachability proof:
     `sport_key == "wnba"` resolved and the 0.150 entry was found.

THE TWO QUESTIONS ARE NOW REPORTED SEPARATELY, because they have different
answers and conflating them is what produced the wrong verdict:

  REACHED?  -- did a totals row get PAST the calibration lookup?
  APPLIED?  -- did the sigma=0.150 interval ever actually price or refuse a row?

As of 2026-08-21 the honest state is REACHED=yes, APPLIED=never observed: 0 of
65 totals rows matched their lens line, so none reached `price_moneyline`. That
is `#500`, and it is a real open risk -- reached-but-never-clearing is inert in
outcome. This script must be able to say "reached, not applied" without that
reading as either a pass or a failure of `#499`.

A high priced count is NOT the success signal and would be a BUG signal. At
sigma=0.150 the 2-sigma bar is ~30pp; almost nothing should clear it.

THE FAILURE THIS GUARDS AGAINST. An earlier verifier in this repo printed
VERIFIED having compared ZERO rows. A board with no live games returns
`index_size: 0` and an EMPTY `withheld_by_reason`, which is indistinguishable
from a broken feature. So: **zero TOTALS rows examined exits 3 (NOTHING
CHECKABLE), never 0.** A null result must never be able to read as a pass.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import urllib.request

BOARD = "https://syndicate-an21.onrender.com/api/board/book-grid?sport=wnba"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"

REASON_INERT = "analytic_estimator_never_backtested_for_this_market"
REASON_INTERVAL = "prob_interval_swamps_edge"
REASON_LINE = "analytic_probability_is_only_valid_at_its_own_line"

TOTALS_MARKETS = {"totals", "totals_alt"}


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
            if comp["status"]["type"]["state"] == "in":
                live_games.append(f"{ev['shortName']} {comp['status']['type']['detail']}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN could not read espn: {exc}")

    board = _get(BOARD)
    lg = board.get("live_gamelines") or {}
    considered = int(lg.get("rows_live_gameline_considered") or 0)
    reasons = lg.get("withheld_by_reason") or {}

    # PER-ROW, and scoped to totals -- the category-wide map cannot answer this.
    rows = board.get("rows") or []
    totals_reason: collections.Counter = collections.Counter()
    for row in rows:
        if str(row.get("market") or "").lower() not in TOTALS_MARKETS:
            continue
        block = row.get("live_gameline")
        if not isinstance(block, dict):
            continue
        if block.get("priceable"):
            totals_reason["<PRICED>"] += 1
        else:
            totals_reason[str(block.get("withheld_reason") or "<unspecified>")] += 1
    totals_seen = sum(totals_reason.values())

    print(f"espn live games   : {len(live_games)}")
    for game in live_games:
        print(f"  {game}")
    print(f"index_size        : {lg.get('index_size')}")
    print(f"considered        : {considered}")
    print(f"projected         : {lg.get('rows_live_gameline_projected')}")
    print(f"priceable         : {lg.get('rows_live_gameline_priceable')}")
    print(f"withheld          : {lg.get('rows_live_gameline_withheld')}")
    print("withheld_by_reason (ALL markets -- context only, NOT the verdict):")
    for key, val in sorted(reasons.items(), key=lambda kv: -int(kv[1] or 0)):
        print(f"  {val:6}  {key}")
    print(f"TOTALS rows in served slice ({len(rows)} of "
          f"{board.get('total_rows')} rows returned): {totals_seen}")
    for key, val in sorted(totals_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {val:6}  {key}")

    if totals_seen <= 0:
        # THE GUARD. Not a pass and not a fail -- no evidence either way.
        print(f"\nNOTHING CHECKABLE: 0 totals rows carried a live_gameline block "
              f"(considered={considered}, espn_live={len(live_games)}). This "
              f"reading proves nothing about `#499`; it looks identical whether "
              f"the feature works or is inert.")
        return 3

    inert = totals_reason.get(REASON_INERT, 0)
    interval = totals_reason.get(REASON_INTERVAL, 0)
    line_mismatch = totals_reason.get(REASON_LINE, 0)
    priced = totals_reason.get("<PRICED>", 0)

    print()
    if inert > 0:
        print(f"FAIL INERT: {inert} TOTALS rows still refuse as {REASON_INERT!r}. "
              f"The calibration lookup did not find ('wnba','totals') -- pricing "
              f"is NOT reached in production.")
        return 1

    # REACHED? Any totals row at or past the line-match gate proves the
    # calibration lookup succeeded, because :612 returns before :624.
    reached = interval + line_mismatch + priced
    if reached <= 0:
        print(f"INCONCLUSIVE: {totals_seen} totals rows examined, none of which "
              f"reached the analytic gate. Reasons seen: {sorted(totals_reason)}")
        return 3

    print(f"PASS REACHED: {reached} TOTALS rows got PAST the calibration lookup "
          f"at live_gameline_join.py:612 (which returns {REASON_INERT!r} when the "
          f"sport/market pair is absent). sport_key resolved and 0.150 was found.")

    # APPLIED? A separate question, with a separate answer.
    if interval > 0 or priced > 0:
        print(f"  INTERVAL APPLIED: priced={priced}, "
              f"refused_by_interval={interval} ({REASON_INTERVAL!r}).")
        if priced > interval:
            print(f"  BUT SUSPICIOUS: priced={priced} exceeds "
                  f"refused_by_interval={interval}. At sigma=0.150 the bar is "
                  f"~30pp; volume here suggests the interval is not being "
                  f"applied. INVESTIGATE.")
            return 1
    else:
        print(f"  INTERVAL NOT YET APPLIED: all {line_mismatch} reached rows "
              f"stopped at {REASON_LINE!r}, so none entered price_moneyline. "
              f"`#499` is REACHED but its interval stays unobserved -- see `#500` "
              f"(analytic_line is not surfaced, so this cannot be diagnosed from "
              f"the served board).")

    if args.json:
        print(json.dumps({
            "espn_live": len(live_games),
            "considered": considered,
            "totals_seen": totals_seen,
            "totals_by_reason": dict(totals_reason),
            "reached": reached,
            "interval_applied": bool(interval or priced),
        }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
