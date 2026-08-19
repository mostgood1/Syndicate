"""WNBA Layer 1 projections — the sport was at 0.0% on every market.

Audited on production 2026-08-07: identity, line and odds were 100% across all
15 WNBA markets and projections were 0.0%, because the join was wired for MLB
only.

The test that matters most is `test_probability_fields_are_null_not_invented`.
WNBA's model ships MEANS, not a distribution, so P(over) cannot be derived
without a distributional assumption nobody has measured. A fabricated
probability would flow into EV, the blended score, and eventually a stake --
`#242`'s rule, one layer deeper: an absent value must never render as a real one.
"""

from __future__ import annotations

from syndicate.features.shared.prop_projections import _norm_name
from syndicate.features.shared.wnba_projections import (
    WnbaPropDistributionIndex,
    attach_wnba_projections,
    load_wnba_prop_distributions,
    load_wnba_projections,
    _hit_prob_over,
    _parse_model_cell,
)

_MODEL = "{'pts': 12.71, 'reb': 5.09, 'ast': 4.27, 'threes': 1.38, 'pra': 22.07, 'pr': 17.8, 'pa': 16.98, 'ra': 9.36}"


def _csv(rows) -> str:
    head = "player,team,model\n"
    return head + "".join(f'"{p}","{t}","{m}"\n' for p, t, m in rows)


def _index(tmp_path, rows=None):
    rows = rows if rows is not None else [("Jordin Canada", "ATL", _MODEL)]
    path = tmp_path / "props_recommendations_2026-08-07.csv"
    path.write_text(_csv(rows), encoding="utf-8")
    return load_wnba_projections(path)


def _row(market, line, player="Jordin Canada", kind="prop", consensus=None, game_state=None):
    row = {"kind": kind, "market": market, "line": line, "player_name": player, "sides": ["over", "under"]}
    if consensus is not None:
        row["consensus"] = consensus
    if game_state is not None:
        # `live_edge_policy.game_state_of` reads `row["game"]["state"]` --
        # matched here so this fixture exercises the SAME function the code
        # under test calls (see wnba_game_projections tests for the same note).
        row["game"] = {"state": game_state}
    return row


# `#263` -- a real ~100-draw empirical ladder, shaped exactly like
# `cards_sim_detail_<date>.json`'s `players[side][i]["prop_ladders"][stat]["ladder"]`.
# Deliberately has GAPS (10, 18, 23 missing) -- the realistic case, not a
# cleaned-up fixture, since the gap-fill behaviour is the thing under test.
_PTS_LADDER = [
    {"total": 2, "hitCount": 100, "hitProb": 1.0},
    {"total": 3, "hitCount": 99, "hitProb": 0.99},
    {"total": 9, "hitCount": 75, "hitProb": 0.75},
    {"total": 11, "hitCount": 60, "hitProb": 0.60},
    # gap: nothing hit exactly 12 or 13
    {"total": 14, "hitCount": 30, "hitProb": 0.30},
    {"total": 17, "hitCount": 20, "hitProb": 0.20},
    # gap through 22
    {"total": 24, "hitCount": 4, "hitProb": 0.04},
    {"total": 30, "hitCount": 1, "hitProb": 0.01},
]

# American -110/-110, both sides -- a standard ~4.55% hold, de-vigs to exactly
# 0.5 fair. Same fixture shape used in test_wnba_game_projections.py.
_TWO_SIDED_CONSENSUS = {"over": -110, "under": -110}


def _distribution_index(player="Jordin Canada", stat="pts", ladder=None) -> WnbaPropDistributionIndex:
    index = WnbaPropDistributionIndex()
    index.by_player[_norm_name(player)] = {stat: ladder if ladder is not None else _PTS_LADDER}
    index.players = 1
    return index


# --- parsing ------------------------------------------------------------------


def test_model_cell_is_a_python_literal_not_json():
    """Single quotes: json.loads would fail on every row."""
    parsed = _parse_model_cell(_MODEL)
    assert parsed["pts"] == 12.71
    assert parsed["ra"] == 9.36


def test_unparseable_model_cell_yields_nothing_rather_than_raising():
    assert _parse_model_cell("not a dict") == {}
    assert _parse_model_cell("") == {}
    assert _parse_model_cell(None) == {}


def test_missing_file_is_an_empty_index_not_an_error(tmp_path):
    index = load_wnba_projections(tmp_path / "absent.csv")
    assert index.players == 0


# --- the join -----------------------------------------------------------------


def test_points_projection_is_attached(tmp_path):
    grid = [_row("player_points", 11.5)]
    coverage = attach_wnba_projections(grid, _index(tmp_path))
    assert coverage["rows_with_projection"] == 1
    projection = grid[0]["projection"]
    assert projection["projected"] == 12.71
    assert projection["edge_vs_line"] == 1.21
    assert projection["side"] == "over"


def test_under_side_when_the_model_is_below_the_line(tmp_path):
    grid = [_row("player_assists", 7.5)]     # model ast = 4.27
    attach_wnba_projections(grid, _index(tmp_path))
    assert grid[0]["projection"]["side"] == "under"
    assert grid[0]["projection"]["edge_vs_line"] == -3.23


def test_every_mapped_combo_market_resolves(tmp_path):
    """pra/pr/pa/ra are distinct markets and must not collapse onto pts."""
    grid = [
        _row("player_points_rebounds_assists", 20.5),
        _row("player_points_rebounds", 16.5),
        _row("player_points_assists", 15.5),
        _row("player_rebounds_assists", 8.5),
    ]
    attach_wnba_projections(grid, _index(tmp_path))
    assert [r["projection"]["projected"] for r in grid] == [22.07, 17.8, 16.98, 9.36]


def test_probability_fields_are_null_not_invented(tmp_path):
    """The whole point: means cannot become P(over) without an assumption."""
    grid = [_row("player_points", 11.5)]
    attach_wnba_projections(grid, _index(tmp_path))
    projection = grid[0]["projection"]
    assert projection["model_prob_over"] is None
    assert projection["edge_vs_market_pct"] is None
    assert "distribution" in projection["probability_unavailable_reason"]


def test_binary_markets_are_left_blank_with_a_reason(tmp_path):
    grid = [_row("player_double_double", 0.5), _row("player_triple_double", 0.5)]
    coverage = attach_wnba_projections(grid, _index(tmp_path))
    assert coverage["rows_with_projection"] == 0
    assert coverage["unsupported_market_rows"] == 2
    assert "projection" not in grid[0]


def test_unknown_player_is_counted_not_guessed(tmp_path):
    grid = [_row("player_points", 11.5, player="Nobody Here")]
    coverage = attach_wnba_projections(grid, _index(tmp_path))
    assert coverage["rows_with_projection"] == 0
    assert coverage["unmatched_player_rows"] == 1
    assert "projection" not in grid[0]


def test_game_line_rows_are_untouched(tmp_path):
    grid = [{"kind": "game", "market": "spreads", "line": -3.5, "sides": ["away", "home"]}]
    coverage = attach_wnba_projections(grid, _index(tmp_path))
    assert coverage["rows_considered"] == 0
    assert "projection" not in grid[0]


def test_name_matching_folds_accents_and_punctuation(tmp_path):
    index = _index(tmp_path, rows=[("A'ja Wilson", "LV", _MODEL)])
    grid = [_row("player_points", 11.5, player="Aja Wilson")]
    coverage = attach_wnba_projections(grid, index)
    assert coverage["rows_with_projection"] == 1


def test_null_line_still_projects_without_claiming_a_side(tmp_path):
    grid = [_row("player_points", None)]
    attach_wnba_projections(grid, _index(tmp_path))
    projection = grid[0]["projection"]
    assert projection["projected"] == 12.71
    assert "edge_vs_line" not in projection
    assert "side" not in projection


def test_coverage_pct_is_reported(tmp_path):
    grid = [_row("player_points", 11.5), _row("player_double_double", 0.5)]
    coverage = attach_wnba_projections(grid, _index(tmp_path))
    assert coverage["rows_considered"] == 2
    assert coverage["pct_projected"] == 50.0


# `#263` -- the sim's own real, model-free empirical ladder
# (`cards_sim_detail_<date>.json`), threaded in instead of leaving
# `model_prob_over` null for every WNBA prop row.


# --- _hit_prob_over: the ladder math, in isolation --------------------------


def test_hit_prob_over_reads_a_present_total_directly():
    # A half-point line: "over 8.5" == "actual >= 9" == the ladder's total=9 entry.
    assert _hit_prob_over(_PTS_LADDER, 8.5) == 0.75


def test_hit_prob_over_a_whole_number_line_still_rounds_up_correctly():
    # "over 9" == "actual >= 10", which is MISSING from the ladder (gap) --
    # must fall through to total=11's hitProb, not total=9's.
    assert _hit_prob_over(_PTS_LADDER, 9.0) == 0.60


def test_hit_prob_over_fills_a_gap_from_the_next_present_total():
    # Nothing hit exactly 12 or 13 -- "over 11.5" == "actual >= 12" must read
    # total=14's hitProb (the next present total), not return None.
    assert _hit_prob_over(_PTS_LADDER, 11.5) == 0.30


def test_hit_prob_over_beyond_every_simulated_total_is_an_honest_zero():
    # Nothing in this ~100-draw sample ever scored 31+.
    assert _hit_prob_over(_PTS_LADDER, 30.5) == 0.0


def test_hit_prob_over_below_the_floor_is_the_ladders_own_max():
    assert _hit_prob_over(_PTS_LADDER, 0.5) == 1.0


def test_hit_prob_over_handles_an_out_of_order_ladder():
    # Production's own JSON order is whatever the sim emitted it in -- the
    # function must sort, not assume it is already ascending. Indices here are
    # total=14, total=9, total=2, total=24 -- deliberately not ascending, and
    # including the exact total the query resolves to (9) so a correct sort
    # is what makes this pass, not accidental list order.
    shuffled = [_PTS_LADDER[4], _PTS_LADDER[2], _PTS_LADDER[0], _PTS_LADDER[6]]
    assert _hit_prob_over(shuffled, 8.5) == 0.75


def test_hit_prob_over_empty_or_malformed_ladder_is_none_not_a_crash():
    assert _hit_prob_over([], 8.5) is None
    assert _hit_prob_over([{"total": "nonsense"}], 8.5) is None
    assert _hit_prob_over(None, 8.5) is None


# --- WnbaPropDistributionIndex.ladder_for -----------------------------------


def test_ladder_for_maps_board_market_to_stat_code():
    index = _distribution_index()
    assert index.ladder_for("Jordin Canada", "player_points") == _PTS_LADDER
    assert index.ladder_for("Jordin Canada", "player_rebounds") is None, "no reb ladder was indexed"


def test_ladder_for_unknown_player_is_none():
    index = _distribution_index()
    assert index.ladder_for("Nobody Here", "player_points") is None


def test_ladder_for_unmapped_market_is_none():
    index = _distribution_index()
    assert index.ladder_for("Jordin Canada", "totally_unmapped_market") is None


# --- attach_wnba_projections wired to a distribution index ------------------


def test_matched_line_gets_the_real_empirical_probability_and_edge(tmp_path):
    row = _row("player_points", 8.5, consensus=_TWO_SIDED_CONSENSUS)
    attach_wnba_projections([row], _index(tmp_path), _distribution_index())
    projection = row["projection"]

    assert projection["model_prob_over"] == 0.75
    assert projection["basis"] == "empirical_sim_ladder"
    # -110/-110 de-vigs to an exact 0.5 fair -- (0.75 - 0.50) * 100.
    assert projection["edge_vs_market_pct"] == 25.0
    assert projection.get("probability_unavailable_reason") is None, (
        "a stale mean-only reason must not sit beside a real probability"
    )
    # The mean-based fields are UNCHANGED by this -- same as before #263.
    assert projection["projected"] == 12.71
    assert projection["edge_vs_line"] == 4.21


def test_no_distribution_index_supplied_falls_back_exactly_as_before(tmp_path):
    # Every EXISTING caller that doesn't know about #263 yet must see
    # byte-identical behaviour -- this is the regression guard for that.
    row = _row("player_points", 8.5, consensus=_TWO_SIDED_CONSENSUS)
    attach_wnba_projections([row], _index(tmp_path))
    projection = row["projection"]
    assert projection["model_prob_over"] is None
    assert projection["basis"] == "model_mean"
    assert projection["probability_unavailable_reason"] == "model ships means, not a distribution"


def test_distribution_index_present_but_no_ladder_for_this_player_falls_back(tmp_path):
    # The distribution index is real but has nothing for THIS row's player --
    # same fallback as no index at all, never a crash or a fabricated number.
    row = _row("player_points", 8.5, player="Some Other Player", consensus=_TWO_SIDED_CONSENSUS)
    attach_wnba_projections([row], _index(tmp_path, rows=[("Some Other Player", "ATL", _MODEL)]), _distribution_index())
    projection = row["projection"]
    assert projection["model_prob_over"] is None
    assert projection["basis"] == "model_mean"


def test_no_line_means_no_distribution_lookup_even_with_an_index(tmp_path):
    # The ladder answers "P(over THIS number)" -- with no line there is no
    # number to ask it about, so this must degrade the same way a mean-only
    # row with no line already does.
    row = _row("player_points", None)
    attach_wnba_projections([row], _index(tmp_path), _distribution_index())
    projection = row["projection"]
    assert projection["model_prob_over"] is None
    assert projection["projected"] == 12.71


def test_one_sided_book_reports_why_even_with_a_real_probability(tmp_path):
    row = _row("player_points", 8.5, consensus={"over": -110})
    row["sides"] = ["over"]
    attach_wnba_projections([row], _index(tmp_path), _distribution_index())
    projection = row["projection"]
    assert projection["model_prob_over"] == 0.75, "the sim probability still attaches -- only the EDGE is refused"
    assert projection["edge_vs_market_pct"] is None
    assert "one-sided market" in projection["edge_unavailable_reason"]


def test_live_market_suppresses_the_edge_but_not_the_probability(tmp_path):
    row = _row("player_points", 8.5, consensus=_TWO_SIDED_CONSENSUS, game_state="live")
    attach_wnba_projections([row], _index(tmp_path), _distribution_index())
    projection = row["projection"]
    assert projection["model_prob_over"] == 0.75
    assert projection["edge_vs_market_pct"] is None
    assert "pregame projection" in projection["edge_unavailable_reason"]


def test_rows_with_distribution_is_counted_and_attributable(tmp_path):
    matched = _row("player_points", 8.5, consensus=_TWO_SIDED_CONSENSUS)
    unmatched_ladder = _row("player_points", 8.5, player="Someone Else", consensus=_TWO_SIDED_CONSENSUS)
    index = _index(tmp_path, rows=[("Jordin Canada", "ATL", _MODEL), ("Someone Else", "ATL", _MODEL)])
    coverage = attach_wnba_projections([matched, unmatched_ladder], index, _distribution_index())
    assert coverage["rows_with_distribution"] == 1
    assert coverage["rows_with_projection"] == 2, "both still get a mean-based projection"
    assert "empirical sim ladder" in coverage["probability_fields"]


def test_probability_fields_string_is_conditional_on_whether_an_index_was_passed(tmp_path):
    grid = [_row("player_points", 8.5)]
    without_index = attach_wnba_projections(grid, _index(tmp_path))
    assert "no distribution index supplied" in without_index["probability_fields"]

    with_index = attach_wnba_projections(grid, _index(tmp_path), WnbaPropDistributionIndex())
    assert "no distribution index supplied" not in with_index["probability_fields"]


# --- load_wnba_prop_distributions: the loader degrades gracefully -----------


def test_loader_returns_an_empty_index_for_a_date_with_no_artifact():
    # No mocking needed -- an implausible date has no file on any real disk.
    index = load_wnba_prop_distributions("1901-01-01")
    assert index.players == 0
    assert index.by_player == {}
