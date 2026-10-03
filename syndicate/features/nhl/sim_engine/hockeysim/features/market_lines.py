"""Consensus market-lines reader — collected book odds -> per-game HockeyMarketLines.

Reads the Syndicate odds mirror (``data/nhl_source/data/odds/team/date=YYYY-MM-DD/oddsapi.csv``),
which is long-format (one row per bookmaker per market outcome), and collapses it into one
:class:`HockeyMarketLines` per game via a book consensus:

  * moneyline (h2h): consensus American odds per side (median of implied prob -> American).
  * totals: the line the most single-line books hang (see ``_consensus_total``) + consensus
    over/under odds from the books AT that line only.
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


def _quote_log_paths(date: str, root: Optional[Path] = None) -> List[Path]:
    """The per-book quote log shards for ``date`` and its two neighbours under the same NHL root
    (``<nhl_source>/tracking/book_quotes/<d>.jsonl[.gz]``, Central-kickoff-date keyed). The
    neighbours matter: a date's oddsapi.csv also carries adjacent-date games (measured: all 17
    remaining misses on the fleet 2026-09-30..10-04 were such games, absent from the date's shard)."""
    from datetime import date as _d, timedelta

    base = _odds_games_dir(root).parent.parent.parent / "tracking" / "book_quotes"
    try:
        day = _d.fromisoformat(str(date)[:10])
        days = [(day + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]
    except ValueError:
        days = [str(date)]
    return [p for d in days for p in (base / f"{d}.jsonl", base / f"{d}.jsonl.gz") if p.is_file()]


def _quote_log_pregame_totals(date: str, root: Optional[Path] = None) -> Dict[Tuple[str, str], Dict[str, Dict[float, Dict[str, float]]]]:
    """Per game, per book: the book's most recent FULL-GAME totals snapshot captured strictly
    before puck drop, as ``{book: {line: {"over": price, "under": price}}}`` (one line per book).

    Streams the shard (it can be tens of MB; nothing is cached or held but the per-book latest).
    Unreadable lines are skipped; a missing shard yields ``{}`` so the caller falls back.
    """
    import gzip
    import json

    latest: Dict[Tuple[Tuple[str, str], str], Tuple[str, Dict[float, Dict[str, float]]]] = {}
    for path in _quote_log_paths(date, root):
        opener = gzip.open if path.suffix == ".gz" else open
        try:
            with opener(path, "rt", encoding="utf-8") as fh:
                for raw in fh:
                    try:
                        row = json.loads(raw.replace("NaN", "null"))
                    except (ValueError, TypeError):
                        continue
                    if row.get("kind") != "game" or row.get("market") != "totals" or row.get("segment") not in (None, "full"):
                        continue
                    observed = str(row.get("snapshot_ts") or row.get("captured_at") or "")
                    commence = str(row.get("commence_time") or "")
                    sel = str(row.get("selection") or "").lower()
                    line, price = row.get("line"), row.get("price")
                    if not observed or not commence or observed >= commence or sel not in ("over", "under") \
                            or line is None or price is None:
                        continue
                    key = (_game_key(str(row.get("home_team") or ""), str(row.get("away_team") or "")),
                           str(row.get("bookmaker") or "").lower())
                    cur = latest.get(key)
                    if cur is None or observed > cur[0]:
                        latest[key] = (observed, {float(line): {sel: float(price)}})
                    elif observed == cur[0]:
                        cur[1].setdefault(float(line), {})[sel] = float(price)
        except OSError:
            continue
    out: Dict[Tuple[str, str], Dict[str, Dict[float, Dict[str, float]]]] = {}
    for (game, book), (_ts, points) in latest.items():
        out.setdefault(game, {})[book] = points
    return out


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


def _consensus_total(
    by_book: Dict[str, Dict[float, Dict[str, float]]],
) -> Tuple[Optional[float], List[float], List[float]]:
    """The totals line the books are actually hanging, and the over/under prices AT that line.

    WAS ``median(every totals point captured)``. The collector merges every capture into one file
    keyed by ``market_id`` -- which carries the point -- with no capture timestamp, so a book that
    moves (pregame) or keeps quoting after puck drop leaves one row per point it ever hung. Measured
    on the fleet 2026-09-30..10-04: the median priced a line != the modal pregame book line on
    24 of 31 games (8 off the half-goal grid; e.g. LAK@COL priced 9.0 with 8/11 books at 6.5),
    because one game held 15 points from 6.0 to 16.5 (lane ``nhl-game-lines-model``).

    Rule: a book counts only if it quotes exactly ONE totals point with BOTH sides (more than one =
    it moved or went in-play, and this file cannot say which point was its pregame line). The line
    is the point the most such books hang; a tie goes to the point whose de-vigged over is closest
    to even money, then to the lower point. Over/under prices are taken ONLY from books at that
    line. No such book -> ``None`` (an honest "no line"), never a blend of different numbers.
    """
    single: Dict[str, Tuple[float, float, float]] = {}
    for book, points in by_book.items():
        two_sided = [(p, s["over"], s["under"]) for p, s in points.items() if "over" in s and "under" in s]
        if len(points) == 1 and len(two_sided) == 1:
            single[book] = two_sided[0]
    if not single:
        return None, [], []
    counts: Dict[float, int] = {}
    for p, _o, _u in single.values():
        counts[p] = counts.get(p, 0) + 1

    def _over_fair(p: float) -> float:
        fair = []
        for q, o, u in single.values():
            po, pu = _american_to_prob(o), _american_to_prob(u)
            if q == p and po and pu:
                fair.append(po / (po + pu))
        return abs((statistics.fmean(fair) if fair else 0.5) - 0.5)

    line = min(counts, key=lambda p: (-counts[p], _over_fair(p), p))
    overs = [o for p, o, _u in single.values() if p == line]
    unders = [u for p, _o, u in single.values() if p == line]
    return line, overs, unders


def load_market_lines(date: str, *, root: Optional[Path] = None) -> Dict[Tuple[str, str], HockeyMarketLines]:
    """Return ``{(home_abbr, away_abbr): HockeyMarketLines}`` from the collected book odds."""
    rows = _read_csv_rows(_team_odds_path(date, root))
    if not rows:
        return {}

    # Bucket raw prices per game per market outcome.
    ml_home: Dict[Tuple[str, str], List[float]] = {}
    ml_away: Dict[Tuple[str, str], List[float]] = {}
    # totals: game -> book -> point -> {"over": price, "under": price}
    totals_by_book: Dict[Tuple[str, str], Dict[str, Dict[float, Dict[str, float]]]] = {}
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
            if low in ("over", "under") and point is not None:
                book = str(r.get("bookmaker_key") or r.get("bookmaker") or "").strip().lower()
                totals_by_book.setdefault(key, {}).setdefault(book, {}).setdefault(point, {})[low] = price
        elif market == "spreads":
            # home takes the -1.5 side; away the +1.5 side.
            if point is not None and point < 0 and name.strip().lower() == home.strip().lower():
                pl_home.setdefault(key, []).append(price)
            elif point is not None and point > 0 and name.strip().lower() == away.strip().lower():
                pl_away.setdefault(key, []).append(price)

    # Totals prefer the per-book quote log (timestamped, ~10 books): the oddsapi.csv capture holds
    # 2-4 books and no capture time, so it cannot tell a pregame line from an in-play one.
    quoted = _quote_log_pregame_totals(date, root)
    keys = set().union(ml_home, ml_away, totals_by_book, pl_home, pl_away)
    out: Dict[Tuple[str, str], HockeyMarketLines] = {}
    for key in keys:
        total_line, over_prices, under_prices = _consensus_total(quoted.get(key, {}))
        if total_line is None:
            total_line, over_prices, under_prices = _consensus_total(totals_by_book.get(key, {}))
        out[key] = HockeyMarketLines(
            total_line=total_line,
            puck_line=-1.5,
            home_ml_odds=_consensus_american(ml_home.get(key, [])),
            away_ml_odds=_consensus_american(ml_away.get(key, [])),
            over_odds=_consensus_american(over_prices),
            under_odds=_consensus_american(under_prices),
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
