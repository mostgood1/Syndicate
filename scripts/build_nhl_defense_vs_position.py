"""NHL defense vs position: what each team allows to opposing FORWARDS and DEFENSEMEN per game, ranked.

WHY (lane `intelligence-evidence-coverage`; user 2026-10-08: player props must weigh "opposing team
performance vs the players position, average stats allowed to players position"). NFL, NBA and WNBA got
defense-vs-position tables the same day; NHL props had only team-level xG against.

Reads this season's REGULAR-season gamecenter box scores already cached by the in-season builders
(`nhl_source/data/ingestion_cache/boxscore_<gameId>.json`, gameType 2) -- no fetching. Per (defending team,
game) it sums the opponents' forwards' and defensemen's SOG, goals, assists and points, averages per game the
team played, ranks the league (rank 1 = FEWEST allowed). Also records every skater's position (F/D) by name
for the board sentence.

Writes `nhl_source/data/processed/nhl_defense_vs_position_<season>_asof_<YYYYMMDD>.json`, dated by the
newest game included. A display table: no sim loader reads it.

    python scripts/build_nhl_defense_vs_position.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "nhl_defense_vs_position_v1"
GROUPS = {"forwards": "F", "defense": "D"}
STATS = ("sog", "goals", "assists", "points")


def nhl_root() -> Path:
    override = str(os.environ.get("SYNDICATE_NHL_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / "nhl_source"


def season_code(day: dt.date) -> str:
    start = day.year if day.month >= 9 else day.year - 1
    return f"{start}{start + 1}"


def allowed_by_game(boxes: Iterable[Mapping[str, Any]]) -> tuple[dict, dict, str]:
    """((team, game) -> pos -> stat sums allowed, name -> F/D, newest date) from regular-season box scores."""
    games: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    positions: dict[str, str] = {}
    newest = ""
    for box in boxes:
        if int(box.get("gameType") or 0) != 2:
            continue
        gid = str(box.get("id") or "")
        teams = {side: str((box.get(side) or {}).get("abbrev") or "") for side in ("homeTeam", "awayTeam")}
        stats = box.get("playerByGameStats") or {}
        if not gid or not all(teams.values()) or not stats:
            continue
        newest = max(newest, str(box.get("gameDate") or ""))
        for side, other in (("homeTeam", "awayTeam"), ("awayTeam", "homeTeam")):
            defense = teams[other]  # the team that faced these skaters
            bucket = games.setdefault((defense, gid), {p: defaultdict(float) for p in GROUPS.values()})
            for group, pos in GROUPS.items():
                for player in (stats.get(side) or {}).get(group) or []:
                    name = str((player.get("name") or {}).get("default") or "")
                    if name:
                        positions[name] = pos
                    for stat in STATS:
                        bucket[pos][stat] += float(player.get(stat) or 0)
    return games, positions, newest


def per_game_ranked(games: Mapping[tuple[str, str], Mapping[str, Mapping[str, float]]]) -> dict:
    totals: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: {p: defaultdict(float) for p in GROUPS.values()})
    played: dict[str, int] = defaultdict(int)
    for (team, _gid), by_pos in games.items():
        played[team] += 1
        for pos, stats in by_pos.items():
            for stat, value in stats.items():
                totals[team][pos][stat] += value
    out: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for pos in GROUPS.values():
        for stat in STATS:
            league = sorted((totals[t][pos].get(stat, 0.0) / played[t], t) for t in played if played[t])
            for value, team in league:
                rank = 1 + sum(1 for other, _ in league if other < value)  # ties share the best rank
                out.setdefault(team, {}).setdefault(pos, {})[stat] = {
                    "per_game": round(value, 3), "games": played[team], "rank": rank, "of": len(league)}
    return out


def run(today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.date.today()
    season = season_code(today)
    root = nhl_root()
    cache = root / "data" / "ingestion_cache"
    prefix = f"boxscore_{season[:4]}02"

    def boxes():
        for path in sorted(cache.glob(f"{prefix}*.json")):
            try:
                yield json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue

    games, positions, newest = allowed_by_game(boxes())
    summary: dict[str, Any] = {"season": season, "games": len({g for _, g in games}), "teams": 0}
    if games:
        teams = per_game_ranked(games)
        summary["teams"] = len(teams)
        payload = {
            "schema": SCHEMA, "season": f"{season[:4]}-{season[4:]}", "through": newest,
            "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "rank_meaning": "1 = fewest allowed", "positions": {"F": "forwards", "D": "defensemen"},
            "teams": teams, "player_positions": dict(sorted(positions.items())),
        }
        out = root / "data" / "processed" / f"nhl_defense_vs_position_{payload['season']}_asof_{newest.replace('-', '')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(tmp, out)
        summary["written"] = str(out)
    print("[nhl_dvp] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n")[0]).parse_args(argv)
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
