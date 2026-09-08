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
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from syndicate.features.shared.bet_status import FULL_GAME_SEGMENT

__all__ = [
    "REASON_SEGMENT_ACTUAL_PREFIX",
    "order_segment",
    "is_segment_scoreboard_market",
    "segment_scores_view",
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
