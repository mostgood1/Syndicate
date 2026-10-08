"""NBA / WNBA player GAME log across seasons, with the opponent -- from ESPN scoreboards + game summaries.

WHY (lane `intelligence-evidence-coverage`; user 2026-10-08: "build the NBA/WNBA player history vs team
source"). A basketball prop's "history vs this team" needs the player's games against that opponent over
more than one season, and the fleet's box history cannot give it: WNBA `boxscores_history.csv` starts
2026-04-25 (one season), and NBA's 2025-26 rows cover 37-42 of 82 games per team (November missing).

Writes `<sport>_source/data/processed/player_game_log_<season>.csv`, one row per player per game PLAYED
(an ESPN `didNotPlay` row or 0 minutes is not a game), with the columns the prop-evidence box reader
already reads (`game_id, date, TEAM_ABBREVIATION, PLAYER_ID, PLAYER_NAME, MIN, PTS, REB, AST, FG3M, STL,
BLK, TOV`) plus `season, season_type, opponent, home_away, starter, position, source`. Team codes are
Syndicate's tricodes (ESPN's GS/NY/SA/... folded), so `opponent` joins to the board.

`season` is the START year (NBA 2025 = 2025-26; WNBA 2026 = 2026). `date` is the ESPN scoreboard day
asked for (the local schedule date, as in the box history). Regular season and playoffs only, labelled --
never mixed by a reader that cares (learnings: season-phase models).

INCREMENTAL: game ids already in the file are kept and never re-fetched; scoreboards are re-read from three
days before the newest game in the file (`--full`: every day, to pick up a game a failed fetch missed --
fetches are retried 3x with backoff first). Atomic rewrite.

    python scripts/build_basketball_player_game_log.py                       # both sports, this + last 2 seasons
    python scripts/build_basketball_player_game_log.py --sport wnba --seasons 2024,2025,2026
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

REPO = Path(__file__).resolve().parents[1]
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball"
FIELDS = ("game_id", "date", "season", "season_type", "TEAM_ABBREVIATION", "opponent", "home_away", "PLAYER_ID",
          "PLAYER_NAME", "position", "starter", "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV", "source")
SEASON_TYPES = {2: "regular", 3: "playoffs"}
# ESPN abbreviation -> Syndicate tricode
ALIASES = {
    "wnba": {"GS": "GSV", "LV": "LVA", "LA": "LAS", "NY": "NYL", "CONN": "CON", "WAS": "WSH", "PHO": "PHX"},
    "nba": {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX"},
}
# (first month, first day, last month, last day) of the window that can hold regular season + playoffs
WINDOW = {"nba": ((10, 1), (6, 30)), "wnba": ((5, 1), (10, 31))}
FetchJson = Callable[[str], Any]


def source_root(sport: str) -> Path:
    override = str(os.environ.get(f"SYNDICATE_{sport.upper()}_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / f"{sport}_source"


def _fetch(url: str, attempts: int = 3) -> Any:
    """GET JSON, retried with backoff: a transient URLError must not drop a game (the incremental
    rescan only looks back three days, so a game lost here stays lost until a --full run)."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read())
        except Exception:  # noqa: BLE001
            if attempt == attempts - 1:
                raise
            time.sleep(5.0 * (attempt + 1))


def season_days(sport: str, season: int, today: dt.date) -> list[dt.date]:
    (m0, d0), (m1, d1) = WINDOW[sport]
    start = dt.date(season, m0, d0)
    end = dt.date(season + (1 if m1 < m0 else 0), m1, d1)
    end = min(end, today - dt.timedelta(days=1))
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)] if end >= start else []


def _minutes(raw: str) -> float:
    raw = str(raw or "").strip()
    if ":" in raw:
        m, _, s = raw.partition(":")
        return float(m or 0) + float(s or 0) / 60.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _made(raw: str) -> float:
    """'3-7' -> 3."""
    try:
        return float(str(raw).split("-")[0])
    except ValueError:
        return 0.0


def game_rows(sport: str, season: int, day: dt.date, event: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Played player lines of one final game."""
    alias = ALIASES[sport]
    code = lambda abbr: alias.get(str(abbr or "").upper(), str(abbr or "").upper())
    comp = (event.get("competitions") or [{}])[0]
    sides = {code((c.get("team") or {}).get("abbreviation")): c.get("homeAway") for c in comp.get("competitors") or []}
    season_type = SEASON_TYPES.get(int((event.get("season") or {}).get("type") or 0))
    if season_type is None or len(sides) != 2:
        return []
    out = []
    for block in (summary.get("boxscore") or {}).get("players") or []:
        team = code((block.get("team") or {}).get("abbreviation"))
        opponent = next((t for t in sides if t != team), "")
        for stat_block in block.get("statistics") or []:
            names = [str(n).upper() for n in (stat_block.get("names") or stat_block.get("labels") or [])]
            for athlete in stat_block.get("athletes") or []:
                stats = athlete.get("stats") or []
                if athlete.get("didNotPlay") or not stats or len(stats) != len(names):
                    continue
                cell = dict(zip(names, stats))
                minutes = _minutes(cell.get("MIN"))
                if minutes <= 0:
                    continue
                person = athlete.get("athlete") or {}
                num = lambda key: float(cell.get(key) or 0) if str(cell.get(key) or "").replace(".", "", 1).lstrip("-").isdigit() else 0.0
                out.append({
                    "game_id": str(event.get("id") or ""), "date": day.isoformat(), "season": season,
                    "season_type": season_type, "TEAM_ABBREVIATION": team, "opponent": opponent,
                    "home_away": sides.get(team) or "", "PLAYER_ID": str(person.get("id") or ""),
                    "PLAYER_NAME": person.get("displayName") or "", "position": (person.get("position") or {}).get("abbreviation") or "",
                    "starter": int(bool(athlete.get("starter"))), "MIN": round(minutes, 1),
                    "PTS": num("PTS"), "REB": num("REB"), "AST": num("AST"), "FG3M": _made(cell.get("3PT", "0-0")),
                    "STL": num("STL"), "BLK": num("BLK"), "TOV": num("TO"), "source": "espn",
                })
    return out


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (str(r["date"]), str(r["game_id"]), str(r["TEAM_ABBREVIATION"]), str(r["PLAYER_NAME"]))):
            writer.writerow({k: row.get(k, "") for k in FIELDS})
    os.replace(tmp, path)


def run(sport: str, season: int, *, today: dt.date | None = None, fetch: FetchJson = _fetch, pause: float = 0.2,
        full: bool = False) -> dict[str, Any]:
    today = today or dt.date.today()
    league = sport  # ESPN path segment: nba / wnba
    path = source_root(sport) / "data" / "processed" / f"player_game_log_{season}.csv"
    rows: list[dict[str, Any]] = list(_read(path))
    have = {r["game_id"] for r in rows}
    newest = max((r["date"] for r in rows), default="")
    days = season_days(sport, season, today)
    if newest and not full:
        floor = (dt.date.fromisoformat(newest) - dt.timedelta(days=3))
        days = [d for d in days if d >= floor]
    summary = {"sport": sport, "season": season, "days_scanned": len(days), "kept_games": len(have),
               "new_games": 0, "failed": 0}
    for day in days:
        try:
            board = fetch(f"{BASE}/{league}/scoreboard?dates={day:%Y%m%d}")
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            print(f"[bb_log] SCOREBOARD_FAILED {sport} {day} {type(exc).__name__}", flush=True)
            continue
        for event in board.get("events") or []:
            gid = str(event.get("id") or "")
            state = (((event.get("status") or {}).get("type") or {}).get("state") or "").lower()
            if not gid or gid in have or state != "post":
                continue
            if int((event.get("season") or {}).get("type") or 0) not in SEASON_TYPES:
                continue
            try:
                got = game_rows(sport, season, day, event, fetch(f"{BASE}/{league}/summary?event={gid}"))
            except Exception as exc:  # noqa: BLE001
                summary["failed"] += 1
                print(f"[bb_log] SUMMARY_FAILED {sport} {gid} {type(exc).__name__}", flush=True)
                continue
            if got:
                rows.extend(got)
                have.add(gid)
                summary["new_games"] += 1
            time.sleep(pause)
    if summary["new_games"] or not path.is_file():
        _write(path, rows)
    summary.update(rows=len(rows), games=len({r["game_id"] for r in rows}))
    print("[bb_log] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sport", choices=("nba", "wnba"), action="append")
    parser.add_argument("--seasons", default=None, help="comma list of START years; default: this season and the two before")
    parser.add_argument("--full", action="store_true", help="rescan every day of the season (picks up games a failed fetch missed)")
    args = parser.parse_args(argv)
    today = dt.date.today()
    for sport in args.sport or ("wnba", "nba"):
        current = today.year if sport == "wnba" or today.month >= 8 else today.year - 1
        seasons = [int(s) for s in args.seasons.split(",")] if args.seasons else [current - 2, current - 1, current]
        for season in seasons:
            try:
                run(sport, season, today=today, full=args.full)
            except Exception as exc:  # noqa: BLE001 -- one season's outage must not stop the rest
                print(f"[bb_log] SEASON_FAILED {sport} {season} {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
