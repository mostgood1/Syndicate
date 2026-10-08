"""NFL defense vs position: what each defense allows to QBs, RBs, WRs and TEs, per game, ranked.

WHY (lane `intelligence-evidence-coverage`, phase 2; user 2026-10-08: "focus on
recency and matchups"). A player-prop matchup is "how does THIS defense handle
THIS position" -- the board's NFL matchup line only said how many points the
opponent allowed. The play-by-play and the roster already on the fleet answer
the real question:

  * `nfl_source/tracking/nflverse/pbp/pbp_<season>.csv` -- `defteam`, `play_type`,
    passer / receiver / rusher ids, yards, completions, touchdowns;
  * `nfl_source/tracking/nflverse/roster/roster_<season>.csv` -- gsis_id -> position.

Per (defense, game, position) it sums what was allowed, then averages per game
the defense played and ranks the league (rank 1 = FEWEST allowed). Regular
season only; two-point tries and kneels excluded; sacks are not targets.

Writes `nfl_source/tracking/derived/nfl_defense_vs_position_<season>_wk<NN>.json`
DATED by the last week included -- never in place.

    python scripts/build_nfl_defense_vs_position.py             # season from the newest pbp file
    python scripts/build_nfl_defense_vs_position.py --season 2026
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "nfl_defense_vs_position_v1"
POSITIONS = ("QB", "RB", "WR", "TE")
# (position, stat) pairs worth a sentence; the value is per game.
STATS = {
    "QB": ("pass_yds", "completions", "pass_td", "interceptions", "rush_yds"),
    "RB": ("rush_yds", "carries", "rush_td", "rec_yds", "receptions"),
    "WR": ("rec_yds", "receptions", "targets", "rec_td"),
    "TE": ("rec_yds", "receptions", "targets", "rec_td"),
}
_POSITION_ALIASES = {"HB": "RB", "FB": "RB"}


def nfl_root() -> Path:
    override = str(os.environ.get("SYNDICATE_NFL_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / "nfl_source"


def _f(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if out != out else out


def _flag(value: Any) -> bool:
    return _f(value) == 1.0


def load_positions(rows: Iterable[Mapping[str, str]]) -> dict[str, str]:
    """gsis_id -> position, from the roster's NEWEST week per player."""
    best: dict[str, tuple[float, str]] = {}
    for row in rows:
        gsis = str(row.get("gsis_id") or "").strip()
        pos = str(row.get("position") or "").strip().upper()
        pos = _POSITION_ALIASES.get(pos, pos)
        if not gsis or pos not in POSITIONS:
            continue
        week = _f(row.get("week"))
        if gsis not in best or week >= best[gsis][0]:
            best[gsis] = (week, pos)
    return {gsis: pos for gsis, (_week, pos) in best.items()}


def allowed_by_game(plays: Iterable[Mapping[str, str]], positions: Mapping[str, str]) -> dict[tuple[str, str], dict[str, dict[str, float]]]:
    """(defteam, game_id) -> position -> stat sums allowed in that game."""
    games: dict[tuple[str, str], dict[str, dict[str, float]]] = defaultdict(lambda: {p: defaultdict(float) for p in POSITIONS})
    for play in plays:
        if str(play.get("season_type") or "").upper() not in {"REG", ""}:
            continue
        if _flag(play.get("two_point_attempt")) or _flag(play.get("qb_kneel")):
            continue
        defteam = str(play.get("defteam") or "").strip()
        game_id = str(play.get("game_id") or "").strip()
        kind = str(play.get("play_type") or "").strip().lower()
        if not defteam or not game_id or kind not in {"pass", "run"}:
            continue
        bucket = games[(defteam, game_id)]
        td_player = str(play.get("td_player_id") or "").strip()
        if kind == "pass" and not _flag(play.get("sack")):
            passer = positions.get(str(play.get("passer_player_id") or "").strip())
            receiver_id = str(play.get("receiver_player_id") or "").strip()
            receiver = positions.get(receiver_id)
            complete = _flag(play.get("complete_pass"))
            if passer == "QB":
                q = bucket["QB"]
                q["pass_yds"] += _f(play.get("passing_yards")) if complete else 0.0
                q["completions"] += 1.0 if complete else 0.0
                q["pass_td"] += 1.0 if _flag(play.get("pass_touchdown")) else 0.0
                q["interceptions"] += 1.0 if _flag(play.get("interception")) else 0.0
            if receiver in POSITIONS and receiver != "QB":
                r = bucket[receiver]
                r["targets"] += 1.0
                if complete:
                    r["receptions"] += 1.0
                    r["rec_yds"] += _f(play.get("receiving_yards"))
                if _flag(play.get("pass_touchdown")) and td_player == receiver_id:
                    r["rec_td"] += 1.0
        elif kind == "run":
            rusher_id = str(play.get("rusher_player_id") or "").strip()
            rusher = positions.get(rusher_id)
            if rusher in POSITIONS:
                r = bucket[rusher]
                r["rush_yds"] += _f(play.get("rushing_yards"))
                r["carries"] += 1.0
                if _flag(play.get("rush_touchdown")) and td_player == rusher_id:
                    r["rush_td"] += 1.0
    return games


def per_game_ranked(games: Mapping[tuple[str, str], Mapping[str, Mapping[str, float]]]) -> dict[str, dict[str, dict[str, dict[str, float]]]]:
    """defteam -> position -> stat -> {per_game, games, rank, of} (rank 1 = fewest allowed)."""
    totals: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: {p: defaultdict(float) for p in POSITIONS})
    played: dict[str, int] = defaultdict(int)
    for (defteam, _game_id), positions in games.items():
        played[defteam] += 1
        for pos, stats in positions.items():
            for stat, value in stats.items():
                totals[defteam][pos][stat] += value
    out: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for pos, stats in STATS.items():
        for stat in stats:
            league = sorted((totals[d][pos].get(stat, 0.0) / played[d], d) for d in played if played[d])
            for index, (value, defteam) in enumerate(league):
                # ties share the best rank
                rank = 1 + sum(1 for other, _ in league if other < value)
                out.setdefault(defteam, {}).setdefault(pos, {})[stat] = {
                    "per_game": round(value, 2), "games": played[defteam], "rank": rank, "of": len(league),
                }
    return out


def through_week(plays: Iterable[Mapping[str, str]]) -> int:
    weeks = [int(_f(p.get("week"))) for p in plays if str(p.get("season_type") or "REG").upper() in {"REG", ""}]
    return max(weeks) if weeks else 0


def run(season: int | None = None) -> dict[str, Any]:
    root = nfl_root()
    pbp_dir = root / "tracking" / "nflverse" / "pbp"
    if season is None:
        found = sorted(int(m.group(1)) for p in pbp_dir.glob("pbp_*.csv") if (m := re.fullmatch(r"pbp_(\d{4})\.csv", p.name)))
        if not found:
            raise SystemExit(f"no pbp files under {pbp_dir}")
        season = found[-1]
    with (pbp_dir / f"pbp_{season}.csv").open(encoding="utf-8", newline="") as handle:
        plays = list(csv.DictReader(handle))
    with (root / "tracking" / "nflverse" / "roster" / f"roster_{season}.csv").open(encoding="utf-8", newline="") as handle:
        positions = load_positions(csv.DictReader(handle))
    week = through_week(plays)
    teams = per_game_ranked(allowed_by_game(plays, positions))
    payload = {
        "schema": SCHEMA, "season": season, "through_week": week,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "rank_meaning": "1 = fewest allowed", "source": "nflverse pbp + roster",
        "teams": teams,
    }
    out_dir = root / "tracking" / "derived"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"nfl_defense_vs_position_{season}_wk{week:02d}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    summary = {"season": season, "through_week": week, "plays": len(plays), "positions_mapped": len(positions), "defenses": len(teams), "written": str(path)}
    print("[nfl_dvp] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--season", type=int, default=None)
    args = parser.parse_args(argv)
    run(args.season)
    return 0


if __name__ == "__main__":
    sys.exit(main())
