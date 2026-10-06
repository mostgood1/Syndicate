"""NBA SmartSim availability: leave out players who missed the team's last 2 games (lane `nba-prop-calibration`).

MEASURED (findings_2026-10-02_nba_lines_props_backtest.md, "NBA availability (K=2), engine re-run"): on a paired
as-of re-run of today's engine, 42 dates / 334 games:
  * played-player minutes MAE 7.39 -> 5.47 (-1.92 [-2.08, -1.76]);
  * sim minutes handed to non-players 67.4 -> 38.0 per team-game;
  * Brier at the de-vigged book line better in 6 of 7 markets, none worse.
  * Cost: 539 player-games of players who DID play dropped (7.7%).
A posted pre-tip prop line re-admits 125 of those (3,104 of 7,302 lost minutes) and only 8 of 2,501 non-players. It
missed its pre-registered 70% recovery bar; the user adopted it anyway, labelled post-hoc (2026-10-06).

RULE.
  * NBA, REGULAR-season slates only (nba_season_phase). Preseason rest is the norm, and the K rule was not measured
    on play-in or postseason. Unknown phase: not applied.
  * History: this season's regular-season rows of player_logs.csv (stats.nba Regular Season) strictly before the
    slate. Never last season: early in the season "the last 2 games" must not reach back to April.
  * A player who appeared for the team this season (MIN > 0) but in none of its last K games is ADDED to the sim's
    excluded map. A team with fewer than K games this season is skipped.
  * RE-ADMIT: a player with any posted pre-tip player-prop line in oddsapi_player_props_<date>.csv is not added.
  * Only ADDS keys. It never removes an injury or league-status exclusion and never overrides playing_today.

SWITCH: on when nba_sim_availability.json carries "enabled": true (optional "k", 1..5, default 2; optional
"readmit_with_prop_line", default true). Env SYNDICATE_NBA_SIM_AVAILABILITY=0 is a kill switch, =1 forces on. A missing
file means off. Never raises; prints a summary line.
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Set, Tuple

FILE = "nba_sim_availability.json"
FLAG = "SYNDICATE_NBA_SIM_AVAILABILITY"
HISTORY = "player_logs.csv"


def _config(processed_root: Path, env: Mapping[str, str]) -> Tuple[Optional[Dict[str, Any]], str]:
    raw = str(env.get(FLAG) or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return None, f"{FLAG} off"
    doc: Dict[str, Any] = {}
    path = Path(processed_root) / FILE
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            return None, f"{FILE} unreadable: {type(exc).__name__}"
    if raw not in {"1", "true", "yes", "on"} and doc.get("enabled") is not True:
        return None, f"{FILE} absent or not enabled"
    try:
        k = int(doc.get("k", 2))
    except (TypeError, ValueError):
        return None, f"{FILE} k is not an integer"
    if not 1 <= k <= 5:
        return None, f"{FILE} k={k} outside 1..5"
    return {"k": k, "readmit": doc.get("readmit_with_prop_line", True) is not False}, "ok"


def _team_history(path: Path, lo: str, hi: str) -> Tuple[Dict[str, list], Dict[str, Set[str]]]:
    """({team: [(date, {names who played})] in date order}, {team: names who played for it this season})."""
    games: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    gdate: Dict[Tuple[str, str], str] = {}
    seen: Dict[str, Set[str]] = defaultdict(set)
    with path.open(encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            d = str(r.get("GAME_DATE") or r.get("date") or "")[:10]
            if not d or d < lo or d >= hi:
                continue
            gid = str(r.get("GAME_ID") or "")
            if gid and not gid.zfill(10).startswith("002"):
                continue                       # regular-season games only, even if a mixed file appears
            try:
                if float(r.get("MIN") or 0) <= 0:
                    continue
            except ValueError:
                continue
            team = str(r.get("TEAM_ABBREVIATION") or "").strip().upper()
            name = str(r.get("PLAYER_NAME") or "")
            if not team or not name:
                continue
            games[(team, gid or d)].add(name)
            gdate[(team, gid or d)] = d
            seen[team].add(name)
    by_team: Dict[str, list] = defaultdict(list)
    for key in sorted(games, key=lambda k: (gdate[k], k[1])):
        by_team[key[0]].append((gdate[key], games[key]))
    return by_team, seen


def _priced_names(processed_root: Path, date_str: str) -> Set[str]:
    """Names with any posted player-prop line in the date's pre-tip snapshot (empty if absent)."""
    out: Set[str] = set()
    path = Path(processed_root) / f"oddsapi_player_props_{date_str}.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("market") or "").startswith("player_") and str(r.get("player_name") or "").strip():
                out.add(str(r["player_name"]))
    return out


def add_nba_recency_exclusions(excluded_map: Dict[str, Set[str]], *, processed_root: Path, date_str: str,
                               league_code: str, name_key: Callable[[object], str],
                               env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Merge the K-missed-games exclusions into the sim's excluded map, in place. Returns what it did."""
    summary: Dict[str, Any] = {"applied": False, "added": 0, "readmitted_with_prop_line": 0}
    try:
        if str(league_code or "").strip().lower() != "nba":
            summary["reason"] = "not nba"
            return summary
        cfg, why = _config(Path(processed_root), env if env is not None else os.environ)
        if cfg is None:
            summary["reason"] = why
            return summary
        d = str(date_str)[:10]
        from syndicate.features.shared.nba_season_phase import phase_for_date, phase_start

        phase = phase_for_date(d, processed_root=processed_root)
        if phase != "regular":
            summary["reason"] = f"slate phase {phase or 'unknown'}: rule measured on the regular season only"
            return summary
        lo = phase_start(d, "regular", processed_root=processed_root)
        path = Path(processed_root) / HISTORY
        if not lo or not path.is_file():
            summary["reason"] = "regular-season start unknown" if not lo else f"history absent: {path}"
            return summary
        by_team, seen = _team_history(path, lo, d)
        priced = {str(name_key(n) or "").strip().upper() for n in _priced_names(Path(processed_root), d)} if cfg["readmit"] else set()
        k = cfg["k"]
        for team, rows in by_team.items():
            if len(rows) < k:
                continue
            recent: Set[str] = set()
            for _d, played in rows[-k:]:
                recent |= played
            for name in seen.get(team, set()) - recent:
                key = str(name_key(name) or "").strip().upper()
                if not key:
                    continue
                if key in priced:
                    summary["readmitted_with_prop_line"] += 1
                    continue
                bucket = excluded_map.setdefault(team, set())
                if key not in bucket:
                    bucket.add(key)
                    summary["added"] += 1
        summary.update(applied=True, k=k, teams=len(by_team), history_from=lo)
        return summary
    except Exception as exc:  # noqa: BLE001 -- the sim must survive this
        summary["reason"] = f"failed: {type(exc).__name__}"
        return summary
    finally:
        print("[nba_sim_availability] NBA_SIM_AVAILABILITY " + json.dumps(summary, default=str), flush=True)
