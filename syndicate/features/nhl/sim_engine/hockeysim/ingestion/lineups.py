"""Derive line combinations + starting goalie from recent-game TOI (owned port of vendor logic).

Ports ``nhl_betting/data/rosters.py`` ``infer_lines`` / ``project_toi`` (the TOI-ranking line model)
onto the NHL ``api-web`` boxscore feed. The api-web boxscore lacks per-player PP/PK TOI, so unit
assignment uses the overall-TOI ranking as a proxy (top skaters -> PP1/PP2, etc.); line slots and the
starter-goalie heuristic follow the vendor exactly.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .nhl_web import NhlWebIngestClient, season_code_for_date


def _toi_to_min(value: object) -> float:
    s = str(value or "").strip()
    if ":" not in s:
        return 0.0
    mm, ss = s.split(":", 1)
    try:
        return int(mm) + int(ss) / 60.0
    except ValueError:
        return 0.0


def _canonical_pos(raw: object) -> str:
    token = str(raw or "").strip().upper()
    if token == "G":
        return "G"
    if token in ("D", "LD", "RD"):
        return "D"
    return "F"


def _abbr_of(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("default") or "").upper()
    return str(value or "").upper()


def _name_of(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("default") or "").strip()
    return str(value or "").strip()


def build_team_usage(
    client: NhlWebIngestClient,
    team_abbr: str,
    *,
    date: str,
    n_games: int = 8,
    name_map: Optional[Dict[int, str]] = None,
) -> List[Dict]:
    """Aggregate a team's per-player recent-game TOI into usage rows.

    Returns ``[{player_id, full_name, position, games_played, toi_avg}]`` sorted by TOI desc.
    """
    season = season_code_for_date(date)
    game_ids = client.recent_finished_game_ids(team_abbr, season, before_date=date, n=n_games)
    acc: Dict[int, Dict] = {}
    for gid in game_ids:
        box = client.boxscore(gid)
        if not box:
            continue
        pbg = box.get("playerByGameStats") or {}
        side = None
        if _abbr_of((box.get("homeTeam") or {}).get("abbrev")) == team_abbr.upper():
            side = "homeTeam"
        elif _abbr_of((box.get("awayTeam") or {}).get("abbrev")) == team_abbr.upper():
            side = "awayTeam"
        if side is None:
            continue
        team_stats = pbg.get(side) or {}
        for group in ("forwards", "defense", "goalies"):
            for p in team_stats.get(group) or []:
                pid = p.get("playerId")
                if pid is None:
                    continue
                pid = int(pid)
                pos = _canonical_pos(p.get("position") or ("G" if group == "goalies" else ("D" if group == "defense" else "F")))
                row = acc.setdefault(pid, {
                    "player_id": pid,
                    "full_name": (name_map or {}).get(pid) or _name_of(p.get("name")),
                    "position": pos,
                    "games_played": 0,
                    "toi_total": 0.0,
                })
                row["games_played"] += 1
                row["toi_total"] += _toi_to_min(p.get("toi"))
    usage = []
    for row in acc.values():
        gp = max(1, row["games_played"])
        row["toi_avg"] = round(row["toi_total"] / gp, 3)
        usage.append(row)
    usage.sort(key=lambda r: r["toi_avg"], reverse=True)
    return usage


def infer_lines(usage: List[Dict]) -> List[Dict]:
    """Assign line_slot (L1-L4 / D1-D3), pp_unit, pk_unit by TOI ranking (vendor algorithm)."""
    forwards = [r for r in usage if r["position"] == "F"]
    defense = [r for r in usage if r["position"] == "D"]
    forwards.sort(key=lambda r: r["toi_avg"], reverse=True)
    defense.sort(key=lambda r: r["toi_avg"], reverse=True)

    for idx, r in enumerate(forwards):
        r["line_slot"] = ("L1", "L2", "L3", "L4")[idx // 3] if idx < 12 else None
    for idx, r in enumerate(defense):
        r["line_slot"] = ("D1", "D2", "D3")[idx // 2] if idx < 6 else None
    for r in usage:
        if r["position"] == "G":
            r["line_slot"] = None

    # PP/PK proxy from overall TOI among skaters (api-web lacks per-strength TOI).
    skaters = sorted([r for r in usage if r["position"] != "G"], key=lambda r: r["toi_avg"], reverse=True)
    pp1 = {r["player_id"] for r in skaters[:5]}
    pp2 = {r["player_id"] for r in skaters[5:10]}
    pk1 = {r["player_id"] for r in skaters[:4]}
    pk2 = {r["player_id"] for r in skaters[4:8]}
    for r in usage:
        pid = r["player_id"]
        r["pp_unit"] = 1 if pid in pp1 else (2 if pid in pp2 else None)
        r["pk_unit"] = 1 if pid in pk1 else (2 if pid in pk2 else None)
    return usage


def project_lineup(usage: List[Dict]) -> List[Dict]:
    """Add proj_toi (recent avg) and flag the starter goalie (highest recent goalie TOI)."""
    goalies = sorted([r for r in usage if r["position"] == "G"], key=lambda r: r["toi_avg"], reverse=True)
    starter_id = goalies[0]["player_id"] if goalies else None
    for r in usage:
        r["proj_toi"] = round(float(r.get("toi_avg") or 0.0), 3)
        r["is_starter_goalie"] = (r["position"] == "G" and r["player_id"] == starter_id)
    return usage
