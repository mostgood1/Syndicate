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


def margin_band(margin: float | None) -> str:
    """Projected margin from the batter's own team's view, coarsely banded.

    Three bands, not more: each must carry enough TRAIN rows to fit a ratio
    that is not noise. `unknown` is its own band and falls back to the flat
    scalar -- absent must never silently join a band it did not earn.
    """
    if margin is None:
        return "unknown"
    if margin <= -0.5:
        return "underdog"
    if margin >= 0.5:
        return "favorite"
    return "even"


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
    # Two arms, fitted on the SAME train rows so the comparison is like-for-like:
    #   flat  -- one scalar for every batter
    #   slot  -- one scalar per lineup slot
    # Substitution rate rises monotonically 7.7% (slot 3) -> 16.7% (slot 9)
    # `[measured, 618 games]`, so a flat scalar must be wrong for somebody. This
    # tests whether correcting that actually buys anything on the scoreboard.
    ratios = []
    ratios_by_slot: dict[int, list[float]] = defaultdict(list)
    ratios_by_band: dict[str, list[float]] = defaultdict(list)
    rows_by_date: dict[str, list] = defaultdict(list)
    for date in dates:
        try:
            payload = json.loads((CACHE / f"summary_{date}.json").read_text(
                encoding="utf-8", errors="replace"))
        except Exception:
            continue
        seen = set()
        for game in payload.get("outputs") or []:
            # PROJECTED margin, from the batter's own team's perspective.
            #
            # Score state is a LIVE variable and is unknown when a projection is
            # made, so it cannot be conditioned on directly. What IS known
            # pregame is who is expected to be behind -- and the substitution
            # data says managers pinch-hit 2.7:1 when trailing and make
            # defensive replacements 2.5:1 when leading `[measured, 618 games]`.
            # So the projected margin is the pregame-available proxy for the
            # live signal. Stated because this is a substitution, not the
            # measured quantity itself.
            full = (game or {}).get("full") or {}
            h_m, a_m_runs = full.get("home_runs_mean"), full.get("away_runs_mean")
            home_name = str(game.get("home") or "").strip()
            away_name = str(game.get("away") or "").strip()
            proj_margin = None
            if isinstance(h_m, (int, float)) and isinstance(a_m_runs, (int, float)):
                proj_margin = float(h_m) - float(a_m_runs)
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
                    team = str(r.get("team") or "").strip()
                    own_margin = None
                    if proj_margin is not None and team:
                        if team == home_name:
                            own_margin = proj_margin
                        elif team == away_name:
                            own_margin = -proj_margin
                    band = margin_band(own_margin)
                    rows_by_date[date].append({"name": name, "fam": fam, "k": k,
                                               "row": r, "band": band})
                    if date in train_dates and (date, name) not in seen:
                        a = actuals.get((date, name))
                        ab_a = col(a, "ab") if a else None
                        if ab_a is not None:
                            seen.add((date, name))
                            ratio = ab_a / float(ab_m)
                            ratios.append(ratio)
                            slot = r.get("lineup_order")
                            if isinstance(slot, (int, float)) and 1 <= int(slot) <= 9:
                                ratios_by_slot[int(slot)].append(ratio)
                            ratios_by_band[band].append(ratio)
    if not ratios:
        print("no train ratios")
        return 1
    haircut = statistics.fmean(ratios)
    # A slot with too few TRAIN observations falls back to the flat scalar
    # rather than to a noisy per-slot fit -- an unknown must not get a
    # confident correction of its own.
    MIN_SLOT_N = 25
    slot_haircut = {s: (statistics.fmean(v) if len(v) >= MIN_SLOT_N else haircut)
                    for s, v in ratios_by_slot.items()}
    slot_n = {s: len(v) for s, v in ratios_by_slot.items()}
    band_haircut = {b: (statistics.fmean(v) if len(v) >= MIN_SLOT_N else haircut)
                    for b, v in ratios_by_band.items()}
    band_n = {b: len(v) for b, v in ratios_by_band.items()}

    print("=" * 92)
    print("P1 — OPPORTUNITY HAIRCUT, scored against the market")
    print("=" * 92)
    print(f"\n  dates {len(dates)}   TRAIN {len(train_dates)} ({dates[0]}..{dates[cut-1]})"
          f"   TEST {len(test_dates)} ({dates[cut]}..{dates[-1]})")
    print(f"  FLAT haircut fitted on TRAIN: actual_AB / model_AB = {haircut:.4f} "
          f"({(haircut - 1) * 100:+.1f}% opportunity)")
    print(f"  SLOT haircut (fallback to flat below n={MIN_SLOT_N}):")
    for s in range(1, 10):
        if s in slot_haircut:
            fb = "  <- fallback" if slot_n.get(s, 0) < MIN_SLOT_N else ""
            print(f"    slot {s}: {slot_haircut[s]:.4f} "
                  f"({(slot_haircut[s] - 1) * 100:+5.1f}%)  n={slot_n.get(s, 0):4d}{fb}")
    print()

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
            slot = r.get("lineup_order")
            cut_slot = slot_haircut.get(int(slot), haircut) \
                if isinstance(slot, (int, float)) else haircut
            band = item.get("band", "unknown")
            cut_band = band_haircut.get(band, haircut)
            # slot x band combined, multiplicatively around the flat scalar so
            # the two corrections compose instead of one overwriting the other
            cut_both = haircut * (cut_slot / haircut) * (cut_band / haircut)
            p_base = binom_at_least(ab_m, rate, k)
            p_cut = binom_at_least(ab_m * haircut, rate, k)
            p_slot = binom_at_least(ab_m * cut_slot, rate, k)
            p_band = binom_at_least(ab_m * cut_band, rate, k)
            p_both = binom_at_least(ab_m * cut_both, rate, k)
            prod = None
            for key, val in r.items():
                if isinstance(key, str) and isinstance(val, (int, float)) \
                   and key.startswith("p_") and key.endswith(f"_{k}plus"):
                    prod = float(val)

            scored[fam]["baseline"].append(brier_score(p_base, outcome))
            scored[fam]["haircut"].append(brier_score(p_cut, outcome))
            scored[fam]["slot"].append(brier_score(p_slot, outcome))
            scored[fam]["band"].append(brier_score(p_band, outcome))
            scored[fam]["both"].append(brier_score(p_both, outcome))
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
    print("  MARGIN-BAND haircut fitted on TRAIN (pregame proxy for score state):")
    for b in ("underdog", "even", "favorite", "unknown"):
        if b in band_haircut:
            fb = "  <- fallback" if band_n.get(b, 0) < MIN_SLOT_N else ""
            print(f"    {b:9s}: {band_haircut[b]:.4f} "
                  f"({(band_haircut[b] - 1) * 100:+5.1f}%)  n={band_n.get(b, 0):4d}{fb}")
    print()
    header = (f"  {'family':13s} {'n':>5s} {'flat':>9s} {'slot':>9s} {'band':>9s} "
              f"{'BOTH':>9s} {'market':>8s}   best vs flat")
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
        b_slot = statistics.fmean(cells["slot"])
        b_band = statistics.fmean(cells["band"])
        b_both = statistics.fmean(cells["both"])
        b_mkt = statistics.fmean(cells["market"])
        b_prod = statistics.fmean(cells["production"]) if cells["production"] else None
        best = min(b_slot, b_band, b_both)
        delta = b_cut - best   # positive = conditioning HELPED over flat
        note = f"{delta:+.5f}" + ("  better" if delta > 0 else "  worse")
        if best < b_mkt:
            note += "  ** BEATS MARKET **"
        out_rows.append({"family": fam, "n": len(outs), "base_rate": base_rate,
                         "baseline": b_base, "flat": b_cut, "slot": b_slot,
                         "band": b_band, "both": b_both, "market": b_mkt,
                         "production": b_prod, "best_minus_flat": delta})
        print(f"  {fam:13s} {len(outs):5d} {b_cut:9.5f} {b_slot:9.5f} {b_band:9.5f} "
              f"{b_both:9.5f} {b_mkt:8.5f}   {note}")

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
