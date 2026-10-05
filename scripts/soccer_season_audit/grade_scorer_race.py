# -*- coding: utf-8 -*-
"""First / last goalscorer: the board's race probability graded at the price.

Lane `soccer-scorer-race-grade` (2026-10-05). The 2026-10-02 props backtest left
these two markets untested ("no box-score order captured"); ESPN's `keyEvents`
carry every goal with its period and clock, so the order IS recoverable.

WHAT IS GRADED. The probability the board serves: production's own
`soccer_scorer_markets.scorer_race(player_props, match_expected_goals=total_mean)`
on PRE-KICKOFF builds (`load_recs(prekickoff_only=True)`), the same inputs
`soccer_projections._scorer_race_for` passes. Last scorer uses the same number
(the board's stated time-reversal assumption).

PRICES. `props/<run-date>.csv` carries no capture time, and a run-date file can be
rewritten during that day's matches. So a match is priced ONLY from files whose run
date is strictly before its kickoff date (US Central), the latest such file: those
captures cannot be in-play. They are early prices (>= the day before), not closes.
One-sided (OVER/yes only): compared with the raw implied probability WITH vig.

OUTCOMES. ESPN summary `keyEvents`: scoring plays, own goals and shootouts
excluded, ordered by (period, clock). A player who did not appear is VOID (as
books settle it and as `population_outcomes_soccer` does). No qualifying goal:
every appeared player loses. "No Scorer" rows are skipped.

    SOCCER_AUDIT_CACHE=C:/tmp/soccer-lpb/cache py -3 grade_scorer_race.py [--out report.json]
"""
import argparse
import collections
import glob
import io
import json
import math
import os
import re
import sys
import tempfile
from zoneinfo import ZoneInfo

import pandas as pd

from common import PRIMARY, S, boot_ci, dec_from_american, load_recs, same_fixture, ts

sys.path.insert(0, PRIMARY)
from syndicate.features.shared.prop_projections import _norm_name  # noqa: E402
from syndicate.features.shared.soccer_scorer_markets import scorer_race  # noqa: E402

CT = ZoneInfo("America/Chicago")
ESPN_CACHE = os.path.join(tempfile.gettempdir(), "espn_shots_cache")
MARKETS = {"player_first_goal_scorer": "first", "player_last_goal_scorer": "last"}


def _espn_outcome(league, match_id):
    path = os.path.join(ESPN_CACHE, f"{league}_{match_id}.json")
    if not os.path.exists(path):
        return None, "no_espn_summary"
    j = json.load(io.open(path, encoding="utf-8"))
    comp = ((j.get("header") or {}).get("competitions") or [{}])[0]
    if ((comp.get("status") or {}).get("type") or {}).get("name") != "STATUS_FULL_TIME":
        return None, "not_final"
    appeared = set()
    for r in j.get("rosters") or []:
        for p in r.get("roster") or []:
            sub = p.get("subbedIn")
            if isinstance(sub, dict):
                sub = sub.get("didSub")
            if p.get("starter") or sub:
                appeared.add(_norm_name((p.get("athlete") or {}).get("displayName")))
    goals = []
    for e in j.get("keyEvents") or []:
        if not e.get("scoringPlay") or e.get("shootout"):
            continue
        if str((e.get("type") or {}).get("type") or "") == "own-goal":
            continue
        parts = e.get("participants") or []
        name = ((parts[0] if parts else {}).get("athlete") or {}).get("displayName")
        if not name:
            return None, "goal_without_scorer"
        key = ((e.get("period") or {}).get("number") or 0, float((e.get("clock") or {}).get("value") or 0.0))
        goals.append((key, _norm_name(name)))
    if not appeared:
        return None, "no_roster"
    goals.sort()
    if len(goals) >= 2 and (goals[0][0] == goals[1][0] or goals[-1][0] == goals[-2][0]):
        return None, "goal_order_tie"
    return {"appeared": appeared, "first": goals[0][1] if goals else None,
            "last": goals[-1][1] if goals else None, "n_goals": len(goals)}, None


def _lookup_player(pool, board_name):
    """Copy of `soccer_projections.attach_soccer_projections._lookup_player` (a nested
    function, so not importable): exact normalised match, else a UNIQUE token-subset
    match; a one-token subset needs >= 4 characters; more than one candidate refuses."""
    key = _norm_name(board_name)
    if not key or not pool:
        return None, "empty"
    if pool.get(key) is not None:
        return pool[key], "exact"
    tokens = set(key.split())
    candidates = []
    for pool_key, value in pool.items():
        pool_tokens = set(str(pool_key or "").split())
        if not pool_tokens:
            continue
        shorter, longer = (pool_tokens, tokens) if len(pool_tokens) <= len(tokens) else (tokens, pool_tokens)
        if not shorter <= longer or (len(shorter) == 1 and len(next(iter(shorter))) < 4):
            continue
        candidates.append(value)
    if len(candidates) == 1:
        return candidates[0], "alias"
    return None, ("ambiguous" if candidates else "miss")


def _same_person(a, b):
    """Two normalised names: equal, or one's tokens a subset of the other's (>= 2 tokens)."""
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small) >= 2 and small <= big


def _load_prices():
    """{run_date: DataFrame} of first/last scorer rows."""
    out = collections.defaultdict(list)
    for f in glob.glob(os.path.join(S, "prod", "props", "*.csv")):
        b = os.path.basename(f)
        m = re.search(r"(\d{4}-\d{2}-\d{2})\.csv$", b)
        if b.startswith("_") or not m:
            continue
        try:
            df = pd.read_csv(f, usecols=["league", "player", "market_key", "over_price", "game_time",
                                          "home_team", "away_team"])
        except Exception:
            continue
        df = df[df.market_key.isin(MARKETS)]
        if len(df):
            out[m.group(1)].append(df)
    return {d: pd.concat(v, ignore_index=True) for d, v in out.items()}


def _brier(units, key):
    xs = [x for u in units for x in u]
    return sum((x[key] - x["won"]) ** 2 for x in xs) / len(xs)


def _ll(units, key):
    xs = [x for u in units for x in u]
    total = 0.0
    for x in xs:
        p = min(max(x[key], 1e-6), 1 - 1e-6)
        total -= math.log(p) if x["won"] else math.log(1 - p)
    return total / len(xs)


def _roi(units, dec_key="best_dec"):
    xs = [x for u in units for x in u]
    if not xs:
        return float("nan")
    return sum((x[dec_key] - 1.0) if x["won"] else -1.0 for x in xs) / len(xs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()

    recs = load_recs(prekickoff_only=True)
    prices = _load_prices()
    price_dates = sorted(prices)
    drop = collections.Counter()
    rows = []
    rec_dates, outcome_dates, priced_dates = set(), set(), set()
    for (league, mid), rec in recs.items():
        if rec["kickoff"] is None or not rec["players"]:
            drop["no_kickoff_or_players"] += 1
            continue
        kick_ct = rec["kickoff"].astimezone(CT).date().isoformat()
        rec_dates.add(kick_ct)
        outcome, why = _espn_outcome(league, mid)
        if outcome is None:
            drop[why] += 1
            continue
        outcome_dates.add(kick_ct)
        px = None
        for d in reversed([d for d in price_dates if d < kick_ct]):
            cand = prices[d]
            cand = cand[cand.league == league]
            if not len(cand):
                continue
            gt = cand.game_time.map(ts)
            cand = cand[[g is not None and abs((g - rec["kickoff"]).total_seconds()) <= 3 * 3600 for g in gt]]
            cand = cand[[same_fixture(rec["home"], rec["away"], h, a) for h, a in zip(cand.home_team, cand.away_team)]]
            if len(cand):
                px, px_date = cand, d
                break
        if px is None:
            drop["match_not_priced_pre_kickoff"] += 1
            continue
        priced_dates.add(kick_ct)
        race = scorer_race(rec["players"], match_expected_goals=rec["total_mean"])
        by_player = {_norm_name(k): v for k, v in (race.get("by_player") or {}).items()}
        for (market, player), grp in px.groupby(["market_key", "player"]):
            pname = _norm_name(player)
            if not pname or "no scorer" in pname or "no goalscorer" in pname:
                continue
            p_model, _state = _lookup_player(by_player, player)
            if p_model is None:
                drop["player_not_in_race"] += 1
                continue
            if not any(_same_person(pname, a) for a in outcome["appeared"]):
                drop["dnp_void"] += 1
                continue
            decs = sorted(dec_from_american(x) for x in grp.over_price.dropna())
            if not decs:
                continue
            which = MARKETS[market]
            scorer = outcome[which]
            rows.append({
                "match": f"{league}|{mid}", "date": kick_ct, "price_file": px_date, "market": which,
                "player": player, "p_model": float(p_model), "best_dec": decs[-1],
                "median_dec": decs[len(decs) // 2], "p_implied": 1.0 / decs[-1],
                "won": int(scorer is not None and _same_person(pname, scorer)), "version": rec["version"],
            })

    inter = sorted(rec_dates & outcome_dates & priced_dates)
    report = {"coverage": {
        "prekickoff_build_dates": len(rec_dates), "outcome_dates": len(outcome_dates),
        "price_file_dates": len(price_dates), "priced_match_dates": len(priced_dates),
        "intersection_dates": len(inter), "window": [inter[0], inter[-1]] if inter else None,
        "matches_graded": len({r["match"] for r in rows}), "dropped": dict(drop)}, "markets": {}}
    print(json.dumps(report["coverage"], indent=1))

    for which in ("first", "last"):
        sub = [r for r in rows if r["market"] == which]
        if not sub:
            report["markets"][which] = {"n": 0}
            continue
        by_match = collections.defaultdict(list)
        for r in sub:
            by_match[r["match"]].append(r)
        units = list(by_match.values())
        bet_units = [u for u in ([x for x in u if x["p_model"] * x["best_dec"] > 1.0] for u in units) if u]
        bets = [x for u in bet_units for x in u]
        res = {
            "player_lines": len(sub), "matches": len(units), "dates": len({x["date"] for x in sub}),
            "hit_rate": round(sum(x["won"] for x in sub) / len(sub), 4),
            "mean_p_model": round(sum(x["p_model"] for x in sub) / len(sub), 4),
            "mean_p_implied": round(sum(x["p_implied"] for x in sub) / len(sub), 4),
            "brier_model_minus_implied": round(_brier(units, "p_model") - _brier(units, "p_implied"), 5),
            "brier_ci95": [round(v, 5) for v in boot_ci(units, lambda us: _brier(us, "p_model") - _brier(us, "p_implied"))],
            "logloss_model_minus_implied": round(_ll(units, "p_model") - _ll(units, "p_implied"), 5),
            "logloss_ci95": [round(v, 5) for v in boot_ci(units, lambda us: _ll(us, "p_model") - _ll(us, "p_implied"))],
            "ev_pos_bets": len(bets), "ev_pos_matches": len(bet_units),
            "ev_pos_wins": sum(x["won"] for x in bets),
            "roi_model_ev_pos_best": round(_roi(bet_units), 4) if bets else None,
            "roi_ci95": [round(v, 4) for v in boot_ci(bet_units, _roi)] if bets else None,
            "roi_model_ev_pos_median_price": round(_roi(bet_units, "median_dec"), 4) if bets else None,
            "by_version": dict(collections.Counter(x["version"] for x in sub)),
        }
        report["markets"][which] = res
        print(which, json.dumps(res, indent=1))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)


if __name__ == "__main__":
    main()
