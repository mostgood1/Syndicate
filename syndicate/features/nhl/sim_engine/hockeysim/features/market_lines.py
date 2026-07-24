"""Consensus market-lines reader — collected book odds -> per-game HockeyMarketLines.

Reads the Syndicate odds mirror (``data/nhl_source/data/odds/team/date=YYYY-MM-DD/oddsapi.csv``),
which is long-format (one row per bookmaker per market outcome), and collapses it into one
:class:`HockeyMarketLines` per game via a book consensus:

  * moneyline (h2h): consensus American odds per side (median of implied prob -> American).
  * totals: the consensus line (median point) + consensus over/under odds at ~that line.
  * puckline (spreads at ±1.5): consensus home -1.5 / away +1.5 odds.

Consensus is computed in implied-probability space (robust to the +/- American discontinuity), then
converted back. Missing markets degrade to ``None`` fields — the producer/adapter handles absence.
"""
from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..contracts import HockeyMarketLines
from .loaders import _odds_games_dir, _read_csv_rows, _team_abbr  # reuse mirror path + csv reader

# team odds live under data/odds/team/date=.../oddsapi.csv (sibling of the games dir).


def _team_odds_path(date: str, root: Optional[Path] = None) -> Path:
    games_dir = _odds_games_dir(root)  # .../data/odds/games
    return games_dir.parent / "team" / f"date={date}" / "oddsapi.csv"


def _american_to_prob(odds: float) -> Optional[float]:
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return None
    if o == 0:
        return None
    return 100.0 / (o + 100.0) if o > 0 else (-o) / ((-o) + 100.0)


def _prob_to_american(prob: float) -> int:
    p = min(max(float(prob), 1e-4), 1.0 - 1e-4)
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def _consensus_american(prices: List[float]) -> Optional[int]:
    probs = [p for p in (_american_to_prob(x) for x in prices) if p is not None]
    if not probs:
        return None
    return _prob_to_american(statistics.median(probs))


def _game_key(home: str, away: str) -> Tuple[str, str]:
    return (_team_abbr(home) or str(home).upper(), _team_abbr(away) or str(away).upper())


def load_market_lines(date: str, *, root: Optional[Path] = None) -> Dict[Tuple[str, str], HockeyMarketLines]:
    """Return ``{(home_abbr, away_abbr): HockeyMarketLines}`` from the collected book odds."""
    rows = _read_csv_rows(_team_odds_path(date, root))
    if not rows:
        return {}

    # Bucket raw prices per game per market outcome.
    ml_home: Dict[Tuple[str, str], List[float]] = {}
    ml_away: Dict[Tuple[str, str], List[float]] = {}
    over: Dict[Tuple[str, str], List[float]] = {}
    under: Dict[Tuple[str, str], List[float]] = {}
    total_pts: Dict[Tuple[str, str], List[float]] = {}
    pl_home: Dict[Tuple[str, str], List[float]] = {}
    pl_away: Dict[Tuple[str, str], List[float]] = {}

    def _f(v: object) -> Optional[float]:
        try:
            return float(v) if str(v).strip() != "" else None
        except (TypeError, ValueError):
            return None

    for r in rows:
        home = str(r.get("home") or r.get("home_team") or "").strip()
        away = str(r.get("away") or r.get("away_team") or "").strip()
        if not home or not away:
            continue
        key = _game_key(home, away)
        market = str(r.get("market") or "").strip().lower()
        name = str(r.get("outcome_name") or "").strip()
        price = _f(r.get("outcome_price"))
        point = _f(r.get("outcome_point"))
        if price is None:
            continue
        if market == "h2h":
            if name.strip().lower() == home.strip().lower():
                ml_home.setdefault(key, []).append(price)
            elif name.strip().lower() == away.strip().lower():
                ml_away.setdefault(key, []).append(price)
        elif market == "totals":
            low = name.lower()
            if low == "over":
                over.setdefault(key, []).append(price)
                if point is not None:
                    total_pts.setdefault(key, []).append(point)
            elif low == "under":
                under.setdefault(key, []).append(price)
                if point is not None:
                    total_pts.setdefault(key, []).append(point)
        elif market == "spreads":
            # home takes the -1.5 side; away the +1.5 side.
            if point is not None and point < 0 and name.strip().lower() == home.strip().lower():
                pl_home.setdefault(key, []).append(price)
            elif point is not None and point > 0 and name.strip().lower() == away.strip().lower():
                pl_away.setdefault(key, []).append(price)

    keys = set().union(ml_home, ml_away, over, under, pl_home, pl_away)
    out: Dict[Tuple[str, str], HockeyMarketLines] = {}
    for key in keys:
        total_line = statistics.median(total_pts[key]) if total_pts.get(key) else None
        out[key] = HockeyMarketLines(
            total_line=total_line,
            puck_line=-1.5,
            home_ml_odds=_consensus_american(ml_home.get(key, [])),
            away_ml_odds=_consensus_american(ml_away.get(key, [])),
            over_odds=_consensus_american(over.get(key, [])),
            under_odds=_consensus_american(under.get(key, [])),
            home_pl_odds=_consensus_american(pl_home.get(key, [])),
            away_pl_odds=_consensus_american(pl_away.get(key, [])),
        )
    return out


def market_for_game(
    lines: Dict[Tuple[str, str], HockeyMarketLines],
    home_name: str,
    away_name: str,
) -> Optional[HockeyMarketLines]:
    """Look up a game's market lines by team names (abbrev-normalized)."""
    return lines.get(_game_key(home_name, away_name))
