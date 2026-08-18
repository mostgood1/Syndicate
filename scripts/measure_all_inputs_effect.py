"""Do ALL the newly-wired inputs move Brier against the market?

    Arm "on" applies EVERY applier `build_roster` now runs -- pitch splits,
    batter batted-ball blend, pitcher batted-ball rates -- so this is the local
    equivalent of a real rebuild, scored against the price.

    26 -> 10 unfed fields is PLUMBING. This is the quality question, and the
    session's record says it is a real one: pitch splits alone were +0.001, and
    two mechanisms together INTERFERED (-0.00331, negative in 4 of 4).

`#440` — the payoff measurement for the 2026-08-17 research finding that
pitch-type effectiveness is fully built, actively sampled, and **100% unfed**:

    pitcher.arsenal                 100.0%   (449/449)
    pitcher.pitch_type_whiff_mult     0.0%   (0/449)
    batter.vs_pitch_type              0.0%   (0/450)

The sim consumes those as `.get(pitch_type, 1.0)`, so with empty maps a slider
and a fastball are interchangeable. The cause was a **cache-only** loader whose
`pitcher_pitch_splits` namespace had never been written; the populator is a
manual x64 tool outside the daily pipeline.

WHY THE ARCHIVED ROSTERS CANNOT JUST BE RE-READ. Splits are applied at ROSTER
BUILD time (`build_roster._apply_cached_statcast_pitch_splits`), not at read
time. The archived artifacts were built with an empty cache, so re-reading them
picks up nothing. This calls **the builder's own applier** on the loaded
profiles — the same function a rebuild would run — so arm B is what production
would carry if the cache were populated.

Arms differ in exactly one thing: whether the pitchers carry pitch-type
multipliers. Same rosters, same seeds, same odds, same outcomes.

Usage:
  py -3 scripts/measure_pitch_splits_effect.py --games 45 --sims 120
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

MARKETS = {
    "batter_hits": ("H", "h"),
    "batter_total_bases": ("__TB__", "tb"),
    "batter_runs_scored": ("R", "r"),
    "batter_rbis": ("RBI", "rbi"),
}


def _stat(stats: dict, key: str):
    if key == "__TB__":
        out = 0.0
        for field, w in (("1B", 1), ("2B", 2), ("3B", 3), ("HR", 4)):
            v = stats.get(field)
            if v is None:
                return None
            out += float(v) * w
        return out
    v = stats.get(key)
    return None if v is None else float(v)


def load_actuals() -> dict:
    out = {}
    with (DATA / "processed/mlb_batter_game_log.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            n = str(row.get("player_name") or "").strip().lower()
            d = str(row.get("date") or "")[:10]
            if n and d:
                out[(d, n)] = row
    return out


def load_odds(date: str) -> dict:
    p = SNAPSHOTS / date / f"oddsapi_hitter_props_{date.replace('-', '_')}.json"
    if not p.is_file():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for name, markets in (payload.get("hitter_props") or {}).items():
        for mk, e in (markets or {}).items():
            if isinstance(e, dict) and e.get("line") is not None and e.get("over_odds") and e.get("under_odds"):
                out[(str(name).strip().lower(), mk)] = e
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


def prob_at_least(pmf: Counter, k: int):
    tot = sum(pmf.values())
    return (sum(c for v, c in pmf.items() if v >= k) / tot) if tot else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=45)
    ap.add_argument("--sims", type=int, default=120)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    from sim_engine.data.build_roster import _apply_cached_statcast_pitch_splits
    from sim_engine.data.batted_ball import (apply_batted_ball_to_batter,
                                             apply_batted_ball_to_pitcher)
    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.data.statcast_pitch_splits import default_statcast_cache
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    cache = default_statcast_cache()
    actuals = load_actuals()

    jobs = []
    for snap in sorted(SNAPSHOTS.iterdir()):
        for path in sorted((snap / "roster_objs").glob("roster_obj_*.json")):
            if PK_RE.search(path.name):
                jobs.append((snap.name, path))
    jobs = jobs[:args.games]

    print("=" * 92)
    print("PITCH-TYPE SPLITS — effect on props, scored against the market")
    print("=" * 92)
    print(f"\n  games {len(jobs)}   sims/game {args.sims} per arm\n")

    scored = defaultdict(lambda: defaultdict(list))
    counters = Counter()
    applied_total = pitchers_total = 0

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

        names = {}
        for r in (away, home):
            for b in list(r.lineup.batters) + list(r.lineup.bench or []):
                names[int(b.player.mlbam_id)] = str(b.player.full_name or "").strip().lower()

        pmfs = {"off": defaultdict(lambda: defaultdict(Counter)),
                "on": defaultdict(lambda: defaultdict(Counter))}

        for arm in ("off", "on"):
            if arm == "on":
                for r_ in (away, home):
                    for b_ in list(r_.lineup.batters) + list(r_.lineup.bench or []):
                        apply_batted_ball_to_batter(b_, season=args.season, weight=0.35)
                    for p_ in [r_.lineup.pitcher] + list(r_.lineup.bullpen or []):
                        apply_batted_ball_to_pitcher(p_, season=args.season)
                # apply the builder's OWN applier -- this is what a rebuilt
                # roster would carry, not a reimplementation
                for r in (away, home):
                    for p in [r.lineup.pitcher] + list(r.lineup.bullpen or []):
                        pitchers_total += 1
                        if _apply_cached_statcast_pitch_splits(
                                p, season=args.season, statcast_cache=cache,
                                statcast_ttl_seconds=None):
                            applied_total += 1
            cfg = GameConfig(rng_seed=args.seed, manager_pitching="v2")
            for i in range(args.sims):
                try:
                    res = simulate_game(away, home, replace(cfg, rng_seed=args.seed + i))
                except Exception:
                    continue
                for pid, st in res.batter_stats.items():
                    for _, (sk, _) in MARKETS.items():
                        v = _stat(st, sk)
                        if v is not None:
                            pmfs[arm][int(pid)][sk][int(v)] += 1

        for pid, name in names.items():
            arow = actuals.get((date, name))
            if arow is None:
                counters["no_actual"] += 1
                continue
            for mk, (sk, lc) in MARKETS.items():
                q = odds.get((name, mk))
                if q is None:
                    counters["no_market"] += 1
                    continue
                actual = col(arow, lc)
                if actual is None:
                    counters["no_stat"] += 1
                    continue
                k = int(float(q["line"]) + 0.5)
                fair = devig([q["over_odds"], q["under_odds"]])
                if not fair:
                    counters["devig_failed"] += 1
                    continue
                p_off = prob_at_least(pmfs["off"][pid][sk], k)
                p_on = prob_at_least(pmfs["on"][pid][sk], k)
                if p_off is None or p_on is None:
                    counters["no_pmf"] += 1
                    continue
                outcome = 1.0 if actual >= k else 0.0
                scored[mk]["splits_off"].append(brier_score(p_off, outcome))
                scored[mk]["splits_on"].append(brier_score(p_on, outcome))
                scored[mk]["market"].append(brier_score(fair[0], outcome))
                scored[mk]["_out"].append(outcome)
                counters["scored"] += 1

    print(f"SPLITS APPLIED to {applied_total}/{pitchers_total} pitcher-slots "
          f"({applied_total / max(1, pitchers_total):.1%})")
    if applied_total == 0:
        print("  REFUSED: the cache produced no splits -- arm 'on' is identical to 'off'\n"
              "  and any comparison below would be meaningless.")
        return 1
    print("\nJOIN")
    for k_, v in sorted(counters.items()):
        print(f"  {k_:16s} {v}")
    if not counters["scored"]:
        print("\nNOTHING SCORED.")
        return 1

    print("\nRESULTS — Brier, lower is better\n")
    hdr = (f"  {'market':22s} {'n':>5s} {'base':>6s} {'splits OFF':>11s} {'splits ON':>10s} "
           f"{'market':>8s}   effect")
    print(hdr)
    print("  " + "-" * (len(hdr) + 4))
    rows = []
    for mk, cells in sorted(scored.items()):
        outs = cells["_out"]
        base = statistics.fmean(outs)
        if base <= 0.001 or base >= 0.999:
            print(f"  {mk:22s} REFUSED — degenerate base rate {base:.3f}")
            continue
        b_off = statistics.fmean(cells["splits_off"])
        b_on = statistics.fmean(cells["splits_on"])
        b_mkt = statistics.fmean(cells["market"])
        moved = b_off - b_on
        note = f"{moved:+.5f}" + ("  better" if moved > 0 else "  worse")
        if b_on < b_mkt:
            note += "  ** BEATS MARKET **"
        rows.append({"market": mk, "n": len(outs), "splits_off": b_off,
                     "splits_on": b_on, "market_brier": b_mkt, "improvement": moved})
        print(f"  {mk:22s} {len(outs):5d} {base:6.3f} {b_off:11.5f} {b_on:10.5f} "
              f"{b_mkt:8.5f}   {note}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"applied": applied_total,
                                         "pitcher_slots": pitchers_total,
                                         "counters": dict(counters), "rows": rows},
                                        indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
