"""Replay the NBA live TOTAL ANCHOR on the fleet's recorded ticks and grade it against finals. READ-ONLY.

Todo #834, lane nba-live-resim-total-anchor. The anchor is `syndicate/features/nba/live_resim.py` "total anchor"
(absent switch = off). Template: `scripts/replay_nba_live_margin_anchor.py` (#780).

Substrate: production. `nba_source/data/processed/live_resim_history/<date>.jsonl` holds every published tick's FULL
total histogram with its state (period, clock, score) and `as_of`. Each tick is re-anchored with the module's own
functions (`total_anchor_for` -> the closing consensus total from the quote log and the pregame SmartSim total;
`remaining_regulation_fraction`; `anchor_total_result`), so the replay is the code that would run, not a model of it.

Prints:
  1. COVERAGE: games with an anchor, why the rest had none, and the offset (close - pregame sim total).
  2. LEVEL: final total - the model's total mean, raw vs anchored, by the share of regulation still to play
     (game-clustered 95%).
  3. TOTALS: the ledger's full-game totals states (same game and `live_state_as_of`) re-priced off the raw and the
     anchored histogram with the join's own `price_distribution_market` (k = 1): Brier anchored - raw, model - market;
     then the WALK-FORWARD probit scale k (`live_totals_width_fit.fit_k`, fit on every earlier ledger date, score the
     next) for each, because `live_gameline_join._TOTALS_PROB_SCALE_BY_SPORT["nba"]` (2.16) was fitted on raw totals.

Run on the fleet host (nice 19), with the data root set:
    wsl -d Ubuntu-24.04 -- env SYNDICATE_DATA_ROOT=/home/amyn/syndicate-prod/data nice -n 19 \
        /home/amyn/.venvs/syndicate/bin/python /mnt/c/<repo>/scripts/replay_nba_live_total_anchor.py </dev/null
    env: FROM / UNTIL (ledger + slate dates, default 2026-10-21 / 2026-11-14 -- M2's 11-15..11-22 is held out),
         ESPN_CACHE (default /mnt/c/tmp/livegrade/espn)
"""
import glob
import json
import os
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import live_totals_width_fit as wf  # noqa: E402  (finals + the probit fit helpers)

from syndicate.features.college_basketball.prior_calibration import closing_totals  # noqa: E402
from syndicate.features.nba import live_resim as lr  # noqa: E402
from syndicate.features.shared.live_gameline_join import price_distribution_market  # noqa: E402

g = wf.g
FROM = os.environ.get("FROM") or "2026-10-21"
UNTIL = os.environ.get("UNTIL") or "2026-11-14"
DATA = Path(os.environ.get("SYNDICATE_DATA_ROOT") or os.path.expanduser("~/syndicate-prod/data"))
NBA = DATA / "nba_source"
BANDS = (("tip (> 0.85 left)", 0.85, 1.01), ("early (0.60-0.85)", 0.60, 0.85), ("mid (0.25-0.60)", 0.25, 0.60),
         ("late (< 0.25)", -0.01, 0.25))


def history():
    rows = []
    for f in sorted(glob.glob(str(NBA / "data" / "processed" / "live_resim_history" / "*.jsonl"))):
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("source") != "live_resim" or r.get("carried_forward") or not r.get("total_dist"):
                continue
            d = str(r.get("slate_date") or r.get("date") or "")
            if not (FROM <= d <= UNTIL):
                continue
            r["_d"] = d
            rows.append(r)
    return rows


def finals_total(d):
    """{espn id: (home names, away names, (home, away))} for ESPN dates d and d+1 (late tips)."""
    idx = {}
    for dd in (date.fromisoformat(d), date.fromisoformat(d) + timedelta(days=1)):
        idx.update(wf.finals_margin("nba", dd))
    return idx


def mean_of(dist):
    n = sum(int(c) for c in dist.values())
    return sum(int(t) * int(c) for t, c in dist.items()) / n if n else None


def main():
    hist = history()
    games = {(r["_d"], str(r["event_id"])): (r.get("home_code"), r.get("away_code")) for r in hist}
    closes, anchors, why = {}, {}, Counter()
    for (d, eid), (home, away) in sorted(games.items()):
        if d not in closes:
            try:
                closes[d] = closing_totals("nba", d)
            except Exception as exc:  # noqa: BLE001
                print(f"quotes for {d} unreadable: {type(exc).__name__}")
                closes[d] = {}
        a = lr.total_anchor_for(d, eid, home, away, root=NBA, market=closes[d])
        if isinstance(a, lr.NbaResimRefusal):
            why[a.reason] += 1
        else:
            anchors[(d, eid)] = a
    print(f"1. COVERAGE: {len(anchors)} of {len(games)} NBA games ({len(anchors) / max(1, len(games)):.0%}) have a total "
          f"anchor, {FROM}..{UNTIL}; none: {dict(why)}")
    offs = [a.offset for a in anchors.values()]
    if offs:
        print(f"   offset (close - pregame sim total): mean {sum(offs) / len(offs):+.2f}, mean |.| "
              f"{sum(abs(o) for o in offs) / len(offs):.2f}, books median {sorted(a.books for a in anchors.values())[len(offs) // 2]}")

    fin_idx, finals = {}, {}
    for (d, eid), (home, away) in games.items():
        if d not in fin_idx:
            fin_idx[d] = finals_total(d)
        hn, an = lr.team_name("nba", home), lr.team_name("nba", away)
        hit = g.match(fin_idx[d], hn, an)
        if hit:
            hs, as_ = fin_idx[d][hit][2]
            finals[(d, eid)] = hs + as_

    states = []
    for r in hist:
        key = (r["_d"], str(r["event_id"]))
        F = finals.get(key)
        if key not in anchors or F is None:
            continue
        frac = lr.remaining_regulation_fraction(r.get("period"), r.get("clock_s"))
        anc = lr.anchor_total_result({"total_dist": r["total_dist"], "total_mean": r.get("total")}, anchors[key],
                                     remaining_fraction=frac)
        states.append({"g": key, "eid": key[1], "hn": lr.team_name("nba", r.get("home_code")), "as_of": r.get("as_of"),
                       "frac": frac, "sims": r.get("sims"), "F": F,
                       "raw_dist": r["total_dist"], "anc_dist": anc["total_dist"],
                       "raw_mean": mean_of(r["total_dist"]), "anc_mean": anc["total_mean"]})
    print(f"\n2. LEVEL: {len(states)} ticks / {len({s['g'] for s in states})} games with an anchor and a final; "
          f"final - model total mean, game-clustered")

    def level(label, ss):
        if not ss:
            print(f"   {label:<22} (none)")
            return
        r_ = g.cl_mean([(s["g"], s["F"] - s["raw_mean"]) for s in ss])
        a_ = g.cl_mean([(s["g"], s["F"] - s["anc_mean"]) for s in ss])
        print(f"   {label:<22} {len(ss):>6} {len({s['g'] for s in ss}):>4}  raw {g.fmt(r_[0], r_[1])}  anchored {g.fmt(a_[0], a_[1])}")

    level("all ticks", states)
    for lab, lo, hi in BANDS:
        level(lab, [s for s in states if lo < s["frac"] <= hi])

    # 3. The ledger's totals states at the same game and live_state_as_of. The ledger's `event_id` is the odds feed's,
    # not ESPN's, so the join is (home team name, state instant); a ledger row in the other orientation still prices a
    # total the same way, so both orientations are matched.
    by_state = {}
    for s in states:
        by_state[(s["hn"], s["as_of"])] = s
    tot, seen = [], set()
    for f in sorted(glob.glob(str(NBA / "data" / "live_gameline_ledger" / "live_gameline_ledger_*.jsonl"))):
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("market") != "totals" or r.get("segment") != "full" or r.get("line") is None:
                continue
            if not (FROM <= str(r.get("date") or "") <= UNTIL) or r.get("market_fair_prob") is None:
                continue
            s = by_state.get((str(r.get("home_team") or ""), r.get("live_state_as_of"))) \
                or by_state.get((str(r.get("away_team") or ""), r.get("live_state_as_of")))
            if s is None:
                continue
            ln = float(r["line"])
            k = (s["eid"], s["as_of"], ln)
            if k in seen or s["F"] == ln:
                continue
            seen.add(k)
            out = {}
            for lab, dist in (("raw", s["raw_dist"]), ("anc", s["anc_dist"])):
                v = price_distribution_market(dist=dist, line=ln, side="over", market="totals", market_prob=None,
                                              sims=s["sims"], sport="nba")
                out[lab] = v.get("model_prob")
            if out["raw"] is None or out["anc"] is None:
                continue
            tot.append({"g": s["g"], "date": str(r.get("date")), "y": 1 if s["F"] > ln else 0, "raw": out["raw"],
                        "anc": out["anc"], "pf": float(r["market_fair_prob"]), "frac": s["frac"]})
    print(f"\n3. TOTALS: {len(tot)} ledger totals states / {len({x['g'] for x in tot})} games re-priced (k = 1)")
    if not tot:
        return
    d1 = g.cl_mean([(x["g"], (x["anc"] - x["y"]) ** 2 - (x["raw"] - x["y"]) ** 2) for x in tot])
    dm_r = g.cl_mean([(x["g"], (x["raw"] - x["y"]) ** 2 - (x["pf"] - x["y"]) ** 2) for x in tot])
    dm_a = g.cl_mean([(x["g"], (x["anc"] - x["y"]) ** 2 - (x["pf"] - x["y"]) ** 2) for x in tot])
    print(f"   Brier anchored - raw {g.fmt(d1[0], d1[1])}; model - market raw {g.fmt(dm_r[0], dm_r[1])} -> anchored "
          f"{g.fmt(dm_a[0], dm_a[1])}")
    for lab, lo, hi in BANDS:
        sub = [x for x in tot if lo < x["frac"] <= hi]
        if sub:
            a1 = g.cl_mean([(x["g"], (x["anc"] - x["y"]) ** 2 - (x["raw"] - x["y"]) ** 2) for x in sub])
            print(f"     {lab:<22} {len(sub):>5}: Brier anchored - raw {g.fmt(a1[0], a1[1])}")
    for lab in ("raw", "anc"):
        rows = [{"g": x["g"], "date": x["date"], "y": x["y"], "z": wf.inv_phi(x[lab]), "prog": None} for x in tot]
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
                        for x, x2 in zip(rows, tot)])
        k216 = g.cl_mean([(x["g"], (wf.pk(x["z"], 2.16) - x["y"]) ** 2 - (x2["pf"] - x["y"]) ** 2)
                          for x, x2 in zip(rows, tot)])
        print(f"   {'RAW' if lab == 'raw' else 'ANCHORED':<8} k fitted {k_all:.3f}; walk-forward gain {g.fmt(gg[0], gg[1])}"
              f" over {len(dates) - 2} dates; model(k) - market {g.fmt(km[0], km[1])}; model(2.16) - market "
              f"{g.fmt(k216[0], k216[1])}; last k {' '.join(path[-4:])}")


if __name__ == "__main__":
    main()
