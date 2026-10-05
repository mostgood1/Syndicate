# -*- coding: utf-8 -*-
"""Price test: last goalscorer, the board's race vs the time-aware race, on the SAME lines.

Lane `soccer-last-scorer-pricing` (2026-10-05). `last_scorer_timed_race.py` fits the
time-aware race (on-pitch curves, goal-time intensity, w(minutes share) on post-09-07
builds) on matches BEFORE `--split`; this grades both probabilities at the price on
matches ON/AFTER it, with the pricing, outcome and void rules of `grade_scorer_race.py`
(prices only from run-date files strictly before kickoff; 1u flat on EV>0 at the best
price; one-sided, vs raw implied with vig).

    SOCCER_AUDIT_CACHE=C:/tmp/soccer-lpb/cache py -3 last_scorer_price_test.py [--split 2026-09-16]
"""
import argparse
import collections
import glob
import json
import math
import os

import last_scorer_timed_race as timed
from common import boot_ci, load_recs, same_fixture, ts, dec_from_american
from grade_scorer_race import (CT, ESPN_CACHE, _espn_outcome, _load_prices, _lookup_player, _norm_name,
                               _same_person, scorer_race)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="2026-09-16")
    ap.add_argument("--out")
    args = ap.parse_args()
    timed.W_VERSION = "post0907"

    recs = load_recs(prekickoff_only=True)
    parsed = []
    for path in glob.glob(os.path.join(ESPN_CACHE, "*.json")):
        m = timed._parse(path)
        if m is None:
            continue
        m["key"] = tuple(os.path.basename(path)[:-5].rsplit("_", 1))
        parsed.append(m)
    S, B, G, W = timed._fit([m for m in parsed if m["date"] and m["date"] < args.split], recs)

    prices = _load_prices()
    price_dates = sorted(prices)
    rows, drop = [], collections.Counter()
    for (league, mid), rec in recs.items():
        if rec["kickoff"] is None or not rec["players"] or rec["version"] != "post0907":
            continue
        kick_ct = rec["kickoff"].astimezone(CT).date().isoformat()
        if kick_ct < args.split:
            continue
        outcome, why = _espn_outcome(league, mid)
        if outcome is None:
            drop[why] += 1
            continue
        px = None
        for d in reversed([d for d in price_dates if d < kick_ct]):
            cand = prices[d]
            cand = cand[(cand.league == league) & (cand.market_key == "player_last_goal_scorer")]
            if not len(cand):
                continue
            gt = cand.game_time.map(ts)
            cand = cand[[g is not None and abs((g - rec["kickoff"]).total_seconds()) <= 3 * 3600 for g in gt]]
            cand = cand[[same_fixture(rec["home"], rec["away"], h, a) for h, a in zip(cand.home_team, cand.away_team)]]
            if len(cand):
                px = cand
                break
        if px is None:
            drop["not_priced_pre_kickoff"] += 1
            continue
        old = {_norm_name(k): v for k, v in (scorer_race(rec["players"], match_expected_goals=rec["total_mean"]).get("by_player") or {}).items()}
        new = {k: v[1] for k, v in timed.timed_race(rec["players"], rec["total_mean"], S, B, G, W).items()}
        for player, grp in px.groupby("player"):
            pname = _norm_name(player)
            if not pname or "no scorer" in pname or "no goalscorer" in pname:
                continue
            p_old, _ = _lookup_player(old, player)
            p_new, _ = _lookup_player(new, player)
            if p_old is None or p_new is None:
                drop["player_not_in_race"] += 1
                continue
            if not any(_same_person(pname, a) for a in outcome["appeared"]):
                drop["dnp_void"] += 1
                continue
            decs = sorted(dec_from_american(x) for x in grp.over_price.dropna())
            if not decs:
                continue
            rows.append({"match": f"{league}|{mid}", "date": kick_ct, "p_old": p_old, "p_new": p_new,
                         "dec": decs[-1], "won": int(outcome["last"] is not None and _same_person(pname, outcome["last"]))})

    by_match = collections.defaultdict(list)
    for r in rows:
        by_match[r["match"]].append(r)
    units = list(by_match.values())

    def roi(us, key):
        xs = [x for u in us for x in u if x[key] * x["dec"] > 1.0]
        return sum((x["dec"] - 1) if x["won"] else -1.0 for x in xs) / len(xs) if xs else float("nan")

    def ll(us, key):
        xs = [x for u in us for x in u]
        return -sum(math.log(max(1e-6, x[key])) if x["won"] else math.log(max(1e-6, 1 - x[key])) for x in xs) / len(xs)

    report = {"split": args.split, "lines": len(rows), "matches": len(units),
              "dates": len({r["date"] for r in rows}), "wins": sum(r["won"] for r in rows), "dropped": dict(drop)}
    for key in ("p_old", "p_new"):
        bets = [x for u in units for x in u if x[key] * x["dec"] > 1.0]
        report[key] = {"ev_pos_bets": len(bets), "ev_pos_wins": sum(x["won"] for x in bets),
                       "roi": round(roi(units, key), 4) if bets else None,
                       "roi_ci95": [round(v, 4) for v in boot_ci(units, lambda us, k=key: roi(us, k))] if bets else None,
                       "logloss": round(ll(units, key), 5)}
    report["roi_new_minus_old_ci95"] = [round(v, 4) for v in boot_ci(units, lambda us: roi(us, "p_new") - roi(us, "p_old"))]
    report["logloss_new_minus_old_ci95"] = [round(v, 5) for v in boot_ci(units, lambda us: ll(us, "p_new") - ll(us, "p_old"))]
    print(json.dumps(report, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)


if __name__ == "__main__":
    main()
