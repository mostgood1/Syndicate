"""Local NHL artifact producer — the Syndicate-owned replacement for the vendor CLI subprocess.

Runs the ``hockeysim`` engine over a date's slate and writes the artifact CSVs the NHL UI reads,
ending the ``python -m nhl_betting.cli`` dependency (Phase 5, direct cutover). Reads only
Syndicate-owned inputs: the mirrored slate/roster/lineup/goalie artifacts + collected book odds
(``syndicate.local_nhl_odds`` collector output).

Pipeline per game: build_slate_features (projection-primed) -> inject consensus market lines ->
(optional) market-anchor -> build_game_prediction -> write predictions_{date}.csv.

Usage:
    py -3 scripts/build_nhl_artifacts.py --date 2026-06-14
    py -3 scripts/build_nhl_artifacts.py --date 2026-06-14 --no-anchor --out-dir /tmp/out
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Dict, Optional, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from syndicate.features.nhl.sim_engine.hockeysim.adapters import build_game_prediction  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.artifacts import write_predictions_csv  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyMarketLines  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.market_anchoring import anchor_game_features  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import (  # noqa: E402
    _processed_dir,
    build_slate_features,
    nhl_source_root,
)
from syndicate.features.nhl.sim_engine.hockeysim.features.market_lines import (  # noqa: E402
    load_market_lines,
    market_for_game,
)


def build_predictions_for_date(
    date: str,
    *,
    root: Optional[Path] = None,
    anchor: bool = True,
    anchor_weight: float = 0.35,
    out_dir: Optional[Path] = None,
) -> Tuple[Path, int]:
    """Produce predictions_{date}.csv for a slate. Returns (path, game_count)."""
    games = build_slate_features(date, root=root)
    lines = load_market_lines(date, root=root)

    predictions = []
    markets: Dict[str, HockeyMarketLines] = {}
    for g in games:
        market = market_for_game(lines, g.home.name, g.away.name)
        if market is not None:
            g = replace(g, market=market)
            if anchor:
                g = anchor_game_features(g, weight=anchor_weight)
        markets[g.game_pk] = g.market
        predictions.append(build_game_prediction(g))

    out_path = (out_dir or _processed_dir(root)) / f"predictions_{date}.csv"
    n = write_predictions_csv(out_path, predictions, markets)
    return out_path, n


def main() -> int:
    ap = argparse.ArgumentParser(description="Build local NHL artifacts (hockeysim producer)")
    ap.add_argument("--date", required=True, help="slate date YYYY-MM-DD")
    ap.add_argument("--root", default=None, help="artifact root (default data/nhl_source)")
    ap.add_argument("--no-anchor", action="store_true", help="disable market anchoring")
    ap.add_argument("--anchor-weight", type=float, default=0.35)
    ap.add_argument("--out-dir", default=None, help="output dir (default <root>/data/processed)")
    args = ap.parse_args()

    root = Path(args.root) if args.root else None
    out_dir = Path(args.out_dir) if args.out_dir else None
    path, n = build_predictions_for_date(
        args.date, root=root, anchor=not args.no_anchor,
        anchor_weight=args.anchor_weight, out_dir=out_dir,
    )
    if n == 0:
        print(f"No games for {args.date} (no mirrored scoreboard). Nothing written.")
        return 1
    print(f"Wrote {n} game predictions -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
