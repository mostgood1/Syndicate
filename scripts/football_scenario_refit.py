"""Joint re-fit of the smartsim2 football profiles with the four scenario switches ON.

Lane `football-scenario-calibration`. Design, levers, moments and the 2025 gates were
PRE-REGISTERED in `.syndicate/findings_2026-10-06_football_scenario_calibration.md`
("JOINT RE-FIT") before this script existed; this file implements that text.

WHY. `halftime_kickoff`, `fourth_down_decision_model`, `non_offensive_scoring` and
`possession_aware_priors` each fix a measured defect, and each, switched on alone,
moved the scoring level or the home edge AWAY from the market: the profiles were
fitted with the defects present (`model_engine_standard.md` 4.4). So the switches
ship together with a re-fit of the rates that were absorbing them, or not at all.

WHAT IS FITTED. Production's own `build_projection` (env, ratings, shrink -- all
production's) over every 4th FIT game, with ONLY `CalibrationProfile` fields
overridden. Moments are the harness's counters (`football_scenario_rates`), so the
sim and the real games are counted by the same code. z = (sim - real) / SE_real,
SE_real from a game-clustered bootstrap; objective = sum z^2.

    py -3 scripts/football_scenario_refit.py descent  --sport nfl
    py -3 scripts/football_scenario_refit.py descent  --sport ncaaf
    FOOTBALL_SCENARIO_READ_VALIDATION=1 py -3 scripts/football_scenario_refit.py validate --sport nfl

`validate` reads 2025 ONCE per sport (a marker file refuses a second read) and
writes a CANDIDATE profile artifact outside `data/` when every gate passes.
Promotion to the fleet is a separate decision; this script promotes nothing.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import football_scenario_rates as F  # noqa: E402

SWITCHES = {"halftime_kickoff": True, "fourth_down_decision_model": True,
            "non_offensive_scoring": True, "possession_aware_priors": True}
FIT_SEASONS = {"nfl": [2023, 2024], "ncaaf": [2024]}
# v2 (pre-registered bc646508): NFL 2025 was spent by v1; NFL validates on 2026.
VALIDATION_SEASON = 2025
VALIDATION_SEASONS = {"nfl": 2026, "ncaaf": 2025}
MIN_VALIDATION_GAMES = {"nfl": 128, "ncaaf": 1}
OUT_DIR = "refit_v2"
DESCENT_SEEDS = 60
SMOKE = False   # --smoke: 6 games, 10 seeds, 2 grid values, separate output dir
FINAL_SEEDS = 300
EVERY = 4

# Pre-registered grids. Multiplicative levers: shipped value x these factors.
MULT_FACTORS = (0.75, 0.875, 1.0, 1.125, 1.25)
# Amendment 2 (before the full run): `field_goal_attempt_base_probability` is
# unreachable with `fourth_down_decision_model` ON (the measured table replaces the
# FG ladder) -- the smoke run's reachability check dropped it -- so the FG-frequency
# lever is `field_goal_weight_multiplier` instead.
MULT_LEVERS = ("drive_yardage_multiplier", "touchdown_weight_multiplier",
               "red_zone_touchdown_weight_bonus", "field_goal_weight_multiplier",
               "red_zone_gain_stiffening")   # v2: drives that stall in the red zone kick
ABS_LEVERS = {"home_field_bonus": (0.0, 0.03, 0.06, 0.09, 0.12),
              # v2 amendment 1: widened -- v1 was OVER-dispersed and 0.6 was the floor
              "drive_success_offense_sensitivity": (0.3, 0.45, 0.6, 0.8, 1.0, 1.2),
              "drive_success_defense_sensitivity": (0.3, 0.45, 0.6, 0.8, 1.0, 1.2)}
LEVER_ORDER = ("home_field_bonus", "drive_yardage_multiplier", "touchdown_weight_multiplier",
               "red_zone_touchdown_weight_bonus", "field_goal_weight_multiplier",
               "drive_success_offense_sensitivity", "drive_success_defense_sensitivity",
               "red_zone_gain_stiffening")

MOMENTS = ("mean_total", "mean_margin", "total_sd_gap", "margin_sd_gap",
           "p_td", "p_fg", "p_punt", "p_to", "plays_per_drive", "drives_per_team_game", "p_td_rz",
           "ppd_weak", "ppd_strong",
           # v2: DISCRIMINATION. v1 lowered its objective by compressing team quality;
           # a slope of actual on projected above 1 is exactly that compression.
           "margin_slope", "total_slope")


# ---------------------------------------------------------------------------
# workers: ONE pool for the whole descent; the override travels with the task
# ---------------------------------------------------------------------------

_W: Dict[str, Any] = {}


def _init(sport: str, arg: str) -> None:
    if sport == "nfl":
        F._nfl_init(arg, {})
        _W["nfl_base"] = F._W["gen"].nfl_calibration_profile
    else:
        F._ncaaf_init(arg, {})
        _W["ncaaf_base"] = F._W["gen"].NCAAF_CALIBRATION_PROFILE
    _W["sport"] = sport


def _task(task: Dict[str, Any]) -> Dict[str, Any]:
    gen, ov = F._W["gen"], task.get("overrides") or {}
    if _W["sport"] == "nfl":
        base = _W["nfl_base"]
        gen.nfl_calibration_profile = (lambda: dataclasses.replace(base(), **ov)) if ov else base
    else:
        gen.NCAAF_CALIBRATION_PROFILE = dataclasses.replace(_W["ncaaf_base"], **ov) if ov else _W["ncaaf_base"]
    out = F.sim_task(task)
    out["overrides_key"] = task["overrides_key"]
    return out


def _key(ov: Dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(ov, sort_keys=True).encode()).hexdigest()[:12]


class Evaluator:
    def __init__(self, sport: str, seasons: List[int], seeds: int, workers: int, cache: Path, every: int = EVERY) -> None:
        self.sport, self.seeds, self.cache = sport, seeds, cache
        tasks = (F.nfl_tasks if sport == "nfl" else F.ncaaf_tasks)(seasons, seeds)
        self.tasks = tasks[::every] if every else tasks
        if SMOKE:
            self.tasks = self.tasks[:: max(1, len(self.tasks) // 6)][:6]
        arg = str(F.nfl_root()) if sport == "nfl" else str(F.ncaaf_work())
        self.pool = ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(sport, arg))
        self.done: Dict[str, Dict[str, dict]] = {}
        if cache.exists():
            for line in cache.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    self.done.setdefault(d["overrides_key"], {})[d["game_id"]] = d

    def run(self, ov: Dict[str, Any]) -> Dict[str, dict]:
        k = _key(ov)
        have = self.done.setdefault(k, {})
        todo = [dict(t, overrides=ov, overrides_key=k) for t in self.tasks if str(t["game_id"]) not in have]
        if todo:
            t0 = time.time()
            with self.cache.open("a", encoding="utf-8") as fh:
                for d in self.pool.map(_task, todo, chunksize=2):
                    fh.write(json.dumps(d) + "\n")
                    have[d["game_id"]] = d
            print(f"    [eval {k}] {len(todo)} games x {self.seeds} seeds in {(time.time() - t0) / 60:.1f} min", flush=True)
        return have

    def close(self) -> None:
        self.pool.shutdown()


# ---------------------------------------------------------------------------
# moments
# ---------------------------------------------------------------------------

def _terciles(sims: Dict[str, dict], games: List[str]) -> Dict[Tuple[str, str], str]:
    gaps = []
    for g in games:
        r = sims[g]["ratings"]
        gaps.append((g, "home", r["home_offense_rating"] - r["away_defense_rating"]))
        gaps.append((g, "away", r["away_offense_rating"] - r["home_defense_rating"]))
    v = sorted(x[2] for x in gaps)
    lo, hi = v[len(v) // 3], v[2 * len(v) // 3]
    return {(g, s): ("weak" if x < lo else ("mid" if x < hi else "strong")) for g, s, x in gaps}


def _sd(xs: List[float]) -> float:
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _slope(xs: List[float], ys: List[float]) -> float:
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx else float("nan")


def moments(src: Dict[str, dict], games: List[str], terc: Dict[Tuple[str, str], str],
            sims_for_game_level: Optional[Dict[str, dict]] = None, real: Optional[Dict[str, dict]] = None,
            is_real: bool = False) -> Dict[str, float]:
    """The pre-registered moments over `games`. For the REAL side, game-level means use
    actual scores; the SD-gap moments are defined on the SIM side against the real
    residuals and are 0 for the real side (their target)."""
    c: Dict[str, float] = {}
    tw: Dict[str, float] = {}
    ts: Dict[str, float] = {}
    for g in games:
        for side in ("home", "away"):
            d = src[g][f"c_{side}"]
            for k, v in d.items():
                c[k] = c.get(k, 0.0) + v
            t = terc[(g, side)]
            if t in ("weak", "strong"):
                bucket = tw if t == "weak" else ts
                bucket["pts"] = bucket.get("pts", 0.0) + d.get("pts", 0.0)
                bucket["drives"] = bucket.get("drives", 0.0) + d.get("drives", 0.0)
    out = {
        "p_td": c.get("res:TD", 0) / c["drives"], "p_fg": c.get("res:FG", 0) / c["drives"],
        "p_punt": c.get("res:PUNT", 0) / c["drives"], "p_to": c.get("res:TO", 0) / c["drives"],
        "plays_per_drive": c["plays"] / c["drives"], "drives_per_team_game": c["drives"] / c["team_games"],
        "p_td_rz": c.get("rz:td", 0) / max(1.0, c.get("rz:n", 0)),
        "ppd_weak": tw["pts"] / tw["drives"], "ppd_strong": ts["pts"] / ts["drives"],
    }
    if is_real:
        out["mean_total"] = sum(src[g]["total"] for g in games) / len(games)
        out["mean_margin"] = sum(src[g]["margin"] for g in games) / len(games)
        out["total_sd_gap"] = 0.0
        out["margin_sd_gap"] = 0.0
        out["margin_slope"] = 1.0
        out["total_slope"] = 1.0
    else:
        out["mean_total"] = sum(src[g]["total_mean"] for g in games) / len(games)
        out["mean_margin"] = sum(src[g]["margin_mean"] for g in games) / len(games)
        # predictive spread vs the realised spread of the residuals (calibrated -> 0)
        out["total_sd_gap"] = (sum(src[g]["total_stdev"] for g in games) / len(games)
                               - _sd([real[g]["total"] - src[g]["total_mean"] for g in games]))
        out["margin_sd_gap"] = (sum(src[g]["margin_stdev"] for g in games) / len(games)
                                - _sd([real[g]["margin"] - src[g]["margin_mean"] for g in games]))
        out["margin_slope"] = _slope([src[g]["margin_mean"] for g in games], [real[g]["margin"] for g in games])
        out["total_slope"] = _slope([src[g]["total_mean"] for g in games], [real[g]["total"] for g in games])
    return out


def real_se(real: Dict[str, dict], games: List[str], terc: Dict[Tuple[str, str], str],
            prod: Optional[Dict[str, dict]] = None, reps: int = 400, seed: int = 5) -> Dict[str, float]:
    rng = random.Random(seed)
    draws: Dict[str, List[float]] = {m: [] for m in MOMENTS}
    sd_t, sd_m = [], []
    sl_m, sl_t = [], []
    for _ in range(reps):
        sample = [games[rng.randrange(len(games))] for _ in games]
        # duplicate keys collapse in a dict, so resample by index into lists
        m = _moments_from_list(real, sample, terc)
        for k, v in m.items():
            draws[k].append(v)
        sd_t.append(_sd([real[g]["total"] for g in sample]))
        sd_m.append(_sd([real[g]["margin"] for g in sample]))
        if prod is not None:   # v2: slope SE with production's projections held fixed
            sl_m.append(_slope([prod[g]["margin_mean"] for g in sample], [real[g]["margin"] for g in sample]))
            sl_t.append(_slope([prod[g]["total_mean"] for g in sample], [real[g]["total"] for g in sample]))
    se = {k: _sd(v) for k, v in draws.items() if v}
    # the SD-gap moments: SE of a realised SD
    se["total_sd_gap"] = _sd(sd_t)
    se["margin_sd_gap"] = _sd(sd_m)
    if sl_m:
        se["margin_slope"] = _sd(sl_m)
        se["total_slope"] = _sd(sl_t)
    return se


def _moments_from_list(real: Dict[str, dict], sample: List[str], terc) -> Dict[str, float]:
    fake = {f"{g}#{i}": real[g] for i, g in enumerate(sample)}
    tf = {(f"{g}#{i}", s): terc[(g, s)] for i, g in enumerate(sample) for s in ("home", "away")}
    m = moments(fake, list(fake), tf, is_real=True)
    for k in ("total_sd_gap", "margin_sd_gap", "margin_slope", "total_slope"):
        m.pop(k)
    return m


def objective(sim_m: Dict[str, float], real_m: Dict[str, float], se: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
    z = {k: (sim_m[k] - real_m[k]) / se[k] for k in MOMENTS if se.get(k)}
    return sum(v * v for v in z.values()), z


# ---------------------------------------------------------------------------
# descent
# ---------------------------------------------------------------------------

def _shipped(sport: str):
    if sport == "nfl":
        from scripts import backtest_nfl_lines_props as H
        H.configure_env(F.nfl_root())        # the same env the workers resolve the profile under
        from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE as P
    else:
        F._ncaaf_env(F.ncaaf_prepare_work())
        from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE as P
    return P


def grids(sport: str) -> Dict[str, List[float]]:
    p = _shipped(sport)
    out: Dict[str, List[float]] = {}
    for lever in MULT_LEVERS:
        base = float(getattr(p, lever))
        out[lever] = sorted({round(base * f, 4) for f in MULT_FACTORS})
    for lever, grid in ABS_LEVERS.items():
        base = float(getattr(p, lever))
        out[lever] = sorted(set(grid) | {base})
    return out


def cmd_descent(args) -> None:
    sport = args.sport
    out = F.OUT_ROOT / sport / ("refit_v2_smoke" if SMOKE else OUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    real_all = F._load(F.OUT_ROOT / sport / f"real_{'-'.join(map(str, FIT_SEASONS[sport]))}.jsonl")
    ev = Evaluator(sport, FIT_SEASONS[sport], DESCENT_SEEDS, args.workers, out / f"descent_s{DESCENT_SEEDS}.jsonl")
    log = (out / "descent_log.jsonl").open("a", encoding="utf-8")
    try:
        prod = ev.run({})
        games = sorted(set(prod) & set(real_all))
        print(f"[{sport}] FIT games {len(ev.tasks)}, with real outcomes {len(games)}, {DESCENT_SEEDS} seeds")
        terc = _terciles(prod, games)
        real_m = moments(real_all, games, terc, is_real=True)
        se = real_se(real_all, games, terc, prod=prod)

        def score(ov: Dict[str, Any], label: str) -> float:
            sims = ev.run(ov)
            m = moments(sims, games, terc, real=real_all)
            obj, z = objective(m, real_m, se)
            rec = {"label": label, "overrides": ov, "objective": obj, "z": z, "moments": m}
            log.write(json.dumps(rec) + "\n")
            log.flush()
            print(f"  {label:58} obj {obj:9.2f}   " + " ".join(f"{k}={v:+.1f}" for k, v in z.items() if abs(v) >= 2))
            return obj

        prod_obj = score({}, "PRODUCTION (all switches OFF)")
        cur = dict(SWITCHES)
        cur_obj = score(cur, "switches ON, shipped levers")
        g = grids(sport)
        if SMOKE:
            g = {k: [v[0], v[-1]] for k, v in g.items()}
        # reachability before use (rule v2 in mlb-combined-calibration): one game, extreme value
        live: List[str] = []
        one = ev.tasks[:1]
        for lever in LEVER_ORDER:
            lo_ov = dict(cur, **{lever: g[lever][0]})
            hi_ov = dict(cur, **{lever: g[lever][-1]})
            a = _task_once(ev, one, lo_ov)
            b = _task_once(ev, one, hi_ov)
            if a["total_mean"] == b["total_mean"] and a["margin_mean"] == b["margin_mean"]:
                print(f"  DROPPED (unreachable): {lever}")
                log.write(json.dumps({"label": "dropped_unreachable", "lever": lever}) + "\n")
            else:
                live.append(lever)
        for pass_no in (1, 2):
            for lever in live:
                best_v, best_obj = cur.get(lever, getattr(_shipped(sport), lever)), cur_obj
                for v in g[lever]:
                    if v == cur.get(lever, getattr(_shipped(sport), lever)):
                        continue
                    o = score(dict(cur, **{lever: v}), f"pass {pass_no} {lever}={v}")
                    if o < best_obj - 1e-9:
                        best_v, best_obj = v, o
                if best_obj < cur_obj:
                    cur[lever] = best_v
                    cur_obj = best_obj
                    print(f"  -> keep {lever}={best_v}  obj {cur_obj:.2f}")
        # Amendment 2: a kept value on its grid's EDGE gets one step further, once.
        for lever in live:
            grid = g[lever]
            v = cur.get(lever)
            if v is None or v not in (grid[0], grid[-1]) or len(grid) < 2:
                continue
            if lever in MULT_LEVERS:
                step = 0.875 if v == grid[0] else 1.125
                nxt = round(v * step, 4)
            else:
                d = grid[1] - grid[0] if v == grid[0] else grid[-1] - grid[-2]
                nxt = round(v - d if v == grid[0] else v + d, 4)
            o = score(dict(cur, **{lever: nxt}), f"edge {lever}={nxt}")
            if o < cur_obj - 1e-9:
                cur[lever], cur_obj = nxt, o
                print(f"  -> keep {lever}={nxt} (edge step)  obj {cur_obj:.2f}")
        result = {"sport": sport, "production_objective": prod_obj, "fitted_objective": cur_obj,
                  "overrides": cur, "real_moments": real_m, "se": se, "games": len(games),
                  "seeds": DESCENT_SEEDS, "every": EVERY}
        (out / "descent_result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"\n[{sport}] production obj {prod_obj:.2f} -> fitted obj {cur_obj:.2f}\n  {cur}")
    finally:
        log.close()
        ev.close()


def _task_once(ev: Evaluator, tasks: List[dict], ov: Dict[str, Any]) -> dict:
    t = dict(tasks[0], overrides=ov, overrides_key="reach_" + _key(ov))
    return ev.pool.submit(_task, t).result()


# ---------------------------------------------------------------------------
# validation: 2025, ONCE per sport
# ---------------------------------------------------------------------------

def _paired(deltas: List[float]) -> Tuple[float, float, float]:
    return F._paired_ci(deltas)


def cmd_validate(args) -> None:
    sport = args.sport
    if not os.environ.get("FOOTBALL_SCENARIO_READ_VALIDATION"):
        raise SystemExit("2025 is VALIDATION; set FOOTBALL_SCENARIO_READ_VALIDATION=1 to read it (once)")
    out = F.OUT_ROOT / sport / OUT_DIR
    season = VALIDATION_SEASONS[sport]
    marker = out / f"VALIDATION_READ_{season}"
    if marker.exists() and not args.resume:
        raise SystemExit(f"2025 was already read for {sport} ({marker.read_text().strip()}); it is read ONCE")
    fit = json.loads((out / "descent_result.json").read_text(encoding="utf-8"))
    cand = fit["overrides"]
    marker.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} candidate={cand}", encoding="utf-8")
    if sport == "nfl":
        real = F.real_nfl([season])
        close = {g: (r["close_spread"], r["close_total"]) for g, r in real.items()}
    else:
        if not (F.ncaaf_work() / "cache" / "ppa_games_2025_wk01.json").exists():
            import shutil
            for p in Path(r"C:\tmp\ncaaf_lpb\cache").glob("ppa_games_2025_wk*.json"):
                shutil.copy2(p, F.ncaaf_work() / "cache" / p.name)
        real = F.real_ncaaf([season])
        from scripts import backtest_ncaaf_lines_props as H
        lines = H.load_cfbd_lines_2025()
        close = {str(g): (-b["spread"] if b.get("spread") is not None else None, b.get("total")) for g, b in lines.items()}
    real_rec = {}
    for gid, g in real.items():
        rec = {"game_id": gid, "c_home": {}, "c_away": {}, "total": g["total"], "margin": g["margin"]}
        for side in ("home", "away"):
            mine = [d for d in g["drives"] if d.side == side]
            for d in mine:
                F.add_drive(rec[f"c_{side}"], d, sport)
            F.add_team_game(rec[f"c_{side}"], mine)
        real_rec[gid] = rec
    # Amendment 3: VALIDATION scores EVERY 2025 game. The every-4th subset is a
    # descent cost-saving; reusing it here would have graded on ~68 NFL games.
    ev = Evaluator(sport, [season], FINAL_SEEDS, args.workers, out / f"validation_{season}_s{FINAL_SEEDS}.jsonl",
                   every=1)
    if len(ev.tasks) < MIN_VALIDATION_GAMES[sport]:
        ev.close()
        marker.unlink()
        raise SystemExit(f"only {len(ev.tasks)} completed {season} games; v2 pre-registered >= "
                         f"{MIN_VALIDATION_GAMES[sport]} before reading -- nothing read")
    try:
        prod = ev.run({})
        candd = ev.run(cand)
    finally:
        ev.close()
    games = sorted(set(prod) & set(candd) & set(real_rec))
    terc = _terciles(prod, games)
    real_m = moments(real_rec, games, terc, is_real=True)
    se = real_se(real_rec, games, terc, prod=prod)
    p_obj, p_z = objective(moments(prod, games, terc, real=real_rec), real_m, se)
    c_obj, c_z = objective(moments(candd, games, terc, real=real_rec), real_m, se)
    gates = {}
    gates["a_objective_20pct_lower"] = (c_obj <= 0.8 * p_obj, f"prod {p_obj:.2f} cand {c_obj:.2f}")
    worst = max(abs(c_z[k]) - abs(p_z[k]) for k in c_z)
    gates["b_no_moment_z_grows_gt_1"] = (worst <= 1.0, f"worst |z| growth {worst:+.2f}")
    for name, fn, tol in (
        ("c_margin_mae", lambda s, g: abs(real_rec[g]["margin"] - s[g]["margin_mean"]), 0.15),
        ("d_total_mae", lambda s, g: abs(real_rec[g]["total"] - s[g]["total_mean"]), 0.15),
        ("e_home_win_brier", lambda s, g: (s[g]["home_win_rate"] - (1.0 if real_rec[g]["margin"] > 0 else 0.0)) ** 2, 0.003),
    ):
        keep = [g for g in games if not (name.startswith("e_") and real_rec[g]["margin"] == 0)]
        m, lo, hi = _paired([fn(candd, g) - fn(prod, g) for g in keep])
        gates[name] = (hi < tol, f"delta {m:+.4f} [{lo:+.4f}, {hi:+.4f}] n={len(keep)}")
    for name, idx, key in (("f_close_margin", 0, "margin_mean"), ("f_close_total", 1, "total_mean")):
        keep = [g for g in games if close.get(g) and close[g][idx] is not None]
        if len(keep) < 50:
            gates[name] = (False, f"only {len(keep)} games with a close -- cannot pass")
            continue
        m, lo, hi = _paired([abs(candd[g][key] - close[g][idx]) - abs(prod[g][key] - close[g][idx]) for g in keep])
        gates[name] = (hi < 0.15, f"delta {m:+.3f} [{lo:+.3f}, {hi:+.3f}] n={len(keep)}")
    passed = all(v[0] for v in gates.values())
    report = {"sport": sport, "season": season, "games": len(games), "seeds": FINAL_SEEDS,
              "candidate": cand, "gates": {k: {"pass": v[0], "detail": v[1]} for k, v in gates.items()},
              "PASS": passed, "z_production": p_z, "z_candidate": c_z}
    (out / "validation_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n[{sport}] VALIDATION {season}, {len(games)} games, {FINAL_SEEDS} seeds")
    for k, (ok, detail) in gates.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {k:28} {detail}")
    print(f"  => {'ALL GATES PASS' if passed else 'NOT SHIPPABLE'}")
    if passed:
        from syndicate.features.shared.calibration_profile_store import save_versioned_profile
        prof = dataclasses.replace(_shipped(sport), **cand)
        path = save_versioned_profile(prof, artifact_path=out / f"{sport}_candidate_profile.json",
                                      version=f"{sport}-scenario-refit-2",
                                      fit_from={"lane": "football-scenario-calibration", "fit": FIT_SEASONS[sport],
                                                "validation": season, "gates": report["gates"]})
        print(f"  candidate artifact (NOT promoted): {path}")


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("descent", "validate"))
    ap.add_argument("--sport", choices=("nfl", "ncaaf"), required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--resume", action="store_true", help="validate: finish an interrupted 2025 read")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args(argv)
    from scripts.football_scenario_rates import idle_self
    idle_self()   # fleet shares this machine
    if args.smoke:
        global SMOKE, DESCENT_SEEDS
        SMOKE, DESCENT_SEEDS = True, 10
    {"descent": cmd_descent, "validate": cmd_validate}[args.cmd](args)


if __name__ == "__main__":
    main()
