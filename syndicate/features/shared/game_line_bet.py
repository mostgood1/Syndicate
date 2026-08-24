"""Turn a team-relative game line into the over/under shape the grader speaks.

--------------------------------------------------------------------------
WHY THIS EXISTS
--------------------------------------------------------------------------

MEASURED 2026-08-24 on the settlement line, every cycle:

    SETTLED date=2026-08-23 orders=171 graded=0 already_graded=71
      ungraded={'unmapped_market': 80, ...}
    UNMAPPED_MARKETS {'spreads': 41, 'h2h': 31, 'h2h_3_way': 6, 'spreads_alt': 2}

Player props graded; game lines never did. Not because the arithmetic was
missing -- `resolve_bet_status` has always known how to compare a value to a
line -- but because a game line is not phrased in its vocabulary. It asks for a
`side` of over/under and a numeric `line`; a spread arrives as
`side="Texas Rangers", line=-1.5` and a moneyline as `side="Levante", line=None`.
`_side_direction("Texas Rangers")` returns None, so every one of them refused
with `unknown_side` or `no_line` before any grading could happen.

So this is a TRANSLATION, not a second grader. Everything here converts a
team-relative bet into `(current_value, side, line)` and hands it back to the
one function that decides won/lost/push. A second copy of that decision is how
`book_grid` drifted; there is exactly one.

--------------------------------------------------------------------------
THE HALF-POINT IS THE WHOLE TRICK
--------------------------------------------------------------------------

`resolve_bet_status` settles equality as a PUSH. That is right for a spread
(a two-run line landing on a two-run margin returns the stake) and wrong for a
three-way market, where a draw is a loss for both teams and a win for the draw.

Rather than teach the grader a second comparator, the line is moved off the
integer grid, exactly as a sportsbook does it:

    three-way, team side   margin      > 0.5     draw (0) loses, no push possible
    three-way, draw side   |margin|    < 0.5     only 0 wins, no push possible

Both are strict inequalities against a value that is always a whole number, so
equality never arises and the push branch is unreachable by construction. No
new parameter, no new branch in the grader, and the impossible case is
impossible rather than merely unhandled.

--------------------------------------------------------------------------
A DRAW IS A PROPERTY OF THE SPORT, NOT OF THE MARKET NAME
--------------------------------------------------------------------------

The obvious rule -- "`h2h` is two-way, `h2h_3_way` is three-way" -- is wrong,
and production says so. Soccer's own odds history carries:

    market=h2h|side=Draw|book=fanduel        (Levante v Real Betis)

So `h2h` IS three-way in soccer while being two-way in baseball. Keying the
behaviour on the market name would grade a soccer draw as a push on the
favourite, returning a stake that was lost. `draw_possible` is therefore passed
in by the caller, which knows its sport, and the market name only ever
STRENGTHENS the conclusion (`h2h_3_way` is three-way in every sport).

--------------------------------------------------------------------------
SIGN CONVENTION, WRITTEN DOWN BECAUSE IT IS EASY TO INVERT
--------------------------------------------------------------------------

A spread is quoted as a handicap ADDED to the team's score: "Texas -1.5" wins
when Texas's own margin beats 1.5. So the line handed to the grader is the
NEGATED quote, and the value is the margin from the bet's team:

    line = -quoted_point            Texas -1.5 -> line  1.5, margin must exceed it
                                    Texas +1.5 -> line -1.5, may lose by up to 1.5

Getting this backwards grades every favourite as an underdog and vice versa,
and would do so silently -- the numbers stay plausible. It is unit-tested in
both directions for that reason.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "is_game_line_market",
    "game_line_view",
    "REASON_UNKNOWN_GAME_MARKET",
    "REASON_SIDE_NOT_A_TEAM",
    "REASON_NO_SCORES",
    "REASON_NO_SPREAD_LINE",
]

# Named refusals. Each one sends the next person somewhere different, which is
# the whole reason they are not a single `cannot_grade`.
REASON_UNKNOWN_GAME_MARKET = "unmapped_game_market"
REASON_SIDE_NOT_A_TEAM = "side_not_a_team_in_this_game"
REASON_NO_SCORES = "no_team_scores"
REASON_NO_SPREAD_LINE = "no_spread_line"

# Markets decided by the SCOREBOARD rather than by a player's line, and by the
# score of ONE side rather than the combined total (`totals` is already handled
# by each sport's resolver and is deliberately not here -- it needs no team
# resolution at all).
_MONEYLINE_MARKETS = frozenset({"h2h", "h2h_3_way", "moneyline"})
_SPREAD_MARKETS = frozenset({"spreads", "spreads_alt", "spread", "handicap"})
# Explicitly three-way whatever the sport. See the module docstring: the
# converse does NOT hold, so this set can only add three-way-ness, never
# remove it.
_ALWAYS_THREE_WAY = frozenset({"h2h_3_way"})

_DRAW_TOKENS = frozenset({"draw", "tie", "x", "the draw"})


def _canonical_market(sport: Any, market: Any) -> str:
    from syndicate.features.shared.market_keys import canonical_market_key

    raw = str(market or "").strip().lower()
    # `canonical_market_key` is the single authority on market names (`#224`).
    # Four private market tables drifted apart in this codebase in one day; a
    # fifth here would be the same mistake.
    return str(canonical_market_key(sport, raw) or raw)


def is_game_line_market(sport: Any, market: Any) -> bool:
    canonical = _canonical_market(sport, market)
    return canonical in _MONEYLINE_MARKETS or canonical in _SPREAD_MARKETS


def _as_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().replace("+", "")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _is_draw_side(side: Any) -> bool:
    return str(side or "").strip().lower() in _DRAW_TOKENS


def _margin_for_side(
    *, sport: Any, side: Any, home_team: Any, away_team: Any,
    home_score: float, away_score: float,
) -> float | None:
    """Score difference from the perspective of the team the bet is on.

    Team names go through `team_aliases.canonical_team`, never a local map --
    it is the single club resolver (`#218`), and two normalisers that disagree
    is a silent mismatch rather than an error anyone sees.
    """
    from syndicate.features.shared.team_aliases import canonical_team

    wanted = canonical_team(sport, side)
    home = canonical_team(sport, home_team)
    away = canonical_team(sport, away_team)
    if wanted is None:
        return None
    if home is not None and wanted == home:
        return home_score - away_score
    if away is not None and wanted == away:
        return away_score - home_score
    # The side names a club, but not one of THIS game's two. Refused rather
    # than defaulted to either team: picking one produces a confident verdict
    # on the wrong bet, which is worse than no verdict at all.
    return None


def game_line_view(
    *,
    sport: Any,
    market: Any,
    side: Any,
    line: Any,
    home_team: Any,
    away_team: Any,
    home_score: Any,
    away_score: Any,
    draw_possible: bool,
) -> dict[str, Any]:
    """`{current_value, side, line}` for the grader, or `{unavailable_reason}`.

    Pure: no clock, no feed, no artifact. Every sport's resolver supplies the
    two scores and this decides nothing about whether they are final -- that
    stays with the resolver, which is the only thing that knows the game state.
    """
    canonical = _canonical_market(sport, market)
    is_moneyline = canonical in _MONEYLINE_MARKETS
    is_spread = canonical in _SPREAD_MARKETS
    if not (is_moneyline or is_spread):
        return {"unavailable_reason": REASON_UNKNOWN_GAME_MARKET}

    home = _as_float(home_score)
    away = _as_float(away_score)
    if home is None or away is None:
        # A half-known score is not a score. Refusing both together stops a
        # missing away total being read as a shutout.
        return {"unavailable_reason": REASON_NO_SCORES}

    three_way = canonical in _ALWAYS_THREE_WAY or (is_moneyline and draw_possible)

    if is_moneyline and _is_draw_side(side):
        if not three_way:
            # A draw side on a market this sport cannot draw is not a bet we
            # can make sense of, and guessing at it is how a wrong verdict
            # gets written confidently.
            return {"unavailable_reason": REASON_SIDE_NOT_A_TEAM}
        # |margin| < 0.5 is true for a level score and for nothing else.
        return {
            "current_value": abs(home - away),
            "side": "under",
            "line": 0.5,
        }

    margin = _margin_for_side(
        sport=sport, side=side, home_team=home_team, away_team=away_team,
        home_score=home, away_score=away,
    )
    if margin is None:
        return {"unavailable_reason": REASON_SIDE_NOT_A_TEAM}

    if is_moneyline:
        # Two-way: level is a PUSH and the stake comes back (draw-no-bet, and
        # the sports where a tie is merely rare rather than impossible).
        # Three-way: level is a LOSS, and the half-point makes it one without
        # the grader needing to know the difference.
        return {
            "current_value": margin,
            "side": "over",
            "line": 0.5 if three_way else 0.0,
        }

    quoted = _as_float(line)
    if quoted is None:
        # A spread with no number is not gradeable and never will be. Named
        # separately from a moneyline's absent line, which is correct and
        # expected -- the two need opposite responses.
        return {"unavailable_reason": REASON_NO_SPREAD_LINE}
    # See the module docstring on the sign. The quote is a handicap added to
    # the team's score, so the margin must beat its negation.
    return {
        "current_value": margin,
        "side": "over",
        "line": -quoted,
    }
