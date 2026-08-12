"""Soccer Layer 1 projections — the sport was at 0.0% on all 7 markets.

The tests that matter are the two about `total_distribution`. Its name invites
the assumption that it is a distribution; it is a summary stat carrying
`over_2_5_probability` and nothing else, so it can answer P(over) at 2.5 and at
no other line. Emitting a probability for line 3.5 from a mean would be a
fabricated edge dressed as a simulated one.
"""

from __future__ import annotations

import json

from syndicate.features.shared.soccer_projections import (
    attach_soccer_projections,
    load_soccer_projections,
)

_MATCH = {
    "match_id": "401879041",
    "event_id": "evt-brugge",
    "matchup": {"home_team": "Club Brugge", "away_team": "KV Kortrijk"},
    "win_probability": {"home": 0.8, "draw": 0.1267, "away": 0.0733},
    "team_projection": {"home_mean": 2.5667, "away_mean": 0.7133, "total_mean": 3.28, "margin_mean": 1.8533},
    "total_distribution": {"mean": 3.28, "over_2_5_probability": 0.6467},
    "spread_distribution": {"home": 1.8533, "away": -1.8533},
}

_PLAYERS = [
    {
        "match_id": "401879041",
        "player_name": "Nicolo Tresoldi",
        "anytime_scorer_probability": 0.2893,
        "expected_shots": 1.5985,
        "expected_shots_on_target": 0.6045,
    }
]


def _index(tmp_path, matches=None, players=None):
    league_dir = tmp_path / "belgian_pro_league" / "api" / "recommendations"
    league_dir.mkdir(parents=True, exist_ok=True)
    (league_dir / "recommendations_2026-08-07.json").write_text(
        json.dumps(
            {
                "league": "belgian_pro_league",
                "date": "2026-08-07",
                "matches": matches if matches is not None else [_MATCH],
                "player_props": players if players is not None else _PLAYERS,
            }
        ),
        encoding="utf-8",
    )
    return load_soccer_projections([tmp_path], "2026-08-07")


def _row(market, line=None, **extra):
    row = {
        "market": market,
        "line": line,
        "event_id": "evt-brugge",
        "home_team": "Club Brugge",
        "away_team": "KV Kortrijk",
        "sides": ["over", "under"],
    }
    row.update(extra)
    return row


def test_index_loads_matches_and_players(tmp_path):
    index = _index(tmp_path)
    assert index.matches == 1
    assert index.leagues == ["belgian_pro_league"]


def test_h2h_carries_a_real_probability(tmp_path):
    grid = [_row("h2h", sides=["away", "home"])]
    coverage = attach_soccer_projections(grid, _index(tmp_path))
    projection = grid[0]["projection"]
    assert projection["model_prob_over"] == 0.8
    assert projection["basis"] == "win_probability"
    assert projection["draw_probability"] == 0.1267
    assert coverage["rows_with_true_probability"] == 1


def test_totals_at_2_5_use_the_real_probability(tmp_path):
    grid = [_row("totals", 2.5)]
    attach_soccer_projections(grid, _index(tmp_path))
    projection = grid[0]["projection"]
    assert projection["model_prob_over"] == 0.6467
    assert projection["basis"] == "over_2_5_probability"


def test_totals_away_from_2_5_fall_back_to_a_mean_and_claim_no_probability(tmp_path):
    """`total_distribution` is a summary stat. At 3.5 it knows only a mean."""
    grid = [_row("totals", 3.5)]
    attach_soccer_projections(grid, _index(tmp_path))
    projection = grid[0]["projection"]
    assert projection["model_prob_over"] is None
    assert projection["projected"] == 3.28
    assert projection["edge_vs_line"] == -0.22
    assert projection["side"] == "under"


def test_spreads_use_the_margin_mean(tmp_path):
    grid = [_row("spreads", 1.5, sides=["away", "home"])]
    attach_soccer_projections(grid, _index(tmp_path))
    projection = grid[0]["projection"]
    assert projection["projected"] == 1.853
    assert projection["model_prob_over"] is None


def test_anytime_scorer_is_a_probability_not_a_mean(tmp_path):
    grid = [_row("player_goal_scorer_anytime", None, player_name="Nicolo Tresoldi")]
    attach_soccer_projections(grid, _index(tmp_path))
    assert grid[0]["projection"]["model_prob_over"] == 0.2893


def test_shots_markets_are_means(tmp_path):
    grid = [
        _row("player_shots", 1.5, player_name="Nicolo Tresoldi"),
        _row("player_shots_on_target", 0.5, player_name="Nicolo Tresoldi"),
    ]
    attach_soccer_projections(grid, _index(tmp_path))
    assert grid[0]["projection"]["projected"] == 1.599
    assert grid[0]["projection"]["model_prob_over"] is None
    assert grid[1]["projection"]["projected"] == 0.605


def test_first_goal_scorer_is_never_filled_from_anytime(tmp_path):
    """'Anytime' is not 'first' -- still true, and now enforced on a real number.

    POLICY CHANGED IN `#368`, deliberately. This used to assert the row stayed
    EMPTY, because the only way to fill it was to copy the anytime probability
    and that overstates every row. First/last scorer are now DERIVED by a Poisson
    race (`soccer_scorer_markets`), which is a transformation rather than a copy.

    So the guarantee this test exists for is unchanged and is asserted directly:
    the first-scorer probability must come out STRICTLY BELOW the anytime one. A
    player cannot be likelier to score first than to score at all, and if a
    future change ever reintroduces the copy, that inequality breaks.
    """
    anytime_row = _row("player_goal_scorer_anytime", None, player_name="Nicolo Tresoldi")
    first_row = _row("player_first_goal_scorer", None, player_name="Nicolo Tresoldi")
    attach_soccer_projections([anytime_row, first_row], _index(tmp_path))

    anytime = (anytime_row.get("projection") or {}).get("model_prob_over")
    first = (first_row.get("projection") or {}).get("model_prob_over")
    assert anytime is not None, "fixture no longer produces an anytime probability"
    assert first is not None, "#368 should now derive a first-scorer probability"
    assert first < anytime, "first-scorer must never equal or exceed anytime -- that is the copy"
    assert first_row["projection"]["basis"] == "poisson_scorer_race"


def test_unknown_match_is_counted_not_guessed(tmp_path):
    grid = [
        {
            "market": "h2h",
            "line": None,
            "event_id": "other",
            "home_team": "Nobody",
            "away_team": "Nobody Else",
            "sides": ["away", "home"],
        }
    ]
    coverage = attach_soccer_projections(grid, _index(tmp_path))
    assert coverage["unmatched_match_rows"] == 1
    assert "projection" not in grid[0]


def test_team_name_fallback_when_event_id_is_absent(tmp_path):
    grid = [_row("h2h", sides=["away", "home"])]
    grid[0].pop("event_id")
    attach_soccer_projections(grid, _index(tmp_path))
    assert grid[0]["projection"]["model_prob_over"] == 0.8


def test_player_props_do_not_cross_matches(tmp_path):
    """Keyed by match_id, so a same-named player in another fixture cannot leak."""
    grid = [_row("player_shots", 1.5, player_name="Nicolo Tresoldi")]
    grid[0]["event_id"] = "evt-brugge"
    index = _index(tmp_path, players=[dict(_PLAYERS[0], match_id="different-match")])
    coverage = attach_soccer_projections(grid, index)
    assert coverage["unmatched_player_rows"] == 1
    assert "projection" not in grid[0]
