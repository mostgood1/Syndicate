"""The live-prop probability carry read the RAW rows with NORMALISED key names.

`5bab0685` shipped 2026-08-30 to carry the MC re-sim's `liveModelProbOver`
across the cards merge, and it has never carried anything. Measured on
production 2026-09-23, 00:00-01:30Z, 10 MLB games live:

    producer   LIVE_MC_PRICED  rows=8, 19, 17, 28, 36, 45 across six games
    published  live {rows 1,050, with_live_projection 1,030, with_live_prob 0}
    logs       NEITHER `LIVE_PROB_CARRIED` NOR `LIVE_PROB_CARRY_IMPORT_FAILED`
               emitted, while `LIVE_MC_PRICED` was -- so `by_key` was empty and
               the function returned through a SILENT early return.

Why it was empty: the two sides of the merge speak different spellings.
`_game_from_report_row` puts the RAW report rows into `live_row["liveProps"]`
untouched, while `_live_props_from_card` runs its rows through
`_normalize_live_prop_row`. The vendored producer writes
`live_model_prob_over` (`flask_frontend.py:14763`), plus `player_name` /
`batter_name` and `threshold` for the key fields -- every one of which the
normaliser maps and the carry did not.
"""

from __future__ import annotations

from syndicate.features.mlb.live_lens import _carry_live_probability

# Exactly the producer's spelling: snake_case throughout.
RAW_MC_ROW = {
    "player_name": "Aaron Judge",
    "market": "batter_home_runs",
    "prop": "batter_home_runs",
    "selection": "Over",
    "threshold": 0.5,
    "live_model_prob_over": 0.41,
    "live_edge": 7.25,
    "live_projection": 0.62,
}

# What the cards side looks like after `_normalize_live_prop_row`.
CARD_ROW = {
    "playerName": "Aaron Judge",
    "market": "batter_home_runs",
    "prop": "batter_home_runs",
    "selection": "Over",
    "line": 0.5,
    "liveProjection": 0.62,
    "liveModelProbOver": None,
    "liveEdge": None,
}


def test_the_probability_is_carried_from_a_raw_producer_row():
    out = _carry_live_probability([dict(CARD_ROW)], {"gamePk": 823494, "liveProps": [dict(RAW_MC_ROW)]})
    assert out[0]["liveModelProbOver"] == 0.41


def test_its_own_edge_travels_with_it():
    out = _carry_live_probability([dict(CARD_ROW)], {"gamePk": 823494, "liveProps": [dict(RAW_MC_ROW)]})
    assert out[0]["liveEdge"] == 7.25


def test_a_camelcase_source_row_still_works():
    # Not every producer is the vendored one; the normaliser handles both and
    # this must not regress the spelling that already worked in tests.
    camel = {"playerName": "Aaron Judge", "market": "batter_home_runs",
             "prop": "batter_home_runs", "selection": "Over", "line": 0.5,
             "liveModelProbOver": 0.33}
    out = _carry_live_probability([dict(CARD_ROW)], {"gamePk": 1, "liveProps": [camel]})
    assert out[0]["liveModelProbOver"] == 0.33


def test_a_card_row_with_no_counterpart_is_returned_untouched():
    other = dict(CARD_ROW, playerName="Juan Soto")
    out = _carry_live_probability([other], {"gamePk": 1, "liveProps": [dict(RAW_MC_ROW)]})
    assert out[0]["liveModelProbOver"] is None


def test_an_existing_probability_is_never_overwritten():
    already = dict(CARD_ROW, liveModelProbOver=0.9)
    out = _carry_live_probability([already], {"gamePk": 1, "liveProps": [dict(RAW_MC_ROW)]})
    assert out[0]["liveModelProbOver"] == 0.9


def test_the_failing_path_now_reports_itself(capsys):
    # The whole reason this went unnoticed: the counter sat AFTER the early
    # return, so an empty `by_key` printed nothing at all.
    _carry_live_probability([dict(CARD_ROW)], {"gamePk": 823494, "liveProps": []})
    line = capsys.readouterr().out
    assert "LIVE_PROB_CARRIED" in line
    assert "carried=0" in line
    assert "source_rows=0" in line


def test_the_success_path_reports_what_it_carried(capsys):
    _carry_live_probability([dict(CARD_ROW)], {"gamePk": 823494, "liveProps": [dict(RAW_MC_ROW)]})
    line = capsys.readouterr().out
    assert "carried=1" in line
    assert "source_with_prob=1" in line


def test_a_source_row_without_a_probability_is_counted_but_not_carried(capsys):
    bare = {k: v for k, v in RAW_MC_ROW.items() if k != "live_model_prob_over"}
    out = _carry_live_probability([dict(CARD_ROW)], {"gamePk": 1, "liveProps": [bare]})
    assert out[0]["liveModelProbOver"] is None
    assert "source_with_prob=0" in capsys.readouterr().out


def test_no_card_rows_is_a_no_op():
    assert _carry_live_probability([], {"gamePk": 1, "liveProps": [dict(RAW_MC_ROW)]}) == []
