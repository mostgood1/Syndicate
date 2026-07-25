"""Write full-squad rosters (every rostered player, not just those with
accumulated per-90 stats) for every team in a league.

Requires scripts/build_team_branding_snapshot.py to have been run first for
this league (reads its team-directory snapshot for the id list -- see
syndicate/features/soccer/sources.py::all_teams). Writes one CSV per
league/season, matching the `rosters_{season}.csv` naming convention other
sports already use:

    data/soccer_source/{league}/api/rosters/rosters_{season}.csv

Usage:
    python scripts/build_soccer_rosters.py --league mls --season 2026
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.features.schedule import default_season
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_teams import fetch_team_roster
from syndicate.features.soccer.sources import SPARSE_ROSTER_THRESHOLD
from syndicate.features.soccer.sources import all_teams
from syndicate.features.soccer.sources import roster_rows
from syndicate.features.soccer.sources import sparse_roster_teams

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.atomic_artifact_write import atomic_write_csv



def _fetch_roster_with_retries(league: str, team_id: str, *, attempts: int = 3, retry_delay: float = 2.0) -> list[dict]:
    """A safety net for genuine request-level flakiness, not a fix for the
    Bundesliga/La Liga/Ligue 1 sparse-roster gap seen this session: that gap
    was verified to persist across retries a few seconds apart (same team,
    same empty result each time), so it's a real if temporally-unstable
    state on ESPN's side -- it changed between two checks ~20 minutes apart
    within the same session, not between requests seconds apart. Retrying
    here cheaply recovers a true transient blip (a dropped connection, a
    momentary 5xx) without doing anything for the slower-timescale gap;
    sparse_roster_teams() and re-running this script later are what surface
    and eventually resolve that one."""
    best: list[dict] = []
    for attempt in range(attempts):
        players = fetch_team_roster(league, team_id)
        if len(players) >= SPARSE_ROSTER_THRESHOLD:
            return players
        if len(players) > len(best):
            best = players
        if attempt < attempts - 1:
            time.sleep(retry_delay)
    return best


def build_rosters(league: str, season: int, *, out_root: Path, sleep_seconds: float = 0.2) -> pd.DataFrame:
    teams = all_teams(league)
    if not teams:
        raise SystemExit(
            f"no team directory for {league}; run scripts/build_team_branding_snapshot.py --sport {league} first"
        )

    rows: list[dict] = []
    for team in teams:
        team_id = str(team.get("team_id") or "").strip()
        team_name = str(team.get("name") or "").strip()
        if not team_id:
            continue
        try:
            players = _fetch_roster_with_retries(league, team_id)
        except Exception as error:
            print(f"skip {team_name} ({team_id}): {error}")
            continue
        for player in players:
            rows.append({"team_id": team_id, "team": team_name, **player})
        time.sleep(sleep_seconds)

    frame = pd.DataFrame(rows)
    out_path = out_root / league / "api" / "rosters" / f"rosters_{season}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_csv(out_path, frame)
    print(f"wrote {out_path} ({len(frame)} players across {len(teams)} teams)")

    # roster_rows/sparse_roster_teams read the file back from disk (not the
    # in-memory frame) so this check exercises the exact same read path the
    # UI uses -- catches a write-side bug here too, not just an upstream
    # ESPN data gap.
    roster_rows.cache_clear()
    sparse = sparse_roster_teams(league, season)
    if sparse:
        print(
            f"WARNING: {len(sparse)}/{len(teams)} {league} teams have fewer than "
            f"{SPARSE_ROSTER_THRESHOLD} players -- likely an incomplete upstream ESPN "
            f"roster for these clubs, not necessarily a bug here:"
        )
        for team in sorted(sparse, key=lambda item: item["player_count"]):
            print(f"    {team['name']} ({team['team_id']}): {team['player_count']} players")

    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(LEAGUE_ESPN_SLUGS))
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    args = parser.parse_args()
    season = args.season or default_season(args.league)
    build_rosters(args.league, season, out_root=Path(args.out_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
