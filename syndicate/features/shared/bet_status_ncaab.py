"""Resolve a men's college basketball (NCAAB) bet's CURRENT value from ESPN's scoreboard.

The sibling of `bet_status_nba` / `_ncaaf` / `_nhl`, and the same contract: it answers
"what is the thing this bet is on worth right now" and leaves every judgement about
winning and losing to `bet_status.resolve_bet_status`.

Until this existed `paper_settlement._default_resolver` had no `ncaab` entry, and every
NCAAB paper order read `no_resolver_for_ncaab` forever (measured on the fleet
2026-11-02 ~19:3xZ, opening day: both NCAAB orders in the book carried it). The women's
game (`bet_status_wncaab`) runs through the SAME code below with its own league table;
the only differences are the ESPN path and the periods.

--------------------------------------------------------------------------
THE FEED: ESPN'S SCOREBOARD, AND `groups=50` IS NOT OPTIONAL
--------------------------------------------------------------------------

    GET site.api.espn.com/apis/site/v2/sports/basketball/<path>/scoreboard
        ?dates=YYYYMMDD&groups=50&limit=500

Without `groups=50` (ESPN's Division I filter) the college scoreboard returns a small
featured subset. Measured 2026-11-02: men's 18 events without it, 182 with it; women's
16 without, 164 with. A resolver reading the bare scoreboard would refuse most games as
"not on the scoreboard" -- a gap that looks like a feed outage. `limit=500` holds the
largest slate (`ncaab/slate.py` fetches the same URL for the board).

Each event carries what settlement needs and nothing is read per game:
`status.type.{state, completed, name}`, `status.period`, and per competitor `score` and
`linescores[{value, period}]` -- one entry per period played, overtime periods appended
(2026-03-01 men's 401828251: three entries, the third an OT; women's 401824559: five).

One scoreboard read per capture date per resolver, at most -- never per order. A game
whose `commence_time` is still in the future reads `not started` WITHOUT a read, so
`portfolio_commit`'s per-tick resolve does not fetch a slate that has not tipped.

--------------------------------------------------------------------------
THE JOIN
--------------------------------------------------------------------------

`event_id` is OddsAPI's hash and addresses nothing on ESPN, so the game is found by the
TEAM PAIR on the kickoff's US-Eastern date(s) (`bet_status_nfl.order_capture_dates`).
Both sides of the ORDER and both ESPN competitors go through
`team_aliases.canonical_team(<sport>, ...)`, the registry-backed map whose canonical
value is the SCHOOL and which DROPS ambiguous tokens ("Bulldogs" names 14 schools and
resolves to None). Never `teams_match`: its prefix heuristic joins "Michigan" to
"Michigan State" (`bet_status_ncaaf` measured it).

  * The ESPN side resolves from ESPN's own display names, every form that resolves
    required to agree (`population_outcomes_espn`'s rule, the scorecard's join). The
    registry IS ESPN's team list, so this is ESPN's team id by another route: measured
    2026-11-02 on the men's slate, all 119 D1-vs-D1 games resolved both sides to the
    same school the registry gives their ESPN team id, 0 conflicting forms.
  * Both order sides must resolve, to DIFFERENT schools, or the order refuses as
    `<sport>_team_not_in_registry_or_ambiguous` -- a registry gap, which is a different
    job from a game missing off the scoreboard.
  * The pair is matched UNORDERED, then oriented by school. At a NEUTRAL SITE "home" is a
    label each vendor assigns and ESPN and OddsAPI disagree (`ncaab/slate.py` measured 6
    of 119 on 11-02). A positional `home` bet is the ODDS FEED's home team, so the scores
    are handed to `game_line_view` in the ORDER's orientation; `matched_by` says when they
    were swapped.
  * One pair twice on a date refuses both as ambiguous.

--------------------------------------------------------------------------
STATE, AND WHAT IS NEVER GRADED
--------------------------------------------------------------------------

`status.type.completed` is the authority for final. `state == "post"` without
`completed` is a postponed, cancelled or suspended game: it refuses by name
(`<sport>_game_not_completed:<STATUS_NAME>`) and never grades off a 0-0. A full-game
total reports its live sum in play (points only rise, so `resolve_bet_status` may decide
an over early, as for every other sport); spreads and moneylines decide at the final.

A THREE-WAY moneyline settles on regulation and the final score includes overtime, so
`h2h_3_way` refuses rather than grading a tie-after-regulation as the OT winner's.
Player props refuse permanently: nothing here reads a box score.

--------------------------------------------------------------------------
SEGMENTS: HALVES FOR MEN, QUARTERS FOR WOMEN, GRADED AT THE FINAL
--------------------------------------------------------------------------

    ncaab    h1 = period 1, h2 = period 2               (two 20-minute halves)
    wncaab   q1..q4 = that period, h1 = 1+2, h2 = 3+4   (four 10-minute quarters)

A segment grades from the per-period linescores of a COMPLETED game, the way
`bet_status_nba` grades off the completed-game linescore file. In play it refuses as
`<sport>_segment_waits_for_final`; the bet is decided by the final either way. Before
grading, each side's linescores must sum to its final score: a linescore short a period
is a smaller number that looks real.

OVERTIME IS THE BOOK'S RULE. A segment ending at the last regulation period (men's `h2`,
women's `q4` and `h2`) takes the overtime periods or not per `bet_status_nba
._OVERTIME_RULES`, the per-book table read 2026-10-29 from each book's house rules. None
of the quoted sentences names a league -- they are the books' basketball period rules
(DraftKings: "4th Quarter Markets and 2nd Half Markets include overtime"; FanDuel,
BetMGM, Pinnacle: quarters exclude it, the second half includes it). A book not in the
table grades only a game with no overtime, where every rule agrees; with overtime it
refuses as `<sport>_overtime_rule_unread:<book>`. Bovada -- the book on both 11-02 NCAAB
paper orders -- is not in it yet.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from syndicate.features.shared.bet_status import FULL_GAME_SEGMENT
from syndicate.features.shared.segment_actuals import (
    REASON_SEGMENT_ACTUAL_PREFIX,
    REASON_UNSUPPORTED_SEGMENT_PREFIX,
    order_segment,
    segment_scores_view,
)

__all__ = [
    "CollegeBasketballLeague",
    "NCAAB",
    "college_basketball_status_resolver",
    "ncaab_status_resolver",
    "scoreboard_url",
]

# Sport-free reasons. The rest are per league, `<sport>_...`, built in `_Reasons` -- an
# unprefixed reason shared by two resolvers cannot say which one produced it
# (`bet_status_ncaaf.REASON_NO_SCORES` has the measured case).
REASON_UNMAPPED_MARKET = "unmapped_market"
REASON_NO_MATCHUP = "no_home_away_teams_on_order"

_TOTAL_MARKETS = frozenset({"totals", "totals_alt"})
_THREE_WAY_MARKETS = frozenset({"h2h_3_way"})

_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/{path}/scoreboard"
    "?dates={compact}&groups=50&limit=500"
)


@dataclass(frozen=True)
class CollegeBasketballLeague:
    """One college basketball league: its sport slug, ESPN path and periods.

    `segments` maps each segment to its REGULATION periods; overtime is added per book
    (module docstring) to a segment that ends at the last regulation period."""

    sport: str
    espn_path: str
    regulation_periods: int
    segments: Mapping[str, tuple[int, ...]]


NCAAB = CollegeBasketballLeague(
    sport="ncaab",
    espn_path="mens-college-basketball",
    regulation_periods=2,
    segments={"h1": (1,), "h2": (2,)},
)


def scoreboard_url(league: CollegeBasketballLeague, capture_date: str) -> str:
    return _SCOREBOARD_URL.format(path=league.espn_path, compact=str(capture_date).replace("-", ""))


class _Reasons:
    """The league's own refusal strings, so a counter names the resolver that wrote it."""

    def __init__(self, sport: str) -> None:
        self.not_this_sport = f"not_an_{sport}_order"
        self.team_unresolved = f"{sport}_team_not_in_registry_or_ambiguous"
        self.no_scoreboard = f"no_{sport}_scoreboard_for_date"
        self.game_not_found = f"game_not_in_{sport}_scoreboard"
        self.ambiguous = f"matchup_twice_in_{sport}_scoreboard"
        self.not_completed = f"{sport}_game_not_completed:"
        self.no_scores = f"{sport}_game_carries_no_scores"
        self.props = f"{sport}_props_not_graded"
        self.three_way = f"{sport}_three_way_needs_regulation_score"
        self.segment_waits = f"{sport}_segment_waits_for_final"
        self.linescore_disagrees = f"{sport}_linescore_disagrees_with_final"
        self.overtime_unread = f"{sport}_overtime_rule_unread:"


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _canonical_market(sport: str, market: Any) -> str:
    from syndicate.features.shared.market_keys import canonical_market_key

    raw = str(market or "").strip().lower()
    return canonical_market_key(sport, raw) or raw


def _school(sport: str, names: list[Any]) -> str | None:
    """One school for these name forms, or None (unresolved, or forms that disagree)."""
    from syndicate.features.shared.team_aliases import canonical_team

    found = {school for school in (canonical_team(sport, str(name)) for name in names if name) if school}
    return next(iter(found)) if len(found) == 1 else None


def _kickoff_in_future(order: Mapping[str, Any]) -> bool:
    from syndicate.features.shared.bet_status_nfl import _parse_kickoff, _utcnow

    moment = _parse_kickoff(order.get("commence_time"))
    return moment is not None and moment > _utcnow()


def college_basketball_status_resolver(
    league: CollegeBasketballLeague,
    selected_date: str,
    *,
    fetch_json: Callable[[str], Any] | None = None,
):
    """A resolver `paper_settlement` can inject, for one college basketball league.

    `fetch_json(url) -> payload | None` is the scoreboard read (a test's seam; None is
    the network, resolved at call time)."""
    from syndicate.features.shared.bet_status_nba import _OVERTIME_RULES
    from syndicate.features.shared.bet_status_nfl import order_capture_dates
    from syndicate.features.shared.game_line_bet import game_line_view, is_game_line_market
    from syndicate.features.shared.population_outcomes_espn import parse_scoreboard_events

    sport = league.sport
    reasons = _Reasons(sport)
    cache: dict[str, Any] = {}

    def games(capture_date: str) -> list[dict[str, Any]] | None:
        """This date's events, each with `home_school` / `away_school`; None = not read."""
        slot = f"games:{capture_date}"
        if slot not in cache:
            from syndicate.features.shared.population_outcomes_espn import _default_fetch_json

            fetch = fetch_json or _default_fetch_json
            try:
                payload = fetch(scoreboard_url(league, capture_date))
            except Exception:
                payload = None
            events = parse_scoreboard_events(payload)
            if events is not None:
                as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
                for event in events:
                    event["home_school"] = _school(sport, event["home"]["names"])
                    event["away_school"] = _school(sport, event["away"]["names"])
                    event["as_of"] = as_of
            cache[slot] = events
        return cache[slot]

    def locate(order: Mapping[str, Any], home: str, away: str) -> tuple[dict[str, Any] | None, str]:
        """(event, "") or (None, refusal). Kickoff date first, plan date last."""
        capture_dates = order_capture_dates(order, selected_date)
        if not capture_dates:
            return None, reasons.no_scoreboard
        wanted = frozenset((home, away))
        for capture_date in capture_dates:
            found = [
                event for event in games(capture_date) or ()
                if frozenset((event["home_school"], event["away_school"])) == wanted
            ]
            if len(found) > 1:
                return None, reasons.ambiguous
            if found:
                return found[0], ""
        # Named for the capture that SHOULD have held the game (cached: no second read).
        if games(capture_dates[0]) is None:
            return None, reasons.no_scoreboard
        return None, reasons.game_not_found

    def segment_line(order, market, segment, event, home_side, away_side, stamp) -> dict[str, Any]:
        """A segment spread/total/moneyline off a COMPLETED game's linescores, or a refusal."""
        if not stamp["is_final"]:
            return {"unavailable_reason": reasons.segment_waits}
        home = home_side["linescores"]
        away = away_side["linescores"]
        played = len(home or ())
        if (
            home is None or away is None or len(away) != played or played < league.regulation_periods
            or any(value is None for value in home + away)
        ):
            return {"unavailable_reason": f"{REASON_SEGMENT_ACTUAL_PREFIX}{segment}"}
        if sum(home) != home_side["score"] or sum(away) != away_side["score"]:
            # A linescore short a period sums to a smaller number that looks real.
            return {"unavailable_reason": reasons.linescore_disagrees}

        periods = list(league.segments[segment])
        if played > league.regulation_periods and periods[-1] == league.regulation_periods:
            book = str(order.get("book") or "").strip().lower()
            includes_overtime = _OVERTIME_RULES.get(book, {}).get(segment)
            if includes_overtime is None:
                return {"unavailable_reason": f"{reasons.overtime_unread}{book or 'no_book'}"}
            if includes_overtime:
                periods.extend(range(league.regulation_periods + 1, played + 1))

        view = segment_scores_view(
            sport=sport,
            market=market,
            order=order,
            segment=segment,
            home_score=sum(home[number - 1] for number in periods),
            away_score=sum(away[number - 1] for number in periods),
            is_final=True,
            started=True,
            home_name=order.get("home_team"),
            away_name=order.get("away_team"),
            matched_by=stamp["matched_by"],
        )
        if view.get("unavailable_reason"):
            return view
        # `segment_periods` says which rule produced the number on an overtime game.
        return {**view, "segment_periods": periods, "as_of": stamp["as_of"],
                "espn_event_id": stamp["espn_event_id"]}

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if str(order.get("sport") or "").strip().lower() != sport:
            return {"unavailable_reason": reasons.not_this_sport}

        # PERMANENT BEFORE TRANSIENT: segment, prop and market refusals come before any
        # read, so a structural gap is never hidden behind "no scoreboard yet".
        segment = order_segment(order)
        if segment != FULL_GAME_SEGMENT and segment not in league.segments:
            return {"unavailable_reason": f"{REASON_UNSUPPORTED_SEGMENT_PREFIX}{segment}"}
        if order.get("player_name"):
            return {"unavailable_reason": reasons.props}
        market = _canonical_market(sport, order.get("market"))
        if market in _THREE_WAY_MARKETS:
            return {"unavailable_reason": reasons.three_way}
        is_total = market in _TOTAL_MARKETS
        if not (is_total or is_game_line_market(sport, market)):
            return {"unavailable_reason": REASON_UNMAPPED_MARKET}

        home_name, away_name = order.get("home_team"), order.get("away_team")
        if not home_name or not away_name:
            return {"unavailable_reason": REASON_NO_MATCHUP}
        home, away = _school(sport, [home_name]), _school(sport, [away_name])
        if not home or not away or home == away:
            return {"unavailable_reason": reasons.team_unresolved}

        if _kickoff_in_future(order):
            return {"current_value": None, "is_final": False, "started": False}

        event, refusal = locate(order, home, away)
        if event is None:
            return {"unavailable_reason": refusal}
        swapped = event["home_school"] != home
        home_side, away_side = (event["away"], event["home"]) if swapped else (event["home"], event["away"])
        stamp = {
            "matched_by": "espn_scoreboard:swapped" if swapped else "espn_scoreboard",
            "is_final": bool(event["completed"]),
            "started": event["state"] in ("in", "post"),
            # THE AS-OF: when this scoreboard was read, so a stale read says so on the page.
            "as_of": event.get("as_of"),
            "game_state": event.get("detail") or event["state"] or None,
            "espn_event_id": event["event_id"],
        }
        if event["state"] == "post" and not event["completed"]:
            return {"unavailable_reason": f"{reasons.not_completed}{event.get('status_name') or 'unknown'}"}
        if not stamp["started"]:
            return {**stamp, "current_value": None}

        if segment != FULL_GAME_SEGMENT:
            return segment_line(order, market, segment, event, home_side, away_side, stamp)

        home_score, away_score = home_side["score"], away_side["score"]
        if home_score is None or away_score is None:
            return {"unavailable_reason": reasons.no_scores}
        scores = {"home_score": home_score, "away_score": away_score,
                  "home_name": home_name, "away_name": away_name}
        if is_total:
            return {**stamp, **scores, "current_value": home_score + away_score}
        view = game_line_view(
            sport=sport,
            market=market,
            side=order.get("side"),
            line=order.get("line"),
            home_team=home_name,
            away_team=away_name,
            home_score=home_score,
            away_score=away_score,
            # Basketball has no draw: overtime runs until someone wins.
            draw_possible=False,
        )
        if view.get("unavailable_reason"):
            return view
        return {**view, **stamp, **scores}

    return resolve


def ncaab_status_resolver(selected_date: str, *, fetch_json: Callable[[str], Any] | None = None):
    """A resolver `bet_status`/`paper_settlement` can inject, for NCAAB orders."""
    return college_basketball_status_resolver(NCAAB, selected_date, fetch_json=fetch_json)
