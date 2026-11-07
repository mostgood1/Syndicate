"""Does a second college re-sim loop slow the first one down? Time the REAL engine, alone vs. shared.

Lane `ncaab-live-resim-capacity` (todo #762, the NCAAB budget-loop item). The men's and women's live
re-sim loops are two `threading.Thread`s in ONE live-odds-worker process (`ncaab/live_resim._start_loop`).
If the possession engine is pure-Python CPU work, two threads share one GIL and each gets about half a
core; two PROCESSES each get a core. This measures exactly that, on the production engine
(`live_resim.resim_live_game`, NCAAB / WNCAAB `LeagueParams`), with synthetic priors so it needs no data:

    py -3 scripts/ncaab_resim_contention_probe.py --repeats 3
    py -3 scripts/ncaab_resim_contention_probe.py --state tip --json

Modes, each run `--repeats` times, interleaved (alone, threads, processes, alone, ...) so host load drifts
over all of them alike:

  alone      one NCAAB re-sim in this process.
  threads    the NCAAB re-sim and a WNCAAB re-sim at once, two threads in this process (production's shape).
  processes  the same two at once, each in its own process.

Per run it reports the NCAAB re-sim's wall seconds, its own thread CPU seconds (`time.thread_time`), and
`cpu_share` = cpu / wall. A GIL-bound pair shows `threads` wall ~2x `alone` with cpu_share ~0.5, and
`processes` back near `alone`. Run it at IDLE priority (the fleet shares this host's cores): PowerShell `Start-Process ... -PassThru`, then
`.PriorityClass = 'Idle'` (the `cmd /c start /low /b /wait` wrapper hung this script with 5 s of CPU, 2026-11-07).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import multiprocessing as mp
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATE = "2026-01-10"
_RATES = {"pts_pm": 0.42, "fga_pm": 0.33, "fgm_pm": 0.15, "threes_att_pm": 0.13, "threes_pm": 0.045, "fta_pm": 0.11,
          "ftm_pm": 0.08, "oreb_pm": 0.04, "dreb_pm": 0.1, "reb_pm": 0.14, "ast_pm": 0.07, "tov_pm": 0.055,
          "stl_pm": 0.03, "blk_pm": 0.015, "pf_pm": 0.075}
_MINUTES = [34, 32, 30, 28, 26, 20, 15, 10, 5, 2]


def _write_priors(directory: Path, n: int = 10) -> None:
    from syndicate.features.ncaab import live_resim as lr

    cols = ("season", "as_of", "team_id", "athlete_id", "player_name", "games", "minutes", "min_proj", "starter_prob",
            "last_game", "prior_season_minutes") + tuple(f"{k}_pm" for k in lr.RATE_STATS)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"player_priors_2026_asof_{DATE.replace('-', '')}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for team in ("10", "20"):
            for i in range(n):
                w.writerow({"season": 2026, "as_of": DATE, "team_id": team, "athlete_id": f"{team}{i}",
                            "player_name": f"P{team}_{i}", "games": 5, "minutes": 100, "min_proj": _MINUTES[i],
                            "starter_prob": 1.0 if i < 5 else 0.0, "last_game": DATE, "prior_season_minutes": 0,
                            **_RATES})


def _inputs(league: str, priors_dir: Path) -> dict[str, Any]:
    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.ncaab import live_team_model as tm

    prior = tm.NcaabGamePrior(home_id="10", away_id="20", neutral=False, possessions=68.0, home_ppp=1.08,
                              away_ppp=1.02, home_points=73.0, away_points=69.0, total=142.0, home_margin=4.0,
                              ratings_season=2026, ratings_as_of=dt.date(2026, 1, 9), prior_season_fallback=False,
                              home_games=10, away_games=10)
    pri = lr.load_player_priors(dt.date.fromisoformat(DATE), dirs=[priors_dir])
    out = lr.build_engine_inputs(DATE, "10", "20", neutral=False, priors=pri, team_prior=prior, league=league)
    if isinstance(out, lr.NcaabResimRefusal):
        raise SystemExit(f"inputs refused for {league}: {out}")
    return out


def _state(league: str, which: str):
    from syndicate.features.basketball_engine.resume import GameState

    if which == "tip":
        return GameState(period=1, seconds_remaining=None, home_period_pts=(0,), away_period_pts=(0,))
    # Half the game left: the men at halftime, the women at the start of Q3.
    if league == "wncaab":
        return GameState(period=3, seconds_remaining=600, home_period_pts=(18, 17, 0), away_period_pts=(16, 15, 0),
                         possession="home")
    return GameState(period=2, seconds_remaining=1200, home_period_pts=(36, 0), away_period_pts=(33, 0),
                     possession="home")


def _one(league: str, priors_dir: str, sims: int, which: str, seed: int = 7) -> dict[str, float]:
    """One re-sim through production's `resim_live_game`; wall + this thread's CPU seconds."""
    from syndicate.features.ncaab import live_resim as lr

    inputs = _inputs(league, Path(priors_dir))
    gs = _state(league, which)
    lr.ncaab_engine(league=league)  # bind the engine before the clock starts (a one-time cost in production too)
    w0, c0 = time.perf_counter(), time.thread_time()
    res = lr.resim_live_game(inputs, gs, sims=sims, base_seed=seed, league=league)
    wall, cpu = time.perf_counter() - w0, time.thread_time() - c0
    if isinstance(res, lr.NcaabResimRefusal):
        raise SystemExit(f"{league} re-sim refused: {res}")
    return {"wall": wall, "cpu": cpu, "sims": float(res["sims_run"])}


def _proc_target(q: Any, league: str, priors_dir: str, sims: int, which: str, barrier: Any) -> None:
    from syndicate.features.ncaab import live_resim as lr

    _inputs(league, Path(priors_dir))
    lr.ncaab_engine(league=league)
    barrier.wait()
    q.put((league, _one(league, priors_dir, sims, which)))


def run_alone(priors_dir: str, sims: int, which: str) -> dict[str, float]:
    return _one("ncaab", priors_dir, sims, which)


def run_threads(priors_dir: str, sims: int, which: str) -> dict[str, float]:
    out: dict[str, dict[str, float]] = {}
    barrier = threading.Barrier(2)

    def work(league: str) -> None:
        from syndicate.features.ncaab import live_resim as lr

        _inputs(league, Path(priors_dir))
        lr.ncaab_engine(league=league)
        barrier.wait()
        out[league] = _one(league, priors_dir, sims, which)

    ts = [threading.Thread(target=work, args=(lg,)) for lg in ("ncaab", "wncaab")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return {**out["ncaab"], "other_wall": out["wncaab"]["wall"]}


def run_processes(priors_dir: str, sims: int, which: str) -> dict[str, float]:
    ctx = mp.get_context("spawn")
    q, barrier = ctx.Queue(), ctx.Barrier(2)
    ps = [ctx.Process(target=_proc_target, args=(q, lg, priors_dir, sims, which, barrier)) for lg in ("ncaab", "wncaab")]
    for p in ps:
        p.start()
    got = dict(q.get() for _ in ps)
    for p in ps:
        p.join()
    return {**got["ncaab"], "other_wall": got["wncaab"]["wall"]}


MODES = {"alone": run_alone, "threads": run_threads, "processes": run_processes}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sims", type=int, default=100, help="draws per re-sim (production: 200; refusal floor 100)")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--state", choices=("half", "tip"), default="half")
    ap.add_argument("--modes", default="alone,threads,processes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    modes = [m for m in args.modes.split(",") if m]
    runs: dict[str, list[dict[str, float]]] = {m: [] for m in modes}
    with tempfile.TemporaryDirectory() as tmp:
        _write_priors(Path(tmp))
        run_alone(tmp, 100, args.state)  # warm imports and caches outside the measurement
        for _ in range(args.repeats):
            for m in modes:
                runs[m].append(MODES[m](tmp, args.sims, args.state))
    summary: dict[str, Any] = {"sims": args.sims, "state": args.state, "repeats": args.repeats, "modes": {}}
    base = statistics.median(r["wall"] for r in runs.get("alone") or [{"wall": float("nan")}])
    for m, rs in runs.items():
        wall = statistics.median(r["wall"] for r in rs)
        cpu = statistics.median(r["cpu"] for r in rs)
        summary["modes"][m] = {"wall_s": round(wall, 3), "cpu_s": round(cpu, 3), "cpu_share": round(cpu / wall, 3),
                               "ms_per_sim": round(1000 * wall / args.sims, 1), "slowdown_vs_alone": round(wall / base, 2),
                               "walls": [round(r["wall"], 3) for r in rs]}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"NCAAB re-sim, {args.sims} sims, state={args.state}, median of {args.repeats}")
        for m, s in summary["modes"].items():
            print(f"  {m:9s} wall {s['wall_s']:7.3f} s  cpu {s['cpu_s']:7.3f} s  cpu_share {s['cpu_share']:.2f}  "
                  f"{s['ms_per_sim']:6.1f} ms/sim  x{s['slowdown_vs_alone']:.2f}  walls={s['walls']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
