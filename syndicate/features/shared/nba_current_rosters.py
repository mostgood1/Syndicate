"""NBA CURRENT team rosters from ESPN, written as ``rosters_<season>.csv`` (lane ``nba-current-rosters``).

WHY. Measured 2026-10-20 (NBA opening night) on the fleet: the SmartSim simulated PHI @ NYK with last season's PHI --
Paul George, Kelly Oubre Jr., Kyle Lowry, Quentin Grimes -- and none of LeBron James, Jaylen Brown, Anfernee Simons,
Kentavious Caldwell-Pope, who are on ESPN's 2026-27 PHI roster and played. Two inputs carried 2025-26 membership:

  * ``basketball_props_features.build_features_for_date_local`` tags each player with the team of his LAST
    ``player_logs.csv`` row (2026-04-12), and the slate filter keeps a player only when that team is playing.
  * ``rosters_2025-26.csv`` (stats.nba, written 2026-09-30) is the roster file every reader falls back to:
    ``pick_rosters_file`` takes the newest ``rosters_*.csv`` when the season's own file is absent, and nothing on the
    fleet writes a 2026-27 roster (the native source CLI has no fetch-rosters). The sim's roster filter, the injury
    scraper's team correction and the live tick all read it.

WHAT. ``refresh_current_rosters`` fetches ESPN's 30 team rosters (``site.api.espn.com .../teams/{id}/roster``; the
fleet reaches it, stats.nba ``commonteamroster`` timed out from it on 2026-10-20) and writes ``rosters_<season>.csv``
under the data root's NBA processed dir, the season label taken from ESPN's own ``season.displayName``. The columns
are the stats.nba ``commonteamroster`` columns the readers use, so every ``rosters_*.csv`` reader picks it up
unchanged, plus ``ESPN_ID`` / ``ESPN_NAME`` / ``ROSTER_SOURCE`` / ``FETCHED_AT``. ``PLAYER_ID`` is the stats.nba id,
resolved by name from ``player_logs.csv`` and older roster files (the live tick joins on it), and ``PLAYER`` is then
the stats.nba spelling of the name: the sim's roster filter compares names with ``_norm_name_key``, which keeps
periods, so ESPN's "AJ Green" would not match a props row's "A.J. Green". A player with no stats.nba history (a
rookie before his first game) keeps ESPN's name and a blank ``PLAYER_ID``.

COMPLETE OR NOTHING. A partial file is worse than none: once ``rosters_<season>.csv`` exists, ``pick_rosters_file``
no longer considers the old season's file, so a missing team would lose its roster entirely. The file is written only
when every one of the 30 teams has >= ``MIN_TEAM_PLAYERS`` players; a team whose fetch fails keeps its rows from the
existing ESPN-sourced file of the same season, and if that still leaves a team short nothing is written. Atomic write.

``current_roster_index`` is the reader the props features use to re-key a player's team. It returns ``None`` unless an
ESPN-sourced roster for the slate's season exists, covers all 30 teams, and was fetched no later than one day after
the slate date: a roster fetched in October must never re-key an as-of replay of a March date (future knowledge).

Throttled (default every 90 min, env ``SYNDICATE_NBA_CURRENT_ROSTERS_MAX_AGE_MINUTES``). Kill switch
``SYNDICATE_NBA_CURRENT_ROSTERS=0`` (absent = ON) turns off both the refresh and the re-key. Never raises; returns
what it did and prints one ``NBA_CURRENT_ROSTERS`` line.
"""
from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

FLAG = "SYNDICATE_NBA_CURRENT_ROSTERS"
MAX_AGE_ENV = "SYNDICATE_NBA_CURRENT_ROSTERS_MAX_AGE_MINUTES"
DEFAULT_MAX_AGE_MINUTES = 90.0
SOURCE = "espn"
N_TEAMS = 30
MIN_TEAM_PLAYERS = 8
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

# ESPN abbreviation -> the tricode every Syndicate NBA artifact uses (same map as
# basketball_props_smart_sim._espn_to_tri_local, kept here so this module stays import-light).
ESPN_TO_TRI = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "UTAH": "UTA", "WSH": "WAS", "SA": "SAS", "PHO": "PHX"}

# stats.nba team ids (fixed), so TeamID / TEAM_ID match the stats.nba roster files' columns.
STATS_TEAM_ID = {
    "ATL": 1610612737, "BOS": 1610612738, "CLE": 1610612739, "NOP": 1610612740, "CHI": 1610612741,
    "DAL": 1610612742, "DEN": 1610612743, "GSW": 1610612744, "HOU": 1610612745, "LAC": 1610612746,
    "LAL": 1610612747, "MIA": 1610612748, "MIL": 1610612749, "MIN": 1610612750, "BKN": 1610612751,
    "NYK": 1610612752, "ORL": 1610612753, "IND": 1610612754, "PHI": 1610612755, "PHX": 1610612756,
    "POR": 1610612757, "SAC": 1610612758, "SAS": 1610612759, "OKC": 1610612760, "TOR": 1610612761,
    "UTA": 1610612762, "MEM": 1610612763, "WAS": 1610612764, "DET": 1610612765, "CHA": 1610612766,
}

# stats.nba commonteamroster column order first (readers select by name; any positional reader still sees the same
# leading columns), then this producer's own columns.
COLUMNS = [
    "TeamID", "SEASON", "LeagueID", "PLAYER", "NICKNAME", "PLAYER_SLUG", "NUM", "POSITION", "HEIGHT", "WEIGHT",
    "BIRTH_DATE", "AGE", "EXP", "SCHOOL", "PLAYER_ID", "HOW_ACQUIRED", "TEAM_ID", "TEAM_ABBREVIATION", "TEAM_NAME",
    "ESPN_ID", "ESPN_NAME", "ESPN_STATUS", "ROSTER_SOURCE", "FETCHED_AT",
]

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(FLAG) or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def name_key(value: object) -> str:
    """Accent-, punctuation- and suffix-insensitive player key: 'Nikola Vučević' == 'Nikola Vucevic',
    'Kelly Oubre Jr.' == 'Kelly Oubre', 'Kentavious Caldwell-Pope' == 'Kentavious Caldwell Pope'."""
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    if "(" in text:
        text = text.split("(", 1)[0]
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[-_/]", " ", text)
    text = re.sub(r"[^a-z0-9 ]", "", text)
    tokens = [t for t in text.split() if t and t not in _SUFFIXES]
    return " ".join(tokens)


def season_for_date(date_str: str) -> str:
    """'2026-10-20' -> '2026-27' (the label the roster readers compute: start year = year if month >= 7)."""
    y, m = int(str(date_str)[:4]), int(str(date_str)[5:7])
    start = y if m >= 7 else y - 1
    return f"{start}-{str(start + 1)[-2:]}"


def roster_path(processed_root: Path, season: str) -> Path:
    return Path(processed_root) / f"rosters_{season}.csv"


def _http_get_json(url: str, timeout: float = 20.0) -> Dict[str, Any]:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Syndicate nba_current_rosters)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 -- fixed ESPN host
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def espn_teams(http_get: Callable[[str], Dict[str, Any]]) -> List[Tuple[str, str]]:
    """[(espn_team_id, tricode)] for the league's teams."""
    payload = http_get(f"{ESPN_BASE}/teams")
    out: List[Tuple[str, str]] = []
    for league in ((payload.get("sports") or [{}])[0].get("leagues") or []):
        for item in league.get("teams") or []:
            team = item.get("team") or {}
            abbr = str(team.get("abbreviation") or "").strip().upper()
            tid = str(team.get("id") or "").strip()
            if abbr and tid:
                out.append((tid, ESPN_TO_TRI.get(abbr, abbr)))
    return out


def _athlete_rows(payload: Mapping[str, Any], tri: str, *, season_label: str, fetched_at: str,
                  stats_ids: Mapping[str, Tuple[str, str]]) -> List[Dict[str, Any]]:
    team_name = str(((payload.get("team") or {}).get("displayName")) or "")
    athletes = payload.get("athletes") or []
    # The roster endpoint answers either a flat athlete list or position groups ({"items": [...]}).
    flat: List[Mapping[str, Any]] = []
    for item in athletes:
        if isinstance(item, Mapping) and isinstance(item.get("items"), list):
            flat.extend(x for x in item["items"] if isinstance(x, Mapping))
        elif isinstance(item, Mapping):
            flat.append(item)
    rows: List[Dict[str, Any]] = []
    for a in flat:
        name = str(a.get("displayName") or a.get("fullName") or "").strip()
        if not name:
            continue
        status = str(((a.get("status") or {}).get("type")) or "").strip().lower()
        stats_id, stats_name = stats_ids.get(name_key(name), ("", ""))
        exp = (a.get("experience") or {}).get("years") if isinstance(a.get("experience"), Mapping) else None
        rows.append({
            "TeamID": STATS_TEAM_ID.get(tri, ""),
            "SEASON": season_label,
            "LeagueID": "00",
            "PLAYER": stats_name or name,
            "NICKNAME": str(a.get("firstName") or ""),
            "PLAYER_SLUG": str(a.get("slug") or ""),
            "NUM": str(a.get("jersey") or ""),
            "POSITION": str(((a.get("position") or {}).get("abbreviation")) or ""),
            "HEIGHT": str(a.get("displayHeight") or ""),
            "WEIGHT": str(a.get("displayWeight") or ""),
            "BIRTH_DATE": str(a.get("dateOfBirth") or "")[:10],
            "AGE": a.get("age") if a.get("age") is not None else "",
            "EXP": "R" if exp == 0 else (exp if exp is not None else ""),
            "SCHOOL": str(((a.get("college") or {}).get("name")) or "") if isinstance(a.get("college"), Mapping) else "",
            "PLAYER_ID": stats_id,
            "HOW_ACQUIRED": "",
            "TEAM_ID": STATS_TEAM_ID.get(tri, ""),
            "TEAM_ABBREVIATION": tri,
            "TEAM_NAME": team_name,
            "ESPN_ID": str(a.get("id") or ""),
            "ESPN_NAME": name,
            "ESPN_STATUS": status,
            "ROSTER_SOURCE": SOURCE,
            "FETCHED_AT": fetched_at,
        })
    return rows


def stats_id_index(processed_root: Path) -> Dict[str, Tuple[str, str]]:
    """{name_key: (stats.nba PLAYER_ID, stats.nba name)} from player_logs.csv and every rosters_*.csv not written by
    this producer (player_logs read first, so its spelling wins). Ambiguous keys (two ids for one key) are dropped
    rather than guessed."""
    seen: Dict[str, set] = {}
    names: Dict[str, str] = {}
    root = Path(processed_root)
    sources: List[Tuple[Path, str, str]] = [(root / "player_logs.csv", "PLAYER_NAME", "PLAYER_ID")]
    sources += [(p, "PLAYER", "PLAYER_ID") for p in sorted(root.glob("rosters_*.csv"))]
    for path, name_col, id_col in sources:
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace", newline="") as fh:
                reader = csv.DictReader(fh)
                if not reader.fieldnames or name_col not in reader.fieldnames or id_col not in reader.fieldnames:
                    continue
                if "ROSTER_SOURCE" in reader.fieldnames:
                    continue  # our own output: its ids came from here in the first place
                for r in reader:
                    k = name_key(r.get(name_col))
                    pid = str(r.get(id_col) or "").strip()
                    if pid.endswith(".0"):
                        pid = pid[:-2]
                    if k and pid and pid.isdigit():
                        seen.setdefault(k, set()).add(pid)
                        names.setdefault(k, str(r.get(name_col) or "").strip())
        except Exception:  # noqa: BLE001
            continue
    return {k: (next(iter(v)), names[k]) for k, v in seen.items() if len(v) == 1}


def _read_rows(path: Path) -> List[Dict[str, str]]:
    try:
        with Path(path).open(encoding="utf-8", errors="replace", newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:  # noqa: BLE001
        return []


def _fetched_at(rows: Iterable[Mapping[str, str]]) -> Optional[datetime]:
    best: Optional[datetime] = None
    for r in rows:
        try:
            ts = datetime.fromisoformat(str(r.get("FETCHED_AT") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        best = ts if best is None or ts > best else best
    return best


def _write_atomic(path: Path, rows: List[Dict[str, Any]]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def refresh_current_rosters(processed_root: Path, date_str: str, *, max_age_minutes: Optional[float] = None,
                            http_get: Optional[Callable[[str], Dict[str, Any]]] = None, now: Optional[datetime] = None,
                            force: bool = False, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Fetch ESPN's current rosters and (re)write ``rosters_<season>.csv``. Returns what it did; never raises."""
    env = env if env is not None else os.environ
    processed_root = Path(processed_root)
    now = now or datetime.now(timezone.utc)
    out: Dict[str, Any] = {"date": str(date_str)[:10], "wrote": False}
    try:
        if not enabled(env):
            out["skipped"] = f"{FLAG} off"
            return out
        season = season_for_date(date_str)
        out["season"] = season
        path = roster_path(processed_root, season)
        existing = [r for r in _read_rows(path) if str(r.get("ROSTER_SOURCE") or "") == SOURCE] if path.is_file() else []
        if max_age_minutes is None:
            try:
                max_age_minutes = float(env.get(MAX_AGE_ENV) or DEFAULT_MAX_AGE_MINUTES)
            except ValueError:
                max_age_minutes = DEFAULT_MAX_AGE_MINUTES
        last = _fetched_at(existing)
        if not force and last is not None and (now - last).total_seconds() < float(max_age_minutes) * 60.0:
            out["skipped"] = f"fetched {int((now - last).total_seconds() // 60)} min ago"
            return out
        get = http_get or _http_get_json
        teams = espn_teams(get)
        out["teams_listed"] = len(teams)
        if len(teams) != N_TEAMS:
            out["reason"] = f"ESPN listed {len(teams)} teams, expected {N_TEAMS}"
            return out
        fetched_at = now.isoformat()
        ids = stats_id_index(processed_root)
        rows: List[Dict[str, Any]] = []
        failed: List[str] = []
        carried: List[str] = []
        for espn_id, tri in teams:
            try:
                payload = get(f"{ESPN_BASE}/teams/{espn_id}/roster")
                label = str(((payload.get("season") or {}).get("displayName")) or "").strip()
                if label and label != season:
                    out["reason"] = f"ESPN serves season {label}, slate season is {season}: not written"
                    return out
                team_rows = _athlete_rows(payload, tri, season_label=season, fetched_at=fetched_at, stats_ids=ids)
            except Exception as exc:  # noqa: BLE001
                team_rows = []
                out.setdefault("errors", {})[tri] = f"{type(exc).__name__}: {str(exc)[:80]}"
            if len(team_rows) < MIN_TEAM_PLAYERS:
                prior = [dict(r) for r in existing if str(r.get("TEAM_ABBREVIATION") or "").upper() == tri]
                if len(prior) >= MIN_TEAM_PLAYERS:
                    rows.extend(prior)
                    carried.append(tri)
                    continue
                failed.append(tri)
                continue
            rows.extend(team_rows)
        out.update(players=len(rows), carried_over=sorted(carried), failed=sorted(failed),
                   stats_id_matched=sum(1 for r in rows if str(r.get("PLAYER_ID") or "").strip()))
        if failed:
            out["reason"] = f"incomplete: {len(failed)} team(s) short of {MIN_TEAM_PLAYERS} players; nothing written"
            return out
        _write_atomic(path, rows)
        out.update(wrote=True, path=str(path), fetched_at=fetched_at)
        return out
    except Exception as exc:  # noqa: BLE001 -- the props refresh must survive this
        out["reason"] = f"failed: {type(exc).__name__}: {str(exc)[:160]}"
        return out
    finally:
        print("[nba_current_rosters] NBA_CURRENT_ROSTERS " + json.dumps(out, default=str), flush=True)


@dataclass
class RosterIndex:
    """Who is on which team NOW, keyed both ways the props features can look a player up."""
    season: str
    fetched_at: datetime
    team_by_key: Dict[str, str] = field(default_factory=dict)
    team_by_stats_id: Dict[str, str] = field(default_factory=dict)
    teams: Dict[str, List[str]] = field(default_factory=dict)

    def team_for(self, *, player_id: object = None, player_name: object = None) -> Optional[str]:
        pid = str(player_id or "").strip()
        if pid.endswith(".0"):
            pid = pid[:-2]
        if pid and pid in self.team_by_stats_id:
            return self.team_by_stats_id[pid]
        return self.team_by_key.get(name_key(player_name))


def current_roster_index(processed_root: Path, date_str: str, *, env: Optional[Mapping[str, str]] = None) -> Optional[RosterIndex]:
    """The ESPN current roster valid for ``date_str``, or None (switch off, no file, incomplete, or the roster was
    fetched more than a day after the slate -- a replay of a past date must not see later moves)."""
    try:
        if not enabled(env):
            return None
        season = season_for_date(date_str)
        rows = [r for r in _read_rows(roster_path(processed_root, season)) if str(r.get("ROSTER_SOURCE") or "") == SOURCE]
        if not rows:
            return None
        fetched = _fetched_at(rows)
        if fetched is None:
            return None
        slate = date.fromisoformat(str(date_str)[:10])
        if fetched.date() > slate + timedelta(days=1):
            return None
        idx = RosterIndex(season=season, fetched_at=fetched)
        ambiguous: set = set()
        for r in rows:
            tri = str(r.get("TEAM_ABBREVIATION") or "").strip().upper()
            k = name_key(r.get("PLAYER"))
            if not tri or not k:
                continue
            idx.teams.setdefault(tri, []).append(str(r.get("PLAYER") or ""))
            if k in idx.team_by_key and idx.team_by_key[k] != tri:
                ambiguous.add(k)
            idx.team_by_key[k] = tri
            pid = str(r.get("PLAYER_ID") or "").strip()
            if pid.endswith(".0"):
                pid = pid[:-2]
            if pid:
                idx.team_by_stats_id[pid] = tri
        for k in ambiguous:  # two current players share a key on different teams: never guess between them
            idx.team_by_key.pop(k, None)
        if len(idx.teams) != N_TEAMS or any(len(v) < MIN_TEAM_PLAYERS for v in idx.teams.values()):
            return None
        return idx
    except Exception:  # noqa: BLE001
        return None
