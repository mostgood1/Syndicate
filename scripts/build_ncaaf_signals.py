"""Build dated, as-of NCAAF matchup-signal tables (lane `signal-engine-football`).

For every (season, week W): per player with an appearance earlier that season, carry and reception shares (season,
last 3, base, trend); per team, offensive plays per game (rush attempts + pass attempts). Weeks < W only. One table
per week: `<data root>/ncaaf_source/signals/<season>/wkNN.jsonl` (player rows, plus `kind: "team"` rows).

SOURCE  CFBD player box rows -- `ncaaf_player_game_history.csv` (2023-24) and `ncaaf_player_game_stats_snapshot.csv`
        (2025-26) under `ncaaf_source/source_artifacts/data/processed/player_game_stats/`. The box has no targets, so
        reception share stands in for target share. "Team" rows (team rushes, kneels) count toward team totals and are
        never a player.

    python3 scripts/build_ncaaf_signals.py --data-root ~/syndicate-prod/data --seasons 2024,2025
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.matchup_signals import norm_player, write_signal_table  # noqa: E402
from syndicate.features.shared.matchup_signals_football import share_features, week_key  # noqa: E402

BOX_FILES = ("ncaaf_player_game_history.csv", "ncaaf_player_game_stats_snapshot.csv")
STATS = ("rushing_attempts", "receptions", "passing_attempts", "rushing_yards", "receiving_yards", "passing_yards",
         "passing_tds")


def _f(v: Any) -> float:
    try:
        return float(v) if v not in (None, "", "NA") else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_box(root: Path, seasons: set[int]) -> list[dict[str, Any]]:
    """Deduplicated box rows (season, game_id, player_id) for `seasons`; later files win."""
    base = root / "ncaaf_source" / "source_artifacts" / "data" / "processed" / "player_game_stats"
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for name in BOX_FILES:
        path = base / name
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    season, week = int(r.get("season") or 0), int(float(r.get("week") or 0))
                except (TypeError, ValueError):
                    continue
                if season not in seasons or not week or not r.get("game_id"):
                    continue
                rows[(str(season), str(r["game_id"]), str(r.get("player_id")))] = {
                    "season": season, "week": week, "game_id": str(r["game_id"]), "player_id": str(r.get("player_id")),
                    "player": r.get("player_name") or "", "key": norm_player(r.get("player_name")),
                    "team": r.get("team") or "", "opponent": r.get("opponent") or "",
                    "is_team_row": (r.get("player_name") or "").strip().lower() == "team",
                    **{s: _f(r.get(s)) for s in STATS}}
    return list(rows.values())


def team_games(box: Iterable[Mapping[str, Any]]) -> dict[tuple[int, str, str], dict[str, Any]]:
    """(season, game_id, team) -> {week, opponent, carries, receptions, pass_att, plays}."""
    out: dict[tuple[int, str, str], dict[str, Any]] = {}
    for r in box:
        t = out.setdefault((r["season"], r["game_id"], r["team"]),
                           {"week": r["week"], "opponent": r["opponent"], "carries": 0.0, "receptions": 0.0, "pass_att": 0.0})
        t["carries"] += r["rushing_attempts"]
        t["receptions"] += r["receptions"]
        t["pass_att"] += r["passing_attempts"]
    for t in out.values():
        t["plays"] = t["carries"] + t["pass_att"]
    return out


def build_week(box: list[Mapping[str, Any]], teams: Mapping[tuple[int, str, str], Mapping[str, Any]], season: int,
               week: int) -> list[dict[str, Any]]:
    by_player: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for r in box:
        if r["season"] == season and r["week"] < week and not r["is_team_row"]:
            by_player[(r["player_id"], r["team"])].append(r)
    rows: list[dict[str, Any]] = []
    for (pid, team), games in by_player.items():
        games.sort(key=lambda g: (g["week"], g["game_id"]))
        tg = [teams[(season, g["game_id"], team)] for g in games]
        feats: dict[str, Any] = {"kind": "player", "player_id": pid, "player": games[-1]["player"],
                                 "player_key": games[-1]["key"], "team": team, "week": week, "games_prior": len(games)}
        feats.update(share_features([(g["rushing_attempts"], t["carries"]) for g, t in zip(games, tg)], "carry"))
        feats.update(share_features([(g["receptions"], t["receptions"]) for g, t in zip(games, tg)], "rec"))
        rows.append(feats)
    per_team: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for (s, _game, team), t in teams.items():
        if s == season and t["week"] < week:
            per_team[team].append(t)
    for team, games in per_team.items():
        rows.append({"kind": "team", "team": team, "week": week, "games_prior": len(games),
                     "plays_pg": round(sum(g["plays"] for g in games) / len(games), 2)})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--seasons", required=True)
    ap.add_argument("--max-week", type=int, default=16)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    seasons = {int(s) for s in args.seasons.split(",") if s.strip()}
    box = load_box(root, seasons)
    teams = team_games(box)
    for season in sorted(seasons):
        season_games = {k: v for k, v in teams.items() if k[0] == season}
        double = defaultdict(int)
        for (_s, _g, team), t in season_games.items():
            double[(team, t["week"])] += 1
        written = 0
        for week in range(2, args.max_week + 1):
            rows = build_week(box, teams, season, week)
            write_signal_table(root, "ncaaf", str(season), week_key(week), rows)
            written += len(rows)
        print(f"NCAAF_SIGNALS season={season} box_rows={sum(1 for r in box if r['season'] == season)} "
              f"team_games={len(season_games)} teams_with_two_games_in_a_week={sum(1 for v in double.values() if v > 1)} "
              f"rows={written}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
