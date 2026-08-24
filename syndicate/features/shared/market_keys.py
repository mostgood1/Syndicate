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

# --------------------------------------------------------------------------
# PERIODS AND ALTERNATES, added 2026-08-24.
#
# Kalshi lists a game's intervals as their own series -- `KXWNBA1QTOTAL`
# ("1st Quarter Total"), `KXWNBA2HSPREAD` ("2nd Half Spread"), `KXWNBA2H`
# ("2nd Half Winner") -- and the board already carries the matching keys
# (`totals_q1`, `spreads_h2`, `h2h_h2`). Nothing joined them because the
# vocabulary stopped at the full-game words.
#
# SUFFIXES ARE THE BOARD'S, NOT INVENTED: q1..q4 quarters, h1/h2 halves,
# p1..p3 hockey periods, `_alt` for alternate lines. All are already in use in
# this repo, which is what makes them the right spelling -- a period key that
# only Kalshi's side understands joins to nothing.
_PERIOD_SUFFIX: dict[str, str] = {
    "1st quarter": "q1", "first quarter": "q1", "1q": "q1", "q1": "q1",
    "2nd quarter": "q2", "second quarter": "q2", "2q": "q2", "q2": "q2",
    "3rd quarter": "q3", "third quarter": "q3", "3q": "q3", "q3": "q3",
    "4th quarter": "q4", "fourth quarter": "q4", "4q": "q4", "q4": "q4",
    "1st half": "h1", "first half": "h1", "1h": "h1", "h1": "h1",
    "2nd half": "h2", "second half": "h2", "2h": "h2", "h2": "h2",
    "1st period": "p1", "first period": "p1", "p1": "p1",
    "2nd period": "p2", "second period": "p2", "p2": "p2",
    "3rd period": "p3", "third period": "p3", "p3": "p3",
}

# The market word, once the period has been stripped off the front.
_GAME_CORE: dict[str, str] = {
    "winner": "h2h",
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


def canonical_game_market(text: Any) -> str | None:
    """A game-line market name, period and alternate included, or None.

    Separate from `canonical_market_key` because the grammar is different: this
    one PARSES rather than looks up, since "2nd Half Spread" is a period and a
    market word rather than a phrase any table could enumerate.

    None is a real answer and the caller must refuse on it. A game line joined
    to the wrong period is the same class of error as one joined to the wrong
    game -- a confidently-priced bet on something else entirely.
    """
    token = _normalize(text)
    if not token:
        return None

    alt = False
    for marker in ("alternate ", "alt "):
        if token.startswith(marker):
            alt, token = True, token[len(marker):].strip()
    for marker in (" alternate", " alt"):
        if token.endswith(marker):
            alt, token = True, token[: -len(marker)].strip()

    # THREE-WAY IS ITS OWN MARKET, not a moneyline with a footnote. A draw is a
    # third outcome, so pricing it as `h2h` would misstate every soccer line.
    three_way = False
    for marker in ("3 way", "three way", "3way"):
        if marker in token:
            three_way = True
            token = token.replace(marker, " ").strip()

    period = ""
    for phrase, suffix in _PERIOD_SUFFIX.items():
        if token.startswith(phrase + " "):
            period, token = suffix, token[len(phrase):].strip()
            break

    core = _GAME_CORE.get(token)
    if core is None:
        return None
    if three_way:
        # Only a moneyline has a three-way form.
        return "h2h_3_way" if core == "h2h" and not period else None
    if period:
        # `_alt` and a period together are not a shape the board carries, so it
        # is refused rather than spelled into existence.
        return None if alt else f"{core}_{period}"
    return f"{core}_alt" if alt else core


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

# --------------------------------------------------------------------------
# FOOTBALL and SOCCER, added 2026-08-24 to open Kalshi beyond MLB/WNBA.
#
# Until now only mlb/nba/wnba had any vocabulary here, which is why the Kalshi
# boot census read `KALSHI_SPORT NFL ticker_substring_n=317 classified_n=0`:
# 317 NFL series listed and not one classified. `auto_series_from_catalogue`
# requires `canonical_market_key(sport, stat)` to resolve before it will
# register a series, so a sport with no map can never discover anything however
# player-shaped its titles are. The gap was in this file, not in the discovery.
#
# The VALUES are OddsAPI's keys, because that is what the board emits and the
# join compares against -- taken from what the repo already uses
# (`player_pass_yds`, `player_reception_yds`, `player_anytime_td`), never
# invented here. The KEYS are the stat wordings a title might carry; Kalshi's
# exact wording is reported by `prop_candidates` rather than assumed, and any
# spelling this table misses shows up there as an unmapped stat instead of
# silently joining to the wrong market.
_FOOTBALL: dict[str, str] = {
    "passing yards": "player_pass_yds",
    "pass yards": "player_pass_yds",
    "pass yds": "player_pass_yds",
    "passing touchdowns": "player_pass_tds",
    "passing tds": "player_pass_tds",
    "pass tds": "player_pass_tds",
    "passing attempts": "player_pass_attempts",
    "pass attempts": "player_pass_attempts",
    "passing completions": "player_pass_completions",
    "completions": "player_pass_completions",
    "interceptions thrown": "player_pass_interceptions",
    "passing interceptions": "player_pass_interceptions",
    "rushing yards": "player_rush_yds",
    "rush yards": "player_rush_yds",
    "rush yds": "player_rush_yds",
    "rushing attempts": "player_rush_attempts",
    "rush attempts": "player_rush_attempts",
    "carries": "player_rush_attempts",
    "receiving yards": "player_reception_yds",
    "reception yards": "player_reception_yds",
    "reception yds": "player_reception_yds",
    "receptions": "player_receptions",
    "catches": "player_receptions",
    "touchdowns": "player_anytime_td",
    "anytime touchdown": "player_anytime_td",
    "anytime td": "player_anytime_td",
    "touchdown": "player_anytime_td",
}

_SOCCER: dict[str, str] = {
    "goals": "player_goals",
    "goal": "player_goals",
    "anytime goalscorer": "player_goal_scorer_anytime",
    "goalscorer": "player_goal_scorer_anytime",
    "to score": "player_goal_scorer_anytime",
    "assists": "player_assists",
    "shots": "player_shots",
    "shots on target": "player_shots_on_target",
    "shots on goal": "player_shots_on_goal",
}

_BY_SPORT: dict[str, dict[str, str]] = {
    "mlb": _MLB,
    "nba": _BASKETBALL,
    "wnba": _BASKETBALL,
    # NCAAF shares the football vocabulary. The STATS are identical; only the
    # rosters differ, and rosters are not this table's concern.
    "nfl": _FOOTBALL,
    "ncaaf": _FOOTBALL,
    "soccer": _SOCCER,
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
        # GAME-LINE SPELLINGS TOO. `totals_1st_5_innings` and
        # `spreads_1st_5_innings` are the board's own keys, produced by
        # `canonical_game_market`, and the prop-only passthrough refused them --
        # so a period market the parser had just resolved correctly came back
        # `stat_not_in_market_vocabulary` one step later.
        if underscored.startswith(("totals", "spreads", "h2h", "team_totals")):
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
