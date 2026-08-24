"""Resolve an MLB bet's CURRENT value from the live game feed.

The resolver `bet_status` takes as an injection. It answers one question --
"what is the thing this bet is on worth right now" -- and leaves every judgement
about winning, losing and decided to `resolve_bet_status`, which is where the
monotonicity rules live.

**IT READS THE LIVE FEED, NOT A FINAL ONE.** `box_score_stats.final_stat_value`
is named for its original caller (settlement) but is a pure function over a
`feed/live` payload, and an in-progress game's payload has exactly the same
boxscore shape as a finished one. So the same tested reader serves both, and
there is no second copy of MLB's stat-name vocabulary to drift.

**NO SYNCHRONOUS FETCH.** `load_final_feed` will hit statsapi.mlb.com when the
cache misses; this passes `fetch_if_missing=False`. The refresh worker already
captures `feed_live` on its own cadence, and a per-bet network call inside the
board build would put a live HTTP dependency in the middle of the artifact
pipeline -- which is the shape `#506` removed from the web service (15 live
statsapi calls per request, 3318-8400ms). A missing feed is a NAMED absence
here, not something to go and fetch.

**MARKET NAMES ARE MAPPED EXPLICITLY.** The board's market vocabulary
(`batter_total_bases`) and the box score's stat vocabulary (`total_bases`) are
different namespaces that happen to look similar. Stripping a `batter_` prefix
would work until it met `batter_hits_runs_rbis`, so every market is listed.
An unmapped market is refused by name rather than guessed at.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["mlb_status_resolver"]

REASON_NO_GAME_PK = "no_game_pk"
REASON_NO_FEED = "no_live_feed"
REASON_UNMAPPED_MARKET = "unmapped_market"
REASON_NO_STAT = "stat_not_in_feed"
# The order names teams the schedule does not. Distinct from `no_game_pk`,
# which now means "and we could not recover one from the matchup either".
REASON_NO_SCHEDULE = "no_schedule_for_date"
REASON_NO_TEAM_MATCH = "matchup_not_on_schedule"
# The ORDER names no teams (or names ones the alias map cannot read). Split from
# the above because they need opposite fixes: this one means the ledger record
# is too thin to recover from, that one means the schedule or the names
# disagree. Orders written before `home_team` joined `_LEAN_FIELDS` land here,
# and lumping them together would hide exactly how much of the backlog is
# recoverable.
REASON_NO_MATCHUP_ON_ORDER = "no_matchup_on_order"
# NOT AN MLB BET. Checked first, because every refusal below is phrased as a
# statement about MLB data and would be a lie about a soccer order: a Liverpool
# match run through `canonical_team("mlb", ...)` returns None and would have
# been reported as `no_matchup_on_order`, i.e. "the ledger record is too thin"
# -- which is false, and would have sent the next fix at the wrong problem.
REASON_NOT_MLB = "not_an_mlb_order"
# TWO games, same teams, same day. Refused rather than picked: a doubleheader
# graded against the wrong half is a confident wrong verdict, and the two games
# routinely disagree.
REASON_AMBIGUOUS = "ambiguous_doubleheader"

# board market -> (group, box-score stat name)
# KEYED ON THE CANONICAL MARKET NAME, and looked up through
# `market_keys.canonical_market_key` -- never on the raw string.
#
# This table read `pitcher_strikeouts` and `pitcher_outs` until 2026-08-23. The
# board emits `strikeouts` and `outs` (`#224`), so every MLB PITCHER PROP
# resolved to `unmapped_market` and could never be graded at all -- the fourth
# instance of the same vocabulary drift found in one day, and the one that would
# have made the settlement figures quietly hitter-only.
#
# `canonical_market_key` accepts both spellings, so the lookup below absorbs
# whichever the caller has. That is the fix; a longer list would not have been.
_MARKET_TO_STAT: dict[str, tuple[str, str]] = {
    "batter_hits": ("hitter", "hits"),
    "batter_total_bases": ("hitter", "total_bases"),
    "batter_home_runs": ("hitter", "home_runs"),
    "batter_rbis": ("hitter", "rbi"),
    "batter_runs_scored": ("hitter", "runs"),
    "batter_hits_runs_rbis": ("hitter", "hits_runs_rbis"),
    "strikeouts": ("pitcher", "strikeouts"),
    "hits_allowed": ("pitcher", "hits_allowed"),
    "earned_runs": ("pitcher", "earned_runs"),
    "walks_allowed": ("pitcher", "walks_allowed"),
    "outs": ("pitcher", "outs"),
}


def _stat_for_market(market: str) -> tuple[str, str] | None:
    """The box-score stat for a board market, in either spelling."""
    from syndicate.features.shared.market_keys import canonical_market_key

    canonical = canonical_market_key("mlb", market) or market
    return _MARKET_TO_STAT.get(canonical)

# Markets resolved from the SCOREBOARD rather than a player's line.
_GAME_TOTAL_MARKETS = frozenset({"totals", "totals_alt"})


def _schedule_index(selected_date: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """StatsAPI's slate for a date, keyed by canonical (home, away).

    WHY THIS EXISTS. Every order in the ledger resolved to `no_game_pk` --
    58 of 58 on 2026-08-22 and 45 of 45 on 2026-08-23. The board row's
    `game_pk` is set to `row.get("event_id")`, which is the ODDSAPI HASH, not
    StatsAPI's numeric id; `intelligence_contracts` already documents the two id
    spaces as different ("MLB board rows carry a StatsAPI gamePk while quotes
    carry an OddsAPI hash"). `int()` cannot parse a hash, so every bet was
    unidentifiable and nothing could ever be graded.

    The matchup is the recovery path the contracts dataclass already names:
    the ledger carries `home_team`, `away_team` and `commence_time` on every
    record, so this fixes the orders ALREADY WRITTEN rather than only the ones
    written from now on. No backfill.

    Team names go through `team_aliases.canonical_team`, not a private map --
    four separate market-name tables drifted apart in this codebase in one day
    and a fifth for teams would be the same mistake.
    """
    from syndicate.features.shared.team_aliases import canonical_team

    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    try:
        # Imported inside the guard, not beside it: `mlb.cards` is a 5,700-line
        # module and an import failure here must degrade to `no_schedule_for_date`
        # rather than take down grading for every other sport in the same run.
        from syndicate.features.mlb.cards import _schedule_raw_games

        games = _schedule_raw_games(selected_date)
    except Exception:
        return index

    for game in games:
        teams = game.get("teams") if isinstance(game.get("teams"), Mapping) else {}
        home = ((teams.get("home") or {}).get("team") or {}).get("name")
        away = ((teams.get("away") or {}).get("team") or {}).get("name")
        game_pk = _int_or_none(game.get("gamePk"))
        home_key = canonical_team("mlb", home)
        away_key = canonical_team("mlb", away)
        if game_pk is None or not home_key or not away_key:
            continue
        index.setdefault((home_key, away_key), []).append(
            {"game_pk": game_pk, "game_date": game.get("gameDate")}
        )
    return index


def _parse_stamp(value: Any):
    from datetime import datetime, timezone

    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _resolve_game_pk(
    order: Mapping[str, Any], index: Mapping[tuple[str, str], list[dict[str, Any]]]
) -> tuple[int | None, str | None]:
    """The order's StatsAPI gamePk, or a NAMED reason there isn't one."""
    from syndicate.features.shared.team_aliases import canonical_team

    # FAST PATH: a genuinely numeric id on the record. Kept first so orders
    # written once the upstream stamps a real gamePk cost no schedule lookup.
    direct = _int_or_none(order.get("game_pk"))
    if direct is not None:
        return direct, None

    if not index:
        return None, REASON_NO_SCHEDULE

    home = canonical_team("mlb", order.get("home_team"))
    away = canonical_team("mlb", order.get("away_team"))
    if not home or not away:
        return None, REASON_NO_MATCHUP_ON_ORDER

    candidates = index.get((home, away))
    if not candidates:
        return None, REASON_NO_TEAM_MATCH
    if len(candidates) == 1:
        return candidates[0]["game_pk"], None

    # DOUBLEHEADER. Disambiguated by start time, and only when the order carries
    # one -- picking a half at random is a confident wrong verdict, and the two
    # games of a doubleheader routinely disagree.
    commence = _parse_stamp(order.get("commence_time"))
    if commence is None:
        return None, REASON_AMBIGUOUS
    scored = []
    for candidate in candidates:
        stamp = _parse_stamp(candidate.get("game_date"))
        if stamp is None:
            continue
        scored.append((abs((stamp - commence).total_seconds()), candidate["game_pk"]))
    if not scored:
        return None, REASON_AMBIGUOUS
    scored.sort()
    # Within an hour, or we are guessing. The two halves of a doubleheader are
    # normally 3+ hours apart, so a near-miss here means the matchup matched
    # something else entirely.
    if scored[0][0] > 3600:
        return None, REASON_AMBIGUOUS
    return scored[0][1], None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _game_is_final(feed: Mapping[str, Any]) -> bool:
    state = (
        ((feed.get("gameData") or {}).get("status") or {}).get("abstractGameState")
    )
    return str(state or "").strip().lower() == "final"


def _game_has_started(feed: Mapping[str, Any]) -> bool:
    state = (
        ((feed.get("gameData") or {}).get("status") or {}).get("abstractGameState")
    )
    return str(state or "").strip().lower() in {"live", "final"}


def _team_runs(feed: Mapping[str, Any]) -> tuple[float, float] | None:
    """(home, away) runs, or None if either is missing.

    Both or neither: a half-known score is not a score, and a missing away
    total read as zero is a shutout that did not happen.
    """
    linescore = (feed.get("liveData") or {}).get("linescore") or {}
    teams = linescore.get("teams") or {}
    home = (teams.get("home") or {}).get("runs")
    away = (teams.get("away") or {}).get("runs")
    if home is None or away is None:
        return None
    try:
        return float(home), float(away)
    except (TypeError, ValueError):
        return None


def _feed_team_names(feed: Mapping[str, Any]) -> tuple[Any, Any]:
    """(home, away) as the FEED names them.

    Taken from the feed rather than from the order, deliberately. The order's
    `home_team`/`away_team` came from the odds provider and are what the
    schedule join already matched on -- but the SCORES come from this payload,
    and pairing a score with a name from a different source is how a game gets
    graded backwards. The two names travel with the two numbers.
    """
    teams = (feed.get("gameData") or {}).get("teams") or {}
    return (
        (teams.get("home") or {}).get("name"),
        (teams.get("away") or {}).get("name"),
    )


def _combined_score(feed: Mapping[str, Any]) -> float | None:
    linescore = (feed.get("liveData") or {}).get("linescore") or {}
    teams = linescore.get("teams") or {}
    home = ((teams.get("home") or {}).get("runs"))
    away = ((teams.get("away") or {}).get("runs"))
    if home is None or away is None:
        return None
    try:
        return float(home) + float(away)
    except (TypeError, ValueError):
        return None


def mlb_status_resolver(selected_date: str):
    """Build a resolver bound to one slate date.

    Feeds are cached per game for the life of the returned closure: a slate has
    far more bets than games, and re-reading (and gunzipping) the same payload
    once per bet is the kind of quiet cost that turns a diagnostic into a
    reason the board build got slower.
    """
    from syndicate.features.mlb.box_score_stats import final_stat_value, load_final_feed
    from syndicate.features.shared.game_line_bet import game_line_view, is_game_line_market

    # Built ONCE per resolver, on first use. Reading the schedule file per order
    # would turn a 58-order settle into 58 file reads for one unchanging answer.
    _schedule_cache: dict[str, Any] = {}

    def schedule():
        if "index" not in _schedule_cache:
            _schedule_cache["index"] = _schedule_index(selected_date)
        return _schedule_cache["index"]

    cache: dict[int, Mapping[str, Any] | None] = {}

    def _feed(game_pk: int) -> Mapping[str, Any] | None:
        if game_pk not in cache:
            try:
                # fetch_if_missing=False -- see the module docstring.
                cache[game_pk] = load_final_feed(
                    selected_date, game_pk, fetch_if_missing=False
                )
            except Exception:
                cache[game_pk] = None
        return cache[game_pk]

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        # SPORT FIRST. This resolver is handed every order in the ledger, and a
        # non-MLB one is not a defect in anything -- it just needs a different
        # resolver that does not exist yet. Saying so plainly keeps the ungraded
        # counts readable as a work list.
        if str(order.get("sport") or "").strip().lower() not in {"mlb", ""}:
            return {"unavailable_reason": REASON_NOT_MLB}

        game_pk, reason = _resolve_game_pk(order, schedule())
        if game_pk is None:
            return {"unavailable_reason": reason or REASON_NO_GAME_PK}

        # THE MARKET CHECK RUNS BEFORE THE FEED LOOKUP, and the ordering is the
        # whole point. "We have no stat for this market" is PERMANENT -- it will
        # be true after the game ends, tomorrow, and forever. "The feed is not
        # cached yet" is TEMPORARY and resolves on its own.
        #
        # Checked feed-first, the temporary reason swallows the permanent one:
        # today's line read `no_live_feed: 50` while an unknown share of those
        # 50 could never grade at all, so "50 bets pending" and "50 bets we can
        # track" looked identical. That is the same ordering mistake the Kalshi
        # join made this morning with its date guard, in a second place.
        #
        # Answering "is everything on this slate trackable" needs the permanent
        # blockers counted BEFORE kickoff, not discovered after it.
        market = str(order.get("market") or "").strip().lower()
        is_game_total = market in _GAME_TOTAL_MARKETS
        # SPREADS AND MONEYLINES ARE SCOREBOARD BETS, not player lines. They
        # refused with `unmapped_market` until 2026-08-24 -- 41 spreads, 31
        # h2h and 2 spreads_alt on a single slate, permanently ungraded --
        # because the lookup below only ever knew player stats.
        is_game_line = is_game_line_market("mlb", market)
        mapped = None if (is_game_total or is_game_line) else _stat_for_market(market)
        if not (is_game_total or is_game_line) and mapped is None:
            # Every prop family not listed. Named rather than guessed -- a
            # wrong stat produces a confident wrong verdict.
            return {"unavailable_reason": REASON_UNMAPPED_MARKET}

        feed = _feed(game_pk)
        if not isinstance(feed, Mapping) or not feed:
            return {"unavailable_reason": REASON_NO_FEED}

        started = _game_has_started(feed)
        is_final = _game_is_final(feed)

        if is_game_total:
            total = _combined_score(feed)
            if total is None:
                return {"unavailable_reason": REASON_NO_STAT}
            return {"current_value": total, "is_final": is_final, "started": started}

        if is_game_line:
            runs = _team_runs(feed)
            if runs is None:
                return {"unavailable_reason": REASON_NO_STAT}
            home_runs, away_runs = runs
            home_name, away_name = _feed_team_names(feed)
            view = game_line_view(
                sport="mlb",
                market=market,
                side=order.get("side"),
                line=order.get("line"),
                home_team=home_name,
                away_team=away_name,
                home_score=home_runs,
                away_score=away_runs,
                # BASEBALL DOES NOT DRAW. A regulation game plays until someone
                # is ahead, so a moneyline here is two-way and a level score is
                # a push rather than a loss. Passed explicitly rather than
                # inferred from the market name, because production shows
                # soccer using the SAME name (`h2h`) three-way.
                draw_possible=False,
            )
            if view.get("unavailable_reason"):
                return view
            # `side` and `line` are RESTATED for the grader -- see
            # `paper_settlement`. The order still records what was bet.
            return {
                "current_value": view["current_value"],
                "side": view["side"],
                "line": view["line"],
                "is_final": is_final,
                "started": started,
            }

        group, stat = mapped
        value = final_stat_value(
            dict(feed),
            group=group,
            stat=stat,
            player_name=str(order.get("player_name") or ""),
        )
        if value is None:
            # The player has not recorded this stat yet, OR the name did not
            # match. Those are different and this cannot tell them apart, so it
            # does NOT default to 0 -- a bet reported as "0 hits, Under is fine"
            # when we simply failed to find the player is the worst possible
            # wrong answer.
            return {"unavailable_reason": REASON_NO_STAT}

        return {"current_value": value, "is_final": is_final, "started": started}

    return resolve
