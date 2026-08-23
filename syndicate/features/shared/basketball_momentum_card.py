"""Turn a captured basketball momentum block into CHART DATA for a game card.

Consumed by `templates/shared/_game_card_generic.html` via
`game["shared_momentum"]`, the same slot soccer fills. The template already
draws the inline SVG for any sport that fills it, so this is wiring rather than
a new chart -- and until now **nothing in the repo filled that slot except
soccer**, so basketball momentum has been captured to disk since 2026-08-22
23:19Z and displayed nowhere.

## WHAT IS DELIBERATELY NOT COPIED FROM SOCCER: THE STRENGTH LABELS

`soccer/cards.py::_momentum_chart` grades `current` into "shading it" / "on
top" / "pressing hard" at 40/60/80. Those numbers are FotMob's OWN 0-100 scale,
and they were fitted -- a 2026-08-22 holdout over 5,552 matches measured
goal-rate lift per band (<40: no lift at all; 60-80: 1.19x; 80+: 1.23x). That
docstring then says, in as many words, that the bands **must not be reused**
against a different, unbounded scale.

Basketball's `current` is exactly that: an unbounded weighted sum. Real values
captured from a live WNBA game on 2026-08-22 were **-0.67, -3.03, -4.55,
-1.35**. Every one of them is "<40", so soccer's own thresholds would render
literally every basketball game as "Balanced" forever -- a feature that is
inert while looking like it works, which is the failure `model_engine_
standard.md` exists to name.

**SO THE LABEL HERE STATES A DIRECTION AND NEVER A STRENGTH.** No adjective
implies how much, because Phase C has not measured a single band for
basketball, and soccer has just demonstrated how that goes wrong in the other
direction: its production ESPN-commentary proxy was found to carry NO signal at
any half-life from 30s to 1800s. A confident adjective on an unvalidated scale
is a stronger claim than the data supports.

The chart SHAPE is the honest part and is what carries the information at a
glance. That is what this emits.

## NO SCORE MARKS, unlike soccer's goal marks

Soccer marks goals on the trace because a goal is the rare event the build-up
is meant to precede, so the two together make the panel checkable by eye. The
same game had **97 narrator (scoring) events**. Ninety-seven marks is not a
readable annotation, it is a second, noisier chart drawn on top of the first.
`goals` is emitted empty so the template's loop is a no-op.
"""

from __future__ import annotations

from typing import Any, Mapping

from syndicate.features.shared.basketball_momentum import _LEAGUE_PERIODS

# Below this share of the game's own peak, the sides are called level. This is a
# RELATIVE reading -- "flat against this game's own range" -- not a claim that
# any absolute value means anything, which is the distinction the module
# docstring exists to protect.
_LEVEL_FRACTION = 0.15


def regulation_seconds(league_code: str) -> float:
    """Full regulation in seconds, per league. NOT a constant.

    Soccer hardcodes 5400. WNBA is 2400 (4x10), NBA 2880 (4x12), NCAAB 2400
    (2x20) -- so a shared constant would put the "now" line in the wrong place
    on two of the three, and a chart whose x-axis lies about where you are in
    the game loses half of what the panel is for.
    """
    rules = _LEAGUE_PERIODS.get(str(league_code or "").strip().lower())
    if rules is None:
        return 2400.0
    return float(rules["quarter_minutes"]) * float(rules["regulation_periods"]) * 60.0


def period_ticks(league_code: str) -> list[float]:
    """Period boundaries as x-percentages, for the eye to anchor on.

    Soccer emits a single `half_x`. Basketball has three interior boundaries in
    a four-quarter league and one in a two-half league, and which is which is
    exactly what tells you whether a run happened early or late.
    """
    rules = _LEAGUE_PERIODS.get(str(league_code or "").strip().lower())
    if rules is None:
        return [25.0, 50.0, 75.0]
    periods = int(float(rules["regulation_periods"]))
    return [round(100.0 * i / periods, 2) for i in range(1, periods)]


def basketball_momentum_chart(
    block: Mapping[str, Any] | None,
    *,
    league_code: str,
    home_abbr: str,
    away_abbr: str,
    axis: str = "seconds",
) -> dict[str, Any] | None:
    """Chart data, or None when there is nothing honest to draw.

    None rather than an empty chart: a flat line at zero and "no data yet" look
    identical on a canvas, and only one of them is a game state.
    """
    if not isinstance(block, Mapping) or block.get("supported") is not True:
        return None
    pressure = block.get("pressure")
    if not isinstance(pressure, Mapping):
        return None
    axis_block = pressure.get(axis)
    if not isinstance(axis_block, Mapping):
        return None

    series = axis_block.get("series")
    current = axis_block.get("current")
    if not isinstance(series, list) or not series or current is None:
        return None

    points_raw: list[tuple[float, float]] = []
    for point in series:
        if not isinstance(point, Mapping):
            continue
        try:
            points_raw.append((float(point.get("t") or 0.0), float(point.get("v") or 0.0)))
        except (TypeError, ValueError):
            continue
    if not points_raw:
        return None

    full = regulation_seconds(league_code) if axis == "seconds" else max(
        1e-6, float(block.get("as_of_possessions") or 0.0)
    )
    peak = max(1e-6, max(abs(v) for _, v in points_raw))

    try:
        current_value = float(current)
    except (TypeError, ValueError):
        return None

    # NORMALISED AGAINST THIS GAME'S OWN PEAK, so the label says "who is ahead
    # on pressure right now, relative to how this game has swung" and makes no
    # cross-game claim it cannot support.
    relative = abs(current_value) / peak
    if relative < _LEVEL_FRACTION or current_value == 0.0:
        side = None
        label = "Level"
    elif current_value > 0.0:
        side = home_abbr
        label = f"{home_abbr} pressure"
    else:
        side = away_abbr
        label = f"{away_abbr} pressure"

    return {
        "label": label,
        "side_is_home": side is not None and side == home_abbr,
        "side_is_away": side is not None and side == away_abbr,
        "home_abbr": home_abbr,
        "away_abbr": away_abbr,
        "events": block.get("events") or 0,
        "points": [
            {"x": round(min(100.0, 100.0 * t / full), 2), "y": round(v / peak, 4)}
            for t, v in points_raw
        ],
        "now_x": round(min(100.0, 100.0 * (points_raw[-1][0] or 0.0) / full), 2),
        # Soccer's single half tick, kept for template compatibility, plus the
        # real per-league boundaries.
        "half_x": 50.0,
        "period_ticks": period_ticks(league_code),
        # Empty BY DESIGN -- see the module docstring. Ninety-seven marks is not
        # an annotation.
        "goals": [],
        # **A SCALE NOBODY HAS CALIBRATED, said out loud in the payload.**
        # Anything downstream that wants to grade this into bands has to notice
        # this first. Phase C has measured no bands for basketball.
        "scale": "uncalibrated_relative_to_game_peak",
    }
