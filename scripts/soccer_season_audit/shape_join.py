# -*- coding: utf-8 -*-
"""Does game shape explain the model's misses? (lane hypothesis H6)

PRE-KICKOFF features only for anything called actionable: each team's FotMob profile
over the 365 days BEFORE the fixture (>= 10 matches) -- own-perspective momentum
press, match intensity, xG for/against. Scored against the model's residual AND the
closing market's residual on the same matches: a feature that explains the model's
miss but not the market's is information the market has and the model lacks.

In-match shape (intensity, tilt, swings) is reported separately as DESCRIPTIVE only:
it is known at full time, so it can inform the live model, never a pregame price.
"""
import collections
import datetime as dt
import json
import math
import os

import audit_games as ag
import shape as shp
from common import LEAGUES, S, boot_ci, canonical_team_name, devig, find_fixture, load_outcomes, load_recs, mean

RES = {}


def corr(pairs):
    n = len(pairs)
    if n < 12:
        return float("nan")
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else float("nan")


def report(items, feat, resid, label, by_league=True):
    pairs = [(feat(i), resid(i)) for i in items if feat(i) is not None and resid(i) is not None]
    if len(pairs) < 12:
        print(f"  {label}: n={len(pairs)} too few")
        return None
    r = corr(pairs)
    ci = boot_ci(pairs, lambda s: corr(s), reps=1500)
    flag = " *" if (ci[0] > 0 or ci[1] < 0) else ""
    out = {"n": len(pairs), "r": r, "ci": ci}
    txt = ""
    if by_league:
        per = {}
        for lg in LEAGUES:
            lp = [(feat(i), resid(i)) for i in items if i["lg"] == lg and feat(i) is not None and resid(i) is not None]
            if len(lp) >= 20:
                per[lg] = {"n": len(lp), "r": corr(lp)}
        out["by_league"] = per
        txt = "  | " + " ".join(f"{lg[:6]} {v['r']:+.2f}({v['n']})" for lg, v in per.items())
    print(f"  {label:58s} n={len(pairs):4d} r={r:+.3f} [{ci[0]:+.3f},{ci[1]:+.3f}]{flag}{txt}")
    return out


def main():
    recs = load_recs()
    outc = load_outcomes()
    fd = ag.load_fd()
    rows, _, _ = ag.build_rows(recs, outc, fd, {})

    frows = [f for f in (shp.feats(m) for m in shp.load()) if f]
    hist = collections.defaultdict(list)
    for r in frows:
        hist[(r["league"], canonical_team_name(r["home"]))].append((r["date"], r["tilt"], r["intensity"], r["xg_h"], r["xg_a"]))
        hist[(r["league"], canonical_team_name(r["away"]))].append((r["date"], -r["tilt"], r["intensity"], r["xg_a"], r["xg_h"]))

    def prior(lg, team, date):
        lo = (dt.date.fromisoformat(date) - dt.timedelta(days=365)).isoformat()
        sel = [x for x in hist.get((lg, canonical_team_name(team)), []) if lo <= x[0] < date]
        if len(sel) < 10:
            return None
        return {"press": mean(x[1] for x in sel), "inten": mean(x[2] for x in sel),
                "xgf": mean(x[3] for x in sel), "xga": mean(x[4] for x in sel), "n": len(sel)}

    cur = collections.defaultdict(list)
    for r in frows:
        if r["current"]:
            cur[r["league"]].append(r)

    items, nofm = [], collections.Counter()
    for r in rows:
        m = r["m"]
        d = dt.date.fromisoformat(m["date"])
        cands = [(x["home"], x["away"], x) for x in cur.get(r["lg"], []) if abs((dt.date.fromisoformat(x["date"]) - d).days) <= 1]
        fm = find_fixture(m["home"], m["away"], cands)
        if fm is None:
            nofm[r["lg"]] += 1
            continue
        ph, pa = prior(r["lg"], fm["home"], fm["date"]), prior(r["lg"], fm["away"], fm["date"])
        it = {"lg": r["lg"], "date": r["date"], "fm": fm, "ph": ph, "pa": pa, "hg": r["hg"], "ag": r["ag"],
              "goals_res": (r["hg"] + r["ag"] - m["total_mean"]) if m["total_mean"] is not None else None,
              "home_res": (1.0 if r["hg"] > r["ag"] else 0.0) - m["p_home"] / (m["p_home"] + m["p_draw"] + m["p_away"]),
              "corner_res": None, "goals_mres": None, "home_mres": None}
        th, ta = r["o"]["teams"]["home"], r["o"]["teams"]["away"]
        if th.get("wonCorners") is not None and m["corners_h"] is not None:
            it["corner_res"] = th["wonCorners"] + ta["wonCorners"] - m["corners_h"] - m["corners_a"]
        f = r["fd"]
        if f is not None:
            avg = [ag.fnum(f.get("AvgCH")), ag.fnum(f.get("AvgCD")), ag.fnum(f.get("AvgCA"))]
            ps = [ag.fnum(f.get("PSCH")), ag.fnum(f.get("PSCD")), ag.fnum(f.get("PSCA"))]
            if None not in avg:
                it["home_mres"] = (1.0 if r["hg"] > r["ag"] else 0.0) - devig(ps if None not in ps else avg)[0]
            o, u = ag.fnum(f.get("AvgC>2.5")), ag.fnum(f.get("AvgC<2.5"))
            if o and u:
                it["goals_mres"] = r["hg"] + r["ag"] - ag.poisson_mean_from_over25(devig([o, u])[0])
        items.append(it)
    print(f"matches joined model+outcome+FotMob: {len(items)}; unjoined to FotMob by league: {dict(nofm)}")
    withp = [i for i in items if i["ph"] and i["pa"]]
    print(f"with >=10 prior FotMob matches for BOTH teams: {len(withp)}")
    RES["n"] = {"joined": len(items), "with_prior": len(withp), "unjoined": dict(nofm)}

    print("\n=== PRE-KICKOFF team shape vs residuals (model residual, then CLOSING-market residual on the same rows) ===")
    env = lambda i: (i["ph"]["xgf"] + i["pa"]["xga"] + i["pa"]["xgf"] + i["ph"]["xga"]) / 2.0
    inten = lambda i: i["ph"]["inten"] + i["pa"]["inten"]
    press = lambda i: i["ph"]["press"] - i["pa"]["press"]
    xgd = lambda i: (i["ph"]["xgf"] - i["ph"]["xga"]) - (i["pa"]["xgf"] - i["pa"]["xga"])
    both = [i for i in withp if i["goals_mres"] is not None]
    RES["xg_env_vs_goals_model"] = report(withp, env, lambda i: i["goals_res"], "prior xG environment -> goals residual (MODEL)")
    RES["xg_env_vs_goals_model_same_rows"] = report(both, env, lambda i: i["goals_res"], "  same rows as market (Europe)", by_league=False)
    RES["xg_env_vs_goals_market"] = report(both, env, lambda i: i["goals_mres"], "prior xG environment -> goals residual (MARKET)", by_league=False)
    RES["intensity_vs_goals_model"] = report(withp, inten, lambda i: i["goals_res"], "prior combined intensity -> goals residual (MODEL)")
    RES["intensity_vs_goals_market"] = report(both, inten, lambda i: i["goals_mres"], "prior combined intensity -> goals residual (MARKET)", by_league=False)
    hm = [i for i in withp if i["home_mres"] is not None]
    RES["press_vs_home_model"] = report(withp, press, lambda i: i["home_res"], "prior press diff (h-a) -> home-win residual (MODEL)")
    RES["press_vs_home_model_same_rows"] = report(hm, press, lambda i: i["home_res"], "  same rows as market", by_league=False)
    RES["press_vs_home_market"] = report(hm, press, lambda i: i["home_mres"], "prior press diff (h-a) -> home-win residual (MARKET)", by_league=False)
    RES["xgd_vs_home_model"] = report(hm, xgd, lambda i: i["home_res"], "prior xG-difference gap -> home-win residual (MODEL)", by_league=False)
    RES["xgd_vs_home_market"] = report(hm, xgd, lambda i: i["home_mres"], "prior xG-difference gap -> home-win residual (MARKET)", by_league=False)
    RES["intensity_vs_corners_model"] = report(withp, inten, lambda i: i["corner_res"], "prior combined intensity -> corners residual (MODEL)")
    RES["press_abs_vs_corners_model"] = report(withp, lambda i: abs(press(i)), lambda i: i["corner_res"], "prior |press diff| -> corners residual (MODEL)")

    print("\n=== IN-MATCH shape vs residuals (descriptive; known only at full time -> live model only) ===")
    for nm, fn in (("intensity", lambda i: i["fm"]["intensity"]), ("|tilt|", lambda i: i["fm"]["abs_tilt"]),
                   ("swings", lambda i: i["fm"]["swings"]), ("late intensity 75'+", lambda i: i["fm"]["late_intensity"])):
        srt = sorted([i for i in items if i["goals_res"] is not None], key=fn)
        k = len(srt) // 3
        terc = [srt[:k], srt[k:2 * k], srt[2 * k:]]
        g = " | ".join(f"T{j + 1} goals res {mean(x['goals_res'] for x in t):+.2f}" for j, t in enumerate(terc))
        cc = [x for x in srt if x["corner_res"] is not None]
        kc = len(cc) // 3
        c = " | ".join(f"corners res {mean(x['corner_res'] for x in t):+.2f}" for t in (cc[:kc], cc[kc:2 * kc], cc[2 * kc:]))
        print(f"  {nm:20s} {g}   ||  {c}")
        RES[f"inmatch_{nm}"] = {"goals_res_terciles": [mean(x['goals_res'] for x in t) for t in terc]}
    json.dump(RES, open(os.path.join(S, "shape_join_results.json"), "w", encoding="utf-8"), default=str)
    print("\nwrote shape_join_results.json")


if __name__ == "__main__":
    main()
