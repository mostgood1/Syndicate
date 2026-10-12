"""Fit the engine's NCAAB bonus foul rate (`EventSimConfig.bonus_nonshoot_foul_per_poss`) to 2025-26.

Lane `ncaab-native-live-tier` (user 2026-10-12: "build the bonus free throw mechanism"). The mechanism is
a MECHANISM, so its rate is FITTED, not guessed (model engine standard, mechanism vs estimator), against
what the corpus measured for the regular season (5,865 games, both teams per game):

    second half minus first half points  +7.7    (FT points +6.9 of it)
    FTA per game                          39.9    (15.3 first half, 24.6 second)
    personal fouls per game               34.2    (14.5 / 19.7)

For each candidate rate, every sampled game is simulated PREGAME (tip) from its walk-forward inputs
(`ncaab_live_resim_backtest.build_tasks`, the same builder the backtest uses), and the engine's mean
per-half points, FTA and PF are compared with those targets. Read-only; writes one JSON report.

    py -3 scripts/fit_ncaab_bonus_rate.py --games 40 --sims 20 --rates 0,0.04,0.08,0.12,0.16 --out fit.json
Run at Idle priority -- the fleet shares this machine.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import random
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TARGETS = {"h2_minus_h1": 7.7, "fta_per_game": 39.9, "pf_per_game": 34.2}
# P3's end-game intentional-foul fields (engine.py, default off), set from NCAAB's OWN measurement
# (ncaab_live_tier.md): in the last 2:00 the trailing team fouls 0.99 / 1.46 / 1.64 per minute down 1-3 / 4-6 /
# 7-10 against ~0.6 for the leader; at ~1.7 defensive possessions a minute that is ~0.25 / 0.5 / 0.6 extra per
# possession. A starting point the sweep keeps or drops, not a fit.
ENDGAME = {"endgame_foul_window_s": 120, "endgame_foul_max_deficit": 10, "endgame_foul_p_by_deficit": (0.25, 0.5, 0.6)}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def run_one(job: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    from syndicate.features.basketball_engine import league_params, simulate_pbp_game_boxscore
    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.ncaab import live_team_model as tm

    task, rate, sims = job["task"], float(job["rate"]), int(job["sims"])
    h2m, endgame = float(job.get("h2_mult", 1.0)), bool(job.get("endgame"))
    rec = task["record"]
    prior = tm.NcaabGamePrior(**{**task["prior"], "ratings_as_of": dt.date.fromisoformat(task["prior"]["ratings_as_of"])})
    priors = lr.PlayerPriors(season=rec["season"], as_of=dt.date.fromisoformat(rec["date"]), source="walk_forward",
                             by_team=task["player_priors"])
    inputs = lr.build_engine_inputs(rec["date"], rec["home"]["id"], rec["away"]["id"], neutral=rec["neutral"],
                                    priors=priors, team_prior=prior)
    if isinstance(inputs, lr.NcaabResimRefusal):
        return {"rate": rate, "refused": inputs.reason}
    cfg = inputs["cfg"]
    if rate > 0:
        cfg = replace(cfg, bonus_free_throws=True, bonus_nonshoot_foul_per_poss=rate, bonus_second_half_mult=h2m)
    if endgame:
        cfg = replace(cfg, **ENDGAME)
    kw = {k: inputs[k] for k in ("home_players", "away_players", "target_home_points", "target_away_points")}
    out = {"rate": rate, "h2_mult": h2m, "endgame": endgame, "h1": [], "h2": [], "fta": [], "pf": [], "total": []}
    for s in range(sims):
        hb, ab, hq, aq = simulate_pbp_game_boxscore(rng=np.random.default_rng(1000 + s), cfg=cfg,
                                                    league=league_params("ncaab"), **kw)
        out["h1"].append(hq[0] + aq[0])
        out["h2"].append(hq[1] + aq[1])
        out["total"].append(sum(hq) + sum(aq))
        out["fta"].append(sum(int(p.get("fta") or 0) for p in hb["players"] + ab["players"]))
        out["pf"].append(sum(int(p.get("pf") or 0) for p in hb["players"] + ab["players"]))
    out = {k: (statistics.fmean(v) if isinstance(v, list) else v) for k, v in out.items()}
    out["final_total"] = rec["home"]["score"] + rec["away"]["score"]
    out["prior_total"] = prior.total
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--sims", type=int, default=20)
    ap.add_argument("--rates", default="0,0.04,0.08,0.12,0.16")
    ap.add_argument("--h2-mults", default="1.0")
    ap.add_argument("--endgame", default="0", help="comma list of 0/1: run each combination without/with ENDGAME")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261012)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    bt = _load("ncaab_live_resim_backtest")
    tasks, _skipped = bt.build_tasks(args.season, regular_sample=args.games * 3, sims=args.sims, seed=args.seed, min_games=5)
    regular = [t for t in tasks if t["record"]["phase"] == "regular"]
    random.Random(args.seed).shuffle(regular)
    regular = regular[: args.games]
    rates = [float(x) for x in args.rates.split(",")]
    mults = [float(x) for x in args.h2_mults.split(",")]
    endgames = [x.strip() == "1" for x in args.endgame.split(",")]
    combos = [(r, m, e) for r in rates for m in mults for e in endgames]
    jobs = [{"task": t, "rate": r, "h2_mult": m, "endgame": e, "sims": args.sims} for r, m, e in combos for t in regular]
    from multiprocessing import Pool

    with Pool(processes=max(1, args.workers)) as pool:
        results = pool.map(run_one, jobs, chunksize=1)
    report: dict[str, Any] = {"games": len(regular), "sims": args.sims, "targets": TARGETS, "substrate": "LOCAL corpus + player box, walk-forward", "by_rate": {}}
    for r, mm, eg in combos:
        rows = [x for x in results if (x["rate"], x.get("h2_mult"), x.get("endgame")) == (r, mm, eg) and "refused" not in x]
        if not rows:
            continue
        m = lambda k: statistics.fmean(x[k] for x in rows)  # noqa: E731
        key = f"rate={r} h2_mult={mm} endgame={int(eg)}"
        report["by_rate"][key] = {
            "n": len(rows), "h1": round(m("h1"), 2), "h2": round(m("h2"), 2), "h2_minus_h1": round(m("h2") - m("h1"), 2),
            "fta_per_game": round(m("fta"), 2), "pf_per_game": round(m("pf"), 2),
            "total_minus_final": round(m("total") - m("final_total"), 2), "total_minus_prior": round(m("total") - m("prior_total"), 2),
        }
        print(key, report["by_rate"][key], flush=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
