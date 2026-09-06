"""Is this bet winning RIGHT NOW -- against the live game, not against the line.

WHAT THIS IS NOT, because I built the other thing first and called it tracking.
`position_marks` answers "has the market moved toward us", which is a proxy for
whether the PICK was good. It cannot tell you that Steven Kwan has 1 total base
with two innings left and the Over 1.5 is behind. Those are different questions
and this module is the second one.

--------------------------------------------------------------------------
MONOTONICITY IS THE WHOLE DESIGN, AND IGNORING IT MAKES A TRACKER THAT LIES
--------------------------------------------------------------------------

A counting stat only ever goes UP. Total bases, hits, points, strikeouts, runs
scored -- none of them can fall. That single fact splits every over/under bet
into two completely different situations, and a tracker that renders them the
same way is worse than no tracker:

    Over 1.5, currently 2   -> **WON**. Permanently, in the 3rd inning. Nothing
                               that happens later can undo it.
    Under 1.5, currently 0  -> NOT won. It is merely still alive, and it stays
                               merely alive until the final whistle.

Both would read as "winning" under a naive `current vs line` comparison, and one
of them is a settled fact while the other is a coin still in the air. So:

  - On a monotone market, crossing the line DECIDES the bet -- `won` for an
    over, `lost` for an under -- and the status never changes again.
  - Not having crossed it is `live_ahead`/`live_behind`, never `won`, until the
    game is final.

Spreads and moneylines are NOT monotone: a margin swings both ways, so they are
undecided until final no matter how far ahead the score is. A five-run lead in
the 2nd is `live_ahead` and nothing more.

--------------------------------------------------------------------------
EVERY UNRESOLVABLE BET IS NAMED
--------------------------------------------------------------------------

Same discipline as `clv_join`, `order_clv` and `position_marks`: a bet whose
current value cannot be resolved gets a reason, never a guess and never a
default. "We cannot see this bet" and "this bet is behind" must never share a
rendering -- the first is a data problem to fix and the second is a bet to
sweat, and a tracker that blurs them will be trusted for exactly as long as it
takes to notice.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

__all__ = [
    "STATUS_WON",
    "STATUS_LOST",
    "STATUS_LIVE_AHEAD",
    "STATUS_LIVE_BEHIND",
    "STATUS_NOT_STARTED",
    "is_monotone_market",
    "resolve_bet_status",
    "statuses_for_orders",
    "bet_status_report_line",
    "FULL_GAME_SEGMENT",
    "REASON_SEGMENT_PREFIX",
    "segment_refusal",
]

STATUS_WON = "won"
STATUS_LOST = "lost"
STATUS_LIVE_AHEAD = "live_ahead"
STATUS_LIVE_BEHIND = "live_behind"
STATUS_LIVE_TIED = "live_tied"
STATUS_NOT_STARTED = "not_started"

REASON_NO_CURRENT_VALUE = "no_current_value"
REASON_NO_LINE = "no_line"
REASON_UNKNOWN_SIDE = "unknown_side"

# Markets whose value can only INCREASE. Listed explicitly rather than inferred
# from a name pattern: `spreads` and `totals` both end in "s" and one of them is
# monotone, so any heuristic here is a coin flip on the cases that matter.
#
# A market absent from this list is treated as NON-monotone, which is the
# conservative direction: it can then only ever be decided at final, so an
# unknown market family is under-called rather than declared won early.
_MONOTONE_MARKETS = frozenset(
    {
        # Game scoring totals -- runs/points scored only accumulate.
        "totals",
        "totals_alt",
        "totals_h1",
        "totals_h2",
        # MLB hitter counting stats.
        "batter_hits",
        "batter_total_bases",
        "batter_home_runs",
        "batter_rbis",
        "batter_runs_scored",
        "batter_singles",
        "batter_doubles",
        "batter_triples",
        "batter_walks",
        "batter_strikeouts",
        "batter_stolen_bases",
        "batter_hits_runs_rbis",
        # MLB pitcher counting stats. BOTH SPELLINGS, and that is the point:
        # `market_keys` canonicalises `pitcher_strikeouts` to `strikeouts` and
        # `pitcher_outs` to `outs` (`#224`), and the board emits the canonical
        # form -- so the prefixed names alone matched nothing the board
        # produces. MEASURED 2026-08-23: `is_monotone_market("strikeouts")` was
        # False, which silently switched the early-decision mechanism OFF for
        # every MLB pitcher prop. Not a missing feature: an inert one, with
        # passing tests, reporting `live_behind` on bets that were already won.
        #
        # This function takes no sport, so it cannot canonicalise on lookup.
        # `test_every_monotone_name_is_the_one_the_board_emits` is what stops
        # the two vocabularies drifting apart again.
        "strikeouts",
        "pitcher_strikeouts",
        "hits_allowed",
        "pitcher_hits_allowed",
        "earned_runs",
        "pitcher_earned_runs",
        "walks_allowed",
        "pitcher_walks",
        "outs",
        "pitcher_outs",
        # Basketball counting stats.
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_steals",
        "player_blocks",
        "player_turnovers",
        "player_points_rebounds",
        "player_points_assists",
        "player_rebounds_assists",
        "player_points_rebounds_assists",
    }
)


def is_monotone_market(market: Any) -> bool:
    """Can this market's value only go up?

    Exact match, never a prefix: `totals` is monotone and `totals_alt` is too,
    but `spreads` is not while `spreads_alt` shares its prefix. Prefix matching
    here would declare a spread bet WON in the second inning.
    """
    return str(market or "").strip().lower() in _MONOTONE_MARKETS


# THE SEGMENT A WHOLE-GAME ACTUAL CAN GRADE, AND THE ONLY ONE.
#
# The board spells a segment bet as TWO fields -- `market="totals"` plus
# `segment="first5"` -- and `market_segments.segment_market_keys` is where that
# split is made (`out[f"{base}_{suffix}"] = (seg, canonical)`, the canonical
# market being the bare name). Every stage downstream keeps them apart:
# `odds_book_quotes._KEY_FIELDS`, `book_grid._INSTANCE_FIELDS`,
# `kalshi_board_join._match_key` and `execution_ledger`'s row all carry
# `segment`.
#
# THE GRADERS DO NOT READ IT. Measured 2026-09-05 across every status resolver:
# `bet_status_wnba` refuses a non-full segment and is the ONLY one that does.
# mlb / ncaaf / nfl / soccer each take `market` alone, match `"totals"`, and
# return the whole-game combined score -- so a first-five-innings UNDER 3.5 is
# compared against a nine-inning total of 8 and settles LOST, with confidence
# and without a log line. That is not an ungraded bet, it is a wrongly graded
# one, which is the more expensive direction: an ungraded row shows up in the
# work list, a mis-graded row shows up in the P&L as skill.
#
# It is live today, not hypothetical. Production `book_quotes` for 2026-09-04
# carried 21,714 `first5`, 5,549 `first3` and 3,343 `first1` MLB rows for such
# an order to be written from.
FULL_GAME_SEGMENT = "full"

# Named for the thing that is wrong -- the ACTUAL is whole-game -- rather than
# for the artifact it came from, because the cause is shared and the artifacts
# are not. `bet_status_wnba` says `final_box_is_full_game_not_h1` for the same
# refusal; that wording is kept where it is, since it is additionally true.
REASON_SEGMENT_PREFIX = "actual_is_full_game_not_"


def segment_refusal(
    order: Mapping[str, Any],
    *,
    reason_prefix: str = REASON_SEGMENT_PREFIX,
) -> dict[str, Any] | None:
    """`None` if this order may be graded off a whole-game actual, else a refusal.

    `reason_prefix` EXISTS FOR ONE CALLER AND SHOULD NOT GROW. `bet_status_wnba`
    already shipped this refusal, spelled `final_box_is_full_game_not_<seg>`, and
    that string is a recorded reading in `state_basketball.md`. Renaming it to
    unify the vocabulary would orphan that reading for a cosmetic gain -- the
    same trade `bet_status_ncaaf` declines when it keeps NFL's unprefixed
    `game_carries_no_scores`. New callers take the default.

    ABSENT MEANS `full`, AND THAT PERMISSIVE DEFAULT IS DELIBERATE -- it is the
    one direction this guard is allowed to be lenient in, and the reasoning has
    to be stated because the standing rule is the opposite ("unknown must not
    default permissive").

    Every full-game order ever written carries no `segment` key at all: the
    field was added for the board's quote rows, not retrofitted onto the
    ledger's history. Refusing on absence would therefore refuse THE ENTIRE
    BOOK rather than the segment rows -- taking grading to zero, which is
    precisely the failure `kalshi_catalogue` records paying for once already
    (a false positive on `KXNFLH2HWINS` would have taken the Kalshi order path
    to zero). A guard that can only fire on a value that is PRESENT and NOT
    `full` cannot make that mistake.

    The exposure this leaves is narrow and named: a segment row that loses its
    `segment` field somewhere upstream grades as full-game. That is a JOIN
    defect, not a grading one, and `execution_ledger` writes the field today
    (`:134`, `:268`, `:1117`), so nothing currently produces it.

    Call this at the TOP of a resolver, before the market check and before any
    artifact is read. Segment is permanently unanswerable from a whole-game
    actual, while a missing artifact is transient, and checking the transient
    condition first hides the structural one behind a reason that looks like it
    will fix itself -- the ordering rule `bet_status_wnba` states and paid for.
    """
    if not isinstance(order, Mapping):
        return None
    # STRIP BEFORE THE DEFAULT, not after. `str(x or "full")` leaves a
    # whitespace-only value intact -- `"  "` is truthy -- and the strip that
    # followed then produced `""`, which is not `"full"`, so the order refused
    # with `actual_is_full_game_not_` and no segment named. A refusal whose
    # reason has a blank where the cause goes is unreadable as a work item, and
    # it fires on a row that should have graded. Caught by
    # `test_absent_blank_and_full_all_grade["  "]`, not by review.
    segment = str(order.get("segment") or "").strip().lower() or FULL_GAME_SEGMENT
    if segment == FULL_GAME_SEGMENT:
        return None
    return {"unavailable_reason": f"{reason_prefix}{segment}"}


def _as_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().replace("+", "")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _side_direction(side: Any) -> int | None:
    """+1 for a bet that wants the value HIGH, -1 for one that wants it low."""
    token = str(side or "").strip().lower()
    if token in {"over", "o", "yes"}:
        return 1
    if token in {"under", "u", "no"}:
        return -1
    return None


def resolve_bet_status(
    *,
    market: Any,
    side: Any,
    line: Any,
    current_value: Any,
    is_final: bool = False,
    started: bool = True,
) -> dict[str, Any]:
    """Where one bet stands against the live value. Never guesses.

    Always returns a dict carrying `status` and `unavailable_reason`, so an
    absent verdict cannot silently read as "not considered" -- the contract
    `project_live_player_stat` keeps for the same reason.
    """
    out: dict[str, Any] = {
        "status": None,
        "current_value": None,
        "line": None,
        "margin": None,
        "monotone": is_monotone_market(market),
        "decided": False,
        "unavailable_reason": None,
    }

    if not started:
        out["status"] = STATUS_NOT_STARTED
        return out

    line_value = _as_float(line)
    if line_value is None:
        # A moneyline has no line, and this function is about lines. The caller
        # resolves those from the score itself.
        out["unavailable_reason"] = REASON_NO_LINE
        return out
    direction = _side_direction(side)
    if direction is None:
        out["unavailable_reason"] = REASON_UNKNOWN_SIDE
        return out
    current = _as_float(current_value)
    if current is None:
        # WE CANNOT SEE THIS BET. Distinct from being behind on it.
        out["unavailable_reason"] = REASON_NO_CURRENT_VALUE
        return out

    out["current_value"] = current
    out["line"] = line_value
    # Signed TOWARD the bet: positive always means "in our favour", whichever
    # side we took, so a single column reads correctly for overs and unders.
    out["margin"] = round((current - line_value) * direction, 4)

    if is_final:
        out["decided"] = True
        if current == line_value:
            # A push. Reported as its own thing rather than folded into either
            # outcome, because it returns the stake and is neither.
            out["status"] = STATUS_LIVE_TIED
        else:
            out["status"] = STATUS_WON if out["margin"] > 0 else STATUS_LOST
        return out

    if out["monotone"]:
        # THE DECIDING CASE. On a value that can only rise, crossing the line
        # settles the bet immediately and permanently -- an over is won, an
        # under is lost, and neither can be taken back by anything later in the
        # game.
        if current > line_value:
            out["decided"] = True
            out["status"] = STATUS_WON if direction > 0 else STATUS_LOST
            return out
        # Not crossed: an over is behind, an under is merely still alive. NOT
        # won -- it cannot be won until the game ends.
        out["status"] = STATUS_LIVE_BEHIND if direction > 0 else STATUS_LIVE_AHEAD
        return out

    # Non-monotone (spreads, and anything not listed): the value swings, so no
    # in-game lead decides anything.
    if out["margin"] > 0:
        out["status"] = STATUS_LIVE_AHEAD
    elif out["margin"] < 0:
        out["status"] = STATUS_LIVE_BEHIND
    else:
        out["status"] = STATUS_LIVE_TIED
    return out


def statuses_for_orders(
    orders: Sequence[Mapping[str, Any]],
    *,
    resolver: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Status for every order, plus counts. `resolver` supplies the live value.

    The resolver is injected rather than imported so this module stays free of
    every sport's live-feed shape, and so a sport whose feed is unavailable
    degrades to a named reason on its own orders instead of taking down the
    others.
    """
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    reasons: dict[str, int] = {}

    for order in orders:
        try:
            resolved = resolver(order) or {}
        except Exception as exc:  # pragma: no cover - resolver-specific
            resolved = {"unavailable_reason": f"resolver_error:{type(exc).__name__}"}

        if resolved.get("unavailable_reason"):
            reason = str(resolved["unavailable_reason"])
            reasons[reason] = reasons.get(reason, 0) + 1
            rows.append(
                {
                    "idempotency_key": order.get("idempotency_key"),
                    "position_key": order.get("position_key"),
                    "venue": order.get("venue"),
                    "sport": order.get("sport"),
                    "market": order.get("market"),
                    "side": order.get("side"),
                    "line": _as_float(order.get("line")),
                    "player_name": order.get("player_name"),
                    "status": None,
                    "unavailable_reason": reason,
                }
            )
            continue

        status = resolve_bet_status(
            market=order.get("market"),
            side=order.get("side"),
            line=order.get("line"),
            current_value=resolved.get("current_value"),
            is_final=bool(resolved.get("is_final")),
            started=bool(resolved.get("started", True)),
        )
        if status.get("unavailable_reason"):
            reason = str(status["unavailable_reason"])
            reasons[reason] = reasons.get(reason, 0) + 1
        else:
            counts[str(status["status"])] = counts.get(str(status["status"]), 0) + 1
        rows.append(
            {
                "idempotency_key": order.get("idempotency_key"),
                "position_key": order.get("position_key"),
                "venue": order.get("venue"),
                "sport": order.get("sport"),
                "market": order.get("market"),
                "side": order.get("side"),
                "player_name": order.get("player_name"),
                "stake_dollars": _as_float(order.get("fill_stake_dollars"))
                or _as_float(order.get("requested_stake_dollars")),
                **status,
                "projected": resolved.get("projected"),
            }
        )

    return {
        "orders": len(orders),
        "resolved": sum(counts.values()),
        "counts": dict(sorted(counts.items())),
        "reasons": dict(sorted(reasons.items())),
        # Decided-so-far, which is the number a reader actually wants at a
        # glance and would otherwise have to add up from `counts`.
        "decided": sum(1 for row in rows if row.get("decided")),
        "rows": rows,
    }


def bet_status_report_line(report: Mapping[str, Any]) -> str:
    """One log line. `logger.info` never reaches Render's collector -- print this."""
    counts = report.get("counts") or {}
    return (
        "[bet_status] BET_STATUS"
        f" orders={report.get('orders')}"
        f" resolved={report.get('resolved')}"
        f" decided={report.get('decided')}"
        f" won={counts.get(STATUS_WON, 0)}"
        f" lost={counts.get(STATUS_LOST, 0)}"
        f" ahead={counts.get(STATUS_LIVE_AHEAD, 0)}"
        f" behind={counts.get(STATUS_LIVE_BEHIND, 0)}"
        f" reasons={report.get('reasons')}"
    )
