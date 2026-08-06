"""Backfill MLB per-book odds history from OddsAPI's historical endpoints (#210).

WHY
---
#208/#209 established that the single-book / no-closing-line problem is a
CAPTURE defect: the books were never written down, so nothing on our disks can
recover them. That makes every prop verdict in #186-#204 unrecoverable *from our
own artifacts* -- but OddsAPI kept its own history, and our account has access to
it. This buys back what capture threw away, which is the only route to CLV on
past bets rather than only on bets placed from today forward.

Measured against the live account 2026-08-06 before writing this:

    /v4/historical/sports/baseball_mlb/events        1 credit  per call
    /v4/historical/sports/baseball_mlb/odds         10 credits per market-region
    .../events/{id}/odds                            10 credits per market-region

    account headers: 250,600 used / 14,749,400 remaining

The headers sum to 15M, but do NOT treat that as the cap: the same discrepancy
was recorded 2026-07-30 and the user re-confirmed then that 5,000,000 is the real
billed monthly cap. Budget against 5M. A 30-day backfill at ~140k credits is
~2.8% of one month against that denominator -- still comfortable, but size it
against 5M, not against `x-requests-remaining`.

Snapshots are ~5 minutes apart and a slate call returns every book (10 observed:
fanduel, draftkings, betmgm, williamhill_us, fanatics, betrivers, betonlineag,
lowvig, bovada, betus).

WHAT IT WRITES
--------------
Straight into the #209 quote log via `append_book_quotes`, in exactly the shape
live capture now produces. Backfilled and live rows are then indistinguishable to
any consumer, so `closing_quotes()` and `best_price_by_market()` work across the
whole range without a per-source branch. That is the point of routing it here
rather than inventing a backfill-only artifact.

COST CONTROL
------------
Runs a dry run by default and prints the exact credit estimate; spending
requires `--execute`. A hard `--max-credits` ceiling aborts mid-run rather than
silently overspending, and progress is checkpointed per date so an abort or a
network failure resumes instead of re-buying what it already has.

A CAUTION ON WHAT THIS PROVES
-----------------------------
Backfilled closing lines make CLV *measurable*; they do not make the old prop
verdicts valid. Those bets were selected using a single arbitrary book's price,
so re-grading them against best-price closing lines measures how bad that
selection was -- it does not retroactively turn them into bets we would have
made. Report the two separately.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.odds_book_quotes import append_book_quotes  # noqa: E402
from syndicate.features.shared.odds_book_quotes import book_quotes_path  # noqa: E402
from syndicate.features.shared.odds_book_quotes import quote_rows_from_oddsapi_events  # noqa: E402

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"

GAME_MARKETS = ["h2h", "spreads", "totals"]
# Matches DEFAULT_HITTER_MARKETS + PITCHER_MARKET_KEY_MAP in
# fetch_mlb_oddsapi_local.py, so backfilled rows carry the same market names the
# live path produces.
HITTER_MARKETS = [
    "batter_hits",
    "batter_hits_runs_rbis",
    "batter_total_bases",
    "batter_home_runs",
    "batter_rbis",
    "batter_runs_scored",
    "batter_strikeouts",
]
PITCHER_MARKETS = ["pitcher_strikeouts", "pitcher_outs", "pitcher_hits_allowed", "pitcher_walks", "pitcher_earned_runs"]
PITCHER_MARKET_RENAME = {
    "pitcher_strikeouts": "strikeouts",
    "pitcher_outs": "outs",
    "pitcher_hits_allowed": "hits_allowed",
    "pitcher_walks": "walks_allowed",
    "pitcher_earned_runs": "earned_runs",
}

# Minutes before first pitch to sample. The late ones are what CLV needs; the
# early ones give an opening reference and the movement between them.
GAME_OFFSETS_MINUTES = [24 * 60, 6 * 60, 3 * 60, 60, 15, 5]
# Props post late and thinly, so an offset earlier than a few hours out mostly
# buys empty responses at full price.
PROP_OFFSETS_MINUTES = [3 * 60, 10]

CREDITS_PER_MARKET_REGION = 10


class Budget:
    def __init__(self, max_credits: int) -> None:
        self.max_credits = int(max_credits)
        self.spent = 0
        self.calls = 0
        self.remaining_reported: int | None = None

    def charge(self, headers: dict[str, str]) -> None:
        self.calls += 1
        try:
            self.spent += int(headers.get("x-requests-last") or 0)
        except Exception:
            pass
        try:
            self.remaining_reported = int(headers.get("x-requests-remaining") or 0)
        except Exception:
            pass
        if self.max_credits and self.spent > self.max_credits:
            raise RuntimeError(
                f"credit ceiling hit: spent {self.spent} > --max-credits {self.max_credits}. "
                f"Progress is checkpointed; re-run to continue."
            )


def _get(path: str, params: dict[str, Any], *, api_key: str, budget: Budget, retries: int = 3) -> Any:
    query = dict(params)
    query["apiKey"] = api_key
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(query)}"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as response:
                headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
                budget.charge(headers)
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            headers = {str(key).lower(): str(value) for key, value in (exc.headers or {}).items()}
            # A 4xx still bills in some cases, and always carries the counters.
            budget.charge(headers)
            if exc.code in (404, 422):
                # No snapshot at that instant, or a market this event never
                # offered. Both are ordinary and must not abort the run.
                return None
            last_error = exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    print(f"  ! giving up on {path} after {retries} attempts: {last_error}", flush=True)
    return None


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _events_for_date(date_str: str, *, api_key: str, budget: Budget) -> list[dict[str, Any]]:
    """Slate for a date, read from a snapshot late enough that every game of the
    day has been posted but early enough that none has been dropped."""
    probe = f"{date_str}T16:00:00Z"
    payload = _get(f"/historical/sports/{SPORT}/events", {"date": probe}, api_key=api_key, budget=budget)
    data = (payload or {}).get("data") if isinstance(payload, dict) else payload
    events: list[dict[str, Any]] = []
    for event in data or []:
        commence = _parse_iso(event.get("commence_time"))
        if commence is None:
            continue
        # The endpoint returns everything upcoming, which spans several days.
        # Keep the ones whose first pitch falls on the requested UTC date or the
        # early hours after it -- MLB night games roll past midnight UTC.
        start_of_day = _parse_iso(f"{date_str}T00:00:00Z")
        if start_of_day is None:
            continue
        if not (start_of_day <= commence < start_of_day + timedelta(days=1, hours=12)):
            continue
        events.append(event)
    return events


def _snapshot_timestamps(events: list[dict[str, Any]], offsets_minutes: list[int]) -> list[str]:
    stamps: set[str] = set()
    for event in events:
        commence = _parse_iso(event.get("commence_time"))
        if commence is None:
            continue
        for offset in offsets_minutes:
            moment = commence - timedelta(minutes=offset)
            # Round to the 5-minute grid the API snapshots on, so games sharing
            # a start time share one paid call instead of buying it twice.
            rounded = moment.replace(second=0, microsecond=0)
            rounded = rounded - timedelta(minutes=rounded.minute % 5)
            stamps.add(rounded.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return sorted(stamps)


def _backfill_game_markets(date_str: str, events: list[dict[str, Any]], *, api_key: str, budget: Budget, regions: str) -> int:
    stamps = _snapshot_timestamps(events, GAME_OFFSETS_MINUTES)
    appended = 0
    for stamp in stamps:
        payload = _get(
            f"/historical/sports/{SPORT}/odds",
            {"regions": regions, "markets": ",".join(GAME_MARKETS), "date": stamp, "oddsFormat": "american"},
            api_key=api_key,
            budget=budget,
        )
        data = (payload or {}).get("data") if isinstance(payload, dict) else None
        if not data:
            continue
        observed_at = str((payload or {}).get("timestamp") or stamp)
        rows = quote_rows_from_oddsapi_events(data)
        for row in rows:
            # The API's own snapshot timestamp, not our wall clock -- these rows
            # describe a past instant and must sort by when the price was live.
            row["snapshot_ts"] = observed_at
        result = append_book_quotes(
            sport="mlb", date_str=date_str, rows=rows, captured_at=observed_at, publish=False
        )
        appended += int(result.get("appended") or 0)
    return appended


def _backfill_props(date_str: str, events: list[dict[str, Any]], *, api_key: str, budget: Budget, regions: str, markets: list[str]) -> int:
    market_map = {key: PITCHER_MARKET_RENAME.get(key, key) for key in markets}
    appended = 0
    for event in events:
        event_id = str(event.get("id") or "").strip()
        commence = _parse_iso(event.get("commence_time"))
        if not event_id or commence is None:
            continue
        for offset in PROP_OFFSETS_MINUTES:
            moment = commence - timedelta(minutes=offset)
            stamp = moment.replace(second=0, microsecond=0).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            payload = _get(
                f"/historical/sports/{SPORT}/events/{event_id}/odds",
                {"regions": regions, "markets": ",".join(markets), "date": stamp, "oddsFormat": "american"},
                api_key=api_key,
                budget=budget,
            )
            data = (payload or {}).get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                continue
            observed_at = str((payload or {}).get("timestamp") or stamp)
            rows = quote_rows_from_oddsapi_events([data], market_map=market_map)
            for row in rows:
                row["snapshot_ts"] = observed_at
            result = append_book_quotes(
                sport="mlb", date_str=date_str, rows=rows, captured_at=observed_at, publish=False
            )
            appended += int(result.get("appended") or 0)
    return appended


def _state_path() -> Path:
    return book_quotes_path("mlb", "backfill").with_name("historical_backfill_state.json")


def _load_state() -> dict[str, Any]:
    path = _state_path()
    try:
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
    except Exception:
        pass
    return {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def _date_range(start: str, end: str) -> list[str]:
    first = _parse_iso(f"{start}T00:00:00Z")
    last = _parse_iso(f"{end}T00:00:00Z")
    if first is None or last is None or last < first:
        return []
    out: list[str] = []
    cursor = first
    while cursor <= last:
        out.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill MLB per-book odds from OddsAPI historical endpoints")
    parser.add_argument("--start", required=True, help="first date, YYYY-MM-DD (UTC)")
    parser.add_argument("--end", required=True, help="last date, YYYY-MM-DD (UTC), inclusive")
    parser.add_argument("--regions", default="us")
    parser.add_argument("--skip-props", action="store_true", help="game markets only -- roughly 1/5 the cost")
    parser.add_argument("--skip-game-markets", action="store_true")
    parser.add_argument("--max-credits", type=int, default=400_000)
    parser.add_argument("--execute", action="store_true", help="actually spend credits; omit for a dry-run estimate")
    parser.add_argument("--force", action="store_true", help="re-run dates already recorded as done")
    args = parser.parse_args(argv)

    api_key = str(os.environ.get("ODDS_API_KEY") or os.environ.get("ODDSAPI_KEY") or "").strip()
    if not api_key:
        print("ERROR: ODDS_API_KEY not set")
        return 2

    dates = _date_range(args.start, args.end)
    if not dates:
        print("ERROR: empty or inverted date range")
        return 2

    prop_markets = ([] if args.skip_props else HITTER_MARKETS + PITCHER_MARKETS)
    regions_count = len([part for part in str(args.regions).split(",") if part.strip()]) or 1

    if not args.execute:
        # Estimated, not measured -- stated as such. Slate size and start-time
        # spread vary by date, so this uses a typical 15-game day.
        games_per_day = 15
        distinct_stamps = len(GAME_OFFSETS_MINUTES) * 6  # start times cluster; ~6 distinct per day
        game_cost = 0 if args.skip_game_markets else distinct_stamps * len(GAME_MARKETS) * regions_count * CREDITS_PER_MARKET_REGION
        prop_cost = games_per_day * len(PROP_OFFSETS_MINUTES) * len(prop_markets) * regions_count * CREDITS_PER_MARKET_REGION
        per_day = game_cost + prop_cost + 1
        print(f"DRY RUN -- {len(dates)} dates, {dates[0]} .. {dates[-1]}")
        print(f"  game markets: ~{game_cost:,} credits/day ({len(GAME_MARKETS)} markets x {regions_count} region(s) x ~{distinct_stamps} snapshots)")
        print(f"  props:        ~{prop_cost:,} credits/day ({len(prop_markets)} markets x {regions_count} region(s) x {len(PROP_OFFSETS_MINUTES)} snapshots x ~{games_per_day} games)")
        print(f"  TOTAL:        ~{per_day * len(dates):,} credits  (ceiling --max-credits={args.max_credits:,})")
        print(f"  writes to:    {book_quotes_path('mlb', dates[0]).parent}")
        print("\nRe-run with --execute to spend.")
        return 0

    state = _load_state()
    done: dict[str, Any] = dict(state.get("dates") or {})
    budget = Budget(args.max_credits)
    total_appended = 0

    for date_str in dates:
        if not args.force and date_str in done:
            print(f"{date_str}: already done ({done[date_str]}), skipping", flush=True)
            continue
        try:
            events = _events_for_date(date_str, api_key=api_key, budget=budget)
            if not events:
                print(f"{date_str}: no events in the historical slate (off-day / All-Star break)", flush=True)
                done[date_str] = {"events": 0, "appended": 0}
                state["dates"] = done
                _save_state(state)
                continue
            appended = 0
            if not args.skip_game_markets:
                appended += _backfill_game_markets(date_str, events, api_key=api_key, budget=budget, regions=args.regions)
            if prop_markets:
                appended += _backfill_props(date_str, events, api_key=api_key, budget=budget, regions=args.regions, markets=prop_markets)
            total_appended += appended
            done[date_str] = {"events": len(events), "appended": appended, "credits_spent_running": budget.spent}
            state["dates"] = done
            state["last_run"] = datetime.now(timezone.utc).isoformat()
            state["credits_spent"] = budget.spent
            state["remaining_reported"] = budget.remaining_reported
            _save_state(state)
            print(
                f"{date_str}: events={len(events)} quotes_appended={appended} "
                f"credits_spent={budget.spent:,} remaining={budget.remaining_reported:,}",
                flush=True,
            )
        except RuntimeError as exc:
            print(f"ABORT at {date_str}: {exc}", flush=True)
            state["dates"] = done
            _save_state(state)
            return 3

    print(f"\nDONE. dates={len(dates)} quotes_appended={total_appended:,} credits_spent={budget.spent:,} calls={budget.calls:,}")
    print(f"remaining (API-reported): {budget.remaining_reported:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
