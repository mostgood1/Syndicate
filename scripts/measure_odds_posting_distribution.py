"""When do MLB player-prop lines first become available, per date?

Reads mlb_source/tracking/book_quotes/<date>.jsonl from production via the ops
stream endpoint. Each row carries BOTH:

  captured_at      -- when our fetcher wrote it to disk
  book_updated_at  -- the book's own last-update stamp for that quote

The pair is what makes this measurable. captured_at alone conflates "the book
posted late" with "we polled late"; book_updated_at bounds when the line
already existed at the book.

FULL SCAN, deliberately. The first draft of this script stopped at the first
`prop` row on the assumption the file is append-ordered by capture time. It is
not: on 2026-08-12 the first prop row in file order stamps 02:03 while the
first game row stamps 14:08, which is impossible under that assumption. Every
number that version printed was the first row in FILE order, not the earliest
in TIME. Costs ~20MB/date to do correctly; that is the price of the answer.

Also reports a volume-qualified time (`first_bulk`): the earliest capture sweep
carrying at least MIN_BULK prop rows. A single stray prop quote is not "prop
odds are available for this slate", and the guard being scheduled around this
needs the time real coverage lands, not the time one row does.
"""
from __future__ import annotations

import collections
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

CENTRAL = timezone(timedelta(hours=-5))  # CDT, matches the repo's central_* helpers
PITCHER_MARKETS = {
    "strikeouts", "outs", "earned_runs", "hits_allowed",
    "walks_allowed", "pitches", "batters_faced",
}
MIN_BULK = 50

BASE = "https://syndicate-an21.onrender.com/api/ops/artifacts/stream?path="
PATH = "mlb_source/tracking/book_quotes/{date}.jsonl"


def _token() -> str:
    for line in open(os.path.join(os.getcwd(), ".env"), encoding="utf-8-sig"):
        if line.startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found in .env")


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(CENTRAL)


def _local(ts: str | None, *, slate: str | None = None) -> str:
    """Clock time in CDT, with a day offset relative to the slate date.

    The offset is not cosmetic. Rendering these as bare %H:%M made prop odds
    for the 08-07 slate look like they landed at 23:30 ON 08-07, when the
    capture is 2026-08-07T04:30Z = 23:30 CDT on 08-06 -- the evening BEFORE.
    Half these timestamps are previous-day, so a bare clock reading inverts
    the very question being asked.
    """
    parsed = _parse(ts)
    if parsed is None:
        return "-"
    stamp = parsed.strftime("%H:%M")
    if not slate:
        return stamp
    offset = (parsed.date() - datetime.fromisoformat(slate).date()).days
    return f"{stamp}{'' if offset == 0 else f'{offset:+d}d'}"


def measure(date: str, token: str) -> dict | None:
    req = urllib.request.Request(BASE + PATH.format(date=date), headers={"X-Admin-Token": token})
    mins: dict[str, str] = {}
    per_sweep: collections.Counter = collections.Counter()
    rows = 0

    def note(key: str, value) -> None:
        if not value:
            return
        text = str(value)
        if key not in mins or text < mins[key]:
            mins[key] = text

    try:
        resp = urllib.request.urlopen(req, timeout=600)
    except Exception as exc:
        print(f"{date}: unavailable ({exc})", file=sys.stderr)
        return None
    with resp:
        for raw in resp:
            try:
                row = json.loads(raw)
            except Exception:
                continue
            rows += 1
            kind = row.get("kind")
            captured = row.get("captured_at")
            if kind == "game":
                note("game", captured)
                continue
            if kind != "prop":
                continue
            note("prop", captured)
            note("prop_book", row.get("book_updated_at"))
            note("first_pitch", row.get("commence_time"))
            market = str(row.get("market") or "")
            if market in PITCHER_MARKETS:
                note("pitcher", captured)
            elif market.startswith("batter_"):
                note("hitter", captured)
            if captured:
                per_sweep[str(captured)] += 1

    bulk = sorted(ts for ts, n in per_sweep.items() if n >= MIN_BULK)
    return {
        "date": date,
        "rows": rows,
        "sweeps": len(per_sweep),
        "first_bulk": bulk[0] if bulk else None,
        **{f"first_{k}": v for k, v in mins.items()},
    }


def main() -> None:
    token = _token()
    dates = sys.argv[1:] or [f"2026-08-{day:02d}" for day in range(6, 14)]
    rows = []
    for date in dates:
        result = measure(date, token)
        if result:
            rows.append(result)
            print(f"  ...{date} scanned ({result['rows']} rows, {result['sweeps']} sweeps)", file=sys.stderr)

    print()
    print("MLB prop-odds first availability. Times are local CDT; '-1d' = the day")
    print("BEFORE the slate. Full scan of book_quotes.")
    print(f"'bulk' = first capture sweep with >={MIN_BULK} prop rows.")
    print("'lead' = hours from first prop capture to the slate's first pitch.")
    print()
    hdr = (
        f"{'slate':<12}{'prop capture':>14}{'bulk':>14}{'book posted':>14}"
        f"{'first pitch':>13}{'lead h':>8}{'sweeps':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    leads = []
    for r in rows:
        slate = r["date"]
        first_prop = _parse(r.get("first_prop"))
        first_pitch = _parse(r.get("first_first_pitch"))
        lead = ""
        if first_prop and first_pitch:
            hours = (first_pitch - first_prop).total_seconds() / 3600.0
            leads.append((hours, slate))
            lead = f"{hours:.1f}"
        print(
            f"{slate:<12}"
            f"{_local(r.get('first_prop'), slate=slate):>14}"
            f"{_local(r.get('first_bulk'), slate=slate):>14}"
            f"{_local(r.get('first_prop_book'), slate=slate):>14}"
            f"{_local(r.get('first_first_pitch'), slate=slate):>13}"
            f"{lead:>8}"
            f"{r['sweeps']:>8}"
        )

    if leads:
        leads.sort()
        print()
        print("Lead time, first prop capture -> first pitch (hours):")
        print(f"  min    {leads[0][0]:6.1f}   ({leads[0][1]})")
        print(f"  median {leads[len(leads) // 2][0]:6.1f}")
        print(f"  max    {leads[-1][0]:6.1f}   ({leads[-1][1]})")
        print(f"  n={len(leads)}")
        thin = [(h, d) for h, d in leads if h < 6]
        print(f"  slates with under 6h of lead: {len(thin)}" + (f" -> {[d for _, d in thin]}" if thin else ""))


if __name__ == "__main__":
    main()
