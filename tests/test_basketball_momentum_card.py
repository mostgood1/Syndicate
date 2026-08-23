"""Chart data for the game card, and the reason soccer's labels are not reused.

**THE LOAD-BEARING TEST HERE IS `test_soccer_thresholds_would_be_inert`.** Every
other assertion checks that this module does what it says; that one records WHY
it exists, using the four values a real live WNBA game actually produced. Delete
the reasoning and someone will "unify" the two label paths and ship a chart that
says "Balanced" forever.
"""

from __future__ import annotations

from typing import Any

import pytest

from syndicate.features.shared.basketball_momentum_card import basketball_momentum_chart
from syndicate.features.shared.basketball_momentum_card import period_ticks
from syndicate.features.shared.basketball_momentum_card import regulation_seconds

# Captured from event 401857164 (NYL @ IND), 2026-08-22/23, on the seconds axis.
LIVE_CURRENTS = (-0.6679, -3.0349, -4.553, -1.3478)


def _block(current: float, *, as_of: float = 2207.0, series=None,
           supported: bool = True) -> dict[str, Any]:
    if series is None:
        series = [{"t": float(t), "v": float(v)} for t, v in
                  zip(range(0, 1260, 60), [0.5, -1.2, 2.1, 0.3, -3.0, 1.1, 4.2,
                                           -0.8, 2.2, -1.9, 0.4, 3.3, -2.7,
                                           1.5, -4.55, 0.9, 2.8, -1.1, 0.2,
                                           -3.4, current])]
    return {
        "schema": "basketball_momentum_v1", "supported": supported, "reason": None,
        "events": 198, "as_of_seconds": as_of, "as_of_possessions": 148.84,
        "pressure": {
            "seconds": {"half_life": 120.0, "as_of": as_of,
                        "current": current, "series": series},
            "possessions": {"half_life": 8.0, "as_of": 148.84,
                            "current": -1.4657, "series": series},
        },
        "scoring_narrator": {"events": 97, "seconds": {}},
    }


def _chart(current: float, **kw: Any):
    return basketball_momentum_chart(
        _block(current, **kw), league_code="wnba", home_abbr="IND", away_abbr="NYL"
    )


# ---------------------------------------------------------------------------
# WHY THIS MODULE EXISTS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("current", LIVE_CURRENTS)
def test_soccer_thresholds_would_be_inert_on_real_basketball_values(current) -> None:
    """**Soccer's 40/60/80 bands would render EVERY basketball game "Balanced".**

    Those bands are FotMob's 0-100 scale, fitted against measured goal-rate
    lift. Basketball's `current` is an unbounded weighted sum, and these four
    values are what a real live WNBA game produced. All are far below 40, so
    reusing the bands gives a feature that renders, never errors, and says the
    same thing forever -- the neutral-default trap in its display form.

    This module therefore labels DIRECTION and never strength.
    """
    assert abs(current) < 40.0, "premise: real values sit far below soccer's lowest band"

    chart = _chart(current)
    assert chart["label"] != "Balanced"
    assert chart["label"] in {"IND pressure", "NYL pressure", "Level"}
    # And it must never carry a strength adjective.
    for adjective in ("shading", "on top", "pressing hard", "strong", "weak"):
        assert adjective not in chart["label"].lower()


def test_the_payload_declares_its_scale_uncalibrated() -> None:
    """Anything downstream that wants bands has to trip over this first."""
    assert _chart(-1.3478)["scale"] == "uncalibrated_relative_to_game_peak"


# ---------------------------------------------------------------------------
# Per-league axis -- soccer's 5400 would be wrong on all three
# ---------------------------------------------------------------------------

def test_regulation_seconds_is_per_league() -> None:
    assert regulation_seconds("wnba") == 2400.0      # 4 x 10
    assert regulation_seconds("nba") == 2880.0       # 4 x 12
    assert regulation_seconds("ncaab") == 2400.0     # 2 x 20
    assert regulation_seconds("nba") != 5400.0       # soccer's constant


def test_period_ticks_follow_the_league_not_a_fixed_half() -> None:
    assert period_ticks("wnba") == [25.0, 50.0, 75.0]
    assert period_ticks("ncaab") == [50.0]           # two halves, one boundary


def test_now_x_places_the_game_correctly_on_its_own_axis() -> None:
    """A chart that fills the width at minute 15 exactly as at minute 39 tells
    you nothing about where in the game you are -- soccer's own stated bug."""
    chart = _chart(-1.3478, as_of=1200.0,
                   series=[{"t": 0.0, "v": 1.0}, {"t": 1200.0, "v": -1.3478}])
    assert chart["now_x"] == 50.0                    # halfway through 2400s
    assert chart["points"][-1]["x"] == 50.0


# ---------------------------------------------------------------------------
# Direction and the level band
# ---------------------------------------------------------------------------

def test_positive_current_is_the_home_side() -> None:
    chart = _chart(4.55)
    assert chart["label"] == "IND pressure"
    assert chart["side_is_home"] is True
    assert chart["side_is_away"] is False


def test_negative_current_is_the_away_side() -> None:
    chart = _chart(-4.55)
    assert chart["label"] == "NYL pressure"
    assert chart["side_is_away"] is True
    assert chart["side_is_home"] is False


def test_a_near_zero_reading_is_level_and_takes_no_side() -> None:
    chart = _chart(0.01)
    assert chart["label"] == "Level"
    assert chart["side_is_home"] is False
    assert chart["side_is_away"] is False


# ---------------------------------------------------------------------------
# None, never an empty chart
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("block", [
    None,
    {},
    {"supported": False, "reason": "no pressure events in the play feed yet"},
    {"supported": True, "pressure": None},
    {"supported": True, "pressure": {"seconds": {"series": [], "current": 0.0}}},
    {"supported": True, "pressure": {"seconds": {"series": [{"t": 0, "v": 1}], "current": None}}},
])
def test_nothing_to_draw_returns_none_not_a_flat_line(block) -> None:
    """A flat line at zero and "no data yet" look identical on a canvas, and
    only one of them is a game state."""
    assert basketball_momentum_chart(
        block, league_code="wnba", home_abbr="IND", away_abbr="NYL"
    ) is None


# ---------------------------------------------------------------------------
# The template's contract
# ---------------------------------------------------------------------------

def test_emits_every_field_the_shared_template_reads() -> None:
    """`_game_card_generic.html` reads these by name; a missing one renders
    blank rather than raising, which is how a chart goes silently wrong."""
    chart = _chart(-1.3478)
    for key in ("label", "side_is_home", "side_is_away", "home_abbr", "away_abbr",
                "events", "points", "now_x", "goals"):
        assert key in chart, f"template reads mom.{key}"
    assert all({"x", "y"} <= set(p) for p in chart["points"])


def test_score_marks_are_empty_by_design() -> None:
    """Soccer marks ~3 goals. This game had 97 narrator events; 97 marks is a
    second, noisier chart drawn on top of the first."""
    assert _chart(-1.3478)["goals"] == []


def test_y_is_normalised_into_the_unit_range() -> None:
    chart = _chart(-1.3478)
    assert all(-1.0 <= p["y"] <= 1.0 for p in chart["points"])
    assert max(abs(p["y"]) for p in chart["points"]) == pytest.approx(1.0)


def test_the_possessions_axis_is_selectable() -> None:
    """Both axes are published; Phase C decides which to display."""
    chart = basketball_momentum_chart(
        _block(-1.3478), league_code="wnba", home_abbr="IND", away_abbr="NYL",
        axis="possessions",
    )
    assert chart is not None
    assert chart["label"] == "NYL pressure"
