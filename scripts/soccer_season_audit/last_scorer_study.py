# -*- coding: utf-8 -*-
"""How last goalscorers differ from first goalscorers, and where the race model misses.

Lane `soccer-last-scorer-pricing` (2026-10-05). `grade_scorer_race.py` found last
scorer losing -66.8% at the price against -34.8% for first scorer, on the SAME
probability (the board prices last scorer as first under time-reversal symmetry).

Two readings, neither needing prices:

1. THE GOAL RECORD (every full-time ESPN summary in the cache): who scores the first
   and the last qualifying goal -- starter or substitute, minute, and game state
   before the goal (trailing / level / leading, from the running score; matches with
   an own goal are left out of the game-state split because ESPN's team field on an
   own goal is not trusted here).
2. THE MODEL'S CALIBRATION, split by starter / substitute: over every APPEARED player
   in the board's race (`scorer_race` on pre-kickoff builds), sum of the model's
   probability against realised first / last scorers. If time-reversal held, the
   first and last ratios would match.

    SOCCER_AUDIT_CACHE=C:/tmp/soccer-lpb/cache py -3 last_scorer_study.py [--out report.json]
"""
import argparse
import collections
import glob
import io
import json
import os
import sys

from common import PRIMARY, boot_ci, load_recs
from grade_scorer_race import ESPN_CACHE, _lookup_player, _same_person

sys.path.insert(0, PRIMARY)
from syndicate.features.shared.prop_projections import _norm_name  # noqa: E402
from syndicate.features.shared.soccer_scorer_markets import scorer_race  # noqa: E402


def _summary(path):
    j = json.load(io.open(path, encoding="utf-8"))
    comp = ((j.get("header") or {}).get("competitions") or [{}])[0]
    if ((comp.get("status") or {}).get("type") or {}).get("name") != "STATUS_FULL_TIME":
        return None
    side_of_team = {str((c.get("team") or {}).get("id")): c.get("homeAway") for c in comp.get("competitors") or []}
    players = {}
    for r in j.get("rosters") or []:
        for p in r.get("roster") or []:
            sub = p.get("subbedIn")
            if isinstance(sub, dict):
                sub = sub.get("didSub")
            if not (p.get("starter") or sub):
                continue
            name = _norm_name((p.get("athlete") or {}).get("displayName"))
            players[name] = {"starter": bool(p.get("starter")), "side": r.get("homeAway")}
    goals, own_goal = [], False
    for e in j.get("keyEvents") or []:
        if not e.get("scoringPlay") or e.get("shootout"):
            continue
        is_og = str((e.get("type") or {}).get("type") or "") == "own-goal"
        own_goal = own_goal or is_og
        parts = e.get("participants") or []
        name = _norm_name(((parts[0] if parts else {}).get("athlete") or {}).get("displayName"))
        goals.append({
            "key": ((e.get("period") or {}).get("number") or 0, float((e.get("clock") or {}).get("value") or 0.0)),
            "minute": float((e.get("clock") or {}).get("value") or 0.0) / 60.0,
            "side": side_of_team.get(str((e.get("team") or {}).get("id"))),
            "scorer": name, "own_goal": is_og,
        })
    goals.sort(key=lambda g: g["key"])
    return {"players": players, "goals": goals, "own_goal": own_goal}


def _scorer_role(players, name):
    for k, v in players.items():
        if _same_person(name, k):
            return "starter" if v["starter"] else "sub"
    return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()

    # ---- 1. the goal record
    record = {"first": collections.Counter(), "last": collections.Counter()}
    minutes = {"first": [], "last": []}
    state = {"first": collections.Counter(), "last": collections.Counter()}
    summaries = {}
    for path in glob.glob(os.path.join(ESPN_CACHE, "*.json")):
        s = _summary(path)
        if s is None:
            continue
        base = os.path.basename(path)[:-5]
        league, mid = base.rsplit("_", 1)
        summaries[(league, mid)] = s
        q = [g for g in s["goals"] if not g["own_goal"]]
        if not q:
            continue
        for which, g in (("first", q[0]), ("last", q[-1])):
            record[which][_scorer_role(s["players"], g["scorer"])] += 1
            minutes[which].append(g["minute"])
            if not s["own_goal"]:
                score = {"home": 0, "away": 0}
                for h in s["goals"]:
                    if h is g:
                        break
                    if h["side"] in score:
                        score[h["side"]] += 1
                other = "away" if g["side"] == "home" else "home"
                if g["side"] in score:
                    diff = score[g["side"]] - score[other]
                    state[which]["trailing" if diff < 0 else "level" if diff == 0 else "leading"] += 1
    out = {"goal_record": {}}
    for which in ("first", "last"):
        n = sum(record[which].values())
        mins = sorted(minutes[which])
        out["goal_record"][which] = {
            "matches_with_goal": n,
            "sub_share": round(record[which]["sub"] / n, 4) if n else None,
            "unknown_role": record[which]["unknown"],
            "median_minute": round(mins[len(mins) // 2], 1) if mins else None,
            "game_state": dict(state[which]),
        }

    # ---- 2. model calibration by role
    recs = load_recs(prekickoff_only=True)
    cal = {w: collections.defaultdict(lambda: [0.0, 0, 0]) for w in ("first", "last")}
    units = collections.defaultdict(list)
    for (league, mid), rec in recs.items():
        s = summaries.get((league, mid))
        if s is None or not rec["players"]:
            continue
        q = [g for g in s["goals"] if not g["own_goal"]]
        race = scorer_race(rec["players"], match_expected_goals=rec["total_mean"])
        by_player = {_norm_name(k): v for k, v in (race.get("by_player") or {}).items()}
        rows = []
        for name, info in s["players"].items():
            p, _st = _lookup_player(by_player, name)
            if p is None:
                continue
            role = "starter" if info["starter"] else "sub"
            for which, g in (("first", q[0] if q else None), ("last", q[-1] if q else None)):
                won = int(g is not None and _same_person(name, g["scorer"]))
                c = cal[which][role]
                c[0] += p
                c[1] += won
                c[2] += 1
                rows.append((which, role, p, won))
        units[(league, mid)] = rows
    out["calibration"] = {}
    unit_list = list(units.values())
    for which in ("first", "last"):
        out["calibration"][which] = {}
        for role in ("starter", "sub"):
            p_sum, wins, n = cal[which][role]
            ratio = (lambda us, w=which, r=role: (
                sum(x[3] for u in us for x in u if x[0] == w and x[1] == r)
                / max(1e-9, sum(x[2] for u in us for x in u if x[0] == w and x[1] == r))))
            out["calibration"][which][role] = {
                "players": n, "model_expected": round(p_sum, 1), "realised": wins,
                "realised_over_expected": round(wins / p_sum, 3) if p_sum else None,
                "ci95": [round(v, 3) for v in boot_ci(unit_list, ratio)],
            }
    out["matches_in_calibration"] = len(unit_list)
    print(json.dumps(out, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)


if __name__ == "__main__":
    main()
