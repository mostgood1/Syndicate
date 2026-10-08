"""NHL player GAME LOGS for prior seasons, in the schema of `raw/player_game_stats.csv`.

WHY (lane `intelligence-evidence-coverage`; user 2026-10-08: "we need robust history - so ensure we have
years of data, not just days - esp for player historic performance"). The prop evidence reads
`nhl_source/source_artifacts/data/raw/player_game_stats.csv`, which on the fleet spans 2026-05-01 onward
(last spring's playoffs + this season). "Last 10" in October and "vs this team" need prior seasons.

For every player in that file, per season, the NHL web API game log (regular season 2 and playoffs 3):
    https://api-web.nhle.com/v1/player/<id>/game-log/<YYYYYYYY>/<2|3>
written as `raw/player_game_log_<YYYYYYYY>.csv` with the SAME columns the reader already parses
(gamePk, date, team, player_id, player, primary_position, role, shots, goals, assists, blocked, timeOnIce,
saves, shotsAgainst, decision) plus `opponent` and `game_type`. `date` is the game day at 16:00Z (noon
Eastern): the API gives a day, not a time, and the reader converts to the Eastern date.
Uses the repo's NHL fetcher (the API refuses a bare client). INCREMENTAL: a (player, season) already in
its file is not re-fetched.

    python scripts/build_nhl_player_game_logs.py                          # the three seasons before this one
    python scripts/build_nhl_player_game_logs.py --seasons 20242025
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BASE = "https://api-web.nhle.com/v1"
FIELDS = ("gamePk", "date", "team", "player_id", "player", "primary_position", "role", "shots", "goals", "assists",
          "blocked", "timeOnIce", "saves", "shotsAgainst", "decision", "opponent", "game_type")
FetchJson = Callable[[str], Any]


def raw_dir() -> Path:
    override = str(os.environ.get("SYNDICATE_NHL_SOURCE_ROOT") or "").strip()
    root = Path(override) if override else Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / "nhl_source"
    return root / "source_artifacts" / "data" / "raw"


def _name(raw: Any) -> str:
    text = str(raw or "")
    if text.startswith("{"):
        try:
            return str(ast.literal_eval(text).get("default") or "")
        except (ValueError, SyntaxError):
            return text
    return text


def current_players(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    """player_id -> {name, role, position} from the current game-stats file."""
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        pid = str(r.get("player_id") or "").strip()
        if pid:
            out[pid] = {"name": _name(r.get("player")), "role": str(r.get("role") or ""),
                        "position": str(r.get("primary_position") or "")}
    return out


def game_rows(player_id: str, meta: dict[str, str], game_type: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    goalie = meta.get("role") == "goalie"
    for g in (payload or {}).get("gameLog") or []:
        day = str(g.get("gameDate") or "")[:10]
        if not day:
            continue
        row = {"gamePk": g.get("gameId"), "date": f"{day}T16:00:00Z", "team": g.get("teamAbbrev"),
               "player_id": player_id, "player": str({"default": meta.get("name") or ""}),
               "primary_position": meta.get("position") or "", "role": meta.get("role") or "",
               "timeOnIce": g.get("toi") or "", "opponent": g.get("opponentAbbrev") or "", "game_type": game_type,
               "decision": g.get("decision") or ""}
        if goalie:
            shots_against = g.get("shotsAgainst")
            goals_against = g.get("goalsAgainst")
            row.update(shotsAgainst=shots_against,
                       saves=(shots_against - goals_against) if shots_against is not None and goals_against is not None else "")
        else:
            row.update(shots=g.get("shots", 0), goals=g.get("goals", 0), assists=g.get("assists", 0), blocked="")
        out.append(row)
    return out


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def run(season: str, *, fetch: FetchJson | None = None, pause: float = 0.1) -> dict[str, Any]:
    if fetch is None:
        from syndicate.features.nhl.boxscore_log import fetch_json as fetch
    directory = raw_dir()
    players = current_players(_read(directory / "player_game_stats.csv"))
    path = directory / f"player_game_log_{season}.csv"
    rows: list[dict[str, Any]] = list(_read(path))
    have = {r["player_id"] for r in rows}
    summary: dict[str, Any] = {"season": season, "players": len(players), "kept": len(have), "fetched": 0, "failed": 0}
    for pid, meta in sorted(players.items()):
        if pid in have:
            continue
        try:
            for game_type in (2, 3):
                rows.extend(game_rows(pid, meta, game_type, fetch(f"{BASE}/player/{pid}/game-log/{season}/{game_type}") or {}))
            summary["fetched"] += 1
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            print(f"[nhl_logs] FETCH_FAILED season={season} player={pid} {type(exc).__name__}", flush=True)
        time.sleep(pause)
    rows.sort(key=lambda r: (str(r["date"]), str(r["gamePk"]), str(r["player_id"])))
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})
    os.replace(tmp, path)
    summary["rows"] = len(rows)
    print("[nhl_logs] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seasons", default=None, help="comma list like 20242025; default: the three before this one")
    args = parser.parse_args(argv)
    today = dt.date.today()
    start = today.year if today.month >= 9 else today.year - 1
    seasons = args.seasons.split(",") if args.seasons else [f"{y}{y + 1}" for y in range(start - 3, start)]
    for season in seasons:
        try:
            run(season)
        except Exception as exc:  # noqa: BLE001
            print(f"[nhl_logs] SEASON_FAILED season={season} {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
