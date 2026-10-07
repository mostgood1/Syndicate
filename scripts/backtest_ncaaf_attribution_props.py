"""NCAAF Phase B (lane `football-sim-player-attribution`): sim-attributed NCAAF props vs the book.

Pre-registered ("NCAAF Phase B/C") in `.syndicate/findings_2026-10-07_football_player_attribution.md`.

  engine   production's NCAAF `build_projection` (promoted profile, scenario switches OFF), the as-of
           SP+/PPA tasks of `football_scenario_rates.ncaaf_tasks` (FBS-vs-FBS, weeks 3-15), 300 seeds
  tables   `ncaaf_attribution_tables_2024.json` (CFBD 2024 through the ACCEPTED parser)
  usage    parsed plays: current season before the week + prior season scaled to 4 games;
           availability = previous game's touches + every player quoted for this game (A1)
  rows     OddsAPI historical quotes (private root), two-sided only, de-vigged per book
  actuals  parsed per-player-game totals (NCAAF rule: a sack is a QB rush)

Phase B (2024) grades against the BOOK only -- production's NCAAF yardage props are built from player
box scores, which exist for 2025 only. The held-out 2025 read (Phase C) adds production and is refused
here until that comparison is implemented.

    py -3 scripts/backtest_ncaaf_attribution_props.py --season 2024 --workers 3
    py -3 scripts/backtest_ncaaf_attribution_props.py --season 2024 --limit-games 6      # smoke
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import football_scenario_rates as F  # noqa: E402
from scripts import ncaaf_attribution_usage as U  # noqa: E402

QUOTES = Path(r"C:\tmp\football_scenarios\ncaaf_props")
PARSED = Path(r"C:\tmp\football_scenarios\ncaaf_attribution")
OUT = Path(r"C:\tmp\football_scenarios\attribution")
TABLES = OUT / "ncaaf_attribution_tables_2024.json"
SEEDS = 300
MARKET_KEY = {"Passing Yards": "pass_yds", "Passing TDs": "pass_td", "Rushing Yards": "rush_yds",
              "Rushing Attempts": "rush_att", "Receiving Yards": "rec_yds", "Receptions": "receptions",
              "Anytime TD": "anytime_td"}


def _implied(price: Any) -> Optional[float]:
    try:
        a = float(price)
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def _devig(p_yes: float, p_no: float) -> float:
    return p_yes / (p_yes + p_no)


# ---------------------------------------------------------------------------
# parsed plays: usage inputs and actuals
# ---------------------------------------------------------------------------

def load_parsed(season: int) -> List[Dict[str, str]]:
    path = PARSED / f"ncaaf_attributed_plays_{season}.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def actuals(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str], Dict[str, Dict[str, float]]]:
    """{(game_id, team): {player_key: {stat: total}}}; NCAAF: a sack is a QB rush."""
    out: Dict[Tuple[str, str], Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for r in rows:
        g, team, y = r["game_id"], r["posteam"], float(r["yards_gained"] or 0)
        d = out[(g, team)]
        if r["play_type"] == "run" and r["rusher_player_id"]:
            p = d[r["rusher_player_id"]]
            p["rush_att"] += 1
            p["rush_yds"] += y
            if r["touchdown"] == "1":
                p["anytime_td"] = 1.0
        elif r["play_type"] == "pass" and r["passer_player_id"]:
            q = d[r["passer_player_id"]]
            if r["sack"] == "1":
                q["rush_att"] += 1
                q["rush_yds"] += y
                continue
            q["pass_att"] += 1
            if r["complete_pass"] == "1":
                q["completions"] += 1
                q["pass_yds"] += y
                if r["touchdown"] == "1":
                    q["pass_td"] += 1
                if r["receiver_player_id"]:
                    rc = d[r["receiver_player_id"]]
                    rc["receptions"] += 1
                    rc["rec_yds"] += y
                    if r["touchdown"] == "1":
                        rc["anytime_td"] = 1.0
    return out


# ---------------------------------------------------------------------------
# quote rows
# ---------------------------------------------------------------------------

def load_rows(season: int, tasks: Dict[str, Dict[str, Any]], parsed_cur: List[Dict[str, str]],
              parsed_prior: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    from syndicate.features.football.sim_engine.smartsim2 import player_attribution as A
    drops: Dict[str, int] = defaultdict(int)
    act = actuals(parsed_cur)
    pairs: Dict[Tuple, Dict[str, float]] = defaultdict(dict)
    for path in sorted(glob.glob(str(QUOTES / f"quotes_{season}_wk*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            q = json.loads(line)
            gid = str(q.get("cfbd_game_id"))
            stat = MARKET_KEY.get(q.get("market"))
            if gid not in tasks or stat is None:
                drops["game_not_in_tasks_or_market"] += 1
                continue
            pairs[(gid, q["bookmaker"], stat, q["player_name"], q.get("line"))][str(q["selection"]).lower()] = q["price"]
    rosters: Dict[Tuple[str, str], List[str]] = {}

    def roster(gid: str, team: str, week: int) -> List[str]:
        key = (gid, team)
        if key not in rosters:
            cur = [r for r in parsed_cur if int(r["week"] or 0) < week]
            u = A.build_team_usage(team, cur, parsed_prior)
            ros = sorted({p.player_id for p in u.players} | ({u.qb_id} if u.qb_id else set())
                         | set(act.get((gid, team), {}).keys()))
            rosters[key] = ros
        return rosters[key]

    rows = []
    for (gid, book, stat, player, line), sides in pairs.items():
        t = tasks[gid]
        key = U.player_key(player)
        side = None
        for s in ("home", "away"):
            ros = roster(gid, t[s], t["week"])
            if U.resolve_key(key, ros) in ros:
                if side is not None:
                    side = "both"
                    break
                side = s
        if side in (None, "both"):
            drops[f"player_side_{side or 'unknown'}"] += 1
            continue
        team = t[side]
        ros = roster(gid, team, t["week"])
        pk = U.resolve_key(key, ros)
        actual = act.get((gid, team), {}).get(pk, {})
        if stat == "anytime_td":
            if "yes" not in sides or "no" not in sides:
                drops["td_one_sided"] += 1
                continue
            yes, no = _implied(sides["yes"]), _implied(sides["no"])
            if yes is None or no is None:
                continue
            rows.append({"gid": gid, "week": t["week"], "side": side, "team": team, "pid": pk, "player": player,
                         "stat": stat, "line": None, "book": book, "y": int(actual.get("anytime_td", 0.0) >= 1),
                         "p_book": _devig(yes, no)})
            continue
        if line is None or "over" not in sides or "under" not in sides:
            drops["one_sided"] += 1
            continue
        a = actual.get(stat, 0.0)
        if a == float(line):
            drops["push"] += 1
            continue
        over, under = _implied(sides["over"]), _implied(sides["under"])
        if over is None or under is None:
            continue
        rows.append({"gid": gid, "week": t["week"], "side": side, "team": team, "pid": pk, "player": player,
                     "stat": stat, "line": float(line), "book": book, "y": int(a > float(line)),
                     "p_book": _devig(over, under)})
    return rows, dict(drops)


# ---------------------------------------------------------------------------
# sims (workers)
# ---------------------------------------------------------------------------

_W: Dict[str, Any] = {}


def _init(work: str, season: int) -> None:
    F._ncaaf_init(work, {})
    from syndicate.features.football.sim_engine.smartsim2 import player_attribution as A
    _W.update(A=A, tables=A.AttributionTables.load(TABLES), cur=load_parsed(season), prior=load_parsed(season - 1))


def sim_game(task: Dict[str, Any]) -> Dict[str, Any]:
    A, gen = _W["A"], F._W["gen"]
    cur = [r for r in _W["cur"] if int(r["week"] or 0) < task["week"]]
    usage = {s: A.build_team_usage(task[s], cur, _W["prior"], force_active=task["quoted"][s],
                                   qb_override=task["quoted_qb"][s]) for s in ("home", "away")}
    acc = A.AttributionAccumulator(home=usage["home"], away=usage["away"], tables=_W["tables"], sacks_are_rushing=True)
    t0 = time.time()
    gen.build_projection(season=task["season"], week=task["week"], home_team=task["home"], away_team=task["away"],
                         game_id=str(task["game_id"]), ppa_index={}, rating_source=task["rating_source"], seeds=SEEDS,
                         sp_index=task["index"], sp_means=tuple(task["means"]), segment_accumulator=acc)
    probs = {}
    for pid, stat, line in task["asks"]:
        vals = acc.results.get(pid, {}).get(stat)
        if vals is None:
            probs[f"{pid}|{stat}|{line}"] = None
        elif line is None:
            probs[f"{pid}|{stat}|{line}"] = sum(1 for v in vals if v >= 1) / len(vals)
        else:
            probs[f"{pid}|{stat}|{line}"] = A.prob_over(vals, float(line))
    team = {s: {k: sum(v) / len(v) for k, v in acc.team_totals[s].items()} for s in ("home", "away")}
    return {"gid": str(task["game_id"]), "probs": probs, "team_means": team, "secs": round(time.time() - t0, 1),
            "qb": {s: usage[s].qb_id for s in ("home", "away")}}


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _ll(p: float, y: int) -> float:
    p = min(1 - 1e-3, max(1e-3, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _paired(rows: List[Dict[str, Any]], a: str, b: str, reps: int = 2000) -> Tuple[float, float, float]:
    by_g: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        by_g[r["gid"]].append(_ll(r[a], r["y"]) - _ll(r[b], r["y"]))
    games = list(by_g)
    rng = random.Random(9)

    def mean_of(gs):
        vals = [v for g in gs for v in by_g[g]]
        return sum(vals) / len(vals)
    bs = sorted(mean_of([games[rng.randrange(len(games))] for _ in games]) for _ in range(reps))
    return mean_of(games), bs[int(0.025 * reps)], bs[int(0.975 * reps) - 1]


def _slope(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    if len(rows) < 30:
        return None
    ps, ys = [r[key] for r in rows], [r["y"] for r in rows]
    mp, my = sum(ps) / len(ps), sum(ys) / len(ys)
    v = sum((p - mp) ** 2 for p in ps)
    return sum((p - mp) * (y - my) for p, y in zip(ps, ys)) / v if v else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit-games", type=int, default=0)
    args = ap.parse_args()
    from scripts.football_scenario_rates import idle_self
    idle_self()   # fleet shares this machine
    if args.season == 2025:
        raise SystemExit("2025 is the held-out Phase C read; its production comparison is not implemented here yet")
    season = args.season
    tag = f"{season}" + (f"_smoke{args.limit_games}" if args.limit_games else "")
    task_list = F.ncaaf_tasks([season], SEEDS)
    tasks = {str(t["game_id"]): t for t in task_list}
    cur, prior = load_parsed(season), load_parsed(season - 1)
    rows, drops = load_rows(season, tasks, cur, prior)
    games = sorted({r["gid"] for r in rows})
    if args.limit_games:
        games = games[:: max(1, len(games) // args.limit_games)][: args.limit_games]
        rows = [r for r in rows if r["gid"] in set(games)]
    print(f"[ncaaf attr {season}] {len(rows)} quote rows over {len(games)} games (of {len(tasks)} sim tasks); drops {drops}",
          flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / f"ncaaf_attr_sims_{tag}.jsonl"
    done = {}
    if cache.exists():
        for l in cache.read_text(encoding="utf-8").splitlines():
            if l.strip():
                d = json.loads(l)
                done[d["gid"]] = d
    todo = []
    for gid in games:
        if gid in done:
            continue
        rs = [r for r in rows if r["gid"] == gid]
        quoted = {"home": sorted({r["pid"] for r in rs if r["side"] == "home"}),
                  "away": sorted({r["pid"] for r in rs if r["side"] == "away"})}
        votes: Dict[str, Dict[str, int]] = {"home": {}, "away": {}}
        for r in rs:
            if r["stat"].startswith("pass_"):
                votes[r["side"]][r["pid"]] = votes[r["side"]].get(r["pid"], 0) + 1
        t = dict(tasks[gid])
        t.update(asks=sorted({(r["pid"], r["stat"], r["line"]) for r in rs}, key=str), quoted=quoted,
                 quoted_qb={s: (max(v, key=v.get) if v else None) for s, v in votes.items()})
        todo.append(t)
    print(f"[ncaaf attr] {len(done)} cached, {len(todo)} games to simulate at {SEEDS} seeds", flush=True)
    t0 = time.time()
    if todo:
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init, initargs=(str(F.ncaaf_work()), season)) as ex, \
                cache.open("a", encoding="utf-8") as fh:
            futs = [ex.submit(sim_game, t) for t in todo]
            for i, f in enumerate(as_completed(futs), 1):
                d = f.result()
                fh.write(json.dumps(d) + "\n")
                fh.flush()
                done[d["gid"]] = d
                if i % 10 == 0 or i == len(todo):
                    el = time.time() - t0
                    print(f"[ncaaf attr] {i}/{len(todo)} {el / 60:.1f} min eta {el / i * (len(todo) - i) / 60:.1f} min", flush=True)
    for r in rows:
        d = done.get(r["gid"])
        r["p_attr"] = d["probs"].get(f"{r['pid']}|{r['stat']}|{r['line']}") if d else None
    graded = [r for r in rows if r.get("p_attr") is not None]
    # construction check: simulated vs parsed team volume
    act = actuals(cur)
    sim_t: Dict[str, List[float]] = defaultdict(list)
    real_t: Dict[str, List[float]] = defaultdict(list)
    for gid in games:
        d = done.get(gid)
        if not d:
            continue
        for s in ("home", "away"):
            team = tasks[gid][s]
            tot = defaultdict(float)
            for p in act.get((gid, team), {}).values():
                for k, v in p.items():
                    tot[k] += v
            for k in ("pass_att", "pass_yds", "rush_att", "rush_yds"):
                sim_t[k].append(d["team_means"][s][k])
                real_t[k].append(tot.get(k, 0.0))
    print(f"\n[ncaaf attr {season}] graded {len(graded)} of {len(rows)} rows; unattributed {len(rows) - len(graded)}")
    print("construction (per team-game):  " + "  ".join(
        f"{k} sim {sum(sim_t[k]) / len(sim_t[k]):.1f} real {sum(real_t[k]) / len(real_t[k]):.1f}" for k in sim_t if sim_t[k]))
    print(f"{'market':12} {'n':>6} {'games':>5} {'LL attr':>8} {'LL book':>8}  {'attr-book [95% CI]':>28}  slope attr/book")
    rep = {}
    for stat in sorted({r["stat"] for r in graded}):
        rs = [r for r in graded if r["stat"] == stat]
        if len(rs) < 30:
            continue
        m, lo, hi = _paired(rs, "p_attr", "p_book")
        la = sum(_ll(r["p_attr"], r["y"]) for r in rs) / len(rs)
        lb = sum(_ll(r["p_book"], r["y"]) for r in rs) / len(rs)
        sa, sb = _slope(rs, "p_attr"), _slope(rs, "p_book")
        rep[stat] = {"n": len(rs), "games": len({r["gid"] for r in rs}), "ll_attr": la, "ll_book": lb,
                     "attr_minus_book": [m, lo, hi], "beats_book": hi < 0, "slope_attr": sa, "slope_book": sb}
        print(f"{stat:12} {len(rs):6d} {rep[stat]['games']:5d} {la:8.4f} {lb:8.4f}  {m:+.4f} [{lo:+.4f},{hi:+.4f}]{'*' if hi < 0 else ' '}  "
              f"{'-' if sa is None else f'{sa:.2f}'}/{'-' if sb is None else f'{sb:.2f}'}")
    (OUT / f"ncaaf_attr_report_{tag}.json").write_text(json.dumps(
        {"season": season, "rows": len(rows), "graded": len(graded), "drops": drops, "markets": rep,
         "construction": {k: [sum(sim_t[k]) / len(sim_t[k]), sum(real_t[k]) / len(real_t[k])] for k in sim_t if sim_t[k]}},
        indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
