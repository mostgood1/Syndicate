"""Resolve a soccer bet's CURRENT value from the live-state artifact.

The third sibling of `bet_status_mlb` and `bet_status_wnba`, and deliberately
the same shape: it answers "what is the thing this bet is on worth right now"
and leaves every judgement about winning and losing to `resolve_bet_status`.

--------------------------------------------------------------------------
WHY THIS EXISTS: SOCCER BETS COULD NEVER SETTLE
--------------------------------------------------------------------------

`paper_settlement._default_resolver` had builders for `mlb` and `wnba` only, so
every soccer order returned `no_resolver_for_soccer` -- forever. Measured
2026-08-25 14:03:02Z:

    SETTLED date=2026-08-25 orders=2 graded=0 ungraded={'no_resolver_for_soccer': 2}
    PNL_CUT all_time by_sport=[('mlb', 181, ...), ('soccer', 0, ...), ('wnba', 0, ...)]

Zero soccer bets settled, ever, while the board that produces them was ~97%
soccer by row count (9,041 candidates, 1,277 opportunities on the 08-24 slate).
A bet that is taken and can never be graded is worse than one never taken: it
consumes bankroll and is invisible to every performance number.

--------------------------------------------------------------------------
JOINED ON THE TEAM PAIR, NOT ON `event_id` -- THIS IS THE MLB TRAP
--------------------------------------------------------------------------

`bet_status_wnba` records that MLB "cost a day" because the board stamps ids
from OddsAPI while the resolving artifact wants the provider's own. Soccer has
exactly that gap and it is worse, not better: the order's `event_id` is the
OddsAPI event hash, while `poll_soccer_live_state.py` keys its matches by
ESPN's event id. They are different namespaces and no amount of parsing bridges
them.

WNBA got to key on `event_id` because its box and its board share one id. Soccer
does not, so this joins on `home_team`/`away_team` through `team_aliases`, the
same resolver `attach_game_state` and `_soccer_live_state_games` already use for
this sport. Those fields are on `OrderRequest` and every order placed since they
were added carries them; an order without them refuses BY NAME rather than
falling back to an id that cannot match.

--------------------------------------------------------------------------
TWO SHAPES OF SCOREBOARD BET, AND ONLY ONE NEEDS TRANSLATING
--------------------------------------------------------------------------

MONEYLINES AND SPREADS go through `game_line_view`, which is sport-agnostic and
already handles a draw leg. They need it because a spread arrives as
`side="Chelsea", line=-1.5` and the grader speaks over/under.

TOTALS DO NOT, and that is the whole reason they were missing. A total already
arrives in the grader's vocabulary -- `side="over", line=2.5` -- so the only
thing needed is the combined goals. `bet_status_mlb` grades its 46 settled
totals exactly this way (`_combined_score`, no `game_line_view` call), and
routing a total through the translator instead is what produced:

    UNMAPPED_MARKETS date=2026-08-25 {'totals': 1}      (measured 14:47:23Z)

`is_game_line_market` is False for `totals` by design -- it is the SPREAD and
MONEYLINE test -- so the first cut of this resolver refused a bet it already
held both numbers for. Two of the four pending soccer orders were totals.

**`team_totals` IS REFUSED BY NAME AND IS NOT THE SAME MARKET.** It is one
team's goals, not the combined score, and grading it off `home + away` would
double the number and settle overs that lost. The side token carries which team
and nothing here reads it, so it refuses rather than guesses -- the same trade
the module makes everywhere else.

A total's line is often integral in soccer (Asian 2.0, 3.0) where MLB's rarely
is, and that needs NO special handling: `resolve_bet_status` settles equality as
a push, which is exactly right for a total landing on its line. This is the
opposite of the three-way moneyline case, where the half-point trick exists
precisely BECAUSE a push would be wrong.

PLAYER PROPS GRADE OFF THE MATCH BOX, never off `live_player_props` (lane
`soccer-live-anytime-scorer`, 2026-10-13). Those projections were capped at twelve
players per match, so a player outside the cap was ABSENT rather than at zero,
and grading that as "0 shots, the under is fine" is the exact failure
`bet_status_wnba` names -- "the worst possible wrong answer". Props refused
outright until then, and soccer had no player-prop results at all.

The poller's per-match `match_box` (`espn_match_box`) lists EVERY player ESPN
boxed for the match -- starters, used and unused subs -- with goals, shots,
shots on target and assists. So:
  shots / shots on target / assists   the box value against the line;
  anytime goalscorer                  box goals against 0.5 (yes/no);
  a boxed player who never appeared   void once the match is final, as books do;
  a player NOT in the box             refused by name -- a spelling the box does
                                      not share is not the same as zero;
  first / last goalscorer, cards      refused by name: a race with book-specific
                                      own-goal rules, and the box carries no cards.

--------------------------------------------------------------------------
FINAL IS ASSERTED, NEVER INFERRED FROM THE CLOCK
--------------------------------------------------------------------------

`is_final` comes from the artifact's own `status_state == "post"` / `final`
boolean, which the poller carries through from ESPN verbatim and preserves once
set. A 90th-minute clock is not a finished match -- stoppage time is real and
routinely decides totals -- so nothing here reads the clock.

**A `final` that never arrives costs a delay; a `final` invented from a clock
settles a live bet wrongly.** Same trade `bet_status_wnba` makes and for the
same reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from syndicate.features.shared.segment_actuals import (
    FULL_GAME_SEGMENT,
    REASON_UNSUPPORTED_SEGMENT_PREFIX,
    order_segment,
    segment_actuals,
    segment_periods,
)

__all__ = ["soccer_status_resolver"]

REASON_NOT_SOCCER = "not_a_soccer_order"
REASON_NO_MATCHUP = "no_home_away_teams_on_order"
REASON_NO_LIVE_STATE = "no_soccer_live_state_for_date"
REASON_MATCH_NOT_FOUND = "match_not_in_soccer_live_state"
# Player props (see the module docstring).
REASON_PROP_MARKET = "soccer_prop_market_not_graded"
REASON_SCORER_RACE = "soccer_first_last_scorer_not_graded"
REASON_NO_BOX = "no_soccer_player_box_for_match"
REASON_PLAYER_NOT_IN_BOX = "player_not_in_soccer_box"
REASON_PLAYER_AMBIGUOUS = "player_name_ambiguous_in_soccer_box"
REASON_DNP_VOID = "soccer_player_did_not_appear_void"
REASON_STAT_UNAVAILABLE = "soccer_box_stat_unavailable"
REASON_UNKNOWN_MARKET = "unmapped_market"
# A team total is ONE side's goals. Grading it off the combined score would
# roughly double the value and settle overs that lost, so it refuses until the
# side token is read properly.
REASON_TEAM_TOTAL = "team_totals_needs_a_per_team_score"
REASON_NO_SCORES = "match_carries_no_scores"
# The rolling aggregate is readable but has moved on to another date, and no
# settlement record was kept for the date we are grading. Distinct from
# `no_soccer_live_state_for_date`, which means we could read nothing at all:
# this one says the window CLOSED, which is a different job for whoever reads
# the counter -- it points at retention, not at the poller being down.
REASON_FINALS_WINDOW_CLOSED = "soccer_finals_window_closed"

# The combined-goals family. `team_totals` is deliberately ABSENT -- see the
# module docstring. Mirrors `live_gameline_join._TOTALS_MARKETS`, which is the
# vocabulary the board actually emits (`totals_alt` and `alternate_totals` are
# the same market at another line, and a distribution -- or here a final score
# -- prices any line).
_GAME_TOTAL_MARKETS = frozenset({"totals", "total", "totals_alt", "alternate_totals"})
_TEAM_TOTAL_MARKETS = frozenset({"team_totals", "team_total", "team_totals_alt"})
# Prop market -> `match_box` player field. Anytime is goals against 0.5.
_PROP_STATS = {
    "player_shots": "shots",
    "player_shots_on_target": "shots_on_target",
    "player_assists": "assists",
    "player_goals": "goals",
}
_ANYTIME_MARKETS = frozenset({
    "player_goal_scorer_anytime", "player_anytime_goal_scorer", "anytime_goal_scorer", "anytime_goalscorer",
})
_SCORER_RACE_MARKETS = frozenset({"player_first_goal_scorer", "player_last_goal_scorer"})
_ANYTIME_LINE = 0.5
# MATCH CORNERS AND BOTH-TEAMS-TO-SCORE `[2026-10-27, lane paper-evicted-grading,
# #744]`. Both refused `unmapped_market` forever -- 233 corners and 89 btts paper
# orders on the fleet, corners being the LARGEST soccer board market
# (`market_keys`). Both read off the per-league `match_box`: corners from ESPN's
# own team stat line (`teams.{home,away}.stats.Corners`), btts from the score.
# Full match only: no half-time corners count is kept.
_CORNERS_MARKETS = frozenset({"alternate_totals_corners", "totals_corners"})
_BTTS_MARKETS = frozenset({"btts"})
_BTTS_LINE = 0.5
REASON_NO_CORNERS = "soccer_box_carries_no_corners"


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _as_float(value: Any) -> float | None:
    """ESPN ships scores as STRINGS ("1"). A string compares wrong downstream
    without ever raising, which is the failure `board_enrichment` records for
    this same field."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def soccer_status_resolver(selected_date: str):
    """A resolver `paper_settlement` can inject, for soccer orders.

    The live-state read happens ONCE per resolver, not once per order: a slate
    of forty soccer orders must not mean forty reads of one artifact that does
    not change between them.
    """
    from syndicate.features.shared.game_line_bet import game_line_view, is_game_line_market
    from syndicate.features.shared.team_aliases import teams_match

    cache: dict[str, Any] = {}

    def matches() -> list[dict[str, Any]] | None:
        if "matches" in cache:
            return cache["matches"]
        cache["matches"] = _load_matches(selected_date)
        return cache["matches"]

    def boxes(order: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """The match-box records for the order's GAME dates, else the slate's."""
        dates = _game_dates(order, selected_date) if order is not None else []
        if not dates:
            if "boxes" not in cache:
                cache["boxes"] = _load_player_boxes(selected_date)
            return cache["boxes"]
        out: list[dict[str, Any]] = []
        for day in dates:
            key = f"box:{day}"
            if key not in cache:
                cache[key] = _load_match_box_records([day])
            out.extend(cache[key])
        return out

    def locate(order: Mapping[str, Any], *, need_box: bool) -> tuple[dict[str, Any] | None, str | None]:
        """The match record for this order, or a named reason.

        THE GAME'S OWN DATE, NOT THE SLATE'S `[2026-10-27, #744]`. A forward
        bet is placed on one slate and played days later -- measured on the
        fleet, 170 soccer game lines and most of the 322 corners/btts orders
        were dated 10-04 for matches on 10-09..11 -- and every read here was
        keyed on `selected_date`, so those orders could NEVER find their match.
        The slate-date state still answers first whenever the game is on (or
        beside) its slate, so in-play grading is unchanged; otherwise, and for
        corners (which only the box carries), the per-league `match_box` files
        are read around the kickoff date.
        """
        home_team, away_team = order.get("home_team"), order.get("away_team")
        dates = _game_dates(order, selected_date)
        on_slate = not dates or _within_a_day(dates[0], selected_date)
        found = None
        if on_slate and not need_box:
            found = matches()
            if found is not None:
                for candidate in found:
                    if teams_match("soccer", home_team, candidate.get("home_team")) and teams_match(
                        "soccer", away_team, candidate.get("away_team")
                    ):
                        return candidate, None
        records = boxes(order)
        paired = [
            r for r in records
            if teams_match("soccer", home_team, r.get("home_team"))
            and teams_match("soccer", away_team, r.get("away_team"))
        ]
        if paired:
            # Dates are read nearest-the-kickoff first; a finished copy beats an
            # in-play one, since a file can hold a match the poller left mid-game.
            final = [r for r in paired if r.get("final") or str(r.get("status_state") or "").lower() == "post"]
            return _box_as_match((final or paired)[0]), None
        if on_slate and not need_box and found is None and not records:
            return None, REASON_NO_LIVE_STATE
        return None, REASON_MATCH_NOT_FOUND

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if _norm(order.get("sport")) != "soccer":
            # This resolver is handed every order; a non-soccer one is not a
            # defect in anything and must not be reported as a soccer failure.
            return {"unavailable_reason": REASON_NOT_SOCCER}

        # SEGMENT BEFORE MARKET, same ordering and same reason as the market
        # check below. `market_segments` gives soccer `h1`/`h2`, and
        # `fetch_soccer_oddsapi_odds_local` already asks for both. Those two
        # are graded below off the per-half goals the poller now carries
        # (`segment_actuals`), refusing BY NAME on a record without them; any
        # other segment is a join defect and refuses here. Absent or `full`
        # means the whole match, for the reason `bet_status.segment_refusal`
        # states.
        segment = order_segment(order)
        if segment != FULL_GAME_SEGMENT and segment_periods("soccer", segment) is None:
            return {"unavailable_reason": f"{REASON_UNSUPPORTED_SEGMENT_PREFIX}{segment}"}

        # THE MARKET CHECK COMES FIRST, before the artifact read -- the rule
        # `bet_status_wnba` states and paid for: "we cannot grade this market"
        # is permanent, "the artifact is not captured yet" is transient, and
        # checking the transient one first hides the structural one.
        market = order.get("market")
        canonical = _norm(market)
        # ORDER MATTERS. `team_totals` must be caught BEFORE the combined-total
        # test, because a permissive `startswith("total")` would swallow it and
        # grade one team's goals against the whole scoreline.
        if canonical in _TEAM_TOTAL_MARKETS:
            return {"unavailable_reason": REASON_TEAM_TOTAL}
        if order.get("player_name"):
            # A PLAYER PROP. Classified before any read, for the same reason.
            if canonical in _SCORER_RACE_MARKETS:
                return {"unavailable_reason": REASON_SCORER_RACE}
            anytime = canonical in _ANYTIME_MARKETS
            stat = "goals" if anytime else _PROP_STATS.get(canonical)
            if stat is None or segment != FULL_GAME_SEGMENT:
                return {"unavailable_reason": REASON_PROP_MARKET}
            return _resolve_prop(order, stat, anytime, boxes(order))
        is_total = canonical in _GAME_TOTAL_MARKETS
        is_corners = canonical in _CORNERS_MARKETS
        is_btts = canonical in _BTTS_MARKETS
        is_line = is_game_line_market("soccer", market)
        if not (is_total or is_line or is_corners or is_btts):
            return {"unavailable_reason": REASON_UNKNOWN_MARKET}
        if (is_corners or is_btts) and segment != FULL_GAME_SEGMENT:
            return {"unavailable_reason": f"{REASON_UNSUPPORTED_SEGMENT_PREFIX}{segment}"}

        home_team, away_team = order.get("home_team"), order.get("away_team")
        if not home_team or not away_team:
            # See the module docstring: `event_id` is the OddsAPI hash and
            # cannot address an ESPN-keyed artifact, so there is no fallback
            # here that would be anything but a guess.
            return {"unavailable_reason": REASON_NO_MATCHUP}

        record, refusal = locate(order, need_box=is_corners)
        if record is None:
            return {"unavailable_reason": refusal}
        if str(record.get("status_state") or "").strip().lower() == "pre":
            return {"current_value": None, "is_final": False, "started": False}

        if is_corners or is_btts:
            home = _as_float(record.get("home_score"))
            away = _as_float(record.get("away_score"))
            is_final = bool(record.get("final"))
            if is_btts:
                if home is None or away is None:
                    return {"unavailable_reason": REASON_NO_SCORES}
                # 1 when both teams have scored, against a 0.5 line: "yes" is an
                # over and "no" an under in the grader's own vocabulary.
                return {
                    "current_value": 1.0 if home > 0 and away > 0 else 0.0,
                    "line": _BTTS_LINE,
                    "is_final": is_final,
                    "started": True,
                }
            corners = record.get("corners")
            if not corners or corners[0] is None or corners[1] is None:
                # Both teams' counts or nothing: a missing count is not zero.
                return {"unavailable_reason": REASON_NO_CORNERS}
            return {"current_value": corners[0] + corners[1], "is_final": is_final, "started": True}

        if segment == FULL_GAME_SEGMENT:
            home = _as_float(record.get("home_score"))
            away = _as_float(record.get("away_score"))
            # ASSERTED BY THE ARTIFACT, never read off the clock. Stoppage time
            # is real and decides totals.
            is_final = bool(record.get("final"))
        else:
            # THE HALF'S OWN SCORE PAIR, or a named refusal. `is_final` is the
            # half's: a first-half total is decided at the interval, which the
            # poller's `status_period` (2 once the second half is under way)
            # or the match's own `final` asserts -- never the clock.
            actual = segment_actuals("soccer", segment, record)
            if actual.get("unavailable_reason"):
                return actual
            if not actual.get("started"):
                return {"current_value": None, "is_final": False, "started": False}
            home = _as_float(actual.get("home_score"))
            away = _as_float(actual.get("away_score"))
            is_final = bool(actual.get("is_final"))

        if is_total:
            # NO TRANSLATION. The order already carries `side="over"` and a
            # numeric line, so the grader needs only the combined goals --
            # exactly what `bet_status_mlb._combined_score` hands it. Passing
            # this through `game_line_view` is what refused it as
            # `unmapped_market` in the first place.
            if home is None or away is None:
                # A half-known score is not a score. Refusing both together
                # stops a missing away total reading as a clean sheet -- the
                # same rule `game_line_view` states for its own two scores.
                return {"unavailable_reason": REASON_NO_SCORES}
            return {
                "current_value": home + away,
                "is_final": is_final,
                "started": True,
            }

        view = game_line_view(
            sport="soccer",
            market=market,
            side=order.get("side"),
            line=order.get("line"),
            home_team=home_team,
            away_team=away_team,
            home_score=home,
            away_score=away,
            # SOCCER DRAWS. A level 2-way moneyline is a PUSH and a level
            # three-way is a LOSS; `game_line_view` encodes both off this flag
            # and the market name, so neither is decided here. A first-half
            # result is three-way exactly as the match result is: a level half
            # is the DRAW outcome, not a push on the favourite.
            draw_possible=True,
        )
        if "unavailable_reason" in view:
            return view

        return {
            "current_value": view.get("current_value"),
            "side": view.get("side"),
            "line": view.get("line"),
            "is_final": is_final,
            "started": True,
        }

    return resolve



def _load_player_boxes(selected_date: str) -> list[dict[str, Any]]:
    """Every `match_box` record for the date, then the day before, then the day after.

    The same per-league files `_segment_fields_by_matchup` walks. They are a
    live-odds-worker filesystem write: readable here on the local fleet (one disk),
    NOT on a split deployment, where every prop refuses as `no_soccer_player_box_for_match`
    rather than grading off something else.

    WHY THREE DATES. The poller files a match under ESPN's date, and an order's date
    is the board's. They differ across midnight UTC: measured 2026-10-13 on the 10-10..12
    board, 1,410 prop rows dated 10-11 found their box only in the 10-10 file. The
    order's own date is read FIRST, so a match is never answered from a neighbouring
    day while its own day has it; a team pair cannot recur within three days.
    Never raises.
    """
    from datetime import date, timedelta

    try:
        day = date.fromisoformat(str(selected_date)[:10])
    except ValueError:
        return []
    return _load_match_box_records([(day + timedelta(days=offset)).isoformat() for offset in (0, -1, 1)])


def _load_match_box_records(dates: list[str]) -> list[dict[str, Any]]:
    """Every per-league `match_box` record filed under each date, in the order given.

    The one reader of those files for both props and game lines. Never raises.

    READ THROUGH `soccer.sources.live_state_payload`, which tries the state
    store and then the poller's own file on disk. The poller writes these files
    straight to disk (`poll_soccer_live_state.py`, `out_path.write_text`), while
    a bare `read_json_file` on the keyvalue backend asks Redis only, where a
    dated key lives ten days at most. Measured on the fleet 2026-10-27 over
    the 497 stale soccer paper orders, with kickoff-date binding in both runs:
    the Redis-only read graded 25, this read 494; every league's file for
    09-30..10-27 was on disk (lane paper-evicted-grading, #744).
    """
    out: list[dict[str, Any]] = []
    try:
        from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES, live_state_payload

        for stamp in dates:
            for league in list(LEAGUE_DISPLAY_NAMES):
                payload = live_state_payload(str(league), stamp)
                match_box = payload.get("match_box") if isinstance(payload, Mapping) else None
                if isinstance(match_box, Mapping):
                    out.extend(dict(r) for r in match_box.values() if isinstance(r, Mapping))
    except Exception:
        return out
    return out


def _game_dates(order: Mapping[str, Any] | None, selected_date: str) -> list[str]:
    """The UTC kickoff date, then the day before and after, or [] with no kickoff.

    ESPN files a match under its own (US) date, which can sit a day either side
    of the UTC kickoff; the kickoff date is read first so a match is never
    answered from a neighbouring day while its own day has it.
    """
    from datetime import datetime, timedelta

    raw = str((order or {}).get("commence_time") or "").strip()
    if not raw:
        return []
    try:
        kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return []
    return [(kickoff + timedelta(days=offset)).isoformat() for offset in (0, -1, 1)]


def _within_a_day(one: str, two: str) -> bool:
    from datetime import date

    try:
        return abs((date.fromisoformat(one[:10]) - date.fromisoformat(str(two)[:10])).days) <= 1
    except ValueError:
        return False


def _box_as_match(record: Mapping[str, Any]) -> dict[str, Any]:
    """A `match_box` record in `_load_matches`' shape, plus both teams' corners.

    Scores are `score_home` / `score_away` here; final is the poller's own
    `final` boolean or ESPN's `post` state, never the clock.
    """
    state = str(record.get("status_state") or "").strip().lower()
    stats = record.get("teams") if isinstance(record.get("teams"), Mapping) else {}

    def corners(side: str) -> float | None:
        block = stats.get(side) if isinstance(stats.get(side), Mapping) else {}
        line = block.get("stats") if isinstance(block.get("stats"), Mapping) else {}
        return _as_float(line.get("Corners"))

    return {
        "home_team": record.get("home_team"),
        "away_team": record.get("away_team"),
        "home_score": record.get("score_home"),
        "away_score": record.get("score_away"),
        "final": bool(record.get("final")) or state == "post",
        "in_progress": state == "in",
        "status_state": state,
        "status_detail": record.get("status_detail"),
        "home_linescores": record.get("home_linescores"),
        "away_linescores": record.get("away_linescores"),
        "period": record.get("status_period"),
        "corners": (corners("home"), corners("away")),
        "source": "soccer_match_box",
    }


def _name_keys(name: Any) -> tuple[str, str]:
    """(folded name, folded name with its tokens sorted). The second catches a book
    that writes "Heung-Min Son" for ESPN's "Son Heung-Min". Folding is the pregame
    starter matcher's own, so the two cannot drift."""
    from syndicate.features.soccer.features.lineups import _norm_player_name

    folded = _norm_player_name(str(name or ""))
    return folded, " ".join(sorted(folded.split()))


def _names_nest(book: str, espn: str) -> bool:
    """One name's words inside the other's, the way books and ESPN differ.

    Books write full names, ESPN the playing name: measured 2026-10-13 on the 10-10..12
    board, "erling braut haaland" / "Erling Haaland", "joao pedro junqueira de jesus" /
    "João Pedro", "antony matheus dos santos" / "Antony" were 11% of prop rows refused
    as not in the box. A nested pair of two or more words is accepted; a ONE-word ESPN
    name only as the book name's first word. The caller still requires the match to be
    unique within the match's box, so two candidates refuse rather than guess.
    """
    b, e = book.split(), espn.split()
    if not b or not e or b == e:
        return False
    if len(e) == 1:
        return b[0] == e[0]
    small, large = (e, b) if len(e) <= len(b) else (b, e)
    return len(small) >= 2 and set(small) <= set(large)


def _resolve_prop(order: Mapping[str, Any], stat: str, anytime: bool, boxes: list[dict[str, Any]]) -> dict[str, Any]:
    from syndicate.features.shared.team_aliases import teams_match

    home_team, away_team = order.get("home_team"), order.get("away_team")
    if not home_team or not away_team:
        return {"unavailable_reason": REASON_NO_MATCHUP}
    record = next((b for b in boxes if teams_match("soccer", home_team, b.get("home_team"))
                   and teams_match("soccer", away_team, b.get("away_team"))), None)
    if record is None:
        return {"unavailable_reason": REASON_NO_BOX}
    state = str(record.get("status_state") or "").strip().lower()
    if state == "pre":
        return {"current_value": None, "is_final": False, "started": False}
    # FINAL IS ASSERTED by the artifact, never read off the clock (module docstring).
    final = bool(record.get("final")) or state == "post"

    wanted = _name_keys(order.get("player_name"))
    rows: list[Mapping[str, Any]] = []
    for side in ("home", "away"):
        block = (record.get("players") or {}).get(side) or {}
        rows.extend(r for r in (block.get("players") or []) if isinstance(r, Mapping))
    exact = [r for r in rows if _name_keys(r.get("player_name"))[0] == wanted[0]]
    found = exact or [r for r in rows if _name_keys(r.get("player_name"))[1] == wanted[1]]
    if not found:
        found = [r for r in rows if _names_nest(wanted[0], _name_keys(r.get("player_name"))[0])]
    if not found:
        return {"unavailable_reason": REASON_PLAYER_NOT_IN_BOX}
    if len(found) > 1:
        return {"unavailable_reason": REASON_PLAYER_AMBIGUOUS}
    row = found[0]
    if final and not row.get("appeared"):
        return {"unavailable_reason": REASON_DNP_VOID}
    value = _as_float(row.get(stat))
    if value is None:
        if row.get("appeared"):
            return {"unavailable_reason": REASON_STAT_UNAVAILABLE}
        value = 0.0  # an unused sub mid-match: nothing yet, and nothing missing
    resolved: dict[str, Any] = {"current_value": value, "is_final": final, "started": True,
                                "source": "soccer_match_box"}
    if anytime and _as_float(order.get("line")) is None:
        resolved["line"] = _ANYTIME_LINE
    return resolved


def _finals_record_path(root, selected_date: str):
    return root / "live" / f"soccer_finals_{selected_date}.json"


def _remember_finals(selected_date: str, matches) -> None:
    """Keep this date's FINISHED matches where a later tick can still find them.

    WHY SETTLEMENT HAS TO KEEP ITS OWN RECORD. `live/soccer_live_lens.json` is a
    ROLLING SINGLE-DATE snapshot, and both of its readers gate on
    `snapshot["date"] == selected_date` -- correctly, since answering for one
    date out of another date's match state would grade the wrong scoreline.
    But `settle_orders` deliberately runs for TODAY AND YESTERDAY (a slate that
    starts before midnight UTC files its orders under the previous date), and
    the moment the aggregate rolls, the yesterday pass can read NOTHING: the
    per-league `match_box` tree is a filesystem write on live-odds-worker and
    settlement runs on refresh-worker. So yesterday's pass was structurally
    impossible for soccer -- which is the sport that needs it most, since
    European matches finish within a couple of hours of the UTC date roll.

    MEASURED 2026-08-26: soccer had settled ZERO orders all-time, and at
    14:57Z the pass for 2026-08-25 reported `no_soccer_live_state_for_date: 3`
    while the aggregate had already rolled to 2026-08-26.

    UNIONED, NEVER REPLACED. A tick that can see only some of the day's finals
    must not erase the ones an earlier tick recorded, and the poller itself
    rebuilds nothing it has already marked final. Same trim the poller applies:
    a handful of scalars per finished match, so this cannot grow with squad
    size or trip the aggregate's 1MB write warning.

    NEVER RAISES. Settlement failing because a cache write failed would be a
    worse outcome than the gap this closes.
    """
    finished = [m for m in matches if m.get("final")]
    if not finished:
        return
    try:
        from syndicate.features.shared.refresh_state_store import (
            data_root,
            read_json_file,
            write_json_file,
        )

        path = _finals_record_path(data_root(), selected_date)
        merged: dict[Any, dict[str, Any]] = {}
        existing = read_json_file(path)
        if isinstance(existing, Mapping) and str(existing.get("date") or "") == str(selected_date):
            for record in existing.get("matches") or []:
                if isinstance(record, Mapping):
                    merged[(record.get("home_team"), record.get("away_team"))] = dict(record)
        added = 0
        for record in finished:
            key = (record.get("home_team"), record.get("away_team"))
            if key not in merged:
                added += 1
            merged[key] = dict(record)
        if not added:
            # Nothing new this tick. Skipping the write keeps a settled day
            # from being rewritten every three minutes for the rest of it.
            return
        write_json_file(path, {"date": str(selected_date), "matches": list(merged.values())})
    except Exception:
        return


def _recall_finals(selected_date: str):
    """This date's finished matches from settlement's own record, or None.

    None means nothing was kept -- NOT that the day had no matches. The caller
    keeps those two as different reasons, which is the same split the rest of
    this module draws and the reason `_load_matches` returns None rather than
    an empty list.
    """
    try:
        from syndicate.features.shared.refresh_state_store import data_root, read_json_file

        record = read_json_file(_finals_record_path(data_root(), selected_date))
    except Exception:
        return None
    if not isinstance(record, Mapping):
        return None
    if str(record.get("date") or "") != str(selected_date):
        # A record written for another date cannot answer for this one, for
        # exactly the reason the aggregate is date-gated in the first place.
        return None
    out = [dict(m) for m in (record.get("matches") or []) if isinstance(m, Mapping)]
    return out or None

def _load_matches(selected_date: str) -> list[dict[str, Any]] | None:
    """Every soccer match this service can see, in play OR finished.

    Delegates to `board_enrichment._soccer_live_state_games`, which is the ONE
    place that knows soccer's two-source asymmetry and is already relied on by
    the chip-state correction:

      `live/soccer_live_lens.json`  cross-service (keyvalue), IN-PLAY ONLY
      per-league `match_box`        local filesystem, spans `in` AND `post`

    A second copy of that logic is how the two would drift, and this module's
    siblings both record what a drifting duplicate costs. **Settlement runs on
    refresh-worker** (`pipeline/intelligence_state.py` calls `settle_orders`),
    where only the aggregate is readable -- so finished matches reach this
    resolver only because `poll_active_leagues_for_tick` now publishes them into
    that aggregate. Without that, this would grade nothing in production while
    passing every test on a dev box, which is precisely the inert-feature shape
    `model_engine_standard.md` exists to prevent.

    None means "we could not read any live state", which is NOT the same as "no
    matches today" -- the caller reports them as different reasons.
    """
    try:
        from syndicate.features.shared.board_enrichment import _soccer_live_state_games
    except ImportError:  # pragma: no cover - deploy-skew guard
        return None

    try:
        resolved = _soccer_live_state_games(selected_date)
    except Exception:
        resolved = None
    if resolved is None:
        # THE AGGREGATE HAS ROLLED PAST THIS DATE (or could not be read at all).
        # Settlement's own kept record is the only thing that can still answer,
        # and it is what makes the yesterday pass possible for soccer.
        return _recall_finals(selected_date)

    games, _age = resolved
    segment_fields = _segment_fields_by_matchup(selected_date)
    out: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, Mapping):
            continue
        home = game.get("home") if isinstance(game.get("home"), Mapping) else {}
        away = game.get("away") if isinstance(game.get("away"), Mapping) else {}
        state = str(game.get("state") or "").strip().lower()
        extra = segment_fields.get((_norm(home.get("name")), _norm(away.get("name")))) or {}
        out.append(
            {
                "home_team": home.get("name"),
                "away_team": away.get("name"),
                "home_score": game.get("home_score"),
                "away_score": game.get("away_score"),
                # `_soccer_live_state_games` has already collapsed both of the
                # artifact's finished signals (`status_state == "post"` and the
                # `final` boolean) into one state token.
                "final": state == "final",
                "in_progress": state == "live",
                "status_detail": game.get("detailed"),
                # SEGMENT FIELDS, joined back on from the artifacts the shared
                # reader trims them out of -- see `_segment_fields_by_matchup`.
                # Absent reads as a named refusal downstream, never as 0-0.
                "home_linescores": extra.get("home_linescores"),
                "away_linescores": extra.get("away_linescores"),
                "period": extra.get("period"),
            }
        )
    # Kept BEFORE returning, so the window is recorded on every tick that can
    # still see it rather than only on the one that happens to grade.
    _remember_finals(selected_date, out)
    return out


def _segment_fields_by_matchup(selected_date: str) -> dict[tuple[str, str], dict[str, Any]]:
    """`(home, away)` -> `{home_linescores, away_linescores, period}` for every
    match this service can see. Never raises; empty when nothing carries them.

    WHY THIS IS A SECOND READ OF THE SAME ARTIFACTS. `_load_matches` delegates
    to `board_enrichment._soccer_live_state_games`, which is the one reader
    of soccer's two-source asymmetry -- and which trims each match down to the
    fields the CHIP correction needs, dropping the per-half goals the poller
    now writes. Carrying them through that trim is a three-line edit to
    `board_enrichment.py`, and that file is claimed by OPEN lane
    `ncaaf-live-resim` (2026-09-08), so it is not made here. Until it is, the
    two settlement fields are joined back on from the SAME three sources the
    shared reader walks, by the team pair the poller wrote, in the same order:
    the aggregate's in-play `games`, its `finals`, then each catalogued
    league's `match_box` by NAME. A record WITHOUT the fields never overwrites
    one WITH them.

    The join key is the exact normalised pair, not `teams_match`: both sides of
    the join are the poller's own `displayName`s, so aliasing has nothing to
    resolve and would only widen the match.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    records: list[Mapping[str, Any]] = []
    try:
        from syndicate.features.shared.refresh_state_store import data_root, read_json_file
        from syndicate.features.shared.soccer_live_gameline_source import soccer_live_games
    except ImportError:  # pragma: no cover - deploy-skew guard
        return out

    try:
        records.extend(g for g in soccer_live_games(selected_date) if isinstance(g, Mapping))
    except Exception:
        pass
    try:
        root = data_root()
        snapshot = read_json_file(root / "live" / "soccer_live_lens.json")
        if isinstance(snapshot, Mapping) and str(snapshot.get("date") or "") == str(selected_date):
            finals = snapshot.get("finals")
            if isinstance(finals, list):
                records.extend(r for r in finals if isinstance(r, Mapping))
        try:
            from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES

            league_names = list(LEAGUE_DISPLAY_NAMES)
        except Exception:  # pragma: no cover - deploy-skew guard
            league_names = []
        for league in league_names:
            payload = read_json_file(
                root / "soccer_source" / str(league) / "api" / "live_state" / f"live_state_{selected_date}.json"
            )
            if not isinstance(payload, Mapping):
                continue
            match_box = payload.get("match_box")
            if isinstance(match_box, Mapping):
                records.extend(r for r in match_box.values() if isinstance(r, Mapping))
    except Exception:
        pass

    for record in records:
        key = (_norm(record.get("home_team")), _norm(record.get("away_team")))
        if not key[0] or not key[1]:
            continue
        fields = {
            "home_linescores": record.get("home_linescores"),
            "away_linescores": record.get("away_linescores"),
            "period": record.get("status_period"),
        }
        if fields["home_linescores"] is None and fields["away_linescores"] is None and key in out:
            continue
        out[key] = fields
    return out
