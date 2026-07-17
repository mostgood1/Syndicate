"""Print whether any MLB game is currently live for a given date, as JSON on stdout.

Isolated in its own process (invoked via subprocess by
syndicate/features/shared/live_refresh_loop.py) so a bug in the vendored MLB
client can't take down the shared live-refresh loop every sport's adaptive
phase decision depends on. Mirrors fetch_mlb_schedule_for_date.py's pattern.

This exists as an independent, authoritative signal for "is a game live right
now" -- decoupled from live_lens_report_<date>.json, whose own generation
cadence/timing is exactly what can make it lag behind actual game state.
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

    live_game_pks: list[int] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        status = game.get("status") if isinstance(game.get("status"), dict) else {}
        abstract_state = str(status.get("abstractGameState") or "").strip().lower()
        detailed_state = str(status.get("detailedState") or "").strip().lower()
        if abstract_state == "live" or detailed_state == "in progress":
            game_pk = game.get("gamePk")
            if game_pk is not None:
                try:
                    live_game_pks.append(int(game_pk))
                except (TypeError, ValueError):
                    pass

    print(json.dumps({"live_game_pks": live_game_pks}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
