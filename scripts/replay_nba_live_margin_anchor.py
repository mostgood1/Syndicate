"""Replay the NBA live MARGIN ANCHOR on the fleet's recorded ticks and grade it against finals. READ-ONLY.

Todo #780, lane nba-live-margin-anchor (user 2026-11-13 "Build it now"). The anchor is
`syndicate/features/nba/live_resim.py` "margin anchor"; the hypothesis and falsification were committed before this
ran (`64b3e45cc`).

Substrate: production. `nba_source/data/processed/live_resim_history/<date>.jsonl` holds every published tick's FULL
margin histogram with its state (period, clock, score) and `as_of`. Each tick is re-anchored with the module's own
functions (`margin_anchor_for` -> the closing consensus from the quote log and the pregame SmartSim margin;
`remaining_regulation_fraction`; `anchor_result`), so the replay is the code that would run, not a model of it.

Prints:
  1. COVERAGE: games with an anchor, and why the rest had none.
  2. MONEYLINE: raw vs anchored P(home) (Agresti-Coull at the tick's sims, the join's estimator) against the final,
     Brier per state, game-clustered 95%: overall and by the share of regulation still to play; then raw vs anchored
     minus the market on the ledger's h2h states (same event and `live_state_as_of`); and the >= 10 pp disagreement
     count at each game's first state.
  3. SPREADS: the ledger's full-game spreads states re-priced off the anchored histogram (the join's own
     `price_distribution_market`), Brier raw vs anchored, and the walk-forward probit scale k on the anchored numbers
     (the 4.4 re-fit: k 2.02 was fitted on raw margins).

Run on the fleet host (nice 19), with the data root set:
    wsl -d Ubuntu-24.04 -- env SYNDICATE_DATA_ROOT=/home/amyn/syndicate-prod/data nice -n 19 \
        /home/amyn/.venvs/syndicate/bin/python /mnt/c/<repo>/scripts/replay_nba_live_margin_anchor.py </dev/null
    env: FROM / UNTIL (ledger dates, default 2026-10-21 / 2026-11-12), ESPN_CACHE (default /mnt/c/tmp/livegrade/espn)
"""
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import live_totals_width_fit as wf  # noqa: E402  (finals + the probit fit helpers; MARKET stays totals there)

from syndicate.features.nba import live_resim as lr  # noqa: E402
from syndicate.features.ncaab.live_resim import home_spread_quotes  # noqa: E402
from syndicate.features.shared.live_gameline_join import agresti_coull_point, price_distribution_market  # noqa: E402

g = wf.g
FROM = os.environ.get("FROM") or "2026-10-21"
UNTIL = os.environ.get("UNTIL") or "2026-11-12"
DATA = Path(os.environ.get("SYNDICATE_DATA_ROOT") or os.path.expanduser("~/syndicate-prod/data"))
NBA = DATA / "nba_source"
BANDS = (("tip (> 0.85 left)", 0.85, 1.01), ("early (0.60-0.85)", 0.60, 0.85), ("mid (0.25-0.60)", 0.25, 0.60),
         ("late (< 0.25)", -0.01, 0.25))


def p_home(dist, sims):
    """The join's moneyline estimator off a margin histogram: P(m > 0) + half the ties, Agresti-Coull at the sims."""
    n = sum(int(c) for c in dist.values())
    if n <= 0:
        return None
    raw = (sum(int(c) for m, c in dist.items() if int(m) > 0) + 0.5 * sum(int(c) for m, c in dist.items() if int(m) == 0)) / n
    return agresti_coull_point(raw, int(sims or n))


def history():
    rows = []
    for f in sorted(glob.glob(str(NBA / "data" / "processed" / "live_resim_history" / "*.jsonl"))):
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("source") != "live_resim" or r.get("carried_forward") or not r.get("margin_dist"):
                continue
            d = str(r.get("slate_date") or r.get("date") or "")
            if not (FROM <= d <= UNTIL):
                continue
            r["_d"] = d
            rows.append(r)
    return rows


def finals_for(d):
    idx = {}
    for dd in (date.fromisoformat(d), date.fromisoformat(d) + timedelta(days=1)):
        idx.update(wf.finals_margin("nba", dd))
    return idx


def main():
    hist = history()
    games = {(r["_d"], str(r["event_id"])): (r.get("home_code"), r.get("away_code")) for r in hist}
    markets = {}
    anchors, why = {}, Counter()
    for (d, eid), (home, away) in sorted(games.items()):
        if d not in markets:
            try:
                markets[d] = home_spread_quotes("nba", d)
            except Exception as exc:  # noqa: BLE001
                print(f"quotes for {d} unreadable: {type(exc).__name__}")
                markets[d] = {}
        a = lr.margin_anchor_for(d, eid, home, away, root=NBA, market=markets[d])
        if isinstance(a, lr.NbaResimRefusal):
            why[a.reason] += 1
        else:
            anchors[(d, eid)] = a
    print(f"1. COVERAGE: {len(anchors)} of {len(games)} NBA games ({len(anchors) / max(1, len(games)):.0%}) have an anchor, "
          f"{FROM}..{UNTIL}; none: {dict(why)}")
    offs = [a.offset for a in anchors.values()]
    if offs:
        print(f"   offset (close - pregame sim margin): mean {sum(offs) / len(offs):+.2f}, mean |.| "
              f"{sum(abs(o) for o in offs) / len(offs):.2f}, books median {sorted(a.books for a in anchors.values())[len(offs) // 2]}")

    fin_idx, finals = {}, {}
    for (d, eid), (home, away) in games.items():
        if d not in fin_idx:
            fin_idx[d] = finals_for(d)
        hn, an = lr.team_name("nba", home), lr.team_name("nba", away)
        hit = g.match(fin_idx[d], hn, an)
        if hit:
            finals[(d, eid)] = wf.ledger_home_margin({"home_team": hn, "away_team": an}, fin_idx[d][hit])

    states = []
    for r in hist:
        key = (r["_d"], str(r["event_id"]))
        M = finals.get(key)
        if key not in anchors or M is None or M == 0:
            continue
        frac = lr.remaining_regulation_fraction(r.get("period"), r.get("clock_s"))
        res = {"margin_dist": r["margin_dist"], "home_win_prob": r.get("p_home"), "home_margin_mean": r.get("margin")}
        anc = lr.anchor_result(res, anchors[key], remaining_fraction=frac)
        states.append({"g": key, "eid": key[1], "hn": lr.team_name("nba", r.get("home_code")), "as_of": r.get("as_of"),
                       "frac": frac, "sims": r.get("sims"),
                       "y": 1.0 if M > 0 else 0.0, "M": M, "raw_dist": r["margin_dist"], "anc_dist": anc["margin_dist"],
                       "p_raw": p_home(r["margin_dist"], r.get("sims")), "p_anc": p_home(anc["margin_dist"], r.get("sims"))})
    states = [s for s in states if s["p_raw"] is not None and s["p_anc"] is not None]
    print(f"\n2. MONEYLINE: {len(states)} ticks / {len({s['g'] for s in states})} games with an anchor and a final")

    def brier_line(label, ss):
        if not ss:
            print(f"   {label:<22} (none)")
            return
        br = sum((s["p_raw"] - s["y"]) ** 2 for s in ss) / len(ss)
        ba = sum((s["p_anc"] - s["y"]) ** 2 for s in ss) / len(ss)
        dd = g.cl_mean([(s["g"], (s["p_anc"] - s["y"]) ** 2 - (s["p_raw"] - s["y"]) ** 2) for s in ss])
        print(f"   {label:<22} {len(ss):>6} {len({s['g'] for s in ss}):>4}  Brier raw {br:.4f}  anchored {ba:.4f}"
              f"  anchored - raw {g.fmt(dd[0], dd[1])}")

    brier_line("all ticks", states)
    for lab, lo, hi in BANDS:
        brier_line(lab, [s for s in states if lo < s["frac"] <= hi])

    # Against the market: the ledger's h2h states at the same game and live_state_as_of. The ledger's `event_id` is the
    # odds feed's, not ESPN's, so the join is (home team name, state instant); a ledger row oriented the other way does
    # not match and is dropped (its probabilities are in the other home frame).
    by_state = {(s["hn"], s["as_of"]): s for s in states}
    led_h2h, led_sp = [], []
    for f in sorted(glob.glob(str(NBA / "data" / "live_gameline_ledger" / "live_gameline_ledger_*.jsonl"))):
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("segment") != "full" or not (FROM <= str(r.get("date") or "") <= UNTIL):
                continue
            s = by_state.get((str(r.get("home_team") or ""), r.get("live_state_as_of")))
            if s is None or r.get("market_fair_prob") is None:
                continue
            if r.get("market") == "h2h":
                led_h2h.append((s, float(r["market_fair_prob"])))
            elif r.get("market") == "spreads" and r.get("line") is not None:
                led_sp.append((s, r))
    seen = {}
    for s, pf in led_h2h:
        seen.setdefault((s["eid"], s["as_of"]), (s, pf))
    mk = list(seen.values())
    if mk:
        dr = g.cl_mean([(s["g"], (s["p_raw"] - s["y"]) ** 2 - (pf - s["y"]) ** 2) for s, pf in mk])
        da = g.cl_mean([(s["g"], (s["p_anc"] - s["y"]) ** 2 - (pf - s["y"]) ** 2) for s, pf in mk])
        print(f"   vs the MARKET on {len(mk)} ledger h2h states / {len({s['g'] for s, _ in mk})} games: model - market "
              f"raw {g.fmt(dr[0], dr[1])}  ->  anchored {g.fmt(da[0], da[1])}")
        for lab, lo, hi in BANDS:
            sub = [(s, pf) for s, pf in mk if lo < s["frac"] <= hi]
            if sub:
                a1 = g.cl_mean([(s["g"], (s["p_raw"] - s["y"]) ** 2 - (pf - s["y"]) ** 2) for s, pf in sub])
                a2 = g.cl_mean([(s["g"], (s["p_anc"] - s["y"]) ** 2 - (pf - s["y"]) ** 2) for s, pf in sub])
                print(f"     {lab:<22} {len(sub):>5}: raw {g.fmt(a1[0], a1[1])} -> anchored {g.fmt(a2[0], a2[1])}")
        first = {}
        for s, pf in sorted(mk, key=lambda t: str(t[0]["as_of"])):
            first.setdefault(s["g"], (s, pf))
        far_r = sum(abs(s["p_raw"] - pf) >= 0.10 for s, pf in first.values())
        far_a = sum(abs(s["p_anc"] - pf) >= 0.10 for s, pf in first.values())
        print(f"   first ledger state per game, >= 10 pp from the market: raw {far_r}, anchored {far_a} of {len(first)}")

    # 3. SPREADS: the join's own pricer on the anchored histogram, then the walk-forward probit scale.
    sp, seen_sp = [], set()
    for s, r in led_sp:
        key = (s["eid"], s["as_of"], r["line"])
        if key in seen_sp:
            continue
        seen_sp.add(key)
        ln = float(r["line"])
        if s["M"] == ln:
            continue
        out = {}
        for lab, dist in (("raw", s["raw_dist"]), ("anc", s["anc_dist"])):
            v = price_distribution_market(dist=dist, line=ln, side="home", market="spreads", market_prob=None,
                                          sims=s["sims"], sport="nba")
            out[lab] = v.get("model_prob")
        if out["raw"] is None or out["anc"] is None:
            continue
        sp.append({"g": s["g"], "date": s["g"][0], "y": 1 if s["M"] > ln else 0, "raw": out["raw"], "anc": out["anc"],
                   "pf": float(r["market_fair_prob"])})
    print(f"\n3. SPREADS: {len(sp)} ledger spreads states / {len({x['g'] for x in sp})} games re-priced")
    if sp:
        d1 = g.cl_mean([(x["g"], (x["anc"] - x["y"]) ** 2 - (x["raw"] - x["y"]) ** 2) for x in sp])
        dm_r = g.cl_mean([(x["g"], (x["raw"] - x["y"]) ** 2 - (x["pf"] - x["y"]) ** 2) for x in sp])
        dm_a = g.cl_mean([(x["g"], (x["anc"] - x["y"]) ** 2 - (x["pf"] - x["y"]) ** 2) for x in sp])
        print(f"   Brier anchored - raw {g.fmt(d1[0], d1[1])}; model - market raw {g.fmt(dm_r[0], dm_r[1])} -> anchored "
              f"{g.fmt(dm_a[0], dm_a[1])}")
        for lab in ("raw", "anc"):
            rows = [{"g": x["g"], "date": x["date"], "y": x["y"], "z": wf.inv_phi(x[lab]), "prog": None} for x in sp]
            dates = sorted({x["date"] for x in rows})
            k_all = wf.fit_k(rows)
            gain, path = [], []
            for i in range(2, len(dates)):
                train = [x for x in rows if x["date"] < dates[i]]
                test = [x for x in rows if x["date"] == dates[i]]
                k = wf.fit_k(train)
                path.append(f"{dates[i][5:]}:{k:.2f}")
                gain += [(x["g"], (wf.pk(x["z"], k) - x["y"]) ** 2 - (wf.pk(x["z"], 1.0) - x["y"]) ** 2) for x in test]
            gg = g.cl_mean(gain) if gain else (float("nan"), float("nan"), 0, 0)
            km = g.cl_mean([(x["g"], (wf.pk(x["z"], k_all) - x["y"]) ** 2 - (x2["pf"] - x["y"]) ** 2)
                            for x, x2 in zip(rows, sp)])
            print(f"   {'RAW' if lab == 'raw' else 'ANCHORED':<8} k fitted {k_all:.3f}; walk-forward gain {g.fmt(gg[0], gg[1])}"
                  f" over {len(dates) - 2} dates; model(k) - market {g.fmt(km[0], km[1])}; last k {' '.join(path[-4:])}")


if __name__ == "__main__":
    main()
