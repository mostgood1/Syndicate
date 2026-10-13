"""Pregame published-total bias for NBA, A/B over recorded as-of engine-input sets (todo #695).

Runs the PRODUCTION engine object (`live_resim.resim_live_game` with `game_state=None`, i.e. from the tip) on each
game's recorded pregame engine inputs, once per arm, same seed per game in every arm. Reports, per arm and
population (regular / postseason kept apart): sim total minus actual final (bias, MAE), sim total minus the pre-tip
market total, and the PAIRED arm difference with a game bootstrap CI.

The arms differ only in what was recorded (e.g. `record_nba_engine_inputs_asof.py --no-total-inputs` = the
skip_def_subtraction OFF path). Process env decides the rest exactly as on the fleet (SYNDICATE_NBA_TEAM_INPUTS
absent = on); this script sets nothing.

    python scripts/nba_pregame_total_bias.py run --arm on=<inputs_root> --arm off=<inputs_root> \\
        --games games.jsonl --lines-cache <oddsapi games dir> --sims 200 --shard 0/3 --out <dir>
    python scripts/nba_pregame_total_bias.py summarize --out <dir>
"""
from __future__ import annotations

import argparse
import json
import pickle
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import basketball_live_checkpoint_backtest as bt  # noqa: E402


def _rows_path(out: Path, shard: str) -> Path:
    return out / f"rows_{shard.replace('/', 'of')}.jsonl"


def run(args: argparse.Namespace) -> int:
    from syndicate.features.nba import live_resim as lr

    arms = dict(a.split("=", 1) for a in args.arm)
    index = {k: bt.index_engine_inputs(Path(v)) for k, v in arms.items()}
    lines = bt.load_pregame_lines(Path(args.lines_cache)) if args.lines_cache else {}
    games = [g for g in bt.load_games(Path(args.games)) if g.population in set(args.population)]
    i, n = (int(x) for x in args.shard.split("/"))
    games = [g for k, g in enumerate(games) if k % n == i]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = _rows_path(out, args.shard)
    done = set()
    if path.exists():
        done = {json.loads(ln)["event_id"] for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    with path.open("a", encoding="utf-8") as fh:
        for g in games:
            if g.event_id in done:
                continue
            key = (g.date, bt.ESPN_TO_TRI.get(g.home, g.home), bt.ESPN_TO_TRI.get(g.away, g.away))
            paths = {arm: idx.get(key) for arm, idx in index.items()}
            if any(p is None for p in paths.values()):
                continue  # paired only: a game missing from any arm is out of every arm
            pre = bt.pregame_for(g, lines, {})
            row: Dict[str, Any] = {"event_id": g.event_id, "date": g.date, "home": g.home, "away": g.away,
                                   "population": g.population, "actual_total": g.final_home + g.final_away,
                                   "actual_margin": g.final_home - g.final_away, "market_total": pre.total,
                                   "market_spread_home": pre.spread_home, "line_source": pre.source, "arms": {}}
            seed = lr.stable_seed(g.event_id, -1)
            for arm, p in paths.items():
                with p.open("rb") as f:
                    inputs = dict(pickle.load(f)["kwargs"])
                res = lr.resim_live_game(inputs, None, sims=args.sims, base_seed=seed)
                if isinstance(res, lr.NbaResimRefusal):
                    row["arms"][arm] = {"refusal": res.reason}
                else:
                    row["arms"][arm] = {"total": res["total_mean"], "margin": res["home_margin_mean"],
                                        "p_home": res["home_win_prob"], "sims": res["sims_run"]}
            fh.write(json.dumps(row) + "\n")
            fh.flush()
    print(f"PREGAME_BIAS_SHARD_DONE shard={args.shard}", flush=True)
    return 0


def _ci(diffs: List[float]) -> str:
    if len(diffs) < 2:
        return "n/a"
    m, lo, hi = bt.paired_bootstrap(diffs)
    return f"{m:+.2f} [{lo:+.2f}, {hi:+.2f}]"


def summarize(args: argparse.Namespace) -> int:
    out = Path(args.out)
    rows = [json.loads(ln) for f in sorted(out.glob("rows_*.jsonl"))
            for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    arms = sorted({a for r in rows for a in r["arms"]})
    report: Dict[str, Any] = {"n_rows": len(rows), "arms": arms, "cells": []}
    for pop in sorted({r["population"] for r in rows}):
        rs = [r for r in rows if r["population"] == pop and all("total" in r["arms"].get(a, {}) for a in arms)]
        mk = [r for r in rs if r["market_total"] is not None]
        print(f"===== {pop}  n={len(rs)} (with market total {len(mk)})")
        for a in arms:
            bias = [r["arms"][a]["total"] - r["actual_total"] for r in rs]
            vs_mkt = [r["arms"][a]["total"] - r["market_total"] for r in mk]
            mbias = [r["arms"][a]["margin"] - r["actual_margin"] for r in rs]
            cell = {"population": pop, "arm": a, "n": len(rs), "total_bias_vs_actual": statistics.fmean(bias),
                    "total_mae": statistics.fmean(abs(x) for x in bias), "n_market": len(mk),
                    "total_minus_market": statistics.fmean(vs_mkt) if vs_mkt else None,
                    "margin_bias": statistics.fmean(mbias), "margin_mae": statistics.fmean(abs(x) for x in mbias)}
            report["cells"].append(cell)
            print(f"  {a:6s} total bias vs actual {cell['total_bias_vs_actual']:+.2f}  MAE {cell['total_mae']:.2f}  "
                  f"minus market {cell['total_minus_market'] if cell['total_minus_market'] is None else round(cell['total_minus_market'], 2):}  "
                  f"| margin bias {cell['margin_bias']:+.2f} MAE {cell['margin_mae']:.2f}")
        if mk:
            mkt_bias = [r["market_total"] - r["actual_total"] for r in mk]
            mkt_mae = statistics.fmean(abs(x) for x in mkt_bias)
            print(f"  market total bias vs actual {statistics.fmean(mkt_bias):+.2f}  MAE {mkt_mae:.2f}")
        if len(arms) == 2:
            a, b = arms
            print(f"  paired {a}-{b}: total {_ci([r['arms'][a]['total'] - r['arms'][b]['total'] for r in rs])}; "
                  f"|err| {_ci([abs(r['arms'][a]['total'] - r['actual_total']) - abs(r['arms'][b]['total'] - r['actual_total']) for r in rs])}; "
                  f"margin |err| {_ci([abs(r['arms'][a]['margin'] - r['actual_margin']) - abs(r['arms'][b]['margin'] - r['actual_margin']) for r in rs])}")
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--arm", action="append", required=True, help="label=<engine inputs root>; repeat")
    r.add_argument("--games", required=True)
    r.add_argument("--lines-cache")
    r.add_argument("--population", action="append", default=None)
    r.add_argument("--sims", type=int, default=200)
    r.add_argument("--shard", default="0/1")
    r.add_argument("--out", required=True)
    s = sub.add_parser("summarize")
    s.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        args.population = args.population or ["regular", "postseason"]
        return run(args)
    return summarize(args)


if __name__ == "__main__":
    raise SystemExit(main())
