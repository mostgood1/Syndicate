# -*- coding: utf-8 -*-
"""Game shape from FotMob's per-minute momentum, overall and by league.

Sources: the committed 2-year research cache (2024-08-09..2026-08-22) plus this
session's season harvests. Current season = 2026-27 in Europe, 2026 in MLS.

FotMob momentum is their MODEL output on a display-minute clock (positive =
home pressure -- asserted below from the data, not assumed). Goals and shots
carry ELAPSED seconds (first-half stoppage included), so a goal's display
minute is elapsed minus first-half stoppage once past 45.
"""
import collections
import gzip
import json
import math
import os
import random

S = os.environ.get("SOCCER_AUDIT_CACHE") or os.path.dirname(os.path.abspath(__file__))
PRIMARY = os.environ.get("SYNDICATE_REPO_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
random.seed(7)


def load():
    with gzip.open(os.path.join(PRIMARY, "reports", "soccer_backtest", "fotmob_2y.json.gz"), "rt", encoding="utf-8") as h:
        ms = json.load(h)["matches"]
    seen = {str(m["match_id"]) for m in ms}
    for fn in ("fotmob_season.json", "fotmob_season3.json"):
        p = os.path.join(S, fn)
        if not os.path.exists(p):
            print("MISSING", fn)
            continue
        for m in json.load(open(p, encoding="utf-8"))["matches"]:
            if str(m["match_id"]) not in seen:
                ms.append(m)
                seen.add(str(m["match_id"]))
    return ms


def season(m):
    y, mo = int(m["date"][:4]), int(m["date"][5:7])
    if m["league"] == "mls":
        return str(y)
    start = y if mo >= 7 else y - 1
    return f"{start}-{(start + 1) % 100:02d}"


def current(m):
    return season(m) in ("2026-27", "2026") and m["date"] >= "2026-07-15"


def disp_minute(m, t_seconds):
    fhs = float(m.get("first_half_stoppage_min") or 2.0)
    mt = t_seconds / 60.0
    return mt if mt <= 45.0 + fhs else mt - fhs


def feats(m):
    mom = [(p["t"] / 60.0, float(p["value"])) for p in (m.get("vendor_momentum") or [])]
    if len(mom) < 60:
        return None
    vals = [v for _, v in mom]
    n = len(vals)
    mean = sum(vals) / n
    roll = [sum(vals[max(0, i - 4):i + 1]) / len(vals[max(0, i - 4):i + 1]) for i in range(n)]
    swings, last = 0, 0
    for r in roll:
        s = 1 if r > 10 else (-1 if r < -10 else 0)
        if s and last and s != last:
            swings += 1
        if s:
            last = s
    late = [v for mi, v in mom if mi >= 75]
    goals = m.get("goals") or []
    hg = sum(1 for g in goals if g["home"])
    ag = len(goals) - hg
    shots = m.get("shots") or []
    gm = [disp_minute(m, g["t"]) for g in goals]
    reds = sum(1 for e in (m.get("events") or []) if (e.get("card") or "").lower().startswith("red"))
    return {
        "league": m["league"], "season": season(m), "current": current(m), "date": m["date"],
        "home": m.get("home_team"), "away": m.get("away_team"),
        "tilt": mean, "abs_tilt": abs(mean), "intensity": sum(abs(v) for v in vals) / n,
        "volatility": math.sqrt(sum((v - mean) ** 2 for v in vals) / n), "swings": swings,
        "late_tilt": (sum(late) / len(late)) if late else 0.0,
        "late_intensity": (sum(abs(v) for v in late) / len(late)) if late else 0.0,
        "hg": hg, "ag": ag, "goals": hg + ag,
        "goals_2h": sum(1 for x in gm if x > 45.0), "goals_76p": sum(1 for x in gm if x > 75.0),
        "xg_h": sum(s["xg"] for s in shots if s["home"]), "xg_a": sum(s["xg"] for s in shots if not s["home"]),
        "shots": len(shots), "reds": reds,
    }


def boot_ci(groups, stat, reps=1000):
    """Bootstrap over MATCHES (the unit), 95% percentile CI."""
    vals = []
    k = len(groups)
    for _ in range(reps):
        vals.append(stat([groups[random.randrange(k)] for _ in range(k)]))
    vals.sort()
    return vals[int(0.025 * reps)], vals[int(0.975 * reps)]


def corr(xs, ys):
    n = len(xs)
    if n < 10:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sxy / (sx * sy) if sx and sy else float("nan")


def auc(pairs):
    """Mann-Whitney AUC by average ranks, O(n log n)."""
    n_pos = sum(1 for _, y in pairs if y)
    n_neg = len(pairs) - n_pos
    if not n_pos or not n_neg:
        return float("nan")
    order = sorted(range(len(pairs)), key=lambda i: pairs[i][0])
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and pairs[order[j + 1]][0] == pairs[order[i]][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    rank_sum = sum(ranks[i] for i in range(len(pairs)) if pairs[i][1])
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def next_goal_pairs(m):
    """(tilt over the 10 display minutes before a goal, scored_by_home), goals >= 12'."""
    mom = [(p["t"] / 60.0, float(p["value"])) for p in (m.get("vendor_momentum") or [])]
    out = []
    for g in m.get("goals") or []:
        dm = disp_minute(m, g["t"])
        if dm < 12:
            continue
        w = [v for mi, v in mom if dm - 10.0 <= mi < dm - 0.5]
        if len(w) >= 5:
            out.append((sum(w) / len(w), bool(g["home"])))
    return out


def table(rows, matches_by_id, label):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["league"]].append(r)
    by["ALL"] = list(rows)
    print(f"\n=== {label} ===")
    print(f"{'league':19s} {'n':>5s} {'goals':>6s} {'95%CI':>13s} {'draw%':>6s} {'2H%':>5s} {'76+%':>5s} {'76+ CI':>13s} "
          f"{'inten':>6s} {'|tilt|':>6s} {'swing':>5s} {'r(int,G)':>8s} {'domWin%':>7s} {'nextAUC':>7s} {'AUC CI':>13s}")
    result = {}
    for lg in sorted(by, key=lambda k: (k == "ALL", k)):
        g = by[lg]
        n = len(g)
        if n < 15:
            continue
        goals = sum(r["goals"] for r in g) / n
        gci = boot_ci(g, lambda s: sum(r["goals"] for r in s) / len(s))
        draw = sum(1 for r in g if r["hg"] == r["ag"]) / n
        tg = sum(r["goals"] for r in g)
        h2 = sum(r["goals_2h"] for r in g) / max(tg, 1)
        l76 = sum(r["goals_76p"] for r in g) / max(tg, 1)
        lci = boot_ci(g, lambda s: sum(r["goals_76p"] for r in s) / max(sum(r["goals"] for r in s), 1))
        inten = sum(r["intensity"] for r in g) / n
        at = sum(r["abs_tilt"] for r in g) / n
        sw = sum(r["swings"] for r in g) / n
        rig = corr([r["intensity"] for r in g], [r["goals"] for r in g])
        dec = [r for r in g if r["hg"] != r["ag"] and abs(r["tilt"]) > 1.0]
        dom = sum(1 for r in dec if (r["tilt"] > 0) == (r["hg"] > r["ag"])) / max(len(dec), 1)
        pair_groups = [next_goal_pairs(matches_by_id[r["_id"]]) for r in g]
        flat = [p for grp in pair_groups for p in grp]
        a = auc(flat)
        aci = boot_ci([grp for grp in pair_groups if grp], lambda s: auc([p for grp in s for p in grp]), reps=300) if len(flat) > 40 else (float("nan"), float("nan"))
        print(f"{lg:19s} {n:5d} {goals:6.2f} [{gci[0]:4.2f},{gci[1]:4.2f}] {100*draw:6.1f} {100*h2:5.1f} {100*l76:5.1f} "
              f"[{100*lci[0]:4.1f},{100*lci[1]:4.1f}] {inten:6.1f} {at:6.1f} {sw:5.1f} {rig:8.3f} {100*dom:7.1f} {a:7.3f} [{aci[0]:.3f},{aci[1]:.3f}]")
        result[lg] = {"n": n, "goals_per_match": goals, "goals_ci": gci, "draw_rate": draw, "second_half_goal_share": h2,
                      "late_76plus_goal_share": l76, "late_ci": lci, "intensity": inten, "abs_tilt": at, "swings": sw,
                      "r_intensity_goals": rig, "dominant_side_win_rate": dom, "dominant_n": len(dec),
                      "next_goal_auc": a, "next_goal_auc_ci": aci, "next_goal_n": len(flat)}
    return result


def main():
    ms = load()
    by_id = {}
    rows = []
    for m in ms:
        f = feats(m)
        if f is None:
            continue
        f["_id"] = str(m["match_id"])
        by_id[f["_id"]] = m
        rows.append(f)
    print(f"matches with momentum: {len(rows)} (of {len(ms)})")
    cov = collections.Counter((r["league"], r["season"]) for r in rows)
    for k in sorted(cov):
        print("  ", k, cov[k])
    # sign convention check: positive tilt should go with home goal difference
    print("sign check r(tilt, home GD) =", round(corr([r["tilt"] for r in rows], [r["hg"] - r["ag"] for r in rows]), 3))

    past = [r for r in rows if not r["current"]]
    cur = [r for r in rows if r["current"]]
    out = {"past_2y": table(past, by_id, "PAST TWO SEASONS (2024-25, 2025-26; MLS 2024-25)"),
           "current": table(cur, by_id, "CURRENT SEASON (2026-27; MLS 2026) through 2026-09-14")}

    # team shape index: per (league, season, team) average own-perspective pressure and match intensity
    teams = collections.defaultdict(lambda: {"n": 0, "press": 0.0, "inten": 0.0, "swings": 0.0, "goals_for": 0, "goals_against": 0, "xg_for": 0.0, "xg_against": 0.0})
    for r in rows:
        for side, sign in (("home", 1), ("away", -1)):
            t = teams[(r["league"], r["season"], r[side])]
            t["n"] += 1
            t["press"] += sign * r["tilt"]
            t["inten"] += r["intensity"]
            t["swings"] += r["swings"]
            t["goals_for"] += r["hg"] if side == "home" else r["ag"]
            t["goals_against"] += r["ag"] if side == "home" else r["hg"]
            t["xg_for"] += r["xg_h"] if side == "home" else r["xg_a"]
            t["xg_against"] += r["xg_a"] if side == "home" else r["xg_h"]
    out["team_shape"] = {"|".join(k): v for k, v in teams.items()}
    out["match_rows"] = [{k: v for k, v in r.items()} for r in rows if r["current"] or r["season"] in ("2025-26", "2025")]
    json.dump(out, open(os.path.join(S, "shape_by_league.json"), "w", encoding="utf-8"))
    print("\nwrote shape_by_league.json")


if __name__ == "__main__":
    main()
