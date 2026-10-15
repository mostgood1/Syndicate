"""Print the MLB schedule for a given date as normalized JSON on stdout.

Isolated in its own process (invoked via subprocess by
syndicate/features/shared/schedule_adapter.py) so a bug in the StatsAPI
client can't take down the shared schedule adapter every sport's gating
logic depends on.

Off vendor since 2026-10-15 (lane mlb-schedule-fetch-native, user request): this imported StatsApiClient and
fetch_schedule_for_date from the vendored vendor/mlb_bettingv2 sim_engine.data.statsapi. It now uses
syndicate.features.mlb.statsapi_http, a faithful copy of exactly that (no cache, same requests and retries).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    from syndicate.features.mlb.statsapi_http import fetch_schedule_for_date

    try:
        games = fetch_schedule_for_date(str(args.date))
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1

    rows: list[dict[str, object]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        # A postponed/cancelled game's date still matches the query date in
        # MLB's schedule API, so without this it reads back as a real
        # scheduled event -- wrong tip-off-window triggers, wrong "does this
        # date have games" answers downstream in live_refresh_loop.py. Same
        # underlying gap fixed in schedule_adapter.py's basketball path and
        # the vendored WNBA CLI's own schedule filter.
        status = game.get("status") if isinstance(game.get("status"), dict) else {}
        detailed_state = str(status.get("detailedState") or "").strip().lower()
        if detailed_state in {"postponed", "cancelled", "canceled", "suspended"}:
            continue
        game_pk = game.get("gamePk")
        teams = game.get("teams") or {}
        home_team = ((teams.get("home") or {}).get("team") or {})
        away_team = ((teams.get("away") or {}).get("team") or {})
        rows.append(
            {
                "event_id": str(game_pk) if game_pk is not None else None,
                "home": home_team.get("name"),
                "away": away_team.get("name"),
                "start_time_utc": game.get("gameDate"),
                "home_team_id": home_team.get("id"),
                "away_team_id": away_team.get("id"),
            }
        )

    print(json.dumps(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
