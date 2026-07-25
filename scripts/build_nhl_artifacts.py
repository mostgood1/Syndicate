"""Local NHL artifact producer — the Syndicate-owned replacement for the vendor CLI subprocess.

Runs the ``hockeysim`` engine over a date's slate and writes the artifact CSVs the NHL UI reads,
ending the ``python -m nhl_betting.cli`` dependency (Phase 5, direct cutover). Reads only
Syndicate-owned inputs: the mirrored slate/roster/lineup/goalie artifacts + collected book odds
(``syndicate.local_nhl_odds`` collector output).

Pipeline per game: build_slate_features (projection-primed) -> inject consensus market lines ->
(optional) market-anchor -> build_game_prediction -> write predictions_{date}.csv. Player props go
through the boxscore engine (build_prop_projections) joined to collected prop lines.

Usage:
    py -3 scripts/build_nhl_artifacts.py --date 2026-06-14
    py -3 scripts/build_nhl_artifacts.py --date 2026-06-14 --props
    py -3 scripts/build_nhl_artifacts.py --date 2026-06-14 --no-anchor --out-dir /tmp/out
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from syndicate.features.nhl.sim_engine.hockeysim.adapters import build_game_prediction  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.artifacts import (  # noqa: E402
    prop_recommendation_row,
    write_predictions_csv,
    write_props_recommendations_csv,
)
from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyMarketLines  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.market_anchoring import anchor_game_features  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.player_props import build_prop_projections  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import (  # noqa: E402
    _processed_dir,
    build_slate_features,
    nhl_source_root,
)
from syndicate.features.nhl.sim_engine.hockeysim.features.market_lines import (  # noqa: E402
    load_market_lines,
    market_for_game,
)
from syndicate.features.nhl.sim_engine.hockeysim.features.props_lines import (  # noqa: E402
    load_props_lines,
    normalize_name,
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


def _poisson_p_over(line: float, lam: float) -> float:
    """P(X > line) for X ~ Poisson(lam). Half-lines have no push (P(X==line)=0)."""
    lam = max(0.0, float(lam))
    k = math.floor(float(line)) + 1  # smallest integer strictly greater than a .5 line
    cdf = 0.0
    for i in range(0, k):
        cdf += math.exp(-lam) * (lam ** i) / math.factorial(i)
    return max(0.0, min(1.0, 1.0 - cdf))


def build_props_for_date(
    date: str,
    *,
    root: Optional[Path] = None,
    n_sims: int = 400,
    out_dir: Optional[Path] = None,
) -> Tuple[Path, int]:
    """Produce props_recommendations_{date}.csv for a slate. Returns (path, row_count)."""
    games = build_slate_features(date, root=root)
    lines = load_props_lines(date, root=root)
    by_name: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for ln in lines:
        by_name[str(ln["name_key"])].append(ln)

    rows_out: List[Dict[str, object]] = []
    for g in games:
        namemap: Dict[str, int] = {}
        for p in list(g.home_players) + list(g.away_players):
            namemap[normalize_name(p.full_name)] = int(p.player_id)

        pid_market_line: Dict[Tuple[int, str], float] = {}
        for nk, rowlist in by_name.items():
            pid = namemap.get(nk)
            if pid is None:
                continue
            for r in rowlist:
                pid_market_line.setdefault((pid, str(r["market"])), float(r["line"]))
        if not pid_market_line:
            continue

        projs = build_prop_projections(g, lines=pid_market_line, n_sims=n_sims)
        proj_by_key = {(p.player_id, p.market): p for p in projs}

        for nk, rowlist in by_name.items():
            pid = namemap.get(nk)
            if pid is None:
                continue
            for r in rowlist:
                pr = proj_by_key.get((pid, str(r["market"])))
                if pr is None:
                    continue
                line = float(r["line"])
                p_over = _poisson_p_over(line, pr.proj_lambda)
                proj_obj = replace(pr, line=line, p_over=round(p_over, 6), p_under=round(1.0 - p_over, 6))
                op = r.get("over_price")
                up = r.get("under_price")
                row = prop_recommendation_row(
                    proj_obj,
                    over_price=int(round(float(op))) if op is not None else None,
                    under_price=int(round(float(up))) if up is not None else None,
                    book=str(r.get("book") or ""),
                )
                if row:
                    rows_out.append(row)

    out_path = (out_dir or _processed_dir(root)) / f"props_recommendations_{date}.csv"
    n = write_props_recommendations_csv(out_path, rows_out)
    return out_path, n


def main() -> int:
    ap = argparse.ArgumentParser(description="Build local NHL artifacts (hockeysim producer)")
    ap.add_argument("--date", required=True, help="slate date YYYY-MM-DD")
    ap.add_argument("--root", default=None, help="artifact root (default data/nhl_source)")
    ap.add_argument("--no-anchor", action="store_true", help="disable market anchoring")
    ap.add_argument("--anchor-weight", type=float, default=0.35)
    ap.add_argument("--props", action="store_true", help="also build props_recommendations")
    ap.add_argument("--props-n-sims", type=int, default=400)
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
    if args.props:
        ppath, pn = build_props_for_date(args.date, root=root, n_sims=args.props_n_sims, out_dir=out_dir)
        print(f"Wrote {pn} props recommendations -> {ppath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
