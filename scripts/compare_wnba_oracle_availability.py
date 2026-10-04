"""Oracle availability vs the real availability rule, on the SAME player-game-market rows (lane `wnba-book-information`).

The oracle re-run excludes exactly the players who did not play (from the box score), so it is the ceiling of perfect
pregame injury/inactive information. Both archives carry the fix #2 + #3 stack (availability + rate shrink; the oracle's
shrink is applied post-hoc with the engine's own `apply_rate_shrink`, verified equal to in-engine). Rows are paired:
a (game, player, market) enters only if BOTH archives priced it, the player played, and the book has a two-sided line
-- so the oracle's extra rows (players the real rule wrongly dropped) and its dropped rows (DNPs) are excluded and the
comparison is the same bets priced two ways.

Per phase x market x late-out band: n, Brier (oracle, stack, book), Brier delta oracle - stack with a game-clustered
bootstrap CI, the same for MAE of the mean, and the remaining gap to the book.

Usage (WSL): python scripts/compare_wnba_oracle_availability.py --oracle ~/wnba_bt/oracle_shrunk --stack ~/wnba_bt/stack_same
             --espn-dir ... --box-dir ... --odds-dir ... --out ~/wnba_bt/oracle_compare
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


B = _load("bt_wnba", "backtest_wnba_lines_props.py")
BI = _load("bi_wnba", "analyze_wnba_book_information.py")
AV = BI.AV

BANDS = (("no late outs", 0.0, 0.001), ("late outs < 15 min", 0.001, 15.0), ("late outs >= 15 min", 15.0, 1e9))


def paired_rows(oracle: Dict, stack: Dict, games: Dict, box: Dict, book: Dict, lo: Dict) -> List[Dict]:
    rows: List[Dict] = []
    for gid in sorted(set(oracle) & set(stack)):
        g = games.get(gid)
        if not g:
            continue
        for pk in sorted(set(oracle[gid]) & set(stack[gid])):
            act = box.get(gid, {}).get(pk)
            if not act:
                continue
            for mk, (expr, _col) in B.PROP_MARKETS.items():
                eo, es = oracle[gid][pk].get(mk), stack[gid][pk].get(mk)
                b = (book.get(gid) or {}).get("props", {}).get((pk, mk))
                if not (eo and es and b and eo.get("over") and es.get("over")):
                    continue
                y = sum(act[s] for s in expr)
                line = b["line"]
                if y == line:
                    continue
                late = lo.get((gid, act.get("team")), 0.0)   # box rows carry the Syndicate tricode
                rows.append({"gid": gid, "phase": g["phase"], "mk": mk, "y": y, "over": int(y > line), "line": line,
                             "po": B.clip(eo["over"](line)), "ps": B.clip(es["over"](line)), "pb": B.clip(b["p"]),
                             "mo": eo["mean"], "ms": es["mean"], "late": late})
    return rows


def summarize(R: List[Dict], n_boot: int) -> Dict:
    br = lambda p, o: (p - o) ** 2
    return {
        "n": len(R), "games": len({r["gid"] for r in R}),
        "brier_oracle": round(statistics.fmean(br(r["po"], r["over"]) for r in R), 5),
        "brier_stack": round(statistics.fmean(br(r["ps"], r["over"]) for r in R), 5),
        "brier_book": round(statistics.fmean(br(r["pb"], r["over"]) for r in R), 5),
        "brier_delta_oracle_minus_stack": B.boot_ci([(r["gid"], br(r["po"], r["over"]) - br(r["ps"], r["over"])) for r in R], n_boot),
        "brier_delta_oracle_minus_book": B.boot_ci([(r["gid"], br(r["po"], r["over"]) - br(r["pb"], r["over"])) for r in R], n_boot),
        "brier_delta_stack_minus_book": B.boot_ci([(r["gid"], br(r["ps"], r["over"]) - br(r["pb"], r["over"])) for r in R], n_boot),
        "mae_oracle": round(statistics.fmean(abs(r["mo"] - r["y"]) for r in R), 3),
        "mae_stack": round(statistics.fmean(abs(r["ms"] - r["y"]) for r in R), 3),
        "mae_delta_oracle_minus_stack": B.boot_ci([(r["gid"], abs(r["mo"] - r["y"]) - abs(r["ms"] - r["y"])) for r in R], n_boot),
        "bias_oracle": round(statistics.fmean(r["mo"] - r["y"] for r in R), 3),
        "bias_stack": round(statistics.fmean(r["ms"] - r["y"] for r in R), 3),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--oracle", required=True)
    ap.add_argument("--stack", required=True)
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    args = ap.parse_args(argv)
    games = B.load_games(Path(args.espn_dir))
    box, _ = B.load_box(Path(args.box_dir), games)
    box_all = AV.load_box_all(Path(args.box_dir), games)
    book, _ = B.load_book(Path(args.odds_dir), games)
    lo = BI.late_outs(games, box_all)
    _, oracle, _ = B.load_sim_json_games(sorted(Path(args.oracle).glob("*/smart_sim_*.json")), games)
    _, stack, _ = B.load_sim_json_games(sorted(Path(args.stack).glob("*/smart_sim_*.json")), games)
    rows = paired_rows(oracle, stack, games, box, book, lo)
    report: Dict = {"paired_rows": len(rows), "cells": {}}
    for phase in ("regular", "playoff"):
        for mk in B.PROP_MARKETS:
            R = [r for r in rows if r["phase"] == phase and r["mk"] == mk]
            if len(R) < 30:
                continue
            cell = {"all": summarize(R, args.n_boot)}
            for name, lo_c, hi_c in BANDS:
                bb = [r for r in R if lo_c <= r["late"] < hi_c]
                if len(bb) >= 30:
                    cell[name] = summarize(bb, args.n_boot)
            report["cells"][f"{phase}:{mk}"] = cell
            a = cell["all"]
            print(f"{phase:8s} {mk:32s} n={a['n']} Brier oracle {a['brier_oracle']} stack {a['brier_stack']} book {a['brier_book']} "
                  f"d(o-s) {a['brier_delta_oracle_minus_stack']} d(o-book) {a['brier_delta_oracle_minus_book']}", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "oracle_compare.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
