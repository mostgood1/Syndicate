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

import re
from datetime import datetime, timezone
from typing import Any, Mapping

_QUOTE_CACHE_KEY = "_quote_rows_cache"

# "Chelsea Gray OVER 1.5 3PM" -> "Chelsea Gray". Full words only: a bare O/U
# would risk clipping a real name.
_PICK_SUFFIX_RE = re.compile(r"\s+(?:OVER|UNDER)\s+[-+]?\d.*$", re.IGNORECASE)


def _player_identity(value: Any) -> str:
    """The PLAYER out of a field that may hold a whole display pick (#236).

    Identity is a hard filter in `quote_ref_for_bet` -- an exact normalized
    match on the player -- so a producer that writes the display string into
    the identity field does not merely look untidy, it makes the row
    unpriceable. Measured on production 2026-08-06: WNBA served 0 of 27 prop
    rows priced against a shard holding 2,615 prop quotes for 28 players,
    because every one of `player_name`/`entity`/`name`/`player` read
    "Chelsea Gray OVER 1.5 3PM" while the shard said "Chelsea Gray".

    This REPAIRS a known-malformed input shape; it does not loosen the match.
    The stripped name still has to be exactly right. The root cause is fixed at
    its producer (wnba/cards.py's `display_pick` fallback), but the same shape
    is cheap to emit from any sport, so the consumer defends itself too.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    return _PICK_SUFFIX_RE.sub("", text).strip() or text


def _implied_probability(price: Any) -> float | None:
    try:
        value = float(price)
    except Exception:
        return None
    if value == 0:
        return None
    return (100.0 / (value + 100.0)) if value > 0 else (abs(value) / (abs(value) + 100.0))


def _attach_board_score(row: dict[str, Any], quote: Mapping[str, Any]) -> None:
    """Stamp the blended board score and its components on a row (#243).

    Scoring only. The LANE comes from `opportunity_gate` (#245), which is the
    single place that decides eligibility and which runs again at serve time so
    its verdict cannot go stale in a cached pool.

    Never raises: a missing score costs a sort key, a raised exception costs the
    board.
    """
    try:
        from syndicate.features.shared.opportunity_signals import blended_score

        scored = blended_score(
            ev_pct=quote.get("ev_pct"),
            model_edge=row.get("model_edge_pct"),
            books_quoting=quote.get("books_quoting"),
            book_age_seconds=quote.get("book_age_seconds"),
        )
        # #245: the gate owns the lane. This used to compute its own
        # live/pregame/dead verdict here, which is exactly the pattern that made
        # ten fixes land in ten layers -- so it delegates now, and the same
        # function runs again at serve time so the answer cannot go stale.
        from syndicate.features.shared.opportunity_gate import annotate as gate_annotate

        gate_annotate(row, quote)
        if scored:
            row["board_score"] = scored.get("score")
            row["board_score_components"] = scored
    except Exception:
        return


def _model_edge_pct(model_prob: Any, fair_prob: Any) -> float | None:
    """The sim's disagreement with the de-vigged market, in points.

    Delegated to `opportunity_signals` so there is one definition; imported
    lazily because this module is on the request path and that one is not always
    needed. Never raises -- an enrichment that can break the board is worse than
    one that omits a field.
    """
    try:
        from syndicate.features.shared.opportunity_signals import model_edge_pct

        return model_edge_pct(model_prob, fair_prob)
    except Exception:
        return None


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


def _row_slate_date(row: Mapping[str, Any]) -> str | None:
    """The slate date this PROP ROW belongs to, from the row itself (#235).

    Prop rows carry no game dict, but they do carry their own date -- measured
    on production 2026-08-06, every unpriced board prop row had
    `game_date="2026-08-06"` and `context_label="2026-08-06"` while the caller
    was enriching a 3-day board window with a single date. Only an ISO date is
    accepted: `context_label` is "2026 Week 1" for NFL, and feeding that to a
    date-sharded lookup is how a lane reads an empty shard forever.
    """
    for key in ("game_date", "slate_date", "date", "commence_time", "start_time_utc", "game_time_utc", "context_label"):
        value = str(row.get(key) or "").strip()
        if len(value) >= 10 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10]):
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
    # #238: the no-vig fair value. Named `..._vs_fair` on the flattened row so
    # it can never be confused with the legacy `ev_pct`, which was computed
    # against a VIGGED price and read systematically low by about half the hold.
    ("fair_price", "fair_price"),
    ("fair_probability", "fair_probability"),
    ("hold_pct", "hold_pct"),
    ("ev_vs_fair_pct", "ev_pct"),
    ("best_ev_vs_fair_pct", "best_ev_pct"),
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
                # Same display-string-as-identity repair as enrich_prop_rows:
                # WNBA's candidates carry the whole pick here too.
                player_name=_player_identity(candidate.get("player_name") or candidate.get("entity")) or None,
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

            # #231: re-price the EDGE against best available, here rather than in
            # a second enrichment pass over the raw rows. This is what let the
            # third call site go away: previously enrich_recommendation_rows had
            # to run BEFORE _append_game_bet_candidate purely so the recomputed
            # ev_pct would be read into `edge`, which meant enriching the same
            # data twice at two different stages.
            #
            # `edge` on a finished candidate is DISPLAY TEXT ("3.2%"), not a
            # number, so it is formatted the same way _pct_text does it. The
            # numeric model probability is kept alongside on the candidate, which
            # is what makes recomputing possible at all this late.
            model_probability = _model_probability(candidate)
            # #238: measure the model against the NO-VIG fair probability when
            # the opposing side was available. Against `best_implied` -- which
            # still carries the book's margin -- the sim was made to look
            # systematically pessimistic by roughly half the hold (measured
            # median 6.25%, so ~3.1 points on a typical market). That is not a
            # cosmetic difference: it is the difference between a row clearing
            # an edge threshold and being dropped.
            fair_probability = quote.get("fair_probability")
            if model_probability is not None and fair_probability is not None:
                candidate["model_edge_pct"] = _model_edge_pct(model_probability, fair_probability)
                edge_value = (model_probability - float(fair_probability)) * 100.0
                candidate["edge"] = f"{edge_value:.1f}%"
                candidate["edge_priced_against"] = "no_vig_fair"
                candidate["ev_priced_against"] = quote.get("best_bookmaker")
            elif model_probability is not None and best_implied is not None:
                # No opposing side, so no fair price exists. Kept, but labelled,
                # because a vigged edge silently mixed in with fair ones would be
                # a number nobody could interpret.
                edge_value = (model_probability - best_implied) * 100.0
                candidate["edge"] = f"{edge_value:.1f}%"
                candidate["edge_priced_against"] = "vigged_best_price"
                candidate["ev_priced_against"] = quote.get("best_bookmaker")
            # Scored LAST on this path: the sim component reads
            # `model_edge_pct`, which the block above has only just written.
            _attach_board_score(candidate, quote)
    except Exception:
        return candidates
    return candidates


def enrich_prop_rows(
    rows: list[dict[str, Any]],
    *,
    date_str: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Attach price context to PROP DASHBOARD rows.

    Props reach the board through an entirely separate lane from game bets --
    `_build_prop_dashboard_row` over each sport's `home_rails`/`props_bar`
    items -- which never passes through `_game_bet_candidates_from_game` and so
    never saw enrichment. Traced from production 2026-08-06:
    `command_center/top_game_bets` had 5 of 12 quotes while
    `command_center/top_props` and every `home_rails` lane had 0 of 14/28/9.

    These rows carry no game dict, so there are no teams and no game date --
    but they DO carry `player_name`, which `quote_ref_for_bet` accepts as a
    full identity signal in its own right. A player is unique to one game on a
    given slate, so this is a sound join, not a loosening: a prop row still
    cannot pick up an unrelated game's price.

    `sport_slug` comes off each row rather than a parameter, because this lane
    mixes sports in a single list.

    So does the DATE, for the same reason and a sharper one (#235). The quote
    log is sharded by date, and `date_str` is a single value for a list that
    spans a whole board window -- production served `dates_covered`
    ["2026-08-06", "2026-08-07", "2026-08-08"] in one payload. One window date
    applied to every row reads the wrong (often nonexistent) shard and returns
    nothing, uniformly, which is exactly what "0 of 12 pregame and 0 of 7 live
    priced" looked like while the same players on the same slate priced fine on
    the game lane. That lane was immune because `enrich_candidate_rows` takes
    the date from each GAME dict rather than from a caller-wide parameter.
    `date_str` stays as the fallback for rows that carry no date of their own.
    """
    if not rows:
        return rows
    try:
        from syndicate.features.shared.odds_book_quotes import quote_ref_for_bet

        now = now or datetime.now(timezone.utc)
        for row in rows:
            if not isinstance(row, dict) or row.get("quote"):
                continue
            player = _player_identity(
                row.get("player_name") or row.get("entity") or row.get("player")
            )
            if not str(player or "").strip():
                # Without a player there is no identity signal at all here, and
                # guessing from the market alone would attach some other
                # player's price.
                continue
            sport_slug = str(row.get("sport_slug") or row.get("sport") or "").strip().lower()
            if not sport_slug:
                continue
            quote = quote_ref_for_bet(
                sport=sport_slug,
                date_str=_row_slate_date(row) or date_str,
                # Canonical key first: "batter_total_bases" joins, the display
                # string "Total Bases" does not. Market stays a SOFT narrowing
                # signal either way, so a sport with no canonical key still
                # matches on player identity.
                market=row.get("market_key") or row.get("market"),
                selection=row.get("pick") or row.get("selection"),
                line=row.get("line"),
                player_name=player,
                now=now,
            )
            if not quote:
                continue
            row["quote"] = quote
            for flat_key, quote_key in _FLAT_QUOTE_FIELDS:
                row[flat_key] = quote.get(quote_key)
            best_implied = _implied_probability(quote.get("best_price"))
            shown_implied = _implied_probability(row.get("odds"))
            if best_implied is not None and shown_implied is not None:
                row["price_improvement_pct"] = round((shown_implied - best_implied) * 100.0, 2)
            _attach_board_score(row, quote)
    except Exception:
        return rows
    return rows
