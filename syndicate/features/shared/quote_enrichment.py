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
    """The slate date, from whichever key this sport's game dict actually uses.

    The snake_case names alone were not enough and that was the whole bug:
    measured on production 2026-08-06, MLB game dicts carry `gameDate`
    ("2026-08-06T16:35:00Z") and `officialDate` and NONE of game_date/date/
    selected_date/start_date/commence_time -- so this returned None, enrichment
    returned early, and every candidate came back with quote: null while the
    lookup itself worked perfectly against the same data offline.
    """
    for key in (
        "game_date", "date", "selected_date", "start_date", "commence_time",
        # camelCase variants -- what the board's own game dicts really use.
        "gameDate", "officialDate", "startTime", "commenceTime", "start_time",
    ):
        value = str(game.get(key) or "").strip()
        if len(value) >= 10:
            return value[:10]
    return None


def _team_names(game: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    """(home, away, matchup) in whatever shape the game dict holds them.

    `matchup` is a DICT on MLB game dicts -- {"home": {"abbr": "BAL", "name":
    "Baltimore Orioles"}, "away": {...}} -- not the "LAA @ BAL" string the
    board's candidate rows carry. Stringifying it would feed the matcher a blob
    of JSON, so pull the real names out and pass the string form only when it
    genuinely is a string.
    """
    def side(value: Any) -> Any:
        if isinstance(value, Mapping):
            return value.get("name") or value.get("abbr") or value.get("team") or None
        return value

    matchup = game.get("matchup")
    home = side(game.get("home_team")) or side(game.get("home"))
    away = side(game.get("away_team")) or side(game.get("away"))
    if isinstance(matchup, Mapping):
        home = home or side(matchup.get("home"))
        away = away or side(matchup.get("away"))
        matchup = None  # the dict is not a parseable "AWAY @ HOME" string
    elif not isinstance(matchup, str):
        matchup = None
    return home, away, matchup


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
        home_team, away_team, matchup = _team_names(game)

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
                home_team=home_team or row.get("home_team"),
                away_team=away_team or row.get("away_team"),
                matchup=matchup or row.get("matchup"),
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


# Flattened fields the board template renders from. Kept here, next to the
# enrichment that produces them, rather than duplicated at each call site.
_FLAT_QUOTE_FIELDS = (
    ("book", "bookmaker"),
    ("best_book", "best_bookmaker"),
    ("best_price", "best_price"),
    ("books_quoting", "books_quoting"),
    ("price_rank", "price_rank"),
    ("consensus_price", "consensus_price"),
    ("book_age_seconds", "book_age_seconds"),
    ("capture_age_seconds", "capture_age_seconds"),
    ("book_updated_at", "book_updated_at"),
)


def enrich_candidate_rows(
    game: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    *,
    sport_slug: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Attach price context to FINISHED candidate dicts.

    Enriching `game_market_recommendations` alone was not enough and the live
    numbers said so: 3-7 of 46 MLB candidates carried a quote, all of them
    Moneyline/Total. `_game_bet_candidates_from_game` builds candidates in
    SEVERAL loops -- game_market_recommendations, gameLens, the plain `betting`
    dict, shared_top_play_rows -- and only the first passed through enrichment.
    Player props come from the others, and props are most of the volume.

    So this runs over the assembled list instead, which is the one place every
    loop's output converges. Reads the flattened candidate shape (`entity`/
    `player_name`, text `line` and `odds`) rather than the raw row shape.
    """
    if not candidates:
        return candidates
    try:
        from syndicate.features.shared.odds_book_quotes import quote_ref_for_bet

        date_str = _game_date(game)
        if not date_str:
            return candidates
        now = now or datetime.now(timezone.utc)
        event_id = game.get("event_id") or game.get("gamePk") or game.get("game_pk")
        home_team, away_team, matchup = _team_names(game)

        for candidate in candidates:
            if not isinstance(candidate, dict) or candidate.get("quote"):
                continue
            quote = quote_ref_for_bet(
                sport=sport_slug,
                date_str=date_str,
                event_id=event_id,
                market=candidate.get("market"),
                selection=candidate.get("pick") or candidate.get("selection"),
                line=candidate.get("line"),
                player_name=candidate.get("player_name") or candidate.get("entity"),
                home_team=home_team,
                away_team=away_team,
                matchup=matchup,
                now=now,
            )
            if not quote:
                continue
            candidate["quote"] = quote
            for flat_key, quote_key in _FLAT_QUOTE_FIELDS:
                candidate[flat_key] = quote.get(quote_key)

            best_implied = _implied_probability(quote.get("best_price"))
            shown_implied = _implied_probability(candidate.get("odds"))
            if best_implied is not None and shown_implied is not None:
                candidate["price_improvement_pct"] = round((shown_implied - best_implied) * 100.0, 2)
    except Exception:
        return candidates
    return candidates
