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
from ..features.props_lines import initial_surname_key, load_props_lines, normalize_name
from .lineups import ASSIST_SHARE_PRIOR_SEASON_WEIGHT, attach_assist_share, build_team_usage, infer_lines, project_lineup
from .nhl_web import NhlWebIngestClient, season_code_for_date

_LINEUP_COLUMNS = ["player_id", "full_name", "position", "line_slot", "pp_unit", "pk_unit", "proj_toi", "confidence", "team",
                   "proj_ev_toi", "assist_share"]
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


def _book_listed_ids(usage: List[Dict], team_name: str, lines: List[Dict]) -> set:
    """Skaters in ``usage`` a current book line names, for a game this team plays.

    Exact normalized name first, then a UNIQUE initial+surname within the team (the usage name can be
    the boxscore's abbreviation). Lines without team names are ignored: an abbreviation must never
    reach across games.
    """
    team = normalize_name(team_name)
    names = {normalize_name(l.get("player_name")) for l in lines
             if team and team in (normalize_name(l.get("home_team")), normalize_name(l.get("away_team")))}
    if not names:
        return set()
    skaters = [r for r in usage if r.get("position") in ("F", "D")]
    by_full = {normalize_name(r.get("full_name")): int(r["player_id"]) for r in skaters}
    by_abbr: Dict[str, List[int]] = {}
    for r in skaters:
        by_abbr.setdefault(initial_surname_key(r.get("full_name")), []).append(int(r["player_id"]))
    out = set()
    for n in names:
        if n in by_full:
            out.add(by_full[n])
            continue
        cands = by_abbr.get(initial_surname_key(n), [])
        if len(cands) == 1:
            out.add(cands[0])
    return out


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
    try:
        book_lines = load_props_lines(date, root=root)
    except Exception:  # noqa: BLE001 - the lines only steer who dresses; the lineup must still build
        book_lines = []
    roster_rows: List[Dict] = []
    goalie_rows: List[Dict] = []

    for abbr, team_name in teams:
        team_code = _alias_team_abbr(abbr)
        # FULL names, not the boxscore's "A. Copp": the props producer joins book lines by name, and
        # with abbreviated names it matched 0 of 339 lines on 2026-10-02 (every NHL prop unprojected).
        name_map = client.roster_full_names(team_code, season_code_for_date(date))
        usage = build_team_usage(client, team_code, date=date, n_games=n_games, name_map=name_map)
        # Early in a season the usage window reaches back into LAST season's games
        # (`recent_finished_game_ids`), so a player who left in the summer would keep his old
        # team's slot. When the club roster is known, only its players are dressed.
        if name_map:
            usage = [r for r in usage if int(r["player_id"]) in name_map]
        if not usage:
            continue
        infer_lines(usage, must_dress=_book_listed_ids(usage, team_name, book_lines))
        project_lineup(usage, date=date)
        season = season_code_for_date(date)
        prev = f"{int(season[:4]) - 1}{season[:4]}" if len(season) == 8 else ""
        attach_assist_share(usage, [(client.onice_goals(team_code, season), 1.0),
                                    (client.onice_goals(team_code, prev) if prev else {}, ASSIST_SHARE_PRIOR_SEASON_WEIGHT)],
                            date)
        for r in usage:
            lineup_rows.append({
                "player_id": r["player_id"], "full_name": r["full_name"], "position": r["position"],
                "line_slot": r.get("line_slot"), "pp_unit": r.get("pp_unit"), "pk_unit": r.get("pk_unit"),
                "proj_toi": r.get("proj_toi"), "confidence": 0.5, "team": team_name,
                "proj_ev_toi": r.get("proj_ev_toi"),
                "assist_share": r.get("assist_share"),
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
