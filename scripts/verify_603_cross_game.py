"""`#603` verification: do venue quotes still answer the WRONG GAME?

Run this against production. It answers ONE question and refuses to answer it
when it cannot.

--------------------------------------------------------------------------
THE COLLIDABILITY PRECHECK IS THE POINT OF THIS SCRIPT
--------------------------------------------------------------------------

`#603` was "verified" three times on 2026-08-29/30 and every reading was
worthless, twice for the same reason:

    polymarket ncaaf   live=5   sharing=0   <- 5 rows, 5 distinct (side,line)
    kalshi     mlb     live=7   sharing=0   <- 7 rows, 7 distinct (side,line)

**A collision was arithmetically impossible in both.** No two live games shared
a `(side, line)`, so the count would have read 0 with the fix, without the fix,
and with the whole module deleted. A zero that cannot be a one is not evidence.

So this script computes COLLIDABLE first -- how many `(side, line)` keys are
claimed by more than one live game -- and reports every population as one of:

    UNMEASURABLE  no collidable pair existed; the reading proves NOTHING
    PASS          collidable pairs existed and NONE shared a price
    FAIL          collidable pairs existed and at least one shared a price

`UNMEASURABLE` is a first-class outcome, not a soft pass. Exit code 3.

--------------------------------------------------------------------------
AND THE BUILD-STAMP GATE, for the same reason
--------------------------------------------------------------------------

`/api/board/layer2-shortlist` is a PURE READ of a worker-built artifact. It
computes nothing at request time, so a pool written before your deploy will
happily report the old behaviour forever. `--after <iso>` refuses to read a
pool whose `written_at` does not cross it. Elapsed time is a fact about you,
not about the system.
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
TOTALS_MARKETS = {"totals", "totals_alt"}
EXIT_OK, EXIT_FAIL, EXIT_ERROR, EXIT_UNMEASURABLE = 0, 1, 2, 3


def _admin_token() -> str:
    token = (os.environ.get("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    # The gitignored .env is where this lives on a dev machine. Read rather
    # than required-in-argv so the secret never reaches a log or a shell history.
    try:
        with open(".env", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("ADMIN_TOKEN"):
                    return line.split("=", 1)[1].strip().strip('"').strip()
    except OSError:
        pass
    return ""


def _board(date: str, token: str) -> dict:
    url = f"{BASE}/api/board/layer2-shortlist?date={date}&limit=2000"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read())


def _venue_price(row: dict, source: str):
    return ((row.get("quote") or {}).get("book_prices") or {}).get(source)


def census(rows, source: str, sport: str) -> dict:
    """Collidability FIRST, then sharing. Never sharing alone."""
    live = [
        r
        for r in rows
        if r.get("sport") == sport
        and r.get("market") in TOTALS_MARKETS
        and r.get("is_live")
        and _venue_price(r, source) is not None
    ]
    by_key: dict = collections.defaultdict(set)
    for row in live:
        by_key[(row.get("side"), row.get("line"))].add(
            f"{row.get('away_team')}@{row.get('home_team')}"
        )
    collidable = {k: v for k, v in by_key.items() if len(v) > 1}

    shared = []
    for (side, line), games in collidable.items():
        prices = {
            _venue_price(r, source)
            for r in live
            if r.get("side") == side and r.get("line") == line
        }
        # ONE price across two or more games on the same (side, line) is the
        # defect. Distinct prices is the fix working -- each game answered by
        # its own quote.
        if len(prices) == 1:
            shared.append({"side": side, "line": line, "games": sorted(games), "price": prices.pop()})

    if not collidable:
        verdict = "UNMEASURABLE"
    elif shared:
        verdict = "FAIL"
    else:
        verdict = "PASS"
    return {
        "verdict": verdict,
        "live_rows": len(live),
        "distinct_side_line": len(by_key),
        "collidable_keys": len(collidable),
        "shared": shared,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="slate date, YYYY-MM-DD")
    parser.add_argument(
        "--after",
        help="ISO instant the board's written_at must EXCEED (normally the deploy time)",
    )
    parser.add_argument("--sports", default="mlb,ncaaf,soccer,wnba,nfl")
    parser.add_argument("--sources", default="kalshi,polymarket")
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
            print(f"unreadable written_at={written!r} or --after={args.after!r}", file=sys.stderr)
            return EXIT_ERROR
        if stamp <= floor:
            print(
                f"REFUSED: board written_at {written} does NOT cross --after {args.after}.\n"
                "  That pool was built by the OLD code. This endpoint is a pure read of a\n"
                "  worker-built artifact, so waiting longer changes nothing until it rebuilds.",
                file=sys.stderr,
            )
            return EXIT_ERROR

    rows = payload.get("rows") or []
    results = {}
    for source in [s.strip() for s in args.sources.split(",") if s.strip()]:
        for sport in [s.strip() for s in args.sports.split(",") if s.strip()]:
            out = census(rows, source, sport)
            if out["live_rows"]:
                results[f"{source}/{sport}"] = out

    if args.json:
        print(json.dumps({"written_at": written, "rows": len(rows), "results": results}, indent=2))
    else:
        print(f"board written_at={written}  rows={len(rows)}\n")
        print(f"{'source/sport':22s} {'live':>5s} {'keys':>5s} {'collidable':>11s}  verdict")
        for name, out in sorted(results.items()):
            print(
                f"{name:22s} {out['live_rows']:5d} {out['distinct_side_line']:5d}"
                f" {out['collidable_keys']:11d}  {out['verdict']}"
            )
            for hit in out["shared"]:
                print(f"     !! {hit['side']} {hit['line']} @ {hit['price']} -> {hit['games']}")
        print()

    verdicts = {out["verdict"] for out in results.values()}
    if "FAIL" in verdicts:
        print("OVERALL: FAIL -- at least one collidable pair still shares one price")
        return EXIT_FAIL
    if "PASS" in verdicts:
        print("OVERALL: PASS -- every collidable pair was answered by distinct prices")
        return EXIT_OK
    print(
        "OVERALL: UNMEASURABLE -- no population had two live games sharing a (side, line).\n"
        "  This is NOT a pass. Re-run when more games are live concurrently."
    )
    return EXIT_UNMEASURABLE


if __name__ == "__main__":
    raise SystemExit(main())
