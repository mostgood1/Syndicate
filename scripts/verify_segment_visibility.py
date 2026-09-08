"""Prove the chain: join -> ledger file -> the bucket harness's own bucketing.

The harness fetches rows over HTTP from production, so the production reading
comes after a deploy. What this settles LOCALLY is the half that does not need
production: that a segment row refused by the real join produces a real ledger
line whose shape `bucket_live_edges.py` buckets into a non-`full` segment.

Run: python scripts/verify_segment_visibility.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.bucket_live_edges import band_for  # noqa: E402
from syndicate.features.shared.live_gameline_join import attach_live_gamelines  # noqa: E402
from syndicate.features.shared.live_gameline_ledger import (  # noqa: E402
    append_records,
    build_records,
)

HIT = {
    "game_pk": 824966, "home_win_prob": 0.62, "sims_run": 4000,
    "total_mean": 8.4, "home_margin": 0.6, "total_runs_dist": {}, "margin_dist": {},
    "as_of": "2026-09-07T02:00:00Z", "carried_forward": False, "analytic_markets": {},
    "progress": {"fraction": 0.4, "inning": 4, "half": "top", "outs": 1},
    "pregame_home_win_prob": 0.55,
}


def row(segment, market="h2h", line=None):
    return {
        "kind": "game", "market": market, "segment": segment, "line": line,
        "event_id": "1145a9db", "home_team": "Athletics", "away_team": "Texas Rangers",
        "books": ["pinnacle", "fanduel"], "age_seconds": 42.5,
        "updated_at": "2026-09-07T02:00:00Z",
        "game": {"state": "live", "home_score": 3, "away_score": 1},
        "projection": {},
    }


def main() -> int:
    grid = [row("full"), row("full", "totals", 8.5),
            row("first5"), row("first5", "totals", 4.5), row("first3"), row("first1")]
    coverage = attach_live_gamelines(grid, {("texas rangers", "athletics"): HIT})
    print("JOIN     considered=%s projected=%s priceable=%s"
          % (coverage["rows_live_gameline_considered"],
             coverage["rows_live_gameline_projected"],
             coverage["rows_live_gameline_priceable"]))
    print("         withheld_by_reason=%s" % (coverage["withheld_by_reason"],))

    records = build_records(grid, sport="mlb", date_str="2026-09-07")
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "live_gameline_ledger_2026-09-07.jsonl"
        cov = append_records(path, records)
        print("LEDGER   candidates=%s written=%s truncated=%s"
              % (cov["candidates"], cov["written"], cov["truncated_build_cap"]))
        lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    # exactly the key `bucket_live_edges.main` builds
    buckets = defaultdict(list)
    for r in lines:
        buckets[(str(r.get("game_state") or "?"), str(r.get("market") or "?"),
                 str(r.get("segment") or "?"), band_for(r.get("progress_fraction")))].append(r)

    print("\nHARNESS BUCKETS (state / market / segment / progress_band):")
    for key in sorted(buckets):
        rows = buckets[key]
        priced = sum(1 for r in rows if r.get("priceable"))
        print("  %-6s %-8s %-7s %-16s n=%d priceable=%d  reason=%s"
              % (*key, len(rows), priced,
                 sorted({str(r.get("withheld_reason")) for r in rows})))

    segments = {k[2] for k in buckets}
    print("\nSEGMENTS VISIBLE:", sorted(segments))
    if segments == {"full"}:
        print("FAIL -- still blind: the ledger shows only `full`.")
        return 1
    # counting must not have become pricing
    leaked = [r for r in lines if not r.get("priceable") and r.get("segment") != "full"
              and any(r.get(f) is not None for f in ("model_home_win_prob", "market_fair_prob", "edge_pp"))]
    if leaked:
        print("FAIL -- a refusal record carries a number:", leaked[0])
        return 1
    print("PASS -- non-full segments are countable, and carry no probability, "
          "no market price and no edge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
