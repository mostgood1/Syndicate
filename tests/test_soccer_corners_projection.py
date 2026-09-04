"""Soccer corners get a model view -- from the CORNERS mean, and no further.

MEASURED on the served board 2026-09-04: `alternate_totals_corners` was **186
rows, 0 with a model, 0 with an edge** -- the largest unmodelled market in
soccer's candidate pool -- while `soccer/cards.py` had been rendering
`Proj {total:.1f} | Line {market:g}` for corners all along. The sim had the
number; the board was the surface that could not see it.

TWO THINGS THIS MUST NOT DO, and both have a test:

  1. **Price corners with the goals model.** `market_keys.py` records the
     near-miss: "Over 4.5 corners?" and a soccer goals total at 4.5 look
     identical once the unit is dropped, so a careless join "would have priced a
     corners market [with] our goals model and the join would have looked clean".
  2. **Turn a mean into a probability.** `distribution.py` accumulates
     `mean_home_corners` / `mean_away_corners` and divides -- there is no corners
     distribution, no SD, no per-line over-probability. `edge_vs_line` in corner
     units is the honest contract, the same one WNBA uses, and these rows stay
     UNBUYABLE because `_model_edge_for` refuses to add stat units to an EV
     percentage.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.soccer_projections import (  # noqa: E402
    SoccerProjectionIndex,
    attach_soccer_projections,
)


def _index(**match):
    idx = SoccerProjectionIndex()
    base = {
        "match_id": "m1", "league": "epl",
        "home_team": "Arsenal", "away_team": "Chelsea",
        "volume_projection": {"home_corners": 6.1, "away_corners": 4.3},
        "total_distribution": {"mean": 2.7},
    }
    base.update(match)
    idx.by_teams[("arsenal", "chelsea")] = base
    idx.by_event["m1"] = base
    idx.matches = 1
    return idx


def _row(market, line, side="over"):
    return {
        "sport": "soccer", "league": "epl", "market": market, "line": line,
        "home_team": "Arsenal", "away_team": "Chelsea", "sides": [side, "under"],
        "side": side, "consensus": {"over": -110, "under": -110},
    }


def _project(idx, row):
    rows = [row]
    attach_soccer_projections(rows, idx)
    return rows[0].get("projection")


def test_corners_now_carry_a_model_view():
    """6.1 + 4.3 = 10.4 against a 9.5 line."""
    proj = _project(_index(), _row("alternate_totals_corners", 9.5))
    assert proj is not None, "186 rows had no projection at all before this"
    assert proj.get("basis") == "corners_mean"
    assert proj.get("edge_vs_line") is not None


def test_the_number_is_the_CORNERS_mean_not_the_goals_mean():
    """THE DISCRIMINATING TEST, and the one `market_keys` warns about. The match
    carries a goals total of 2.7 and a corners total of 10.4. A branch reading
    the wrong block would price a corners line with the goals model and look
    entirely clean doing it."""
    proj = _project(_index(), _row("alternate_totals_corners", 9.5))
    edge = proj["edge_vs_line"]
    assert abs(edge - (10.4 - 9.5)) < 1e-6, f"edge {edge} is not the CORNERS mean"
    assert abs(edge - (2.7 - 9.5)) > 1e-6, "this is the GOALS mean -- wrong model"


def test_it_publishes_NO_probability_and_therefore_no_priced_edge():
    """A mean presented as a probability is a fabricated edge. These rows must
    stay unbuyable until the engine produces a corners DISTRIBUTION."""
    proj = _project(_index(), _row("alternate_totals_corners", 9.5))
    assert proj.get("model_prob_over") is None
    assert proj.get("edge_vs_market_pct") is None


def test_a_match_with_no_corners_block_gets_NOTHING_not_a_zero():
    """Absent must stay absent. A 0.0 corners projection would read as "the sim
    expects no corners", which is a claim, not a gap."""
    idx = _index(volume_projection={})
    assert _project(idx, _row("alternate_totals_corners", 9.5)) is None


def test_the_goals_total_is_untouched():
    """Regression guard: the branch must not capture plain totals."""
    proj = _project(_index(), _row("totals", 2.5))
    assert proj is not None
    assert proj.get("basis") != "corners_mean"
