"""Census DUPLICATE BETS on the Layer 2 shortlist, and say which kind they are.

WHY THIS IS A SCRIPT AND NOT A ONE-OFF. `deploys.md` 2026-09-06 records
`colliding _row_keys 35 -> 4` and `kalshi_only 39 -> 0` for the player-name
fold, and until this landed those numbers were reproducible by exactly one
session. A measurement nobody else can re-take is a claim, not evidence.

WHAT IT MEASURES

    colliding `_row_key`s   two shortlist rows naming the SAME BET.
                            `by_key`/`by_event` in `kalshi_board_join` hold
                            LISTS and the join iterates every candidate, so one
                            venue contract pairs with BOTH -- two separately
                            stakeable rows resolving to one ticker. That is
                            DOUBLE EXPOSURE, not a cosmetic duplicate.

    kalshi_plus_books       prop rows carrying an exchange price INSIDE a
                            multi-book `quote.book_prices`. Price shopping in
                            this board happens WITHIN a row; a second row for
                            one bet is that mechanism failing.

    two-spelling names      a normalised player carrying more than one raw
                            spelling. This is the diacritic split
                            (`Julio Rodriguez` / `Julio Rodriguez` with an i-acute)
                            that `fold_market_identity_term` closed.

THE TWO SIGNALS ARE READ TOGETHER, AND THAT IS THE POINT. A capture outage
drives collisions AND `kalshi_only` to zero exactly like a working fold does --
and drives `kalshi_plus_books` DOWN, where the fold drives it UP. Reporting only
the first would call an outage a fix.

`--baseline` writes the reading to JSON; `--compare` diffs a later run against
it and BUCKETS the keys, because a raw row-count delta cannot tell "a new book
listed a bet nobody else lists" (legitimate new coverage) from "one bet split
into two rows" (the defect). Only the collision count separates them:

    both       present before and after   -- should GAIN books
    after_only genuine new coverage       -- expected, not a fault
    before_only a regression              -- the bucket to actually worry about

`limit=2000` IS NOT OPTIONAL AND IS NOT A TUNING KNOB. The endpoint defaults to
200 and truncates silently. The first census of this defect returned 200 of
1,996 rows and reported ZERO collisions -- a clean bill of health for a defect
that was live. `_board_rows_for_join` reads the artifact directly and is NOT
truncated, so the default hides precisely the rows the join acts on.

Usage:
    py -3 scripts/census_board_row_duplicates.py --date 2026-09-06 --sport mlb
    py -3 scripts/census_board_row_duplicates.py --date 2026-09-06 --baseline before.json
    py -3 scripts/census_board_row_duplicates.py --date 2026-09-06 --compare before.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from typing import Any

# The REAL functions, never a reimplementation. A census keyed by a private copy
# of `_row_key` measures the copy, not the board -- and this repo has already
# paid for two normalisers disagreeing about one name.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from syndicate.features.shared.kalshi_board_join import (  # noqa: E402
    _row_key,
    normalize_person,
)

DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"


def _books(row: dict) -> list[str]:
    quote = row.get("quote")
    if not isinstance(quote, dict):
        return []
    return sorted(quote.get("book_prices") or {})


def _nonascii(text: Any) -> bool:
    return any(ord(ch) > 127 for ch in str(text or ""))


def fetch(base_url: str, date: str, sport: str, timeout: float, *, retries: int = 4) -> dict:
    """Read the shortlist, RETRYING a 502.

    **A 502 HERE IS ROUTINE AND MEANS NOTHING ABOUT THE BOARD.** A web deploy
    502s every route for ~2 minutes (`blueprint_sync` measured 2026-08-08), and
    with several sessions deploying, a census run of any length will meet one.
    The first version of this script raised a bare `HTTPError` traceback, which
    is indistinguishable at a glance from "the endpoint is broken" and invites
    exactly the wrong conclusion -- that the board is down, or that a fold
    regressed. Measured the day it landed: the first run against a forward date
    hit one and reported a stack trace.

    An EMPTY slate and an UNREACHABLE service must never look alike, so a
    non-502 error is raised with its status named rather than swallowed.
    """
    url = f"{base_url}/api/board/layer2-shortlist?date={date}&sport={sport}&limit=2000"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as handle:
                return json.load(handle)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code != 502:
                raise SystemExit(
                    f"HTTP {exc.code} from {url}\n"
                    f"  This is a SERVICE answer, not a board answer -- do not read it as "
                    f"'no rows' or 'no duplicates'."
                ) from exc
            wait = 20 * (attempt + 1)
            print(f"  502 (attempt {attempt + 1}/{retries}) -- a web deploy 502s every route "
                  f"for ~2 min; retrying in {wait}s", flush=True)
            time.sleep(wait)
        except urllib.error.URLError as exc:
            raise SystemExit(f"cannot reach {base_url}: {exc.reason}") from exc
    raise SystemExit(
        f"still 502 after {retries} attempts ({last}). A deploy is probably in flight; "
        f"re-run when it is live. NOTHING is known about the board from this."
    )


def census(payload: dict) -> dict:
    rows = [r for r in (payload.get("rows") or []) if isinstance(r, dict)]
    props = [r for r in rows if r.get("kind") == "prop"]

    groups: dict[tuple, list[int]] = defaultdict(list)
    unkeyed = 0
    for index, row in enumerate(rows):
        key = _row_key(row)
        if key is None:
            unkeyed += 1
            continue
        groups[key].append(index)
    collisions = {k: v for k, v in groups.items() if len(v) > 1}

    # SPLIT BY CLASS. A `totals` vs `totals_alt` collision is the main-vs-
    # alternate case `_collapse_duplicate_bets` owns at index build; a collision
    # between rows whose RAW market names AGREE is not, and is the one that
    # reaches the join. Reporting one number for both hides which defect is live.
    raw_market_differs = 0
    for indexes in collisions.values():
        if len({str(rows[i].get("market") or "") for i in indexes}) > 1:
            raw_market_differs += 1

    spellings: dict[str, set[str]] = defaultdict(set)
    for row in props:
        name = row.get("player_name")
        if name:
            spellings[normalize_person(name)].add(str(name))
    two_spellings = {k: sorted(v) for k, v in spellings.items() if len(v) > 1}

    venue_split = Counter()
    for row in props:
        books = _books(row)
        if books == ["kalshi"]:
            venue_split["kalshi_only"] += 1
        elif "kalshi" in books:
            venue_split["kalshi_plus_books"] += 1
        else:
            venue_split["no_kalshi"] += 1

    return {
        "written_at": payload.get("written_at"),
        "total_rows": payload.get("total_rows"),
        "rows_read": len(rows),
        "prop_rows": len(props),
        "unkeyed_rows": unkeyed,
        "colliding_keys": len(collisions),
        "extra_rows": sum(len(v) - 1 for v in collisions.values()),
        "colliding_keys_raw_market_differs": raw_market_differs,
        "colliding_keys_raw_market_agrees": len(collisions) - raw_market_differs,
        "kalshi_only": venue_split["kalshi_only"],
        "kalshi_only_accented": sum(
            1 for r in props if _books(r) == ["kalshi"] and _nonascii(r.get("player_name"))
        ),
        "kalshi_plus_books": venue_split["kalshi_plus_books"],
        "no_kalshi": venue_split["no_kalshi"],
        "names_with_two_spellings": len(two_spellings),
        "two_spelling_names": two_spellings,
        "_keys": ["|".join(str(part) for part in k) for k in groups],
    }


def measurability(result: dict) -> tuple[bool, str]:
    """Can this reading distinguish a HELD fold from a BROKEN one? `(ok, why)`.

    **A CENSUS THAT CANNOT READ UNHEALTHY IS NOT A VERIFICATION**, and this
    script shipped able to print one. Asked for a forward date whose MLB slate
    was not built yet, it rendered `colliding _row_keys 0` over **zero rows** in
    the same format as a real pass. Nothing about that output says "no data";
    every counter is legitimately 0 and the reader supplies the conclusion.

    The defect this measures only EXISTS where two prop feeds disagree about a
    name, so the reading is informative only when both are present:

      * prop rows at all -- no props, no player names, nothing to fold;
      * an exchange price INSIDE a multi-book map (`kalshi_plus_books`) -- this
        is the merge working. At zero, either the exchange is absent from this
        slate or capture is down, and in both cases a 0 collision count is
        explained by absence rather than by the fold.

    Deliberately NOT keyed on "are there diacritic names today". That is the
    thing under test, and gating the instrument on it would make the census
    unable to fail -- the same circularity as an instrument built out of the
    symptom it measures.
    """
    if result["rows_read"] == 0:
        return False, "the slate is EMPTY -- 0 rows read. Nothing is known."
    if result["prop_rows"] == 0:
        return False, f"{result['rows_read']} rows but ZERO prop rows -- the fold acts on props."
    if result["kalshi_plus_books"] == 0:
        return False, (
            f"{result['prop_rows']} prop rows but kalshi_plus_books=0 -- no exchange price "
            "sits inside a multi-book map, so a 0 collision count is explained by the "
            "exchange being absent, not by the fold holding."
        )
    return True, (
        f"{result['prop_rows']} prop rows, kalshi_plus_books={result['kalshi_plus_books']} "
        "-- both feeds present, so a 0 here is a real 0."
    )


def render(result: dict) -> None:
    print(f"written_at                 {result['written_at']}")
    print(f"rows read / total          {result['rows_read']} / {result['total_rows']}"
          f"   props {result['prop_rows']}   unkeyed {result['unkeyed_rows']}")
    print(f"colliding _row_keys        {result['colliding_keys']}"
          f"   (extra rows {result['extra_rows']})")
    print(f"   raw market DIFFERS      {result['colliding_keys_raw_market_differs']}"
          f"   <- main-vs-alternate; the join collapses these at index build")
    print(f"   raw market AGREES       {result['colliding_keys_raw_market_agrees']}"
          f"   <- reaches the join; DOUBLE EXPOSURE")
    print(f"kalshi_plus_books          {result['kalshi_plus_books']}"
          f"   <- must RISE when a fold lands")
    print(f"kalshi_only                {result['kalshi_only']}"
          f"   ({result['kalshi_only_accented']} accented)")
    print(f"no_kalshi                  {result['no_kalshi']}")
    print(f"names w/ 2 spellings       {result['names_with_two_spellings']}")
    for name, variants in sorted(result["two_spelling_names"].items()):
        print(f"      {name!r}: {variants}")
    ok, why = measurability(result)
    print()
    if ok:
        verdict = ("HELD" if result["colliding_keys_raw_market_agrees"] == 0
                   else "NOT HELD -- same-market collisions present")
        print(f"MEASURABLE: {why}")
        print(f"VERDICT: {verdict}")
    else:
        # Loud, and it does NOT say the board is fine. An unmeasurable slate and
        # a clean one print the same counters; only this line separates them.
        print(f"*** NOT MEASURABLE: {why}")
        print("*** The zeros above are ABSENCE, not health. Do not record this as a pass.")


def compare(before: dict, after: dict) -> None:
    b, a = set(before.get("_keys") or []), set(after.get("_keys") or [])
    print()
    print(f"BEFORE {before['written_at']}  ->  AFTER {after['written_at']}")
    for field, arrow in (
        ("colliding_keys", "-> 0"),
        ("colliding_keys_raw_market_agrees", "-> 0"),
        ("kalshi_plus_books", "must RISE"),
        ("kalshi_only", "-> 0"),
        ("names_with_two_spellings", "-> 0"),
    ):
        print(f"  {field:36s} {before.get(field)} -> {after.get(field)}   {arrow}")
    print()
    print("  key buckets -- a row-count delta CANNOT tell new coverage from a split:")
    print(f"    both        {len(b & a):5d}   should GAIN books")
    print(f"    after_only  {len(a - b):5d}   genuine new coverage, expected")
    print(f"    before_only {len(b - a):5d}   <- the regression bucket")
    print()
    rose = (after.get("kalshi_plus_books") or 0) > (before.get("kalshi_plus_books") or 0)
    gone = (after.get("colliding_keys_raw_market_agrees") or 0) == 0
    if gone and rose:
        print("  VERDICT: duplicates gone AND the exchange price MERGED (not lost).")
    elif gone and not rose:
        print("  VERDICT: duplicates gone but kalshi_plus_books did NOT rise -- "
              "consistent with a CAPTURE OUTAGE, not with a fold. Do not bank this.")
    else:
        print("  VERDICT: same-market collisions remain; the fold did not close them.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", required=True)
    parser.add_argument("--sport", default="mlb")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--baseline", help="write this reading to JSON")
    parser.add_argument("--compare", help="diff against a baseline JSON")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = census(fetch(args.base_url, args.date, args.sport, args.timeout))
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "_keys"}, indent=2))
    else:
        render(result)

    if args.baseline:
        with open(args.baseline, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
        print(f"\nbaseline written to {args.baseline}")

    if args.compare:
        with open(args.compare, encoding="utf-8") as handle:
            compare(json.load(handle), result)

    # EXIT CODE, so an automated run cannot report success by saying nothing.
    #   0 = measurable AND held
    #   2 = measurable AND a same-market collision is present (the real alarm)
    #   3 = NOT MEASURABLE -- distinct from both, because "no data" must never
    #       share an exit code with "verified clean".
    ok, _ = measurability(result)
    if not ok:
        return 3
    return 0 if result["colliding_keys_raw_market_agrees"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
