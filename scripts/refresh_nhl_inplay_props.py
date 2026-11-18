"""One NHL in-play player-prop pull: live games only, one call per game, into the shared quote log.

Launched by `syndicate.features.nhl.inplay_props_lane.launch_autorun_nhl_inplay_props` on the
live-odds-worker's capture thread (lane nhl-inplay-props-drop). Read that module for why it exists and
what it costs. Prints ONE line, `[nhl_inplay_props] PULL {...}`, which the worker's log keeps: stdout is
inherited, not captured.

    python scripts/refresh_nhl_inplay_props.py --date 2026-11-17
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _utc_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pull(date: str, *, now: datetime | None = None, client: Any = None, append: Any = None) -> dict[str, Any]:
    """Fetch every live NHL game's props once and append them. Returns the PULL summary."""
    import pandas as pd

    from syndicate.features.nhl import inplay_props_lane as lane
    from syndicate.local_nhl_odds import (
        NHL_PROP_BOOKMAKERS,
        NHL_REGULAR_SPORT_KEY,
        OddsApiClient,
        _append_nhl_book_quotes,
        _event_sport_key,
        list_nhl_events,
    )

    started = time.monotonic()
    moment = now or datetime.now(timezone.utc)
    client = client or OddsApiClient(rate_limit_per_sec=10.0)
    append = append or _append_nhl_book_quotes
    # The sweep's own overrides, so the two pulls always ask for the same books.
    bookmakers = os.getenv("PROPS_ODDSAPI_BOOKMAKERS", NHL_PROP_BOOKMAKERS).strip() or None
    regions = os.getenv("PROPS_ODDSAPI_REGIONS", "us").strip() or "us"
    markets = ",".join(lane.NHL_INPLAY_PROP_MARKETS)
    # `/events` draws nothing on the quota. The window is "started in the last 4 h"; `live_events` applies it.
    listed = list_nhl_events(
        client,
        commence_from_iso=_utc_iso(moment - timedelta(seconds=lane._LIVE_AFTER_START_SECONDS)),
        commence_to_iso=_utc_iso(moment),
    )
    live = lane.live_events(listed, now=moment)
    collected_at = _utc_iso(moment)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    credits = 0.0
    with_props = 0

    def fetch(event: dict[str, Any]):
        # ONE call, no fallback: a retry without the book list or per market multiplies credits, and a
        # live pull that misses is retried on the next tick anyway.
        return event, client.event_odds(_event_sport_key(event, NHL_REGULAR_SPORT_KEY), str(event["id"]),
                                        markets=markets, regions=regions, bookmakers=bookmakers)

    with ThreadPoolExecutor(max_workers=max(1, min(6, len(live) or 1))) as pool:
        futures = [pool.submit(fetch, event) for event in live]
        for future in as_completed(futures):
            try:
                event, (payload, headers) = future.result()
            except Exception as exc:  # noqa: BLE001 -- one game's failure never costs the others
                errors.append(f"{type(exc).__name__}: {exc}"[:200])
                continue
            try:
                credits += float((headers or {}).get("x-requests-last") or 0)
            except (TypeError, ValueError):
                pass
            parsed = lane.parse_prop_event(payload, date=date, collected_at=collected_at)
            if parsed:
                with_props += 1
            rows.extend(parsed)
    distribution = append(pd.DataFrame(rows), date=date, kind="prop") if rows else None
    return {
        "date": date,
        "at": collected_at,
        "events_listed": len(listed),
        "events_live": len(live),
        "events_with_props": with_props,
        "rows": len(rows),
        "credits": credits,
        "errors": errors,
        "by_game_date": (distribution or {}).get("by_game_date") if isinstance(distribution, dict) else None,
        "append_error": (distribution or {}).get("error") if isinstance(distribution, dict) else None,
        "elapsed_s": round(time.monotonic() - started, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", required=True, help="the board (Central) date the worker's slate is on")
    args = parser.parse_args(argv)
    try:
        summary = pull(str(args.date))
    except Exception as exc:  # noqa: BLE001
        print(f"[nhl_inplay_props] PULL_FAILED date={args.date} {type(exc).__name__}: {exc}", flush=True)
        return 1
    print("[nhl_inplay_props] PULL " + json.dumps(summary, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
