"""Build Syndicate-UI-facing soccer artifacts for one league/date.

Fetches the league's ESPN scoreboard for the date (upcoming + in-progress
fixtures), rates teams from locally ingested history, runs SoccerSim
(``SoccerSimulationAdapter.simulate_props``, which also produces the game-
level outputs), and writes two artifacts under ``data/soccer_source/{league}/api/``:

- ``recommendations/recommendations_{date}.json`` -- one row per fixture
  (win/draw/away probability, projected score, total/BTTS, shot/corner
  volume) plus a flat list of top player-prop projections. This is the one
  file ``syndicate/features/soccer/cards.py`` reads.
- ``display_prediction_dates.json`` -- the running date index cards/archive
  use for date-picker navigation, in the same ``{"dates": [...], "latest":
  ...}`` shape NCAAB's mirror uses.

Usage:
    python scripts/build_soccer_artifacts.py --league epl --date 2026-07-19
    python scripts/build_soccer_artifacts.py --league epl  # defaults to today
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

from syndicate.features.soccer.adapters import build_soccer_simulation_adapter
from syndicate.features.soccer.features.loaders import build_soccer_simulation_input
from syndicate.features.soccer.features.loaders import compute_team_ratings
from syndicate.features.soccer.features.loaders import team_rows_from_match_history
from syndicate.features.soccer.features.team_names import match_team_name
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_lineups import fetch_events
from syndicate.features.soccer.ingestion.player_history import fetch_asa_mls_team_history

_GOALS_BASED_RATING_LEAGUES = {"eredivisie", "primeira_liga", "championship", "belgian_pro_league"}
PROMOTED_TEAM_RATING = {"attack_rating": -0.18, "defense_rating": -0.18}
_DEFAULT_SIMULATIONS = 400


def _api_root(league: str, out_root: Path) -> Path:
    return out_root / league / "api"


def _load_team_ratings(league: str, source_root: Path) -> dict[str, dict[str, float]]:
    if league == "mls":
        rows = fetch_asa_mls_team_history(date_cls.today().year)
        return compute_team_ratings(rows)
    if league in _GOALS_BASED_RATING_LEAGUES:
        history_dir = source_root / league / "history"
        frames = [pd.read_csv(path) for path in sorted(history_dir.glob("matches_*.csv"))]
        if not frames:
            raise SystemExit(f"no match history under {history_dir}; run fetch_soccer_history_local.py --kind matches first")
        match_rows = pd.concat(frames, ignore_index=True).to_dict("records")
        rows = team_rows_from_match_history(match_rows)
        return compute_team_ratings(rows, window=90)
    history_dir = source_root / league / "team_history"
    frames = [pd.read_csv(path) for path in sorted(history_dir.glob("teams_*.csv"))]
    if not frames:
        raise SystemExit(f"no team history under {history_dir}; run fetch_soccer_history_local.py --kind teams first")
    rows = pd.concat(frames, ignore_index=True).to_dict("records")
    return compute_team_ratings(rows, window=45)


def _load_player_rows(league: str, source_root: Path) -> list[dict[str, Any]]:
    players_dir = source_root / league / "players"
    frames = [pd.read_csv(path) for path in sorted(players_dir.glob("players_*.csv"))]
    if not frames:
        return []
    return pd.concat(frames, ignore_index=True).to_dict("records")


def _fill_promoted(ratings: dict[str, dict[str, float]], team_names: list[str]) -> list[str]:
    filled: list[str] = []
    for team in team_names:
        if match_team_name(team, list(ratings)) is None:
            ratings[team] = dict(PROMOTED_TEAM_RATING)
            filled.append(team)
    return filled


def _fetch_fixtures(league: str, iso_date: str) -> list[dict[str, Any]]:
    compact = iso_date.replace("-", "")
    window = f"{compact}-{compact}"
    events = fetch_events(league, date_windows=[window], statuses={"pre", "in", "post"})
    fixtures: list[dict[str, Any]] = []
    for event in events:
        home = str(event.get("home_team") or "").strip()
        away = str(event.get("away_team") or "").strip()
        if not home or not away:
            continue
        fixtures.append(
            {
                "event_id": str(event.get("event_id") or ""),
                "home_team": home,
                "away_team": away,
                "kickoff": event.get("date"),
                "status_state": event.get("status_state"),
                "home_score": event.get("home_score"),
                "away_score": event.get("away_score"),
            }
        )
    return fixtures


def _top_props_for_match(player_outputs: list[dict[str, Any]], match_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = [row for row in player_outputs if row.get("match_id") == match_id]
    rows.sort(key=lambda row: row.get("anytime_scorer_probability") or 0.0, reverse=True)
    return [
        {
            "player_id": row.get("player_id"),
            "player_name": row.get("player_name"),
            "team": row.get("team"),
            "side": row.get("side"),
            "position": row.get("position"),
            "anytime_scorer_probability": row.get("anytime_scorer_probability"),
            "expected_shots": row.get("expected_shots"),
            "expected_shots_on_target": row.get("expected_shots_on_target"),
            "expected_minutes_share": row.get("expected_minutes_share"),
        }
        for row in rows[:limit]
    ]


def build_artifacts(league: str, iso_date: str, *, source_root: Path, out_root: Path, simulations: int) -> dict[str, Any]:
    if league not in LEAGUE_ESPN_SLUGS:
        raise SystemExit(f"unknown league {league!r}; choices: {sorted(LEAGUE_ESPN_SLUGS)}")

    fixtures_raw = _fetch_fixtures(league, iso_date)
    api_root = _api_root(league, out_root)
    rec_path = api_root / "recommendations" / f"recommendations_{iso_date}.json"

    if not fixtures_raw:
        payload = {"league": league, "date": iso_date, "generated_at": pd.Timestamp.now("UTC").isoformat(), "matches": [], "player_props": []}
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _update_date_index(api_root, iso_date)
        print(f"no ESPN fixtures found for {league} on {iso_date}; wrote empty artifact")
        return payload

    ratings = _load_team_ratings(league, source_root)
    team_names = [fixture["home_team"] for fixture in fixtures_raw] + [fixture["away_team"] for fixture in fixtures_raw]
    promoted = _fill_promoted(ratings, team_names)
    player_rows = _load_player_rows(league, source_root)

    fixtures = [
        {
            "match_id": fixture["event_id"] or f"{league}_{iso_date}_{fixture['home_team']}_{fixture['away_team']}".replace(" ", "_"),
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
        }
        for fixture in fixtures_raw
    ]
    simulation_input = build_soccer_simulation_input(
        league=league,
        date=iso_date,
        fixtures=fixtures,
        ratings=ratings,
        player_rows=player_rows,
        simulations=simulations,
    )
    adapter = build_soccer_simulation_adapter(league)
    output = adapter.simulate_props(simulation_input)
    match_outputs = list(output.match_outputs)
    player_outputs = list(output.player_outputs)
    print(f"simulated {len(match_outputs)} {league} matches, {len(player_outputs)} player projections for {iso_date}")

    fixture_meta_by_id = {fixture["event_id"] or fixtures[i]["match_id"]: fixture for i, fixture in enumerate(fixtures_raw)}
    matches: list[dict[str, Any]] = []
    for match_output in match_outputs:
        match_id = match_output["match_id"]
        meta = fixture_meta_by_id.get(match_id, {})
        matches.append(
            {
                **match_output,
                "event_id": meta.get("event_id") or match_id,
                "kickoff": meta.get("kickoff"),
                "status_state": meta.get("status_state") or "pre",
                "live_home_score": meta.get("home_score"),
                "live_away_score": meta.get("away_score"),
                "top_props": _top_props_for_match(player_outputs, match_id),
            }
        )

    payload = {
        "league": league,
        "date": iso_date,
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "simulations": simulations,
        "promoted_prior_teams": promoted,
        "matches": matches,
        "player_props": [
            {
                "player_id": row.get("player_id"),
                "player_name": row.get("player_name"),
                "team": row.get("team"),
                "side": row.get("side"),
                "position": row.get("position"),
                "match_id": row.get("match_id"),
                "anytime_scorer_probability": row.get("anytime_scorer_probability"),
                "anytime_scorer_probability_if_playing": row.get("anytime_scorer_probability_if_playing"),
                "expected_shots": row.get("expected_shots"),
                "expected_shots_if_playing": row.get("expected_shots_if_playing"),
                "expected_shots_on_target": row.get("expected_shots_on_target"),
                "expected_shots_on_target_if_playing": row.get("expected_shots_on_target_if_playing"),
                "expected_minutes_share": row.get("expected_minutes_share"),
            }
            for row in player_outputs
        ],
    }
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _update_date_index(api_root, iso_date)
    print(f"wrote {rec_path}")
    return payload


def _update_date_index(api_root: Path, iso_date: str) -> None:
    index_path = api_root / "display_prediction_dates.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if index_path.exists():
        try:
            existing = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    dates = set(existing.get("dates") or [])
    dates.add(iso_date)
    sorted_dates = sorted(dates)
    index_path.write_text(json.dumps({"dates": sorted_dates, "latest": sorted_dates[-1]}, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(LEAGUE_ESPN_SLUGS))
    parser.add_argument("--date", default=None, help="ISO date, default today")
    parser.add_argument("--simulations", type=int, default=_DEFAULT_SIMULATIONS)
    parser.add_argument("--source-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    args = parser.parse_args()

    iso_date = args.date or date_cls.today().isoformat()
    build_artifacts(
        args.league,
        iso_date,
        source_root=Path(args.source_root),
        out_root=Path(args.out_root),
        simulations=args.simulations,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
