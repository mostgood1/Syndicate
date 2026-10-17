"""Prop consistency by threshold -- "cleared 30+ yds 10/10, 40+ 8/10, 50+ 5/10" (lane `alt-ladder-consistency`).

User 2026-10-16: "we should at least have historical data around prop consistency ie has hit 30 yds 10/10 40 yds 8/10
etc", after choosing "Alt-line consistency first" for the SGP builder. For every player x stat on a sheet this counts
how many of his recent games cleared each rung of a ladder around the line. The values are the ones the sheet row
already carries (`check.form10.values`, newest first), so the ladder exists for every prop whether or not alternate
lines were fetched.

Where the alt-ladder capture (`scripts/fetch_alt_ladders.py`, option c) has the rung, the rung also carries:
  * the best price and book on it;
  * the market's probability -- the median implied across books divided by the same player-market's MAIN-line margin
    factor (median implied / de-vigged fair at the main line, taken from the sheet row). It is an ESTIMATE: the alt
    rungs are over-only, so their own vig cannot be removed directly;
  * the consistency posterior -- `cheat_sheets.consistency_posterior`, the market as a beta prior worth 40 games,
    the same shrinkage the sheet's consistency column uses.
CONTEXT, NEVER AN EDGE LABEL: the 10-14 consistency backtest measured streaks at alt rungs as priced (-2.6 pts vs
the price). This table answers "how often has he cleared it", and the posterior keeps that from reading as a bet.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

RUNGS_EACH_SIDE = 2          # rungs below and above the main line (5 in all) when no alt ladder is captured
MAX_ALT_RUNGS = 7

# The step between generated rungs, by the stat's scale. A market not listed steps by 1.
_STEPS = (("passing yards", 25.0), ("pass_yds", 25.0), ("yards", 10.0), ("yds", 10.0), ("saves", 3.0),
          ("outs", 3.0), ("attempts", 3.0))
# Basketball "points" are big numbers; hockey points are 0-3. Read the scale off the line as well as the name.
_BIG_LINE_STEP = ((150.0, 25.0), (40.0, 10.0), (15.0, 3.0))

# The alternate key's base (`fetch_alt_ladders`: `base_market`) -> the market name the sheet's rows use, per sport.
# MLB and soccer rows already use OddsAPI's keys; NHL and the football sports use display names.
ALT_TO_SHEET = {
    "nhl": {"player_shots_on_goal": "SOG", "player_points": "POINTS", "player_goals": "GOALS",
            "player_assists": "ASSISTS", "player_total_saves": "SAVES"},
    "nfl": {"player_pass_yds": "Passing Yards", "player_pass_tds": "Passing TDs", "player_pass_attempts": "Passing Attempts",
            "player_pass_interceptions": "Interceptions", "player_rush_yds": "Rushing Yards",
            "player_rush_attempts": "Rushing Attempts", "player_reception_yds": "Receiving Yards",
            "player_receptions": "Receptions"},
}


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def step_for(market: Any, line: float) -> float:
    for limit, step in _BIG_LINE_STEP:
        if line >= limit:
            return step
    m = str(market or "").lower()
    for key, step in _STEPS:
        if key in m:
            return step if step <= max(1.0, line) else 1.0
    return 1.0


def rung_label(rung: float) -> str:
    """39.5 -> '40+', 2.5 -> '3+', 0.5 -> '1+'; a whole-number line reads 'over 40'."""
    if abs(rung - round(rung)) < 1e-9:
        return f"over {rung:g}"
    return f"{int(math.ceil(rung))}+"


def generated_rungs(market: Any, line: float) -> list[float]:
    """Round-number rungs around the line ('30+, 40+, 50+' for yards): the line itself, then +/- RUNGS_EACH_SIDE steps
    at the step's round numbers, never below 0.5."""
    step = step_for(market, line)
    base = line if abs(line - math.floor(line) - 0.5) < 1e-9 else math.floor(line) + 0.5
    if step > 1:
        base = round((line + 0.5) / step) * step - 0.5
    rungs = {round(base + k * step, 1) for k in range(-RUNGS_EACH_SIDE, RUNGS_EACH_SIDE + 1)}
    # A round rung within half a step of the line merges into it ("200+" and "201+" on a 200.5 line read as one).
    rungs = {r for r in rungs if abs(r - line) >= step / 2.0} | {round(line, 1)}
    return sorted(r for r in rungs if r >= 0.5)


def hit_counts(values: Iterable[Any], rung: float) -> tuple[int, int]:
    vals = [float(v) for v in values if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))]
    return sum(1 for v in vals if v > rung), len(vals)


def _row_values(row: Mapping[str, Any]) -> list[float]:
    form = (row.get("check") or {}).get("form10") or {}
    return [float(v) for v in form.get("values") or [] if isinstance(v, (int, float))]


def _margin_factor(row: Mapping[str, Any]) -> float | None:
    """median implied / de-vigged fair at the row's own main line -- the factor a rung's implied price is divided by."""
    shop = row.get("shop") or {}
    implied, fair = shop.get("median_implied"), (row.get("check") or {}).get("p_market")
    try:
        implied, fair = float(implied), float(fair)
    except (TypeError, ValueError):
        return None
    if str(row.get("side") or "").lower() == "under":
        return None      # the factor is read off the OVER side; an under row's fair is the other side
    if not (0 < fair < 1 and 0 < implied < 1):
        return None
    factor = implied / fair
    return factor if 1.0 <= factor <= 1.25 else None


def _implied(price: Any) -> float | None:
    from syndicate.features.shared.opportunity_signals import implied_probability

    return implied_probability(price)


def load_alt_rows(data_root: Path, sport: str, day: str) -> list[dict[str, Any]]:
    path = Path(data_root) / f"{sport}_source" / "tracking" / "alt_ladders" / f"{day}.jsonl"
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _alt_index(sport: str, alt_rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[float, dict[str, Any]]]:
    """(player, sheet market) -> rung -> {book: price}, OVER side, the latest capture of each book's rung."""
    mapping = ALT_TO_SHEET.get(sport, {})
    latest: dict[tuple, tuple[str, Any]] = {}
    for r in alt_rows:
        if str(r.get("side") or "").lower() != "over" or r.get("line") is None or r.get("price") is None:
            continue
        base = str(r.get("base_market") or "")
        market = mapping.get(base, base)
        key = (_norm(r.get("player")), _norm(market), float(r["line"]), str(r.get("bookmaker") or ""))
        stamp = str(r.get("captured_at") or "")
        if key not in latest or stamp >= latest[key][0]:
            latest[key] = (stamp, r.get("price"))
    index: dict[tuple[str, str], dict[float, dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    for (player, market, line, book), (_stamp, price) in latest.items():
        index[(player, market)][line][book] = price
    return index


def ladder_for(row: Mapping[str, Any], alt: Mapping[float, Mapping[str, Any]] | None = None,
               factor_row: Mapping[str, Any] | None = None, fallback_factor: float | None = None) -> dict[str, Any] | None:
    """One player x stat ladder from the row's recent values, with the alt rungs' prices where captured."""
    values = _row_values(row)
    try:
        line = float(row.get("line"))
    except (TypeError, ValueError):
        return None
    if not values:
        return None
    alt = alt or {}
    quoted = sorted(alt)
    if quoted:
        # the books' own rungs nearest the main line, plus the main line, back in order
        rungs = sorted(set(sorted(quoted, key=lambda r: abs(r - line))[:MAX_ALT_RUNGS]) | {round(line, 1)})
    else:
        rungs = generated_rungs(row.get("market"), line)
    factor = _margin_factor(factor_row or row)
    factor_basis = "this prop's main-line margin"
    if factor is None and fallback_factor is not None:
        # one-sided props (most MLB overs) have no main-line margin of their own: the typical one for the market
        factor, factor_basis = fallback_factor, "the market's typical main-line margin on this sheet"
    out = []
    for rung in rungs:
        hits, games = hit_counts(values, rung)
        cell: dict[str, Any] = {"rung": rung, "label": rung_label(rung), "hits": hits, "games": games,
                                "rate": round(hits / games, 3) if games else None, "main": abs(rung - line) < 1e-9}
        books = alt.get(rung) or {}
        if books:
            best_book, best_price = min(books.items(), key=lambda kv: _implied(kv[1]) or 1.0)
            implied = sorted(x for x in (_implied(p) for p in books.values()) if x)
            med = implied[len(implied) // 2] if implied else None
            p_market = round(min(0.995, med / factor), 4) if (med and factor) else None
            cell.update({"best_price": best_price, "best_book": best_book, "books": len(books), "p_market": p_market,
                         "p_market_basis": f"estimate: alt median implied / {factor_basis}" if p_market else None})
            if p_market is not None:
                from syndicate.features.shared.cheat_sheets import consistency_posterior

                cell["p_shrunk"] = consistency_posterior(p_market, hits, games)
        out.append(cell)
    face = {k: row.get(k) for k in ("team_name", "opponent", "league", "headshot_src", "headshot_url",
                                     "team_logo_src", "team_logo") if row.get(k)}
    return {**face, "player": row.get("player"), "team": row.get("team"), "pos": row.get("pos"), "market": row.get("market"),
            "event_id": row.get("event_id"), "line": line, "games": len(values), "values": values,
            "labels": list(row.get("form_labels") or [])[: len(values)], "rungs": out, "alt_captured": bool(quoted)}


def build(sheet: Mapping[str, Any], alt_rows: Iterable[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """One ladder per player x stat on the sheet. The OVER row (if any) carries the margin factor; the first row met
    carries the line."""
    sport = str(sheet.get("sport") or "")
    index = _alt_index(sport, alt_rows)
    by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    order: list[tuple[str, str]] = []
    for row in sheet.get("rows") or []:
        key = (_norm(row.get("player")), _norm(row.get("market")))
        if not key[0]:
            continue
        if key not in by_key:
            order.append(key)
        by_key[key].append(row)
    factors: dict[str, list[float]] = defaultdict(list)
    for rows in by_key.values():
        for r in rows:
            f = _margin_factor(r) if str(r.get("side") or "").lower() in ("over", "yes") else None
            if f is not None:
                factors[_norm(r.get("market"))].append(f)
    every = sorted(f for fs in factors.values() for f in fs)
    out = []
    for key in order:
        rows = by_key[key]
        main = rows[0]
        over = next((r for r in rows if str(r.get("side") or "").lower() in ("over", "yes")), None)
        pool = sorted(factors.get(key[1]) or []) or every
        fallback = pool[len(pool) // 2] if pool else None
        lad = ladder_for(main, index.get(key), factor_row=over, fallback_factor=fallback)
        if lad is not None:
            out.append(lad)
    return out
