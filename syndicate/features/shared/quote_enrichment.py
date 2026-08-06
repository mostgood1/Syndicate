"""Attach per-book price context to board recommendation rows (#215).

WHY THIS IS ONE MODULE AND NOT SEVEN
------------------------------------
Every sport builds `game_market_recommendations` its own way
(`_mlb_game_market_recommendation_rows`, `_nfl_...`, `_ncaaf_...`, plus
nba/cards.py and wnba/cards.py), but all of them funnel through a single
consumer: `_game_bet_candidates_from_game`. Enriching there covers all eight
sports with one implementation, and a sport added later gets it for free.

WHAT IT ADDS, AND WHY EACH FIELD EARNS ITS PLACE
-----------------------------------------------
A row today carries `display_pick`, `ev_pct`, `p_win`, `market_label`,
`selection` -- no price, no book, no timestamp. That is why "which book has the
edge" had nowhere to live and why the board could not tell a dead market from a
fresh one.

`quote`      -- the full quote_ref: book, price, both clocks, rank, consensus.
`ev_pct`     -- RECOMPUTED against best available price where a model
                probability exists. This changes WHICH candidates surface, not
                just how they look: #211 measured 140 bets clearing a 3% edge
                threshold under best price and 0 the other way, because best
                price is never worse, so measured edge is never lower.
`price_improvement_pct` -- what moving book is worth on this row, in probability
                points. The one number that makes #211's +2.79 actionable at bet
                time rather than visible only in a backtest.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not drop rows that have no quote. A missing quote means the odds log has
nothing for that market yet (out of season, a market we do not fetch, a game
before the #209 capture shipped) -- not that the pick is invalid. Silently
dropping them would make the board look emptier the further back you look, which
is the opposite of informative. Rows without a quote keep their original
`ev_pct` untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

_QUOTE_CACHE_KEY = "_quote_rows_cache"


def _implied_probability(price: Any) -> float | None:
    try:
        value = float(price)
    except Exception:
        return None
    if value == 0:
        return None
    return (100.0 / (value + 100.0)) if value > 0 else (abs(value) / (abs(value) + 100.0))


def _model_probability(row: Mapping[str, Any]) -> float | None:
    for key in ("p_win", "model_probability", "confidence", "model_prob"):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except Exception:
            continue
        # Sports modules are inconsistent about percent vs fraction; both appear
        # on real rows. Anything above 1 is a percentage.
        if value > 1.0:
            value = value / 100.0
        if 0.0 < value < 1.0:
            return value
    return None


def _game_date(game: Mapping[str, Any]) -> str | None:
    for key in ("game_date", "date", "selected_date", "start_date", "commence_time"):
        value = str(game.get(key) or "").strip()
        if len(value) >= 10:
            return value[:10]
    return None


def _selection_hint(row: Mapping[str, Any]) -> str | None:
    for key in ("selection", "side", "team_side", "pick", "display_pick"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return None


def _market_hint(row: Mapping[str, Any]) -> str | None:
    for key in ("market_label", "market", "label"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return None


def enrich_recommendation_rows(
    game: Mapping[str, Any],
    rows: list[dict[str, Any]],
    *,
    sport_slug: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Stamp `quote` on each row and re-rank against best price.

    Never raises. The board rendering a row without price context is a
    degradation; the board 500ing because an odds log was mid-write is an
    outage.
    """
    if not rows:
        return rows
    try:
        from syndicate.features.shared.odds_book_quotes import quote_ref_for_bet

        date_str = _game_date(game)
        if not date_str:
            return rows
        now = now or datetime.now(timezone.utc)
        event_id = game.get("event_id") or game.get("gamePk") or game.get("game_pk")

        for row in rows:
            if not isinstance(row, dict) or row.get("quote"):
                continue
            quote = quote_ref_for_bet(
                sport=sport_slug,
                date_str=date_str,
                event_id=event_id,
                market=_market_hint(row),
                selection=_selection_hint(row),
                line=row.get("line") if row.get("line") is not None else row.get("market_line"),
                player_name=row.get("player_name") or row.get("player"),
                # Identity is a hard filter in quote_ref_for_bet, so these are
                # what actually let a match happen at all. MLB board rows carry
                # a StatsAPI gamePk while quotes carry an OddsAPI event hash --
                # the ids CANNOT match -- so the join is the player for props
                # and the team pair for game markets, and `matchup` ("LAA @ BAL")
                # is often the only place the teams appear on a board row.
                home_team=game.get("home_team") or row.get("home_team"),
                away_team=game.get("away_team") or row.get("away_team"),
                matchup=game.get("matchup") or row.get("matchup"),
                now=now,
            )
            if not quote:
                continue
            row["quote"] = quote

            model_probability = _model_probability(row)
            best_implied = _implied_probability(quote.get("best_price"))
            # The reference is the price the ROW is showing, not quote["price"].
            # Board rows carry no bookmaker, so quote_ref returns the best book
            # by default and comparing it against itself is always 0.00 -- which
            # is what the first version of this did, silently reporting "no
            # improvement available" on every card. The row's own `odds` is the
            # number actually on screen, so that is what an improvement is
            # measured against.
            shown_implied = _implied_probability(
                row.get("odds") if row.get("odds") is not None else row.get("price")
            )
            if best_implied is not None and shown_implied is not None:
                # Positive means the best book beats what this row is showing --
                # i.e. what shopping is worth on THIS bet, right now.
                row["price_improvement_pct"] = round((shown_implied - best_implied) * 100.0, 2)
            if model_probability is not None and best_implied is not None:
                row["ev_pct"] = round((model_probability - best_implied) * 100.0, 2)
                row["ev_priced_against"] = quote.get("best_bookmaker")
    except Exception:
        return rows
    return rows
