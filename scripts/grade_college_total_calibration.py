"""Grade the college TOTALS calibration (todo #816) on its own post-load slates -- READ-ONLY.

Lane ncaab-total-overprojection. The registered 7-day tests (T1-T5) and their verdict rules are in
`.syndicate/findings_2026-11-16_ncaab_total_overprojection.md` § "#816 7-day grade, PRE-REGISTERED"; this script prints
every number they read. Run it on the fleet under a role's environ (finals come from the slate files, rows from the
live game-line ledger, fits from the processed dir):

    python scripts/grade_college_total_calibration.py --league ncaab --from 2026-11-17 --to 2026-11-23

LIVE, per slate d (full-game totals, the engine's own number `model_home_win_prob_uncalibrated`, else the served
number on rows that never carried a calibration):
  served  = the calibration IN FORCE for d (`calibration_for(league, "live", d)`, the newest fit dated before d),
            applied to every row of the slate -- what the board served from the load on, and what it would have served
            for a slate's pre-load rows;
  market  = the row's de-vigged over price; raw = the engine;
  spread  = a SPREAD-ONLY fit (a = 0) on the same trailing window the daily refit uses, applied the same way -- the
            counterfactual for flipping `FIT_LEVEL`.
  Each game's rows weigh 1 in all (as in the fit). Brier differences are averaged per game, then across games; the SE
  is game-clustered, and a night-clustered SE is printed beside it (games on one night share shocks).
FLAGS: served |p - market| >= 3 pp, graded against finals by lean (over / under), per game then pooled: hit - fair.
PREGAME, per slate: one row per graded game at its close (`pregame_fit_rows`): served = the pregame calibration in
  force, market = 0.5, raw = the sim.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from collections import defaultdict
from typing import Any

from syndicate.features.college_basketball import total_prob_calibration as tpc

FLAG_PP = 3.0


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _days(first: str, last: str) -> list[str]:
    d, end = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def live_rows_by_game(league: str, day: str) -> dict[tuple[str, str], list[tuple[float, float, float]]]:
    """(home, away) join key -> [(x, offset, y)] for one slate's live full-game totals; the same reading as
    `tpc.live_fit_rows`, keeping the game key for clustering."""
    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.shared.live_gameline_ledger import ledger_path, read_records

    finals, _ = tpc._finals(league, day)
    out: dict[tuple[str, str], list[tuple[float, float, float]]] = defaultdict(list)
    for rec in read_records(ledger_path(league, day)):
        if rec.get("market") != "totals" or str(rec.get("segment") or "") not in ("full", "full_game") or rec.get("line") is None:
            continue
        p_raw = rec.get("model_home_win_prob_uncalibrated")
        if p_raw is None:
            if rec.get("total_cal"):
                continue
            p_raw = rec.get("model_home_win_prob")
        p_mkt = rec.get("market_fair_prob_over")
        if p_raw is None or p_mkt is None or not 0.0 < float(p_mkt) < 1.0:
            continue
        key = (lr._join_key(league, rec.get("home_team")), lr._join_key(league, rec.get("away_team")))
        total = finals.get(key) or finals.get((key[1], key[0]))
        line = float(rec["line"])
        if total is None or total == line:
            continue
        out[key].append((tpc._logit(p_raw) - tpc._logit(p_mkt), tpc._logit(p_mkt), 1.0 if total > line else 0.0))
    return out


def _spread_only_for(league: str, day: str, floor: dt.date) -> dict[str, Any]:
    """The spread-only live fit the daily refit would have written for slate `day` (window ending day - 1)."""
    d = dt.date.fromisoformat(day)
    as_of = d - dt.timedelta(days=1)
    first = max(floor, as_of - dt.timedelta(days=tpc.WINDOW_DAYS - 1))
    rows = []
    for back in _days(first.isoformat(), as_of.isoformat()):
        rows += tpc.live_fit_rows(league, back)
    return tpc.fit(rows, level=False) if sum(w for *_, w in rows) >= tpc.MIN_GAMES else {}


def _mean_se(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return float("nan"), float("nan")
    m = sum(values) / n
    if n < 2:
        return m, float("nan")
    return m, math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1) / n)


def grade(league: str, days: list[str], floor: dt.date) -> dict[str, Any]:
    games: list[dict[str, Any]] = []      # one per (day, game): mean Brier per arm, flags
    pregame: list[dict[str, Any]] = []
    fits: dict[str, Any] = {}
    for day in days:
        d = dt.date.fromisoformat(day)
        cal = tpc.calibration_for(league, "live", d)
        pcal = tpc.calibration_for(league, "pregame", d)
        so = _spread_only_for(league, day, floor)
        fits[day] = {"live": cal.stamp() if cal else None, "pregame": pcal.stamp() if pcal else None,
                     "spread_only_live_c": round(so["c"], 4) if so else None}
        for key, rows in live_rows_by_game(league, day).items():
            arms = defaultdict(float)
            flags = []
            for x, off, y in rows:
                p_mkt, p_raw = _sig(off), _sig(off + x)
                p_cal = _sig(off + cal.a + cal.c * x) if cal else p_raw
                p_so = _sig(off + so["c"] * x) if so else p_raw
                for arm, p in (("market", p_mkt), ("raw", p_raw), ("served", p_cal), ("spread_only", p_so)):
                    arms[arm] += (p - y) ** 2 / len(rows)
                edge = (p_cal - p_mkt) * 100.0
                if abs(edge) >= FLAG_PP:
                    lean_over = edge > 0
                    flags.append(("over" if lean_over else "under", y if lean_over else 1.0 - y, p_mkt if lean_over else 1.0 - p_mkt))
            games.append({"day": day, "game": "|".join(key), "rows": len(rows), "calibrated": cal is not None, **arms, "flags": flags})
        for x, _off, y, _w in tpc.pregame_fit_rows(league, day):
            p_raw = _sig(x)
            p_cal = _sig(pcal.a + pcal.c * x) if pcal else p_raw
            pregame.append({"day": day, "market": 0.25, "raw": (p_raw - y) ** 2, "served": (p_cal - y) ** 2,
                            "calibrated": pcal is not None})
    return {"games": games, "pregame": pregame, "fits": fits}


def summarize(league: str, res: dict[str, Any]) -> dict[str, Any]:
    games = [g for g in res["games"] if g["calibrated"]]
    out: dict[str, Any] = {"league": league, "live_games": len(games), "nights": sorted({g["day"] for g in games}),
                           "fits": res["fits"]}
    for arm in ("market", "raw", "served", "spread_only"):
        out[f"live_brier_{arm}"] = round(sum(g[arm] for g in games) / len(games), 5) if games else None
    for a, b in (("served", "market"), ("served", "raw"), ("served", "spread_only")):
        diffs = [g[a] - g[b] for g in games]
        m, se = _mean_se(diffs)
        nights = defaultdict(list)
        for g in games:
            nights[g["day"]].append(g[a] - g[b])
        nm, nse = _mean_se([sum(v) / len(v) for v in nights.values()])
        out[f"T_{a}_minus_{b}"] = {"mean": round(m, 5), "se_game": round(se, 5), "ci90_game": [round(m - 1.645 * se, 5), round(m + 1.645 * se, 5)],
                                   "night_mean": round(nm, 5), "se_night": None if math.isnan(nse) else round(nse, 5), "nights": len(nights)}
    for side in ("over", "under"):
        per = []
        for g in games:
            fl = [f for f in g["flags"] if f[0] == side]
            if fl:
                per.append((sum(f[1] for f in fl) / len(fl), sum(f[2] for f in fl) / len(fl)))
        diffs = [h - f for h, f in per]
        m, se = _mean_se(diffs)
        out[f"flags_{side}"] = {"games": len(per), "hit": round(sum(h for h, _ in per) / len(per), 3) if per else None,
                                "fair": round(sum(f for _, f in per) / len(per), 3) if per else None,
                                "hit_minus_fair_pp": None if not per else round(100 * m, 1),
                                "ci90_pp": None if len(per) < 2 else [round(100 * (m - 1.645 * se), 1), round(100 * (m + 1.645 * se), 1)]}
    pre = [p for p in res["pregame"] if p["calibrated"]]
    if pre:
        diffs = [p["served"] - p["market"] for p in pre]
        m, se = _mean_se(diffs)
        out["pregame"] = {"games": len(pre), **{f"brier_{k}": round(sum(p[k] for p in pre) / len(pre), 5) for k in ("market", "raw", "served")},
                          "served_minus_market": round(m, 5), "ci90": None if len(pre) < 2 else [round(m - 1.645 * se, 5), round(m + 1.645 * se, 5)]}
    by_night = defaultdict(list)
    for g in games:
        by_night[g["day"]].append(g)
    out["by_night"] = {d: {"games": len(v), "served": round(sum(g["served"] for g in v) / len(v), 4),
                           "market": round(sum(g["market"] for g in v) / len(v), 4),
                           "spread_only": round(sum(g["spread_only"] for g in v) / len(v), 4)} for d, v in sorted(by_night.items())}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--league", default="ncaab")
    ap.add_argument("--from", dest="first", required=True)
    ap.add_argument("--to", dest="last", required=True)
    ap.add_argument("--floor", default=tpc.FIT_FLOOR.isoformat())
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    out = []
    for league in [s.strip() for s in args.league.split(",") if s.strip()]:
        s = summarize(league, grade(league, _days(args.first, args.last), dt.date.fromisoformat(args.floor)))
        out.append(s)
        print(json.dumps(s, indent=1, sort_keys=True), flush=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
