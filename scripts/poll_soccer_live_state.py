"""Poll ESPN for in-progress matches and write a soccer live-lens snapshot.

For every league fixture ESPN currently reports as ``in`` progress, rebuilds
the current match state (score, cards, corners, shots-so-far per player --
via ``espn_live_state.build_live_state``) and projects it forward with the
resumed-match live lens (``features/soccer/features/live_lens.py``):
updated three-way/total/BTTS/corners, goal-in-the-next-10-minutes
probability, and live shot-prop projections for the players who have
appeared. Writes one artifact per league/date:

    data/soccer_source/{league}/api/live_state/live_state_{date}.json

``syndicate/features/soccer/live_lens.py`` (the UI feature module) reads
this directly -- no engine work happens in the request path.

Usage:
    python scripts/poll_soccer_live_state.py --league epl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_cls
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.build_soccer_artifacts import _fill_promoted
from scripts.build_soccer_artifacts import _load_player_rows
from scripts.build_soccer_artifacts import _load_team_ratings
from syndicate.features.soccer.features.live_lens import goal_in_window_probability
from syndicate.features.soccer.features.live_lens import project_live_match
from syndicate.features.soccer.features.live_lens import project_live_player_props
from syndicate.features.soccer.features.team_names import match_team_name
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_lineups import fetch_events
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary
from syndicate.features.soccer.ingestion.espn_live_state import build_live_state

_GOAL_WINDOWS_SECONDS = {"next_10_min": 600.0, "next_5_min": 300.0}


def _team_player_rows(player_rows: list[dict[str, Any]], team_name: str) -> list[dict[str, Any]]:
    rows = []
    for row in player_rows:
        matched = match_team_name(str(row.get("team") or ""), [team_name])
        if matched is not None:
            rows.append(row)
    return rows


def _rating_for(ratings: dict[str, dict[str, float]], team_name: str) -> dict[str, float]:
    matched = match_team_name(team_name, list(ratings))
    if matched is None:
        return {"attack_rating": -0.18, "defense_rating": -0.18}
    return ratings[matched]


def poll_league(league: str, iso_date: str, *, source_root: Path, out_root: Path, simulations: int) -> dict[str, Any]:
    compact = iso_date.replace("-", "")
    window = f"{compact}-{compact}"
    live_events = fetch_events(league, date_windows=[window], statuses={"in"})
    api_root = out_root / league / "api"
    out_path = api_root / "live_state" / f"live_state_{iso_date}.json"

    games: dict[str, Any] = {}
    if live_events:
        ratings = _load_team_ratings(league, source_root)
        team_names = [event["home_team"] for event in live_events] + [event["away_team"] for event in live_events]
        _fill_promoted(ratings, team_names)
        player_rows = _load_player_rows(league, source_root)

        for event in live_events:
            event_id = str(event.get("event_id") or "")
            if not event_id:
                continue
            try:
                summary = fetch_match_summary(league, event_id)
                live_state = build_live_state(summary, event_id=event_id, home_team=event.get("home_team"), away_team=event.get("away_team"))
            except Exception as error:
                print(f"skip {event_id}: {error}")
                continue

            home_rating = _rating_for(ratings, live_state["home_team"])
            away_rating = _rating_for(ratings, live_state["away_team"])
            projection = project_live_match(live_state, home_rating=home_rating, away_rating=away_rating, simulations=simulations)
            goal_windows = {
                label: goal_in_window_probability(live_state, home_rating=home_rating, away_rating=away_rating, window_seconds=seconds, simulations=simulations)
                for label, seconds in _GOAL_WINDOWS_SECONDS.items()
            }
            home_players = _team_player_rows(player_rows, live_state["home_team"])
            away_players = _team_player_rows(player_rows, live_state["away_team"])
            live_props = project_live_player_props(
                live_state,
                home_rating=home_rating,
                away_rating=away_rating,
                home_player_rows=home_players,
                away_player_rows=away_players,
                simulations=simulations,
            )
            games[event_id] = {
                "event_id": event_id,
                "home_team": live_state["home_team"],
                "away_team": live_state["away_team"],
                "half": live_state["half"],
                "clock_remaining": live_state["clock_remaining"],
                "score_home": live_state["score_home"],
                "score_away": live_state["score_away"],
                "home_red_cards": live_state["home_red_cards"],
                "away_red_cards": live_state["away_red_cards"],
                "home_shots_so_far": live_state["home_shots_so_far"],
                "away_shots_so_far": live_state["away_shots_so_far"],
                "home_shots_on_target_so_far": live_state["home_shots_on_target_so_far"],
                "away_shots_on_target_so_far": live_state["away_shots_on_target_so_far"],
                "home_corners_so_far": live_state["home_corners_so_far"],
                "away_corners_so_far": live_state["away_corners_so_far"],
                "projection": projection.to_dict(),
                "goal_windows": goal_windows,
                "live_player_props": [row.to_dict() for row in sorted(live_props, key=lambda r: r.projected_final_shots, reverse=True)[:12]],
            }

    payload = {
        "league": league,
        "date": iso_date,
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "count": len(games),
        "games": games,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(games)} live games)")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(LEAGUE_ESPN_SLUGS))
    parser.add_argument("--date", default=None, help="ISO date, default today")
    parser.add_argument("--simulations", type=int, default=300)
    parser.add_argument("--source-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    args = parser.parse_args()
    iso_date = args.date or date_cls.today().isoformat()
    poll_league(args.league, iso_date, source_root=Path(args.source_root), out_root=Path(args.out_root), simulations=args.simulations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
