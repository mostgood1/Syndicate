"""P1: does correcting the OPPORTUNITY bias close the gap to the market?

`#440` Phase 7. The engine over-projects plate appearances by ~15-20%
`[measured 2026-08-17: ab_mean +14.6%, pa_mean +19.7%, n=2,495]` because it has
**no position-player substitution model at all** -- `simulate.py`'s only
reference to `bench` builds a lookup cache. The nine listed starters bat all
game, every game.

This tests the CHEAP version of the fix before anyone builds in-sim
substitution: scale opportunity by a fitted removal factor and see whether the
Brier gap to the market (0.0015-0.010) closes.

WHY PROBABILITIES ARE RECOMPUTED RATHER THAN RESCALED. Production's
`p_h_1plus` was derived FROM the inflated opportunity, so there is no way to
apply a haircut to it directly. Instead both arms are recomputed under one
stated model -- binomial over AB with a per-AB rate taken from the engine's own
`h_mean / ab_mean` -- so BASELINE and HAIRCUT differ in exactly one thing: the
opportunity. Production's own number is printed alongside as a REFERENCE, not as
a competitor, because it carries a different distributional assumption than
mine and comparing them would confound two changes at once.

HOLD-OUT: the haircut factor is fitted on the first half of dates and applied to
the second. `plan_2026-08-14_models.md` D4 exists because an earlier MLB de-bias
was fitted and scored on the same window.

Usage:
  py -3 scripts/mlb_opportunity_haircut.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.model_scoring import brier_score  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

CACHE = Path("C:/tmp/mlb_prop_market_cache")
DATA = REPO_ROOT / "data/mlb_source/source_artifacts/data"
SNAPSHOTS = DATA / "daily_pitcher_props/snapshots"

# family -> (odds market, batter-log column, engine mean field)
FAMILIES = {
    "hits": ("batter_hits", "h", "h_mean"),
    "total_bases": ("batter_total_bases", "tb", "tb_mean"),
    "runs": ("batter_runs_scored", "r", "r_mean"),
}
BUCKET_RE = re.compile(r"^(?P<fam>[a-z_]+?)_(?P<k>\d+)plus$")


def binom_at_least(n_trials: float, p: float, k: int) -> float:
    """P(X >= k) for X ~ Binomial(round(n), p). Exact, no Normal approximation.

    AB is fractional in the projection, so it is rounded to the nearest whole
    trial count -- stated because rounding is a modelling choice, not a detail.
    """
    n = max(0, int(round(n_trials)))
    p = min(max(p, 0.0), 1.0)
    if k <= 0:
        return 1.0
    if n < k:
        return 0.0
    below = 0.0
    for i in range(0, k):
        below += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return max(0.0, min(1.0, 1.0 - below))


def load_actuals() -> dict:
    out = {}
    path = DATA / "processed/mlb_batter_game_log.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            name = str(row.get("player_name") or "").strip().lower()
            date = str(row.get("date") or "")[:10]
            if name and date:
                out[(date, name)] = row
    return out


def load_odds(date: str) -> dict:
    path = SNAPSHOTS / date / f"oddsapi_hitter_props_{date.replace('-', '_')}.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for name, markets in (payload.get("hitter_props") or {}).items():
        for mk, entry in (markets or {}).items():
            if isinstance(entry, dict) and entry.get("line") is not None \
               and entry.get("over_odds") and entry.get("under_odds"):
                out[(str(name).strip().lower(), mk)] = entry
    return out


def col(row: dict, key: str):
    if key not in row:
        return None
    raw = row.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    actuals = load_actuals()
    dates = sorted(p.stem.replace("summary_", "") for p in CACHE.glob("summary_*.json"))
    if len(dates) < 4:
        print(f"need >=4 cached dates, have {len(dates)}")
        return 1
    cut = len(dates) // 2
    train_dates, test_dates = set(dates[:cut]), set(dates[cut:])

    # ---- pass 1: fit the haircut on TRAIN ----
    ratios = []
    rows_by_date: dict[str, list] = defaultdict(list)
    for date in dates:
        try:
            payload = json.loads((CACHE / f"summary_{date}.json").read_text(
                encoding="utf-8", errors="replace"))
        except Exception:
            continue
        seen = set()
        for game in payload.get("outputs") or []:
            for bucket, entries in ((game or {}).get("hitter_props_likelihood_topn") or {}).items():
                m = BUCKET_RE.match(str(bucket))
                if not m or not isinstance(entries, list):
                    continue
                fam, k = m.group("fam"), int(m.group("k"))
                if fam not in FAMILIES:
                    continue
                for r in entries:
                    if not isinstance(r, dict) or not r.get("is_lineup_batter"):
                        continue
                    name = str(r.get("name") or "").strip().lower()
                    ab_m = r.get("ab_mean")
                    if not name or not isinstance(ab_m, (int, float)) or ab_m <= 0:
                        continue
                    rows_by_date[date].append({"name": name, "fam": fam, "k": k, "row": r})
                    if date in train_dates and (date, name) not in seen:
                        a = actuals.get((date, name))
                        ab_a = col(a, "ab") if a else None
                        if ab_a is not None:
                            seen.add((date, name))
                            ratios.append(ab_a / float(ab_m))
    if not ratios:
        print("no train ratios")
        return 1
    haircut = statistics.fmean(ratios)

    print("=" * 92)
    print("P1 — OPPORTUNITY HAIRCUT, scored against the market")
    print("=" * 92)
    print(f"\n  dates {len(dates)}   TRAIN {len(train_dates)} ({dates[0]}..{dates[cut-1]})"
          f"   TEST {len(test_dates)} ({dates[cut]}..{dates[-1]})")
    print(f"  haircut fitted on TRAIN: actual_AB / model_AB = {haircut:.4f} "
          f"({(haircut - 1) * 100:+.1f}% opportunity)\n")

    # ---- pass 2: score TEST ----
    scored = defaultdict(lambda: defaultdict(list))
    counters = Counter()
    for date in sorted(test_dates):
        odds = load_odds(date)
        if not odds:
            counters["dates_no_odds"] += 1
            continue
        for item in rows_by_date.get(date, []):
            fam, k, r = item["fam"], item["k"], item["row"]
            mk, stat_col, mean_field = FAMILIES[fam]
            quote = odds.get((item["name"], mk))
            if quote is None:
                counters["no_market"] += 1
                continue
            if abs(float(quote["line"]) - (k - 0.5)) > 1e-6:
                counters["line_mismatch"] += 1
                continue
            a = actuals.get((date, item["name"]))
            actual = col(a, stat_col) if a else None
            if actual is None:
                counters["no_actual"] += 1
                continue
            ab_m = float(r.get("ab_mean") or 0)
            mean_v = r.get(mean_field)
            if ab_m <= 0 or not isinstance(mean_v, (int, float)):
                counters["no_engine_mean"] += 1
                continue
            rate = float(mean_v) / ab_m            # per-AB rate, engine's own
            fair = devig([quote["over_odds"], quote["under_odds"]])
            if not fair:
                counters["devig_failed"] += 1
                continue

            outcome = 1.0 if actual >= k else 0.0
            p_base = binom_at_least(ab_m, rate, k)
            p_cut = binom_at_least(ab_m * haircut, rate, k)
            prod = None
            for key, val in r.items():
                if isinstance(key, str) and isinstance(val, (int, float)) \
                   and key.startswith("p_") and key.endswith(f"_{k}plus"):
                    prod = float(val)

            scored[fam]["baseline"].append(brier_score(p_base, outcome))
            scored[fam]["haircut"].append(brier_score(p_cut, outcome))
            scored[fam]["market"].append(brier_score(fair[0], outcome))
            if prod is not None:
                scored[fam]["production"].append(brier_score(prod, outcome))
            scored[fam]["_out"].append(outcome)
            counters["scored"] += 1

    print("JOIN")
    for k_, v in sorted(counters.items()):
        print(f"  {k_:16s} {v}")
    if not counters["scored"]:
        print("\nNOTHING SCORED.")
        return 1

    print("\nRESULTS on HELD-OUT dates — Brier, lower is better\n")
    header = (f"  {'family':13s} {'n':>5s} {'base':>6s} {'baseline':>9s} {'HAIRCUT':>9s} "
              f"{'market':>8s} {'(prod)':>8s}   gap closed?")
    print(header)
    print("  " + "-" * (len(header) + 4))
    out_rows = []
    for fam, cells in sorted(scored.items()):
        outs = cells["_out"]
        base_rate = statistics.fmean(outs)
        if base_rate <= 0.001 or base_rate >= 0.999:
            print(f"  {fam:13s} REFUSED — degenerate base rate {base_rate:.3f}")
            continue
        b_base = statistics.fmean(cells["baseline"])
        b_cut = statistics.fmean(cells["haircut"])
        b_mkt = statistics.fmean(cells["market"])
        b_prod = statistics.fmean(cells["production"]) if cells["production"] else None
        gap_before, gap_after = b_base - b_mkt, b_cut - b_mkt
        moved = gap_before - gap_after
        verdict = (f"closed {moved:+.5f}" if moved > 0 else f"WIDENED {moved:+.5f}")
        if b_cut < b_mkt:
            verdict += "  ** BEATS MARKET **"
        out_rows.append({"family": fam, "n": len(outs), "base_rate": base_rate,
                         "baseline": b_base, "haircut": b_cut, "market": b_mkt,
                         "production": b_prod, "gap_before": gap_before,
                         "gap_after": gap_after})
        print(f"  {fam:13s} {len(outs):5d} {base_rate:6.3f} {b_base:9.5f} {b_cut:9.5f} "
              f"{b_mkt:8.5f} {(f'{b_prod:.5f}' if b_prod is not None else '—'):>8s}   {verdict}")

    print("\n  `baseline` and `HAIRCUT` differ in ONE thing: the opportunity. Both are")
    print("  recomputed binomially from the engine's own per-AB rate, so the comparison")
    print("  is like-for-like. `(prod)` is production's published number, shown as a")
    print("  REFERENCE — it carries a different distributional assumption and is not the")
    print("  control for this experiment.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"haircut": haircut, "rows": out_rows,
                                         "counters": dict(counters)}, indent=2),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
