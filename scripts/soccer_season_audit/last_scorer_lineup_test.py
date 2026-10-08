# -*- coding: utf-8 -*-
"""Last goalscorer with the CONFIRMED LINEUP known: calibration and price test, out of sample.

Lane `soccer-last-scorer-lineup` (2026-10-08), hypothesis and ship rule pre-registered in
lanes.md (2243e188) before this ran. `findings_2026-10-05_soccer_last_scorer.md` ended:
"the fix that would matter is knowing the bench". The live pipeline does know it within
~1 h of kickoff (`features/lineups.attach_confirmed_starters`, wired into
`build_soccer_artifacts.py`), so this measures what that knowledge is worth.

THREE RACES, same players, same rates, same lines:
- `board`  : `soccer_scorer_markets.scorer_race`, timing-blind (what the board prices).
- `timed`  : the 10-05 time-aware race; role GUESSED from `expected_minutes_share`.
- `lineup` : the time-aware race with the role KNOWN. From ESPN's matchday roster, a
             listed player is in the starting XI (starter on-pitch curve), on the bench
             (substitute curve), or not in the squad (removed; his rate joins the
             unlisted residual). A bench player's last-scorer probability is then made
             CONDITIONAL ON APPEARING, divided by P(bench player comes on), because a
             player who does not take part is a VOID bet -- the price is for "if he plays".
             Starters appear with probability 1.

ESPN's `starter` flag stands in for the lineup published ~1 h pre-kickoff, so this is an
UPPER BOUND on the live mechanism (warm-up changes are ignored). Curves, goal intensity,
w(m) and P(bench appears) are fitted on matches BEFORE `--split`; everything reported is
on/after it, post-09-07 builds only. Pricing and void rules are `last_scorer_price_test.py`'s.

    SOCCER_AUDIT_CACHE=C:/tmp/soccer-lpb/cache py -3 last_scorer_lineup_test.py [--split 2026-09-16]
"""
import argparse
import collections
import glob
import io
import json
import math
import os

import last_scorer_timed_race as timed
from common import boot_ci, dec_from_american, load_recs, same_fixture, ts
from grade_scorer_race import (CT, ESPN_CACHE, _espn_outcome, _load_prices, _lookup_player, _norm_name,
                               _same_person, scorer_race)
from syndicate.features.shared.soccer_scorer_markets import player_goal_rate

T = timed.T


def _matchday_roster(path):
    """[(norm_name, starter, appeared)] for everyone on ESPN's matchday sheet."""
    j = json.load(io.open(path, encoding="utf-8"))
    out = []
    for r in j.get("rosters") or []:
        for p in r.get("roster") or []:
            sub = p.get("subbedIn")
            if isinstance(sub, dict):
                sub = sub.get("didSub")
            name = _norm_name((p.get("athlete") or {}).get("displayName"))
            if name:
                out.append((name, bool(p.get("starter")), bool(p.get("starter") or sub)))
    return out


def _role(roster, board_name):
    hits = [(starter, appeared) for name, starter, appeared in roster if _same_person(board_name, name)]
    if len(hits) != 1:
        return "absent" if not hits else None  # ambiguous -> None (keep the timed guess)
    return "starter" if hits[0][0] else "bench"


def fit_bench_appear(matches_paths):
    """P(a bench player comes on), pooled over the fit matches."""
    on = tot = 0
    for path in matches_paths:
        for _name, starter, appeared in _matchday_roster(path):
            if not starter:
                tot += 1
                on += int(appeared)
    return (on + 1) / (tot + 2), tot


def lineup_race(players, total_mean, roster, S, B, G, W, p_bench):
    """{norm_name: (p_first, p_last, role)}; bench probabilities conditional on appearing."""
    profiles, roles, listed = {}, {}, 0.0
    for pl in players:
        name = _norm_name(pl.get("player_name"))
        lam = player_goal_rate(pl.get("anytime_scorer_probability"))
        if not name or lam is None:
            continue
        role = _role(roster, name)
        if role == "absent":
            continue
        if role == "starter":
            curve = S
        elif role == "bench":
            curve = B
        else:
            share = pl.get("expected_minutes_share")
            w = W[min(timed.M_BUCKETS - 1, int(float(share) * timed.M_BUCKETS))] if share is not None else 1.0
            curve = [w * S[t] + (1 - w) * B[t] for t in range(T)]
        o = [G[t] * curve[t] for t in range(T)]
        z = sum(o) or 1.0
        profiles[name] = [lam * x / z for x in o]
        roles[name] = role or "unresolved"
        listed += lam
    lam_total = max(float(total_mean), listed) if total_mean is not None else listed
    resid = max(0.0, lam_total - listed)
    total_t = [resid * G[t] / T + sum(p[t] for p in profiles.values()) for t in range(T)]
    cum = [0.0]
    for t in range(T):
        cum.append(cum[-1] + total_t[t])
    out = {}
    for name, prof in profiles.items():
        first = sum(prof[t] * math.exp(-cum[t]) * timed._within(total_t[t]) for t in range(T))
        last = sum(prof[t] * math.exp(-(cum[T] - cum[t + 1])) * timed._within(total_t[t]) for t in range(T))
        if roles[name] == "bench":
            first, last = min(0.99, first / p_bench), min(0.99, last / p_bench)
        out[name] = (first, last, roles[name])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="2026-09-16")
    ap.add_argument("--out")
    args = ap.parse_args()
    timed.W_VERSION = "post0907"

    recs = load_recs(prekickoff_only=True)
    parsed, paths = [], {}
    for path in glob.glob(os.path.join(ESPN_CACHE, "*.json")):
        m = timed._parse(path)
        if m is None:
            continue
        m["key"] = tuple(os.path.basename(path)[:-5].rsplit("_", 1))
        parsed.append(m)
        paths[m["key"]] = path
    fit = [m for m in parsed if m["date"] and m["date"] < args.split]
    S, B, G, W = timed._fit(fit, recs)
    p_bench, n_bench = fit_bench_appear([paths[m["key"]] for m in fit])

    prices = _load_prices()
    price_dates = sorted(prices)
    rows, drop, roles_seen = [], collections.Counter(), collections.Counter()
    cal = collections.defaultdict(lambda: [0.0, 0])
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
        roster = _matchday_roster(paths[(league, mid)]) if (league, mid) in paths else []
        if not roster:
            drop["no_roster"] += 1
            continue
        board = {_norm_name(k): v for k, v in (scorer_race(rec["players"], match_expected_goals=rec["total_mean"]).get("by_player") or {}).items()}
        tim = {k: v[1] for k, v in timed.timed_race(rec["players"], rec["total_mean"], S, B, G, W).items()}
        lin_full = lineup_race(rec["players"], rec["total_mean"], roster, S, B, G, W, p_bench)
        lin = {k: v[1] for k, v in lin_full.items()}

        # (a) calibration over every listed player who APPEARED (graded = not void)
        for name, starter, appeared in roster:
            if not appeared:
                continue
            p_b, _ = _lookup_player(board, name)
            p_t, _ = _lookup_player(tim, name)
            p_l, key = _lookup_player(lin, name)
            if p_b is None or p_t is None or p_l is None:
                continue
            won = int(outcome["last"] is not None and _same_person(name, outcome["last"]))
            role = "starter" if starter else "sub"
            for model, p in (("board", p_b), ("timed", p_t), ("lineup", p_l)):
                cal[(model, role)][0] += p
                cal[(model, role)][1] += won

        # (b) the price
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
        for player, grp in px.groupby("player"):
            pname = _norm_name(player)
            if not pname or "no scorer" in pname or "no goalscorer" in pname:
                continue
            p_b, _ = _lookup_player(board, player)
            p_t, _ = _lookup_player(tim, player)
            p_l, _ = _lookup_player(lin, player)
            full, _ = _lookup_player(lin_full, player)
            role = full[2] if full else "unresolved"
            if p_b is None or p_t is None:
                drop["player_not_in_race"] += 1
                continue
            if p_l is None:
                # Not in the matchday squad: the lineup model would not offer this line at
                # all, and the book voids it. It cannot be graded either way.
                drop["absent_from_matchday_squad"] += 1
                if any(_same_person(pname, a) for a in outcome["appeared"]):
                    # A NAME-MATCH FAILURE, not an absence: the lineup race removed a player
                    # who played. Counted so the result can be judged with it in view.
                    drop["absent_but_appeared_name_miss"] += 1
                continue
            if not any(_same_person(pname, a) for a in outcome["appeared"]):
                drop["dnp_void"] += 1
                continue
            decs = sorted(dec_from_american(x) for x in grp.over_price.dropna())
            if not decs:
                continue
            roles_seen[role] += 1
            rows.append({"match": f"{league}|{mid}", "date": kick_ct, "board": p_b, "timed": p_t, "lineup": p_l,
                         "role": role, "dec": decs[-1],
                         "won": int(outcome["last"] is not None and _same_person(pname, outcome["last"]))})

    by_match = collections.defaultdict(list)
    for r in rows:
        by_match[r["match"]].append(r)
    units = list(by_match.values())

    def bets(us, key, role=None):
        return [x for u in us for x in u if x[key] * x["dec"] > 1.0 and (role is None or x["role"] == role)]

    def roi(us, key, role=None):
        xs = bets(us, key, role)
        return sum((x["dec"] - 1) if x["won"] else -1.0 for x in xs) / len(xs) if xs else float("nan")

    def ll(us, key):
        xs = [x for u in us for x in u]
        return -sum(math.log(max(1e-6, x[key])) if x["won"] else math.log(max(1e-6, 1 - x[key])) for x in xs) / len(xs)

    report = {
        "split": args.split, "lines": len(rows), "matches": len(units), "dates": len({r["date"] for r in rows}),
        "wins": sum(r["won"] for r in rows), "dropped": dict(drop), "graded_line_roles": dict(roles_seen),
        "fitted": {"p_bench_appears": round(p_bench, 4), "bench_entries_in_fit": n_bench},
        "calibration_realised_over_expected_appeared_players": {
            f"{m}/{r}": round(c[1] / c[0], 3) if c[0] else None for (m, r), c in sorted(cal.items())},
        "calibration_counts": {f"{m}/{r}": {"expected": round(c[0], 2), "realised": c[1]} for (m, r), c in sorted(cal.items())},
    }
    for key in ("board", "timed", "lineup"):
        b = bets(units, key)
        report[key] = {"ev_pos_bets": len(b), "ev_pos_wins": sum(x["won"] for x in b),
                       "roi": round(roi(units, key), 4) if b else None,
                       "roi_ci95": [round(v, 4) for v in boot_ci(units, lambda us, k=key: roi(us, k))] if b else None,
                       "logloss": round(ll(units, key), 5),
                       "by_role": {r: {"bets": len(bets(units, key, r)), "wins": sum(x["won"] for x in bets(units, key, r)),
                                       "roi": round(roi(units, key, r), 4) if bets(units, key, r) else None}
                                   for r in ("starter", "bench", "unresolved")}}
    # EXPLORATORY (not in the pre-registration): the bench subgroup on its own.
    report["exploratory_lineup_bench_roi_ci95"] = [round(v, 4) for v in boot_ci(units, lambda us: roi(us, "lineup", "bench"))]
    report["exploratory_lineup_starter_roi_ci95"] = [round(v, 4) for v in boot_ci(units, lambda us: roi(us, "lineup", "starter"))]
    for a, b in (("lineup", "board"), ("lineup", "timed")):
        report[f"logloss_{a}_minus_{b}_ci95"] = [round(v, 5) for v in boot_ci(units, lambda us, a=a, b=b: ll(us, a) - ll(us, b))]
        report[f"roi_{a}_minus_{b}_ci95"] = [round(v, 4) for v in boot_ci(units, lambda us, a=a, b=b: roi(us, a) - roi(us, b))]
    print(json.dumps(report, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)


if __name__ == "__main__":
    main()
