"""Where does the LIVE full-game MONEYLINE's Brier gap to the market come from? READ-ONLY.

Todo #780, lane live-moneyline-gap-diagnosis (user 2026-11-13 "Diagnose it now"). Hypotheses H1-H4 were written into the
lane before this ran. The fit that surfaced the gap: `.syndicate/findings_2026-11-13_live_margin_width_fit.md`
(model - market Brier, NBA +0.020, NCAAB +0.009; tempering does not close it).

Population: the fleet's live gameline ledgers, h2h / full rows with a model P(home wins) and a market fair P(home),
one per (event_id, live_state_as_of), matched to the ESPN final in the LEDGER's home orientation (the fit script's
`finals_margin` / `ledger_home_margin`); a tied final is dropped. Ledger dates <= UNTIL (default 2026-11-12), so the
PREREG_780 window (NCAAB >= 11-13) is never read.

Prints, per sport:
  0. the reproduction: Brier model, market, and model - market, game-clustered 95%;
  H1 bias: signed residual (y - p) for model and market, calibration by model-probability bin, and the logistic
     calibration intercept / slope of each;
  H2 stage: model - market Brier by progress (points scored / the model's total mean);
  H3 staleness: model - market Brier by state age (recorded_at - live_state_as_of) and by whether the quote is newer
     than the state the model saw;
  H4 information: logistic y ~ a + b1 logit(p_model) + b2 logit(p_market), b1 / b2 with a game bootstrap;
  and, descriptive: the lead table (model - market by the home lead) and the big-disagreement rows.

Run on the fleet host (nice 19):
    wsl -d Ubuntu-24.04 -- nice -n 19 python3 /mnt/c/<repo>/scripts/live_moneyline_gap.py </dev/null
    env: SPORTS (default nba,ncaab,ncaaf,wncaab), UNTIL, ESPN_CACHE (default /mnt/c/tmp/livegrade/espn), BOOT (default 200)
"""
import glob
import json
import math
import os
import random
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_totals_width_fit as wf  # noqa: E402  (sets the ESPN cache from ESPN_CACHE; MARKET stays totals there)

g = wf.g
SPORTS = (os.environ.get("SPORTS") or "nba,ncaab,ncaaf,wncaab").split(",")
UNTIL = os.environ.get("UNTIL") or "2026-11-12"
BOOT = int(os.environ.get("BOOT") or 200)
CLIP = 1e-3


def ts(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def logit(p):
    p = min(max(p, CLIP), 1 - CLIP)
    return math.log(p / (1 - p))


def load(sport):
    states = {}
    for f in sorted(glob.glob(f"{g.DATA}/{sport}_source/data/live_gameline_ledger/live_gameline_ledger_*.jsonl")):
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("market") != "h2h" or r.get("segment") != "full":
                continue
            d = str(r.get("date") or "")
            if not d or d > UNTIL:
                continue
            if r.get("model_home_win_prob") is None or r.get("market_fair_prob") is None:
                continue
            states.setdefault((r.get("event_id"), r.get("live_state_as_of") or r.get("recorded_at")), r)
    idx = {}
    for ds in sorted({r["date"] for r in states.values()}):
        d0 = date.fromisoformat(ds)
        i = {}
        for d in (d0, d0 + timedelta(days=1)):
            i.update(wf.finals_margin(sport, d))
        idx[ds] = i
    fin, rows, drop = {}, [], defaultdict(int)
    for (eid, _as_of), r in states.items():
        if eid not in fin:
            h = g.match(idx[r["date"]], r.get("home_team"), r.get("away_team"))
            if not h:
                fin[eid] = None
            else:
                e = idx[r["date"]][h]
                fin[eid] = (e[2][0] + e[2][1], wf.ledger_home_margin(r, e))
        if fin[eid] is None:
            drop["unmatched"] += 1
            continue
        total, M = fin[eid]
        if M is None:
            drop["orientation_ambiguous"] += 1
            continue
        if M == 0:
            drop["tie"] += 1
            continue
        try:
            hs, as_ = float(r.get("home_score")), float(r.get("away_score"))
        except (TypeError, ValueError):
            hs = as_ = None
        if hs is not None and hs + as_ > total:
            drop["score_gt_final"] += 1
            continue
        mt = r.get("model_total_mean")
        rec, st_, qu = ts(r.get("recorded_at")), ts(r.get("live_state_as_of")), ts(r.get("quote_updated_at"))
        rows.append({
            "g": eid, "date": r["date"], "y": 1.0 if M > 0 else 0.0,
            "pm": float(r["model_home_win_prob"]), "pf": float(r["market_fair_prob"]),
            "pre": r.get("pregame_home_win_prob"),
            "lead": (hs - as_) if hs is not None else None,
            "prog": ((hs + as_) / float(mt)) if (hs is not None and mt) else None,
            "state_age": (rec - st_).total_seconds() if (rec and st_) else None,
            "quote_minus_state": (qu - st_).total_seconds() if (qu and st_) else None,
            "quote_age": r.get("quote_age_seconds"),
            "priced": bool(r.get("priceable")),
        })
    return rows, drop, len(states)


def diff(rows):
    """Brier model - market per row, for g.cl_mean."""
    return [(x["g"], (x["pm"] - x["y"]) ** 2 - (x["pf"] - x["y"]) ** 2) for x in rows]


def line(label, rows, width=26):
    if not rows:
        return f"   {label:<{width}} (none)"
    d = g.cl_mean(diff(rows))
    bm = sum((x["pm"] - x["y"]) ** 2 for x in rows) / len(rows)
    bf = sum((x["pf"] - x["y"]) ** 2 for x in rows) / len(rows)
    return (f"   {label:<{width}} {len(rows):>6} {len({x['g'] for x in rows}):>5}  Brier model {bm:.4f}  market {bf:.4f}"
            f"  model-market {g.fmt(d[0], d[1])}")


def fit_logistic(xs, ys, iters=30):
    """Newton-Raphson for y ~ X beta (X carries its own intercept column). Returns beta or None."""
    k = len(xs[0])
    beta = [0.0] * k
    for _ in range(iters):
        grad = [0.0] * k
        hess = [[0.0] * k for _ in range(k)]
        for x, y in zip(xs, ys):
            eta = sum(b * v for b, v in zip(beta, x))
            p = 1.0 / (1.0 + math.exp(-max(min(eta, 30), -30)))
            w = p * (1 - p)
            for i in range(k):
                grad[i] += (y - p) * x[i]
                for j in range(k):
                    hess[i][j] += w * x[i] * x[j]
        step = solve(hess, grad)
        if step is None:
            return None
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return beta


def solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            return None
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for cc in range(c, n + 1):
                    m[r][cc] -= f * m[c][cc]
    return [m[i][n] / m[i][i] for i in range(n)]


def boot_logistic(rows, design, seed=780):
    """Point fit plus a 95% game bootstrap for each coefficient."""
    xs, ys = [design(x) for x in rows], [x["y"] for x in rows]
    point = fit_logistic(xs, ys)
    by_game = defaultdict(list)
    for x in rows:
        by_game[x["g"]].append(x)
    games = list(by_game)
    rnd = random.Random(seed)
    draws = []
    for _ in range(BOOT):
        sample = [x for gg in (rnd.choice(games) for _ in games) for x in by_game[gg]]
        b = fit_logistic([design(x) for x in sample], [x["y"] for x in sample], iters=15)
        if b is not None:
            draws.append(b)
    ci = []
    for i in range(len(point or [])):
        v = sorted(d[i] for d in draws)
        ci.append((v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]) if v else (float("nan"), float("nan")))
    return point, ci


def band(v, cuts):
    if v is None:
        return None
    for lab, lo, hi in cuts:
        if lo <= v < hi:
            return lab
    return None


PROG = (("< 0.15 (tip)", -1e9, 0.15), ("0.15-0.40", 0.15, 0.40), ("0.40-0.75", 0.40, 0.75), (">= 0.75", 0.75, 1e9))
AGE = (("< 30 s", -1e9, 30), ("30-60 s", 30, 60), ("60-120 s", 60, 120), ("120-300 s", 120, 300), (">= 300 s", 300, 1e9))
QVS = (("quote <= state", -1e9, 0.5), ("quote newer 0-30 s", 0.5, 30), ("quote newer 30-120 s", 30, 120),
       ("quote newer >= 120 s", 120, 1e9))
BINS = [(i / 10, (i + 1) / 10) for i in range(10)]


def report(sport):
    rows, drop, n_states = load(sport)
    if not rows:
        print(f"\n## {sport}: no graded h2h states")
        return
    dates = sorted({x["date"] for x in rows})
    print(f"\n## {sport} h2h: ledger dates {dates[0]}..{dates[-1]} ({len(dates)}), states {n_states}, graded {len(rows)} / "
          f"{len({x['g'] for x in rows})} games (priced {sum(x['priced'] for x in rows)}); dropped {dict(drop)}")
    print("   0. REPRODUCTION")
    print(line("all graded states", rows))
    print(line("priced only", [x for x in rows if x["priced"]]))

    print("   H1 BIAS: signed residual y - p (home frame), game-clustered")
    rm = g.cl_mean([(x["g"], x["y"] - x["pm"]) for x in rows])
    rf = g.cl_mean([(x["g"], x["y"] - x["pf"]) for x in rows])
    print(f"     model {g.fmt(rm[0], rm[1])}   market {g.fmt(rf[0], rf[1])}")
    fav = [x for x in rows if abs(x["pm"] - 0.5) > 0.0]
    fm = g.cl_mean([(x["g"], (x["y"] if x["pm"] > 0.5 else 1 - x["y"]) - max(x["pm"], 1 - x["pm"])) for x in fav])
    ff = g.cl_mean([(x["g"], (x["y"] if x["pm"] > 0.5 else 1 - x["y"]) - (x["pf"] if x["pm"] > 0.5 else 1 - x["pf"]))
                    for x in fav])
    print(f"     the MODEL's favourite (by its own p): wins minus model's claim {g.fmt(fm[0], fm[1])};"
          f" wins minus market's price for the same side {g.fmt(ff[0], ff[1])}")
    print("     calibration by model p:  bin     n     mean p_model  mean p_market  hit rate")
    for lo, hi in BINS:
        b = [x for x in rows if lo <= x["pm"] < hi or (hi == 1.0 and x["pm"] == 1.0)]
        if len(b) >= 30:
            print(f"                              {lo:.1f}-{hi:.1f} {len(b):>6}  {sum(x['pm'] for x in b) / len(b):>11.3f}"
                  f"  {sum(x['pf'] for x in b) / len(b):>12.3f}  {sum(x['y'] for x in b) / len(b):>8.3f}")
    for name, key in (("model", "pm"), ("market", "pf")):
        pt, ci = boot_logistic(rows, lambda x, key=key: (1.0, logit(x[key])))
        if pt:
            print(f"     logistic calibration, {name:<6}: intercept {pt[0]:+.3f} [{ci[0][0]:+.3f}, {ci[0][1]:+.3f}]"
                  f"  slope {pt[1]:.3f} [{ci[1][0]:.3f}, {ci[1][1]:.3f}]   (1 / 0 = calibrated)")

    print("   H2 STAGE: model - market Brier by progress (points scored / model total mean)")
    for lab, lo, hi in PROG:
        print(line(lab, [x for x in rows if band(x["prog"], PROG) == lab]))

    print("   H3 STALENESS: by state age (recorded_at - live_state_as_of)")
    for lab, _lo, _hi in AGE:
        print(line(lab, [x for x in rows if band(x["state_age"], AGE) == lab]))
    print("   H3 STALENESS: by quote time minus the model's state time")
    for lab, _lo, _hi in QVS:
        print(line(lab, [x for x in rows if band(x["quote_minus_state"], QVS) == lab]))

    print("   H4 INFORMATION: logistic y ~ a + b1 logit(p_model) + b2 logit(p_market), game bootstrap 95%")
    pt, ci = boot_logistic(rows, lambda x: (1.0, logit(x["pm"]), logit(x["pf"])))
    if pt:
        print(f"     a {pt[0]:+.3f} [{ci[0][0]:+.3f}, {ci[0][1]:+.3f}]   b1 model {pt[1]:.3f} [{ci[1][0]:.3f}, {ci[1][1]:.3f}]"
              f"   b2 market {pt[2]:.3f} [{ci[2][0]:.3f}, {ci[2][1]:.3f}]   ({len(rows)} states, BOOT={BOOT})")

    print("   DESCRIPTIVE: by the home lead at the state (model - market mean p, then each one's residual)")
    LEAD = (("home <= -10", -1e9, -9.5), ("home -9..-4", -9.5, -3.5), ("-3..+3", -3.5, 3.5), ("home +4..+9", 3.5, 9.5),
            ("home >= +10", 9.5, 1e9))
    for lab, _lo, _hi in LEAD:
        b = [x for x in rows if band(x["lead"], LEAD) == lab]
        if not b:
            continue
        gap = g.cl_mean([(x["g"], x["pm"] - x["pf"]) for x in b])
        print(line(lab, b) + f"   mean p_model - p_market {g.fmt(gap[0], gap[1])}")
    big = [x for x in rows if abs(x["pm"] - x["pf"]) >= 0.10]
    if big:
        side = g.cl_mean([(x["g"], (x["y"] if x["pm"] > x["pf"] else 1 - x["y"])) for x in big])
        # The side the model prefers over the market: home when p_model > p_market. Each one's claim for THAT side.
        claim_m = sum((x["pm"] if x["pm"] > x["pf"] else 1 - x["pm"]) for x in big) / len(big)
        claim_f = sum((x["pf"] if x["pm"] > x["pf"] else 1 - x["pf"]) for x in big) / len(big)
        print(f"   DISAGREEMENT |p_model - p_market| >= 0.10: {len(big)} states / {len({x['g'] for x in big})} games;"
              f" the side the model prefers wins {g.fmt(side[0], side[1])} (model said {claim_m:.3f}, market {claim_f:.3f})")
        print(line("  those states", big))
        for lab, _lo, _hi in PROG:
            print(line(f"  of which {lab}", [x for x in big if band(x["prog"], PROG) == lab]))
    tip = [x for x in rows if band(x["prog"], PROG) == PROG[0][0] and x["pre"] is not None]
    if tip:
        bp = g.cl_mean([(x["g"], (float(x["pre"]) - x["y"]) ** 2 - (x["pf"] - x["y"]) ** 2) for x in tip])
        lag = g.cl_mean([(x["g"], abs(x["pm"] - float(x["pre"]))) for x in tip])
        print(f"   THE PRIOR AT TIP (progress < 0.15, {len(tip)} states with a pregame number):"
              f" pregame-model minus market Brier {g.fmt(bp[0], bp[1])};"
              f" |live model - its pregame number| {g.fmt(lag[0], lag[1])}")


if __name__ == "__main__":
    for sp in SPORTS:
        report(sp)
