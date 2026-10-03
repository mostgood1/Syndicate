"""Derive line combinations + starting goalie from recent-game TOI (owned port of vendor logic).

Ports ``nhl_betting/data/rosters.py`` ``infer_lines`` / ``project_toi`` (the TOI-ranking line model)
onto the NHL ``api-web`` boxscore feed. The api-web boxscore lacks per-player PP/PK TOI, so unit
assignment uses the overall-TOI ranking as a proxy (top skaters -> PP1/PP2, etc.); line slots and the
starter-goalie heuristic follow the vendor exactly.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional

from .nhl_web import NhlWebIngestClient, season_code_for_date


_GOALIE_START_MIN = 30.0  # a goalie with 30+ minutes started (or played most of) the game


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
    team_last_game = ""
    for gid in game_ids:
        box = client.boxscore(gid)
        if not box:
            continue
        game_date = str(box.get("gameDate") or "")[:10]
        pbg = box.get("playerByGameStats") or {}
        side = None
        if _abbr_of((box.get("homeTeam") or {}).get("abbrev")) == team_abbr.upper():
            side = "homeTeam"
        elif _abbr_of((box.get("awayTeam") or {}).get("abbrev")) == team_abbr.upper():
            side = "awayTeam"
        if side is None:
            continue
        team_last_game = max(team_last_game, game_date)
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
                toi = _toi_to_min(p.get("toi"))
                row["games_played"] += 1
                row["toi_total"] += toi
                if pos == "G" and toi >= _GOALIE_START_MIN:
                    row["starts"] = row.get("starts", 0) + 1
                    row["last_start_date"] = max(str(row.get("last_start_date") or ""), game_date)
    usage = []
    for row in acc.values():
        gp = max(1, row["games_played"])
        row["toi_avg"] = round(row["toi_total"] / gp, 3)
        row["team_last_game_date"] = team_last_game
        usage.append(row)
    usage.sort(key=lambda r: r["toi_avg"], reverse=True)
    return usage


def _dress_score(r: Dict) -> float:
    """Total ice time over the window: how much a player actually PLAYED, not how long he played
    the games he was in. ``toi_total`` when the usage row carries it, else ``toi_avg * games``."""
    total = r.get("toi_total")
    if total is None:
        total = float(r.get("toi_avg") or 0.0) * float(r.get("games_played") or 0)
    return float(total or 0.0)


def infer_lines(usage: List[Dict], must_dress: Optional[set] = None) -> List[Dict]:
    """Assign line_slot (L1-L4 / D1-D3), pp_unit, pk_unit (vendor TOI model, two defects fixed).

    WHO DRESSES is chosen by TOTAL ice time over the window, then the dressed 12 F / 6 D are
    ordered into lines by AVERAGE ice time. Ranking everyone by the average let a player with one
    long game outrank an every-night regular: measured 2026-10-02 (lane nhl-player-props-projection,
    `scripts/backtest_nhl_props.py`), 10% of 2025-26 regular-season skaters who PLAYED had no slot
    -- and an unslotted skater gets zero ice time in the engine (`_line_order`), so he projected
    0.001 SOG against 0.86 actual; in preseason a prospect's single split-squad game pushed Adam
    Fox off the D pairs.

    SPECIAL-TEAMS UNITS HAVE A POSITIONAL SHAPE: PP = 3 F + 2 D, PK = 2 F + 2 D, from the dressed
    players. They used to be the top 5 / top 4 skaters by overall ice time -- mostly defensemen,
    since D log the most minutes -- and `engine.py` `_fill_unit` then topped each unit up from that
    same list, so PP1 carried 2-3 D and PK1 3-4. That was the D-heavy minutes (D1 30.4 simulated vs
    22.7 real) behind the D-over / F-under bias in every skater market. The api-web boxscore has no
    per-strength ice time, so the PK forwards are the next four after the PP1 forwards, not a
    measured penalty-kill role.
    """
    forwards = [r for r in usage if r["position"] == "F"]
    defense = [r for r in usage if r["position"] == "D"]
    for r in usage:
        r["line_slot"] = None
        r["pp_unit"] = None
        r["pk_unit"] = None

    forced = {int(p) for p in (must_dress or ())}

    def _dressed(rows: List[Dict], k: int) -> List[Dict]:
        # A player a sportsbook has posted a line on is dressed FIRST `[2026-10-03, lane
        # nhl-player-props-projection]`: early in a season the window is mostly last season's final
        # games, so a regular who missed some of them (Carlson 23.7 min avg) ranked out of the top 6 D
        # by total ice time and projected nothing. A posted line is the market saying he plays.
        ranked = sorted(rows, key=lambda r: (int(r["player_id"]) in forced, _dress_score(r),
                                             float(r.get("toi_avg") or 0.0)), reverse=True)
        picked = ranked[:k]
        return sorted(picked, key=lambda r: float(r.get("toi_avg") or 0.0), reverse=True)

    dressed_f = _dressed(forwards, 12)
    dressed_d = _dressed(defense, 6)
    for idx, r in enumerate(dressed_f):
        r["line_slot"] = ("L1", "L2", "L3", "L4")[idx // 3]
    for idx, r in enumerate(dressed_d):
        r["line_slot"] = ("D1", "D2", "D3")[idx // 2]

    for unit, (fs, ds) in enumerate(((dressed_f[0:3], dressed_d[0:2]), (dressed_f[3:6], dressed_d[2:4])), start=1):
        for r in fs + ds:
            r["pp_unit"] = unit
    for unit, (fs, ds) in enumerate(((dressed_f[3:5], dressed_d[0:2]), (dressed_f[5:7], dressed_d[2:4])), start=1):
        for r in fs + ds:
            r["pk_unit"] = unit
    return usage


def _starter_goalie_id(usage: List[Dict], date: Optional[str]) -> Optional[int]:
    """Most STARTS in the window (ties -> most recent start), swapped on the 2nd of a back-to-back.

    The old rule was the highest AVERAGE goalie TOI, and a backup's one full start averages the same
    ~60 minutes as the starter's every start -- measured over 2025-26 team-games (lane
    nhl-player-props-projection, `C:/tmp/nhlprops/goalie_rules.py`): 49.0% right in the regular
    season, 76.2% in the playoffs. Most starts alone: 54.6%; plus the back-to-back swap (the
    goalie who started yesterday rarely starts today): 63.0% / 89.0%. Longer windows or recency
    weights moved it by under 1.5 points, so the plain rule ships.
    """
    goalies = [r for r in usage if r["position"] == "G"]
    if not goalies:
        return None
    ranked = sorted(
        goalies,
        key=lambda r: (int(r.get("starts") or 0), str(r.get("last_start_date") or ""), float(r.get("toi_avg") or 0.0)),
        reverse=True,
    )
    pick = ranked[0]
    if date and len(ranked) > 1:
        try:
            yesterday = (_dt.date.fromisoformat(str(date)[:10]) - _dt.timedelta(days=1)).isoformat()
        except ValueError:
            yesterday = ""
        last_game = str(pick.get("team_last_game_date") or "")
        if yesterday and last_game == yesterday and str(pick.get("last_start_date") or "") == yesterday:
            pick = ranked[1]
    return pick["player_id"]


def project_lineup(usage: List[Dict], date: Optional[str] = None) -> List[Dict]:
    """Add proj_toi (recent avg) and flag the starter goalie (see `_starter_goalie_id`)."""
    starter_id = _starter_goalie_id(usage, date)
    for r in usage:
        r["proj_toi"] = round(float(r.get("toi_avg") or 0.0), 3)
        r["is_starter_goalie"] = (r["position"] == "G" and r["player_id"] == starter_id)
    return usage
