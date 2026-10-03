"""Fit and test a per-market DISPERSION factor for WNBA SmartSim prop ladders (lane `wnba-prop-dispersion`).

WHY. Lane `wnba-lines-props-backtest` (2026-10-02, 4,618 player-games, as-of re-run of today's engine) measured the
sim's prop distributions 1.23-1.58x too narrow (residual sd / sim sd), 80% intervals covering 58-84%, and every
market's ladder P(over) worse than the de-vigged book at the book line. This measures whether WIDENING the ladder,
and nothing else, fixes the probability -- before any engine code changes.

THE ESTIMATOR, exactly as the engine would apply it. For each player and market, every simulated value v becomes
    v' = max(0, round_half_up(mu + k * (v - mu)))        mu = the sim mean, unchanged in expectation for k >= 1
and P(over line) is read the board's way, P(v' >= floor(line) + 1) (`wnba_projections._hit_prob_over`). One k per
market. Combos (PR, PA, RA, PRA) get their OWN k: they are built from joint draws already, so a k_combo above the
components' k measures missing SHARED variance (minutes / game script), not missing correlation.

FIT / TEST, never mixed. k is chosen on regular-season dates before --split (default 2026-08-01) by mean log-loss at
the book line; the test is everything on/after --split (regular season) and the playoffs, reported separately. The
grid is 0.80..4.00; a k at either edge is reported as EDGE, not as a fit (learnings 2026-09-28).

THREE FITS, because a book-line log-loss fit CONFOUNDS width with the mean. The sim mean is biased low (minutes,
lane wnba-lines-props-backtest), so at the book line a wider ladder also drifts every probability toward 0.5 -- i.e.
it shrinks a biased, weakly informative forecast. Separated:
  `line`      k chosen by log-loss at the book line (what the board would feel),
  `ladder`    k chosen by the ranked probability score over the WHOLE ladder (a width fit, line-agnostic),
  `recentred` the ladder SHIFTED to the player's own as-of mean before dilation (v -> own_mu + k (v - mu)) and k
              chosen at the book line: the width the ladder needs once its mean is right (a preview of fixes 2/3).

WHAT IS REPORTED per market and period: n rows / games, fitted k (train), held-out Brier and log-loss at the book
line for k=1 (today's engine), k=fit, the de-vigged book and the player's own as-of average under a normal; paired
game-clustered CIs for (fit - k=1) and (fit - book); reliability by predicted-probability decile at the book line;
and the RANKED PROBABILITY SCORE over the WHOLE ladder (every integer threshold 1..max), so a k that only helps at
the book's line and distorts the rest of the ladder is visible. The mean is unchanged by construction; the report
checks it (mean shift).

INPUTS. `<archive>/<date>/smart_sim_<date>_*.json` from `backtest_wnba_lines_props.py game|sim` (as-of re-run, 500
sims), ESPN finals, fleet box scores, OddsAPI historical book -- the same loaders, imported, so the rows are the
backtest's rows.

Usage (WSL, where the archive is):
  python scripts/fit_wnba_prop_dispersion.py --archive ~/wnba_bt/archive --espn-dir /mnt/c/tmp/wnba_bt/espn \\
      --box-dir /mnt/c/tmp/wnba_bt/box --odds-dir /mnt/c/tmp/wnba_bt/odds_hist --out ~/wnba_bt/dispersion
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bt_wnba", REPO / "scripts" / "backtest_wnba_lines_props.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)  # type: ignore[union-attr]

K_GRID = [round(0.80 + 0.05 * i, 2) for i in range(65)]          # 0.80 .. 4.00


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def dilate(dist: Dict[int, float], mu: float, k: float) -> Dict[int, float]:
    """The engine estimator on a {value: mass} histogram: v -> max(0, round_half_up(mu + k (v - mu)))."""
    out: Dict[int, float] = defaultdict(float)
    for v, m in dist.items():
        out[max(0, round_half_up(mu + k * (v - mu)))] += m
    return dict(out)


def p_over(dist: Dict[int, float], line: float) -> float:
    """The board's read: P(X >= floor(line) + 1)."""
    thr = math.floor(float(line)) + 1
    tot = sum(dist.values()) or 1.0
    return sum(m for v, m in dist.items() if v >= thr) / tot


def rps(dist: Dict[int, float], y: float) -> float:
    """Ranked probability score: sum over every integer threshold 1..max(support, y) of the squared ladder error.
    Survival function by a reverse cumulative sum, O(support)."""
    tot = sum(dist.values()) or 1.0
    hi = int(max(max(dist) if dist else 0, y)) + 1
    mass = [0.0] * (hi + 2)
    for v, m in dist.items():
        mass[min(max(int(v), 0), hi + 1)] += m
    s, surv, acc = 0.0, [0.0] * (hi + 2), 0.0
    for t in range(hi + 1, -1, -1):
        acc += mass[t]
        surv[t] = acc / tot                                   # P(X >= t)
    for t in range(1, hi + 1):
        s += (surv[t] - (1.0 if y >= t else 0.0)) ** 2
    # UNNORMALISED sum. Dividing by the number of thresholds (the first version) rewards a WIDER ladder for having
    # more thresholds -- every fit then ran to the top of the grid. Thresholds past the support add exactly 0.
    return s


def load_rows(archive: Path, games: Dict, box: Dict, hist, book: Dict) -> List[Dict]:
    """One row per (game, player, market) with the sim histogram, mean, actual, and -- when two-sided -- the book."""
    idx = B._pair_index(games)
    rows: List[Dict] = []
    cnt = Counter()
    for p in sorted(archive.glob("*/smart_sim_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        gid = B.match_game(idx, str(d.get("date")), str(d.get("home")).upper(), str(d.get("away")).upper())
        if not gid:
            cnt["no_final_match"] += 1
            continue
        g = games[gid]
        for side in ("home", "away"):
            for pl in (d.get("players") or {}).get(side) or []:
                pk = B.norm_name(pl.get("player_name"))
                act = box.get(gid, {}).get(pk)
                if not act:
                    cnt["did_not_play_or_no_box"] += 1
                    continue
                base, n_prior = hist.player_avg(pk, g["tip"])
                lad = pl.get("prop_ladders") if isinstance(pl.get("prop_ladders"), dict) else {}
                for mk, (expr, _c) in B.PROP_MARKETS.items():
                    blk = lad.get(B.LADDER_STAT[mk])
                    if not isinstance(blk, dict) or not isinstance(blk.get("distribution"), dict):
                        cnt[f"no_ladder:{mk}"] += 1
                        continue
                    dist = {int(float(v)): float(m) for v, m in blk["distribution"].items()}
                    tot = sum(dist.values())
                    if tot <= 0:
                        continue
                    mu = sum(v * m for v, m in dist.items()) / tot
                    y = sum(act[s] for s in expr)
                    b = (book.get(gid) or {}).get("props", {}).get((pk, mk))
                    sd_own = hist.player_sd(pk, g["tip"], expr)
                    rows.append({"gid": gid, "date": g["date"], "phase": g["phase"], "mk": mk, "dist": dist, "mu": mu,
                                 "y": y, "line": b["line"] if b else None, "p_book": b["p"] if b else None,
                                 "own_mu": sum(base[s] for s in expr) if base and n_prior >= 3 else None,
                                 "own_sd": sd_own})
                    cnt[f"rows:{mk}"] += 1
    print("load:", json.dumps(dict(cnt)), flush=True)
    return rows


def _ll(p: float, y: int) -> float:
    return B.logloss(B.clip(p), y)


def shifted(r: Dict, k: float, recentre: bool) -> Dict[int, float]:
    if not recentre:
        return dilate(r["dist"], r["mu"], k)
    out: Dict[int, float] = defaultdict(float)
    for v, m in r["dist"].items():
        out[max(0, round_half_up(r["own_mu"] + k * (v - r["mu"])))] += m
    return dict(out)


def evaluate(rows: List[Dict], k: float, recentre: bool = False) -> Dict:
    """Scores at the book line (two-sided rows, pushes excluded) and the RPS over the whole ladder (all rows)."""
    if recentre:
        rows = [r for r in rows if r["own_mu"] is not None]
    at_line = [r for r in rows if r["line"] is not None and r["y"] != r["line"]]
    ps = [p_over(shifted(r, k, recentre), r["line"]) for r in at_line]
    ys = [int(r["y"] > r["line"]) for r in at_line]
    return {"ps": ps, "ys": ys, "gids": [r["gid"] for r in at_line], "rows": at_line,
            "rps": [rps(shifted(r, k, recentre), r["y"]) for r in rows]}


def fit_k(train: List[Dict], objective: str = "line", recentre: bool = False) -> Tuple[float, List[Tuple[float, float]], bool]:
    curve = []
    for k in K_GRID:
        e = evaluate(train, k, recentre) if recentre else evaluate(train, k)
        if not e["ps"]:
            return 1.0, [], False
        loss = statistics.fmean(e["rps"]) if objective == "ladder" else \
            statistics.fmean(_ll(p, y) for p, y in zip(e["ps"], e["ys"]))
        curve.append((k, loss))
    best = min(curve, key=lambda t: t[1])
    edge = best[0] in (K_GRID[0], K_GRID[-1])
    return best[0], curve, edge


def paired(gids: List[str], a: List[float], b: List[float]) -> Dict:
    return B.boot_ci([(g, x - y) for g, x, y in zip(gids, a, b)])


def score_period(rows: List[Dict], k: float, recentre: bool = False) -> Dict:
    if recentre:
        rows = [r for r in rows if r["own_mu"] is not None]
    if not rows:
        return {"n": 0}
    e1, ek = evaluate(rows, 1.0), evaluate(rows, k, recentre)
    out: Dict = {"n_rows_all": len(rows), "games": len({r["gid"] for r in rows})}
    if ek["ps"]:
        ys, gids = ek["ys"], ek["gids"]
        pb = [B.clip(r["p_book"]) for r in ek["rows"]]
        own = []
        for r in ek["rows"]:
            own.append(B.clip(B.normal_over(r["own_mu"], r["own_sd"])(r["line"])) if r["own_mu"] is not None and r["own_sd"] else None)
        sq = lambda ps: [(p - y) ** 2 for p, y in zip(ps, ys)]  # noqa: E731
        out["at_book_line"] = {
            "n": len(ys), "games": len(set(gids)), "over_rate": round(statistics.fmean(ys), 4),
            "brier_k1": round(statistics.fmean(sq(e1["ps"])), 5), "brier_kfit": round(statistics.fmean(sq(ek["ps"])), 5),
            "brier_book": round(statistics.fmean(sq(pb)), 5),
            "brier_own_avg_normal": round(statistics.fmean((o - y) ** 2 for o, y in zip(own, ys) if o is not None), 5)
            if any(o is not None for o in own) else None,
            "logloss_k1": round(statistics.fmean(_ll(p, y) for p, y in zip(e1["ps"], ys)), 5),
            "logloss_kfit": round(statistics.fmean(_ll(p, y) for p, y in zip(ek["ps"], ys)), 5),
            "logloss_book": round(statistics.fmean(_ll(p, y) for p, y in zip(pb, ys)), 5),
            "dbrier_kfit_minus_k1": paired(gids, sq(ek["ps"]), sq(e1["ps"])),
            "dbrier_kfit_minus_book": paired(gids, sq(ek["ps"]), sq(pb)),
            "dbrier_k1_minus_book": paired(gids, sq(e1["ps"]), sq(pb)),
            "reliability_k1": B.reliability(e1["ps"], ys, 10), "reliability_kfit": B.reliability(ek["ps"], ys, 10),
        }
    out["rps_whole_ladder"] = {"k1": round(statistics.fmean(e1["rps"]), 5), "kfit": round(statistics.fmean(ek["rps"]), 5),
                               "d_kfit_minus_k1": paired([r["gid"] for r in rows], ek["rps"], e1["rps"])}
    resid = [r["y"] - r["mu"] for r in rows]

    def _sd(rs, k):
        sds = []
        for r in rs:
            dd = dilate(r["dist"], r["mu"], k)
            tot = sum(dd.values())
            m = sum(v * w for v, w in dd.items()) / tot
            sds.append(math.sqrt(sum(w * (v - m) ** 2 for v, w in dd.items()) / tot))
        return statistics.fmean(sds)
    out["dispersion"] = {"residual_sd": round(statistics.pstdev(resid), 3), "sim_sd_k1": round(_sd(rows, 1.0), 3),
                         "sim_sd_kfit": round(_sd(rows, k), 3),
                         "mean_shift_from_dilation": round(statistics.fmean(
                             sum(v * w for v, w in dilate(r["dist"], r["mu"], k).items()) / sum(r["dist"].values()) - r["mu"]
                             for r in rows), 4)}
    return out


def B_fmt(d: Optional[Dict]) -> str:
    if not d or d.get("point") is None:
        return ""
    return f"{d['point']:+.4f}[{d['ci95'][0]:+.4f},{d['ci95'][1]:+.4f}]"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--split", default="2026-08-01")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=2000)
    args = ap.parse_args(argv)
    _boot = B.boot_ci
    B.boot_ci = lambda rows, n_boot=args.n_boot, seed=7: _boot(rows, n_boot, seed)  # noqa: E731
    games = B.load_games(Path(args.espn_dir))
    box, _ = B.load_box(Path(args.box_dir), games)
    hist = B.History(games, box)
    book, _ = B.load_book(Path(args.odds_dir), games)
    rows = load_rows(Path(args.archive), games, box, hist, book)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report: Dict = {"split": args.split, "k_grid": [K_GRID[0], K_GRID[-1], 0.05], "markets": {}}
    for mk in B.PROP_MARKETS:
        R = [r for r in rows if r["mk"] == mk]
        train = [r for r in R if r["phase"] == "regular" and r["date"] < args.split]
        test_reg = [r for r in R if r["phase"] == "regular" and r["date"] >= args.split]
        test_po = [r for r in R if r["phase"] == "playoff"]
        ent = {}
        for fit_name, objective, recentre in (("line", "line", False), ("ladder", "ladder", False),
                                              ("recentred", "line", True)):
            k, curve, edge = fit_k(train, objective, recentre)
            ent[fit_name] = {"k_fit": k, "k_at_grid_edge": edge, "objective": objective, "recentred": recentre,
                             "fit_curve": [(a, round(b, 5)) for a, b in curve],
                             "train": score_period(train, k, recentre),
                             "test_regular": score_period(test_reg, k, recentre),
                             "test_playoff": score_period(test_po, k, recentre)}
            t = ent[fit_name]["test_regular"].get("at_book_line") or {}
            rp = ent[fit_name]["test_regular"].get("rps_whole_ladder") or {}
            print(f"{mk:32s} {fit_name:9s} k={k}{' EDGE' if edge else ''} test n={t.get('n')} brier k1/kfit/book/own="
                  f"{t.get('brier_k1')}/{t.get('brier_kfit')}/{t.get('brier_book')}/{t.get('brier_own_avg_normal')} "
                  f"d(kfit-k1)={B_fmt(t.get('dbrier_kfit_minus_k1'))} d(kfit-book)={B_fmt(t.get('dbrier_kfit_minus_book'))} "
                  f"rps k1/kfit={rp.get('k1')}/{rp.get('kfit')}", flush=True)
        report["markets"][mk] = ent
    (out / "dispersion_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"wrote {out / 'dispersion_report.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
