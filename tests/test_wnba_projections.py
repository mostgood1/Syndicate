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

from syndicate.features.shared.wnba_projections import (
    attach_wnba_projections,
    load_wnba_projections,
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


def _row(market, line, player="Jordin Canada", kind="prop"):
    return {"kind": kind, "market": market, "line": line, "player_name": player, "sides": ["over", "under"]}


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
