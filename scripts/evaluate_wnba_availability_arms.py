"""Lane `wnba-availability-recency-tune`. Apply the PRE-REGISTERED decision rule (findings_2026-10-14_wnba_availability_recency_tune.md §3, main 789500a6)
to `fit_wnba_sim_availability.py --compare` outputs. Held-out regular season decides; playoffs are reported only.

  1. minutes MAE not worse:   d_mae CI lower <= 0   (CI wholly > 0 = worse -> fail)
  2. no priced market worse:  no prop market d_brier CI wholly > 0
  3. a real gain:             minutes d_mae CI wholly < 0, OR points / PRA d_brier CI wholly < 0
  If both variants qualify, the larger minutes-MAE gain (more negative point). Else `k` stays.
Usage: python3 evaluate_arms.py <compare_regular_k2_min20.json> <compare_exempt_apps3of5.json>
"""
import json
import sys

GAIN_MARKETS = ("player_points", "player_points_rebounds_assists")


def verdict(rep):
    ph = rep["phases"]["test_regular"]
    m = ph["minutes"]["d_mae_variant_minus_base"]
    lo, hi = m["ci95"]
    c1 = lo <= 0
    worse = [k for k, v in ph["props"].items()
             if isinstance(v, dict) and v.get("d_brier_variant_minus_base") and v["d_brier_variant_minus_base"]["ci95"][0] > 0]
    c2 = not worse
    gains = []
    if hi < 0:
        gains.append("minutes_mae")
    for k in GAIN_MARKETS:
        v = ph["props"].get(k) or {}
        b = v.get("d_brier_variant_minus_base")
        if b and b["ci95"][1] < 0:
            gains.append(f"{k}_brier")
    c3 = bool(gains)
    return {"qualifies": c1 and c2 and c3, "c1_minutes_not_worse": c1, "c2_no_market_worse": c2,
            "worse_markets": worse, "c3_gains": gains, "minutes_d_mae": m, "minutes_n": ph["minutes"]["n"]}


def main():
    out = {}
    for path in sys.argv[1:]:
        rep = json.load(open(path))
        name = path.rsplit("compare_", 1)[-1].replace(".json", "")
        out[name] = verdict(rep)
        print(name, json.dumps(out[name]))
    ok = {k: v for k, v in out.items() if v["qualifies"]}
    if not ok:
        print("DECISION: k stays (no variant meets the pre-registered rule)")
    else:
        best = min(ok, key=lambda k: ok[k]["minutes_d_mae"]["point"])
        print(f"DECISION: recommend {best} (qualifying: {sorted(ok)}) -- production enable is a separate user decision")


if __name__ == "__main__":
    main()
