"""Keep players who will not play out of the WNBA SmartSim pool (lane `wnba-sim-availability`).

THE DEFECT. Measured 2026-10-03 on an as-of re-run of the engine over the 2026 WNBA season (662 team-games): the sim
gave **42.6 of every 200 team minutes to players who did not play** -- 29.05 to players absent from the box score
(inactive/injured, 2.28 per team-game) and 13.55 to players listed DNP. Players who did play got 157.4, which is the
-2.96 min/player bias and the starters' shortfall that dragged every prop mean low. For most of the season there was
no pregame injury feed, so nothing told the sim a player had been out for weeks.

THE RULE, chosen on May-July and tested on Aug-Sep + playoffs (`scripts/fit_wnba_sim_availability.py`): drop a player
from a team's pool when they did not appear (MIN > 0) in any of that team's last K games, K = 1 by default. Held out
(230 team-games): removes 38.9 of 47.3 non-player minutes per team-game, at a cost of 6.1 real-player minutes
(79 players returning after a single missed game, ~3.6% of player-games, who then get no projection).

WHAT IT DOES NOT OVERRIDE. A player the props source marks `playing_today` is never excluded here -- a positive
availability signal beats a recency guess. Injury / league-status exclusions are untouched; this only ADDS keys.

INPUT. `boxscores_history.csv` in the WNBA processed root (production writes it daily; the as-of re-run truncates it
to games before the slate). Only games strictly before the slate date are read. A missing or unreadable history adds
nothing and says why (`SIM_AVAILABILITY skipped reason=...`). Never raises.

GATING. WNBA only. OFF unless `SYNDICATE_WNBA_SIM_AVAILABILITY` is truthy; K from
`SYNDICATE_WNBA_SIM_AVAILABILITY_MISSED_GAMES` (default 1, bounded 1..5).
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

FLAG = "SYNDICATE_WNBA_SIM_AVAILABILITY"
K_ENV = "SYNDICATE_WNBA_SIM_AVAILABILITY_MISSED_GAMES"
HISTORY_FILE = "boxscores_history.csv"


def flag_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = (env if env is not None else os.environ).get(FLAG)
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def missed_games_k(env: Optional[Mapping[str, str]] = None) -> int:
    try:
        k = int(str((env if env is not None else os.environ).get(K_ENV) or "1").strip())
    except ValueError:
        k = 1
    return max(1, min(5, k))


def _read_history(path: Path, date_str: str) -> Tuple[Optional[Dict[str, List[Tuple[str, Set[str]]]]], Dict[str, Set[str]], str]:
    """({team: [(game_key, players_who_played)] in date order}, {team: every name seen}, reason)."""
    if not path.is_file():
        return None, {}, f"history absent: {path}"
    games: Dict[Tuple[str, str], Dict[str, Any]] = {}
    seen: Dict[str, Set[str]] = defaultdict(set)
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                d = str(r.get("date") or r.get("GAME_DATE") or "")[:10]
                if not d or d >= date_str:
                    continue
                team = str(r.get("TEAM_ABBREVIATION") or "").strip().upper()
                gid = str(r.get("game_id") or r.get("GAME_ID") or r.get("gameId") or d)
                name = str(r.get("PLAYER_NAME") or "")
                if not team or not name:
                    continue
                g = games.setdefault((team, gid), {"date": d, "played": set()})
                seen[team].add(name)
                try:
                    if float(r.get("MIN") or 0) > 0:
                        g["played"].add(name)
                except ValueError:
                    pass
    except Exception as exc:  # noqa: BLE001
        return None, {}, f"history unreadable: {type(exc).__name__}"
    by_team: Dict[str, List[Tuple[str, Set[str]]]] = defaultdict(list)
    for (team, gid), g in sorted(games.items(), key=lambda kv: (kv[1]["date"], kv[0][1])):
        by_team[team].append((g["date"], g["played"]))
    return dict(by_team), dict(seen), "ok"


def recency_exclusions(*, processed_root: Path, date_str: str, k: int,
                       name_key: Callable[[object], str]) -> Tuple[Dict[str, Set[str]], str]:
    """{team: {player keys}} for players with team history who did not play in any of the team's last k games."""
    by_team, seen, reason = _read_history(Path(processed_root) / HISTORY_FILE, str(date_str)[:10])
    if by_team is None:
        return {}, reason
    out: Dict[str, Set[str]] = {}
    for team, rows in by_team.items():
        if len(rows) < k:
            continue
        recent: Set[str] = set()
        for _d, played in rows[-k:]:
            recent |= played
        for name in seen.get(team, set()):
            if name not in recent:
                key = name_key(name)
                if key:
                    out.setdefault(team, set()).add(str(key).strip().upper())
    return out, "ok"


def add_recency_exclusions(excluded_map: Dict[str, Set[str]], *, processed_root: Path, date_str: str, league_code: str,
                           props_df: Any, name_key: Callable[[object], str],
                           env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Merge recency exclusions into the sim's existing excluded map, in place. Returns what it did."""
    summary: Dict[str, Any] = {"applied": False, "added": 0}
    try:
        if str(league_code or "").strip().lower() != "wnba":
            summary["reason"] = "not wnba"
            return summary
        if not flag_enabled(env):
            summary["reason"] = f"{FLAG} off"
            return summary
        k = missed_games_k(env)
        add, reason = recency_exclusions(processed_root=processed_root, date_str=date_str, k=k, name_key=name_key)
        if not add:
            summary["reason"] = reason if reason != "ok" else "nobody to exclude"
            print(f"[wnba_sim_availability] SIM_AVAILABILITY skipped reason={summary['reason']}", flush=True)
            return summary
        playing: Set[Tuple[str, str]] = set()
        try:
            if props_df is not None and "playing_today" in getattr(props_df, "columns", []):
                for _, row in props_df.iterrows():
                    if str(row.get("playing_today")).strip().lower() in {"1", "true", "yes", "y"}:
                        playing.add((str(row.get("team") or "").strip().upper(), str(name_key(row.get("player_name")) or "").upper()))
        except Exception:  # noqa: BLE001
            playing = set()
        for team, keys in add.items():
            for key in keys:
                if (team, key) in playing:
                    continue
                bucket = excluded_map.setdefault(team, set())
                if key not in bucket:
                    bucket.add(key)
                    summary["added"] += 1
        summary.update(applied=summary["added"] > 0, k=k, reason="ok")
        print(f"[wnba_sim_availability] SIM_AVAILABILITY applied date={date_str} k={k} added={summary['added']}", flush=True)
    except Exception as exc:  # noqa: BLE001 -- availability must never cost the sim its run
        summary["reason"] = f"failed: {type(exc).__name__}: {exc}"
        print(f"[wnba_sim_availability] SIM_AVAILABILITY_FAILED {type(exc).__name__}: {exc}", flush=True)
    return summary
