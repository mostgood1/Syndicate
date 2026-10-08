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

GATING. WNBA only. `SYNDICATE_WNBA_SIM_AVAILABILITY` truthy -> on; explicitly falsy (0/false/no/off) -> off, a kill
switch that wins over everything; UNSET -> on only if `wnba_sim_availability.json` in the processed root carries
`"enabled": true` (FILE SWITCH, 2026-10-04, user "enable the availability and rate shrink fixes": the per-run
SmartSim subprocess reads the file, so turning it on needs no role restart -- cf. the 2026-10-04 08:39Z outage, which
was an env flip's restart). Unknown never means on. K from `SYNDICATE_WNBA_SIM_AVAILABILITY_MISSED_GAMES` (default 1,
bounded 1..5).
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
TEAM_ALIASES = {"GS": "GSV", "LV": "LVA", "LA": "LAS", "NY": "NYL", "CONN": "CON", "WAS": "WSH", "PHO": "PHX"}


SWITCH_FILE = "wnba_sim_availability.json"


def flag_state(env: Optional[Mapping[str, str]] = None) -> str:
    """'on' / 'off' (explicit kill switch) / 'unset'. The env var always wins over the switch file."""
    raw = str((env if env is not None else os.environ).get(FLAG) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return "on"
    if raw in {"0", "false", "no", "off"}:
        return "off"
    return "unset"


def file_enabled(processed_root: Path) -> Tuple[bool, str]:
    """True only when the switch file parses and says `"enabled": true` (the JSON boolean, nothing truthy-ish)."""
    path = Path(processed_root) / SWITCH_FILE
    if not path.is_file():
        return False, f"switch file absent: {path}"
    try:
        import json

        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"switch file unreadable: {type(exc).__name__}"
    if isinstance(doc, dict) and doc.get("enabled") is True:
        return True, "ok"
    return False, "switch file not enabled"


def flag_enabled(env: Optional[Mapping[str, str]] = None, processed_root: Optional[Path] = None) -> bool:
    state = flag_state(env)
    if state != "unset":
        return state == "on"
    return bool(processed_root is not None and file_enabled(processed_root)[0])


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
                # Fold ESPN codes into Syndicate tricodes: production writes PLAYOFF box rows as GS/LV/NY (measured
                # 2026-10-08), so without this a team's "last game" stayed its regular-season finale and the rule
                # excluded players who had played every playoff game (10-07: Fauthoux 31 min, Evans 18, Gueye 13).
                raw_team = str(r.get("TEAM_ABBREVIATION") or "").strip().upper()
                team = TEAM_ALIASES.get(raw_team, raw_team)
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


def recency_exclusions(*, processed_root: Path, date_str: str, k: int, name_key: Callable[[object], str],
                       window_dates: Optional[Dict[str, List[str]]] = None) -> Tuple[Dict[str, Set[str]], str]:
    """{team: {player keys}} for players with team history who did not play in any of the team's last k games.
    `window_dates`, when given, is filled with {team: [dates of those last k games]} (the games the player missed)."""
    by_team, seen, reason = _read_history(Path(processed_root) / HISTORY_FILE, str(date_str)[:10])
    if by_team is None:
        return {}, reason
    out: Dict[str, Set[str]] = {}
    for team, rows in by_team.items():
        if len(rows) < k:
            continue
        if window_dates is not None:
            window_dates[team] = [d for d, _p in rows[-k:]]
        recent: Set[str] = set()
        for _d, played in rows[-k:]:
            recent |= played
        for name in seen.get(team, set()):
            if name not in recent:
                key = name_key(name)
                if key:
                    out.setdefault(team, set()).add(str(key).strip().upper())
    return out, "ok"


INJURY_FILE = "injuries.csv"                     # in the raw root next to processed/ (data/raw)
OUT_STATUSES = {"OUT", "DOUBTFUL", "SUSPENDED", "INACTIVE"}
SNAPSHOT_MAX_AGE_DAYS = 3
PARTIAL_SNAPSHOT_RATIO = 0.5


def _injury_snapshots(processed_root: Path, name_key: Callable[[object], str]) -> Tuple[Optional[Dict[str, Dict[str, str]]], str]:
    """{snapshot date: {player key: STATUS}} from raw/injuries.csv, a stack of DAILY snapshots (e3f2c3c0)."""
    path = Path(processed_root).parent / "raw" / INJURY_FILE
    if not path.is_file():
        return None, f"injury feed absent: {path}"
    snaps: Dict[str, Dict[str, str]] = defaultdict(dict)
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                d = str(r.get("date") or "")[:10]
                k = str(name_key(r.get("player")) or "").strip().upper()
                if d and k:
                    snaps[d][k] = str(r.get("status") or "").strip().upper()
    except Exception as exc:  # noqa: BLE001
        return None, f"injury feed unreadable: {type(exc).__name__}"
    return dict(snaps), "ok"


def _snapshot_on_or_before(snaps: Dict[str, Dict[str, str]], date_str: str) -> Optional[str]:
    days = sorted(d for d in snaps if d <= date_str)
    if not days:
        return None
    latest = days[-1]
    if len(days) >= 2 and len(snaps[latest]) < PARTIAL_SNAPSHOT_RATIO * len(snaps[days[-2]]):
        return days[-2]                              # a partial fetch must not read as "everyone returned"
    return latest


def injury_explained_returns(excluded: Dict[str, Set[str]], window_dates: Dict[str, List[str]], *, processed_root: Path,
                             date_str: str, name_key: Callable[[object], str]) -> Tuple[Set[Tuple[str, str]], str]:
    """(team, player key) pairs the recency rule excluded whose absence the injury report EXPLAINS and who have since
    LEFT it: on every missed game the snapshot on/before that date listed them OUT/DOUBTFUL/SUSPENDED/INACTIVE, and the
    latest snapshot on/before the slate does not. Measured 2026-10-07: Dana Evans (18 min) and Stephanie Talbot (21)
    were OUT for 10-04, off the 10-06 report, and the K=1 rule still dropped them. Unknown never re-admits: no feed, no
    snapshot for a missed game, or a latest snapshot older than SNAPSHOT_MAX_AGE_DAYS keeps the exclusion."""
    snaps, reason = _injury_snapshots(processed_root, name_key)
    if not snaps:
        return set(), reason
    ds = str(date_str)[:10]
    now = _snapshot_on_or_before(snaps, ds)
    if now is None:
        return set(), "no injury snapshot on or before the slate"
    from datetime import date as _date
    if (_date.fromisoformat(ds) - _date.fromisoformat(now)).days > SNAPSHOT_MAX_AGE_DAYS:
        return set(), f"latest injury snapshot {now} is stale"
    out: Set[Tuple[str, str]] = set()
    for team, keys in excluded.items():
        missed = window_dates.get(team) or []
        if not missed:
            continue
        for key in keys:
            if snaps[now].get(key, "") in OUT_STATUSES:
                continue                              # still on the report: not returned
            explained = True
            for g in missed:
                s = _snapshot_on_or_before(snaps, g)
                if s is None or snaps[s].get(key, "") not in OUT_STATUSES:
                    explained = False
                    break
            if explained:
                out.add((team, key))
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
        state = flag_state(env)
        if state == "off":
            summary["reason"] = f"{FLAG} off"
            return summary
        if state == "unset":
            on, why = file_enabled(processed_root)
            if not on:
                summary["reason"] = f"{FLAG} unset and {why}"
                return summary
        summary["switch"] = "env" if state == "on" else "file"
        k = missed_games_k(env)
        window: Dict[str, List[str]] = {}
        add, reason = recency_exclusions(processed_root=processed_root, date_str=date_str, k=k, name_key=name_key,
                                         window_dates=window)
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
        returned, why = injury_explained_returns(add, window, processed_root=processed_root, date_str=date_str,
                                                 name_key=name_key)
        summary["readmitted_injury_return"] = sorted(f"{t}:{k_}" for t, k_ in returned)
        summary["readmit_reason"] = why
        for team, keys in add.items():
            for key in keys:
                if (team, key) in playing or (team, key) in returned:
                    continue
                bucket = excluded_map.setdefault(team, set())
                if key not in bucket:
                    bucket.add(key)
                    summary["added"] += 1
        summary.update(applied=summary["added"] > 0, k=k, reason="ok")
        print(f"[wnba_sim_availability] SIM_AVAILABILITY applied date={date_str} k={k} added={summary['added']} "
              f"readmitted_injury_return={len(returned)} ({why})", flush=True)
    except Exception as exc:  # noqa: BLE001 -- availability must never cost the sim its run
        summary["reason"] = f"failed: {type(exc).__name__}: {exc}"
        print(f"[wnba_sim_availability] SIM_AVAILABILITY_FAILED {type(exc).__name__}: {exc}", flush=True)
    return summary
