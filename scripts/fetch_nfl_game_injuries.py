#!/usr/bin/env python3
"""Capture NFL game-day injury statuses for games inside the T-3h window.

One ESPN scoreboard call for the date, then one game-summary call per game
starting within the window (`syndicate/features/nfl/game_injuries.py` has the
source notes, including what is NOT confirmed about inactives). Writes per-game
snapshots, a change log, and the timestamp-free `statuses_<date>.json` the
starting-soon trigger fingerprints.

Always prints one `NFL_GAME_INJURIES_FETCH` line, so a run that captured
nothing says why. Exits non-zero only when the scoreboard itself failed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import game_injuries as gi  # noqa: E402


def _get_json(url: str, *, timeout: float) -> object:
    # No custom User-Agent: see fetch_espn_live_status_for_date.py -- ESPN 403s
    # browser-like UAs from Render's IP and accepts urllib's own.
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def run(date_str: str, *, now_epoch: float, timeout: float = 8.0, fetch=_get_json, publish=None) -> dict:
    publish = publish or _publish_statuses
    compact = date_str.replace("-", "")
    result = {"date": date_str, "events_total": 0, "events_in_window": 0, "fetched": 0, "rows": 0,
              "changes": 0, "shape_unknown": 0, "errors": 0, "statuses_rewritten": False,
              "statuses_published": False}
    try:
        scoreboard = fetch(gi.SCOREBOARD_URL.format(compact_date=compact), timeout=timeout)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        result["error"] = f"scoreboard {type(exc).__name__}: {exc}"
        return result
    events = gi.parse_scoreboard_events(scoreboard)
    in_window = gi.events_in_window(events, now_epoch=now_epoch)
    result["events_total"], result["events_in_window"] = len(events), len(in_window)
    captured_at = datetime.fromtimestamp(now_epoch, tz=timezone.utc).isoformat(timespec="seconds")
    for event in in_window:
        try:
            summary = fetch(gi.SUMMARY_URL.format(event_id=event.event_id), timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            result["errors"] += 1
            print(f"[nfl_game_injuries] SUMMARY_FETCH_FAILED event={event.event_id} {type(exc).__name__}: {exc}", flush=True)
            continue
        rows, shape_ok = gi.parse_summary_injuries(summary, event.event_id)
        if not shape_ok:
            # LOUD: an unrecognised summary is not "nobody is hurt".
            result["shape_unknown"] += 1
            print(f"[nfl_game_injuries] SUMMARY_SHAPE_UNKNOWN event={event.event_id} keys={sorted(summary)[:12] if isinstance(summary, dict) else type(summary).__name__}", flush=True)
            continue
        changes = gi.record_game(date_str, event, rows, captured_at=captured_at)
        result["fetched"] += 1
        result["rows"] += len(rows)
        result["changes"] += len(changes)
        for change in changes:
            print(
                f"[nfl_game_injuries] STATUS_CHANGE event={event.event_id} {change.get('team_abbr')} "
                f"{change.get('athlete_name')} {change.get('change')} {change.get('from') or ''}->{change.get('status')}",
                flush=True,
            )
    if result["fetched"]:
        result["statuses_rewritten"] = gi.rebuild_statuses(date_str)
        if result["statuses_rewritten"]:
            result["statuses_published"] = publish(gi.statuses_path(date_str))
    return result


def _publish_statuses(path: Path) -> bool:
    """Push `statuses_<date>.json` to web, which live-odds-worker pulls from.

    THE READER IS ON ANOTHER SERVICE. The starting-soon injury trigger runs in
    `live_refresh_loop` on live-odds-worker; this script runs on refresh-worker,
    and Render disks are per-service. Written here and never published, the
    file was invisible to the trigger (found 2026-09-28). Only on a REWRITE --
    `rebuild_statuses` returns False when no status changed, so an unchanged
    tick costs no request. Never raises: a failed publish must not fail the
    capture, which is still recorded locally.
    """
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = bool(publish_hot_artifact(path))
    except Exception as exc:  # noqa: BLE001 -- best effort, see docstring
        print(f"[nfl_game_injuries] STATUSES_PUBLISH_FAILED {type(exc).__name__}: {exc}", flush=True)
        return False
    if not published:
        print(f"[nfl_game_injuries] STATUSES_NOT_PUBLISHED path={path}", flush=True)
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Central date YYYY-MM-DD (default: today, Central)")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.date:
        date_str = args.date
    else:
        from syndicate.features.shared.timezone import central_today_iso

        date_str = central_today_iso()
    result = run(date_str, now_epoch=time.time(), timeout=args.timeout)
    print(
        "[nfl_game_injuries] NFL_GAME_INJURIES_FETCH "
        + " ".join(f"{key}={value}" for key, value in result.items()),
        flush=True,
    )
    if args.json:
        print(json.dumps(result))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
