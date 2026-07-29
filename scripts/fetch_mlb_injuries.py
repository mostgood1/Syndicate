"""Fetch current-day MLB IL/DL status per team, as JSON on stdout.

Isolated in its own process (invoked via subprocess by
syndicate/features/shared/live_refresh_loop.py) so a bug in the vendored MLB
client can't take down the shared live-refresh loop's fingerprint check --
same reasoning as fetch_mlb_live_game_pks_for_date.py, whose pattern this
mirrors exactly.

Reuses the same IL/DL detection logic vendor/mlb_bettingv2/tools/daily_update.py's
roster-fetch step already applies (that file's nested _status_is_injured,
duplicated here rather than imported since it's a closure inside a much larger
workflow function, not an importable module-level helper). This script exists
to make that same signal available on a cheap standalone cadence, independent
of running the full daily sim -- MLB had no distinct injury-report ingestion
before this (unlike NBA/WNBA's dedicated fetch-injuries CLI command), so a
scratch that hadn't yet reached the posted lineup artifact went undetected
between sim runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
_MLB_ROOT = REPO_ROOT / "vendor" / "mlb_bettingv2"
if str(_MLB_ROOT) not in sys.path:
    sys.path.insert(0, str(_MLB_ROOT))


def _status_is_injured(status_obj: Any) -> bool:
    # Mirrors vendor/mlb_bettingv2/tools/daily_update.py's nested
    # _status_is_injured exactly -- keep both in sync if StatsAPI's status
    # code/description shapes ever change.
    if not isinstance(status_obj, dict) or not status_obj:
        return False
    code = str(status_obj.get("code") or "").strip().upper()
    desc = str(status_obj.get("description") or "").strip().lower()
    if code.startswith("IL") or code.startswith("DL"):
        return True
    # StatsAPI often uses D10/D15/D60/etc for disabled list.
    if len(code) >= 2 and code.startswith("D") and any(ch.isdigit() for ch in code[1:]):
        return True
    if "injured list" in desc or "disabled list" in desc:
        return True
    return False


def _team_ids_playing(games: list[dict[str, Any]]) -> list[int]:
    team_ids: set[int] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        teams = game.get("teams") if isinstance(game.get("teams"), dict) else {}
        for side in ("away", "home"):
            side_obj = teams.get(side) if isinstance(teams.get(side), dict) else {}
            team = side_obj.get("team") if isinstance(side_obj.get("team"), dict) else {}
            try:
                team_id = int(team.get("id") or 0)
            except (TypeError, ValueError):
                team_id = 0
            if team_id > 0:
                team_ids.add(team_id)
    return sorted(team_ids)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    from sim_engine.data.statsapi import StatsApiClient, fetch_schedule_for_date, fetch_team_roster

    client = StatsApiClient()
    try:
        games = fetch_schedule_for_date(client, str(args.date))
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1

    teams_out: dict[str, list[dict[str, Any]]] = {}
    for team_id in _team_ids_playing(games):
        injured_players: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for roster_type in ("active", "40Man"):
            try:
                entries = fetch_team_roster(client, team_id, roster_type=roster_type, date_str=str(args.date))
            except Exception:
                continue
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                person = entry.get("person") if isinstance(entry.get("person"), dict) else {}
                try:
                    player_id = int(person.get("id") or 0)
                except (TypeError, ValueError):
                    player_id = 0
                if player_id <= 0 or player_id in seen_ids:
                    continue
                status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
                if _status_is_injured(status):
                    seen_ids.add(player_id)
                    injured_players.append(
                        {
                            "player_id": player_id,
                            "full_name": person.get("fullName"),
                            "status": status,
                            "position": entry.get("position"),
                            "roster_type_source": roster_type,
                        }
                    )
        teams_out[str(team_id)] = injured_players

    print(json.dumps({"date": str(args.date), "teams": teams_out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
