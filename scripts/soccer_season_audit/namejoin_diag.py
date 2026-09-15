# -*- coding: utf-8 -*-
"""Is the player join, not the model, what moves the shots verdict between 1.40 and 0.88?

Three matchers, predicted (Understat/ASA/ESPN-aggregate names) -> ESPN matchday roster:
  exact   : folded full name, or first-initial + surname, unique per side (audit_props.py)
  strict1 : exact, then a ONE-TO-ONE greedy assignment on token containment / surname /
            SequenceMatcher >= 0.84, per side, best score first
Reported per league: share of ESPN APPEARED players matched, share of real team shots
attributed to a matched predicted player, and the shots ratio under each matcher and
under the 2026-08-31 method (unconditional mean, every predicted row, unmatched -> 0).
"""
import collections
import os
import random
from difflib import SequenceMatcher

from common import LEAGUES, fold, load_outcomes, load_recs, mean


def appeared(p):
    return bool(p["starter"] or p["subbed_in"] or (p.get("appearances") or 0) > 0)


def toks(n):
    return [t for t in fold(n).split() if t]


def score(a, b):
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return 0.0
    if " ".join(ta) == " ".join(tb):
        return 1.0
    sa, sb = set(ta), set(tb)
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    if small <= big:
        return 0.95
    if ta[-1] == tb[-1] and ta[0][:1] == tb[0][:1]:
        return 0.93
    r = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    if ta[-1] == tb[-1]:
        r = max(r, 0.85)
    return r


def exact_match(preds, roster):
    out = {}
    for i, p in enumerate(preds):
        f = toks(p["player_name"])
        cands = [j for j, q in enumerate(roster) if toks(q["name"]) == f]
        if len(cands) != 1 and f:
            cands = [j for j, q in enumerate(roster) if toks(q["name"]) and toks(q["name"])[-1] == f[-1] and toks(q["name"])[0][:1] == f[0][:1]]
        if len(cands) == 1:
            out[i] = cands[0]
    return out


def strict_match(preds, roster, thr=0.84):
    pairs = sorted(((score(p["player_name"], q["name"]), i, j) for i, p in enumerate(preds) for j, q in enumerate(roster)), reverse=True)
    used_i, used_j, out = set(), set(), {}
    for s, i, j in pairs:
        if s < thr:
            break
        if i in used_i or j in used_j:
            continue
        out[i] = j
        used_i.add(i)
        used_j.add(j)
    return out


def main():
    recs, outc = load_recs(), load_outcomes()
    stats = collections.defaultdict(lambda: collections.Counter())
    rows = collections.defaultdict(list)
    samples = []
    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        if not o or not m["players"]:
            continue
        for side in ("home", "away"):
            preds = [p for p in m["players"] if p.get("side") == side]
            roster = [q for q in o["players"] if q["side"] == side]
            team_shots = sum(q["shots"] or 0 for q in roster)
            st = stats[lg]
            st["pred"] += len(preds)
            st["roster"] += len(roster)
            st["appeared"] += sum(1 for q in roster if appeared(q))
            st["team_shots"] += team_shots
            for name, fn in (("exact", exact_match), ("strict", strict_match)):
                mp = fn(preds, roster)
                matched_j = set(mp.values())
                st[f"{name}_pred_matched"] += len(mp)
                st[f"{name}_app_matched"] += sum(1 for j, q in enumerate(roster) if appeared(q) and j in matched_j)
                st[f"{name}_shots_attr"] += sum(q["shots"] or 0 for j, q in enumerate(roster) if j in matched_j)
                for i, p in enumerate(preds):
                    q = roster[mp[i]] if i in mp else None
                    rows[(lg, name)].append({"date": m["date"], "es": p.get("expected_shots") or 0.0, "esp": p.get("expected_shots_if_playing"),
                                             "share": p.get("expected_minutes_share") or 0.0, "matched": q is not None,
                                             "played": bool(q and appeared(q)), "shots": (q["shots"] or 0.0) if q else 0.0})
                if name == "strict":
                    un_q = [q for j, q in enumerate(roster) if appeared(q) and j not in matched_j and (q["shots"] or 0) > 0]
                    un_p = [p["player_name"] for i, p in enumerate(preds) if i not in mp]
                    if un_q and random.random() < 0.08 and len(samples) < 25:
                        samples.append((lg, [q["name"] for q in un_q][:3], un_p[:8]))
    print(f"{'league':20s} {'pred/team':>9s} {'roster/team':>11s} | exact: {'pred m%':>7s} {'app m%':>6s} {'shots attr%':>11s} | strict: {'pred m%':>7s} {'app m%':>6s} {'shots attr%':>11s}")
    for lg in LEAGUES:
        st = stats[lg]
        teams = max(st["roster"] and 1, 1)
        n_team = sum(1 for (l, _), m in recs.items() if l == lg and outc.get((l, _)) and m["players"]) * 2
        if not n_team:
            continue
        print(f"{lg:20s} {st['pred'] / n_team:9.1f} {st['roster'] / n_team:11.1f} | "
              f"       {100 * st['exact_pred_matched'] / max(st['pred'], 1):7.1f} {100 * st['exact_app_matched'] / max(st['appeared'], 1):6.1f} {100 * st['exact_shots_attr'] / max(st['team_shots'], 1):11.1f} | "
              f"        {100 * st['strict_pred_matched'] / max(st['pred'], 1):7.1f} {100 * st['strict_app_matched'] / max(st['appeared'], 1):6.1f} {100 * st['strict_shots_attr'] / max(st['team_shots'], 1):11.1f}")
    print("\nSHOTS RATIO pred/real under each matcher (all dates, all leagues):")
    for name in ("exact", "strict"):
        allr = [r for lg in LEAGUES for r in rows[(lg, name)]]
        method_0831 = mean(r["es"] for r in allr) / max(mean(r["shots"] for r in allr), 1e-9)
        app = [r for r in allr if r["played"] and r["esp"] is not None]
        print(f"  {name:7s} 08-31 method (unconditional, every predicted row, unmatched->0): n={len(allr)} pred {mean(r['es'] for r in allr):.3f} real {mean(r['shots'] for r in allr):.3f} ratio {method_0831:.3f}")
        print(f"  {name:7s} appeared-only, if_playing mean: n={len(app)} pred {mean(r['esp'] for r in app):.3f} real {mean(r['shots'] for r in app):.3f} ratio {mean(r['esp'] for r in app) / max(mean(r['shots'] for r in app), 1e-9):.3f}")
        for lab, lo, hi in (("share<0.5", 0, 0.5), ("0.5-0.85", 0.5, 0.85), (">=0.85", 0.85, 2)):
            g = [r for r in app if lo <= r["share"] < hi]
            if g:
                print(f"      {lab:10s} n={len(g):5d} pred {mean(r['esp'] for r in g):.3f} real {mean(r['shots'] for r in g):.3f} ratio {mean(r['esp'] for r in g) / max(mean(r['shots'] for r in g), 1e-9):.2f}")
    print("\nSAMPLE: appeared ESPN shooters the STRICT matcher could not bind, beside that side's unbound predicted names")
    for lg, q, p in samples:
        print(f"  {lg:18s} ESPN {q}  || predicted-unbound {p}")


if __name__ == "__main__":
    random.seed(3)
    main()
