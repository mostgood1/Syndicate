# -*- coding: utf-8 -*-
"""Game markets, season to date: 1X2, O/U 2.5, Asian handicap, BTTS, team goals, corners.

Model: production `recommendations_*.json` (final artifacts; the 09-02 snapshot is the
pre-kickoff control). Outcomes: ESPN box scores. Prices: football-data.co.uk CLOSING
average (typical) and maximum (best) for 1X2 / O/U 2.5 / AH; production `game_markets`
(last PRE-KICKOFF capture) for BTTS and corners.

Every CI is a bootstrap over MATCHES. Betting thresholds are pre-registered
(2/4/6/8 pp vs the de-vigged market) and selected only leave-one-date-out.
"""
import collections
import datetime as dt
import glob
import io
import json
import math
import os

import pandas as pd

from common import (LEAGUES, PRIMARY, S, ah_home_value, boot_ci, dec_from_american, devig, find_fixture,
                    implied_poisson_goals, load_outcomes, load_recs, mean, nb_sf, norm_scores, poisson_pmf, ts)

Ts = (0.02, 0.04, 0.06, 0.08)
ORDER = ["ALL"] + LEAGUES
RESULTS = {}


def fnum(x):
    try:
        v = float(str(x).strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 1.0 else None


def flt(x):
    try:
        v = float(str(x).strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- loaders

def load_fd():
    out = collections.defaultdict(list)
    for lg in LEAGUES:
        f = pd.read_csv(os.path.join(S, "fd", lg + ".csv"), encoding="latin-1")
        f.columns = [str(c).replace("ï»¿", "").replace("﻿", "") for c in f.columns]
        if lg == "mls":
            f = f[f["Season"].astype(str).str.contains("2026")].rename(
                columns={"Home": "HomeTeam", "Away": "AwayTeam", "HG": "FTHG", "AG": "FTAG"})
        for r in f.to_dict("records"):
            try:
                r["_date"] = dt.datetime.strptime(str(r["Date"]).strip(), "%d/%m/%Y").date()
            except ValueError:
                continue
            out[lg].append(r)
    return out


def load_game_markets():
    events = {}
    for f in glob.glob(os.path.join(S, "prod", "game_markets", "*.json")):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            j = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(j, dict):
            continue
        gen = ts(j.get("generated_at"))
        lg = j.get("league")
        for r in j.get("rows") or []:
            gt = ts(r.get("game_time"))
            if gen is None or gt is None or gen >= gt:
                continue                                   # pre-kickoff captures only
            e = events.setdefault((lg, r.get("event_id")), {"league": lg, "home": r.get("home_team"),
                                                             "away": r.get("away_team"), "game_time": gt, "caps": {}})
            e["caps"].setdefault(gen, []).append(r)
    for e in events.values():
        last = max(e["caps"])
        e["rows"], e["captured_at"] = e["caps"][last], last
        del e["caps"]
    return events


def btts_market(rows):
    by_book = collections.defaultdict(dict)
    for r in rows:
        if r.get("market_key") == "btts":
            by_book[r.get("book")][str(r.get("side")).lower()] = dec_from_american(r["price"])
    fairs, yes, no = [], [], []
    for sides in by_book.values():
        if "yes" in sides and "no" in sides:
            fairs.append(devig([sides["yes"], sides["no"]])[0])
            yes.append(sides["yes"])
            no.append(sides["no"])
    if not fairs:
        return None
    return {"fair": mean(fairs), "books": len(fairs), "best": (max(yes), max(no)),
            "med": (sorted(yes)[len(yes) // 2], sorted(no)[len(no) // 2])}


def corners_market(rows):
    by = collections.defaultdict(dict)
    for r in rows:
        if r.get("market_key") == "alternate_totals_corners" and r.get("line") is not None:
            by[(r.get("book"), float(r["line"]))][str(r.get("side")).lower()] = dec_from_american(r["price"])
    lines = collections.defaultdict(lambda: {"fair": [], "over": [], "under": []})
    for (_, line), sides in by.items():
        if abs(line % 1 - 0.5) > 1e-9 or "over" not in sides or "under" not in sides:
            continue                                      # half lines, two-sided quotes only
        lines[line]["fair"].append(devig([sides["over"], sides["under"]])[0])
        lines[line]["over"].append(sides["over"])
        lines[line]["under"].append(sides["under"])
    if not lines:
        return None
    line = min(lines, key=lambda l: abs(mean(lines[l]["fair"]) - 0.5))
    v = lines[line]
    return {"line": line, "fair": mean(v["fair"]), "books": len(v["fair"]),
            "best": (max(v["over"]), max(v["under"])),
            "med": (sorted(v["over"])[len(v["over"]) // 2], sorted(v["under"])[len(v["under"]) // 2])}


def last_season_corners():
    out = {}
    for lg in LEAGUES:
        p = os.path.join(PRIMARY, "data", "soccer_source", lg, "history", "matches_2025.csv")
        if not os.path.exists(p):
            continue
        f = pd.read_csv(p).dropna(subset=["home_corners", "away_corners"])
        if f.empty:
            continue
        tot = f.home_corners + f.away_corners
        out[lg] = {"total_mean": tot.mean(), "disp": max(1.0, tot.var() / tot.mean()),
                   "home_mean": f.home_corners.mean(), "away_mean": f.away_corners.mean()}
    return out


# ---------------------------------------------------------------- scoring helpers

def compare(items, model_loss, market_loss, label, group=lambda it: it["lg"], min_n=8, extra=None):
    groups = collections.defaultdict(list)
    for it in items:
        groups["ALL"].append(it)
        groups[group(it)].append(it)
    print(f"\n--- {label} ---")
    print(f"{'group':20s} {'n':>4s} {'model':>7s} {'market':>7s} {'diff':>8s} {'95% CI':>18s} {'model better':>12s}" + ("  " + extra[0] if extra else ""))
    res = {}
    keys = [k for k in ORDER if k in groups] + sorted(k for k in groups if k not in ORDER)
    for g in keys:
        its = groups[g]
        if len(its) < min_n:
            continue
        ml = mean(model_loss(i) for i in its)
        kl = mean(market_loss(i) for i in its)
        ci = boot_ci(its, lambda s: mean(model_loss(i) - market_loss(i) for i in s))
        better = sum(1 for i in its if model_loss(i) < market_loss(i)) / len(its)
        ex = extra[1](its) if extra else ""
        flag = " LOSES" if ci[0] > 0 else (" WINS" if ci[1] < 0 else "")
        print(f"{g:20s} {len(its):4d} {ml:7.4f} {kl:7.4f} {ml - kl:+8.4f} [{ci[0]:+.4f},{ci[1]:+.4f}] {100 * better:11.1f}%{flag}  {ex}")
        res[g] = {"n": len(its), "model": ml, "market": kl, "diff": ml - kl, "ci": ci, "model_better_share": better,
                  "dates": sorted({i["date"] for i in its})[0::max(1, len({i['date'] for i in its}) - 1)]}
    return res


def roi(bl, field):
    by = collections.defaultdict(list)
    for b in bl:
        by[b["key"]].append(b[field])
    units = list(by.values())
    if not units:
        return float("nan"), (float("nan"), float("nan")), 0
    r = sum(sum(u) for u in units) / sum(len(u) for u in units)
    return r, boot_ci(units, lambda s: sum(sum(u) for u in s) / max(sum(len(u) for u in s), 1)), len(units)


def lodo(by_T, field="p_typ", min_train=20):
    dates = sorted({b["date"] for bl in by_T.values() for b in bl})
    held = []
    for d in dates:
        best_T, best_r = None, -1e9
        for T, bl in by_T.items():
            tr = [b for b in bl if b["date"] != d]
            if len(tr) < min_train:
                continue
            r = sum(b[field] for b in tr) / len(tr)
            if r > best_r:
                best_T, best_r = T, r
        if best_T is not None:
            held += [b for b in by_T[best_T] if b["date"] == d]
    return held


def betting(items, legs, label, baseline=None):
    by_T = {T: [] for T in Ts}
    for it in items:
        for leg in legs(it):
            for T in Ts:
                if leg["edge"] >= T:
                    by_T[T].append({"date": it["date"], "key": it["key"], "lg": it["lg"], **leg})
    print(f"\n  BETTING {label}: flat 1u; typical = average/median price, best = max price")
    print(f"  {'rule':14s} {'bets':>5s} {'matches':>7s} {'hit%':>6s} {'odds':>5s} {'ROI typ':>8s} {'95% CI':>17s} {'ROI best':>8s} {'95% CI':>17s}")
    out = {}

    def line(name, bl):
        if not bl:
            print(f"  {name:14s} {0:5d}")
            return None
        rt, ct, nm = roi(bl, "p_typ")
        rb, cb, _ = roi(bl, "p_best")
        hit = sum(1 for b in bl if b["p_typ"] > 0) / len(bl)
        odds = mean(b["dec_typ"] for b in bl)
        print(f"  {name:14s} {len(bl):5d} {nm:7d} {100 * hit:6.1f} {odds:5.2f} {100 * rt:+7.1f}% [{100 * ct[0]:+6.1f},{100 * ct[1]:+6.1f}] "
              f"{100 * rb:+7.1f}% [{100 * cb[0]:+6.1f},{100 * cb[1]:+6.1f}]")
        return {"bets": len(bl), "matches": nm, "hit": hit, "odds": odds, "roi_typ": rt, "ci_typ": ct, "roi_best": rb, "ci_best": cb}

    if baseline:
        bl = [{"date": it["date"], "key": it["key"], "lg": it["lg"], **leg} for it in items for leg in baseline(it)]
        out["market_lean"] = line("market lean", bl)
    for T in Ts:
        out[f"edge>={int(T * 100)}pp"] = line(f"edge>={int(T * 100)}pp", by_T[T])
    out["lodo_heldout"] = line("LODO held-out", lodo(by_T))
    per = collections.defaultdict(list)
    for b in by_T[0.04]:
        per[b["lg"]].append(b)
    txt = []
    for lg in LEAGUES:
        if per.get(lg):
            r, c, nm = roi(per[lg], "p_typ")
            txt.append(f"{lg} {len(per[lg])}b {100 * r:+.0f}% [{100 * c[0]:+.0f},{100 * c[1]:+.0f}]")
            out.setdefault("by_league_edge4", {})[lg] = {"bets": len(per[lg]), "roi_typ": r, "ci_typ": c}
    print("  by league @4pp (typical price): " + " | ".join(txt))
    return out


def poisson_mean_from_over25(p):
    lo, hi = 0.05, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if 1.0 - sum(poisson_pmf(k, mid) for k in range(3)) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def settle(dec, won):
    return dec - 1.0 if won else -1.0


def settle_ah(hg, ag, line, dec, side):
    if side == "away":
        hg, ag, line = ag, hg, -line
    parts = [line - 0.25, line + 0.25] if abs((line * 4) % 2 - 1) < 1e-9 else [line]
    return sum((1.0 / len(parts)) * ((dec - 1.0) if hg - ag + p > 0 else (0.0 if hg - ag + p == 0 else -1.0)) for p in parts)


# ---------------------------------------------------------------- main

def build_rows(recs, outc, fd, gm):
    gm_by = collections.defaultdict(list)
    for e in gm.values():
        gm_by[e["league"]].append(e)
    rows, cov, score_mismatch = [], collections.Counter(), 0
    for (lg, mid), m in recs.items():
        cov[(lg, "predicted")] += 1
        o = outc.get((lg, mid))
        if not o:
            continue
        th, ta = o["teams"].get("home") or {}, o["teams"].get("away") or {}
        if th.get("score") is None or ta.get("score") is None:
            continue
        cov[(lg, "outcome")] += 1
        kd = m["kickoff"].date() if m["kickoff"] else dt.date.fromisoformat(m["date"])
        f = find_fixture(m["home"], m["away"], [(r["HomeTeam"], r["AwayTeam"], r) for r in fd.get(lg, []) if abs((r["_date"] - kd).days) <= 1])
        if f is not None:
            cov[(lg, "fd")] += 1
            if flt(f.get("FTHG")) is not None and (int(flt(f["FTHG"])) != int(th["score"]) or int(flt(f["FTAG"])) != int(ta["score"])):
                score_mismatch += 1
        ev = None
        if m["kickoff"]:
            ev = find_fixture(m["home"], m["away"], [(e["home"], e["away"], e) for e in gm_by.get(lg, [])
                                                     if abs((e["game_time"] - m["kickoff"]).total_seconds()) <= 3 * 3600])
        if ev is not None:
            cov[(lg, "game_markets")] += 1
        rows.append({"m": m, "o": o, "hg": int(th["score"]), "ag": int(ta["score"]), "fd": f, "gm": ev, "lg": lg,
                     "date": m["date"], "key": f"{lg}|{mid}", "version": m["version"]})
    return rows, cov, score_mismatch


def main():
    recs = load_recs()
    outc = load_outcomes()
    fd = load_fd()
    gm = load_game_markets()
    lsc = last_season_corners()
    pooled_disp = mean(v["disp"] for v in lsc.values())
    rows, cov, mism = build_rows(recs, outc, fd, gm)

    print("=== COVERAGE (matches) ===")
    print(f"{'league':20s} {'predicted':>9s} {'outcome':>8s} {'fd close':>8s} {'gm capture':>10s}  dates")
    for lg in LEAGUES:
        ds = sorted({r['date'] for r in rows if r['lg'] == lg})
        print(f"{lg:20s} {cov[(lg, 'predicted')]:9d} {cov[(lg, 'outcome')]:8d} {cov[(lg, 'fd')]:8d} {cov[(lg, 'game_markets')]:10d}  "
              f"{ds[0] if ds else ''}..{ds[-1] if ds else ''} ({len(ds)} dates)")
    print(f"ESPN vs football-data score mismatches: {mism}")
    RESULTS["coverage"] = {f"{k[0]}|{k[1]}": v for k, v in cov.items()}

    # ------------------------------------------------ 1X2
    items = []
    for r in rows:
        f = r["fd"]
        if f is None:
            continue
        avg = [fnum(f.get("AvgCH")), fnum(f.get("AvgCD")), fnum(f.get("AvgCA"))]
        mx = [fnum(f.get("MaxCH")), fnum(f.get("MaxCD")), fnum(f.get("MaxCA"))]
        ps = [fnum(f.get("PSCH")), fnum(f.get("PSCD")), fnum(f.get("PSCA"))]
        if None in avg or None in mx:
            continue
        mk = devig(ps if None not in ps else avg)
        m = r["m"]
        s = m["p_home"] + m["p_draw"] + m["p_away"]
        md = [m["p_home"] / s, m["p_draw"] / s, m["p_away"] / s]
        res = 0 if r["hg"] > r["ag"] else (1 if r["hg"] == r["ag"] else 2)
        items.append({**r, "model": md, "market": mk, "res": res, "avg": avg, "max": mx})

    def brier3(p, res):
        return sum((p[i] - (1.0 if i == res else 0.0)) ** 2 for i in range(3))

    print("\n================ 1X2 (multiclass Brier; market = de-vigged closing average, MLS Pinnacle close where present) ================")
    RESULTS["1x2"] = compare(items, lambda i: brier3(i["model"], i["res"]), lambda i: brier3(i["market"], i["res"]), "1X2 Brier by league")
    RESULTS["1x2_logloss"] = compare(items, lambda i: -math.log(max(i["model"][i["res"]], 1e-3)), lambda i: -math.log(max(i["market"][i["res"]], 1e-3)), "1X2 log loss by league")
    RESULTS["1x2_version"] = compare(items, lambda i: brier3(i["model"], i["res"]), lambda i: brier3(i["market"], i["res"]), "1X2 Brier by model version (artifact generated_at vs 2026-09-07 20:12Z)", group=lambda i: i["version"])
    fav = [i for i in items if max(i["market"]) >= 0.60]
    if fav:
        fi = [max(range(3), key=lambda k: i["market"][k]) for i in fav]
        print(f"\n  FAVOURITES (market >= 0.60): n={len(fav)} model fav p {mean(i['model'][k] for i, k in zip(fav, fi)):.3f} "
              f"market {mean(i['market'][k] for i, k in zip(fav, fi)):.3f} actual {mean(1.0 if i['res'] == k else 0.0 for i, k in zip(fav, fi)):.3f}")
        by = collections.defaultdict(list)
        for i, k in zip(fav, fi):
            by[i["lg"]].append((i["model"][k], i["market"][k], 1.0 if i["res"] == k else 0.0))
        print("  by league: " + " | ".join(f"{lg} n{len(v)} m{mean(x[0] for x in v):.2f}/k{mean(x[1] for x in v):.2f}/a{mean(x[2] for x in v):.2f}" for lg, v in sorted(by.items())))
        RESULTS["favourites"] = {"n": len(fav), "model": mean(i['model'][k] for i, k in zip(fav, fi)), "market": mean(i['market'][k] for i, k in zip(fav, fi)), "actual": mean(1.0 if i['res'] == k else 0.0 for i, k in zip(fav, fi))}
    print("\n  draw rate: model %.3f market %.3f actual %.3f" % (mean(i["model"][1] for i in items), mean(i["market"][1] for i in items), mean(1.0 if i["res"] == 1 else 0.0 for i in items)))
    RESULTS["1x2_bet"] = betting(
        items,
        lambda i: [{"edge": i["model"][k] - i["market"][k], "side": k, "dec_typ": i["avg"][k], "dec_best": i["max"][k],
                    "p_typ": settle(i["avg"][k], i["res"] == k), "p_best": settle(i["max"][k], i["res"] == k)} for k in range(3)],
        "1X2", baseline=lambda i: [{"edge": 0, "dec_typ": i["avg"][k], "dec_best": i["max"][k], "p_typ": settle(i["avg"][k], i["res"] == k),
                                    "p_best": settle(i["max"][k], i["res"] == k)} for k in [max(range(3), key=lambda k: i["market"][k])]])
    for side, nm in ((0, "home"), (1, "draw"), (2, "away")):
        bl = [{"date": i["date"], "key": i["key"], "p_typ": settle(i["avg"][side], i["res"] == side)} for i in items if i["model"][side] - i["market"][side] >= 0.04]
        r, c, n = roi(bl, "p_typ")
        print(f"  1X2 {nm:4s} leg edge>=4pp: {len(bl)} bets ROI {100 * r:+.1f}% [{100 * c[0]:+.1f},{100 * c[1]:+.1f}]")

    # snapshot control (H7): pre-kickoff builds vs final rebuilds, same matches, same market
    snap = load_recs(os.path.join(S, "recs_snapshot_0902"))
    ctl = []
    for i in items:
        sm = snap.get((i["lg"], i["m"]["match_id"]))
        if sm and sm["generated_at"] and i["m"]["kickoff"] and sm["generated_at"] < i["m"]["kickoff"]:
            s = sm["p_home"] + sm["p_draw"] + sm["p_away"]
            ctl.append((brier3([sm["p_home"] / s, sm["p_draw"] / s, sm["p_away"] / s], i["res"]), brier3(i["model"], i["res"]), brier3(i["market"], i["res"])))
    if ctl:
        print(f"\n  H7 CONTROL: {len(ctl)} matches with a PRE-KICKOFF build: snapshot Brier {mean(c[0] for c in ctl):.4f} | final {mean(c[1] for c in ctl):.4f} | market {mean(c[2] for c in ctl):.4f}")
        RESULTS["h7_control"] = {"n": len(ctl), "snapshot": mean(c[0] for c in ctl), "final": mean(c[1] for c in ctl), "market": mean(c[2] for c in ctl)}

    # ------------------------------------------------ O/U 2.5
    tot = []
    for r in rows:
        f = r["fd"]
        if f is None:
            continue
        o, u = fnum(f.get("AvgC>2.5")), fnum(f.get("AvgC<2.5"))
        mo, mu_ = fnum(f.get("MaxC>2.5")), fnum(f.get("MaxC<2.5"))
        if None in (o, u, mo, mu_):
            continue
        m = r["m"]
        pm = m["p_over25"]
        if pm is None:
            sc = norm_scores(m["scores"])
            pm = sum(p for (h, a), p in sc.items() if h + a > 2)
        tot.append({**r, "pm": float(pm), "pk": devig([o, u])[0], "y": 1.0 if r["hg"] + r["ag"] > 2 else 0.0, "px": (o, u), "pmx": (mo, mu_)})
    print("\n================ OVER/UNDER 2.5 (Brier; market = de-vigged closing average) ================")
    RESULTS["ou25"] = compare(tot, lambda i: (i["pm"] - i["y"]) ** 2, lambda i: (i["pk"] - i["y"]) ** 2, "O/U 2.5 Brier by league",
                              extra=("goals: actual / model mean / market-implied mean",
                                     lambda its: f"{mean(i['hg'] + i['ag'] for i in its):.2f} / {mean(i['m']['total_mean'] or 0 for i in its):.2f} / {mean(poisson_mean_from_over25(i['pk']) for i in its):.2f}"))
    RESULTS["ou25_bet"] = betting(
        tot,
        lambda i: [{"edge": i["pm"] - i["pk"], "dec_typ": i["px"][0], "dec_best": i["pmx"][0], "p_typ": settle(i["px"][0], i["y"] == 1), "p_best": settle(i["pmx"][0], i["y"] == 1)},
                   {"edge": i["pk"] - i["pm"], "dec_typ": i["px"][1], "dec_best": i["pmx"][1], "p_typ": settle(i["px"][1], i["y"] == 0), "p_best": settle(i["pmx"][1], i["y"] == 0)}],
        "O/U 2.5", baseline=lambda i: [{"edge": 0, "dec_typ": i["px"][0 if i["pk"] >= 0.5 else 1], "dec_best": i["pmx"][0 if i["pk"] >= 0.5 else 1],
                                        "p_typ": settle(i["px"][0 if i["pk"] >= 0.5 else 1], (i["y"] == 1) == (i["pk"] >= 0.5)),
                                        "p_best": settle(i["pmx"][0 if i["pk"] >= 0.5 else 1], (i["y"] == 1) == (i["pk"] >= 0.5))}])
    print("  total-goals bias (actual - model mean) by league: " + " | ".join(
        f"{lg} {mean(i['hg'] + i['ag'] - (i['m']['total_mean'] or 0) for i in tot if i['lg'] == lg):+.2f}" for lg in LEAGUES if any(i['lg'] == lg for i in tot)))
    all_tot = [r for r in rows if r["m"]["total_mean"] is not None]
    bias_units = all_tot
    ci = boot_ci(bias_units, lambda s: mean(i['hg'] + i['ag'] - i['m']['total_mean'] for i in s))
    print(f"  ALL matches with a model total (incl. MLS): n={len(all_tot)} actual {mean(i['hg'] + i['ag'] for i in all_tot):.3f} model {mean(i['m']['total_mean'] for i in all_tot):.3f} "
          f"bias {mean(i['hg'] + i['ag'] - i['m']['total_mean'] for i in all_tot):+.3f} [{ci[0]:+.3f},{ci[1]:+.3f}]")
    RESULTS["total_bias_all"] = {"n": len(all_tot), "bias": mean(i['hg'] + i['ag'] - i['m']['total_mean'] for i in all_tot), "ci": ci}

    # ------------------------------------------------ Asian handicap (closing main line)
    ah = []
    for r in rows:
        f = r["fd"]
        if f is None:
            continue
        line = flt(f.get("AHCh"))
        h, a = fnum(f.get("AvgCAHH")), fnum(f.get("AvgCAHA"))
        mh, ma = fnum(f.get("MaxCAHH")), fnum(f.get("MaxCAHA"))
        sc = norm_scores(r["m"]["scores"])
        if None in (line, h, a, mh, ma) or not sc:
            continue
        w, _, _, _, l = ah_home_value(sc, line)
        aw, _, _, _, al = ah_home_value({(r["hg"], r["ag"]): 1.0}, line)
        if w + l <= 0 or aw + al <= 0:
            continue
        ah.append({**r, "line": line, "qm": w / (w + l), "qk": devig([h, a])[0], "y": aw / (aw + al), "px": (h, a), "pmx": (mh, ma)})
    print("\n================ ASIAN HANDICAP, closing main line (Brier on home-cover, pushes removed) ================")
    RESULTS["ah"] = compare(ah, lambda i: (i["qm"] - i["y"]) ** 2, lambda i: (i["qk"] - i["y"]) ** 2, "AH Brier by league")
    RESULTS["ah_bet"] = betting(
        ah,
        lambda i: [{"edge": i["qm"] - i["qk"], "dec_typ": i["px"][0], "dec_best": i["pmx"][0], "p_typ": settle_ah(i["hg"], i["ag"], i["line"], i["px"][0], "home"), "p_best": settle_ah(i["hg"], i["ag"], i["line"], i["pmx"][0], "home")},
                   {"edge": i["qk"] - i["qm"], "dec_typ": i["px"][1], "dec_best": i["pmx"][1], "p_typ": settle_ah(i["hg"], i["ag"], i["line"], i["px"][1], "away"), "p_best": settle_ah(i["hg"], i["ag"], i["line"], i["pmx"][1], "away")}],
        "AH")

    # ------------------------------------------------ BTTS
    bt = []
    for r in rows:
        m = r["m"]
        pm = m["p_btts"]
        if pm is None:
            sc = norm_scores(m["scores"])
            pm = sum(p for (h, a), p in sc.items() if h > 0 and a > 0)
        y = 1.0 if (r["hg"] > 0 and r["ag"] > 0) else 0.0
        mk = btts_market(r["gm"]["rows"]) if r["gm"] else None
        imp = None
        f = r["fd"]
        if f is not None:
            avg = [fnum(f.get("AvgCH")), fnum(f.get("AvgCD")), fnum(f.get("AvgCA"))]
            o, u = fnum(f.get("AvgC>2.5")), fnum(f.get("AvgC<2.5"))
            if None not in avg and o and u:
                p1 = devig(avg)
                lam = implied_poisson_goals(p1[0], p1[2], devig([o, u])[0])
                if lam:
                    imp = (1 - math.exp(-lam[0])) * (1 - math.exp(-lam[1]))
                    r["lam"] = lam
        bt.append({**r, "pm": float(pm), "y": y, "mk": mk, "imp": imp})
    print("\n================ BTTS ================")
    wm = [i for i in bt if i["mk"]]
    if wm:
        ages = sorted((i["m"]["kickoff"] - i["gm"]["captured_at"]).total_seconds() / 3600 for i in wm if i["m"]["kickoff"])
        print(f"  BTTS market capture age before kickoff: median {ages[len(ages) // 2]:.1f} h, p90 {ages[int(0.9 * len(ages))]:.1f} h, books/match {mean(i['mk']['books'] for i in wm):.1f}")
    RESULTS["btts_vs_captured"] = compare(wm, lambda i: (i["pm"] - i["y"]) ** 2, lambda i: (i["mk"]["fair"] - i["y"]) ** 2, "BTTS Brier vs captured BTTS market (pre-kickoff)")
    wi = [i for i in bt if i["imp"] is not None]
    RESULTS["btts_vs_implied"] = compare(wi, lambda i: (i["pm"] - i["y"]) ** 2, lambda i: (i["imp"] - i["y"]) ** 2, "BTTS Brier vs Poisson-implied from CLOSING 1X2+O/U2.5 (benchmark, not a price)")
    print(f"  BTTS rate: model {mean(i['pm'] for i in bt):.3f} actual {mean(i['y'] for i in bt):.3f} (n={len(bt)})")
    RESULTS["btts_bet"] = betting(
        wm,
        lambda i: [{"edge": i["pm"] - i["mk"]["fair"], "dec_typ": i["mk"]["med"][0], "dec_best": i["mk"]["best"][0], "p_typ": settle(i["mk"]["med"][0], i["y"] == 1), "p_best": settle(i["mk"]["best"][0], i["y"] == 1)},
                   {"edge": i["mk"]["fair"] - i["pm"], "dec_typ": i["mk"]["med"][1], "dec_best": i["mk"]["best"][1], "p_typ": settle(i["mk"]["med"][1], i["y"] == 0), "p_best": settle(i["mk"]["best"][1], i["y"] == 0)}],
        "BTTS")

    # ------------------------------------------------ team goals
    tg = []
    for r in bt:
        m = r["m"]
        sc = norm_scores(m["scores"])
        if not sc or m["home_mean"] is None:
            continue
        sims = m["sims"] or 400
        floor = 0.5 / sims
        mh = collections.Counter()
        ma = collections.Counter()
        for (h, a), p in sc.items():
            mh[h] += p
            ma[a] += p
        item = {**r, "units": []}
        for side, goals, mean_, marg in (("home", r["hg"], m["home_mean"], mh), ("away", r["ag"], m["away_mean"], ma)):
            lam = r.get("lam")
            ml = r.get("lam")[0 if side == "home" else 1] if lam else None
            item["units"].append({
                "goals": goals, "model_mean": mean_, "market_mean": ml,
                "ll_model": -math.log(max(marg.get(goals, 0.0), floor)),
                "ll_market": -math.log(max(poisson_pmf(goals, ml), floor)) if ml else None,
                "b2_model": (sum(p for k, p in marg.items() if k >= 2) - (1.0 if goals >= 2 else 0.0)) ** 2,
                "b2_market": ((1 - poisson_pmf(0, ml) - poisson_pmf(1, ml)) - (1.0 if goals >= 2 else 0.0)) ** 2 if ml else None})
        tg.append(item)
    print("\n================ TEAM GOALS (per team-match; market = Poisson-implied from closing 1X2 + O/U 2.5) ================")
    wl = [i for i in tg if all(u["market_mean"] is not None for u in i["units"])]
    RESULTS["team_goals_ll"] = compare(wl, lambda i: mean(u["ll_model"] for u in i["units"]), lambda i: mean(u["ll_market"] for u in i["units"]), "team goals log loss (per team)")
    RESULTS["team_goals_over15"] = compare(wl, lambda i: mean(u["b2_model"] for u in i["units"]), lambda i: mean(u["b2_market"] for u in i["units"]), "team goals >= 2 Brier (per team)")
    for side_idx, nm in ((0, "home"), (1, "away")):
        units = [i["units"][side_idx] for i in tg]
        ci = boot_ci(units, lambda s: mean(u["goals"] - u["model_mean"] for u in s))
        print(f"  {nm} goals: actual {mean(u['goals'] for u in units):.3f} model {mean(u['model_mean'] for u in units):.3f} bias {mean(u['goals'] - u['model_mean'] for u in units):+.3f} [{ci[0]:+.3f},{ci[1]:+.3f}] "
              f"MAE model {mean(abs(u['goals'] - u['model_mean']) for u in units):.3f}")

    # ------------------------------------------------ corners
    co = []
    for r in rows:
        th, ta = r["o"]["teams"]["home"], r["o"]["teams"]["away"]
        ch, ca = th.get("wonCorners"), ta.get("wonCorners")
        if (ch is None or ca is None) and r["fd"] is not None:
            ch, ca = flt(r["fd"].get("HC")), flt(r["fd"].get("AC"))
        m = r["m"]
        if ch is None or ca is None or m["corners_h"] is None:
            continue
        ls = lsc.get(r["lg"])
        co.append({**r, "ch": ch, "ca": ca, "mh": m["corners_h"], "ma": m["corners_a"], "disp": ls["disp"] if ls else pooled_disp,
                   "base_h": ls["home_mean"] if ls else mean(v["home_mean"] for v in lsc.values()),
                   "base_a": ls["away_mean"] if ls else mean(v["away_mean"] for v in lsc.values()),
                   "mk": corners_market(r["gm"]["rows"]) if r["gm"] else None})
    print("\n================ CORNERS ================")
    print(f"{'group':20s} {'n':>4s} {'actual':>6s} {'model':>6s} {'bias':>6s} {'95% CI':>15s} {'MAE mdl':>7s} {'MAE base':>8s} {'r':>5s} | team: {'bias':>6s} {'MAE mdl':>7s} {'MAE base':>8s} {'r':>5s}")
    RESULTS["corners"] = {}
    for g in ORDER:
        its = co if g == "ALL" else [i for i in co if i["lg"] == g]
        if len(its) < 8:
            continue
        a = [i["ch"] + i["ca"] for i in its]
        p = [i["mh"] + i["ma"] for i in its]
        ci = boot_ci(its, lambda s: mean(i["ch"] + i["ca"] - i["mh"] - i["ma"] for i in s))
        base = [i["base_h"] + i["base_a"] for i in its]
        ta_ = [x for i in its for x in (i["ch"], i["ca"])]
        tp_ = [x for i in its for x in (i["mh"], i["ma"])]
        tb_ = [x for i in its for x in (i["base_h"], i["base_a"])]

        def r_(xs, ys):
            n = len(xs)
            mx, my = sum(xs) / n, sum(ys) / n
            sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
            sy = math.sqrt(sum((y - my) ** 2 for y in ys))
            return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else float("nan")
        row = {"n": len(its), "actual": mean(a), "model": mean(p), "bias": mean(a) - mean(p), "ci": ci,
               "mae_model": mean(abs(x - y) for x, y in zip(a, p)), "mae_base": mean(abs(x - y) for x, y in zip(a, base)), "r": r_(p, a),
               "team_bias": mean(ta_) - mean(tp_), "team_mae_model": mean(abs(x - y) for x, y in zip(ta_, tp_)),
               "team_mae_base": mean(abs(x - y) for x, y in zip(ta_, tb_)), "team_r": r_(tp_, ta_)}
        RESULTS["corners"][g] = row
        print(f"{g:20s} {len(its):4d} {row['actual']:6.2f} {row['model']:6.2f} {row['bias']:+6.2f} [{ci[0]:+.2f},{ci[1]:+.2f}] {row['mae_model']:7.2f} {row['mae_base']:8.2f} {row['r']:5.2f} | "
              f"      {row['team_bias']:+6.2f} {row['team_mae_model']:7.2f} {row['team_mae_base']:8.2f} {row['team_r']:5.2f}")
    cm = []
    for i in co:
        if not i["mk"]:
            continue
        k = int(math.floor(i["mk"]["line"])) + 1
        cm.append({**i, "pm": nb_sf(k, i["mh"] + i["ma"], i["disp"]), "pk": i["mk"]["fair"], "y": 1.0 if i["ch"] + i["ca"] >= k else 0.0})
    if cm:
        print(f"  corners main line: mean line {mean(i['mk']['line'] for i in cm):.2f} vs model mean {mean(i['mh'] + i['ma'] for i in cm):.2f} vs actual {mean(i['ch'] + i['ca'] for i in cm):.2f}; books/match {mean(i['mk']['books'] for i in cm):.1f}")
    RESULTS["corners_line"] = compare(cm, lambda i: (i["pm"] - i["y"]) ** 2, lambda i: (i["pk"] - i["y"]) ** 2, "corners over MAIN line Brier (model = NB, last-season league dispersion)")
    RESULTS["corners_bet"] = betting(
        cm,
        lambda i: [{"edge": i["pm"] - i["pk"], "dec_typ": i["mk"]["med"][0], "dec_best": i["mk"]["best"][0], "p_typ": settle(i["mk"]["med"][0], i["y"] == 1), "p_best": settle(i["mk"]["best"][0], i["y"] == 1)},
                   {"edge": i["pk"] - i["pm"], "dec_typ": i["mk"]["med"][1], "dec_best": i["mk"]["best"][1], "p_typ": settle(i["mk"]["med"][1], i["y"] == 0), "p_best": settle(i["mk"]["best"][1], i["y"] == 0)}],
        "corners main line")

    # ------------------------------------------------ team shots / SOT volume (context for player props)
    print("\n================ TEAM SHOT VOLUME (model vs ESPN box) ================")
    RESULTS["team_volume"] = {}
    for g in ORDER:
        its = [r for r in rows if (g == "ALL" or r["lg"] == g) and r["m"]["shots_h"] is not None
               and r["o"]["teams"]["home"].get("totalShots") is not None]
        if len(its) < 8:
            continue
        ps = sum(r["m"]["shots_h"] + r["m"]["shots_a"] for r in its)
        rs = sum(r["o"]["teams"]["home"]["totalShots"] + r["o"]["teams"]["away"]["totalShots"] for r in its)
        pt = sum((r["m"]["sot_h"] or 0) + (r["m"]["sot_a"] or 0) for r in its)
        rt = sum((r["o"]["teams"]["home"].get("shotsOnTarget") or 0) + (r["o"]["teams"]["away"].get("shotsOnTarget") or 0) for r in its)
        RESULTS["team_volume"][g] = {"n": len(its), "shots_ratio": ps / max(rs, 1), "sot_ratio": pt / max(rt, 1), "model_shots_pm": ps / len(its), "actual_shots_pm": rs / len(its)}
        print(f"  {g:20s} n={len(its):4d} shots/match model {ps / len(its):5.1f} actual {rs / len(its):5.1f} ratio {ps / max(rs, 1):.2f} | SOT ratio {pt / max(rt, 1):.2f}")

    json.dump(RESULTS, open(os.path.join(S, "games_results.json"), "w", encoding="utf-8"), default=str)
    print("\nwrote games_results.json")


if __name__ == "__main__":
    main()
