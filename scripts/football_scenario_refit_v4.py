"""Re-fit v4 (NCAAF): cross-tier strength + early-season blending levers, with moments that can see them.

Lane `football-scenario-calibration`. Pre-registered ("RE-FIT v4" + "v4 amendment 1") in
`.syndicate/findings_2026-10-06_football_scenario_calibration.md` before this file existed.

INPUT LEVERS (applied to each game's as-of SP+/PPA blend entry BEFORE `sp_offense_defense_rating`; production
code is untouched -- a shipped result would be implemented in the NCAAF generator as a separate, reviewed step):
  tier_offset      d SP+ points: every P4 team gets +d offense and -d defense-allowed (a cross-tier gap)
  tier_decay_weeks K: d x max(0, 1 - (week - 3) / K); K = 0 means no decay (an EARLY-season gap)
  blend_k          the in-season blend's prior constant k (w = n / (n + k)); production 2.0
Everything else is a CalibrationProfile override, as in v2/v3.

    py -3 scripts/football_scenario_refit_v4.py descent  --workers 3
    FOOTBALL_SCENARIO_READ_VALIDATION=1 py -3 scripts/football_scenario_refit_v4.py validate --season 2026 --workers 3
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import football_scenario_rates as F  # noqa: E402
from scripts import football_scenario_refit as R  # noqa: E402

SPORT = "ncaaf"
OUT_DIR = "refit_v4"
FIT_SEASON = 2024
INPUT_LEVERS = ("tier_offset", "tier_decay_weeks", "blend_k")
P4_CONFS = {"SEC", "Big Ten", "Big 12", "ACC"}
GRIDS_V4 = {"tier_offset": (0.0, 1.0, 2.0, 3.0, 4.0), "tier_decay_weeks": (0.0, 4.0, 8.0),
            "blend_k": (0.5, 1.0, 2.0, 4.0, 8.0)}
DEFAULTS_V4 = {"tier_offset": 0.0, "tier_decay_weeks": 0.0, "blend_k": 2.0}
MOMENTS_V4 = R.MOMENTS + ("bias_tier_early", "bias_conf_early")


# ---------------------------------------------------------------------------
# the input transform -- shared with the live replay so both apply it identically
# ---------------------------------------------------------------------------

def p4_norm_set(season: int, norm) -> set:
    out = set()
    for g in F._ncaaf_games(season):
        for side in ("home", "away"):
            if g.get(f"{side}Conference") in P4_CONFS or g.get(f"{side}Team") == "Notre Dame":
                out.add(norm(g[f"{side}Team"]))
    return out


def apply_input_levers(task: Dict[str, Any], ov: Dict[str, Any], p4: set) -> Dict[str, Any]:
    d = float(ov.get("tier_offset", 0.0) or 0.0)
    if not d:
        return task
    k_weeks = float(ov.get("tier_decay_weeks", 0.0) or 0.0)
    eff = d * (max(0.0, 1.0 - (int(task["week"]) - 3) / k_weeks) if k_weeks > 0 else 1.0)
    if eff == 0.0:
        return task
    idx = {t: ((o + eff, de - eff) if t in p4 else (o, de)) for t, (o, de) in task["index"].items()}
    return dict(task, index=idx)


def profile_part(ov: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in ov.items() if k not in INPUT_LEVERS}


# ---------------------------------------------------------------------------
# evaluator: one pool; tasks rebuilt per blend_k; tier transform applied per task
# ---------------------------------------------------------------------------

class V4Evaluator:
    def __init__(self, season: int, seeds: int, workers: int, cache: Path, select) -> None:
        self.season, self.seeds, self.cache = season, seeds, cache
        F._ncaaf_env(F.ncaaf_prepare_work())
        from scripts import generate_smartsim2_ncaaf_projections as gen
        self.p4 = p4_norm_set(season, gen.norm)
        self._by_k: Dict[Optional[float], List[dict]] = {}
        base = self._tasks(None)
        self.ids = select(base)
        from concurrent.futures import ProcessPoolExecutor
        self.pool = ProcessPoolExecutor(max_workers=workers, initializer=R._init,
                                        initargs=(SPORT, str(F.ncaaf_work())))
        self.done: Dict[str, Dict[str, dict]] = {}
        if cache.exists():
            for line in cache.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    self.done.setdefault(d["overrides_key"], {})[d["game_id"]] = d

    def _tasks(self, k: Optional[float]) -> List[dict]:
        key = None if k in (None, DEFAULTS_V4["blend_k"]) else float(k)
        if key not in self._by_k:
            self._by_k[key] = F.ncaaf_tasks([self.season], self.seeds, blend_k=key)
        return self._by_k[key]

    def run(self, ov: Dict[str, Any]) -> Dict[str, dict]:
        okey = R._key(ov)
        have = self.done.setdefault(okey, {})
        tasks = [t for t in self._tasks(ov.get("blend_k")) if str(t["game_id"]) in self.ids]
        prof = profile_part(ov)
        todo = [dict(apply_input_levers(t, ov, self.p4), overrides=prof, overrides_key=okey)
                for t in tasks if str(t["game_id"]) not in have]
        if todo:
            t0 = time.time()
            with self.cache.open("a", encoding="utf-8") as fh:
                for d in self.pool.map(R._task, todo, chunksize=2):
                    d["overrides_key"] = okey
                    fh.write(json.dumps(d) + "\n")
                    have[d["game_id"]] = d
            print(f"    [eval {okey}] {len(todo)} games x {self.seeds} seeds in {(time.time() - t0) / 60:.1f} min", flush=True)
        return have

    def close(self) -> None:
        self.pool.shutdown()


# ---------------------------------------------------------------------------
# moments: v2's 15 + two early-season bias moments
# ---------------------------------------------------------------------------

def _meta(season: int) -> Dict[str, dict]:
    return {str(g["id"]): g for g in F._ncaaf_games(season)}


def _is_p4(g: dict, side: str) -> bool:
    return g.get(f"{side}Conference") in P4_CONFS or g.get(f"{side}Team") == "Notre Dame"


def early_groups(meta: Dict[str, dict], games: List[str]) -> Tuple[Dict[str, int], List[str]]:
    """({gid: +1/-1 sign toward the P4 team} for early P4-vs-G5 games, [early conference gids])."""
    tier, conf = {}, []
    for gid in games:
        g = meta.get(gid)
        if not g or not (3 <= int(g.get("week") or 0) <= 6):
            continue
        hp, ap = _is_p4(g, "home"), _is_p4(g, "away")
        if hp != ap and not g.get("conferenceGame"):
            tier[gid] = 1 if hp else -1
        if g.get("conferenceGame"):
            conf.append(gid)
    return tier, conf


def bias_moments(sims: Dict[str, dict], real: Dict[str, dict], tier: Dict[str, int], conf: List[str]) -> Dict[str, float]:
    t = [tier[g] * (real[g]["margin"] - sims[g]["margin_mean"]) for g in tier if g in sims]
    c = [real[g]["margin"] - sims[g]["margin_mean"] for g in conf if g in sims]
    return {"bias_tier_early": sum(t) / len(t) if t else 0.0, "bias_conf_early": sum(c) / len(c) if c else 0.0}


def bias_se(prod: Dict[str, dict], real: Dict[str, dict], tier: Dict[str, int], conf: List[str],
            reps: int = 400) -> Dict[str, float]:
    rng = random.Random(7)
    out = {}
    for name, xs in (("bias_tier_early", [tier[g] * (real[g]["margin"] - prod[g]["margin_mean"]) for g in tier if g in prod]),
                     ("bias_conf_early", [real[g]["margin"] - prod[g]["margin_mean"] for g in conf if g in prod])):
        if len(xs) < 5:
            out[name] = float("nan")
            continue
        bs = [sum(xs[rng.randrange(len(xs))] for _ in xs) / len(xs) for _ in range(reps)]
        m = sum(bs) / reps
        out[name] = (sum((b - m) ** 2 for b in bs) / reps) ** 0.5
    return out


def full_objective(sims, games, terc, real, real_m, se, tier, conf) -> Tuple[float, Dict[str, float], Dict[str, float]]:
    m = R.moments(sims, games, terc, real=real)
    m.update(bias_moments(sims, real, tier, conf))
    z = {k: (m[k] - real_m[k]) / se[k] for k in MOMENTS_V4 if se.get(k) and se[k] == se[k]}
    return sum(v * v for v in z.values()), z, m


def _setup(ev: V4Evaluator, real: Dict[str, dict], meta: Dict[str, dict]):
    prod = ev.run({})
    games = sorted(set(prod) & set(real))
    terc = R._terciles(prod, games)
    real_m = R.moments(real, games, terc, is_real=True)
    real_m.update({"bias_tier_early": 0.0, "bias_conf_early": 0.0})
    tier, conf = early_groups(meta, games)
    se = R.real_se(real, games, terc, prod=prod)
    se.update(bias_se(prod, real, tier, conf))
    return prod, games, terc, real_m, se, tier, conf


# ---------------------------------------------------------------------------
# descent (FIT 2024)
# ---------------------------------------------------------------------------

SMOKE = False
VARIANT = "v4"          # "v41": constrained descent (gate b enforced on FIT), pre-registered 913af5d6
V41_START = {"tier_offset": 3.0, "tier_decay_weeks": 8.0}


def fit_select(meta: Dict[str, dict]):
    """Every 4th FIT game PLUS every early (wk 3-6) P4-vs-G5 and conference game (pre-registered)."""
    def select(tasks: List[dict]) -> set:
        ids = {str(t["game_id"]) for t in tasks[::R.EVERY]}
        tier, conf = early_groups(meta, [str(t["game_id"]) for t in tasks])
        allids = ids | set(tier) | set(conf)
        if SMOKE:   # 6 early tier + 6 early conference + 8 others (fewer leaves a bootstrap tercile empty)
            allids = set(list(tier)[:6]) | set(conf[:6]) | set(sorted(ids)[:8])
        return allids
    return select


def cmd_descent(args) -> None:
    out = F.OUT_ROOT / SPORT / (OUT_DIR + "_smoke" if SMOKE else OUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    meta = _meta(FIT_SEASON)
    real = F._load(F.OUT_ROOT / SPORT / f"real_{FIT_SEASON}.jsonl")
    ev = V4Evaluator(FIT_SEASON, 10 if SMOKE else R.DESCENT_SEEDS, args.workers,
                     out / f"descent_s{10 if SMOKE else R.DESCENT_SEEDS}.jsonl", fit_select(meta))
    log = (out / "descent_log.jsonl").open("a", encoding="utf-8")
    try:
        prod, games, terc, real_m, se, tier, conf = _setup(ev, real, meta)
        print(f"[v4] FIT games {len(games)} (early P4-vs-G5 {len(tier)}, early conference {len(conf)}), {R.DESCENT_SEEDS} seeds")

        last_z: Dict[str, Dict[str, float]] = {}

        def score(ov: Dict[str, Any], label: str) -> float:
            obj, z, m = full_objective(ev.run(ov), games, terc, real, real_m, se, tier, conf)
            last_z[R._key(ov)] = z
            ok = feasible(z)
            log.write(json.dumps({"label": label, "overrides": ov, "objective": obj, "z": z, "moments": m,
                                  "feasible_b": ok}) + "\n")
            log.flush()
            print(f"  {label:58} obj {obj:9.2f} {'' if ok else '[violates b]'}  "
                  + " ".join(f"{k}={v:+.1f}" for k, v in z.items() if abs(v) >= 2), flush=True)
            return obj

        prod_z: Dict[str, float] = {}

        def feasible(z: Dict[str, float]) -> bool:
            """v4.1: gate (b) on FIT -- no moment's abs z more than 1.0 above production's. Always true for v4."""
            if VARIANT != "v41" or not prod_z:
                return True
            return all(abs(z[k]) - abs(prod_z.get(k, 0.0)) <= 1.0 for k in z)

        prod_obj = score({}, "PRODUCTION")
        prod_z.update(last_z[R._key({})])
        if VARIANT == "v41":
            cur = dict(V41_START)
            cur_obj = score(cur, "v4.1 start: production + tier offset 3 / decay 8")
            if not feasible(last_z[R._key(cur)]):
                print("  start violates the (b) constraint -> starting from production")
                cur, cur_obj = {}, prod_obj
        else:
            v3 = json.loads((F.OUT_ROOT / SPORT / "refit_v3" / "descent_result.json").read_text(encoding="utf-8"))["overrides"]
            cur = dict(v3)
            cur_obj = score(cur, "v3 fitted (start point)")
        R.SWITCH_BASE = {}  # v4 levers below; switches stay as v3 chose
        g = dict(R.grids(SPORT))
        g.update({k: list(v) for k, v in GRIDS_V4.items()})
        if VARIANT == "v41":
            g["drive_success_offense_sensitivity"] = [0.45, 0.6, 0.8, 1.0, 1.2]   # floor raised (v4.1)
            g["non_offensive_scoring"] = [False, True]
        if SMOKE:
            g = {k: [v[0], v[-1]] for k, v in g.items()}
        order = (["non_offensive_scoring"] if VARIANT == "v41" else []) + list(GRIDS_V4) + list(R.LEVER_ORDER)
        # the LATEST-week early tier game: at week 3 the decay factor is 1 for every K, so a week-3 probe
        # would wrongly report tier_decay_weeks as unreachable (it did, in the smoke run)
        tier_tasks = sorted((t for t in ev._tasks(None) if str(t["game_id"]) in set(tier)), key=lambda t: -int(t["week"]))
        one = tier_tasks[:1] or ev._tasks(None)[:1]

        def reachable(lever: str) -> bool:
            base = dict(cur)
            if lever == "tier_decay_weeks":
                base["tier_offset"] = 3.0          # decay only acts on a non-zero offset
            lo = dict(base, **{lever: g[lever][0]})
            hi = dict(base, **{lever: g[lever][-1]})
            res = []
            for o in (lo, hi):
                src = next(t for t in ev._tasks(o.get("blend_k")) if t["game_id"] == one[0]["game_id"])
                t = dict(apply_input_levers(src, o, ev.p4), overrides=profile_part(o), overrides_key="reach_" + R._key(o))
                res.append(ev.pool.submit(R._task, t).result())
            return not (res[0]["total_mean"] == res[1]["total_mean"] and res[0]["margin_mean"] == res[1]["margin_mean"])

        live = []
        for lever in order:
            if lever not in g:
                continue
            if reachable(lever):
                live.append(lever)
            else:
                print(f"  DROPPED (unreachable): {lever}")
                log.write(json.dumps({"label": "dropped_unreachable", "lever": lever}) + "\n")
        for pass_no in (1, 2):
            for lever in live:
                base_v = cur.get(lever, DEFAULTS_V4.get(lever, getattr(R._shipped(SPORT), lever, None)))
                best_v, best_obj = base_v, cur_obj
                for v in g[lever]:
                    if v == base_v:
                        continue
                    ov = dict(cur, **{lever: v})
                    if v is False:
                        ov.pop(lever)                   # an OFF switch is written as absent
                    o = score(ov, f"pass {pass_no} {lever}={v}")
                    if o < best_obj - 1e-9 and feasible(last_z[R._key(ov)]):
                        best_v, best_obj = v, o
                if best_obj < cur_obj:
                    cur[lever], cur_obj = best_v, best_obj
                    if cur[lever] is False:
                        cur.pop(lever)
                    print(f"  -> keep {lever}={best_v}  obj {cur_obj:.2f}", flush=True)
        result = {"sport": SPORT, "version": VARIANT, "feasible_b_on_fit": feasible(last_z.get(R._key(cur), {})), "production_objective": prod_obj, "fitted_objective": cur_obj,
                  "overrides": cur, "games": len(games), "early_tier_games": len(tier), "early_conf_games": len(conf)}
        (out / "descent_result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"\n[v4] production obj {prod_obj:.2f} -> fitted obj {cur_obj:.2f} (ratio {cur_obj / prod_obj:.3f})\n  {cur}")
    finally:
        log.close()
        ev.close()


# ---------------------------------------------------------------------------
# validation (held-out NCAAF 2026; read ONCE; >= 300 FBS-vs-FBS games, weeks 3+)
# ---------------------------------------------------------------------------

def cfbd_close(season: int) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
    """{game_id: (market home margin, total)} from cached CFBD /lines weeks (production's convention:
    market margin = -spread). Reads `FOOTBALL_SCENARIO_NCAAF_LINES_DIR` when set (a private 2026 pull),
    else the primary checkout's data/ncaaf_source/data."""
    from scripts import backtest_ncaaf_lines_props as H
    base = Path(os.environ.get("FOOTBALL_SCENARIO_NCAAF_LINES_DIR")
                or r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\ncaaf_source\data")
    out = {}
    for path in sorted(base.glob("cfbd_lines_wk*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            if isinstance(row, dict) and int(row.get("season") or 0) == season:
                book = H.cfbd_book(row)
                if book:
                    out[str(row["id"])] = (-book["spread"] if book.get("spread") is not None else None, book.get("total"))
    return out


def cmd_validate(args) -> None:
    season = args.season
    if not os.environ.get("FOOTBALL_SCENARIO_READ_VALIDATION"):
        raise SystemExit(f"{season} is VALIDATION; set FOOTBALL_SCENARIO_READ_VALIDATION=1 to read it (once)")
    out = F.OUT_ROOT / SPORT / OUT_DIR
    marker = out / f"VALIDATION_READ_{season}"
    if marker.exists() and not args.resume:
        raise SystemExit(f"{season} already read: {marker.read_text().strip()}")
    cand = json.loads((out / "descent_result.json").read_text(encoding="utf-8"))["overrides"]
    real_g = F.real_ncaaf([season])
    real = {}
    for gid, g in real_g.items():
        rec = {"game_id": gid, "c_home": {}, "c_away": {}, "total": g["total"], "margin": g["margin"]}
        for side in ("home", "away"):
            mine = [d for d in g["drives"] if d.side == side]
            for d in mine:
                F.add_drive(rec[f"c_{side}"], d, SPORT)
            F.add_team_game(rec[f"c_{side}"], mine)
        real[gid] = rec
    meta = _meta(season)
    ev = V4Evaluator(season, R.FINAL_SEEDS, args.workers, out / f"validation_{season}_s{R.FINAL_SEEDS}.jsonl",
                     lambda tasks: {str(t["game_id"]) for t in tasks})
    if len(ev.ids) < 300:
        ev.close()
        raise SystemExit(f"only {len(ev.ids)} completed {season} FBS games (wk3+); pre-registered >= 300 -- nothing read")
    marker.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} candidate={cand}", encoding="utf-8")
    try:
        prod, games, terc, real_m, se, tier, conf = _setup(ev, real, meta)
        cs = ev.run(cand)
    finally:
        ev.close()
    p_obj, p_z, _ = full_objective(prod, games, terc, real, real_m, se, tier, conf)
    c_obj, c_z, _ = full_objective(cs, games, terc, real, real_m, se, tier, conf)
    gates = {"a_objective_20pct_lower": (c_obj <= 0.8 * p_obj, f"prod {p_obj:.2f} cand {c_obj:.2f}")}
    worst = max(abs(c_z[k]) - abs(p_z[k]) for k in c_z)
    gates["b_no_moment_z_grows_gt_1"] = (worst <= 1.0, f"worst abs z growth {worst:+.2f}")
    for name, fn, tol in (
        ("c_margin_mae", lambda s, g: abs(real[g]["margin"] - s[g]["margin_mean"]), 0.15),
        ("d_total_mae", lambda s, g: abs(real[g]["total"] - s[g]["total_mean"]), 0.15),
        ("e_home_win_brier", lambda s, g: (s[g]["home_win_rate"] - (1.0 if real[g]["margin"] > 0 else 0.0)) ** 2, 0.003),
    ):
        keep = [g for g in games if not (name.startswith("e_") and real[g]["margin"] == 0)]
        m, lo, hi = R._paired([fn(cs, g) - fn(prod, g) for g in keep])
        gates[name] = (hi < tol, f"delta {m:+.4f} [{lo:+.4f}, {hi:+.4f}] n={len(keep)}")
    close = cfbd_close(season)
    for name, idx, key in (("f_close_margin", 0, "margin_mean"), ("f_close_total", 1, "total_mean")):
        keep = [g for g in games if close.get(g) and close[g][idx] is not None]
        if len(keep) < 50:
            gates[name] = (False, f"only {len(keep)} games with a {season} CFBD close -- cannot pass")
            continue
        m, lo, hi = R._paired([abs(cs[g][key] - close[g][idx]) - abs(prod[g][key] - close[g][idx]) for g in keep])
        gates[name] = (hi < 0.15, f"delta {m:+.3f} [{lo:+.3f}, {hi:+.3f}] n={len(keep)}")
    report = {"season": season, "games": len(games), "candidate": cand,
              "gates": {k: {"pass": v[0], "detail": v[1]} for k, v in gates.items()},
              "PASS": all(v[0] for v in gates.values()), "z_production": p_z, "z_candidate": c_z}
    (out / f"validation_report_{season}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n[v4] VALIDATION {season}, {len(games)} games")
    for k, (ok, detail) in gates.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {k:28} {detail}")


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("descent", "validate"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--variant", choices=("v4", "v41"), default="v4")
    args = ap.parse_args(argv)
    global SMOKE, VARIANT, OUT_DIR
    SMOKE = args.smoke
    VARIANT = args.variant
    if VARIANT == "v41":
        OUT_DIR = "refit_v41"
    F.idle_self()   # fleet shares this machine
    {"descent": cmd_descent, "validate": cmd_validate}[args.cmd](args)


if __name__ == "__main__":
    main()
