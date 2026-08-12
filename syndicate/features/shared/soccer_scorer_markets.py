"""First/last goal scorer probabilities, derived from the sim (`#368`).

Measured on the live board 2026-08-11: `player_first_goal_scorer` (823 rows) and
`player_last_goal_scorer` (454 rows) both at **0.0% coverage** -- 1,277 rows, the
single largest unprojected block in soccer -- while `player_goal_scorer_anytime`
ran at 16.2% off the same artifact.

`soccer_projections` left them out on purpose, and its reasoning was sound as far
as it went: "anytime is not first, and reusing the anytime probability would
overstate every one of those rows." Correct. But a Poisson race is not reuse --
it is a transformation with a stated model, and the sim supplies exactly the
quantity it needs.

THE DERIVATION
--------------
Treat goals as a Poisson process. The sim gives per-player
`anytime_scorer_probability`, so that player's goal rate is

    lambda_p = -ln(1 - P_anytime(p))

For competing Poisson sources the first arrival belongs to source p with
probability lambda_p / Lambda, and the match produces any goal at all with
probability 1 - exp(-Lambda). So

    P(p scores first) = (lambda_p / Lambda) * (1 - exp(-Lambda))

LAST scorer takes the SAME value. A homogeneous Poisson process is symmetric
under time reversal, so the last arrival has the same source distribution as the
first. Football rates do rise late in matches, but that inhomogeneity is common
to all players on the pitch and cancels out of the RELATIVE shares -- which is
all this expression uses. Stated here because it is an assumption, not a fact.

LAMBDA COMES FROM THE MATCH, NOT FROM THE PLAYERS. This is the part that decides
whether the numbers are honest. Reconciled across 55 matches with player rows:

    sum(lambda_p) vs the sim's own total_distribution.mean
      mean diff -0.176   max |diff| 1.573

Some fixtures agree to four decimals; others are short by up to 1.57 goals
because their player list is incomplete. Anchoring on `sum(lambda_p)` would make
the shares sum to 1 by construction and inflate every listed player on exactly
the fixtures with missing players -- silently, and worst where the data is
weakest. Anchoring on the match's stated mean instead leaves the missing players'
share UNALLOCATED, which is the honest representation of not knowing.

`attributable_share` travels with the result so a consumer can see how much of
the match's goal rate the listed players actually account for.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

# Below this, the listed players account for so little of the match's goal rate
# that their first-scorer shares are dominated by whoever is missing.
_MIN_ATTRIBUTABLE_SHARE = 0.30


def _prob(value: Any) -> float | None:
    try:
        if value is None:
            return None
        p = float(value)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= p < 1.0):
        # 1.0 implies an infinite rate; treat as unusable rather than clamping to
        # a huge lambda that would swamp every other player in the match.
        return None
    return p


def player_goal_rate(anytime_probability: Any) -> float | None:
    """lambda_p implied by P(anytime scorer), under the Poisson model."""
    p = _prob(anytime_probability)
    if p is None or p <= 0.0:
        return None
    return -math.log(1.0 - p)


def scorer_race(
    player_rows: Iterable[Mapping[str, Any]],
    *,
    match_expected_goals: float | None,
) -> dict[str, Any]:
    """First/last scorer probabilities for one match.

    Returns `{"by_player": {norm_name: prob}, "attributable_share": float,
    "lambda_total": float, "usable": bool}`.
    """
    rates: dict[str, float] = {}
    listed_total = 0.0
    for row in player_rows or ():
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("player_name") or "").strip()
        rate = player_goal_rate(row.get("anytime_scorer_probability"))
        if not name or rate is None:
            continue
        # A player appearing twice would otherwise double-count into Lambda.
        rates[name] = rate
        listed_total += rate

    stated = None
    try:
        if match_expected_goals is not None:
            stated = float(match_expected_goals)
    except (TypeError, ValueError):
        stated = None

    # The match's own expected total is authoritative. It can never be LESS than
    # what the listed players already imply, so take the larger of the two --
    # otherwise a stale or rounded match mean would push shares above 1.
    lambda_total = max(stated, listed_total) if stated is not None else listed_total
    if lambda_total <= 0.0:
        return {"by_player": {}, "attributable_share": 0.0, "lambda_total": 0.0, "usable": False}

    any_goal = 1.0 - math.exp(-lambda_total)
    by_player = {
        name: round((rate / lambda_total) * any_goal, 6) for name, rate in rates.items()
    }
    attributable = listed_total / lambda_total
    return {
        "by_player": by_player,
        "attributable_share": round(attributable, 4),
        "lambda_total": round(lambda_total, 4),
        # Same precision as the per-player values: rounded to 4dp this can sit
        # a hair BELOW their sum, and a consumer checking the invariant
        # "no player share exceeds P(any goal)" would see a false violation.
        "any_goal_probability": round(any_goal, 6),
        "usable": attributable >= _MIN_ATTRIBUTABLE_SHARE,
    }
