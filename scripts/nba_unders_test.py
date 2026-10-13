"""H6: do NBA prop UNDERS beat the market? Main lines only, one row per player-game-market (lane `signal-engine-nba`).

Pre-registered in the lane block (2026-10-13, `804f11d5`) before any H6 outcome was read. The lead came from H1-H5's
baselines (under residual +1.4..+2.3% across eligible lines), which used every alternate point; this test removes that
multiplicity.

  main line   per (event, market, player): the point quoted (two-sided) by the most books; tie -> the point whose median
              Shin p_over is nearest 0.5
  fair        median per-book Shin de-vig (production `opportunity_signals.devig`); sensitivity: multiplicative
  H6a         pooled UNDER residual (y_under - p_shin_under) > 0
  H6b         the same on players with prior-10 mean MIN >= 30 (from the as-of signal tables)
  bar         game-clustered 95% CI > 0 in CONFIRM and point estimate > 0 in DISCOVER
  reported    flat 1-unit ROI of the under at the BEST book price and at the MEDIAN book price; per-market residuals
              with Benjamini-Hochberg q = 0.10 on CONFIRM

    python3 scripts/nba_unders_test.py --data-root ~/syndicate-prod/data --season 2025-26 \\
        --props-dir .../asof/props_odds_hist --logs-statsnba .../playergamelogs_2025-26_Regular_Season.json --out h6.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from signal_lift import MARKET_STATS, WINDOWS, load_outcomes  # noqa: E402
from syndicate.features.shared.matchup_signals import bh_adjust, norm_player, read_signal_table, residual_stats  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402


def decimal(price: float) -> float:
    return 1.0 + price / 100.0 if price > 0 else 1.0 + 100.0 / -price


def main_lines(path: Path) -> list[dict[str, Any]]:
    by_point: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("market") not in MARKET_STATS:
                continue
            side = str(r.get("outcome_name") or "").strip().lower()
            if side not in ("over", "under"):
                continue
            try:
                point, price = float(r["point"]), float(r["price"])
            except (TypeError, ValueError, KeyError):
                continue
            by_point[(r["event_id"], r["market"], norm_player(r.get("player_name")), point)][r.get("bookmaker") or ""][side] = price
    candidates: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for (event, market, player, point), books in by_point.items():
        two = {b: s for b, s in books.items() if "over" in s and "under" in s}
        if not two:
            continue
        shin = [devig([s["over"], s["under"]], method="shin") for s in two.values()]
        mult = [devig([s["over"], s["under"]], method="multiplicative") for s in two.values()]
        shin = [f[0] for f in shin if f]
        mult = [f[0] for f in mult if f]
        if not shin:
            continue
        unders = [decimal(s["under"]) for s in two.values()]
        candidates[(event, market, player)].append({
            "event": event, "market": market, "player_key": player, "point": point, "books": len(shin),
            "p_over": statistics.median(shin), "p_over_mult": statistics.median(mult) if mult else None,
            "under_dec_best": max(unders), "under_dec_median": statistics.median(unders)})
    out = []
    for cands in candidates.values():
        cands.sort(key=lambda c: (-c["books"], abs(c["p_over"] - 0.5)))
        out.append(cands[0])
    return out


def roi_stats(rows: list[Mapping[str, Any]], dec_key: str, B: int = 600, seed: int = 7) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    pnl = lambda r: (r[dec_key] - 1.0) if r["y"] == 1.0 else -1.0  # noqa: E731
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[r["game"]].append(r)
    keys = list(groups)
    rng = random.Random(seed)
    boots = []
    for _ in range(B):
        sample = [r for _ in keys for r in groups[rng.choice(keys)]]
        boots.append(100 * sum(pnl(r) for r in sample) / len(sample))
    boots.sort()
    return {"roi_pct": round(100 * sum(pnl(r) for r in rows) / len(rows), 2),
            "ci95": [round(boots[int(0.025 * B)], 2), round(boots[int(0.975 * B) - 1], 2)]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--season", required=True)
    ap.add_argument("--props-dir", required=True)
    ap.add_argument("--logs-statsnba", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    root = os.path.expanduser(args.data_root)
    outcomes = load_outcomes(Path(os.path.expanduser(args.logs_statsnba)))
    last = max(hi for _, hi in WINDOWS.values())
    rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)  # (window, subset) -> rows
    per_market: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    counts = defaultdict(int)
    for path in sorted(Path(os.path.expanduser(args.props_dir)).glob("*.csv")):
        day = path.stem
        if day > last:
            continue
        window = next((w for w, (lo, hi) in WINDOWS.items() if lo <= day <= hi), None)
        if window is None:
            continue
        tiers = {r["player_key"]: r.get("min_prior10") for r in read_signal_table(root, "nba", args.season, day)}
        for line in main_lines(path):
            counts["main_lines"] += 1
            res = outcomes.get((line["player_key"], day))
            if not res or any(res.get(c) is None for c in MARKET_STATS[line["market"]]):
                counts["no_outcome"] += 1
                continue
            value = sum(res[c] for c in MARKET_STATS[line["market"]])
            if value == line["point"]:
                counts["push"] += 1
                continue
            y = 1.0 if value < line["point"] else 0.0
            rec = {"y": y, "p": 1.0 - line["p_over"], "game": line["event"],
                   "p_mult": None if line["p_over_mult"] is None else 1.0 - line["p_over_mult"],
                   "under_dec_best": line["under_dec_best"], "under_dec_median": line["under_dec_median"]}
            rows[(window, "all")].append(rec)
            if (tiers.get(line["player_key"]) or 0) >= 30:
                rows[(window, "min30")].append(rec)
            per_market[(window, line["market"])].append(rec)
            counts["graded"] += 1
    report: dict[str, Any] = {"counts": dict(counts), "hypotheses": {}, "per_market_confirm": {}}
    for name, subset in (("H6a_all", "all"), ("H6b_min30", "min30")):
        entry: dict[str, Any] = {}
        for window in WINDOWS:
            rs = rows[(window, subset)]
            entry[window] = {
                "shin": residual_stats(rs),
                "multiplicative": residual_stats([{"y": r["y"], "p": r["p_mult"], "game": r["game"]} for r in rs if r["p_mult"] is not None], B=300),
                "roi_best_price": roi_stats(rs, "under_dec_best"),
                "roi_median_price": roi_stats(rs, "under_dec_median"),
            }
        d, c = entry["discover"]["shin"], entry["confirm"]["shin"]
        entry["verdict"] = "SUPPORTED" if (c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0) else "NOT SUPPORTED"
        report["hypotheses"][name] = entry
    pvals = {}
    for (window, market), rs in per_market.items():
        if window != "confirm":
            continue
        st = residual_stats(rs, B=400)
        report["per_market_confirm"][market] = {"shin": st, "roi_best_price": roi_stats(rs, "under_dec_best", B=300)}
        pvals[market] = st.get("p_one_sided")
    for market, keep in bh_adjust(pvals, q=0.10).items():
        report["per_market_confirm"][market]["bh_q10"] = keep
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("H6 counts", dict(counts))
    for name, e in report["hypotheses"].items():
        for w in WINDOWS:
            s, m, rb, rm = e[w]["shin"], e[w]["multiplicative"], e[w]["roi_best_price"], e[w]["roi_median_price"]
            print(f"  {name:10s} {w:8s} n={s.get('n')} g={s.get('games')} hit={s.get('hit_rate')} p={s.get('mean_p')} "
                  f"resid={s.get('residual')} ci={s.get('ci95')} | mult resid={m.get('residual')} | "
                  f"ROI best={rb.get('roi_pct')} {rb.get('ci95')} median={rm.get('roi_pct')} {rm.get('ci95')}")
        print(f"  {name:10s} VERDICT {e['verdict']}")
    for market, e in sorted(report["per_market_confirm"].items()):
        s = e["shin"]
        print(f"    confirm {market:32s} n={s.get('n')} resid={s.get('residual')} ci={s.get('ci95')} "
              f"ROI best={e['roi_best_price'].get('roi_pct')} BH={e['bh_q10']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
