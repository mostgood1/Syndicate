#!/usr/bin/env python3
"""Run the Kalshi-vs-Polymarket US moneyline arb scan once, against real
production inputs, and print what it finds.

DETECTION ONLY -- this reads two already-computed artifacts (the board's own
rows, Kalshi's markets) and makes a handful of live, read-only calls to
Polymarket US (`polymarket_us_markets.fetch_game_markets`, which locates the
real game-market offset range and pages to the end of it -- see that
function's docstring for why the offset cannot be hardcoded). Nothing here
can place an order.

    python scripts/probe_kalshi_polymarket_arb.py --date 2026-08-24
    python scripts/probe_kalshi_polymarket_arb.py --date 2026-08-24 --fee-buffer 0.02
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.kalshi_polymarket_arb import (  # noqa: E402
    DEFAULT_FEE_BUFFER,
    run_arb_scan,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Kalshi vs Polymarket US moneyline arb scan.")
    parser.add_argument("--date", required=True, help="slate date, YYYY-MM-DD")
    parser.add_argument("--fee-buffer", type=float, default=DEFAULT_FEE_BUFFER)
    args = parser.parse_args()

    result = run_arb_scan(selected_date=args.date, fee_buffer=args.fee_buffer)

    if result.get("status") != "ok":
        print(f"[kalshi_polymarket_arb] STATUS=error reason={result.get('reason')}", flush=True)
        return 1

    print(
        "[kalshi_polymarket_arb] SCAN"
        f" date={result['date']}"
        f" kalshi_discovery={result.get('kalshi_discovery')}"
        f" kalshi_moneylines={result['kalshi_moneylines_resolved']}"
        f" kalshi_refusals={result['kalshi_refusals']}"
        f" polymarket_moneylines={result['polymarket_moneylines_resolved']}"
        f" polymarket_refusals={result['polymarket_refusals']}"
        f" matched_games={result['matched_games']}"
        f" join_refusals={result['join_refusals']}"
        f" flagged={result['flagged_count']}"
        f" fee_buffer={result['fee_buffer_used']}",
        flush=True,
    )

    for opp in result["opportunities"]:
        marker = "OPPORTUNITY" if opp["is_opportunity"] else "no_edge"
        print(
            f"[kalshi_polymarket_arb] {marker}"
            f" {opp['away_team']}@{opp['home_team']} {opp['game_date']}"
            f" combo={opp['best_combo']} cost={opp['best_combo_cost']:.4f}"
            f" raw_edge={opp['raw_edge']:.4f} edge_after_buffer={opp['edge_after_buffer']:.4f}"
            f" kalshi_ticker={opp['kalshi_ticker']} polymarket_id={opp['polymarket_market_id']}"
            f" polymarket_fee_coefficient={opp['polymarket_fee_coefficient']}",
            flush=True,
        )

    if not result["opportunities"]:
        print("[kalshi_polymarket_arb] NO_MATCHED_GAMES", flush=True)

    return 0 if result["flagged_count"] >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
