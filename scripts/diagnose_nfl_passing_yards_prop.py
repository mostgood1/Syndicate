"""Why is production's NFL passing-yards prop probability worse than a coin? -- lane `nfl-passing-yards-prop-coin`.

Rows are built exactly as `scripts/backtest_football_attribution_props.build_rows` builds them (same quotes,
same event map, same production `player_stats` / `props` calls), plus the fields each candidate cause needs:
the raw as-of mean, the context multiplier, the sd, n, the rate source, the as-of game log, and an OFFICIAL
per-game stat recomputed from pbp (sacks and two-point plays excluded) to test the grading convention.

    py -3 scripts/diagnose_nfl_passing_yards_prop.py build --seasons 2023,2024     # FIT rows -> jsonl
    py -3 scripts/diagnose_nfl_passing_yards_prop.py analyze --seasons 2023,2024   # decomposition table

2025 is held out and was read once by lane football-sim-player-attribution; building it here needs
`--second-read-2025` and is disclosed as a second read.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import backtest_nfl_lines_props as H  # noqa: E402

ROOT = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\nfl_source")
OUT = Path(r"C:\tmp\football_scenarios\passing_yards_coin")
STATS = ("passing_yards", "passing_attempts")


def _official_qb_games(season: int) -> Dict[Tuple[str, str], Dict[str, float]]:
    """(game_id, passer_id) -> official attempts / yards (sacks + 2pt excluded) and team dropback share."""
    path = ROOT / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
    agg: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(lambda: {"att": 0.0, "yds": 0.0, "db": 0.0, "sacks": 0.0})
    team_db: Dict[Tuple[str, str], float] = defaultdict(float)
    team_of: Dict[Tuple[str, str], str] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("season_type") != "REG" or not r.get("passer_player_id"):
                continue
            k = (r["game_id"], r["passer_player_id"])
            two = r.get("two_point_attempt") == "1"
            if r.get("qb_dropback") == "1" and not two:
                agg[k]["db"] += 1
                team_db[(r["game_id"], r.get("posteam") or "")] += 1
                team_of[k] = r.get("posteam") or ""
            if two:
                continue
            if r.get("sack") == "1":
                agg[k]["sacks"] += 1
                continue
            if r.get("pass_attempt") == "1":
                agg[k]["att"] += 1
            if r.get("passing_yards"):
                agg[k]["yds"] += float(r["passing_yards"])
    out = {}
    for k, v in agg.items():
        tot = team_db.get((k[0], team_of.get(k, "")), 0.0)
        out[k] = dict(v, db_share=(v["db"] / tot) if tot else 0.0)
    return out


def build(seasons: List[int]) -> Path:
    H.configure_env(ROOT)
    H._patch_game_log_cache()
    from syndicate.features.nfl import player_stats as ps
    from syndicate.features.nfl import props as P
    from syndicate.features.nfl.game_context import game_context
    from syndicate.features.shared.team_aliases import canonical_team

    unfed = [s for s in seasons if not game_context(s)]
    if unfed:
        raise SystemExit(f"refusing: game_context() resolves no schedule for {unfed}")
    sched = H.load_schedule(ROOT)
    quotes, _ = H.load_quotes(ROOT, seasons)
    ev_map, _ = H.map_events(quotes, sched)
    official = {s: _official_qb_games(s) for s in set(seasons) | {s - 1 for s in seasons}}
    drops: Counter = Counter()
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
                mean, sd, n, rsrc = ps.player_rate_with_prior(season, week, pid, stat)
                if mean is None:
                    drops["no_model_rate"] += 1
                else:
                    mult = P.nfl_game_context_multiplier(season, week, pid, stat)
                    actual = ps.final_stat_value(season, gid, pid, stat)
                    if actual is None:
                        drops["no_actual"] += 1
                    else:
                        log_season = season if rsrc == "current_season_rolling" else season - 1
                        log = [r for r in ps.player_game_log(log_season, pid)
                               if rsrc != "current_season_rolling" or r["week"] < week]
                        off = official[season].get((gid, pid), {})
                        res = {"pid": pid, "season": season, "week": week, "mean_raw": float(mean), "ctx": mult,
                               "mean": float(mean) * mult, "sd": sd, "n": n, "rsrc": rsrc, "actual": float(actual),
                               "team": canon,
                               "log": [{"gid": r["game_id"], "w": r["week"], "v": r[stat],
                                        "att": r["passing_attempts"],
                                        "off_att": official[log_season].get((r["game_id"], pid), {}).get("att"),
                                        "off_yds": official[log_season].get((r["game_id"], pid), {}).get("yds"),
                                        "share": official[log_season].get((r["game_id"], pid), {}).get("db_share")}
                                       for r in log],
                               "off_actual_att": off.get("att"), "off_actual_yds": off.get("yds"),
                               "actual_share": off.get("db_share"), "actual_sacks": off.get("sacks")}
        resolved[key] = res
        return res

    pairs: Dict[Tuple, Dict[str, float]] = defaultdict(dict)
    for q in quotes:
        gid = ev_map.get((q["home"], q["away"], q["commence"]))
        if gid is None or not sched[gid]["completed"]:
            continue
        pairs[(gid, q["book"], q["market"], q["player"], q["line"])][q["sel"]] = q["price"]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"rows_{'-'.join(map(str, seasons))}.jsonl"
    n_rows = 0
    with path.open("w", encoding="utf-8") as fh:
        for (gid, book, market, player, line), sides in pairs.items():
            stat = P._NFL_PROP_MARKET_TO_STAT[market]
            if stat not in STATS:
                continue
            r = resolve(gid, player, stat)
            if r is None:
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
                drops["no_model_probability"] += 1
                continue
            row = dict(r, gid=gid, book=book, player=player, stat=stat, line=float(line), y=int(r["actual"] > line),
                       p_model=p_model, p_book=H.devig(H.implied(sides["over"]), H.implied(sides["under"])))
            fh.write(json.dumps(row) + "\n")
            n_rows += 1
    print(f"[diag] wrote {n_rows} rows to {path}; drops {dict(drops)}", flush=True)
    return path


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------

def _ll(p: float, y: int) -> float:
    p = min(max(p, 1e-3), 1 - 1e-3)
    return -math.log(p if y else 1 - p)


def _slope(ps: List[float], ys: List[int]) -> Optional[float]:
    """Calibration slope as lane football-sim-player-attribution defines it: OLS of y on p (1 = calibrated,
    0 = no information, < 0 = inverted)."""
    mp, my = statistics.fmean(ps), statistics.fmean(ys)
    v = sum((p - mp) ** 2 for p in ps)
    return sum((p - mp) * (y - my) for p, y in zip(ps, ys)) / v if v else None


def _boot_delta(rows: List[Dict[str, Any]], fa, fb, n_boot: int = 500, seed: int = 7) -> Tuple[float, float, float]:
    """Paired game-clustered bootstrap of mean LL(fa) - LL(fb)."""
    import random
    by_g: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        by_g[r["gid"]].append(_ll(fa(r), r["y"]) - _ll(fb(r), r["y"]))
    gs = list(by_g)
    point = sum(sum(v) for v in by_g.values()) / sum(len(v) for v in by_g.values())
    rng = random.Random(seed)
    ds = []
    for _ in range(n_boot):
        s = n = 0.0
        for g in (rng.choice(gs) for _ in gs):
            s += sum(by_g[g])
            n += len(by_g[g])
        ds.append(s / n)
    ds.sort()
    return point, ds[int(0.025 * n_boot)], ds[int(0.975 * n_boot)]


def _prob(stat: str, mean: float, sd: float, n: int, line: float) -> Optional[float]:
    from syndicate.features.nfl import props as P
    return P._nfl_prop_model_probability(stat=stat, mean=mean, stdev=sd, n=n, line=line)


def _ols(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else float("nan")
    return my - b * mx, b


def analyze(path: Path) -> Dict[str, Any]:
    H.configure_env(ROOT)
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    rep: Dict[str, Any] = {"rows_file": str(path)}
    for stat in STATS:
        R = [r for r in rows if r["stat"] == stat]
        if not R:
            continue
        S: Dict[str, Any] = {"n": len(R), "games": len({r["gid"] for r in R}), "players": len({r["pid"] for r in R})}
        ys = [r["y"] for r in R]
        S["over_rate"] = round(statistics.fmean(ys), 4)
        S["mean_p_book"] = round(statistics.fmean(r["p_book"] for r in R), 4)
        S["mean_p_model"] = round(statistics.fmean(r["p_model"] for r in R), 4)

        def arm(name: str, f) -> None:
            ps = [f(r) for r in R]
            if any(p is None for p in ps):
                S.setdefault("arms", {})[name] = {"error": f"{sum(p is None for p in ps)} rows unpriced"}
                return
            S.setdefault("arms", {})[name] = {
                "LL": round(statistics.fmean(_ll(p, y) for p, y in zip(ps, ys)), 4),
                "brier": round(statistics.fmean((p - y) ** 2 for p, y in zip(ps, ys)), 4),
                "slope": round(_slope(ps, ys) or float("nan"), 3),
                "mean_abs_p_minus_half": round(statistics.fmean(abs(p - 0.5) for p in ps), 4)}

        arm("coin", lambda r: 0.5)
        arm("book", lambda r: r["p_book"])
        arm("production", lambda r: r["p_model"])
        # (1) spread / tail: same mean, wider sd
        for m in (1.5, 2.0, 3.0):
            arm(f"sd_x{m:g}", lambda r, m=m: _prob(stat, r["mean"], r["sd"] * m, r["n"], r["line"]))
        # empirical residual sd of (actual - mean) on these rows, used as a flat sd
        res_sd = statistics.pstdev([r["actual"] - r["mean"] for r in R])
        S["residual_sd_actual_minus_mean"] = round(res_sd, 2)
        S["model_sd_median"] = round(statistics.median(r["sd"] for r in R), 2)
        arm("sd_empirical_flat", lambda r: _prob(stat, r["mean"], res_sd, r["n"], r["line"]))
        # (2) mean: context off, line-anchored (no information), shrink toward line
        arm("ctx_off", lambda r: _prob(stat, r["mean_raw"], r["sd"], r["n"], r["line"]))
        arm("mean_eq_line", lambda r: _prob(stat, r["line"], r["sd"], r["n"], r["line"]))
        # information in the mean: actual - line on mean - line
        dx = [r["mean"] - r["line"] for r in R]
        dy = [r["actual"] - r["line"] for r in R]
        a, b = _ols(dx, dy)
        S["regress_actual_minus_line_on_mean_minus_line"] = {"intercept": round(a, 2), "slope": round(b, 3)}
        a2, b2 = _ols([r["mean_raw"] - r["line"] for r in R], dy)
        S["regress_on_raw_mean_minus_line"] = {"intercept": round(a2, 2), "slope": round(b2, 3)}
        S["mean_minus_line"] = {"median": round(statistics.median(dx), 2), "mean": round(statistics.fmean(dx), 2),
                                "p10": round(sorted(dx)[len(dx) // 10], 2), "p90": round(sorted(dx)[9 * len(dx) // 10], 2)}
        S["ctx"] = {"mean": round(statistics.fmean(r["ctx"] for r in R), 4),
                    "share_not_1": round(sum(r["ctx"] != 1.0 for r in R) / len(R), 4),
                    "p10": round(sorted(r["ctx"] for r in R)[len(R) // 10], 3),
                    "p90": round(sorted(r["ctx"] for r in R)[9 * len(R) // 10], 3)}
        for w in (0.25, 0.5):
            arm(f"mean_shrunk_to_line_w{w:g}",
                lambda r, w=w: _prob(stat, r["line"] + w * (r["mean"] - r["line"]), r["sd"], r["n"], r["line"]))
        # (3) QB identity / as-of log: starts-only mean (games with dropback share >= 0.7)
        def starts_mean(r):
            v = [g["v"] for g in r["log"] if (g.get("share") or 0) >= 0.7]
            return statistics.fmean(v) if len(v) >= 2 else None
        arm("mean_starts_only", lambda r: _prob(stat, starts_mean(r) * r["ctx"], r["sd"], r["n"], r["line"])
            if starts_mean(r) is not None else r["p_model"])
        partial = [r for r in R if any((g.get("share") or 0) < 0.7 for g in r["log"])]
        S["rows_with_partial_game_in_log"] = len(partial)
        S["rows_with_partial_game_in_log_given_rel_gap_lt_-20pct"] = round(
            statistics.fmean(int(r in partial) for r in R if (r["mean"] - r["line"]) / r["line"] < -0.2), 3)
        # (5) combined candidates: log restricted to starts (share >= 0.7) with mean AND sd recomputed through
        # production's own estimator (stdev + shrink_spread); Normal-only (blend off); official-convention log.
        from syndicate.features.nfl import player_stats as ps_mod

        def rate(r, starts_only: bool, official: bool):
            key = "off_att" if stat == "passing_attempts" else "off_yds"
            log = [g for g in r["log"] if not starts_only or (g.get("share") or 0) >= 0.7]
            vals = [(g[key] if official else g["v"]) for g in log]
            if len(vals) < 2 or any(v is None for v in vals):
                return r["mean"], r["sd"], r["n"]
            m = statistics.fmean(vals)
            return m * r["ctx"], ps_mod.shrink_spread(statistics.stdev(vals), len(vals), m, stat), len(vals)

        def normal(mean, sd, line):
            return 1.0 - statistics.NormalDist(mean, sd).cdf(line)

        arm("blend_off", lambda r: normal(r["mean"], r["sd"], r["line"]))
        arm("starts_only_rate", lambda r: _prob(stat, *rate(r, True, False), r["line"]))
        arm("starts_only_rate+blend_off", lambda r: normal(rate(r, True, False)[0], rate(r, True, False)[1], r["line"]))
        for w in (0.25, 0.5):
            arm(f"starts_only+blend_off+shrink_w{w:g}",
                lambda r, w=w: normal(r["line"] + w * (rate(r, True, False)[0] - r["line"]), rate(r, True, False)[1], r["line"]))
        arm("blend_off+mean_eq_line", lambda r: normal(r["line"], r["sd"], r["line"]))
        if stat == "passing_attempts":
            # graded on OFFICIAL attempts (sacks excluded) -- the quantity the book's line is about
            Ro = [r for r in R if r.get("off_actual_att") is not None and r["off_actual_att"] != r["line"]]
            yo = [int(r["off_actual_att"] > r["line"]) for r in Ro]
            S["official_grade"] = {"n": len(Ro), "over_rate": round(statistics.fmean(yo), 4)}
            for name, f in (("book", lambda r: r["p_book"]), ("production", lambda r: r["p_model"]),
                            ("official_log", lambda r: _prob(stat, *rate(r, False, True), r["line"])),
                            ("official_log+starts_only", lambda r: _prob(stat, *rate(r, True, True), r["line"])),
                            ("official_log+starts_only+blend_off",
                             lambda r: normal(rate(r, True, True)[0], rate(r, True, True)[1], r["line"]))):
                ps_ = [f(r) for r in Ro]
                S["official_grade"][name] = {"LL": round(statistics.fmean(_ll(p, y) for p, y in zip(ps_, yo)), 4),
                                             "slope": round(_slope(ps_, yo) or float("nan"), 3),
                                             "mean_p": round(statistics.fmean(ps_), 4)}
        # (4) convention: official (sack/2pt-free) actual vs production's actual
        diff = [r["actual"] - r["off_actual_" + ("att" if stat == "passing_attempts" else "yds")]
                for r in R if r.get("off_actual_att") is not None]
        S["actual_minus_official"] = {"mean": round(statistics.fmean(diff), 3) if diff else None,
                                      "share_nonzero": round(sum(d != 0 for d in diff) / len(diff), 4) if diff else None}
        off_key = "off_actual_att" if stat == "passing_attempts" else "off_actual_yds"
        Ro = [r for r in R if r.get(off_key) is not None and r[off_key] != r["line"]]
        S["over_rate_official"] = round(statistics.fmean(int(r[off_key] > r["line"]) for r in Ro), 4) if Ro else None
        S["book_LL_official_grade"] = round(statistics.fmean(_ll(r["p_book"], int(r[off_key] > r["line"])) for r in Ro), 4) if Ro else None
        S["prod_LL_official_grade"] = round(statistics.fmean(_ll(r["p_model"], int(r[off_key] > r["line"])) for r in Ro), 4) if Ro else None
        # segments
        seg: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in R:
            seg[f"rsrc={r['rsrc']}"].append(r)
            seg[f"n={'2-3' if r['n'] <= 3 else '4-8' if r['n'] <= 8 else '9+'}"].append(r)
            seg[f"partial_in_log={any((g.get('share') or 0) < 0.7 for g in r['log'])}"].append(r)
            rel = (r["mean"] - r["line"]) / r["line"]
            seg[f"rel_gap={'<-20%' if rel < -.2 else '-20..-5%' if rel < -.05 else '-5..+5%' if rel <= .05 else '+5..+20%' if rel <= .2 else '>+20%'}"].append(r)
            seg[f"actual_share={'<0.7' if (r.get('actual_share') or 0) < 0.7 else '>=0.7'}"].append(r)
        S["segments"] = {}
        for k, rr in sorted(seg.items()):
            yy = [r["y"] for r in rr]
            S["segments"][k] = {"n": len(rr), "games": len({r["gid"] for r in rr}),
                                "LL_prod": round(statistics.fmean(_ll(r["p_model"], r["y"]) for r in rr), 4),
                                "LL_book": round(statistics.fmean(_ll(r["p_book"], r["y"]) for r in rr), 4),
                                "over_rate": round(statistics.fmean(yy), 3),
                                "mean_p_prod": round(statistics.fmean(r["p_model"] for r in rr), 3)}
        S["delta_prod_minus_coin"] = _boot_delta(R, lambda r: r["p_model"], lambda r: 0.5)
        rep[stat] = S
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("build", "analyze"))
    ap.add_argument("--seasons", default="2023,2024")
    ap.add_argument("--second-read-2025", action="store_true")
    args = ap.parse_args()
    from scripts.football_scenario_rates import idle_self
    idle_self()   # the production fleet shares this machine
    seasons = [int(s) for s in args.seasons.split(",")]
    if 2025 in seasons and not args.second_read_2025:
        raise SystemExit("2025 is held out (read once by football-sim-player-attribution); pass --second-read-2025")
    path = OUT / f"rows_{'-'.join(map(str, seasons))}.jsonl"
    if args.cmd == "build":
        build(seasons)
        return 0
    rep = analyze(path)
    out = OUT / f"report_{'-'.join(map(str, seasons))}.json"
    out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
