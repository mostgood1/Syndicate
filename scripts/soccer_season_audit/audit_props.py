# -*- coding: utf-8 -*-
"""Player props, season to date: shots, shots on target, anytime scorer.

Accuracy: the model's stored means/probabilities vs ESPN box-score player stats.
Market: production `props/<date>.csv` (one-sided OVER prices, 8 US books); ROI at the
BEST and MEDIAN offered price; a player who did not appear is VOID, as books settle it.

The 2026-08-31 shrink fit used dates < 2026-08-22; this run re-fits on those dates
only and scores everything on or after them, so every scaled number is held out.
"""
import collections
import glob
import json
import math
import os
import re

import pandas as pd

from common import LEAGUES, S, boot_ci, dec_from_american, find_fixture, fold, load_outcomes, load_recs, mean, poisson_sf, ts
from namejoin_diag import score as name_score, strict_match


def bind_players(preds, roster):
    """One-to-one, per side, best score first (namejoin_diag.strict_match)."""
    out = {}
    for side in ("home", "away"):
        ps = [p for p in preds if p.get("side") == side]
        rs = [q for q in roster if q["side"] == side]
        for i, j in strict_match(ps, rs).items():
            out[id(ps[i])] = rs[j]
    return out

TRAIN_END = "2026-08-22"
Ts = (0.0, 0.05, 0.10, 0.15)
RESULTS = {}
BIND_CACHE = {}
MARKETS = {"player_shots": "shots", "player_shots_on_target": "sot", "player_goal_scorer_anytime": "anytime"}


def appeared(p):
    return bool(p["starter"] or p["subbed_in"] or (p.get("appearances") or 0) > 0)


def index_roster(players):
    full, init_last = collections.defaultdict(list), collections.defaultdict(list)
    for p in players:
        f = fold(p["name"]).split()
        if not f:
            continue
        full[(p["side"], " ".join(f))].append(p)
        init_last[(p["side"], f[0][:1], f[-1])].append(p)
    return full, init_last


def find_player(name, side, full, init_last):
    f = fold(name).split()
    if not f:
        return None
    hit = full.get((side, " ".join(f)))
    if hit and len(hit) == 1:
        return hit[0]
    hit = init_last.get((side, f[0][:1], f[-1]))
    return hit[0] if hit and len(hit) == 1 else None


def decile_table(rows, pred, real, label):
    srt = sorted(rows, key=pred)
    k = max(1, len(srt) // 10)
    print(f"  calibration by predicted decile ({label}):")
    for i in range(0, len(srt), k):
        ch = srt[i:i + k]
        if len(ch) < 20:
            continue
        p, a = mean(pred(x) for x in ch), mean(real(x) for x in ch)
        print(f"    {pred(ch[0]):6.3f}-{pred(ch[-1]):<6.3f} n={len(ch):5d} pred {p:6.3f} real {a:6.3f} ratio {p / max(a, 1e-9):5.2f}")


def main():
    recs = load_recs()
    outc = load_outcomes()

    # ---------------------------------------------------------------- accuracy rows
    rows, unmatched, cap = [], collections.Counter(), collections.defaultdict(lambda: [0.0, 0.0])
    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        if not o or not m["players"]:
            continue
        for side in ("home", "away"):
            t = o["teams"].get(side) or {}
            cap[lg][0] += sum(p["shots"] or 0 for p in o["players"] if p["side"] == side)
            cap[lg][1] += t.get("totalShots") or 0
        bound = bind_players(m["players"], o["players"])
        BIND_CACHE[(lg, mid)] = bound
        for p in m["players"]:
            hit = bound.get(id(p))
            if hit is None:
                unmatched[lg] += 1
                continue
            rows.append({"lg": lg, "date": m["date"], "key": f"{lg}|{mid}", "name": p.get("player_name"),
                         "share": float(p.get("expected_minutes_share") or 0.0), "played": appeared(hit),
                         "es": p.get("expected_shots"), "esp": p.get("expected_shots_if_playing"),
                         "et": p.get("expected_shots_on_target"), "etp": p.get("expected_shots_on_target_if_playing"),
                         "ag": p.get("anytime_scorer_probability"), "agp": p.get("anytime_scorer_probability_if_playing"),
                         "shots": hit["shots"] or 0.0, "sot": hit["sot"] or 0.0, "goals": hit["goals"] or 0.0})
    print("=== PLAYER JOIN + CAPTURE ===")
    good = set()
    for lg in LEAGUES:
        n = sum(1 for r in rows if r["lg"] == lg)
        ratio = cap[lg][0] / max(cap[lg][1], 1)
        ok = ratio >= 0.85
        if ok:
            good.add(lg)
        print(f"  {lg:20s} matched {n:6d} unmatched {unmatched[lg]:5d} ({100 * unmatched[lg] / max(n + unmatched[lg], 1):4.1f}%) "
              f"player-sum/team shots {ratio:.2f} {'OK' if ok else 'EXCLUDED (capture)'}")
    RESULTS["join"] = {lg: {"matched": sum(1 for r in rows if r["lg"] == lg), "unmatched": unmatched[lg],
                            "capture_ratio": cap[lg][0] / max(cap[lg][1], 1)} for lg in LEAGUES}

    played = [r for r in rows if r["played"] and r["lg"] in good and r["esp"] is not None]
    train = [r for r in played if r["date"] < TRAIN_END]
    test = [r for r in played if r["date"] >= TRAIN_END]
    print(f"\n  appeared rows {len(played)} (train < {TRAIN_END}: {len(train)}, held-out: {len(test)}); matches {len({r['key'] for r in played})}; dates {min(r['date'] for r in played)}..{max(r['date'] for r in played)}")

    def fit_c(rs, pk, rk):
        return sum(r[pk] for r in rs) / max(sum(r[rk] for r in rs), 1e-9)

    c_shots = fit_c(train, "esp", "shots")
    c_sot = fit_c([r for r in train if r["etp"] is not None], "etp", "sot")
    # anytime: shrink the implied scoring intensity, lambda = -ln(1-p), by a grid-fitted c on TRAIN log loss
    def ll_anytime(rs, c):
        tot = 0.0
        for r in rs:
            p = 1.0 - (1.0 - min(max(r["agp"], 1e-6), 0.999)) ** (1.0 / c)
            y = 1.0 if r["goals"] >= 1 else 0.0
            tot += -(y * math.log(max(p, 1e-6)) + (1 - y) * math.log(max(1 - p, 1e-6)))
        return tot / max(len(rs), 1)
    tr_any = [r for r in train if r["agp"] is not None]
    c_any = min((ll_anytime(tr_any, c / 100.0), c / 100.0) for c in range(60, 251, 5))[1] if tr_any else 1.0
    print(f"  TRAIN-fitted shrink: shots c={c_shots:.3f} (2026-08-31 fit was 1.3331) | SOT c={c_sot:.3f} | anytime intensity c={c_any:.2f}")
    RESULTS["shrink"] = {"c_shots": c_shots, "c_sot": c_sot, "c_anytime": c_any, "train_rows": len(train), "test_rows": len(test)}

    print("\n================ SHOTS / SOT MEANS (appeared players, *_if_playing means) ================")
    print(f"{'group':20s} {'n':>6s} {'matches':>7s} | shots: {'pred':>5s} {'real':>5s} {'ratio':>5s} {'MAE raw':>7s} {'MAE /c':>7s} {'MAE const':>9s} | SOT: {'ratio':>5s} {'MAE raw':>7s} {'MAE /c':>7s} {'MAE const':>9s}  (held-out dates only)")
    RESULTS["means"] = {}
    for g in ["ALL"] + LEAGUES:
        rs = [r for r in test if g == "ALL" or r["lg"] == g]
        if len(rs) < 100:
            continue
        am = mean(r["shots"] for r in rs)
        tm = mean(r["sot"] for r in rs)
        rt = [r for r in rs if r["etp"] is not None]
        row = {"n": len(rs), "matches": len({r['key'] for r in rs}), "pred": mean(r["esp"] for r in rs), "real": am,
               "ratio": mean(r["esp"] for r in rs) / max(am, 1e-9),
               "mae_raw": mean(abs(r["esp"] - r["shots"]) for r in rs), "mae_scaled": mean(abs(r["esp"] / c_shots - r["shots"]) for r in rs),
               "mae_const": mean(abs(am - r["shots"]) for r in rs),
               "sot_ratio": mean(r["etp"] for r in rt) / max(mean(r["sot"] for r in rt), 1e-9),
               "sot_mae_raw": mean(abs(r["etp"] - r["sot"]) for r in rt), "sot_mae_scaled": mean(abs(r["etp"] / c_sot - r["sot"]) for r in rt),
               "sot_mae_const": mean(abs(tm - r["sot"]) for r in rt)}
        RESULTS["means"][g] = row
        print(f"{g:20s} {row['n']:6d} {row['matches']:7d} |        {row['pred']:5.2f} {row['real']:5.2f} {row['ratio']:5.2f} {row['mae_raw']:7.3f} {row['mae_scaled']:7.3f} {row['mae_const']:9.3f} |      "
              f"{row['sot_ratio']:5.2f} {row['sot_mae_raw']:7.3f} {row['sot_mae_scaled']:7.3f} {row['sot_mae_const']:9.3f}")
    decile_table(test, lambda r: r["esp"], lambda r: r["shots"], "shots, held-out")
    print("  by expected_minutes_share (held-out, shots ratio): " + " | ".join(
        f"{lab} n{len(g)} {mean(r['esp'] for r in g) / max(mean(r['shots'] for r in g), 1e-9):.2f}"
        for lab, g in (("<0.5", [r for r in test if r["share"] < 0.5]), ("0.5-0.85", [r for r in test if 0.5 <= r["share"] < 0.85]), (">=0.85", [r for r in test if r["share"] >= 0.85])) if g))

    print("\n================ ANYTIME SCORER (appeared players) ================")
    print(f"{'group':20s} {'n':>6s} {'pred':>6s} {'real':>6s} {'Brier raw':>9s} {'Brier /c':>9s} {'Brier base':>10s} {'LL raw':>7s} {'LL /c':>7s}")
    RESULTS["anytime"] = {}
    for g in ["ALL"] + LEAGUES:
        rs = [r for r in test if (g == "ALL" or r["lg"] == g) and r["agp"] is not None]
        if len(rs) < 100:
            continue
        base = mean(1.0 if r["goals"] >= 1 else 0.0 for r in rs)
        sc = lambda p: 1.0 - (1.0 - min(max(p, 1e-6), 0.999)) ** (1.0 / c_any)
        row = {"n": len(rs), "pred": mean(r["agp"] for r in rs), "real": base,
               "brier_raw": mean((r["agp"] - (1.0 if r["goals"] >= 1 else 0.0)) ** 2 for r in rs),
               "brier_scaled": mean((sc(r["agp"]) - (1.0 if r["goals"] >= 1 else 0.0)) ** 2 for r in rs),
               "brier_base": mean((base - (1.0 if r["goals"] >= 1 else 0.0)) ** 2 for r in rs),
               "ll_raw": ll_anytime(rs, 1.0), "ll_scaled": ll_anytime(rs, c_any)}
        RESULTS["anytime"][g] = row
        print(f"{g:20s} {row['n']:6d} {row['pred']:6.3f} {row['real']:6.3f} {row['brier_raw']:9.4f} {row['brier_scaled']:9.4f} {row['brier_base']:10.4f} {row['ll_raw']:7.4f} {row['ll_scaled']:7.4f}")
    decile_table([r for r in test if r["agp"] is not None], lambda r: r["agp"], lambda r: 1.0 if r["goals"] >= 1 else 0.0, "anytime, held-out")

    # ---------------------------------------------------------------- market
    frames = []
    for f in glob.glob(os.path.join(S, "prod", "props", "*.csv")):
        b = os.path.basename(f)
        if b.startswith("_") or os.path.getsize(f) < 50:
            continue
        mdate = re.search(r"(\d{4}-\d{2}-\d{2})\.csv$", b)
        try:
            fr = pd.read_csv(f)
        except Exception:
            continue
        if fr.empty or "market_key" not in fr:
            continue
        fr = fr[fr["market_key"].isin(list(MARKETS))].copy()
        fr["_fdate"] = mdate.group(1) if mdate else ""
        frames.append(fr)
    if not frames:
        print("no props market rows")
        return
    px = pd.concat(frames, ignore_index=True)
    px["_gt"] = px["game_time"].map(ts)
    px = px[px["_gt"].notna()]
    px = px[px["_fdate"] <= px["_gt"].map(lambda t: t.date().isoformat())]          # captures dated on/before the game
    px = px.sort_values("_fdate").drop_duplicates(["event_id", "player", "market_key", "line", "book"], keep="last")
    print(f"\n=== PROPS MARKET ROWS: {len(px)} after de-dup; by market {px['market_key'].value_counts().to_dict()}")

    by_league = collections.defaultdict(list)
    for (lg, mid), m in recs.items():
        if m["kickoff"]:
            by_league[lg].append(m)
    offers = collections.defaultdict(lambda: {"decs": [], "books": []})
    ev_join = {}
    for ev, g in px.groupby("event_id"):
        r0 = g.iloc[0]
        lg = r0["league"]
        gt = r0["_gt"]
        m = find_fixture(r0["home_team"], r0["away_team"], [(x["home"], x["away"], x) for x in by_league.get(lg, [])
                                                            if abs((x["kickoff"] - gt).total_seconds()) <= 3 * 3600])
        ev_join[ev] = m is not None
        if m is None:
            continue
        for r in g.itertuples():
            line = float(r.line) if pd.notna(r.line) else None
            key = (lg, m["match_id"], fold(r.player), r.market_key, line)
            offers[key]["decs"].append(dec_from_american(r.over_price))
            offers[key]["books"].append(r.book)
    print(f"  events joined to a predicted match: {sum(ev_join.values())} of {len(ev_join)}")

    bets, nojoin = [], collections.Counter()
    for (lg, mid, pname, mkey, line), off in offers.items():
        m = recs.get((lg, mid))
        o = outc.get((lg, mid))
        if not m or not o:
            nojoin["no_outcome"] += 1
            continue
        scored = sorted(((name_score(pname, p.get("player_name")), k) for k, p in enumerate(m["players"])), reverse=True)
        pm = None
        if scored and scored[0][0] >= 0.84 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            pm = m["players"][scored[0][1]]
        if pm is None:
            nojoin["no_model_player"] += 1
            continue
        if (lg, mid) not in BIND_CACHE:
            BIND_CACHE[(lg, mid)] = bind_players(m["players"], o["players"])
        hit = BIND_CACHE[(lg, mid)].get(id(pm))
        if hit is None or not appeared(hit):
            nojoin["void_or_unmatched"] += 1
            continue
        kind = MARKETS[mkey]
        if kind == "anytime":
            p_raw = pm.get("anytime_scorer_probability_if_playing")
            if p_raw is None:
                continue
            p_sc = 1.0 - (1.0 - min(max(p_raw, 1e-6), 0.999)) ** (1.0 / c_any)
            won = (hit["goals"] or 0) >= 1
        else:
            if line is None:
                continue
            k = int(math.floor(line)) + 1
            mu = pm.get("expected_shots_if_playing" if kind == "shots" else "expected_shots_on_target_if_playing")
            if mu is None:
                continue
            c = c_shots if kind == "shots" else c_sot
            p_raw, p_sc = poisson_sf(k, mu), poisson_sf(k, mu / c)
            won = (hit["shots" if kind == "shots" else "sot"] or 0) >= k
        decs = sorted(off["decs"])
        best, med = decs[-1], decs[len(decs) // 2]
        bets.append({"lg": lg, "date": m["date"], "key": f"{lg}|{mid}", "kind": kind, "line": line, "p_raw": p_raw, "p_sc": p_sc,
                     "imp_best": 1.0 / best, "imp_med": 1.0 / med, "best": best, "med": med, "won": won, "nbooks": len(decs),
                     "fd": next((d for d, b in zip(off["decs"], off["books"]) if b == "fanduel"), None)})
    print(f"  priced player-lines graded: {len(bets)}; dropped {dict(nojoin)}")
    RESULTS["props_market_n"] = {"graded": len(bets), "dropped": dict(nojoin)}

    for kind in ("shots", "sot", "anytime"):
        kb = [b for b in bets if b["kind"] == kind]
        if not kb:
            continue
        print(f"\n================ {kind.upper()} PROPS vs OFFERED PRICE ({len(kb)} player-lines, {len({b['key'] for b in kb})} matches) ================")
        lines = collections.Counter(b["line"] for b in kb)
        print("  lines: " + ", ".join(f"{l}:{n}" for l, n in sorted(lines.items(), key=lambda x: (x[0] is None, x[0] or 0))))
        y = lambda b: 1.0 if b["won"] else 0.0
        units = list({b["key"]: None for b in kb})
        by_key = collections.defaultdict(list)
        for b in kb:
            by_key[b["key"]].append(b)
        grp = list(by_key.values())
        for nm, fn in (("model raw", lambda b: b["p_raw"]), ("model /c", lambda b: b["p_sc"]), ("market implied (best, with vig)", lambda b: b["imp_best"]), ("market implied (median, with vig)", lambda b: b["imp_med"])):
            br = mean((fn(b) - y(b)) ** 2 for b in kb)
            print(f"  Brier {nm:34s} {br:.4f}   mean p {mean(fn(b) for b in kb):.3f} vs hit {mean(y(b) for b in kb):.3f}")
        d = boot_ci(grp, lambda s: mean((b["p_raw"] - y(b)) ** 2 - (b["imp_best"] - y(b)) ** 2 for u in s for b in u))
        d2 = boot_ci(grp, lambda s: mean((b["p_sc"] - y(b)) ** 2 - (b["imp_best"] - y(b)) ** 2 for u in s for b in u))
        print(f"  Brier diff model raw - market best [{d[0]:+.4f},{d[1]:+.4f}] | model /c - market best [{d2[0]:+.4f},{d2[1]:+.4f}]  (negative = model better; market carries vig)")
        res = {"n": len(kb), "matches": len(grp), "hit": mean(y(b) for b in kb), "brier_raw": mean((b["p_raw"] - y(b)) ** 2 for b in kb),
               "brier_scaled": mean((b["p_sc"] - y(b)) ** 2 for b in kb), "brier_imp_best": mean((b["imp_best"] - y(b)) ** 2 for b in kb),
               "diff_raw_ci": d, "diff_scaled_ci": d2, "betting": {}}
        print(f"  {'rule':24s} {'bets':>5s} {'hit%':>6s} {'odds':>5s} {'ROI best':>8s} {'95% CI':>17s} {'ROI median':>10s} {'95% CI':>17s}")
        for pname, pk in (("raw", "p_raw"), ("/c", "p_sc")):
            by_T = {}
            for T in Ts:
                bl = [{**b, "p_best": (b["best"] - 1.0) if b["won"] else -1.0, "p_typ": (b["med"] - 1.0) if b["won"] else -1.0}
                      for b in kb if b[pk] - b["imp_best"] >= T]
                by_T[T] = bl
                if not bl:
                    continue
                rb, cb, _ = roi_c(bl, "p_best")
                rm, cm, _ = roi_c(bl, "p_typ")
                print(f"  {pname + ' edge>=' + str(int(T * 100)) + 'pp':24s} {len(bl):5d} {100 * mean(1.0 if b['won'] else 0.0 for b in bl):6.1f} {mean(b['best'] for b in bl):5.2f} "
                      f"{100 * rb:+7.1f}% [{100 * cb[0]:+6.1f},{100 * cb[1]:+6.1f}] {100 * rm:+9.1f}% [{100 * cm[0]:+6.1f},{100 * cm[1]:+6.1f}]")
                res["betting"][f"{pname}_edge{int(T * 100)}"] = {"bets": len(bl), "roi_best": rb, "ci_best": cb, "roi_med": rm, "ci_med": cm}
            held = lodo_c(by_T, "p_best")
            if held:
                rb, cb, _ = roi_c(held, "p_best")
                print(f"  {pname + ' LODO held-out':24s} {len(held):5d} {'':6s} {'':5s} {100 * rb:+7.1f}% [{100 * cb[0]:+6.1f},{100 * cb[1]:+6.1f}]")
                res["betting"][f"{pname}_lodo"] = {"bets": len(held), "roi_best": rb, "ci_best": cb}
        allb = [{**b, "p_best": (b["best"] - 1.0) if b["won"] else -1.0} for b in kb]
        rb, cb, _ = roi_c(allb, "p_best")
        print(f"  {'bet EVERY over (best)':24s} {len(allb):5d} {100 * mean(1.0 if b['won'] else 0.0 for b in allb):6.1f} {mean(b['best'] for b in allb):5.2f} {100 * rb:+7.1f}% [{100 * cb[0]:+6.1f},{100 * cb[1]:+6.1f}]")
        res["betting"]["every_over_best"] = {"bets": len(allb), "roi_best": rb, "ci_best": cb}
        per = []
        for lg in LEAGUES:
            lb = [{**b, "p_best": (b["best"] - 1.0) if b["won"] else -1.0} for b in kb if b["lg"] == lg and b["p_sc"] - b["imp_best"] >= 0.05]
            if len(lb) >= 10:
                rb, cb, _ = roi_c(lb, "p_best")
                per.append(f"{lg} {len(lb)}b {100 * rb:+.0f}% [{100 * cb[0]:+.0f},{100 * cb[1]:+.0f}]")
                res["betting"].setdefault("by_league_scaled_edge5", {})[lg] = {"bets": len(lb), "roi_best": rb, "ci_best": cb}
        print("  by league, /c edge>=5pp, best price: " + " | ".join(per))
        RESULTS[f"props_{kind}"] = res

    json.dump(RESULTS, open(os.path.join(S, "props_results.json"), "w", encoding="utf-8"), default=str)
    print("\nwrote props_results.json")


def roi_c(bl, field):
    by = collections.defaultdict(list)
    for b in bl:
        by[b["key"]].append(b[field])
    units = list(by.values())
    r = sum(sum(u) for u in units) / sum(len(u) for u in units)
    return r, boot_ci(units, lambda s: sum(sum(u) for u in s) / max(sum(len(u) for u in s), 1)), len(units)


def lodo_c(by_T, field, min_train=30):
    dates = sorted({b["date"] for bl in by_T.values() for b in bl})
    held = []
    for d in dates:
        best_T, best_r = None, -1e9
        for T, bl in by_T.items():
            tr = [b for b in bl if b["date"] != d]
            if len(tr) >= min_train:
                r = sum(b[field] for b in tr) / len(tr)
                if r > best_r:
                    best_T, best_r = T, r
        if best_T is not None:
            held += [b for b in by_T[best_T] if b["date"] == d]
    return held


# ============================================================================ --asof: vs the player's own average
# Lane `soccer-lines-props-backtest`, 2026-10-02. The NHL props template (lane `nhl-player-props-projection`,
# deploys.md 2026-10-02 21:38Z): a prop market earns a board probability only if the model beats the
# PLAYER'S OWN AS-OF AVERAGE and the book. Every earlier soccer prop grade used a constant or an engine
# arm as its baseline, so this mode is the missing half. Additive: `main()` above is unchanged.
#
#   population  model players bound one-to-one to an ESPN box-score player who APPEARED (books void
#               non-appearances), from the latest build generated BEFORE kickoff (`prekickoff_only`).
#   model mean  the `*_if_playing` field (the conditional-on-appearing mean the board prices since
#               fix #2); anytime = `anytime_scorer_probability_if_playing`.
#   baseline a  the player's own mean per APPEARANCE over this season's box scores with kickoff
#               strictly before this one, same league, folded name; >= ASOF_MIN_APPS prior apps.
#   baseline b  his last 5 appearances (same prior-only rule).
#   baseline c  a: shrunk toward the league's as-of per-appearance mean with ASOF_SHRINK pseudo-apps.
#   CI          match-clustered percentile bootstrap (common.boot_ci), 95%.
#   verdict     BEATS (CI wholly < 0), WORSE (wholly > 0), NO_DIFF, INSUFFICIENT_N (< ASOF_MIN_ROWS rows
#               or < ASOF_MIN_MATCHES matches).
#   book        one-sided OVER prices only, so NO de-vig exists: the comparison is model vs the raw
#               implied probability (with vig) and flat-stake ROI at the best price, and it can never
#               certify "beats the de-vigged book" -- which keeps the gate shut by construction.
ASOF_MIN_APPS, ASOF_SHRINK = 3, 3.0
ASOF_MIN_ROWS, ASOF_MIN_MATCHES = 200, 30
ASOF_POST_FIX = {"shots": "2026-09-17T00:00:00+00:00", "sot": "2026-09-17T00:00:00+00:00",
                 "goals": "2026-09-17T00:00:00+00:00", "assists": "2026-09-19T00:00:00+00:00"}
ASOF_STATS = {"shots": ("expected_shots_if_playing", "shots", (0.5, 1.5, 2.5)),
              "sot": ("expected_shots_on_target_if_playing", "sot", (0.5, 1.5)),
              "goals": ("anytime_scorer_probability_if_playing", "goals", (0.5,)),
              "assists": ("expected_assists_if_playing", "assists", (0.5,))}
ASOF_BOOK = {"player_shots": "shots", "player_shots_on_target": "sot",
             "player_goal_scorer_anytime": "goals", "player_assists": "assists"}


def _asof_history(outc):
    """(league, folded name) -> [(kickoff, appeared-row)] sorted; league -> [(kickoff, row)] for the league mean."""
    hist, league_rows = collections.defaultdict(list), collections.defaultdict(list)
    for (lg, mid), o in outc.items():
        k = ts(o.get("kickoff")) or ts(f"{o.get('date')}T12:00:00Z")
        for p in o.get("players") or []:
            if not appeared(p):
                continue
            hist[(lg, fold(p["name"]))].append((k, p))
            league_rows[lg].append((k, p))
    for v in list(hist.values()) + list(league_rows.values()):
        v.sort(key=lambda x: x[0])
    return hist, league_rows


def _asof_val(p, stat):
    v = p.get(stat)
    if stat == "goals":
        return 1.0 if (v or 0) >= 1 else 0.0          # the anytime outcome, not the goal count
    return None if v is None else float(v)


def _verdict(n, matches, ci):
    if n < ASOF_MIN_ROWS or matches < ASOF_MIN_MATCHES:
        return "INSUFFICIENT_N"
    if ci[1] < 0:
        return "BEATS"
    if ci[0] > 0:
        return "WORSE"
    return "NO_DIFF"


def _clip(p):
    return min(max(p, 1e-4), 1 - 1e-4)


def _boot_rows(units, fn, reps=2000, seed=11):
    """Match-clustered percentile CI of mean(fn(row)) -- the same estimator as common.boot_ci over
    units, computed from per-match (sum, count) so a resample costs O(matches), not O(rows)."""
    import numpy as np
    if len(units) < 5:
        return (float("nan"), float("nan"))
    sums = np.array([sum(fn(r) for r in u) for u in units], dtype=float)
    cnts = np.array([len(u) for u in units], dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(units), size=(reps, len(units)))
    vals = np.sort(sums[idx].sum(axis=1) / cnts[idx].sum(axis=1))
    return float(vals[int(0.025 * reps)]), float(vals[int(0.975 * reps) - 1])


def grade_asof(out_path, dump_rows=None):
    recs = load_recs(prekickoff_only=True)
    outc = load_outcomes()
    hist, league_rows = _asof_history(outc)
    funnel = collections.Counter()
    rows = []
    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        if not o:
            funnel["match_no_outcome"] += 1
            continue
        funnel["match_graded"] += 1
        kick = m["kickoff"]
        bound = bind_players(m["players"], o["players"])
        lg_prior = [p for k, p in league_rows[lg] if k < kick]
        lg_mean = {}
        for stat, (_f, ostat, _l) in ASOF_STATS.items():
            lv = [v for v in (_asof_val(q, ostat) for q in lg_prior) if v is not None]
            lg_mean[stat] = mean(lv) if lv else None
        for p in m["players"]:
            funnel["model_player_rows"] += 1
            hit = bound.get(id(p))
            if hit is None:
                funnel["unbound_to_box_score"] += 1
                continue
            if not appeared(hit):
                funnel["did_not_appear(void)"] += 1
                continue
            prior = [q for k, q in hist.get((lg, fold(hit["name"])), []) if k < kick]
            r = {"lg": lg, "key": f"{lg}|{mid}", "date": m["date"], "gen": m["generated_at"],
                 "starter": bool(hit["starter"]), "n_prior": len(prior), "share": p.get("expected_minutes_share")}
            for stat, (field, ostat, _lines) in ASOF_STATS.items():
                mv, y = p.get(field), _asof_val(hit, ostat)
                vals = [v for v in (_asof_val(q, ostat) for q in prior) if v is not None]
                lmean = lg_mean[stat]
                r[stat] = {"model": None if mv is None else float(mv), "y": y,
                           "a": mean(vals) if len(vals) >= ASOF_MIN_APPS else None,
                           "b": mean(vals[-5:]) if len(vals) >= ASOF_MIN_APPS else None,
                           "c": ((sum(vals) + ASOF_SHRINK * lmean) / (len(vals) + ASOF_SHRINK)) if lmean is not None else None,
                           "lmean": lmean}
            rows.append(r)
            funnel["appeared_rows"] += 1
    print("=== AS-OF FUNNEL ===", dict(funnel))
    if dump_rows:
        # H38 (lane soccer-shots-allocation-blend): one JSON line per appeared player-row, every stat's
        # model / actual / baselines, so a fitted estimator can be scored without re-reading the cache.
        with open(dump_rows, "w", encoding="utf-8") as handle:
            for r in rows:
                handle.write(json.dumps({**r, "gen": r["gen"].isoformat() if r["gen"] else None}, default=str) + "\n")

    def cell(rs, stat):
        rs = [r for r in rs if r[stat]["model"] is not None and r[stat]["y"] is not None and r[stat]["a"] is not None]
        if not rs:
            return {"n": 0, "verdict": "INSUFFICIENT_N"}
        by = collections.defaultdict(list)
        for r in rs:
            by[r["key"]].append(r)
        units = list(by.values())
        g = lambda r, k: r[stat][k]
        out = {"n": len(rs), "matches": len(units), "dates": f"{min(r['date'] for r in rs)}..{max(r['date'] for r in rs)}",
               "mean_actual": mean(g(r, "y") for r in rs), "mean_model": mean(g(r, "model") for r in rs),
               "mean_base_a": mean(g(r, "a") for r in rs),
               "bias_model": mean(g(r, "model") - g(r, "y") for r in rs)}
        for k in ("model", "a", "b", "c"):
            out[f"mae_{k}"] = mean(abs(g(r, k) - g(r, "y")) for r in rs)
        if stat == "goals":   # binary: Brier is the MAE analogue; MAE of a probability is not a proper score
            for k in ("model", "a", "b", "c"):
                out[f"brier_{k}"] = mean((g(r, k) - g(r, "y")) ** 2 for r in rs)
            loss = lambda r, k: (g(r, k) - g(r, "y")) ** 2
        else:
            loss = lambda r, k: abs(g(r, k) - g(r, "y"))
        for k in ("a", "b", "c"):
            d = mean(loss(r, "model") - loss(r, k) for r in rs)
            ci = _boot_rows(units, lambda r, k=k: loss(r, "model") - loss(r, k))
            out[f"d_vs_{k}"] = {"point": d, "ci95": ci, "verdict": _verdict(len(rs), len(units), ci)}
        # probability at standard lines: model vs Poisson(baseline a), both conditional on appearing
        lines = {}
        for line in ASOF_STATS[stat][2]:
            kk = int(math.floor(line)) + 1
            def pm(r):
                return g(r, "model") if stat == "goals" else poisson_sf(kk, g(r, "model"))
            def pb(r):
                return (1 - math.exp(-max(g(r, "a"), 0.0))) if stat == "goals" else poisson_sf(kk, max(g(r, "a"), 1e-9))
            yy = lambda r: 1.0 if (g(r, "y") >= kk) else 0.0
            bm = mean((pm(r) - yy(r)) ** 2 for r in rs)
            bb = mean((pb(r) - yy(r)) ** 2 for r in rs)
            lm = mean(-math.log(_clip(pm(r)) if yy(r) else 1 - _clip(pm(r))) for r in rs)
            lb = mean(-math.log(_clip(pb(r)) if yy(r) else 1 - _clip(pb(r))) for r in rs)
            ci = _boot_rows(units, lambda r: (pm(r) - yy(r)) ** 2 - (pb(r) - yy(r)) ** 2)
            def pc(r):   # the shrunk baseline c: the fairer naive probability early in a season
                return (1 - math.exp(-max(g(r, "c"), 0.0))) if stat == "goals" else poisson_sf(kk, max(g(r, "c"), 1e-9))
            bc = mean((pc(r) - yy(r)) ** 2 for r in rs)
            lc = mean(-math.log(_clip(pc(r)) if yy(r) else 1 - _clip(pc(r))) for r in rs)
            ci_c = _boot_rows(units, lambda r: (pm(r) - yy(r)) ** 2 - (pc(r) - yy(r)) ** 2)
            ci_lc = _boot_rows(units, lambda r: (-math.log(_clip(pm(r)) if yy(r) else 1 - _clip(pm(r))))
                               - (-math.log(_clip(pc(r)) if yy(r) else 1 - _clip(pc(r)))))
            lines[str(line)] = {"base_rate": mean(yy(r) for r in rs), "brier_model": bm, "brier_base_a": bb,
                                "logloss_model": lm, "logloss_base_a": lb, "dbrier": bm - bb, "dbrier_ci95": ci,
                                "verdict": _verdict(len(rs), len(units), ci),
                                "brier_base_c": bc, "logloss_base_c": lc, "dbrier_vs_c": bm - bc, "dbrier_vs_c_ci95": ci_c,
                                "verdict_vs_c": _verdict(len(rs), len(units), ci_c),
                                "dlogloss_vs_c": lm - lc, "dlogloss_vs_c_ci95": ci_lc,
                                "verdict_logloss_vs_c": _verdict(len(rs), len(units), ci_lc)}
        out["lines"] = lines
        return out

    report = {"funnel": dict(funnel), "params": {"min_apps": ASOF_MIN_APPS, "shrink": ASOF_SHRINK, "min_rows": ASOF_MIN_ROWS,
                                                  "min_matches": ASOF_MIN_MATCHES, "post_fix": ASOF_POST_FIX},
              "coverage": {"recs_prekickoff_matches": len(recs), "outcome_matches": len(outc),
                           "intersection_matches": funnel["match_graded"]},
              "cells": {}}
    for stat in ASOF_STATS:
        post = ts(ASOF_POST_FIX[stat])
        arms = {"all_versions": rows,
                "pre_fix": [r for r in rows if r["gen"] and r["gen"] < ts("2026-09-15T21:38:00+00:00")],
                "post_fix": [r for r in rows if r["gen"] and r["gen"] >= post]}
        for arm, rs in arms.items():
            report["cells"][f"{stat}|{arm}|ALL"] = cell(rs, stat)
            for role, sel in (("starter", True), ("sub", False)):
                report["cells"][f"{stat}|{arm}|role={role}"] = cell([r for r in rs if r["starter"] is sel], stat)
            if arm == "all_versions":
                small = []
                for lg in LEAGUES:
                    c = cell([r for r in rs if r["lg"] == lg], stat)
                    if c.get("matches", 0) >= ASOF_MIN_MATCHES:
                        report["cells"][f"{stat}|{arm}|{lg}"] = c
                    else:
                        small.append(lg)
                if small:
                    report["cells"][f"{stat}|{arm}|POOLED_SMALL({'+'.join(small)})"] = cell([r for r in rs if r["lg"] in small], stat)
    report["book"] = _asof_book(recs, outc, hist)
    json.dump(report, open(out_path, "w", encoding="utf-8"), default=str, indent=1)
    for k, c in report["cells"].items():
        if not c.get("n"):
            print(f"  {k:55s} n=0")
            continue
        da = c["d_vs_a"]
        print(f"  {k:55s} n={c['n']:6d} m={c['matches']:4d} act {c['mean_actual']:.3f} mod {c['mean_model']:.3f} base {c['mean_base_a']:.3f} "
              f"MAE mod {c['mae_model']:.4f} a {c['mae_a']:.4f} | d(loss) vs a {da['point']:+.4f} [{da['ci95'][0]:+.4f},{da['ci95'][1]:+.4f}] {da['verdict']}")
    print(f"wrote {out_path}")


def _asof_book(recs, outc, hist):
    """One-sided OVER prices: model vs raw implied (with vig) on the same rows, and flat ROI at the best price
    when model p > implied, beside the same rule driven by baseline a. Rows: appeared + baseline a present."""
    frames = []
    for f in glob.glob(os.path.join(S, "prod", "props", "*.csv")):
        b = os.path.basename(f)
        if b.startswith("_") or os.path.getsize(f) < 50:
            continue
        mdate = re.search(r"(\d{4}-\d{2}-\d{2})\.csv$", b)
        try:
            fr = pd.read_csv(f)
        except Exception:
            continue
        if fr.empty or "market_key" not in fr:
            continue
        fr = fr[fr["market_key"].isin(list(ASOF_BOOK))].copy()
        fr["_fdate"] = mdate.group(1) if mdate else ""
        frames.append(fr)
    if not frames:
        return {"n": 0, "reason": "no prop price rows"}
    px = pd.concat(frames, ignore_index=True)
    px["_gt"] = px["game_time"].map(ts)
    px = px[px["_gt"].notna()]
    px = px[px["_fdate"] <= px["_gt"].map(lambda t: t.date().isoformat())]
    px = px.sort_values("_fdate").drop_duplicates(["event_id", "player", "market_key", "line", "book"], keep="last")
    two_sided = int(px["under_price"].notna().sum()) if "under_price" in px else 0
    by_league = collections.defaultdict(list)
    for (lg, mid), m in recs.items():
        by_league[lg].append(m)
    offers = collections.defaultdict(list)
    for ev, g in px.groupby("event_id"):
        r0 = g.iloc[0]
        m = find_fixture(r0["home_team"], r0["away_team"], [(x["home"], x["away"], x) for x in by_league.get(r0["league"], [])
                                                            if x["kickoff"] and abs((x["kickoff"] - r0["_gt"]).total_seconds()) <= 3 * 3600])
        if m is None:
            continue
        for r in g.itertuples():
            line = float(r.line) if pd.notna(r.line) else 0.5
            offers[(r0["league"], m["match_id"], fold(r.player), ASOF_BOOK[r.market_key], line)].append(dec_from_american(r.over_price))
    bets, drop = [], collections.Counter()
    bind = {}
    for (lg, mid, pname, stat, line), decs in offers.items():
        m, o = recs.get((lg, mid)), outc.get((lg, mid))
        if not m or not o:
            drop["no_outcome"] += 1
            continue
        sc = sorted(((name_score(pname, p.get("player_name")), k) for k, p in enumerate(m["players"])), reverse=True)
        if not sc or sc[0][0] < 0.84 or (len(sc) > 1 and sc[1][0] >= sc[0][0]):
            drop["no_model_player"] += 1
            continue
        pm = m["players"][sc[0][1]]
        if (lg, mid) not in bind:
            bind[(lg, mid)] = bind_players(m["players"], o["players"])
        hit = bind[(lg, mid)].get(id(pm))
        if hit is None or not appeared(hit):
            drop["void_or_unbound"] += 1
            continue
        field, ostat, _ = ASOF_STATS[stat]
        mv, y = pm.get(field), _asof_val(hit, ostat)
        prior = [v for v in (_asof_val(q, ostat) for k, q in hist.get((lg, fold(hit["name"])), []) if k < m["kickoff"]) if v is not None]
        if mv is None or y is None or len(prior) < ASOF_MIN_APPS:
            drop["no_model_value_or_baseline"] += 1
            continue
        kk = int(math.floor(line)) + 1
        a = mean(prior)
        p_mod = float(mv) if stat == "goals" else poisson_sf(kk, float(mv))
        p_base = (1 - math.exp(-a)) if stat == "goals" else poisson_sf(kk, max(a, 1e-9))
        best = max(decs)
        bets.append({"stat": stat, "line": line, "key": f"{lg}|{mid}", "date": m["date"], "gen": m["generated_at"],
                     "won": (y >= kk), "p_mod": p_mod, "p_base": p_base, "imp": 1.0 / best, "best": best})
    out = {"price_rows": int(len(px)), "two_sided_rows": two_sided, "graded_player_lines": len(bets), "dropped": dict(drop), "markets": {}}
    for stat in ASOF_STATS:
        kb = [b for b in bets if b["stat"] == stat]
        if not kb:
            out["markets"][stat] = {"n": 0}
            continue
        by = collections.defaultdict(list)
        for b in kb:
            by[b["key"]].append(b)
        units = list(by.values())
        yv = lambda b: 1.0 if b["won"] else 0.0
        res = {"n": len(kb), "matches": len(units), "hit_rate": mean(yv(b) for b in kb),
               "brier_model": mean((b["p_mod"] - yv(b)) ** 2 for b in kb), "brier_base_a": mean((b["p_base"] - yv(b)) ** 2 for b in kb),
               "brier_implied_with_vig": mean((b["imp"] - yv(b)) ** 2 for b in kb),
               "mean_p_model": mean(b["p_mod"] for b in kb), "mean_implied": mean(b["imp"] for b in kb)}
        res["dbrier_model_minus_implied_ci95"] = _boot_rows(units, lambda b: (b["p_mod"] - yv(b)) ** 2 - (b["imp"] - yv(b)) ** 2)
        for who, pk in (("model", "p_mod"), ("base_a", "p_base")):
            bl = [{**b, "pl": (b["best"] - 1.0) if b["won"] else -1.0} for b in kb if b[pk] > b["imp"]]
            if bl:
                r, ci, nu = roi_c(bl, "pl")
                res[f"roi_{who}_ev_pos"] = {"bets": len(bl), "matches": nu, "roi": r, "ci95": ci}
        out["markets"][stat] = res
    return out


if __name__ == "__main__":
    import sys
    if "--asof" in sys.argv:
        _dump = sys.argv[sys.argv.index("--dump-rows") + 1] if "--dump-rows" in sys.argv else None
        grade_asof(sys.argv[sys.argv.index("--asof") + 1] if len(sys.argv) > sys.argv.index("--asof") + 1
                   else os.path.join(S, "asof_props.json"), dump_rows=_dump)
    else:
        main()
