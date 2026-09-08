"""Grade a SEGMENT bet off the segment's own scores -- shared by every resolver.

`bet_status.segment_refusal` is the guard that stopped a first-five-innings
UNDER 3.5 being settled against a nine-inning total of 8. It refuses; it does
not grade. This module is the other half: once a sport's resolver has read the
segment's ACTUAL scores -- runs through inning N, points through quarter N --
this turns them into the `{current_value, side, line}` shape the grader takes,
exactly as the whole-game path does, so the two paths cannot drift in how a
spread sign or a moneyline push is spelled.

WHAT A SEGMENT ACTUAL IS, PER MARKET
------------------------------------
    totals   home_seg + away_seg, graded over/under as the order says.
    spreads  home_seg - away_seg against the quoted handicap, through
             `game_line_view`, which owns the sign convention.
    h2h      the segment's winner. A partial interval CAN end level -- five
             innings, one quarter -- so `draw_possible=False` is passed and
             the TWO-WAY market pushes on a tie (`game_line_view` puts the
             line at 0.0, `resolve_bet_status` reports a level margin as
             `live_tied`, `paper_settlement` maps that to `push`). An order
             whose market is `h2h_3_way` is three-way BY NAME
             (`_ALWAYS_THREE_WAY`) and a tie loses there, which is what the
             book paid out.

THE FALLBACK IS THE REFUSAL, NOT THE FULL GAME. A resolver that cannot read a
segment actual must let `segment_refusal` fire unchanged, or refuse with the
named reason below. It must never fall through to the whole-game score; that
is the defect `segment_refusal` exists for.

--------------------------------------------------------------------------
PER-PERIOD ACTUALS FOR NFL, NCAAF AND SOCCER (WP2) -- WHY THE SECOND HALF OF THIS MODULE EXISTS
--------------------------------------------------------------------------

`bet_status.segment_refusal` closed the hazard of grading a first-half total
against a whole-game score, and it closed it by refusing EVERY segment order.
That was the right first move -- a mis-graded row shows up in the P&L as skill,
an ungraded one shows up in the work list -- but it left the work list
permanent: `market_segments.SPORT_SEGMENTS` gives football `q1..q4/h1/h2` and
soccer `h1/h2`, the fetchers request them, Kalshi quotes `KXNCAAF1H` and
`1Q-4Q`, and nothing could ever settle one.

The actual for those segments is already in the feed the pollers read. ESPN's
scoreboard carries `competitors[].linescores[]` -- VERIFIED 2026-09-08 on
NCAAF 401858438 and NFL 401772830: `[{"value": 10.0, "displayValue": "10",
"period": 1}, ...]`, one entry per period played, absent periods absent. For
soccer the SCOREBOARD's `linescores` is `null` (verified on EPL 401879317,
2026-08-30) but the match SUMMARY's `header.competitions[0].competitors[]
.linescores` is `[{"displayValue": "3"}, {"displayValue": "1"}]` -- one entry
per half, no `period` key, in order. The soccer poller already fetches that
summary for every in-play and every newly finished match, so nothing new is
fetched; the value was in hand and discarded.

--------------------------------------------------------------------------
WHAT A SEGMENT MEANS, PER SPORT, AND THE OVERTIME DECISION
--------------------------------------------------------------------------

    football   q1..q4   that period alone
               h1       periods 1 + 2
               h2       periods 3 + 4 **AND EVERY OVERTIME PERIOD**
    soccer     h1       period 1 (stoppage time included -- it IS period 1)
               h2       period 2 only; extra time is NOT the second half

`h2` includes overtime because that is the sportsbook convention the orders
were priced under: second-half lines settle on all points scored after the
half, including OT, while fourth-quarter lines settle on the fourth quarter
alone. Grading `h2` as `q3 + q4` would settle a second-half over as LOST on a
game decided in OT. Consequently `h2` is only final when the GAME is final,
where `q4` is final the moment period 5 begins.

--------------------------------------------------------------------------
NAMED REFUSAL, NEVER A SILENT FULL-GAME GRADE
--------------------------------------------------------------------------

A record with no linescores -- a capture written before this shipped, a feed
that omitted them, a soccer box reused from a pre-change cache -- refuses as
`segment_actual_unavailable:<seg>`. It must not fall back to `home_score +
away_score`, which is exactly the wrong answer this whole path exists to stop.
A segment the sport does not play (`first5` on an NFL order) refuses as
`unsupported_segment:<seg>`, which is a JOIN defect and a different job.

The one permissive direction is inherited from `segment_refusal` and stated
there: an ABSENT or `full` segment means the whole game, because every
full-game order in the ledger's history carries no `segment` key at all.

This module returns the SCORE PAIR and the segment's own finality. It does not
grade: `game_line_view` translates spreads and moneylines (push handling and
the three-way half-point trick live there, once) and `resolve_bet_status`
decides won/lost/push. A total is `home + away` handed straight to the grader,
same as the full-game path.

Soccer's resolver calls `game_line_view` itself with `draw_possible=True`
rather than `segment_scores_view`: a first-half result is three-way exactly as
the match result is, and a level half is the DRAW outcome, not a push.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from syndicate.features.shared.bet_status import FULL_GAME_SEGMENT

__all__ = [
    "REASON_SEGMENT_ACTUAL_PREFIX",
    "order_segment",
    "is_segment_scoreboard_market",
    "segment_scores_view",
    # Per-period actuals (NFL / NCAAF / soccer).
    "FULL_GAME_SEGMENT",
    "REASON_UNSUPPORTED_SEGMENT_PREFIX",
    "SEGMENT_PERIODS",
    "segment_periods",
    "linescores_from_competitor",
    "segment_score_pair",
    "segment_is_final",
    "segment_actuals",
]

# The feed/box HAS the game but not the segment: a linescore short of inning N,
# a box whose quarters were not captured. Named with the segment so the work
# list says which reading is missing. `<prefix><segment>`, colon-separated so
# it cannot be confused with `segment_refusal`'s `..._not_<segment>`.
REASON_SEGMENT_ACTUAL_PREFIX = "segment_actual_unavailable:"

_TOTAL_MARKETS = frozenset({"totals", "totals_alt"})


def order_segment(order: Mapping[str, Any]) -> str:
    """The order's segment, `full` when absent -- the same reading
    `segment_refusal` takes, so the two cannot disagree on blank/whitespace."""
    if not isinstance(order, Mapping):
        return FULL_GAME_SEGMENT
    return str(order.get("segment") or "").strip().lower() or FULL_GAME_SEGMENT


def is_segment_scoreboard_market(sport: Any, market: Any) -> bool:
    """Can this market be graded from two segment scores alone?

    Totals, spreads and moneylines can. A player prop with a segment (a
    first-five strikeouts line) cannot -- the linescore carries no player
    stats -- and must keep refusing.
    """
    from syndicate.features.shared.game_line_bet import is_game_line_market

    token = str(market or "").strip().lower()
    return token in _TOTAL_MARKETS or is_game_line_market(sport, token)


def segment_scores_view(
    *,
    sport: Any,
    market: Any,
    order: Mapping[str, Any],
    segment: str,
    home_score: Any,
    away_score: Any,
    is_final: bool,
    started: bool,
    home_name: Any,
    away_name: Any,
    matched_by: str,
    expect_home: Any = None,
    expect_away: Any = None,
) -> dict[str, Any]:
    """The resolver dict for one segment order, or a named refusal.

    `is_final` here means THE SEGMENT is complete -- the fifth inning has
    ended, the first half is over -- not that the game is. A finished segment
    cannot change, so its bet is decidable while the game plays on.
    """
    from syndicate.features.shared.game_line_bet import (
        REASON_NO_SCORES,
        game_line_view,
    )

    home = _as_float(home_score)
    away = _as_float(away_score)
    if home is None or away is None:
        # Both or neither: a half-known segment score read as a shutout is
        # the same wrong verdict the whole-game readers refuse.
        return {"unavailable_reason": REASON_NO_SCORES}

    scoreboard = {
        "is_final": bool(is_final),
        "started": bool(started),
        "matched_by": matched_by,
        # THE SEGMENT, carried with the verdict so a graded row says which
        # portion of the game it was settled on. `home_score`/`away_score`
        # are the SEGMENT scores here, and `settled_segment` is what tells a
        # reader of the ledger not to check them against the final.
        "settled_segment": segment,
        "home_score": home,
        "away_score": away,
        "home_name": home_name,
        "away_name": away_name,
    }

    token = str(market or "").strip().lower()
    if token in _TOTAL_MARKETS:
        # No `game_line_view`: a total's side is already over/under and its
        # value is the combined score -- the same reasoning `bet_status_wnba`
        # states for the whole game.
        return {"current_value": home + away, **scoreboard}

    view = game_line_view(
        sport=sport,
        market=token,
        side=order.get("side"),
        line=order.get("line"),
        home_team=home_name,
        away_team=away_name,
        home_score=home,
        away_score=away,
        expect_home=expect_home,
        expect_away=expect_away,
        # A SEGMENT CAN END LEVEL, and the two-way market pushes when it
        # does. False here means "do not make plain `h2h` three-way";
        # `h2h_3_way` stays three-way by name regardless.
        draw_possible=False,
    )
    if view.get("unavailable_reason"):
        return view
    return {
        "current_value": view["current_value"],
        "side": view["side"],
        "line": view["line"],
        **scoreboard,
    }


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


# ---------------------------------------------------------------------------
# Per-period actuals: NFL / NCAAF / soccer. See the module docstring's second
# section. The score pair and the segment's OWN finality; grading stays with
# `game_line_view` / `resolve_bet_status`.
# ---------------------------------------------------------------------------

REASON_UNSUPPORTED_SEGMENT_PREFIX = "unsupported_segment:"

# Periods that make up each segment. `None` as the LAST element means "and
# every period after the previous one" -- the overtime rule for football's
# second half, see the module docstring.
_FOOTBALL_SEGMENTS: Mapping[str, tuple[int | None, ...]] = {
    "q1": (1,),
    "q2": (2,),
    "q3": (3,),
    "q4": (4,),
    "h1": (1, 2),
    "h2": (3, 4, None),
}
_SOCCER_SEGMENTS: Mapping[str, tuple[int | None, ...]] = {
    "h1": (1,),
    "h2": (2,),
}

SEGMENT_PERIODS: Mapping[str, Mapping[str, tuple[int | None, ...]]] = {
    "nfl": _FOOTBALL_SEGMENTS,
    "ncaaf": _FOOTBALL_SEGMENTS,
    "soccer": _SOCCER_SEGMENTS,
}


def segment_periods(sport: Any, segment: Any) -> tuple[int | None, ...] | None:
    """The periods a segment spans for this sport, or None if the sport does
    not play that segment. `full` is never answered here: it is not a segment."""
    table = SEGMENT_PERIODS.get(str(sport or "").strip().lower())
    if not table:
        return None
    return table.get(str(segment or "").strip().lower())


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return int(parsed)


def linescores_from_competitor(row: Any) -> list[int | None] | None:
    """ESPN `competitors[].linescores` -> per-period points, index 0 = period 1.

    Two shapes, both real (module docstring): the scoreboard's entries carry
    `value` and `period`; the soccer summary's carry only `displayValue` and
    rely on order. A `period` is honoured when present, so a feed that omits a
    period leaves a hole (`None`) rather than shifting every later period left
    -- a shifted linescore grades the wrong quarter with confidence.

    None when the row carries no linescores at all (soccer's scoreboard,
    pregame events); `[]` is never returned in its place, so a caller can tell
    "not provided" from "provided and empty".
    """
    if not isinstance(row, Mapping):
        return None
    entries = row.get("linescores")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return None
    out: list[int | None] = []
    for position, entry in enumerate(entries, start=1):
        if isinstance(entry, Mapping):
            value = entry.get("value")
            if value is None:
                value = entry.get("displayValue")
            period = _int_or_none(entry.get("period")) or position
        else:
            value = entry
            period = position
        points = _int_or_none(value)
        if period < 1:
            continue
        while len(out) < period:
            out.append(None)
        out[period - 1] = points
    return out


def _period_values(linescores: Any) -> list[int | None] | None:
    if not isinstance(linescores, Sequence) or isinstance(linescores, (str, bytes)):
        return None
    return [_int_or_none(v) if v is not None else None for v in linescores]


def _sum_periods(
    values: list[int | None], periods: tuple[int | None, ...]
) -> tuple[int | None, bool]:
    """(sum over the segment's periods present, whether any period was present).

    A period that is present-but-None while a LATER one is present is a data
    hole, and the sum is refused (None) rather than treated as zero.
    """
    open_ended = periods and periods[-1] is None
    fixed = [p for p in periods if p is not None]
    wanted = list(fixed)
    if open_ended and fixed:
        wanted.extend(range(fixed[-1] + 1, len(values) + 1))
    total = 0
    seen = 0
    for period in wanted:
        if period > len(values):
            break
        value = values[period - 1]
        if value is None:
            if any(period_after <= len(values) and values[period_after - 1] is not None for period_after in wanted if period_after > period):
                return None, True
            break
        total += value
        seen += 1
    return (total if seen else None), seen > 0


def segment_score_pair(
    sport: Any,
    segment: Any,
    *,
    home_linescores: Any,
    away_linescores: Any,
) -> tuple[int, int] | None:
    """`(home, away)` for the segment, or None when either side cannot answer.

    Both sides together, never one: a first-half total with the away half
    missing would read as a shutout, the same rule every full-game resolver
    states for its two scores.
    """
    periods = segment_periods(sport, segment)
    if not periods:
        return None
    home = _period_values(home_linescores)
    away = _period_values(away_linescores)
    if home is None or away is None:
        return None
    home_sum, home_seen = _sum_periods(home, periods)
    away_sum, away_seen = _sum_periods(away, periods)
    if home_sum is None or away_sum is None or not (home_seen and away_seen):
        return None
    return home_sum, away_sum


def segment_is_final(
    sport: Any,
    segment: Any,
    *,
    game_final: bool,
    period: Any,
    halftime: bool = False,
) -> bool:
    """Has this segment's clock run out?

    A game that is final closes every segment. Otherwise the CURRENT period
    closes any segment whose last period is behind it -- `q1` once period 2 is
    under way -- with `halftime` closing a segment that ends at period 2, since
    ESPN reports period 2 through the interval. An open-ended segment (football
    `h2`, overtime included) closes only with the game.
    """
    if game_final:
        return True
    periods = segment_periods(sport, segment)
    if not periods:
        return False
    if periods[-1] is None:
        return False
    last = periods[-1]
    current = _int_or_none(period)
    if current is not None and current > last:
        return True
    if halftime and last == 2 and str(sport or "").strip().lower() in ("nfl", "ncaaf"):
        return True
    if halftime and last == 1 and str(sport or "").strip().lower() == "soccer":
        return True
    return False


def _is_halftime(record: Mapping[str, Any]) -> bool:
    tokens = " ".join(
        str(record.get(key) or "") for key in ("status", "status_name", "status_detail", "detail")
    ).lower()
    return "halftime" in tokens or "half time" in tokens or tokens.strip() == "ht"


def segment_actuals(sport: Any, segment: Any, record: Mapping[str, Any]) -> dict[str, Any]:
    """The segment's `{home_score, away_score, is_final, started}` from a
    captured game record, or a NAMED `{unavailable_reason}`.

    The record is the shape the sport's poller persists: `home_linescores` /
    `away_linescores` (per-period ints), `final`, and where available
    `period` / `status`. A record without linescores refuses by name -- see
    the module docstring on why it must never fall back to the game score.

    `started=False` is returned, without a refusal, when the game is in play
    and this segment's first period has not begun: a fourth-quarter total in
    the first quarter is not unanswerable, it is not yet asked. That maps to
    `resolve_bet_status`'s `not_started`, which is the honest state.
    """
    slug = str(sport or "").strip().lower()
    seg = str(segment or "").strip().lower()
    periods = segment_periods(slug, seg)
    if not periods:
        return {"unavailable_reason": f"{REASON_UNSUPPORTED_SEGMENT_PREFIX}{seg}"}

    game_final = bool(record.get("final"))
    in_progress = bool(record.get("in_progress")) or game_final
    home = _period_values(record.get("home_linescores"))
    away = _period_values(record.get("away_linescores"))
    if home is None or away is None:
        return {"unavailable_reason": f"{REASON_SEGMENT_ACTUAL_PREFIX}{seg}"}

    pair = segment_score_pair(slug, seg, home_linescores=home, away_linescores=away)
    if pair is None:
        first = periods[0]
        current = _int_or_none(record.get("period"))
        if not game_final and first is not None and (
            (current is not None and current < first) or (current is None and len(home) < first and len(away) < first and in_progress)
        ):
            # In play, and this segment has not begun. Not a data gap.
            return {"home_score": None, "away_score": None, "is_final": False, "started": False}
        return {"unavailable_reason": f"{REASON_SEGMENT_ACTUAL_PREFIX}{seg}"}

    return {
        "home_score": pair[0],
        "away_score": pair[1],
        "is_final": segment_is_final(
            slug, seg, game_final=game_final, period=record.get("period"), halftime=_is_halftime(record)
        ),
        "started": True,
    }
