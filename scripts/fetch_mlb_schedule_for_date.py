"""Print the MLB schedule for a given date as normalized JSON on stdout.

Isolated in its own process (invoked via subprocess by
syndicate/features/shared/schedule_adapter.py) so a bug in the vendored MLB
client can't take down the shared schedule adapter every sport's gating
logic depends on.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_MLB_ROOT = REPO_ROOT / "vendor" / "mlb_bettingv2"
if str(_MLB_ROOT) not in sys.path:
    sys.path.insert(0, str(_MLB_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    from sim_engine.data.statsapi import StatsApiClient, fetch_schedule_for_date

    client = StatsApiClient()
    try:
        games = fetch_schedule_for_date(client, str(args.date))
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1

    rows: list[dict[str, object]] = []
    for game in games:
        if not isinstance(game, dict):
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
            }
        )

    print(json.dumps(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
