"""Fit and check the player-scaled NegBin remainder that prices WNBA live COUNT props.

`[2026-09-28, lane live-props-model-probability]`. Produces the `_NEGBIN_REMAINDER` table in
`syndicate/features/shared/wnba_live_prop_probability.py` and the line-level calibration that
justified it. Two steps, so the slow network pass runs once:

    # 1. replay + grade every WNBA game with a sim anchor, CLOCK-sampled, to JSON
    py -3 scripts/fit_wnba_live_count_remainder.py grade --start 2026-07-15 --end 2026-08-31 --out jul_aug.json
    py -3 scripts/fit_wnba_live_count_remainder.py grade --start 2026-09-01 --end 2026-09-27 --out sep.json

    # 2. fit on one set, report LINE-LEVEL calibration on another (and the live normal beside it)
    py -3 scripts/fit_wnba_live_count_remainder.py fit --train jul_aug.json --test sep.json

THE GATE IS LINE-LEVEL CALIBRATION, not interval coverage: predicted vs observed P(final >= line)
over the ladder the lens publishes (half-points above the banked value, out to 3 sd), reported
for all players and for rotation players (pregame minutes >= 20). Interval coverage of 91.5-91.8%
coexisted with 18 pp over-pricing of overs; see learnings.md 2026-09-28.

Needs ADMIN_TOKEN (env, or `.env` in the repo root) for the sim anchors.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

STATS = ("points", "rebounds", "assists", "threes")
COUNT_STATS = ("rebounds", "assists", "threes")
BUCKETS = ((30.0, float("inf")), (20.0, 30.0), (10.0, 20.0), (5.0, 10.0), (0.0, 5.0))
BUCKET_MID = (35.0, 25.0, 15.0, 7.5, 2.5)


def grade(start: str, end: str, out: Path) -> None:
    import grade_wnba_live_prop_projection as g
    from syndicate.features.shared.wnba_live_prop_rows import normalize_name

    rows = {k: [] for k in STATS}
    d, stop = date.fromisoformat(start), date.fromisoformat(end)
    while d <= stop:
        ds = d.isoformat(); d += timedelta(days=1)
        try:
            events = g.event_ids_for_date(ds)
        except Exception:
            continue
        if not events:
            continue
        anchors = g.sim_anchor_index(ds)
        if not anchors:
            print(ds, "no sim anchor -- skipped", flush=True)
            continue
        for ev in events:
            try:
                summary = g._get(f"{g._SUMMARY}?event={urllib.parse.quote(str(ev))}")
            except Exception:
                continue
            comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
            if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
                continue
            check = g.reconcile(g.replay(summary))
            for stat in STATS:
                if check["points_exact"] != check["players"] or check[f"{stat}_exact"] != check["players"]:
                    continue  # the replay must reproduce the official box for this stat
                for r in g.grade_event(summary, anchors, stat, "clock")["rows"]:
                    r["date"], r["event"] = ds, ev
                    r["pregame_minutes"] = (anchors.get(normalize_name(r["player"])) or {}).get("min_mean")
                    rows[stat].append(r)
        print(ds, {k: len(v) for k, v in rows.items()}, flush=True)
    out.write_text(json.dumps({"rows": rows}), encoding="utf-8")


def _bucket(m: float) -> int | None:
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= (m or 0.0) < hi:
            return i
    return None


def _nb_logpmf(k: int, m: float, r: float) -> float:
    if m <= 0:
        return 0.0 if k == 0 else -50.0
    p = r / (r + m)
    return math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log1p(-p)


def _prep(rows: list[dict]) -> list[tuple]:
    out = []
    for r in rows:
        b = _bucket(r["minutes_remaining"])
        remainder = int(round(r["actual"] - r["current"]))
        if b is None or remainder < 0:
            continue
        out.append((b, max(r["projected"] - r["current"], 0.0), remainder, r))
    return out


def fit_negbin(data: list[tuple], per_bucket_r: bool) -> tuple[list[float], list[float]]:
    c_grid = [0.4 + 0.02 * i for i in range(131)]
    r_grid = [0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 7, 10, 15, 25, 50, 100, 400]
    cs, rs = [1.0] * len(BUCKETS), [5.0] * len(BUCKETS)
    by_b = [[d for d in data if d[0] == i] for i in range(len(BUCKETS))]
    for _ in range(3):
        for i, rows in enumerate(by_b):
            if len(rows) >= 100:
                cs[i] = max(c_grid, key=lambda c: sum(_nb_logpmf(R, c * rh, rs[i]) for _, rh, R, _ in rows))
        if per_bucket_r:
            for i, rows in enumerate(by_b):
                if len(rows) >= 100:
                    rs[i] = max(r_grid, key=lambda r: sum(_nb_logpmf(R, cs[i] * rh, r) for _, rh, R, _ in rows))
        else:
            best = max(r_grid, key=lambda r: sum(_nb_logpmf(R, cs[b] * rh, r) for b, rh, R, _ in data))
            rs = [best] * len(BUCKETS)
    return cs, rs


def line_calibration(rows: list[dict], price, rotation_only: bool) -> dict:
    """`price(row, line) -> P or None`; ladder = half-points above banked, out to centre + 3 sd."""
    from syndicate.features.shared.wnba_live_prop_probability import grid_center_and_sd

    preds = []
    for r in rows:
        if rotation_only and (r.get("pregame_minutes") or 0) < 20:
            continue
        placed = grid_center_and_sd(r["projected"], r["current"], r["minutes_remaining"], r["_market"])
        if not placed:
            continue
        center, sd = placed
        line = math.floor(r["current"]) + 0.5
        while line <= center + 3 * max(sd, 0.5):
            p = price(r, line)
            if p is not None:
                preds.append((p, 1.0 if r["actual"] >= line else 0.0))
            line += 1.0
    if not preds:
        return {"n": 0}
    base = sum(y for _, y in preds) / len(preds)
    brier = sum((p - y) ** 2 for p, y in preds) / len(preds)
    brier0 = sum((base - y) ** 2 for _, y in preds) / len(preds)
    bins = [[] for _ in range(10)]
    for p, y in preds:
        bins[min(9, int(p * 10))].append((p, y))
    gaps = {f"{i / 10:.1f}": round(sum(y for _, y in b) / len(b) - sum(p for p, _ in b) / len(b), 3)
            for i, b in enumerate(bins) if len(b) >= 50}
    return {"n": len(preds), "brier_skill": round(1 - brier / brier0, 3),
            "worst_gap": max(abs(v) for v in gaps.values()), "gaps": gaps}


def fit(train_path: Path, test_path: Path) -> None:
    from syndicate.features.shared import wnba_live_prop_probability as P

    train = json.loads(train_path.read_text(encoding="utf-8"))["rows"]
    test = json.loads(test_path.read_text(encoding="utf-8"))["rows"]
    for stat in COUNT_STATS:
        for r in test[stat]:
            r["_market"] = stat
        print(f"\n==== {stat.upper()}  train n={len(train[stat])}  test n={len(test[stat])}")
        for per_b in (True, False):
            cs, rs = fit_negbin(_prep(train[stat]), per_b)

            def nb_price(r, line, cs=cs, rs=rs):
                b = _bucket(r["minutes_remaining"])
                if b is None:
                    return None
                m = cs[b] * max(r["projected"] - r["current"], 0.0)
                return P._negbin_sf(math.ceil(line - r["current"]), m, rs[b])

            for rot in (False, True):
                c = line_calibration(test[stat], nb_price, rot)
                print(f"  NegBin r per {'bucket' if per_b else 'stat  '} {'rotation' if rot else 'all     '}: "
                      f"skill {c.get('brier_skill')} worst {c.get('worst_gap')}  c={[round(x, 2) for x in cs]} r={rs}")

        def shipped(r, line, stat=stat):
            return P.live_prop_prob_over(projected=r["projected"], line=line, minutes_remaining=r["minutes_remaining"],
                                         market=stat, current=r["current"])["prob_over"]

        c = line_calibration(test[stat], shipped, True)
        print(f"  SHIPPED function rotation: skill {c.get('brier_skill')} worst {c.get('worst_gap')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grade"); g.add_argument("--start", required=True); g.add_argument("--end", required=True)
    g.add_argument("--out", required=True, type=Path)
    f = sub.add_parser("fit"); f.add_argument("--train", required=True, type=Path); f.add_argument("--test", required=True, type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "grade":
        grade(args.start, args.end, args.out)
    else:
        fit(args.train, args.test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
