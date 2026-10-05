# -*- coding: utf-8 -*-
"""Prototype: a TIME-AWARE scorer race, fitted on early dates and tested on later ones.

Lane `soccer-last-scorer-pricing` (2026-10-05). `last_scorer_study.py` measured the
board's race (`soccer_scorer_markets.scorer_race`) pricing first and last scorer
identically while substitutes score 4.5% of FIRST goals and 35.7% of LAST goals; by
role, realised/expected was starters 1.33 / subs 0.07 on first scorer and starters
0.90 / subs 2.10 on last scorer.

THE MECHANISM. Each listed player keeps the board's own per-match goal rate
`lambda_p = -ln(1 - P_anytime)` and the match keeps its stated total; what changes is
WHEN in the 90 minutes that rate is spent:

    rho_p(t) = lambda_p * g(t) * o_p(t) / integral(g * o_p)

- `g(t)`: league-wide goal intensity by minute (goals rise late), from ESPN goal minutes.
- `o_p(t) = w(m_p) * S(t) + (1 - w(m_p)) * B(t)`: the player's on-pitch probability,
  given they play. S / B are the measured on-pitch curves of starters / substitutes
  (from ESPN substitution minutes). `w(m)` is P(starter | played) by the producer's
  `expected_minutes_share` bucket.
- Unlisted residual rate is spread by `g(t)` alone.

Then P(first = p) = sum_t rho_p(t) exp(-R(0,t)) and P(last = p) = sum_t rho_p(t) exp(-R(t,90)),
R the cumulative total rate, on a 1-minute grid. S, B, g and w are FITTED on matches
before `--split` and every number reported is on matches on/after it.

    SOCCER_AUDIT_CACHE=C:/tmp/soccer-lpb/cache py -3 last_scorer_timed_race.py [--split 2026-09-01]
"""
import argparse
import collections
import glob
import io
import json
import math
import os
import sys

from common import PRIMARY, boot_ci, load_recs
from grade_scorer_race import ESPN_CACHE, _lookup_player, _same_person

sys.path.insert(0, PRIMARY)
from syndicate.features.shared.prop_projections import _norm_name  # noqa: E402
from syndicate.features.shared.soccer_scorer_markets import player_goal_rate, scorer_race  # noqa: E402

T = 90
M_BUCKETS = 10
W_VERSION = None  # set by --w-version


def _minute(e):
    return min(T - 1, max(0, int(float((e.get("clock") or {}).get("value") or 0.0) // 60)))


def _parse(path):
    j = json.load(io.open(path, encoding="utf-8"))
    comp = ((j.get("header") or {}).get("competitions") or [{}])[0]
    if ((comp.get("status") or {}).get("type") or {}).get("name") != "STATUS_FULL_TIME":
        return None
    roles, sub_in_ids = {}, set()
    for r in j.get("rosters") or []:
        for p in r.get("roster") or []:
            sub = p.get("subbedIn")
            if isinstance(sub, dict):
                sub = sub.get("didSub")
            ath = p.get("athlete") or {}
            if p.get("starter") or sub:
                roles[str(ath.get("id"))] = {"name": _norm_name(ath.get("displayName")),
                                             "starter": bool(p.get("starter"))}
            if sub:
                sub_in_ids.add(str(ath.get("id")))
    on, off = {}, {}
    for e in j.get("keyEvents") or []:
        if str((e.get("type") or {}).get("type") or "") != "substitution":
            continue
        ids = [str((x.get("athlete") or {}).get("id")) for x in e.get("participants") or []]
        for pid in ids:
            if pid in sub_in_ids:
                on[pid] = _minute(e)
            elif pid in roles:
                off[pid] = _minute(e)
    goals = []
    for e in j.get("keyEvents") or []:
        if e.get("scoringPlay") and not e.get("shootout"):
            parts = e.get("participants") or []
            goals.append({"key": ((e.get("period") or {}).get("number") or 0, float((e.get("clock") or {}).get("value") or 0)),
                          "minute": _minute(e), "own_goal": str((e.get("type") or {}).get("type")) == "own-goal",
                          "scorer": _norm_name(((parts[0] if parts else {}).get("athlete") or {}).get("displayName"))})
    goals.sort(key=lambda g: g["key"])
    date = str(comp.get("date") or (j.get("header") or {}).get("competitions", [{}])[0].get("date") or "")[:10]
    return {"date": date, "roles": roles, "on": on, "off": off, "goals": goals}


def _fit(matches, recs):
    s_on = [0.0] * T
    b_on = [0.0] * T
    n_s = n_b = 0
    g = [1e-9] * T
    for m in matches:
        for pid, info in m["roles"].items():
            if info["starter"]:
                end = m["off"].get(pid, T)
                n_s += 1
                for t in range(min(end, T)):
                    s_on[t] += 1
            else:
                start = m["on"].get(pid)
                if start is None:
                    continue
                n_b += 1
                for t in range(start, T):
                    b_on[t] += 1
        for goal in m["goals"]:
            if not goal["own_goal"]:
                g[goal["minute"]] += 1
    S = [x / max(1, n_s) for x in s_on]
    B = [x / max(1, n_b) for x in b_on]
    tot = sum(g)
    G = [x * T / tot for x in g]
    # w(m): P(starter | played) by expected_minutes_share bucket
    counts = [[0, 0] for _ in range(M_BUCKETS)]
    for key, m in matches_by_key(matches).items():
        rec = recs.get(key)
        if not rec or (W_VERSION and rec["version"] != W_VERSION):
            continue
        for pl in rec["players"]:
            share = pl.get("expected_minutes_share")
            if share is None:
                continue
            name = _norm_name(pl.get("player_name"))
            for info in m["roles"].values():
                if _same_person(name, info["name"]):
                    b = min(M_BUCKETS - 1, int(float(share) * M_BUCKETS))
                    counts[b][0 if info["starter"] else 1] += 1
                    break
    W = [(c[0] + 1) / (c[0] + c[1] + 2) for c in counts]
    return S, B, G, W


def matches_by_key(matches):
    return {m["key"]: m for m in matches}


def timed_race(players, total_mean, S, B, G, W):
    """{norm_name: (p_first, p_last)} for listed players, same inputs as `scorer_race`."""
    rates = {}
    profiles = {}
    listed = 0.0
    for pl in players:
        name = _norm_name(pl.get("player_name"))
        lam = player_goal_rate(pl.get("anytime_scorer_probability"))
        if not name or lam is None:
            continue
        share = pl.get("expected_minutes_share")
        w = W[min(M_BUCKETS - 1, int(float(share) * M_BUCKETS))] if share is not None else 1.0
        o = [G[t] * (w * S[t] + (1 - w) * B[t]) for t in range(T)]
        z = sum(o) or 1.0
        profiles[name] = [lam * x / z for x in o]
        rates[name] = lam
        listed += lam
    lam_total = max(float(total_mean), listed) if total_mean is not None else listed
    resid = max(0.0, lam_total - listed)
    total_t = [resid * G[t] / T + sum(p[t] for p in profiles.values()) for t in range(T)]
    cum = [0.0]
    for t in range(T):
        cum.append(cum[-1] + total_t[t])
    out = {}
    for name, prof in profiles.items():
        # discrete: arrival in minute t at rate prof[t]; first = none before t, last = none after t
        first = sum(prof[t] * math.exp(-cum[t]) * _within(total_t[t]) for t in range(T))
        last = sum(prof[t] * math.exp(-(cum[T] - cum[t + 1])) * _within(total_t[t]) for t in range(T))
        out[name] = (first, last)
    return out


def _within(rate):
    """P(the arrival in a minute is the first of that minute) ~ (1 - e^-r)/r, -> 1 for small r."""
    return (1 - math.exp(-rate)) / rate if rate > 1e-12 else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="2026-09-01")
    ap.add_argument("--w-version", default="post0907",
                    help="fit w(m) only on builds of this model version (the minutes field changed at 09-07)")
    ap.add_argument("--out")
    args = ap.parse_args()
    global W_VERSION
    W_VERSION = args.w_version or None

    recs = load_recs(prekickoff_only=True)
    parsed = []
    for path in glob.glob(os.path.join(ESPN_CACHE, "*.json")):
        m = _parse(path)
        if m is None:
            continue
        league, mid = os.path.basename(path)[:-5].rsplit("_", 1)
        m["key"] = (league, mid)
        parsed.append(m)
    fit = [m for m in parsed if m["date"] and m["date"] < args.split]
    test = [m for m in parsed if m["date"] and m["date"] >= args.split
            and (not W_VERSION or (recs.get(m["key"]) or {}).get("version") == W_VERSION)]
    S, B, G, W = _fit(fit, recs)

    cal = {(v, w, r): [0.0, 0] for v in ("old", "new") for w in ("first", "last") for r in ("starter", "sub")}
    units = []
    for m in test:
        rec = recs.get(m["key"])
        if not rec or not rec["players"]:
            continue
        old = {_norm_name(k): v for k, v in (scorer_race(rec["players"], match_expected_goals=rec["total_mean"]).get("by_player") or {}).items()}
        new = timed_race(rec["players"], rec["total_mean"], S, B, G, W)
        q = [g for g in m["goals"] if not g["own_goal"]]
        rows = []
        for info in m["roles"].values():
            p_old, _ = _lookup_player(old, info["name"])
            p_new, _ = _lookup_player(new, info["name"])
            if p_old is None or p_new is None:
                continue
            role = "starter" if info["starter"] else "sub"
            for which, idx in (("first", 0), ("last", 1)):
                goal = (q[0] if which == "first" else q[-1]) if q else None
                won = int(goal is not None and _same_person(info["name"], goal["scorer"]))
                pn = p_new[idx]
                cal[("old", which, role)][0] += p_old
                cal[("new", which, role)][0] += pn
                cal[("old", which, role)][1] += won
                cal[("new", which, role)][1] += won
                rows.append((which, p_old, pn, won))
        if rows:
            units.append(rows)

    def ll(us, which, idx):
        xs = [x for u in us for x in u if x[0] == which]
        return -sum(math.log(max(1e-6, x[idx])) if x[3] else math.log(max(1e-6, 1 - x[idx])) for x in xs) / len(xs)

    report = {"fit_matches": len(fit), "test_matches_scored": len(units), "split": args.split,
              "curves": {"starter_on_at_60": round(S[60], 3), "starter_on_at_85": round(S[85], 3),
                         "sub_on_at_60": round(B[60], 3), "sub_on_at_85": round(B[85], 3),
                         "goal_intensity_first15_vs_last15": round(sum(G[:15]) / sum(G[75:]), 3),
                         "w_by_minutes_share": [round(x, 2) for x in W]},
              "calibration_realised_over_expected": {
                  f"{v}/{w}/{r}": round(c[1] / c[0], 3) if c[0] else None for (v, w, r), c in cal.items()},
              "logloss": {}}
    for which in ("first", "last"):
        d = lambda us, w=which: ll(us, w, 2) - ll(us, w, 1)  # noqa: E731  new minus old
        report["logloss"][which] = {"old": round(ll(units, which, 1), 5), "new": round(ll(units, which, 2), 5),
                                    "new_minus_old": round(d(units), 5), "ci95": [round(x, 5) for x in boot_ci(units, d)]}
    print(json.dumps(report, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)


if __name__ == "__main__":
    main()
