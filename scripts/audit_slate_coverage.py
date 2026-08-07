"""Daily guard: does the BOARD cover the games that are actually being played?

This exists because "what is happening today" turned out to be load-bearing and
nobody was checking it. Measured 2026-08-07 on production:

  - the NFL board carried 1,244 rows for "today" whose games start **34 to 156
    days out**, while NFL PRESEASON games in the current window had no rows at
    all -- a capture gap that looked like an empty schedule;
  - soccer carried rows for today only, with nothing for the rest of the week,
    despite fixtures being sharded by fixture date (#239);
  - MLB was the only sport whose board matched its slate.

THE TWO FAILURES THIS CATCHES ARE OPPOSITE, and a single row count sees neither:

  MISSING   a scheduled game with no market rows -> we are not capturing it
  ORPHAN    market rows whose game is far outside the window -> the board is
            showing a future slate under today's date

A board can look full and be wrong in both directions at once, which is exactly
what NFL did.

Run daily. Non-zero exit when a sport has scheduled games and zero rows for
them, so it can gate a pipeline rather than only inform a human.

    python scripts/audit_slate_coverage.py
    python scripts/audit_slate_coverage.py --date 2026-08-07 --days 7
    python scripts/audit_slate_coverage.py --sports nfl,soccer --json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone

DEFAULT_BASE = "https://syndicate-an21.onrender.com"

# Fetch failures must never look like "no games". An audit whose expected side
# silently reads empty passes every sport -- which is how this script reported
# sched=0 for a 15-game MLB slate after being rate-limited.
FETCH_ERRORS: list[str] = []
SPORTS = ["mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"]


def _get(url: str, timeout: float = 180.0):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _board_rows(base_url: str, sport: str, day: str) -> list[dict]:
    """Every row, fetched PER MARKET.

    The unfiltered endpoint is a global top-N ranked by book coverage, so it
    drops thin markets -- precisely the ones a coverage audit is hunting.
    """
    try:
        head = _get(f"{base_url}/api/board/book-grid?sport={sport}&date={day}&limit=1")
    except Exception as exc:
        FETCH_ERRORS.append(f"{sport} board head {day}: {type(exc).__name__}")
        return []
    rows: list[dict] = []
    for market in sorted(head.get("markets") or []):
        url = (
            f"{base_url}/api/board/book-grid?sport={sport}&date={day}"
            f"&market={urllib.parse.quote(market)}&limit=4000"
        )
        try:
            rows.extend(_get(url).get("rows") or [])
        except Exception as exc:
            FETCH_ERRORS.append(f"{sport} board {market} {day}: {type(exc).__name__}")
            continue
    return rows


def _scheduled_events(base_url: str, sport: str, day: str) -> list:
    """The schedule as PRODUCTION sees it, via /api/board/game-chips.

    Deliberately not `fetch_schedule_for_date`: that reads local artifacts, and
    on a dev machine it returns zero for every sport -- including MLB on a
    15-game slate. An audit whose "expected" side silently reads empty is worse
    than no audit, because every sport then passes. Measured: this endpoint
    returned mlb=15, soccer=35, nfl=1, wnba=3 for 2026-08-07 while the local
    adapter returned 0 for all four.

    Note the parameter is `sports` (plural); `sport` silently returns the SPA
    shell rather than JSON.
    """
    try:
        payload = _get(f"{base_url}/api/board/game-chips?sports={urllib.parse.quote(sport)}&date={day}")
    except Exception as exc:
        FETCH_ERRORS.append(f"{sport} chips {day}: {type(exc).__name__}")
        return []
    return list(payload.get("chips") or [])


def _commence_date(row: dict) -> date | None:
    raw = row.get("commence_time")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date()


def audit(base_url: str, sport: str, start: date, days: int) -> dict:
    horizon = Counter()
    events_by_day: dict[str, int] = {}
    covered_event_ids: set[str] = set()
    scheduled_event_ids: set[str] = set()

    rows = _board_rows(base_url, sport, start.isoformat())
    for row in rows:
        commence = _commence_date(row)
        horizon[(commence - start).days if commence else "unstamped"] += 1
        event_id = str(row.get("event_id") or "").strip()
        if event_id and commence is not None and 0 <= (commence - start).days < days:
            covered_event_ids.add(event_id)

    keys_by_day: dict[str, frozenset] = {}
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        events = _scheduled_events(base_url, sport, day)
        events_by_day[day] = len(events)
        day_keys = set()
        for event in events:
            event_id = str((event or {}).get("game_key") or "").strip()
            if event_id:
                scheduled_event_ids.add(event_id)
                day_keys.add(event_id)
        keys_by_day[day] = frozenset(day_keys)

    # A schedule source that returns THE SAME GAMES for every date is not a
    # schedule -- and it will happily make a sport look either fully covered or
    # fully missing. MEASURED 2026-08-07: /api/board/game-chips returned game_key
    # 401873271 (CAR @ ARI, actually played 08-06) for 08-05, 08-06, 08-07, 08-08
    # AND 08-12 -- the NFL week-self-pins-to-1 defect surfacing here.
    #
    # This audit therefore REFUSES TO VERDICT such a sport rather than reporting
    # a confident MISSING built on it. Two different schedule sources were wrong
    # in opposite directions in one session; a third silent one is not wanted.
    non_empty = [keys for keys in keys_by_day.values() if keys]
    date_blind = bool(len(non_empty) > 1 and len(set(non_empty)) == 1)

    scheduled_total = sum(events_by_day.values())
    in_window = sum(count for key, count in horizon.items() if isinstance(key, int) and 0 <= key < days)
    beyond = sum(count for key, count in horizon.items() if isinstance(key, int) and key >= days)

    return {
        "sport": sport,
        "board_rows": len(rows),
        "rows_in_window": in_window,
        "rows_beyond_window": beyond,
        "rows_unstamped": horizon.get("unstamped", 0),
        "scheduled_games": scheduled_total,
        "scheduled_by_day": events_by_day,
        "days_with_games": sum(1 for count in events_by_day.values() if count),
        "days_with_rows": len({key for key in horizon if isinstance(key, int) and 0 <= key < days}),
        # The headline failure: games are on, and the board has nothing for them.
        "SCHEDULE_SOURCE_SUSPECT": date_blind,
        "MISSING": bool(scheduled_total and in_window == 0 and not date_blind),
        # The other failure: rows exist but every one is outside the window.
        "ORPHAN_ONLY": bool(len(rows) and in_window == 0 and beyond),
        # THE QUIET ONE. A board can cover today and nothing else and still look
        # healthy on every total. Measured 2026-08-07: soccer had 230 scheduled
        # games across 7 days and rows for exactly ONE day -- fixtures are
        # sharded by fixture date (#239), so a puller that only ever asks for
        # today gets a 404 for the rest and logs "absent". A row count cannot
        # see this; only days-covered can.
        "THIN_HORIZON": bool(
            sum(1 for c in events_by_day.values() if c) > 1
            and len({k for k in horizon if isinstance(k, int) and 0 <= k < days})
            < sum(1 for c in events_by_day.values() if c)
        ),
        "horizon_days_present": sorted(k for k in horizon if isinstance(k, int)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--date", default="")
    parser.add_argument("--days", type=int, default=7, help="window to consider 'current' (default 7)")
    parser.add_argument("--sports", default=",".join(SPORTS))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    start = (
        datetime.fromisoformat(args.date).date()
        if args.date.strip()
        else datetime.now(timezone.utc).date()
    )
    sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]
    results = [audit(args.base_url, sport, start, args.days) for sport in sports]

    if args.json:
        print(json.dumps(results, indent=1, default=str))
    else:
        print(f"Slate coverage — {args.base_url}  {start} .. +{args.days}d\n")
        print(f"{'sport':8s} {'sched':>6s} {'days':>5s} {'rows':>6s} {'in-win':>7s} {'beyond':>7s} {'unstmp':>7s}  verdict")
        for r in results:
            verdict = (
                "SCHEDULE SUSPECT — same games every date, cannot verdict" if r["SCHEDULE_SOURCE_SUSPECT"]
                else "MISSING — games on, no rows" if r["MISSING"]
                else "ORPHAN — all rows outside window" if r["ORPHAN_ONLY"]
                else f"THIN — games on {r['days_with_games']}d, rows on {r['days_with_rows']}d" if r["THIN_HORIZON"]
                else "ok"
            )
            print(
                f"{r['sport']:8s} {r['scheduled_games']:6d} {r['days_with_games']:5d} "
                f"{r['board_rows']:6d} {r['rows_in_window']:7d} {r['rows_beyond_window']:7d} "
                f"{r['rows_unstamped']:7d}  {verdict}"
            )
        print()
        for r in results:
            if r["MISSING"] or r["ORPHAN_ONLY"] or r["THIN_HORIZON"] or r["SCHEDULE_SOURCE_SUSPECT"]:
                print(f"  {r['sport']}: scheduled_by_day={r['scheduled_by_day']}")
                print(f"  {r['sport']}: horizon_days_present={r['horizon_days_present'][:20]}")

    if FETCH_ERRORS:
        print("")
        print(f"{len(FETCH_ERRORS)} FETCH FAILURES -- verdicts above are NOT trustworthy:", file=sys.stderr)
        for line in FETCH_ERRORS[:10]:
            print(f"  {line}", file=sys.stderr)
        return 2

    failures = [r["sport"] for r in results if r["MISSING"]]
    if failures:
        print(f"\nFAIL: scheduled games with no board rows — {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
