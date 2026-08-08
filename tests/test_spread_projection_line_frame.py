"""The spread projection must read the line in the AWAY frame (#262 fallout).

`#262` made the grid row's `line` canonical — always the away/over side's line —
so a row's line agrees with its own cells. `project_game_market` still negated
it for home, on the older contract that the line arrived in the home frame.

Measured on production 2026-08-08, one distribution evaluated at +/-1.5:

    line=+1.5 side=home -> 0.7386   (P(margin > -1.5); should be ~0.26)
    line=-1.5 side=home -> 0.2296   (P(margin > +1.5); should be ~0.74)

i.e. every home spread row carried its OPPOSITE line's probability. That fed
19-28 point "edges" and implied model views of 86-89% on games the market
priced near even.

The distribution below is symmetric and deliberately simple, so the assertions
are arithmetic rather than approximations:

    margin (home - away):  -2  -1   0  +1  +2
    weight:                 1   2   4   2   1     (total 10)
"""

from __future__ import annotations

from syndicate.features.shared.prop_projections import _SEGMENT_PAYLOADS, project_game_market

_SEGMENT_KEY = _SEGMENT_PAYLOADS["full"]

_DIST = {"-2": 1, "-1": 2, "0": 4, "1": 2, "2": 1}


class _Index:
    """Minimal stand-in for PropProjectionIndex's game lookup.

    `game_payloads` returns {segment_key: payload}; the caller picks the segment.
    """

    def __init__(self, payload, segment_key):
        self._payloads = {segment_key: payload}

    def game_payloads(self, **_kwargs):
        return self._payloads


def _project(side, line, index):
    return project_game_market(
        index,
        sport="mlb",
        home_team="St. Louis Cardinals",
        away_team="Colorado Rockies",
        market="spreads",
        selection=side,
        line=line,
        segment="full",
    )


def test_home_favourite_must_win_by_two(monkeypatch):
    """away +1.5 (canonical +1.5) means home is -1.5: home needs margin > 1.5.

    P(margin > 1.5) = 1/10. The pre-fix code returned P(margin > -1.5) = 7/10.
    """
    index = _Index({"run_margin_dist": _DIST}, _SEGMENT_KEY)
    projection = _project("home", 1.5, index)
    assert projection is not None
    assert projection["model_prob_over"] == 0.1


def test_home_underdog_may_lose_by_one(monkeypatch):
    """away -1.5 (canonical -1.5) means home is +1.5: home covers on margin > -1.5.

    P(margin > -1.5) counts -1, 0, +1, +2 = (2+4+2+1)/10 = 0.9. A margin of -1
    IS greater than -1.5 -- home losing by one still covers +1.5, which is the
    whole point of the half-run line and the thing an off-by-one here would hide.
    """
    index = _Index({"run_margin_dist": _DIST}, _SEGMENT_KEY)
    projection = _project("home", -1.5, index)
    assert projection is not None
    assert projection["model_prob_over"] == 0.9


def test_the_two_home_sides_are_not_swapped():
    """The exact defect: +1.5 and -1.5 returning each other's probability."""
    index = _Index({"run_margin_dist": _DIST}, _SEGMENT_KEY)
    plus = _project("home", 1.5, index)["model_prob_over"]
    minus = _project("home", -1.5, index)["model_prob_over"]
    assert plus < minus, "home -1.5 must be LESS likely than home +1.5"


def test_away_side_is_unchanged_by_the_fix():
    """The away branch already received the frame it wanted.

    away +1.5 covers when margin < 1.5 -> 9/10.
    """
    index = _Index({"run_margin_dist": _DIST}, _SEGMENT_KEY)
    assert _project("away", 1.5, index)["model_prob_over"] == 0.9


def test_the_two_sides_of_one_market_are_complementary():
    """away +1.5 and home -1.5 are the same market. Their probabilities must
    sum to 1 plus whatever push mass sits exactly on the line (none here, the
    line is a half-run)."""
    index = _Index({"run_margin_dist": _DIST}, _SEGMENT_KEY)
    home = _project("home", 1.5, index)["model_prob_over"]
    away = _project("away", 1.5, index)["model_prob_over"]
    assert round(home + away, 6) == 1.0
