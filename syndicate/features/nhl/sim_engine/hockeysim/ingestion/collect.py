"""Owned slate-input collector — writes roster/lineup/starting-goalie CSVs from the NHL API.

The Syndicate replacement for the vendor ``roster-update`` / ``lineup-update`` / starting-goalie
commands. For each team on a date's scoreboard it derives line combinations + a starting goalie from
recent-game TOI (:mod:`lineups`) and writes the three processed CSVs the loaders read, in the exact
columns they expect. Network-based (NHL api-web), cache-first.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from syndicate.local_nhl_odds import _alias_team_abbr, _team_abbr

from ..features.loaders import _load_scoreboard_games, _processed_dir
from .lineups import build_team_usage, infer_lines, project_lineup
from .nhl_web import NhlWebIngestClient

_LINEUP_COLUMNS = ["player_id", "full_name", "position", "line_slot", "pp_unit", "pk_unit", "proj_toi", "confidence", "team"]
_ROSTER_COLUMNS = ["full_name", "player_id", "team", "position", "team_id"]
_GOALIE_COLUMNS = ["team", "goalie", "status", "confidence", "source"]


def _write_csv(path: Path, columns: List[str], rows: List[Dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in columns})
    return len(rows)


def _slate_teams(date: str, root: Optional[Path]) -> List[Tuple[str, str]]:
    """Return ``[(abbr, team_name)]`` for every team on the date's scoreboard (deduped)."""
    seen: Dict[str, str] = {}
    for _pk, home, away in _load_scoreboard_games(date, root=root):
        for name in (home, away):
            ab = _team_abbr(name)
            if ab and ab not in seen:
                seen[ab] = name
    return list(seen.items())


def collect_slate_inputs(
    date: str,
    *,
    root: Optional[Path] = None,
    client: Optional[NhlWebIngestClient] = None,
    n_games: int = 8,
    out_dir: Optional[Path] = None,
    write: bool = True,
) -> Dict[str, object]:
    """Collect + (optionally) write roster/lineup/starting-goalie CSVs for a slate.

    Returns a summary dict with row counts and output paths.
    """
    teams = _slate_teams(date, root)
    client = client or NhlWebIngestClient()
    out_dir = out_dir or _processed_dir(root)

    lineup_rows: List[Dict] = []
    roster_rows: List[Dict] = []
    goalie_rows: List[Dict] = []

    for abbr, team_name in teams:
        usage = build_team_usage(client, _alias_team_abbr(abbr), date=date, n_games=n_games)
        if not usage:
            continue
        infer_lines(usage)
        project_lineup(usage)
        for r in usage:
            lineup_rows.append({
                "player_id": r["player_id"], "full_name": r["full_name"], "position": r["position"],
                "line_slot": r.get("line_slot"), "pp_unit": r.get("pp_unit"), "pk_unit": r.get("pk_unit"),
                "proj_toi": r.get("proj_toi"), "confidence": 0.5, "team": team_name,
            })
            roster_rows.append({
                "full_name": r["full_name"], "player_id": r["player_id"], "team": team_name,
                "position": r["position"], "team_id": "",
            })
        starter = next((r for r in usage if r.get("is_starter_goalie")), None)
        if starter:
            goalie_rows.append({
                "team": team_name, "goalie": starter["full_name"], "status": "projected",
                "confidence": 0.5, "source": "hockeysim_toi",
            })

    summary: Dict[str, object] = {
        "date": date, "teams": len(teams),
        "lineup_rows": len(lineup_rows), "roster_rows": len(roster_rows), "goalies": len(goalie_rows),
    }
    if write:
        lineups_path = out_dir / f"lineups_{date}.csv"
        roster_path = out_dir / f"roster_snapshot_{date}.csv"
        goalies_path = out_dir / f"starting_goalies_{date}.csv"
        _write_csv(lineups_path, _LINEUP_COLUMNS, lineup_rows)
        _write_csv(roster_path, _ROSTER_COLUMNS, roster_rows)
        _write_csv(goalies_path, _GOALIE_COLUMNS, goalie_rows)
        summary["lineups_path"] = str(lineups_path)
        summary["roster_path"] = str(roster_path)
        summary["goalies_path"] = str(goalies_path)
    else:
        summary["_lineups"] = lineup_rows
        summary["_roster"] = roster_rows
        summary["_goalies"] = goalie_rows
    return summary
