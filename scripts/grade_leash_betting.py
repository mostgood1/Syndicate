"""Grade the F5-leash sweep on BETTING HIT RATE, not just statistical bias.

`#440` Phase 7 follow-up. This is the gate `scripts/sweep_starter_leash.py`
deliberately does not attempt, and the reason it matters is recorded in
`manager_pitching_overrides/forward_start_2026_04_14_v1.json`:
`starter_tto_quality_scaling` was promoted on a clean, consistently-signed
STATISTICAL improvement and reverted the same session because it made the
strikeout betting hit rate WORSE (55.78% -> 54.65%). Statistical accuracy and
money are different questions and this repo has already paid to learn it.

METHOD. For each start that has an archived market line, at each grid value:

  model P(over)  = simulated mass strictly above the line, with PUSH MASS
                   EXCLUDED FROM BOTH SIDES rather than split -- the same rule
                   `prop_projections._dist_prob_over` states and for the same
                   reason.
  market P(over) = de-vigged from the two quoted prices.
  pick           = the side the model thinks the market has mispriced.
  outcome        = actual outs vs the line; exact equality is a PUSH and is
                   excluded from the hit rate and counted.

Reported as hit rate AND as ROI at the actually-quoted odds, because a hit rate
alone is not a P&L: picks land on both -180 favourites and +140 underdogs and
those do not pay the same.

TWO METHODOLOGICAL NOTES, both stated rather than buried.

1. **This is NOT `betting_accuracy.py`.** That harness is referenced by the
   overrides file but is ABSENT from this checkout, so its 55.78%/54.65%
   figures were produced by an instrument this script is not. **Do not compare
   these numbers to those.** Compare grid points to each other, within this run.
2. **The market join is by PITCHER NAME**, because that is the key the odds
   artifact uses (`pitcher_props["zack wheeler"]`). Name joins are the `#218`
   failure mode, so unmatched pitchers are COUNTED AND REPORTED, never dropped
   quietly.

Usage:
  py -3 scripts/grade_leash_betting.py --pmfs reports/phase7/leash_pmfs.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.opportunity_signals import devig, implied_probability  # noqa: E402

MLB_DATA = REPO_ROOT / "data/mlb_source/source_artifacts/data"
PK_RE = re.compile(r"_pk(\d+)_")


def load_actuals() -> dict[tuple[str, str, str], float]:
    path = MLB_DATA / "processed/mlb_pitcher_game_log.csv"
    out: dict[tuple[str, str, str], float] = {}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    out[(row["date"], row["game_pk"], row["player_id"])] = float(row["outs"])
                except (KeyError, TypeError, ValueError):
                    continue
    return out


def load_name_map() -> dict[tuple[str, str], str]:
    """(date, player_id) -> lowercased starter name, from the roster artifacts."""
    out: dict[tuple[str, str], str] = {}
    for family in ("daily_pitcher_props", "daily_hitter_props"):
        base = MLB_DATA / family / "snapshots"
        if not base.exists():
            continue
        for snapshot in sorted(base.iterdir()):
            for path in sorted((snapshot / "roster_objs").glob("roster_obj_*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                for side in ("away", "home"):
                    pitcher = (((payload.get(side) or {}).get("lineup") or {}).get("pitcher") or {})
                    player = pitcher.get("player") or {}
                    pid, name = player.get("mlbam_id"), player.get("full_name")
                    if pid and name:
                        out.setdefault((snapshot.name, str(pid)), str(name).strip().lower())
    return out


def load_lines() -> dict[tuple[str, str], dict[str, Any]]:
    """(date, lowercased pitcher name) -> {line, over_odds, under_odds}."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for family in ("daily_pitcher_props", "daily_hitter_props"):
        base = MLB_DATA / family / "snapshots"
        if not base.exists():
            continue
        for snapshot in sorted(base.iterdir()):
            for path in snapshot.glob("oddsapi_pitcher_props_*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                for name, markets in (payload.get("pitcher_props") or {}).items():
                    entry = (markets or {}).get("outs")
                    if not isinstance(entry, dict):
                        continue
                    line = entry.get("line")
                    over, under = entry.get("over_odds"), entry.get("under_odds")
                    if line is None or over is None or under is None:
                        continue
                    out.setdefault((snapshot.name, str(name).strip().lower()),
                                   {"line": float(line), "over": over, "under": under})
    return out


def model_over_probability(pmf: dict[str, Any], line: float) -> float | None:
    """Mass strictly above the line, push mass excluded from BOTH sides."""
    over = under = 0.0
    for raw_value, raw_count in pmf.items():
        try:
            value, count = float(raw_value), float(raw_count)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        if value > line:
            over += count
        elif value < line:
            under += count
    total = over + under
    return (over / total) if total > 0 else None


def payout(odds: Any, won: bool) -> float | None:
    """Profit per 1 unit staked."""
    try:
        price = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if not won:
        return -1.0
    return price / 100.0 if price > 0 else 100.0 / abs(price)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pmfs", type=Path, default=REPO_ROOT / "reports/phase7/leash_pmfs.json")
    parser.add_argument("--method", choices=("multiplicative", "power", "both"), default="both")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    if not args.pmfs.is_file():
        print(f"missing {args.pmfs} -- run sweep_starter_leash.py --dump-pmfs first")
        return 1
    records = [r for r in json.loads(args.pmfs.read_text(encoding="utf-8")) if "error" not in r]
    actuals, names, lines = load_actuals(), load_name_map(), load_lines()

    counters = {"records": len(records), "no_actual": 0, "no_name": 0,
                "no_line": 0, "no_model_prob": 0, "graded": 0, "push": 0}
    methods = ["multiplicative", "power"] if args.method == "both" else [args.method]

    # grid -> method -> list of (won, profit)
    book: dict[int, dict[str, list[tuple[bool, float]]]] = defaultdict(lambda: defaultdict(list))
    sides: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    matched_starts: set[tuple[str, str, str]] = set()

    for rec in records:
        key = (rec["date"], rec["game_pk"], rec["player_id"])
        actual = actuals.get(key)
        if actual is None:
            counters["no_actual"] += 1
            continue
        name = names.get((rec["date"], rec["player_id"]))
        if not name:
            counters["no_name"] += 1
            continue
        quote = lines.get((rec["date"], name))
        if not quote:
            counters["no_line"] += 1
            continue
        model_p = model_over_probability(rec["pmf"], quote["line"])
        if model_p is None:
            counters["no_model_prob"] += 1
            continue
        if actual == quote["line"]:
            counters["push"] += 1
            continue

        matched_starts.add(key)
        grid = int(rec["grid"])
        over_won = actual > quote["line"]

        for method in methods:
            fair = devig([quote["over"], quote["under"]], method=method)
            if not fair:
                continue
            market_over = fair[0]
            take_over = model_p > market_over
            won = over_won if take_over else (not over_won)
            profit = payout(quote["over"] if take_over else quote["under"], won)
            if profit is None:
                continue
            book[grid][method].append((won, profit))
            sides[grid][("over" if take_over else "under")] += 1
        counters["graded"] += 1

    print("=" * 104)
    print("F5 LEASH -- BETTING GRADE ON PITCHER OUTS")
    print("=" * 104)
    print("\nJOIN (name-keyed market join; unmatched are counted, not dropped)")
    for key, value in counters.items():
        print(f"  {key:16s} {value}")
    print(f"  distinct graded starts {len(matched_starts)}")
    if not counters["graded"]:
        print("\nNOTHING GRADED.")
        return 1

    print("\nRESULTS  (pick = the side the model thinks is mispriced; push excluded)")
    header = f"  {'leash':>6s} {'method':>15s} {'bets':>6s} {'hit rate':>9s} {'ROI/unit':>9s} {'over':>6s} {'under':>6s}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    rows = []
    for grid in sorted(book):
        for method in methods:
            entries = book[grid][method]
            if not entries:
                continue
            wins = sum(1 for won, _ in entries if won)
            roi = sum(profit for _, profit in entries) / len(entries)
            rate = wins / len(entries)
            rows.append({"leash": grid, "method": method, "bets": len(entries),
                         "hit_rate": rate, "roi": roi})
            mark = "  <- current" if grid == 5 else ""
            print(f"  {grid:6d} {method:>15s} {len(entries):6d} {rate:8.2%} "
                  f"{roi:+8.2%} {sides[grid]['over']//len(methods):6d} "
                  f"{sides[grid]['under']//len(methods):6d}{mark}")

    print("\n  NOT comparable to the overrides file's 55.78%/54.65%: that came from")
    print("  betting_accuracy.py, which is ABSENT from this checkout. Compare grid")
    print("  points to each other within this run only.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"counters": counters, "rows": rows}, indent=2),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
