"""`#412` display half -- the three numbers a live row carries must read apart.

"im not seeing proj/edge data on the live lines so make sure we are carrying
live projection, sim projection, and actual so far."

The join fix (`test_live_projection_market_key`) puts all three on the row. This
is the half that makes them legible, plus the one interaction that would have
quietly undermined it: the live overlay preserves the pregame projection's
fields, so `age_hours` describes the number that was REPLACED. Left alone, a
re-sim seconds old inherits a 26h-old pregame timestamp and renders with the
stale marker -- telling the reader to distrust the one number on the row that
actually knows the score.
"""

from __future__ import annotations

import pathlib

_TEMPLATE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "syndicate" / "templates" / "shared" / "layer1_board.html"
)


def _html() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


def test_a_live_projection_is_never_marked_stale():
    """The inherited-age trap, asserted directly."""
    html = _html()
    start = html.index("var isLive = onProj")
    body = html[start:start + 1400]
    assert "if (isLive) { projStale = false; }" in body, (
        "a live re-sim can inherit the pregame projection's age and render stale"
    )


def test_all_three_numbers_are_reachable():
    html = _html()
    assert "p.sim_projected" in html, "the pregame projection is not read"
    assert "p.actual_so_far" in html, "actual-so-far is not read"
    assert "p.live_aware" in html, "nothing distinguishes a live projection"


def test_the_actual_is_inline_not_only_in_a_tooltip():
    # On a live row the actual is the one number that is not a model output.
    # A projection of 1.80 means something different with 0 in the book than
    # with 2, and a tooltip is not read while scanning.
    html = _html()
    assert '<span class="l1-actual">' in html


def test_the_tooltip_names_which_number_is_which():
    # "1.80" alone does not say whether it is the live or the pregame number.
    html = _html()
    start = html.index("var projNote =")
    body = html[start:start + 600]
    assert '"live re-sim"' in body
    assert "pregame sim " in body
    assert " so far" in body


def test_a_live_projection_is_visually_distinct():
    """It is the only kind whose edge the live-edge policy allows on a live game.

    A live and a pregame projection rendering identically is what made the
    suppressed-edge column unreadable in the first place.
    """
    html = _html()
    assert "l1-live-proj" in html
    assert ".l1-live-proj {" in html, "the class is emitted but has no styling"
