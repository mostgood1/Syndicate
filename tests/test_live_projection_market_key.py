"""`#412` -- the live prop join keyed on a display grouping and matched nothing.

REPORTED FROM THE BOARD: "im not seeing proj/edge data on the live lines so make
sure we are carrying live projection, sim projection, and actual so far."

The join was not partially broken, it was totally broken, and its own
instrumentation said so on production 2026-08-13:

    rows_live_considered: 1385      live_games_in_snapshot: 7
    rows_live_projected:  0         snapshot_rows_indexed: 90
    miss_no_player:       0         miss_no_market_alias: 1385   <- all of them

`build_live_prop_index` keyed each snapshot row on `market`. But `market` is a
DISPLAY GROUPING, not a market -- measured the same day:

    market                prop                    rows
    hitter_props          hits                      39
    hitter_props          total_bases               29
    hitter_props          runs_scored                1
    hitter_total_bases    batter_total_bases        20
    hitter_rbis           batter_rbis               15

So `hitter_props` (a) collapsed four unrelated markets onto one key, colliding 70
rows against each other, and (b) matched no board market, because the board
speaks OddsAPI (`batter_hits`). The correct key was sitting in the next field the
whole time: `prop` is already the board's vocabulary.

THE CONTROL, run against one production snapshot and one production board:

    old keying -> rows_live_projected = 0
    new keying -> rows_live_projected = 41

Same snapshot, same rows, same index. Nothing else changed.
"""

from __future__ import annotations

from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
from syndicate.features.shared.live_projection_join import (
    attach_live_projections,
    build_live_prop_index,
)


def _snapshot(*props):
    return {
        "games": [
            {
                "status": {"abstract": "Live", "detailed": "In Progress"},
                "liveProps": list(props),
            }
        ]
    }


def _prop(player, market, prop_key, line, projection=0.8, actual=1.0):
    return {
        "playerName": player,
        "market": market,
        "prop": prop_key,
        "line": line,
        "liveProjection": projection,
        "modelProbOver": 0.42,
        "actualSoFar": actual,
        "selection": "Over",
    }


def _row(player, market, line, projection=None):
    return {
        "kind": "prop",
        "game": {"state": "live"},
        "player_name": player,
        "market": market,
        "line": line,
        "projection": dict(projection or {}),
    }


def test_the_grouping_field_does_not_decide_the_market():
    """The reported case. `hitter_props` must not be the key."""
    index = build_live_prop_index(
        _snapshot(_prop("Brandon Lowe", "hitter_props", "total_bases", 1.5))
    )
    grid = [_row("Brandon Lowe", "batter_total_bases", 1.5)]
    coverage = attach_live_projections(grid, index)
    assert coverage["rows_live_projected"] == 1, coverage


def test_one_grouping_covering_four_markets_does_not_collide():
    """`hitter_props` covered hits, total_bases, runs_scored and rbis at once.

    Keyed on the grouping, these four overwrite each other in the index and at
    most one survives -- so this asserts all four land, not merely that some do.
    """
    index = build_live_prop_index(
        _snapshot(
            _prop("Aaron Judge", "hitter_props", "hits", 0.5, projection=1.1),
            _prop("Aaron Judge", "hitter_props", "total_bases", 0.5, projection=2.2),
            _prop("Aaron Judge", "hitter_props", "runs_scored", 0.5, projection=3.3),
            _prop("Aaron Judge", "hitter_props", "rbis", 0.5, projection=4.4),
        )
    )
    grid = [
        _row("Aaron Judge", "batter_hits", 0.5),
        _row("Aaron Judge", "batter_total_bases", 0.5),
        _row("Aaron Judge", "batter_runs_scored", 0.5),
        _row("Aaron Judge", "batter_rbis", 0.5),
    ]
    coverage = attach_live_projections(grid, index)
    assert coverage["rows_live_projected"] == 4, coverage
    assert [r["projection"]["projected"] for r in grid] == [1.1, 2.2, 3.3, 4.4], (
        "the four markets crossed wires -- the grouping is still the key somewhere"
    )


def test_the_alias_map_joins_in_both_directions():
    """`_MARKET_ALIASES` was a one-way expansion and the snapshot speaks both.

    The same market arrived as `hits` on 39 rows and `batter_hits` on 6. A
    one-way map matches whichever side happens to hold the canonical name.
    """
    for snapshot_name in ("hits", "batter_hits"):
        index = build_live_prop_index(
            _snapshot(_prop("Mookie Betts", "hitter_props", snapshot_name, 1.5))
        )
        grid = [_row("Mookie Betts", "batter_hits", 1.5)]
        coverage = attach_live_projections(grid, index)
        assert coverage["rows_live_projected"] == 1, f"{snapshot_name}: {coverage}"


def test_a_batters_strikeouts_never_joins_a_pitchers():
    # The families must stay separate. Merging them would price a hitter's
    # strikeout prop off the pitcher's distribution, which joins and is wrong --
    # strictly worse than not joining.
    index = build_live_prop_index(
        _snapshot(_prop("Framber Valdez", "pitcher_props", "strikeouts", 5.5))
    )
    grid = [_row("Framber Valdez", "batter_strikeouts", 5.5)]
    coverage = attach_live_projections(grid, index)
    assert coverage["rows_live_projected"] == 0


def test_a_row_with_no_live_projection_is_not_marked_live_aware():
    """`modelProbOver` alone is NOT evidence the model saw the score.

    Measured 2026-08-13: 63 of 144 snapshot rows carried `modelProbOver` while
    `liveProjection`, `modelMean` and `actualSoFar` were all null -- a pregame
    probability sitting in a live-lens row. Indexing those marks them
    `live_aware`, which hands `live_edge_policy` exactly the pregame-vs-live
    edge it exists to suppress (`#340`: a +23-point "edge" on a coin flip).
    """
    prop = _prop("Max Muncy", "hitter_runs", "batter_runs_scored", 0.5)
    prop["liveProjection"] = None
    prop["actualSoFar"] = None
    index = build_live_prop_index(_snapshot(prop))
    assert index["rows_indexed"] == 0
    assert index["skipped_no_live_projection"] == 1

    grid = [_row("Max Muncy", "batter_runs_scored", 0.5)]
    attach_live_projections(grid, index)
    assert live_edge_unavailable_reason(grid[0]), "a pregame row gained a live edge"


def test_the_live_number_does_not_erase_the_sim_number():
    """All THREE numbers, which is what was actually asked for.

    The overlay used to write `projected` over the pregame value, so the board
    could never show the move from "we projected 2.27" to "now 1.8, with 1
    already in the book".
    """
    index = build_live_prop_index(
        _snapshot(_prop("Brandon Lowe", "hitter_props", "total_bases", 1.5,
                        projection=1.8, actual=1.0))
    )
    grid = [_row("Brandon Lowe", "batter_total_bases", 1.5,
                 projection={"projected": 2.274, "basis": "total_bases_2plus"})]
    attach_live_projections(grid, index)
    p = grid[0]["projection"]
    assert p["live_projected"] == 1.8
    assert p["sim_projected"] == 2.274, "the pregame projection was overwritten"
    assert p["actual_so_far"] == 1.0
    assert p["sim_basis"] == "total_bases_2plus"


def test_a_second_pass_does_not_record_the_live_number_as_the_sim_number():
    # The artifact is rebuilt every cycle over rows that may already carry an
    # overlay. Re-stamping would ratchet `sim_projected` toward the live value
    # and quietly erase the pregame baseline over the course of a game.
    index = build_live_prop_index(
        _snapshot(_prop("Brandon Lowe", "hitter_props", "total_bases", 1.5, projection=1.8))
    )
    grid = [_row("Brandon Lowe", "batter_total_bases", 1.5,
                 projection={"projected": 2.274, "basis": "total_bases_2plus"})]
    attach_live_projections(grid, index)
    attach_live_projections(grid, index)
    assert grid[0]["projection"]["sim_projected"] == 2.274


def test_the_snapshot_ceiling_is_reported():
    """A low count must be attributable without a second investigation.

    The lens indexes far fewer rows than the board carries (68 indexable against
    1336 live board rows). "The join is broken" and "the lens only covers this
    much" render identically as a small number and have opposite fixes.
    """
    prop = _prop("Max Muncy", "hitter_runs", "batter_runs_scored", 0.5)
    prop["liveProjection"] = None
    index = build_live_prop_index(
        _snapshot(prop, _prop("Brandon Lowe", "hitter_props", "total_bases", 1.5))
    )
    coverage = attach_live_projections([], index)
    assert coverage["snapshot_rows_seen"] == 2
    assert coverage["snapshot_rows_indexed"] == 1
    assert coverage["snapshot_skipped_no_live_projection"] == 1
