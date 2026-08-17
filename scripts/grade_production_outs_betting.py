"""Grade PRODUCTION's shipped pitcher-outs model on betting outcomes.

`#440` Phase 7. Companion to `grade_leash_betting.py`, and it exists because
that script's verdict was CONFOUNDED, not because it was wrong:

  on 148 starts, ALWAYS OVER returned 58.78% / +8.16% with no model at all,
  the leash grid varied only how often it bet the over (106 -> 146 of 148),
  and the whole spread was 1.49 SE.

**This does NOT sweep the leash.** It cannot: re-simulating the grid needs the
schema-v4 `roster_obj_*.json`, and production does not have those (404 at every
root; only the raw input bundle exists and the sim's loader rejects it with
schema_version=None). What this DOES is test the confound itself on a larger,
independent window using production's own published `outs_dist` -- if overs win
~59% here too, the confound is systemic and any future grid grade must control
for it; if they do not, the June window was anomalous.

PATH QUIRK, measured 2026-08-17 and worth not rediscovering: the two families
live under DIFFERENT stream roots.
    odds    -> mlb_source/data/daily/snapshots/<date>/...
    rosters -> mlb_source/source_artifacts/data/daily/snapshots/<date>/...

Usage:
  py -3 scripts/grade_production_outs_betting.py
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

BASE = "https://syndicate-an21.onrender.com"
CACHE = Path(tempfile.gettempdir()) / "syndicate_phase7_cache"
ODDS_ROOT = "mlb_source/data/daily/snapshots"
SUMMARY_PREFIX = "mlb_source__source_artifacts__data"


def _token() -> str:
    for line in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found in .env")


def _stream(path: str, token: str) -> bytes | None:
    target = CACHE / path.replace("/", "__")
    if target.is_file():
        return target.read_bytes()
    url = f"{BASE}/api/ops/artifacts/stream?path={urllib.parse.quote(path)}"
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"X-Admin-Token": token}), timeout=180).read()
    except Exception:  # noqa: BLE001
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return raw


def load_actuals() -> tuple[dict[tuple[str, str, str], float], dict[str, str]]:
    """Outcomes AND the id->name map.

    The game log carries `player_id` AND `player_name`, so the name join the
    odds artifact needs (it is keyed by lowercased pitcher name) costs nothing
    extra. `probables.json` 404s at both stream roots, and the plain roster
    files would be ~12 MB of egress for the same identity map.

    This is an identity map only -- no outcome information crosses into the
    forecast side, so using the outcome file for it introduces no leakage.
    """
    raw = (CACHE / f"{SUMMARY_PREFIX}__processed__mlb_pitcher_game_log.csv").read_bytes()
    out: dict[tuple[str, str, str], float] = {}
    names: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace"))):
        try:
            out[(row["date"], row["game_pk"], row["player_id"])] = float(row["outs"])
        except (KeyError, TypeError, ValueError):
            continue
        name = (row.get("player_name") or "").strip().lower()
        if name:
            names.setdefault(str(row["player_id"]), name)
    return out, names


def model_over_probability(pmf: dict[str, Any], line: float) -> float | None:
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
    try:
        price = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if not won:
        return -1.0
    return price / 100.0 if price > 0 else 100.0 / abs(price)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    token = _token()

    actuals, name_by_id = load_actuals()
    dates = sorted({k[0] for k in actuals})

    counters = {"dates": len(dates), "dates_with_odds": 0, "starts_seen": 0,
                "no_line": 0, "no_name": 0, "push": 0, "graded": 0}
    entries: list[tuple[bool, float, float, Any, Any]] = []  # (over_won, model_p, line, over_odds, under_odds)

    for date in dates:
        summary_raw = _stream(
            f"mlb_source/source_artifacts/data/daily/daily_summary_{date.replace('-', '_')}.json", token)
        if summary_raw is None:
            continue
        odds_payload = None
        for variant in (f"oddsapi_pitcher_props_{date.replace('-', '_')}_pregame.json",
                        f"oddsapi_pitcher_props_{date.replace('-', '_')}.json"):
            raw = _stream(f"{ODDS_ROOT}/{date}/{variant}", token)
            if raw is None:
                continue
            try:
                candidate = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                continue
            props = candidate.get("pitcher_props") or {}
            if any(isinstance(v, dict) and "outs" in v for v in props.values()):
                odds_payload = props
                break
        if not odds_payload:
            continue
        counters["dates_with_odds"] += 1

        # name -> line, from the odds artifact
        lines = {}
        for name, markets in odds_payload.items():
            entry = (markets or {}).get("outs")
            if isinstance(entry, dict) and entry.get("line") is not None \
                    and entry.get("over_odds") and entry.get("under_odds"):
                lines[str(name).strip().lower()] = entry

        summary = json.loads(summary_raw.decode("utf-8", errors="replace"))
        for game in summary.get("outputs") or []:
            game_pk = str(game.get("game_pk") or "")
            for pid, props in (game.get("pitcher_props") or {}).items():
                dist = (props or {}).get("outs_dist")
                if not isinstance(dist, dict) or not dist:
                    continue
                counters["starts_seen"] += 1
                actual = actuals.get((date, game_pk, str(pid)))
                if actual is None:
                    continue
                name = name_by_id.get(str(pid))
                if not name:
                    counters["no_name"] += 1
                    continue
                quote = lines.get(name)
                if not quote:
                    counters["no_line"] += 1
                    continue
                line = float(quote["line"])
                if actual == line:
                    counters["push"] += 1
                    continue
                model_p = model_over_probability(dist, line)
                if model_p is None:
                    continue
                counters["graded"] += 1
                entries.append((actual > line, model_p, line,
                                quote["over_odds"], quote["under_odds"]))

    print("=" * 92)
    print("PRODUCTION SHIPPED MODEL -- PITCHER OUTS BETTING GRADE")
    print("=" * 92)
    for key, value in counters.items():
        print(f"  {key:18s} {value}")
    if not entries:
        print("\nNOTHING GRADED.")
        return 1

    n = len(entries)
    overs = sum(1 for won, *_ in entries if won)
    print(f"\nBASE RATE  outcomes over the line: {overs}/{n} = {overs/n:.2%}")

    # Side-blind baselines -- reported FIRST, because the June grade read as a
    # +12.40% model edge when +8.16% of it needed no model.
    print("\nSIDE-BLIND BASELINES (no model):")
    for label, always_over in (("ALWAYS OVER", True), ("ALWAYS UNDER", False)):
        profits = [payout(o if always_over else u, (won if always_over else not won))
                   for won, _p, _l, o, u in entries]
        profits = [p for p in profits if p is not None]
        wins = sum(1 for won, *_ in entries if (won if always_over else not won))
        print(f"  {label:12s} hit {wins/n:7.2%}   ROI {sum(profits)/len(profits):+7.2%}")

    print("\nMODEL (pick = side the model thinks is mispriced):")
    rows = []
    for method in ("multiplicative", "power"):
        profits, wins, over_picks = [], 0, 0
        for won, model_p, _line, over_odds, under_odds in entries:
            fair = devig([over_odds, under_odds], method=method)
            if not fair:
                continue
            take_over = model_p > fair[0]
            over_picks += int(take_over)
            hit = won if take_over else (not won)
            profit = payout(over_odds if take_over else under_odds, hit)
            if profit is None:
                continue
            profits.append(profit)
            wins += int(hit)
        rate, roi = wins / len(profits), sum(profits) / len(profits)
        rows.append({"method": method, "bets": len(profits), "hit_rate": rate, "roi": roi,
                     "over_picks": over_picks})
        print(f"  {method:15s} bets {len(profits):4d}  hit {rate:7.2%}  ROI {roi:+7.2%}  "
              f"over-picks {over_picks}/{len(profits)} ({over_picks/len(profits):.0%})")

    import math
    se = math.sqrt(0.5 * 0.5 / n)
    print(f"\n  SE of a hit rate at n={n}: {se:.2%}. Any difference under ~{2*se:.1%} is noise.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"counters": counters, "n": n, "over_base_rate": overs / n, "rows": rows},
            indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
