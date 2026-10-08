"""A row's sim distribution, published as the producer's OWN pricing at nearby lines.

`[2026-10-08, user: "charts that show sim dispersion of the line" -- approved
mockup board 10, lane layer2-board-ui-redesign]`

The chart under each prop draws P(stat in bucket) from consecutive points of
`projection["ladder"] = [[threshold, p_over], ...]`. The points come from the
SAME function that priced the row (Poisson / negative binomial / blended normal /
empirical sim ladder, whichever the producer uses), evaluated at the row's line
and a few lines either side -- so the chart is the model's own distribution and
not a reconstruction from the mean. The page draws it only when the ladder's
value at the row's line reproduces the row's published probability.

Display metadata only: nothing that scores, gates or sizes reads `ladder`.
"""

from __future__ import annotations

import math
from typing import Any, Callable

#: Thresholds either side of the line. 3 gives 7 points / 8 buckets.
_POINTS_EACH_SIDE = 3
#: Continuous stats step in fractions of the stat's SD.
_CONTINUOUS_STEP_SD = 0.5


def price_ladder(
    price_over: Callable[[float], Any],
    line: Any,
    *,
    sd: Any = None,
    allow_negative: bool = False,
) -> list[list[float]] | None:
    """`[[threshold, P(over threshold)], ...]` ascending, or None.

    Count stats (no `sd`): half-integer thresholds around the line -- each bucket
    is one whole value. Continuous stats: the line +/- k * 0.5 SD.
    """
    try:
        line_value = float(line)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(line_value):
        return None
    try:
        sd_value = float(sd) if sd is not None else None
    except (TypeError, ValueError):
        sd_value = None
    if sd_value is not None and sd_value > 0 and math.isfinite(sd_value):
        step = sd_value * _CONTINUOUS_STEP_SD
        thresholds = [round(line_value + i * step, 3) for i in range(-_POINTS_EACH_SIDE, _POINTS_EACH_SIDE + 1)]
    else:
        centre = math.floor(line_value) + 0.5
        # Counts stop at -0.5; a MARGIN (home minus away) runs both ways.
        thresholds = [centre + i for i in range(-_POINTS_EACH_SIDE, _POINTS_EACH_SIDE + 1) if allow_negative or centre + i >= -0.5]
        if line_value not in thresholds:
            thresholds = sorted(set(thresholds + [line_value]))
    points: list[list[float]] = []
    for threshold in thresholds:
        # A threshold the producer cannot price is SKIPPED, not fatal: soccer
        # and MLB tables exist only at fixed rungs (soccer assists 0.5/1.5,
        # MLB hitter "N+" lists). The row's OWN line must price, and the chart
        # needs at least three points.
        try:
            p = price_over(threshold)
        except Exception:  # noqa: BLE001 -- a display ladder must never break pricing
            p = None
        try:
            p = float(p) if p is not None else None
        except (TypeError, ValueError):
            p = None
        if p is None or not math.isfinite(p):
            if abs(threshold - line_value) < 1e-9:
                return None
            continue
        points.append([threshold, round(min(1.0, max(0.0, p)), 4)])
    if len(points) < 3:
        return None
    # Monotone non-increasing in the threshold; a pricing function that is not
    # (a blend artefact) is published as-is but clipped so buckets stay >= 0.
    for i in range(1, len(points)):
        if points[i][1] > points[i - 1][1]:
            points[i][1] = points[i - 1][1]
    return points


__all__ = ["price_ladder"]
