"""Do the wired features INTERACT, or are they independently negligible?

`#440`. Every measurement so far tested one dimension at a time, which is right
for ATTRIBUTION and systematically understates COMPLEMENTARY features. Asked
directly: "are we sure wiring all of these together won't make a combined
difference?" The honest answer was no — so this measures it instead of arguing.

A 2x2 FACTORIAL over the two features that are actually wired:

    A  position substitutions   (`GameConfig.position_substitutions`, `#440` P2)
    B  pitch-type splits        (`_apply_cached_statcast_pitch_splits`, 305 pitchers)

    arm 00  neither      arm 10  subs only
    arm 01  splits only  arm 11  BOTH

**Interaction = (11 - 00) - [(10 - 00) + (01 - 00)]**

Positive interaction means the pair does more than the sum of its parts — the
superadditivity the question is about. Zero means the isolated tests were fair
and the features simply do not help much. Negative means they partly cancel.

All four arms share rosters, seeds, odds and outcomes. Only the two flags move.

Usage:
  py -3 scripts/measure_combined_sim_features.py --games 45 --sims 120
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
ARMS = (("00", False, False), ("10", True, False),
        ("01", False, True), ("11", True, True))


def _stat(st: dict, key: str):
    if key == "__TB__":
        tot = 0.0
        for f, w in (("1B", 1), ("2B", 2), ("3B", 3), ("HR", 4)):
            v = st.get(f)
            if v is None:
                return None
            tot += float(v) * w
        return tot
    v = st.get(key)
    return None if v is None else float(v)


def load_actuals() -> dict:
    out = {}
    with (DATA / "processed/mlb_batter_game_log.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            n = str(r.get("player_name") or "").strip().lower()
            d = str(r.get("date") or "")[:10]
            if n and d:
                out[(d, n)] = r
    return out


def load_odds(date: str) -> dict:
    p = SNAPSHOTS / date / f"oddsapi_hitter_props_{date.replace('-', '_')}.json"
    if not p.is_file():
        return {}
    try:
        pay = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for name, mk in (pay.get("hitter_props") or {}).items():
        for k, e in (mk or {}).items():
            if isinstance(e, dict) and e.get("line") is not None and e.get("over_odds") and e.get("under_odds"):
                out[(str(name).strip().lower(), k)] = e
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


def p_at_least(pmf: Counter, k: int):
    t = sum(pmf.values())
    return (sum(c for v, c in pmf.items() if v >= k) / t) if t else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=45)
    ap.add_argument("--sims", type=int, default=120)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    from sim_engine.data.build_roster import _apply_cached_statcast_pitch_splits
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

    print("=" * 96)
    print("2x2 FACTORIAL — do substitutions and pitch splits INTERACT?")
    print("=" * 96)
    print(f"\n  games {len(jobs)}   sims/game {args.sims} per arm   4 arms\n")

    scored = defaultdict(lambda: defaultdict(list))
    counters = Counter()

    for date, path in jobs:
        odds = load_odds(date)
        if not odds:
            counters["dates_no_odds"] += 1
            continue
        try:
            raw = read_game_roster_artifact(path)
        except Exception:
            counters["roster_unreadable"] += 1
            continue
        away, home = raw["away"], raw["home"]
        names = {}
        for r in (away, home):
            for b in list(r.lineup.batters) + list(r.lineup.bench or []):
                names[int(b.player.mlbam_id)] = str(b.player.full_name or "").strip().lower()

        pmfs = {a: defaultdict(lambda: defaultdict(Counter)) for a, _, _ in ARMS}
        splits_on = False
        for arm, subs, splits in ARMS:
            if splits and not splits_on:
                for r in (away, home):
                    for p in [r.lineup.pitcher] + list(r.lineup.bullpen or []):
                        _apply_cached_statcast_pitch_splits(
                            p, season=args.season, statcast_cache=cache,
                            statcast_ttl_seconds=None)
                splits_on = True
            # NOTE arms are ordered so splits are applied once and stay applied;
            # the 00/10 arms run BEFORE that, so they are genuinely splits-free.
            cfg = GameConfig(rng_seed=args.seed, manager_pitching="v2",
                             position_substitutions=subs)
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
                continue
            for mk, (sk, lc) in MARKETS.items():
                q = odds.get((name, mk))
                if q is None:
                    continue
                actual = col(arow, lc)
                if actual is None:
                    continue
                k = int(float(q["line"]) + 0.5)
                fair = devig([q["over_odds"], q["under_odds"]])
                if not fair:
                    continue
                probs = {a: p_at_least(pmfs[a][pid][sk], k) for a, _, _ in ARMS}
                if any(v is None for v in probs.values()):
                    continue
                outcome = 1.0 if actual >= k else 0.0
                for a in probs:
                    scored[mk][a].append(brier_score(probs[a], outcome))
                scored[mk]["market"].append(brier_score(fair[0], outcome))
                scored[mk]["_out"].append(outcome)
                counters["scored"] += 1

    if not counters["scored"]:
        print("NOTHING SCORED.")
        return 1
    print(f"scored rows: {counters['scored']}\n")
    hdr = (f"  {'market':20s} {'n':>5s} {'00 none':>9s} {'10 subs':>9s} {'01 splt':>9s} "
           f"{'11 BOTH':>9s} {'market':>8s} {'interact':>9s}")
    print(hdr)
    print("  " + "-" * (len(hdr) + 2))
    rows = []
    for mk, c in sorted(scored.items()):
        outs = c["_out"]
        base = statistics.fmean(outs)
        if base <= 0.001 or base >= 0.999:
            continue
        b = {a: statistics.fmean(c[a]) for a, _, _ in ARMS}
        mkt = statistics.fmean(c["market"])
        # improvements are POSITIVE when Brier falls
        d10, d01, d11 = b["00"] - b["10"], b["00"] - b["01"], b["00"] - b["11"]
        inter = d11 - (d10 + d01)
        rows.append({"market": mk, "n": len(outs), **{f"arm_{a}": b[a] for a, _, _ in ARMS},
                     "market_brier": mkt, "gain_subs": d10, "gain_splits": d01,
                     "gain_both": d11, "interaction": inter})
        flag = "  ** BOTH BEATS MARKET **" if b["11"] < mkt else ""
        print(f"  {mk:20s} {len(outs):5d} {b['00']:9.5f} {b['10']:9.5f} {b['01']:9.5f} "
              f"{b['11']:9.5f} {mkt:8.5f} {inter:+9.5f}{flag}")

    print("\n  interaction = (both - none) - [(subs - none) + (splits - none)]")
    print("  POSITIVE => the pair does MORE than the sum of its parts.")
    print("  ~ZERO    => the one-at-a-time tests were fair; no hidden synergy.")
    tot = statistics.fmean([r["interaction"] for r in rows]) if rows else 0.0
    print(f"\n  mean interaction across markets: {tot:+.5f}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
