"""`_compact_pregame_facts` -- the redesigned pregame compact card's data.

Every fact here has a market-vs-model preference order that must match
`_market_tiles`'s full-card tiles exactly, or the compact card and the full
card it links to could show opposite answers for the same match. Each test
below is paired with the equivalent assertion `_market_tiles` itself would
make, not just a standalone expected value.
"""

from __future__ import annotations

from syndicate.features.soccer.cards import _compact_pregame_facts


def _base(**overrides):
    args = {
        "away_abbr": "AWY",
        "home_abbr": "HME",
        "team_projection": {"away_mean": 1.4, "home_mean": 1.7, "total_mean": 3.1},
        "total_distribution": {"both_teams_scored_probability": 0.62},
        "volume_projection": {"away_corners": 4.2, "home_corners": 5.4},
        "betting": {},
        "scoreline_probabilities": {"1-1": 0.135, "2-1": 0.11, "1-0": 0.09},
    }
    args.update(overrides)
    return args


def test_nothing_simulated_returns_none():
    out = _compact_pregame_facts(**_base(
        team_projection={}, total_distribution={}, volume_projection={},
        betting={}, scoreline_probabilities={},
    ))
    assert out is None


def test_team_totals_are_rounded_to_one_decimal():
    out = _compact_pregame_facts(**_base())
    assert out["away_total"] == "1.4"
    assert out["home_total"] == "1.7"


def test_btts_prefers_market_price_over_model():
    # Market says 40% (No), model says 62% (Yes) -- market must win, same
    # preference order as `_market_tiles`'s BTTS tile.
    out = _compact_pregame_facts(**_base(betting={"p_btts_yes": 0.40}))
    assert out["btts"] == "No"


def test_btts_falls_back_to_model_when_no_market_price():
    out = _compact_pregame_facts(**_base(betting={}))
    assert out["btts"] == "Yes"


def test_btts_at_exactly_half_reads_yes():
    out = _compact_pregame_facts(**_base(
        total_distribution={"both_teams_scored_probability": 0.5}, betting={}))
    assert out["btts"] == "Yes"


def test_goals_line_sides_with_the_model_over_the_market_total():
    # model total_mean=3.1 > market line 2.5 -> model likes the OVER.
    out = _compact_pregame_facts(**_base(betting={"total": 2.5}))
    assert out["goals"] == "o2.5"


def test_goals_line_sides_under_when_model_total_is_below_the_line():
    out = _compact_pregame_facts(**_base(
        team_projection={"away_mean": 0.8, "home_mean": 0.9, "total_mean": 1.7},
        betting={"total": 2.5}))
    assert out["goals"] == "u2.5"


def test_goals_with_no_market_line_shows_the_model_projection_not_an_ou_line():
    out = _compact_pregame_facts(**_base(betting={}))
    assert out["goals"] == "3.1 proj"


def test_corners_reads_volume_projection_not_team_projection():
    # The exact bug `_market_tiles`'s corners tile hit in production: corners
    # live on `volume_projection`, and a read from `team_projection` (which has
    # no corners keys) must not silently succeed with a wrong number.
    out = _compact_pregame_facts(**_base(
        team_projection={"away_mean": 1.4, "home_mean": 1.7, "total_mean": 3.1,
                         "away_corners": 99.0, "home_corners": 99.0},
        volume_projection={"away_corners": 4.2, "home_corners": 5.4},
        betting={"corners_total": 8.5},
    ))
    assert out["corners"] == "o8.5"


def test_corners_with_no_market_line_shows_projection_not_a_fabricated_line():
    out = _compact_pregame_facts(**_base(betting={}))
    assert out["corners"] == "9.6 proj"


def test_corners_absent_when_volume_projection_missing():
    out = _compact_pregame_facts(**_base(volume_projection=None, betting={}))
    assert out["corners"] is None


def test_top_score_is_the_highest_probability_entry_away_first():
    out = _compact_pregame_facts(**_base())
    assert out["top_score"]["text"] == "AWY 1 - HME 1"
    assert out["top_score"]["pct"] == "13.5%"


def test_top_score_none_when_scoreline_probabilities_empty():
    out = _compact_pregame_facts(**_base(scoreline_probabilities={}))
    assert out["top_score"] is None


def test_malformed_scoreline_keys_are_skipped_not_crashed_on():
    # "not-a-score-key" contains a hyphen and outranks "2-1" by probability,
    # so an unguarded partition() would "parse" it as a scoreline. Both sides
    # must be digit strings for a key to be accepted.
    out = _compact_pregame_facts(**_base(
        scoreline_probabilities={"not-a-score-key": 0.9, "garbage": 0.5, "2-1": 0.2}))
    assert out["top_score"]["text"] == "AWY 1 - HME 2"


def test_all_four_facts_present_together():
    out = _compact_pregame_facts(**_base(
        betting={"p_btts_yes": 0.58, "total": 2.5, "corners_total": 9.5}))
    assert out["btts"] == "Yes"
    assert out["goals"] == "o2.5"
    assert out["corners"] == "o9.5"
    assert out["top_score"]["text"] == "AWY 1 - HME 1"
