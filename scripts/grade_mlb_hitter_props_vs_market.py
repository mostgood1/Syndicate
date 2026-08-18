"""Do MLB hitter props BEAT THE MARKET? `#440` Phase 7 — the falsification test.

WHY THIS IS THE LOAD-BEARING MEASUREMENT. Everything scored this session was
scored against CLIMATOLOGY, which answers "does the engine know anything". It
cannot answer "does the engine know something the PRICE does not", and that is
the only question that decides whether the sim is a betting asset.

Hitter props are the right place to ask it:
  * they are the ONLY MLB market with measured conditional signal
    (r = 0.13-0.16, de-biasing flips 5 of 7 markets) `[measured 08-14]`;
  * MLB game lines carry a SHARP reference on 102 of 102 markets (Pinnacle,
    Betfair, Matchbook) while PROPS carry 0% -- so props are priced by soft
    books, which is a materially lower bar than beating a sharp close;
  * the live game-line model already LOSES to the market (Brier +0.038).

THE THREE FORECASTS, scored on identical rows:
    model_raw  -- production's `p_*_Kplus`
    model_cal  -- production's `p_*_Kplus_cal` (its existing calibration layer)
    market     -- de-vigged from the two quoted prices

Brier score, lower is better. If neither model beats `market`, MLB has no
demonstrated edge in the one market where it has demonstrated signal, and the
improvement programme should not be started on the assumption that it does.

JOINS AND THEIR RISKS, stated rather than discovered later:
  * model -> market is by PLAYER NAME (the odds artifact is name-keyed). Name
    joins are the `#218` failure mode; unmatched are COUNTED and reported.
  * bucket `X_Kplus` maps to line `K - 0.5`, because "1 or more" IS "over 0.5".
  * PRODUCTION supplies the projections (the local mirror carries only HR-target
    subsets), per CLAUDE.md's "never scope a backtest from the checkout".

Usage:
  py -3 scripts/grade_mlb_hitter_props_vs_market.py --dates 2026-06-15..2026-06-27
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date as Date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.model_scoring import brier_score  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

DATA = REPO_ROOT / "data/mlb_source/source_artifacts/data"
SNAPSHOTS = DATA / "daily_pitcher_props/snapshots"
BASE = "https://syndicate-an21.onrender.com"

# bucket prefix -> (odds market key, COLUMN IN mlb_batter_game_log.csv)
#
# THE COLUMN NAMES ARE THE CSV'S, NOT THE STATSAPI BOX-SCORE'S. The first draft
# of this file used `hits`/`totalBases`/`runs`/`homeRuns` -- the API spelling --
# against a CSV whose headers are `h`/`tb`/`r`/`hr`. Every lookup missed, and
# because the reader did `float(row.get(key) or 0)` every outcome silently
# became 0.0. The run "succeeded", reported a base rate of 0.000 for three of
# four families, and would have shown the model BEATING THE MARKET in 3 of 4 --
# because with all-zero outcomes Brier reduces to p^2 and the model simply
# predicts smaller numbers. `rbi` matched by coincidence, which is the only
# reason one family looked different and the bug was visible at all.
FAMILIES = {
    "hits": ("batter_hits", "h"),
    "hits_runs_rbis": ("batter_hits_runs_rbis", "__hrr__"),
    "total_bases": ("batter_total_bases", "tb"),
    "rbis": ("batter_rbis", "rbi"),
    "runs": ("batter_runs_scored", "r"),
    "home_runs": ("batter_home_runs", "hr"),
}
BUCKET_RE = re.compile(r"^(?P<fam>[a-z_]+?)_(?P<k>\d+)plus$")


def _env() -> dict:
    out = {}
    for line in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def fetch_projections(date: str, token: str, cache: Path) -> list[dict]:
    """Flat rows: name, bucket, k, family, p_raw, p_cal."""
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / f"summary_{date}.json"
    if cached.is_file():
        raw = cached.read_bytes()
    else:
        path = f"mlb_source/source_artifacts/data/daily/daily_summary_{date.replace('-', '_')}.json"
        try:
            req = urllib.request.Request(
                f"{BASE}/api/ops/artifacts/stream?path={urllib.parse.quote(path)}",
                headers={"X-Admin-Token": token})
            raw = urllib.request.urlopen(req, timeout=240).read()
        except Exception:
            return []
        cached.write_bytes(raw)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return []

    rows = []
    for game in payload.get("outputs") or []:
        topn = (game or {}).get("hitter_props_likelihood_topn") or {}
        for bucket, entries in topn.items():
            m = BUCKET_RE.match(str(bucket))
            if not m or not isinstance(entries, list):
                continue
            fam, k = m.group("fam"), int(m.group("k"))
            if fam not in FAMILIES:
                continue
            for row in entries:
                if not isinstance(row, dict):
                    continue
                p_raw = p_cal = None
                for key, val in row.items():
                    if not isinstance(key, str) or not isinstance(val, (int, float)):
                        continue
                    if key.startswith("p_") and key.endswith(f"_{k}plus"):
                        p_raw = float(val)
                    elif key.startswith("p_") and key.endswith(f"_{k}plus_cal"):
                        p_cal = float(val)
                if p_raw is None and p_cal is None:
                    continue
                name = str(row.get("name") or "").strip().lower()
                if name:
                    rows.append({"date": date, "name": name, "family": fam, "k": k,
                                 "p_raw": p_raw, "p_cal": p_cal})
    return rows


def load_odds(date: str) -> dict[tuple[str, str], dict]:
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
            if not isinstance(entry, dict):
                continue
            if entry.get("line") is None or entry.get("over_odds") is None or entry.get("under_odds") is None:
                continue
            out[(str(name).strip().lower(), mk)] = entry
    return out


def load_actuals() -> dict[tuple[str, str], dict]:
    path = DATA / "processed/mlb_batter_game_log.csv"
    out: dict[tuple[str, str], dict] = {}
    if not path.is_file():
        return out
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("player_name") or row.get("name") or "").strip().lower()
            date = str(row.get("date") or "")[:10]
            if name and date:
                out[(date, name)] = row
    return out


def stat_value(row: dict, stat: str) -> float | None:
    """None when the column is ABSENT. Never 0.0.

    A missing column must not look like a zero outcome -- that is what turned a
    name-mapping error into a fake "model beats market" result. Absent is
    unknown; the caller counts it and drops the row.
    """
    def f(key):
        if key not in row:
            return None
        raw = row.get(key)
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if stat == "__hrr__":
        parts = [f("h"), f("r"), f("rbi")]
        return sum(parts) if all(p is not None for p in parts) else None
    return f(stat)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", default="2026-06-15..2026-06-27")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    lo, _, hi = args.dates.partition("..")
    d0, d1 = Date.fromisoformat(lo), Date.fromisoformat(hi or lo)
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]

    env = _env()
    token = env.get("ADMIN_TOKEN", "")
    cache = Path(env.get("TEMP", "/tmp")) / "mlb_prop_market_cache"
    actuals = load_actuals()

    counters = Counter()
    scored: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    print("=" * 96)
    print("MLB HITTER PROPS — MODEL vs MARKET (the falsification test)")
    print("=" * 96)
    print(f"\n  actual player-games loaded: {len(actuals)}\n")

    for date in dates:
        projections = fetch_projections(date, token, cache)
        odds = load_odds(date)
        if not projections or not odds:
            print(f"  {date}: projections={len(projections)} odds={len(odds)} -> SKIPPED")
            counters["dates_skipped"] += 1
            continue
        counters["dates_used"] += 1
        hit = 0
        for pr in projections:
            counters["projection_rows"] += 1
            mk, stat = FAMILIES[pr["family"]]
            quote = odds.get((pr["name"], mk))
            if quote is None:
                counters["no_market"] += 1
                continue
            line = float(quote["line"])
            # bucket `Kplus` is the line K-0.5; anything else is a different bet
            if abs(line - (pr["k"] - 0.5)) > 1e-6:
                counters["line_mismatch"] += 1
                continue
            actual_row = actuals.get((date, pr["name"]))
            if actual_row is None:
                counters["no_actual"] += 1
                continue
            value = stat_value(actual_row, stat)
            if value is None:
                counters["no_stat"] += 1
                continue
            fair = devig([quote["over_odds"], quote["under_odds"]])
            if not fair:
                counters["devig_failed"] += 1
                continue
            outcome = 1.0 if value >= pr["k"] else 0.0
            key = pr["family"]
            if pr["p_raw"] is not None:
                scored[key]["model_raw"].append(brier_score(pr["p_raw"], outcome))
            if pr["p_cal"] is not None:
                scored[key]["model_cal"].append(brier_score(pr["p_cal"], outcome))
            scored[key]["market"].append(brier_score(fair[0], outcome))
            scored[key]["_outcomes"].append(outcome)
            counters["scored"] += 1
            hit += 1
        print(f"  {date}: projections={len(projections)} odds={len(odds)} scored={hit}")

    print("\nJOIN (unmatched are counted, never dropped silently)")
    for k, v in sorted(counters.items()):
        print(f"  {k:18s} {v}")
    if not counters["scored"]:
        print("\nNOTHING SCORED.")
        return 1

    print("\nRESULTS  — Brier, LOWER IS BETTER\n")
    header = (f"  {'family':16s} {'n':>6s} {'base rate':>10s} {'model_raw':>10s} "
              f"{'model_cal':>10s} {'market':>9s}   verdict")
    print(header)
    print("  " + "-" * (len(header) + 6))
    rows_out = []
    for family, cells in sorted(scored.items()):
        mkt = [x for x in cells["market"] if x is not None]
        raw = [x for x in cells["model_raw"] if x is not None]
        cal = [x for x in cells["model_cal"] if x is not None]
        outs = cells["_outcomes"]
        if not mkt:
            continue
        b_mkt = statistics.fmean(mkt)
        b_raw = statistics.fmean(raw) if raw else None
        b_cal = statistics.fmean(cal) if cal else None
        base = statistics.fmean(outs)
        best = min(b for b in (b_raw, b_cal) if b is not None) if (raw or cal) else None
        verdict = "—"
        # A base rate pinned at 0 or 1 is a BROKEN JOIN, not a result. Scoring it
        # would compare forecasts against a constant outcome, under which Brier
        # collapses to p^2 and "beating the market" means only "predicts smaller
        # numbers". This guard exists because that exact failure produced a
        # confident "model beats market in 3 of 4 families" on the first run.
        if base <= 0.001 or base >= 0.999:
            verdict = f"REFUSED — degenerate base rate {base:.3f} (join is broken)"
            best = None
        elif best is not None:
            verdict = "MODEL BEATS MARKET" if best < b_mkt else "market wins"
        rows_out.append({"family": family, "n": len(mkt), "brier_market": b_mkt,
                         "brier_model_raw": b_raw, "brier_model_cal": b_cal,
                         "base_rate": statistics.fmean(outs), "verdict": verdict})
        print(f"  {family:16s} {len(mkt):6d} {statistics.fmean(outs):10.3f} "
              f"{(f'{b_raw:.5f}' if b_raw is not None else '—'):>10s} "
              f"{(f'{b_cal:.5f}' if b_cal is not None else '—'):>10s} "
              f"{b_mkt:9.5f}   {verdict}")

    beat = [r for r in rows_out if r["verdict"] == "MODEL BEATS MARKET"]
    print(f"\n  families where the model beats the market: {len(beat)} of {len(rows_out)}")
    print("  Brier differences of a few 1e-3 on n in the hundreds are NOT decisive;")
    print("  treat this as a screen, and require a paired test before acting.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"counters": dict(counters), "rows": rows_out},
                                        indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
