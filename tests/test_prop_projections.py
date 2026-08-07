"""S3 / L1-B -- the sim's projections joined to market lines.

Covers the two things that make this honest rather than decorative: that a
projection is never invented when the sim cannot answer, and that edge is
measured against a NO-VIG market probability rather than a raw book price.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.shared.prop_projections import (
    PropProjectionIndex,
    attach_projections,
    load_prop_projections,
    starter_ids_from_roster_snapshots,
)


def _index_with_pitcher():
    index = PropProjectionIndex()
    index.ingest_game(
        {
            "pitcher_props": {
                "111": {
                    # 10 sims: outs 15,16,17,18,19,20,21,22,23,24
                    "outs_dist": {str(v): 1 for v in range(15, 25)},
                    "outs_mean": 19.5,
                }
            }
        },
        pitcher_names={"111": "Paul Skenes"},
    )
    return index


def _index_with_hitter():
    index = PropProjectionIndex()
    index.ingest_game(
        {
            "hitter_props_likelihood_topn": {
                "total_bases_2plus": [
                    {"name": "Seiya Suzuki", "p_tb_2plus": 0.51, "p_tb_2plus_cal": 0.445, "tb_mean": 1.646}
                ]
            },
            "hitter_hr_likelihood_all": {
                "overall": [{"name": "Aaron Judge", "p_hr_1plus": 0.19, "p_hr_1plus_cal": 0.17, "hr_mean": 0.21}]
            },
        }
    )
    return index


def test_pitcher_probability_comes_from_the_distribution_not_a_normal():
    index = _index_with_pitcher()
    result = index.project(player_name="Paul Skenes", market="outs", line=17.5)
    # 18..24 of 15..24 are over 17.5 -> 7/10
    assert result["model_prob_over"] == 0.7
    assert result["projected"] == 19.5
    assert result["source"] == "pitcher_distribution"


def test_pitcher_join_needs_the_roster_name_map():
    """`starter_names` is keyed by SIDE while `pitcher_props` is keyed by ID,
    and nothing links them. Guessing from dict order would give one starter the
    other's distribution -- a confident wrong number beside a real price."""
    index = PropProjectionIndex()
    index.ingest_game({"pitcher_props": {"111": {"outs_dist": {"18": 1}, "outs_mean": 18}}})
    assert index.project(player_name="Paul Skenes", market="outs", line=17.5) is None


def test_calibrated_probability_is_preferred_over_raw():
    index = _index_with_hitter()
    result = index.project(player_name="Seiya Suzuki", market="batter_total_bases", line=1.5)
    assert result["model_prob_over"] == 0.445   # the _cal value, not 0.51
    assert result["projected"] == 1.646


def test_a_whole_number_line_on_a_threshold_market_returns_nothing():
    """"Over 2.0 total bases" carries push mass that an N-plus bucket cannot
    express. A blank cell is honest; answering the wrong question is not."""
    index = _index_with_hitter()
    assert index.project(player_name="Seiya Suzuki", market="batter_total_bases", line=2.0) is None


def test_home_runs_only_answers_the_half_line_it_has():
    index = _index_with_hitter()
    assert index.project(player_name="Aaron Judge", market="batter_home_runs", line=0.5) is not None
    # 355 real rows on 2026-07-12 asked for HR over 1.5/2.5; the sim has only a
    # 1-or-more bucket, so those must come back empty rather than guessed.
    assert index.project(player_name="Aaron Judge", market="batter_home_runs", line=2.5) is None


def test_unknown_player_and_market_return_nothing():
    index = _index_with_pitcher()
    assert index.project(player_name="Nobody At All", market="outs", line=17.5) is None
    assert index.project(player_name="Paul Skenes", market="not_a_market", line=1.5) is None


def _grid_row(over_price, under_price, **overrides):
    row = {
        "market": "batter_total_bases",
        "player_name": "Seiya Suzuki",
        "line": 1.5,
        "sides": ["over", "under"],
        "consensus": {"over": over_price, "under": under_price},
        "best": {"over": {"price": over_price}, "under": {"price": under_price}},
    }
    row.update(overrides)
    return row


def test_edge_is_measured_against_a_NO_VIG_probability():
    """#238's finding: comparing a model probability against a raw book price
    overstates edge by roughly half the hold (median 6.25%, so ~3.1 points)."""
    index = _index_with_hitter()
    # -110/-110 is 52.38% each side, 4.76% hold -> no-vig is exactly 50%.
    rows = [_grid_row(-110, -110)]
    attach_projections(rows, index)
    projection = rows[0]["projection"]
    assert projection["market_fair_prob_over"] == 0.5
    # model 0.445 vs fair 0.500 -> -5.5 points, NOT the -2.9 a vigged
    # comparison against 52.38% would have produced.
    assert projection["edge_vs_market_pct"] == -5.5


def test_a_one_sided_market_gets_a_projection_but_no_edge():
    index = _index_with_hitter()
    rows = [_grid_row(-110, None, sides=["over"], consensus={"over": -110})]
    coverage = attach_projections(rows, index)
    assert rows[0]["projection"]["model_prob_over"] == 0.445
    assert rows[0]["projection"]["edge_vs_market_pct"] is None
    # "the sim has a view" and "we can price that view honestly" are different
    # claims and the coverage report separates them.
    assert coverage["rows_with_projection"] == 1
    assert coverage["rows_with_edge"] == 0


def test_coverage_counts_every_row_now_that_game_markets_project():
    """Was player-only. Game markets (h2h/spreads/totals) are projected too, so
    the denominator is every row -- renaming it would have been the safer half
    of this change; both keys are emitted so nothing reading the old one breaks,
    but `rows_considered` is the honest name."""
    index = _index_with_hitter()
    rows = [_grid_row(-110, -110), {"market": "h2h", "player_name": None, "sides": ["home"]}]
    coverage = attach_projections(rows, index)
    assert coverage["rows_considered"] == 2
    assert coverage["rows_with_projection"] == 1      # the h2h row has no sim behind it here
    assert coverage["pct_projected"] == 50.0


def test_a_pregame_projection_is_not_priced_against_a_live_market():
    """The sim's payloads are generated before first pitch. Once a game starts
    the market re-prices on the actual state and the model does not, so the
    difference is the SCORE, not an edge.

    Found on 2026-07-12: an event with commence 16:07 carried book quotes at
    17:35 (away -500) while the sim still said 0.495 -- a +23-point "edge" on a
    coin-flip game, and game-market edges spreading -55 to +54 on moneylines
    where books are sharpest.
    """
    index = _index_with_hitter()
    for state in ("live", "final", "in_progress"):
        rows = [_grid_row(-110, -110, game={"state": state})]
        attach_projections(rows, index)
        projection = rows[0]["projection"]
        assert projection["model_prob_over"] == 0.445        # still projected
        assert projection["edge_vs_market_pct"] is None      # but not priced
        assert state in projection["edge_unavailable_reason"]


def test_a_pregame_game_still_gets_an_edge():
    index = _index_with_hitter()
    rows = [_grid_row(-110, -110, game={"state": "pregame"})]
    attach_projections(rows, index)
    assert rows[0]["projection"]["edge_vs_market_pct"] == -5.5


def test_roster_snapshot_reader_extracts_both_starters():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "roster_0_MIL_at_PIT_pk1_g1.json"
        path.write_text(
            json.dumps(
                {
                    "away": {"starter": {"id": 694819, "name": "Jacob Misiorowski"}},
                    "home": {"starter": {"id": 694973, "name": "Paul Skenes"}},
                }
            ),
            encoding="utf-8",
        )
        mapping = starter_ids_from_roster_snapshots(tmp)
    assert mapping == {"694819": "Jacob Misiorowski", "694973": "Paul Skenes"}


def test_a_missing_snapshot_directory_is_not_an_error():
    # Roster snapshots are patchy on a local mirror by design. Absent means
    # pitcher props do not project; it must never mean a crash or a guess.
    assert starter_ids_from_roster_snapshots("/no/such/dir") == {}
    with TemporaryDirectory() as tmp:
        index = load_prop_projections(Path(tmp) / "missing.json")
    assert index.games == 0
