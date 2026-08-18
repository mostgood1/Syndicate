"""RE-PROJECT MLB hitter props with in-sim substitution, and score vs the market.

`#440` P2, the payoff measurement. Everything before this was either a rescaling
of production's published numbers (`mlb_opportunity_haircut.py`) or an
opportunity-only reading (`measure_substitution_effect.py`). Neither can answer
the question that decides whether P2 was worth doing:

    does removing batters in-sim move BRIER AGAINST THE PRICE?

WHY THE HAIRCUT SCRIPT CANNOT ANSWER IT. That script scores PRODUCTION'S
PUBLISHED projections, which an undeployed engine change does not touch. This
one re-simulates from the same archived roster artifacts and takes the
probability from the SIM'S OWN empirical distribution -- no binomial assumption,
no rescaling. `crps`/`Brier` then compare OFF vs ON vs the de-vigged market on
IDENTICAL rows.

The two arms differ in exactly one input: `GameConfig.position_substitutions`.
Same rosters, same seeds, same odds, same outcomes.

Usage:
  py -3 scripts/reproject_mlb_props_with_subs.py --games 40 --sims 120
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor" / "mlb_bettingv2"
for p in (str(REPO_ROOT), str(VENDOR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from syndicate.features.shared.model_scoring import brier_score  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

DATA = REPO_ROOT / "data/mlb_source/source_artifacts/data"
SNAPSHOTS = DATA / "daily_pitcher_props/snapshots"
PK_RE = re.compile(r"_pk(\d+)_")

# odds market -> (sim stat key, batter-log column)
#
# `TB` is NOT a key the sim emits -- `batter_stats` carries
# 1B/2B/3B/HR/H/R/RBI/AB/PA/BB/SO/HBP/SB/CS and total bases is derived. The
# first draft asked for "TB", got nothing, and silently dropped the whole
# family (154 `no_sim_pmf`). Derived keys are resolved by `_stat_value` below.
MARKETS = {
    "batter_hits": ("H", "h"),
    "batter_total_bases": ("__TB__", "tb"),
    "batter_runs_scored": ("R", "r"),
    "batter_rbis": ("RBI", "rbi"),
}


def _stat_value(stats: dict, key: str):
    """Sim stat, resolving derived keys. Returns None when unavailable."""
    if key == "__TB__":
        parts = []
        for field, weight in (("1B", 1), ("2B", 2), ("3B", 3), ("HR", 4)):
            v = stats.get(field)
            if v is None:
                return None
            parts.append(float(v) * weight)
        return sum(parts)
    v = stats.get(key)
    return None if v is None else float(v)


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


def prob_at_least(pmf: Counter, k: int) -> float | None:
    total = sum(pmf.values())
    if total <= 0:
        return None
    return sum(c for v, c in pmf.items() if v >= k) / total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=40)
    parser.add_argument("--sims", type=int, default=120)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    actuals = load_actuals()
    jobs = []
    for snapshot in sorted(SNAPSHOTS.iterdir()):
        date = snapshot.name
        for path in sorted((snapshot / "roster_objs").glob("roster_obj_*.json")):
            if PK_RE.search(path.name):
                jobs.append((date, path))
    jobs = jobs[:args.games]
    if not jobs:
        print("no roster artifacts")
        return 1

    print("=" * 92)
    print("RE-PROJECTION WITH IN-SIM SUBSTITUTION — scored against the market")
    print("=" * 92)
    print(f"\n  games {len(jobs)}   sims/game {args.sims} per arm\n")

    scored = defaultdict(lambda: defaultdict(list))
    counters = Counter()

    for date, path in jobs:
        odds = load_odds(date)
        if not odds:
            counters["dates_no_odds"] += 1
            continue
        try:
            raw = read_game_roster_artifact(path)
            away, home = raw["away"], raw["home"]
        except Exception:
            counters["roster_unreadable"] += 1
            continue

        name_of = {}
        for r in (away, home):
            for b in list(r.lineup.batters) + list(r.lineup.bench or []):
                name_of[int(b.player.mlbam_id)] = str(b.player.full_name or "").strip().lower()

        # two arms, identical seeds
        pmfs = {False: defaultdict(lambda: defaultdict(Counter)),
                True: defaultdict(lambda: defaultdict(Counter))}
        for enabled in (False, True):
            cfg = GameConfig(rng_seed=args.seed, manager_pitching="v2",
                             position_substitutions=enabled)
            for i in range(args.sims):
                try:
                    res = simulate_game(away, home, replace(cfg, rng_seed=args.seed + i))
                except Exception:
                    continue
                for pid, st in res.batter_stats.items():
                    for _, (stat_key, _) in MARKETS.items():
                        val = _stat_value(st, stat_key)
                        if val is None:
                            continue
                        pmfs[enabled][int(pid)][stat_key][int(val)] += 1

        for pid, name in name_of.items():
            actual_row = actuals.get((date, name))
            if actual_row is None:
                counters["no_actual"] += 1
                continue
            for mk, (stat_key, log_col) in MARKETS.items():
                quote = odds.get((name, mk))
                if quote is None:
                    counters["no_market"] += 1
                    continue
                actual = col(actual_row, log_col)
                if actual is None:
                    counters["no_stat"] += 1
                    continue
                line = float(quote["line"])
                k = int(line + 0.5)          # over 0.5 == 1 or more
                fair = devig([quote["over_odds"], quote["under_odds"]])
                if not fair:
                    counters["devig_failed"] += 1
                    continue
                p_off = prob_at_least(pmfs[False][pid][stat_key], k)
                p_on = prob_at_least(pmfs[True][pid][stat_key], k)
                if p_off is None or p_on is None:
                    counters["no_sim_pmf"] += 1
                    continue
                outcome = 1.0 if actual >= k else 0.0
                scored[mk]["subs_off"].append(brier_score(p_off, outcome))
                scored[mk]["subs_on"].append(brier_score(p_on, outcome))
                scored[mk]["market"].append(brier_score(fair[0], outcome))
                scored[mk]["_out"].append(outcome)
                counters["scored"] += 1

    print("JOIN")
    for k_, v in sorted(counters.items()):
        print(f"  {k_:18s} {v}")
    if not counters["scored"]:
        print("\nNOTHING SCORED.")
        return 1

    print("\nRESULTS — Brier, lower is better\n")
    header = (f"  {'market':22s} {'n':>5s} {'base':>6s} {'subs OFF':>9s} {'subs ON':>9s} "
              f"{'market':>8s}   effect")
    print(header)
    print("  " + "-" * (len(header) + 4))
    rows = []
    for mk, cells in sorted(scored.items()):
        outs = cells["_out"]
        base = statistics.fmean(outs)
        if base <= 0.001 or base >= 0.999:
            print(f"  {mk:22s} REFUSED — degenerate base rate {base:.3f}")
            continue
        b_off = statistics.fmean(cells["subs_off"])
        b_on = statistics.fmean(cells["subs_on"])
        b_mkt = statistics.fmean(cells["market"])
        moved = b_off - b_on
        note = (f"{moved:+.5f}" + ("  better" if moved > 0 else "  worse"))
        if b_on < b_mkt:
            note += "  ** BEATS MARKET **"
        rows.append({"market": mk, "n": len(outs), "base_rate": base,
                     "subs_off": b_off, "subs_on": b_on, "market": b_mkt,
                     "improvement": moved})
        print(f"  {mk:22s} {len(outs):5d} {base:6.3f} {b_off:9.5f} {b_on:9.5f} "
              f"{b_mkt:8.5f}   {note}")

    print("\n  Both arms are the SIM'S OWN empirical distribution over the same seeds;")
    print("  they differ in exactly one input, `position_substitutions`. No binomial")
    print("  assumption and no rescaling of production's published numbers.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"counters": dict(counters), "rows": rows},
                                        indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
