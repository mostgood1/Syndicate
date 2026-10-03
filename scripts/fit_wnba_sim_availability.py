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

COMPARE MODE (`--compare <variant archive>`): the engine re-run WITH the rule against the baseline archive on the
same held-out dates, PAIRED by (game, player, market): played-player minutes bias/MAE, prop mean MAE vs actual, ladder
Brier at the book line (the board's reader), each as a paired game-clustered CI; plus the coverage cost -- player-games
the baseline projected that the variant does not, split by whether the player actually played.

Usage (WSL): python scripts/fit_wnba_sim_availability.py --archive ~/wnba_bt/archive --espn-dir ... --box-dir ...
             python scripts/fit_wnba_sim_availability.py --archive ~/wnba_bt/archive --compare ~/wnba_bt/avail_on \
                 --odds-dir ... --espn-dir ... --box-dir ... --out ...
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
    ap.add_argument("--compare", default="", help="variant archive (engine re-run WITH the rule) to score vs --archive")
    ap.add_argument("--odds-dir", default="", help="required with --compare (book lines for the ladder Brier)")
    ap.add_argument("--n-boot", type=int, default=2000)
    args = ap.parse_args(argv)
    if args.compare:
        return compare(args)
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


def _sim_minutes(archive: Path, games: Dict, split: str) -> Dict:
    idx = B._pair_index(games)
    out: Dict = {}
    for f in sorted(archive.glob("*/smart_sim_*.json")):
        if f.parent.name < split:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        gid = B.match_game(idx, str(d.get("date")), str(d.get("home")).upper(), str(d.get("away")).upper())
        if not gid:
            continue
        for side in ("home", "away"):
            for pl in (d.get("players") or {}).get(side) or []:
                out[(gid, B.norm_name(pl.get("player_name")))] = float(pl.get("min_mean") or 0)
    return out


def compare(args) -> int:
    _boot = B.boot_ci
    B.boot_ci = lambda rows, n_boot=args.n_boot, seed=7: _boot(rows, n_boot, seed)  # noqa: E731
    games = B.load_games(Path(args.espn_dir))
    box, _ = B.load_box(Path(args.box_dir), games)
    hist = B.History(games, box)
    book, _ = B.load_book(Path(args.odds_dir), games)
    base_p = Path(args.archive)
    var_p = Path(args.compare)
    sims = lambda a: sorted(p for p in a.glob("*/smart_sim_*.json") if p.parent.name >= args.split)  # noqa: E731
    _gb, pb, _ = B.load_sim_json_games(sims(base_p), games)
    _gv, pv, _ = B.load_sim_json_games(sims(var_p), games)
    mb, mv = _sim_minutes(base_p, games, args.split), _sim_minutes(var_p, games, args.split)
    report: Dict = {"split": args.split, "phases": {}}
    for phase, pf in (("test_regular", lambda g: g["phase"] == "regular"), ("test_playoff", lambda g: g["phase"] == "playoff")):
        gids = sorted(g for g in set(pb) & set(pv) if pf(games[g]))
        ent: Dict = {"games": len(gids)}
        # minutes, played players present in both
        mrows = [(g, k) for (g, k) in mb if g in gids and (g, k) in mv and k in box.get(g, {})]
        if mrows:
            act = {(g, k): box[g][k]["MIN"] for g, k in mrows}
            ent["minutes"] = {
                "n": len(mrows),
                "bias_base": round(statistics.fmean(mb[r] - act[r] for r in mrows), 3),
                "bias_variant": round(statistics.fmean(mv[r] - act[r] for r in mrows), 3),
                "mae_base": round(statistics.fmean(abs(mb[r] - act[r]) for r in mrows), 3),
                "mae_variant": round(statistics.fmean(abs(mv[r] - act[r]) for r in mrows), 3),
                "d_mae_variant_minus_base": B.boot_ci([(r[0], abs(mv[r] - act[r]) - abs(mb[r] - act[r])) for r in mrows])}
        # coverage cost: baseline projected, variant did not
        lost_played = sum(1 for g in gids for k in pb[g] if k not in pv[g] and k in box.get(g, {}))
        lost_absent = sum(1 for g in gids for k in pb[g] if k not in pv[g] and k not in box.get(g, {}))
        ent["coverage"] = {"baseline_player_games": sum(len(pb[g]) for g in gids),
                           "variant_player_games": sum(len(pv[g]) for g in gids),
                           "dropped_who_played": lost_played, "dropped_who_did_not_play": lost_absent}
        mk_out = {}
        for mk, (expr, _c) in B.PROP_MARKETS.items():
            pts, bri = [], []
            for g in gids:
                for k, mk_b in pb[g].items():
                    eb, ev = mk_b.get(mk), (pv[g].get(k) or {}).get(mk)
                    a = box.get(g, {}).get(k)
                    if not eb or not ev or not a:
                        continue
                    y = sum(a[x] for x in expr)
                    pts.append((g, abs(ev["mean"] - y) - abs(eb["mean"] - y), ev["mean"] - y, eb["mean"] - y))
                    bk = (book.get(g) or {}).get("props", {}).get((k, mk))
                    if bk and y != bk["line"] and eb.get("over") and ev.get("over"):
                        yy = int(y > bk["line"])
                        bri.append((g, (B.clip(ev["over"](bk["line"])) - yy) ** 2 - (B.clip(eb["over"](bk["line"])) - yy) ** 2,
                                    (B.clip(ev["over"](bk["line"])) - yy) ** 2, (B.clip(bk["p"]) - yy) ** 2))
            if not pts:
                continue
            mk_out[mk] = {"n": len(pts), "bias_base": round(statistics.fmean(r[3] for r in pts), 3),
                          "bias_variant": round(statistics.fmean(r[2] for r in pts), 3),
                          "d_mae_variant_minus_base": B.boot_ci([(r[0], r[1]) for r in pts])}
            if bri:
                mk_out[mk]["book_n"] = len(bri)
                mk_out[mk]["d_brier_variant_minus_base"] = B.boot_ci([(r[0], r[1]) for r in bri])
                mk_out[mk]["brier_variant"] = round(statistics.fmean(r[2] for r in bri), 5)
                mk_out[mk]["brier_book"] = round(statistics.fmean(r[3] for r in bri), 5)
        ent["props"] = mk_out
        report["phases"][phase] = ent
        print(phase, json.dumps({k: v for k, v in ent.items() if k != "props"}), flush=True)
        for mk, v in mk_out.items():
            print(f"   {mk:32s} {json.dumps(v)}", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "availability_compare.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
