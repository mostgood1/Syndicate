"""Bucket the live game-line ledger and find where a model edge actually SURVIVES.

`[2026-09-07, user: "start bucket harness on MLB and soccer"]` -- the two engines
whose inputs AND outputs are both green in production. NCAAF and NFL each carry
6 input alarms and NCAAF has an open output alarm, so a bucket built on them
would inherit an ambiguity no bucket can resolve: a flat bucket from an unfed
feature and a genuinely flat bucket are the same number.

--------------------------------------------------------------------------
WHAT THIS MEASURES, AND WHAT IT CANNOT
--------------------------------------------------------------------------
The live game-line ledger (`<sport>_source/data/live_gameline_ledger/*.jsonl`)
carries, per row: `market`, `segment`, `game_state`, `progress_fraction`,
`model_home_win_prob`, `market_fair_prob`, `edge_pp`, `prob_std_err`,
`priceable` and `withheld_reason`. Profiled on MLB 2026-09-06: 2,454 rows, 15
events, all `game_state=live`, all `segment=full`.

**IT CARRIES NO OUTCOME.** There is no settled result on these rows, so this
harness does NOT compute win rate, ROI or CLV and does not pretend to. Those
live in the execution ledger, which is keyvalue-backed and has no row-level
export -- the same wall that made the segment re-grade unverifiable except by
re-running its own idempotency check.

What it DOES measure is where the model's edge survives its own uncertainty,
which is the question that gates everything downstream: an edge smaller than its
interval is not an edge, and 43.8% of MLB's live rows are withheld for exactly
that reason (`prob_interval_swamps_edge`, 1,075 of 2,454).

--------------------------------------------------------------------------
THE RULES THIS ENFORCES, each earned
--------------------------------------------------------------------------
* **DENOMINATOR BEFORE RATE.** Every bucket prints `n` first. Five wrong
  findings in one session came from rates without them.
* **A THIN BUCKET IS `UNMEASURED`, NOT ZERO.** Below `--min-n` a bucket reports
  its count and refuses to publish a rate. A 0% built on n=3 reads identically
  to a real zero.
* **SPLIT BY GAME STATE.** A finished slate reads as a regression when live and
  pregame rows are pooled. This ledger is all-live today, so the split is
  cheap now and load-bearing the moment pregame rows appear.
* **SEGMENT IS A DIMENSION, NOT A FOOTNOTE.** `segment` reached order rows and
  no MLB resolver read it, which mis-graded 49 settled orders for -$31.32.
* **REFUSALS ARE COUNTED, NOT DROPPED.** A bucket that withholds 90% of its
  rows is a finding. Filtering to `priceable` first would hide it.

    py -3 scripts/bucket_live_edges.py --sport mlb --days 3
    py -3 scripts/bucket_live_edges.py --sport mlb,soccer --days 7 --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Progress bands. Cut where the GAME changes character, not on even thirds:
# an edge early is a different animal from one with the outcome nearly settled,
# and the interval shrinks monotonically with time elapsed.
PROGRESS_BANDS = (
    (0.00, 0.25, "q1_early"),
    (0.25, 0.50, "q2_midearly"),
    (0.50, 0.75, "q3_midlate"),
    (0.75, 1.01, "q4_late"),
)


def _base_url() -> str:
    for key in ("SYNDICATE_BASE_URL", "BASE_URL"):
        v = str(os.environ.get(key) or "").strip()
        if v:
            return v.rstrip("/")
    return "https://syndicate-an21.onrender.com"


def _token() -> str:
    v = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if v:
        return v
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ADMIN_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def fetch_rows(sport: str, day: str, token: str) -> list[dict]:
    rel = (f"{sport}_source/data/live_gameline_ledger/"
           f"live_gameline_ledger_{day}.jsonl")
    url = (_base_url() + "/api/ops/artifacts/export?"
           + urllib.parse.urlencode({"pattern": rel, "limit": "2"}))
    req = urllib.request.Request(url, headers={"X-Admin-Token": token,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.load(resp)
    except Exception:
        return []
    out = []
    for _name, raw in (payload.get("artifacts") or {}).items():
        if not isinstance(raw, str):
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def band_for(progress) -> str:
    try:
        p = float(progress)
    except (TypeError, ValueError):
        return "unknown_progress"
    for lo, hi, name in PROGRESS_BANDS:
        if lo <= p < hi:
            return name
    return "unknown_progress"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sport", default="mlb,soccer")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--min-n", type=int, default=30,
                    help="below this a bucket reports UNMEASURED, never a rate")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    token = _token()
    if not token:
        print("REFUSING: no ADMIN_TOKEN. Every fetch would 401 and every bucket "
              "would read 0 rows -- a confident empty that looks like a finding.")
        return 2

    sports = [s.strip() for s in args.sport.split(",") if s.strip()]
    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(args.days)]

    report: dict = {"sports": {}, "days_requested": days, "min_n": args.min_n}
    for sport in sports:
        rows: list[dict] = []
        days_seen: list[str] = []
        for day in days:
            got = fetch_rows(sport, day, token)
            if got:
                days_seen.append(day)
                rows.extend(got)
        print(f"\n{'='*78}\n{sport.upper()}  {len(rows)} rows over {len(days_seen)} "
              f"day(s) {days_seen or '-- NONE --'}")
        if not rows:
            print("  NO ROWS. This says nothing about the model; it says the ledger "
                  "has no file for these dates.")
            report["sports"][sport] = {"rows": 0, "days": []}
            continue

        buckets: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            key = (str(r.get("game_state") or "?"),
                   str(r.get("market") or "?"),
                   str(r.get("segment") or "?"),
                   band_for(r.get("progress_fraction")))
            buckets[key].append(r)

        print(f"  {'state':6s} {'market':8s} {'seg':6s} {'band':12s} "
              f"{'n':>5s} {'priced':>7s} {'price%':>7s} {'|edge|pp':>9s} "
              f"{'se_pp':>7s} {'edge/se':>8s}  top refusal")
        out_buckets = []
        for key in sorted(buckets, key=lambda k: -len(buckets[k])):
            state, market, segment, band = key
            group = buckets[key]
            n = len(group)
            priced = [r for r in group if r.get("priceable") is True]
            edges = [abs(float(r["edge_pp"])) for r in group
                     if r.get("edge_pp") is not None]
            ses = [abs(float(r["prob_std_err"])) * 100.0 for r in group
                   if r.get("prob_std_err") is not None]
            reasons: dict[str, int] = defaultdict(int)
            for r in group:
                w = r.get("withheld_reason")
                if w:
                    reasons[str(w)] += 1
            top = max(reasons.items(), key=lambda kv: kv[1])[0][:34] if reasons else "-"

            row = {"game_state": state, "market": market, "segment": segment,
                   "progress_band": band, "n": n, "priceable": len(priced),
                   "withheld_by_reason": dict(reasons)}
            if n < args.min_n:
                # A rate on n<min is not a rate. Print the count and stop.
                print(f"  {state:6s} {market:8s} {segment:6s} {band:12s} "
                      f"{n:5d} {len(priced):7d} {'UNMEAS':>7s} {'UNMEAS':>9s} "
                      f"{'UNMEAS':>7s} {'UNMEAS':>8s}  {top}")
                row["verdict"] = "UNMEASURED_thin_bucket"
                out_buckets.append(row)
                continue

            price_pct = 100.0 * len(priced) / n
            mean_edge = statistics.fmean(edges) if edges else float("nan")
            mean_se = statistics.fmean(ses) if ses else float("nan")
            ratio = (mean_edge / mean_se) if ses and mean_se else float("nan")
            row.update({"priceable_pct": round(price_pct, 1),
                        "mean_abs_edge_pp": round(mean_edge, 3),
                        "mean_se_pp": round(mean_se, 3),
                        "edge_over_se": round(ratio, 3)})
            print(f"  {state:6s} {market:8s} {segment:6s} {band:12s} "
                  f"{n:5d} {len(priced):7d} {price_pct:6.1f}% {mean_edge:9.2f} "
                  f"{mean_se:7.2f} {ratio:8.2f}  {top}")
            out_buckets.append(row)

        report["sports"][sport] = {"rows": len(rows), "days": days_seen,
                                   "buckets": out_buckets}

    print("\nREAD IT AS: `edge/se` is the ratio this platform already gates on -- "
          "`prob_interval_swamps_edge` withholds a row whose edge is small "
          "against its own interval. A bucket with a high ratio is where the "
          "model says something the market does not, LOUDLY ENOUGH TO HEAR. It "
          "is NOT a claim that the model is right: this ledger carries no "
          "outcome, so nothing here is a win rate, an ROI or a CLV.")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
