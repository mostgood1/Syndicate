"""Which WNBA players will NOT play? An as-of availability rule for the SmartSim player pool (lane `wnba-sim-availability`).

WHY. On the as-of re-run of today's engine (662 team-games, lane `wnba-lines-props-backtest`), the sim gave **42.6 of
every 200 team minutes to players who did not play**: 29.05 to players absent from the box score (inactive/injured,
2.28 per team-game) and 13.55 to players listed DNP. Players who played got 157.4, which is the -2.96 min/player bias
and the starters' shortfall. There is no pregame injury feed for most of 2026, so the sim kept simulating players
whose last appearance was weeks ago.

WHAT THIS MEASURES (offline, before any engine change). For every player the sim put in a game's pool, as-of
features from the TEAM's earlier box scores only:
  * missed_last_k -- did not appear (MIN > 0) in any of the team's last k games (k = 1, 2, 3),
  * team_games_since_last_appearance,
and the outcome: played (MIN > 0) in this game. Each candidate rule "drop if missed_last_k" is scored on
  * non-player sim minutes REMOVED (good) vs real-player sim minutes WRONGLY removed (bad), per team-game,
  * real players wrongly dropped (count) and the ACTUAL minutes they went on to play,
train (regular season before --split) and test (on/after, and playoffs) separately. The rule's EFFECT on the
remaining players' minutes needs the engine's own re-allocation (bench-first, `_derive_sim_minutes_local`), so that
is measured by an engine re-run afterwards, not guessed here.

Usage (WSL): python scripts/fit_wnba_sim_availability.py --archive ~/wnba_bt/archive --espn-dir ... --box-dir ...
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bt_wnba", REPO / "scripts" / "backtest_wnba_lines_props.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)  # type: ignore[union-attr]


def load_box_all(box_dir: Path, games: Dict[str, Dict]) -> Dict[str, Dict[str, Dict]]:
    """{gid: {team: {player_key: minutes}}} INCLUDING DNP rows (MIN 0) -- absence from this map = not dressed."""
    out: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for p in sorted(box_dir.glob("boxscores_2026-*.csv")):
        with p.open(encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                gid = str(r.get("game_id") or r.get("gameId") or "")
                if gid not in games:
                    continue
                team = B.SYND_ALIASES.get(str(r.get("TEAM_ABBREVIATION")).upper(), str(r.get("TEAM_ABBREVIATION")).upper())
                try:
                    out[gid][team][B.norm_name(r.get("PLAYER_NAME"))] = float(r.get("MIN") or 0)
                except ValueError:
                    out[gid][team][B.norm_name(r.get("PLAYER_NAME"))] = 0.0
    return out


class TeamHistory:
    def __init__(self, games: Dict[str, Dict], box_all: Dict) -> None:
        self.by_team: Dict[str, List[tuple]] = defaultdict(list)
        for g in sorted(games.values(), key=lambda x: x["tip"]):
            if g["id"] not in box_all:
                continue
            for team in (g["home"], g["away"]):
                played = {k for k, m in box_all[g["id"]].get(team, {}).items() if m > 0}
                self.by_team[team].append((g["tip"], played))

    def features(self, team: str, player: str, tip: str) -> Dict:
        prior = [p for t, p in self.by_team.get(team, []) if t < tip]
        f: Dict = {"team_games_prior": len(prior)}
        for k in (1, 2, 3):
            last = prior[-k:]
            f[f"missed_last_{k}"] = bool(last) and len(last) == k and all(player not in s for s in last)
        since = None
        for i, s in enumerate(reversed(prior)):
            if player in s:
                since = i
                break
        f["since_last"] = since if since is not None else len(prior)
        f["ever_played_for_team"] = any(player in s for s in prior)
        return f


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--split", default="2026-08-01")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    games = B.load_games(Path(args.espn_dir))
    box_all = load_box_all(Path(args.box_dir), games)
    th = TeamHistory(games, box_all)
    idx = B._pair_index(games)
    rows = []
    for f in sorted(Path(args.archive).glob("*/smart_sim_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        gid = B.match_game(idx, str(d.get("date")), str(d.get("home")).upper(), str(d.get("away")).upper())
        if not gid or gid not in box_all:
            continue
        g = games[gid]
        for side, team in (("home", g["home"]), ("away", g["away"])):
            for pl in (d.get("players") or {}).get(side) or []:
                k = B.norm_name(pl.get("player_name"))
                act = box_all[gid].get(team, {}).get(k)
                rows.append({"gid": gid, "team": team, "date": g["date"], "phase": g["phase"],
                             "sim_min": float(pl.get("min_mean") or 0), "act_min": act or 0.0,
                             "played": bool(act and act > 0), "dressed": act is not None,
                             **th.features(team, k, g["tip"])})
    rules = {"missed_last_1": lambda r: r["missed_last_1"], "missed_last_2": lambda r: r["missed_last_2"],
             "missed_last_3": lambda r: r["missed_last_3"],
             "never_played_for_team": lambda r: (not r["ever_played_for_team"]) and r["team_games_prior"] >= 3}
    report: Dict = {"split": args.split, "rows": len(rows), "periods": {}}
    periods = {"train": lambda r: r["phase"] == "regular" and r["date"] < args.split,
               "test_regular": lambda r: r["phase"] == "regular" and r["date"] >= args.split,
               "test_playoff": lambda r: r["phase"] == "playoff"}
    for pname, pf in periods.items():
        R = [r for r in rows if pf(r)]
        tg = len({(r["gid"], r["team"]) for r in R}) or 1
        base = {"team_games": tg,
                "sim_min_to_nonplayers_per_team_game": round(sum(r["sim_min"] for r in R if not r["played"]) / tg, 2),
                "sim_min_to_absent_per_team_game": round(sum(r["sim_min"] for r in R if not r["dressed"]) / tg, 2),
                "played_player_min_bias": round(statistics.fmean(r["sim_min"] - r["act_min"] for r in R if r["played"]), 3)
                if any(r["played"] for r in R) else None}
        res = {}
        for rname, rule in rules.items():
            drop = [r for r in R if rule(r)]
            res[rname] = {
                "dropped_rows": len(drop),
                "nonplayer_sim_min_removed_per_team_game": round(sum(r["sim_min"] for r in drop if not r["played"]) / tg, 2),
                "real_player_sim_min_removed_per_team_game": round(sum(r["sim_min"] for r in drop if r["played"]) / tg, 2),
                "real_players_wrongly_dropped": sum(1 for r in drop if r["played"]),
                "their_actual_minutes_mean": round(statistics.fmean(r["act_min"] for r in drop if r["played"]), 2)
                if any(r["played"] for r in drop) else None,
                "precision_nonplayer": round(sum(1 for r in drop if not r["played"]) / len(drop), 4) if drop else None,
                "recall_of_nonplayer_minutes": round(sum(r["sim_min"] for r in drop if not r["played"]) /
                                                     max(1e-9, sum(r["sim_min"] for r in R if not r["played"])), 4)}
        report["periods"][pname] = {"baseline": base, "rules": res}
        print(pname, json.dumps(base))
        for rname, v in res.items():
            print(f"   {rname:24s} {json.dumps(v)}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "availability_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
