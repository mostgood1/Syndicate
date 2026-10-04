"""Fit the WNBA minutes re-share (lane `wnba-minutes-redistribution`) and test it out of sample.

Rows: every pool player in every REGULATION team-game of an as-of re-run archive (OT games skipped -- every team plays
exactly 200 minutes). Target: actual minutes (0 for a pool player who did not play). Feature `freed` comes from the
ENGINE's own `freed_minutes` over the processed root's `boxscores_history.csv` (strictly before the slate), so the fit
and production read the same signal through the same code. Fit: grid search over (b0, b1, leak) minimising minutes
SSE on dates < --split; report out-of-sample (dates >= --split) minutes MAE/bias overall, by rotation tier and by
`freed` band, each against the unmodified sim with a game-clustered bootstrap CI. A fitted value on a grid edge is
flagged -- widen the grid rather than trust it.

Usage (WSL): python scripts/fit_wnba_minutes_redistribution.py --archive ~/wnba_bt/oracle --processed ~/wnba_bt/stack/proc
             --espn-dir ... --box-dir ... --out ~/wnba_bt/redistribution_fit [--write-artifact <dir>]
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from syndicate.features.shared import wnba_sim_minutes_redistribution as R  # noqa: E402
from syndicate.features.shared.basketball_props_smart_sim import _norm_name_key  # noqa: E402


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


B = _load("bt_wnba", "backtest_wnba_lines_props.py")
AV = _load("fit_avail", "fit_wnba_sim_availability.py")

GRID_B0 = [round(-0.2 + 0.025 * i, 3) for i in range(25)]      # -0.2 .. 0.4
GRID_B1 = [round(-0.2 + 0.05 * i, 3) for i in range(21)]       # -0.2 .. 0.8
GRID_LEAK = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
FREED_BANDS = (("freed 0", 0.0, 0.001), ("freed < 15", 0.001, 15.0), ("freed >= 15", 15.0, 1e9))
TIERS = (("rank 1-5", 1, 5), ("rank 6-8", 6, 8), ("rank 9+", 9, 99))


def team_games(archive: Path, processed: Path, games: Dict, box_all: Dict) -> List[Dict]:
    idx = B._pair_index(games)
    out: List[Dict] = []
    for p in sorted(archive.glob("*/smart_sim_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        gid = B.match_game(idx, str(d.get("date")), str(d.get("home")).upper(), str(d.get("away")).upper())
        if not gid or gid not in box_all:
            continue
        g = games[gid]
        for side, team in (("home", g["home"]), ("away", g["away"])):
            actual = box_all[gid].get(team, {})
            if not actual or sum(actual.values()) > 201.0:
                continue
            names, sims = [], []
            for pl in (d.get("players") or {}).get(side) or []:
                try:
                    sims.append(float(pl.get("min_mean") or 0.0))
                except (TypeError, ValueError):
                    continue
                names.append(pl.get("player_name"))
            if not sims or sum(sims) < R.TOTAL / 2:
                continue
            pool = {str(_norm_name_key(n) or "").strip().upper() for n in names}
            freed, _why = R.freed_minutes(processed, str(d.get("date")), team, pool, _norm_name_key)
            ys = [actual.get(B.norm_name(n), 0.0) for n in names]
            order = sorted(range(len(sims)), key=lambda i: -sims[i])
            rank = {i: r + 1 for r, i in enumerate(order)}
            out.append({"gid": gid, "date": str(d.get("date")), "sims": sims, "ys": ys, "freed": freed or 0.0,
                        "rank": [rank[i] for i in range(len(sims))]})
    return out


def sse(rows: List[Dict], params: Dict[str, float]) -> float:
    tot = 0.0
    for r in rows:
        for m, y in zip(R.reshare(r["sims"], r["freed"], params), r["ys"]):
            tot += (y - m) ** 2
    return tot


def evaluate(rows: List[Dict], params: Dict[str, float], n_boot: int) -> Dict:
    def block(sel) -> Optional[Dict]:
        cur, new = [], []
        for r in rows:
            nm = R.reshare(r["sims"], r["freed"], params)
            for i, (s, m, y) in enumerate(zip(r["sims"], nm, r["ys"])):
                if sel(r, i):
                    cur.append((r["gid"], s, y))
                    new.append((r["gid"], m, y))
        if not cur:
            return None
        return {"n": len(cur),
                "bias_current": B.boot_ci([(g, y - s) for g, s, y in cur], n_boot),
                "bias_new": B.boot_ci([(g, y - m) for g, m, y in new], n_boot),
                "mae_current": round(statistics.fmean(abs(y - s) for _, s, y in cur), 3),
                "mae_new": round(statistics.fmean(abs(y - m) for _, m, y in new), 3),
                "mae_delta_new_minus_current": B.boot_ci([(c[0], abs(n_[2] - n_[1]) - abs(c[2] - c[1])) for c, n_ in zip(cur, new)], n_boot)}
    rep: Dict = {"all": block(lambda r, i: True)}
    for bname, lo, hi in FREED_BANDS:
        rep[bname] = block(lambda r, i, lo=lo, hi=hi: lo <= r["freed"] < hi)
        for tname, a, b in TIERS:
            rep[f"{bname} / {tname}"] = block(lambda r, i, lo=lo, hi=hi, a=a, b=b: lo <= r["freed"] < hi and a <= r["rank"][i] <= b)
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True, help="as-of re-run archive (oracle availability for the fit)")
    ap.add_argument("--processed", required=True, help="processed root holding boxscores_history.csv")
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--split", default="2026-08-01")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--write-artifact", default="", help="write wnba_sim_minutes_redistribution.json here")
    args = ap.parse_args(argv)
    games = B.load_games(Path(args.espn_dir))
    box_all = AV.load_box_all(Path(args.box_dir), games)
    rows = team_games(Path(args.archive), Path(args.processed), games, box_all)
    train = [r for r in rows if r["date"] < args.split]
    test = [r for r in rows if r["date"] >= args.split]
    print(f"team-games: train {len(train)} ({len({r['date'] for r in train})} dates), test {len(test)} "
          f"({len({r['date'] for r in test})} dates)", flush=True)
    best = min(((sse(train, {"b0": b0, "b1": b1, "leak": lk}), b0, b1, lk)
                for b0, b1, lk in itertools.product(GRID_B0, GRID_B1, GRID_LEAK)), key=lambda t: t[0])
    params = {"b0": best[1], "b1": best[2], "leak": best[3]}
    edges = [k for k, grid in (("b0", GRID_B0), ("b1", GRID_B1), ("leak", GRID_LEAK)) if params[k] in (grid[0], grid[-1])]
    zero = {"b0": 0.0, "b1": 0.0, "leak": 0.0}
    rep = {"params": params, "grid_edge": edges, "train_team_games": len(train), "test_team_games": len(test),
           "train_sse": {"fitted": round(best[0], 1), "current": round(sse(train, zero), 1)},
           "test": evaluate(test, params, args.n_boot), "train": evaluate(train, params, args.n_boot)}
    print(f"params {params}  grid edge: {edges or 'none'}  train SSE {rep['train_sse']}", flush=True)
    for k, v in rep["test"].items():
        if v:
            print(f"  TEST {k:28s} n {v['n']:5d} bias {v['bias_current']['point']:+.2f} -> {v['bias_new']['point']:+.2f} "
                  f"{v['bias_new']['ci95']}  MAE {v['mae_current']} -> {v['mae_new']} d {v['mae_delta_new_minus_current']}", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "redistribution_fit.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    if args.write_artifact:
        art = Path(args.write_artifact)
        art.mkdir(parents=True, exist_ok=True)
        (art / R.PARAM_FILE).write_text(json.dumps({"params": params, "fit": {
            "archive": str(args.archive), "split": args.split, "train_team_games": len(train),
            "grid_edge": edges}}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
