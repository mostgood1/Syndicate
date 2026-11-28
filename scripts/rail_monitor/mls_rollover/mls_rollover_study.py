"""MLS ratings season-rollover study (lane mls-ratings-season-rollover, 2026-11-27). Read-only: three public GETs to
ASA /mls/games/xgoals (seasons 2024, 2025, 2026). Nothing on the fleet is read or written.

Question: at the start of a season, should a team's rating inputs (xG for / against per match) come from the new
season's games so far (what the code does once its season pick is fixed), from last season, or from a mix?

For every match of the 2025 and 2026 seasons, each team's inputs are built only from games BEFORE the match's UTC day:
  A  season-to-date only (0 games -> league mean: every team equal, as the promoted prior makes them today)
  B  last season's full aggregate (a team with none, e.g. expansion -> league mean)
  C<G> B while the team has fewer than G games this season, then A        (G = 5, 10, 17)
  D<W> games-weighted window: this season's n games plus max(0, W - n) games at last season's rate  (W = 17, 34)
Expected goals: lambda_home = gh * (xgf_h / mu) * (xga_a / mu), lambda_away = ga * (xgf_a / mu) * (xga_h / mu), with
mu = last season's mean xG per team-match and gh / ga = last season's home / away goals per match. A stand-in for the
engine's rating -> simulation mapping, good enough to RANK input rules, not to reproduce the engine's numbers.
Scores: mean Poisson log-likelihood of the actual goals (higher is better) and 1X2 Brier (lower is better), by the
SMALLER of the two teams' games-this-season before the match, with a paired difference vs A and its 95% interval.

  py -3 mls_rollover_study.py            (or the fleet venv: requests only)
"""
import math
import statistics
from collections import defaultdict

import requests

ASA = "https://app.americansocceranalysis.com/api/v1/mls/games/xgoals"
UA = {"User-Agent": "syndicate-readonly-study"}


def fetch(season):
    r = requests.get(ASA, params={"season_name": str(season)}, headers=UA, timeout=60)
    r.raise_for_status()
    out = []
    for g in r.json():
        if g.get("home_goals") is None or g.get("home_team_xgoals") is None:
            continue
        out.append({"day": str(g["date_time_utc"])[:10], "h": g["home_team_id"], "a": g["away_team_id"],
                    "hg": int(g["home_goals"]), "ag": int(g["away_goals"]),
                    "hx": float(g["home_team_xgoals"]), "ax": float(g["away_team_xgoals"])})
    out.sort(key=lambda g: g["day"])
    return out


def season_agg(games):
    s = defaultdict(lambda: [0, 0.0, 0.0])  # n, xg_for, xg_against
    for g in games:
        for t, f, a in ((g["h"], g["hx"], g["ax"]), (g["a"], g["ax"], g["hx"])):
            s[t][0] += 1
            s[t][1] += f
            s[t][2] += a
    return {t: (n, f / n, a / n) for t, (n, f, a) in s.items() if n}


def pois(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def score(lh, la, hg, ag):
    ll = math.log(max(pois(hg, lh), 1e-12)) + math.log(max(pois(ag, la), 1e-12))
    ph = [pois(k, lh) for k in range(11)]
    pa = [pois(k, la) for k in range(11)]
    pH = sum(ph[i] * pa[j] for i in range(11) for j in range(11) if i > j)
    pD = sum(ph[i] * pa[i] for i in range(11))
    pA = 1 - pH - pD
    y = (1, 0, 0) if hg > ag else (0, 1, 0) if hg == ag else (0, 0, 1)
    brier = (pH - y[0]) ** 2 + (pD - y[1]) ** 2 + (pA - y[2]) ** 2
    return ll, brier


RULES = ["A", "B", "C5", "C10", "C17", "D17", "D34"]


def inputs(rule, n, cur, prev, mu):
    """(xgf, xga) for one team under `rule`; cur = (n, f, a) to date or None; prev = (n, f, a) last season or None."""
    cf, ca = (cur[1], cur[2]) if cur and cur[0] > 0 else (None, None)
    pf, pa = (prev[1], prev[2]) if prev else (None, None)
    if rule == "A":
        return (cf, ca) if cf is not None else (mu, mu)
    if rule == "B":
        return (pf, pa) if pf is not None else (mu, mu)
    if rule.startswith("C"):
        g = int(rule[1:])
        if n < g and pf is not None:
            return pf, pa
        return (cf, ca) if cf is not None else (mu, mu)
    w = int(rule[1:])
    fill = max(0, w - n) if pf is not None else 0
    if n + fill == 0:
        return mu, mu
    f = ((n * cf if n else 0.0) + fill * (pf or 0.0)) / (n + fill)
    a = ((n * ca if n else 0.0) + fill * (pa or 0.0)) / (n + fill)
    return f, a


def bucket(n):
    return "0" if n == 0 else "1-4" if n < 5 else "5-9" if n < 10 else "10-16" if n < 17 else "17-33" if n < 34 else "34+"


def run(season, games, prev_games):
    prev = season_agg(prev_games)
    mu = statistics.mean([v for t in prev.values() for v in (t[1],)])
    gh = statistics.mean(g["hg"] for g in prev_games)
    ga = statistics.mean(g["ag"] for g in prev_games)
    to_date = defaultdict(lambda: [0, 0.0, 0.0])
    res = defaultdict(lambda: defaultdict(list))  # bucket -> rule -> [(ll, brier)]
    day_games = defaultdict(list)
    for g in games:
        day_games[g["day"]].append(g)
    for day in sorted(day_games):
        for g in day_games[day]:
            nh, na = to_date[g["h"]][0], to_date[g["a"]][0]
            cur = {t: ((v[0], v[1] / v[0], v[2] / v[0]) if v[0] else None) for t, v in ((g["h"], to_date[g["h"]]), (g["a"], to_date[g["a"]]))}
            b = bucket(min(nh, na))
            for rule in RULES:
                fh, ah = inputs(rule, nh, cur[g["h"]], prev.get(g["h"]), mu)
                fa, aa = inputs(rule, na, cur[g["a"]], prev.get(g["a"]), mu)
                lh = max(0.05, gh * (fh / mu) * (aa / mu))
                la = max(0.05, ga * (fa / mu) * (ah / mu))
                res[b][rule].append(score(lh, la, g["hg"], g["ag"]))
        for g in day_games[day]:  # this day's games count only from the next day on
            for t, f, a in ((g["h"], g["hx"], g["ax"]), (g["a"], g["ax"], g["hx"])):
                to_date[t][0] += 1
                to_date[t][1] += f
                to_date[t][2] += a
    return res


def report(label, res):
    print(f"\n== {label}")
    order = ["0", "1-4", "5-9", "10-16", "17-33", "34+"]
    print(f"{'bucket':>7} {'n':>4} " + " ".join(f"{r:>16}" for r in RULES))
    for b in order + ["ALL"]:
        rows = {r: (res[b][r] if b != "ALL" else [x for bb in order for x in res[bb][r]]) for r in RULES}
        n = len(rows["A"])
        if not n:
            continue
        cells = []
        for r in RULES:
            d_ll = [x[0] - y[0] for x, y in zip(rows[r], rows["A"])]
            m = statistics.mean(d_ll)
            se = statistics.stdev(d_ll) / math.sqrt(n) if n > 1 else 0.0
            cells.append(f"{statistics.mean(x[0] for x in rows[r]):+.3f}/{m:+.3f}" if r == "A" else f"{m:+.4f}+-{1.96 * se:.4f}")
        print(f"{b:>7} {n:>4} " + " ".join(f"{c:>16}" for c in cells))
    print("  (A column: mean log-lik / 0; others: mean log-lik minus A, 95% half-width; POSITIVE = better than A)")
    print(f"{'bucket':>7} {'n':>4} " + " ".join(f"{r:>9}" for r in RULES) + "   (1X2 Brier, lower is better)")
    for b in order + ["ALL"]:
        rows = {r: (res[b][r] if b != "ALL" else [x for bb in order for x in res[bb][r]]) for r in RULES}
        n = len(rows["A"])
        if n:
            print(f"{b:>7} {n:>4} " + " ".join(f"{statistics.mean(x[1] for x in rows[r]):9.4f}" for r in RULES))


if __name__ == "__main__":
    data = {s: fetch(s) for s in (2024, 2025, 2026)}
    for s in data:
        print(f"season {s}: {len(data[s])} games with goals and xG, {data[s][0]['day']} .. {data[s][-1]['day']}")
    both = defaultdict(lambda: defaultdict(list))
    for s in (2025, 2026):
        res = run(s, data[s], data[s - 1])
        report(f"season {s} (last season {s - 1})", res)
        for b, rr in res.items():
            for r, v in rr.items():
                both[b][r].extend(v)
    report("2025 + 2026 pooled", both)
