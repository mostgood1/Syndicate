"""Phase B/C of lane `football-sim-player-attribution`: sim-attributed NFL props vs production's.

Pre-registered in `.syndicate/findings_2026-10-07_football_player_attribution.md`.

SAME ROWS, THREE PROBABILITIES. Quote rows, player resolution, the actual stat and production's
probability are built exactly as `scripts/backtest_nfl_lines_props.py` builds them -- through
production's own `nfl/player_stats` and `nfl/props._nfl_prop_model_probability`. The attribution
probability for the same row is the share of production's own 300 `build_projection` seeds in
which the attributed stat clears the line. The book is de-vigged per book (two-sided rows only).

    py -3 scripts/backtest_football_attribution_props.py --seasons 2023,2024 --workers 3
    py -3 scripts/backtest_football_attribution_props.py --seasons 2023,2024 --limit-games 6   # smoke
    FOOTBALL_SCENARIO_READ_VALIDATION=1 py -3 scripts/backtest_football_attribution_props.py --seasons 2025
"""
from __future__ import annotations

import argparse
import csv
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

from scripts import backtest_nfl_lines_props as H  # noqa: E402

ROOT = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\nfl_source")
OUT = Path(r"C:\tmp\football_scenarios\attribution")
TABLES = OUT / "attribution_tables_2023-2024.json"
SEEDS = 300
# production's stat names -> the attribution module's keys
STAT_KEY = {"passing_yards": "pass_yds", "passing_attempts": "pass_att", "passing_tds": "pass_td",
            "rushing_yards": "rush_yds", "rushing_attempts": "rush_att", "receptions": "receptions",
            "receiving_yards": "rec_yds", "interceptions": "interceptions", "anytime_td": "anytime_td"}
USAGE_COLS = ("game_id", "season_type", "week", "posteam", "play_type", "passer_player_id", "passer_player_name",
              "receiver_player_id", "receiver_player_name", "rusher_player_id", "rusher_player_name",
              "complete_pass", "sack", "yards_gained")


# ---------------------------------------------------------------------------
# rows: production's own resolution + probability, per quote (copied control flow of the
# harness's score_props; every number comes from the production functions it calls)
# ---------------------------------------------------------------------------

def build_rows(seasons: List[int]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    H._patch_game_log_cache()
    from syndicate.features.nfl import player_stats as ps
    from syndicate.features.nfl import props as P
    from syndicate.features.nfl.game_context import game_context
    from syndicate.features.shared.team_aliases import canonical_team

    unfed = [s for s in seasons if not game_context(s)]
    if unfed:
        raise SystemExit(f"refusing: game_context() resolves no schedule for {unfed}")
    sched = H.load_schedule(ROOT)
    quotes, _src = H.load_quotes(ROOT, seasons)
    ev_map, _miss = H.map_events(quotes, sched)
    drops: Dict[str, int] = defaultdict(int)
    resolved: Dict[Tuple[str, str, str], Optional[Dict[str, Any]]] = {}

    def resolve(gid: str, name: str, stat: str) -> Optional[Dict[str, Any]]:
        key = (gid, name, stat)
        if key in resolved:
            return resolved[key]
        g = sched[gid]
        season, week = g["season_i"], g["week_i"]
        res = None
        pid, _ = ps.resolve_player_id_with_prior(season, name)
        if pid is None:
            drops["player_unresolved"] += 1
        else:
            team, _ = ps.player_team_with_prior(season, week, pid)
            canon = canonical_team("nfl", team) if team else None
            if canon is None or canon not in {canonical_team("nfl", g["home_team"]), canonical_team("nfl", g["away_team"])}:
                drops["player_team_refused"] += 1
            else:
                if stat == "anytime_td":
                    mean, n, _ = ps.anytime_td_rate_with_prior(season, week, pid)
                    sd = None
                else:
                    mean, sd, n, _ = ps.player_rate_with_prior(season, week, pid, stat)
                if mean is None:
                    drops["no_model_rate"] += 1
                else:
                    mult = P.nfl_game_context_multiplier(season, week, pid, stat)
                    actual = ps.final_stat_value(season, gid, pid, stat)
                    if actual is None:
                        drops["no_actual"] += 1
                    else:
                        res = {"pid": pid, "season": season, "week": week, "mean": float(mean) * mult, "sd": sd,
                               "n": n, "actual": float(actual), "team": canon}
        resolved[key] = res
        return res

    pairs: Dict[Tuple, Dict[str, float]] = defaultdict(dict)
    for q in quotes:
        gid = ev_map.get((q["home"], q["away"], q["commence"]))
        if gid is None or not sched[gid]["completed"]:
            continue
        pairs[(gid, q["book"], q["market"], q["player"], q["line"])][q["sel"]] = q["price"]
    rows = []
    for (gid, book, market, player, line), sides in pairs.items():
        stat = P._NFL_PROP_MARKET_TO_STAT[market]
        r = resolve(gid, player, stat)
        if r is None:
            continue
        g = sched[gid]
        base = {"gid": gid, "season": r["season"], "week": r["week"], "home": g["home_team"], "away": g["away_team"],
                "pid": r["pid"], "player": player, "stat": stat, "book": book, "team": r["team"]}
        if stat == "anytime_td":
            if "yes" not in sides or "no" not in sides or H.implied(sides["yes"]) is None or H.implied(sides["no"]) is None:
                drops["td_one_sided"] += 1
                continue
            p_model = P._nfl_prop_model_probability(stat=stat, mean=r["mean"], stdev=None, n=r["n"], line=None)
            if p_model is None:
                continue
            rows.append(dict(base, line=None, y=int(r["actual"] >= 1), p_model=p_model,
                             p_book=H.devig(H.implied(sides["yes"]), H.implied(sides["no"]))))
            continue
        if line is None or "over" not in sides or "under" not in sides:
            drops["one_sided"] += 1
            continue
        if r["actual"] == line:
            drops["push"] += 1
            continue
        if H.implied(sides["over"]) is None or H.implied(sides["under"]) is None:
            continue
        p_model = P._nfl_prop_model_probability(stat=stat, mean=r["mean"], stdev=r["sd"], n=r["n"], line=line)
        if p_model is None:
            continue
        rows.append(dict(base, line=float(line), y=int(r["actual"] > line), p_model=p_model,
                         p_book=H.devig(H.implied(sides["over"]), H.implied(sides["under"]))))
    return rows, dict(drops)


# ---------------------------------------------------------------------------
# attribution sims (workers)
# ---------------------------------------------------------------------------

_W: Dict[str, Any] = {}


def _init(root: str) -> None:
    H.configure_env(Path(root))
    try:
        import psutil
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS if os.name == "nt" else 19)
    except Exception:  # noqa: BLE001
        pass
    from scripts import generate_smartsim2_nfl_projections as gen
    from syndicate.features.football.sim_engine.smartsim2 import player_attribution as A
    _W.update(gen=gen, A=A, plays={}, rows={}, tables=A.AttributionTables.load(TABLES))


def _season_rows(season: int) -> List[Dict[str, str]]:
    if season not in _W["rows"]:
        path = ROOT / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
        out = []
        if path.exists():
            with path.open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    if r.get("season_type") == "REG":
                        out.append({k: r.get(k, "") for k in USAGE_COLS})
        _W["rows"][season] = out
    return _W["rows"][season]


def _plays(season: int):
    if season not in _W["plays"]:
        _W["plays"][season] = _W["gen"].load_pbp_plays(season)
    return _W["plays"][season]


def sim_game(task: Dict[str, Any]) -> Dict[str, Any]:
    gen, A = _W["gen"], _W["A"]
    s, wk = task["season"], task["week"]
    cur = [r for r in _season_rows(s) if int(r["week"] or 0) < wk]
    prior = _season_rows(s - 1)
    usage = {side: A.build_team_usage(task[side], cur, prior, force_active=task["quoted"][side],
                                      qb_override=task["quoted_qb"][side], half_life=task.get("hl"))
             for side in ("home", "away")}
    acc = A.AttributionAccumulator(home=usage["home"], away=usage["away"], tables=_W["tables"],
                                   pass_odds_multiplier=task.get("c", 1.0), incomplete_as_run=task.get("r", 0.0))
    t0 = time.time()
    gen.build_projection(season=s, week=wk, home_team=task["home"], away_team=task["away"], game_id=task["gid"],
                         current_plays=_plays(s), prior_plays=_plays(s - 1), seeds=SEEDS, segment_accumulator=acc)
    probs = {}
    for pid, stat, line in task["asks"]:
        vals = acc.results.get(pid, {}).get(STAT_KEY.get(stat, stat))
        if vals is None:
            probs[f"{pid}|{stat}|{line}"] = None
        elif line is None:
            probs[f"{pid}|{stat}|{line}"] = sum(1 for v in vals if v >= 1) / len(vals)
        else:
            probs[f"{pid}|{stat}|{line}"] = A.prob_over(vals, float(line))
    team = {side: {k: sum(v) / len(v) for k, v in acc.team_totals[side].items()} for side in ("home", "away")}
    return {"gid": task["gid"], "probs": probs, "team_means": team, "secs": round(time.time() - t0, 1),
            "qb": {side: usage[side].qb_id for side in ("home", "away")},
            "n_players": {side: len(usage[side].players) for side in ("home", "away")}}


# Amendment 2 grid (pre-registered a5f2b4e0)
GRID_C = (1.0, 0.85, 0.7, 0.6, 0.5, 0.4)
GRID_R = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)


class _FanOut:
    """Hands each seed's output to every grid accumulator: the engine runs once per game."""

    def __init__(self, accs):
        self.accs = accs

    def add(self, output):
        for a in self.accs.values():
            a.add(output)


def fit_game(task: Dict[str, Any]) -> Dict[str, Any]:
    gen, A = _W["gen"], _W["A"]
    s, wk = task["season"], task["week"]
    cur = [r for r in _season_rows(s) if int(r["week"] or 0) < wk]
    prior = _season_rows(s - 1)
    usage = {side: A.build_team_usage(task[side], cur, prior) for side in ("home", "away")}
    accs = {f"{c}|{r}": A.AttributionAccumulator(home=usage["home"], away=usage["away"], tables=_W["tables"],
                                                 pass_odds_multiplier=c, incomplete_as_run=r)
            for c in GRID_C for r in GRID_R}
    gen.build_projection(season=s, week=wk, home_team=task["home"], away_team=task["away"], game_id=task["gid"],
                         current_plays=_plays(s), prior_plays=_plays(s - 1), seeds=task["seeds"],
                         segment_accumulator=_FanOut(accs))
    return {"gid": task["gid"], "grid": {k: {side: {st: sum(v) / len(v) for st, v in a.team_totals[side].items()
                                                  if st in ("rush_att", "pass_att", "rush_yds", "pass_yds")}
                                           for side in ("home", "away")} for k, a in accs.items()}}


def run_fit(rows: List[Dict[str, Any]], workers: int, every: int, seeds: int) -> Dict[str, Any]:
    games = sorted({r["gid"] for r in rows})[::every]
    meta = {r["gid"]: r for r in rows}
    tasks = [{"gid": g, "season": meta[g]["season"], "week": meta[g]["week"], "home": meta[g]["home"],
              "away": meta[g]["away"], "seeds": seeds} for g in games]
    print(f"[fit] {len(tasks)} FIT games x {seeds} seeds, {len(GRID_C) * len(GRID_R)} grid points per engine run", flush=True)
    sums: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    n = 0
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(str(ROOT),)) as ex:
        for i, f in enumerate(as_completed([ex.submit(fit_game, t) for t in tasks]), 1):
            d = f.result()
            for k, sides in d["grid"].items():
                for side in sides.values():
                    for st, v in side.items():
                        sums[k][st] += v
            n += 2
            if i % 10 == 0 or i == len(tasks):
                print(f"[fit] {i}/{len(tasks)}", flush=True)
    TARGET = {"rush_att": 27.0, "pass_att": 33.24}     # nflverse FIT 2023-24, 1,088 team-games
    table = []
    for k, st in sums.items():
        m = {x: v / n for x, v in st.items()}
        loss = sum((m[x] / TARGET[x] - 1.0) ** 2 for x in TARGET)
        c, r = map(float, k.split("|"))
        table.append((loss, c, r, m))
    table.sort()
    for loss, c, r, m in table[:8]:
        print(f"  c={c:<5} r={r:<4} loss {loss:.5f}  rush_att {m['rush_att']:.2f}  pass_att {m['pass_att']:.2f}  "
              f"rush_yds {m['rush_yds']:.1f}  pass_yds {m['pass_yds']:.1f}")
    base = next(t for t in table if t[1] == 1.0 and t[2] == 0.0)
    print(f"  (uncorrected c=1 r=0: rush_att {base[3]['rush_att']:.2f} pass_att {base[3]['pass_att']:.2f})")
    best = table[0]
    out = {"c": best[1], "r": best[2], "loss": best[0], "means": best[3], "games": len(tasks), "seeds": seeds,
           "target": TARGET, "uncorrected": base[3]}
    (OUT / "run_share_fit_nfl.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


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
    m = mean_of(games)
    bs = sorted(mean_of([games[rng.randrange(len(games))] for _ in games]) for _ in range(reps))
    return m, bs[int(0.025 * reps)], bs[int(0.975 * reps) - 1]


def _slope(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    """Calibration slope: logistic-free version -- OLS of y on p, centred (1 = calibrated, 0 = no information)."""
    if len(rows) < 30:
        return None
    ps = [r[key] for r in rows]
    ys = [r["y"] for r in rows]
    mp, my = sum(ps) / len(ps), sum(ys) / len(ys)
    v = sum((p - mp) ** 2 for p in ps)
    return sum((p - mp) * (y - my) for p, y in zip(ps, ys)) / v if v else None


def score(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for stat in sorted({r["stat"] for r in rows}):
        rs = [r for r in rows if r["stat"] == stat and r.get("p_attr") is not None]
        if len(rs) < 30:
            continue
        m_prod, lo_p, hi_p = _paired(rs, "p_attr", "p_model")
        m_book, lo_b, hi_b = _paired(rs, "p_attr", "p_book")
        ll = {k: sum(_ll(r[k], r["y"]) for r in rs) / len(rs) for k in ("p_attr", "p_model", "p_book")}
        out[stat] = {"n": len(rs), "games": len({r["gid"] for r in rs}), "logloss": ll,
                     "attr_minus_prod": [m_prod, lo_p, hi_p], "attr_minus_book": [m_book, lo_b, hi_b],
                     "beats_prod": hi_p < 0, "beats_book": hi_b < 0,
                     "slope": {k: _slope(rs, k) for k in ("p_attr", "p_model", "p_book")}}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit-games", type=int, default=0)
    ap.add_argument("--fit-run-share", action="store_true", help="amendment 2: grid-fit (c, r) on every 8th FIT game")
    ap.add_argument("--pass-odds-mult", type=float, default=1.0)
    ap.add_argument("--incomplete-as-run", type=float, default=0.0)
    ap.add_argument("--half-life", type=float, default=None, help="amendment 3 share estimator (E1: recency half-life)")
    ap.add_argument("--markets", default="", help="comma list of production stat names to grade (Phase C: passing_yards,passing_attempts)")
    args = ap.parse_args()
    from scripts.football_scenario_rates import idle_self
    idle_self()   # fleet shares this machine
    seasons = [int(s) for s in args.seasons.split(",")]
    tag = "-".join(map(str, seasons)) + (f"_smoke{args.limit_games}" if args.limit_games else "")
    if args.pass_odds_mult != 1.0 or args.incomplete_as_run != 0.0:
        tag += f"_c{args.pass_odds_mult:g}_r{args.incomplete_as_run:g}"
    if args.half_life is not None:
        tag += f"_hl{args.half_life:g}"
    if 2025 in seasons:
        if not os.environ.get("FOOTBALL_SCENARIO_READ_VALIDATION"):
            raise SystemExit("2025 props are the held-out read; set FOOTBALL_SCENARIO_READ_VALIDATION=1 (once)")
        marker = OUT / "PROPS_2025_READ"
        if marker.exists() and not args.limit_games:
            raise SystemExit(f"2025 props already read: {marker.read_text()}")
        if args.limit_games:
            raise SystemExit("no smoke runs on the held-out season")
        marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")
    H.configure_env(ROOT)
    from syndicate.features.shared.team_aliases import canonical_team
    rows, drops = build_rows(seasons)
    if args.markets:
        keep = {m.strip() for m in args.markets.split(",") if m.strip()}
        rows = [r for r in rows if r["stat"] in keep]
        tag += "_" + "-".join(sorted(keep))
    games = sorted({r["gid"] for r in rows})
    if args.limit_games:
        games = games[:: max(1, len(games) // args.limit_games)][: args.limit_games]
        rows = [r for r in rows if r["gid"] in set(games)]
    print(f"[attr] {len(rows)} quote rows over {len(games)} games, drops {drops}", flush=True)
    if args.fit_run_share:
        if 2025 in seasons:
            raise SystemExit("the run-share fit is FIT-only")
        run_fit(rows, args.workers, every=8, seeds=100)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / f"attr_sims_{tag}.jsonl"
    done = {}
    if cache.exists():
        for l in cache.read_text(encoding="utf-8").splitlines():
            if l.strip():
                d = json.loads(l)
                done[d["gid"]] = d
    tasks = []
    for gid in games:
        if gid in done:
            continue
        rs = [r for r in rows if r["gid"] == gid]
        asks = sorted({(r["pid"], r["stat"], r["line"]) for r in rs}, key=str)
        side_of = {canonical_team("nfl", rs[0]["home"]): "home", canonical_team("nfl", rs[0]["away"]): "away"}
        quoted = {"home": set(), "away": set()}
        qb_votes: Dict[str, Dict[str, int]] = {"home": {}, "away": {}}
        for r in rs:
            side = side_of.get(r["team"])
            if side is None:
                continue
            quoted[side].add(r["pid"])
            if r["stat"].startswith("passing_"):
                qb_votes[side][r["pid"]] = qb_votes[side].get(r["pid"], 0) + 1
        quoted_qb = {side: (max(v, key=v.get) if v else None) for side, v in qb_votes.items()}
        tasks.append({"gid": gid, "season": rs[0]["season"], "week": rs[0]["week"], "home": rs[0]["home"],
                      "away": rs[0]["away"], "asks": asks, "quoted": {k: sorted(v) for k, v in quoted.items()},
                      "quoted_qb": quoted_qb, "c": args.pass_odds_mult, "r": args.incomplete_as_run,
                      "hl": args.half_life})
    print(f"[attr] {len(done)} games cached, {len(tasks)} to simulate at {SEEDS} seeds", flush=True)
    t0 = time.time()
    if tasks:
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init, initargs=(str(ROOT),)) as ex, \
                cache.open("a", encoding="utf-8") as fh:
            futs = [ex.submit(sim_game, t) for t in tasks]
            for i, f in enumerate(as_completed(futs), 1):
                d = f.result()
                fh.write(json.dumps(d) + "\n")
                fh.flush()
                done[d["gid"]] = d
                if i % 10 == 0 or i == len(tasks):
                    el = time.time() - t0
                    print(f"[attr] {i}/{len(tasks)} {el / 60:.1f} min eta {el / i * (len(tasks) - i) / 60:.1f} min", flush=True)
    for r in rows:
        d = done.get(r["gid"])
        r["p_attr"] = d["probs"].get(f"{r['pid']}|{r['stat']}|{r['line']}") if d else None
    rep = score(rows)
    rep_meta = {"seasons": seasons, "rows": len(rows), "games": len(games), "drops": drops,
                "unattributed_rows": sum(1 for r in rows if r.get("p_attr") is None)}
    (OUT / f"attr_report_{tag}.json").write_text(json.dumps({"meta": rep_meta, "markets": rep}, indent=1), encoding="utf-8")
    print(f"\n[attr] {seasons}: {rep_meta}")
    print(f"{'market':16} {'n':>6} {'games':>5} {'LL attr':>8} {'LL prod':>8} {'LL book':>8}  {'attr-prod [95% CI]':>28}  {'attr-book [95% CI]':>28}  slope a/p/b")
    for stat, m in rep.items():
        ap_, ab = m["attr_minus_prod"], m["attr_minus_book"]
        sl = m["slope"]
        print(f"{stat:16} {m['n']:6d} {m['games']:5d} {m['logloss']['p_attr']:8.4f} {m['logloss']['p_model']:8.4f} "
              f"{m['logloss']['p_book']:8.4f}  {ap_[0]:+.4f} [{ap_[1]:+.4f},{ap_[2]:+.4f}]{'*' if m['beats_prod'] else ' '} "
              f"{ab[0]:+.4f} [{ab[1]:+.4f},{ab[2]:+.4f}]{'*' if m['beats_book'] else ' '}  "
              + "/".join("-" if sl[k] is None else f"{sl[k]:.2f}" for k in ("p_attr", "p_model", "p_book")))


if __name__ == "__main__":
    main()
