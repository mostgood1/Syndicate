"""Paired read of a #765 harness run (`scripts/backtest_basketball_intervals.py --projectors pregame_rate,resim,resim_mech`):
resim_mech (here: NCAAB blowout rule off) against resim (production), per game x checkpoint, regular season only.
Lane ncaab-live-totals-bias, 2026-11-08. Findings: .syndicate/findings_2026-11-08_ncaab_live_totals_bias.md
Usage: python3 scripts/ncaab_blowout_harness_read.py <run>/results.jsonl
Reads the projected TOTAL and the projected MARGIN (home - away), each against its actual.
The margin AT the checkpoint is recovered from pregame_rate: margin = so_far + close x share left, so
so_far = pr_margin(cp) - pr_margin(0m) x (1 - frac(cp))."""
import json, sys
from collections import defaultdict
path = sys.argv[1]
rows = defaultdict(dict)
phase, mnow = {}, {}
with open(path) as f:
    for line in f:
        r = json.loads(line)
        g = r["game_id"]
        phase[g] = r.get("phase")
        pr = {c["checkpoint"]: c for c in r.get("cp_rows") or [] if c["projector"] == "pregame_rate" and c["segment"] == "full"}
        if "0m" in pr:
            for cp, c in pr.items():
                mnow[(g, cp)] = c["margin"] - pr["0m"]["margin"] * (1.0 - float(c["frac"]))
        for c in r.get("cp_rows") or []:
            if c.get("projector") in ("resim", "resim_mech", "pregame_rate"):
                rows[(g, c["segment"], c["checkpoint"])][c["projector"]] = {"total": (c["total"], c["actual_total"]),
                                                                         "margin": (c["margin"], c["actual_margin"])}
def ms(v):
    n = len(v); mu = sum(v) / n
    return mu, ((sum((x - mu) ** 2 for x in v) / (n - 1) / n) ** 0.5 if n > 1 else float("nan")), n
splits = {"all": lambda m: True, "|m now|>=15": lambda m: m is not None and abs(m) >= 15, "|m now|<15": lambda m: m is not None and abs(m) < 15}
for stat, seg in (("total", "full"), ("total", "h2"), ("margin", "full")):
    for sname, pred in splits.items():
        print(f"--- {seg} {stat}, regular season, {sname}")
        for cp in ("0m", "10m", "20m", "30m", "38m"):
            d_abs, shift, bp, bo, bl = [], [], [], [], []
            for (g, s, c), p in rows.items():
                if s != seg or c != cp or phase.get(g) != "regular" or "resim" not in p or "resim_mech" not in p:
                    continue
                if not pred(mnow.get((g, cp))):
                    continue
                t0, a = p["resim"][stat]; t1 = p["resim_mech"][stat][0]
                d_abs.append(abs(t1 - a) - abs(t0 - a)); shift.append(t1 - t0); bp.append(t0 - a); bo.append(t1 - a)
                if "pregame_rate" in p:
                    bl.append(p["pregame_rate"][stat][0] - a)
            if len(d_abs) < 3:
                continue
            m1, s1, n = ms(d_abs); m2, s2, _ = ms(shift); p0 = ms(bp); o0 = ms(bo)
            lb = ms(bl)[0] if len(bl) > 2 else float("nan")
            print(f"  {cp:>3s} games={n:3d}  |err| off-prod {m1:+.2f} +- {1.96*s1:.2f} (1.96 SE)  shift {m2:+.2f} +- {s2:.2f}  "
                  f"bias prod {p0[0]:+.2f} +- {p0[1]:.2f}  off {o0[0]:+.2f}  pregame_rate {lb:+.2f}")
