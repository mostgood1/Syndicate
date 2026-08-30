"""The venue-basis reading: is the in-play comparison RUNNING, and what does it say?

Run against production after a refresh-worker deploy.

--------------------------------------------------------------------------
WHY THIS REFUSES INSTEAD OF REPORTING ZERO
--------------------------------------------------------------------------

"No live venue edges exist" and "the comparison never ran" produce the SAME
number, and they call for opposite actions. This repo has paid for that
confusion repeatedly -- most recently `#603`, "verified" three times where a
collision was arithmetically impossible in every reading, and `#382`, where a
fixed-field fan-out dropped a measurement and the floor it fed read 0 rows in
production while its unit tests passed.

So this separates four populations and never collapses them:

    LIVE ROWS                     the slate
      + a VENUE PRICE             the population that COULD carry a verdict
        + the `venue_basis` KEY   proof the attach AND the fan-out both ran
          + displayable           the actual finding

A zero at the third level is a WIRING failure. A zero at the fourth is a
FINDING. Reporting "0 edges" without the third level is the mistake.

Exit codes:  0 measured   2 error/refused   3 UNMEASURABLE (no population)

--------------------------------------------------------------------------
AND THE BUILD-STAMP GATE
--------------------------------------------------------------------------

`/api/board/layer2-shortlist` is a PURE READ of a worker-built artifact. A pool
written before the deploy reports the old code forever, so `--after <iso>`
refuses a board whose `written_at` does not cross it. Elapsed time is a fact
about you, not about the system.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

BASE = os.environ.get("SYNDICATE_BASE_URL", "https://syndicate-an21.onrender.com")
VENUE_BOOKS = ("kalshi", "polymarket", "polymarket_us")
EXIT_OK, EXIT_ERROR, EXIT_UNMEASURABLE = 0, 2, 3


def _admin_token() -> str:
    token = (os.environ.get("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    try:
        with open(".env", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("ADMIN_TOKEN"):
                    return line.split("=", 1)[1].strip().strip('"').strip()
    except OSError:
        pass
    return ""


def _board(date: str, token: str) -> dict:
    url = f"{BASE}/api/board/layer2-shortlist?date={date}&limit=3000"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def _short(reason: str, width: int = 88) -> str:
    text = " ".join(str(reason or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--after", help="ISO instant the board's written_at must EXCEED")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    token = _admin_token()
    if not token:
        print("ADMIN_TOKEN not found in env or .env", file=sys.stderr)
        return EXIT_ERROR
    try:
        payload = _board(args.date, token)
    except Exception as exc:  # noqa: BLE001
        print(f"board read failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    written = payload.get("written_at")
    if args.after:
        try:
            stamp = datetime.fromisoformat(str(written).replace("Z", "+00:00"))
            floor = datetime.fromisoformat(args.after.replace("Z", "+00:00"))
            if floor.tzinfo is None:
                floor = floor.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            print(f"unreadable written_at={written!r} / --after={args.after!r}", file=sys.stderr)
            return EXIT_ERROR
        if stamp <= floor:
            print(
                f"REFUSED: board written_at {written} does NOT cross --after {args.after}.\n"
                "  That pool was built by the OLD code. This endpoint is a pure read of a\n"
                "  worker-built artifact, so waiting changes nothing until it rebuilds.",
                file=sys.stderr,
            )
            return EXIT_ERROR

    rows = payload.get("rows") or []
    live = [r for r in rows if r.get("is_live")]

    population, keyed, displayable = [], [], []
    for row in live:
        quote = row.get("quote") or {}
        books = quote.get("book_prices") or {}
        if not any(b in books for b in VENUE_BOOKS):
            continue
        population.append(row)
        if "venue_basis" not in quote:
            continue
        keyed.append(row)
        basis = quote.get("venue_basis")
        if isinstance(basis, dict) and basis.get("displayable"):
            displayable.append((row, basis))

    reasons = collections.Counter()
    venues = collections.Counter()
    bounded = 0
    for row in keyed:
        basis = (row.get("quote") or {}).get("venue_basis")
        if not isinstance(basis, dict):
            reasons["<null: the venue never quoted this side>"] += 1
            continue
        venues[str(basis.get("venue"))] += 1
        if basis.get("fee_is_upper_bound"):
            bounded += 1
        if not basis.get("displayable"):
            reasons[_short(basis.get("reason"))] += 1

    out = {
        "written_at": written,
        "rows": len(rows),
        "live_rows": len(live),
        "live_with_venue_price": len(population),
        "carrying_venue_basis_key": len(keyed),
        "displayable": len(displayable),
        "by_venue": dict(venues),
        "fee_upper_bound_rows": bounded,
        "refusals": dict(reasons),
        "edges": [
            {
                "sport": r.get("sport"),
                "game": f"{r.get('away_team')}@{r.get('home_team')}",
                "market": r.get("market"),
                "side": r.get("side"),
                "line": r.get("line"),
                "edge_pct": b.get("edge_pct"),
                "venue": b.get("venue"),
                "venue_probability": b.get("venue_probability"),
                "consensus_probability": b.get("consensus_probability"),
                "fee": b.get("venue_fee_per_contract"),
                "fee_is_upper_bound": b.get("fee_is_upper_bound"),
                "servable": b.get("servable"),
            }
            for r, b in sorted(
                displayable, key=lambda p: -abs(float(p[1].get("edge_pct") or 0.0))
            )
        ],
    }

    if args.json:
        print(json.dumps(out, indent=2))
        return EXIT_OK if population else EXIT_UNMEASURABLE

    print(f"board written_at={written}  rows={len(rows)}  live={len(live)}\n")
    print(f"  live rows with a venue price   {len(population):5d}   <- the population")
    print(f"  carrying the venue_basis key   {len(keyed):5d}   <- attach + fan-out both ran")
    print(f"  displayable                    {len(displayable):5d}   <- the finding")
    if venues:
        print(f"  by venue                       {dict(venues)}")
        print(f"  fee is an upper bound on       {bounded} row(s) (kalshi series multiplier absent)")

    if not population:
        print(
            "\nOVERALL: UNMEASURABLE -- no LIVE row carried a venue price, so the\n"
            "  comparison had nothing to run on. This is NOT evidence it works or\n"
            "  that no edges exist. Re-run when games are in progress."
        )
        return EXIT_UNMEASURABLE

    if not keyed:
        print(
            f"\nOVERALL: NOT WIRED -- {len(population)} live rows carried a venue price and\n"
            "  NONE carried the `venue_basis` key. The population existed and the\n"
            "  annotation is absent, so this is the attach or the board fan-out, NOT\n"
            "  an absence of edges. Check the deployed SHA contains the carry."
        )
        return EXIT_ERROR

    if out["edges"]:
        print("\n  EDGES (display-only; none of these is servable):")
        for e in out["edges"]:
            bound = " (fee is an UPPER BOUND)" if e["fee_is_upper_bound"] else ""
            print(
                f"    {e['edge_pct']:+7.2f} pts  {e['venue']:11s} {e['sport']:6s}"
                f" {e['market']:10s} {e['side']}"
                f"{'' if e['line'] is None else ' ' + str(e['line'])}  {e['game']}"
            )
            print(
                f"             venue {e['venue_probability']} + fee {e['fee']}"
                f" vs consensus {e['consensus_probability']}{bound}"
            )
    if reasons:
        print("\n  REFUSALS (a zero must be attributable, never bare):")
        for reason, count in reasons.most_common():
            print(f"    {count:4d}  {reason}")

    print(
        f"\nOVERALL: MEASURED -- the comparison ran on {len(keyed)} of {len(population)} "
        f"eligible live rows and found {len(displayable)} displayable."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
