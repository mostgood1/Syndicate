"""Does the opportunity bias show up in GAME TOTALS too? `#440` Phase 7 / P1.

THE ARITHMETIC PREDICTION. The engine over-projects plate appearances by ~12-15%
`[measured: ab_mean +14.6%, and a fitted haircut of 0.8837]` because it models no
position-player substitution. ~+0.5 AB x 9 batters = ~4.5 phantom PA per team per
game; at roughly 0.12 runs/PA that is **~+0.5 runs per team, ~+1.0 on the total**.

If game totals run high by about that much, it is a second INDEPENDENT
confirmation of the same root cause -- one that does not depend on any prop
market, any odds file, or any name join.

Unlike hitter props (mean-only), game lines publish real DISTRIBUTIONS
(`total_runs_dist`, `run_margin_dist`), so this also scores them properly:
CRPS against climatology, the same instrument used everywhere else this session.

Actuals come from `feed_live` finals, keyed by `game_pk` -- an exact id join with
none of `#218`'s name-matching risk.

Usage:
  py -3 scripts/mlb_totals_bias_check.py
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.model_scoring import crps_empirical  # noqa: E402

CACHE = Path("C:/tmp/mlb_prop_market_cache")
FEED = REPO_ROOT / "data/mlb_source/source_artifacts/data/raw/statsapi/feed_live"


def finals_by_game_pk() -> dict[str, tuple[int, int]]:
    """game_pk -> (away_runs, home_runs) from the linescore."""
    out: dict[str, tuple[int, int]] = {}
    for path in FEED.rglob("*.json.gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            continue
        live = payload.get("liveData") or {}
        teams = ((live.get("linescore") or {}).get("teams") or {})
        away = (teams.get("away") or {}).get("runs")
        home = (teams.get("home") or {}).get("runs")
        # only completed games -- an in-progress linescore is not an outcome
        state = (((payload.get("gameData") or {}).get("status") or {})
                 .get("abstractGameState") or "")
        if away is None or home is None or state != "Final":
            continue
        out[path.stem.replace(".json", "")] = (int(away), int(home))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    finals = finals_by_game_pk()
    print("=" * 88)
    print("MLB GAME TOTALS — is the opportunity bias visible here too?")
    print("=" * 88)
    print(f"\n  completed games with a final: {len(finals)}\n")

    pred_tot, act_tot, pred_mar, act_mar = [], [], [], []
    dists: list[tuple[float, dict]] = []
    counters = Counter()

    for path in sorted(CACHE.glob("summary_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for game in payload.get("outputs") or []:
            pk = str(game.get("game_pk") or "").strip()
            full = (game or {}).get("full") or {}
            a_m, h_m = full.get("away_runs_mean"), full.get("home_runs_mean")
            final = finals.get(pk)
            if final is None:
                counters["no_final"] += 1
                continue
            if not isinstance(a_m, (int, float)) or not isinstance(h_m, (int, float)):
                counters["no_projection"] += 1
                continue
            counters["joined"] += 1
            a_a, h_a = final
            pred_tot.append(float(a_m) + float(h_m))
            act_tot.append(a_a + h_a)
            pred_mar.append(float(h_m) - float(a_m))
            act_mar.append(h_a - a_a)
            dist = full.get("total_runs_dist")
            if isinstance(dist, dict) and dist:
                dists.append((float(a_a + h_a), dist))

    for k, v in sorted(counters.items()):
        print(f"  {k:16s} {v}")
    if not pred_tot:
        print("\nNOTHING JOINED.")
        return 1

    mp, ma = statistics.fmean(pred_tot), statistics.fmean(act_tot)
    print(f"\nTOTAL RUNS   n={len(pred_tot)}")
    print(f"  model  {mp:6.3f}")
    print(f"  actual {ma:6.3f}")
    print(f"  BIAS   {mp - ma:+6.3f} runs on the total  ({(mp - ma) / ma:+.1%})")
    print(f"         = {(mp - ma) / 2:+.3f} runs per team")

    mpm, mam = statistics.fmean(pred_mar), statistics.fmean(act_mar)
    print(f"\nRUN MARGIN (home - away)   n={len(pred_mar)}")
    print(f"  model {mpm:+6.3f}   actual {mam:+6.3f}   bias {mpm - mam:+6.3f}")
    print("  (margin should be LESS affected: inflating both offenses roughly")
    print("   cancels in the difference but adds in the sum)")

    print("\nPREDICTION FROM THE PROP-SIDE MEASUREMENT")
    print("  ~+0.5 AB x 9 batters = ~4.5 phantom PA/team; at ~0.12 runs/PA")
    print("  that is ~+0.5 runs/team and ~+1.0 on the total.")
    per_team = (mp - ma) / 2
    if 0.25 <= per_team <= 0.85:
        print(f"  MEASURED {per_team:+.3f} runs/team -> CONSISTENT with that mechanism.")
    elif per_team > 0:
        print(f"  MEASURED {per_team:+.3f} runs/team -> same SIGN, different size.")
    else:
        print(f"  MEASURED {per_team:+.3f} runs/team -> DOES NOT match; totals are not high.")

    if dists:
        actuals = [a for a, _ in dists]
        clim_pmf = {str(v): c for v, c in Counter(actuals).items()}
        clim = statistics.fmean(
            s for s in (crps_empirical(a, clim_pmf) for a in actuals) if s is not None)
        model = statistics.fmean(
            s for s in (crps_empirical(a, d) for a, d in dists) if s is not None)
        print(f"\nDISTRIBUTIONAL SCORE on total_runs_dist   n={len(dists)}")
        print(f"  CRPS model {model:.4f}   CRPS climatology {clim:.4f}   "
              f"skill {1 - model / clim:+.2%}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "n": len(pred_tot), "model_total": mp, "actual_total": ma,
            "total_bias": mp - ma, "per_team_bias": per_team,
            "model_margin": mpm, "actual_margin": mam,
        }, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
