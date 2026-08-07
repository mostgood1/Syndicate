"""Canonical market keys — the join key between our board and any odds feed (#224).

Step 3 of `docs/ai_context/plan_one_opportunity_pipeline.md`.

THE MEASUREMENT THAT MOTIVATED THIS
-----------------------------------
`/api/ops/opportunity-contract/status`, first reading 2026-08-06:
`missing_market_key` was **100% of every row, in every lane, in both sports** --
106/106 game candidates, 46/46 prop sources, 45/45 dashboard rows. Every board
row carried only a display string ("Hits", "Total Bases", "Moneyline") while the
odds log keys on `batter_hits`, `batter_total_bases`, `h2h`. Nothing could join.

The keys mostly exist upstream (MLB prop rows carry `prop: "batter_total_bases"`,
rail sources carry `stat`), they were just never carried to the board. This
module is the one place that decides what canonical means, so producers thread a
key rather than each inventing one.

WHY OddsAPI's VOCABULARY
------------------------
Because that is what the quote log is keyed on, and the quote log is what a
canonical key has to join TO. Choosing our own vocabulary would mean translating
at every read instead of once at production.

NOT A PARSER OF DISPLAY TEXT
----------------------------
`canonical_market_key` takes a candidate key or a stat name. It deliberately
returns None rather than guessing from free text: a wrong key silently joins a
bet to another market's price, which is worse than an unjoined row and is exactly
the class of error #217 fixed by making identity a hard filter.
"""

from __future__ import annotations

from typing import Any

# Stat/label vocabulary -> OddsAPI market key. Left side is what our producers
# actually emit (checked against live rail sources and prop artifacts); right
# side is what `book_quotes` is keyed on.
_MLB: dict[str, str] = {
    "hits": "batter_hits",
    "batter_hits": "batter_hits",
    "total_bases": "batter_total_bases",
    "total bases": "batter_total_bases",
    "batter_total_bases": "batter_total_bases",
    "home_runs": "batter_home_runs",
    "home runs": "batter_home_runs",
    "hr": "batter_home_runs",
    "batter_home_runs": "batter_home_runs",
    "rbis": "batter_rbis",
    "rbi": "batter_rbis",
    "batter_rbis": "batter_rbis",
    "runs": "batter_runs_scored",
    "runs_scored": "batter_runs_scored",
    "batter_runs_scored": "batter_runs_scored",
    "hits_runs_rbis": "batter_hits_runs_rbis",
    "batter_hits_runs_rbis": "batter_hits_runs_rbis",
    "strikeouts": "strikeouts",
    "pitcher_strikeouts": "strikeouts",
    "outs": "outs",
    "outs_recorded": "outs",
    "outs recorded": "outs",
    "pitcher_outs": "outs",
    "earned_runs": "earned_runs",
    "earned runs": "earned_runs",
    "pitcher_earned_runs": "earned_runs",
    "walks_allowed": "walks_allowed",
    "walks allowed": "walks_allowed",
    "pitcher_walks": "walks_allowed",
    "hits_allowed": "hits_allowed",
    "hits allowed": "hits_allowed",
    "pitcher_hits_allowed": "hits_allowed",
}

_BASKETBALL: dict[str, str] = {
    "pts": "player_points",
    "points": "player_points",
    "player_points": "player_points",
    "reb": "player_rebounds",
    "rebounds": "player_rebounds",
    "player_rebounds": "player_rebounds",
    "ast": "player_assists",
    "assists": "player_assists",
    "player_assists": "player_assists",
    "threes": "player_threes",
    "3pm": "player_threes",
    "player_threes": "player_threes",
    "pra": "player_points_rebounds_assists",
    "pr": "player_points_rebounds",
    "pa": "player_points_assists",
    "ra": "player_rebounds_assists",
    "player_points_rebounds_assists": "player_points_rebounds_assists",
    # The tail the counter was still reporting: 2 of 18 WNBA rows. Taken from
    # the markets the WNBA quote log actually carries (measured 2026-08-06:
    # player_points/rebounds/assists/threes/points_rebounds_assists/
    # points_rebounds/points_assists/double_double) plus the standard box-score
    # codes our rails emit, rather than from another production read -- the web
    # service began returning 502 under repeated dashboard rebuilds and is not
    # worth destabilising for a two-row lookup.
    "blk": "player_blocks",
    "blocks": "player_blocks",
    "stl": "player_steals",
    "steals": "player_steals",
    "to": "player_turnovers",
    "tov": "player_turnovers",
    "turnovers": "player_turnovers",
    "dd": "player_double_double",
    "double_double": "player_double_double",
    "double double": "player_double_double",
    "td": "player_triple_double",
    "triple_double": "player_triple_double",
    "triple double": "player_triple_double",
    "fg3m": "player_threes",
    "3s": "player_threes",
}

# Game-level markets are the same three words in every sport, which is why they
# are not per-sport. "ATS"/"run line"/"puck line" are the same wager as a spread.
_GAME: dict[str, str] = {
    "moneyline": "h2h",
    "money line": "h2h",
    "ml": "h2h",
    "h2h": "h2h",
    "spread": "spreads",
    "spreads": "spreads",
    "ats": "spreads",
    "run line": "spreads",
    "runline": "spreads",
    "puck line": "spreads",
    "puckline": "spreads",
    "total": "totals",
    "totals": "totals",
    "over/under": "totals",
    "ou": "totals",
}

_BY_SPORT: dict[str, dict[str, str]] = {
    "mlb": _MLB,
    "nba": _BASKETBALL,
    "wnba": _BASKETBALL,
}


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", " ").split())


def canonical_market_key(sport: Any, *values: Any) -> str | None:
    """First value that resolves to a canonical key, else None.

    Pass candidates in order of trustworthiness -- an explicit key first, a stat
    name after, and the display label LAST if at all. Returning None is a real
    answer: `validate()` reports it and the counter records it, which is how a
    gap stays visible instead of becoming a wrong join.
    """
    sport_map = _BY_SPORT.get(_normalize(sport), {})
    for value in values:
        token = _normalize(value)
        if not token:
            continue
        underscored = token.replace(" ", "_")
        for key in (token, underscored):
            if key in _GAME:
                return _GAME[key]
            if key in sport_map:
                return sport_map[key]
        # An unmapped value that already looks like an OddsAPI key (the feed's
        # own vocabulary, e.g. a market we do not have a label for yet) is
        # accepted as-is rather than dropped -- it will join, and refusing it
        # would lose a key we already have.
        if underscored.startswith(("batter_", "pitcher_", "player_")):
            return underscored
        # #247: strip a leading ROLE word and retry. Our boards label props by
        # role ("Hitter Hits", "Pitcher Outs") while graders and the odds feed
        # use the bare stat ("hits", "outs") -- and the table already holds the
        # bare form, so the role word was the only thing preventing the join.
        #
        # This is not cosmetic. `canonical_market_key("mlb", "Hitter Hits")`
        # returned None while `("mlb", "batter_hits")` returned batter_hits, so
        # the two sides of settlement could never agree on what market a bet was
        # in. Safe by construction: every role-stripped form either hits the
        # same entry the prefixed alias already pointed at ("batter_home_runs" ->
        # "home_runs" -> batter_home_runs) or nothing at all.
        head, _, tail = underscored.partition("_")
        if tail and head in {"hitter", "batter", "pitcher", "player"}:
            if tail in _GAME:
                return _GAME[tail]
            if tail in sport_map:
                return sport_map[tail]
    return None
