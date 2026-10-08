"""NBA / WNBA defense vs position: what each team allows to guards, forwards and centers, per game, ranked.

WHY (lane `intelligence-evidence-coverage`, phase 2; user 2026-10-08: "start the
NBA/WNBA defense vs position producer"). The basketball prop matchup line said
how the opponent defends overall; a points / rebounds / assists prop wants "how
does THIS team handle THIS position". The box-score history on the fleet answers it:

  * NBA  `nba_source/source_artifacts/data/processed/boxscores_history.csv` -- two
    schemas in one file (nba.com live columns and the legacy upper-case ones);
    game type from the 10-digit id (002 = regular season, 004 = playoffs);
    position from the player's starts, else `rosters_<season>.csv`.
  * WNBA `wnba_source/data/processed/boxscores_history.csv` -- ESPN ids; game
    type from `schedule_<year>.csv` `season_type_slug`; position from starts.

PHASES ARE NEVER MIXED (learnings: season-phase models): one table per
(season, phase) -- `regular` and `playoffs`; preseason and exhibitions dropped.
Per (team, game, position) it sums what OPPONENTS scored, averages per game the
team played, ranks the league (rank 1 = FEWEST allowed).

Writes, beside the history it read, DATED by the newest game included:
  `<sport>_defense_vs_position_<season>_<phase>_asof_<YYYYMMDD>.json`

    python scripts/build_basketball_defense_vs_position.py --sport wnba
    python scripts/build_basketball_defense_vs_position.py --sport nba --season 2025-26
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "basketball_defense_vs_position_v1"
POSITIONS = ("G", "F", "C")
STATS = ("pts", "reb", "ast", "fg3m", "pra", "pr", "pa", "ra")
_COLS = {"pts": ("PTS", "points"), "reb": ("REB", "reboundsTotal"), "ast": ("AST", "assists"), "fg3m": ("FG3M", "threePointersMade")}
# ESPN codes production writes into WNBA playoff box rows (measured 2026-10-08)
WNBA_TEAM_ALIASES = {"GS": "GSV", "LV": "LVA", "LA": "LAS", "NY": "NYL", "CONN": "CON", "WAS": "WSH", "PHO": "PHX"}
NBA_PHASE_BY_PREFIX = {"002": "regular", "004": "playoffs"}


def source_root(sport: str) -> Path:
    override = str(os.environ.get(f"SYNDICATE_{sport.upper()}_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / f"{sport}_source"


def history_path(sport: str) -> Path:
    root = source_root(sport)
    if sport == "nba":
        return root / "source_artifacts" / "data" / "processed" / "boxscores_history.csv"
    return root / "data" / "processed" / "boxscores_history.csv"


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _pick(row: Mapping[str, str], names: Iterable[str]) -> str:
    for name in names:
        value = str(row.get(name) or "").strip()
        if value:
            return value
    return ""


def _minutes(row: Mapping[str, str]) -> float:
    raw = _pick(row, ("MIN", "minutes"))
    if ":" in raw:
        mins, _, secs = raw.partition(":")
        return (_f(mins) or 0.0) + (_f(secs) or 0.0) / 60.0
    if raw.startswith("PT"):  # ISO duration, PT36M33.00S
        body = raw[2:]
        mins, _, rest = body.partition("M")
        return (_f(mins) or 0.0) + (_f(rest.rstrip("S")) or 0.0) / 60.0
    return _f(raw) or 0.0


def _position_token(raw: str) -> str | None:
    token = str(raw or "").strip().upper().replace("PG", "G").replace("SG", "G").replace("SF", "F").replace("PF", "F")
    token = token.split("-")[0][:1]
    return token if token in POSITIONS else None


def season_of(sport: str, date: str) -> str:
    if sport == "wnba":
        return date[:4]
    year, month = int(date[:4]), int(date[5:7])
    start = year if month >= 8 else year - 1
    return f"{start}-{str(start + 1)[2:]}"


def wnba_phases(root: Path) -> dict[str, str]:
    """ESPN game id -> 'regular' / 'playoffs' from every schedule_<year>.csv."""
    out: dict[str, str] = {}
    for path in sorted((root / "data" / "processed").glob("schedule_*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                slug = str(row.get("season_type_slug") or "").strip()
                phase = {"regular-season": "regular", "post-season": "playoffs"}.get(slug)
                if phase and str(row.get("game_subtype") or "") != "ALLSTAR":
                    out[str(row.get("game_id") or "").strip()] = phase
    return out


def normalise(sport: str, rows: Iterable[Mapping[str, str]], wnba_phase: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """One record per (game, player) that played: game, date, phase, team, player, start position, stats."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        gid = _pick(row, ("game_id", "gameId"))
        date = _pick(row, ("date",))[:10]
        if not gid or not date:
            continue
        if sport == "nba":
            gid = gid.zfill(10) if gid.isdigit() and len(gid) <= 10 else gid
            phase = NBA_PHASE_BY_PREFIX.get(gid[:3])
        else:
            phase = (wnba_phase or {}).get(gid)
        if phase is None:
            continue
        team = _pick(row, ("teamTricode", "TEAM_ABBREVIATION")).upper()
        if sport == "wnba":
            team = WNBA_TEAM_ALIASES.get(team, team)
        player = _pick(row, ("personId", "PLAYER_ID"))
        if not team or not player or _minutes(row) <= 0:
            continue
        stats = {k: _f(_pick(row, cols)) or 0.0 for k, cols in _COLS.items()}
        stats["pra"] = stats["pts"] + stats["reb"] + stats["ast"]
        stats["pr"], stats["pa"], stats["ra"] = stats["pts"] + stats["reb"], stats["pts"] + stats["ast"], stats["reb"] + stats["ast"]
        out[(gid, player)] = {
            "game": gid, "date": date, "phase": phase, "season": season_of(sport, date), "team": team,
            "player": player, "name": _pick(row, ("PLAYER_NAME",)) or " ".join(
                x for x in (_pick(row, ("firstName",)), _pick(row, ("familyName",))) if x),
            "start_pos": _position_token(_pick(row, ("START_POSITION", "position"))), "stats": stats,
        }
    return list(out.values())


def positions(records: Iterable[Mapping[str, Any]], roster: Mapping[str, str] | None = None) -> dict[str, str]:
    """player -> G/F/C: the position he starts at most, else the roster's primary token."""
    starts: dict[str, Counter] = defaultdict(Counter)
    for rec in records:
        if rec.get("start_pos"):
            starts[rec["player"]][rec["start_pos"]] += 1
    out = {pid: _position_token(pos) for pid, pos in (roster or {}).items()}
    out = {pid: pos for pid, pos in out.items() if pos}
    for pid, counts in starts.items():
        out[pid] = counts.most_common(1)[0][0]
    return out


def allowed_tables(records: list[Mapping[str, Any]], pos_of: Mapping[str, str]) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
    """team -> position -> stat -> {per_game, games, rank, of}, from the opponents' box rows."""
    teams_in_game: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        teams_in_game[rec["game"]].add(rec["team"])
    allowed: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: {p: defaultdict(float) for p in POSITIONS})
    games: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        both = teams_in_game[rec["game"]]
        if len(both) != 2:
            continue
        (defense,) = both - {rec["team"]}
        games[defense].add(rec["game"])
        pos = pos_of.get(rec["player"])
        if pos is None:
            continue
        for stat, value in rec["stats"].items():
            allowed[defense][pos][stat] += value
    out: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for pos in POSITIONS:
        for stat in STATS:
            league = sorted((allowed[t][pos].get(stat, 0.0) / len(games[t]), t) for t in games if games[t])
            for value, team in league:
                rank = 1 + sum(1 for other, _ in league if other < value)  # ties share the best rank
                out.setdefault(team, {}).setdefault(pos, {})[stat] = {
                    "per_game": round(value, 2), "games": len(games[team]), "rank": rank, "of": len(league),
                }
    return out


def _nba_roster(root: Path, season: str) -> dict[str, str]:
    path = root / "data" / "processed" / f"rosters_{season}.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {str(r.get("PLAYER_ID") or "").strip(): str(r.get("POSITION") or "") for r in csv.DictReader(handle)}


def run(sport: str, season: str | None = None) -> list[dict[str, Any]]:
    root = source_root(sport)
    path = history_path(sport)
    with path.open(encoding="utf-8", newline="") as handle:
        records = normalise(sport, csv.DictReader(handle), wnba_phases(root) if sport == "wnba" else None)
    if not records:
        raise SystemExit(f"no regular-season or playoff rows in {path}")
    season = season or max(rec["season"] for rec in records)
    records = [rec for rec in records if rec["season"] == season]
    pos_of = positions(records, _nba_roster(root, season) if sport == "nba" else None)
    summaries = []
    for phase in ("regular", "playoffs"):
        chosen = [rec for rec in records if rec["phase"] == phase]
        if not chosen:
            continue
        through = max(rec["date"] for rec in chosen)
        teams = allowed_tables(chosen, pos_of)
        players = {rec["player"] for rec in chosen}
        names = {rec["name"]: pos_of[rec["player"]] for rec in chosen if rec.get("name") and rec["player"] in pos_of}
        payload = {
            "schema": SCHEMA, "sport": sport, "season": season, "phase": phase, "through": through,
            "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "rank_meaning": "1 = fewest allowed", "positions": list(POSITIONS), "stats": list(STATS),
            "players_with_position": sum(1 for p in players if p in pos_of), "players": len(players),
            "teams": teams,
            "player_positions": dict(sorted(names.items())),  # name -> G/F/C, what the board sentence reads
        }
        out = path.parent / f"{sport}_defense_vs_position_{season}_{phase}_asof_{through.replace('-', '')}.json"
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(tmp, out)
        summary = {"sport": sport, "season": season, "phase": phase, "through": through, "rows": len(chosen),
                   "teams": len(teams), "players": len(players), "with_position": payload["players_with_position"], "written": str(out)}
        print("[bb_dvp] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
        summaries.append(summary)
    return summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sport", choices=("nba", "wnba"), action="append")
    parser.add_argument("--season", default=None)
    args = parser.parse_args(argv)
    for sport in args.sport or ("nba", "wnba"):
        try:
            run(sport, args.season)
        except (SystemExit, FileNotFoundError) as exc:
            print(f"[bb_dvp] SKIPPED sport={sport} reason={exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
