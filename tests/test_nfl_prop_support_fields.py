"""NFL prop projections publish the SUPPORT their artifact already carries.

Measured 2026-10-16 on the served board: **0 of 705** NFL prop rows carried any
support field, and **188 of 206** ceiling-rejected prop rows had none -- so
`_MODEL_EDGE_MAX_POINTS` (a 15-point MAGNITUDE bound) was the only gate
available. With no support on the row, a 49-point "edge" off a rotational
player's near-empty season is indistinguishable from a real one: Braelon Allen
projected 3.8 against a 15.5 receiving-yards line (edge -49.93) while the
accepted prop population sits +7.85% ABOVE its line.

The values were never missing. The fleet artifact
`nfl_prop_projections_2026_wk6.json` carries `sample_games` on **1,094 of 1,094**
rows and `projected_sd` on 785, and the price ladder in the SAME function reads
both off the same `entry`. They were simply not copied onto the projection.

These tests drive the real `attach_nfl_prop_projections` over artifact rows
shaped exactly like the fleet's, so a regression in the copy -- or in anything
downstream that filters published projection keys -- fails here.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.nfl.props import (  # noqa: E402
    _NFL_PROP_MARKET_TO_STAT,
    _nfl_prop_join_market_key,
)
from syndicate.features.shared.nfl_prop_projections import (  # noqa: E402
    NflPropProjectionIndex,
    attach_nfl_prop_projections,
)

#: A real fleet artifact row's field set (A.J. Brown, wk6), with the numbers
#: changed to a yardage stat so `projected_sd` is exercised. Keeping the exact
#: key set matters: the defect was a copy omission, so a fixture inventing its
#: own shape could pass while production still dropped the fields.
ARTIFACT_ROW = {
    "game_id": "New York Jets|New England Patriots",
    "market": "receiving yards::braelon allen",
    "period": "full_game",
    "entity": "Braelon Allen",
    "sim_projection": 0.0607,
    "projected_value": 3.8,
    "sim_source": "nfl_season_rate",
    "projected_sd": 4.6129,
    "sample_games": 14,
    "rate_source": "current_season_rolling",
    "player_id_source": "current_season",
    "player_team": "NYJ",
    "player_team_source": "current_season",
}

LABEL = next(k for k, v in _NFL_PROP_MARKET_TO_STAT.items() if v == "receiving_yards")


def _grid_row(line=15.5, player="Braelon Allen"):
    return {
        "kind": "prop",
        "market": LABEL,
        "player_name": player,
        "line": line,
        "side": "over",
        "home_team": "New England Patriots",
        "away_team": "New York Jets",
    }


def _attach(artifact_row, line=15.5, player="Braelon Allen"):
    """Index the artifact row under the module's OWN join key, then attach."""
    key = _nfl_prop_join_market_key("receiving_yards", player, line)
    index = NflPropProjectionIndex(
        entries={key: artifact_row}, season=2026, week=6, row_count=1
    )
    row = _grid_row(line=line, player=player)
    coverage = attach_nfl_prop_projections([row], index)
    return row.get("projection"), coverage


# ---------------------------------------------------------------------------
# the fields reach the published projection
# ---------------------------------------------------------------------------

def test_the_projection_publishes_both_support_fields():
    projection, coverage = _attach(ARTIFACT_ROW)
    assert coverage["rows_with_projection"] == 1, coverage
    assert projection is not None
    assert projection["sample_games"] == 14
    assert projection["projected_sd"] == pytest.approx(4.6129)


def test_the_support_comes_from_the_ENTRY_and_not_a_constant():
    """Reachability, the way `model_engine_standard.md` requires: off != on.

    A hard-coded value would pass the test above. Two different entries must
    produce two different published values, and an entry WITHOUT the fields
    must publish None rather than a default that reads as real support.
    """
    rich, _ = _attach({**ARTIFACT_ROW, "sample_games": 3, "projected_sd": 1.25})
    assert rich["sample_games"] == 3
    assert rich["projected_sd"] == pytest.approx(1.25)

    bare = {k: v for k, v in ARTIFACT_ROW.items()
            if k not in ("sample_games", "projected_sd")}
    thin, _ = _attach(bare)
    assert thin["sample_games"] is None
    assert thin["projected_sd"] is None


def test_zero_games_stays_ZERO_and_absent_stays_NONE():
    """THE distinction the coercion exists for.

    `int(x or 0)` -- the shape used for the price ladder two lines below the
    copy -- maps BOTH an absent sample and a genuine zero onto 0. A consumer
    gating on support would then treat "we never recorded a sample" as "this
    player has played zero games", which is the permissive direction and
    exactly what this repo's standing rule forbids.
    """
    zero, _ = _attach({**ARTIFACT_ROW, "sample_games": 0})
    assert zero["sample_games"] == 0
    assert zero["sample_games"] is not None

    absent = {k: v for k, v in ARTIFACT_ROW.items() if k != "sample_games"}
    none_row, _ = _attach(absent)
    assert none_row["sample_games"] is None


def test_a_bool_is_not_a_sample_count():
    """`isinstance(True, int)` is True in Python, so the guard is load-bearing."""
    weird, _ = _attach({**ARTIFACT_ROW, "sample_games": True})
    assert weird["sample_games"] is None


def test_the_support_survives_the_LINE_REPRICE_path():
    """The reprice branch rebuilds `entry` as {**base, sim_projection}, so the
    support must survive it too. A line the artifact never stored takes that
    path, and it is the branch that produced 74 rows on the fleet 2026-10-05.

    The entry is keyed at the line the ARTIFACT stored (15.5) while the grid
    asks for one it never stored (21.5): `_nfl_prop_join_market_key` includes
    the line, so keying both at the same value would match directly and this
    test would silently assert nothing about reprice.
    """
    stored_key = _nfl_prop_join_market_key("receiving_yards", "Braelon Allen", 15.5)
    index = NflPropProjectionIndex(
        entries={stored_key: ARTIFACT_ROW}, season=2026, week=6, row_count=1
    )
    row = _grid_row(line=21.5)
    coverage = attach_nfl_prop_projections([row], index)
    projection = row.get("projection")
    assert coverage["rows_with_projection"] == 1, coverage
    assert projection.get("line_repriced") is True, "expected the reprice branch"
    assert projection["sample_games"] == 14
    assert projection["projected_sd"] == pytest.approx(4.6129)


# ---------------------------------------------------------------------------
# the fields are USABLE as a gate -- the point of publishing them
# ---------------------------------------------------------------------------

def test_a_low_support_row_is_now_distinguishable_from_a_real_edge():
    """The measured defect, as a test.

    Braelon Allen: projected 3.8 against a 15.5 line is a 0.245 ratio while the
    accepted population sits at 1.0785. Before this change nothing on the row
    said the projection rested on a near-empty season. Now a consumer can read
    the sample and the spread and decide, instead of inferring from the edge's
    magnitude alone.
    """
    projection, _ = _attach(ARTIFACT_ROW)
    assert projection["projected"] == pytest.approx(3.8)
    assert projection["sample_games"] is not None
    assert projection["projected_sd"] is not None
    # the support is present ALONGSIDE the provenance already carried, so a
    # reader can tell a thin current-season rate from a prior-season fallback
    assert projection["rate_source"] == "current_season_rolling"
