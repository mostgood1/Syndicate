"""Read Kalshi's OWN fee parameters per series, so nothing has to guess them.

`venue_fees.py` says it at length: **Kalshi publishes its fee parameters per
series, so do not hardcode a rate.** `GET /trade-api/v2/series/<ticker>` carries

    fee_type        "quadratic" | "quadratic_with_maker_fees"
    fee_multiplier  a float scaling the 0.07 base taker rate

Until 2026-09-01 that reading had been done by hand, once, across the series the
platform traded at the time -- and the gap showed up as a real cost. `#624`
step 6 could not resolve whether MLB BATTER-PROP series were half rate or full
rate, so it reported a BOUND (+2.22% to +2.66% ROI) instead of a number, and the
0.44-point width of that bound was more than half the gate's shortfall. This
script is the thing that should have existed: one command, every series, read
from the venue.

WHAT THE 2026-09-01 READ FOUND, 19 MLB series, 0 failures:

    x0.5  KXMLBGAME  KXMLBSPREAD  KXMLBTOTAL  KXMLBKS  KXMLBOUTS
          KXMLBHIT  KXMLBHR  KXMLBHRR  KXMLBRBI  KXMLBTB  KXMLBSB
          KXMLBF5TOTAL  KXMLBF5SPREAD  KXMLBTEAMTOTAL
    x1.0  KXMLBERA  KXMLBHA  KXMLBWA  KXMLBASGAME  KXMLBINNINGTOTAL

**Every batter-prop series is HALF RATE.** So `#624` step 6's m=1.0 bound was
pure caution and can be retired.

**THE MULTIPLIER IS A PROPERTY OF THE SERIES AND NOTHING ELSE. Every broader
rule anyone might reach for is FALSIFIED by this table:**

  * not per SPORT -- five MLB series are full rate;
  * not props-vs-games -- `KXMLBASGAME` is a GAME at 1.0 while `KXMLBGAME` is
    0.5, and both are `quadratic_with_maker_fees`;
  * not per MARKET FAMILY, which is the sharpest one -- `KXMLBTOTAL` and
    `KXMLBF5TOTAL` are 0.5 while `KXMLBINNINGTOTAL` is **1.0**. Three totals
    series, two different rates.

The five full-rate series are pitcher rate stats (earned runs, hits allowed,
walks), the All-Star game, and inning totals. Three of those sit inside `#624`'s
gate book, which is "unders minus HR/HRR" rather than "batter unders", so a
single multiplier would be wrong in both directions at once.

**REGISTERED != FETCHED, and the fee question follows what is FETCHED.** The
first version of this list carried the 14 series in
`kalshi_catalogue.SERIES_SPORT` and called itself complete. Five more are
fetched without being registered there (`KXMLBASGAME`, `KXMLBF5TOTAL`,
`KXMLBF5SPREAD`, `KXMLBINNINGTOTAL`, `KXMLBTEAMTOTAL`) -- **two of them full
rate** -- and they surfaced only because a stale background grep of non-test
`.py` finished after the read had already been declared complete. If you add a
series anywhere, re-run this.

`fee_multiplier` is venue configuration and can change. This writes a dated
snapshot rather than a constant of nature; re-run it before leaning on the
numbers, and diff the result.

Usage:
    py -3 scripts/read_kalshi_fee_params.py
    py -3 scripts/read_kalshi_fee_params.py --series KXMLBHIT KXNFLGAME
    py -3 scripts/read_kalshi_fee_params.py --write reports/venue/kalshi_fee_params.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERIES_ENDPOINT = "https://api.elections.kalshi.com/trade-api/v2/series/"

# The MLB series this repo registers, from `kalshi_catalogue.SERIES_SPORT`.
# Listed here so the default run covers the sport the gate is about; pass
# --series for anything else.
MLB_SERIES = (
    # registered in `kalshi_catalogue.SERIES_SPORT`
    "KXMLBGAME", "KXMLBSPREAD", "KXMLBTOTAL",
    "KXMLBKS", "KXMLBOUTS", "KXMLBERA", "KXMLBHA", "KXMLBWA",
    "KXMLBHIT", "KXMLBHR", "KXMLBHRR", "KXMLBRBI", "KXMLBTB", "KXMLBSB",
    # FETCHED but not in SERIES_SPORT -- found only because a stale background
    # grep of non-test .py surfaced them after the first read had been called
    # "complete". Two of them are FULL rate. Registration and fetching are
    # different lists, and the fee question follows what is FETCHED.
    "KXMLBASGAME", "KXMLBF5TOTAL", "KXMLBF5SPREAD",
    "KXMLBINNINGTOTAL", "KXMLBTEAMTOTAL",
)


def read_series(ticker: str, timeout: float = 45.0) -> dict:
    """Fee parameters for one series, or a row saying why not.

    A failure is REPORTED, never defaulted. `venue_fees.kalshi_fee_params`
    refuses a series it cannot read for exactly this reason: pricing an unknown
    series at the common case is how a fake arb gets manufactured.
    """
    request = urllib.request.Request(
        SERIES_ENDPOINT + ticker,
        headers={"Accept": "application/json", "User-Agent": "syndicate-fee-probe"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return {"series": ticker, "error": f"{type(exc).__name__}: {exc}"}
    inner = payload.get("series")
    row = inner if isinstance(inner, dict) else payload
    if not isinstance(row, dict):
        return {"series": ticker, "error": "series_payload_not_a_mapping"}
    return {
        "series": ticker,
        "fee_type": row.get("fee_type"),
        "fee_multiplier": row.get("fee_multiplier"),
        "title": row.get("title"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--series", nargs="*", default=list(MLB_SERIES))
    ap.add_argument("--write", default="", help="also write the rows to this JSON path")
    ap.add_argument("--read-at", default="", help="stamp the snapshot with this ISO time")
    args = ap.parse_args()

    rows = [read_series(ticker) for ticker in args.series]

    print(f"{'series':<18}{'fee_type':<30}{'mult':>6}   title")
    print("-" * 96)
    for row in rows:
        if row.get("error"):
            print(f"{row['series']:<18}READ FAILED -- {row['error'][:60]}")
            continue
        print(f"{row['series']:<18}{str(row.get('fee_type')):<30}"
              f"{str(row.get('fee_multiplier')):>6}   {str(row.get('title') or '')[:34]}")

    good = [r for r in rows if not r.get("error")]
    failed = [r for r in rows if r.get("error")]
    multipliers = sorted({r.get("fee_multiplier") for r in good}, key=lambda v: (v is None, v))
    print(f"\n{len(good)} read, {len(failed)} failed. distinct multipliers: {multipliers}")
    if len(multipliers) > 1:
        print("NOT UNIFORM -- a single multiplier for this set would be wrong for some "
              "series in both directions. Resolve per series.")
    for multiplier in multipliers:
        named = sorted(r["series"] for r in good if r.get("fee_multiplier") == multiplier)
        print(f"  x{multiplier}: {' '.join(named)}")
    if failed:
        print("\nFAILED, and these are NOT to be treated as the common case:")
        for row in failed:
            print(f"  {row['series']}: {row['error'][:70]}")

    if args.write:
        dest = Path(args.write)
        if not dest.is_absolute():
            dest = REPO_ROOT / dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(
            {"read_at": args.read_at or None, "endpoint": SERIES_ENDPOINT, "rows": rows},
            indent=2), encoding="utf-8")
        print(f"\nwrote {dest}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
