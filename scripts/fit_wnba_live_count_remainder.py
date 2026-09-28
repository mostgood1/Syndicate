"""Fit and check the player-scaled NegBin remainder that prices WNBA live COUNT props.

`[2026-09-28, lane live-props-model-probability]`. Produces the `_NEGBIN_REMAINDER` table in
`syndicate/features/shared/wnba_live_prop_probability.py` and the line-level calibration that
justified it. Two steps, so the slow network pass runs once:

    # 1. replay + grade every WNBA game with a sim anchor, CLOCK-sampled, to JSON
    py -3 scripts/fit_wnba_live_count_remainder.py grade --start 2026-07-15 --end 2026-08-31 --out jul_aug.json
    py -3 scripts/fit_wnba_live_count_remainder.py grade --start 2026-09-01 --end 2026-09-27 --out sep.json

    # 2. fit on one set, report LINE-LEVEL calibration on another (and the live normal beside it)
    py -3 scripts/fit_wnba_live_count_remainder.py fit --train jul_aug.json --test sep.json

    # 3. the REMAINING-MINUTES model behind rebounds/assists (`_MINUTES_BETA`), vs the rule
    py -3 scripts/fit_wnba_live_count_remainder.py fit-minutes --train jul_aug.json --test sep.json

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


def _minutes_features(r: dict) -> tuple[float, list[float]]:
    """Same features, same order, as `expected_remaining_minutes` in production."""
    el = r["elapsed"]; played = r["minutes_played"] or 0.0; clock = max(0.0, 40.0 - el)
    pre = r.get("pregame_minutes") or 0.0
    s_pre = min(1.0, pre / 40.0); s_live = min(1.0, played / el) if el > 0 else s_pre
    late = min(1.0, el / 40.0)
    blow = min(max(abs(r.get("margin") or 0.0) - 8.0, 0.0), 20.0) / 20.0 * late
    s_rule = min(1.0, max(pre - played, 0.0) / clock) if clock > 0 else 0.0
    return clock, [1.0, s_pre, s_live, late * s_pre, late * s_live, s_rule, blow * s_pre, blow]


def fit_minutes(train_path: Path, test_path: Path) -> None:
    import numpy as np
    from syndicate.features.shared import wnba_live_prop_probability as P

    def usable(rows):
        return [r for r in rows if r.get("final_minutes") is not None and r.get("elapsed") is not None
                and r.get("minutes_played") is not None and r.get("pregame_minutes")]
    train = usable(json.loads(train_path.read_text(encoding="utf-8"))["rows"]["points"])
    test = usable(json.loads(test_path.read_text(encoding="utf-8"))["rows"]["points"])
    X, y, w = [], [], []
    for r in train:
        clock, x = _minutes_features(r)
        if clock >= 1.0:
            X.append(x); y.append(min(1.5, max(0.0, r["final_minutes"] - r["minutes_played"]) / clock)); w.append(clock)
    X, y, sw = np.array(X), np.array(y), np.sqrt(np.array(w))
    beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    print("beta (fitted)  ", [round(float(b), 4) for b in beta])
    print("beta (shipped) ", list(P._MINUTES_BETA))
    for label, rot in (("all", False), ("rotation", True)):
        e_rule, e_ship = [], []
        for r in test:
            clock = max(0.0, 40.0 - r["elapsed"])
            if clock < 1.0 or (rot and r["pregame_minutes"] < 20):
                continue
            actual = max(0.0, r["final_minutes"] - r["minutes_played"])
            e_rule.append(min(max(r["pregame_minutes"] - r["minutes_played"], 0.0), clock) - actual)
            e_ship.append(P.expected_remaining_minutes(r["pregame_minutes"], r["minutes_played"], clock, r.get("margin")) - actual)
        mae = lambda e: sum(abs(v) for v in e) / len(e)
        print(f"  {label:8} n={len(e_rule)}  remaining-minutes MAE: rule {mae(e_rule):.3f}  shipped model {mae(e_ship):.3f}")


def _blended_rate(r: dict) -> float | None:
    from syndicate.features.shared.wnba_live_prop_projection import project_live_player_stat

    v = project_live_player_stat(current_stat=r["current"], minutes_played=r.get("minutes_played"),
                                 pregame_stat=r.get("pregame_stat"), pregame_minutes=r.get("pregame_minutes"),
                                 game_minutes_remaining=max(0.0, 40.0 - r["elapsed"]))
    return v.get("rate")


def _prep(rows: list[dict], market: str = "") -> list[tuple]:
    """Bucket + expected remainder, on the SAME minutes estimate production uses for `market`."""
    from syndicate.features.shared import wnba_live_prop_probability as P

    out = []
    for r in rows:
        remainder = int(round(r["actual"] - r["current"]))
        if remainder < 0:
            continue
        if market in P.MINUTES_MODEL_MARKETS:
            if r.get("elapsed") is None:
                continue
            rate = _blended_rate(r)
            em = P.expected_remaining_minutes(r.get("pregame_minutes"), r.get("minutes_played"),
                                              max(0.0, 40.0 - r["elapsed"]), r.get("margin"))
            if rate is None or em is None:
                continue
            b, base = _bucket(em), rate * em
        else:
            b, base = _bucket(r["minutes_remaining"]), max(r["projected"] - r["current"], 0.0)
        if b is None:
            continue
        out.append((b, base, remainder, r))
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
        placed = grid_center_and_sd(r["projected"], r["current"], r["minutes_remaining"], r["_market"],
                                    rate=r.get("_rate"), expected_minutes=r.get("_em"))
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
            if stat in P.MINUTES_MODEL_MARKETS and r.get("elapsed") is not None:
                r["_rate"] = _blended_rate(r)
                r["_em"] = P.expected_remaining_minutes(r.get("pregame_minutes"), r.get("minutes_played"),
                                                        max(0.0, 40.0 - r["elapsed"]), r.get("margin"))
        print(f"\n==== {stat.upper()}  train n={len(train[stat])}  test n={len(test[stat])}")
        for per_b in (True, False):
            cs, rs = fit_negbin(_prep(train[stat], stat), per_b)
            test_prepped = {id(t[3]): t for t in _prep(test[stat], stat)}

            def nb_price(r, line, cs=cs, rs=rs, test_prepped=test_prepped):
                t = test_prepped.get(id(r))
                if t is None:
                    return None
                return P._negbin_sf(math.ceil(line - r["current"]), cs[t[0]] * t[1], rs[t[0]])

            for rot in (False, True):
                c = line_calibration(test[stat], nb_price, rot)
                print(f"  NegBin r per {'bucket' if per_b else 'stat  '} {'rotation' if rot else 'all     '}: "
                      f"skill {c.get('brier_skill')} worst {c.get('worst_gap')}  c={[round(x, 2) for x in cs]} r={rs}")

        def shipped(r, line, stat=stat):
            return P.live_prop_prob_over(projected=r["projected"], line=line, minutes_remaining=r["minutes_remaining"],
                                         market=stat, current=r["current"], rate=r.get("_rate"),
                                         expected_minutes=r.get("_em"))["prob_over"]

        c = line_calibration(test[stat], shipped, True)
        print(f"  SHIPPED function rotation: skill {c.get('brier_skill')} worst {c.get('worst_gap')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grade"); g.add_argument("--start", required=True); g.add_argument("--end", required=True)
    g.add_argument("--out", required=True, type=Path)
    f = sub.add_parser("fit"); f.add_argument("--train", required=True, type=Path); f.add_argument("--test", required=True, type=Path)
    fm = sub.add_parser("fit-minutes"); fm.add_argument("--train", required=True, type=Path)
    fm.add_argument("--test", required=True, type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "grade":
        grade(args.start, args.end, args.out)
    elif args.cmd == "fit-minutes":
        fit_minutes(args.train, args.test)
    else:
        fit(args.train, args.test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
